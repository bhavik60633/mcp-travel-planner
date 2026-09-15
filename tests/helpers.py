"""Simulated flight sources, fixtures and small helpers used by the TP-01 tests."""

from __future__ import annotations

import base64
import copy
import json
import re
import threading
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

import httpx

FIXTURES = Path(__file__).parent / "fixtures"

# Every simulated test runs "on" this day, so dates in the fixtures stay in the future.
TODAY = date(2026, 9, 14)

UNAVAILABLE = "Flight prices are temporarily unavailable. Try again in a few minutes."


def load_fixture(name: str):
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def decode_tfs(url: str) -> bytes:
    """Return the decoded Google Flights `tfs` search descriptor of a booking link."""
    tfs = parse_qs(urlparse(url).query)["tfs"][0]
    return base64.urlsafe_b64decode(tfs + "=" * (-len(tfs) % 4))


class FakeClock:
    """A monotonic clock the tests move forward by hand (used for the cache)."""

    def __init__(self) -> None:
        self.now = 1_000_000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


class ConcurrencyTracker:
    """Records the highest number of source calls running at the same moment."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.active = 0
        self.max_active = 0

    def enter(self) -> None:
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)

    def exit(self) -> None:
        with self._lock:
            self.active -= 1


def make_offer(
    origin="BOM",
    destination="DXB",
    depart="2026-10-20",
    return_date=None,
    price=15082,
    currency="INR",
    airline_code="6E",
    airline="IndiGo",
    flight_number="6E 1451",
    dep_time="08:10",
    arr_time="09:40",
    duration=180,
):
    """A valid non-stop offer, built through the public Offer model."""
    from flights.models import Offer

    def journey(frm, to, day):
        return {
            "from": frm,
            "to": to,
            "departure": f"{day}T{dep_time}",
            "arrival": f"{day}T{arr_time}",
            "duration_min": duration,
            "stops": 0,
            "segments": [
                {
                    "airline_code": airline_code,
                    "airline": airline,
                    "flight_number": flight_number,
                    "from": frm,
                    "to": to,
                    "departure": f"{day}T{dep_time}",
                    "arrival": f"{day}T{arr_time}",
                    "duration_min": duration,
                    "aircraft": None,
                }
            ],
            "layovers": [],
        }

    return Offer.model_validate(
        {
            "id": f"{flight_number}-{depart}-{price}",
            "price": price,
            "currency": currency,
            "airlines": [airline],
            "duration_min": duration * (2 if return_date else 1),
            "stops": 0,
            "booking_url": "https://www.google.com/travel/flights/search?tfs=CBwQAg",
            "booking_type": "route",
            "outbound": journey(origin, destination, depart),
            "return": journey(destination, origin, return_date) if return_date else None,
            "return_match": "exact" if return_date else None,
        }
    )


class FakeSource:
    """Stands in for gf-search, fli, swoop or Travelpayouts."""

    def __init__(
        self,
        name="gf-search",
        offers=None,
        error=None,
        delay=0.0,
        complete=False,
        uses_google=True,
        respond=None,
        tracker=None,
        block=None,
    ):
        self.name = name
        self.complete = complete
        self.uses_google = uses_google
        self.offers = list(offers or [])
        self.error = error
        self.delay = delay
        self.respond = respond
        self.tracker = tracker
        self.block = block
        self.calls = []

    def search(self, query):
        self.calls.append(query)
        if self.tracker:
            self.tracker.enter()
        try:
            if self.block is not None:
                self.block.wait(timeout=30)
            if self.delay:
                time.sleep(self.delay)
            if self.error is not None:
                raise self.error
            if self.respond is not None:
                return self.respond(query)
            return [offer.model_copy(deep=True) for offer in self.offers]
        finally:
            if self.tracker:
                self.tracker.exit()


class FakeDateSource:
    """Stands in for a cheapest-days source."""

    def __init__(self, name="fake-dates", days=None, error=None):
        self.name = name
        self.uses_google = True
        self.days = list(days or [])
        self.error = error
        self.calls = []

    def search_dates(self, query):
        self.calls.append(query)
        if self.error is not None:
            raise self.error
        return [dict(day) for day in self.days]


class FakeFliClient:
    """Stands in for fli's SearchFlights / SearchDates client."""

    def __init__(self, results=None, error=None):
        self.results = results
        self.error = error
        self.searches = []

    def search(self, filters, top_n=5, currency=None, language=None, country=None):
        self.searches.append({"filters": filters, "currency": currency, "language": language, "country": country})
        if self.error is not None:
            raise self.error
        return self.results

    def build_flight_booking_url(self, flight, *, currency=None, language=None, country=None):
        return "https://www.google.com/travel/flights/booking?tfs=CBwQAhoeEgoyMDI2LTExLTA5"


