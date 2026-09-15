"""Opening hours from Google Places (TP-05 A2–A7).

Times are minutes after midnight in the place's own time. Google numbers days 0–6 from Sunday. A place open
24 hours has one period that opens on day 0 at 00:00 with no close. `currentOpeningHours` covers the next 7 days
(special days such as holidays included), and its periods carry dates; `regularOpeningHours` is the usual week.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Optional

DAY_NAMES = ["Sunday", "Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday"]
WEEK_ORDER = [1, 2, 3, 4, 5, 6, 0]  # Monday first, for labels
WHOLE_DAY = [(0, 1440)]

Intervals = list[tuple[int, int]]


def google_day(day: date) -> int:
    return (day.weekday() + 1) % 7


def clock(minutes: int) -> str:
    """600 -> "10:00 AM"."""
    hour, minute = divmod(minutes % 1440, 60)
    return f"{hour % 12 or 12}:{minute:02d} {'AM' if hour < 12 else 'PM'}"


def _point(point: dict) -> int:
    return int(point.get("hour", 0)) * 60 + int(point.get("minute", 0))


def _merge(intervals: Intervals) -> Intervals:
    merged: Intervals = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1]:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


def weekly_intervals(hours: dict, day: int) -> Intervals:
    """When the place is open on Google weekday `day`, from its usual weekly hours."""
    found: Intervals = []
    for period in hours.get("periods") or []:
        opens, closes = period.get("open"), period.get("close")
        if not opens:
            continue
        if not closes:
            return list(WHOLE_DAY)
        open_day, close_day = int(opens.get("day", 0)), int(closes.get("day", 0))
        start, end = _point(opens), _point(closes)
        span = (close_day - open_day) % 7
        if span == 0 and end <= start:
            span = 7
        if open_day == day:
            found.append((start, end if span == 0 else 1440))
        for extra in range(1, span + 1):
            if (open_day + extra) % 7 == day:
                found.append((0, end if extra == span else 1440))
    return _merge(found)


def dated_intervals(hours: dict, day: date) -> Optional[Intervals]:
    """When the place is open on `day`, from hours whose periods carry dates; None when they don't include `day`."""
    found: Intervals = []
    listed = False
    for period in hours.get("periods") or []:
        opens, closes = period.get("open") or {}, period.get("close")
        stamp = opens.get("date")
        if not stamp:
            continue
        open_date = date(stamp["year"], stamp["month"], stamp["day"])
        close_stamp = (closes or {}).get("date")
        close_date = date(close_stamp["year"], close_stamp["month"], close_stamp["day"]) if close_stamp else open_date + timedelta(days=1)
        close_minute = _point(closes) if closes else 0
        if open_date == day or close_date == day:
            listed = True
        start = _point(opens) if open_date == day else (0 if open_date < day else None)
        end = close_minute if close_date == day else (1440 if close_date > day else None)
        if start is not None and end is not None and end > start:
            found.append((start, end))
    return _merge(found) if listed else None


def day_intervals(place: dict, day: date, today: date) -> Optional[Intervals]:
    """When the place is open on `day`: that exact date's hours within the next 7 days, otherwise the usual week."""
    current, regular = place.get("current_hours"), place.get("regular_hours")
    if current and 0 <= (day - today).days < 7:
        dated = dated_intervals(current, day)
        if dated is not None:
            return dated
    if regular and regular.get("periods"):
        return weekly_intervals(regular, google_day(day))
    return None


def is_whole_day(intervals: Intervals) -> bool:
    return intervals == WHOLE_DAY


def fits(intervals: Intervals, start: int, end: int) -> bool:
    return any(opens <= start and end <= closes for opens, closes in intervals)


def hours_text(intervals: Intervals) -> Optional[str]:
    if not intervals:
        return None
    if is_whole_day(intervals):
        return "Open 24 hours"
    return "Open " + ", ".join(f"{clock(opens)} – {clock(closes)}" for opens, closes in intervals)


def join_days(days: list[int]) -> str:
    names = [DAY_NAMES[day] for day in days]
    return names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
