"""Stays search: validation-free core used by /api/stays and /plan-trip. Cached for 30 minutes."""

from __future__ import annotations

import logging
import re
import threading
import time
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, replace
from datetime import date
from typing import Callable, Optional

from .airbnb import AirbnbMcpSource, StaysUnavailable
from .budget import rate_to_inr as default_rate_to_inr

log = logging.getLogger(__name__)

MAX_STAYS = 18
_MONEY = re.compile(r"([₹$€£])\s?([\d,]+(?:\.\d+)?)")
_SYMBOLS = {"₹": "INR", "$": "USD", "€": "EUR", "£": "GBP"}
_RATING = re.compile(r"([\d.]+) out of 5 average rating,\s*([\d,]+) reviews?")


@dataclass(frozen=True)
class StaysQuery:
    place: str
    checkin: date
    checkout: date
    adults: int
    max_per_night: Optional[int] = None  # rupees; TP-05 D1

    @property
    def nights(self) -> int:
        return (self.checkout - self.checkin).days

    def arguments(self) -> dict:
        arguments = {"location": self.place, "checkin": self.checkin.isoformat(), "checkout": self.checkout.isoformat(), "adults": self.adults}
        if self.max_per_night:
            arguments["maxPrice"] = self.max_per_night
        return arguments

    def to_json(self) -> dict:
        data = {"place": self.place, "checkin": self.checkin.isoformat(), "checkout": self.checkout.isoformat(), "adults": self.adults, "nights": self.nights}
        if self.max_per_night:
            data["max_per_night"] = self.max_per_night
        return data


@dataclass(frozen=True)
class StaysOutcome:
    stays: list[dict]
    search_url: Optional[str]
    cached: bool


def _dig(data, *keys):
    for key in keys:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


PHOTO_SERVER = "https://a0.muscache.com/"
MAX_PHOTOS = 5


def _photos(listing: dict) -> list[str]:
    """Up to 5 listing photos from Airbnb's image server, cover first (TP-04 A1).

    The Airbnb server joins them into one text: "https://a0.muscache.com/…jpg, https://a0.muscache.com/…".
    """
    raw = listing.get("contextualPictures")
    if isinstance(raw, str):
        candidates = raw.split(",")
    elif isinstance(raw, list):
        candidates = [item.get("picture") if isinstance(item, dict) else item for item in raw]
    else:
        candidates = []
    photos: list[str] = []
    for candidate in candidates:
        url = str(candidate or "").strip()
        if url.startswith(PHOTO_SERVER) and " " not in url and url not in photos:
            photos.append(url)
        if len(photos) == MAX_PHOTOS:
            break
    return photos


def normalize_listing(listing: dict, query: StaysQuery) -> Optional[dict]:
    listing_id = str(listing.get("id") or "")
    if not listing_id.isdigit():
        return None
    nights = max(query.nights, 1)

    price_label = _dig(listing, "structuredDisplayPrice", "primaryLine", "accessibilityLabel") or ""
    money = _MONEY.search(price_label)
    total = per_night = currency = None
    if money:
        amount = int(round(float(money.group(2).replace(",", ""))))
        currency = _SYMBOLS[money.group(1)]
        priced_nights = re.search(r"\bfor (\d+) nights?\b", price_label)
        if re.search(r"\b(per|a) night\b", price_label):
            per_night, total = amount, amount * nights
        elif priced_nights and int(priced_nights.group(1)) not in (0, nights):
            # The price is for the nights Airbnb says, not always the nights asked for (TP-07 C5).
            per_night = int(round(amount / int(priced_nights.group(1))))
            total = per_night * nights
        else:
            total, per_night = amount, int(round(amount / nights))

    rating_match = _RATING.search(listing.get("avgRatingA11yLabel") or "")
    rating = float(rating_match.group(1)) if rating_match else None
    reviews = int(rating_match.group(2).replace(",", "")) if rating_match else 0

    # The listing's map position, so a stay's distance from its place can be checked (TP-06 H8).
    coordinate = _dig(listing, "demandStayListing", "location", "coordinate") or {}
    lat, lng = coordinate.get("latitude"), coordinate.get("longitude")
    location = {"lat": lat, "lng": lng} if all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in (lat, lng)) else None

    return {
        "id": listing_id,
        "name": _dig(listing, "demandStayListing", "description", "name", "localizedStringWithTranslationPreference")
        or _dig(listing, "structuredContent", "mapCategoryInfo", "body")
        or "Airbnb stay",
        "summary": _dig(listing, "structuredContent", "mapCategoryInfo", "body"),
        "url": f"https://www.airbnb.com/rooms/{listing_id}?check_in={query.checkin.isoformat()}&check_out={query.checkout.isoformat()}&adults={query.adults}",
        "total_price": total,
        "price_per_night": per_night,
        "currency": currency,
        "nights": nights,
        "rating": rating,
        "reviews": reviews,
        "photos": _photos(listing),
        "location": location,
    }


class StaysService:
    def __init__(self, source=None, clock: Optional[Callable[[], float]] = None, today: Optional[Callable[[], date]] = None,
                 timeout_s: float = 15.0, ttl_s: float = 1800.0, rate_to_inr: Optional[Callable[[str], float]] = None):
        self.source = source if source is not None else AirbnbMcpSource()
        self.rate_to_inr = rate_to_inr or default_rate_to_inr
        self.clock = clock or time.monotonic
        self.today = today or date.today
        self.timeout_s = timeout_s
        self.ttl_s = ttl_s
        self._cache: dict[tuple, tuple[float, StaysOutcome]] = {}
        self._lock = threading.Lock()

    def search(self, query: StaysQuery) -> StaysOutcome:
        key = (query.place.lower(), query.checkin, query.checkout, query.adults, query.max_per_night)
        with self._lock:
            hit = self._cache.get(key)
            if hit and self.clock() - hit[0] < self.ttl_s:
                return replace(hit[1], cached=True)

        raw = self._call(query.arguments())
        stays = [stay for stay in (normalize_listing(item, query) for item in raw.get("searchResults") or [] if isinstance(item, dict)) if stay]
        if query.max_per_night:
            # Airbnb's price filter isn't exact, and a stay without a price can't be shown as within the budget.
            # Only rupee prices can be compared with the rupee limit; Airbnb is asked for INR (airbnb-currency.mjs).
            stays = [
                stay for stay in stays
                if stay["currency"] == "INR" and stay["price_per_night"] is not None and stay["price_per_night"] <= query.max_per_night
            ]
        outcome = StaysOutcome(stays=stays[:MAX_STAYS], search_url=raw.get("searchUrl"), cached=False)
        if outcome.stays:
            with self._lock:
                self._cache[key] = (self.clock(), outcome)
        return outcome

    def _call(self, arguments: dict) -> dict:
        result: Future = Future()

        def work():
            if not result.set_running_or_notify_cancel():
                return
            try:
                value = self.source.search(arguments)
            except BaseException as exc:
                result.set_exception(exc)
            else:
                result.set_result(value)

        threading.Thread(target=work, name="airbnb-stays", daemon=True).start()
        try:
            data = result.result(timeout=self.timeout_s)
        except (FutureTimeout, TimeoutError):
            log.warning("Airbnb stays timed out after %.0f s", self.timeout_s)
            raise StaysUnavailable("timeout") from None
        except StaysUnavailable as exc:
            log.warning("Airbnb stays unavailable: %s", exc.reason)
            raise
        except Exception as exc:
            log.warning("Airbnb stays failed (%s)", type(exc).__name__)
            raise StaysUnavailable("failed") from None
        return data if isinstance(data, dict) else {}