def fli_result(data: dict):
    """Rebuild a fli FlightResult from fli's saved JSON output."""
    from fli.models import Airline, Airport, FlightLeg, FlightResult, Layover

    def airline(code: str):
        return Airline["_" + code] if code[0].isdigit() else Airline[code]

    legs = [
        FlightLeg(
            airline=airline(leg["airline"]["code"]),
            flight_number=leg["flight_number"],
            departure_airport=Airport[leg["departure_airport"]["code"]],
            arrival_airport=Airport[leg["arrival_airport"]["code"]],
            departure_datetime=datetime.fromisoformat(leg["departure_time"]),
            arrival_datetime=datetime.fromisoformat(leg["arrival_time"]),
            duration=leg["duration"],
            aircraft=leg.get("aircraft"),
        )
        for leg in data["legs"]
    ]
    layovers = [
        Layover(airport=Airport[stop["airport"]["code"]], duration=stop["duration"])
        for stop in data.get("layovers") or []
    ]
    return FlightResult(
        legs=legs,
        price=data.get("price"),
        currency=data.get("currency"),
        duration=data["duration"],
        stops=data["stops"],
        layovers=layovers or None,
    )


# --------------------------------------------------------------------------- TP-03


def google_page_html(ds1_fixture: str, labels_fixture: str | None = None, currency_words: str = "Indian rupees") -> str:
    """A Google Flights results page rebuilt from saved parts: its visible flight labels and its data script."""
    ds1 = (FIXTURES / ds1_fixture).read_text(encoding="utf-8")
    if labels_fixture:
        labels = [line.strip() for line in (FIXTURES / labels_fixture).read_text(encoding="utf-8").splitlines() if line.strip()]
    else:
        labels = [f'aria-label="From 1 {currency_words}. Simulated label."']
    divs = "".join(f"<div {label}></div>" for label in labels)
    return f'<!doctype html><html><body>{divs}<script class="ds:1" nonce="test">{ds1}</script></body></html>'


def google_page_html_without(ds1_fixture: str, labels_fixture: str, drop_price: int) -> str:
    """The same saved page as a read in which Google left out every flight priced `drop_price`."""
    import rjsonc

    text = (FIXTURES / ds1_fixture).read_text(encoding="utf-8")
    head, rest = text.split("data:", 1)
    data_text, tail = rest.rsplit(",", 1)
    data = rjsonc.loads(data_text)

    def priced_at_drop(flight) -> bool:
        try:
            return flight[1][0][1] == drop_price
        except (IndexError, TypeError):
            return False

    for index in (2, 3):
        if index < len(data) and isinstance(data[index], list):
            for section in data[index]:
                if isinstance(section, list):
                    section[:] = [flight for flight in section if not priced_at_drop(flight)]

    labels = [
        line.strip()
        for line in (FIXTURES / labels_fixture).read_text(encoding="utf-8").splitlines()
        if line.strip() and f"From {drop_price} " not in line and f"From {drop_price:,} " not in line
    ]
    divs = "".join(f"<div {label}></div>" for label in labels)
    ds1 = f"{head}data:{json.dumps(data)},{tail}"
    return f'<!doctype html><html><body>{divs}<script class="ds:1" nonce="test">{ds1}</script></body></html>'


class FakeGoogle:
    """Answers Google Flights page requests with saved pages and records each request.

    Pages are served in order (the last one repeats), or chosen per request by `pick(params) -> index`.
    """

    def __init__(self, *pages: str, pick=None):
        self.pages = list(pages)
        self.pick = pick
        self.requests: list[dict] = []

    def __call__(self, url: str, params: dict) -> str:
        self.requests.append({"url": url, **params})
        if self.pick is not None:
            return self.pages[self.pick(params)]
        return self.pages[min(len(self.requests), len(self.pages)) - 1]


