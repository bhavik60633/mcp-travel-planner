import logging
import os
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import date, timedelta
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from agno.agent import Agent
from agno.models.openai import OpenAIChat

from flights.api import router as flights_router
from photos.api import router as photos_router
from places.geo import inside, km_between, span_km
from places.google import GoogleUnavailable
from places.service import PlaceChecker, PlanReview, TripPlan, get_place_checker
from places.stayfind import StayFinder, get_stay_finder
from plans.days import day_blocks, day_texts, named_days, replace_days
from plans.stops import MAX_DISTANCE_KM, MAX_TRIP_DAYS, Stop, base_stop, fit_nights, places_section, read_ai_stops, stops_problem, stops_prompt, with_dates
from plans.text import and_list, day_dates, nearby_rule, without_em_dashes
from plans.timetable import FAR_KM
from stays.api import get_stays_service
from stays.budget import nightly_stay_budget
from stays.api import router as stays_router
from stays.service import StaysQuery, StaysService
from tripinfo.api import get_place_suggester, get_trip_info_service
from tripinfo.api import router as trip_info_router
from tripinfo.service import TripInfoService
from tripinfo.suggest import MapUnavailable, PlaceSuggester, distance_km

log = logging.getLogger("yori")

# --------------------
# CREATE AGENT (FIXED)
# --------------------
# TP-07 D7: a stronger model chooses the places; Yori works out the times. YORI_AI_MODEL can change it.
AI_MODEL = os.getenv("YORI_AI_MODEL", "").strip() or "gpt-5.4-mini"

agent = Agent(
    model=OpenAIChat(
        id=AI_MODEL,  # ✅ MUST be `id`
        api_key=os.getenv("OPENAI_API_KEY")
    ),
    instructions="""
You are an expert travel planner.
Create a realistic, detailed, day-wise itinerary.
Use real places, food spots, timings, and travel tips.
Avoid generic templates and repetition.
Start each day with a heading that says where you'll be and the day's highlights, for example: ## Day 2: Canggu beaches and Echo Beach. Don't put the date in a day's heading.
Write the name of every specific place (sights, restaurants, cafés, markets, beaches, museums, temples) in bold, exactly as it appears on Google Maps, for example **Hawa Mahal**. Don't put anything else in bold.
Write every visit on its own line as a 24-hour time range, a colon and the place in bold, for example: 09:00–11:00: **Hawa Mahal** - what to see there. Leave time to travel between places.
Don't use em dashes (—).
"""
)

_BOLD_NAME = re.compile(r"\*\*([^*\n]{2,80}?)\*\*")
_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}")

# TP-07 A3, C2: one area per day, and times that can't move marked for the timetable.
PLACES_RULE = (
    "Plan each day around one area: keep each day's places within 50 km of that day's base (your stay, or where you stay that night), "
    "and cover that area in detail. If somewhere you'd suggest is farther away, give it a day of its own.\n"
    'When a visit has to happen at a set time, such as a sunset, a show or a boat, write "(fixed time)" right after the place\'s name.\n'
)


def _stay_lines(data: dict) -> str:
    """Where the traveller stays, for the AI (TP-07 A3)."""
    lines = []
    stay = data.get("stay") or {}
    if stay.get("name"):
        if stay.get("source") == "area":
            lines.append(f"Your stay's area: {stay['name']}")
        else:
            lines.append(f"Your stay: {stay['name']}" + (f" ({stay['address']})" if stay.get("address") else ""))
    for stop in data.get("stops") or []:
        stop_stay = stop.get("stay") or {}
        if stop_stay.get("name"):
            where = f" ({stop_stay['address']})" if stop_stay.get("address") and stop_stay.get("source") != "area" else ""
            lines.append(f"Your stay in {stop['place']}: {stop_stay['name']}{where}")
    return "".join(f"{line}\n" for line in lines)


