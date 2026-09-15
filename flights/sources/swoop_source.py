"""swoop: Google Flights' internal search (github.com/saraswatayu/swoop). A spare full-list source."""

from __future__ import annotations

from typing import Callable, Optional

from ..booking import google_flights_url
from ..models import Journey, Offer, SearchQuery, Segment
from ..normalize import airline_codes, airline_name, flight_number, make_journey, make_offer, parse_price
from .base import SourceUnavailable

_CABIN = {"economy": "economy", "premium_economy": "premium-economy", "business": "business", "first": "first"}


def _local(day: tuple, time: tuple) -> str:
    year, month, dom = day
    hour, minute = time
    return f"{year:04d}-{month:02d}-{dom:02d}T{hour:02d}:{minute:02d}"


def swoop_journey(itinerary) -> Journey:
    segments = [
        Segment(
            airline_code=s.airline,
            airline=s.airline_name or airline_name(s.airline),
            flight_number=flight_number(s.airline, s.flight_number),
            from_=s.departure_airport_code,
            to=s.arrival_airport_code,
            departure=_local(s.departure_date, s.departure_time),
            arrival=_local(s.arrival_date, s.arrival_time),
            duration_min=int(s.travel_time),
            aircraft=s.aircraft or None,
        )
        for s in itinerary.segments
    ]
    return make_journey(segments, total_minutes=int(itinerary.travel_time) or None)


class SwoopSource:
    name = "swoop"
    complete = True
    uses_google = True

    def __init__(self, search_fn: Optional[Callable] = None):
        self._search_fn = search_fn

    def __repr__(self) -> str:
        return "SwoopSource()"

    def search(self, query: SearchQuery) -> list[Offer]:
        try:
            from swoop import SORT_CHEAPEST, Passengers

            search_fn = self._search_fn
            if search_fn is None:
                from swoop import search as search_fn
        except ImportError as exc:
            raise SourceUnavailable("swoop is not installed") from exc

        try:
            result = search_fn(
                query.origin,
                query.destination,
                query.depart.isoformat(),
                return_date=query.return_date.isoformat() if query.return_date else None,
                cabin=_CABIN[query.cabin],
                passengers=Passengers(adults=query.adults),
                max_stops=query.max_stops,
                sort=SORT_CHEAPEST,
            )
        except Exception as exc:
            raise SourceUnavailable(f"swoop search failed ({type(exc).__name__})") from exc

        offers = []
        for option in getattr(result, "results", None) or []:
            try:
                price = parse_price(option.price)
                if price is None or (option.currency and option.currency.upper() != query.currency):
                    continue
                legs = [leg for leg in option.legs if leg.itinerary is not None and leg.itinerary.segments]
                if not legs:
                    continue
                outbound = swoop_journey(legs[0].itinerary)
                # Round trips list the outbound flight with its total; the return is chosen next (TP-03 D4).
                url = google_flights_url(query, airline_codes([outbound]))
                offers.append(make_offer(self.name, price, query.currency, outbound, None, url, "route"))
            except (AttributeError, TypeError, ValueError):
                continue
        return offers
