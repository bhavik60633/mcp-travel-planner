"""Google Places API (New), for checking the places an itinerary names (TP-04 B1, B4; TP-05 A2).

Only place IDs may be kept between requests (Google's caching terms), so names, addresses, ratings and opening
hours are always fetched fresh: a text search the first time a place is met, then place details by its ID.
"""

from __future__ import annotations

from typing import Optional

import httpx

SEARCH_URL = "https://places.googleapis.com/v1/places:searchText"
DETAILS_URL = "https://places.googleapis.com/v1/places/{place_id}"
FIELDS = (
    "id", "displayName", "formattedAddress", "location", "googleMapsUri", "businessStatus", "rating", "userRatingCount",
    # TP-05 A2: opening hours, and the place's time zone to read them in
    "regularOpeningHours", "currentOpeningHours", "utcOffsetMinutes",
)


class GoogleUnavailable(Exception):
    """Google didn't answer usefully. The message never contains the key."""


def normalize(place: dict) -> dict:
    location = place.get("location") or {}
    return {
        "id": place.get("id"),
        "name": (place.get("displayName") or {}).get("text"),
        "address": place.get("formattedAddress"),
        "maps_url": place.get("googleMapsUri"),
        "location": {"lat": location["latitude"], "lng": location["longitude"]} if "latitude" in location and "longitude" in location else None,
        "business_status": place.get("businessStatus"),
        "rating": place.get("rating"),
        "reviews": place.get("userRatingCount"),
        "regular_hours": place.get("regularOpeningHours"),
        "current_hours": place.get("currentOpeningHours"),
        "utc_offset_minutes": place.get("utcOffsetMinutes"),
    }


class GooglePlaces:
    def __init__(self, api_key: str, http_client: Optional[httpx.Client] = None, timeout_s: float = 8.0):
        self._key = api_key
        self._http = http_client or httpx.Client(timeout=timeout_s)

    def __repr__(self) -> str:
        return "GooglePlaces()"  # never shows the key

    def _send(self, method: str, url: str, fields: str, **kwargs) -> httpx.Response:
        try:
            return self._http.request(method, url, headers={"X-Goog-Api-Key": self._key, "X-Goog-FieldMask": fields}, **kwargs)
        except httpx.HTTPError as exc:
            raise GoogleUnavailable(type(exc).__name__) from None

    def search(self, text: str) -> Optional[dict]:
        """Google's best match for `text`, or None when it finds nothing."""
        response = self._send("POST", SEARCH_URL, ",".join(f"places.{field}" for field in FIELDS), json={"textQuery": text, "languageCode": "en", "pageSize": 1})
        if response.status_code != 200:
            raise GoogleUnavailable(f"HTTP {response.status_code}")
        places = response.json().get("places") or []
        return normalize(places[0]) if places else None

    def details(self, place_id: str) -> Optional[dict]:
        """The place with this ID, or None when Google no longer has it."""
        response = self._send("GET", DETAILS_URL.format(place_id=place_id), ",".join(FIELDS), params={"languageCode": "en"})
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise GoogleUnavailable(f"HTTP {response.status_code}")
        return normalize(response.json())
