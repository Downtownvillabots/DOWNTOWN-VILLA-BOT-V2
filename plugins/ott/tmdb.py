# ============================================================
# 🏨 DOWNTOWN VILLA — OTT TMDB (multi-strategy fetch)
# ============================================================

from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from core import config
from plugins.ott import database as DB
from plugins.ott.config import PRIORITY_LANGS

logger = logging.getLogger(__name__)

TMDB_BASE = "https://api.themoviedb.org/3"
TMDB_IMG = "https://image.tmdb.org/t/p"

# Indian OTT provider IDs on TMDB
INDIAN_OTTS = "8|9|119|122|220|232|237|2336|237|11|10|15|18"
# 8=Netflix, 9=Prime, 119=Prime (alt), 122=Hotstar, 220=JioCinema,
# 232=ZEE5, 237=SonyLIV, 2336=JioHotstar, 11=Mubi, 10=MX, 15=Hulu,
# 18=Hungama


async def _get(path: str, params: Optional[Dict] = None) -> Optional[Dict]:
    if not config.TMDB_API_KEY:
        return None
    try:
        import aiohttp
    except ImportError:
        return None
    p = dict(params or {})
    p["api_key"] = config.TMDB_API_KEY
    p.setdefault("language", "en-US")
    url = f"{TMDB_BASE}/{path.lstrip('/')}"
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(url, params=p, timeout=20) as r:
                if r.status != 200:
                    return None
                return await r.json()
    except Exception as e:
        logger.debug(f"[OTT-TMDB] {path}: {e}")
        return None


def _mk(item: Dict[str, Any], region: str) -> Optional[Dict[str, Any]]:
    mid = item.get("id")
    if not mid:
        return None
    rd = item.get("release_date") or item.get("primary_release_date") or ""
    try:
        d = datetime.strptime(rd, "%Y-%m-%d").replace(tzinfo=DB.IST) if rd else None
    except Exception:
        d = None
    return {
        "tmdb_id": mid,
        "title": item.get("title") or item.get("original_title") or "",
        "overview": item.get("overview") or "",
        "poster_path": item.get("poster_path"),
        "backdrop_path": item.get("backdrop_path"),
        "release_date": rd,
        "vote_average": item.get("vote_average", 0),
        "vote_count": item.get("vote_count", 0),
        "popularity": item.get("popularity", 0),
        "original_language": item.get("original_language", ""),
        "genre_ids": item.get("genre_ids", []),
        "region": region,
    }


# ═══════════════════════════════════════════════════════════
# MULTI-STRATEGY OTT FETCH BY LANGUAGE
# ═══════════════════════════════════════════════════════════

async def fetch_ott_by_language(
    lang: str,
    region: str = None,
    min_vote: int = 0,
    days_back: int = 60,
    days_fwd: int = 180,
    limit: int = 100,
) -> List[Dict[str, Any]]:
    if region is None:
        cfg = await DB.get_cfg()
        region = cfg.get("region", "IN")

    today = datetime.now(DB.IST).date()
    gte = (today - timedelta(days=days_back)).strftime("%Y-%m-%d")
    lte = (today + timedelta(days=days_fwd)).strftime("%Y-%m-%d")
    today_s = today.strftime("%Y-%m-%d")

    lang_filter = lang if lang and lang != "all" else None

    tasks: List = []

    # ── Strategy 1: by primary_release_date ──
    p1: Dict[str, Any] = {
        "region": region,
        "primary_release_date.gte": gte,
        "primary_release_date.lte": lte,
        "sort_by": "popularity.desc",
        "page": 1,
    }
    if lang_filter:
        p1["with_original_language"] = lang_filter
    if min_vote > 0:
        p1["vote_count.gte"] = int(min_vote)
    tasks.append(_get("discover/movie", p1))

    # ── Strategy 2: digital release type ──
    p2 = dict(p1)
    p2["with_release_type"] = "4"
    p2.pop("primary_release_date.gte", None)
    p2.pop("primary_release_date.lte", None)
    p2["release_date.gte"] = gte
    p2["release_date.lte"] = lte
    tasks.append(_get("discover/movie", p2))

    # ── Strategy 3: watch providers (Indian OTTs) ──
    p3: Dict[str, Any] = {
        "watch_region": region,
        "with_watch_providers": INDIAN_OTTS,
        "sort_by": "popularity.desc",
        "page": 1,
    }
    if lang_filter:
        p3["with_original_language"] = lang_filter
    if min_vote > 0:
        p3["vote_count.gte"] = int(min_vote)
    tasks.append(_get("discover/movie", p3))

    # ── Strategy 4: upcoming only ──
    p4: Dict[str, Any] = {
        "region": region,
        "primary_release_date.gte": today_s,
        "sort_by": "primary_release_date.asc",
        "page": 1,
    }
    if lang_filter:
        p4["with_original_language"] = lang_filter
    tasks.append(_get("discover/movie", p4))

    # ── Strategy 5: recent digital ──
    p5: Dict[str, Any] = {
        "region": region,
        "with_release_type": "4",
        "release_date.gte": (today - timedelta(days=14)).strftime("%Y-%m-%d"),
        "release_date.lte": (today + timedelta(days=14)).strftime("%Y-%m-%d"),
        "sort_by": "release_date.desc",
        "page": 1,
    }
    if lang_filter:
        p5["with_original_language"] = lang_filter
    tasks.append(_get("discover/movie", p5))

    results = await asyncio.gather(*tasks, return_exceptions=True)

    seen: set = set()
    out: List[Dict[str, Any]] = []
    for data in results:
        if not isinstance(data, dict):
            continue
        for item in (data.get("results") or []):
            m = _mk(item, region)
            if not m or m["tmdb_id"] in seen:
                continue
            seen.add(m["tmdb_id"])
            out.append(m)

    # Sort: upcoming first (today → future), then recent
    def sort_key(m):
        rd = m.get("release_date") or "9999-99-99"
        return rd

    out.sort(key=sort_key)
    return out[:limit]


