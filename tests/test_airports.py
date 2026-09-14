"""TP-01 C10: airport lookup by city name, airport name or code."""

from __future__ import annotations

import pytest


def lookup(client, q):
    r = client.get("/api/airports", params={"q": q})
    assert r.status_code == 200, r.text
    return r.json()["airports"]


@pytest.mark.parametrize(
    "q, code, city",
    [
        ("delhi", "DEL", "New Delhi"),
        ("DEL", "DEL", "New Delhi"),
        ("del", "DEL", "New Delhi"),
        ("leh", "IXL", "Leh"),
        ("mumbai", "BOM", "Mumbai"),
        ("bali", "DPS", "Denpasar"),
        ("Bali, Indonesia", "DPS", "Denpasar"),
    ],
)
def test_C10_city_names_and_codes_find_the_right_airport_first(api_client, q, code, city):
    first = lookup(api_client, q)[0]

    assert first["code"] == code
    assert first["city"] == city
    assert first["name"]


def test_C10_paris_lists_both_main_airports(api_client):
    airports = lookup(api_client, "paris")

    assert {a["code"] for a in airports[:2]} == {"CDG", "ORY"}
    assert all(a["city"] == "Paris" for a in airports[:2])
    names = {a["code"]: a["name"] for a in airports}
    assert "Charles de Gaulle" in names["CDG"]
    assert "Orly" in names["ORY"]


def test_C10_airport_names_match(api_client):
    assert lookup(api_client, "heathrow")[0]["code"] == "LHR"
    assert lookup(api_client, "kushok bakula")[0]["code"] == "IXL"


@pytest.mark.parametrize("q, codes", [("goa", {"GOI", "GOX"}), ("kerala", {"COK"}), ("ladakh", {"IXL"}), ("maldives", {"MLE"})])
def test_C10_places_without_their_own_airport_get_the_nearest_one(api_client, q, codes):
    assert lookup(api_client, q)[0]["code"] in codes


def test_C10_short_queries_return_nothing_and_results_are_capped(api_client):
    assert lookup(api_client, "") == []
    assert lookup(api_client, "d") == []
    assert len(lookup(api_client, "international")) <= 8
