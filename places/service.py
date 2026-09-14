"""Checks an itinerary against Google Maps.

Places (TP-04 B1–B5):
- Confirmed places get Google's name, address, coordinates, Maps link, rating and review count.
- A permanently closed or unknown place is replaced once: the AI is sent only its name and the reason,
  and the replacement is checked too. If that fails as well, the place is marked unconfirmed.
- A temporarily closed place is kept and labelled.

Opening hours (TP-05 A):
- Every visit's time is checked against the place's hours for that day (that exact date within 7 days).
- A visit at a time the place is closed moves into its hours that day when it doesn't overlap another visit;
  a place closed all day is replaced once; otherwise the visit is labelled.
- Without a start date, every day of the week is checked and the visit is only labelled.

Travel times (TP-05 B): between each day's places, by car and public transport (and walking for short hops).

Only place IDs are kept between itineraries (Google's terms). All checks share one 10-second limit; whatever
isn't done by then says so, and the itinerary never waits longer.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Callable, Optional

from .extract import named_places, replace_place
from .google import GooglePlaces
from .hours import DAY_NAMES, WEEK_ORDER, day_intervals, fits, google_day, hours_text, is_whole_day, join_days, weekly_intervals
from .routes import GoogleRoutes
from .schedule import hhmm, read_visits, rewrite_visit

log = logging.getLogger(__name__)

KEY_ENV = "GOOGLE_MAPS_API_KEY"
NOT_FOUND = "not found on Google Maps"
PERMANENTLY_CLOSED = "permanently closed"
OPEN_LABEL = "Open at this time"
SHORT_HOP_KM = 1.5

Replace = Callable[[str, str], Optional[str]]


def _entry(query: str, status: str, place: Optional[dict] = None, replaces: Optional[str] = None, reason: Optional[str] = None) -> dict:
    place = place or {}
    return {
        "query": query,
        "status": status,
        "name": place.get("name"),
        "address": place.get("address"),
        "maps_url": place.get("maps_url"),
        "location": place.get("location"),
        "rating": place.get("rating"),
        "reviews": place.get("reviews"),
        "replaces": replaces,
        "reason": reason,
    }


def _clock_minutes(text: str) -> int:
    hour, minute = text.split(":")
    return int(hour) * 60 + int(minute)


@dataclass
class PlanReview:
    itinerary: str
    places: list = field(default_factory=list)
    visits: list = field(default_factory=list)
    travel: list = field(default_factory=list)


class PlaceChecker:
    def __init__(
        self,
        google: Optional[GooglePlaces] = None,
        routes: Optional[GoogleRoutes] = None,
        deadline_s: float = 10.0,
        workers: int = 6,
        today: Optional[Callable[[], date]] = None,
    ):
        self.google = google
        self.routes = routes
        self.deadline_s = deadline_s
        self.workers = workers
        self.today = today or date.today
        self._ids: dict[str, str] = {}
        self._lock = threading.Lock()

    def stored(self) -> dict[str, str]:
        """What is kept between itineraries: Google place IDs only."""
        with self._lock:
            return dict(self._ids)

    def check(self, itinerary: str, destination: str, replace: Optional[Replace] = None) -> tuple[str, list[dict]]:
        review = self.review(itinerary, destination, replace=replace)
        return review.itinerary, review.places

    def review(self, itinerary: str, destination: str, replace: Optional[Replace] = None, start_date: Optional[date] = None) -> PlanReview:
        deadline = time.monotonic() + self.deadline_s
        destination = (destination or "").strip()
        itinerary, entries, found = self._check_places(itinerary, destination, replace, deadline)
        visits = read_visits(itinerary)
        if not visits:
            return PlanReview(itinerary, entries)
        itinerary, entries, visit_entries = self._check_times(itinerary, destination, visits, entries, found, replace, start_date)
        travel = self._travel_times(visit_entries, found, start_date, deadline)
        return PlanReview(itinerary, entries, visit_entries, travel)

    # ------------------------------------------------------------------ places (TP-04)

    def _run(self, jobs: list, deadline: float, name: str) -> list:
        pool = ThreadPoolExecutor(max_workers=self.workers, thread_name_prefix=name)
        try:
            futures = [pool.submit(job) for job in jobs]
            wait(futures, timeout=max(deadline - time.monotonic(), 0))
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        results = []
        for future in futures:
            if not future.done() or future.cancelled():
                results.append(None)
            elif future.exception() is not None:
                log.warning("A Google Maps check failed (%s)", type(future.exception()).__name__)
                results.append(None)
            else:
                results.append(future.result())
        return results

    def _check_places(self, itinerary: str, destination: str, replace: Optional[Replace], deadline: float):
        names = named_places(itinerary)
        if not names:
            return itinerary, [], {}
        if self.google is None:
            return itinerary, [_entry(name, "not_checked") for name in names], {}

        results = self._run([lambda name=name: self._check_one(name, destination, replace, deadline) for name in names], deadline, "place-check")
        entries, found = [], {}
        for name, result in zip(names, results):
            if result is None:
                entries.append(_entry(name, "not_checked"))
                continue
            entry, place = result
            entries.append(entry)
            if place is not None:
                found[entry["query"].lower()] = place
        for entry in entries:
            if entry["status"] == "replaced":
                itinerary = replace_place(itinerary, entry["replaces"], entry["query"])
        return itinerary, entries, found

    def _check_one(self, name: str, destination: str, replace: Optional[Replace], deadline: float):
        place = self._lookup(name, destination)
        if place is None:
            reason = NOT_FOUND
        elif place["business_status"] == "CLOSED_PERMANENTLY":
            reason = PERMANENTLY_CLOSED
        elif place["business_status"] == "CLOSED_TEMPORARILY":
            return _entry(name, "temporarily_closed", place), place
        else:
            return _entry(name, "confirmed", place), place

        suggestion = self._ask(replace, name, reason, deadline)
        if suggestion:
            other = self._lookup(suggestion, destination)
            if other is not None and other["business_status"] not in ("CLOSED_PERMANENTLY", "CLOSED_TEMPORARILY"):
                return _entry(suggestion, "replaced", other, replaces=name, reason=reason), other
        return _entry(name, "unconfirmed", reason=reason), None

    @staticmethod
    def _ask(replace: Optional[Replace], name: str, reason: str, deadline: float) -> str:
        if replace is None or time.monotonic() >= deadline:
            return ""
        try:
            suggestion = (replace(name, reason) or "").strip()
        except Exception as exc:  # the AI failing never breaks the itinerary
            log.warning("No replacement suggested for a place (%s)", type(exc).__name__)
            return ""
        return suggestion if suggestion.lower() != name.lower() else ""

    def _lookup(self, name: str, destination: str) -> Optional[dict]:
        key = f"{name.lower()}|{destination.lower()}"
        with self._lock:
            place_id = self._ids.get(key)
        place = self.google.details(place_id) if place_id else None
        if place is None:
            place = self.google.search(f"{name}, {destination}" if destination else name)
        if place is not None and place.get("id"):
            with self._lock:
                self._ids[key] = place["id"]
        return place

    # ------------------------------------------------------------------ opening hours (TP-05 A)

    def _check_times(self, itinerary, destination, visits, entries, found, replace, start_date):
        today = self.today()
        deadline = time.monotonic() + self.deadline_s
        times = [(visit.start_min, visit.end_min) for visit in visits]
        results = []
        for index, visit in enumerate(visits):
            day = start_date + timedelta(days=visit.day - 1) if start_date else None
            start, end = times[index]
            result = {
                "day": visit.day, "date": day.isoformat() if day else None,
                "start": hhmm(start), "end": hhmm(end), "planned_start": visit.start, "planned_end": visit.end,
                "place": visit.place, "status": "not_checked", "hours": None, "label": None,
            }
            place = found.get(visit.place.lower())
            if self.google is None or place is None:
                results.append(result)
                continue
            if day is None:
                result.update(_weekly_verdict(place, start, end))
                results.append(result)
                continue

            intervals = day_intervals(place, day, today)
            if intervals is None:
                result.update(status="hours_not_listed", hours="Hours not listed")
            elif is_whole_day(intervals):
                result.update(status="open_24_hours", hours="Open 24 hours", label=OPEN_LABEL)
            elif fits(intervals, start, end):
                result.update(status="open", hours=hours_text(intervals), label=OPEN_LABEL)
            elif intervals:
                others = [times[j] for j, other in enumerate(visits) if j != index and other.day == visit.day]
                move = _best_move(intervals, start, end, others)
                if move is None:
                    result.update(status="closed_at_time", hours=hours_text(intervals), label=f"Closed at this time · {hours_text(intervals)}")
                else:
                    new_start, label = move
                    new_end = new_start + (end - start)
                    times[index] = (new_start, new_end)
                    itinerary = rewrite_visit(itinerary, visit, new_start, new_end, visit.place)
                    result.update(start=hhmm(new_start), end=hhmm(new_end), status="time_changed", hours=hours_text(intervals), label=label)
            else:
                weekday = DAY_NAMES[google_day(day)]
                reason = f"closed on {weekday}"
                swap = self._replace_closed(visit, day, start, end, destination, replace, reason, today, deadline)
                if swap is None:
                    result.update(status="closed_all_day", label=f"Closed on {weekday}")
                else:
                    new_name, new_place, new_intervals = swap
                    found[new_name.lower()] = new_place
                    itinerary = rewrite_visit(itinerary, visit, visit.start_min, visit.end_min, new_name)
                    if not any(entry["query"].lower() == new_name.lower() for entry in entries):
                        entries.append(_entry(new_name, "replaced", new_place, replaces=visit.place, reason=reason))
                    result.update(place=new_name, status="replaced", hours=hours_text(new_intervals), label=f"Suggested instead of a place that's {reason}")
            results.append(result)

        mentioned = [name.lower() for name in named_places(itinerary)]
        entries = sorted((entry for entry in entries if entry["query"].lower() in mentioned), key=lambda entry: mentioned.index(entry["query"].lower()))
        return itinerary, entries, results

    def _replace_closed(self, visit, day, start, end, destination, replace, reason, today, deadline):
        suggestion = self._ask(replace, visit.place, reason, deadline)
        if not suggestion:
            return None
        try:
            other = self._lookup(suggestion, destination)
        except Exception as exc:
            log.warning("A replacement couldn't be checked on Google Maps (%s)", type(exc).__name__)
            return None
        if other is None or other["business_status"] in ("CLOSED_PERMANENTLY", "CLOSED_TEMPORARILY"):
            return None
        intervals = day_intervals(other, day, today)
        if intervals is None or not (is_whole_day(intervals) or fits(intervals, start, end)):
            return None
        return suggestion, other, intervals

    # ------------------------------------------------------------------ travel times (TP-05 B)

    def _travel_times(self, visits: list[dict], found: dict, start_date: Optional[date], deadline: float) -> list[dict]:
        legs, jobs = [], []
        for earlier, later in zip(visits, visits[1:]):
            if earlier["day"] != later["day"]:
                continue
            leg = {
                "day": earlier["day"], "from": earlier["place"], "to": later["place"], "leave": earlier["end"],
                "car": None, "transit": None, "transit_message": None, "walk": None, "status": "not_checked", "label": "Not checked",
            }
            legs.append(leg)
            origin, destination = found.get(earlier["place"].lower()), found.get(later["place"].lower())
            if self.routes is None or self.google is None or not origin or not destination or not origin.get("location") or not destination.get("location"):
                continue
            jobs.append((leg, origin, destination, earlier, later))
        if not jobs:
            return legs

        results = self._run(
            [lambda o=origin, d=destination, e=earlier: self._one_trip(o, d, e, start_date) for _, origin, destination, earlier, _ in jobs],
            deadline,
            "travel-times",
        )
        for (leg, _, _, earlier, later), result in zip(jobs, results):
            if result is None:
                leg.update(status="not_available", label="Travel time not available")
                continue
            car, walk, transit = result
            if car is None and transit is None and walk is None:
                leg.update(status="not_available", label="Travel time not available")
                continue
            gap = _clock_minutes(later["start"]) - _clock_minutes(earlier["end"])
            leg.update(
                car=car, walk=walk, transit=transit, status="ok",
                transit_message=None if transit else "No public transport at this time",
                label="Not enough time to get there" if car and car["minutes"] > gap else None,
            )
        return legs

    def _one_trip(self, origin: dict, destination: dict, earlier: dict, start_date: Optional[date]):
        car = self.routes.drive(origin["location"], destination["location"])
        walk = self.routes.walk(origin["location"], destination["location"]) if car is not None and car["km"] < SHORT_HOP_KM else None
        day = start_date + timedelta(days=earlier["day"] - 1) if start_date else self.today() + timedelta(days=1)
        local = datetime(day.year, day.month, day.day) + timedelta(minutes=_clock_minutes(earlier["end"]))
        leave_utc = local - timedelta(minutes=origin.get("utc_offset_minutes") or 0)
        transit = self.routes.transit(origin["location"], destination["location"], leave_utc)
        return car, walk, transit


def _best_move(intervals, start: int, end: int, others) -> Optional[tuple[int, str]]:
    """The nearest time inside the place's hours that keeps the visit's length and overlaps no other visit."""
    length = end - start
    best = None
    for opens, closes in intervals:
        if closes - opens < length:
            continue
        candidate = min(max(start, opens), closes - length)
        if any(candidate < other_end and other_start < candidate + length for other_start, other_end in others):
            continue
        shift = abs(candidate - start)
        if best is None or shift < best[0]:
            label = f"Time changed: opens {_ampm(opens)}" if candidate > start else f"Time changed: closes {_ampm(closes)}"
            best = (shift, candidate, label)
    return (best[1], best[2]) if best else None


def _ampm(minutes: int) -> str:
    from .hours import clock

    return clock(minutes)


def _weekly_verdict(place: dict, start: int, end: int) -> dict:
    """Without a date: check the visit against every day of the week, and only label it (TP-05 A7)."""
    regular = place.get("regular_hours")
    if not regular or not regular.get("periods"):
        return {"status": "hours_not_listed", "hours": "Hours not listed", "label": None}
    week = {day: weekly_intervals(regular, day) for day in range(7)}
    if all(is_whole_day(week[day]) for day in range(7)):
        return {"status": "open_24_hours", "hours": "Open 24 hours", "label": OPEN_LABEL}
    same_every_day = all(week[day] == week[1] for day in range(7))
    hours = hours_text(week[1]) if same_every_day else None
    closed = [day for day in WEEK_ORDER if not fits(week[day], start, end)]
    if not closed:
        return {"status": "open", "hours": hours, "label": OPEN_LABEL}
    if len(closed) == 7:
        return {"status": "closed_at_time", "hours": hours, "label": f"Closed at this time · {hours}" if hours else "Closed at this time"}
    return {"status": "closed_some_days", "hours": hours, "label": "Closed at this time on " + join_days(closed)}


def build_place_checker() -> PlaceChecker:
    key = os.environ.get(KEY_ENV, "").strip()
    if not key:
        return PlaceChecker()
    return PlaceChecker(google=GooglePlaces(api_key=key), routes=GoogleRoutes(api_key=key))


_checker: Optional[PlaceChecker] = None
_checker_lock = threading.Lock()


def get_place_checker() -> PlaceChecker:
    """One shared checker, rebuilt if the Google key is added or removed."""
    global _checker
    with _checker_lock:
        has_key = bool(os.environ.get(KEY_ENV, "").strip())
        if _checker is None or (_checker.google is not None) != has_key:
            _checker = build_place_checker()
        return _checker


def _key_status(service: str, label: str) -> dict:
    has_key = bool(os.environ.get(KEY_ENV, "").strip())
    return {"service": service, "label": label, "key": KEY_ENV, "set": has_key, "status": "ready" if has_key else "key missing"}


def place_checks_status() -> dict:
    """For /api/health: whether place checks can run. Never the key itself."""
    return _key_status("place_checks", "Place checks (Google Maps)")


def travel_times_status() -> dict:
    """For /api/health: whether travel times can run (TP-05 K1). Never the key itself."""
    return _key_status("travel_times", "Travel times (Google Routes)")
