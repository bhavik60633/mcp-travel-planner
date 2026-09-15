"""Checks an itinerary against Google Maps and builds each day's timetable from the stay.

Places (TP-04 B1–B5, TP-07 N1–N3):
- Each place is searched only near that day's base: the stay, Yori's base area, the stay in a far area, or a day-trip
  town. A chain matches its branch nearest the stay (or nearest the day's other places without a hotel).
- A permanently closed or unknown place, or one more than 50 km from the base, is replaced once: the AI is sent only its
  name and the reason, and the replacement is checked too. A temporarily closed place is kept and labelled.

Far areas (TP-07 C1, C3, C4): a day whose places are mostly more than 50 km away becomes a day in that area. More than
90 minutes' drive makes it a stay there (unless the trip has one stay for all nights), otherwise a day trip. The AI may
rewrite only those days, and the new text is checked again without further rewrites.

Opening hours (TP-05 A) are checked as before. Then each day's timetable (TP-07 A2, B, C2, D1, E, F) starts from the
stay: visits are put in the order that cuts travel, trips use live traffic at the hour you'd leave, buffers follow D3,
boats come from the checked timetable file or Google, busy meals move or get a wait, and every time in the text is
rewritten to match.

Only place IDs are kept between itineraries (Google's terms). Place checks have 10 seconds, and travel times their own
10 seconds after them (D11); whatever isn't done by then says so.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from dataclasses import replace as replaced
from datetime import date, datetime, timedelta, timezone
from itertools import permutations
from typing import Callable, Optional

from plans import timetable as tt
from plans.busy import BusyHours, build_busy_hours, busy_window
from plans.ferries import CHECK_LABEL, EARLY_MINUTES, find_crossing, load_routes

from .extract import named_places, replace_place
from .geo import centre, km_between, rectangle_around
from .google import GooglePlaces, GoogleUnavailable
from .hours import DAY_NAMES, WEEK_ORDER, clock, day_intervals, fits, google_day, hours_text, is_whole_day, join_days, weekly_intervals
from .names import names_match
from .routes import GoogleRoutes, RoutesUnavailable
from .schedule import Visit, hhmm, read_visits, rewrite_visit

log = logging.getLogger(__name__)

KEY_ENV = "GOOGLE_MAPS_API_KEY"
NOT_FOUND = "not found on Google Maps"
PERMANENTLY_CLOSED = "permanently closed"
TOO_FAR = "more than 50 km from your stay"
OPEN_LABEL = "Open at this time"
NOT_AVAILABLE = "Travel time not available"
BOAT_UNKNOWN = "Boat times unknown: check locally"
NOT_CHECKED_MESSAGE = "Timings not checked yet"
GRACE_S = 0.25

Replace = Callable[[str, str], Optional[str]]
Rewrite = Callable[[str, list, list], Optional[str]]


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


def _time(minutes: Optional[int]) -> Optional[str]:
    return None if minutes is None else hhmm(minutes % 1440)


@dataclass
class TripPlan:
    """What the checker needs to know about the trip: where each night is spent (TP-07 A1)."""

    destination: str = ""
    start_date: Optional[date] = None
    num_days: int = 1
    nights: Optional[int] = None
    stay: Optional[dict] = None
    stops: list = field(default_factory=list)  # [{"place", "nights", "stay"}]
    stay_per_stop: Optional[bool] = None


@dataclass(frozen=True)
class Base:
    """Where a day starts or ends: a stay, Yori's base area, or a far area."""

    name: str
    lat: float
    lng: float
    source: str
    area: str
    address: Optional[str] = None
    label: Optional[str] = None

    @property
    def point(self) -> dict:
        return {"lat": self.lat, "lng": self.lng}

    @property
    def real(self) -> bool:
        return self.source != "area"

    def spot(self) -> dict:
        return {"name": self.name, "point": self.point, "reviews": None}

    def to_json(self) -> dict:
        return {"name": self.name, "address": self.address, "lat": self.lat, "lng": self.lng, "source": self.source, "label": self.label}


@dataclass
class DayPlan:
    day: int
    date: Optional[date]
    morning: Optional[Base]
    night: Optional[Base]
    home: Optional[Base]
    has_night: bool = True
    kind: str = "base"  # base | day_trip | stay_there (move is worked out from morning and night)
    area: Optional[str] = None
    area_base: Optional[Base] = None
    far_minutes: Optional[int] = None

    @property
    def search_base(self) -> Optional[Base]:
        return self.area_base or self.night


@dataclass
class PlanReview:
    itinerary: str
    places: list = field(default_factory=list)
    visits: list = field(default_factory=list)
    travel: list = field(default_factory=list)
    timetable: list = field(default_factory=list)
    timings_checked: bool = False
    timings_message: Optional[str] = NOT_CHECKED_MESSAGE
    new_stays: list = field(default_factory=list)


class _Run:
    """What one review keeps while it runs."""

    def __init__(self, trip: TripPlan, destination: str, place_deadline: float):
        self.trip = trip
        self.destination = destination
        self.days: dict[int, DayPlan] = {}
        self.place_deadline = place_deadline
        self.deadline = place_deadline
        self.pairs: dict = {}
        self.weeks: dict = {}
        self.lock = threading.Lock()

    def expired(self) -> bool:
        return time.monotonic() >= self.deadline


@dataclass
class _Leg:
    rows: list
    ok: bool = False
    arrive: Optional[int] = None
    buffer: int = 0
    leave: Optional[int] = None
    fail_label: Optional[str] = None


def _travel_row(origin: Optional[str], destination: Optional[str], status: str = "not_checked", label: Optional[str] = "Not checked") -> dict:
    return {
        "kind": "travel", "from": origin, "to": destination, "mode": None, "minutes": None, "km": None, "traffic": False, "buffer": None,
        "leave": None, "arrive": None, "status": status, "label": label, "car": None, "walk": None, "transit": None, "transit_message": None,
    }


def _pair_key(a: dict, b: dict) -> tuple:
    return tuple(sorted(((round(a["point"]["lat"], 5), round(a["point"]["lng"], 5)), (round(b["point"]["lat"], 5), round(b["point"]["lng"], 5)))))


def _place_for(found: dict, day: int, name: str) -> Optional[dict]:
    key = name.lower()
    return found.get((day, key)) or found.get((0, key)) or found.get(key)


def _visit_spot(name: str, place: Optional[dict]) -> Optional[dict]:
    if not place or not place.get("location"):
        return None
    return {"name": name, "point": place["location"], "reviews": place.get("reviews")}


def _jetty(side: dict) -> dict:
    return {"name": side["jetty"], "point": {"lat": side["lat"], "lng": side["lng"]}, "reviews": None}


def _boat_row(crossing, departs: Optional[int], day: Optional[date]) -> dict:
    if departs is not None:
        label = CHECK_LABEL
    elif not crossing.runs_on(day):
        label = f"No boats on {day.strftime('%A')}s"
    else:
        label = f"No boat after {hhmm(crossing.last)}"
    return {
        "kind": "boat", "from": crossing.start["jetty"], "to": crossing.end["jetty"], "line": crossing.route["name"],
        "departs": _time(departs), "arrives": _time(departs + crossing.minutes) if departs is not None else None, "minutes": crossing.minutes,
        "be_at_jetty": _time(departs - crossing.early) if departs is not None else None,
        "source": crossing.source, "checked": crossing.route["checked"], "label": label,
    }