def decode_b64(value: str) -> bytes:
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def priced_flights_leaving(ds1_fixture: str, airport: str) -> int:
    """How many priced flights in a saved Google page start at `airport` (the page's own count)."""
    from gf_search.parser import parse_js

    flights = parse_js((FIXTURES / ds1_fixture).read_text(encoding="utf-8"), currency="INR")
    return sum(1 for f in flights if f.get("price") and f["segments"] and f["segments"][0]["from"] == airport)


# --------------------------------------------------------------------------- TP-04


class FakeGooglePlaces:
    """Stands in for Google Places API (New): places:searchText and places/{id}. Records every request."""

    def __init__(self, places=None, block=None):
        self.places = copy.deepcopy(places if places is not None else load_fixture("google-places-jaipur.json")["places"])
        self.block = block
        self.requests: list[httpx.Request] = []
        self._lock = threading.Lock()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        with self._lock:
            self.requests.append(request)
        if self.block is not None:
            self.block.wait(timeout=30)
        path = request.url.path
        if path == "/v1/places:searchText":
            name = json.loads(request.content)["textQuery"].rsplit(", ", 1)[0]
            place = self.places.get(name)
            return httpx.Response(200, json={"places": [place]} if place else {})
        if path.startswith("/v1/places/"):
            place_id = path.rsplit("/", 1)[1]
            place = next((p for p in self.places.values() if p["id"] == place_id), None)
            if place is None:
                return httpx.Response(404, json={"error": {"code": 404, "status": "NOT_FOUND"}})
            return httpx.Response(200, json=place)
        return httpx.Response(404, json={"error": {"code": 404}})

    def searches(self) -> list[str]:
        return [json.loads(r.content)["textQuery"] for r in self.requests if r.url.path == "/v1/places:searchText"]

    def detail_ids(self) -> list[str]:
        return [r.url.path.rsplit("/", 1)[1] for r in self.requests if r.url.path.startswith("/v1/places/")]


PHOTON_FIXTURES = FIXTURES / "photon"


class FakePhoton:
    """Stands in for Photon (TP-06), replaying its real replies saved on 15 Sep 2026 in fixtures/photon.

    A query without a saved reply finds nothing. `fail` is an HTTP status, "error" (no connection) or a
    threading.Event to wait for (a slow Photon).
    """

    def __init__(self, fail=None):
        self.fail = fail
        self.queries: list[str] = []
        self._lock = threading.Lock()

    def __call__(self, request: httpx.Request) -> httpx.Response:
        import re

        query = request.url.params.get("q", "")
        with self._lock:
            self.queries.append(query)
        if isinstance(self.fail, threading.Event):
            self.fail.wait(timeout=30)
        elif self.fail == "error":
            raise httpx.ConnectError("simulated: no connection", request=request)
        elif isinstance(self.fail, int):
            return httpx.Response(self.fail, json={"error": "simulated"})
        saved = PHOTON_FIXTURES / (re.sub(r"[^a-z0-9]+", "-", query.lower()).strip("-") + ".json")
        if not saved.exists():
            return httpx.Response(200, json={"type": "FeatureCollection", "features": []})
        reply = json.loads(saved.read_text(encoding="utf-8"))
        return httpx.Response(reply["status"], json=reply["body"])


class ScriptedAgent:
    """Stands in for the AI (TP-06): answers each prompt with the next reply (the last one repeats) and keeps the prompts."""

    def __init__(self, *replies: str):
        self.replies = list(replies) or [""]
        self.prompts: list[str] = []

    def run(self, prompt):
        from types import SimpleNamespace

        self.prompts.append(prompt)
        reply = self.replies.pop(0) if len(self.replies) > 1 else self.replies[0]
        return SimpleNamespace(content=reply)


TRIPINFO_FIXTURES = FIXTURES / "tripinfo"


def tripinfo_fixture(name: str):
    return json.loads((TRIPINFO_FIXTURES / f"{name}.json").read_text(encoding="utf-8"))


