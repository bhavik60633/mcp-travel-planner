"""Google Flights' results page, read with gf-search's page reader (github.com/NYCU-Chung/google-flights-search).

Since TP-03 the page is requested by `flights.google_page` in English, for India, in the chosen
currency. Round trips come in two steps, as on Google Flights: outbound flights with the round-trip
total, then the exact return flights for the outbound flight chosen.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from ..booking import exact_booking_url, google_flights_url
from ..models import Journey, Offer, SearchQuery, Segment
from ..normalize import airline_codes, airline_name, flight_number, iso_minute, make_journey, make_offer, parse_price
from .base import SourceUnavailable

log = logging.getLogger(__name__)

_TRAVEL_CLASS = {"economy": "economy", "premium_economy": "premium-economy", "business": "business", "first": "first"}


def _journey(item: dict) -> Optional[Journey]:
    try:
        segments = []
        for raw in item.get("segments") or []:
            code = str(raw["flight_no"])[:2].upper()
            segments.append(
                Segment(
                    airline_code=code,
                    airline=airline_name(code),
                    flight_number=flight_number(code, str(raw["flight_no"])[2:]),
                    from_=raw["from"],
                    to=raw["to"],
                    departure=iso_minute(raw["departure"]),
                    arrival=iso_minute(raw["arrival"]),
                    duration_min=int(raw["duration_min"]),
                    aircraft=raw.get("plane") or None,
                )
            )
        return make_journey(segments) if segments else None
    except (KeyError, TypeError, ValueError):
        return None


class GfSearchSource:
    name = "gf-search"
    complete = False  # Google's results page lists the flights it shows, not every fare
    uses_google = True

    def __init__(self, search_fn: Optional[Callable[..., list]] = None, max_results: int = 100):
        self._search_fn = search_fn
        self.max_results = max_results

    def __repr__(self) -> str:
        return "GfSearchSource()"

    def _fetch(self, query: SearchQuery, depart: str, return_date: Optional[str], selected_segments: Optional[list[dict]] = None) -> list:
        search_fn = self._search_fn
        if search_fn is None:
            from ..google_page import GooglePage

            search_fn = self._search_fn = GooglePage().search
        kwargs = dict(
            origin=query.origin,
            destination=query.destination,
            departure_date=depart,
            return_date=return_date,
            adults=query.adults,
            travel_class=_TRAVEL_CLASS[query.cabin],
            max_results=self.max_results,
            currency=query.currency,
            max_stops=query.max_stops,
        )
        if selected_segments is not None:
            kwargs["selected_segments"] = selected_segments
        try:
            raw = search_fn(**kwargs)
        except Exception as exc:
            raise SourceUnavailable(f"gf-search failed ({type(exc).__name__})") from exc
        return [item for item in raw or [] if isinstance(item, dict)]

    def search(self, query: SearchQuery) -> list[Offer]:
        """One-way flights, or round-trip outbound flights priced with Google's round-trip total."""
        return_date = query.return_date.isoformat() if query.return_date else None
        offers = []
        for item in self._fetch(query, query.depart.isoformat(), return_date):
            price, journey = parse_price(item.get("price")), _journey(item)
            if price is None or journey is None:
                continue
            url = google_flights_url(query, airline_codes([journey]))
            offers.append(make_offer(self.name, price, query.currency, journey, None, url, "route"))
        return offers

    def search_returns(self, query: SearchQuery, outbound: Offer) -> list[Offer]:
        """Google's return flights for the chosen outbound flight, each with the exact round-trip total."""
        if query.return_date is None:
            return []
        chosen = [
            {"from": s.from_, "to": s.to, "departure": s.departure, "flight_no": s.flight_number.replace(" ", "")}
            for s in outbound.outbound.segments
        ]
        raw = self._fetch(query, query.depart.isoformat(), query.return_date.isoformat(), selected_segments=chosen)
        offers = []
        for item in raw:
            price, back = parse_price(item.get("price")), _journey(item)
            if price is None or back is None or back.from_ != query.destination:
                continue
            url = exact_booking_url(outbound.outbound, back, query.currency)
            booking_type = "exact" if url else "route"
            url = url or google_flights_url(query, airline_codes([outbound.outbound, back]))
            offers.append(make_offer(self.name, price, query.currency, outbound.outbound, back, url, booking_type, "exact"))
        return offers
