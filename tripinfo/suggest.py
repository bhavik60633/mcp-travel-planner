"""Place suggestions for the trip form's To box, and places found on the map (TP-06 B1, B2, H2).

Photon (komoot, OpenStreetMap data) needs no key and is built for search as you type. Its rule is fair use,
so answers are cached for a day. A slow or failing Photon gives an empty list within 3 seconds, never an error.
"""

from __future__ import annotations

import logging
import math
import threading
import time
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeout
from typing import Callable, Optional

import httpx

from .service import PHOTON_URL, USER_AGENT

log = logging.getLogger(__name__)

MAX_SUGGESTIONS = 6
UNAVAILABLE_MESSAGE = "Place suggestions aren't available right now."
# Kinds of places people travel to. Suburbs, airports, stations, buildings and the like are left out.
PLACE_KINDS = frozenset({
    "country", "state", "region", "province", "county", "district", "municipality",
    "city", "town", "village", "locality", "island", "islet", "archipelago",
})


class MapUnavailable(Exception):
    """Photon didn't give a usable answer in time."""


def distance_km(a: dict, b: dict) -> float:
    """Great-circle distance between two {"lat", "lng"} points."""
    lat1, lng1, lat2, lng2 = map(math.radians, (a["lat"], a["lng"], b["lat"], b["lng"]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def _is_destination(props: dict) -> bool:
    key, value = props.get("osm_key"), props.get("osm_value")
    return (key == "place" and value in PLACE_KINDS) or (key == "boundary" and value == "administrative")


def _label(props: dict) -> str:
    parts: list[str] = []
    for part in (props.get("name"), props.get("state"), props.get("country")):
        if part and part not in parts:
            parts.append(part)
    return ", ".join(parts)


class PlaceSuggester:
    def __init__(
        self,
        http_client: Optional[httpx.Client] = None,
        clock: Optional[Callable[[], float]] = None,
        ttl_s: float = 24 * 3600,
        timeout_s: float = 3.0,
    ):
        self._http = http_client or httpx.Client(timeout=timeout_s, follow_redirects=True)
        self.clock = clock or time.monotonic
        self.ttl_s = ttl_s
        self.timeout_s = timeout_s
        self._cache: dict[tuple, tuple[float, object]] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ the To box (B1, B2)

    def suggest(self, query: str) -> dict:
        text = " ".join((query or "").split())
        if len(text) < 2:
            return {"query": text, "places": [], "available": True, "cached": False}
        key = ("suggest", text.lower())
        hit = self._cached(key)
        if hit is not None:
            return {"query": text, "places": hit, "available": True, "cached": True}
        try:
            features = self._features(text, limit=12)
        except MapUnavailable:
            return {"query": text, "places": [], "available": False, "message": UNAVAILABLE_MESSAGE, "cached": False}

        places: list[dict] = []
        for feature in features:
            try:
                props = feature["properties"]
                lng, lat = feature["geometry"]["coordinates"][:2]
            except (KeyError, TypeError, ValueError):
                continue
            if not props.get("name") or not _is_destination(props):
                continue
            label = _label(props)
            if any(place["label"] == label for place in places):
                continue
            places.append({
                "name": props["name"],
                "label": label,
                "kind": props.get("osm_value"),
                "region": props.get("state"),
                "country": props.get("country"),
                "country_code": (props.get("countrycode") or "").upper() or None,
                "lat": lat,
                "lng": lng,
            })
            if len(places) == MAX_SUGGESTIONS:
                break
        self._store(key, places)
        return {"query": text, "places": places, "available": True, "cached": False}

    # ------------------------------------------------------------------ checking a place (H2)

    def locate(self, query: str) -> Optional[dict]:
        """The first place Photon finds for this text as {"name", "lat", "lng"}, or None. Raises MapUnavailable."""
        text = " ".join((query or "").split())
        if not text:
            return None
        key = ("locate", text.lower())
        hit = self._cached(key)
        if hit is not None:
            return hit or None
        found: Optional[dict] = None
        for feature in self._features(text, limit=1):
            try:
                lng, lat = feature["geometry"]["coordinates"][:2]
                found = {"name": feature["properties"].get("name") or text, "lat": float(lat), "lng": float(lng)}
                break
            except (KeyError, TypeError, ValueError):
                continue
        self._store(key, found or {})
        return found

    # ------------------------------------------------------------------ Photon

    def _cached(self, key: tuple):
        with self._lock:
            hit = self._cache.get(key)
        if hit is not None and self.clock() - hit[0] < self.ttl_s:
            return hit[1]
        return None

    def _store(self, key: tuple, value) -> None:
        with self._lock:
            self._cache[key] = (self.clock(), value)

    def _features(self, text: str, limit: int) -> list:
        result: Future = Future()

        def work():
            if not result.set_running_or_notify_cancel():
                return
            try:
                response = self._http.get(
                    PHOTON_URL,
                    params={"q": text, "limit": limit, "lang": "en"},
                    headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
                )
                if response.status_code != 200:
                    raise MapUnavailable(f"HTTP {response.status_code}")
                features = response.json().get("features")
                if not isinstance(features, list):
                    raise MapUnavailable("no features")
            except BaseException as exc:
                result.set_exception(exc)
            else:
                result.set_result(features)

        threading.Thread(target=work, name="photon", daemon=True).start()
        try:
            return result.result(timeout=self.timeout_s)
        except (FutureTimeout, TimeoutError):
            log.warning("Photon took longer than %.1f s", self.timeout_s)
            raise MapUnavailable("timeout") from None
        except MapUnavailable as exc:
            log.warning("Photon unavailable (%s)", exc)
            raise
        except Exception as exc:
            log.warning("Photon failed (%s)", type(exc).__name__)
            raise MapUnavailable("failed") from None
