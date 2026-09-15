"""TP-07 A3, C1, C3, C5: one area per day; far areas become a stay there or a day trip (Google, Airbnb and the AI simulated)."""

from __future__ import annotations

from helpers import ScriptedAgent
from test_tp03_stays import AIRBNB_ANSWER, FakeAirbnb
from tp07_support import JAIPUR_TRIP, day_rows, jaipur_maps, plan_day, timings_client  # noqa: F401

JAIPUR_DAY_1 = "## Day 1: Pink City\n- 09:00–11:00: **Hawa Mahal** - the windows.\n- 11:30–13:30: **City Palace** - the courtyards."
AGRA_DAY = "## Day 2: Agra and the Taj Mahal\n- 09:00–12:00: **Taj Mahal** - the mausoleum.\n- 12:30–14:30: **Agra Fort** - the fort.\n- 17:00–18:30: **Mehtab Bagh** - the gardens."
JAIPUR_DAY_3 = "## Day 3: Museums\n- 10:00–12:00: **Albert Hall Museum** - the galleries."
JAIPUR_DAY_4 = "## Day 4: Observatory\n- 10:00–11:00: **Jantar Mantar** - the instruments."
PLAN = "\n\n".join([JAIPUR_DAY_1, AGRA_DAY, JAIPUR_DAY_3, JAIPUR_DAY_4])
# v4 (test data): Mehtab Bagh closes at 18:00 in jaipur_maps, so its visit ends then (it was 17:00–18:30, which the TP-05 hours rule moves).
AGRA_IN_DETAIL = "## Day 2: Agra in detail\n- 07:00–10:00: **Taj Mahal** - sunrise at the mausoleum.\n- 11:00–13:00: **Agra Fort** - the fort.\n- 16:30–18:00: **Mehtab Bagh** - sunset over the Taj."


def day(body, number):
    return next(entry for entry in body["timetable"] if entry["day"] == number)


def places_on(body, number):
    return [row["place"] for row in day_rows(body, number, "visit")]


# --------------------------------------------------------------------------- A3


def test_A3_the_ai_is_told_where_the_stay_is_to_keep_each_day_within_50_km_and_to_cover_that_area_in_detail(timings_client, monkeypatch):
    import main

    agent = ScriptedAgent(JAIPUR_DAY_1)
    monkeypatch.setattr(main, "agent", agent)
    client = timings_client(jaipur_maps())

    r = client.post("/plan-trip", json=JAIPUR_TRIP)

    assert r.status_code == 200, r.text
    prompt = agent.prompts[0]
    assert "Your stay: Jaipur Haveli (C Scheme, Jaipur)" in prompt
    assert "keep each day's places within 50 km of that day's base" in prompt
    assert "cover that area in detail" in prompt
    assert '"(fixed time)"' in prompt


# --------------------------------------------------------------------------- C1


def test_C1_a_far_area_more_than_90_minutes_away_becomes_a_stay_there(timings_client, monkeypatch):
    body = plan_day(timings_client(jaipur_maps()), monkeypatch, PLAN, trip=JAIPUR_TRIP, agent=ScriptedAgent(AGRA_IN_DETAIL))

    agra = day(body, 2)
    assert (agra["kind"], agra["area"], agra["label"]) == ("stay_there", "Agra", "Stay in Agra tonight: 4 h 30 min from Jaipur")
    first_trip = day_rows(body, 2, "travel")[0]
    assert (first_trip["from"], first_trip["to"], first_trip["minutes"]) == ("Jaipur Haveli", "Taj Mahal", 270)
    assert day_rows(body, 2)[-1]["kind"] == "checkin"
    assert day_rows(body, 2)[-1]["place"] == "Your stay in Agra"
    # Far places are never mixed with nearby ones on the same day.
    assert places_on(body, 2) == ["Taj Mahal", "Agra Fort", "Mehtab Bagh"]
    assert places_on(body, 1) == ["Hawa Mahal", "City Palace"]
    assert (day(body, 1)["kind"], day(body, 1)["label"]) == ("base", None)


def test_C1_a_far_area_90_minutes_away_or_less_is_a_day_trip_that_says_when_youre_back(timings_client, monkeypatch):
    stepwell = "## Day 2: Abhaneri stepwell\n- 10:00–12:00: **Chand Baori** - the stepwell."
    plan = "\n\n".join([JAIPUR_DAY_1, stepwell, JAIPUR_DAY_3, JAIPUR_DAY_4])

    body = plan_day(timings_client(jaipur_maps()), monkeypatch, plan, trip=JAIPUR_TRIP, agent=ScriptedAgent(stepwell))

    trip_day = day(body, 2)
    # 85 minutes each way plus a 13-minute buffer: back at 13:38, shown as 13:40.
    assert (trip_day["kind"], trip_day["area"], trip_day["label"]) == ("day_trip", "Abhaneri", "Day trip: 1 h 25 min each way, back by 13:40")
    rows = day_rows(body, 2)
    assert (rows[0]["kind"], rows[0]["place"], rows[0]["time"]) == ("leave", "Jaipur Haveli", "08:00")
    assert (rows[-1]["kind"], rows[-1]["place"], rows[-1]["time"]) == ("back", "Jaipur Haveli", "13:40")