class PlaceChecker:
    def __init__(
        self,
        google: Optional[GooglePlaces] = None,
        routes: Optional[GoogleRoutes] = None,
        busy: Optional[BusyHours] = None,
        ferries: Optional[list] = None,
        deadline_s: float = 10.0,
        travel_deadline_s: float = 10.0,
        workers: int = 6,
        today: Optional[Callable[[], date]] = None,
    ):
        self.google = google
        self.routes = routes
        self.busy = busy
        self.ferries = ferries or []
        self.deadline_s = deadline_s
        self.travel_deadline_s = travel_deadline_s
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

    @property
    def timings_checked(self) -> bool:
        return self.google is not None and self.routes is not None

    def review(
        self,
        itinerary: str,
        destination: str,
        replace: Optional[Replace] = None,
        start_date: Optional[date] = None,
        trip: Optional[TripPlan] = None,
        rewrite: Optional[Rewrite] = None,
    ) -> PlanReview:
        destination = (destination or "").strip()
        if trip is None:
            trip = TripPlan(destination=destination, start_date=start_date)
        elif trip.start_date is None and start_date is not None:
            trip = replaced(trip, start_date=start_date)
        checked = self.timings_checked
        run = _Run(trip, destination, time.monotonic() + self.deadline_s)
        visits = read_visits(itinerary)
        total_days = max([max(trip.num_days or 1, 1)] + [visit.day for visit in visits])
        run.days = self._plan_days(trip, destination, total_days, run.place_deadline)

        itinerary, entries, found = self._check_places(itinerary, run, replace, detect_far=True, rewrite_pending=rewrite is not None)
        moves = [plan for plan in run.days.values() if plan.kind in ("stay_there", "day_trip")]
        if moves and rewrite is not None:
            new_text = self._rewrite_far_days(rewrite, itinerary, moves, run)
            if new_text:
                itinerary = new_text
            run.place_deadline = time.monotonic() + self.deadline_s
            itinerary, entries, found = self._check_places(itinerary, run, replace, detect_far=False, rewrite_pending=False)

        review = PlanReview(itinerary, entries, timings_checked=checked, timings_message=None if checked else NOT_CHECKED_MESSAGE, new_stays=_new_stays(run.days))
        visits = read_visits(itinerary)
        if not visits:
            return review

        run.deadline = time.monotonic() + self.travel_deadline_s
        if checked:
            itinerary = self._reorder(itinerary, visits, run, found)
            visits = read_visits(itinerary)
        if self.google is not None:
            itinerary, entries, results = self._check_times(itinerary, run, visits, entries, found, replace)
            visits = read_visits(itinerary)
        else:
            results = [_unchecked_visit(visit, trip.start_date) for visit in visits]

        timetable = self._build_timetable(itinerary, visits, results, run, found, checked)
        if checked:
            itinerary = _rewrite_times(itinerary, visits, timetable)
        review.itinerary = itinerary
        review.places = entries
        review.visits = _visits_json(timetable)
        review.travel = _travel_json(timetable)
        for entry in timetable:
            for row in entry["rows"]:
                row.pop("_index", None)
                row.pop("_pushed", None)
        review.timetable = timetable
        return review

    # ------------------------------------------------------------------ running jobs

    def _run(self, jobs: list, deadline: float, name: str) -> list:
        if not jobs:
            return []
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

    # ------------------------------------------------------------------ where each day starts and ends (TP-07 A1)

    def _area(self, text: str) -> Optional[dict]:
        if self.google is None or not text:
            return None
        try:
            return self.google.area(text)
        except GoogleUnavailable as exc:
            log.warning("A map area couldn't be looked up (%s)", exc)
            return None

    def _plan_days(self, trip: TripPlan, destination: str, total_days: int, deadline: float) -> dict[int, DayPlan]:
        spots: dict[str, Optional[dict]] = {}

        def area_stay(query: str, place: str) -> Optional[Base]:
            spot = spots.get(query.lower())
            return Base("Your stay's area", spot["lat"], spot["lng"], "area", area=place, label=f"Your stay's area: {place}") if spot else None

        def stay_base(stay: Optional[dict], place: str) -> Optional[Base]:
            if not stay:
                return None
            try:
                lat, lng = float(stay["lat"]), float(stay["lng"])
            except (KeyError, TypeError, ValueError):
                return None
            source = stay.get("source") or "google"
            name = str(stay.get("name") or "Your stay")
            label = f"Your stay's area: {name}" if source == "area" else None
            return Base(name, lat, lng, source, area=place, address=stay.get("address"), label=label)

        stops = [stop for stop in trip.stops or [] if stop.get("place")]
        per_stop = bool(stops) and trip.stay_per_stop is not False
        main_stop = max(stops, key=lambda stop: stop.get("nights") or 0) if stops else None

        def stop_query(place: str) -> str:
            return f"{place}, {destination}" if destination and place.lower() != destination.lower() else place

        # Places without a stay start from their centre, looked up within the place checks' time (TP-07 A1, N1).
        queries: list[str] = []
        if self.google is not None:
            if per_stop:
                for stop in stops:
                    if not stay_base(stop.get("stay"), stop["place"]) and not (len(stops) == 1 and stay_base(trip.stay, stop["place"])):
                        queries.append(stop_query(stop["place"]))
            elif not stay_base(trip.stay, destination) and not (main_stop and stay_base(main_stop.get("stay"), destination)) and destination:
                queries.append(destination)
        queries = list(dict.fromkeys(queries))
        found = self._run([lambda query=query: self._area(query) for query in queries], deadline, "stay-area")
        spots.update({query.lower(): spot for query, spot in zip(queries, found)})

        if per_stop:
            bases = []
            for stop in stops:
                place = stop["place"]
                bases.append(stay_base(stop.get("stay"), place) or (stay_base(trip.stay, place) if len(stops) == 1 else None) or area_stay(stop_query(place), place))
            ends, total = [], 0
            for stop in stops:
                total += max(int(stop.get("nights") or 0), 0)
                ends.append(total)

            def night_of(day: int) -> Optional[Base]:
                for index, end in enumerate(ends):
                    if day <= end:
                        return bases[index]
                return bases[-1]
        else:
            place = main_stop["place"] if main_stop else destination
            home = stay_base(trip.stay, place) or (stay_base(main_stop.get("stay"), place) if main_stop else None) or area_stay(destination, destination)

            def night_of(day: int) -> Optional[Base]:
                return home

        nights = trip.nights if trip.nights is not None else max(total_days - 1, 0)
        days = {}
        for day in range(1, total_days + 1):
            night = night_of(day)
            days[day] = DayPlan(
                day=day,
                date=trip.start_date + timedelta(days=day - 1) if trip.start_date else None,
                morning=night_of(day - 1) if day > 1 else night,
                night=night,
                home=night,
                has_night=day <= nights,
            )
        return days

    # ------------------------------------------------------------------ places (TP-04, TP-07 N)

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

    @staticmethod
    def _near_key(name: str, hint: str, base: Base) -> str:
        return f"{name.lower()}|{hint.lower()}|{base.lat:.3f},{base.lng:.3f}"

    def _near(self, name: str, hint: str, base: Optional[Base]) -> list[dict]:
        """Google's matches for `name` within 50 km of the base (N1, N2)."""
        if base is None:
            place = self._lookup(name, hint)
            return [place] if place and names_match(name, place.get("name"), (hint,)) else []
        with self._lock:
            place_id = self._ids.get(self._near_key(name, hint, base))
        if place_id:
            place = self.google.details(place_id)
            if place and place.get("location") and km_between(place["location"], base.point) <= tt.FAR_KM and names_match(name, place.get("name"), (hint,)):
                return [place]
        query = f"{name}, {hint}" if hint else name
        found = self.google.search_all(query, restriction=rectangle_around(base.point, tt.FAR_KM), page_size=5)
        return [
            place for place in found
            if place.get("location") and km_between(place["location"], base.point) <= tt.FAR_KM and names_match(name, place.get("name"), (hint,))
        ]

    def _remember(self, name: str, hint: str, base: Optional[Base], place: Optional[dict]) -> None:
        if base is None or not place or not place.get("id"):
            return
        with self._lock:
            self._ids[self._near_key(name, hint, base)] = place["id"]

    @staticmethod
    def _choose(candidates: list[dict], base: Optional[Base], others: list[dict]) -> Optional[dict]:
        """A chain's branch nearest the stay, or nearest the day's other places without a hotel (N3)."""
        if not candidates:
            return None
        usable = [place for place in candidates if place.get("business_status") != "CLOSED_PERMANENTLY"] or candidates
        if len(usable) == 1 or (base is None and not others):
            return usable[0]
        target = base.point if base is not None and (base.real or not others) else centre(others)
        return min(usable, key=lambda place: km_between(place["location"], target))

    def _check_places(self, itinerary: str, run: _Run, replace: Optional[Replace], detect_far: bool, rewrite_pending: bool):
        names = named_places(itinerary)
        if not names:
            return itinerary, [], {}
        if self.google is None:
            return itinerary, [_entry(name, "not_checked") for name in names], {}
        deadline = run.place_deadline
        first = run.days.get(min(run.days)) if run.days else None

        by_day: dict[int, list[str]] = {}
        for visit in read_visits(itinerary):
            listed = by_day.setdefault(visit.day, [])
            if visit.place.lower() not in (name.lower() for name in listed):
                listed.append(visit.place)
        on_days = {name.lower() for listed in by_day.values() for name in listed}
        jobs = [(day, name) for day in sorted(by_day) for name in by_day[day]] + [(0, name) for name in names if name.lower() not in on_days]

        def base_of(day: int) -> Optional[Base]:
            plan = run.days.get(day)
            if plan is not None:
                return plan.search_base
            return first.search_base if first else None

        def hint_of(day: int) -> str:
            plan = run.days.get(day)
            return plan.area if plan is not None and plan.area_base is not None and plan.area else run.destination

        results = self._run([lambda d=day, n=name: self._near(n, hint_of(d), base_of(d)) for day, name in jobs], deadline, "place-check")
        candidates = {(day, name.lower()): result for (day, name), result in zip(jobs, results)}

        # Not found near the base: is it somewhere else? (N2, C1)
        missing = [(day, name) for day, name in jobs if candidates[(day, name.lower())] == [] and base_of(day) is not None]
        # The name alone: "Taj Mahal, Jaipur" leads Google to Jaipur's Jai Mahal Palace, not the Taj Mahal in Agra (live, 15 Sep 2026).
        anywhere = self._run([lambda n=name: self.google.search(n) for _, name in missing], deadline, "place-far")
        far: dict[tuple, dict] = {}
        for (day, name), place in zip(missing, anywhere):
            if not place or not place.get("location") or not names_match(name, place.get("name"), (run.destination,)):
                continue
            if day == 0 or km_between(place["location"], base_of(day).point) <= tt.FAR_KM:
                candidates[(day, name.lower())] = [place]
            else:
                far[(day, name.lower())] = place

        if detect_far:
            # On a day with a far place, a nearby match can be a namesake: "Chand Baori" matched a well 13 km from Jaipur and
            # "Abhaneri" a Jaipur hotel, while the plan's Abhaneri day was 90 km away (live, 15 Sep 2026). Where Google puts
            # the day's other names decides: those next to the far places count as far too.
            maybe = []
            for day in sorted(by_day):
                plan = run.days.get(day)
                if plan is None or plan.kind != "base" or plan.search_base is None:
                    continue
                if any((day, name.lower()) in far for name in by_day[day]):
                    maybe.extend((day, name) for name in by_day[day] if candidates.get((day, name.lower())) and (day, name.lower()) not in far)
            elsewhere = self._run([lambda n=name: self.google.search(n) for _, name in maybe], deadline, "place-elsewhere")
            for (day, name), place in zip(maybe, elsewhere):
                if not place or not place.get("location") or not names_match(name, place.get("name"), (run.destination,)):
                    continue
                if km_between(place["location"], base_of(day).point) <= tt.FAR_KM:
                    continue
                far_here = [far[(day, other.lower())]["location"] for other in by_day[day] if (day, other.lower()) in far]
                if far_here and km_between(place["location"], centre(far_here)) <= tt.FAR_KM:
                    far[(day, name.lower())] = place

            far_plans = []
            for day in sorted(by_day):
                plan = run.days.get(day)
                if plan is None or plan.kind != "base" or plan.search_base is None:
                    continue
                day_far = [far[(day, name.lower())] for name in by_day[day] if (day, name.lower()) in far]
                # Names Google doesn't know anywhere ("Drive from Jaipur to Agra") don't count either way.
                resolved = [name for name in by_day[day] if candidates.get((day, name.lower())) or (day, name.lower()) in far]
                if day_far and 2 * len(day_far) >= len(resolved):
                    far_plans.append((plan, day_far))
            areas = self._run([lambda p=plan, f=day_far: self._far_area(run, p, f) for plan, day_far in far_plans], deadline, "far-area")
            for (plan, _), area in zip(far_plans, areas):
                if area is not None:
                    self._make_far_day(run, plan, *area)
            redo = [(plan.day, name) for plan, _ in far_plans if plan.kind != "base" for name in by_day[plan.day]]
            results = self._run([lambda d=day, n=name: self._near(n, hint_of(d), base_of(d)) for day, name in redo], deadline, "place-area")
            for (day, name), result in zip(redo, results):
                candidates[(day, name.lower())] = result
                far.pop((day, name.lower()), None)

        # Choose each place, nearest the stay or the day's other places (N3).
        chosen: dict[tuple, dict] = {}
        names_of = {(day, name.lower()): name for day, name in jobs}
        anchors: dict[int, dict[tuple, dict]] = {}
        for day in sorted({day for day, _ in jobs}):
            keys = [(day, name.lower()) for d, name in jobs if d == day]
            # Where each place on the day probably is: its only match, or the middle of its matches.
            anchors[day] = {key: centre([place["location"] for place in candidates[key]]) for key in keys if candidates.get(key)}
            for key in keys:
                if candidates.get(key):
                    others = [location for other, location in anchors[day].items() if other != key]
                    chosen[key] = self._choose(candidates[key], base_of(day), others)

        # A match far from the rest of its day can be a namesake: near Delhi, "Quwwat-ul-Islam Mosque" matched one in Nangloi,
        # 40 km from the Qutb Minar it stands next to (live, 15 Sep 2026). Google's own answer for the name wins when it's nearer the day.
        outliers = []
        for key, place in chosen.items():
            others = [location for other, location in anchors.get(key[0], {}).items() if other != key]
            if len(others) >= 2 and km_between(place["location"], centre(others)) > tt.OUTLIER_KM:
                outliers.append((key, centre(others)))
        answers = self._run([lambda n=names_of[key]: self.google.search(n) for key, _ in outliers], deadline, "place-outlier")
        for (key, middle), place in zip(outliers, answers):
            base = base_of(key[0])
            if (
                place and place.get("location") and names_match(names_of[key], place.get("name"), (hint_of(key[0]),))
                and (base is None or km_between(place["location"], base.point) <= tt.FAR_KM)
                and km_between(place["location"], middle) < km_between(chosen[key]["location"], middle)
            ):
                chosen[key] = place
        for key, place in chosen.items():
            self._remember(names_of[key], hint_of(key[0]), base_of(key[0]), place)

        skip_days = {plan.day for plan in run.days.values() if plan.kind != "base"} if rewrite_pending else set()
        outcomes: dict[tuple, tuple] = {}
        asks: dict[str, tuple] = {}
        for day, name in jobs:
            key = (day, name.lower())
            if candidates.get(key) is None:
                outcomes[key] = (_entry(name, "not_checked"), None)
                continue
            place = chosen.get(key)
            if place is not None and place.get("business_status") == "CLOSED_TEMPORARILY":
                outcomes[key] = (_entry(name, "temporarily_closed", place), place)
            elif place is not None and place.get("business_status") != "CLOSED_PERMANENTLY":
                outcomes[key] = (_entry(name, "confirmed", place), place)
            elif day in skip_days:
                outcomes[key] = (_entry(name, "not_checked"), None)
            else:
                if place is not None:
                    reason = PERMANENTLY_CLOSED
                elif key in far:
                    plan = run.days.get(day)
                    reason = TOO_FAR if plan is None or plan.kind == "base" else f"more than 50 km from {plan.area}"
                else:
                    reason = NOT_FOUND
                asks.setdefault(name.lower(), (name, reason, day))
                outcomes[key] = None

        ask_list = list(asks.values())
        answers = self._run([lambda n=name, r=reason, d=day: self._replace_one(n, r, d, replace, hint_of(d), base_of(d), deadline) for name, reason, day in ask_list], deadline, "place-replace")
        answered = {name.lower(): (reason, answer) for (name, reason, _), answer in zip(ask_list, answers)}

        entries_by_name: dict[str, dict] = {}
        found: dict = {}
        swaps: list[tuple[str, str]] = []
        for day, name in jobs:
            key = (day, name.lower())
            outcome = outcomes.get(key)
            if outcome is None:
                reason, answer = answered.get(name.lower(), (NOT_FOUND, None))
                if answer:
                    suggestion, other = answer
                    outcome = (_entry(suggestion, "replaced", other, replaces=name, reason=reason), other)
                    found[(day, suggestion.lower())] = other
                    found.setdefault(suggestion.lower(), other)
                    if (name, suggestion) not in swaps:
                        swaps.append((name, suggestion))
                else:
                    outcome = (_entry(name, "unconfirmed", reason=reason), None)
            entry, place = outcome
            if place is not None:
                found[key] = place
                found.setdefault(name.lower(), place)
            entries_by_name.setdefault(name.lower(), entry)

        for old, new in swaps:
            itinerary = replace_place(itinerary, old, new)
        entries = [entries_by_name[name.lower()] for name in names if name.lower() in entries_by_name]
        return itinerary, entries, found

    def _replace_one(self, name, reason, day, replace, hint, base, deadline):
        suggestion = self._ask(replace, name, reason, deadline)
        if not suggestion:
            return None
        candidates = self._near(suggestion, hint, base)
        other = self._choose(candidates, base, [])
        if other is None or other["business_status"] in ("CLOSED_PERMANENTLY", "CLOSED_TEMPORARILY"):
            return None
        self._remember(suggestion, hint, base, other)
        return suggestion, other

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

    # ------------------------------------------------------------------ far areas (TP-07 C1, C3)

    def _far_area(self, run: _Run, plan: DayPlan, places: list[dict]):
        towns = Counter(place.get("town") for place in places if place.get("town"))
        town = towns.most_common(1)[0][0] if towns else None
        group = [place for place in places if place.get("town") == town] or places
        middle = centre([place["location"] for place in group])
        point, name = middle, town or group[0].get("name") or "that area"
        if town:
            spot = self._area(town)
            if spot and km_between(spot, middle) <= tt.FAR_KM:
                point = {"lat": spot["lat"], "lng": spot["lng"]}
        minutes = None
        if self.routes is not None and plan.home is not None:
            try:
                car = self._essentials(run, plan.home.spot(), {"name": name, "point": point})
                minutes = car["minutes"] if car else None
            except RoutesUnavailable as exc:
                log.warning("Travel time failed (%s)", exc)
        return name, point, minutes

    def _make_far_day(self, run: _Run, plan: DayPlan, name: str, point: dict, minutes: Optional[int]) -> None:
        one_stay = bool(run.trip.stops) and run.trip.stay_per_stop is False
        if one_stay or not plan.has_night:
            kind = "day_trip"
        elif minutes is not None:
            kind = "stay_there" if minutes > tt.STAY_THERE_MINUTES else "day_trip"
        else:
            kind = "stay_there" if plan.home is None or km_between(plan.home.point, point) > tt.STAY_THERE_MINUTES else "day_trip"
        plan.kind, plan.area, plan.far_minutes = kind, name, minutes
        if kind == "stay_there":
            stay = Base(f"Your stay in {name}", point["lat"], point["lng"], "area", area=name)
            plan.area_base = stay
            plan.night = stay
            following = run.days.get(plan.day + 1)
            if following is not None:
                following.morning = stay
        else:
            plan.area_base = Base(name, point["lat"], point["lng"], "area", area=name)

    def _rewrite_far_days(self, rewrite: Rewrite, itinerary: str, moves: list[DayPlan], run: _Run) -> Optional[str]:
        described = [{"day": plan.day, "kind": plan.kind, "area": plan.area, "label": _far_label(plan), "date": plan.date.isoformat() if plan.date else None} for plan in sorted(moves, key=lambda plan: plan.day)]
        try:
            return rewrite(itinerary, described, _new_stays(run.days))
        except Exception as exc:  # the AI failing never breaks the itinerary
            log.warning("Far days weren't rewritten (%s)", type(exc).__name__)
            return None

    # ------------------------------------------------------------------ opening hours (TP-05 A)

    def _check_times(self, itinerary, run: _Run, visits, entries, found, replace):
        today = self.today()
        start_date = run.trip.start_date
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
            place = _place_for(found, visit.day, visit.place)
            if place is None:
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
                swap = self._replace_closed(run, visit, day, start, end, replace, reason, today, deadline)
                if swap is None:
                    result.update(status="closed_all_day", label=f"Closed on {weekday}")
                else:
                    new_name, new_place, new_intervals = swap
                    found[(visit.day, new_name.lower())] = new_place
                    found.setdefault(new_name.lower(), new_place)
                    itinerary = rewrite_visit(itinerary, visit, visit.start_min, visit.end_min, new_name)
                    if not any(entry["query"].lower() == new_name.lower() for entry in entries):
                        entries.append(_entry(new_name, "replaced", new_place, replaces=visit.place, reason=reason))
                    result.update(place=new_name, status="replaced", hours=hours_text(new_intervals), label=f"Suggested instead of a place that's {reason}")
            results.append(result)

        mentioned = [name.lower() for name in named_places(itinerary)]
        entries = sorted((entry for entry in entries if entry["query"].lower() in mentioned), key=lambda entry: mentioned.index(entry["query"].lower()))
        seen: set[str] = set()
        unique = []
        for entry in entries:  # a replacement can have the name of a place already in the plan
            if entry["query"].lower() not in seen:
                seen.add(entry["query"].lower())
                unique.append(entry)
        return itinerary, unique, results

    def _replace_closed(self, run: _Run, visit, day, start, end, replace, reason, today, deadline):
        suggestion = self._ask(replace, visit.place, reason, deadline)
        if not suggestion:
            return None
        plan = run.days.get(visit.day)
        base = plan.search_base if plan else None
        hint = plan.area if plan is not None and plan.area_base is not None and plan.area else run.destination
        try:
            other = self._choose(self._near(suggestion, hint, base), base, [])
        except Exception as exc:
            log.warning("A replacement couldn't be checked on Google Maps (%s)", type(exc).__name__)
            return None
        if other is None or other["business_status"] in ("CLOSED_PERMANENTLY", "CLOSED_TEMPORARILY"):
            return None
        intervals = day_intervals(other, day, today)
        if intervals is None or not (is_whole_day(intervals) or fits(intervals, start, end)):
            return None
        return suggestion, other, intervals

    # ------------------------------------------------------------------ the order of visits (TP-07 C2)

    def _essentials(self, run: _Run, a: dict, b: dict) -> Optional[dict]:
        """A car trip without traffic (the cheaper price), measured once per review for each pair of places."""
        key = _pair_key(a, b)
        with run.lock:
            if key in run.pairs:
                return run.pairs[key]
        car = self.routes.drive(a["point"], b["point"], traffic=False)
        with run.lock:
            run.pairs[key] = car
        return car

    def _reorder(self, itinerary: str, visits: list[Visit], run: _Run, found: dict) -> str:
        lines = itinerary.split("\n")
        segments = []
        by_day: dict[int, list[Visit]] = {}
        for visit in visits:
            by_day.setdefault(visit.day, []).append(visit)
        for day, day_visits in by_day.items():
            plan = run.days.get(day)
            if plan is None or plan.morning is None:
                continue  # without the stay, the order with least travel isn't known
            previous = plan.morning.spot()
            current, start = [], None
            for visit in day_visits:
                place = _place_for(found, day, visit.place)
                spot = _visit_spot(visit.place, place)
                line = lines[visit.line]
                if spot is None or tt.is_fixed(line) or tt.is_meal(line, (place or {}).get("types")):
                    if 2 <= len(current) <= tt.MAX_REORDER:
                        segments.append((start, current, spot))
                    current, previous = [], spot
                else:
                    if not current:
                        start = previous
                    current.append((visit, spot))
            if 2 <= len(current) <= tt.MAX_REORDER:
                segments.append((start, current, plan.night.spot() if plan is not None and plan.night is not None else None))
        if not segments:
            return itinerary

        pairs = {}
        for start, items, end in segments:
            points = ([start] if start else []) + [spot for _, spot in items] + ([end] if end else [])
            for index, a in enumerate(points):
                for b in points[index + 1 :]:
                    pairs.setdefault(_pair_key(a, b), (a, b))
        self._run([lambda a=a, b=b: self._essentials(run, a, b) for a, b in pairs.values()], run.deadline, "route-order")

        def minutes(a, b):
            with run.lock:
                car = run.pairs.get(_pair_key(a, b))
            return car["minutes"] if car else None

        new_lines = list(lines)
        for start, items, end in segments:
            def cost(order):
                total, previous = 0, start
                for _, spot in order:
                    if previous is not None:
                        leg = minutes(previous, spot)
                        if leg is None:
                            return None
                        total += leg
                    previous = spot
                if end is not None:
                    leg = minutes(previous, end)
                    if leg is None:
                        return None
                    total += leg
                return total

            original = cost(items)
            if original is None:
                continue
            best_cost, best = original, None
            for order in permutations(items):
                value = cost(order)
                if value is not None and value < best_cost:
                    best_cost, best = value, order
            if best is None or best_cost + tt.REORDER_SAVING_MINUTES > original:
                continue
            for (slot, _), (visit, _) in zip(items, best):
                single = Visit(day=visit.day, start_min=visit.start_min, end_min=visit.end_min, place=visit.place, line=0)
                new_lines[slot.line] = rewrite_visit(lines[visit.line], single, slot.start_min, slot.start_min + (visit.end_min - visit.start_min), visit.place)
        return "\n".join(new_lines)

    # ------------------------------------------------------------------ the timetable (TP-07 A2, B, D, E, F)

    def _build_timetable(self, itinerary, visits, results, run: _Run, found, checked) -> list[dict]:
        lines = itinerary.split("\n")
        by_day: dict[int, list[dict]] = {}
        for index, (visit, result) in enumerate(zip(visits, results)):
            place = _place_for(found, visit.day, result["place"])
            line = lines[visit.line]
            by_day.setdefault(visit.day, []).append({
                "index": index, "visit": visit, "result": result, "place": place,
                "fixed": tt.is_fixed(line), "meal": tt.is_meal(line, (place or {}).get("types")),
            })
        days = sorted(by_day)

        if checked and self.busy is not None and run.trip.start_date is not None:
            ids = []
            for items in by_day.values():
                for item in items:
                    place = item["place"]
                    if place and place.get("id") and tt.wants_busy_hours(place.get("types")) and place["id"] not in ids:
                        ids.append(place["id"])
            weeks = self._run([lambda place_id=place_id: self.busy.week(place_id) for place_id in ids], run.deadline, "busy-hours")
            run.weeks = dict(zip(ids, weeks))

        if checked:
            scheduled = self._run([lambda d=day: self._schedule_day(run, self._day_plan(run, d), by_day[d]) for day in days], run.deadline + GRACE_S, "timetable")
        else:
            scheduled = [None] * len(days)

        timetable = []
        for day, outcome in zip(days, scheduled):
            plan = self._day_plan(run, day)
            if outcome is None:
                status, label = ("not_available", NOT_AVAILABLE) if checked else ("not_checked", "Not checked")
                outcome = {"rows": _unchecked_rows(by_day[day], status, label, estimate=not checked), "kind": _day_kind(plan), "label": _far_label(plan) if plan.kind != "base" else None}
            timetable.append({
                "day": day, "date": plan.date.isoformat() if plan.date else None, "kind": outcome["kind"], "area": plan.area,
                "label": outcome["label"], "stay": plan.night.to_json() if plan.night else None, "rows": outcome["rows"],
            })
        return timetable

    def _day_plan(self, run: _Run, day: int) -> DayPlan:
        plan = run.days.get(day)
        if plan is None:
            last = run.days.get(max(run.days)) if run.days else None
            start = run.trip.start_date
            plan = DayPlan(day, start + timedelta(days=day - 1) if start else None, last.night if last else None, last.night if last else None, last.night if last else None, has_night=False)
        return plan

    def _schedule_day(self, run: _Run, plan: DayPlan, items: list[dict]) -> dict:
        day = plan.date
        offset = next((item["place"]["utc_offset_minutes"] for item in items if item["place"] and item["place"].get("utc_offset_minutes") is not None), 0)
        weekday = day.strftime("%A").lower() if day else None
        morning, night = plan.morning, plan.night
        rows: list[dict] = []
        leave_row = None
        if morning is not None:
            leave_row = {"kind": "checkout" if night is not None and morning != night else "leave", "place": morning.name, "time": None, "label": None}
            rows.append(leave_row)
        current = morning.spot() if morning is not None else None
        current_time: Optional[int] = None
        previous_name = morning.name if morning is not None else None

        for item in items:
            result, place = item["result"], item["place"]
            planned_start, planned_end = _clock_minutes(result["start"]), _clock_minutes(result["end"])
            length = planned_end - planned_start
            dest = _visit_spot(result["place"], place)
            ready, fail = None, None
            if current is not None and dest is not None:
                if current_time is None:
                    leg = self._leg_to_start(run, current, dest, planned_start, day, offset)
                    if leave_row is not None and current["name"] == morning.name and leg.leave is not None:
                        leave_row["time"] = _time(leg.leave)
                else:
                    leg = self._leg_from(run, current, dest, current_time, day, offset)
                rows.extend(leg.rows)
                if leg.ok:
                    ready = leg.arrive + leg.buffer
                fail = leg.fail_label
            elif dest is not None and previous_name is not None:
                rows.append(_travel_row(previous_name, result["place"]))

            start, wait_minutes, busy = planned_start, 0, None
            status, hours, label = result["status"], result["hours"], result["label"]
            if fail:
                status, label = "doesnt_fit", f"Doesn't fit this day: {fail}"
            else:
                if ready is not None and ready > planned_start:
                    if item["fixed"]:
                        status, label = "doesnt_fit", f"Doesn't fit this day: you'd arrive at {_time(ready)}"
                    else:
                        start = tt.round_up(ready)
                window = busy_window(run.weeks.get(place["id"]), weekday) if place and place.get("id") and weekday else None
                if window and not item["fixed"] and status != "doesnt_fit":
                    if item["meal"] and tt.in_window(start, window):
                        earliest = ready if ready is not None else (current_time if current_time is not None else 0)
                        quieter = tt.quieter_start(planned_start, earliest, window)
                        if quieter is None:
                            wait_minutes = tt.BUSY_WAIT_MINUTES
                            slot = tt.first_slot(planned_start, earliest)
                            if slot is not None and slot > start:
                                start = slot
                        else:
                            start = quieter
                        busy = tt.busy_text(window)
                    elif not item["meal"] and start < window[1] and window[0] < start + length:
                        busy = tt.busy_text(window)
            end = start + length + wait_minutes
            if not fail and (start, end) != (planned_start, planned_end) and status != "doesnt_fit":
                status, hours, label = self._recheck(plan, place, result["place"], start, end, status, hours, label)
            if not fail and end > tt.DAY_ENDS and status != "doesnt_fit":
                status, label = "doesnt_fit", "Doesn't fit this day: ends after 22:00"

            rows.append({
                "kind": "visit", "place": result["place"], "start": _time(start), "end": _time(end),
                "planned_start": result["planned_start"], "planned_end": result["planned_end"],
                "status": status, "hours": hours, "label": label, "busy": busy, "wait": wait_minutes, "estimate": False,
                "fixed": item["fixed"], "_index": item["index"], "_pushed": ready is not None and ready > planned_start,
            })
            # A visit not found on the map keeps its time, and the next trip is measured from the last place that was.
            if not fail and dest is not None:
                current = dest
                current_time = end
                previous_name = result["place"]

        back_row = None
        if night is not None and items:
            back_row = {"kind": "checkin" if morning is not None and morning != night else "back", "place": night.name, "time": None, "label": None}
            if current is not None and current_time is not None:
                leg = self._leg_from(run, current, night.spot(), current_time, day, offset)
                rows.extend(leg.rows)
                if leg.ok:
                    back_row["time"] = _time(tt.round_up(leg.arrive + leg.buffer))
            elif previous_name is not None:
                rows.append(_travel_row(previous_name, night.name))
            rows.append(back_row)

        if leave_row is not None and leave_row["time"] is not None and _clock_minutes(leave_row["time"]) < tt.EARLIEST_LEAVE:
            leave_row["label"] = "Doesn't fit this day: leaves before 06:00"

        kind = _day_kind(plan)
        label = None
        if plan.kind == "stay_there":
            label = f"Stay in {plan.area} tonight"
            if morning != night and plan.far_minutes and plan.home is not None:
                label += f": {tt.duration_text(plan.far_minutes)} from {plan.home.area}"
        elif plan.kind == "day_trip":
            label = f"Day trip: {tt.duration_text(plan.far_minutes)} each way" if plan.far_minutes else f"Day trip to {plan.area}"
            if back_row is not None and back_row["time"]:
                label += f", back by {back_row['time']}"
        elif kind == "move":
            minutes = None
            try:
                car = self._essentials(run, morning.spot(), night.spot())
                minutes = car["minutes"] if car else None
            except RoutesUnavailable as exc:
                log.warning("Travel time failed (%s)", exc)
            returning = any(other.night == night for other in run.days.values() if other.day < plan.day)
            label = f"{'Back to' if returning else 'Move to'} {night.area}"
            if minutes:
                label += f": {tt.duration_text(minutes)} from {morning.area}"
        return {"rows": rows, "kind": kind, "label": label}

    def _recheck(self, plan: DayPlan, place: Optional[dict], name: str, start: int, end: int, status, hours, label):
        """B4, B5: opening hours again after re-timing."""
        if plan.date is None or place is None or status == "closed_all_day":
            return status, hours, label
        intervals = day_intervals(place, plan.date, self.today())
        if not intervals or is_whole_day(intervals):
            return status, hours, label
        if fits(intervals, start, end):
            if status == "closed_at_time":
                return "open", hours_text(intervals), OPEN_LABEL
            return status, hours, label
        closes = next((close for opens, close in intervals if opens <= start < close), None)
        if closes is None:
            earlier = [close for _, close in intervals if close <= start]
            closes = earlier[-1] if earlier else None
        if closes is None:
            return "doesnt_fit", hours_text(intervals), f"Doesn't fit this day: {name} opens {clock(intervals[0][0])}"
        return "doesnt_fit", hours_text(intervals), f"Doesn't fit this day: {name} closes {clock(closes)}"

    # ------------------------------------------------------------------ one trip

    def _day_or_tomorrow(self, day: Optional[date]) -> date:
        return day or (self.today() + timedelta(days=1))

    def _utc(self, day: Optional[date], minute: int, offset: int) -> datetime:
        ref = self._day_or_tomorrow(day)
        return datetime(ref.year, ref.month, ref.day, tzinfo=timezone.utc) + timedelta(minutes=minute - offset)

    def _traffic_utc(self, day: Optional[date], minute: int, offset: int) -> Optional[datetime]:
        """When to ask Google for live traffic: only for dated trips still ahead (Google refuses times in the past)."""
        if day is None or day < self.today():
            return None
        moment = self._utc(day, minute, offset)
        if day == self.today() and moment <= datetime.now(timezone.utc) + timedelta(minutes=1):
            return None
        return moment

    def _not_available(self, origin: dict, dest: dict) -> _Leg:
        return _Leg([_travel_row(origin["name"], dest["name"], "not_available", NOT_AVAILABLE)])

    def _leg_from(self, run: _Run, origin: dict, dest: dict, leave: int, day: Optional[date], offset: int, early: Optional[int] = None, boats: bool = True) -> _Leg:
        """A trip leaving at `leave`: by car in traffic, on foot when it's short, and public transport when a ride is soon (B1, B2)."""
        if run.expired():
            return self._not_available(origin, dest)
        traffic_at = self._traffic_utc(day, leave, offset)
        try:
            car = self.routes.drive(origin["point"], dest["point"], leave_utc=traffic_at)
        except RoutesUnavailable as exc:
            log.warning("Travel time failed (%s)", exc)
            return self._not_available(origin, dest)
        if car is None:
            if boats:
                return self._boat_from(run, origin, dest, leave, day, offset)
            return self._not_available(origin, dest)
        walk = transit = None
        try:
            if car["km"] < tt.SHORT_HOP_KM:
                walk = self.routes.walk(origin["point"], dest["point"])
            if early is None:
                transit = self.routes.transit(origin["point"], dest["point"], self._utc(day, leave, offset))
        except RoutesUnavailable as exc:
            log.warning("Travel time failed (%s)", exc)
        walking = walk is not None and walk["minutes"] <= tt.LONGEST_WALK_MINUTES
        minutes = walk["minutes"] if walking else car["minutes"]
        buffer = early if early is not None else tt.buffer_minutes(minutes, dest.get("reviews"))
        row = _travel_row(origin["name"], dest["name"], "ok", None)
        row.update(
            mode="walk" if walking else "car", minutes=minutes, km=car["km"], traffic=not walking and traffic_at is not None, buffer=buffer,
            leave=_time(leave), arrive=_time(leave + minutes), car=car, walk=walk, transit=transit,
            transit_message=None if transit else "No public transport at this time",
        )
        return _Leg([row], ok=True, arrive=leave + minutes, buffer=buffer, leave=leave)

    def _leg_to_start(self, run: _Run, origin: dict, dest: dict, start: int, day: Optional[date], offset: int) -> _Leg:
        """The first trip of the day: leave in time to start the visit (A2), asking for traffic at that hour (B1)."""
        if run.expired():
            return self._not_available(origin, dest)
        try:
            estimate = self._essentials(run, origin, dest)
        except RoutesUnavailable as exc:
            log.warning("Travel time failed (%s)", exc)
            return self._not_available(origin, dest)
        if estimate is None:
            return self._boat_to_start(run, origin, dest, start, day, offset)
        leave = max(tt.leave_for(start, estimate["minutes"], tt.buffer_minutes(estimate["minutes"], dest.get("reviews"))), 0)
        leg = self._leg_from(run, origin, dest, leave, day, offset)
        if leg.ok and len(leg.rows) == 1:
            minutes = leg.arrive - leg.leave
            final = max(tt.leave_for(start, minutes, leg.buffer), 0)
            if final != leg.leave:
                leg.rows[0].update(leave=_time(final), arrive=_time(final + minutes))
                leg.leave, leg.arrive = final, final + minutes
        return leg

    def _boat_from(self, run: _Run, origin: dict, dest: dict, leave: int, day: Optional[date], offset: int) -> _Leg:
        """E2, E3: a crossing in the timetable file, otherwise Google's boats."""
        crossing = find_crossing(self.ferries, origin["point"], dest["point"])
        if crossing is None:
            return self._google_boat(run, origin, dest, leave, day, offset)
        to_jetty = self._leg_from(run, origin, _jetty(crossing.start), leave, day, offset, early=crossing.early, boats=False)
        rows = list(to_jetty.rows)
        if not to_jetty.ok:
            return _Leg(rows)
        departs = crossing.next_boat(to_jetty.arrive + crossing.early, day)
        boat = _boat_row(crossing, departs, day)
        rows.append(boat)
        if departs is None:
            return _Leg(rows, fail_label=boat["label"][0].lower() + boat["label"][1:])
        onward = self._leg_from(run, _jetty(crossing.end), dest, departs + crossing.minutes, day, offset, boats=False)
        rows.extend(onward.rows)
        if not onward.ok:
            return _Leg(rows)
        return _Leg(rows, ok=True, arrive=onward.arrive, buffer=onward.buffer, leave=leave)

    def _boat_to_start(self, run: _Run, origin: dict, dest: dict, start: int, day: Optional[date], offset: int) -> _Leg:
        crossing = find_crossing(self.ferries, origin["point"], dest["point"])
        if crossing is None:
            return self._google_boat(run, origin, dest, max(tt.round_down(start - 120, 30), 0), day, offset)
        try:
            onward = self._essentials(run, _jetty(crossing.end), dest)
            to_jetty = self._essentials(run, origin, _jetty(crossing.start))
        except RoutesUnavailable as exc:
            log.warning("Travel time failed (%s)", exc)
            return self._not_available(origin, dest)
        if onward is None or to_jetty is None:
            return self._not_available(origin, dest)
        latest = start - tt.buffer_minutes(onward["minutes"], dest.get("reviews")) - onward["minutes"] - crossing.minutes
        departs = crossing.last_boat_before(latest, day)
        if departs is None:
            departs = crossing.next_boat(0, day)
        if departs is None:
            return self._boat_from(run, origin, dest, max(start - 180, 0), day, offset)
        leave = max(tt.leave_for(departs - crossing.early, to_jetty["minutes"], 0), 0)
        return self._boat_from(run, origin, dest, leave, day, offset)

    def _google_boat(self, run: _Run, origin: dict, dest: dict, leave: int, day: Optional[date], offset: int) -> _Leg:
        """E1: a boat on Google's public transport route, asked for 30 minutes after setting off; otherwise say times are unknown (E3)."""
        row = _travel_row(origin["name"], dest["name"], "not_available", BOAT_UNKNOWN)
        asked = leave + EARLY_MINUTES
        try:
            ferry = self.routes.ferry(origin["point"], dest["point"], self._utc(day, asked, offset))
        except RoutesUnavailable as exc:
            log.warning("Travel time failed (%s)", exc)
            ferry = None
        if ferry is None:
            return _Leg([row])
        ref = self._day_or_tomorrow(day)
        midnight = datetime(ref.year, ref.month, ref.day, tzinfo=timezone.utc) - timedelta(minutes=offset)
        departs = int((ferry["departs_utc"] - midnight).total_seconds() // 60)
        arrives = departs + ferry["minutes"]
        arrive = arrives + ferry.get("after_minutes", 0)
        minutes = max(arrive - leave, 1)
        buffer = tt.buffer_minutes(minutes, dest.get("reviews"))
        row.update(mode="boat", minutes=minutes, buffer=buffer, leave=_time(leave), arrive=_time(arrive), status="ok", label=None)
        boat = {
            "kind": "boat", "from": ferry.get("from_stop") or origin["name"], "to": ferry.get("to_stop") or dest["name"], "line": ferry["line"],
            "departs": _time(departs), "arrives": _time(arrives), "minutes": ferry["minutes"], "be_at_jetty": _time(departs - EARLY_MINUTES),
            "source": "google", "checked": None, "label": None,
        }
        return _Leg([row, boat], ok=True, arrive=arrive, buffer=buffer, leave=leave)


# ---------------------------------------------------------------------- helpers


def _day_kind(plan: DayPlan) -> str:
    if plan.kind in ("stay_there", "day_trip"):
        return plan.kind
    if plan.morning is not None and plan.night is not None and plan.morning != plan.night:
        return "move"
    return "base"


def _far_label(plan: DayPlan) -> Optional[str]:
    if plan.kind == "stay_there":
        where = f": {tt.duration_text(plan.far_minutes)} from {plan.home.area}" if plan.far_minutes and plan.home is not None else ""
        return f"Stay in {plan.area} tonight{where}"
    if plan.kind == "day_trip":
        return f"Day trip: {tt.duration_text(plan.far_minutes)} each way" if plan.far_minutes else f"Day trip to {plan.area}"
    return None


def _new_stays(days: dict[int, DayPlan]) -> list[dict]:
    """C5: the nights to find stays for in each far area."""
    stays: list[dict] = []
    for plan in sorted(days.values(), key=lambda plan: plan.day):
        if plan.kind != "stay_there" or plan.date is None or not plan.has_night:
            continue
        checkout = (plan.date + timedelta(days=1)).isoformat()
        if stays and stays[-1]["place"] == plan.area and stays[-1]["checkout"] == plan.date.isoformat():
            stays[-1]["checkout"] = checkout
            stays[-1]["nights"] += 1
        else:
            stays.append({"place": plan.area, "checkin": plan.date.isoformat(), "checkout": checkout, "nights": 1})
    return stays


def _unchecked_visit(visit: Visit, start_date: Optional[date]) -> dict:
    day = start_date + timedelta(days=visit.day - 1) if start_date else None
    return {
        "day": visit.day, "date": day.isoformat() if day else None, "start": visit.start, "end": visit.end,
        "planned_start": visit.start, "planned_end": visit.end, "place": visit.place, "status": "not_checked", "hours": None, "label": None,
    }


def _unchecked_rows(items: list[dict], status: str, label: str, estimate: bool) -> list[dict]:
    rows, previous = [], None
    for item in items:
        result = item["result"]
        if previous is not None:
            rows.append(_travel_row(previous, result["place"], status, label))
        rows.append({
            "kind": "visit", "place": result["place"], "start": result["start"], "end": result["end"],
            "planned_start": result["planned_start"], "planned_end": result["planned_end"], "status": result["status"],
            "hours": result["hours"], "label": result["label"], "busy": None, "wait": 0, "estimate": estimate, "fixed": item["fixed"],
            "_index": item["index"],
        })
        previous = result["place"]
    return rows


def _rewrite_times(itinerary: str, visits: list[Visit], timetable: list[dict]) -> str:
    """B3: every time range in the text matches the timetable."""
    for entry in timetable:
        for row in entry["rows"]:
            if row["kind"] != "visit" or row.get("_index") is None or row.get("estimate"):
                continue
            visit = visits[row["_index"]]
            start, end = _clock_minutes(row["start"]), _clock_minutes(row["end"])
            if end <= start:
                continue
            if (start, end) != (visit.start_min, visit.end_min):
                itinerary = rewrite_visit(itinerary, visit, start, end, visit.place)
    return itinerary


def _visits_json(timetable: list[dict]) -> list[dict]:
    """Opening hours per visit, as TP-05 answered them."""
    visits = []
    for entry in timetable:
        for row in entry["rows"]:
            if row["kind"] == "visit":
                visits.append({
                    "day": entry["day"], "date": entry["date"], "start": row["start"], "end": row["end"], "planned_start": row["planned_start"],
                    "planned_end": row["planned_end"], "place": row["place"], "status": row["status"], "hours": row["hours"], "label": row["label"],
                })
    return visits


def _travel_json(timetable: list[dict]) -> list[dict]:
    """Trips between each day's places, as TP-05 answered them."""
    legs = []
    for entry in timetable:
        previous, between = None, []
        for row in entry["rows"]:
            if row["kind"] == "visit":
                if previous is not None:
                    trips = [item for item in between if item["kind"] == "travel"]
                    first = trips[0] if trips else _travel_row(previous["place"], row["place"])
                    ok = bool(trips) and all(item["status"] == "ok" for item in trips)
                    status = "ok" if ok else first["status"]
                    label = first["label"] if not ok else ("Not enough time to get there" if row.get("_pushed") else None)
                    legs.append({
                        "day": entry["day"], "from": previous["place"], "to": row["place"], "leave": previous["end"],
                        "car": first["car"] if len(trips) == 1 else None, "transit": first["transit"] if len(trips) == 1 else None,
                        "transit_message": first["transit_message"] if len(trips) == 1 else None, "walk": first["walk"] if len(trips) == 1 else None,
                        "status": status, "label": label,
                    })
                previous, between = row, []
            elif previous is not None:
                between.append(row)
    return legs


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
            label = f"Time changed: opens {clock(opens)}" if candidate > start else f"Time changed: closes {clock(closes)}"
            best = (shift, candidate, label)
    return (best[1], best[2]) if best else None


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
    busy = build_busy_hours()
    if not key:
        return PlaceChecker(busy=busy)
    return PlaceChecker(google=GooglePlaces(api_key=key), routes=GoogleRoutes(api_key=key), busy=busy, ferries=load_routes())


_checker: Optional[PlaceChecker] = None
_checker_lock = threading.Lock()


def get_place_checker() -> PlaceChecker:
    """One shared checker, rebuilt if the Google or SerpApi key is added or removed."""
    global _checker
    with _checker_lock:
        has_key = bool(os.environ.get(KEY_ENV, "").strip())
        has_busy = bool(os.environ.get("SERPAPI_API_KEY", "").strip())
        if _checker is None or (_checker.google is not None) != has_key or (_checker.busy is not None) != has_busy:
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


def real_timings_status() -> dict:
    """For /api/health: whether days are timed from the stay (TP-07 K1). Never the key itself."""
    return _key_status("real_timings", "Real timings (Google Routes)")
