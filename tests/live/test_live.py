"""LIVE tests: real calls. Run with `pytest --live -m live`.

C13: real flight searches (skipped with the reason if every source is blocking).
F7: one real itinerary from the AI model (skipped if OPENAI_API_KEY isn't set).
"""

from __future__ import annotations

import os
from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.live


@pytest.mark.parametrize("origin, destination", [("DEL", "BOM"), ("IXL", "DEL")])
def test_C13_live_one_way_search_finds_priced_flights(origin, destination):
    import main

    depart = (date.today() + timedelta(days=30)).isoformat()
    with TestClient(main.app) as client:
        r = client.get("/api/flights", params={"from": origin, "to": destination, "depart": depart, "currency": "INR"})

    body = r.json()
    attempts = body.get("attempts", [])
    if r.status_code == 503:
        pytest.skip(f"every flight source is blocking right now: {attempts}")

    assert r.status_code == 200, r.text
    assert body["count"] >= 1, f"no flights for {origin}->{destination} on {depart}; attempts: {attempts}"
    cheapest = body["offers"][0]
    assert cheapest["price"] > 0
    print(
        f"\nLIVE {origin}->{destination} {depart}: {body['count']} flights from {body['source']}, "
        f"cheapest {cheapest['currency']} {cheapest['price']} ({', '.join(cheapest['airlines'])})"
    )


def test_F7_live_itinerary_from_the_real_ai_model():
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY is not set on this PC")

    import main

    body = {
        "destination": "Jaipur", "num_days": 2, "budget": 20000, "currency": "INR", "num_travelers": 2,
        "trip_type": "Standard", "group_type": "Couple", "preferences": "Forts and local food.",
    }
    with TestClient(main.app) as client:
        r = client.post("/plan-trip", json=body, timeout=300)

    assert r.status_code == 200, r.text
    assert r.json()["status"] == "success"
    assert "Day 1" in r.json()["itinerary"]
