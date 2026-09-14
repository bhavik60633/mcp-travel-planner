import logging
import os
import re
from datetime import date, timedelta
from typing import Optional

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from agno.agent import Agent
from agno.models.openai import OpenAIChat

from flights.api import router as flights_router
from photos.api import router as photos_router
from places.service import PlaceChecker, PlanReview, get_place_checker
from stays.api import get_stays_service
from stays.budget import nightly_stay_budget
from stays.api import router as stays_router
from stays.service import StaysQuery, StaysService
from tripinfo.api import get_trip_info_service
from tripinfo.api import router as trip_info_router
from tripinfo.service import TripInfoService

log = logging.getLogger("yori")

# --------------------
# CREATE AGENT (FIXED)
# --------------------
agent = Agent(
    model=OpenAIChat(
        id="gpt-4o-mini",  # ✅ MUST be `id`
        api_key=os.getenv("OPENAI_API_KEY")
    ),
    instructions="""
You are an expert travel planner.
Create a realistic, detailed, day-wise itinerary.
Use real places, food spots, timings, and travel tips.
Avoid generic templates and repetition.
Write the name of every specific place (sights, restaurants, cafés, markets, beaches, museums, temples) in bold, exactly as it appears on Google Maps, for example **Hawa Mahal**. Don't put anything else in bold.
Write every visit on its own line as a 24-hour time range, a colon and the place in bold, for example: 09:00–11:00: **Hawa Mahal** — what to see there. Leave time to travel between places.
"""
)

_BOLD_NAME = re.compile(r"\*\*([^*\n]{2,80}?)\*\*")


def _stays_section(stays: list, budget: Optional[dict] = None) -> str:
    """Real Airbnb listings for the trip dates, within the stay budget, for the AI to suggest from (TP-03 E4, TP-05 D3)."""
    limit = f", up to {budget['currency']} {budget['max_per_night']:,} a night" if budget else ""
    lines = ["", f"Real Airbnb listings for these dates{limit} (suggest stays from these, with their prices and links):"]
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


def run_travel_planner(data: dict) -> str:
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
    if data.get("stays"):
        prompt += _stays_section(data["stays"], data.get("stays_budget"))
    if data.get("weather") or data.get("holidays"):
        prompt += _trip_facts_section(data.get("weather") or [], data.get("holidays") or [])
    result = agent.run(prompt)
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


def _find_stays(data: TripRequest, service: StaysService) -> tuple[list, Optional[dict]]:
    """Real stays within the trip budget's share for stays, when the trip has dates (TP-03 E4, TP-05 D3)."""
    if not data.start_date:
        return [], None
    try:
        checkin = date.fromisoformat(data.start_date)
        nights = max(data.num_days, 1)
        budget = nightly_stay_budget(data.budget, data.currency, data.trip_type, nights, rate_to_inr=service.rate_to_inr) if data.budget > 0 else None
        query = StaysQuery(
            place=data.destination.strip(),
            checkin=checkin,
            checkout=checkin + timedelta(days=nights),
            adults=min(max(data.num_travelers, 1), 16),
            max_per_night=budget["max_per_night"] if budget else None,
        )
        return service.search(query).stays[:6], budget
    except Exception as exc:  # stays are a bonus: the itinerary never waits on them failing
        log.warning("Airbnb stays skipped for this itinerary (%s)", type(exc).__name__)
        return [], None


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
    payload = data.model_dump(exclude_none=True)
    stays, stays_budget = _find_stays(data, stays_service)
    if stays:
        payload["stays"] = stays
        if stays_budget:
            payload["stays_budget"] = stays_budget
    payload.update(_trip_facts(data, trip_info))
    try:
        itinerary = run_travel_planner(payload)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

    review = PlanReview(itinerary)
    try:
        review = place_checker.review(itinerary, data.destination, replace=suggest_replacement, start_date=_start_date(data))
    except Exception as exc:  # checks never break the itinerary
        log.warning("Google Maps checks skipped for this itinerary (%s)", type(exc).__name__)
    response = {"status": "success", "itinerary": review.itinerary}
    if review.places:
        response["places"] = review.places
    if review.visits:
        response["visits"] = review.visits  # opening hours per visit (TP-05 A)
    if review.travel:
        response["travel"] = review.travel  # travel times between places (TP-05 B)
    return response
