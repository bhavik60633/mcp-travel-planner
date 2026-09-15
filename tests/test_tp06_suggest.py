"""TP-06 B1, B2: place suggestions for the To box, from Photon (its real replies from 15 Sep 2026 are replayed)."""

from __future__ import annotations

import threading
import time

import httpx
import pytest
from fastapi.testclient import TestClient

from helpers import FakeClock, FakePhoton

UNAVAILABLE = "Place suggestions aren't available right now."


@pytest.fixture
def suggest_client():
    import main
    from tripinfo.api import get_place_suggester
    from tripinfo.suggest import PlaceSuggester

    clients = []

    def _make(photon=None, clock=None, timeout_s=3.0):
        photon = photon or FakePhoton()
        suggester = PlaceSuggester(http_client=httpx.Client(transport=httpx.MockTransport(photon)), clock=clock or FakeClock(), timeout_s=timeout_s)
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


def labels(body: dict) -> list[str]:
    return [place["label"] for place in body["places"]]


# --------------------------------------------------------------------------- B1


def test_B1_bali_suggests_up_to_6_places_with_region_and_country(suggest_client):
    client = suggest_client()

    r = client.get("/api/places/suggest", params={"q": "bali"})

    assert r.status_code == 200, r.text
    body = r.json()
    assert body["available"] is True
    # Photon's suburb "Bali, Taiwan" isn't a trip destination, and the second "Bali Island" repeats a label.
    assert labels(body) == [
        "Bali, Indonesia",
        "Bali Island, Bali, Indonesia",
        "Bali, Northwest, Cameroon",
        "Balin, Łódź Voivodeship, Poland",
        "Balinghem, Hauts-de-France, France",
        "Baliracq-Maumusson, Nouvelle-Aquitaine, France",
    ]
    assert body["places"][0] == {
        "name": "Bali",
        "label": "Bali, Indonesia",
        "kind": "state",
        "region": None,
        "country": "Indonesia",
        "country_code": "ID",
        "lat": -8.2271303,
        "lng": 115.1919203,
    }


def test_B1_islands_and_towns_nearby_are_suggested(suggest_client):
    client = suggest_client()

    body = client.get("/api/places/suggest", params={"q": "nusa pe"}).json()

    assert labels(body) == [
        "Nusa Penida, Bali, Indonesia",
        "Nusa Peropa, East Nusa Tenggara, Indonesia",
        "East Nusa Tenggara, Indonesia",
        "Penida Island, Bali, Indonesia",
        "Nusa Lembongan, Bali, Indonesia",
        "Flores, East Nusa Tenggara, Indonesia",
    ]


def test_B1_airports_stations_and_buildings_are_left_out(suggest_client):
    client = suggest_client()

    body = client.get("/api/places/suggest", params={"q": "jaip"}).json()

    assert labels(body) == [
        "Jaipur, Rajasthan, India",
        "Jaipa, Madhya Pradesh, India",
        "Jaipur, West Bengal, India",
        "Jaipa, La Guajira, Colombia",
        "Jaipur Municipal Corporation, Rajasthan, India",
        "Jaipur Tehsil, Rajasthan, India",
    ]
    assert not any(word in label for label in labels(body) for word in ("Airport", "Junction", "Nagar", "Column"))


# --------------------------------------------------------------------------- B2


@pytest.mark.parametrize("query", ["", "b", "  b  "])
def test_B2_fewer_than_2_letters_returns_no_places_without_asking_photon(suggest_client, query):
    client = suggest_client()

    r = client.get("/api/places/suggest", params={"q": query})

    assert r.status_code == 200, r.text
    assert r.json()["places"] == []
    assert r.json()["available"] is True
    assert client.photon.queries == []


def test_B2_answers_are_cached_for_a_day(suggest_client):
    clock = FakeClock()
    client = suggest_client(clock=clock)

    first = client.get("/api/places/suggest", params={"q": "bali"}).json()
    clock.advance(23 * 3600)
    again = client.get("/api/places/suggest", params={"q": "Bali "}).json()

    assert (first["cached"], again["cached"]) == (False, True)
    assert labels(again) == labels(first)
    assert len(client.photon.queries) == 1

    clock.advance(2 * 3600)  # 25 hours after the first search
    assert client.get("/api/places/suggest", params={"q": "bali"}).json()["cached"] is False
    assert len(client.photon.queries) == 2


@pytest.mark.parametrize("fail", [503, "error"])
def test_B2_when_photon_fails_the_list_is_empty_and_says_so_never_an_error(suggest_client, fail):
    client = suggest_client(FakePhoton(fail=fail))

    r = client.get("/api/places/suggest", params={"q": "bali"})

    assert r.status_code == 200
    assert r.json() == {"query": "bali", "places": [], "available": False, "message": UNAVAILABLE, "cached": False}
    client.get("/api/places/suggest", params={"q": "bali"})
    assert len(client.photon.queries) == 2  # failures aren't cached


def test_B2_when_photon_takes_over_3_seconds_the_list_is_empty(suggest_client):
    from tripinfo.suggest import PlaceSuggester

    assert PlaceSuggester().timeout_s == 3.0

    release = threading.Event()
    try:
        client = suggest_client(FakePhoton(fail=release), timeout_s=0.5)
        started = time.monotonic()
        r = client.get("/api/places/suggest", params={"q": "bali"})
        elapsed = time.monotonic() - started
    finally:
        release.set()

    assert r.status_code == 200
    assert r.json()["available"] is False
    assert elapsed < 2.5