def _redate_daily(body: dict, start: str, end: str) -> dict:
    """A saved Open-Meteo reply moved to the dates asked for, keeping its values in order."""
    body = copy.deepcopy(body)
    daily = body["daily"]
    first, last = date.fromisoformat(start), date.fromisoformat(end)
    saved = len(daily["time"])
    moved = {key: [] for key in daily}
    for index in range((last - first).days + 1):
        day = (first + timedelta(days=index)).isoformat()
        for key, values in daily.items():
            value = values[index % saved]
            if key == "time":
                value = day
            elif key in ("sunrise", "sunset"):
                value = day + value[10:]
            moved[key].append(value)
    body["daily"] = moved
    return body


class FakeWeb:
    """Stands in for the free trip-information services, replaying their real replies saved on 14 Sep 2026.

    `fail` maps a host to an HTTP status, "error" (no connection) or a threading.Event to wait for (a slow
    service). Weather replies are moved to the dates asked for.
    """

    ROUTES = {
        ("nominatim.openstreetmap.org", "/search"): "nominatim-goa",
        ("api.open-meteo.com", "/v1/forecast"): "open-meteo-forecast-goa",
        ("archive-api.open-meteo.com", "/v1/archive"): "open-meteo-archive-goa",
        ("api.frankfurter.dev", "/v1/latest"): "frankfurter-inr-eur",
        ("cdn.jsdelivr.net", "/npm/@fawazahmed0/currency-api@latest/v1/currencies/inr.json"): "currency-api-inr",
        ("date.nager.at", "/api/v3/PublicHolidays/2026/FR"): "nager-fr-2026",
        ("date.nager.at", "/api/v3/PublicHolidays/2026/IN"): "nager-in-2026",
        ("en.wikipedia.org", "/api/rest_v1/page/summary/Goa"): "wikipedia-goa",
        ("en.wikipedia.org", "/api/rest_v1/page/summary/Paris"): "wikipedia-paris",
        ("www.warnely.com", "/api/v1/countries/IN"): "warnely-in",
        ("www.warnely.com", "/api/v1/countries/FR"): "warnely-fr",
    }

    def __init__(self, fail=None):
        self.fail = dict(fail or {})
        self.requests: list[httpx.Request] = []
        self.unexpected: list[str] = []
        self._lock = threading.Lock()

    def requests_to(self, host: str) -> list[httpx.Request]:
        return [r for r in self.requests if r.url.host == host]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        with self._lock:
            self.requests.append(request)
        host, path = request.url.host, request.url.path
        failure = self.fail.get(host)
        if isinstance(failure, threading.Event):
            failure.wait(timeout=30)
        elif failure == "error":
            raise httpx.ConnectError("simulated: no connection", request=request)
        elif isinstance(failure, int):
            return httpx.Response(failure, json={"error": "simulated"})

        if host == "photon.komoot.io" and path.rstrip("/") == "/api":
            name = "photon-paris" if request.url.params.get("q", "").lower().startswith("paris") else "photon-goa"
        else:
            name = self.ROUTES.get((host, path))
        if name is None:
            with self._lock:
                self.unexpected.append(f"{host}{path}")
            return httpx.Response(404, json={"error": "not simulated"})
        saved = tripinfo_fixture(name)
        if saved["status"] == 204:
            return httpx.Response(204)
        body = saved["body"]
        if host in ("api.open-meteo.com", "archive-api.open-meteo.com"):
            body = _redate_daily(body, request.url.params["start_date"], request.url.params["end_date"])
        return httpx.Response(saved["status"], json=body)


# --------------------------------------------------------------------------- TP-05


def weekly_hours(opens: str, closes: str, days=range(7)) -> dict:
    """Google `regularOpeningHours`: open `opens`–`closes` on each Google weekday in `days` (0 is Sunday)."""
    oh, om = map(int, opens.split(":"))
    ch, cm = map(int, closes.split(":"))
    overnight = (ch, cm) <= (oh, om)
    return {
        "periods": [
            {"open": {"day": d, "hour": oh, "minute": om}, "close": {"day": (d + 1) % 7 if overnight else d, "hour": ch, "minute": cm}}
            for d in days
        ],
        "weekdayDescriptions": [],
    }


