# ============================================================
# 🏨 DOWNTOWN VILLA — SPELL CHECK + SUGGESTIONS
# ============================================================
#
# Two jobs:
#   1. clean_query(raw)             — normalize text
#   2. ai_spell_check(text)         — best-guess correction
#   3. get_suggestions(query)       — TMDB fallback list
#
# Public API:
#   clean_query(raw)                → str
#   ai_spell_check(text, is_series) → str | None
#   get_suggestions(query, is_series) → list[dict]
#
# Suggestion dict shape:
#   {
#     "title": str,
#     "year": str,
#     "rating": float,
#     "kind": "movie" | "series",
#     "tmdb_id": int,
#     "poster": str | None,
#     "overview": str,
#   }
#
# ============================================================

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── PATTERNS ──

_RE_EXT = re.compile(
    r"\.(mkv|mp4|avi|mov|wmv|flv|webm|m4v|ts|m2ts|mpg|mpeg)$",
    re.IGNORECASE,
)
_RE_BRACKETS = re.compile(r"[\[\{\(].*?[\]\}\)]")
_RE_NON_WORD = re.compile(r"[^\w\s]+")
_RE_SPACES = re.compile(r"\s+")


# ============================================================
# CLEAN
# ============================================================

def clean_query(raw: str) -> str:
    """Light cleanup — safe to call on any input."""
    if not raw:
        return ""
    try:
        t = str(raw).strip()
        t = _RE_EXT.sub("", t)
        t = _RE_BRACKETS.sub(" ", t)
        t = _RE_NON_WORD.sub(" ", t)
        t = _RE_SPACES.sub(" ", t)
        return t.strip().lower()
    except Exception:
        return str(raw).strip().lower()


# ============================================================
# AI SPELL CHECK
# ============================================================

async def ai_spell_check(
    text: str,
    is_series: bool = False,
) -> Optional[str]:
    """
    Best-effort spell correction.

    Strategy:
      1. If rapidfuzz is available, compare against TMDB top result.
      2. Otherwise, return None (no correction).

    Returns corrected title OR None if no confident correction.
    """
    if not text:
        return None

    base = clean_query(text)
    if not base or len(base) < 3:
        return None

    # Fetch TMDB candidates
    try:
        from providers import tmdb_provider as TP
        if is_series:
            candidates = await TP.search_tv(base)
        else:
            candidates = await TP.fetch(base, bulk=True)
    except Exception as e:
        logger.debug(f"[SPELL] tmdb: {e}")
        return None

    if not candidates:
        return None

    # Try rapidfuzz
    try:
        from rapidfuzz import fuzz
    except ImportError:
        # No fuzzy lib — accept the top hit only if it starts similar
        top = candidates[0]
        top_title = clean_query(top.get("title") or "")
        if top_title and (top_title in base or base in top_title):
            return top.get("title")
        return None

    # Score each candidate
    best_score = 0
    best_title: Optional[str] = None
    for c in candidates[:8]:
        title = c.get("title") or ""
        if not title:
            continue
        score = fuzz.ratio(base, clean_query(title))
        if score > best_score:
            best_score = score
            best_title = title

    # Threshold: only correct if we beat 82%
    if best_score >= 82 and best_title:
        # Don't return the SAME string back
        if clean_query(best_title) == base:
            return None
        return best_title

    return None


# ============================================================
# SUGGESTIONS
# ============================================================

async def get_suggestions(
    query: str,
    is_series: bool = False,
    limit: int = 8,
) -> List[Dict[str, Any]]:
    """
    Return TMDB suggestion list for a query.

    Used when the DB returns no hits.
    """
    if not query:
        return []

    base = clean_query(query)
    if not base or len(base) < 2:
        return []

    try:
        from providers import tmdb_provider as TP
    except Exception as e:
        logger.debug(f"[SUGGEST] provider: {e}")
        return []

    items: List[Dict[str, Any]] = []

    try:
        if is_series:
            raw = await TP.search_tv(base)
        else:
            # Try both; movie results first for non-series queries
            raw_movies = await TP.search_movie(base)
            raw_series = await TP.search_tv(base)

            # Interleave by popularity
            merged = []
            for m in raw_movies[:6]:
                merged.append(m)
            for s in raw_series[:4]:
                merged.append(s)
            raw = merged
    except Exception as e:
        logger.debug(f"[SUGGEST] search: {e}")
        return []

    # Normalize to suggestion shape
    seen = set()
    for item in raw:
        tmdb_id = item.get("tmdb_id")
        if not tmdb_id or tmdb_id in seen:
            continue
        seen.add(tmdb_id)

        items.append({
            "title": item.get("title") or "",
            "year": item.get("year") or "",
            "rating": item.get("rating") or 0,
            "kind": item.get("kind") or "movie",
            "tmdb_id": int(tmdb_id),
            "poster": item.get("poster"),
            "overview": item.get("overview") or "",
            "popularity": item.get("popularity") or 0,
        })

        if len(items) >= limit:
            break

    # Sort by popularity desc
    items.sort(key=lambda x: x.get("popularity", 0), reverse=True)
    return items[:limit]


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    "clean_query",
    "ai_spell_check",
    "get_suggestions",
]
