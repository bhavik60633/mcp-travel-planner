"""TP-06 A6, C1, D1, E3: what the AI is asked for, and the itinerary text Yori returns (the AI and Airbnb simulated)."""

from __future__ import annotations

import re

import pytest

from helpers import ScriptedAgent
from test_tp03_stays import AIRBNB_ANSWER, FakeAirbnb, stays_client  # noqa: F401

BALI = {
    "destination": "Bali, Indonesia",
    "num_days": 6,
    "budget": 90000,
    "currency": "INR",
    "num_travelers": 2,
    "trip_type": "Standard",
    "group_type": "Couple",
    "preferences": "Beaches and temples.",
    "start_date": "2026-10-19",
    "return_date": "2026-10-24",
}
DAY_PLAN = "## Day 1: Canggu beaches\n- 09:00–11:00: **Batu Bolong Beach** - surf lesson."
NEARBY_DAY = "at least one day or half day on a nearby island, town or sight that visitors usually combine with Bali, Indonesia"
NEARBY_LIST = '"Nearby, if you have more time"'


def no_dates(trip: dict) -> dict:
    return {key: value for key, value in trip.items() if key not in ("start_date", "return_date")}


def plan_with(client, monkeypatch, trip, reply=DAY_PLAN):
    import main

    agent = ScriptedAgent(reply)
    monkeypatch.setattr(main, "agent", agent)
    return client.post("/plan-trip", json=trip), agent


# --------------------------------------------------------------------------- A6 (the backend side of the return date)


def test_A6_stays_check_out_on_the_return_date(stays_client, monkeypatch):  # noqa: F811
    airbnb = FakeAirbnb(answer=AIRBNB_ANSWER)

    r, agent = plan_with(stays_client(airbnb), monkeypatch, BALI)

    assert r.status_code == 200, r.text
    # 19 to 24 Oct is 6 days and 5 nights (D1); ₹90,000 × 40% ÷ 5 nights = ₹7,200 a night.
    assert airbnb.calls == [{"location": "Bali, Indonesia", "checkin": "2026-10-19", "checkout": "2026-10-24", "adults": 2, "maxPrice": 7200}]
    assert "Number of days: 6" in agent.prompts[0]
    assert "Return date: 2026-10-24" in agent.prompts[0]


def test_A6_a_same_day_trip_has_no_nights_so_no_stays_are_looked_up(stays_client, monkeypatch):  # noqa: F811
    airbnb = FakeAirbnb(answer=AIRBNB_ANSWER)

    r, _ = plan_with(stays_client(airbnb), monkeypatch, {**BALI, "num_days": 1, "return_date": "2026-10-19"})

    assert r.status_code == 200, r.text
    assert airbnb.calls == []


@pytest.mark.parametrize(
    "change, message",
    [
        ({"return_date": "24-10-2026"}, "Dates must look like 2026-10-20."),
        ({"return_date": "2026-10-18"}, "The return date can't be before the start date."),
    ],
)
def test_A6_an_invalid_return_date_gets_a_plain_400(stays_client, monkeypatch, change, message):  # noqa: F811
    airbnb = FakeAirbnb(answer=AIRBNB_ANSWER)

    r, agent = plan_with(stays_client(airbnb), monkeypatch, {**BALI, **change})

    assert r.status_code == 400
    assert r.json() == {"error": "invalid_request", "message": message}
    assert agent.prompts == []
    assert airbnb.calls == []


# --------------------------------------------------------------------------- C1


def test_C1_the_ai_is_told_to_head_each_day_with_its_area_and_highlights_not_the_date():
    import main

    instructions = str(main.agent.instructions)

    assert "## Day 2: Canggu beaches and Echo Beach" in instructions
    assert "Don't put the date in a day's heading" in instructions


def test_C1_the_prompt_gives_each_days_date_and_weekday(stays_client, monkeypatch):  # noqa: F811
    r, agent = plan_with(stays_client(FakeAirbnb(answer=AIRBNB_ANSWER)), monkeypatch, BALI)

    assert r.status_code == 200, r.text
    prompt = agent.prompts[0]
    for line in ("Day 1 is Monday 19 October 2026", "Day 2 is Tuesday 20 October 2026", "Day 6 is Saturday 24 October 2026"):
        assert line in prompt
    assert "Day 7 is" not in prompt


def test_C1_without_dates_no_weekdays_are_given(api_client, monkeypatch):
    r, agent = plan_with(api_client, monkeypatch, no_dates(BALI))

    assert r.status_code == 200, r.text
    assert re.search(r"Day \d+ is \w+day", agent.prompts[0]) is None


# --------------------------------------------------------------------------- D1


@pytest.mark.parametrize("days", [3, 6])
def test_D1_trips_of_3_days_or_more_spend_a_day_or_half_day_nearby(api_client, monkeypatch, days):
    r, agent = plan_with(api_client, monkeypatch, {**no_dates(BALI), "num_days": days})

    assert r.status_code == 200, r.text
    prompt = agent.prompts[0]
    assert NEARBY_DAY in prompt
    assert "say how to get there and how long it takes" in prompt
    assert NEARBY_LIST not in prompt


@pytest.mark.parametrize("days", [1, 2])
def test_D1_trips_of_1_or_2_days_get_a_short_nearby_list_instead(api_client, monkeypatch, days):
    r, agent = plan_with(api_client, monkeypatch, {**no_dates(BALI), "num_days": days})

    assert r.status_code == 200, r.text
    prompt = agent.prompts[0]
    assert NEARBY_LIST in prompt
    assert NEARBY_DAY not in prompt


# --------------------------------------------------------------------------- E3


def test_E3_the_ai_is_told_not_to_use_em_dashes():
    import main

    instructions = str(main.agent.instructions)

    assert "Don't use em dashes" in instructions
    assert "**Hawa Mahal** —" not in instructions


def test_E3_em_dashes_left_in_the_itinerary_are_replaced_and_time_ranges_are_kept(api_client, monkeypatch):
    reply = (
        "## Day 1: Canggu — surf and sunset\n"
        "- 09:00–11:00: **Batu Bolong Beach** — surf lesson.\n"
        "- 11:30—13:00: **Betelnut Cafe** — lunch.\n"
        "A calm day—no rush."
    )

    r, _ = plan_with(api_client, monkeypatch, no_dates(BALI), reply)

    assert r.status_code == 200, r.text
    assert r.json()["itinerary"] == (
        "## Day 1: Canggu - surf and sunset\n"
        "- 09:00–11:00: **Batu Bolong Beach** - surf lesson.\n"
        "- 11:30–13:00: **Betelnut Cafe** - lunch.\n"
        "A calm day - no rush."
    )
