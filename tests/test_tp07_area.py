"""TP-07 N1–N3, C4: places are found on Google near that day's base (Google and the AI simulated)."""

from __future__ import annotations

import pytest

from helpers import ScriptedAgent
from tp07_support import (  # noqa: F401
    ANJUNA_VILLA,
    GOA_TRIP,
    HALF_LAT_50_KM,
    JAIPUR_TRIP,
    centre_and_half_height,
    goa_maps,
    jaipur_maps,
    plan_day,
    timings_client,
)

GOA_DAY = (
    "## Day 1: North Goa beaches\n"
    "- 09:00–11:00: **Anjuna Beach** - a swim.\n"
    "- 11:30–12:30: **Cafe Coffee Day** - coffee.\n"
    "- 13:00–15:00: **Chapora Fort** - the views.\n"
)


def searches_for(maps, names):
    return [search for search in maps.place_searches() if search["query"].split(", ")[0] in names]


def entry(body, query):
    return next(place for place in body["places"] if place["query"] == query)


# --------------------------------------------------------------------------- N1


def test_N1_every_place_is_searched_near_your_stay(timings_client, monkeypatch):
    maps = goa_maps()

    plan_day(timings_client(maps), monkeypatch, GOA_DAY)

    searches = searches_for(maps, {"Anjuna Beach", "Cafe Coffee Day", "Chapora Fort"})
    assert {search["query"].split(", ")[0] for search in searches} == {"Anjuna Beach", "Cafe Coffee Day", "Chapora Fort"}
    for search in searches:
        assert search["restriction"] is not None, search
        centre, half_height = centre_and_half_height(search["restriction"])
        assert centre == pytest.approx((ANJUNA_VILLA["lat"], ANJUNA_VILLA["lng"]), abs=0.01)
        assert half_height == pytest.approx(HALF_LAT_50_KM, abs=0.01)


def test_N1_a_request_without_a_stay_searches_near_the_destinations_centre(timings_client, monkeypatch):
    maps = goa_maps()
    trip = {key: value for key, value in GOA_TRIP.items() if key != "stay"}
    day = "## Day 1: Candolim\n- 09:30–11:30: **Fort Aguada** - the lighthouse.\n- 12:00–13:00: **Cafe Coffee Day** - coffee.\n"

    body = plan_day(timings_client(maps), monkeypatch, day, trip=trip)

    for search in searches_for(maps, {"Fort Aguada", "Cafe Coffee Day"}):
        centre, _ = centre_and_half_height(search["restriction"])
        assert centre == pytest.approx((15.30, 74.08), abs=0.01)
    assert body["timetable"][0]["stay"]["name"] == "Your stay's area"


# --------------------------------------------------------------------------- N2


def test_N2_a_match_more_than_50_km_from_the_base_counts_as_not_found_and_is_replaced_near_it(timings_client, monkeypatch):
    maps = goa_maps()
    asked = []
    day = "## Day 1: North Goa\n- 09:00–11:00: **Anjuna Beach** - a swim.\n- 11:30–13:30: **Pranjal Beach** - a quiet beach.\n- 14:00–16:00: **Chapora Fort** - the views.\n"

    def replacement(name, reason):
        asked.append((name, reason))
        return "Vagator Beach"

    body = plan_day(timings_client(maps), monkeypatch, day, replacement=replacement)

    assert asked == [("Pranjal Beach", "more than 50 km from your stay")]
    replaced = entry(body, "Vagator Beach")
    assert (replaced["status"], replaced["replaces"], replaced["reason"]) == ("replaced", "Pranjal Beach", "more than 50 km from your stay")
    assert "**Vagator Beach**" in body["itinerary"] and "Pranjal" not in body["itinerary"]
    everything = str(body)
    assert "Gokarna" not in everything and "Pranjal Guest House" not in everything
    for search in searches_for(maps, {"Vagator Beach"}):
        centre, _ = centre_and_half_height(search["restriction"])
        assert centre == pytest.approx((ANJUNA_VILLA["lat"], ANJUNA_VILLA["lng"]), abs=0.01)


def test_N2_a_same_named_place_in_another_state_is_never_used(timings_client, monkeypatch):
    body = plan_day(timings_client(goa_maps()), monkeypatch, GOA_DAY)

    cafe = entry(body, "Cafe Coffee Day")
    assert cafe["status"] == "confirmed"
    assert "Bengaluru" not in str(body)


# --------------------------------------------------------------------------- N3


def test_N3_a_chain_matches_the_branch_nearest_your_stay(timings_client, monkeypatch):
    body = plan_day(timings_client(goa_maps()), monkeypatch, GOA_DAY)

    # Google lists the Panaji branch first; the Candolim branch is nearer the stay in Anjuna.
    assert entry(body, "Cafe Coffee Day")["address"] == "Cafe Coffee Day, Candolim"


def test_N3_without_a_stay_a_chain_matches_the_branch_nearest_the_days_other_places(timings_client, monkeypatch):
    trip = {key: value for key, value in GOA_TRIP.items() if key != "stay"}
    day = "## Day 1: Candolim\n- 09:30–11:30: **Fort Aguada** - the lighthouse.\n- 12:00–13:00: **Cafe Coffee Day** - coffee.\n"

    body = plan_day(timings_client(goa_maps()), monkeypatch, day, trip=trip)

    # Nearest the destination's centre would be Panaji; nearest Fort Aguada, the day's other place, is Candolim.
    assert entry(body, "Cafe Coffee Day")["address"] == "Cafe Coffee Day, Candolim"


# --------------------------------------------------------------------------- C4

AGRA_DAY_TRIP = (
    "## Day 1: Pink City\n- 09:00–11:00: **Hawa Mahal** - the windows.\n\n"
    "## Day 2: Day trip to Agra\n- 10:00–12:00: **Agra Fort** - the red fort.\n- 12:30–13:30: **Sadar Bazar** - shopping.\n\n"
    "## Day 3: Museums\n- 10:00–12:00: **Albert Hall Museum** - the galleries.\n\n"
    "## Day 4: Observatory\n- 10:00–11:00: **Jantar Mantar** - the instruments.\n"
)


def test_C4_places_on_a_day_trip_are_looked_up_near_the_day_trip_town(timings_client, monkeypatch):
    maps = jaipur_maps()
    agra_day = AGRA_DAY_TRIP.split("\n\n")[1]

    body = plan_day(timings_client(maps), monkeypatch, AGRA_DAY_TRIP, trip=JAIPUR_TRIP, agent=ScriptedAgent(agra_day))

    assert entry(body, "Sadar Bazar")["address"] == "Sadar Bazar, Agra"
    agra_searches = [search for search in searches_for(maps, {"Sadar Bazar", "Agra Fort"}) if search["restriction"]]
    assert agra_searches
    final = agra_searches[-1]
    centre, _ = centre_and_half_height(final["restriction"])
    assert centre == pytest.approx((27.1767, 78.0081), abs=0.05)
