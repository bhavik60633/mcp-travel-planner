"""TP-01 F1: /plan-trip keeps working (the AI model is simulated)."""

from __future__ import annotations

from fastapi.testclient import TestClient

BODY = {
    "destination": "Dubai",
    "num_days": 5,
    "budget": 50000,
    "currency": "INR",
    "num_travelers": 2,
    "trip_type": "Standard",
    "group_type": "Couple",
    "preferences": "General sightseeing and local experiences.",
}


def test_F1_plan_trip_returns_the_itinerary_for_the_same_request_body(monkeypatch):
    import main

    received = []

    def fake_planner(data):
        received.append(data)
        return "## Day 1: Old Dubai\nWalk along the Creek."

    monkeypatch.setattr(main, "run_travel_planner", fake_planner)

    with TestClient(main.app) as client:
        r = client.post("/plan-trip", json=BODY)

    assert r.status_code == 200
    assert r.json() == {"status": "success", "itinerary": "## Day 1: Old Dubai\nWalk along the Creek."}
    assert received == [BODY]


def test_F1_planner_failure_is_a_500(monkeypatch):
    import main

    def broken_planner(data):
        raise RuntimeError("model unavailable")

    monkeypatch.setattr(main, "run_travel_planner", broken_planner)

    with TestClient(main.app) as client:
        r = client.post("/plan-trip", json=BODY)

    assert r.status_code == 500


def test_F1_health_check_and_browser_access_from_the_local_website(api_client):
    assert api_client.get("/").json() == {"status": "ok"}

    preflight = api_client.options(
        "/api/flights",
        headers={"Origin": "http://localhost:8080", "Access-Control-Request-Method": "GET"},
    )
    assert preflight.status_code == 200
    assert preflight.headers.get("access-control-allow-origin") in ("*", "http://localhost:8080")
