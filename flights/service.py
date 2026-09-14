"""Runs searches across the flight sources: order, deadline, caching and sharing."""

from __future__ import annotations

import logging
import threading
import time
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from typing import Callable, Optional

from .models import DatesQuery, Offer, SearchQuery
from .sources.base import SourceUnavailable

log = logging.getLogger(__name__)

UNAVAILABLE_MESSAGE = "Flight prices are temporarily unavailable. Try again in a few minutes."


class FlightsUnavailable(Exception):
    """No source could answer."""

    def __init__(self, attempts: list[dict]):
        super().__init__(UNAVAILABLE_MESSAGE)
        self.attempts = attempts


class OutboundNotFound(Exception):
    """The chosen outbound flight isn't in the search results any more."""


@dataclass(frozen=True)
class FlightsOutcome:
    source: Optional[str]
    offers: list[Offer]
    attempts: list[dict]
    cached: bool
    fetched_at: str


@dataclass(frozen=True)
class ReturnsOutcome:
    source: Optional[str]
    outbound: Offer
    offers: list[Offer]
    attempts: list[dict]
    cached: bool
    fetched_at: str


@dataclass(frozen=True)
class DatesOutcome:
    source: Optional[str]
    days: list[dict]
    attempts: list[dict]
    cached: bool
    fetched_at: str


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