OPEN_24_HOURS = {"periods": [{"open": {"day": 0, "hour": 0, "minute": 0}}], "weekdayDescriptions": ["Monday: Open 24 hours"]}


def dated_hours(day: date, opens: str, closes: str) -> dict:
    """Google `currentOpeningHours` with one special day: open `opens`–`closes` on `day`."""
    oh, om = map(int, opens.split(":"))
    ch, cm = map(int, closes.split(":"))
    google_day = (day.weekday() + 1) % 7
    stamp = {"year": day.year, "month": day.month, "day": day.day}
    return {
        "periods": [{"open": {"day": google_day, "hour": oh, "minute": om, "date": stamp}, "close": {"day": google_day, "hour": ch, "minute": cm, "date": stamp}}],
        "specialDays": [{"date": stamp}],
    }


def google_place(place_id: str, name: str, lat: float, lng: float, regular=None, current=None) -> dict:
    """A place in the Places API (New) reply format, in Jaipur (UTC+5:30)."""
    place = {
        "id": place_id,
        "displayName": {"text": name, "languageCode": "en"},
        "formattedAddress": f"{name}, Jaipur, Rajasthan, India",
        "location": {"latitude": lat, "longitude": lng},
        "googleMapsUri": f"https://maps.google.com/?cid={place_id}",
        "businessStatus": "OPERATIONAL",
        "rating": 4.5,
        "userRatingCount": 1000,
        "utcOffsetMinutes": 330,
    }
    if regular is not None:
        place["regularOpeningHours"] = regular
    if current is not None:
        place["currentOpeningHours"] = current
    return place


def jaipur_places_with_hours() -> dict:
    """Hand-written in Google's documented format (TP-05): there was no key to capture real replies."""
    return {
        # Usually 9:00 AM - 4:30 PM; on Wed 16 Sep 2026 Google lists it closing at 1:00 PM.
        "Hawa Mahal": google_place("hours-hawa-mahal", "Hawa Mahal", 26.9239363, 75.8267438, weekly_hours("09:00", "16:30"), dated_hours(date(2026, 9, 16), "09:00", "13:00")),
        "Tapri Central": google_place("hours-tapri-central", "Tapri Central", 26.9005, 75.8061, weekly_hours("08:00", "23:00")),
        "Albert Hall Museum": google_place("hours-albert-hall", "Albert Hall Museum", 26.9116, 75.8195, weekly_hours("10:00", "17:00")),
        "Rajasthan Museum": google_place("hours-rajasthan-museum", "Rajasthan Museum", 26.92, 75.82, weekly_hours("10:00", "17:00", days=[0, 2, 3, 4, 5, 6])),
        "Anokhi Museum": google_place("hours-anokhi", "Anokhi Museum", 26.98, 75.85, weekly_hours("10:00", "17:00", days=[0, 3, 4, 5, 6])),
        "Chokhi Dhani": google_place("hours-chokhi-dhani", "Chokhi Dhani", 26.77, 75.83, weekly_hours("17:00", "23:00")),
        "Jaipur Junction": google_place("hours-jaipur-junction", "Jaipur Junction", 26.9196, 75.7878, OPEN_24_HOURS),
        "Nahargarh Viewpoint": google_place("hours-nahargarh", "Nahargarh Viewpoint", 26.9373, 75.8155),
        "Laxmi Misthan Bhandar": google_place("hours-lmb", "Laxmi Misthan Bhandar", 26.9225, 75.8235, weekly_hours("08:00", "22:30")),
    }


