"""Airport lookup by city, region, airport name or code (TP-01 C10)."""

from __future__ import annotations

from fli.models.airport import AIRPORT_NAMES

from .airport_data import CITY_OF, PLACES

MAX_RESULTS = 8

# Only codes that exist in the airport list are used.
_CITY_OF = {code: city for code, city in CITY_OF.items() if code in AIRPORT_NAMES}
_PLACES: dict[str, list[str]] = {}
for _code, _city in _CITY_OF.items():
    _PLACES.setdefault(_city.lower(), []).append(_code)
for _alias, _codes in PLACES.items():
    known = [c for c in _codes if c in AIRPORT_NAMES]
    if known:
        _PLACES[_alias.lower()] = known


def _airport(code: str) -> dict:
    return {"code": code, "name": AIRPORT_NAMES[code], "city": _CITY_OF.get(code)}


def search_airports(query: str, limit: int = MAX_RESULTS) -> list[dict]:
    """Best matches first. "Bali, Indonesia" is looked up as "Bali"."""
    text = (query or "").split(",")[0].strip()
    needle = " ".join(text.lower().split())
    if len(needle) < 2:
        return []

    scores: dict[str, float] = {}

    def add(code: str, score: float) -> None:
        if code in AIRPORT_NAMES and score > scores.get(code, -1):
            scores[code] = score

    if len(text) == 3 and text.isalpha() and text.isupper():
        add(text, 100)  # typed as a code, e.g. "DEL"
    for rank, code in enumerate(_PLACES.get(needle, [])):
        add(code, 95 - rank * 0.1)  # a city or region, e.g. "leh", "goa", "kerala"
    if len(needle) == 3 and needle.upper() in AIRPORT_NAMES:
        add(needle.upper(), 90)
    for place, codes in _PLACES.items():
        if place.startswith(needle):
            for rank, code in enumerate(codes):
                add(code, 80 - rank * 0.1)
    for code, name in AIRPORT_NAMES.items():
        position = name.lower().find(needle)
        if position >= 0:
            add(code, 70 - min(position, 50) * 0.1 + (3 if code in _CITY_OF else 0))
    if len(needle) <= 3:
        prefix = needle.upper()
        for code in AIRPORT_NAMES:
            if code.startswith(prefix):
                add(code, 60 + (3 if code in _CITY_OF else 0))

    ranked = sorted(scores.items(), key=lambda item: (-item[1], item[0] not in _CITY_OF, item[0]))
    return [_airport(code) for code, _ in ranked[:limit]]
