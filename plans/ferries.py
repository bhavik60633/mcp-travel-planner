"""Boat crossings Google doesn't have times for, from a checked timetable file (TP-07 E2–E4).

A trip uses a crossing when it starts near one jetty and ends near the other. Boats leave every `every_minutes`
from the first to the last boat of that direction. Travellers are asked to be at the jetty 30 minutes early
(or the operator's own check-in time), and these boats are labelled "Check today's times with the operator".
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Optional

from places.geo import km_between

FERRIES_FILE = Path(__file__).with_name("ferries.json")
EARLY_MINUTES = 30
CHECK_LABEL = "Check today's times with the operator"


def load_routes(path: Path = FERRIES_FILE) -> list[dict]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _minutes(text: str) -> int:
    hour, minute = text.split(":")
    return int(hour) * 60 + int(minute)


@dataclass(frozen=True)
class Crossing:
    route: dict
    outbound: bool

    @property
    def start(self) -> dict:
        return self.route["from"] if self.outbound else self.route["to"]

    @property
    def end(self) -> dict:
        return self.route["to"] if self.outbound else self.route["from"]

    @property
    def first(self) -> int:
        return _minutes(self.route["first"] if self.outbound else self.route.get("return_first", self.route["first"]))

    @property
    def last(self) -> int:
        return _minutes(self.route["last"] if self.outbound else self.route.get("return_last", self.route["last"]))

    @property
    def minutes(self) -> int:
        return int(self.route["crossing_minutes"])

    @property
    def early(self) -> int:
        return int(self.route.get("report_minutes", EARLY_MINUTES))

    @property
    def source(self) -> str:
        return self.route["source"] if self.outbound else self.route.get("return_source", self.route["source"])

    def runs_on(self, day: Optional[date]) -> bool:
        return day is None or day.strftime("%A") not in (self.route.get("closed_days") or [])

    def departures(self) -> list[int]:
        every = max(int(self.route["every_minutes"]), 1)
        return list(range(self.first, self.last + 1, every))

    def next_boat(self, earliest: int, day: Optional[date]) -> Optional[int]:
        """The first boat leaving at `earliest` or later that day."""
        if not self.runs_on(day):
            return None
        return next((departure for departure in self.departures() if departure >= earliest), None)

    def last_boat_before(self, latest: int, day: Optional[date]) -> Optional[int]:
        """The last boat leaving at `latest` or earlier that day."""
        if not self.runs_on(day):
            return None
        earlier = [departure for departure in self.departures() if departure <= latest]
        return earlier[-1] if earlier else None


def find_crossing(routes: list[dict], origin: dict, destination: dict) -> Optional[Crossing]:
    """The crossing whose jetties are near the trip's start and end ({"lat", "lng"} each), either way round."""
    best = None
    for route in routes or []:
        for outbound in (True, False):
            crossing = Crossing(route, outbound)
            start, end = crossing.start, crossing.end
            to_start, to_end = km_between(origin, start), km_between(destination, end)
            if to_start > start["area_km"] or to_end > end["area_km"]:
                continue
            # Both ends on the same side of the water isn't a crossing.
            if km_between(origin, end) < to_start or km_between(destination, start) < to_end:
                continue
            score = to_start / start["area_km"] + to_end / end["area_km"]
            if best is None or score < best[0]:
                best = (score, crossing)
    return best[1] if best else None
