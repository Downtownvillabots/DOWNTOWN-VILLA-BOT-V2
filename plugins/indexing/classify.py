# ============================================================
# 🏨 DOWNTOWN VILLA — CONTENT CLASSIFIER
# ============================================================
#
# Decides: movie / series / unknown
# Never blocks a file. Unknown is a valid result.
#
# ============================================================

from __future__ import annotations

import logging
import re
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

# ── Strong series markers ──
#   Matches: "Show.S01E01", "Show_S01E01", "Show S01E01", "1x01"
#   Rejects: "Class01E01", "ShowS01E01" (preceded by letter)
_SERIES_STRONG = re.compile(
    r"(?:(?<![A-Za-z])S\d{1,2}\s*E\d{1,3}"
    r"|(?<![A-Za-z])\d{1,2}x\d{1,3})",
    re.IGNORECASE,
)

# ── Weak series markers (word "Season"/"Episode" etc.) ──
_SERIES_WEAK = re.compile(
    r"\b(?:Season\s*\d{1,2}|Episode\s*\d{1,3}|EP?\s*\d{1,3})\b",
    re.IGNORECASE,
)

# ── Series keywords ──
#   Note: no S\d{2} here — already covered by _SERIES_STRONG
_SERIES_KEYWORDS = re.compile(
    r"\b(series|episode|episodes|web\s*series|tv\s*show|"
    r"season\s*\d|complete\s*season)\b",
    re.IGNORECASE,
)

# ── Movie keywords ──
_MOVIE_KEYWORDS = re.compile(
    r"\b(movie|film|feature|dvdrip|bluray|web-dl|"
    r"hdrip|brrip|camrip)\b",
    re.IGNORECASE,
)


def classify(text: str = "", record: Optional[Dict[str, Any]] = None) -> str:
    """Return 'movie' | 'series' | 'unknown'."""
    try:
        if record:
            r = _classify_record(record)
            if r:
                return r
        if text:
            t = _classify_text(text)
            if t:
                return t
        return "unknown"
    except Exception as e:
        logger.debug(f"[CLASSIFY] error: {e}")
        return "unknown"


def _classify_record(record: Dict[str, Any]) -> Optional[str]:
    try:
        # 1. explicit type wins
        rtype = str(record.get("type") or "").lower().strip()
        if rtype in ("movie", "series"):
            return rtype

        # 2. explicit season/episode → series
        season = record.get("season")
        episode = record.get("episode")
        if season is not None and episode is not None:
            return "series"
        if record.get("episode_identifier"):
            return "series"

        # 3. inspect title for series markers BEFORE falling back to movie
        title = record.get("title") or record.get("normalized_title")
        if title:
            title_str = str(title)
            if _SERIES_STRONG.search(title_str):
                return "series"
            if _SERIES_WEAK.search(title_str):
                return "series"
            if _SERIES_KEYWORDS.search(title_str):
                return "series"

        # 4. title + year → movie (only after series markers are ruled out)
        year = record.get("year")
        if title and year:
            return "movie"

        return None
    except Exception:
        return None


def _classify_text(text: str) -> Optional[str]:
    try:
        t = str(text)
        if _SERIES_STRONG.search(t):
            return "series"
        if _SERIES_KEYWORDS.search(t):
            return "series"
        if _SERIES_WEAK.search(t):
            return "series"
        if _MOVIE_KEYWORDS.search(t):
            if re.search(r"\b(19[3-9]\d|20[0-4]\d)\b", t):
                return "movie"
        return None
    except Exception:
        return None


def is_movie(x: Any) -> bool:
    if isinstance(x, dict):
        return classify(record=x) == "movie"
    return classify(text=str(x)) == "movie"


def is_series(x: Any) -> bool:
    if isinstance(x, dict):
        return classify(record=x) == "series"
    return classify(text=str(x)) == "series"


def classify_record(record: Dict[str, Any]) -> str:
    return classify(record=record)


def classify_many(records: list) -> Dict[str, int]:
    out = {"movie": 0, "series": 0, "unknown": 0}
    for r in records:
        try:
            t = classify_record(r) if isinstance(r, dict) else "unknown"
            out[t] = out.get(t, 0) + 1
        except Exception:
            out["unknown"] += 1
    return out


__all__ = ["classify", "classify_record", "classify_many",
           "is_movie", "is_series"]
