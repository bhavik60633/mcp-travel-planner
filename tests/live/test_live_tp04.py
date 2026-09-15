"""TP-04 LIVE tests: real calls. Run with `pytest --live -m live`.

A4: Airbnb stay photos load (needs AIRBNB_IGNORE_ROBOTS_TXT=1).
B8: every place on a real Jaipur itinerary has a Google Maps link, and Google reports none permanently closed
    (needs OPENAI_API_KEY and GOOGLE_MAPS_API_KEY).
C9: trip essentials for Paris, 9–13 Nov 2026, in INR.
"""

from __future__ import annotations

import os
from datetime import date, timedelta

import httpx
import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.live


def test_A4_live_airbnb_stay_cover_photos_load():
    if os.environ.get("AIRBNB_IGNORE_ROBOTS_TXT") != "1":
        pytest.skip("Airbnb stays are off: AIRBNB_IGNORE_ROBOTS_TXT=1 isn't set on this PC")
    import main

    checkin = date.today() + timedelta(days=30)
    with TestClient(main.app) as client:
        r = client.get("/api/stays", params={"place": "Goa, India", "checkin": checkin.isoformat(), "checkout": (checkin + timedelta(days=5)).isoformat(), "adults": 2})

    assert r.status_code == 200, r.text
    covers = [stay["photos"][0] for stay in r.json()["stays"] if stay["photos"]]
    loaded = 0
    with httpx.Client(timeout=20, follow_redirects=True) as web:
        for cover in covers[:8]:
            response = web.get(cover)
            if response.status_code == 200 and response.headers.get("content-type", "").startswith("image/"):
                loaded += 1
    print(f"\nLIVE A4 Goa: {len(covers)} stays with photos; {loaded} of {min(len(covers), 8)} cover photos checked loaded")
    assert loaded >= 5


def test_B8_live_places_on_a_real_itinerary_are_on_google_maps_and_not_closed():
    missing = [name for name in ("OPENAI_API_KEY", "GOOGLE_MAPS_API_KEY") if not os.environ.get(name)]
    if missing:
        pytest.skip(f"{' and '.join(missing)} isn't set on this PC")
    import main
    from places.service import get_place_checker

    trip = {
        "destination": "Jaipur", "num_days": 3, "budget": 45000, "currency": "INR", "num_travelers": 2,
        "trip_type": "Standard", "group_type": "Couple", "preferences": "Forts, markets and local food.",
    }
    with TestClient(main.app) as client:
        r = client.post("/plan-trip", json=trip)

    assert r.status_code == 200, r.text
    places = r.json().get("places") or []
    print(f"\nLIVE B8 Jaipur: {[(p['query'], p['status']) for p in places]}")
    assert len(places) >= 5, "the AI named fewer than 5 places in bold"
    for place in places:
        assert place["maps_url"] and place["maps_url"].startswith("https://maps.google.com/"), place
        assert place["status"] in ("confirmed", "replaced", "temporarily_closed"), place

    checker = get_place_checker()
    for place_id in checker.stored().values():
        details = checker.google.details(place_id)
        assert details is None or details["business_status"] != "CLOSED_PERMANENTLY", details


def test_C9_live_trip_essentials_for_paris():
    import main

    with TestClient(main.app) as client:
        r = client.get("/api/trip-info", params={"place": "Paris", "start": "2026-11-09", "days": 5, "currency": "INR"})

    assert r.status_code == 200, r.text
    body = r.json()
    print(f"\nLIVE C9 Paris: place={body['place']} weather={[(d['date'], d['kind'], d['high_c']) for d in body['weather'].get('days', [])]} "
          f"currency={body['currency']} holidays={body['holidays']} safety={body['safety'].get('tier')}")
    assert body["place"]["country_code"] == "FR"
    assert body["weather"]["available"] and len(body["weather"]["days"]) == 5
    assert body["currency"]["available"] and body["currency"]["to"] == "EUR" and body["currency"]["rate"] > 0
    assert any(day["date"] == "2026-11-11" and "Armistice" in day["name"] for day in body["holidays"]["days"])
    assert body["intro"]["available"] and "Paris" in body["intro"]["text"]
    assert body["safety"]["available"] and body["safety"]["tier"]