def _stays_section(stays: list, budget: Optional[dict] = None, where: Optional[str] = None) -> str:
    """Real Airbnb listings for the trip dates, within the stay budget, for the AI to suggest from (TP-03 E4, TP-05 D3).

    `where` names a place's own stays when the trip has several places (TP-06 H6, H7).
    """
    limit = f", up to {budget['currency']} {budget['max_per_night']:,} a night" if budget else ""
    scope = where or "for these dates"
    lines = ["", f"Real Airbnb listings {scope}{limit} (suggest stays from these, with their prices and links):"]
    for stay in stays:
        price = f"{stay['currency']} {stay['total_price']:,} for {stay['nights']} nights" if stay.get("total_price") else "price not shown"
        rating = f"rated {stay['rating']} from {stay['reviews']} reviews" if stay.get("rating") else "new listing"
        summary = f" ({stay['summary']})" if stay.get("summary") else ""
        lines.append(f"- {stay['name']}{summary}: {price}, {rating}. {stay['url']}")
    return "\n".join(lines) + "\n"


def _trip_facts_section(weather: list, holidays: list) -> str:
    """The trip's weather and public holidays, for the AI to plan around (TP-04 C6)."""
    lines = [""]
    if weather:
        lines.append("Weather for the trip days (plan around it: indoor plans on rainy or very hot days, outdoor plans on clear days):")
        for day in weather:
            if day.get("rain_chance") is not None:
                rain = f"{day['rain_chance']}% chance of rain"
            elif day.get("rain_mm") is not None:
                rain = f"{day['rain_mm']} mm of rain on this date last year"
            else:
                rain = "rain unknown"
            kind = "forecast" if day.get("kind") == "forecast" else "typical, from last year"
            lines.append(f"- {day['date']}: high {day['high_c']}°C, low {day['low_c']}°C, {rain} ({kind})")
    if holidays:
        lines.append("Public holidays during the trip (expect closures and crowds):")
        for holiday in holidays:
            local = f" ({holiday['local_name']})" if holiday.get("local_name") else ""
            lines.append(f"- {holiday['date']}: {holiday['name']}{local}")
    return "\n".join(lines) + "\n"


def _iso_date(value) -> Optional[date]:
    if not isinstance(value, str) or not _ISO_DATE.fullmatch(value.strip()):
        return None
    try:
        return date.fromisoformat(value.strip())
    except ValueError:
        return None


def trip_prompt(data: dict) -> str:
    """What the AI is told about a trip, for a new plan or a change to one."""
    prompt = f"""
Destination: {data['destination']}
Number of days: {data['num_days']}
Budget: {data['budget']} {data['currency']}
Number of travelers: {data['num_travelers']}
Trip type: {data['trip_type']}
Group type: {data['group_type']}
Preferences: {data['preferences']}
"""
    if data.get("start_date"):
        prompt += f"Start date: {data['start_date']}\n"
    if data.get("return_date"):
        prompt += f"Return date: {data['return_date']}\n"
    start = _iso_date(data.get("start_date"))
    days = min(max(int(data["num_days"]), 1), 30)
    if start:
        # Headings name places, not dates, so the AI gets each day's date and weekday here (TP-06 C1).
        prompt += "Dates:\n" + "".join(f"- {line}\n" for line in day_dates(start, days))
    prompt += nearby_rule(data["destination"], int(data["num_days"])) + "\n"
    prompt += _stay_lines(data) + PLACES_RULE
    if data.get("stops") and start:
        stops = with_dates([(stop["place"], stop["nights"]) for stop in data["stops"]], start)
        prompt += places_section(stops, data.get("stay_per_stop") is not False, start)
    if data.get("stays"):
        prompt += _stays_section(data["stays"], data.get("stays_budget"))
    for group in data.get("stay_groups") or []:
        prompt += _stays_section(group["stays"], group.get("budget"), group.get("where"))
    if data.get("weather") or data.get("holidays"):
        prompt += _trip_facts_section(data.get("weather") or [], data.get("holidays") or [])
    return prompt


def run_travel_planner(data: dict) -> str:
    result = agent.run(trip_prompt(data))
    return result.content


def suggest_replacement(name: str, reason: str) -> Optional[str]:
    """One alternative for a place Google Maps couldn't confirm (TP-04 B2).

    Only the place name and the reason are sent: no Google Maps content goes to the AI.
    """
    prompt = (
        f'The place "{name}" is {reason}. Suggest one real, currently open alternative of the same kind in the same area. '
        "Answer with only its name in bold, exactly as it appears on Google Maps."
    )
    reply = str(agent.run(prompt).content or "").strip()
    bold = _BOLD_NAME.search(reply)
    suggestion = bold.group(1) if bold else (reply.splitlines()[0] if reply else "")
    return suggestion.strip(" .\"'") or None


