"""TP-04 B1–B5: every place in an itinerary is checked on Google Maps (Google and the AI simulated)."""

from __future__ import annotations

import logging
import threading
import time
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from helpers import FakeGooglePlaces

GOOGLE_KEY = "google-test-key-for-yori-place-checks-0000"
JAIPUR_TRIP = {
    "destination": "Jaipur",
    "num_days": 2,
    "budget": 40000,
    "currency": "INR",
    "num_travelers": 2,
    "trip_type": "Standard",
    "group_type": "Couple",
    "preferences": "Forts and food.",
}
OPEN_PLACES_PLAN = """A 2-day plan for Jaipur.

## Day 1: Pink City
- **Morning:** Start at **Hawa Mahal**, then rest at the **hotel**.
- **Evening:** Shop in the bazaars around **Hawa Mahal**.

## Day 2: Forts
- **Morning:** Explore **Amber Fort**.
- **Tip:** Carry water.
"""
CLOSED_PLACES_PLAN = """A 2-day plan for Jaipur.

## Day 1: Pink City
- Breakfast at **Old Café Nirvana**, then **Hawa Mahal**.

## Day 2: Evening
- Dinner at **Imaginary Rooftop**.
"""
HAWA_MAHAL = {
    "query": "Hawa Mahal",
    "status": "confirmed",
    "name": "Hawa Mahal",
    "address": "Hawa Mahal Rd, Badi Choupad, J.D.A. Market, Pink City, Jaipur, Rajasthan 302002, India",
    "maps_url": "https://maps.google.com/?cid=1001",
    "location": {"lat": 26.9239363, "lng": 75.8267438},
    "rating": 4.4,
    "reviews": 190000,
    "replaces": None,
    "reason": None,
}


@pytest.fixture
def places_client():
    import main
    from places.google import GooglePlaces
    from places.service import PlaceChecker, get_place_checker

    clients = []

    def _make(google, key=GOOGLE_KEY, deadline_s=10.0):
        client_google = GooglePlaces(api_key=key, http_client=httpx.Client(transport=httpx.MockTransport(google))) if key else None
        checker = PlaceChecker(google=client_google, deadline_s=deadline_s)
        main.app.dependency_overrides[get_place_checker] = lambda: checker
        client = TestClient(main.app)
        client.__enter__()
        client.checker = checker
        clients.append(client)
        return client

    yield _make
    for client in clients:
        client.__exit__(None, None, None)
    main.app.dependency_overrides.clear()


def plan(client, monkeypatch, itinerary, replacement=None):
    import main

    monkeypatch.setattr(main, "run_travel_planner", lambda data: itinerary)
    if replacement is not None:
        monkeypatch.setattr(main, "suggest_replacement", replacement)
    return client.post("/plan-trip", json=JAIPUR_TRIP)


# --------------------------------------------------------------------------- B1


def test_B1_every_place_the_ai_names_is_looked_up_on_google_once(places_client, monkeypatch):
    google = FakeGooglePlaces()
    client = places_client(google)

    r = plan(client, monkeypatch, OPEN_PLACES_PLAN)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "success"
    assert body["itinerary"] == OPEN_PLACES_PLAN
    assert sorted(google.searches()) == ["Amber Fort, Jaipur", "Hawa Mahal, Jaipur"]
    assert body["places"] == [
        HAWA_MAHAL,
        {
            "query": "Amber Fort",
            "status": "confirmed",
            "name": "Amber Palace",
            "address": "Devisinghpura, Amer, Jaipur, Rajasthan 302001, India",
            "maps_url": "https://maps.google.com/?cid=1002",
            "location": {"lat": 26.9854865, "lng": 75.8513454},
            "rating": 4.6,
            "reviews": 120000,
            "replaces": None,
            "reason": None,
        },
    ]
    request = google.requests[0]
    assert request.headers["X-Goog-Api-Key"] == GOOGLE_KEY
    assert set(request.headers["X-Goog-FieldMask"].split(",")) == {
        "places.id", "places.displayName", "places.formattedAddress", "places.location",
        "places.googleMapsUri", "places.businessStatus", "places.rating", "places.userRatingCount",
        # added by TP-05 A2: opening hours, and the time zone to read them in
        "places.regularOpeningHours", "places.currentOpeningHours", "places.utcOffsetMinutes",
    }