JAIPUR_ROUTES = {
    ("Hawa Mahal", "Tapri Central", "DRIVE"): {"distanceMeters": 3400, "duration": "840s"},
    ("Hawa Mahal", "Tapri Central", "TRANSIT"): {
        "distanceMeters": 3900,
        "duration": "1920s",
        "legs": [{"steps": [
            {"travelMode": "WALK", "staticDuration": "300s"},
            {"travelMode": "TRANSIT", "staticDuration": "1260s", "transitDetails": {
                "stopDetails": {"departureTime": None},
                "transitLine": {"name": "Pink Line", "nameShort": "Pink", "vehicle": {"name": {"text": "Metro rail"}, "type": "SUBWAY"}},
            }},
            {"travelMode": "WALK", "staticDuration": "360s"},
        ]}],
    },
    ("Tapri Central", "Albert Hall Museum", "DRIVE"): {"distanceMeters": 2600, "duration": "3600s"},
    ("Hawa Mahal", "Laxmi Misthan Bhandar", "DRIVE"): {"distanceMeters": 900, "duration": "300s"},
    ("Hawa Mahal", "Laxmi Misthan Bhandar", "WALK"): {"distanceMeters": 850, "duration": "660s"},
}


class FakeGoogleRoutes:
    """Stands in for the Routes API's computeRoutes, in the reply format Google documents. Records every request.

    Public transport leaves `transit_delay_minutes` after the time asked for. Car and walking trips not listed in
    JAIPUR_ROUTES take 20 and 60 minutes; public transport not listed has no route.
    """

    def __init__(self, places: dict, transit_delay_minutes: int = 5, block=None):
        self.names = {(p["location"]["latitude"], p["location"]["longitude"]): name for name, p in places.items()}
        self.transit_delay_minutes = transit_delay_minutes
        self.block = block
        self.requests: list[httpx.Request] = []
        self._lock = threading.Lock()

    def _key(self, request: httpx.Request):
        body = json.loads(request.content)

        def name(waypoint):
            point = waypoint["location"]["latLng"]
            return self.names.get((point["latitude"], point["longitude"]))

        return name(body["origin"]), name(body["destination"]), body["travelMode"]

    def __call__(self, request: httpx.Request) -> httpx.Response:
        with self._lock:
            self.requests.append(request)
        if self.block is not None:
            self.block.wait(timeout=30)
        body = json.loads(request.content)
        key = self._key(request)
        route = copy.deepcopy(JAIPUR_ROUTES.get(key))
        if route is None and key[2] == "DRIVE":
            route = {"distanceMeters": 5000, "duration": "1200s"}
        if route is None and key[2] == "WALK":
            route = {"distanceMeters": 5000, "duration": "3600s"}
        if route is not None and key[2] == "TRANSIT":
            leaves = datetime.fromisoformat(body["departureTime"].replace("Z", "+00:00")) + timedelta(minutes=self.transit_delay_minutes)
            for leg in route["legs"]:
                for step in leg["steps"]:
                    if step.get("transitDetails"):
                        step["transitDetails"]["stopDetails"]["departureTime"] = leaves.strftime("%Y-%m-%dT%H:%M:%SZ")
        return httpx.Response(200, json={"routes": [route]} if route else {})

    def request_for(self, origin: str, destination: str, mode: str):
        return next((request for request in self.requests if self._key(request) == (origin, destination, mode)), None)

    def body_for(self, origin: str, destination: str, mode: str):
        request = self.request_for(origin, destination, mode)
        return json.loads(request.content) if request is not None else None


# --------------------------------------------------------------------------- TP-07


def km_between(a: tuple[float, float], b: tuple[float, float]) -> float:
    import math

    lat1, lng1, lat2, lng2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


