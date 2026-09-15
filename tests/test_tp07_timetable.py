"""TP-07 A1, A2, B1–B6, C2, D1: each day's timetable from the stay, with real travel times and buffers (Google and the AI simulated)."""

from __future__ import annotations

import json
import logging

from conftest import GOOGLE_TEST_KEY
from tp07_support import ANJUNA_VILLA, GOA_TRIP, day_rows, goa_maps, plan_day, timings_client  # noqa: F401

CANDOLIM_INN = {"name": "Candolim Inn", "address": "Candolim, Goa", "lat": 15.518, "lng": 73.762, "source": "google"}

# Car times chosen so the AI's order is already the one with the least travel.
DRIVE = {
    ("Anjuna Villa", "Anjuna Beach"): 12, ("Anjuna Beach", "Chapora Fort"): 15, ("Chapora Fort", "Thalassa"): 8, ("Thalassa", "Anjuna Villa"): 10,
    ("Anjuna Villa", "Chapora Fort"): 20, ("Anjuna Beach", "Thalassa"): 25, ("Anjuna Villa", "Thalassa"): 10,
}
DAY = (
    "## Day 1: North Goa\n"
    "- 09:00–11:00: **Anjuna Beach** - a swim.\n"
    "- 11:00–12:30: **Chapora Fort** - the views.\n"
    "- 12:30–13:30: Lunch at **Thalassa** - Greek food by the sea.\n"
)


def maps_with(drive=None):
    return goa_maps(drive={**DRIVE, **(drive or {})}, points={"Anjuna Villa": ANJUNA_VILLA, "Candolim Inn": CANDOLIM_INN})


def summary(row):
    if row["kind"] == "travel":
        return ("travel", row["from"], row["to"], row["minutes"], row["buffer"], row["leave"], row["arrive"])
    if row["kind"] == "visit":
        return ("visit", row["place"], row["start"], row["end"])
    return (row["kind"], row["place"], row["time"])


# --------------------------------------------------------------------------- A1


def test_A1_the_timetable_starts_from_the_stay_the_trip_carries(timings_client, monkeypatch):
    body = plan_day(timings_client(maps_with()), monkeypatch, DAY)

    stay = body["timetable"][0]["stay"]
    assert (stay["name"], stay["source"], stay["lat"], stay["lng"]) == ("Anjuna Villa", "google", 15.585, 73.743)


def test_A1_a_base_area_yori_picked_is_labelled_your_stays_area(timings_client, monkeypatch):
    base = {"name": "Anjuna, North Goa", "address": None, "lat": 15.5827, "lng": 73.7449, "source": "area"}

    body = plan_day(timings_client(maps_with()), monkeypatch, DAY, trip={**GOA_TRIP, "stay": base})

    stay = body["timetable"][0]["stay"]
    assert (stay["name"], stay["label"]) == ("Anjuna, North Goa", "Your stay's area: Anjuna, North Goa")


def test_A1_each_place_of_a_trip_can_carry_its_own_stay(timings_client, monkeypatch):
    trip = {**GOA_TRIP, "stay": None, "stops": [{"place": "Anjuna", "nights": 1, "stay": ANJUNA_VILLA}, {"place": "Candolim", "nights": 1, "stay": CANDOLIM_INN}], "stay_per_stop": True}
    plan = DAY + "\n## Day 2: Candolim\n- 10:00–12:00: **Fort Aguada** - the lighthouse.\n\n## Day 3: Last morning\n- 09:30–10:30: **Fort Aguada** - one more look.\n"

    body = plan_day(timings_client(maps_with()), monkeypatch, plan, trip={key: value for key, value in trip.items() if value is not None})

    assert [entry["stay"]["name"] for entry in body["timetable"]] == ["Anjuna Villa", "Candolim Inn", "Candolim Inn"]


# --------------------------------------------------------------------------- A2 and B3


def test_A2_B3_each_day_leaves_the_stay_in_time_for_the_first_visit_and_every_later_visit_starts_after_arrival_plus_the_buffer(timings_client, monkeypatch):
    body = plan_day(timings_client(maps_with()), monkeypatch, DAY)

    assert [summary(row) for row in day_rows(body, 1)] == [
        ("leave", "Anjuna Villa", "08:35"),  # 09:00 minus 12 minutes and a 10-minute buffer, rounded down to 5 minutes
        ("travel", "Anjuna Villa", "Anjuna Beach", 12, 10, "08:35", "08:47"),
        ("visit", "Anjuna Beach", "09:00", "11:00"),
        ("travel", "Anjuna Beach", "Chapora Fort", 15, 10, "11:00", "11:15"),
        ("visit", "Chapora Fort", "11:25", "12:55"),  # planned 11:00; the same 1 h 30 min
        ("travel", "Chapora Fort", "Thalassa", 8, 10, "12:55", "13:03"),
        ("visit", "Thalassa", "13:15", "14:15"),  # 13:13, rounded up to 5 minutes
        ("travel", "Thalassa", "Anjuna Villa", 10, 10, "14:15", "14:25"),
        ("back", "Anjuna Villa", "14:35"),
    ]
    assert "- 11:25–12:55: **Chapora Fort** - the views." in body["itinerary"]
    assert "- 13:15–14:15: Lunch at **Thalassa** - Greek food by the sea." in body["itinerary"]
    assert "- 09:00–11:00: **Anjuna Beach** - a swim." in body["itinerary"]


