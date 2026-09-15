"""TP-01 section C: the flights API (C1-C9, C11, C12).

Flight sources are simulated, so nothing here contacts Google or Travelpayouts.
C10 is in test_airports.py and C13 in live/test_live.py.
"""

from __future__ import annotations

import copy
import json
import logging
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta

import httpx
import pytest

from helpers import (
    UNAVAILABLE,
    ConcurrencyTracker,
    FakeClock,
    FakeDateSource,
    FakeFliClient,
    FakeSource,
    decode_tfs,
    fli_result,
    load_fixture,
    make_offer,
)

ISO_MINUTE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}$")
FLIGHT_NO = re.compile(r"^[A-Z0-9]{2} \d{1,4}[A-Z]?$")
AIRLINE_CODE = re.compile(r"^[A-Z0-9]{2}$")

DEFAULTS = {
    "from": "BOM",
    "to": "DXB",
    "depart": "2026-10-20",
    "adults": "1",
    "cabin": "economy",
    "currency": "INR",
}

# A Singapore -> Bengaluru one-way answer in gf-search's shape, for round trips.
RETURN_ONE_WAY = [
    {
        "airlines": ["SQ"],
        "price": "INR 21450",
        "stops": 0,
        "segments": [
            {"from": "SIN", "to": "BLR", "flight_no": "SQ510", "departure": "2026-12-17 20:15",
             "arrival": "2026-12-17 22:05", "duration_min": 260, "plane": "Airbus A350"},
        ],
        "source": "gf_search",
    },
    {
        "airlines": ["UL"],
        "price": "INR 19880",
        "stops": 1,
        "segments": [
            {"from": "SIN", "to": "CMB", "flight_no": "UL309", "departure": "2026-12-17 19:40",
             "arrival": "2026-12-17 21:05", "duration_min": 235, "plane": "Airbus A330"},
            {"from": "CMB", "to": "BLR", "flight_no": "UL1173", "departure": "2026-12-18 07:00",
             "arrival": "2026-12-18 08:25", "duration_min": 85, "plane": "Airbus A320"},
        ],
        "source": "gf_search",
    },
]

# fli's return leg for a Delhi <-> Paris round trip.
FLI_RETURN_LEG = {
    "duration": 475,
    "stops": 0,
    "legs": [
        {
            "departure_airport": {"code": "CDG"},
            "arrival_airport": {"code": "DEL"},
            "departure_time": "2026-11-16T10:40:00",
            "arrival_time": "2026-11-16T23:05:00",
            "duration": 475,
            "airline": {"code": "AF"},
            "flight_number": "226",
            "aircraft": "Boeing 777",
        }
    ],
    "price": None,
    "currency": "INR",
    "layovers": [],
}


def flights(client, **changes):
    params = {**DEFAULTS, **changes}
    return client.get("/api/flights", params={k: v for k, v in params.items() if v is not None})


def gf_source(search_fn):
    from flights.sources import GfSearchSource

    return GfSearchSource(search_fn=search_fn)


# --------------------------------------------------------------------------- C1