def test_C1_a_single_far_place_on_a_nearby_day_is_replaced_near_the_stay(timings_client, monkeypatch):
    mixed = JAIPUR_DAY_1 + "\n- 14:00–16:00: **Taj Mahal** - the mausoleum."
    plan = "\n\n".join([mixed, JAIPUR_DAY_3, JAIPUR_DAY_4])
    asked = []

    def replacement(name, reason):
        asked.append((name, reason))
        return "Jantar Mantar"

    body = plan_day(timings_client(jaipur_maps()), monkeypatch, plan, trip={**JAIPUR_TRIP, "num_days": 3, "return_date": "2026-10-21"}, replacement=replacement)

    assert asked == [("Taj Mahal", "more than 50 km from your stay")]
    assert places_on(body, 1) == ["Hawa Mahal", "City Palace", "Jantar Mantar"]
    assert day(body, 1)["kind"] == "base"
    assert all(row["minutes"] < 60 for row in day_rows(body, 1, "travel") if row.get("minutes"))


def test_C1_with_one_airbnb_for_the_whole_trip_a_far_area_is_always_a_day_trip(timings_client, monkeypatch):
    trip = {**JAIPUR_TRIP, "stops": [{"place": "Jaipur", "nights": 3}], "stay_per_stop": False}

    body = plan_day(timings_client(jaipur_maps()), monkeypatch, PLAN, trip=trip, agent=ScriptedAgent(AGRA_IN_DETAIL))

    agra = day(body, 2)
    assert agra["kind"] == "day_trip"
    assert agra["label"].startswith("Day trip: 4 h 30 min each way, back by ")
    assert day_rows(body, 2)[-1]["kind"] == "back"


# --------------------------------------------------------------------------- C3


def test_C3_the_ai_rewrites_only_the_day_that_moved_covering_that_area_in_detail(timings_client, monkeypatch):
    agent = ScriptedAgent(AGRA_IN_DETAIL)

    body = plan_day(timings_client(jaipur_maps()), monkeypatch, PLAN, trip=JAIPUR_TRIP, agent=agent)

    assert len(agent.prompts) == 1
    prompt = agent.prompts[0]
    assert PLAN in prompt
    assert "Rewrite only Day 2" in prompt
    assert "Stay in Agra tonight" in prompt
    assert "cover Agra in detail" in prompt
    assert body["itinerary"] == PLAN.replace(AGRA_DAY, AGRA_IN_DETAIL)


# --------------------------------------------------------------------------- C5


def test_C5_the_moving_day_checks_out_travels_and_checks_in_and_stays_there_are_searched_for_its_night(timings_client, monkeypatch):
    airbnb = FakeAirbnb(answer=AIRBNB_ANSWER)
    agent = ScriptedAgent(AGRA_IN_DETAIL)

    body = plan_day(timings_client(jaipur_maps(), airbnb=airbnb), monkeypatch, PLAN, trip=JAIPUR_TRIP, agent=agent)

    # The same nightly limit as the rest of the trip: ₹60,000 × 40% ÷ 3 nights = ₹8,000.
    assert {"location": "Agra", "checkin": "2026-10-20", "checkout": "2026-10-21", "adults": 2, "maxPrice": 8000} in airbnb.calls
    assert "Real Airbnb listings in Agra for its dates" in agent.prompts[0]
    assert body["new_stays"] == [{"place": "Agra", "checkin": "2026-10-20", "checkout": "2026-10-21", "nights": 1}]

    agra_rows = day_rows(body, 2)
    assert (agra_rows[0]["kind"], agra_rows[0]["place"]) == ("checkout", "Jaipur Haveli")
    assert (agra_rows[-1]["kind"], agra_rows[-1]["place"]) == ("checkin", "Your stay in Agra")
    assert day(body, 2)["stay"]["name"] == "Your stay in Agra"

    back = day(body, 3)
    assert (back["kind"], back["label"]) == ("move", "Back to Jaipur: 4 h 30 min from Agra")
    back_rows = day_rows(body, 3)
    assert (back_rows[0]["kind"], back_rows[0]["place"]) == ("checkout", "Your stay in Agra")
    first_trip = day_rows(body, 3, "travel")[0]
    assert (first_trip["from"], first_trip["to"], first_trip["minutes"]) == ("Your stay in Agra", "Albert Hall Museum", 270)
    assert (back_rows[-1]["kind"], back_rows[-1]["place"]) == ("checkin", "Jaipur Haveli")
