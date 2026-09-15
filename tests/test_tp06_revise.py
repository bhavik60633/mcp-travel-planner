"""TP-06 F3–F5, H10: asking for changes to a plan (the AI, Airbnb and Google simulated)."""

from __future__ import annotations

import pytest

from helpers import FakeGooglePlaces, ScriptedAgent, jaipur_places_with_hours
from test_tp03_stays import AIRBNB_ANSWER, FakeAirbnb, stays_client  # noqa: F401

BALI = {
    "destination": "Bali, Indonesia",
    "num_days": 3,
    "budget": 60000,
    "currency": "INR",
    "num_travelers": 2,
    "trip_type": "Standard",
    "group_type": "Couple",
    "preferences": "Beaches and temples.",
    "start_date": "2026-10-19",
    "return_date": "2026-10-21",
}
DAY_1 = "## Day 1: Seminyak beaches and sunset\n- 09:00–11:00: **Double Six Beach** - an easy swim.\n- 17:00–19:00: **La Plancha** - sunset drinks."
DAY_2 = "## Day 2: Ubud rice terraces\n- 08:00–10:00: **Tegallalang Rice Terrace** - go early.\n- 11:00–12:30: **Sacred Monkey Forest Sanctuary** - keep bags zipped."
DAY_3 = "## Day 3: Uluwatu cliffs\n- 16:00–18:00: **Uluwatu Temple** - stay for the Kecak dance."
PLAN = f"A 3-day plan for Bali.\n\n{DAY_1}\n\n{DAY_2}\n\n{DAY_3}\n\nEnjoy your trip to Bali!"

NEW_DAY_1 = "## Day 1: Seminyak, slower\n- 10:00–12:00: **Double Six Beach** - a late swim."
NEW_DAY_2 = "## Day 2: Canggu surf and a beach club\n- 09:00–11:00: **Batu Bolong Beach** - surf lesson.\n- 17:00–20:00: **Finns Beach Club** - sunset at the beach club."
NEW_DAY_3 = "## Day 3: Uluwatu sunrise\n- 06:00–08:00: **Uluwatu Temple** - sunrise, fewer people."
FAILED = {"error": "change_failed", "message": "Yori couldn't apply that change. Try saying it another way."}


@pytest.fixture
def client(stays_client):  # noqa: F811
    return stays_client(FakeAirbnb(answer=AIRBNB_ANSWER))


def revise(client, monkeypatch, request, *replies, itinerary=PLAN, trip=BALI):
    import main

    agent = ScriptedAgent(*replies)
    monkeypatch.setattr(main, "agent", agent)
    r = client.post("/api/revise-plan", json={"itinerary": itinerary, "request": request, "trip": trip})
    return r, agent


# --------------------------------------------------------------------------- F3


def test_F3_only_the_named_day_is_rewritten_and_every_other_day_comes_back_exactly(client, monkeypatch):
    r, agent = revise(client, monkeypatch, "Day 2: add a beach club at sunset", NEW_DAY_2)

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "success"
    assert body["changed_days"] == [2]
    assert body["itinerary"] == PLAN.replace(DAY_2, NEW_DAY_2)
    prompt = agent.prompts[0]
    assert "Day 2: add a beach club at sunset" in prompt
    assert PLAN in prompt
    assert "Rewrite only Day 2" in prompt


def test_F3_several_named_days_are_rewritten_and_the_rest_kept(client, monkeypatch):
    r, agent = revise(client, monkeypatch, "Days 1 and 3: less walking", f"{NEW_DAY_1}\n\n{NEW_DAY_3}")

    assert r.status_code == 200, r.text
    assert r.json()["changed_days"] == [1, 3]
    assert r.json()["itinerary"] == PLAN.replace(DAY_1, NEW_DAY_1).replace(DAY_3, NEW_DAY_3)
    assert "Rewrite only Days 1 and 3" in agent.prompts[0]


def test_F3_days_the_ai_rewrites_without_being_asked_are_kept_as_they_were(client, monkeypatch):
    r, _ = revise(client, monkeypatch, "Day 2: add a beach club at sunset", f"{NEW_DAY_1}\n\n{NEW_DAY_2}")

    assert r.status_code == 200, r.text
    assert r.json()["changed_days"] == [2]
    assert r.json()["itinerary"] == PLAN.replace(DAY_2, NEW_DAY_2)