class FlightService:
    def __init__(
        self,
        sources,
        date_sources=(),
        today: Optional[Callable[[], date]] = None,
        clock: Optional[Callable[[], float]] = None,
        deadline_s: float = 20.0,
        cache_ttl_s: float = 600.0,
        dates_cache_ttl_s: float = 1800.0,
    ):
        self.sources = list(sources)
        self.date_sources = list(date_sources)
        self.today = today or date.today
        self.clock = clock or time.monotonic
        self.deadline_s = deadline_s
        self.cache_ttl_s = cache_ttl_s
        self.dates_cache_ttl_s = dates_cache_ttl_s
        self._cache: dict[tuple, tuple[float, object]] = {}
        self._inflight: dict[tuple, Future] = {}
        self._lock = threading.Lock()
        # At most one live request to Google at a time (C11). The worker thread
        # holds it for as long as its request really runs.
        self._google_lock = threading.Lock()

    # ------------------------------------------------------------------ public

    def search(self, query: SearchQuery) -> FlightsOutcome:
        return self._shared(("flights",) + query.cache_key(), self.cache_ttl_s, lambda: self._run_flights(query))

    def returns(self, query: SearchQuery, outbound_id: str) -> ReturnsOutcome:
        """Exact return flights for one outbound flight from the round-trip search (TP-03 C1)."""
        outbound = next((offer for offer in self.search(query).offers if offer.id == outbound_id), None)
        if outbound is None:
            raise OutboundNotFound(outbound_id)
        key = ("returns",) + query.cache_key() + (outbound_id,)
        return self._shared(key, self.cache_ttl_s, lambda: self._run_returns(query, outbound))

    def cheapest_days(self, query: DatesQuery) -> DatesOutcome:
        return self._shared(("dates",) + query.cache_key(), self.dates_cache_ttl_s, lambda: self._run_dates(query))

    # ------------------------------------------------------- cache and sharing

    def _shared(self, key: tuple, ttl: float, run: Callable):
        with self._lock:
            hit = self._cache.get(key)
            if hit and self.clock() - hit[0] < ttl:
                return replace(hit[1], cached=True)
            future = self._inflight.get(key)
            leader = future is None
            if leader:
                future = Future()
                self._inflight[key] = future
        if not leader:
            return future.result()  # an identical search is already running: share its answer

        try:
            outcome = run()
        except BaseException as exc:
            future.set_exception(exc)
            raise
        else:
            future.set_result(outcome)
            has_results = bool(getattr(outcome, "offers", None) or getattr(outcome, "days", None))
            if has_results:
                with self._lock:
                    self._cache[key] = (self.clock(), outcome)
            return outcome
        finally:
            with self._lock:
                self._inflight.pop(key, None)

    # ------------------------------------------------------------ source calls

    def _call(self, source, method: str, args: tuple, timeout_s: float):
        """Run one source call in its own thread; return ("ok", value) / ("unavailable"|"timeout", None)."""
        result: Future = Future()
        uses_google = getattr(source, "uses_google", True)

        def work():
            if uses_google and not self._google_lock.acquire(timeout=max(timeout_s, 0.0)):
                if not result.done():
                    try:
                        result.set_exception(FutureTimeout())
                    except Exception:
                        pass
                return
            try:
                if not result.set_running_or_notify_cancel():
                    return
                try:
                    value = getattr(source, method)(*args)
                except BaseException as exc:
                    result.set_exception(exc)
                else:
                    result.set_result(value)
            finally:
                if uses_google:
                    self._google_lock.release()

        threading.Thread(target=work, name=f"flight-source-{source.name}", daemon=True).start()
        try:
            return "ok", result.result(timeout=max(timeout_s, 0.0))
        except (FutureTimeout, TimeoutError):
            result.cancel()
            log.warning("flight source %s timed out", source.name)
            return "timeout", None
        except SourceUnavailable as exc:
            log.warning("flight source %s unavailable: %s", source.name, exc)
            return "unavailable", None
        except Exception as exc:
            log.warning("flight source %s failed (%s)", source.name, type(exc).__name__)
            return "unavailable", None

    def _run_flights(self, query: SearchQuery) -> FlightsOutcome:
        deadline = time.monotonic() + self.deadline_s
        attempts: list[dict] = []
        best: Optional[tuple[str, list[Offer]]] = None
        empty_source: Optional[str] = None

        for source in self.sources:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            status, value = self._call(source, "search", (query,), remaining)
            offers = self._tidy(value or [], query) if status == "ok" else []
            if status == "ok" and not offers:
                status = "empty"
            attempt = {"source": source.name, "result": status}
            if offers:
                attempt["count"] = len(offers)
            attempts.append(attempt)

            if offers:
                if best is None or len(offers) > len(best[1]):
                    best = (source.name, offers)  # the fuller list wins
                if getattr(source, "complete", False):
                    break
            elif status == "empty" and empty_source is None:
                empty_source = source.name

        if best is not None:
            return FlightsOutcome(best[0], best[1], attempts, False, _now_iso())
        if empty_source is not None:
            return FlightsOutcome(empty_source, [], attempts, False, _now_iso())
        raise FlightsUnavailable(attempts)

    def _run_returns(self, query: SearchQuery, outbound: Offer) -> ReturnsOutcome:
        deadline = time.monotonic() + self.deadline_s
        attempts: list[dict] = []
        empty_source: Optional[str] = None

        for source in self.sources:
            if not callable(getattr(source, "search_returns", None)):
                continue
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            status, value = self._call(source, "search_returns", (query, outbound), remaining)
            offers = self._tidy(value or [], query) if status == "ok" else []
            if status == "ok" and not offers:
                status = "empty"
            attempts.append({"source": source.name, "result": status, **({"count": len(offers)} if offers else {})})
            if offers:
                return ReturnsOutcome(source.name, outbound, offers, attempts, False, _now_iso())
            if status == "empty" and empty_source is None:
                empty_source = source.name

        if empty_source is not None:
            return ReturnsOutcome(empty_source, outbound, [], attempts, False, _now_iso())
        raise FlightsUnavailable(attempts)

    @staticmethod
    def _tidy(offers: list[Offer], query: SearchQuery) -> list[Offer]:
        unique: dict[str, Offer] = {}
        for offer in offers:
            if offer.price <= 0 or offer.currency != query.currency:
                continue
            if query.max_stops is not None and offer.stops > query.max_stops:
                continue
            kept = unique.get(offer.id)
            if kept is None or offer.price < kept.price:
                unique[offer.id] = offer
        return sorted(unique.values(), key=lambda o: (o.price, o.duration_min))

    def _run_dates(self, query: DatesQuery) -> DatesOutcome:
        deadline = time.monotonic() + self.deadline_s
        attempts: list[dict] = []
        empty_source: Optional[str] = None

        for source in self.date_sources:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            status, value = self._call(source, "search_dates", (query,), remaining)
            days = self._lowest_per_day(value or [], query) if status == "ok" else []
            if status == "ok" and not days:
                status = "empty"
            attempts.append({"source": source.name, "result": status, **({"count": len(days)} if days else {})})
            if days:
                return DatesOutcome(source.name, days, attempts, False, _now_iso())
            if status == "empty" and empty_source is None:
                empty_source = source.name

        if empty_source is not None:
            return DatesOutcome(empty_source, [], attempts, False, _now_iso())
        raise FlightsUnavailable(attempts)

    @staticmethod
    def _lowest_per_day(days: list[dict], query: DatesQuery) -> list[dict]:
        lowest: dict[str, int] = {}
        for day in days:
            try:
                when = date.fromisoformat(str(day["date"])[:10])
                price = int(round(float(day["price"])))
            except (KeyError, TypeError, ValueError):
                continue
            if price <= 0 or not query.start <= when <= query.end:
                continue
            key = when.isoformat()
            lowest[key] = min(price, lowest.get(key, price))
        return [{"date": key, "price": lowest[key]} for key in sorted(lowest)]