def test_B3_a_visit_with_time_to_spare_keeps_its_planned_time(timings_client, monkeypatch):
    relaxed = DAY.replace("11:00–12:30: **Chapora Fort**", "15:00–16:30: **Chapora Fort**").replace("12:30–13:30: Lunch at **Thalassa**", "17:00–18:00: Lunch at **Thalassa**")

    body = plan_day(timings_client(maps_with()), monkeypatch, relaxed)

    assert [(row["place"], row["start"], row["end"]) for row in day_rows(body, 1, "visit")] == [
        ("Anjuna Beach", "09:00", "11:00"), ("Chapora Fort", "15:00", "16:30"), ("Thalassa", "17:00", "18:00"),
    ]


def test_A2_changing_the_stay_re_times_the_plan_without_asking_the_ai(timings_client, monkeypatch):
    import main
    from helpers import ScriptedAgent

    agent = ScriptedAgent("")
    monkeypatch.setattr(main, "agent", agent)
    client = timings_client(maps_with({("Candolim Inn", "Anjuna Beach"): 22}))

    r = client.post("/api/retime-plan", json={"itinerary": DAY, "trip": {**GOA_TRIP, "stay": CANDOLIM_INN}})

    assert r.status_code == 200, r.text
    rows = day_rows(r.json(), 1)
    assert (rows[0]["kind"], rows[0]["place"], rows[0]["time"]) == ("leave", "Candolim Inn", "08:25")
    assert agent.prompts == []


# --------------------------------------------------------------------------- B1


def test_B1_car_trips_use_live_traffic_at_the_hour_you_leave(timings_client, monkeypatch):
    maps = maps_with()

    plan_day(timings_client(maps), monkeypatch, DAY)

    timed = [body for origin, destination, body in maps.drive_bodies() if (origin, destination) == ("Anjuna Villa", "Anjuna Beach") and body.get("departureTime")]
    assert timed, "no car trip was asked for with a departure time"
    assert timed[-1]["routingPreference"] == "TRAFFIC_AWARE"
    assert timed[-1]["departureTime"] == "2026-10-19T03:05:00Z"  # 08:35 in Goa (UTC+5:30)


# --------------------------------------------------------------------------- B2


def test_B2_short_trips_are_walked_and_public_transport_shows_when_google_has_a_ride(timings_client, monkeypatch):
    day = "## Day 1: Anjuna\n- 09:00–10:00: **Anjuna Beach** - a swim.\n- 10:15–11:15: Breakfast at **Curlies** - the beach shack.\n"

    body = plan_day(timings_client(maps_with()), monkeypatch, day)

    walk = day_rows(body, 1, "travel")[1]
    assert (walk["from"], walk["to"], walk["mode"], walk["minutes"]) == ("Anjuna Beach", "Curlies", "walk", 3)
    assert walk["car"]["km"] < 1.5
    assert walk["transit"] is None
    assert walk["transit_message"] == "No public transport at this time"


# --------------------------------------------------------------------------- B4


def test_B4_a_visit_pushed_past_closing_time_is_labelled_doesnt_fit_this_day(timings_client, monkeypatch):
    late = "## Day 1: North Goa\n- 09:00–16:40: **Anjuna Beach** - a long beach day.\n- 16:45–18:15: **Chapora Fort** - the views.\n"

    body = plan_day(timings_client(maps_with()), monkeypatch, late)

    fort = day_rows(body, 1, "visit")[1]
    assert (fort["place"], fort["start"], fort["end"]) == ("Chapora Fort", "17:05", "18:35")
    assert (fort["status"], fort["label"]) == ("doesnt_fit", "Doesn't fit this day: Chapora Fort closes 6:00 PM")


def test_B4_a_day_that_would_end_after_22_00_is_labelled_and_nothing_is_dropped(timings_client, monkeypatch):
    late = "## Day 1: North Goa\n- 19:00–21:00: **Anjuna Beach** - sunset.\n- 21:00–22:30: Dinner at **Thalassa** - seafood.\n"

    body = plan_day(timings_client(maps_with({("Anjuna Beach", "Thalassa"): 10})), monkeypatch, late)

    dinner = day_rows(body, 1, "visit")[1]
    assert dinner["place"] == "Thalassa"
    assert dinner["label"] == "Doesn't fit this day: ends after 22:00"
    assert [row["place"] for row in day_rows(body, 1, "visit")] == ["Anjuna Beach", "Thalassa"]


