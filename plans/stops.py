"""Several places on one trip, and a stay at each or one stay for all (TP-06 H2, H5–H7)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional, Sequence

from .text import and_list, long_date

MAX_PLACES = 6
MAX_DISTANCE_KM = 300
MAX_TRIP_DAYS = 14

# "Canggu | 3", "- **Ubud** | 2 nights", "1. Nusa Penida | 1"
_AI_LINE = re.compile(r"^[ \t]*(?:[-*•]|\d{1,2}[.)])?[ \t]*(?P<place>[^|\n]{2,80}?)[ \t]*\|[ \t]*(?P<nights>\d{1,2})\b[^\n]*$", re.MULTILINE)


@dataclass(frozen=True)
class Stop:
    place: str
    nights: int
    checkin: date
    checkout: date

    def to_json(self) -> dict:
        return {"place": self.place, "nights": self.nights, "checkin": self.checkin.isoformat(), "checkout": self.checkout.isoformat()}


def nights_text(nights: int) -> str:
    return f"{nights} night" if nights == 1 else f"{nights} nights"


def max_places(nights: int) -> int:
    """At most one place per 2 nights, and at most 6 places."""
    return max(1, min(MAX_PLACES, nights // 2))


def with_dates(places: Sequence[tuple[str, int]], start: date) -> list[Stop]:
    stops, day = [], start
    for place, nights in places:
        stops.append(Stop(place, nights, day, day + timedelta(days=nights)))
        day += timedelta(days=nights)
    return stops


def read_ai_stops(reply: str) -> list[tuple[str, int]]:
    places = []
    for match in _AI_LINE.finditer(reply or ""):
        place = " ".join(match.group("place").replace("**", "").strip(" *_\"'").split())
        nights = int(match.group("nights"))
        if place and nights >= 1:
            places.append((place, nights))
    return places


def fit_nights(places: list[tuple[str, int]], nights: int) -> Optional[list[tuple[str, int]]]:
    """Keep the places allowed for these nights; the last place takes the nights left, so they add up."""
    kept = places[: max_places(nights)]
    if not kept:
        return None
    last_place, last_nights = kept[-1]
    last_nights += nights - sum(n for _, n in kept)
    if last_nights < 1:
        return None
    return [*kept[:-1], (last_place, last_nights)]


def stops_problem(places: Sequence, nights: Optional[int]) -> Optional[str]:
    """Why a trip's places can't be planned (H5), or None. `places` have .place and .nights."""
    if nights is None:
        return "Several places need a start date and a return date."
    if not places:
        return "Choose at least one place."
    if len(places) > MAX_PLACES:
        return f"A trip can have at most {MAX_PLACES} places."
    if any(not " ".join((stop.place or "").split()) for stop in places):
        return "Every place needs a name."
    if any(stop.nights < 1 for stop in places):
        return "Each place needs at least 1 night."
    if sum(stop.nights for stop in places) != nights:
        return f"The nights at each place must add up to the trip's {nights_text(nights)}."
    return None


def base_stop(stops: Sequence[Stop]) -> Stop:
    """Where one stay for several places goes: the place with the most nights, the first of equals (D13)."""
    return max(stops, key=lambda stop: stop.nights)


def places_section(stops: Sequence[Stop], stay_per_stop: bool, start: date) -> str:
    """The places and dates for the AI (H6, H7)."""
    if not stay_per_stop:
        base = base_stop(stops)
        others = [stop.place for stop in stops if stop is not base]
        return f"\nStay in one place for the whole trip: {base.place}. Plan {and_list(others)} as day trips from {base.place}, with travel times.\n"

    lines = ["", "Places and dates on this trip:"]
    for stop in stops:
        lines.append(f"- {stop.place}, {nights_text(stop.nights)}: check in {long_date(stop.checkin)}, check out {long_date(stop.checkout)}")
    moves = [(before, after, (after.checkin - start).days + 1) for before, after in zip(stops, stops[1:])]
    for before, after, day in moves:
        lines.append(f"- Day {day} ({long_date(after.checkin)}): move from {before.place} to {after.place}")
    if moves:
        _, first, day = moves[0]
        lines.append(
            "On the day you move to the next place, plan the check-out, how to get to the next place with the travel time, and the check-in, "
            f'and name the new place in that day\'s heading, for example "## Day {day}: Move to {first.place}".'
        )
    return "\n".join(lines) + "\n"


def stops_prompt(destination: str, stops_start: date, stops_end: date, travelers: int, trip_type: str, preferences: str) -> str:
    """Asks the AI which places to stay in (H2)."""
    nights = (stops_end - stops_start).days
    most = max_places(nights)
    return (
        f"Suggest where to stay on a trip to {destination}: {nights_text(nights)}, from {long_date(stops_start)} to {long_date(stops_end)}, "
        f"for {travelers} travellers, {trip_type} style. Preferences: {preferences or 'none given'}.\n"
        f"Choose at most {most} {'place' if most == 1 else 'places'} in or near {destination} that visitors usually combine, "
        f"in a sensible travel order. The nights must add up to {nights}.\n"
        'Reply with one line per place in the form "Place | nights", for example "Canggu | 3", and write nothing else. '
        "This is not an itinerary."
    )
