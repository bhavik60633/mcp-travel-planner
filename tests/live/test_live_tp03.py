"""TP-03 LIVE tests: real calls. Run with `pytest --live -m live`.

A2: Yori's cheapest and cheapest non-stop flights match Google Flights' own page, read
    independently from the flight descriptions Google shows (not Yori's page reader).
B3: nearby-day prices from Travelpayouts (skipped until AVIASALES_API_TOKEN is set).
E5: real Airbnb stays (skipped until AIRBNB_IGNORE_ROBOTS_TXT=1 is allowed).
"""

from __future__ import annotations

import os
import re
import time
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.live

CURRENCY_WORDS = {"INR": "Indian rupees", "USD": "US dollars"}


def google_visible_flights(origin: str, destination: str, depart: str, currency: str, reads: int = 3) -> set[tuple[int, str, str, int]]:
    """(price, airline, departure HH:MM, stops) for every flight described on Google Flights' page.

    Google's page shows a slightly different set of flights on each request (seen on 14 Sep 2026: the
    $244 IndiGo 6E 3 Delhi -> London non-stop was missing from one read), so the page is read a few
    times and the flights combined.
    """
    flights = set()
    for read in range(reads):
        if read:
            time.sleep(1.5)
        flights |= _google_page_flights(origin, destination, depart, currency)
    return flights


def _google_page_flights(origin: str, destination: str, depart: str, currency: str) -> set[tuple[int, str, str, int]]:
    from gf_search.builder import build_tfs
    from gf_search.fetcher import _make_client

    page = _make_client().get(
        "https://www.google.com/travel/flights/search",
        params={"tfs": build_tfs(origin, destination, depart), "tfu": "EgIIACIA", "hl": "en", "gl": "IN", "curr": currency},
    )
    # Google writes "Non-stop"/"1:00 pm" or "Nonstop"/"1:00 PM" depending on the English variant.
    label = re.compile(
        r'aria-label="From ([\d,]+) ' + CURRENCY_WORDS[currency] + r'\. (Non-?stop|\d+ stops?) flight with ([^."]+)\. '
        r'Leaves [^"]*? at (\d{1,2}):(\d{2})[\s ]?([ap]m)',
        re.IGNORECASE,
    )
    flights = set()
    for m in label.finditer(page.text):
        hour = int(m.group(4)) % 12 + (12 if m.group(6).lower() == "pm" else 0)
        stops = 0 if m.group(2).lower().startswith("non") else int(m.group(2).split()[0])
        flights.add((int(m.group(1).replace(",", "")), m.group(3), f"{hour:02d}:{m.group(5)}", stops))
    return flights


def same_airline(google_name: str, yori_name: str) -> bool:
    return google_name.split()[0].lower() == yori_name.split()[0].lower()


def matches_google(offer: dict, google: set) -> bool:
    departure = offer["outbound"]["departure"][11:16]
    return any(
        abs(price - offer["price"]) <= 1 and same_airline(airline, offer["airlines"][0]) and time_ == departure and stops == offer["stops"]
        for price, airline, time_, stops in google
    )


@pytest.mark.parametrize("currency", ["INR", "USD"])
@pytest.mark.parametrize("origin, destination", [("DEL", "BOM"), ("BOM", "DXB"), ("DEL", "LHR")])
def test_A2_live_cheapest_flights_match_google_flights(origin, destination, currency):
    import main

    depart = (date.today() + timedelta(days=30)).isoformat()
    with TestClient(main.app) as client:
        r = client.get("/api/flights", params={"from": origin, "to": destination, "depart": depart, "currency": currency, "sort": "cheapest"})
    time.sleep(1.5)
    google = google_visible_flights(origin, destination, depart, currency)

    if r.status_code == 503 or not google:
        pytest.skip(f"Google isn't answering from this PC right now (Yori HTTP {r.status_code}, {len(google)} flights on Google's page)")
    assert r.status_code == 200, r.text
    offers = r.json()["offers"]
    assert offers, "Yori found no flights but Google lists some"

    cheapest_google = min(price for price, *_ in google)
    assert abs(offers[0]["price"] - cheapest_google) <= 1, (offers[0]["price"], cheapest_google)
    assert matches_google(offers[0], google), offers[0]["outbound"]

    google_nonstop = [flight for flight in google if flight[3] == 0]
    if google_nonstop:
        yori_nonstop = next(offer for offer in offers if offer["stops"] == 0)
        assert abs(yori_nonstop["price"] - min(price for price, *_ in google_nonstop)) <= 1
        assert matches_google(yori_nonstop, google)
    print(f"\nLIVE A2 {origin}->{destination} {depart} {currency}: cheapest {offers[0]['price']} matches Google ({len(google)} flights on the page)")


def test_B3_live_nearby_day_prices():
    if not os.environ.get("AVIASALES_API_TOKEN"):
        pytest.skip("AVIASALES_API_TOKEN (Travelpayouts) isn't set on this PC")
    import main

    depart = date.today() + timedelta(days=30)
    with TestClient(main.app) as client:
        r = client.get("/api/flights/dates", params={
            "from": "BOM", "to": "DXB", "currency": "INR",
            "start": (depart - timedelta(days=14)).isoformat(), "end": (depart + timedelta(days=14)).isoformat(),
        })

    assert r.status_code == 200, r.text
    assert len(r.json()["days"]) >= 10


def test_E5_live_airbnb_stays():
    if os.environ.get("AIRBNB_IGNORE_ROBOTS_TXT") != "1":
        pytest.skip("Airbnb stays are off: Airbnb's robots.txt blocks automated searches unless AIRBNB_IGNORE_ROBOTS_TXT=1 is allowed")
    import main

    checkin = date.today() + timedelta(days=30)
    with TestClient(main.app) as client:
        r = client.get("/api/stays", params={"place": "Goa, India", "checkin": checkin.isoformat(), "checkout": (checkin + timedelta(days=5)).isoformat(), "adults": 2})

    assert r.status_code == 200, r.text
    priced = [stay for stay in r.json()["stays"] if stay["total_price"]]
    assert len(priced) >= 5