# --------------------
# FASTAPI APP
# --------------------
app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(flights_router)
app.include_router(photos_router)
app.include_router(stays_router)
app.include_router(trip_info_router)


class StayRequest(BaseModel):
    """A stay on the map: a hotel, an Airbnb, or the base area Yori picked (TP-07 A1)."""

    name: str
    address: Optional[str] = None
    lat: float
    lng: float
    source: str = "google"  # google | airbnb | link | area


class StopRequest(BaseModel):
    place: str = ""
    nights: int = 0
    stay: Optional[StayRequest] = None  # TP-07 A1


class TripRequest(BaseModel):
    destination: str
    num_days: int
    budget: int
    currency: str
    num_travelers: int
    trip_type: str
    group_type: str
    preferences: str
    start_date: Optional[str] = None  # YYYY-MM-DD; used to look up real stays, weather and holidays
    return_date: Optional[str] = None  # YYYY-MM-DD; every date from start to return is a trip day (TP-06 D1)
    stops: Optional[list[StopRequest]] = None  # several places, in order (TP-06 H5)
    stay_per_stop: Optional[bool] = None  # an Airbnb at each place, or one for the whole trip (TP-06 D13)
    stay: Optional[StayRequest] = None  # where each day starts and ends (TP-07 A1)


def _invalid(message: str) -> JSONResponse:
    return JSONResponse(status_code=400, content={"error": "invalid_request", "message": message})


def _trip_nights(data: TripRequest) -> Optional[int]:
    """Nights away: from the start date to the return date, or the number of days for requests without a return date."""
    start = _iso_date(data.start_date)
    if start is None:
        return None
    end = _iso_date(data.return_date)
    return (end - start).days if end is not None else max(data.num_days, 1)


def _trip_problem(data: TripRequest) -> Optional[str]:
    if data.return_date is not None:
        end = _iso_date(data.return_date)
        if end is None:
            return "Dates must look like 2026-10-20."
        start = _iso_date(data.start_date)
        if start is not None and end < start:
            return "The return date can't be before the start date."
    if data.stops is not None:
        has_dates = _iso_date(data.start_date) is not None and _iso_date(data.return_date) is not None
        return stops_problem(data.stops, _trip_nights(data) if has_dates else None)
    return None


def _stay_searches(data: TripRequest) -> list[tuple[Optional[str], StaysQuery]]:
    """Which stays to look up: for the trip, for each place, or at the place with the most nights (TP-06 H6, H7)."""
    start = _iso_date(data.start_date)
    nights = _trip_nights(data)
    if start is None or not nights or nights < 1:
        return []
    adults = min(max(data.num_travelers, 1), 16)
    end = start + timedelta(days=nights)
    if not data.stops:
        return [(None, StaysQuery(place=data.destination.strip(), checkin=start, checkout=end, adults=adults))]
    stops = with_dates([(" ".join(stop.place.split()), stop.nights) for stop in data.stops], start)
    if data.stay_per_stop is False:
        base = base_stop(stops)
        return [(f"in {base.place} for the whole trip", StaysQuery(place=base.place, checkin=start, checkout=end, adults=adults))]
    return [(f"in {stop.place} for its dates", StaysQuery(place=stop.place, checkin=stop.checkin, checkout=stop.checkout, adults=adults)) for stop in stops]


def _nightly_budget(data: TripRequest, service: StaysService) -> Optional[dict]:
    if data.budget <= 0:
        return None
    try:
        return nightly_stay_budget(data.budget, data.currency, data.trip_type, _trip_nights(data), rate_to_inr=service.rate_to_inr)
    except Exception as exc:
        log.warning("No stay budget for this itinerary (%s)", type(exc).__name__)
        return None