def test_F3_changing_the_last_day_keeps_the_closing_words(client, monkeypatch):
    r, _ = revise(client, monkeypatch, "Day 3: sunrise at the temple instead", NEW_DAY_3)

    assert r.status_code == 200, r.text
    assert r.json()["itinerary"] == PLAN.replace(DAY_3, NEW_DAY_3)


def test_F3_revised_days_follow_the_same_text_rules_as_a_new_plan(client, monkeypatch):
    r, _ = revise(client, monkeypatch, "Day 2: add a beach club at sunset", NEW_DAY_2.replace(" - surf lesson", " — surf lesson"))

    assert r.status_code == 200, r.text
    assert "—" not in r.json()["itinerary"]
    assert r.json()["itinerary"] == PLAN.replace(DAY_2, NEW_DAY_2)


@pytest.mark.parametrize("reply", ["Sorry, I can't change that.", NEW_DAY_1])
def test_F3_a_reply_without_the_named_day_changes_nothing_and_says_so(client, monkeypatch, reply):
    r, _ = revise(client, monkeypatch, "Day 2: add a beach club at sunset", reply)

    assert r.status_code == 502
    assert r.json() == FAILED


@pytest.mark.parametrize(
    "change, message",
    [
        ({"request": "   "}, "Say what you'd like to change."),
        ({"itinerary": ""}, "There's no plan to change."),
        ({"request": "Day 5: a beach day"}, "This trip has 3 days."),
    ],
)
def test_F3_a_request_that_cant_be_applied_gets_a_plain_400(client, monkeypatch, change, message):
    import main

    agent = ScriptedAgent(NEW_DAY_2)
    monkeypatch.setattr(main, "agent", agent)
    body = {"itinerary": PLAN, "request": "Day 2: add a beach club", "trip": BALI, **change}

    r = client.post("/api/revise-plan", json=body)

    assert r.status_code == 400
    assert r.json() == {"error": "invalid_request", "message": message}
    assert agent.prompts == []


# --------------------------------------------------------------------------- F4

WHOLE = (
    "A calmer 3-day plan.\n\n"
    "## Day 1: Seminyak slow morning\n- 10:00–12:00: **Double Six Beach** - a swim.\n\n"
    "## Day 2: Ubud cafes\n- 10:00–12:00: **Sacred Monkey Forest Sanctuary** - a short walk.\n\n"
    "## Day 3: Uluwatu sunset\n- 17:00–19:00: **Uluwatu Temple** - sunset."
)


def test_F4_a_request_that_names_no_day_may_change_the_whole_plan_with_the_same_dates_and_days(client, monkeypatch):
    r, agent = revise(client, monkeypatch, "Make it more relaxed", WHOLE)

    assert r.status_code == 200, r.text
    assert r.json()["itinerary"] == WHOLE
    assert r.json()["changed_days"] == [1, 2, 3]
    prompt = agent.prompts[0]
    assert "Rewrite the whole plan" in prompt
    assert "exactly 3 days" in prompt
    assert "Day 3 is Wednesday 21 October 2026" in prompt


def test_F4_a_whole_plan_with_a_different_number_of_days_is_not_applied(client, monkeypatch):
    two_days = WHOLE.split("\n\n## Day 3")[0]

    r, _ = revise(client, monkeypatch, "Make it more relaxed", two_days)

    assert r.status_code == 502
    assert r.json() == FAILED


# --------------------------------------------------------------------------- F5


def test_F5_a_revised_plan_is_given_the_trips_stays_and_weather_like_a_new_plan(stays_client, monkeypatch):  # noqa: F811
    import main

    airbnb = FakeAirbnb(answer=AIRBNB_ANSWER)
    client = stays_client(airbnb)
    weather = [{"date": "2026-10-19", "high_c": 31, "low_c": 24, "rain_chance": 40, "rain_mm": None, "kind": "forecast"}]
    monkeypatch.setattr(main, "_trip_facts", lambda data, service: {"weather": weather})

    r, agent = revise(client, monkeypatch, "Day 2: add a beach club at sunset", NEW_DAY_2)

    assert r.status_code == 200, r.text
    # ₹60,000 × 40% ÷ 2 nights = ₹12,000 a night
    assert airbnb.calls == [{"location": "Bali, Indonesia", "checkin": "2026-10-19", "checkout": "2026-10-21", "adults": 2, "maxPrice": 12000}]
    prompt = agent.prompts[0]
    assert "Real Airbnb listings" in prompt
    assert "Sea-view studio near Candolim Beach" in prompt
    assert "Weather for the trip days" in prompt


