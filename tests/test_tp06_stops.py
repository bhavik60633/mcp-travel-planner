"""TP-06 H2, H5–H9: several places and several Airbnbs (the AI, Photon and Airbnb simulated)."""

from __future__ import annotations

import copy
import threading

import httpx
import pytest
from fastapi.testclient import TestClient

from helpers import FakeClock, FakePhoton, ScriptedAgent
from test_tp03_stays import AIRBNB_ANSWER, STAY_PARAMS, FakeAirbnb, stays_client  # noqa: F401

STOPS_REQUEST = {
    "destination": "Bali, Indonesia",
    "start_date": "2026-10-19",
    "return_date": "2026-10-24",
    "num_travelers": 2,
    "trip_type": "Standard",
    "preferences": "Beaches and rice terraces.",
}
ONE_PLACE = {"place": "Bali, Indonesia", "nights": 5, "checkin": "2026-10-19", "checkout": "2026-10-24"}


class BrokenAgent:
    def __init__(self):
        self.prompts = []

    def run(self, prompt):
        self.prompts.append(prompt)
        raise RuntimeError("model unavailable")


@pytest.fixture
def photon_client():
    import main
    from tripinfo.api import get_place_suggester
    from tripinfo.suggest import PlaceSuggester

    clients = []

    def _make(photon=None, timeout_s=3.0, clock=None):
        photon = photon or FakePhoton()
        suggester = PlaceSuggester(http_client=httpx.Client(transport=httpx.MockTransport(photon)), timeout_s=timeout_s, clock=clock or FakeClock())
        main.app.dependency_overrides[get_place_suggester] = lambda: suggester
        client = TestClient(main.app)
        client.__enter__()
        client.photon = photon
        clients.append(client)
        return client

    yield _make
    for client in clients:
        client.__exit__(None, None, None)
    main.app.dependency_overrides.clear()


def suggest_stops(client, monkeypatch, agent, request=STOPS_REQUEST):
    import main

    monkeypatch.setattr(main, "agent", agent)
    return client.post("/api/plan-stops", json=request)


# --------------------------------------------------------------------------- H2


def test_H2_yori_suggests_places_and_nights_that_add_up_to_the_trip(photon_client, monkeypatch):
    client = photon_client()
    agent = ScriptedAgent("Canggu | 3\nUbud | 2")

    r = suggest_stops(client, monkeypatch, agent)

    assert r.status_code == 200, r.text
    assert r.json() == {
        "stops": [
            {"place": "Canggu", "nights": 3, "checkin": "2026-10-19", "checkout": "2026-10-22"},
            {"place": "Ubud", "nights": 2, "checkin": "2026-10-22", "checkout": "2026-10-24"},
        ],
        "suggested": True,
        "message": None,
    }
    prompt = agent.prompts[0]
    assert "Bali, Indonesia" in prompt
    assert "5 nights" in prompt
    assert "at most 2 places" in prompt
    assert "Place | nights" in prompt
    assert {"Bali, Indonesia", "Canggu, Bali, Indonesia", "Ubud, Bali, Indonesia"} <= set(client.photon.queries)


def test_H2_at_most_one_place_per_2_nights_and_the_last_place_takes_the_nights_left(photon_client, monkeypatch):
    client = photon_client()

    r = suggest_stops(client, monkeypatch, ScriptedAgent("Canggu | 2\nUbud | 2\nNusa Penida | 1"))

    assert r.status_code == 200, r.text
    assert [(stop["place"], stop["nights"]) for stop in r.json()["stops"]] == [("Canggu", 2), ("Ubud", 3)]


@pytest.mark.parametrize("reply, nights", [("Canggu | 3\nUbud | 3", [3, 2]), ("Canggu | 1\nUbud | 1", [1, 4])])
def test_H2_nights_that_dont_add_up_are_evened_out_on_the_last_place(photon_client, monkeypatch, reply, nights):
    client = photon_client()

    r = suggest_stops(client, monkeypatch, ScriptedAgent(reply))

    assert r.status_code == 200, r.text
    assert [stop["nights"] for stop in r.json()["stops"]] == nights
    assert r.json()["suggested"] is True


def test_H2_at_most_6_places():
    from plans.stops import max_places

    assert [max_places(nights) for nights in (1, 2, 3, 5, 12, 13)] == [1, 1, 1, 2, 6, 6]


@pytest.mark.parametrize(
    "reply, message",
    [
        ("Canggu | 3\nAtlantis Reef Hideaway | 2", "Yori couldn't find Atlantis Reef Hideaway on the map, so the trip stays in Bali, Indonesia for now."),
        ("Canggu | 3\nJakarta | 2", "Jakarta is more than 300 km from Bali, Indonesia, so the trip stays in Bali, Indonesia for now."),
        ("Here are some ideas: stay in the south, then the hills.", "Yori couldn't suggest places right now, so the trip stays in Bali, Indonesia for now."),
    ],
)
def test_H2_when_a_place_cant_be_used_the_trip_stays_in_the_destination_and_says_why(photon_client, monkeypatch, reply, message):
    client = photon_client()

    r = suggest_stops(client, monkeypatch, ScriptedAgent(reply))

    assert r.status_code == 200, r.text
    assert r.json() == {"stops": [ONE_PLACE], "suggested": False, "message": message}