class FakeMaps:
    """Stands in for Google Places API (New) and Routes API in TP-07 tests, in the reply formats Google documents.

    - `places`: {name: {"lat", "lng", "town", "types", "reviews", "hours", "matches", "id", "offset"}}. Text Search returns every
      place whose name (or one of its `matches`) equals the query's name before the first ", ", in this order, keeping only
      those inside `locationRestriction` when one is sent.
    - `areas`: {name: {"lat", "lng", "low": (lat, lng), "high": (lat, lng)}}, found when the whole query is the area's name.
    - `points`: other named spots Routes knows by their coordinates (stays, jetties).
    - Car trips take `drive[(from, to)]` minutes (either way round), otherwise 2 minutes per km. A pair in `water` has no road.
    - `ferries`: {(from, to): {"line", "departures": ["09:00", ...] (local), "minutes"}} answers TRANSIT requests with a boat.
    """

    def __init__(self, places, areas=None, points=None, drive=None, water=(), ferries=None, offset=330, block_search=None, fail_routes=None):
        self.places = places
        self.areas = areas or {}
        self.points = points or {}
        self.drive = drive or {}
        self.water = {frozenset(pair) for pair in water}
        self.ferries = ferries or {}
        self.offset = offset
        self.block_search = block_search
        self.fail_routes = fail_routes
        self.requests: list[httpx.Request] = []
        self._lock = threading.Lock()
        self._names = {}
        for name, spec in {**places, **self.areas, **self.points}.items():
            self._names[(round(spec["lat"], 5), round(spec["lng"], 5))] = name

    # ----- Places API (New)

    @staticmethod
    def place_id(name: str) -> str:
        return "place-" + re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")

    def _place(self, name: str, spec: dict) -> dict:
        place = {
            "id": spec.get("id") or self.place_id(name),
            "displayName": {"text": spec.get("display", name), "languageCode": "en"},
            "formattedAddress": f"{spec.get('display', name)}, {spec.get('town', '')}",
            "addressComponents": [{"longText": spec["town"], "shortText": spec["town"], "types": ["locality", "political"]}] if spec.get("town") else [],
            "location": {"latitude": spec["lat"], "longitude": spec["lng"]},
            "googleMapsUri": f"https://maps.google.com/?cid={spec.get('id') or self.place_id(name)}",
            "businessStatus": "OPERATIONAL",
            "rating": 4.5,
            "userRatingCount": spec.get("reviews", 1000),
            "utcOffsetMinutes": spec.get("offset", self.offset),
            "types": spec.get("types", ["tourist_attraction"]),
        }
        if spec.get("hours") is not None:
            place["regularOpeningHours"] = spec["hours"]
        if "low" in spec:
            place["viewport"] = {"low": {"latitude": spec["low"][0], "longitude": spec["low"][1]}, "high": {"latitude": spec["high"][0], "longitude": spec["high"][1]}}
        return place

    def _search(self, body: dict) -> httpx.Response:
        query = body["textQuery"]
        if query in self.areas:
            return httpx.Response(200, json={"places": [self._place(query, self.areas[query])]})
        name = query.split(", ")[0].lower()
        restriction = (body.get("locationRestriction") or {}).get("rectangle")
        found = []
        for place_name, spec in self.places.items():
            if name != place_name.lower() and name not in [m.lower() for m in spec.get("matches", [])]:
                continue
            if restriction and not (
                restriction["low"]["latitude"] <= spec["lat"] <= restriction["high"]["latitude"]
                and restriction["low"]["longitude"] <= spec["lng"] <= restriction["high"]["longitude"]
            ):
                continue
            found.append(self._place(place_name, spec))
        return httpx.Response(200, json={"places": found[: body.get("pageSize", 20)]} if found else {})

    def place_searches(self) -> list[dict]:
        """Each Text Search as {"query", "restriction": ((low lat, low lng), (high lat, high lng)) or None}."""
        searches = []
        for request in self.requests:
            if request.url.path != "/v1/places:searchText":
                continue
            body = json.loads(request.content)
            rect = (body.get("locationRestriction") or {}).get("rectangle")
            searches.append({
                "query": body["textQuery"],
                "restriction": ((rect["low"]["latitude"], rect["low"]["longitude"]), (rect["high"]["latitude"], rect["high"]["longitude"])) if rect else None,
            })
        return searches

    # ----- Routes API

    def _name(self, waypoint: dict) -> Optional[str]:
        point = waypoint["location"]["latLng"]
        return self._names.get((round(point["latitude"], 5), round(point["longitude"], 5)))

    def _spot(self, name: str) -> tuple[float, float]:
        spec = {**self.places, **self.areas, **self.points}[name]
        return spec["lat"], spec["lng"]

    def _route(self, body: dict) -> httpx.Response:
        if self.fail_routes:
            return httpx.Response(self.fail_routes, json={"error": {"code": self.fail_routes, "status": "RESOURCE_EXHAUSTED"}})
        origin, destination, mode = self._name(body["origin"]), self._name(body["destination"]), body["travelMode"]
        if origin is None or destination is None:
            return httpx.Response(200, json={})
        km = km_between(self._spot(origin), self._spot(destination))
        if mode == "DRIVE":
            if frozenset((origin, destination)) in self.water:
                return httpx.Response(200, json={})
            minutes = self.drive.get((origin, destination)) or self.drive.get((destination, origin)) or max(1, round(km * 2))
            return httpx.Response(200, json={"routes": [{"duration": f"{minutes * 60}s", "distanceMeters": round(km * 1250)}]})
        if mode == "WALK":
            if frozenset((origin, destination)) in self.water:
                return httpx.Response(200, json={})
            return httpx.Response(200, json={"routes": [{"duration": f"{max(1, round(km * 15)) * 60}s", "distanceMeters": round(km * 1250)}]})
        ferry = self.ferries.get((origin, destination))
        if mode != "TRANSIT" or not ferry:
            return httpx.Response(200, json={})
        asked = datetime.fromisoformat(body["departureTime"].replace("Z", "+00:00"))
        local = asked + timedelta(minutes=self.offset)
        for departure in ferry["departures"]:
            hour, minute = map(int, departure.split(":"))
            leaves_local = local.replace(hour=hour, minute=minute, second=0, microsecond=0)
            if leaves_local >= local:
                leaves = leaves_local - timedelta(minutes=self.offset)
                steps = [
                    {"travelMode": "WALK", "staticDuration": "300s"},
                    {"travelMode": "TRANSIT", "staticDuration": f"{ferry['minutes'] * 60}s", "transitDetails": {
                        "stopDetails": {"departureTime": leaves.strftime("%Y-%m-%dT%H:%M:%SZ"), "departureStop": {"name": ferry.get("from_stop", origin)}, "arrivalStop": {"name": ferry.get("to_stop", destination)}},
                        "transitLine": {"name": ferry["line"], "vehicle": {"name": {"text": "Ferry"}, "type": "FERRY"}},
                    }},
                    {"travelMode": "WALK", "staticDuration": "120s"},
                ]
                total = int((leaves - asked).total_seconds()) + ferry["minutes"] * 60 + 420
                return httpx.Response(200, json={"routes": [{"duration": f"{total}s", "distanceMeters": round(km * 1000), "legs": [{"steps": steps}]}]})
        return httpx.Response(200, json={})

    def drive_bodies(self) -> list[tuple[str, str, dict]]:
        found = []
        for request in self.requests:
            if request.url.path.endswith(":computeRoutes"):
                body = json.loads(request.content)
                if body["travelMode"] == "DRIVE":
                    found.append((self._name(body["origin"]), self._name(body["destination"]), body))
        return found

    def __call__(self, request: httpx.Request) -> httpx.Response:
        with self._lock:
            self.requests.append(request)
        path = request.url.path
        if path == "/v1/places:searchText":
            if self.block_search is not None:
                time.sleep(self.block_search)
            return self._search(json.loads(request.content))
        if path.startswith("/v1/places/"):
            place_id = path.rsplit("/", 1)[1]
            for name, spec in {**self.places, **self.areas}.items():
                if (spec.get("id") or self.place_id(name)) == place_id:
                    return httpx.Response(200, json=self._place(name, spec))
            return httpx.Response(404, json={"error": {"code": 404, "status": "NOT_FOUND"}})
        if path.endswith(":computeRoutes"):
            return self._route(json.loads(request.content))
        return httpx.Response(404, json={"error": {"code": 404}})


class FakeSerpApi:
    """Stands in for SerpApi's Google Maps place results. `busy` maps a Google place ID to {weekday: {hour: busyness score}}."""

    def __init__(self, busy=None, fail=None):
        self.busy = busy or {}
        self.fail = fail
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if self.fail:
            return httpx.Response(self.fail, json={"error": "simulated"})
        week = self.busy.get(request.url.params.get("place_id"))
        if week is None:
            return httpx.Response(200, json={"place_results": {"title": "A place"}})
        graph = {
            day: [{"time": f"{hour % 12 or 12} {'AM' if hour < 12 else 'PM'}", "busyness_score": score} for hour, score in sorted(hours.items())]
            for day, hours in week.items()
        }
        return httpx.Response(200, json={"place_results": {"popular_times": {"graph_results": graph}}})
