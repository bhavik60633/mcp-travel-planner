"""How much of the trip budget goes to stays (TP-05 D2).

The trip form's budget is the total for the whole trip. Stays get a share by trip type (Budget 30%, Standard 40%,
Luxury 50%), divided by the nights, as the most per night. Airbnb shows stays in India in rupees, so a budget in
another currency is converted with Frankfurter's rate, or Currency-api's if Frankfurter fails. Without a rate
there's no limit, rather than a wrong one.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

import httpx

log = logging.getLogger(__name__)

STAY_SHARES = {"Budget": 0.30, "Standard": 0.40, "Luxury": 0.50}
AIRBNB_CURRENCY = "INR"
FRANKFURTER_URL = "https://api.frankfurter.dev/v1/latest"
CURRENCY_API_URL = "https://cdn.jsdelivr.net/npm/@fawazahmed0/currency-api@latest/v1/currencies/{code}.json"


def rate_to_inr(currency: str, http_client: Optional[httpx.Client] = None) -> float:
    """How many rupees one unit of `currency` is worth today."""
    client = http_client or httpx.Client(timeout=6.0)
    code = currency.upper()
    try:
        response = client.get(FRANKFURTER_URL, params={"base": code, "symbols": AIRBNB_CURRENCY})
        response.raise_for_status()
        return float(response.json()["rates"][AIRBNB_CURRENCY])
    except (httpx.HTTPError, KeyError, ValueError, TypeError) as exc:
        log.warning("Frankfurter has no %s rate (%s); trying Currency-api", code, type(exc).__name__)
    response = client.get(CURRENCY_API_URL.format(code=code.lower()))
    response.raise_for_status()
    return float(response.json()[code.lower()][AIRBNB_CURRENCY.lower()])


def nightly_stay_budget(
    trip_budget: float,
    trip_currency: str,
    trip_type: str,
    nights: int,
    rate_to_inr: Optional[Callable[[str], float]] = None,
) -> Optional[dict]:
    share = STAY_SHARES.get(trip_type, STAY_SHARES["Standard"])
    currency = (trip_currency or AIRBNB_CURRENCY).upper()
    per_night = trip_budget * share / max(nights, 1)
    if currency != AIRBNB_CURRENCY:
        if rate_to_inr is None:
            return None
        try:
            per_night *= float(rate_to_inr(currency))
        except Exception as exc:
            log.warning("No %s to INR rate for the stay budget (%s)", currency, type(exc).__name__)
            return None
    return {
        "max_per_night": int(round(per_night)),
        "currency": AIRBNB_CURRENCY,
        "share": round(share * 100),
        "trip_budget": trip_budget,
        "trip_currency": currency,
    }