# --------------------------------------------------------------------------- B5


def test_B5_opening_hours_are_checked_again_after_re_timing(timings_client, monkeypatch):
    early = "## Day 1: Candolim\n- 09:00–10:30: **Fort Aguada** - the lighthouse.\n"

    body = plan_day(timings_client(maps_with({("Anjuna Villa", "Fort Aguada"): 21})), monkeypatch, early)

    fort = day_rows(body, 1, "visit")[0]
    assert (fort["start"], fort["end"], fort["status"], fort["label"]) == ("09:30", "11:00", "time_changed", "Time changed: opens 9:30 AM")
    # Leaves in time for the new start: 21 minutes, and a 25-minute buffer at a big sight (10 + 15).
    assert day_rows(body, 1)[0]["time"] == "08:40"


# --------------------------------------------------------------------------- B6


def test_B6_travel_times_get_their_own_time_after_slow_place_checks(timings_client, monkeypatch):
    maps = goa_maps(drive=DRIVE, block_search=0.5)

    body = plan_day(timings_client(maps, deadline_s=1.5, travel_deadline_s=1.5), monkeypatch, DAY)

    assert {row["status"] for row in day_rows(body, 1, "travel")} == {"ok"}


def test_B6_a_trip_google_cant_answer_says_so_and_the_reason_is_logged_without_the_key(timings_client, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    maps = goa_maps(drive=DRIVE, fail_routes=429)

    body = plan_day(timings_client(maps), monkeypatch, DAY)

    trips = day_rows(body, 1, "travel")
    assert {(row["status"], row["label"]) for row in trips} == {("not_available", "Travel time not available")}
    assert "Travel time failed (HTTP 429)" in caplog.text
    assert GOOGLE_TEST_KEY not in caplog.text
    assert GOOGLE_TEST_KEY not in json.dumps(body)


# --------------------------------------------------------------------------- C2


def test_C2_visits_are_put_in_the_order_that_cuts_travel_and_fixed_times_and_meals_keep_their_place(timings_client, monkeypatch):
    drive = {
        ("Anjuna Villa", "Fort Aguada"): 25, ("Anjuna Villa", "Chapora Fort"): 8, ("Anjuna Villa", "Anjuna Beach"): 5,
        ("Anjuna Beach", "Chapora Fort"): 10, ("Anjuna Beach", "Fort Aguada"): 30, ("Chapora Fort", "Fort Aguada"): 40,
        ("Fort Aguada", "Vagator Beach"): 45, ("Chapora Fort", "Vagator Beach"): 3, ("Anjuna Beach", "Vagator Beach"): 12,
    }
    day = (
        "## Day 1: North Goa\n"
        "- 10:00–11:30: **Chapora Fort** - the views.\n"
        "- 12:00–13:30: **Fort Aguada** - the lighthouse.\n"
        "- 14:00–15:00: **Anjuna Beach** - a swim.\n"
        "- 18:00–19:00: **Vagator Beach** (fixed time) - sunset.\n"
        "- 19:30–21:00: Dinner at **Thalassa** - seafood.\n"
    )

    body = plan_day(timings_client(goa_maps(drive=drive)), monkeypatch, day)

    visits = day_rows(body, 1, "visit")
    assert [row["place"] for row in visits] == ["Fort Aguada", "Anjuna Beach", "Chapora Fort", "Vagator Beach", "Thalassa"]
    sunset = visits[3]
    assert (sunset["start"], sunset["end"]) == ("18:00", "19:00")


# --------------------------------------------------------------------------- D1


def test_D1_buffers_are_15_percent_of_the_trip_at_least_10_minutes_plus_15_at_big_sights_shown_apart_from_the_trip(timings_client, monkeypatch):
    day = "## Day 1: Candolim\n- 10:00–12:00: **Fort Aguada** - the lighthouse.\n- 14:00–15:00: Lunch at **Thalassa** - Greek food.\n"

    body = plan_day(timings_client(maps_with({("Anjuna Villa", "Fort Aguada"): 25, ("Fort Aguada", "Thalassa"): 80})), monkeypatch, day)

    to_fort, to_lunch = day_rows(body, 1, "travel")[:2]
    assert (to_fort["minutes"], to_fort["buffer"]) == (25, 25)  # 15% is under 10 minutes, and Fort Aguada has 45,000 reviews
    assert (to_lunch["minutes"], to_lunch["buffer"]) == (80, 12)  # 15% of 80 minutes
