"""Trip essentials from free services (TP-04 C1–C5).

- The destination is found with Photon (OpenStreetMap), or Nominatim if Photon fails.
- Weather for each trip day comes from Open-Meteo: the forecast while it reaches (today and the next
  15 days), otherwise last year's weather on the same date, labelled "Typical".
- Currency: Frankfurter (ECB rates), or Currency-api if Frankfurter fails. Nothing when the currencies match.
- Public holidays: Nager.Date. Destination intro: Wikipedia. Safety level: Warnely.
- Each part works on its own and the whole answer takes at most 8 seconds; a part that fails or is too
  slow says "Not available right now". Complete answers are cached for 3 hours; answers with a failed part aren't.
"""

from __future__ import annotations

import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from datetime import date, timedelta
from typing import Callable, Optional
from urllib.parse import quote

import httpx

from .currencies import currency_for_country

log = logging.getLogger(__name__)

# Wikipedia and Nominatim ask apps to identify themselves with a way to reach them.
USER_AGENT = "TravelWithYori/0.1 (https://yoritrip.yorilabs.ai)"
NOT_AVAILABLE_MESSAGE = "Not available right now"
FORECAST_DAYS = 16
PARTS = ("weather", "currency", "holidays", "intro", "safety")

PHOTON_URL = "https://photon.komoot.io/api/"
NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"
FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
FRANKFURTER_URL = "https://api.frankfurter.dev/v1/latest"
CURRENCY_API_URL = "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/{code}.json"
NAGER_URL = "https://date.nager.at/api/v3/PublicHolidays/{year}/{country}"
WIKIPEDIA_URL = "https://en.wikipedia.org/api/rest_v1/page/summary/{title}"
WARNELY_URL = "https://www.warnely.com/api/v1/countries/{country}"

# For /api/health (TP-04 C10). None of these needs a key.
SERVICES = (
    ("place_finder", "Finding the destination (Photon, Nominatim)"),
    ("weather", "Weather (Open-Meteo)"),
    ("currency", "Currency rates (Frankfurter, Currency-api)"),
    ("holidays", "Public holidays (Nager.Date)"),
    ("intro", "Destination intro (Wikipedia)"),
    ("safety", "Safety level (Warnely)"),
)


class PartFailed(Exception):
    """A service didn't give a usable answer."""


def not_available() -> dict:
    return {"available": False, "message": NOT_AVAILABLE_MESSAGE}


def services_status() -> list[dict]:
    return [{"service": service, "label": label, "key": None, "set": True, "status": "ready"} for service, label in SERVICES]


def _one_year_back(day: date) -> date:
    try:
        return day.replace(year=day.year - 1)
    except ValueError:  # 29 February
        return day.replace(year=day.year - 1, day=28)


def _first_sentences(text: str, count: int) -> str:
    sentences = re.split(r"(?<=[.!?])\s+", text.strip())
    return " ".join(sentences[:count])


def _clock_time(value: Optional[str]) -> Optional[str]:
    return value[11:16] if isinstance(value, str) and len(value) >= 16 else None


