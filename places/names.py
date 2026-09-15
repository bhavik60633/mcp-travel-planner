"""Whether a Google result is the place the plan names (TP-07 N2, L4).

Google's Text Search returns its best match inside the area it's given, even when nothing there has that name. On a live
Jaipur plan (15 Sep 2026), "Taj Mahal" matched Jai Mahal Palace and "Agra Fort" matched Nahargarh Fort, both in Jaipur.
A result counts only when it has the name's distinctive words: "Fort", "Beach" or the destination's own name don't count.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Iterable

from .extract import GENERIC_WORDS

LINKING = {"the", "a", "an", "and", "of", "at", "in", "on", "to", "for", "with", "from", "by", "near", "ka", "ki", "ke", "de", "la", "le", "da", "di", "el"}


def words(text: str) -> list[str]:
    plain = unicodedata.normalize("NFKD", text or "").encode("ascii", "ignore").decode("ascii").lower()
    return re.findall(r"[a-z0-9]+", plain)


def _close(a: str, b: str) -> bool:
    """The same word, or one letter apart when both are 4 letters or more ("Amer" and "Amber")."""
    if a == b:
        return True
    if min(len(a), len(b)) < 4 or abs(len(a) - len(b)) > 1:
        return False
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) <= 1
    longer, shorter = (a, b) if len(a) > len(b) else (b, a)
    return any(longer[:i] + longer[i + 1 :] == shorter for i in range(len(longer)))


def _wanted(name: str, ignore: set[str]) -> list[str]:
    # After a comma is where it is ("City Palace, Jaipur"); a town in the name itself still counts ("Pushkar Lake" near Pushkar).
    main = name.split(",")[0]
    named = [word for word in words(main) if word not in LINKING]
    distinctive = [word for word in named if word not in GENERIC_WORDS]
    for group in ([w for w in distinctive if w not in ignore], distinctive, [w for w in named if w not in ignore], named):
        if group:
            return list(dict.fromkeys(group))
    return []


def names_match(name: str, candidate: str | None, ignore: Iterable[str] = ()) -> bool:
    """True when `candidate` has the distinctive words of `name` (all of them, or all but one for 3 or more).

    `ignore` is text whose words don't count, such as the destination ("City Palace, Jaipur" needs "City Palace").
    """
    ignored = {word for text in ignore for word in words(text)}
    wanted = _wanted(name, ignored)
    if not wanted:
        return True
    have = words(candidate or "")
    initials = "".join(word[0] for word in have if word not in LINKING)  # "LMB" for Laxmi Misthan Bhandar
    # One distinctive word must match exactly: "Cured" isn't "Cure Well Speech And Hearing Clinic" (live, 15 Sep 2026).
    same = _close if len(wanted) > 1 else (lambda a, b: a == b)
    hits = sum(1 for word in wanted if any(same(word, other) for other in have) or (len(word) >= 2 and word == initials))
    if hits >= (len(wanted) - 1 if len(wanted) >= 3 else len(wanted)):
        return True
    # Words written together or apart: "Ana Sagar Lake" is "Anasagar Lake" on Google (live, 15 Sep 2026).
    together = "".join(wanted)
    if len(together) >= 6 and together in "".join(have):
        return True
    # Google's shorter name for the same place: "Anokhi Museum" for "Anokhi Museum of Hand Printing" (live, 15 Sep 2026).
    # It must start the same way, so "Agra" isn't "Drive from Jaipur to Agra".
    theirs = [word for word in dict.fromkeys(have) if word not in LINKING and word not in GENERIC_WORDS and word not in ignored]
    named = set(words(name))
    return bool(theirs) and len(theirs) < len(wanted) and all(word in named for word in theirs) and theirs[0] == wanted[0] and len(theirs[0]) >= 4