def test_B1_the_ai_is_told_to_write_each_place_in_bold_by_its_google_maps_name():
    import main

    instructions = str(main.agent.instructions).lower()
    assert "bold" in instructions
    assert "google maps" in instructions


# --------------------------------------------------------------------------- B2


def test_B2_closed_or_unknown_places_are_replaced_once_or_marked(places_client, monkeypatch):
    google = FakeGooglePlaces()
    client = places_client(google)
    asked = []

    def replacement(name, reason):
        asked.append((name, reason))
        return {"Old Café Nirvana": "Tapri Central", "Imaginary Rooftop": "Nowhere Garden"}[name]

    body = plan(client, monkeypatch, CLOSED_PLACES_PLAN, replacement).json()

    assert sorted(asked) == [("Imaginary Rooftop", "not found on Google Maps"), ("Old Café Nirvana", "permanently closed")]
    assert "**Tapri Central**" in body["itinerary"]
    assert "Old Café Nirvana" not in body["itinerary"]
    assert "**Imaginary Rooftop**" in body["itinerary"]

    places = {place["query"]: place for place in body["places"]}
    assert list(places) == ["Tapri Central", "Hawa Mahal", "Imaginary Rooftop"]
    assert places["Tapri Central"] | {"location": None} == {
        "query": "Tapri Central",
        "status": "replaced",
        "name": "Tapri Central",
        "address": "Prithviraj Rd, C Scheme, Jaipur, Rajasthan 302001, India",
        "maps_url": "https://maps.google.com/?cid=1005",
        "location": None,
        "rating": 4.5,
        "reviews": 21000,
        "replaces": "Old Café Nirvana",
        "reason": "permanently closed",
    }
    assert places["Imaginary Rooftop"] == {
        "query": "Imaginary Rooftop",
        "status": "unconfirmed",
        "name": None,
        "address": None,
        "maps_url": None,
        "location": None,
        "rating": None,
        "reviews": None,
        "replaces": None,
        "reason": "not found on Google Maps",
    }
    assert sorted(google.searches()) == sorted([
        "Old Café Nirvana, Jaipur", "Hawa Mahal, Jaipur", "Imaginary Rooftop, Jaipur", "Tapri Central, Jaipur", "Nowhere Garden, Jaipur",
    ])


def test_B2_the_ai_is_sent_only_the_place_name_and_the_reason(monkeypatch):
    import main

    prompts = []

    class RecordingAgent:
        def run(self, prompt):
            prompts.append(prompt)
            return SimpleNamespace(content="Try **Tapri Central** instead.")

    monkeypatch.setattr(main, "agent", RecordingAgent())

    assert main.suggest_replacement("Old Café Nirvana", "permanently closed") == "Tapri Central"
    assert len(prompts) == 1
    assert "Old Café Nirvana" in prompts[0] and "permanently closed" in prompts[0]
    for google_detail in ("maps.google.com", "MI Road", "Rajasthan", "4.1", "850", "CLOSED_PERMANENTLY"):
        assert google_detail not in prompts[0]


def test_B2_a_failing_replacement_marks_the_place_without_breaking_the_itinerary(places_client, monkeypatch):
    client = places_client(FakeGooglePlaces())

    def broken(name, reason):
        raise RuntimeError("model unavailable")

    r = plan(client, monkeypatch, CLOSED_PLACES_PLAN, broken)

    assert r.status_code == 200
    statuses = {place["query"]: place["status"] for place in r.json()["places"]}
    assert statuses == {"Old Café Nirvana": "unconfirmed", "Hawa Mahal": "confirmed", "Imaginary Rooftop": "unconfirmed"}


# --------------------------------------------------------------------------- B3


