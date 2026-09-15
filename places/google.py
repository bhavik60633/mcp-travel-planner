"""Google Places API (New), for checking the places an itinerary names (TP-04 B1, B4; TP-05 A2; TP-07 N1).

Only place IDs may be kept between requests (Google's caching terms), so names, addresses, ratings and opening
hours are always fetched fresh: a text search the first time a place is met, then place details by its ID.
TP-07: searches can be limited to a map rectangle, and regions are looked up with their map area.
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
    # TP-07: the kind of place (meal or sight) and its town
    "types", "addressComponents",
)
AREA_FIELDS = ("id", "displayName", "formattedAddress", "location", "viewport", "utcOffsetMinutes", "addressComponents", "types")
# A search for "Bali" can put a temple first (Tanah Lot, live on 15 Sep 2026); a region or town is preferred.
REGION_TYPES = {
    "country", "administrative_area_level_1", "administrative_area_level_2", "administrative_area_level_3", "administrative_area_level_4",
    "locality", "sublocality", "sublocality_level_1", "neighborhood", "colloquial_area", "postal_town", "archipelago", "island",
}
TOWN_TYPES = ("locality", "postal_town", "administrative_area_level_3", "administrative_area_level_2", "sublocality", "administrative_area_level_1")


class GoogleUnavailable(Exception):
    """Google didn't answer usefully. The message never contains the key."""


def _town(place: dict) -> Optional[str]:
    components = place.get("addressComponents") or []
    for kind in TOWN_TYPES:
        for component in components:
            if kind in (component.get("types") or []):
                return component.get("longText") or component.get("shortText")
    return None


def normalize(place: dict) -> dict:
    location = place.get("location") or {}
    viewport = place.get("viewport")
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
        "types": place.get("types") or [],
        "town": _town(place),
        "viewport": viewport if viewport and viewport.get("low") and viewport.get("high") else None,
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

    def search(self, text: str, restriction: Optional[dict] = None) -> Optional[dict]:
        """Google's best match for `text` (inside `restriction` when given), or None when it finds nothing."""
        places = self.search_all(text, restriction=restriction, page_size=1)
        return places[0] if places else None

    def search_all(self, text: str, restriction: Optional[dict] = None, page_size: int = 5) -> list[dict]:
        """Google's matches for `text`, best first, only inside the map rectangle `restriction` ({"low", "high"}) when given."""
        body: dict = {"textQuery": text, "languageCode": "en", "pageSize": page_size}
        if restriction:
            body["locationRestriction"] = {"rectangle": restriction}
        response = self._send("POST", SEARCH_URL, ",".join(f"places.{field}" for field in FIELDS), json=body)
        if response.status_code != 200:
            raise GoogleUnavailable(f"HTTP {response.status_code}")
        return [normalize(place) for place in response.json().get("places") or []]

    def area(self, text: str) -> Optional[dict]:
        """A region or town with its map area: {"name", "lat", "lng", "viewport", "offset", "town"}, or None."""
        response = self._send("POST", SEARCH_URL, ",".join(f"places.{field}" for field in AREA_FIELDS), json={"textQuery": text, "languageCode": "en", "pageSize": 5})
        if response.status_code != 200:
            raise GoogleUnavailable(f"HTTP {response.status_code}")
        located = [place for place in (normalize(raw) for raw in response.json().get("places") or []) if place["location"]]
        if not located:
            return None
        place = next((candidate for candidate in located if REGION_TYPES & set(candidate["types"])), located[0])
        return {
            "name": place["name"] or text,
            "lat": place["location"]["lat"],
            "lng": place["location"]["lng"],
            "viewport": place["viewport"],
            "offset": place["utc_offset_minutes"],
            "town": place["town"],
        }

    def details(self, place_id: str) -> Optional[dict]:
        """The place with this ID, or None when Google no longer has it."""
        response = self._send("GET", DETAILS_URL.format(place_id=place_id), ",".join(FIELDS), params={"languageCode": "en"})
        if response.status_code == 404:
            return None
        if response.status_code != 200:
            raise GoogleUnavailable(f"HTTP {response.status_code}")
        return normalize(response.json())
