# ============================================================
# 🏨 DOWNTOWN VILLA — GROUPS SHARED SEARCH
# ============================================================
#
# DB search layer used by BOTH movie and series handlers.
#
# Wraps media_search.engine with:
#   • Quick cache lookup (via media_search.instant_cache)
#   • Normalizer + year + is_series parsing
#   • Consistent output shape (list of dicts)
#   • Graceful degradation when shards are offline
#
# Public API:
#   quick_search(query, year=None, is_series=False)
#       → (hits: list[dict], complete: bool)
#
#   search_by_title(title, year=None, kind="movie")
#       → list[dict]      (exact-title variant, no fallback)
#
#   sort_hits(hits, mode="small_to_big")
#       → list[dict]
#
#   to_dict(hit)          (FileHit → dict for session storage)
#
# All hits are plain dicts so they can be stored in sessions
# (media_search.sessions requires JSON-serializable candidates).
#
# ============================================================

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ============================================================
# SECTION 1 — HIT → DICT
# ============================================================

def to_dict(hit: Any) -> Dict[str, Any]:
    """
    Normalize a FileHit (or dict) into a plain dict.
    Session storage requires every value to be JSON-serializable.
    """
    if hit is None:
        return {}

    if isinstance(hit, dict):
        # Already a dict — just clean up
        return {
            "file_id": str(hit.get("file_id") or ""),
            "file_unique_id": hit.get("file_unique_id"),
            "file_name": hit.get("file_name") or "",
            "file_size": int(hit.get("file_size") or 0),
            "title": hit.get("title") or "",
            "normalized_title": hit.get("normalized_title") or "",
            "year": hit.get("year"),
            "type": hit.get("type") or "movie",
            "quality": hit.get("quality"),
            "codec": hit.get("codec"),
            "audio_languages": list(
                hit.get("audio_languages")
                or hit.get("languages")
                or []
            ),
            "subtitle_languages": list(
                hit.get("subtitle_languages") or []
            ),
            "has_subtitle": bool(hit.get("has_subtitle")),
            "series_title": hit.get("series_title"),
            "season": hit.get("season"),
            "episode": hit.get("episode"),
            "source_channel_id": hit.get("source_channel_id"),
            "source_message_id": hit.get("source_message_id"),
        }

    # FileHit object
    try:
        d = hit.to_dict() if hasattr(hit, "to_dict") else {}
    except Exception:
        d = {}

    if not d:
        # Fallback: read attributes
        d = {
            "file_id": getattr(hit, "file_id", ""),
            "file_unique_id": getattr(hit, "file_unique_id", None),
            "file_name": getattr(hit, "file_name", None),
            "file_size": getattr(hit, "file_size", 0),
            "title": getattr(hit, "title", ""),
            "normalized_title": getattr(hit, "normalized_title", ""),
            "year": getattr(hit, "year", None),
            "type": getattr(hit, "type", "movie"),
            "quality": getattr(hit, "quality", None),
            "codec": getattr(hit, "codec", None),
            "audio_languages": list(
                getattr(hit, "audio_languages", []) or []
            ),
            "subtitle_languages": list(
                getattr(hit, "subtitle_languages", []) or []
            ),
            "has_subtitle": bool(getattr(hit, "has_subtitle", False)),
            "series_title": getattr(hit, "series_title", None),
            "season": getattr(hit, "season", None),
            "episode": getattr(hit, "episode", None),
            "source_channel_id": getattr(hit, "source_channel_id", None),
            "source_message_id": getattr(hit, "source_message_id", None),
        }

    # Ensure all fields present
    return {
        "file_id": str(d.get("file_id") or ""),
        "file_unique_id": d.get("file_unique_id"),
        "file_name": d.get("file_name") or "",
        "file_size": int(d.get("file_size") or 0),
        "title": d.get("title") or "",
        "normalized_title": d.get("normalized_title") or "",
        "year": d.get("year"),
        "type": d.get("type") or "movie",
        "quality": d.get("quality"),
        "codec": d.get("codec"),
        "audio_languages": list(
            d.get("audio_languages") or d.get("languages") or []
        ),
        "subtitle_languages": list(d.get("subtitle_languages") or []),
        "has_subtitle": bool(d.get("has_subtitle")),
        "series_title": d.get("series_title"),
        "season": d.get("season"),
        "episode": d.get("episode"),
        "source_channel_id": d.get("source_channel_id"),
        "source_message_id": d.get("source_message_id"),
    }


# ============================================================
# SECTION 2 — QUICK SEARCH (cache-first)
# ============================================================

