"""Request and response shapes for the flights API."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

CABINS = ("economy", "premium_economy", "business", "first")
CURRENCIES = ("INR", "USD", "EUR", "GBP")


class _Model(BaseModel):
    model_config = ConfigDict(populate_by_name=True)


class Segment(_Model):
    airline_code: str
    airline: str
    flight_number: str
    from_: str = Field(alias="from")
    to: str
    departure: str  # local time, YYYY-MM-DDTHH:MM
    arrival: str  # local time, YYYY-MM-DDTHH:MM
    duration_min: int
    aircraft: Optional[str] = None


class Layover(_Model):
    airport: str
    duration_min: int


class Journey(_Model):
    from_: str = Field(alias="from")
    to: str
    departure: str
    arrival: str
    duration_min: int
    stops: int
    segments: list[Segment]
    layovers: list[Layover]


class Offer(_Model):
    id: str
    price: int  # total for all adults, in `currency`
    currency: str
    airlines: list[str]
    duration_min: int
    stops: int
    booking_url: str
    booking_type: Literal["exact", "route", "partner"]
    outbound: Journey
    return_: Optional[Journey] = Field(default=None, alias="return")
    return_match: Optional[Literal["exact", "suggested"]] = None

    def to_json(self) -> dict:
        return self.model_dump(by_alias=True)


@dataclass(frozen=True)
class SearchQuery:
    origin: str
    destination: str
    depart: date
    return_date: Optional[date]
    adults: int
    cabin: str
    currency: str
    max_stops: Optional[int]

    @property
    def trip(self) -> str:
        return "round_trip" if self.return_date else "one_way"

    def cache_key(self) -> tuple:
        return (
            self.origin, self.destination, self.depart, self.return_date,
            self.adults, self.cabin, self.currency, self.max_stops,
        )

    def to_json(self) -> dict:
        return {
            "from": self.origin,
            "to": self.destination,
            "depart": self.depart.isoformat(),
            "return": self.return_date.isoformat() if self.return_date else None,
            "adults": self.adults,
            "cabin": self.cabin,
            "currency": self.currency,
            "stops": "any" if self.max_stops is None else str(self.max_stops),
            "trip": self.trip,
        }


@dataclass(frozen=True)
class DatesQuery:
    origin: str
    destination: str
    start: date
    end: date
    trip_days: Optional[int]
    adults: int
    cabin: str
    currency: str

    def cache_key(self) -> tuple:
        return (
            self.origin, self.destination, self.start, self.end,
            self.trip_days, self.adults, self.cabin, self.currency,
        )

    def to_json(self) -> dict:
        return {
            "from": self.origin,
            "to": self.destination,
            "start": self.start.isoformat(),
            "end": self.end.isoformat(),
            "trip_days": self.trip_days,
            "adults": self.adults,
            "cabin": self.cabin,
            "currency": self.currency,
        }
