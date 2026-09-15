"""TP-06 LIVE tests: real calls. Run with `pytest --live -m live`.

C4, D2: a real 5-day Bali plan (needs OPENAI_API_KEY).
F8: a real change to Day 2 of a 3-day Bali plan keeps Days 1 and 3 (needs OPENAI_API_KEY).
H12: real Airbnb stays for Canggu and Ubud are near their place, for that place's dates (needs AIRBNB_IGNORE_ROBOTS_TXT=1; Photon is free).
"""

from __future__ import annotations

import os
import re
from datetime import date, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.live

BALI_AREAS = (
    "Ubud", "Seminyak", "Canggu", "Kuta", "Legian", "Uluwatu", "Jimbaran", "Nusa Dua", "Sanur", "Denpasar", "Tanah Lot",
    "Tegallalang", "Kintamani", "Munduk", "Bedugul", "Sidemen", "Amed", "Candidasa", "Lovina", "Tulamben",
    "Nusa Penida", "Nusa Lembongan", "Nusa Ceningan", "Gili",
)
NEARBY_ISLANDS = ("Nusa Penida", "Nusa Lembongan", "Nusa Ceningan", "Gili")
_HEADING = re.compile(r"^[^\w\n]{0,8}Day\s*:?\s*(\d{1,2})\b[\s:.\-–]*(.*)$", re.IGNORECASE | re.MULTILINE)
_DATE_WORD = re.compile(
    r"\b(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|mon|tue|wed|thu|fri|sat|sun|january|february|march|april|may|june|july|"
    r"august|september|october|november|december|jan|feb|mar|apr|jun|jul|aug|sep|sept|oct|nov|dec)\b|\b\d{1,4}(?:st|nd|rd|th)?\b",
    re.IGNORECASE,
)


def needs_openai():
    if not os.environ.get("OPENAI_API_KEY"):
        pytest.skip("OPENAI_API_KEY isn't set on this PC")


def bali_trip(days: int) -> dict:
    start = date.today() + timedelta(days=30)
    return {
        "destination": "Bali, Indonesia", "num_days": days, "budget": 150000, "currency": "INR", "num_travelers": 2,
        "trip_type": "Standard", "group_type": "Couple", "preferences": "Beaches, temples and local food.",
        "start_date": start.isoformat(), "return_date": (start + timedelta(days=days - 1)).isoformat(),
    }


def headings(itinerary: str) -> list[tuple[int, str]]:
    return [(int(match.group(1)), match.group(2).replace("**", "").strip(" #*_")) for match in _HEADING.finditer(itinerary)]


def only_date(title: str) -> bool:
    words = _DATE_WORD.findall(title)
    return any(re.search(r"\d", word) for word in words) and re.sub(r"[\s,.()/\-–]+", "", _DATE_WORD.sub("", title)) == ""


@pytest.fixture(scope="module")
def bali_plan() -> str:
    needs_openai()
    import main

    with TestClient(main.app) as client:
        r = client.post("/plan-trip", json=bali_trip(5))
    assert r.status_code == 200, r.text
    return r.json()["itinerary"]


def test_C4_live_bali_headings_name_places_not_dates(bali_plan):
    found = headings(bali_plan)
    print(f"\nLIVE C4 Bali headings: {found}")

    assert [number for number, _ in found][:5] == [1, 2, 3, 4, 5]
    for number, title in found[:5]:
        assert title, f"Day {number} has no title"
        assert not only_date(title), f"Day {number}'s heading is only a date: {title!r}"


def test_D2_live_bali_goes_to_several_areas_and_a_nearby_island(bali_plan):
    titles = [title for _, title in headings(bali_plan)]
    areas = {area for area in BALI_AREAS for title in titles if area.lower() in title.lower()}
    print(f"\nLIVE D2 Bali areas in headings: {sorted(areas)}")

    assert len(areas) >= 3, titles
    assert any(island.lower() in title.lower() for island in NEARBY_ISLANDS for title in titles), titles


def test_F8_live_changing_day_2_keeps_days_1_and_3():
    needs_openai()
    import main
    from plans.days import day_texts

    trip = bali_trip(3)
    with TestClient(main.app) as client:
        first = client.post("/plan-trip", json=trip)
        assert first.status_code == 200, first.text
        before = first.json()["itinerary"]
        r = client.post("/api/revise-plan", json={"itinerary": before, "request": "Day 2: add a beach club at sunset", "trip": trip})

    assert r.status_code == 200, r.text
    after = r.json()["itinerary"]
    old, new = day_texts(before), day_texts(after)
    print(f"\nLIVE F8 Day 2 before: {old.get(2, '')[:200]!r}\nLIVE F8 Day 2 after: {new.get(2, '')[:200]!r}")
    assert r.json()["changed_days"] == [2]
    assert new[1] == old[1]
    assert new[3] == old[3]
    assert new[2] != old[2]


def test_H12_live_each_places_stays_are_near_it_for_its_dates():
    if os.environ.get("AIRBNB_IGNORE_ROBOTS_TXT") != "1":
        pytest.skip("Airbnb stays are off: AIRBNB_IGNORE_ROBOTS_TXT=1 isn't set on this PC")
    import main
    from tripinfo.suggest import PlaceSuggester, distance_km

    start = date.today() + timedelta(days=30)
    suggester = PlaceSuggester()
    stops = [("Canggu", start, start + timedelta(days=3)), ("Ubud", start + timedelta(days=3), start + timedelta(days=5))]
    with TestClient(main.app) as client:
        for place, checkin, checkout in stops:
            spot = suggester.locate(f"{place}, Bali, Indonesia")
            assert spot, f"Photon couldn't find {place}"
            r = client.get("/api/stays", params={
                "place": place, "checkin": checkin.isoformat(), "checkout": checkout.isoformat(), "adults": 2,
                "trip_budget": 150000, "budget_currency": "INR", "trip_type": "Standard", "trip_nights": 5,
            })
            assert r.status_code == 200, r.text
            stays = r.json()["stays"]
            far = [(stay["name"], round(distance_km(spot, stay["location"]), 1)) for stay in stays if stay.get("location") and distance_km(spot, stay["location"]) > 25]
            print(f"\nLIVE H12 {place}: {len(stays)} stays, more than 25 km away: {far}")
            assert stays, f"no stays in {place}"
            assert far == []
            for stay in stays:
                query = parse_qs(urlparse(stay["url"]).query)
                assert (query["check_in"], query["check_out"]) == ([checkin.isoformat()], [checkout.isoformat()])