def test_C1_one_way_search_returns_complete_flights_cheapest_first(make_client):
    raw = load_fixture("gf-DEL-CDG-2026-11-09-max100.json")
    seen = []

    def search_fn(**kwargs):
        seen.append(kwargs)
        return copy.deepcopy(raw)

    client = make_client(sources=[gf_source(search_fn)])
    # Cheapest first is asked for explicitly: the default order is "Best" since TP-03 A4 (frozen 14 Sep 2026).
    r = flights(client, **{"from": "DEL", "to": "CDG", "depart": "2026-11-09", "sort": "cheapest"})

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "gf-search"
    assert body["cached"] is False
    assert body["query"] == {
        "from": "DEL", "to": "CDG", "depart": "2026-11-09", "return": None, "adults": 1,
        "cabin": "economy", "currency": "INR", "stops": "any", "trip": "one_way",
    }
    offers = body["offers"]
    assert body["count"] == len(offers) == 12
    prices = [offer["price"] for offer in offers]
    assert prices == sorted(prices)

    for offer in offers:
        assert isinstance(offer["price"], int) and offer["price"] > 0
        assert offer["currency"] == "INR"
        assert offer["airlines"]
        assert not any(AIRLINE_CODE.match(name) for name in offer["airlines"]), offer["airlines"]
        assert offer["booking_url"].startswith("https://www.google.com/travel/flights")
        assert offer["return"] is None
        journey = offer["outbound"]
        assert (journey["from"], journey["to"]) == ("DEL", "CDG")
        assert ISO_MINUTE.match(journey["departure"]) and ISO_MINUTE.match(journey["arrival"])
        assert journey["departure"].startswith("2026-11-09")
        assert journey["stops"] == len(journey["segments"]) - 1 == len(journey["layovers"])
        assert journey["duration_min"] == sum(s["duration_min"] for s in journey["segments"]) + sum(
            stop["duration_min"] for stop in journey["layovers"]
        )
        for segment in journey["segments"]:
            assert FLIGHT_NO.match(segment["flight_number"]), segment
            assert not AIRLINE_CODE.match(segment["airline"]), segment
            assert ISO_MINUTE.match(segment["departure"]) and ISO_MINUTE.match(segment["arrival"])
        for stop in journey["layovers"]:
            assert re.fullmatch(r"[A-Z]{3}", stop["airport"]) and stop["duration_min"] > 0

    cheapest = offers[0]
    assert cheapest["price"] == 25994
    assert cheapest["airlines"] == ["Etihad Airways"]
    out = cheapest["outbound"]
    assert [s["flight_number"] for s in out["segments"]] == ["EY 219", "EY 33"]
    assert (out["departure"], out["arrival"]) == ("2026-11-09T04:25", "2026-11-09T18:35")
    assert out["layovers"] == [{"airport": "AUH", "duration_min": 430}]
    assert out["duration_min"] == 1120  # the same total fli reported for this flight

    overnight = next(offer for offer in offers if offer["price"] == 28349)
    assert overnight["airlines"] == ["IndiGo", "Qatar Airways"]
    assert overnight["outbound"]["arrival"] == "2026-11-10T06:35"
    assert overnight["outbound"]["layovers"] == [{"airport": "DOH", "duration_min": 440}]

    # gf-search has no booking page, so Book opens Google Flights for this
    # route and date with the flight's airline filtered.
    assert cheapest["booking_type"] == "route"
    tfs = decode_tfs(cheapest["booking_url"])
    for part in (b"DEL", b"CDG", b"2026-11-09", b"EY"):
        assert part in tfs, part

    assert seen[0]["origin"] == "DEL" and seen[0]["currency"] == "INR"


def test_C1_fli_flights_carry_their_exact_google_booking_page(make_client):
    from flights.sources import FliSource

    fixture = load_fixture("fli-flights-DEL-CDG-2026-11-09.json")
    fake = FakeFliClient(results=[fli_result(f) for f in fixture["flights"][:20]])
    client = make_client(sources=[FliSource(client=fake)])

    r = flights(client, **{"from": "DEL", "to": "CDG", "depart": "2026-11-09", "sort": "cheapest"})

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "fli"
    assert body["count"] == 20
    first = body["offers"][0]
    assert first["price"] == 25994
    assert first["airlines"] == ["Etihad Airways"]
    assert [s["flight_number"] for s in first["outbound"]["segments"]] == ["EY 219", "EY 33"]
    assert first["outbound"]["layovers"] == [{"airport": "AUH", "duration_min": 430}]
    assert first["outbound"]["duration_min"] == 1120
    assert first["booking_type"] == "exact"
    assert first["booking_url"].startswith("https://www.google.com/travel/flights/booking")
    assert fake.searches[0]["currency"] == "INR"


# --------------------------------------------------------------------------- C2


def test_C2_round_trip_search_lists_outbound_options_with_round_trip_totals(make_client):
    # Changed by TP-03 D4 (frozen 14 Sep 2026): the return flight is chosen in a second step
    # (/api/flights/returns, tested in test_tp03_flights.py C1), so every pair is exact.
    outbound_rt = load_fixture("gf-BLR-SIN-2026-12-10-rt.json")

    def search_fn(**kw):
        assert kw["origin"] == "BLR" and kw.get("return_date") == "2026-12-17", kw
        return copy.deepcopy(outbound_rt)

    client = make_client(sources=[gf_source(search_fn)])
    r = flights(client, **{"from": "BLR", "to": "SIN", "depart": "2026-12-10", "return": "2026-12-17", "sort": "cheapest"})

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["query"]["trip"] == "round_trip"
    assert body["query"]["return"] == "2026-12-17"
    assert [offer["price"] for offer in body["offers"]] == [39302, 40310, 40310, 46125, 48406]
    for offer in body["offers"]:
        assert (offer["outbound"]["from"], offer["outbound"]["to"]) == ("BLR", "SIN")
        assert offer["outbound"]["departure"].startswith("2026-12-10")
        assert offer["return"] is None
        tfs = decode_tfs(offer["booking_url"])
        assert b"2026-12-10" in tfs and b"2026-12-17" in tfs


