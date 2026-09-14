"""TP-05 B1–B5: travel times between each day's places, by car and public transport (Google simulated)."""

from __future__ import annotations

import json
import logging
import threading
import time

from conftest import GOOGLE_TEST_KEY
from helpers import FakeGooglePlaces, FakeGoogleRoutes, jaipur_places_with_hours
from test_tp05_open_times import plan

DAY_PLAN = (
    "## Day 1: Pink City\n"
    "- 09:00–11:00: **Hawa Mahal** — windows.\n"
    "- 11:30–12:30: **Tapri Central** — chai.\n"
    "- 13:00–15:00: **Albert Hall Museum** — museum.\n"
)


def setup(review_client, **routes_options):
    places = jaipur_places_with_hours()
    routes = FakeGoogleRoutes(places, **{k: v for k, v in routes_options.items() if k != "deadline_s"})
    client = review_client(FakeGooglePlaces(places=places), routes, deadline_s=routes_options.get("deadline_s", 10.0))
    return client, routes


# --------------------------------------------------------------------------- B1


def test_B1_travel_times_by_car_and_public_transport_between_each_pair_of_places_leaving_when_the_visit_ends(review_client, monkeypatch):
    client, routes = setup(review_client)

    body = plan(client, monkeypatch, DAY_PLAN)

    assert [(leg["day"], leg["from"], leg["to"], leg["leave"]) for leg in body["travel"]] == [
        (1, "Hawa Mahal", "Tapri Central", "11:00"),
        (1, "Tapri Central", "Albert Hall Museum", "12:30"),
    ]
    assert body["travel"][0]["car"] == {"minutes": 14, "km": 3.4}
    assert body["travel"][0]["status"] == "ok"

    drive = routes.request_for("Hawa Mahal", "Tapri Central", "DRIVE")
    assert str(drive.url) == "https://routes.googleapis.com/directions/v2:computeRoutes"
    assert drive.headers["X-Goog-Api-Key"] == GOOGLE_TEST_KEY
    assert {"routes.duration", "routes.distanceMeters"} <= set(drive.headers["X-Goog-FieldMask"].split(","))
    drive_body = json.loads(drive.content)
    assert drive_body["routingPreference"] == "TRAFFIC_UNAWARE"
    assert "departureTime" not in drive_body

    transit_body = routes.body_for("Hawa Mahal", "Tapri Central", "TRANSIT")
    assert transit_body["departureTime"] == "2026-10-19T05:30:00Z"  # 11:00 AM in Jaipur (UTC+5:30)
    assert routes.body_for("Tapri Central", "Albert Hall Museum", "TRANSIT")["departureTime"] == "2026-10-19T07:00:00Z"


# --------------------------------------------------------------------------- B2


def test_B2_public_transport_is_shown_with_its_lines_when_a_route_leaves_within_30_minutes(review_client, monkeypatch):
    client, _ = setup(review_client)

    first, second = plan(client, monkeypatch, DAY_PLAN)["travel"]

    assert first["transit"] == {"minutes": 32, "lines": ["Pink Line"], "summary": "Metro 32 min: Pink Line, then 6 min walk"}
    assert first["transit_message"] is None
    assert second["transit"] is None
    assert second["transit_message"] == "No public transport at this time"


def test_B2_a_route_leaving_more_than_30_minutes_later_isnt_shown(review_client, monkeypatch):
    client, _ = setup(review_client, transit_delay_minutes=45)

    first = plan(client, monkeypatch, DAY_PLAN)["travel"][0]

    assert first["transit"] is None
    assert first["transit_message"] == "No public transport at this time"
    assert first["car"] == {"minutes": 14, "km": 3.4}


# --------------------------------------------------------------------------- B3


def test_B3_walking_time_is_added_when_the_car_trip_is_under_1_5_km(review_client, monkeypatch):
    client, routes = setup(review_client)

    short = plan(client, monkeypatch, "## Day 1: Old City\n- 09:00–10:00: **Hawa Mahal**\n- 10:30–11:30: **Laxmi Misthan Bhandar**\n")["travel"][0]
    long = plan(client, monkeypatch, DAY_PLAN)["travel"][0]

    assert short["car"] == {"minutes": 5, "km": 0.9}
    assert short["walk"] == {"minutes": 11}
    assert long["walk"] is None
    assert routes.body_for("Hawa Mahal", "Tapri Central", "WALK") is None


# --------------------------------------------------------------------------- B4


def test_B4_a_trip_that_doesnt_fit_before_the_next_visit_is_labelled(review_client, monkeypatch):
    client, _ = setup(review_client)

    first, second = plan(client, monkeypatch, DAY_PLAN)["travel"]

    assert first["label"] is None
    assert second["car"] == {"minutes": 60, "km": 2.6}
    assert second["label"] == "Not enough time to get there"


# --------------------------------------------------------------------------- B5


def test_B5_travel_times_share_the_10_second_limit_and_unfinished_trips_say_so(review_client, monkeypatch):
    release = threading.Event()
    client, _ = setup(review_client, block=release, deadline_s=1.0)

    started = time.monotonic()
    body = plan(client, monkeypatch, DAY_PLAN)
    elapsed = time.monotonic() - started
    release.set()

    assert elapsed < 3
    assert [(leg["status"], leg["car"], leg["label"]) for leg in body["travel"]] == [
        ("not_available", None, "Travel time not available"),
        ("not_available", None, "Travel time not available"),
    ]


def test_B5_without_a_google_key_travel_times_say_not_checked(review_client, monkeypatch):
    places = jaipur_places_with_hours()
    google, routes = FakeGooglePlaces(places=places), FakeGoogleRoutes(places)
    client = review_client(google, routes, key=None)

    body = plan(client, monkeypatch, DAY_PLAN)

    assert [(leg["status"], leg["label"]) for leg in body["travel"]] == [("not_checked", "Not checked"), ("not_checked", "Not checked")]
    assert {visit["status"] for visit in body["visits"]} == {"not_checked"}
    assert google.requests == [] and routes.requests == []


def test_B5_the_google_key_never_appears_in_responses_or_logs(review_client, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    client, _ = setup(review_client, transit_delay_minutes=45)

    body = plan(client, monkeypatch, DAY_PLAN)
    health = client.get("/api/health").text

    assert GOOGLE_TEST_KEY not in json.dumps(body)
    assert GOOGLE_TEST_KEY not in health
    assert GOOGLE_TEST_KEY not in caplog.text
