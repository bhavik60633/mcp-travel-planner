"""Itinerary text rules shared by new and changed plans (TP-06 C1, D1, E3)."""

from __future__ import annotations

import re
from datetime import date, timedelta

_TIME_RANGE_DASH = re.compile(r"(\d)[ \t]*—[ \t]*(\d)")
_EM_DASH = re.compile(r"[ \t]*—[ \t]*")


def without_em_dashes(text: str) -> str:
    """Em dashes read as AI-written (E3). A time range keeps an en dash (09:00–11:00); any other em dash becomes " - "."""
    return _EM_DASH.sub(" - ", _TIME_RANGE_DASH.sub(r"\1–\2", text or ""))


def long_date(day: date) -> str:
    """"Monday 19 October 2026" """
    return f"{day:%A} {day.day} {day:%B %Y}"


def day_dates(start: date, days: int) -> list[str]:
    """"Day 1 is Monday 19 October 2026", one per trip day (C1)."""
    return [f"Day {number} is {long_date(start + timedelta(days=number - 1))}" for number in range(1, days + 1)]


def nearby_rule(destination: str, days: int) -> str:
    """Nearby islands, towns and sights (D1)."""
    if days >= 3:
        return (
            f"Spend at least one day or half day on a nearby island, town or sight that visitors usually combine with {destination}, "
            "and say how to get there and how long it takes. Name it in that day's heading."
        )
    return f'End with a short "Nearby, if you have more time" list of places near {destination} that are worth a trip.'


def and_list(items: list[str]) -> str:
    """"Canggu", "Canggu and Ubud", "Seminyak, Canggu and Ubud" """
    return items[0] if len(items) == 1 else f"{', '.join(items[:-1])} and {items[-1]}"