def test_C2_fli_round_trips_list_each_outbound_flight_with_its_total(make_client):
    from flights.sources import FliSource

    fixture = load_fixture("fli-flights-DEL-CDG-2026-11-09.json")
    pair = (fli_result(fixture["flights"][0]), fli_result(FLI_RETURN_LEG))
    client = make_client(sources=[FliSource(client=FakeFliClient(results=[pair]))])

    r = flights(client, **{"from": "DEL", "to": "CDG", "depart": "2026-11-09", "return": "2026-11-16"})

    assert r.status_code == 200, r.text
    offer = r.json()["offers"][0]
    assert offer["price"] == 25994
    assert offer["outbound"]["to"] == "CDG"
    assert offer["return"] is None


# --------------------------------------------------------------------------- C3


def test_C3_different_searches_never_return_each_others_results(make_client):
    def respond(q):
        return [
            make_offer(
                origin=q.origin,
                destination=q.destination,
                depart=q.depart.isoformat(),
                return_date=q.return_date.isoformat() if q.return_date else None,
                currency=q.currency,
                price=1000 + q.adults,
            )
        ]

    source = FakeSource("gf-search", respond=respond)
    client = make_client(sources=[source])
    variants = [
        {},
        {"to": "AUH"},
        {"from": "DEL"},
        {"depart": "2026-10-21"},
        {"return": "2026-10-27"},
        {"currency": "USD"},
        {"adults": "2"},
        {"cabin": "business"},
        {"stops": "0"},
    ]

    for change in variants:
        params = {**DEFAULTS, **change}
        r = client.get("/api/flights", params=params)
        assert r.status_code == 200, (change, r.text)
        body = r.json()
        assert body["cached"] is False, change
        q = body["query"]
        assert q["from"] == params["from"] and q["to"] == params["to"]
        assert q["depart"] == params["depart"] and q["return"] == params.get("return")
        assert str(q["adults"]) == params["adults"]
        assert q["cabin"] == params["cabin"] and q["currency"] == params["currency"]
        assert q["stops"] == params.get("stops", "any")
        assert q["trip"] == ("round_trip" if "return" in params else "one_way")
        offer = body["offers"][0]
        assert offer["currency"] == params["currency"]
        assert (offer["outbound"]["from"], offer["outbound"]["to"]) == (params["from"], params["to"])
        assert offer["outbound"]["departure"].startswith(params["depart"])

    assert len(source.calls) == len(variants)
    distinct = {
        (c.origin, c.destination, c.depart, c.return_date, c.adults, c.cabin, c.currency, c.max_stops)
        for c in source.calls
    }
    assert len(distinct) == len(variants)


def test_C3_every_search_field_reaches_gf_search(make_client):
    seen = []

    def search_fn(**kw):
        seen.append(kw)
        return []

    client = make_client(sources=[gf_source(search_fn)])
    flights(
        client,
        **{"from": "DEL", "to": "LHR", "depart": "2026-11-15", "return": "2026-11-22",
           "adults": "3", "cabin": "premium_economy", "currency": "GBP", "stops": "1"},
    )

    kw = seen[0]
    assert (kw["origin"], kw["destination"]) == ("DEL", "LHR")
    assert (kw["departure_date"], kw["return_date"]) == ("2026-11-15", "2026-11-22")
    assert kw["adults"] == 3
    assert kw["travel_class"] == "premium-economy"
    assert kw["currency"] == "GBP"
    assert kw["max_stops"] == 1
    assert kw["max_results"] >= 50


# --------------------------------------------------------------------------- C4


