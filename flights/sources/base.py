"""What every flight source shares."""

from __future__ import annotations


class SourceUnavailable(Exception):
    """A source couldn't answer: blocked, failing or not installed.

    The message is logged, so it must never contain a key, token or URL with secrets.
    """
