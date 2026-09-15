"""Travelpayouts (Aviasales) Data API: recently seen prices with partner booking links.

The token travels only in the X-Access-Token header. It is never put in a URL,
a log line, an error message or a response.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Optional

import httpx
from pydantic import SecretStr

from ..booking import aviasales_url
from ..models import DatesQuery, Journey, Offer, SearchQuery, Segment
from ..normalize import airline_name, flight_number, iso_minute, make_offer, parse_price
from .base import SourceUnavailable

API = "https://api.travelpayouts.com"


class _TravelpayoutsClient:
    uses_google = False

    def __init__(self, token: str, marker: Optional[str] = None, http_client: Optional[httpx.Client] = None, timeout_s: float = 10.0):
        self._token = SecretStr(token)
        self._marker = marker
        self._http = http_client
        self._timeout_s = timeout_s

    def __repr__(self) -> str:
        return f"{type(self).__name__}(token=***)"

    def _get(self, path: str, params: dict) -> dict:
        if self._http is None:
            self._http = httpx.Client(timeout=self._timeout_s)
        try:
            response = self._http.get(
                API + path,
                params={k: v for k, v in params.items() if v is not None},
                headers={"X-Access-Token": self._token.get_secret_value(), "Accept": "application/json"},
            )
        except httpx.HTTPError as exc:
            raise SourceUnavailable(f"Travelpayouts request failed ({type(exc).__name__})") from None
        if response.status_code != 200:
            raise SourceUnavailable(f"Travelpayouts answered HTTP {response.status_code}")
        try:
            data = response.json()
        except ValueError:
            raise SourceUnavailable("Travelpayouts sent an unreadable answer") from None
        if not isinstance(data, dict) or data.get("success") is False:
            raise SourceUnavailable("Travelpayouts reported an error")
        return data


def _journey(frm: str, to: str, airline: str, number, departure_at: str, minutes: Optional[int], stops: int) -> Journey:
    departure = iso_minute(departure_at)
    duration = int(minutes or 0)
    arrival = (datetime.strptime(departure, "%Y-%m-%dT%H:%M") + timedelta(minutes=duration)).strftime("%Y-%m-%dT%H:%M")
    segment = Segment(
        airline_code=airline,
        airline=airline_name(airline),
        flight_number=flight_number(airline, number or ""),
        from_=frm,
        to=to,
        departure=departure,
        arrival=arrival,
        duration_min=duration,
    )
    # This API gives no connection details, so the stop count comes without layover airports.
    return Journey(
        from_=frm, to=to, departure=departure, arrival=arrival, duration_min=duration,
        stops=int(stops or 0), segments=[segment], layovers=[],
    )


class TravelpayoutsSource(_TravelpayoutsClient):
    name = "travelpayouts"
    complete = False

    def search(self, query: SearchQuery) -> list[Offer]:
        if query.cabin != "economy":
            return []  # these saved prices are economy only
        data = self._get(
            "/aviasales/v3/prices_for_dates",
            {
                "origin": query.origin,
                "destination": query.destination,
                "departure_at": query.depart.isoformat(),
                "return_at": query.return_date.isoformat() if query.return_date else None,
                "one_way": "false" if query.return_date else "true",
                "direct": "true" if query.max_stops == 0 else "false",
                "currency": query.currency.lower(),
                "sorting": "price",
                "limit": 30,
            },
        )
        offers = []
        for ticket in data.get("data") or []:
            try:
                price = parse_price(ticket.get("price"))
                if price is None or not str(ticket.get("departure_at", "")).startswith(query.depart.isoformat()):
                    continue
                airline = str(ticket.get("airline") or "")
                frm = ticket.get("origin_airport") or ticket.get("origin") or query.origin
                to = ticket.get("destination_airport") or ticket.get("destination") or query.destination
                outbound = _journey(frm, to, airline, ticket.get("flight_number"), ticket["departure_at"],
                                    ticket.get("duration_to") or ticket.get("duration"), ticket.get("transfers", 0))
                if query.return_date and not ticket.get("return_at"):
                    continue
                if query.max_stops is not None and outbound.stops > query.max_stops:
                    continue
                url = aviasales_url(str(ticket.get("link") or ""), self._marker)
                # Round trips list the outbound flight with the round-trip price (TP-03 D4).
                offers.append(make_offer(self.name, price * query.adults, query.currency, outbound, None, url, "partner"))
            except (KeyError, TypeError, ValueError):
                continue
        return offers


class TravelpayoutsDateSource(_TravelpayoutsClient):
    name = "travelpayouts"

    def search_dates(self, query: DatesQuery) -> list[dict]:
        if query.cabin != "economy":
            return []
        months = sorted({(query.start + timedelta(days=n)).strftime("%Y-%m") for n in range((query.end - query.start).days + 1)})
        days = []
        for month in months:
            data = self._get(
                "/aviasales/v3/grouped_prices",
                {
                    "origin": query.origin,
                    "destination": query.destination,
                    "departure_at": month,
                    "group_by": "departure_at",
                    "currency": query.currency.lower(),
                },
            )
            grouped = data.get("data") or {}
            for day, ticket in grouped.items() if isinstance(grouped, dict) else []:
                try:
                    when = date.fromisoformat(str(day)[:10])
                except ValueError:
                    continue
                price = parse_price((ticket or {}).get("price"))
                if price is not None and query.start <= when <= query.end:
                    days.append({"date": when.isoformat(), "price": price * query.adults})
        return days
