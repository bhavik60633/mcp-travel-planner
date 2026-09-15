"""TP-07 A7, A8: finding your stay from a name or a link, and the base area Yori picks (Google, links, Airbnb and the AI simulated)."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from conftest import GOOGLE_TEST_KEY
from helpers import FakeMaps, ScriptedAgent
from tp07_support import GOA_TRIP, centre_and_half_height, goa_maps, timings_client  # noqa: F401

TAJ_LINK = "https://www.google.com/maps/place/Taj+Fort+Aguada+Resort+%26+Spa/@15.4948,73.7719,17z/data=!3m1!4b1"
COULDNT_READ = "Couldn't read this link. Type the hotel's name instead."
HOTELS = {
    "Taj Fort Aguada Resort": {"matches": ["Taj Fort Aguada Resort & Spa"], "lat": 15.4948, "lng": 73.7719, "town": "Candolim", "types": ["lodging"]},
    "The Leela Goa": {"lat": 15.1640, "lng": 73.9467, "town": "Mobor", "types": ["lodging"]},
    "Casa Vagator": {"lat": 15.6000, "lng": 73.7350, "town": "Vagator", "types": ["lodging"]},
}
PUBLIC = {"maps.app.goo.gl": "142.250.1.1", "www.google.com": "142.250.1.2", "www.casavagator.example": "93.184.216.34", "www.nothing-here.example": "93.184.216.35", "internal.example": "10.0.0.5"}


def hotel_maps() -> FakeMaps:
    base = goa_maps()
    return FakeMaps({**base.places, **HOTELS}, areas=base.areas)


def resolve(host: str) -> list[str]:
    if host in PUBLIC:
        return [PUBLIC[host]]
    raise OSError(f"unknown host {host}")


class LinkWeb:
    """Stands in for the web pages hotel links point to."""

    def __init__(self):
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        host, path = request.url.host, request.url.path
        if host == "maps.app.goo.gl" and path == "/tajgoa":
            return httpx.Response(302, headers={"Location": TAJ_LINK})
        if host == "www.casavagator.example":
            return httpx.Response(200, headers={"content-type": "text/html"}, text="<html><head><title>Casa Vagator | Boutique hotel in Goa</title></head><body></body></html>")
        if host == "www.nothing-here.example":
            return httpx.Response(200, headers={"content-type": "text/html"}, text="<html><body>Welcome</body></html>")
        return httpx.Response(404)


class FakeAirbnbDetails:
    def __init__(self):
        self.calls = []

    def listing_details(self, arguments):
        self.calls.append(arguments)
        return {"details": [{"id": "LOCATION_DEFAULT", "lat": 15.5801, "lng": 73.7462, "subtitle": "Anjuna, Goa, India", "title": "Where you'll be"}]}


@pytest.fixture
def finder_client():
    import main
    from places.google import GooglePlaces
    from places.stayfind import StayFinder, get_stay_finder

    clients = []

    def _make(maps=None, web=None, airbnb=None):
        maps = maps or hotel_maps()
        web = web or LinkWeb()
        airbnb = airbnb or FakeAirbnbDetails()
        finder = StayFinder(
            google=GooglePlaces(api_key=GOOGLE_TEST_KEY, http_client=httpx.Client(transport=httpx.MockTransport(maps))),
            http_client=httpx.Client(transport=httpx.MockTransport(web)),
            airbnb=airbnb,
            resolve=resolve,
        )
        main.app.dependency_overrides[get_stay_finder] = lambda: finder
        client = TestClient(main.app)
        client.__enter__()
        client.maps, client.web, client.airbnb = maps, web, airbnb
        clients.append(client)
        return client

    yield _make
    for client in clients:
        client.__exit__(None, None, None)
    main.app.dependency_overrides.clear()


def find(client, text, destination="Goa"):
    r = client.get("/api/stay/find", params={"q": text, "destination": destination})
    assert r.status_code == 200, r.text
    return r.json()


# --------------------------------------------------------------------------- A7


def test_A7_a_hotel_name_gives_the_best_google_maps_match_inside_the_destinations_area(finder_client):
    client = finder_client()

    body = find(client, "Taj Fort Aguada Resort")

    assert body == {"stays": [{"name": "Taj Fort Aguada Resort", "address": "Taj Fort Aguada Resort, Candolim", "lat": 15.4948, "lng": 73.7719, "source": "google"}], "message": None}
    search = next(s for s in client.maps.place_searches() if s["query"].startswith("Taj Fort Aguada Resort"))
    assert search["restriction"] == ((14.75, 73.68), (15.80, 74.34))


def test_A7_a_hotel_that_isnt_found_near_the_destination_says_so(finder_client):
    body = find(finder_client(), "Hotel That Does Not Exist")

    assert body == {"stays": [], "message": "Couldn't find that hotel near Goa. Check the name, or paste its link."}


def test_A7_a_google_maps_link_gives_that_place(finder_client):
    client = finder_client()

    body = find(client, TAJ_LINK)

    assert [(stay["name"], stay["source"]) for stay in body["stays"]] == [("Taj Fort Aguada Resort", "google")]
    search = next(s for s in client.maps.place_searches() if s["query"].startswith("Taj Fort Aguada Resort & Spa"))
    centre, half_height = centre_and_half_height(search["restriction"])
    assert centre == pytest.approx((15.4948, 73.7719), abs=0.01)
    assert half_height < 0.05


def test_A7_a_short_google_maps_link_is_followed_to_its_place(finder_client):
    client = finder_client()

    body = find(client, "https://maps.app.goo.gl/tajgoa")

    assert [stay["name"] for stay in body["stays"]] == ["Taj Fort Aguada Resort"]
    assert [request.url.host for request in client.web.requests] == ["maps.app.goo.gl"]


def test_A7_an_airbnb_listing_link_gives_the_listings_map_position_from_airbnb(finder_client):
    client = finder_client()

    body = find(client, "https://www.airbnb.co.in/rooms/12345678?check_in=2026-10-19&adults=2")

    assert client.airbnb.calls == [{"id": "12345678"}]
    assert body == {"stays": [{"name": "Airbnb in Anjuna, Goa, India", "address": "Anjuna, Goa, India", "lat": 15.5801, "lng": 73.7462, "source": "airbnb"}], "message": None}


@pytest.mark.parametrize(
    "link",
    [
        "https://www.booking.com/hotel/in/the-leela-goa.en-gb.html",
        "https://www.agoda.com/the-leela-goa/hotel/goa-in.html",
        "https://www.makemytrip.com/hotels/the_leela_goa-details-goa.html",
    ],
)
def test_A7_a_booking_agoda_or_makemytrip_link_gives_the_hotels_name_then_google_maps(finder_client, link):
    client = finder_client()

    body = find(client, link)

    assert [(stay["name"], stay["source"]) for stay in body["stays"]] == [("The Leela Goa", "link")]
    assert client.web.requests == []  # the name comes from the link itself
    assert any(search["query"].lower().startswith("the leela goa") for search in client.maps.place_searches())


def test_A7_a_hotel_website_link_gives_the_name_from_its_page(finder_client):
    client = finder_client()

    body = find(client, "https://www.casavagator.example/")

    assert [(stay["name"], stay["source"]) for stay in body["stays"]] == [("Casa Vagator", "link")]
    assert [request.url.host for request in client.web.requests] == ["www.casavagator.example"]


def test_A7_a_link_yori_cant_read_says_so(finder_client):
    body = find(finder_client(), "https://www.nothing-here.example/")

    assert body == {"stays": [], "message": COULDNT_READ}


@pytest.mark.parametrize("link", ["http://127.0.0.1:8000/admin", "http://192.168.1.10/hotel", "https://internal.example/", "file:///etc/passwd"])
def test_A7_links_to_private_addresses_are_never_opened(finder_client, link):
    client = finder_client()

    body = find(client, link)

    assert body == {"stays": [], "message": COULDNT_READ}
    assert client.web.requests == []


# --------------------------------------------------------------------------- A8

BASE_REQUEST = {"destination": "Goa", "start_date": "2026-10-19", "return_date": "2026-10-21", "num_travelers": 2, "trip_type": "Standard", "preferences": "Beaches and seafood."}
FALLBACK = {"name": "Goa", "address": None, "lat": 15.30, "lng": 74.08, "source": "area"}
FALLBACK_MESSAGE = "Yori couldn't pick a base area inside Goa, so plans start from its centre for now."


class BrokenAgent:
    def __init__(self):
        self.prompts = []

    def run(self, prompt):
        self.prompts.append(prompt)
        raise RuntimeError("model unavailable")


def test_A8_yori_picks_a_base_area_inside_the_destination_and_checks_it_on_google_maps(timings_client, monkeypatch):
    import main

    agent = ScriptedAgent("Anjuna, North Goa")
    monkeypatch.setattr(main, "agent", agent)
    client = timings_client(goa_maps())

    r = client.post("/api/plan-base", json=BASE_REQUEST)

    assert r.status_code == 200, r.text
    assert r.json() == {"base": {"name": "Anjuna, North Goa", "address": None, "lat": 15.5827, "lng": 73.7449, "source": "area"}, "message": None}
    assert "base area" in agent.prompts[0]
    assert "Goa" in agent.prompts[0]
    assert "Reply with only" in agent.prompts[0]


def test_A8_a_base_outside_the_destination_falls_back_to_its_centre_and_says_so(timings_client, monkeypatch):
    import main

    monkeypatch.setattr(main, "agent", ScriptedAgent("Gokarna"))
    client = timings_client(goa_maps())

    r = client.post("/api/plan-base", json=BASE_REQUEST)

    assert r.json() == {"base": FALLBACK, "message": FALLBACK_MESSAGE}


def test_A8_when_the_ai_fails_the_base_is_the_destinations_centre(timings_client, monkeypatch):
    import main

    monkeypatch.setattr(main, "agent", BrokenAgent())
    client = timings_client(goa_maps())

    r = client.post("/api/plan-base", json=BASE_REQUEST)

    assert r.json() == {"base": FALLBACK, "message": FALLBACK_MESSAGE}
