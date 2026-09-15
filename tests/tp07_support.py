"""Shared TP-07 setup: simulated Google Maps for Goa and Jaipur, and a client whose plans use them (Google, SerpApi and the AI simulated)."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from conftest import GOOGLE_TEST_KEY
from helpers import TODAY, FakeClock, FakeMaps, ScriptedAgent, weekly_hours

SERPAPI_TEST_KEY = "serpapi-test-key-for-yori-tp07-0000"
HALF_LAT_50_KM = 50 / 111.32

ANJUNA_VILLA = {"name": "Anjuna Villa", "address": "Anjuna, Goa", "lat": 15.585, "lng": 73.743, "source": "google"}
JAIPUR_HAVELI = {"name": "Jaipur Haveli", "address": "C Scheme, Jaipur", "lat": 26.918, "lng": 75.812, "source": "google"}

GOA_TRIP = {
    "destination": "Goa",
    "num_days": 3,
    "budget": 60000,
    "currency": "INR",
    "num_travelers": 2,
    "trip_type": "Standard",
    "group_type": "Couple",
    "preferences": "Beaches, forts and seafood.",
    "start_date": "2026-10-19",
    "return_date": "2026-10-21",
    "stay": ANJUNA_VILLA,
}
JAIPUR_TRIP = {
    "destination": "Jaipur",
    "num_days": 4,
    "budget": 60000,
    "currency": "INR",
    "num_travelers": 2,
    "trip_type": "Standard",
    "group_type": "Couple",
    "preferences": "Forts, palaces and food.",
    "start_date": "2026-10-19",
    "return_date": "2026-10-22",
    "stay": JAIPUR_HAVELI,
}


def goa_maps(**options) -> FakeMaps:
    places = {
        "Cafe Coffee Day (Bengaluru)": {"display": "Cafe Coffee Day", "matches": ["Cafe Coffee Day"], "lat": 12.9716, "lng": 77.5946, "town": "Bengaluru", "types": ["cafe"], "hours": weekly_hours("08:00", "23:00")},
        "Cafe Coffee Day (Panaji)": {"display": "Cafe Coffee Day", "matches": ["Cafe Coffee Day"], "lat": 15.4989, "lng": 73.8278, "town": "Panaji", "types": ["cafe"], "hours": weekly_hours("08:00", "23:00")},
        "Cafe Coffee Day (Candolim)": {"display": "Cafe Coffee Day", "matches": ["Cafe Coffee Day"], "lat": 15.5170, "lng": 73.7629, "town": "Candolim", "types": ["cafe"], "hours": weekly_hours("08:00", "23:00")},
        "Anjuna Beach": {"lat": 15.5733, "lng": 73.7407, "town": "Anjuna", "types": ["natural_feature"]},
        "Curlies": {"lat": 15.5746, "lng": 73.7392, "town": "Anjuna", "types": ["restaurant"], "hours": weekly_hours("09:00", "23:30")},
        "Chapora Fort": {"lat": 15.6053, "lng": 73.7363, "town": "Vagator", "types": ["tourist_attraction"], "hours": weekly_hours("09:00", "18:00")},
        "Vagator Beach": {"lat": 15.6022, "lng": 73.7337, "town": "Vagator", "types": ["natural_feature"]},
        "Thalassa": {"lat": 15.5935, "lng": 73.7392, "town": "Vagator", "types": ["restaurant"], "hours": weekly_hours("12:00", "23:30")},
        "Fort Aguada": {"lat": 15.4926, "lng": 73.7736, "town": "Candolim", "types": ["tourist_attraction"], "reviews": 45000, "hours": weekly_hours("09:30", "18:00")},
        "Pranjal Guest House": {"matches": ["Pranjal Beach"], "lat": 14.5479, "lng": 74.3188, "town": "Gokarna", "types": ["lodging"]},
    }
    areas = {
        "Goa": {"lat": 15.30, "lng": 74.08, "low": (14.75, 73.68), "high": (15.80, 74.34), "town": "Goa"},
        "Anjuna, North Goa, Goa": {"lat": 15.5827, "lng": 73.7449, "low": (15.56, 73.72), "high": (15.60, 73.76), "town": "Anjuna"},
        "Gokarna, Goa": {"lat": 14.5479, "lng": 74.3188, "low": (14.52, 74.29), "high": (14.57, 74.34), "town": "Gokarna"},
    }
    points = {"Anjuna Villa": ANJUNA_VILLA, **options.pop("points", {})}
    return FakeMaps(places, areas=areas, points=points, **options)


def jaipur_maps(**options) -> FakeMaps:
    places = {
        "Hawa Mahal": {"lat": 26.9239, "lng": 75.8267, "town": "Jaipur", "reviews": 190000, "hours": weekly_hours("09:00", "16:30")},
        "City Palace": {"lat": 26.9258, "lng": 75.8237, "town": "Jaipur", "reviews": 80000, "hours": weekly_hours("09:30", "17:00")},
        "Albert Hall Museum": {"lat": 26.9116, "lng": 75.8195, "town": "Jaipur", "hours": weekly_hours("10:00", "17:00")},
        "Jantar Mantar": {"lat": 26.9248, "lng": 75.8246, "town": "Jaipur", "hours": weekly_hours("09:00", "16:30")},
        "Taj Mahal": {"lat": 27.1751, "lng": 78.0421, "town": "Agra", "reviews": 250000, "hours": weekly_hours("06:00", "18:30")},
        "Agra Fort": {"lat": 27.1795, "lng": 78.0211, "town": "Agra", "hours": weekly_hours("06:00", "18:00")},
        "Mehtab Bagh": {"lat": 27.1797, "lng": 78.0470, "town": "Agra", "hours": weekly_hours("06:00", "18:00")},
        "Sadar Bazar (Jaipur)": {"display": "Sadar Bazar", "matches": ["Sadar Bazar"], "lat": 26.9190, "lng": 75.7980, "town": "Jaipur", "types": ["market"]},
        "Sadar Bazar (Agra)": {"display": "Sadar Bazar", "matches": ["Sadar Bazar"], "lat": 27.1630, "lng": 78.0130, "town": "Agra", "types": ["market"]},
        "Chand Baori": {"lat": 27.0074, "lng": 76.6069, "town": "Abhaneri"},
    }
    areas = {
        "Jaipur": {"lat": 26.9124, "lng": 75.7873, "low": (26.77, 75.64), "high": (27.05, 75.95), "town": "Jaipur"},
        "Agra": {"lat": 27.1767, "lng": 78.0081, "low": (27.10, 77.90), "high": (27.26, 78.10), "town": "Agra"},
    }
    drive = {
        ("Jaipur Haveli", "Taj Mahal"): 270, ("Jaipur Haveli", "Agra Fort"): 265, ("Jaipur Haveli", "Mehtab Bagh"): 275,
        ("Jaipur Haveli", "Agra"): 270, ("Jaipur Haveli", "Sadar Bazar (Agra)"): 268, ("Jaipur Haveli", "Chand Baori"): 85,
        ("Agra", "Albert Hall Museum"): 270, ("Agra", "Hawa Mahal"): 270, ("Agra", "Jantar Mantar"): 270, ("Agra", "City Palace"): 270,
        ("Agra", "Taj Mahal"): 12, ("Agra", "Agra Fort"): 8, ("Agra", "Mehtab Bagh"): 15, ("Agra", "Sadar Bazar (Agra)"): 10,
        ("Taj Mahal", "Agra Fort"): 12, ("Agra Fort", "Mehtab Bagh"): 15, ("Taj Mahal", "Mehtab Bagh"): 10,
    }
    drive.update(options.pop("drive", {}))
    return FakeMaps(places, areas=areas, points={"Jaipur Haveli": JAIPUR_HAVELI}, drive=drive, **options)


class NoStays:
    def search(self, arguments):
        from stays.airbnb import StaysUnavailable

        raise StaysUnavailable("failed")


@pytest.fixture
def timings_client():
    """A TestClient whose plans check places, build timetables and look up busy hours against simulated services."""
    import main
    from places.google import GooglePlaces
    from places.routes import GoogleRoutes
    from places.service import PlaceChecker, get_place_checker
    from plans.busy import BusyHours
    from stays.api import get_stays_service
    from stays.service import StaysService

    clients = []

    def _make(maps, airbnb=None, serpapi=None, ferries=None, deadline_s=10.0, travel_deadline_s=10.0, key=GOOGLE_TEST_KEY):
        def http(handler):
            return httpx.Client(transport=httpx.MockTransport(handler))

        busy = BusyHours(api_key=SERPAPI_TEST_KEY, http_client=http(serpapi), clock=FakeClock()) if serpapi is not None else None
        checker = PlaceChecker(
            google=GooglePlaces(api_key=key, http_client=http(maps)) if key else None,
            routes=GoogleRoutes(api_key=key, http_client=http(maps)) if key else None,
            busy=busy,
            ferries=ferries,
            deadline_s=deadline_s,
            travel_deadline_s=travel_deadline_s,
            today=lambda: TODAY,
        )
        stays = StaysService(source=airbnb or NoStays(), clock=FakeClock(), today=lambda: TODAY)
        main.app.dependency_overrides[get_place_checker] = lambda: checker
        main.app.dependency_overrides[get_stays_service] = lambda: stays
        client = TestClient(main.app)
        client.__enter__()
        client.checker = checker
        client.maps = maps
        clients.append(client)
        return client

    yield _make
    for client in clients:
        client.__exit__(None, None, None)
    main.app.dependency_overrides.clear()


def plan_day(client, monkeypatch, itinerary, trip=None, replacement=None, agent=None, status=200):
    """Plans a trip whose AI answer is `itinerary`. `agent` answers any later AI questions (such as rewriting a day)."""
    import main

    monkeypatch.setattr(main, "run_travel_planner", lambda data: itinerary)
    monkeypatch.setattr(main, "suggest_replacement", replacement or (lambda name, reason: None))
    monkeypatch.setattr(main, "agent", agent or ScriptedAgent(""))
    r = client.post("/plan-trip", json=trip or GOA_TRIP)
    assert r.status_code == status, r.text
    return r.json()


def centre_and_half_height(rect):
    (low_lat, low_lng), (high_lat, high_lng) = rect
    return ((low_lat + high_lat) / 2, (low_lng + high_lng) / 2), (high_lat - low_lat) / 2


def day_rows(body, day, kind=None):
    rows = next(entry for entry in body["timetable"] if entry["day"] == day)["rows"]
    return [row for row in rows if kind is None or row["kind"] == kind]
