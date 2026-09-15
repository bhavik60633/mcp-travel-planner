"""Distances and map areas (TP-07)."""

from __future__ import annotations

import math

EARTH_KM = 6371.0
KM_PER_DEGREE = 111.32


def km_between(a: dict, b: dict) -> float:
    """Great-circle distance between two {"lat", "lng"} points."""
    lat1, lng1, lat2, lng2 = map(math.radians, (a["lat"], a["lng"], b["lat"], b["lng"]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 2 * EARTH_KM * math.asin(math.sqrt(h))


def rectangle_around(point: dict, km: float) -> dict:
    """A Google rectangle ({"low", "high"}) reaching `km` north, south, east and west of the point."""
    half_lat = km / KM_PER_DEGREE
    half_lng = km / (KM_PER_DEGREE * max(math.cos(math.radians(point["lat"])), 0.01))
    return {
        "low": {"latitude": point["lat"] - half_lat, "longitude": point["lng"] - half_lng},
        "high": {"latitude": point["lat"] + half_lat, "longitude": point["lng"] + half_lng},
    }


def span_km(rectangle: dict) -> float:
    """Corner to corner across a Google rectangle."""
    low, high = rectangle["low"], rectangle["high"]
    return km_between({"lat": low["latitude"], "lng": low["longitude"]}, {"lat": high["latitude"], "lng": high["longitude"]})


def inside(rectangle: dict, point: dict) -> bool:
    return (
        rectangle["low"]["latitude"] <= point["lat"] <= rectangle["high"]["latitude"]
        and rectangle["low"]["longitude"] <= point["lng"] <= rectangle["high"]["longitude"]
    )


def centre(points: list[dict]) -> dict:
    return {"lat": sum(p["lat"] for p in points) / len(points), "lng": sum(p["lng"] for p in points) / len(points)}
