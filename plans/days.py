"""The days of an itinerary, for changing only the days a traveller names (TP-06 F3, F4)."""

from __future__ import annotations

import re
from dataclasses import dataclass

# A day heading on its own line: "## Day 2: Canggu", "**Day 2 – Canggu**", "Day 2:".
_HEADING = re.compile(r"^[^\w\n]{0,8}Day\s*:?\s*(\d{1,2})\b", re.IGNORECASE | re.MULTILINE)
# Where the words after the last day begin: another heading, or a closing line.
_AFTER_LAST_DAY = re.compile(
    r"^(?:#{1,6}[ \t]*(?!Day\b)\S|[*_ \t]*(?:Enjoy your|Have a (?:great|wonderful|lovely)|Safe travels|Happy travels|Nearby, if you have more time))",
    re.IGNORECASE | re.MULTILINE,
)
# "Day 2", "Days 1 and 3", "days 1, 2 & 4", "Days 2-4", "day 2 to 4"
_NAMED = re.compile(r"\bdays?\s*(\d{1,2})((?:\s*(?:,|&|\band\b|\bor\b)\s*\d{1,2})*)(?:\s*(?:-|–|\bto\b|\bthrough\b)\s*(\d{1,2}))?", re.IGNORECASE)


@dataclass(frozen=True)
class DayBlock:
    number: int
    start: int
    end: int  # without the whitespace after the day


def day_blocks(text: str) -> list[DayBlock]:
    text = text or ""
    headings = list(_HEADING.finditer(text))
    blocks: list[DayBlock] = []
    for index, heading in enumerate(headings):
        start = heading.start()
        if index + 1 < len(headings):
            end = headings[index + 1].start()
        else:
            end = len(text)
            line_end = text.find("\n", start)
            if line_end != -1:
                after = _AFTER_LAST_DAY.search(text, line_end + 1)
                if after:
                    end = after.start()
        while end > start and text[end - 1].isspace():
            end -= 1
        blocks.append(DayBlock(int(heading.group(1)), start, end))
    return blocks


def day_texts(text: str) -> dict[int, str]:
    """Each day's text, heading included; the first one wins when a day appears twice."""
    texts: dict[int, str] = {}
    for block in day_blocks(text):
        texts.setdefault(block.number, text[block.start:block.end])
    return texts


def replace_days(text: str, replacements: dict[int, str]) -> str:
    """The itinerary with these days' text replaced, and every other character kept."""
    done: set[int] = set()
    firsts = []
    for block in day_blocks(text):
        if block.number not in done:
            done.add(block.number)
            firsts.append(block)
    for block in sorted(firsts, key=lambda b: b.start, reverse=True):
        if block.number in replacements:
            text = text[:block.start] + replacements[block.number].strip() + text[block.end:]
    return text


def named_days(request: str) -> list[int]:
    days: set[int] = set()
    for match in _NAMED.finditer(request or ""):
        listed = [int(match.group(1)), *(int(n) for n in re.findall(r"\d{1,2}", match.group(2) or ""))]
        days.update(listed)
        if match.group(3):
            last = int(match.group(3))
            days.update(range(min(listed[-1], last), max(listed[-1], last) + 1))
    return sorted(days)
