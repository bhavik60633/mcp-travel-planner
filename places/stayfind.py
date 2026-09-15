"""Your stay from a hotel's name or a link to it (TP-07 A7).

Links are read without trusting them: only http and https, never a private or local address, and redirects are
followed one at a time with the same check. Booking.com, Agoda and MakeMyTrip links give the hotel's name from the
link itself, so their pages are never fetched.
"""

from __future__ import annotations

import html
import ipaddress
import logging
import os
import re
import socket
import threading
from typing import Callable, Optional
from urllib.parse import unquote_plus, urljoin, urlparse

import httpx

from .geo import rectangle_around, span_km
from .google import GooglePlaces, GoogleUnavailable

log = logging.getLogger(__name__)

COULDNT_READ = "Couldn't read this link. Type the hotel's name instead."
NOT_FOUND = "Couldn't find that hotel near {destination}. Check the name, or paste its link."
NO_GOOGLE = "Finding your hotel needs Google Maps, which isn't set up yet."
EMPTY = "Type your hotel's name, or paste its link."
MAX_PAGE_CHARACTERS = 500_000
MAX_REDIRECTS = 5
USER_AGENT = "TravelWithYori/0.1 (https://yoritrip.yorilabs.ai)"

_COORDS_AT = re.compile(r"@(-?\d+(?:\.\d+)?),(-?\d+(?:\.\d+)?)")
_COORDS_DATA = re.compile(r"!3d(-?\d+(?:\.\d+)?)!4d(-?\d+(?:\.\d+)?)")
_TITLE = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_OG_TITLE = re.compile(r"<meta[^>]+property=[\"']og:title[\"'][^>]*content=[\"']([^\"']+)", re.IGNORECASE)
_TITLE_SEPARATORS = re.compile(r"\s+[|–—-]\s+")


def _default_resolve(host: str) -> list[str]:
    return sorted({info[4][0] for info in socket.getaddrinfo(host, None)})


def _is_google_maps(host: str, path: str) -> bool:
    return bool(re.fullmatch(r"(www\.|maps\.)?google\.[a-z.]{2,6}", host)) and (path.startswith("/maps") or host.startswith("maps."))


def _is_short_google_link(host: str, path: str) -> bool:
    return host == "maps.app.goo.gl" or (host == "goo.gl" and path.startswith("/maps"))


def _slug_name(slug: str) -> str:
    return " ".join(part.capitalize() for part in re.split(r"[-_]+", slug) if part)


def _name_from_booking_link(host: str, path: str) -> Optional[str]:
    if host == "booking.com" or host.endswith(".booking.com"):
        match = re.match(r"^/hotel/[a-z]{2}/([a-z0-9-]+?)(?:\.[a-z]{2}(?:-[a-z]{2})?)?\.html", path, re.IGNORECASE)
    elif host == "agoda.com" or host.endswith(".agoda.com"):
        match = re.match(r"^/(?:[a-z]{2}-[a-z]{2}/)?([a-z0-9-]+)/hotel/", path, re.IGNORECASE)
    elif host == "makemytrip.com" or host.endswith(".makemytrip.com"):
        match = re.match(r"^/hotels/([a-z0-9_]+?)-details-", path, re.IGNORECASE)
    else:
        return None
    return _slug_name(match.group(1)) if match else None


def _page_title(page: str) -> Optional[str]:
    match = _OG_TITLE.search(page) or _TITLE.search(page)
    if not match:
        return None
    title = " ".join(html.unescape(match.group(1)).split())
    title = _TITLE_SEPARATORS.split(title)[0].strip()
    return title if len(title) >= 2 else None


