"""TP-07 F1–F3: busy hours from Google's popular times through SerpApi (SerpApi, Google and the AI simulated)."""

from __future__ import annotations

import json
import logging

from helpers import FakeMaps, FakeSerpApi
from tp07_support import SERPAPI_TEST_KEY, day_rows, goa_maps, plan_day, timings_client  # noqa: F401

THALASSA = FakeMaps.place_id("Thalassa")
CHAPORA = FakeMaps.place_id("Chapora Fort")
# Mondays at Thalassa: busiest 13:00–15:00 (at least 80% of the peak).
BUSY = {THALASSA: {"monday": {11: 20, 12: 60, 13: 100, 14: 90, 15: 40, 16: 30}}}


def lunch_day(previous_end: str) -> str:
    return (
        "## Day 1: North Goa\n"
        f"- 09:00–{previous_end}: **Chapora Fort** - the views.\n"
        "- 13:00–14:00: Lunch at **Thalassa** - Greek food by the sea.\n"
    )


def maps():
    return goa_maps(drive={("Chapora Fort", "Thalassa"): 5})


# --------------------------------------------------------------------------- F1


def test_F1_restaurants_and_sights_get_busy_hours_from_serpapi_saved_for_30_days(timings_client, monkeypatch):
    serpapi = FakeSerpApi(busy=BUSY)
    client = timings_client(maps(), serpapi=serpapi)

    plan_day(client, monkeypatch, lunch_day("12:00"))

    asked = {request.url.params["place_id"]: request for request in serpapi.requests}
    assert set(asked) == {THALASSA, CHAPORA}
    params = asked[THALASSA].url.params
    assert (params["engine"], params["type"], params["hl"], params["api_key"]) == ("google_maps", "place", "en", SERPAPI_TEST_KEY)
    assert str(asked[THALASSA].url).startswith("https://serpapi.com/search")

    plan_day(client, monkeypatch, lunch_day("12:00"))
    assert len(serpapi.requests) == 2  # saved

    client.checker.busy.clock.advance(31 * 24 * 3600)
    plan_day(client, monkeypatch, lunch_day("12:00"))
    assert len(serpapi.requests) == 4


def test_F1_the_serpapi_key_never_appears_in_answers_or_logs(timings_client, monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    client = timings_client(maps(), serpapi=FakeSerpApi(busy=BUSY))

    body = plan_day(client, monkeypatch, lunch_day("12:00"))
    health = client.get("/api/health").text

    assert SERPAPI_TEST_KEY not in json.dumps(body)
    assert SERPAPI_TEST_KEY not in health
    assert SERPAPI_TEST_KEY not in caplog.text


# --------------------------------------------------------------------------- F2


def test_F2_a_meal_at_a_busy_hour_moves_to_a_quieter_time_within_45_minutes_when_the_day_allows(timings_client, monkeypatch):
    body = plan_day(timings_client(maps(), serpapi=FakeSerpApi(busy=BUSY)), monkeypatch, lunch_day("12:00"))

    lunch = day_rows(body, 1, "visit")[1]
    # Arrival allows 12:15; 12:45 is the quieter time closest to 13:00.
    assert (lunch["place"], lunch["start"], lunch["end"]) == ("Thalassa", "12:45", "13:45")
    assert lunch["busy"] == "Usually busy 13:00–15:00"
    assert lunch["wait"] == 0


def test_F2_otherwise_a_meal_at_a_busy_hour_gets_a_20_minute_wait_and_the_label(timings_client, monkeypatch):
    body = plan_day(timings_client(maps(), serpapi=FakeSerpApi(busy=BUSY)), monkeypatch, lunch_day("12:55"))

    lunch = day_rows(body, 1, "visit")[1]
    assert (lunch["place"], lunch["start"], lunch["end"]) == ("Thalassa", "13:15", "14:35")  # 1 hour plus a 20-minute wait
    assert (lunch["busy"], lunch["wait"]) == ("Usually busy 13:00–15:00", 20)


# --------------------------------------------------------------------------- F3


def test_F3_without_busy_hour_data_theres_no_label_and_no_guess(timings_client, monkeypatch):
    body = plan_day(timings_client(maps(), serpapi=FakeSerpApi(busy={})), monkeypatch, lunch_day("12:00"))

    lunch = day_rows(body, 1, "visit")[1]
    assert (lunch["start"], lunch["end"], lunch["busy"], lunch["wait"]) == ("13:00", "14:00", None, 0)


def test_F3_without_a_serpapi_key_nothing_is_asked_and_nothing_is_labelled(timings_client, monkeypatch):
    body = plan_day(timings_client(maps()), monkeypatch, lunch_day("12:00"))

    lunch = day_rows(body, 1, "visit")[1]
    assert (lunch["busy"], lunch["wait"]) == (None, 0)
