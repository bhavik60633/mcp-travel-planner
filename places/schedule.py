"""The visits an itinerary plans (TP-05 A1).

The AI writes every visit on its own line as a time range, a colon and the place in bold:
`09:00–11:00: **Hawa Mahal** — what to see there`. Yori reads each day's visits from those lines, and
rewrites a visit's time or place in the same line when a check changes it.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .extract import clean, is_place

_DAY_HEADING = re.compile(r"^[^\w\n]{0,8}Day\s*:?\s*(\d{1,2})\b", re.IGNORECASE)
_CLOCK = r"(\d{1,2})[:.](\d{2})\s*(?:([ap])\.?\s?m\b\.?)?"
_VISIT = re.compile(
    # A few words may come before the place: "12:30–13:30: Lunch at **LMB (Laxmi Misthan Bhandar)**".
    # The time range may be in bold too: "**09:00–11:00**: **Amber Fort** — …" (seen on Render, 15 Sep 2026).
    r"^\s*(?:[-*•]\s*)?(?:\*\*)?(?P<range>" + _CLOCK + r"\s*[–—-]\s*" + _CLOCK + r")(?:\*\*)?\s*:?\s*[^*\n]{0,40}?\*\*(?P<place>[^*\n]{2,80}?)\*\*",
    re.IGNORECASE,
)


def _minutes(hour: str, minute: str, half: str | None) -> int:
    h, m = int(hour), int(minute)
    if half:
        h = h % 12 + (12 if half.lower() == "p" else 0)
    return h * 60 + m


def hhmm(minutes: int) -> str:
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


@dataclass(frozen=True)
class Visit:
    day: int
    start_min: int
    end_min: int
    place: str
    line: int

    @property
    def start(self) -> str:
        return hhmm(self.start_min)

    @property
    def end(self) -> str:
        return hhmm(self.end_min)


def read_visits(itinerary: str) -> list[Visit]:
    """Each visit under a "Day N" heading, in order."""
    visits: list[Visit] = []
    day = None
    for index, line in enumerate((itinerary or "").split("\n")):
        heading = _DAY_HEADING.match(line)
        if heading:
            day = int(heading.group(1))
            continue
        match = _VISIT.match(line)
        if day is None or not match or not is_place(match.group("place")):
            continue
        g = match.groups()
        start = _minutes(g[1], g[2], g[3])
        end = _minutes(g[4], g[5], g[6])
        if end <= start:
            continue
        visits.append(Visit(day=day, start_min=start, end_min=end, place=clean(match.group("place")), line=index))
    return visits


def rewrite_visit(itinerary: str, visit: Visit, start_min: int, end_min: int, place: str) -> str:
    """The itinerary with this visit's line showing a new time and/or place."""
    lines = itinerary.split("\n")
    line = lines[visit.line]
    match = _VISIT.match(line)
    if not match:
        return itinerary
    if (start_min, end_min) != (visit.start_min, visit.end_min):
        line = line[: match.start("range")] + f"{hhmm(start_min)}–{hhmm(end_min)}" + line[match.end("range") :]
        match = _VISIT.match(line)
    if place != visit.place:
        line = line[: match.start("place")] + place + line[match.end("place") :]
    lines[visit.line] = line
    return "\n".join(lines)