def test_H2_when_the_ai_fails_the_trip_stays_in_the_destination(photon_client, monkeypatch):
    client = photon_client()

    r = suggest_stops(client, monkeypatch, BrokenAgent())

    assert r.status_code == 200, r.text
    assert r.json() == {"stops": [ONE_PLACE], "suggested": False, "message": "Yori couldn't suggest places right now, so the trip stays in Bali, Indonesia for now."}


@pytest.mark.parametrize("fail", [503, "error"])
def test_H2_when_the_map_cant_be_checked_the_trip_stays_in_the_destination(photon_client, monkeypatch, fail):
    client = photon_client(FakePhoton(fail=fail))

    r = suggest_stops(client, monkeypatch, ScriptedAgent("Canggu | 3\nUbud | 2"))

    assert r.status_code == 200, r.text
    assert r.json() == {"stops": [ONE_PLACE], "suggested": False, "message": "Yori couldn't check the places on the map right now, so the trip stays in Bali, Indonesia for now."}


@pytest.mark.parametrize(
    "change, message",
    [
        ({"destination": " "}, "Where are you going?"),
        ({"start_date": "19-10-2026"}, "Dates must look like 2026-10-20."),
        ({"return_date": "2026-10-18"}, "The return date can't be before the start date."),
        ({"return_date": "2026-11-02"}, "A trip can be at most 14 days."),
    ],
)
def test_H2_an_invalid_request_gets_a_plain_400(photon_client, monkeypatch, change, message):
    client = photon_client()
    agent = ScriptedAgent("Canggu | 3\nUbud | 2")

    r = suggest_stops(client, monkeypatch, agent, {**STOPS_REQUEST, **change})

    assert r.status_code == 400
    assert r.json() == {"error": "invalid_request", "message": message}
    assert agent.prompts == []


# --------------------------------------------------------------------------- H5

TRIP = {
    "destination": "Bali, Indonesia",
    "num_days": 6,
    "budget": 90000,
    "currency": "INR",
    "num_travelers": 2,
    "trip_type": "Standard",
    "group_type": "Couple",
    "preferences": "Beaches and rice terraces.",
    "start_date": "2026-10-19",
    "return_date": "2026-10-24",
}
TWO_PLACES = [{"place": "Canggu", "nights": 3}, {"place": "Ubud", "nights": 2}]
DAY_PLAN = "## Day 1: Canggu beaches\n- 09:00–11:00: **Batu Bolong Beach** - surf lesson."


def plan_with(client, monkeypatch, trip):
    import main

    agent = ScriptedAgent(DAY_PLAN)
    monkeypatch.setattr(main, "agent", agent)
    return client.post("/plan-trip", json=trip), agent


@pytest.mark.parametrize(
    "change, message",
    [
        ({"stops": [{"place": "Canggu", "nights": 3}, {"place": "Ubud", "nights": 3}]}, "The nights at each place must add up to the trip's 5 nights."),
        ({"stops": [{"place": f"Place {n}", "nights": 1} for n in range(7)]}, "A trip can have at most 6 places."),
        ({"stops": [{"place": "  ", "nights": 3}, {"place": "Ubud", "nights": 2}]}, "Every place needs a name."),
        ({"stops": [{"place": "Canggu", "nights": 0}, {"place": "Ubud", "nights": 5}]}, "Each place needs at least 1 night."),
        ({"stops": [], "stay_per_stop": True}, "Choose at least one place."),
        ({"return_date": None}, "Several places need a start date and a return date."),
    ],
)
def test_H5_a_trip_with_places_that_dont_fit_is_refused_with_a_clear_message(stays_client, monkeypatch, change, message):  # noqa: F811
    airbnb = FakeAirbnb(answer=AIRBNB_ANSWER)
    trip = {**TRIP, "stops": TWO_PLACES, "stay_per_stop": True, **change}
    trip = {key: value for key, value in trip.items() if value is not None}

    r, agent = plan_with(stays_client(airbnb), monkeypatch, trip)

    assert r.status_code == 400
    assert r.json() == {"error": "invalid_request", "message": message}
    assert agent.prompts == []
    assert airbnb.calls == []


# --------------------------------------------------------------------------- H6