@pytest.mark.parametrize(
    "change, message",
    [
        ({"from": "DE1"}, "From must be a 3-letter airport code, like DEL."),
        ({"to": "DX"}, "To must be a 3-letter airport code, like DEL."),
        ({"from": "XQX"}, "Unknown airport code: XQX."),
        ({"from": "DXB"}, "From and To must be different airports."),
        ({"depart": "2026-09-13"}, "Departure date can't be in the past."),
        ({"depart": "20-10-2026"}, "Dates must look like 2026-10-20."),
        ({"return": "2026-10-19"}, "Return date can't be before the departure date."),
        ({"adults": "0"}, "Adults must be between 1 and 9."),
        ({"adults": "10"}, "Adults must be between 1 and 9."),
        ({"adults": "two"}, "Adults must be between 1 and 9."),
        ({"currency": "JPY"}, "Currency must be one of INR, USD, EUR, GBP."),
        ({"cabin": "luxury"}, "Cabin must be one of economy, premium_economy, business, first."),
        ({"stops": "5"}, "Stops must be one of any, 0, 1, 2."),
        ({"from": None}, "From, To and departure date are required."),
    ],
)
def test_C4_invalid_input_gets_a_plain_400_message(make_client, change, message):
    source = FakeSource("gf-search")
    client = make_client(sources=[source])

    r = flights(client, **change)

    assert r.status_code == 400
    assert r.json() == {"error": "invalid_request", "message": message}
    assert source.calls == []


def test_C4_lowercase_codes_today_and_defaults_are_accepted(make_client):
    client = make_client(sources=[FakeSource("gf-search", offers=[make_offer()])])

    r = client.get("/api/flights", params={"from": "bom", "to": "dxb", "depart": "2026-09-14"})

    assert r.status_code == 200, r.text
    assert r.json()["query"] == {
        "from": "BOM", "to": "DXB", "depart": "2026-09-14", "return": None, "adults": 1,
        "cabin": "economy", "currency": "INR", "stops": "any", "trip": "one_way",
    }


# --------------------------------------------------------------------------- C5


def test_C5_identical_search_within_10_minutes_comes_from_the_cache(make_client):
    clock = FakeClock()
    source = FakeSource("gf-search", offers=[make_offer()])
    client = make_client(sources=[source], clock=clock)

    first = flights(client).json()
    clock.advance(599)
    second = flights(client).json()

    assert first["cached"] is False
    assert second["cached"] is True
    assert second["offers"] == first["offers"]
    assert second["source"] == first["source"]
    assert len(source.calls) == 1

    clock.advance(2)  # 601 seconds after the first search
    third = flights(client).json()
    assert third["cached"] is False
    assert len(source.calls) == 2


def test_C5_answers_with_no_flights_are_not_cached(make_client):
    source = FakeSource("gf-search", offers=[])
    client = make_client(sources=[source])

    assert flights(client).json()["cached"] is False
    assert flights(client).json()["cached"] is False
    assert len(source.calls) == 2


# --------------------------------------------------------------------------- C6


def test_C6_blocked_source_gives_503_and_nothing_is_cached(make_client):
    from flights.sources import SourceUnavailable

    source = FakeSource("gf-search", error=SourceUnavailable("Google refused the request"))
    client = make_client(sources=[source])

    r = flights(client)
    assert r.status_code == 503
    assert r.json()["error"] == "source_unavailable"
    assert r.json()["message"] == UNAVAILABLE

    source.error = None
    source.offers = [make_offer()]
    again = flights(client)
    assert again.status_code == 200
    assert again.json()["cached"] is False
    assert again.json()["count"] == 1
    assert len(source.calls) == 2


def test_C6_a_crashing_source_counts_as_unavailable(make_client):
    client = make_client(sources=[FakeSource("gf-search", error=RuntimeError("parser crashed"))])

    r = flights(client)

    assert r.status_code == 503
    assert r.json()["message"] == UNAVAILABLE
    assert "parser crashed" not in r.text


def test_C6_no_flights_is_a_200_with_count_0(make_client):
    client = make_client(sources=[FakeSource("gf-search", offers=[])])

    r = flights(client)

    assert r.status_code == 200
    assert r.json()["count"] == 0
    assert r.json()["offers"] == []


# --------------------------------------------------------------------------- C7


