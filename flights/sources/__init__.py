"""Flight sources, in the order they are tried (TP-01 decision D1)."""

from __future__ import annotations

from typing import Mapping

from .base import SourceUnavailable
from .fli_source import FliDateSource, FliSource
from .gf_search import GfSearchSource
from .swoop_source import SwoopSource
from .travelpayouts import TravelpayoutsDateSource, TravelpayoutsSource

__all__ = [
    "SourceUnavailable",
    "GfSearchSource",
    "FliSource",
    "SwoopSource",
    "TravelpayoutsSource",
    "FliDateSource",
    "TravelpayoutsDateSource",
    "build_sources",
    "build_date_sources",
]


def _travelpayouts_settings(env: Mapping[str, str]) -> tuple[str, str | None]:
    token = (env.get("AVIASALES_API_TOKEN") or "").strip()
    marker = (env.get("TRAVELPAYOUTS_MARKER") or "").strip() or None
    return token, marker


def build_sources(env: Mapping[str, str]) -> list:
    """gf-search -> fli -> swoop -> Travelpayouts (only when AVIASALES_API_TOKEN is set)."""
    sources: list = [GfSearchSource(), FliSource(), SwoopSource()]
    token, marker = _travelpayouts_settings(env)
    if token:
        sources.append(TravelpayoutsSource(token=token, marker=marker))
    return sources


def build_date_sources(env: Mapping[str, str]) -> list:
    sources: list = [FliDateSource()]
    token, marker = _travelpayouts_settings(env)
    if token:
        sources.append(TravelpayoutsDateSource(token=token, marker=marker))
    return sources
