"""HTTP route: /api/stays (TP-03 E1, E2; TP-05 D1, D2)."""

from __future__ import annotations

import re
import threading
from dataclasses import replace
from datetime import date
from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from .airbnb import StaysUnavailable
from .budget import nightly_stay_budget
from .service import StaysQuery, StaysService

router = APIRouter()
UNAVAILABLE_MESSAGE = "Airbnb stays are temporarily unavailable. Try again in a few minutes."

_service: StaysService | None = None
_lock = threading.Lock()


def get_stays_service() -> StaysService:
    global _service
    with _lock:
        if _service is None:
            _service = StaysService()
        return _service


class _Invalid(Exception):
    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


def _date(value: str) -> date:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value or ""):
        raise _Invalid("Dates must look like 2026-10-20.")
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise _Invalid("Dates must look like 2026-10-20.") from None


def _whole_number(value: Optional[str], message: str) -> Optional[int]:
    if value is None or not value.strip():
        return None
    if not re.fullmatch(r"\d{1,9}", value.strip()) or int(value) <= 0:
        raise _Invalid(message)
    return int(value)


def parse_stays_query(params, today: date) -> StaysQuery:
    place = " ".join((params.get("place") or "").split())
    if not place:
        raise _Invalid("Where do you want to stay?")
    checkin = _date((params.get("checkin") or "").strip())
    checkout = _date((params.get("checkout") or "").strip())
    if checkin < today:
        raise _Invalid("Check-in can't be in the past.")
    if checkout <= checkin:
        raise _Invalid("Check-out must be after check-in.")
    adults_text = (params.get("adults") or "1").strip()
    if not re.fullmatch(r"\d{1,2}", adults_text) or not 1 <= int(adults_text) <= 16:
        raise _Invalid("Adults must be between 1 and 16.")
    return StaysQuery(place=place, checkin=checkin, checkout=checkout, adults=int(adults_text))


def parse_budget(params, query: StaysQuery, service: StaysService) -> Optional[dict]:
    """The most per night for this search: the traveller's own limit, or the trip budget's share (TP-05 D1, D2)."""
    max_per_night = _whole_number(params.get("max_per_night"), "The most per night must be a whole number above 0.")
    trip_budget = _whole_number(params.get("trip_budget"), "The trip budget must be a whole number above 0.")
    # A place on a trip with several places shares the whole trip's nightly limit (TP-06 D12, H9).
    trip_nights = _whole_number(params.get("trip_nights"), "Trip nights must be a whole number above 0.")
    budget = None
    if trip_budget:
        budget = nightly_stay_budget(
            trip_budget,
            (params.get("budget_currency") or "INR").strip(),
            (params.get("trip_type") or "Standard").strip(),
            trip_nights or query.nights,
            rate_to_inr=service.rate_to_inr,
        )
    if max_per_night:
        budget = {**budget, "max_per_night": max_per_night} if budget else {"max_per_night": max_per_night, "currency": "INR"}
    return budget


@router.get("/api/stays")
def stays(request: Request, service: StaysService = Depends(get_stays_service)):
    try:
        query = parse_stays_query(request.query_params, service.today())
        budget = parse_budget(request.query_params, query, service)
    except _Invalid as exc:
        return JSONResponse(status_code=400, content={"error": "invalid_request", "message": exc.message})
    if budget:
        query = replace(query, max_per_night=budget["max_per_night"])
    try:
        outcome = service.search(query)
    except StaysUnavailable as exc:
        return JSONResponse(status_code=503, content={"error": "source_unavailable", "message": UNAVAILABLE_MESSAGE, "reason": exc.reason})
    body = {
        "query": query.to_json(),
        "source": "airbnb",
        "cached": outcome.cached,
        "count": len(outcome.stays),
        "stays": outcome.stays,
        "search_url": outcome.search_url,
    }
    if budget:
        body["budget"] = budget
    return body
