"""Shared pytest setup for TP-01.

Normal runs never leave this PC: flight sources, the AI model and the clock are
simulated. Tests marked ``live`` make real calls and run only with ``--live``.
"""

from __future__ import annotations

import pytest

from helpers import TODAY, FakeClock


def pytest_addoption(parser):
    parser.addoption(
        "--live",
        action="store_true",
        default=False,
        help="run LIVE tests that call Google, Travelpayouts or OpenAI for real",
    )


def pytest_collection_modifyitems(config, items):
    if config.getoption("--live"):
        return
    skip_live = pytest.mark.skip(reason="LIVE test: run with `pytest --live -m live`")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip_live)


@pytest.fixture
def make_client():
    """Build a TestClient whose flights API uses the given simulated sources."""
    from fastapi.testclient import TestClient

    import main
    from flights.api import get_flight_service
    from flights.service import FlightService

    opened = []

    def _make(sources=(), date_sources=(), deadline_s=20.0, clock=None, today=TODAY):
        service = FlightService(
            sources=list(sources),
            date_sources=list(date_sources),
            today=lambda: today,
            clock=clock or FakeClock(),
            deadline_s=deadline_s,
        )
        main.app.dependency_overrides[get_flight_service] = lambda: service
        client = TestClient(main.app)
        client.__enter__()
        client.service = service
        opened.append(client)
        return client

    yield _make

    for client in opened:
        client.__exit__(None, None, None)
    import main as _main

    _main.app.dependency_overrides.clear()


@pytest.fixture
def api_client():
    """A TestClient for endpoints that need no flight sources (airports, plan-trip)."""
    from fastapi.testclient import TestClient

    import main

    with TestClient(main.app) as client:
        yield client


@pytest.fixture(autouse=True)
def offline_trip_info_and_place_checks(request):
    """Normal runs never call Google or the free trip-information services (TP-04). Tests set their own."""
    if "live" in request.keywords:
        yield
        return
    try:
        import httpx

        import main
        from places.service import PlaceChecker, get_place_checker
        from tripinfo.api import get_trip_info_service
        from tripinfo.service import TripInfoService
    except ImportError:  # before TP-04 is built
        yield
        return

    offline = httpx.Client(transport=httpx.MockTransport(lambda req: httpx.Response(503, json={"error": "offline test"})))
    trip_info = TripInfoService(http_client=offline, deadline_s=1.0)
    checker = PlaceChecker(google=None)
    main.app.dependency_overrides.setdefault(get_trip_info_service, lambda: trip_info)
    main.app.dependency_overrides.setdefault(get_place_checker, lambda: checker)
    yield
    main.app.dependency_overrides.pop(get_trip_info_service, None)
    main.app.dependency_overrides.pop(get_place_checker, None)


GOOGLE_TEST_KEY = "google-test-key-for-yori-tp05-0000"


@pytest.fixture
def review_client():
    """A TestClient whose plan-trip checks places, opening hours and travel times against simulated Google (TP-05)."""
    import httpx
    from fastapi.testclient import TestClient

    import main
    from places.google import GooglePlaces
    from places.routes import GoogleRoutes
    from places.service import PlaceChecker, get_place_checker
    from stays.airbnb import StaysUnavailable
    from stays.api import get_stays_service
    from stays.service import StaysService

    class NoStays:
        def search(self, arguments):
            raise StaysUnavailable("failed")

    clients = []

    def _make(google, routes=None, key=GOOGLE_TEST_KEY, deadline_s=10.0):
        def http(handler):
            return httpx.Client(transport=httpx.MockTransport(handler))

        checker = PlaceChecker(
            google=GooglePlaces(api_key=key, http_client=http(google)) if key else None,
            routes=GoogleRoutes(api_key=key, http_client=http(routes)) if key and routes is not None else None,
            deadline_s=deadline_s,
            today=lambda: TODAY,
        )
        stays = StaysService(source=NoStays(), clock=FakeClock(), today=lambda: TODAY)
        main.app.dependency_overrides[get_place_checker] = lambda: checker
        main.app.dependency_overrides[get_stays_service] = lambda: stays
        client = TestClient(main.app)
        client.__enter__()
        client.checker = checker
        clients.append(client)
        return client

    yield _make
    for client in clients:
        client.__exit__(None, None, None)
    main.app.dependency_overrides.clear()