JAIPUR = {
    "destination": "Jaipur",
    "num_days": 2,
    "budget": 45000,
    "currency": "INR",
    "num_travelers": 2,
    "trip_type": "Standard",
    "group_type": "Couple",
    "preferences": "Forts and museums.",
    "start_date": "2026-10-19",
    "return_date": "2026-10-20",
}
JAIPUR_PLAN = (
    "A 2-day plan for Jaipur.\n\n"
    "## Day 1: Pink City\n- 09:00–11:00: **Hawa Mahal** - the latticed windows.\n\n"
    "## Day 2: Views\n- 09:00–11:00: **Nahargarh Viewpoint** - the city from above.\n\n"
    "Enjoy your trip to Jaipur!"
)
NEW_JAIPUR_DAY_2 = "## Day 2: Museums and chai\n- 10:00–12:00: **Albert Hall Museum** - the galleries.\n- 12:30–13:30: **Tapri Central** - chai on the rooftop."


def test_F5_a_revised_plan_gets_opening_hours_checks_like_a_new_plan(review_client, monkeypatch):
    client = review_client(FakeGooglePlaces(places=jaipur_places_with_hours()))

    r, _ = revise(client, monkeypatch, "Day 2: museums instead", NEW_JAIPUR_DAY_2, itinerary=JAIPUR_PLAN, trip=JAIPUR)

    assert r.status_code == 200, r.text
    body = r.json()
    assert [(v["day"], v["start"], v["end"], v["place"], v["status"]) for v in body["visits"]] == [
        (1, "09:00", "11:00", "Hawa Mahal", "open"),
        (2, "10:00", "12:00", "Albert Hall Museum", "open"),
        (2, "12:30", "13:30", "Tapri Central", "open"),
    ]
    assert {"Hawa Mahal", "Albert Hall Museum", "Tapri Central"} <= {place["name"] for place in body["places"]}


# --------------------------------------------------------------------------- H10

STOPS_TRIP = {
    **BALI,
    "num_days": 6,
    "budget": 90000,
    "return_date": "2026-10-24",
    "stops": [{"place": "Canggu", "nights": 3}, {"place": "Ubud", "nights": 2}],
    "stay_per_stop": True,
}
SIX_DAY_PLAN = "A 6-day plan.\n\n" + "\n\n".join(f"## Day {n}: Sights {n}\n- 09:00–11:00: **Sight {n}** - a visit." for n in range(1, 7))


def test_H10_asking_for_changes_keeps_the_places_their_dates_and_their_airbnbs(stays_client, monkeypatch):  # noqa: F811
    airbnb = FakeAirbnb(answer=AIRBNB_ANSWER)
    client = stays_client(airbnb)
    new_day = "## Day 2: Canggu beach club\n- 17:00–20:00: **Finns Beach Club** - sunset."

    r, agent = revise(client, monkeypatch, "Day 2: add a beach club", new_day, itinerary=SIX_DAY_PLAN, trip=STOPS_TRIP)

    assert r.status_code == 200, r.text
    # The same nightly limit at every place (D12): ₹90,000 × 40% ÷ 5 nights = ₹7,200.
    assert sorted(airbnb.calls, key=lambda call: call["checkin"]) == [
        {"location": "Canggu", "checkin": "2026-10-19", "checkout": "2026-10-22", "adults": 2, "maxPrice": 7200},
        {"location": "Ubud", "checkin": "2026-10-22", "checkout": "2026-10-24", "adults": 2, "maxPrice": 7200},
    ]
    prompt = agent.prompts[0]
    assert "Canggu, 3 nights: check in Monday 19 October 2026, check out Thursday 22 October 2026" in prompt
    assert "Ubud, 2 nights: check in Thursday 22 October 2026, check out Saturday 24 October 2026" in prompt
    assert r.json()["itinerary"] == SIX_DAY_PLAN.replace("## Day 2: Sights 2\n- 09:00–11:00: **Sight 2** - a visit.", new_day)
