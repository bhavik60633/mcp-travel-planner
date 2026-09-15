"""The rules each day's timetable follows (TP-07 A2, B2–B4, C1, C2, D1, F2).

Times are minutes after midnight in the destination's own time.
"""

from __future__ import annotations

import math
import re
from typing import Optional

FAR_KM = 50  # D2: every place on a day is within 50 km of that day's base
OUTLIER_KM = 12  # a match this far from the rest of its day is checked again (N3)
STAY_THERE_MINUTES = 90  # D13: a farther drive means a stay there
SHORT_HOP_KM = 1.5  # B2: walk short trips...
LONGEST_WALK_MINUTES = 10  # ...when the walk takes 10 minutes or less
BIG_SIGHT_REVIEWS = 10_000  # D3: 15 extra minutes at big sights
LONG_TRIP_MINUTES = 60  # leaving for a trip longer than an hour is shown on the half hour
DAY_ENDS = 22 * 60  # B4
EARLIEST_LEAVE = 6 * 60
REORDER_SAVING_MINUTES = 15  # C2: the AI's order is kept unless another saves at least 15 minutes
MAX_REORDER = 6
BUSY_SHIFT_MINUTES = 45  # F2
BUSY_STEP_MINUTES = 15
BUSY_WAIT_MINUTES = 20

MEAL_TYPES = {
    "restaurant", "cafe", "coffee_shop", "bar", "pub", "bakery", "food", "food_court", "meal_takeaway", "meal_delivery",
    "ice_cream_shop", "tea_house", "dessert_shop", "brunch_restaurant", "breakfast_restaurant", "fast_food_restaurant",
}
# Busy hours aren't looked up for these: nobody queues for a beach.
NO_BUSY_TYPES = {"natural_feature", "beach", "lodging", "locality", "political", "sublocality", "neighborhood", "hiking_area", "national_park", "state_park"}

_MEAL_WORDS = re.compile(r"\b(breakfast|brunch|lunch|dinner|supper|meal|drinks|high tea)\b", re.IGNORECASE)
_FIXED = re.compile(r"\(\s*fixed\s+time\s*\)", re.IGNORECASE)
_BEFORE_BOLD = re.compile(r"^(.*?)\*\*")


def half_up(value: float) -> int:
    return int(math.floor(value + 0.5))


def round_up(minutes: int, step: int = 5) -> int:
    return -(-minutes // step) * step


def round_down(minutes: int, step: int = 5) -> int:
    return (minutes // step) * step


def hhmm(minutes: Optional[int]) -> Optional[str]:
    if minutes is None:
        return None
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def duration_text(minutes: int) -> str:
    """270 -> "4 h 30 min"."""
    hours, rest = divmod(max(int(minutes), 0), 60)
    if not hours:
        return f"{rest} min"
    return f"{hours} h {rest} min" if rest else f"{hours} h"


def buffer_minutes(trip_minutes: int, reviews: Optional[int] = None) -> int:
    """D3: 15% of the trip, at least 10 minutes, plus 15 at a big sight."""
    extra = 15 if (reviews or 0) > BIG_SIGHT_REVIEWS else 0
    return max(10, half_up(0.15 * trip_minutes)) + extra


def leave_for(start: int, trip_minutes: int, buffer: int) -> int:
    """When to set off to start a visit on time, rounded down to 5 minutes (30 for trips over an hour)."""
    step = 30 if trip_minutes > LONG_TRIP_MINUTES else 5
    return round_down(start - trip_minutes - buffer, step)


def is_fixed(line: str) -> bool:
    return bool(_FIXED.search(line or ""))


def is_meal(line: str, types: Optional[list] = None) -> bool:
    lead = _BEFORE_BOLD.match(line or "")
    if lead and _MEAL_WORDS.search(lead.group(1)):
        return True
    return any(kind in MEAL_TYPES or kind.endswith("_restaurant") for kind in (types or []))


def wants_busy_hours(types: Optional[list]) -> bool:
    return not any(kind in NO_BUSY_TYPES for kind in (types or []))


def in_window(minute: int, window: tuple[int, int]) -> bool:
    return window[0] <= minute < window[1]


def quieter_start(planned: int, earliest: int, window: tuple[int, int]) -> Optional[int]:
    """F2: the start closest to the planned one, within 45 minutes and at least `earliest`, that isn't in the busy hours."""
    candidates = [
        planned + step
        for step in range(-BUSY_SHIFT_MINUTES, BUSY_SHIFT_MINUTES + 1, BUSY_STEP_MINUTES)
        if planned + step >= earliest and not in_window(planned + step, window)
    ]
    if not candidates:
        return None
    return min(candidates, key=lambda start: (abs(start - planned), start))


def first_slot(planned: int, earliest: int) -> Optional[int]:
    """F2: when every nearby time is busy, the first 15-minute step from the planned start you can make."""
    return next((planned + step for step in range(-BUSY_SHIFT_MINUTES, BUSY_SHIFT_MINUTES + 1, BUSY_STEP_MINUTES) if planned + step >= earliest), None)


def busy_text(window: tuple[int, int]) -> str:
    return f"Usually busy {hhmm(window[0])}–{hhmm(window[1])}"