# ═══════════════════════════════════════════════════════════
# WEEKLY (multi-lang, priority)
# ═══════════════════════════════════════════════════════════

async def fetch_weekly_multi_lang(
    region: str = None,
    languages: list = None,
    min_vote: int = 5,
) -> Dict[int, List[Dict[str, Any]]]:
    if region is None:
        cfg = await DB.get_cfg()
        region = cfg.get("region", "IN")
    if languages is None:
        cfg = await DB.get_cfg()
        languages = cfg.get("languages") or []

    all_langs: List[str] = []
    for code in PRIORITY_LANGS + list(languages or []):
        if code and code not in all_langs:
            all_langs.append(code)

    monday, next_mon = DB.week_range()
    gte = monday.strftime("%Y-%m-%d")
    lte = (next_mon - timedelta(days=1)).strftime("%Y-%m-%d")

    tasks = []
    tasks.append(("__world__", _get("discover/movie", {
        "region": region,
        "primary_release_date.gte": gte,
        "primary_release_date.lte": lte,
        "sort_by": "popularity.desc",
        "vote_count.gte": int(min_vote),
        "page": 1,
    })))
    for lang in all_langs:
        tasks.append((lang, _get("discover/movie", {
            "region": region,
            "with_original_language": lang,
            "primary_release_date.gte": gte,
            "primary_release_date.lte": lte,
            "sort_by": "popularity.desc",
            "vote_count.gte": int(min_vote),
            "page": 1,
        })))

    results = await asyncio.gather(
        *[t[1] for t in tasks], return_exceptions=True)

    seen: set = set()
    out: Dict[int, List[Dict[str, Any]]] = {i: [] for i in range(7)}

    for (src, _), data in zip(tasks, results):
        if not isinstance(data, dict):
            continue
        for item in (data.get("results") or []):
            m = _mk(item, region)
            if not m or m["tmdb_id"] in seen:
                continue
            seen.add(m["tmdb_id"])
            rd = m.get("release_date")
            if not rd:
                continue
            try:
                d = datetime.strptime(rd, "%Y-%m-%d")
            except Exception:
                continue
            idx = d.weekday()
            if not 0 <= idx <= 6:
                continue
            try:
                prio = PRIORITY_LANGS.index(m.get("original_language", ""))
            except ValueError:
                prio = 99
            m["_prio"] = prio
            out[idx].append(m)

    for i in range(7):
        out[i].sort(key=lambda m: (m.get("_prio", 99), -m.get("popularity", 0)))
        for m in out[i]:
            m.pop("_prio", None)
    return out


async def fetch_weekly(region: str = None) -> Dict[int, List[Dict[str, Any]]]:
    return await fetch_weekly_multi_lang(region=region)


# ═══════════════════════════════════════════════════════════
# DETAILS / ENRICH
# ═══════════════════════════════════════════════════════════

async def fetch_details(tmdb_id: int) -> Optional[Dict[str, Any]]:
    return await _get(f"movie/{tmdb_id}", {
        "append_to_response": "watch/providers,credits,release_dates",
    })