def test_B3_a_temporarily_closed_place_is_kept_and_labelled(places_client, monkeypatch):
    client = places_client(FakeGooglePlaces())
    itinerary = "## Day 1: Lakes\n- Sunset view of **Jal Mahal**.\n"
    asked = []

    body = plan(client, monkeypatch, itinerary, lambda name, reason: asked.append(name)).json()

    assert body["itinerary"] == itinerary
    assert asked == []
    assert [(p["query"], p["status"], p["maps_url"]) for p in body["places"]] == [("Jal Mahal", "temporarily_closed", "https://maps.google.com/?cid=1004")]


# --------------------------------------------------------------------------- B4


def test_B4_only_google_place_ids_are_kept_and_details_are_fetched_fresh(places_client, monkeypatch):
    google = FakeGooglePlaces()
    client = places_client(google)
    plan(client, monkeypatch, OPEN_PLACES_PLAN)

    assert sorted(client.checker.stored().values()) == ["test-amber-fort", "test-hawa-mahal"]

    google.places["Hawa Mahal"]["rating"] = 4.5
    google.places["Hawa Mahal"]["userRatingCount"] = 190001
    body = plan(client, monkeypatch, OPEN_PLACES_PLAN).json()

    assert body["places"][0] == HAWA_MAHAL | {"rating": 4.5, "reviews": 190001}
    assert sorted(google.detail_ids()) == ["test-amber-fort", "test-hawa-mahal"]
    assert len(google.searches()) == 2  # the second itinerary used the stored IDs


def test_B4_a_slow_google_never_blocks_the_itinerary(places_client, monkeypatch):
    release = threading.Event()
    client = places_client(FakeGooglePlaces(block=release), deadline_s=1.0)

    started = time.monotonic()
    r = plan(client, monkeypatch, OPEN_PLACES_PLAN)
    elapsed = time.monotonic() - started
    release.set()

    assert r.status_code == 200
    assert elapsed < 3
    assert r.json()["itinerary"] == OPEN_PLACES_PLAN
    assert [(p["query"], p["status"]) for p in r.json()["places"]] == [("Hawa Mahal", "not_checked"), ("Amber Fort", "not_checked")]


def test_B4_place_checks_have_a_10_second_limit():
    from places.service import PlaceChecker

    assert PlaceChecker(google=None).deadline_s == 10.0


# --------------------------------------------------------------------------- B5


def test_B5_without_a_google_key_itineraries_still_work_and_places_show_not_checked(places_client, monkeypatch):
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    google = FakeGooglePlaces()
    client = places_client(google, key=None)

    body = plan(client, monkeypatch, OPEN_PLACES_PLAN).json()

    assert body["itinerary"] == OPEN_PLACES_PLAN
    assert [(p["query"], p["status"], p["maps_url"]) for p in body["places"]] == [("Hawa Mahal", "not_checked", None), ("Amber Fort", "not_checked", None)]
    assert google.requests == []
    services = client.get("/api/health").json()["services"]
    assert {"service": "place_checks", "label": "Place checks (Google Maps)", "key": "GOOGLE_MAPS_API_KEY", "set": False, "status": "key missing"} in services


def test_B5_the_google_key_never_appears_in_responses_or_logs(places_client, monkeypatch, caplog):
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", GOOGLE_KEY)
    google = FakeGooglePlaces()
    del google.places["Amber Fort"]
    client = places_client(google)
    caplog.set_level(logging.DEBUG)

    body = plan(client, monkeypatch, OPEN_PLACES_PLAN, lambda name, reason: "Nowhere Garden").text
    health = client.get("/api/health")

    assert GOOGLE_KEY not in body
    assert GOOGLE_KEY not in health.text
    assert GOOGLE_KEY not in caplog.text
    assert {"service": "place_checks", "label": "Place checks (Google Maps)", "key": "GOOGLE_MAPS_API_KEY", "set": True, "status": "ready"} in health.json()["services"]


def test_B5_the_place_checker_reads_the_google_key_from_the_environment(monkeypatch):
    from places.service import build_place_checker

    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)
    assert build_place_checker().google is None

    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", GOOGLE_KEY)
    assert build_place_checker().google is not None
