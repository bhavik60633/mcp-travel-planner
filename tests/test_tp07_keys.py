"""TP-07 K1: without a Google key the plan says its timings aren't checked; /api/health lists real timings and busy hours."""

from __future__ import annotations

from tp07_support import day_rows, goa_maps, plan_day, timings_client  # noqa: F401

DAY = "## Day 1: North Goa\n- 09:00–11:00: **Anjuna Beach** - a swim.\n- 11:30–13:00: **Chapora Fort** - the views.\n"


def test_K1_without_a_google_key_the_plan_says_timings_not_checked_yet_and_every_time_is_an_estimate(timings_client, monkeypatch):
    maps = goa_maps()

    body = plan_day(timings_client(maps, key=None), monkeypatch, DAY)

    assert (body["timings_checked"], body["timings_message"]) == (False, "Timings not checked yet")
    visits = day_rows(body, 1, "visit")
    assert [(row["place"], row["start"], row["end"]) for row in visits] == [("Anjuna Beach", "09:00", "11:00"), ("Chapora Fort", "11:30", "13:00")]
    assert all(row["estimate"] is True for row in visits)
    assert maps.requests == []


def test_K1_with_a_google_key_the_plan_says_its_timings_are_checked(timings_client, monkeypatch):
    body = plan_day(timings_client(goa_maps()), monkeypatch, DAY)

    assert (body["timings_checked"], body["timings_message"]) == (True, None)
    assert all(row["estimate"] is False for row in day_rows(body, 1, "visit"))


def test_K1_health_lists_real_timings_and_busy_hours_and_whether_each_key_is_set(api_client, monkeypatch):
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", "google-test-key-for-health-tp07-0000")
    monkeypatch.delenv("SERPAPI_API_KEY", raising=False)

    r = api_client.get("/api/health")

    services = r.json()["services"]
    assert {"service": "real_timings", "label": "Real timings (Google Routes)", "key": "GOOGLE_MAPS_API_KEY", "set": True, "status": "ready"} in services
    assert {"service": "busy_hours", "label": "Busy hours (SerpApi)", "key": "SERPAPI_API_KEY", "set": False, "status": "key missing"} in services
    assert "google-test-key-for-health-tp07-0000" not in r.text
