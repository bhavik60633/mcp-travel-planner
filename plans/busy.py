"""Busy hours from Google's popular times, through SerpApi (TP-07 F1–F3).

Each place's week is saved for 30 days, so repeated places don't use up searches. The key is never logged or returned.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from typing import Callable, Optional

import httpx

log = logging.getLogger(__name__)

_KEY_IN_URL = re.compile(r"(api_key=)[^&\s\"']+")


class _HideKeys(logging.Filter):
    """SerpApi takes its key in the link, and httpx logs every link: the key is hidden before any log sees it (F1)."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple) and any("api_key=" in str(arg) for arg in record.args):
            record.args = tuple(_KEY_IN_URL.sub(r"\1[hidden]", str(arg)) if "api_key=" in str(arg) else arg for arg in record.args)
        if isinstance(record.msg, str) and "api_key=" in record.msg:
            record.msg = _KEY_IN_URL.sub(r"\1[hidden]", record.msg)
        return True


if not any(isinstance(existing, _HideKeys) for existing in logging.getLogger("httpx").filters):
    logging.getLogger("httpx").addFilter(_HideKeys())

SERPAPI_URL = "https://serpapi.com/search.json"
KEY_ENV = "SERPAPI_API_KEY"
TTL_S = 30 * 24 * 3600
BUSY_SHARE = 0.8
WEEKDAYS = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
_HOUR = re.compile(r"^\s*(\d{1,2})\s*(AM|PM)\s*$", re.IGNORECASE)


def _hour(text: str) -> Optional[int]:
    match = _HOUR.match(str(text or ""))
    if not match:
        return None
    hour = int(match.group(1)) % 12
    return hour + 12 if match.group(2).upper() == "PM" else hour


class BusyHours:
    def __init__(self, api_key: str, http_client: Optional[httpx.Client] = None, clock: Optional[Callable[[], float]] = None, ttl_s: float = TTL_S, timeout_s: float = 6.0):
        self._key = api_key
        self._http = http_client or httpx.Client(timeout=timeout_s)
        self.clock = clock or time.monotonic
        self.ttl_s = ttl_s
        self._cache: dict[str, tuple[float, dict]] = {}
        self._lock = threading.Lock()

    def __repr__(self) -> str:
        return "BusyHours()"  # never shows the key

    def week(self, place_id: str) -> Optional[dict[str, dict[int, int]]]:
        """{"monday": {13: 100, ...}, ...} from Google's popular times, or None when there's no data."""
        with self._lock:
            hit = self._cache.get(place_id)
        if hit is not None and self.clock() - hit[0] < self.ttl_s:
            return hit[1] or None
        try:
            response = self._http.get(SERPAPI_URL, params={"engine": "google_maps", "type": "place", "place_id": place_id, "hl": "en", "api_key": self._key})
        except httpx.HTTPError as exc:
            log.warning("Busy hours unavailable (%s)", type(exc).__name__)
            return None
        if response.status_code != 200:
            log.warning("Busy hours unavailable (HTTP %s)", response.status_code)
            return None
        try:
            graph = ((response.json().get("place_results") or {}).get("popular_times") or {}).get("graph_results") or {}
        except ValueError:
            return None
        week: dict[str, dict[int, int]] = {}
        for day, entries in graph.items():
            hours = {}
            for item in entries or []:
                hour = _hour(item.get("time"))
                score = item.get("busyness_score")
                if hour is not None and isinstance(score, (int, float)):
                    hours[hour] = int(score)
            if hours:
                week[str(day).lower()] = hours
        with self._lock:
            self._cache[place_id] = (self.clock(), week)
        return week or None

    def busy_window(self, place_id: str, weekday: str) -> Optional[tuple[int, int]]:
        return busy_window(self.week(place_id), weekday)


def busy_window(week: Optional[dict], weekday: str) -> Optional[tuple[int, int]]:
    """The busiest run of hours that day, at least 80% of its peak, as (start, end) minutes; None without data (F2, F3)."""
    hours = (week or {}).get(weekday.lower()) or {}
    if not hours:
        return None
    peak_hour = max(hours, key=hours.get)
    peak = hours[peak_hour]
    if peak <= 0:
        return None
    busy = {hour for hour, score in hours.items() if score >= BUSY_SHARE * peak}
    start = end = peak_hour
    while start - 1 in busy:
        start -= 1
    while end + 1 in busy:
        end += 1
    return start * 60, (end + 1) * 60


def build_busy_hours() -> Optional[BusyHours]:
    key = os.environ.get(KEY_ENV, "").strip()
    return BusyHours(api_key=key) if key else None


def busy_hours_status() -> dict:
    """For /api/health (TP-07 K1). Never the key itself."""
    has_key = bool(os.environ.get(KEY_ENV, "").strip())
    return {"service": "busy_hours", "label": "Busy hours (SerpApi)", "key": KEY_ENV, "set": has_key, "status": "ready" if has_key else "key missing"}
