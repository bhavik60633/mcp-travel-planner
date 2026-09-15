"""Turns query-string values into SearchQuery / DatesQuery, with plain error messages."""

from __future__ import annotations

import re
from datetime import date
from typing import Mapping, Optional

from fli.models.airport import AIRPORT_NAMES

from .models import CABINS, CURRENCIES, DatesQuery, SearchQuery

MAX_DATE_RANGE_DAYS = 62

_CODE = re.compile(r"^[A-Za-z]{3}$")
_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_STOPS = {"any": None, "0": 0, "1": 1, "2": 2}


class InvalidRequest(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _text(params: Mapping[str, str], name: str) -> str:
    return (params.get(name) or "").strip()


def _code(value: str, label: str) -> str:
    if not _CODE.match(value):
        raise InvalidRequest(f"{label} must be a 3-letter airport code, like DEL.")
    code = value.upper()
    if code not in AIRPORT_NAMES:
        raise InvalidRequest(f"Unknown airport code: {code}.")
    return code


def _date(value: str) -> date:
    if not _DATE.match(value):
        raise InvalidRequest("Dates must look like 2026-10-20.")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise InvalidRequest("Dates must look like 2026-10-20.") from None


def _route(params: Mapping[str, str]) -> tuple[str, str]:
    origin = _code(_text(params, "from"), "From")
    destination = _code(_text(params, "to"), "To")
    if origin == destination:
        raise InvalidRequest("From and To must be different airports.")
    return origin, destination


def _travellers(params: Mapping[str, str]) -> tuple[int, str, str]:
    adults_text = _text(params, "adults") or "1"
    if not re.fullmatch(r"\d{1,2}", adults_text) or not 1 <= int(adults_text) <= 9:
        raise InvalidRequest("Adults must be between 1 and 9.")
    cabin = (_text(params, "cabin") or "economy").lower()
    if cabin not in CABINS:
        raise InvalidRequest("Cabin must be one of economy, premium_economy, business, first.")
    currency = (_text(params, "currency") or "INR").upper()
    if currency not in CURRENCIES:
        raise InvalidRequest("Currency must be one of INR, USD, EUR, GBP.")
    return int(adults_text), cabin, currency


def parse_flight_query(params: Mapping[str, str], today: date) -> SearchQuery:
    if not (_text(params, "from") and _text(params, "to") and _text(params, "depart")):
        raise InvalidRequest("From, To and departure date are required.")
    origin, destination = _route(params)

    depart = _date(_text(params, "depart"))
    if depart < today:
        raise InvalidRequest("Departure date can't be in the past.")
    return_text = _text(params, "return")
    return_date: Optional[date] = _date(return_text) if return_text else None
    if return_date and return_date < depart:
        raise InvalidRequest("Return date can't be before the departure date.")

    adults, cabin, currency = _travellers(params)
    stops_text = (_text(params, "stops") or "any").lower()
    if stops_text not in _STOPS:
        raise InvalidRequest("Stops must be one of any, 0, 1, 2.")

    return SearchQuery(
        origin=origin,
        destination=destination,
        depart=depart,
        return_date=return_date,
        adults=adults,
        cabin=cabin,
        currency=currency,
        max_stops=_STOPS[stops_text],
    )


def parse_dates_query(params: Mapping[str, str], today: date) -> DatesQuery:
    if not all(_text(params, name) for name in ("from", "to", "start", "end")):
        raise InvalidRequest("From, To, start and end dates are required.")
    origin, destination = _route(params)

    start = _date(_text(params, "start"))
    end = _date(_text(params, "end"))
    if start < today:
        raise InvalidRequest("Start date can't be in the past.")
    if end < start:
        raise InvalidRequest("End date can't be before the start date.")
    if (end - start).days + 1 > MAX_DATE_RANGE_DAYS:
        raise InvalidRequest(f"Date range can't be longer than {MAX_DATE_RANGE_DAYS} days.")

    trip_text = _text(params, "trip_days")
    trip_days: Optional[int] = None
    if trip_text:
        if not re.fullmatch(r"\d{1,2}", trip_text) or not 1 <= int(trip_text) <= 30:
            raise InvalidRequest("Trip length must be between 1 and 30 days.")
        trip_days = int(trip_text)

    adults, cabin, currency = _travellers(params)
    return DatesQuery(
        origin=origin,
        destination=destination,
        start=start,
        end=end,
        trip_days=trip_days,
        adults=adults,
        cabin=cabin,
        currency=currency,
    )
