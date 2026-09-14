"""Helpers that turn each source's answer into the shared Offer shape."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Iterable, Optional

from fli.models.airline import AIRLINE_NAMES

from .models import Journey, Layover, Offer, Segment

_ISO_MINUTE = re.compile(r"^(\d{4}-\d{2}-\d{2})[T ](\d{2}):(\d{2})")
_FORMAT = "%Y-%m-%dT%H:%M"


def airline_name(code: str) -> str:
    code = (code or "").strip().upper()
    return AIRLINE_NAMES.get(code) or AIRLINE_NAMES.get(f"_{code}") or code


def flight_number(carrier: str, number) -> str:
    """"EY", "219" -> "EY 219"; also accepts numbers that already start with the carrier."""
    carrier = (carrier or "").strip().upper()
    text = str(number or "").strip().upper().replace(" ", "")
    if carrier and text.startswith(carrier) and len(text) > len(carrier):
        text = text[len(carrier):]
    return f"{carrier} {text}".strip()


def iso_minute(value) -> str:
    """Local date and time as YYYY-MM-DDTHH:MM; any timezone suffix is dropped."""
    if isinstance(value, datetime):
        return value.strftime(_FORMAT)
    match = _ISO_MINUTE.match(str(value).strip())
    if not match:
        raise ValueError(f"unreadable time: {value!r}")
    return f"{match.group(1)}T{match.group(2)}:{match.group(3)}"


def minutes_between(earlier: str, later: str) -> int:
    delta = datetime.strptime(later, _FORMAT) - datetime.strptime(earlier, _FORMAT)
    return int(delta.total_seconds() // 60)


def parse_price(value) -> Optional[int]:
    """"INR 25994" / 25994.0 / "25,994" -> 25994; empty or zero -> None."""
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    else:
        digits = str(value).split()[-1].replace(",", "")
        try:
            number = float(digits)
        except ValueError:
            return None
    return int(round(number)) if number > 0 else None


def make_journey(
    segments: list[Segment],
    total_minutes: Optional[int] = None,
    layovers: Optional[list[Layover]] = None,
) -> Journey:
    if not segments:
        raise ValueError("a journey needs at least one flight")
    if layovers is None:
        layovers = [
            Layover(airport=first.to, duration_min=max(minutes_between(first.arrival, second.departure), 0))
            for first, second in zip(segments, segments[1:])
        ]
    duration = total_minutes or (
        sum(s.duration_min for s in segments) + sum(stop.duration_min for stop in layovers)
    )
    return Journey(
        from_=segments[0].from_,
        to=segments[-1].to,
        departure=segments[0].departure,
        arrival=segments[-1].arrival,
        duration_min=duration,
        stops=len(segments) - 1,
        segments=segments,
        layovers=layovers,
    )


def airline_codes(journeys: Iterable[Optional[Journey]]) -> list[str]:
    codes: list[str] = []
    for journey in journeys:
        for segment in journey.segments if journey else []:
            if segment.airline_code not in codes:
                codes.append(segment.airline_code)
    return codes


def make_offer(
    source: str,
    price: int,
    currency: str,
    outbound: Journey,
    back: Optional[Journey],
    booking_url: str,
    booking_type: str,
    return_match: Optional[str] = None,
) -> Offer:
    journeys = [outbound] + ([back] if back else [])
    names: list[str] = []
    for journey in journeys:
        for segment in journey.segments:
            if segment.airline not in names:
                names.append(segment.airline)
    flights = "|".join(s.flight_number for j in journeys for s in j.segments)
    return Offer(
        id=f"{source}:{flights}:{outbound.departure}",
        price=price,
        currency=currency,
        airlines=names,
        duration_min=sum(j.duration_min for j in journeys),
        stops=max(j.stops for j in journeys),
        booking_url=booking_url,
        booking_type=booking_type,
        outbound=outbound,
        return_=back,
        return_match=return_match if back else None,
    )
