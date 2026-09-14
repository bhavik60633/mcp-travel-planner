"""TP-05 LIVE tests: real calls. Run with `pytest --live -m live`.

A11: a real Jaipur itinerary's visits are at times Google lists the places as open, or labelled (needs OPENAI_API_KEY and GOOGLE_MAPS_API_KEY).
B8: real Delhi travel times: every trip has a car time, and at least one has a metro route (needs both keys).
D7: real Goa stays within ₹3,000 a night (needs AIRBNB_IGNORE_ROBOTS_TXT=1).
"""

from __future__ import annotations

import os
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.live

LABELLED = {"closed_at_time", "closed_all_day", "closed_some_days"}
OPEN = {"open", "time_changed", "replaced", "open_24_hours", "hours_not_listed"}


def needs_keys():
    missing = [name for name in ("OPENAI_API_KEY", "GOOGLE_MAPS_API_KEY") if not os.environ.get(name)]
    if missing:
        pytest.skip(f"{' and '.join(missing)} isn't set on this PC")


def plan(destination: str, days: int, preferences: str) -> dict:
    import main

    trip = {
        "destination": destination, "num_days": days, "budget": 45000, "currency": "INR", "num_travelers": 2,
        "trip_type": "Standard", "group_type": "Couple", "preferences": preferences,
        "start_date": (date.today() + timedelta(days=10)).isoformat(),
    }
    with TestClient(main.app) as client:
        r = client.post("/plan-trip", json=trip)
    assert r.status_code == 200, r.text
    return r.json()


def test_A11_live_visits_are_at_times_the_places_are_open_or_labelled():
    needs_keys()

    body = plan("Jaipur", 3, "Forts, museums, markets and local food.")

    visits = body.get("visits") or []
    print(f"\nLIVE A11 Jaipur: {[(v['day'], v['start'], v['end'], v['place'], v['status'], v['label']) for v in visits]}")
    assert len(visits) >= 6, "the AI wrote fewer than 6 timed visits"
    for visit in visits:
        assert visit["status"] in OPEN | LABELLED, visit
        if visit["status"] in LABELLED:
            assert visit["label"], visit
        assert f"{visit['start']}–{visit['end']}: **{visit['place']}**" in body["itinerary"], visit


def test_B8_live_delhi_travel_times_include_a_metro_route():
    needs_keys()

    body = plan("New Delhi", 2, "Monuments across the city, travelling by metro where possible.")

    travel = [leg for leg in body.get("travel") or [] if leg["status"] == "ok"]
    print(f"\nLIVE B8 Delhi: {[(leg['from'], leg['to'], leg['car'], leg['transit'] and leg['transit']['summary']) for leg in travel]}")
    assert travel, "no travel times came back"
    assert all(leg["car"] for leg in travel)
    assert any(leg["transit"] and leg["transit"]["summary"].startswith("Metro") and leg["transit"]["lines"] for leg in travel)


def test_D7_live_goa_stays_within_3000_a_night():
    if os.environ.get("AIRBNB_IGNORE_ROBOTS_TXT") != "1":
        pytest.skip("Airbnb stays are off: AIRBNB_IGNORE_ROBOTS_TXT=1 isn't set on this PC")
    import main

    checkin = date.today() + timedelta(days=30)
    with TestClient(main.app) as client:
        r = client.get("/api/stays", params={
            "place": "Goa, India", "checkin": checkin.isoformat(), "checkout": (checkin + timedelta(days=5)).isoformat(),
            "adults": 2, "max_per_night": 3000,
        })

    assert r.status_code == 200, r.text
    stays = r.json()["stays"]
    print(f"\nLIVE D7 Goa: {len(stays)} stays, per night {sorted(stay['price_per_night'] for stay in stays)}")
    assert stays, "no stays within ₹3,000 a night"
    assert all(stay["price_per_night"] is not None and stay["price_per_night"] <= 3000 for stay in stays)
