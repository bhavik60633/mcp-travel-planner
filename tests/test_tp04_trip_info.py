"""TP-04 C1–C6, C10: trip essentials from free services (their real replies from 14 Sep 2026 are replayed)."""

from __future__ import annotations

import re
import threading
import time
from types import SimpleNamespace

import httpx
import pytest
from fastapi.testclient import TestClient

from helpers import TODAY, FakeClock, FakeWeb, tripinfo_fixture

GOA = {"place": "Goa", "start": "2026-10-14", "days": "5", "currency": "INR"}
PARIS = {"place": "Paris", "start": "2026-11-09", "days": "5", "currency": "INR"}
NOT_AVAILABLE = {"available": False, "message": "Not available right now"}


@pytest.fixture
def trip_client():
    import main
    from tripinfo.api import get_trip_info_service
    from tripinfo.service import TripInfoService

    clients = []

    def _make(web=None, clock=None, deadline_s=8.0):
        web = web or FakeWeb()
        service = TripInfoService(
            http_client=httpx.Client(transport=httpx.MockTransport(web)),
            clock=clock or FakeClock(),
            today=lambda: TODAY,
            deadline_s=deadline_s,
        )
        main.app.dependency_overrides[get_trip_info_service] = lambda: service
        client = TestClient(main.app)
        client.__enter__()
        client.web = web
        clients.append(client)
        return client

    yield _make
    for client in clients:
        client.__exit__(None, None, None)
    main.app.dependency_overrides.clear()


def daily(name):
    return tripinfo_fixture(name)["body"]["daily"]


# --------------------------------------------------------------------------- C1


def test_C1_weather_for_each_trip_day_is_last_years_weather_when_the_forecast_doesnt_reach(trip_client):
    client = trip_client()

    r = client.get("/api/trip-info", params=GOA)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["place"] == {"name": "Goa", "country": "India", "country_code": "IN"}
    archive = daily("open-meteo-archive-goa")
    weather = body["weather"]
    assert weather["available"] is True
    assert [day["date"] for day in weather["days"]] == ["2026-10-14", "2026-10-15", "2026-10-16", "2026-10-17", "2026-10-18"]
    assert weather["days"][0] == {
        "date": "2026-10-14",
        "kind": "typical",
        "label": "Typical",
        "high_c": archive["temperature_2m_max"][0],
        "low_c": archive["temperature_2m_min"][0],
        "rain_chance": None,
        "rain_mm": archive["precipitation_sum"][0],
        "sunrise": archive["sunrise"][0][11:16],
        "sunset": archive["sunset"][0][11:16],
    }
    (request,) = client.web.requests_to("archive-api.open-meteo.com")
    assert (request.url.params["start_date"], request.url.params["end_date"]) == ("2025-10-14", "2025-10-18")
    assert (float(request.url.params["latitude"]), float(request.url.params["longitude"])) == (15.3004543, 74.0855134)
    assert client.web.requests_to("api.open-meteo.com") == []
    assert client.web.unexpected == []


def test_C1_weather_uses_the_forecast_for_days_within_its_range(trip_client):
    client = trip_client()

    days = client.get("/api/trip-info", params={**GOA, "start": "2026-09-20"}).json()["weather"]["days"]

    forecast = daily("open-meteo-forecast-goa")
    assert days[0] == {
        "date": "2026-09-20",
        "kind": "forecast",
        "label": "Forecast",
        "high_c": forecast["temperature_2m_max"][0],
        "low_c": forecast["temperature_2m_min"][0],
        "rain_chance": forecast["precipitation_probability_max"][0],
        "rain_mm": None,
        "sunrise": forecast["sunrise"][0][11:16],
        "sunset": forecast["sunset"][0][11:16],
    }
    assert {day["kind"] for day in days} == {"forecast"}
    assert client.web.requests_to("archive-api.open-meteo.com") == []


def test_C1_a_trip_at_the_edge_of_the_forecast_mixes_forecast_and_typical_days(trip_client):
    client = trip_client()

    days = client.get("/api/trip-info", params={**GOA, "start": "2026-09-27"}).json()["weather"]["days"]

    assert [(day["date"], day["kind"]) for day in days] == [
        ("2026-09-27", "forecast"), ("2026-09-28", "forecast"), ("2026-09-29", "forecast"),
        ("2026-09-30", "typical"), ("2026-10-01", "typical"),
    ]


def test_C1_trip_information_is_cached_for_3_hours(trip_client):
    clock = FakeClock()
    client = trip_client(clock=clock)

    assert client.get("/api/trip-info", params=GOA).json()["cached"] is False
    calls = len(client.web.requests)

    clock.advance(3 * 3600 - 60)
    assert client.get("/api/trip-info", params=GOA).json()["cached"] is True
    assert len(client.web.requests) == calls

    clock.advance(120)
    assert client.get("/api/trip-info", params=GOA).json()["cached"] is False
    assert len(client.web.requests) > calls


