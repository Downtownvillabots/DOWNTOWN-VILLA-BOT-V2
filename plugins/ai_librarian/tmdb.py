# ============================================================
# 🎛️ AI LIBRARIAN — TMDB API
# ============================================================
from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional

from plugins.ai_librarian.fonts import TMDB_API_KEY

logger = logging.getLogger(__name__)


async def _tmdb_get(path, params=None):
    if not TMDB_API_KEY: return None
    try:
        import aiohttp
    except ImportError: return None
    p = {"api_key": TMDB_API_KEY, "language": "en-US", **(params or {})}
    try:
        async with aiohttp.ClientSession() as sess:
            async with sess.get(f"https://api.themoviedb.org/3{path}",
                                params=p, timeout=12) as r:
                if r.status != 200: return None
                return await r.json()
    except Exception as e:
        logger.debug(f"[AI] tmdb: {e}"); return None


async def _tmdb_search_series(query):
    data = await _tmdb_get("/search/tv", {"query": query, "include_adult": "false"})
    if not data: return []
    out = []
    for it in (data.get("results") or [])[:8]:
        title = it.get("name") or it.get("original_name") or ""
        if not title: continue
        date = it.get("first_air_date") or ""
        out.append({
            "tmdb_id": it.get("id"), "title": title,
            "year": (date or "")[:4],
            "rating": it.get("vote_average", 0),
            "poster": it.get("poster_path"),
        })
    return out


async def _tmdb_series_details(tmdb_id):
    if not tmdb_id: return None
    return await _tmdb_get(f"/tv/{tmdb_id}", {})


def _tmdb_languages(details):
    langs = set()
    orig = (details.get("original_language") or "").lower()
    if orig: langs.add(orig)
    for sl in (details.get("spoken_languages") or []):
        code = (sl.get("iso_639_1") or "").lower()
        if code: langs.add(code)
    m = {"en":"English","hi":"Hindi","ta":"Tamil","te":"Telugu","ml":"Malayalam",
         "kn":"Kannada","bn":"Bengali","mr":"Marathi","pa":"Punjabi",
         "gu":"Gujarati","ur":"Urdu","ko":"Korean","ja":"Japanese",
         "zh":"Chinese","es":"Spanish","fr":"French","de":"German",
         "it":"Italian","pt":"Portuguese","ru":"Russian","tr":"Turkish",
         "ar":"Arabic","th":"Thai"}
    named = [m[c] for c in langs if c in m]
    named.sort(key=lambda x: (x != "English", x))
    return named or ["English"]


def _tmdb_seasons(details):
    """Return [{season, episodes, year}, ...] — season 0 skipped."""
    out = []
    for s in (details.get("seasons") or []):
        sn = s.get("season_number")
        if sn is None or sn == 0: continue
        out.append({
            "season": sn,
            "episodes": s.get("episode_count", 0),
            "year": (s.get("air_date") or "")[:4],
        })
    out.sort(key=lambda x: x["season"])
    return out


def _poster_url(path, size="w500"):
    if not path: return None
    return f"https://image.tmdb.org/t/p/{size}{path}"


__all__ = [
    "_tmdb_get", "_tmdb_search_series", "_tmdb_series_details",
    "_tmdb_languages", "_tmdb_seasons", "_poster_url",
]
