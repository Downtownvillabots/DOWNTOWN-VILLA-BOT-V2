# ============================================================
# 🏨 DOWNTOWN VILLA — SERIES TMDB HELPERS
# ============================================================
#
# TMDB lookup helpers for the series wizard:
#   • get_series_languages(query)         → list[str]
#   • get_series_seasons(query)           → list[dict]
#   • get_season_episodes(query, season)  → list[int]
#   • get_series_details(query)           → dict | None
#   • resolve_series(query)               → tmdb_id | None
#
# The wizard passes a query (title) not a tmdb_id, so we:
#   1. Resolve query → tmdb_id  (cached 1h)
#   2. Fetch details/seasons/episodes from TMDB (cached 1h)
#
# Cache lives in-memory; TTL 3600s. Cleared on bot restart —
# that's fine, TMDB is fast.
#
# Uses:
#   • providers.tmdb_provider for search
#   • direct aiohttp for /tv endpoints (languages, seasons, eps)
#
# Public API:
#   resolve_series(query)              → int | None
#   get_series_details(query)          → dict | None
#   get_series_languages(query)        → list[str]
#   get_series_seasons(query)          → list[dict]
#   get_season_episodes(query, season) → list[int]
#   poster_url(path, size)             → str | None
#
# ============================================================

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from core import config

logger = logging.getLogger(__name__)


# ============================================================
# SECTION 1 — CONSTANTS
# ============================================================

_CACHE_TTL = 3600.0
TMDB_BASE = "https://api.themoviedb.org/3"
TMDB_IMG = "https://image.tmdb.org/t/p"

_LANG_MAP: Dict[str, str] = {
    "en": "English", "hi": "Hindi", "ta": "Tamil", "te": "Telugu",
    "ml": "Malayalam", "kn": "Kannada", "bn": "Bengali",
    "mr": "Marathi", "pa": "Punjabi", "gu": "Gujarati",
    "ur": "Urdu", "ko": "Korean", "ja": "Japanese",
    "zh": "Chinese", "cn": "Chinese",
    "es": "Spanish", "fr": "French", "de": "German",
    "it": "Italian", "pt": "Portuguese", "ru": "Russian",
    "tr": "Turkish", "ar": "Arabic", "th": "Thai",
    "id": "Indonesian", "vi": "Vietnamese",
    "tl": "Filipino", "ne": "Nepali", "si": "Sinhala",
    "as": "Assamese", "or": "Odia", "bh": "Bhojpuri",
}


# ============================================================
# SECTION 2 — CACHE
# ============================================================

_cache: Dict[str, Tuple[float, Any]] = {}


def _cache_get(key: str) -> Optional[Any]:
    item = _cache.get(key)
    if not item:
        return None
    if item[0] < time.time():
        _cache.pop(key, None)
        return None
    return item[1]


def _cache_set(key: str, value: Any) -> None:
    _cache[key] = (time.time() + _CACHE_TTL, value)


def _cache_key(kind: str, *parts) -> str:
    return f"{kind}|" + "|".join(str(p) for p in parts)


# ============================================================
# SECTION 3 — TMDB HTTP
# ============================================================

async def _tmdb_get(
    path: str,
    params: Optional[Dict[str, Any]] = None,
) -> Optional[Dict[str, Any]]:
    """Raw GET against TMDB. Returns JSON or None."""
    if not config.TMDB_API_KEY:
        logger.debug("[SERIES-TMDB] no API key")
        return None

    try:
        import aiohttp
    except ImportError:
        return None

    p = {"api_key": config.TMDB_API_KEY, "language": "en-US"}
    if params:
        p.update(params)

    url = f"{TMDB_BASE}/{path.lstrip('/')}"
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, params=p, timeout=15) as r:
                if r.status != 200:
                    logger.debug(f"[SERIES-TMDB] {path} → {r.status}")
                    return None
                return await r.json()
    except Exception as e:
        logger.debug(f"[SERIES-TMDB] {path}: {e}")
        return None


# ============================================================
# SECTION 4 — RESOLVE SERIES (query → tmdb_id)
# ============================================================

async def resolve_series(query: str) -> Optional[int]:
    """
    Search TMDB TV for a title, return the best tmdb_id.
    """
    if not query:
        return None

    key = _cache_key("tmdb_id", query.lower())
    cached = _cache_get(key)
    if cached is not None:
        return cached if cached != 0 else None

    tmdb_id: Optional[int] = None

    # Try provider abstraction first
    try:
        from providers import tmdb_provider as TP
        results = await TP.search_tv(query)
        if results:
            # First result is most popular / most relevant
            top = results[0]
            tid = top.get("tmdb_id")
            if tid:
                tmdb_id = int(tid)
    except Exception as e:
        logger.debug(f"[SERIES-TMDB] provider search: {e}")

    # Fallback: direct TMDB search
    if not tmdb_id:
        data = await _tmdb_get("/search/tv", {"query": query, "page": 1})
        if data:
            results = data.get("results") or []
            if results:
                try:
                    tmdb_id = int(results[0].get("id"))
                except (TypeError, ValueError):
                    tmdb_id = None

    # Cache the result (0 = negative cache)
    _cache_set(key, tmdb_id if tmdb_id else 0)
    return tmdb_id


