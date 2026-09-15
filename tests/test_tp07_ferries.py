"""TP-07 E1–E4: boats and ferries in the day's timetable (Google simulated; a test timetable, and the real timetable file)."""

from __future__ import annotations

import json
import re
from datetime import date
from pathlib import Path

from helpers import FakeMaps, weekly_hours
from tp07_support import day_rows, plan_day, timings_client  # noqa: F401

SANUR_VILLA = {"name": "Sanur Villa", "address": "Sanur, Bali", "lat": -8.6880, "lng": 115.2620, "source": "google"}
BALI_TRIP = {
    "destination": "Bali", "num_days": 2, "budget": 90000, "currency": "INR", "num_travelers": 2, "trip_type": "Standard", "group_type": "Couple",
    "preferences": "Beaches.", "start_date": "2026-10-19", "return_date": "2026-10-20", "stay": SANUR_VILLA,
}
PENIDA = {
    "id": "sanur-nusa-penida",
    "name": "Sanur to Nusa Penida",
    "from": {"jetty": "Sanur Harbour", "lat": -8.6760, "lng": 115.2630, "area_km": 15},
    "to": {"jetty": "Banjar Nyuh Harbour", "lat": -8.6782, "lng": 115.5035, "area_km": 20},
    "first": "07:30", "last": "15:30", "every_minutes": 30, "crossing_minutes": 45,
    "return_first": "08:00", "return_last": "16:30",
    "source": "https://www.directferries.com/sanur_nusa_penida_ferry.htm", "checked": "2026-09-15",
}
MAINLAND = ["Sanur Villa", "Sanur Beach", "Sanur Harbour", "Marine Drive Walkway"]
ISLAND = ["Kelingking Beach", "Crystal Bay", "Banjar Nyuh Harbour", "Pulau Kecil", "Fort Kochi Beach"]


def bali_maps(**options) -> FakeMaps:
    places = {
        "Sanur Beach": {"lat": -8.6780, "lng": 115.2630 + 0.0101, "town": "Sanur", "types": ["natural_feature"]},
        "Kelingking Beach": {"lat": -8.7505, "lng": 115.4746, "town": "Nusa Penida", "types": ["natural_feature"]},
        "Crystal Bay": {"lat": -8.7148, "lng": 115.4578, "town": "Nusa Penida", "types": ["natural_feature"]},
        "Pulau Kecil": {"lat": -8.7200, "lng": 115.3200, "town": "Sanur", "types": ["natural_feature"]},
        "Marine Drive Walkway": {"lat": -8.6600, "lng": 115.2400, "town": "Sanur", "types": ["tourist_attraction"], "hours": weekly_hours("06:00", "22:00")},
        "Fort Kochi Beach": {"lat": -8.6400, "lng": 115.2900, "town": "Sanur", "types": ["natural_feature"]},
    }
    areas = {"Bali": {"lat": -8.34, "lng": 115.09, "low": (-8.85, 114.43), "high": (-8.06, 115.71), "town": "Bali"}}
    points = {"Sanur Villa": SANUR_VILLA, "Sanur Harbour": PENIDA["from"], "Banjar Nyuh Harbour": PENIDA["to"]}
    water = [(a, b) for a in MAINLAND for b in ISLAND]
    return FakeMaps(places, areas=areas, points=points, water=water, offset=480, **options)


# --------------------------------------------------------------------------- E1


def test_E1_a_boat_on_googles_public_transport_route_shows_its_departure_crossing_and_be_at_the_jetty_by(timings_client, monkeypatch):
    ferry = {"line": "Water Metro", "departures": ["10:20", "10:50", "11:20"], "minutes": 25}
    maps = bali_maps(ferries={("Marine Drive Walkway", "Fort Kochi Beach"): ferry})
    day = "## Day 1: Across the water\n- 09:00–10:00: **Marine Drive Walkway** - a walk.\n- 11:00–13:00: **Fort Kochi Beach** - the beach.\n"

    body = plan_day(timings_client(maps, ferries=[PENIDA]), monkeypatch, day, trip=BALI_TRIP)

    boat = day_rows(body, 1, "boat")[0]
    # Google is asked for boats leaving at least 30 minutes after you set off, so you're at the jetty in time.
    assert (boat["line"], boat["departs"], boat["arrives"], boat["minutes"], boat["be_at_jetty"]) == ("Water Metro", "10:50", "11:15", 25, "10:20")
    assert boat["label"] is None
    beach = day_rows(body, 1, "visit")[1]
    assert beach["place"] == "Fort Kochi Beach"
    assert beach["start"] >= "11:15"


# --------------------------------------------------------------------------- E2