@pytest.mark.parametrize(
    "change, message",
    [
        ({"place": " "}, "Where are you going?"),
        ({"start": "14-10-2026"}, "Dates must look like 2026-10-20."),
        ({"days": "0"}, "Days must be between 1 and 30."),
        ({"days": "31"}, "Days must be between 1 and 30."),
        ({"currency": "rupees"}, "Currency must be a 3-letter code like INR."),
    ],
)
def test_C1_invalid_requests_get_a_plain_400(trip_client, change, message):
    client = trip_client()

    r = client.get("/api/trip-info", params={**GOA, **change})

    assert r.status_code == 400
    assert r.json() == {"error": "invalid_request", "message": message}


# --------------------------------------------------------------------------- C2


def test_C2_currency_is_one_unit_of_the_trip_currency_in_the_destinations_currency(trip_client):
    client = trip_client()

    currency = client.get("/api/trip-info", params=PARIS).json()["currency"]

    assert currency == {"available": True, "from": "INR", "to": "EUR", "rate": 0.00903, "inverse": 110.74, "date": "2026-09-11", "source": "Frankfurter"}


def test_C2_currency_api_is_used_when_frankfurter_fails(trip_client):
    client = trip_client(web=FakeWeb(fail={"api.frankfurter.dev": 503}))

    currency = client.get("/api/trip-info", params=PARIS).json()["currency"]

    saved = tripinfo_fixture("currency-api-inr")["body"]
    rate = saved["inr"]["eur"]
    assert currency == {"available": True, "from": "INR", "to": "EUR", "rate": rate, "inverse": round(1 / rate, 2), "date": saved["date"], "source": "Currency-api"}


def test_C2_nothing_is_shown_when_both_currencies_are_the_same(trip_client):
    client = trip_client()

    body = client.get("/api/trip-info", params=GOA).json()

    assert body["currency"] is None
    assert client.web.requests_to("api.frankfurter.dev") == []


# --------------------------------------------------------------------------- C3


def test_C3_public_holidays_on_trip_days_with_their_local_names(trip_client):
    client = trip_client()

    holidays = client.get("/api/trip-info", params=PARIS).json()["holidays"]

    assert holidays == {"available": True, "days": [{"date": "2026-11-11", "name": "Armistice Day", "local_name": "Armistice 1918"}]}


def test_C3_a_country_without_holiday_data_says_so(trip_client):
    client = trip_client()

    holidays = client.get("/api/trip-info", params=GOA).json()["holidays"]

    assert holidays == {"available": False, "message": "Public holidays aren't available for India yet."}


# --------------------------------------------------------------------------- C4


def test_C4_destination_intro_and_safety_level_each_with_its_credit(trip_client):
    client = trip_client()

    body = client.get("/api/trip-info", params=GOA).json()

    extract = tripinfo_fixture("wikipedia-goa")["body"]["extract"]
    intro = body["intro"]
    assert intro["available"] is True
    assert intro["title"] == "Goa"
    assert extract.startswith(intro["text"])
    assert 1 <= len(re.findall(r"[.!?](?:\s|$)", intro["text"])) <= 3
    assert intro["url"] == "https://en.wikipedia.org/wiki/Goa"
    assert intro["credit"] == "Wikipedia"
    (wikipedia,) = client.web.requests_to("en.wikipedia.org")
    assert "yoritrip.yorilabs.ai" in wikipedia.headers["User-Agent"]

    country = tripinfo_fixture("warnely-in")["body"]["country"]
    assert body["safety"] == {
        "available": True,
        "score": country["risk_score"],
        "tier": country["risk_tier"],
        "summary": country["summary"],
        "credit": "Warnely (CC BY 4.0)",
        "url": "https://www.warnely.com",
    }


# --------------------------------------------------------------------------- C5


def test_C5_each_part_works_on_its_own_when_a_service_is_down_or_slow(trip_client):
    release = threading.Event()
    client = trip_client(web=FakeWeb(fail={"archive-api.open-meteo.com": "error", "www.warnely.com": release}), deadline_s=1.0)

    started = time.monotonic()
    r = client.get("/api/trip-info", params=GOA)
    elapsed = time.monotonic() - started
    release.set()

    assert r.status_code == 200, r.text
    assert elapsed < 3
    body = r.json()
    assert body["weather"] == NOT_AVAILABLE
    assert body["safety"] == NOT_AVAILABLE
    assert body["intro"]["available"] is True
    assert body["cached"] is False


def test_C5_failed_parts_are_not_cached(trip_client):
    web = FakeWeb(fail={"www.warnely.com": 503})
    client = trip_client(web=web)
    assert client.get("/api/trip-info", params=GOA).json()["safety"] == NOT_AVAILABLE

    web.fail.clear()
    body = client.get("/api/trip-info", params=GOA).json()

    assert body["cached"] is False
    assert body["safety"]["available"] is True


