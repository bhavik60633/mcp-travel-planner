"""TP-04 A1: Airbnb stay photos (Airbnb server simulated with its real answer for Goa, 14 Sep 2026)."""

from __future__ import annotations

import copy

from helpers import load_fixture
from test_tp03_stays import FakeAirbnb, stays_client  # noqa: F401  (stays_client is a pytest fixture)

WITH_PHOTOS = load_fixture("airbnb-search-goa-2026-10-14-with-photos.json")
PARAMS = {"place": "Goa, India", "checkin": "2026-10-14", "checkout": "2026-10-19", "adults": "2"}


def test_A1_each_stay_gets_up_to_5_airbnb_photos_cover_first(stays_client):  # noqa: F811
    client = stays_client(FakeAirbnb(answer=WITH_PHOTOS))

    r = client.get("/api/stays", params=PARAMS)

    assert r.status_code == 200, r.text
    stays = r.json()["stays"]
    assert len(stays) == 18
    airbnb_order = WITH_PHOTOS["searchResults"][0]["contextualPictures"].split(", ")
    assert stays[0]["photos"] == airbnb_order[:5]
    for stay in stays:
        assert 1 <= len(stay["photos"]) <= 5, stay["name"]
        assert all(photo.startswith("https://a0.muscache.com/") for photo in stay["photos"]), stay["photos"]


def test_A1_a_stay_without_photos_gets_an_empty_list_never_a_broken_link(stays_client):  # noqa: F811
    answer = copy.deepcopy(WITH_PHOTOS)
    del answer["searchResults"][0]["contextualPictures"]
    answer["searchResults"][1]["contextualPictures"] = "http://a0.muscache.com/plain-http.jpg, , javascript:alert(1), https://example.com/elsewhere.jpg"
    client = stays_client(FakeAirbnb(answer=answer))

    stays = client.get("/api/stays", params=PARAMS).json()["stays"]

    assert stays[0]["photos"] == []
    assert stays[1]["photos"] == []
    assert stays[2]["photos"]


def test_A2_the_photo_field_is_switched_on_only_for_the_pinned_airbnb_server():
    import subprocess
    from pathlib import Path

    photos_test = Path(__file__).resolve().parents[1] / "mcp-servers" / "airbnb" / "airbnb-photos.test.mjs"
    result = subprocess.run(["node", "--test", str(photos_test)], capture_output=True, text=True, timeout=60)

    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-3000:]