async def quick_search(
    query: str,
    year: Optional[int] = None,
    is_series: bool = False,
    kind: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], bool]:
    """
    Cache-first DB search.

    Returns:
        (hits, complete)
        hits     — list of dicts (see to_dict)
        complete — True if all shards responded, False on partial failure
    """
    try:
        from media_search.normalizer import parse_query

        norm, parsed_year, parsed_series = parse_query(query)
        use_year = year if year is not None else parsed_year
        requested_kind = (
            kind if kind in ("movie", "series", "any") else None
        )
        use_series = (
            requested_kind == "series"
            if requested_kind is not None
            else is_series or parsed_series
        )

        if not norm:
            return [], True

        # ── Cache lookup ──
        cache_key: Optional[str] = None
        try:
            from media_search import instant_cache as IC
            cache_kind = requested_kind or (
                "series" if use_series else "default"
            )
            cache_key = IC.build_key(norm, use_year, cache_kind)
            cached = IC.get(cache_key)
            if cached is not None:
                if cached.get("complete", True):
                    return list(cached.get("hits") or []), True
        except Exception as e:
            logger.debug(f"[GROUPS-SEARCH] cache: {e}")

        # ── Engine search ──
        from media_search import engine as _eng_mod
        engine = getattr(_eng_mod, "engine", None)
        if engine is None:
            logger.warning("[GROUPS-SEARCH] engine missing")
            return [], False

        result = None
        try:
            if requested_kind == "movie":
                result = await engine.search_movie(norm, year=use_year)
            elif requested_kind == "series" or (
                requested_kind is None and use_series
            ):
                result = await engine.search_series(norm, year=use_year)
            elif requested_kind == "any":
                result = await engine.search_any(norm, year=use_year)
            else:
                r_movie = await engine.search_movie(norm, year=use_year)
                if r_movie and r_movie.hits:
                    result = r_movie
                else:
                    result = await engine.search_series(norm, year=use_year)

                if not (result and result.hits):
                    result = await engine.search_any(norm, year=use_year)
        except Exception as e:
            logger.exception(f"[GROUPS-SEARCH] engine: {e}")
            return [], False

        if result is None:
            return [], True

        raw_hits = list(result.hits or [])
        complete = bool(getattr(result, "complete", True))

        hits = [to_dict(h) for h in raw_hits]
        hits = [h for h in hits if h.get("file_id")]

        # ── Cache store ──
        if cache_key and hits and complete:
            try:
                from media_search import instant_cache as IC
                IC.set(cache_key, {
                    "hits": hits,
                    "complete": complete,
                })
            except Exception:
                pass

        return hits, complete

    except Exception as e:
        logger.exception(f"[GROUPS-SEARCH] quick_search: {e}")
        return [], False


# ============================================================
# SECTION 3 — EXACT-TITLE SEARCH
# ============================================================

async def search_by_title(
    title: str,
    year: Optional[int] = None,
    kind: str = "movie",
) -> List[Dict[str, Any]]:
    """
    Exact search when user picked a specific suggestion.
    Tries with year first, then without.

    kind: "movie" | "series" | "any"
    """
    if not title:
        return []

    is_series = kind == "series"

    hits, _ = await quick_search(
        title,
        year=year,
        is_series=is_series,
        kind=kind if kind in ("movie", "series", "any") else None,
    )

    # Fallback: retry without year
    if not hits and year is not None:
        hits, _ = await quick_search(
            title,
            year=None,
            is_series=is_series,
            kind=kind if kind in ("movie", "series", "any") else None,
        )

    return hits


# ============================================================
# SECTION 4 — SORT
# ============================================================

_SORT_MODES = ("small_to_big", "big_to_small")


def sort_hits(
    hits: List[Dict[str, Any]],
    mode: str = "small_to_big",
) -> List[Dict[str, Any]]:
    """Sort by file_size."""
    if not hits:
        return []

    reverse = mode == "big_to_small"
    try:
        return sorted(
            hits,
            key=lambda h: int(h.get("file_size") or 0),
            reverse=reverse,
        )
    except Exception:
        return list(hits)



# ============================================================
# SECTION 5 — FILTERS
# ============================================================

def _to_int_safe(v: Any) -> Optional[int]:
    """Convert v to int safely. None on failure."""
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def filter_by_kind(
    hits: List[Dict[str, Any]],
    kind: str,
) -> List[Dict[str, Any]]:
    """kind: movie | series | any"""
    if kind == "movie":
        return [h for h in hits if not _is_series(h)]
    if kind == "series":
        return [h for h in hits if _is_series(h)]
    return list(hits)


def _is_series(h: Dict[str, Any]) -> bool:
    if h.get("type") == "series":
        return True
    if h.get("season") is not None and h.get("episode") is not None:
        return True
    return False


