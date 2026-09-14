"""TP-03 E1, E2, E4: Airbnb stays through the Airbnb MCP server (server simulated)."""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from helpers import TODAY, FakeClock, load_fixture

AIRBNB_ANSWER = load_fixture("airbnb-search-goa-2026-10-20.json")
STAY_PARAMS = {"place": "Goa, India", "checkin": "2026-10-20", "checkout": "2026-10-25", "adults": "2"}
UNAVAILABLE = "Airbnb stays are temporarily unavailable. Try again in a few minutes."
GOA_TRIP = {
    "destination": "Goa",
    "num_days": 5,
    "budget": 60000,
    "currency": "INR",
    "num_travelers": 2,
    "trip_type": "Standard",
    "group_type": "Couple",
    "preferences": "Beaches and seafood.",
}


class FakeAirbnb:
    """Stands in for the Airbnb MCP server's search tool."""

    def __init__(self, answer=None, error=None, block=None):
        self.answer = answer
        self.error = error
        self.block = block
        self.calls = []

    def search(self, arguments):
        self.calls.append(arguments)
        if self.block is not None:
            self.block.wait(timeout=30)
        if self.error is not None:
            raise self.error
        return self.answer


class FakeAgent:
    def __init__(self):
        self.prompts = []

    def run(self, prompt):
        self.prompts.append(prompt)
        return SimpleNamespace(content="## Day 1: Beaches\nMorning: Swim at Candolim.")


@pytest.fixture
def stays_client():
    import main
    from stays.api import get_stays_service
    from stays.service import StaysService

    clients = []

    def _make(source, clock=None, timeout_s=15.0):
        service = StaysService(source=source, clock=clock or FakeClock(), today=lambda: TODAY, timeout_s=timeout_s)
        main.app.dependency_overrides[get_stays_service] = lambda: service
        client = TestClient(main.app)
        client.__enter__()
        client.service = service
        clients.append(client)
        return client

    yield _make
    for client in clients:
        client.__exit__(None, None, None)
    main.app.dependency_overrides.clear()


# --------------------------------------------------------------------------- E1


def test_E1_stays_come_from_the_airbnb_server_and_are_cached_for_30_minutes(stays_client):
    airbnb = FakeAirbnb(answer=AIRBNB_ANSWER)
    clock = FakeClock()
    client = stays_client(airbnb, clock=clock)

    r = client.get("/api/stays", params=STAY_PARAMS)

    assert r.status_code == 200, r.text
    body = r.json()
    assert airbnb.calls == [{"location": "Goa, India", "checkin": "2026-10-20", "checkout": "2026-10-25", "adults": 2}]
    assert body["query"] == {"place": "Goa, India", "checkin": "2026-10-20", "checkout": "2026-10-25", "adults": 2, "nights": 5}
    assert body["source"] == "airbnb"
    assert body["cached"] is False
    assert body["search_url"].startswith("https://www.airbnb.com/s/Goa--India/homes")
    assert body["count"] == len(body["stays"]) == 3
    assert body["stays"][0] == {
        "id": "12345678",
        "name": "Sea-view studio near Candolim Beach",
        "summary": "Apartment in Candolim",
        "url": "https://www.airbnb.com/rooms/12345678?check_in=2026-10-20&check_out=2026-10-25&adults=2",
        "total_price": 18450,
        "price_per_night": 3690,
        "currency": "INR",
        "nights": 5,
        "rating": 4.92,
        "reviews": 118,
        "photos": [],  # added by TP-04 A1: every stay has a photo list
    }
    new_place = body["stays"][1]
    assert (new_place["total_price"], new_place["price_per_night"]) == (27500, 5500)
    assert (new_place["rating"], new_place["reviews"]) == (None, 0)
    no_price = body["stays"][2]
    assert (no_price["total_price"], no_price["price_per_night"], no_price["currency"]) == (None, None, None)
    assert (no_price["rating"], no_price["reviews"]) == (4.8, 36)

    clock.advance(29 * 60)
    assert client.get("/api/stays", params=STAY_PARAMS).json()["cached"] is True
    assert len(airbnb.calls) == 1

    clock.advance(2 * 60)  # 31 minutes after the first search
    assert client.get("/api/stays", params=STAY_PARAMS).json()["cached"] is False
    assert len(airbnb.calls) == 2


@pytest.mark.parametrize(
    "change, message",
    [
        ({"place": " "}, "Where do you want to stay?"),
        ({"checkin": "20-10-2026"}, "Dates must look like 2026-10-20."),
        ({"checkin": "2026-09-13"}, "Check-in can't be in the past."),
        ({"checkout": "2026-10-20"}, "Check-out must be after check-in."),
        ({"adults": "0"}, "Adults must be between 1 and 16."),
        ({"adults": "17"}, "Adults must be between 1 and 16."),
    ],
)
def test_E1_invalid_stay_searches_get_a_plain_400(stays_client, change, message):
    airbnb = FakeAirbnb(answer=AIRBNB_ANSWER)
    client = stays_client(airbnb)

    r = client.get("/api/stays", params={**STAY_PARAMS, **change})

    assert r.status_code == 400
    assert r.json() == {"error": "invalid_request", "message": message}
    assert airbnb.calls == []


