"""Google Flights' results page, read directly (TP-03 D1).

Yori asks Google in English, for India, in the chosen currency, and reads every flight in the
page's data script. The page's own flight descriptions ("From 6314 Indian rupees…") say which
currency its prices are in, so a page in another currency is refused, never relabelled.
"""

from __future__ import annotations

import base64
import re
import time
from typing import Callable, Optional

SEARCH_URL = "https://www.google.com/travel/flights/search"
# Google's page lists a slightly different set of flights on each request (seen 14 Sep 2026), so it is
# read again until a read adds nothing new, at most this many times (TP-03 A3).
MAX_READS = 3
CURRENCY_WORDS = {"INR": "Indian rupees", "USD": "US dollars", "EUR": "euros", "GBP": "British pounds"}
_SEAT = {"economy": 1, "premium-economy": 2, "business": 3, "first": 4}


class WrongCurrency(Exception):
    """Google answered in a different currency from the one asked for."""


def _http_get(url: str, params: dict) -> str:
    from gf_search.fetcher import _make_client

    response = _make_client().get(url, params=params)
    if response.status_code != 200:
        raise RuntimeError(f"Google answered HTTP {response.status_code}")
    return response.text


def build_tfs(origin: str, destination: str, depart: str, return_date: Optional[str], adults: int, seat: int,
              selected_segments: Optional[list[dict]] = None) -> str:
    """Google's search descriptor. `selected_segments` marks the outbound flight already chosen."""
    from gf_search._utils import _field_len, _field_varint
    from gf_search.builder import _FIELD16_ALL_RESULTS, _airport_bytes

    selections = b""
    for segment in selected_segments or []:
        number = segment["flight_no"].replace(" ", "")
        selections += _field_len(
            4,
            _field_len(1, segment["from"].encode())
            + _field_len(2, segment["departure"][:10].encode())
            + _field_len(3, segment["to"].encode())
            + _field_len(5, number[:2].encode())
            + _field_len(6, number[2:].encode()),
        )
    outbound = _field_len(2, depart.encode()) + selections + _field_len(13, _airport_bytes(origin)) + _field_len(14, _airport_bytes(destination))
    info = _field_varint(1, 28) + _field_varint(2, 2) + _field_len(3, outbound)
    if return_date:
        info += _field_len(3, _field_len(2, return_date.encode()) + _field_len(13, _airport_bytes(destination)) + _field_len(14, _airport_bytes(origin)))
    info += _field_varint(8, 1) * max(adults, 1)
    info += _field_varint(9, seat) + _field_varint(14, 1) + _field_len(16, _FIELD16_ALL_RESULTS)
    info += _field_varint(19, 1 if return_date else 2)
    return base64.urlsafe_b64encode(info).rstrip(b"=").decode("ascii")


def check_currency(html: str, currency: str) -> None:
    """Refuse a page whose flight descriptions are in another supported currency."""
    def described_in(words: str) -> bool:
        return re.search(r'aria-label="[^"]*?\d[\d,]* ' + re.escape(words), html) is not None

    if currency in CURRENCY_WORDS and described_in(CURRENCY_WORDS[currency]):
        return
    others = [code for code, words in CURRENCY_WORDS.items() if code != currency and described_in(words)]
    if others:
        raise WrongCurrency(f"Google answered in {others[0]} instead of {currency}")


def read_flights(script_text: str, currency: str) -> list[dict]:
    """Every flight in the page's data script: Google's "Best" list (data[2]) and its other flights (data[3]).

    Same fields as gf-search's page reader, which keeps only the first flight per airline and departure
    time and so hides other connections from the same first flight, often cheaper ones (TP-03 A3).
    """
    import rjsonc
    from gf_search._utils import _fmt_date, _fmt_time

    try:
        data = rjsonc.loads(script_text.split("data:", 1)[1].rsplit(",", 1)[0])
    except Exception:
        return []

    def at(leg: list, index: int, default=None):
        return leg[index] if len(leg) > index else default

    flights = []
    for index in (2, 3):
        sections = data[index] if index < len(data) and isinstance(data[index], list) else []
        for section in sections:
            for item in section if isinstance(section, list) else []:
                try:
                    flight, price = item[0], item[1][0][1]
                    carriers, segments = [], []
                    for leg in flight[2]:
                        if not isinstance(leg, list):
                            continue
                        info = leg[22] if len(leg) > 22 and isinstance(leg[22], list) else []
                        if info and info[0]:
                            carriers.append(info[0])
                        segments.append({
                            "from": at(leg, 3, ""),
                            "to": at(leg, 6, ""),
                            "flight_no": f"{info[0]}{info[1]}" if len(info) >= 2 and info[0] and info[1] else "",
                            "departure": f"{_fmt_date(at(leg, 20))} {_fmt_time(at(leg, 8))}".strip(),
                            "arrival": f"{_fmt_date(at(leg, 21))} {_fmt_time(at(leg, 10))}".strip(),
                            "duration_min": at(leg, 11, 0),
                            "plane": at(leg, 17, ""),
                        })
                    flights.append({
                        "airlines": list(dict.fromkeys(carriers)) or ([flight[0]] if flight[0] else []),
                        "price": f"{currency} {price}" if price is not None else "",
                        "stops": max(0, len(segments) - 1),
                        "segments": segments,
                    })
                except (IndexError, TypeError, KeyError):
                    continue
    return flights


def _price_of(flight: dict) -> int:
    try:
        return int(str(flight.get("price") or "").split()[-1])
    except (IndexError, ValueError):
        return 10**9


class GooglePage:
    def __init__(self, http_get: Optional[Callable[[str, dict], str]] = None, pause_s: Optional[float] = None):
        self._get = http_get or _http_get
        # A short pause between reads of the real page, as gf-search does; none for saved pages in tests.
        self._pause_s = pause_s if pause_s is not None else (1.5 if http_get is None else 0.0)

    def search(self, *, origin: str, destination: str, departure_date: str, return_date: Optional[str] = None,
               adults: int = 1, travel_class: str = "economy", max_results: Optional[int] = None,
               currency: str = "INR", max_stops: Optional[int] = None,
               selected_segments: Optional[list[dict]] = None) -> list[dict]:
        from selectolax.lexbor import LexborHTMLParser

        tfs = build_tfs(origin, destination, departure_date, return_date, adults, _SEAT.get(travel_class, 1), selected_segments)
        params = {"tfs": tfs, "tfu": "EgIIACIA", "hl": "en", "gl": "IN", "curr": currency}

        merged: dict[tuple, dict] = {}
        for read in range(MAX_READS):
            if read and self._pause_s:
                time.sleep(self._pause_s)
            try:
                html = self._get(SEARCH_URL, params)
                check_currency(html, currency)
            except Exception:
                if merged:
                    break  # keep the flights already read
                raise
            script = LexborHTMLParser(html).css_first(r"script.ds\:1")
            added = 0
            for flight in read_flights(script.text(), currency) if script else []:
                key = (
                    tuple(flight.get("airlines") or []),
                    tuple((segment.get("flight_no"), segment.get("departure")) for segment in flight.get("segments") or []),
                )
                if key not in merged:
                    merged[key] = flight
                    added += 1
                elif _price_of(flight) < _price_of(merged[key]):
                    merged[key] = flight
            if read and not added:
                break

        flights = list(merged.values())
        if selected_segments:
            # After an outbound flight is chosen, Google lists the flights home.
            flights = [f for f in flights if f.get("segments") and f["segments"][0].get("from") == destination]
        if max_stops is not None:
            flights = [f for f in flights if f.get("stops", 0) <= max_stops]
        return flights
