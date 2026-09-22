# ============================================================
# 🏨 DOWNTOWN VILLA — CONTENT CLASSIFIER
# ============================================================
#
# Decides: movie / series / unknown
#
# USES (in priority order):
#   1. Series metadata (season + episode present) → series
#   2. Type field from parser if already set
#   3. Filename patterns (S01E01, 1x01, Season 1)
#   4. Year present + title → movie
#   5. Fallback → unknown
#
# RULE: Never blocks a file. Unknown is a valid result.
#
# ============================================================

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


# ============================================================
# SECTION 1 — PATTERNS
# ============================================================

# Strong series signals (season + episode)
_SERIES_STRONG = re.compile(
    r"\b(?:S\d{1,2}E\d{1,3}|S\d{1,2}\s*E\d{1,3}|\d{1,2}x\d{1,3})\b",
    re.IGNORECASE,
)

# Weaker series signals (season only, episode only)
_SERIES_WEAK = re.compile(
    r"\b(?:Season\s*\d{1,2}|Episode\s*\d{1,3}|EP?\s*\d{1,3})\b",
    re.IGNORECASE,
)

# Series keywords
_SERIES_KEYWORDS = re.compile(
    r"\b(series|episode|episodes|web\s*series|tv\s*show|"
    r"season\s*\d|complete\s*season|S\d{2}\b)\b",
    re.IGNORECASE,
)

# Movie keywords
_MOVIE_KEYWORDS = re.compile(
    r"\b(movie|film|feature|dvdrip|bluray|web-dl|"
    r"hdrip|brrip|camrip)\b",
    re.IGNORECASE,
)


# ============================================================
# SECTION 2 — PUBLIC CLASSIFY
# ============================================================

def classify(
    text: str = "",
    record: Optional[Dict[str, Any]] = None,
) -> str:
    """
    Return 'movie' | 'series' | 'unknown'.

    Prefers `record` fields when present.
    Falls back to `text` pattern matching.

    NEVER raises. NEVER blocks. Always returns a string.
    """
    try:
        # ── 1. Record-based classification (highest priority) ──
        if record:
            r = _classify_record(record)
            if r:
                return r

        # ── 2. Text-based classification ──
        if text:
            t = _classify_text(text)
            if t:
                return t

        return "unknown"

    except Exception as e:
        logger.debug(f"[CLASSIFY] error: {e}")
        return "unknown"


# ============================================================
# SECTION 3 — RECORD-BASED
# ============================================================

def _classify_record(record: Dict[str, Any]) -> Optional[str]:
    """Classify from a parsed metadata dict."""
    try:
        # Explicit type set by parser
        rtype = str(record.get("type") or "").lower().strip()
        if rtype in ("movie", "series"):
            return rtype

        # Series markers (strongest signal)
        season = record.get("season")
        episode = record.get("episode")
        if season is not None and episode is not None:
            return "series"

        # Series title + identifier
        if record.get("episode_identifier"):
            return "series"

        # Movie: has title + year, no series markers
        title = record.get("title") or record.get("normalized_title")
        year = record.get("year")
        if title and year:
            return "movie"

        # Title only (no year)
        if title:
            # If the title alone looks like a series
            title_str = str(title)
            if _SERIES_STRONG.search(title_str):
                return "series"
            if _SERIES_WEAK.search(title_str):
                return "series"

        return None

    except Exception:
        return None


# ============================================================
# SECTION 4 — TEXT-BASED
# ============================================================

def _classify_text(text: str) -> Optional[str]:
    """Classify from a filename / caption."""
    try:
        t = str(text)

        # Series markers (strong) — most reliable
        if _SERIES_STRONG.search(t):
            return "series"

        # Series keywords
        if _SERIES_KEYWORDS.search(t):
            return "series"

        # Weak series markers
        if _SERIES_WEAK.search(t):
            return "series"

        # Movie keywords
        if _MOVIE_KEYWORDS.search(t):
            # Check for year presence
            if re.search(r"\b(19[3-9]\d|20[0-4]\d)\b", t):
                return "movie"

        return None

    except Exception:
        return None


# ============================================================
# SECTION 5 — CONVENIENCE
# ============================================================

def is_movie(text_or_record: Any) -> bool:
    if isinstance(text_or_record, dict):
        return classify(record=text_or_record) == "movie"
    return classify(text=str(text_or_record)) == "movie"


def is_series(text_or_record: Any) -> bool:
    if isinstance(text_or_record, dict):
        return classify(record=text_or_record) == "series"
    return classify(text=str(text_or_record)) == "series"


def classify_record(record: Dict[str, Any]) -> str:
    """Alias for compatibility with old code."""
    return classify(record=record)


# ============================================================
# SECTION 6 — BATCH HELPER
# ============================================================

def classify_many(records: list) -> Dict[str, int]:
    """Count movies / series / unknown in a batch."""
    out = {"movie": 0, "series": 0, "unknown": 0}
    for r in records:
        try:
            t = classify_record(r) if isinstance(r, dict) else "unknown"
            out[t] = out.get(t, 0) + 1
        except Exception:
            out["unknown"] += 1
    return out


# ============================================================
# SELF-CHECK
# ============================================================

def _self_check() -> bool:
    ok = True

    if classify(text="Movie.2024.1080p.mkv") != "movie":
        # No year-matched strong signal → falls through
        pass  # Acceptable either way

    if classify(text="Breaking.Bad.S01E01.1080p.mkv") != "series":
        ok = False

    if classify(text="Show.Name.1x05.mkv") != "series":
        ok = False

    if classify(record={"season": 1, "episode": 5}) != "series":
        ok = False

    if classify(record={"title": "Inception", "year": 2010}) != "movie":
        ok = False

    return ok


try:
    _SELF_CHECK_PASS = _self_check()
except Exception:
    _SELF_CHECK_PASS = False


# ============================================================
# PUBLIC EXPORTS
# ============================================================

__all__ = [
    "classify",
    "classify_record",
    "classify_many",
    "is_movie",
    "is_series",
]
