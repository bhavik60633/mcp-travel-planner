"""TP-07 LIVE tests: real calls. Run with `pytest --live -m live`.

L1: Bali with a Nusa Penida day: the boat trip and the times after it (needs OPENAI_API_KEY and GOOGLE_MAPS_API_KEY).
L2: a Jaipur car trip at 18:00 is within 20% of Google's own traffic estimate for that hour (needs GOOGLE_MAPS_API_KEY).
L3: a busy, well-known Jaipur restaurant has busy hours (needs GOOGLE_MAPS_API_KEY and SERPAPI_API_KEY).
L4: Jaipur with a day at Agra becomes a stay in Agra, with the move's travel time (needs OPENAI_API_KEY and GOOGLE_MAPS_API_KEY).
N4: 3 Goa plans: every checked place is within 50 km of its day's base, and every trip shows its travel time (needs both keys).
"""

from __future__ import annotations

import json
import math
import os
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.live


def needs(*names):
    missing = [name for name in names if not os.environ.get(name)]
    if missing:
        pytest.skip(f"{' and '.join(missing)} isn't set on this PC")


def km(a, b):
    lat1, lng1, lat2, lng2 = map(math.radians, (a["lat"], a["lng"], b["lat"], b["lng"]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 2 * 6371.0 * math.asin(math.sqrt(h))


def trip(destination, days, preferences, stay=None, start_in=20):
    start = date.today() + timedelta(days=start_in)
    body = {
        "destination": destination, "num_days": days, "budget": 150000, "currency": "INR", "num_travelers": 2, "trip_type": "Standard",
        "group_type": "Couple", "preferences": preferences, "start_date": start.isoformat(), "return_date": (start + timedelta(days=days - 1)).isoformat(),
    }
    if stay:
        body["stay"] = stay
    return body


def base_for(client, request):
    r = client.post("/api/plan-base", json={key: request[key] for key in ("destination", "start_date", "return_date", "num_travelers", "trip_type", "preferences")})
    assert r.status_code == 200, r.text
    return r.json()["base"]


def rows(body, kind):
    return [(entry["day"], row) for entry in body.get("timetable") or [] for row in entry["rows"] if row["kind"] == kind]


def test_L1_live_bali_nusa_penida_boat_and_the_times_after_it():
    needs("OPENAI_API_KEY", "GOOGLE_MAPS_API_KEY")
    import main

    ferries = {route["id"]: route for route in json.loads((Path(main.__file__).parent / "plans" / "ferries.json").read_text(encoding="utf-8"))}
    penida = ferries["sanur-nusa-penida"]
    with TestClient(main.app) as client:
        stays = client.get("/api/stay/find", params={"q": "Hyatt Regency Bali", "destination": "Bali"}).json()["stays"]
        assert stays, "the hotel wasn't found"
        request = trip("Bali", 5, "Beaches in Sanur, and one full day on Nusa Penida for Kelingking Beach and Crystal Bay.", stay=stays[0])
        body = client.post("/plan-trip", json=request).json()

    boats = rows(body, "boat")
    print(f"\nLIVE L1 boats: {[(day, row['from'], row['to'], row['departs'], row['be_at_jetty']) for day, row in boats]}")
    assert boats, "no boat trip was planned"
    outbound = [row for _, row in boats if row["from"] == penida["from"]["jetty"] and row["departs"]]
    assert outbound and all(penida["first"] <= row["departs"] <= penida["last"] for row in outbound)
    for entry in body["timetable"]:
        arrive = None
        for row in entry["rows"]:
            if row["kind"] == "travel" and row["status"] == "ok":
                arrive = row
            if row["kind"] == "visit" and arrive and row["status"] != "doesnt_fit":
                ready = datetime.strptime(arrive["arrive"], "%H:%M") + timedelta(minutes=arrive["buffer"])
                assert datetime.strptime(row["start"], "%H:%M") >= ready - timedelta(minutes=1), (entry["day"], row)


def test_L2_live_a_jaipur_car_trip_at_18_00_is_within_20_percent_of_googles_own_estimate():
    needs("GOOGLE_MAPS_API_KEY")
    from places.routes import GoogleRoutes

    routes = GoogleRoutes(api_key=os.environ["GOOGLE_MAPS_API_KEY"])
    hawa_mahal, amber_fort = {"lat": 26.9239, "lng": 75.8267}, {"lat": 26.9855, "lng": 75.8513}
    day = date.today() + timedelta(days=7)
    leave_utc = datetime(day.year, day.month, day.day, 18, 0) - timedelta(minutes=330)

    yori = routes.drive(hawa_mahal, amber_fort, leave_utc=leave_utc)
    google = routes.drive(hawa_mahal, amber_fort, leave_utc=leave_utc.replace(tzinfo=timezone.utc))
    print(f"\nLIVE L2 Hawa Mahal to Amber Fort at 18:00: Yori {yori}, Google {google}")
    assert yori and google
    assert abs(yori["minutes"] - google["minutes"]) <= 0.2 * google["minutes"]


def test_L3_live_a_busy_jaipur_restaurant_has_busy_hours():
    needs("GOOGLE_MAPS_API_KEY", "SERPAPI_API_KEY")
    from places.google import GooglePlaces
    from plans.busy import BusyHours

    place = GooglePlaces(api_key=os.environ["GOOGLE_MAPS_API_KEY"]).search("Laxmi Misthan Bhandar, Johari Bazar, Jaipur")
    assert place and place["id"]
    busy = BusyHours(api_key=os.environ["SERPAPI_API_KEY"]).week(place["id"])
    print(f"\nLIVE L3 LMB busy hours: {busy}")
    assert busy and any(busy.values())


def test_L4_live_jaipur_with_a_day_at_agra_becomes_a_stay_in_agra():
    needs("OPENAI_API_KEY", "GOOGLE_MAPS_API_KEY")
    import main

    request = trip("Jaipur", 4, "Jaipur's forts and palaces, and one full day at the Taj Mahal and Agra Fort in Agra.")
    with TestClient(main.app) as client:
        request["stay"] = base_for(client, request)
        body = client.post("/plan-trip", json=request).json()

    days = [(entry["day"], entry["kind"], entry["area"], entry["label"]) for entry in body["timetable"]]
    print(f"\nLIVE L4 days: {days}")
    agra = [entry for entry in body["timetable"] if entry["kind"] == "stay_there" and entry["area"] == "Agra"]
    assert agra, "no day became a stay in Agra"
    assert agra[0]["label"].startswith("Stay in Agra tonight: ")
    assert any(stay["place"] == "Agra" for stay in body.get("new_stays") or [])
    first_trip = next(row for row in agra[0]["rows"] if row["kind"] == "travel")
    assert first_trip["minutes"] and first_trip["minutes"] > 90


def test_N4_live_three_goa_plans_keep_every_place_within_50_km_of_its_days_base():
    needs("OPENAI_API_KEY", "GOOGLE_MAPS_API_KEY")
    import main

    with TestClient(main.app) as client:
        for attempt in range(3):
            request = trip("Goa", 3, "Beaches, forts, cafes and seafood.", start_in=20 + attempt)
            request["stay"] = base_for(client, request)
            body = client.post("/plan-trip", json=request).json()
            located = {place["query"]: place["location"] for place in body.get("places") or [] if place.get("location")}
            for entry in body["timetable"]:
                base = entry["stay"]
                for row in entry["rows"]:
                    if row["kind"] == "visit" and row["place"] in located and entry["kind"] == "base":
                        assert km(base, located[row["place"]]) <= 50, (attempt, entry["day"], row["place"])
                    if row["kind"] == "travel":
                        assert row["status"] == "ok" or row["label"], (attempt, entry["day"], row)
            print(f"\nLIVE N4 Goa plan {attempt + 1}: base {request['stay']['name']}, days {[entry['kind'] for entry in body['timetable']]}")
