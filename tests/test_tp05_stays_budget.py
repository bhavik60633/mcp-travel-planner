"""TP-05 D1–D3: Airbnb stays within the trip's budget, and K1: travel times in /api/health."""

from __future__ import annotations

import pytest

from helpers import load_fixture
from test_tp03_stays import AIRBNB_ANSWER, GOA_TRIP, STAY_PARAMS, FakeAgent, FakeAirbnb, stays_client  # noqa: F401


# --------------------------------------------------------------------------- D1


def test_D1_the_most_per_night_is_sent_to_airbnb_and_stays_above_it_are_left_out(stays_client):  # noqa: F811
    airbnb = FakeAirbnb(answer=AIRBNB_ANSWER)
    client = stays_client(airbnb)

    r = client.get("/api/stays", params={**STAY_PARAMS, "max_per_night": "4000"})

    assert r.status_code == 200, r.text
    assert airbnb.calls == [{"location": "Goa, India", "checkin": "2026-10-20", "checkout": "2026-10-25", "adults": 2, "maxPrice": 4000}]
    body = r.json()
    # ₹3,690 a night stays; ₹5,500 a night is above the limit; a stay without a price can't be shown as within it.
    assert [stay["price_per_night"] for stay in body["stays"]] == [3690]
    assert body["count"] == 1
    assert body["query"]["max_per_night"] == 4000
    assert body["budget"] == {"max_per_night": 4000, "currency": "INR"}


@pytest.mark.parametrize("value", ["0", "-5", "abc", "4000.5"])
def test_D1_an_invalid_nightly_limit_gets_a_plain_400(stays_client, value):  # noqa: F811
    airbnb = FakeAirbnb(answer=AIRBNB_ANSWER)
    client = stays_client(airbnb)

    r = client.get("/api/stays", params={**STAY_PARAMS, "max_per_night": value})

    assert r.status_code == 400
    assert r.json() == {"error": "invalid_request", "message": "The most per night must be a whole number above 0."}
    assert airbnb.calls == []


def test_D1_searches_with_different_limits_are_not_mixed_up_in_the_cache(stays_client):  # noqa: F811
    airbnb = FakeAirbnb(answer=AIRBNB_ANSWER)
    client = stays_client(airbnb)

    low = client.get("/api/stays", params={**STAY_PARAMS, "max_per_night": "4000"}).json()
    high = client.get("/api/stays", params={**STAY_PARAMS, "max_per_night": "6000"}).json()

    assert [call["maxPrice"] for call in airbnb.calls] == [4000, 6000]
    assert (low["count"], high["count"]) == (1, 2)


# --------------------------------------------------------------------------- D2


def test_D2_the_nightly_stay_budget_is_the_trip_types_share_of_the_budget_divided_by_the_nights():
    from stays.budget import STAY_SHARES, nightly_stay_budget

    assert STAY_SHARES == {"Budget": 0.30, "Standard": 0.40, "Luxury": 0.50}
    assert nightly_stay_budget(60000, "INR", "Standard", 5) == {"max_per_night": 4800, "currency": "INR", "share": 40, "trip_budget": 60000, "trip_currency": "INR"}
    assert nightly_stay_budget(60000, "INR", "Budget", 5)["max_per_night"] == 3600
    assert nightly_stay_budget(60000, "INR", "Luxury", 5)["max_per_night"] == 6000
    assert nightly_stay_budget(60000, "INR", "Backpacking", 5)["share"] == 40  # unknown trip types count as Standard


def test_D2_a_budget_in_another_currency_is_converted_to_rupees():
    from stays.budget import nightly_stay_budget

    budget = nightly_stay_budget(1000, "USD", "Standard", 4, rate_to_inr=lambda code: {"USD": 88.2}[code])

    assert budget == {"max_per_night": 8820, "currency": "INR", "share": 40, "trip_budget": 1000, "trip_currency": "USD"}


def test_D2_without_a_currency_rate_there_is_no_limit_rather_than_a_wrong_one():
    from stays.budget import nightly_stay_budget

    def no_rate(code):
        raise RuntimeError("rates unavailable")

    assert nightly_stay_budget(1000, "USD", "Standard", 4, rate_to_inr=no_rate) is None


def test_D2_api_stays_works_out_the_limit_from_the_trip_budget(stays_client):  # noqa: F811
    airbnb = FakeAirbnb(answer=AIRBNB_ANSWER)
    client = stays_client(airbnb)

    r = client.get("/api/stays", params={**STAY_PARAMS, "trip_budget": "60000", "budget_currency": "INR", "trip_type": "Standard"})

    assert r.status_code == 200, r.text
    assert airbnb.calls[0]["maxPrice"] == 4800
    assert r.json()["budget"] == {"max_per_night": 4800, "currency": "INR", "share": 40, "trip_budget": 60000, "trip_currency": "INR"}


def test_D2_a_limit_the_traveller_sets_wins_over_the_trip_budget(stays_client):  # noqa: F811
    airbnb = FakeAirbnb(answer=AIRBNB_ANSWER)
    client = stays_client(airbnb)

    body = client.get("/api/stays", params={**STAY_PARAMS, "trip_budget": "60000", "budget_currency": "INR", "trip_type": "Standard", "max_per_night": "6000"}).json()

    assert airbnb.calls[0]["maxPrice"] == 6000
    assert body["budget"] == {"max_per_night": 6000, "currency": "INR", "share": 40, "trip_budget": 60000, "trip_currency": "INR"}


# --------------------------------------------------------------------------- D3


def test_D3_the_ai_is_given_only_stays_within_the_trip_budget(stays_client, monkeypatch):  # noqa: F811
    import main

    agent = FakeAgent()
    monkeypatch.setattr(main, "agent", agent)
    airbnb = FakeAirbnb(answer=AIRBNB_ANSWER)
    client = stays_client(airbnb)

    r = client.post("/plan-trip", json={**GOA_TRIP, "start_date": "2026-10-20"})

    assert r.status_code == 200, r.text
    assert airbnb.calls[0]["maxPrice"] == 4800  # ₹60,000 × 40% ÷ 5 nights
    prompt = agent.prompts[0]
    assert "Sea-view studio near Candolim Beach" in prompt
    assert prompt.count("https://www.airbnb.com/rooms/") == 1
    assert "up to INR 4,800 a night" in prompt


# --------------------------------------------------------------------------- K1


def test_K1_health_lists_travel_times_and_whether_the_google_key_is_set(api_client, monkeypatch):
    key = "google-test-key-for-health-k1-0000"
    monkeypatch.setenv("GOOGLE_MAPS_API_KEY", key)

    r = api_client.get("/api/health")

    assert {"service": "travel_times", "label": "Travel times (Google Routes)", "key": "GOOGLE_MAPS_API_KEY", "set": True, "status": "ready"} in r.json()["services"]
    assert key not in r.text