def test_C7_a_blocked_source_hands_over_to_the_next_one(make_client):
    from flights.sources import SourceUnavailable

    gf = FakeSource("gf-search", error=SourceUnavailable("blocked"))
    fli = FakeSource("fli", complete=True, offers=[make_offer(price=100), make_offer(price=120, flight_number="6E 1453")])
    swoop = FakeSource("swoop", complete=True, offers=[make_offer()])
    client = make_client(sources=[gf, fli, swoop])

    body = flights(client).json()

    assert body["source"] == "fli"
    assert body["count"] == 2
    assert body["attempts"] == [
        {"source": "gf-search", "result": "unavailable"},
        {"source": "fli", "result": "ok", "count": 2},
    ]
    assert swoop.calls == []  # fli returned the full list, so swoop isn't asked


def test_C7_empty_answers_hand_over_to_the_next_source(make_client):
    gf = FakeSource("gf-search", offers=[])
    fli = FakeSource("fli", complete=True, offers=[])
    swoop = FakeSource("swoop", complete=True, offers=[make_offer()])
    client = make_client(sources=[gf, fli, swoop])

    body = flights(client).json()

    assert body["source"] == "swoop"
    assert [a["result"] for a in body["attempts"]] == ["empty", "empty", "ok"]


def test_C7_the_fuller_list_wins_when_two_sources_answer(make_client):
    three = [make_offer(price=p, flight_number=f"6E {p}") for p in (100, 110, 120)]
    five = [
        make_offer(price=p, flight_number=f"AI {p}", airline_code="AI", airline="Air India")
        for p in (90, 130, 140, 150, 160)
    ]

    client = make_client(sources=[FakeSource("gf-search", offers=three), FakeSource("fli", complete=True, offers=five)])
    body = flights(client).json()
    assert (body["source"], body["count"]) == ("fli", 5)

    client = make_client(sources=[FakeSource("gf-search", offers=five), FakeSource("fli", complete=True, offers=three)])
    body = flights(client).json()
    assert (body["source"], body["count"]) == ("gf-search", 5)


def test_C7_source_order_and_travelpayouts_only_with_a_token():
    from flights.sources import build_date_sources, build_sources

    assert [s.name for s in build_sources({})] == ["gf-search", "fli", "swoop"]
    assert [s.complete for s in build_sources({})] == [False, True, True]
    assert [s.name for s in build_sources({"AVIASALES_API_TOKEN": "   "})] == ["gf-search", "fli", "swoop"]
    assert [s.name for s in build_sources({"AVIASALES_API_TOKEN": "tp-test"})] == [
        "gf-search", "fli", "swoop", "travelpayouts",
    ]
    assert [s.name for s in build_date_sources({})] == ["fli"]
    assert [s.name for s in build_date_sources({"AVIASALES_API_TOKEN": "tp-test"})] == ["fli", "travelpayouts"]


def test_C7_swoop_results_are_normalised(make_client):
    from swoop import Itinerary, SearchResult, Segment, TripLeg, TripOption

    from flights.sources import SwoopSource

    option = TripOption(
        selector="sel-1",
        price=15082,
        currency="INR",
        legs=[
            TripLeg(
                origin="BOM",
                destination="DXB",
                date="2026-10-20",
                itinerary=Itinerary(
                    airline_code="6E",
                    airline_names=["IndiGo"],
                    segments=[
                        Segment(
                            airline="6E", airline_name="IndiGo", flight_number="1451",
                            departure_airport_code="BOM", arrival_airport_code="DXB",
                            departure_date=(2026, 10, 20), arrival_date=(2026, 10, 20),
                            departure_time=(8, 10), arrival_time=(9, 40), travel_time=180,
                            aircraft="Airbus A321neo",
                        )
                    ],
                    layovers=[],
                    travel_time=180,
                    stop_count=0,
                ),
            )
        ],
    )
    client = make_client(sources=[SwoopSource(search_fn=lambda *a, **kw: SearchResult(results=[option]))])

    body = flights(client).json()

    assert body["source"] == "swoop"
    offer = body["offers"][0]
    assert offer["price"] == 15082 and offer["airlines"] == ["IndiGo"]
    segment = offer["outbound"]["segments"][0]
    assert segment["flight_number"] == "6E 1451"
    assert (segment["departure"], segment["arrival"]) == ("2026-10-20T08:10", "2026-10-20T09:40")
    assert offer["booking_url"].startswith("https://www.google.com/travel/flights")


# --------------------------------------------------------------------------- C8