def test_H6_each_place_gets_its_own_airbnbs_for_its_own_dates_and_the_ai_plans_the_move(stays_client, monkeypatch):  # noqa: F811
    answer = copy.deepcopy(AIRBNB_ANSWER)
    # Priced per night, so the first stay fits the ₹7,200 limit at both places (the saved answer is priced for 5 nights).
    answer["searchResults"][0]["structuredDisplayPrice"]["primaryLine"]["accessibilityLabel"] = "₹3,690 a night"
    airbnb = FakeAirbnb(answer=answer)

    r, agent = plan_with(stays_client(airbnb), monkeypatch, {**TRIP, "stops": TWO_PLACES, "stay_per_stop": True})

    assert r.status_code == 200, r.text
    # The same nightly limit at every place (D12): ₹90,000 × 40% ÷ 5 nights = ₹7,200.
    assert sorted(airbnb.calls, key=lambda call: call["checkin"]) == [
        {"location": "Canggu", "checkin": "2026-10-19", "checkout": "2026-10-22", "adults": 2, "maxPrice": 7200},
        {"location": "Ubud", "checkin": "2026-10-22", "checkout": "2026-10-24", "adults": 2, "maxPrice": 7200},
    ]
    prompt = agent.prompts[0]
    assert "Canggu, 3 nights: check in Monday 19 October 2026, check out Thursday 22 October 2026" in prompt
    assert "Ubud, 2 nights: check in Thursday 22 October 2026, check out Saturday 24 October 2026" in prompt
    assert "Real Airbnb listings in Canggu for its dates, up to INR 7,200 a night" in prompt
    assert "Real Airbnb listings in Ubud for its dates, up to INR 7,200 a night" in prompt
    assert "plan the check-out, how to get to the next place with the travel time, and the check-in" in prompt
    assert '"## Day 4: Move to Ubud' in prompt


# --------------------------------------------------------------------------- H7


@pytest.mark.parametrize(
    "stops, base, day_trips",
    [
        (TWO_PLACES, "Canggu", "Ubud"),
        ([{"place": "Canggu", "nights": 2}, {"place": "Ubud", "nights": 3}], "Ubud", "Canggu"),
        ([{"place": "Seminyak", "nights": 2}, {"place": "Canggu", "nights": 1}, {"place": "Ubud", "nights": 2}], "Seminyak", "Canggu and Ubud"),
    ],
)
def test_H7_one_airbnb_for_several_places_is_at_the_place_with_the_most_nights(stays_client, monkeypatch, stops, base, day_trips):  # noqa: F811
    airbnb = FakeAirbnb(answer=AIRBNB_ANSWER)

    r, agent = plan_with(stays_client(airbnb), monkeypatch, {**TRIP, "stops": stops, "stay_per_stop": False})

    assert r.status_code == 200, r.text
    assert airbnb.calls == [{"location": base, "checkin": "2026-10-19", "checkout": "2026-10-24", "adults": 2, "maxPrice": 7200}]
    prompt = agent.prompts[0]
    assert f"Stay in one place for the whole trip: {base}" in prompt
    assert f"Plan {day_trips} as day trips from {base}, with travel times" in prompt


# --------------------------------------------------------------------------- H8


def test_H8_stays_include_each_listings_map_position(stays_client):  # noqa: F811
    answer = copy.deepcopy(AIRBNB_ANSWER)
    del answer["searchResults"][1]["demandStayListing"]["location"]
    client = stays_client(FakeAirbnb(answer=answer))

    stays = client.get("/api/stays", params=STAY_PARAMS).json()["stays"]

    assert stays[0]["location"] == {"lat": 15.5186, "lng": 73.7625}
    assert stays[1]["location"] is None


# --------------------------------------------------------------------------- H9 (the backend side of stays per place)


def test_H9_a_places_stays_use_the_nightly_limit_of_the_whole_trip(stays_client):  # noqa: F811
    airbnb = FakeAirbnb(answer=AIRBNB_ANSWER)
    client = stays_client(airbnb)
    params = {"place": "Canggu", "checkin": "2026-10-19", "checkout": "2026-10-22", "adults": "2", "trip_budget": "90000", "budget_currency": "INR", "trip_type": "Standard"}

    r = client.get("/api/stays", params={**params, "trip_nights": "5"})

    assert r.status_code == 200, r.text
    # ₹90,000 × 40% ÷ the trip's 5 nights, not ÷ the 3 nights in Canggu (D12).
    assert airbnb.calls[0]["maxPrice"] == 7200
    assert r.json()["budget"]["max_per_night"] == 7200


@pytest.mark.parametrize("value", ["0", "-1", "two"])
def test_H9_an_invalid_trip_nights_gets_a_plain_400(stays_client, value):  # noqa: F811
    client = stays_client(FakeAirbnb(answer=AIRBNB_ANSWER))

    r = client.get("/api/stays", params={**STAY_PARAMS, "trip_budget": "90000", "trip_nights": value})

    assert r.status_code == 400
    assert r.json() == {"error": "invalid_request", "message": "Trip nights must be a whole number above 0."}


def test_H2_a_slow_map_check_doesnt_hold_up_the_answer(photon_client, monkeypatch):
    import time

    release = threading.Event()
    try:
        client = photon_client(FakePhoton(fail=release), timeout_s=0.5)
        started = time.monotonic()
        r = suggest_stops(client, monkeypatch, ScriptedAgent("Canggu | 3\nUbud | 2"))
        elapsed = time.monotonic() - started
    finally:
        release.set()

    assert r.status_code == 200, r.text
    assert r.json()["suggested"] is False
    assert elapsed < 3.0
