# ============================================================
# 🏨 DOWNTOWN VILLA — TMDB PROVIDER
# ============================================================
#
# Unified TMDB search + detail fetcher.
#
# Used by:
#   • plugins/series_group/tmdb.py  (search_series)
#   • plugins/missing/scan.py       (own session, not this)
#
# Public API:
#   fetch(query, bulk=True)  → list[dict]
#   get_movie(tmdb_id)       → dict | None
#   get_tv(tmdb_id)          → dict | None
#   search_movie(query)      → list[dict]
#   search_tv(query)         → list[dict]
#
# Returned item shape:
#   {
#     "tmdb_id": int,
#     "title": str,
#     "original_title": str,
#     "year": str,
#     "overview": str,
#     "poster": str | None,       # poster_path
#     "backdrop": str | None,
#     "rating": float,
#     "votes": int,
#     "kind": "movie" | "series",
#     "lang": str,                # original_language
#   }
#
# ============================================================

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional

from core import config

logger = logging.getLogger(__name__)

TMDB_BASE = "https://api.themoviedb.org/3"
HTTP_TIMEOUT = 10


# ── HTTP ──

async def _get(path: str, params: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
    """Raw GET against TMDB. Returns JSON or None."""
    if not config.TMDB_API_KEY:
        logger.debug("[TMDB] no API key set")
        return None

    try:
        import aiohttp
    except ImportError:
        logger.warning("[TMDB] aiohttp not installed")
        return None

    p = {"api_key": config.TMDB_API_KEY, "language": "en-US"}
    if params:
        p.update(params)

    url = f"{TMDB_BASE}{path}"
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, params=p, timeout=HTTP_TIMEOUT) as r:
                if r.status != 200:
                    logger.debug(f"[TMDB] {path} → {r.status}")
                    return None
                return await r.json()
    except asyncio.TimeoutError:
        logger.debug(f"[TMDB] timeout: {path}")
        return None
    except Exception as e:
        logger.debug(f"[TMDB] {path}: {e}")
        return None


# ── NORMALIZE ──

def _normalize_movie(r: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "tmdb_id": r.get("id"),
        "title": r.get("title") or r.get("original_title") or "",
        "original_title": r.get("original_title") or "",
        "year": (r.get("release_date") or "")[:4],
        "release_date": r.get("release_date") or "",
        "overview": r.get("overview") or "",
        "poster": r.get("poster_path"),
        "backdrop": r.get("backdrop_path"),
        "rating": round(float(r.get("vote_average") or 0), 1),
        "votes": int(r.get("vote_count") or 0),
        "popularity": round(float(r.get("popularity") or 0), 1),
        "kind": "movie",
        "lang": (r.get("original_language") or "").lower(),
    }


def _normalize_tv(r: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "tmdb_id": r.get("id"),
        "title": r.get("name") or r.get("original_name") or "",
        "original_title": r.get("original_name") or "",
        "year": (r.get("first_air_date") or "")[:4],
        "release_date": r.get("first_air_date") or "",
        "overview": r.get("overview") or "",
        "poster": r.get("poster_path"),
        "backdrop": r.get("backdrop_path"),
        "rating": round(float(r.get("vote_average") or 0), 1),
        "votes": int(r.get("vote_count") or 0),
        "popularity": round(float(r.get("popularity") or 0), 1),
        "kind": "series",
        "lang": (r.get("original_language") or "").lower(),
    }


# ── SEARCH ──

async def search_movie(query: str) -> List[Dict[str, Any]]:
    """Search movies. Returns normalized list."""
    if not query:
        return []
    data = await _get("/search/movie", {"query": query})
    if not data:
        return []
    return [_normalize_movie(r) for r in (data.get("results") or [])]


async def search_tv(query: str) -> List[Dict[str, Any]]:
    """Search TV series. Returns normalized list."""
    if not query:
        return []
    data = await _get("/search/tv", {"query": query})
    if not data:
        return []
    return [_normalize_tv(r) for r in (data.get("results") or [])]


async def fetch(query: str, bulk: bool = True) -> List[Dict[str, Any]]:
    """
    Unified search — returns BOTH movies and TV, sorted by popularity.

    Used by series_group.tmdb.search_series(...) — but that caller
    wants series, so we put TV first when bulk=False.
    """
    if not query:
        return []

    if bulk:
        # Run both in parallel
        results = await asyncio.gather(
            search_tv(query),
            search_movie(query),
            return_exceptions=True,
        )
        tv = results[0] if not isinstance(results[0], Exception) else []
        mv = results[1] if not isinstance(results[1], Exception) else []
        merged = list(tv) + list(mv)
    else:
        # Series-first (used by series_group)
        tv = await search_tv(query)
        merged = list(tv)

    # Sort by popularity desc, then rating
    merged.sort(
        key=lambda x: (x.get("popularity", 0), x.get("rating", 0)),
        reverse=True,
    )
    return merged[:10]


# ── DETAILS ──

async def get_movie(tmdb_id: int) -> Optional[Dict[str, Any]]:
    data = await _get(f"/movie/{int(tmdb_id)}")
    return _normalize_movie(data) if data else None


async def get_tv(tmdb_id: int) -> Optional[Dict[str, Any]]:
    data = await _get(f"/tv/{int(tmdb_id)}")
    return _normalize_tv(data) if data else None


# ── POSTER URL ──

def poster_url(path: Optional[str], size: str = "w500") -> Optional[str]:
    if not path:
        return None
    return f"https://image.tmdb.org/t/p/{size}{path}"


# ── EXPORTS ──

__all__ = [
    "fetch",
    "search_movie",
    "search_tv",
    "get_movie",
    "get_tv",
    "poster_url",
]