def _find_stay_groups(data: TripRequest, service: StaysService) -> list[dict]:
    """Real stays within the trip budget's share for stays, when the trip has dates (TP-03 E4, TP-05 D3, TP-06 H6).

    Every place gets the same nightly limit: the stays share divided by all the trip's nights (TP-06 D12).
    """
    searches = _stay_searches(data)
    if not searches:
        return []
    budget = _nightly_budget(data, service)
    if budget:
        searches = [(where, replace(query, max_per_night=budget["max_per_night"])) for where, query in searches]

    def search(item):
        where, query = item
        try:
            return {"where": where, "stays": service.search(query).stays[:6], "budget": budget}
        except Exception as exc:  # stays are a bonus: the itinerary never waits on them failing
            log.warning("Airbnb stays skipped for this itinerary (%s)", type(exc).__name__)
            return None

    with ThreadPoolExecutor(max_workers=len(searches), thread_name_prefix="trip-stays") as pool:
        groups = list(pool.map(search, searches))
    return [group for group in groups if group and group["stays"]]


def _trip_facts(data: TripRequest, service: TripInfoService) -> dict:
    """Weather and public holidays for the trip days, when the trip has dates (TP-04 C6)."""
    if not data.start_date:
        return {}
    try:
        start = date.fromisoformat(data.start_date)
        info = service.info(data.destination.strip(), start, min(max(data.num_days, 1), 30), data.currency)
    except Exception as exc:  # trip facts are a bonus too
        log.warning("Trip facts skipped for this itinerary (%s)", type(exc).__name__)
        return {}
    facts = {}
    weather = info.get("weather") or {}
    if weather.get("available") and weather.get("days"):
        facts["weather"] = weather["days"]
    holidays = info.get("holidays") or {}
    if holidays.get("available") and holidays.get("days"):
        facts["holidays"] = holidays["days"]
    return facts


def _start_date(data: TripRequest) -> Optional[date]:
    try:
        return date.fromisoformat(data.start_date) if data.start_date else None
    except ValueError:
        return None


def _plan_payload(data: TripRequest, stays_service: StaysService, trip_info: TripInfoService) -> dict:
    payload = data.model_dump(exclude_none=True)
    groups = _find_stay_groups(data, stays_service)
    if groups:
        payload["stay_groups"] = groups
    payload.update(_trip_facts(data, trip_info))
    return payload


def _trip_plan(data: TripRequest) -> TripPlan:
    """Where each night is spent, for the timetable (TP-07 A1)."""
    stops = [
        {"place": " ".join(stop.place.split()), "nights": stop.nights, "stay": stop.stay.model_dump() if stop.stay else None}
        for stop in data.stops or []
    ]
    has_dates = _iso_date(data.start_date) is not None and _iso_date(data.return_date) is not None
    return TripPlan(
        destination=data.destination.strip(),
        start_date=_start_date(data),
        num_days=max(data.num_days, 1),
        nights=_trip_nights(data) if has_dates else None,
        stay=data.stay.model_dump() if data.stay else None,
        stops=stops,
        stay_per_stop=data.stay_per_stop,
    )


def _far_days_section(itinerary: str, moves: list[dict]) -> str:
    """Asks the AI to rewrite only the days that moved to a far area (TP-07 C3)."""
    days = [move["day"] for move in moves]
    named = f"Day {days[0]}" if len(days) == 1 else f"Days {and_list([str(day) for day in days])}"
    each = "starting with its heading" if len(days) == 1 else "each starting with its heading"
    lines = [f"\nThis is the traveller's current plan:\n\n{itinerary.strip()}\n", "These days are too far from the stay to plan as they are:"]
    for move in moves:
        lines.append(f"- Day {move['day']}: {move['label']}. Plan it in and around {move['area']} only, and cover {move['area']} in detail.")
    lines.append(
        f"Rewrite only {named}. Keep the dates, and don't add places from other areas. "
        f'Reply with only {named}, {each}, for example "## Day {days[0]}: ...". Write nothing else.'
    )
    return "\n".join(lines) + "\n"