def test_C5_if_the_place_cant_be_found_every_part_says_not_available(trip_client):
    client = trip_client(web=FakeWeb(fail={"photon.komoot.io": "error", "nominatim.openstreetmap.org": 503}))

    r = client.get("/api/trip-info", params=GOA)

    assert r.status_code == 200
    body = r.json()
    assert body["place"] is None
    for part in ("weather", "currency", "holidays", "intro", "safety"):
        assert body[part] == NOT_AVAILABLE, part


def test_C5_nominatim_finds_the_place_when_photon_fails(trip_client):
    client = trip_client(web=FakeWeb(fail={"photon.komoot.io": 503}))

    body = client.get("/api/trip-info", params=GOA).json()

    assert body["place"] == {"name": "Goa", "country": "India", "country_code": "IN"}
    assert body["weather"]["available"] is True
    (nominatim,) = client.web.requests_to("nominatim.openstreetmap.org")
    assert "yoritrip.yorilabs.ai" in nominatim.headers["User-Agent"]


def test_C5_trip_information_waits_at_most_8_seconds_by_default():
    from tripinfo.service import TripInfoService

    assert TripInfoService().deadline_s == 8.0


# --------------------------------------------------------------------------- C6


def test_C6_the_ai_plans_around_the_trips_weather_and_holidays(trip_client, monkeypatch):
    import main
    from stays.api import get_stays_service
    from stays.service import StaysService, StaysUnavailable

    from test_tp03_stays import FakeAirbnb

    client = trip_client()
    stays = StaysService(source=FakeAirbnb(error=StaysUnavailable("failed")), clock=FakeClock(), today=lambda: TODAY)
    main.app.dependency_overrides[get_stays_service] = lambda: stays
    prompts = []

    class RecordingAgent:
        def run(self, prompt):
            prompts.append(prompt)
            return SimpleNamespace(content="## Day 1: Louvre\nMorning: museum.")

    monkeypatch.setattr(main, "agent", RecordingAgent())
    trip = {
        "destination": "Paris", "num_days": 5, "budget": 250000, "currency": "INR", "num_travelers": 2,
        "trip_type": "Standard", "group_type": "Couple", "preferences": "Art.", "start_date": "2026-11-09",
    }

    r = client.post("/plan-trip", json=trip)

    assert r.status_code == 200, r.text
    (prompt,) = prompts
    assert "Weather for the trip days" in prompt
    for day in ("2026-11-09", "2026-11-10", "2026-11-11", "2026-11-12", "2026-11-13"):
        assert day in prompt
    assert "Armistice Day" in prompt
    assert "indoor" in prompt.lower()


def test_C6_without_weather_or_holidays_the_prompt_is_unchanged(monkeypatch):
    import main

    prompts = []

    class RecordingAgent:
        def run(self, prompt):
            prompts.append(prompt)
            return SimpleNamespace(content="ok")

    monkeypatch.setattr(main, "agent", RecordingAgent())
    main.run_travel_planner({
        "destination": "Paris", "num_days": 5, "budget": 250000, "currency": "INR", "num_travelers": 2,
        "trip_type": "Standard", "group_type": "Couple", "preferences": "Art.",
    })

    assert "Weather" not in prompts[0]
    assert "holiday" not in prompts[0].lower()


# --------------------------------------------------------------------------- C10


def test_C10_health_lists_every_information_service_and_whether_its_set_up(api_client, monkeypatch):
    monkeypatch.delenv("GOOGLE_MAPS_API_KEY", raising=False)

    services = api_client.get("/api/health").json()["services"]

    assert services == [
        {"service": "place_finder", "label": "Finding the destination (Photon, Nominatim)", "key": None, "set": True, "status": "ready"},
        {"service": "weather", "label": "Weather (Open-Meteo)", "key": None, "set": True, "status": "ready"},
        {"service": "currency", "label": "Currency rates (Frankfurter, Currency-api)", "key": None, "set": True, "status": "ready"},
        {"service": "holidays", "label": "Public holidays (Nager.Date)", "key": None, "set": True, "status": "ready"},
        {"service": "intro", "label": "Destination intro (Wikipedia)", "key": None, "set": True, "status": "ready"},
        {"service": "safety", "label": "Safety level (Warnely)", "key": None, "set": True, "status": "ready"},
        {"service": "place_checks", "label": "Place checks (Google Maps)", "key": "GOOGLE_MAPS_API_KEY", "set": False, "status": "key missing"},
        # added by TP-05 K1
        {"service": "travel_times", "label": "Travel times (Google Routes)", "key": "GOOGLE_MAPS_API_KEY", "set": False, "status": "key missing"},
    ]
