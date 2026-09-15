"""fli: Google Flights' internal search (github.com/punitarani/fli). Full flight lists and exact booking pages."""

from __future__ import annotations

import logging
from typing import Optional

from ..booking import google_flights_url
from ..models import DatesQuery, Journey, Layover, Offer, SearchQuery, Segment
from ..normalize import airline_codes, airline_name, flight_number, iso_minute, make_journey, make_offer, parse_price
from .base import SourceUnavailable

log = logging.getLogger(__name__)

_SEAT = {"economy": "ECONOMY", "premium_economy": "PREMIUM_ECONOMY", "business": "BUSINESS", "first": "FIRST"}
_STOPS = {None: "ANY", 0: "NON_STOP", 1: "ONE_STOP_OR_FEWER", 2: "TWO_OR_FEWER_STOPS"}
# Ask Google in English, for India, whatever the currency (TP-03 D1), so fares don't depend on where the server runs.
LANGUAGE = "en"
COUNTRY = "IN"


def _code(member) -> str:
    return getattr(member, "name", str(member)).lstrip("_")


def fli_journey(result) -> Journey:
    segments = []
    for leg in result.legs:
        code = _code(leg.airline)
        segments.append(
            Segment(
                airline_code=code,
                airline=getattr(leg.airline, "value", None) or airline_name(code),
                flight_number=flight_number(code, leg.flight_number),
                from_=_code(leg.departure_airport),
                to=_code(leg.arrival_airport),
                departure=iso_minute(leg.departure_datetime),
                arrival=iso_minute(leg.arrival_datetime),
                duration_min=int(leg.duration),
                aircraft=getattr(leg, "aircraft", None) or None,
            )
        )
    layovers = None
    if result.layovers and len(result.layovers) == len(segments) - 1:
        layovers = [Layover(airport=_code(stop.airport), duration_min=int(stop.duration)) for stop in result.layovers]
    return make_journey(segments, total_minutes=int(result.duration) if result.duration else None, layovers=layovers)


class FliSource:
    name = "fli"
    complete = True
    uses_google = True

    def __init__(self, client=None):
        self._client = client

    def __repr__(self) -> str:
        return "FliSource()"

    def _new_client(self):
        if self._client is not None:
            return self._client
        try:
            from fli.search import SearchFlights
        except ImportError as exc:
            raise SourceUnavailable("fli is not installed") from exc
        return SearchFlights()

    @staticmethod
    def _filters(query: SearchQuery):
        from fli.core import build_flight_segments, parse_sort_by, resolve_airport
        from fli.models import FlightSearchFilters, MaxStops, PassengerInfo, SeatType

        segments, trip_type = build_flight_segments(
            origin=[resolve_airport(query.origin)],
            destination=[resolve_airport(query.destination)],
            departure_date=query.depart.isoformat(),
            return_date=query.return_date.isoformat() if query.return_date else None,
        )
        return FlightSearchFilters(
            trip_type=trip_type,
            passenger_info=PassengerInfo(adults=query.adults),
            flight_segments=segments,
            stops=MaxStops[_STOPS[query.max_stops]],
            seat_type=SeatType[_SEAT[query.cabin]],
            sort_by=parse_sort_by("CHEAPEST"),
            show_all_results=True,
        )

    def search(self, query: SearchQuery) -> list[Offer]:
        try:
            filters = self._filters(query)
        except Exception as exc:
            raise SourceUnavailable(f"fli could not prepare the search ({type(exc).__name__})") from exc
        client = self._new_client()
        try:
            results = client.search(filters, currency=query.currency, language=LANGUAGE, country=COUNTRY)
        except Exception as exc:
            raise SourceUnavailable(f"fli search failed ({type(exc).__name__})") from exc

        offers = []
        for item in results or []:
            try:
                offer = self._offer(item, query, client)
            except Exception as exc:  # one unreadable result shouldn't lose the rest
                log.debug("fli: skipped a result (%s)", type(exc).__name__)
                continue
            if offer is not None:
                offers.append(offer)
        return offers

    def _offer(self, item, query: SearchQuery, client) -> Optional[Offer]:
        pair = item if isinstance(item, tuple) else (item,)
        outbound_result = pair[0]
        return_result = pair[1] if len(pair) > 1 else None
        price = parse_price(outbound_result.price)  # Google puts the round-trip total on the outbound leg
        currency = (outbound_result.currency or query.currency).upper()
        if price is None or currency != query.currency:
            return None
        outbound = fli_journey(outbound_result)
        if query.return_date:
            # Round trips list each outbound flight with Google's total; the exact return is chosen next (TP-03 D4).
            return make_offer(self.name, price, query.currency, outbound, None, google_flights_url(query, airline_codes([outbound])), "route")

        try:
            url = client.build_flight_booking_url(item, currency=query.currency, language=LANGUAGE, country=COUNTRY)
        except Exception:
            url = None
        if url and url.startswith("https://www.google.com/travel/flights"):
            booking_type = "exact"
        else:
            url, booking_type = google_flights_url(query, airline_codes([outbound])), "route"
        return make_offer(self.name, price, query.currency, outbound, None, url, booking_type)


class FliDateSource:
    name = "fli"
    uses_google = True

    def __init__(self, client=None):
        self._client = client

    def __repr__(self) -> str:
        return "FliDateSource()"

    def search_dates(self, query: DatesQuery) -> list[dict]:
        try:
            from fli.core import build_date_search_segments, resolve_airport
            from fli.models import DateSearchFilters, MaxStops, PassengerInfo, SeatType

            round_trip = query.trip_days is not None
            segments, trip_type = build_date_search_segments(
                origin=[resolve_airport(query.origin)],
                destination=[resolve_airport(query.destination)],
                start_date=query.start.isoformat(),
                trip_duration=query.trip_days,
                is_round_trip=round_trip,
            )
            filters = DateSearchFilters(
                trip_type=trip_type,
                passenger_info=PassengerInfo(adults=query.adults),
                flight_segments=segments,
                stops=MaxStops.ANY,
                seat_type=SeatType[_SEAT[query.cabin]],
                from_date=query.start.isoformat(),
                to_date=query.end.isoformat(),
                duration=query.trip_days if round_trip else None,
            )
        except Exception as exc:
            raise SourceUnavailable(f"fli could not prepare the date search ({type(exc).__name__})") from exc

        client = self._client
        if client is None:
            try:
                from fli.search import SearchDates
            except ImportError as exc:
                raise SourceUnavailable("fli is not installed") from exc
            client = SearchDates()
        try:
            results = client.search(filters, currency=query.currency, language=LANGUAGE, country=COUNTRY)
        except Exception as exc:
            raise SourceUnavailable(f"fli date search failed ({type(exc).__name__})") from exc

        days = []
        for result in results or []:
            price = parse_price(getattr(result, "price", None))
            dates = getattr(result, "date", None)
            if price is None or not dates:
                continue
            first = dates[0]
            day = first.date().isoformat() if hasattr(first, "date") else str(first)[:10]
            days.append({"date": day, "price": price})
        return days