# --------------------------------------------------------------------------- E2


@pytest.mark.parametrize("reason", ["blocked_by_robots_txt", "failed"])
def test_E2_a_failing_airbnb_server_gives_a_plain_503(stays_client, reason):
    from stays.airbnb import StaysUnavailable

    error = StaysUnavailable(reason) if reason != "failed" else RuntimeError("node exited with code 1")
    client = stays_client(FakeAirbnb(error=error))

    r = client.get("/api/stays", params=STAY_PARAMS)

    assert r.status_code == 503
    assert r.json() == {"error": "source_unavailable", "message": UNAVAILABLE, "reason": reason}
    assert "node exited" not in r.text


def test_E2_a_slow_airbnb_server_gives_a_503_within_the_time_limit(stays_client):
    from stays.service import StaysService

    assert StaysService(source=FakeAirbnb()).timeout_s <= 15

    release = threading.Event()
    try:
        client = stays_client(FakeAirbnb(answer=AIRBNB_ANSWER, block=release), timeout_s=0.5)
        started = time.monotonic()
        r = client.get("/api/stays", params=STAY_PARAMS)
        elapsed = time.monotonic() - started
    finally:
        release.set()

    assert r.status_code == 503
    assert r.json()["reason"] == "timeout"
    assert elapsed < 2.5


def test_E2_plan_trip_still_works_when_stays_fail(stays_client, monkeypatch):
    import main

    agent = FakeAgent()
    monkeypatch.setattr(main, "agent", agent)
    client = stays_client(FakeAirbnb(error=RuntimeError("Airbnb server crashed")))

    r = client.post("/plan-trip", json={**GOA_TRIP, "start_date": "2026-10-20"})

    assert r.status_code == 200, r.text
    assert r.json()["status"] == "success"
    assert "Airbnb listings" not in agent.prompts[0]


# --------------------------------------------------------------------------- E4


def test_E4_the_ai_gets_the_real_listings_for_the_destination(stays_client, monkeypatch):
    import main

    agent = FakeAgent()
    monkeypatch.setattr(main, "agent", agent)
    airbnb = FakeAirbnb(answer=AIRBNB_ANSWER)
    client = stays_client(airbnb)

    r = client.post("/plan-trip", json={**GOA_TRIP, "start_date": "2026-10-20"})

    assert r.status_code == 200, r.text
    # maxPrice added by TP-05 D3: 60,000 x 40% (Standard) / 5 nights = 4,800 a night
    assert airbnb.calls == [{"location": "Goa", "checkin": "2026-10-20", "checkout": "2026-10-25", "adults": 2, "maxPrice": 4800}]
    prompt = agent.prompts[0]
    assert "Real Airbnb listings" in prompt
    assert "Sea-view studio near Candolim Beach" in prompt
    assert "INR 18,450 for 5 nights" in prompt
    assert "https://www.airbnb.com/rooms/12345678" in prompt


def test_E4_without_a_start_date_no_stays_are_looked_up(stays_client, monkeypatch):
    import main

    agent = FakeAgent()
    monkeypatch.setattr(main, "agent", agent)
    airbnb = FakeAirbnb(answer=AIRBNB_ANSWER)
    client = stays_client(airbnb)

    r = client.post("/plan-trip", json=GOA_TRIP)

    assert r.status_code == 200
    assert airbnb.calls == []
    assert "Airbnb" not in agent.prompts[0]


# --------------------------------------------------------------------------- E5 (found while connecting Airbnb)


def test_E5_airbnbs_country_redirect_page_is_followed():
    # Found on 14 Sep 2026: from India, www.airbnb.com answers with a small "Redirecting to www.airbnb.co.in"
    # page instead of search results, so every Airbnb search failed (connector issue #60).
    import subprocess
    from pathlib import Path

    handoff_test = Path(__file__).resolve().parents[1] / "mcp-servers" / "airbnb" / "domain-handoff.test.mjs"
    result = subprocess.run(["node", "--test", str(handoff_test)], capture_output=True, text=True, timeout=60)

    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-3000:]


def test_E5_the_airbnb_server_starts_with_the_redirect_fix_loaded():
    from pathlib import Path

    from stays.airbnb import HANDOFF, AirbnbMcpSource

    server = Path("server") / "index.js"
    source = AirbnbMcpSource(server_path=server, ignore_robots_txt=True)

    assert source.server_args() == ["--import", HANDOFF.as_uri(), str(server), "--ignore-robots-txt"]
    assert HANDOFF.exists()