def filter_by_language(
    hits: List[Dict[str, Any]],
    language: str,
) -> List[Dict[str, Any]]:
    if not language:
        return list(hits)
    ll = language.lower()
    out: List[Dict[str, Any]] = []
    for h in hits:
        langs = [str(x).lower() for x in
                 (h.get("audio_languages") or [])]
        if not langs or any(ll in l or l in ll for l in langs):
            out.append(h)
    return out

def filter_by_season(
    hits: List[Dict[str, Any]],
    season: int,
) -> List[Dict[str, Any]]:
    target = _to_int_safe(season)
    if target is None:
        return list(hits)
    out: List[Dict[str, Any]] = []
    for h in hits:
        if _to_int_safe(h.get("season")) == target:
            out.append(h)
    return out


def filter_by_episode(
    hits: List[Dict[str, Any]],
    episode: int,
) -> List[Dict[str, Any]]:
    target = _to_int_safe(episode)
    if target is None:
        return list(hits)
    out: List[Dict[str, Any]] = []
    for h in hits:
        if _to_int_safe(h.get("episode")) == target:
            out.append(h)
    return out


def filter_by_quality(
    hits: List[Dict[str, Any]],
    quality: str,
) -> List[Dict[str, Any]]:
    q = (quality or "").upper().strip()
    if not q:
        return list(hits)
    return [
        h for h in hits
        if str(h.get("quality") or "").upper().strip() == q
    ]


# ============================================================
# SECTION 6 — AGGREGATORS
# ============================================================

def unique_qualities(hits: List[Dict[str, Any]]) -> List[str]:
    seen: List[str] = []
    for h in hits:
        q = str(h.get("quality") or "").upper()
        if q and q not in seen:
            seen.append(q)
    # Sort by rank desc
    rank = {
        "2160P": 90, "4K": 90, "UHD": 90,
        "1440P": 80, "2K": 80,
        "1080P": 70, "FHD": 70,
        "720P": 60, "HD": 60,
        "576P": 50,
        "480P": 40, "SD": 40,
        "360P": 30,
    }
    seen.sort(key=lambda x: rank.get(x, 25), reverse=True)
    return seen


def unique_languages(hits: List[Dict[str, Any]]) -> List[str]:
    seen: List[str] = []
    for h in hits:
        for l in (h.get("audio_languages") or []):
            n = str(l).strip().title()
            if n and n not in seen:
                seen.append(n)
    return seen


def unique_seasons(hits: List[Dict[str, Any]]) -> List[int]:
    out: List[int] = []
    for h in hits:
        sn = h.get("season")
        if sn is None:
            continue
        try:
            s = int(sn)
        except (TypeError, ValueError):
            continue
        if s not in out:
            out.append(s)
    return sorted(out)


def unique_episodes(
    hits: List[Dict[str, Any]],
    season: Optional[int] = None,
) -> List[int]:
    out: List[int] = []
    for h in hits:
        if season is not None and h.get("season") != season:
            continue
        ep = h.get("episode")
        if ep is None:
            continue
        try:
            e = int(ep)
        except (TypeError, ValueError):
            continue
        if e not in out:
            out.append(e)
    return sorted(out)


def is_complete(hits: List[Dict[str, Any]]) -> bool:
    return bool(hits)


# ============================================================
# SECTION 7 — PUBLIC EXPORTS
# ============================================================

# ============================================================
# SECTION 7 — COOLDOWN READER
# ============================================================

async def get_cooldown_seconds(
    chat_id: int,
    default: float = 3.0,
) -> float:
    """
    Return the per-group cooldown between searches.

    Reads cfg["search"]["cooldown_seconds"]. Returns `default`
    on any error. Clamps to [0, 300].
    """
    try:
        from plugins.groups import state as GS
        cfg = await GS.get_config(int(chat_id))
        s = cfg.get("search") or {}
        v = s.get("cooldown_seconds", default)
        n = float(v)
        if n < 0:
            return 0.0
        if n > 300:
            return 300.0
        return n
    except Exception:
        return float(default)


# ============================================================
# SECTION 7 — PUBLIC EXPORTS
# ============================================================

__all__ = [
    # Normalize
    "to_dict",
    # Core search
    "quick_search",
    "search_by_title",
    # Sort
    "sort_hits",
    # Filters
    "filter_by_kind",
    "filter_by_language",
    "filter_by_season",
    "filter_by_episode",
    "filter_by_quality",
    # Aggregators
    "unique_qualities",
    "unique_languages",
    "unique_seasons",
    "unique_episodes",
    "is_complete",
    # Cooldown
    "get_cooldown_seconds",
]