def _far_days_rewriter(data: TripRequest, payload: dict, stays_service: Optional[StaysService]):
    """The AI rewrites the days in a far area, with real Airbnbs there for those nights (TP-07 C3, C5)."""

    def rewrite(itinerary: str, moves: list[dict], new_stays: list[dict]) -> Optional[str]:
        prompt = trip_prompt(payload)
        if stays_service is not None and new_stays:
            budget = _nightly_budget(data, stays_service)
            adults = min(max(data.num_travelers, 1), 16)
            for stay in new_stays:
                query = StaysQuery(place=stay["place"], checkin=date.fromisoformat(stay["checkin"]), checkout=date.fromisoformat(stay["checkout"]), adults=adults)
                if budget:
                    query = replace(query, max_per_night=budget["max_per_night"])
                try:
                    found = stays_service.search(query).stays[:6]
                except Exception as exc:  # stays are a bonus
                    log.warning("Airbnb stays skipped for a far area (%s)", type(exc).__name__)
                    continue
                if found:
                    prompt += _stays_section(found, budget, f"in {stay['place']} for its dates")
        prompt += _far_days_section(itinerary, moves)
        reply = str(agent.run(prompt).content or "")
        texts = day_texts(reply)
        days = [move["day"] for move in moves]
        if any(day not in texts for day in days):
            log.warning("The AI didn't rewrite every far day")
            return None
        return replace_days(itinerary, {day: without_em_dashes(texts[day]) for day in days})

    return rewrite


def _checked_response(itinerary: str, data: TripRequest, place_checker: PlaceChecker, replace_place=None, rewrite=None) -> dict:
    review = PlanReview(itinerary)
    try:
        review = place_checker.review(itinerary, data.destination, replace=replace_place, start_date=_start_date(data), trip=_trip_plan(data), rewrite=rewrite)
    except Exception as exc:  # checks never break the itinerary
        log.warning("Google Maps checks skipped for this itinerary (%s)", type(exc).__name__)
    response = {"status": "success", "itinerary": review.itinerary}
    if review.places:
        response["places"] = review.places
    if review.visits:
        response["visits"] = review.visits  # opening hours per visit (TP-05 A)
    if review.travel:
        response["travel"] = review.travel  # travel times between places (TP-05 B)
    if review.timetable:
        response["timetable"] = review.timetable  # each day from the stay (TP-07)
        response["timings_checked"] = review.timings_checked
        response["timings_message"] = review.timings_message
    if review.new_stays:
        response["new_stays"] = review.new_stays  # nights in far areas to find stays for (TP-07 C5)
    return response


@app.get("/")
def health():
    return {"status": "ok"}


@app.post("/plan-trip")
def plan_trip(
    data: TripRequest,
    stays_service: StaysService = Depends(get_stays_service),
    trip_info: TripInfoService = Depends(get_trip_info_service),
    place_checker: PlaceChecker = Depends(get_place_checker),
):
    problem = _trip_problem(data)
    if problem:
        return _invalid(problem)
    payload = _plan_payload(data, stays_service, trip_info)
    try:
        itinerary = without_em_dashes(run_travel_planner(payload))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    return _checked_response(itinerary, data, place_checker, suggest_replacement, _far_days_rewriter(data, payload, stays_service))


# --------------------
# CHANGES TO A PLAN (TP-06 F)
# --------------------
CHANGE_FAILED = {"error": "change_failed", "message": "Yori couldn't apply that change. Try saying it another way."}


class RevisePlanRequest(BaseModel):
    itinerary: str = ""
    request: str = ""
    trip: TripRequest


def _change_failed() -> JSONResponse:
    return JSONResponse(status_code=502, content=CHANGE_FAILED)


def _revise_section(itinerary: str, request: str, days: list[int], total: int) -> str:
    text = f"\nThis is the traveller's current plan:\n\n{itinerary.strip()}\n\nThe traveller asked for this change: \"{request}\"\n"
    if days:
        named = f"Day {days[0]}" if len(days) == 1 else f"Days {and_list([str(day) for day in days])}"
        each = "starting with its heading" if len(days) == 1 else "each starting with its heading"
        return text + (
            f"Rewrite only {named} to make this change. Keep what still fits, keep the dates, and make it fit with the days around it. "
            f'Reply with only {named}, {each}, for example "## Day {days[0]}: ...". Write nothing else.\n'
        )
    return text + (
        f"Rewrite the whole plan to make this change. Keep exactly {total} {'day' if total == 1 else 'days'}, with the same dates. "
        'Reply with the whole plan, each day starting with its heading, for example "## Day 1: ...".\n'
    )


