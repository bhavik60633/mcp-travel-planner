"""HTTP route: /api/trip-info (TP-04 C1–C5)."""

from __future__ import annotations

import logging
import re
import threading
from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from .service import PARTS, TripInfoService, not_available
from .suggest import UNAVAILABLE_MESSAGE, PlaceSuggester

log = logging.getLogger(__name__)
router = APIRouter()

_service: TripInfoService | None = None
_suggester: PlaceSuggester | None = None
_service_lock = threading.Lock()


def get_trip_info_service() -> TripInfoService:
    global _service
    with _service_lock:
        if _service is None:
            _service = TripInfoService()
        return _service


def get_place_suggester() -> PlaceSuggester:
    global _suggester
    with _service_lock:
        if _suggester is None:
            _suggester = PlaceSuggester()
        return _suggester


@router.get("/api/places/suggest")
def suggest_places(q: str = "", suggester: PlaceSuggester = Depends(get_place_suggester)):
    """Places for the trip form's To box (TP-06 B1, B2). Never an error: an empty list says why."""
    try:
        return suggester.suggest(q[:100])
    except Exception as exc:
        log.warning("Place suggestions failed (%s)", type(exc).__name__)
        return {"query": " ".join(q.split()), "places": [], "available": False, "message": UNAVAILABLE_MESSAGE, "cached": False}


def _invalid(message: str) -> JSONResponse:
    return JSONResponse(status_code=400, content={"error": "invalid_request", "message": message})


@router.get("/api/trip-info")
def trip_info(request: Request, service: TripInfoService = Depends(get_trip_info_service)):
    params = request.query_params
    place = (params.get("place") or "").strip()
    if not place:
        return _invalid("Where are you going?")
    start_text = (params.get("start") or "").strip()
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", start_text):
        return _invalid("Dates must look like 2026-10-20.")
    try:
        start = date.fromisoformat(start_text)
    except ValueError:
        return _invalid("Dates must look like 2026-10-20.")
    days_text = (params.get("days") or "").strip()
    if not days_text.isdigit() or not 1 <= int(days_text) <= 30:
        return _invalid("Days must be between 1 and 30.")
    currency = (params.get("currency") or "").strip()
    if not re.fullmatch(r"[A-Za-z]{3}", currency):
        return _invalid("Currency must be a 3-letter code like INR.")

    try:
        return service.info(place, start, int(days_text), currency.upper())
    except Exception as exc:  # trip essentials never break the page
        log.warning("Trip information failed (%s)", type(exc).__name__)
        return {"place": None, **{part: not_available() for part in PARTS}, "cached": False}