def test_C8_the_default_deadline_is_20_seconds_or_less():
    from flights.service import FlightService

    assert FlightService(sources=[]).deadline_s <= 20


def test_C8_hanging_sources_get_a_503_within_the_deadline(make_client):
    release = threading.Event()
    try:
        gf = FakeSource("gf-search", block=release)
        fli = FakeSource("fli", complete=True, block=release)
        client = make_client(sources=[gf, fli], deadline_s=1.0)

        started = time.monotonic()
        r = flights(client)
        elapsed = time.monotonic() - started

        assert r.status_code == 503
        assert r.json()["message"] == UNAVAILABLE
        assert elapsed < 3.0
    finally:
        release.set()


# --------------------------------------------------------------------------- C9


def test_C9_cheapest_days_gives_the_lowest_fare_per_day(make_client):
    days = FakeDateSource(
        days=[
            {"date": "2026-11-02", "price": 30100},
            {"date": "2026-11-01", "price": 25994},
            {"date": "2026-11-02", "price": 28100.4},
        ]
    )
    client = make_client(date_sources=[days])

    r = client.get(
        "/api/flights/dates",
        params={"from": "DEL", "to": "CDG", "start": "2026-11-01", "end": "2026-11-30", "currency": "EUR"},
    )

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "fake-dates"
    assert body["currency"] == "EUR"
    assert body["days"] == [{"date": "2026-11-01", "price": 25994}, {"date": "2026-11-02", "price": 28100}]
    q = days.calls[0]
    assert (q.origin, q.destination, q.start, q.end, q.currency, q.trip_days) == (
        "DEL", "CDG", date(2026, 11, 1), date(2026, 11, 30), "EUR", None,
    )


@pytest.mark.parametrize(
    "params, status, message",
    [
        ({"start": "2026-10-01", "end": "2026-12-01"}, 200, None),  # 62 days
        ({"start": "2026-10-01", "end": "2026-12-02"}, 400, "Date range can't be longer than 62 days."),
        ({"start": "2026-10-05", "end": "2026-10-04"}, 400, "End date can't be before the start date."),
        ({"start": "2026-09-13", "end": "2026-10-04"}, 400, "Start date can't be in the past."),
        ({"start": "2026-10-01", "end": "2026-10-10", "trip_days": "0"}, 400, "Trip length must be between 1 and 30 days."),
        ({"start": "2026-10-01", "end": "2026-10-10", "currency": "JPY"}, 400, "Currency must be one of INR, USD, EUR, GBP."),
    ],
)
def test_C9_date_range_rules(make_client, params, status, message):
    client = make_client(date_sources=[FakeDateSource(days=[])])

    r = client.get("/api/flights/dates", params={"from": "DEL", "to": "CDG", **params})

    assert r.status_code == status, r.text
    if message:
        assert r.json() == {"error": "invalid_request", "message": message}


def test_C9_round_trip_length_reaches_the_source(make_client):
    days = FakeDateSource(days=[])
    client = make_client(date_sources=[days])

    client.get("/api/flights/dates", params={"from": "DEL", "to": "CDG", "start": "2026-10-01", "end": "2026-10-10", "trip_days": "7"})

    assert days.calls[0].trip_days == 7


def test_C9_every_date_source_failing_gives_503(make_client):
    from flights.sources import SourceUnavailable

    client = make_client(date_sources=[FakeDateSource(error=SourceUnavailable("blocked"))])

    r = client.get("/api/flights/dates", params={"from": "DEL", "to": "CDG", "start": "2026-10-01", "end": "2026-10-10"})

    assert r.status_code == 503
    assert r.json()["message"] == UNAVAILABLE


def test_C9_fli_cheapest_days_are_normalised():
    from flights.models import DatesQuery
    from flights.sources import FliDateSource

    class DatePrice:
        def __init__(self, day, price):
            self.date = (datetime(2026, 11, day),)
            self.price = price
            self.currency = "INR"

    source = FliDateSource(client=FakeFliClient(results=[DatePrice(1, 25994.0), DatePrice(2, 27100.6)]))
    query = DatesQuery(
        origin="DEL", destination="CDG", start=date(2026, 11, 1), end=date(2026, 11, 2),
        trip_days=None, adults=1, cabin="economy", currency="INR",
    )

    assert source.search_dates(query) == [
        {"date": "2026-11-01", "price": 25994},
        {"date": "2026-11-02", "price": 27101},
    ]