@app.post("/api/revise-plan")
def revise_plan(
    body: RevisePlanRequest,
    stays_service: StaysService = Depends(get_stays_service),
    trip_info: TripInfoService = Depends(get_trip_info_service),
    place_checker: PlaceChecker = Depends(get_place_checker),
):
    """Rewrites the days a traveller names and keeps every other day exactly as it was (TP-06 F3–F5, H10)."""
    request = " ".join(body.request.split())
    if not request:
        return _invalid("Say what you'd like to change.")
    if not body.itinerary.strip():
        return _invalid("There's no plan to change.")
    data = body.trip
    problem = _trip_problem(data)
    if problem:
        return _invalid(problem)
    total = max(data.num_days, 1)
    days = named_days(request)
    if any(day < 1 or day > total for day in days):
        return _invalid(f"This trip has {total} {'day' if total == 1 else 'days'}.")
    current = day_texts(body.itinerary)
    if any(day not in current for day in days):
        return _change_failed()

    payload = _plan_payload(data, stays_service, trip_info)
    try:
        reply = str(agent.run(trip_prompt(payload) + _revise_section(body.itinerary, request, days, total)).content or "")
    except Exception as exc:
        log.warning("A plan change failed (%s)", type(exc).__name__)
        return _change_failed()

    if days:
        rewritten = day_texts(reply)
        if any(day not in rewritten for day in days):
            return _change_failed()
        itinerary = replace_days(body.itinerary, {day: without_em_dashes(rewritten[day]) for day in days})
    else:
        if [block.number for block in day_blocks(reply)] != list(range(1, total + 1)):
            return _change_failed()
        itinerary = without_em_dashes(reply.strip())
        days = list(range(1, total + 1))

    response = _checked_response(itinerary, data, place_checker, suggest_replacement, _far_days_rewriter(data, payload, stays_service))
    response["changed_days"] = days
    return response


# --------------------
# REAL TIMINGS (TP-07)
# --------------------
BASE_FALLBACK = "Yori couldn't pick a base area inside {destination}, so plans start from its centre for now."
BASE_NOT_ON_MAP = "Yori couldn't find {destination} on the map, so plans aren't timed from a base yet."


class RetimeRequest(BaseModel):
    itinerary: str = ""
    trip: TripRequest


@app.post("/api/retime-plan")
def retime_plan(body: RetimeRequest, place_checker: PlaceChecker = Depends(get_place_checker)):
    """Re-times a plan from a new stay without asking the AI (TP-07 A2, A4)."""
    if not body.itinerary.strip():
        return _invalid("There's no plan to re-time.")
    problem = _trip_problem(body.trip)
    if problem:
        return _invalid(problem)
    return _checked_response(body.itinerary, body.trip, place_checker)


@app.get("/api/stay/find")
def find_stay(q: str = "", destination: str = "", finder: StayFinder = Depends(get_stay_finder)):
    """A stay from a hotel's name or a link to it (TP-07 A7)."""
    return finder.find(q, destination)


class BaseAreaRequest(BaseModel):
    destination: str = ""
    start_date: str = ""
    return_date: str = ""
    num_travelers: int = 2
    trip_type: str = "Standard"
    preferences: str = ""


def base_prompt(data: BaseAreaRequest, destination: str) -> str:
    dates = f" from {data.start_date} to {data.return_date}" if data.start_date and data.return_date else ""
    return (
        f"Pick one base area inside {destination} for a trip{dates} for {data.num_travelers} travellers, {data.trip_type} style. "
        f"Preferences: {data.preferences or 'none given'}.\n"
        "The base area is the town or neighbourhood to stay in: close to most of what they'd like to see, with places to stay and eat.\n"
        'Reply with only its name and region, in the form "Neighbourhood, Region". Write nothing else.'
    )


def _base_name(reply: str) -> str:
    line = next((line for line in reply.splitlines() if line.strip()), "")
    line = re.sub(r"^\s*(?:[-*•]\s*)?(?:base area\s*:\s*)?", "", line, flags=re.IGNORECASE)
    return " ".join(line.replace("**", "").strip(" .\"'`").split())[:80]


def _inside_area(area: dict, spot: dict) -> bool:
    if area.get("viewport") and span_km(area["viewport"]) >= 5:
        return inside(area["viewport"], spot)
    return km_between(area, spot) <= FAR_KM


