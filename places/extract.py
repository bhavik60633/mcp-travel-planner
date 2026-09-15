"""The places an itinerary names. The AI writes each specific place in bold (TP-04 B1)."""

from __future__ import annotations

import re

_BOLD = re.compile(r"\*\*([^*\n]{2,80}?)\*\*")
_TIME = re.compile(r"^\d{1,2}(?:[:.]\d{2})?\s*(?:am|pm|a\.m\.|p\.m\.)?$", re.IGNORECASE)
_MONEY = re.compile(r"[₹$€£¥]|\b(?:INR|USD|EUR|GBP)\b")
_DAY = re.compile(r"^day\s*\d+", re.IGNORECASE)
_LINKING_WORDS = {"a", "an", "the", "and", "or", "of", "at", "in", "on", "to", "for", "with"}

# Words that on their own don't name one place: "the hotel", "local market", "breakfast".
GENERIC_WORDS = {
    "a", "an", "the", "and", "or", "of", "at", "in", "on", "to", "for", "with", "your", "our", "local", "nearby", "famous",
    "morning", "afternoon", "evening", "night", "noon", "midday", "sunrise", "sunset", "early", "late", "mid",
    "breakfast", "brunch", "lunch", "dinner", "snack", "snacks", "tea", "coffee", "drinks", "food", "street", "meal",
    "hotel", "hostel", "homestay", "resort", "villa", "stay", "accommodation", "room", "check", "checkin", "checkout",
    "beach", "beaches", "market", "markets", "bazaar", "restaurant", "restaurants", "cafe", "café", "bar", "pub",
    "museum", "temple", "temples", "church", "fort", "palace", "park", "garden", "lake", "river", "viewpoint", "old", "city", "town",
    "airport", "station", "railway", "bus", "taxi", "cab", "auto", "rickshaw", "transfer", "transport", "flight", "train", "ferry",
    "day", "tip", "tips", "note", "notes", "pro", "travel", "budget", "cost", "costs", "total", "estimated", "price", "prices",
    "overview", "highlights", "highlight", "itinerary", "plan", "optional", "free", "time", "rest", "relax", "shopping",
    "sightseeing", "activities", "activity", "tour", "walk", "arrival", "departure", "return", "important", "must", "see", "try",
}


def clean(raw: str) -> str:
    """A name without surrounding punctuation. Brackets are kept when they pair up: "LMB (Laxmi Misthan Bhandar)"."""
    name = raw.strip().strip(" .,;!?-–—\"'")
    while name.endswith(")") and name.count(")") > name.count("("):
        name = name[:-1].rstrip(" .,;!?-–—\"'")
    while name.startswith("(") and name.count("(") > name.count(")"):
        name = name[1:].lstrip(" .,;!?-–—\"'")
    return name


def _is_place(raw: str) -> bool:
    if raw.strip().endswith(":"):
        return False  # a label such as **Morning:**
    name = clean(raw)
    if len(name) < 3 or not any(ch.isalpha() for ch in name):
        return False
    if _TIME.match(name) or _MONEY.search(name) or _DAY.match(name):
        return False
    words = re.findall(r"[^\W\d_]+", name)
    if not words:
        return False
    if all(word.lower() in GENERIC_WORDS for word in words):
        # "City Palace" or "Old City" still name a place; a lone common word or a lowercase phrase ("the hotel") doesn't.
        named = [word for word in words if word.lower() not in _LINKING_WORDS]
        return len(words) > 1 and bool(named) and all(word[0].isupper() for word in named)
    return True


is_place = _is_place


def named_places(itinerary: str) -> list[str]:
    """Each place the itinerary names in bold, once, in order of first mention."""
    seen: set[str] = set()
    names: list[str] = []
    for match in _BOLD.finditer(itinerary or ""):
        if not _is_place(match.group(1)):
            continue
        name = clean(match.group(1))
        if name.lower() not in seen:
            seen.add(name.lower())
            names.append(name)
    return names


def replace_place(itinerary: str, old: str, new: str) -> str:
    """The itinerary with every bold mention of `old` naming `new` instead."""
    return _BOLD.sub(lambda m: f"**{new}**" if clean(m.group(1)).lower() == old.lower() else m.group(0), itinerary)
