# ============================================================
# 🏨 DOWNTOWN VILLA — QUERY NORMALIZER
# ============================================================
#
# Turns messy user input into a clean title + optional year
# + movie/series hint.
#
# Public API:
#   parse_query(raw)  → (normalized, year | None, is_series)
#   normalize(raw)    → normalized string only
#
# Examples:
#   "Braking Bad S01E03 1080p" → ("breaking bad", None, True)
#   "Inception 2010"           → ("inception", 2010, False)
#   "The Office Complete"      → ("the office", None, True)
#
# ============================================================

from __future__ import annotations

import logging
import re
from typing import Optional, Tuple

logger = logging.getLogger(__name__)


# ── PATTERNS ──

_RE_YEAR = re.compile(r"\b(19[3-9]\d|20[0-4]\d)\b")

_RE_SEASON_EP = re.compile(
    r"\bS(\d{1,2})\s*[\s._-]?\s*E(\d{1,3})\b", re.IGNORECASE
)
_RE_SEASON_EP_ALT = re.compile(
    r"\b(\d{1,2})\s*x\s*(\d{1,3})\b"
)
_RE_SEASON_ONLY = re.compile(
    r"\bS(?:eason)?\s*(\d{1,2})\b", re.IGNORECASE
)
_RE_EPISODE_ONLY = re.compile(
    r"\bE(?:p|pisode)?\s*(\d{1,3})\b", re.IGNORECASE
)

_RE_QUALITY = re.compile(
    r"\b(2160p|1440p|1080p|720p|576p|480p|360p|"
    r"4k|uhd|fhd|hd|sd|bluray|blu-ray|brrip|bdrip|"
    r"web-?dl|webrip|web|hdrip|dvdrip|dvdscr|hdtv)\b",
    re.IGNORECASE,
)

_RE_CODEC = re.compile(
    r"\b(hevc|h\.?264|h\.?265|x264|x265|aac|ac3|dts|ddp?)\b",
    re.IGNORECASE,
)

_RE_JUNK = re.compile(
    r"\b(esub|esubs|subs|sub|dual\s*audio|multi\s*audio|"
    r"10bit|8bit|hdr|sdr|imax|proper|repack|extended|"
    r"unrated|directors?\.?cut|remastered|"
    r"complete|season|series)\b",
    re.IGNORECASE,
)

_RE_EXT = re.compile(
    r"\.(mkv|mp4|avi|mov|wmv|flv|webm|m4v|ts|m2ts|mpg|mpeg)$",
    re.IGNORECASE,
)

_RE_BRACKETS = re.compile(r"[\[\{\(].*?[\]\}\)]")

_RE_NON_WORD = re.compile(r"[^\w\s]+")

_RE_SPACES = re.compile(r"\s+")


# ── PUBLIC API ──

def parse_query(raw: str) -> Tuple[str, Optional[int], bool]:
    """
    Parse user input.

    Returns:
        (normalized, year | None, is_series)
    """
    if not raw:
        return "", None, False

    try:
        text = str(raw).strip()
        if not text:
            return "", None, False

        # 1. Series detection (BEFORE stripping)
        is_series = _detect_series(text)

        # 2. Extract year
        year: Optional[int] = None
        ym = _RE_YEAR.search(text)
        if ym:
            try:
                year = int(ym.group(1))
            except ValueError:
                year = None

        # 3. Clean
        clean = _clean(text)

        # 4. Strip extension from tail
        clean = _RE_EXT.sub("", clean)

        # 5. Cut at first quality/codec/season/year token
        cut_markers = [
            _RE_QUALITY, _RE_CODEC,
            _RE_SEASON_EP, _RE_SEASON_EP_ALT,
            _RE_SEASON_ONLY, _RE_EPISODE_ONLY,
        ]
        earliest = len(clean)
        for pat in cut_markers:
            m = pat.search(clean)
            if m and m.start() < earliest:
                earliest = m.start()
        if year:
            for m in _RE_YEAR.finditer(clean):
                if m.start() < earliest:
                    earliest = m.start()
                    break
        if earliest < len(clean):
            clean = clean[:earliest]

        # 6. Strip junk words
        clean = _RE_JUNK.sub(" ", clean)

        # 7. Collapse spaces + lowercase
        clean = _RE_SPACES.sub(" ", clean).strip().lower()

        # 8. Strip leading articles (optional, helps fuzzy)
        #    Keep "the" — helps exact matches. Don't strip.

        return clean, year, is_series

    except Exception as e:
        logger.debug(f"[NORM] parse_query: {e}")
        return str(raw).strip().lower(), None, False


def normalize(raw: str) -> str:
    """Just the normalized string, no year/series info."""
    norm, _, _ = parse_query(raw)
    return norm


# ── INTERNAL ──

def _clean(text: str) -> str:
    """Basic cleanup — brackets, extensions, non-word chars."""
    t = str(text)
    t = _RE_BRACKETS.sub(" ", t)
    t = _RE_EXT.sub("", t)
    t = _RE_NON_WORD.sub(" ", t)
    t = _RE_SPACES.sub(" ", t)
    return t.strip()


def _detect_series(text: str) -> bool:
    """True if the text looks like a series identifier."""
    if _RE_SEASON_EP.search(text):
        return True
    if _RE_SEASON_EP_ALT.search(text):
        return True
    if _RE_SEASON_ONLY.search(text):
        return True
    # "complete" / "season N" / "web series"
    low = text.lower()
    if "complete" in low and ("season" in low or "series" in low):
        return True
    if "web series" in low or "tv show" in low:
        return True
    return False


# ── EXPORTS ──

__all__ = [
    "parse_query",
    "normalize",
]
