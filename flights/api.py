"""HTTP routes: /api/flights, /api/flights/returns, /api/flights/dates, /api/airports, /api/health."""

from __future__ import annotations

import os
import threading
from datetime import timedelta

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse

from .airports import search_airports
from .ordering import SORTS, order_offers
from .service import UNAVAILABLE_MESSAGE, FlightService, FlightsUnavailable, OutboundNotFound
from .sources import build_date_sources, build_sources
from .validation import InvalidRequest, parse_dates_query, parse_flight_query
from places.service import place_checks_status, real_timings_status, travel_times_status
from plans.busy import busy_hours_status
from tripinfo.service import services_status

router = APIRouter()

# Features that need a key, for /api/health (TP-03 D1). Only whether each key is set is shown.
FEATURES = (
    ("ai_itineraries", "AI itineraries", "OPENAI_API_KEY"),
    ("nearby_day_prices", "Prices for nearby days", "AVIASALES_API_TOKEN"),
    ("photos", "Destination photos", "UNSPLASH_ACCESS_KEY"),
)

_service: FlightService | None = None
_service_lock = threading.Lock()


def get_flight_service() -> FlightService:
    """One shared service, built from environment settings the first time it's needed."""
    global _service
    with _service_lock:
        if _service is None:
            _service = FlightService(sources=build_sources(os.environ), date_sources=build_date_sources(os.environ))
        return _service


def _error(status: int, error: str, message: str, **extra) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": error, "message": message, **extra})


def _sort(params) -> str:
    value = (params.get("sort") or "best").strip().lower()
    if value not in SORTS:
        raise InvalidRequest("Sort must be one of best, cheapest, fastest, earliest.")
    return value


@router.get("/api/flights")
def search_flights(request: Request, service: FlightService = Depends(get_flight_service)):
    try:
        query = parse_flight_query(request.query_params, service.today())
        sort = _sort(request.query_params)
    except InvalidRequest as exc:
        return _error(400, "invalid_request", exc.message)
    try:
        outcome = service.search(query)
    except FlightsUnavailable as exc:
        return _error(503, "source_unavailable", UNAVAILABLE_MESSAGE, attempts=exc.attempts)
    return {
        "query": query.to_json(),
        "sort": sort,
        "source": outcome.source,
        "cached": outcome.cached,
        "fetched_at": outcome.fetched_at,
        "count": len(outcome.offers),
        "offers": [offer.to_json() for offer in order_offers(outcome.offers, sort)],
        "attempts": outcome.attempts,
    }


@router.get("/api/flights/returns")
def return_flights(request: Request, service: FlightService = Depends(get_flight_service)):
    try:
        query = parse_flight_query(request.query_params, service.today())
        sort = _sort(request.query_params)
        if query.return_date is None:
            raise InvalidRequest("Choose a return date to see return flights.")
        outbound_id = (request.query_params.get("outbound") or "").strip()
        if not outbound_id:
            raise InvalidRequest("Choose an outbound flight first.")
    except InvalidRequest as exc:
        return _error(400, "invalid_request", exc.message)
    try:
        outcome = service.returns(query, outbound_id)
    except OutboundNotFound:
        return _error(404, "not_found", "That outbound flight is no longer available. Search again.")
    except FlightsUnavailable as exc:
        return _error(503, "source_unavailable", UNAVAILABLE_MESSAGE, attempts=exc.attempts)
    return {
        "query": query.to_json(),
        "sort": sort,
        "source": outcome.source,
        "cached": outcome.cached,
        "fetched_at": outcome.fetched_at,
        "outbound": outcome.outbound.to_json(),
        "count": len(outcome.offers),
        "offers": [offer.to_json() for offer in order_offers(outcome.offers, sort)],
        "attempts": outcome.attempts,
    }


@router.get("/api/flights/dates")
def cheapest_days(request: Request, service: FlightService = Depends(get_flight_service)):
    try:
        query = parse_dates_query(request.query_params, service.today())
    except InvalidRequest as exc:
        return _error(400, "invalid_request", exc.message)
    try:
        outcome = service.cheapest_days(query)
    except FlightsUnavailable as exc:
        return _error(503, "source_unavailable", UNAVAILABLE_MESSAGE, attempts=exc.attempts)
    priced = {day["date"] for day in outcome.days}
    every_day = [(query.start + timedelta(days=n)).isoformat() for n in range((query.end - query.start).days + 1)]
    return {
        "query": query.to_json(),
        "source": outcome.source,
        "cached": outcome.cached,
        "fetched_at": outcome.fetched_at,
        "currency": query.currency,
        "count": len(outcome.days),
        "days": outcome.days,
        "missing": [day for day in every_day if day not in priced],
        "attempts": outcome.attempts,
    }


@router.get("/api/airports")
def airports(q: str = ""):
    return {"airports": search_airports(q)}


@router.get("/api/health")
def health(service: FlightService = Depends(get_flight_service)):
    return {
        "status": "ok",
        "sources": [source.name for source in service.sources],
        "date_sources": [source.name for source in service.date_sources],
        "travelpayouts_configured": any(source.name == "travelpayouts" for source in service.sources),
        "features": [
            {"feature": feature, "label": label, "key": key, "set": bool((os.environ.get(key) or "").strip())}
            for feature, label, key in FEATURES
        ],
        # Information services behind trip essentials and place checks (TP-04 B5, C10).
        "services": [*services_status(), place_checks_status(), travel_times_status(), real_timings_status(), busy_hours_status()],
    }