def test_E2_a_crossing_in_the_timetable_file_takes_the_first_boat_at_least_30_minutes_after_arrival_at_the_jetty(timings_client, monkeypatch):
    maps = bali_maps(drive={("Sanur Beach", "Sanur Harbour"): 5, ("Banjar Nyuh Harbour", "Kelingking Beach"): 40})
    day = "## Day 1: Nusa Penida\n- 09:00–10:00: **Sanur Beach** - morning swim.\n- 12:00–14:00: **Kelingking Beach** - the T-Rex cliff.\n"

    body = plan_day(timings_client(maps, ferries=[PENIDA]), monkeypatch, day, trip=BALI_TRIP)

    rows = day_rows(body, 1)
    to_jetty = next(row for row in rows if row["kind"] == "travel" and row["to"] == "Sanur Harbour")
    assert (to_jetty["from"], to_jetty["minutes"], to_jetty["buffer"], to_jetty["leave"], to_jetty["arrive"]) == ("Sanur Beach", 5, 30, "10:00", "10:05")
    boat = day_rows(body, 1, "boat")[0]
    assert {key: boat[key] for key in ("from", "to", "departs", "arrives", "minutes", "be_at_jetty", "source", "checked", "label")} == {
        "from": "Sanur Harbour", "to": "Banjar Nyuh Harbour", "departs": "11:00", "arrives": "11:45", "minutes": 45, "be_at_jetty": "10:30",
        "source": "https://www.directferries.com/sanur_nusa_penida_ferry.htm", "checked": "2026-09-15", "label": "Check today's times with the operator",
    }
    from_jetty = next(row for row in rows if row["kind"] == "travel" and row["from"] == "Banjar Nyuh Harbour")
    assert (from_jetty["to"], from_jetty["minutes"], from_jetty["leave"], from_jetty["arrive"]) == ("Kelingking Beach", 40, "11:45", "12:25")
    cliff = day_rows(body, 1, "visit")[1]
    assert (cliff["place"], cliff["start"], cliff["end"]) == ("Kelingking Beach", "12:35", "14:35")


# --------------------------------------------------------------------------- E3


def test_E3_when_the_last_boat_has_left_the_trip_says_so_and_the_visit_doesnt_fit(timings_client, monkeypatch):
    maps = bali_maps(drive={("Sanur Beach", "Sanur Harbour"): 5})
    day = "## Day 1: Too late\n- 15:00–16:00: **Sanur Beach** - swim.\n- 17:00–18:00: **Kelingking Beach** - the cliff.\n"

    body = plan_day(timings_client(maps, ferries=[PENIDA]), monkeypatch, day, trip=BALI_TRIP)

    boat = day_rows(body, 1, "boat")[0]
    assert (boat["departs"], boat["label"]) == (None, "No boat after 15:30")
    cliff = day_rows(body, 1, "visit")[1]
    assert (cliff["place"], cliff["status"]) == ("Kelingking Beach", "doesnt_fit")
    assert cliff["label"].startswith("Doesn't fit this day")


def test_E3_a_crossing_with_no_known_boat_times_says_check_locally_and_the_ai_is_never_asked(timings_client, monkeypatch):
    from helpers import ScriptedAgent

    agent = ScriptedAgent("")
    maps = bali_maps()
    day = "## Day 1: The islet\n- 09:00–10:00: **Sanur Beach** - swim.\n- 11:00–12:00: **Pulau Kecil** - the islet.\n"

    body = plan_day(timings_client(maps, ferries=[PENIDA]), monkeypatch, day, trip=BALI_TRIP, agent=agent)

    trip = next(row for row in day_rows(body, 1, "travel") if row["to"] == "Pulau Kecil")
    assert trip["label"] == "Boat times unknown: check locally"
    assert day_rows(body, 1, "boat") == []
    assert agent.prompts == []


# --------------------------------------------------------------------------- E4

FERRIES_FILE = Path(__file__).resolve().parents[1] / "plans" / "ferries.json"
CLOCK = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def test_E4_every_crossing_in_the_timetable_file_is_complete_and_was_checked_in_the_last_6_months():
    routes = json.loads(FERRIES_FILE.read_text(encoding="utf-8"))

    assert {route["id"] for route in routes} >= {"sanur-nusa-penida", "sanur-nusa-lembongan", "padang-bai-gili-trawangan", "gateway-of-india-elephanta", "port-blair-havelock"}
    for route in routes:
        for side in ("from", "to"):
            assert route[side]["jetty"], route["id"]
            assert -90 <= route[side]["lat"] <= 90 and -180 <= route[side]["lng"] <= 180, route["id"]
            assert route[side]["area_km"] > 0, route["id"]
        for key in ("first", "last"):
            assert CLOCK.match(route[key]), (route["id"], key)
        assert route["first"] <= route["last"], route["id"]
        assert route["every_minutes"] > 0 and route["crossing_minutes"] > 0, route["id"]
        assert route["source"].startswith("https://"), route["id"]
        checked = date.fromisoformat(route["checked"])
        assert (date.today() - checked).days <= 183, f"{route['id']} was last checked on {checked}: check it again with the operator"
