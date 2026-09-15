"""Google Routes API: how long it takes between two places by car, public transport, on foot and by boat (TP-05 B, TP-07 B1, E1).

Car trips are asked for with live traffic at the time you'd leave (Google's Pro price, TP-07 D4). Comparing orders of
visits uses times without traffic (the Essentials price). Public transport is shown only when a ride leaves within
30 minutes, so a metro that has stopped running isn't suggested. Boats come from Google's public transport routes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Callable, Optional

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


def _utc_text(moment: datetime) -> str:
    return moment.strftime("%Y-%m-%dT%H:%M:%SZ")


def _as_utc(moment: datetime) -> datetime:
    return moment.replace(tzinfo=timezone.utc) if moment.tzinfo is None else moment.astimezone(timezone.utc)


class GoogleRoutes:
    def __init__(self, api_key: str, http_client: Optional[httpx.Client] = None, timeout_s: float = 8.0, now: Optional[Callable[[], datetime]] = None):
        self._key = api_key
        self._http = http_client or httpx.Client(timeout=timeout_s)
        self._now = now or (lambda: datetime.now(timezone.utc))

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

    def drive(self, origin: dict, destination: dict, leave_utc: Optional[datetime] = None, traffic: bool = True) -> Optional[dict]:
        """A car trip: live traffic at `leave_utc` (Google needs it in the future), or no traffic for comparing orders of visits."""
        traffic = traffic and leave_utc is not None
        body = {"origin": _waypoint(origin), "destination": _waypoint(destination), "travelMode": "DRIVE", "routingPreference": "TRAFFIC_AWARE" if traffic else "TRAFFIC_UNAWARE"}
        if traffic:
            body["departureTime"] = _utc_text(_as_utc(leave_utc))
        route = self._route(body, BASIC_FIELDS)
        if route is None:
            return None
        return {"minutes": _minutes(route.get("duration")), "km": round((route.get("distanceMeters") or 0) / 1000, 1)}

    def walk(self, origin: dict, destination: dict) -> Optional[dict]:
        route = self._route({"origin": _waypoint(origin), "destination": _waypoint(destination), "travelMode": "WALK"}, BASIC_FIELDS)
        return {"minutes": _minutes(route.get("duration"))} if route else None

    def _transit_route(self, origin: dict, destination: dict, leave_utc: datetime) -> Optional[dict]:
        body = {"origin": _waypoint(origin), "destination": _waypoint(destination), "travelMode": "TRANSIT", "departureTime": _utc_text(_as_utc(leave_utc))}
        return self._route(body, TRANSIT_FIELDS)

    def transit(self, origin: dict, destination: dict, leave_utc: datetime) -> Optional[dict]:
        route = self._transit_route(origin, destination, leave_utc)
        if route is None:
            return None
        steps = [step for leg in route.get("legs") or [] for step in leg.get("steps") or []]
        rides = [index for index, step in enumerate(steps) if step.get("transitDetails")]
        if not rides:
            return None

        first = steps[rides[0]]["transitDetails"]
        departs = (first.get("stopDetails") or {}).get("departureTime")
        if departs:
            wait = datetime.fromisoformat(departs.replace("Z", "+00:00")) - _as_utc(leave_utc)
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

    def ferry(self, origin: dict, destination: dict, leave_utc: datetime) -> Optional[dict]:
        """A boat on Google's public transport route leaving from `leave_utc`: its line, departure (UTC), crossing and whole trip (TP-07 E1)."""
        route = self._transit_route(origin, destination, leave_utc)
        if route is None:
            return None
        steps = [step for leg in route.get("legs") or [] for step in leg.get("steps") or []]
        for index, step in enumerate(steps):
            details = step.get("transitDetails") or {}
            line = details.get("transitLine") or {}
            if ((line.get("vehicle") or {}).get("type")) != "FERRY":
                continue
            stops = details.get("stopDetails") or {}
            departs = stops.get("departureTime")
            if not departs:
                return None
            after = sum(_seconds(later.get("staticDuration")) for later in steps[index + 1 :])
            return {
                "line": line.get("name") or line.get("nameShort") or "Ferry",
                "departs_utc": datetime.fromisoformat(departs.replace("Z", "+00:00")),
                "minutes": _minutes(step.get("staticDuration")),
                "after_minutes": round(after / 60),
                "from_stop": (stops.get("departureStop") or {}).get("name"),
                "to_stop": (stops.get("arrivalStop") or {}).get("name"),
                "total_minutes": _minutes(route.get("duration")),
            }
        return None
