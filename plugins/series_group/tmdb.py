# ============================================================
# 🏨 DOWNTOWN VILLA — TMDB HELPERS FOR SERIES
# ============================================================
#
# Uses the SAME TMDB integration as the rest of the bot.
# No API key required if provider already initialized.
#
# ============================================================

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ============================================================
# SEARCH
# ============================================================

async def search_series(query: str) -> List[Dict[str, Any]]:
    """Search TMDB for a series."""
    try:
        from providers import tmdb_provider
        r = await tmdb_provider.fetch(query, bulk=True)
        if not r:
            return []
        return list(r)[:8]
    except Exception as e:
        logger.debug(f"[SG-TMDB] search: {e}")
        return []


# ============================================================
# DETAILS
# ============================================================

async def get_details(tmdb_id: int) -> Optional[Dict[str, Any]]:
    """Fetch full details for a series."""
    try:
        import aiohttp
        from core import config
        if not config.TMDB_API_KEY:
            return None

        url = f"https://api.themoviedb.org/3/tv/{tmdb_id}"
        params = {"api_key": config.TMDB_API_KEY, "language": "en-US"}

        async with aiohttp.ClientSession() as s:
            async with s.get(url, params=params, timeout=10) as r:
                if r.status != 200:
                    return None
                return await r.json()
    except Exception as e:
        logger.debug(f"[SG-TMDB] details: {e}")
        return None


# ============================================================
# LANGUAGES
# ============================================================

_LANG_MAP = {
    "en": "English", "hi": "Hindi", "ta": "Tamil", "te": "Telugu",
    "ml": "Malayalam", "kn": "Kannada", "bn": "Bengali",
    "mr": "Marathi", "pa": "Punjabi", "gu": "Gujarati",
    "ur": "Urdu", "ko": "Korean", "ja": "Japanese",
    "zh": "Chinese", "es": "Spanish", "fr": "French",
    "de": "German", "it": "Italian", "pt": "Portuguese",
    "ru": "Russian", "tr": "Turkish", "ar": "Arabic",
    "th": "Thai",
}


def extract_languages(details: Dict[str, Any]) -> List[str]:
    """Extract spoken languages from TMDB details."""
    langs = set()
    try:
        orig = (details.get("original_language") or "").lower()
        if orig:
            langs.add(orig)
        for sl in (details.get("spoken_languages") or []):
            code = (sl.get("iso_639_1") or "").lower()
            if code:
                langs.add(code)
    except Exception:
        pass

    named = [_LANG_MAP[c] for c in langs if c in _LANG_MAP]
    named.sort(key=lambda x: (x != "English", x))
    return named or ["English"]


# ============================================================
# SEASONS
# ============================================================

def extract_seasons(details: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Return list of seasons:
      [{season: 1, episodes: 10, year: "2018"}, ...]
    Season 0 skipped (specials).
    """
    out: List[Dict[str, Any]] = []
    try:
        for s in (details.get("seasons") or []):
            sn = s.get("season_number")
            if sn is None or sn == 0:
                continue
            out.append({
                "season": int(sn),
                "episodes": int(s.get("episode_count", 0) or 0),
                "year": (s.get("air_date") or "")[:4],
            })
        out.sort(key=lambda x: x["season"])
    except Exception:
        pass
    return out


# ============================================================
# EPISODES FOR A SEASON
# ============================================================

async def get_season_episodes(
    tmdb_id: int,
    season: int,
) -> List[int]:
    """
    Fetch episode numbers for a specific season.
    Returns list like [1, 2, 3, ...].
    """
    try:
        import aiohttp
        from core import config
        if not config.TMDB_API_KEY:
            return []

        url = f"https://api.themoviedb.org/3/tv/{tmdb_id}/season/{season}"
        params = {"api_key": config.TMDB_API_KEY, "language": "en-US"}

        async with aiohttp.ClientSession() as s:
            async with s.get(url, params=params, timeout=10) as r:
                if r.status != 200:
                    return []
                data = await r.json()

        eps = []
        for ep in (data.get("episodes") or []):
            n = ep.get("episode_number")
            if n is not None:
                eps.append(int(n))
        return sorted(eps)
    except Exception as e:
        logger.debug(f"[SG-TMDB] episodes: {e}")
        return []


# ============================================================
# POSTER
# ============================================================

def poster_url(path: Optional[str], size: str = "w500") -> Optional[str]:
    if not path:
        return None
    return f"https://image.tmdb.org/t/p/{size}{path}"


# ============================================================
# PUBLIC
# ============================================================

__all__ = [
    "search_series",
    "get_details",
    "extract_languages",
    "extract_seasons",
    "get_season_episodes",
    "poster_url",
]