class StayFinder:
    def __init__(self, google: Optional[GooglePlaces], http_client: Optional[httpx.Client] = None, airbnb=None, resolve: Optional[Callable[[str], list[str]]] = None, timeout_s: float = 6.0):
        self.google = google
        self._http = http_client or httpx.Client(timeout=timeout_s)
        self.airbnb = airbnb
        self._resolve = resolve or _default_resolve
        self._areas: dict[str, Optional[dict]] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ what you typed

    def find(self, text: str, destination: str) -> dict:
        text = " ".join((text or "").split())
        destination = " ".join((destination or "").split())
        if not text:
            return {"stays": [], "message": EMPTY}
        if self.google is None:
            return {"stays": [], "message": NO_GOOGLE}
        try:
            if re.match(r"^[a-z][a-z0-9+.-]*:", text, re.IGNORECASE) and not re.match(r"^[a-z]:\\", text, re.IGNORECASE):
                return self._link(text, destination)
            if text.lower().startswith("www."):
                return self._link("https://" + text, destination)
            return self._by_name(text, destination, "google")
        except GoogleUnavailable as exc:
            log.warning("Finding a stay failed (%s)", exc)
            return {"stays": [], "message": "Google Maps isn't answering right now. Try again in a minute."}

    def _area(self, destination: str) -> Optional[dict]:
        key = destination.lower()
        with self._lock:
            if key in self._areas:
                return self._areas[key]
        area = self.google.area(destination) if destination else None
        with self._lock:
            self._areas[key] = area
        return area

    @staticmethod
    def _stay(place: dict, source: str) -> dict:
        return {"name": place["name"], "address": place["address"], "lat": place["location"]["lat"], "lng": place["location"]["lng"], "source": source}

    def _by_name(self, name: str, destination: str, source: str) -> dict:
        area = self._area(destination)
        restriction = None
        if area:
            # A tiny map area means Google found a spot, not the region: search 50 km around it instead.
            restriction = area["viewport"] if area["viewport"] and span_km(area["viewport"]) >= 5 else rectangle_around(area, 50)
        query = f"{name}, {destination}" if destination else name
        places = [place for place in self.google.search_all(query, restriction=restriction, page_size=5) if place.get("location")]
        if not places:
            return {"stays": [], "message": NOT_FOUND.format(destination=destination or "your destination")}
        return {"stays": [self._stay(place, source) for place in places], "message": None}

    # ------------------------------------------------------------------ links

    def _public(self, host: str) -> bool:
        try:
            addresses = [str(ipaddress.ip_address(host))]
        except ValueError:
            try:
                addresses = self._resolve(host)
            except OSError:
                return False
        if not addresses:
            return False
        for address in addresses:
            ip = ipaddress.ip_address(address)
            if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
                return False
        return True

    def _link(self, url: str, destination: str) -> dict:
        read_fail = {"stays": [], "message": COULDNT_READ}
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme not in ("http", "https") or not host:
            return read_fail
        if _is_google_maps(host, parsed.path):
            return self._google_link(url, destination) or read_fail
        if _is_short_google_link(host, parsed.path):
            final = self._follow_to_google(url)
            return (self._google_link(final, destination) if final else None) or read_fail
        if re.search(r"(^|\.)airbnb\.[a-z.]{2,6}$", host):
            return self._airbnb(parsed.path) or read_fail
        name = _name_from_booking_link(host, parsed.path)
        if name:
            return self._by_name(name, destination, "link")
        page = self._fetch(url)
        title = _page_title(page) if page else None
        if not title:
            return read_fail
        return self._by_name(title, destination, "link")

    def _google_link(self, url: str, destination: str) -> Optional[dict]:
        parsed = urlparse(url)
        place = re.search(r"/maps/place/([^/]+)", parsed.path)
        name = unquote_plus(place.group(1)).strip() if place else ""
        coords = _COORDS_DATA.search(url) or _COORDS_AT.search(url)
        if not name:
            return None
        if coords:
            point = {"lat": float(coords.group(1)), "lng": float(coords.group(2))}
            found = [p for p in self.google.search_all(name, restriction=rectangle_around(point, 1), page_size=1) if p.get("location")]
            if found:
                return {"stays": [self._stay(found[0], "google")], "message": None}
        result = self._by_name(name, destination, "google")
        return result if result["stays"] else None

    def _follow_to_google(self, url: str) -> Optional[str]:
        for _ in range(MAX_REDIRECTS):
            parsed = urlparse(url)
            host = (parsed.hostname or "").lower()
            if _is_google_maps(host, parsed.path):
                return url
            if parsed.scheme not in ("http", "https") or not self._public(host):
                return None
            try:
                response = self._http.get(url, headers={"User-Agent": USER_AGENT}, follow_redirects=False)
            except httpx.HTTPError as exc:
                log.warning("A map link couldn't be read (%s)", type(exc).__name__)
                return None
            location = response.headers.get("location")
            if not (300 <= response.status_code < 400 and location):
                return None
            url = urljoin(url, location)
        return None

    def _airbnb(self, path: str) -> Optional[dict]:
        match = re.search(r"/rooms/(\d+)", path)
        if not match or self.airbnb is None:
            return None
        try:
            data = self.airbnb.listing_details({"id": match.group(1)})
        except Exception as exc:
            log.warning("An Airbnb link couldn't be read (%s)", type(exc).__name__)
            return None
        for section in (data or {}).get("details") or []:
            if section.get("id") == "LOCATION_DEFAULT" and isinstance(section.get("lat"), (int, float)) and isinstance(section.get("lng"), (int, float)):
                where = section.get("subtitle") or "your Airbnb"
                return {"stays": [{"name": f"Airbnb in {where}", "address": section.get("subtitle"), "lat": section["lat"], "lng": section["lng"], "source": "airbnb"}], "message": None}
        return None

    def _fetch(self, url: str) -> Optional[str]:
        for _ in range(MAX_REDIRECTS):
            parsed = urlparse(url)
            host = (parsed.hostname or "").lower()
            if parsed.scheme not in ("http", "https") or not host or not self._public(host):
                return None
            try:
                response = self._http.get(url, headers={"User-Agent": USER_AGENT, "Accept": "text/html"}, follow_redirects=False)
            except httpx.HTTPError as exc:
                log.warning("A hotel link couldn't be read (%s)", type(exc).__name__)
                return None
            location = response.headers.get("location")
            if 300 <= response.status_code < 400 and location:
                url = urljoin(url, location)
                continue
            if response.status_code != 200:
                return None
            return response.text[:MAX_PAGE_CHARACTERS]
        return None


_finder: Optional[StayFinder] = None
_finder_lock = threading.Lock()


def get_stay_finder() -> StayFinder:
    global _finder
    with _finder_lock:
        key = os.environ.get("GOOGLE_MAPS_API_KEY", "").strip()
        if _finder is None or (_finder.google is not None) != bool(key):
            from stays.airbnb import AirbnbMcpSource

            _finder = StayFinder(google=GooglePlaces(api_key=key) if key else None, airbnb=AirbnbMcpSource())
        return _finder