_GENRE_MAP = {
    28: "Action", 12: "Adventure", 16: "Animation", 35: "Comedy",
    80: "Crime", 99: "Documentary", 18: "Drama", 10751: "Family",
    14: "Fantasy", 36: "History", 27: "Horror", 10402: "Music",
    9648: "Mystery", 10749: "Romance", 878: "Sci-Fi",
    10770: "TV Movie", 53: "Thriller", 10752: "War", 37: "Western",
}


def _extract_provider(details: Dict, region: str) -> str:
    try:
        providers = (details.get("watch/providers") or {}).get("results") or {}
        r = providers.get(region.upper()) or {}
        for key in ("flatrate", "free", "ads", "rent", "buy"):
            lst = r.get(key) or []
            if lst:
                names = [p.get("provider_name") for p in lst[:3] if p.get("provider_name")]
                if names:
                    return ", ".join(names)
    except Exception:
        pass
    return "—"


def _extract_director(details: Dict) -> str:
    try:
        crew = (details.get("credits") or {}).get("crew") or []
        for c in crew:
            if (c.get("job") or "").lower() == "director":
                return c.get("name") or "—"
    except Exception:
        pass
    return "—"


def _extract_cast(details: Dict, limit: int = 3) -> str:
    try:
        cast = (details.get("credits") or {}).get("cast") or []
        names = [c.get("name") for c in cast[:limit] if c.get("name")]
        return ", ".join(names) if names else "—"
    except Exception:
        return "—"


def _extract_release_info(details: Dict, region: str) -> Dict[str, str]:
    out = {"date": "", "type": "", "certification": "", "note": ""}
    try:
        rd = (details.get("release_dates") or {}).get("results") or []
        for r in rd:
            if (r.get("iso_3166_1") or "").upper() != region.upper():
                continue
            dates = r.get("release_dates") or []
            # Prefer digital release
            for d in dates:
                if d.get("type") == 4:
                    out["date"] = (d.get("release_date") or "")[:10]
                    out["type"] = "Digital"
                    out["certification"] = d.get("certification") or ""
                    out["note"] = d.get("note") or ""
                    break
            if not out["date"] and dates:
                first = dates[0]
                out["date"] = (first.get("release_date") or "")[:10]
                type_map = {
                    1: "Premiere", 2: "Limited", 3: "Theatrical",
                    4: "Digital", 5: "Physical", 6: "TV",
                }
                out["type"] = type_map.get(first.get("type"), "")
                out["certification"] = first.get("certification") or ""
            break
    except Exception:
        pass
    return out


async def enrich_movie(movie: Dict[str, Any], region: str = None) -> Dict[str, Any]:
    if region is None:
        cfg = await DB.get_cfg()
        region = cfg.get("region", "IN")

    tmdb_id = movie.get("tmdb_id")
    if not tmdb_id:
        return movie

    cached = await DB.get_movie(tmdb_id)
    if cached and cached.get("overview"):
        return cached

    details = await fetch_details(tmdb_id)
    if not details:
        return movie

    genre_names = ", ".join(
        _GENRE_MAP.get(g.get("id"), "")
        for g in (details.get("genres") or [])
        if _GENRE_MAP.get(g.get("id"))
    )

    enriched = {
        "tmdb_id": tmdb_id,
        "title": details.get("title") or movie.get("title") or "",
        "overview": details.get("overview") or movie.get("overview") or "",
        "poster_path": details.get("poster_path") or movie.get("poster_path"),
        "backdrop_path": details.get("backdrop_path") or movie.get("backdrop_path"),
        "release_date": details.get("release_date") or movie.get("release_date"),
        "vote_average": details.get("vote_average", 0),
        "vote_count": details.get("vote_count", 0),
        "runtime": details.get("runtime", 0),
        "genres": genre_names,
        "original_language": details.get("original_language", ""),
        "director": _extract_director(details),
        "cast": _extract_cast(details),
        "provider": _extract_provider(details, region),
        "region": region,
        "region_release": _extract_release_info(details, region),
    }

    await DB.save_movie(enriched)
    return enriched


def poster_url(path: Optional[str], size: str = "w500") -> Optional[str]:
    if not path:
        return None
    return f"{TMDB_IMG}/{size}{path}"


__all__ = [
    "PRIORITY_LANGS", "INDIAN_OTTS",
    "fetch_weekly", "fetch_weekly_multi_lang",
    "fetch_ott_by_language",
    "fetch_details", "enrich_movie", "poster_url",
]