# ============================================================
# SECTION 5 — GET SERIES DETAILS
# ============================================================

async def get_series_details(query: str) -> Optional[Dict[str, Any]]:
    """
    Full series details (seasons, genres, spoken_languages, etc.).
    """
    if not query:
        return None

    key = _cache_key("details", query.lower())
    cached = _cache_get(key)
    if cached is not None:
        return cached if cached != {} else None

    tmdb_id = await resolve_series(query)
    if not tmdb_id:
        _cache_set(key, {})
        return None

    data = await _tmdb_get(f"/tv/{tmdb_id}")
    if not data:
        _cache_set(key, {})
        return None

    _cache_set(key, data)
    return data


# ============================================================
# SECTION 6 — LANGUAGES
# ============================================================

async def get_series_languages(query: str) -> List[str]:
    """
    Return language names for a series.
    Combines original_language + spoken_languages, translated
    through _LANG_MAP. English is always first when present.
    """
    details = await get_series_details(query)
    if not details:
        return []

    codes: set = set()

    orig = (details.get("original_language") or "").lower()
    if orig:
        codes.add(orig)

    for sl in (details.get("spoken_languages") or []):
        code = (sl.get("iso_639_1") or "").lower()
        if code:
            codes.add(code)

    # Translate to names, dedupe
    names: List[str] = []
    for c in codes:
        n = _LANG_MAP.get(c)
        if n and n not in names:
            names.append(n)

    # Stable order: English first, then alphabetical
    names.sort(key=lambda x: (x != "English", x))
    return names


# ============================================================
# SECTION 7 — SEASONS
# ============================================================

async def get_series_seasons(query: str) -> List[Dict[str, Any]]:
    """
    Return season list for a series.

    Skips season 0 (specials).

    Output:
      [
        {"season": 1, "episodes": 10, "year": "2008"},
        {"season": 2, "episodes": 13, "year": "2009"},
        ...
      ]
    """
    details = await get_series_details(query)
    if not details:
        return []

    out: List[Dict[str, Any]] = []
    for s in (details.get("seasons") or []):
        sn = s.get("season_number")
        if sn is None or sn == 0:
            continue
        try:
            sn_int = int(sn)
        except (TypeError, ValueError):
            continue

        out.append({
            "season": sn_int,
            "episodes": int(s.get("episode_count") or 0),
            "year": (s.get("air_date") or "")[:4],
        })

    out.sort(key=lambda x: x["season"])
    return out


# ============================================================
# SECTION 8 — EPISODES FOR A SEASON
# ============================================================

async def get_season_episodes(query: str, season: int) -> List[int]:
    """
    Return episode numbers for a specific season.
    Skips specials (episode_number == 0).
    """
    if not query or season is None:
        return []

    try:
        sn = int(season)
    except (TypeError, ValueError):
        return []

    key = _cache_key("eps", query.lower(), sn)
    cached = _cache_get(key)
    if cached is not None:
        return list(cached) if cached else []

    tmdb_id = await resolve_series(query)
    if not tmdb_id:
        _cache_set(key, [])
        return []

    data = await _tmdb_get(f"/tv/{tmdb_id}/season/{sn}")
    if not data:
        _cache_set(key, [])
        return []

    eps: List[int] = []
    for ep in (data.get("episodes") or []):
        n = ep.get("episode_number")
        if n is None:
            continue
        try:
            n_int = int(n)
        except (TypeError, ValueError):
            continue
        if n_int <= 0:
            continue
        if n_int not in eps:
            eps.append(n_int)

    eps.sort()
    _cache_set(key, eps)
    return eps


# ============================================================
# SECTION 9 — POSTER URL
# ============================================================

def poster_url(path: Optional[str], size: str = "w500") -> Optional[str]:
    if not path:
        return None
    return f"{TMDB_IMG}/{size}{path}"


# ============================================================
# SECTION 10 — PUBLIC EXPORTS
# ============================================================

def snapshot() -> Dict[str, Any]:
    return {
        "cache_size": len(_cache),
        "has_api_key": bool(config.TMDB_API_KEY),
    }


__all__ = [
    "resolve_series",
    "get_series_details",
    "get_series_languages",
    "get_series_seasons",
    "get_season_episodes",
    "poster_url",
    "snapshot",
]
