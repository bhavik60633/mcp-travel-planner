"""Google Routes API: how long it takes between two places by car, public transport and on foot (TP-05 B).

Car trips are asked for without live traffic (Google's Essentials price). Public transport is asked for leaving
at a given time, and is shown only when a ride leaves within 30 minutes of it, so a metro that has stopped
running isn't suggested.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import httpx

ROUTES_URL = "https://routes.googleapis.com/directions/v2:computeRoutes"
BASIC_FIELDS = "routes.duration,routes.distanceMeters"
TRANSIT_FIELDS = BASIC_FIELDS + ",routes.legs.steps.travelMode,routes.legs.steps.staticDuration,routes.legs.steps.transitDetails"
MAX_WAIT_MINUTES = 30

VEHICLES = {
    "SUBWAY": "Metro", "METRO_RAIL": "Metro", "MONORAIL": "Metro", "LIGHT_RAIL": "Metro", "TRAM": "Tram",
    "BUS": "Bus", "INTERCITY_BUS": "Bus", "TROLLEYBUS": "Bus", "SHARE_TAXI": "Shared taxi", "FERRY": "Ferry",
    "RAIL": "Train", "HEAVY_RAIL": "Train", "COMMUTER_TRAIN": "Train", "HIGH_SPEED_TRAIN": "Train", "LONG_DISTANCE_TRAIN": "Train",
}


class RoutesUnavailable(Exception):
    """Google didn't answer usefully. The message never contains the key."""


def _seconds(duration) -> float:
    try:
        return float(str(duration or "0s").rstrip("s"))
    except ValueError:
        return 0.0


def _minutes(duration) -> int:
    return max(1, round(_seconds(duration) / 60))


def _waypoint(location: dict) -> dict:
    return {"location": {"latLng": {"latitude": location["lat"], "longitude": location["lng"]}}}


class GoogleRoutes:
    def __init__(self, api_key: str, http_client: Optional[httpx.Client] = None, timeout_s: float = 8.0):
        self._key = api_key
        self._http = http_client or httpx.Client(timeout=timeout_s)

    def __repr__(self) -> str:
        return "GoogleRoutes()"  # never shows the key

    def _route(self, body: dict, fields: str) -> Optional[dict]:
        try:
            response = self._http.post(ROUTES_URL, json=body, headers={"X-Goog-Api-Key": self._key, "X-Goog-FieldMask": fields})
        except httpx.HTTPError as exc:
            raise RoutesUnavailable(type(exc).__name__) from None
        if response.status_code != 200:
            raise RoutesUnavailable(f"HTTP {response.status_code}")
        routes = response.json().get("routes") or []
        return routes[0] if routes else None

    def drive(self, origin: dict, destination: dict) -> Optional[dict]:
        body = {"origin": _waypoint(origin), "destination": _waypoint(destination), "travelMode": "DRIVE", "routingPreference": "TRAFFIC_UNAWARE"}
        route = self._route(body, BASIC_FIELDS)
        if route is None:
            return None
        return {"minutes": _minutes(route.get("duration")), "km": round((route.get("distanceMeters") or 0) / 1000, 1)}

    def walk(self, origin: dict, destination: dict) -> Optional[dict]:
        route = self._route({"origin": _waypoint(origin), "destination": _waypoint(destination), "travelMode": "WALK"}, BASIC_FIELDS)
        return {"minutes": _minutes(route.get("duration"))} if route else None

    def transit(self, origin: dict, destination: dict, leave_utc: datetime) -> Optional[dict]:
        body = {
            "origin": _waypoint(origin),
            "destination": _waypoint(destination),
            "travelMode": "TRANSIT",
            "departureTime": leave_utc.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }
        route = self._route(body, TRANSIT_FIELDS)
        if route is None:
            return None
        steps = [step for leg in route.get("legs") or [] for step in leg.get("steps") or []]
        rides = [index for index, step in enumerate(steps) if step.get("transitDetails")]
        if not rides:
            return None

        first = steps[rides[0]]["transitDetails"]
        departs = (first.get("stopDetails") or {}).get("departureTime")
        if departs:
            wait = datetime.fromisoformat(departs.replace("Z", "+00:00")) - leave_utc.replace(tzinfo=timezone.utc)
            if wait.total_seconds() / 60 > MAX_WAIT_MINUTES:
                return None

        lines: list[str] = []
        for index in rides:
            line = steps[index]["transitDetails"].get("transitLine") or {}
            name = line.get("name") or line.get("nameShort")
            if name and name not in lines:
                lines.append(name)
        vehicle = ((first.get("transitLine") or {}).get("vehicle") or {}).get("type")
        total = _minutes(route.get("duration"))
        final_walk = sum(_seconds(step.get("staticDuration")) for step in steps[rides[-1] + 1 :] if step.get("travelMode") == "WALK")
        summary = f"{VEHICLES.get(vehicle, 'Public transport')} {total} min: {' then '.join(lines) or 'public transport'}"
        if final_walk >= 60:
            summary += f", then {round(final_walk / 60)} min walk"
        return {"minutes": total, "lines": lines, "summary": summary}