@app.post("/api/plan-base")
def plan_base(data: BaseAreaRequest, place_checker: PlaceChecker = Depends(get_place_checker)):
    """A base area inside the destination for a trip without a hotel, checked on the map (TP-07 A8)."""
    destination = " ".join(data.destination.split())
    if not destination:
        return _invalid("Where are you going?")
    google = place_checker.google
    if google is None:
        return {"base": None, "message": None}
    try:
        area = google.area(destination)
    except GoogleUnavailable as exc:
        log.warning("No base area: the destination couldn't be looked up (%s)", exc)
        area = None
    if area is None:
        return {"base": None, "message": BASE_NOT_ON_MAP.format(destination=destination)}
    fallback = {
        "base": {"name": destination, "address": None, "lat": area["lat"], "lng": area["lng"], "source": "area"},
        "message": BASE_FALLBACK.format(destination=destination),
    }
    try:
        reply = str(agent.run(base_prompt(data, destination)).content or "")
    except Exception as exc:
        log.warning("No base area suggested (%s)", type(exc).__name__)
        return fallback
    name = _base_name(reply)
    if not name or name.lower() == destination.lower():
        return fallback
    try:
        spot = google.area(f"{name}, {destination}")
    except GoogleUnavailable as exc:
        log.warning("The base area couldn't be checked (%s)", exc)
        return fallback
    if spot is None or not _inside_area(area, spot):
        return fallback
    return {"base": {"name": name, "address": None, "lat": spot["lat"], "lng": spot["lng"], "source": "area"}, "message": None}


# --------------------
# SEVERAL PLACES (TP-06 H2)
# --------------------
COULDNT_SUGGEST = "Yori couldn't suggest places right now, so the trip stays in {destination} for now."
COULDNT_CHECK = "Yori couldn't check the places on the map right now, so the trip stays in {destination} for now."
NOT_FOUND = "Yori couldn't find {place} on the map, so the trip stays in {destination} for now."
TOO_FAR = "{place} is more than {km} km from {destination}, so the trip stays in {destination} for now."


class StopsRequest(BaseModel):
    destination: str = ""
    start_date: str = ""
    return_date: str = ""
    num_travelers: int = 2
    trip_type: str = "Standard"
    preferences: str = ""


@app.post("/api/plan-stops")
def plan_stops(data: StopsRequest, suggester: PlaceSuggester = Depends(get_place_suggester)):
    """Places to stay and the nights at each, checked on the map; otherwise the destination for all nights (TP-06 H2)."""
    destination = " ".join(data.destination.split())
    if not destination:
        return _invalid("Where are you going?")
    start, end = _iso_date(data.start_date), _iso_date(data.return_date)
    if start is None or end is None:
        return _invalid("Dates must look like 2026-10-20.")
    if end < start:
        return _invalid("The return date can't be before the start date.")
    if (end - start).days + 1 > MAX_TRIP_DAYS:
        return _invalid(f"A trip can be at most {MAX_TRIP_DAYS} days.")
    nights = (end - start).days

    def one_place(message: Optional[str]) -> dict:
        return {"stops": [Stop(destination, nights, start, end).to_json()], "suggested": False, "message": message}

    if nights < 1:
        return one_place(None)
    try:
        reply = str(agent.run(stops_prompt(destination, start, end, data.num_travelers, data.trip_type, data.preferences)).content or "")
    except Exception as exc:
        log.warning("No places suggested for this trip (%s)", type(exc).__name__)
        return one_place(COULDNT_SUGGEST.format(destination=destination))
    places = fit_nights(read_ai_stops(reply), nights)
    if not places:
        return one_place(COULDNT_SUGGEST.format(destination=destination))

    try:
        home = suggester.locate(destination)
        if home is None:
            return one_place(COULDNT_CHECK.format(destination=destination))
        for place, _ in places:
            spot = suggester.locate(f"{place}, {destination}") or suggester.locate(place)
            if spot is None:
                return one_place(NOT_FOUND.format(place=place, destination=destination))
            if distance_km(home, spot) > MAX_DISTANCE_KM:
                return one_place(TOO_FAR.format(place=place, km=MAX_DISTANCE_KM, destination=destination))
    except MapUnavailable:
        return one_place(COULDNT_CHECK.format(destination=destination))
    return {"stops": [stop.to_json() for stop in with_dates(places, start)], "suggested": True, "message": None}
