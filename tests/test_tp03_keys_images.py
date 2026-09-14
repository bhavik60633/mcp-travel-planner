"""TP-03 D1 and D3: which keys are set, and photos through the backend (Unsplash simulated)."""

from __future__ import annotations

import httpx
import pytest
from fastapi.testclient import TestClient

from helpers import FakeClock

UNSPLASH_KEY = "unsplash-test-key-0a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d"
UNSPLASH_ANSWER = {
    "total": 939,
    "results": [
        {
            "urls": {"regular": "https://images.unsplash.com/photo-amber?w=1080", "small": "https://images.unsplash.com/photo-amber?w=400"},
            "alt_description": "Amber Fort at sunrise",
            "user": {"name": "Asha Rao", "links": {"html": "https://unsplash.com/@asharao"}},
            "links": {"html": "https://unsplash.com/photos/amber-fort"},
        }
    ],
}


def _provide(value):
    # A plain closure: FastAPI reads default arguments of overrides as request parameters.
    return lambda: value


@pytest.fixture
def app_with():
    """A TestClient with some backend services replaced."""
    import main

    clients = []

    def _make(overrides: dict):
        for dependency, value in overrides.items():
            main.app.dependency_overrides[dependency] = _provide(value)
        client = TestClient(main.app)
        client.__enter__()
        clients.append(client)
        return client

    yield _make
    for client in clients:
        client.__exit__(None, None, None)
    main.app.dependency_overrides.clear()


# --------------------------------------------------------------------------- D1


def test_D1_health_lists_each_feature_and_whether_its_key_is_set(api_client, monkeypatch):
    openai_key = "openai-test-value-for-health-check-0000"
    monkeypatch.setenv("OPENAI_API_KEY", openai_key)
    monkeypatch.delenv("AVIASALES_API_TOKEN", raising=False)
    monkeypatch.setenv("UNSPLASH_ACCESS_KEY", UNSPLASH_KEY)

    r = api_client.get("/api/health")

    assert r.status_code == 200
    assert r.json()["features"] == [
        {"feature": "ai_itineraries", "label": "AI itineraries", "key": "OPENAI_API_KEY", "set": True},
        {"feature": "nearby_day_prices", "label": "Prices for nearby days", "key": "AVIASALES_API_TOKEN", "set": False},
        {"feature": "photos", "label": "Destination photos", "key": "UNSPLASH_ACCESS_KEY", "set": True},
    ]
    assert openai_key not in r.text and UNSPLASH_KEY not in r.text


# --------------------------------------------------------------------------- D3


def image_service(handler, key=UNSPLASH_KEY, clock=None):
    from photos.service import ImageService

    return ImageService(access_key=key, http_client=httpx.Client(transport=httpx.MockTransport(handler)), clock=clock or FakeClock())


def test_D3_photos_come_through_the_backend_and_are_cached_for_24_hours(app_with, caplog):
    from photos.api import get_image_service

    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(200, json=UNSPLASH_ANSWER, headers={"X-Ratelimit-Limit": "50", "X-Ratelimit-Remaining": "48"})

    clock = FakeClock()
    client = app_with({get_image_service: image_service(handler, clock=clock)})

    first = client.get("/api/images", params={"query": "Amber Fort"})

    assert first.status_code == 200, first.text
    assert first.json() == {
        "query": "Amber Fort",
        "cached": False,
        "reason": None,
        "image": {
            "url": "https://images.unsplash.com/photo-amber?w=1080",
            "small_url": "https://images.unsplash.com/photo-amber?w=400",
            "alt": "Amber Fort at sunrise",
            "photographer": "Asha Rao",
            "photographer_url": "https://unsplash.com/@asharao",
            "unsplash_url": "https://unsplash.com/photos/amber-fort",
        },
    }
    request = calls[0]
    assert request.url.host == "api.unsplash.com" and request.url.path == "/search/photos"
    assert request.url.params["query"] == "Amber Fort travel"
    assert request.headers["Authorization"] == f"Client-ID {UNSPLASH_KEY}"
    assert UNSPLASH_KEY not in str(request.url)
    assert UNSPLASH_KEY not in first.text and UNSPLASH_KEY not in caplog.text

    clock.advance(23 * 3600)
    again = client.get("/api/images", params={"query": "amber fort"})
    assert again.json()["cached"] is True
    assert again.json()["image"]["url"] == "https://images.unsplash.com/photo-amber?w=1080"
    assert len(calls) == 1

    clock.advance(2 * 3600)  # 25 hours after the first search
    later = client.get("/api/images", params={"query": "Amber Fort"})
    assert later.json()["cached"] is False
    assert len(calls) == 2


@pytest.mark.parametrize("status", [403, 429])
def test_D3_at_the_hourly_limit_the_answer_is_no_photo(app_with, status):
    from photos.api import get_image_service

    client = app_with({get_image_service: image_service(lambda request: httpx.Response(status, text="Rate Limit Exceeded"))})

    r = client.get("/api/images", params={"query": "Amber Fort"})

    assert r.status_code == 200
    assert r.json() == {"query": "Amber Fort", "cached": False, "reason": "rate_limited", "image": None}


def test_D3_no_results_or_no_key_means_no_photo(app_with):
    from photos.api import get_image_service

    calls = []

    def empty(request):
        calls.append(request)
        return httpx.Response(200, json={"total": 0, "results": []})

    client = app_with({get_image_service: image_service(empty)})
    assert client.get("/api/images", params={"query": "Nowhere Village"}).json()["reason"] == "not_found"

    client = app_with({get_image_service: image_service(empty, key=None)})
    r = client.get("/api/images", params={"query": "Amber Fort"})
    assert r.json() == {"query": "Amber Fort", "cached": False, "reason": "not_configured", "image": None}
    assert len(calls) == 1  # nothing was sent without a key


def test_D3_a_query_is_required(app_with):
    from photos.api import get_image_service

    client = app_with({get_image_service: image_service(lambda request: httpx.Response(200, json=UNSPLASH_ANSWER))})

    r = client.get("/api/images", params={"query": "  "})

    assert r.status_code == 400
    assert r.json() == {"error": "invalid_request", "message": "A photo search needs some words, like a place name."}
