"""Result order: Best (the default), Cheapest, Fastest or Earliest departure (TP-03 A4)."""

from __future__ import annotations

from statistics import median

from .models import Offer

SORTS = ("best", "cheapest", "fastest", "earliest")

# "Best" weighs time and stops against price, like Google Flights' default order: each hour of
# travel counts as 3% of the typical price in the results, and each stop as 5%.
HOUR_WEIGHT = 0.03
STOP_WEIGHT = 0.05


def order_offers(offers: list[Offer], sort: str = "best") -> list[Offer]:
    if sort == "cheapest":
        return sorted(offers, key=lambda o: (o.price, o.duration_min))
    if sort == "fastest":
        return sorted(offers, key=lambda o: (o.duration_min, o.price))
    if sort == "earliest":
        return sorted(offers, key=lambda o: (o.outbound.departure, o.price))
    if not offers:
        return []
    typical = median(o.price for o in offers)
    return sorted(
        offers,
        key=lambda o: (o.price + o.duration_min / 60 * HOUR_WEIGHT * typical + o.stops * STOP_WEIGHT * typical, o.price),
    )
