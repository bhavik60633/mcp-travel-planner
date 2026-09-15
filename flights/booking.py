"""Booking links.

Google Flights reads its search from the `tfs` parameter: a URL-safe base64
protocol-buffer message. Field numbers follow the public descriptions used by
fast-flights and gf-search (FlightData 2=date, 5=max stops, 6=airlines,
13/14=airports; Info 3=flight data, 8=passenger, 9=seat, 19=trip type).
"""

from __future__ import annotations

import base64
from typing import Iterable, Optional
from urllib.parse import quote

from .models import Journey, SearchQuery

GOOGLE_FLIGHTS_SEARCH = "https://www.google.com/travel/flights/search"
AVIASALES = "https://www.aviasales.com"

_SEAT = {"economy": 1, "premium_economy": 2, "business": 3, "first": 4}
# gf-search sends this "all results" flag so smaller airports get results too.
_ALL_RESULTS = b"\x08" + b"\xff" * 9 + b"\x01"


def _varint(value: int) -> bytes:
    out = bytearray()
    while True:
        byte = value & 0x7F
        value >>= 7
        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _field_varint(field: int, value: int) -> bytes:
    return _varint(field << 3) + _varint(value)


def _field_bytes(field: int, data: bytes) -> bytes:
    return _varint((field << 3) | 2) + _varint(len(data)) + data


def _airport(code: str) -> bytes:
    return _field_varint(1, 1) + _field_bytes(2, code.encode())


def _flight_data(day: str, origin: str, destination: str, airlines: Iterable[str], max_stops: Optional[int]) -> bytes:
    data = _field_bytes(2, day.encode())
    if max_stops is not None:
        data += _field_varint(5, max_stops)
    for code in airlines:
        data += _field_bytes(6, code.encode())
    return data + _field_bytes(13, _airport(origin)) + _field_bytes(14, _airport(destination))


def google_flights_url(query: SearchQuery, airlines: Iterable[str] = ()) -> str:
    """Google Flights for the query's route, dates, travellers and cabin, filtered to `airlines`."""
    airlines = list(airlines)
    info = _field_varint(1, 28) + _field_varint(2, 2)
    info += _field_bytes(3, _flight_data(query.depart.isoformat(), query.origin, query.destination, airlines, query.max_stops))
    if query.return_date:
        info += _field_bytes(
            3, _flight_data(query.return_date.isoformat(), query.destination, query.origin, airlines, query.max_stops)
        )
    info += _field_varint(8, 1) * query.adults
    info += _field_varint(9, _SEAT.get(query.cabin, 1))
    info += _field_varint(14, 1)
    info += _field_bytes(16, _ALL_RESULTS)
    info += _field_varint(19, 1 if query.return_date else 2)
    tfs = base64.urlsafe_b64encode(info).rstrip(b"=").decode("ascii")
    return f"{GOOGLE_FLIGHTS_SEARCH}?tfs={tfs}&hl=en&curr={quote(query.currency)}"


def exact_booking_url(outbound: Journey, back: Optional[Journey], currency: str) -> Optional[str]:
    """Google Flights' booking page with exactly these flights selected (built offline by fli), or None."""
    try:
        from datetime import datetime

        from fli.models import Airline, Airport, FlightLeg, FlightResult
        from fli.search import SearchFlights

        def result(journey: Journey) -> FlightResult:
            legs = [
                FlightLeg(
                    airline=Airline["_" + s.airline_code] if s.airline_code[:1].isdigit() else Airline[s.airline_code],
                    flight_number=s.flight_number.split()[-1],
                    departure_airport=Airport[s.from_],
                    arrival_airport=Airport[s.to],
                    departure_datetime=datetime.strptime(s.departure, "%Y-%m-%dT%H:%M"),
                    arrival_datetime=datetime.strptime(s.arrival, "%Y-%m-%dT%H:%M"),
                    duration=max(s.duration_min, 1),
                )
                for s in journey.segments
            ]
            return FlightResult(legs=legs, price=None, currency=currency, duration=max(journey.duration_min, 1), stops=journey.stops)

        trip = (result(outbound), result(back)) if back else result(outbound)
        url = SearchFlights().build_flight_booking_url(trip, currency=currency)
    except Exception:
        return None
    return url if url.startswith("https://www.google.com/travel/flights/booking") else None


def aviasales_url(link: str, marker: Optional[str]) -> str:
    """Aviasales link from a Travelpayouts ticket, with the partner marker for commission."""
    url = AVIASALES + (link if link.startswith("/") else f"/{link}")
    if marker:
        url += ("&" if "?" in url else "?") + f"marker={quote(marker)}"
    return url