class TripInfoService:
    def __init__(
        self,
        http_client: Optional[httpx.Client] = None,
        clock: Optional[Callable[[], float]] = None,
        today: Optional[Callable[[], date]] = None,
        ttl_s: float = 3 * 3600,
        deadline_s: float = 8.0,
    ):
        self._http = http_client or httpx.Client(timeout=6.0, follow_redirects=True)
        self.clock = clock or time.monotonic
        self.today = today or date.today
        self.ttl_s = ttl_s
        self.deadline_s = deadline_s
        self._cache: dict[tuple, tuple[float, dict]] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ the whole answer

    def info(self, place: str, start: date, days: int, currency: str) -> dict:
        currency = currency.upper()
        key = (place.strip().lower(), start.isoformat(), days, currency)
        with self._lock:
            hit = self._cache.get(key)
        if hit is not None and self.clock() - hit[0] < self.ttl_s:
            return {**hit[1], "cached": True}

        deadline = time.monotonic() + self.deadline_s
        pool = ThreadPoolExecutor(max_workers=len(PARTS), thread_name_prefix="trip-info")
        try:
            finding = pool.submit(self._find_place, place.strip())
            wait([finding], timeout=self.deadline_s)
            where = self._outcome("place", finding, default=None)
            if where is None:
                parts = {name: not_available() for name in PARTS}
            else:
                jobs = {
                    "weather": pool.submit(self._weather, where, start, days),
                    "currency": pool.submit(self._currency, where, currency),
                    "holidays": pool.submit(self._holidays, where, start, days),
                    "intro": pool.submit(self._intro, where),
                    "safety": pool.submit(self._safety, where),
                }
                wait(list(jobs.values()), timeout=max(deadline - time.monotonic(), 0))
                parts = {name: self._outcome(name, job, default=not_available()) for name, job in jobs.items()}
        finally:
            pool.shutdown(wait=False, cancel_futures=True)

        public_place = {"name": where["name"], "country": where["country"], "country_code": where["country_code"]} if where else None
        answer = {"place": public_place, **parts}
        failed = where is None or any(isinstance(part, dict) and part.get("message") == NOT_AVAILABLE_MESSAGE for part in parts.values())
        if not failed:
            with self._lock:
                self._cache[key] = (self.clock(), answer)
        return {**answer, "cached": False}

    @staticmethod
    def _outcome(name: str, future, default):
        if not future.done() or future.cancelled():
            log.warning("Trip information: %s took too long", name)
            return default
        error = future.exception()
        if error is not None:
            log.warning("Trip information: %s unavailable (%s)", name, type(error).__name__)
            return default
        return future.result()

    def _json(self, url: str, params: Optional[dict] = None):
        response = self._http.get(url, params=params, headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
        if response.status_code != 200:
            raise PartFailed(f"HTTP {response.status_code}")
        return response.json()

    # ------------------------------------------------------------------ the destination

    def _find_place(self, place: str) -> Optional[dict]:
        try:
            features = self._json(PHOTON_URL, {"q": place, "limit": 1, "lang": "en"}).get("features") or []
            if features:
                props = features[0]["properties"]
                lng, lat = features[0]["geometry"]["coordinates"][:2]
                code = (props.get("countrycode") or "").upper()
                if code:
                    return {"name": props.get("name") or place, "country": props.get("country"), "country_code": code, "lat": lat, "lng": lng}
        except (PartFailed, httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
            log.warning("Photon couldn't find the destination (%s); trying Nominatim", type(exc).__name__)
        try:
            results = self._json(NOMINATIM_URL, {"q": place, "format": "jsonv2", "limit": 1, "addressdetails": 1, "accept-language": "en"})
            if results:
                first = results[0]
                address = first.get("address") or {}
                code = (address.get("country_code") or "").upper()
                if code:
                    return {"name": first.get("name") or place, "country": address.get("country"), "country_code": code, "lat": float(first["lat"]), "lng": float(first["lon"])}
        except (PartFailed, httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
            log.warning("Nominatim couldn't find the destination (%s)", type(exc).__name__)
        return None

    # ------------------------------------------------------------------ the parts

    def _weather(self, where: dict, start: date, days: int) -> dict:
        today = self.today()
        last_forecast_day = today + timedelta(days=FORECAST_DAYS - 1)
        trip_days = [start + timedelta(days=offset) for offset in range(days)]
        forecast_days = [day for day in trip_days if today <= day <= last_forecast_day]
        typical_days = [day for day in trip_days if day not in forecast_days]
        at = {"latitude": where["lat"], "longitude": where["lng"], "timezone": "auto"}
        found: dict[str, dict] = {}

        if forecast_days:
            daily = self._json(FORECAST_URL, {
                **at,
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_probability_max,sunrise,sunset",
                "start_date": forecast_days[0].isoformat(),
                "end_date": forecast_days[-1].isoformat(),
            })["daily"]
            rows = {moment: index for index, moment in enumerate(daily["time"])}
            for day in forecast_days:
                i = rows[day.isoformat()]
                found[day.isoformat()] = {
                    "date": day.isoformat(), "kind": "forecast", "label": "Forecast",
                    "high_c": daily["temperature_2m_max"][i], "low_c": daily["temperature_2m_min"][i],
                    "rain_chance": daily["precipitation_probability_max"][i], "rain_mm": None,
                    "sunrise": _clock_time(daily["sunrise"][i]), "sunset": _clock_time(daily["sunset"][i]),
                }

        if typical_days:
            last_year = [_one_year_back(day) for day in typical_days]
            daily = self._json(ARCHIVE_URL, {
                **at,
                "daily": "temperature_2m_max,temperature_2m_min,precipitation_sum,sunrise,sunset",
                "start_date": min(last_year).isoformat(),
                "end_date": max(last_year).isoformat(),
            })["daily"]
            rows = {moment: index for index, moment in enumerate(daily["time"])}
            for day, before in zip(typical_days, last_year):
                i = rows[before.isoformat()]
                found[day.isoformat()] = {
                    "date": day.isoformat(), "kind": "typical", "label": "Typical",
                    "high_c": daily["temperature_2m_max"][i], "low_c": daily["temperature_2m_min"][i],
                    "rain_chance": None, "rain_mm": daily["precipitation_sum"][i],
                    "sunrise": _clock_time(daily["sunrise"][i]), "sunset": _clock_time(daily["sunset"][i]),
                }
        return {"available": True, "days": [found[day.isoformat()] for day in trip_days]}

    def _currency(self, where: dict, currency: str) -> Optional[dict]:
        destination = currency_for_country(where["country_code"])
        if destination is None:
            raise PartFailed("unknown currency for this country")
        if destination == currency:
            return None
        try:
            body = self._json(FRANKFURTER_URL, {"base": currency, "symbols": destination})
            rate, rate_date, source = float(body["rates"][destination]), body["date"], "Frankfurter"
        except (PartFailed, httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
            log.warning("Frankfurter has no %s rate (%s); trying Currency-api", destination, type(exc).__name__)
            body = self._json(CURRENCY_API_URL.format(code=currency.lower()))
            rate, rate_date, source = float(body[currency.lower()][destination.lower()]), body["date"], "Currency-api"
        return {"available": True, "from": currency, "to": destination, "rate": rate, "inverse": round(1 / rate, 2), "date": rate_date, "source": source}

    def _holidays(self, where: dict, start: date, days: int) -> dict:
        end = start + timedelta(days=days - 1)
        found = []
        for year in range(start.year, end.year + 1):
            response = self._http.get(NAGER_URL.format(year=year, country=where["country_code"]), headers={"User-Agent": USER_AGENT, "Accept": "application/json"})
            if response.status_code in (204, 404):
                return {"available": False, "message": f"Public holidays aren't available for {where.get('country') or 'this country'} yet."}
            if response.status_code != 200:
                raise PartFailed(f"HTTP {response.status_code}")
            for holiday in response.json():
                if start.isoformat() <= holiday["date"] <= end.isoformat() and holiday.get("global", True):
                    entry = {"date": holiday["date"], "name": holiday["name"], "local_name": holiday.get("localName")}
                    if entry not in found:
                        found.append(entry)
        return {"available": True, "days": found}

    def _intro(self, where: dict) -> dict:
        body = self._json(WIKIPEDIA_URL.format(title=quote(where["name"].replace(" ", "_"), safe="")))
        if body.get("type") != "standard" or not body.get("extract"):
            raise PartFailed("no plain Wikipedia article")
        return {
            "available": True,
            "title": body.get("title") or where["name"],
            "text": _first_sentences(body["extract"], 3),
            "url": body["content_urls"]["desktop"]["page"],
            "credit": "Wikipedia",
        }

    def _safety(self, where: dict) -> dict:
        country = self._json(WARNELY_URL.format(country=where["country_code"]))["country"]
        return {
            "available": True,
            "score": country["risk_score"],
            "tier": country["risk_tier"],
            "summary": country.get("summary"),
            "credit": "Warnely (CC BY 4.0)",
            "url": "https://www.warnely.com",
        }