# --------------------------------------------------------------------------- C11


def test_C11_identical_searches_arriving_together_share_one_request(make_client):
    source = FakeSource("gf-search", offers=[make_offer()], delay=0.5)
    client = make_client(sources=[source])

    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda _: flights(client), range(4)))

    assert all(r.status_code == 200 for r in responses)
    assert len(source.calls) == 1
    assert len({json.dumps(r.json()["offers"]) for r in responses}) == 1


def test_C11_only_one_live_google_request_runs_at_a_time(make_client):
    tracker = ConcurrencyTracker()

    def respond(q):
        return [make_offer(origin=q.origin, destination=q.destination)]

    gf = FakeSource("gf-search", delay=0.2, tracker=tracker, respond=respond)
    fli = FakeSource("fli", delay=0.2, tracker=tracker, complete=True, respond=respond)
    client = make_client(sources=[gf, fli])
    routes = [("BOM", "DXB"), ("DEL", "CDG"), ("BLR", "SIN"), ("IXL", "DEL")]

    with ThreadPoolExecutor(max_workers=4) as pool:
        responses = list(pool.map(lambda route: flights(client, **{"from": route[0], "to": route[1]}), routes))

    assert all(r.status_code == 200 for r in responses), [r.text for r in responses]
    assert tracker.max_active == 1
    assert len(gf.calls) == 4


# --------------------------------------------------------------------------- C12

TOKEN = "tp-test-token-9f8e7d6c5b4a"


def test_C12_the_token_never_appears_in_responses_or_logs(make_client, caplog):
    from flights.sources import TravelpayoutsSource

    caplog.set_level(logging.DEBUG)
    requests = []

    def handler(request):
        requests.append(request)
        # A badly behaved upstream that echoes the token back in its error.
        return httpx.Response(401, json={"error": f"Unauthorized: {request.headers.get('X-Access-Token')}"})

    source = TravelpayoutsSource(token=TOKEN, http_client=httpx.Client(transport=httpx.MockTransport(handler)))
    client = make_client(sources=[source])

    r = flights(client)

    assert r.status_code == 503
    assert requests and requests[0].headers["X-Access-Token"] == TOKEN
    assert TOKEN not in str(requests[0].url)
    assert TOKEN not in r.text
    assert TOKEN not in client.get("/api/health").text
    assert TOKEN not in repr(source)
    assert TOKEN not in caplog.text


def test_C12_travelpayouts_answers_get_a_partner_link_without_the_token(make_client, caplog):
    from flights.sources import TravelpayoutsSource

    caplog.set_level(logging.DEBUG)

    def handler(request):
        assert request.url.host == "api.travelpayouts.com"
        assert request.url.path == "/aviasales/v3/prices_for_dates"
        p = request.url.params
        assert (p["origin"], p["destination"], p["departure_at"], p["currency"]) == ("BOM", "DXB", "2026-10-20", "inr")
        return httpx.Response(
            200,
            json={
                "success": True,
                "currency": "inr",
                "data": [
                    {
                        "origin": "BOM", "destination": "DXB", "origin_airport": "BOM", "destination_airport": "DXB",
                        "price": 14990, "airline": "6E", "flight_number": "1451",
                        "departure_at": "2026-10-20T08:10:00+05:30", "return_at": "", "transfers": 0,
                        "return_transfers": 0, "duration": 180, "duration_to": 180, "duration_back": 0,
                        "link": "/search/BOM2010DXB1?t=6E17609472001760952600000180BOMDXB_abc&search_date=14092026",
                    }
                ],
            },
        )

    source = TravelpayoutsSource(
        token=TOKEN, marker="123456", http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    client = make_client(sources=[source])

    r = flights(client)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["source"] == "travelpayouts"
    offer = body["offers"][0]
    assert offer["price"] == 14990
    assert offer["airlines"] == ["IndiGo"]
    assert offer["outbound"]["departure"] == "2026-10-20T08:10"
    assert offer["outbound"]["segments"][0]["flight_number"] == "6E 1451"
    assert offer["booking_type"] == "partner"
    assert offer["booking_url"].startswith("https://www.aviasales.com/search/BOM2010DXB1")
    assert "marker=123456" in offer["booking_url"]
    assert TOKEN not in r.text
    assert TOKEN not in caplog.text
