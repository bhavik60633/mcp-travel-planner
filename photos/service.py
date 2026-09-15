"""Unsplash photo search with a 24-hour cache.

The key travels only in the Authorization header, never in a URL, log line or response.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from typing import Callable, Optional

import httpx

log = logging.getLogger(__name__)

SEARCH_URL = "https://api.unsplash.com/search/photos"
_FROM_ENVIRONMENT = object()


class ImageService:
    def __init__(self, access_key=_FROM_ENVIRONMENT, http_client: Optional[httpx.Client] = None,
                 clock: Optional[Callable[[], float]] = None, ttl_s: float = 24 * 3600, pause_s: float = 15 * 60):
        self._access_key = access_key
        self._http = http_client
        self._clock = clock or time.monotonic
        self._ttl_s = ttl_s
        self._pause_s = pause_s
        self._cache: dict[str, tuple[float, dict]] = {}
        self._paused_until = 0.0
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        return "ImageService(access_key=***)"

    def _key(self) -> Optional[str]:
        key = os.environ.get("UNSPLASH_ACCESS_KEY") if self._access_key is _FROM_ENVIRONMENT else self._access_key
        return (key or "").strip() or None

    @staticmethod
    def _answer(query: str, reason: Optional[str], image: Optional[dict], cached: bool = False) -> dict:
        return {"query": query, "cached": cached, "reason": reason, "image": image}

    def photo(self, query: str) -> dict:
        cache_key = query.lower()
        now = self._clock()
        with self._lock:
            hit = self._cache.get(cache_key)
            if hit and now - hit[0] < self._ttl_s:
                return self._answer(query, hit[1]["reason"], hit[1]["image"], cached=True)
            paused = now < self._paused_until

        key = self._key()
        if not key:
            return self._answer(query, "not_configured", None)
        if paused:
            return self._answer(query, "rate_limited", None)

        if self._http is None:
            self._http = httpx.Client(timeout=8.0)
        try:
            response = self._http.get(
                SEARCH_URL,
                params={"query": f"{query} travel", "per_page": 1, "orientation": "landscape"},
                headers={"Authorization": f"Client-ID {key}", "Accept-Version": "v1"},
            )
        except httpx.HTTPError as exc:
            log.warning("Unsplash request failed (%s)", type(exc).__name__)
            return self._answer(query, "unavailable", None)

        if response.status_code in (403, 429):
            with self._lock:
                self._paused_until = self._clock() + self._pause_s
            log.warning("Unsplash hourly limit reached; photos paused for %d minutes", self._pause_s // 60)
            return self._answer(query, "rate_limited", None)
        if response.status_code != 200:
            log.warning("Unsplash answered HTTP %s", response.status_code)
            return self._answer(query, "unavailable", None)

        try:
            results = response.json().get("results") or []
        except ValueError:
            return self._answer(query, "unavailable", None)

        if results:
            photo = results[0]
            image = {
                "url": photo["urls"]["regular"],
                "small_url": photo["urls"]["small"],
                "alt": photo.get("alt_description") or query,
                "photographer": photo["user"]["name"],
                "photographer_url": photo["user"]["links"]["html"],
                "unsplash_url": photo["links"]["html"],
            }
            stored = {"reason": None, "image": image}
        else:
            stored = {"reason": "not_found", "image": None}
        with self._lock:
            self._cache[cache_key] = (self._clock(), stored)
        return self._answer(query, stored["reason"], stored["image"])
