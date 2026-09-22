# ============================================================
# 🏨 DOWNTOWN VILLA — MISSING SCANNER
# ============================================================
#
# Compares TMDB to local DB. Finds gaps.
# New: deduplication, sorting, filtering, per-industry cache.
# ============================================================

from __future__ import annotations
import asyncio, logging, re, time
from calendar import monthrange
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from core import config

logger = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))

TMDB_BASE = "https://api.themoviedb.org/3"

# ── Industries ──
INDUSTRIES = [
    ("hollywood", "🇺🇸 Hollywood", "en"),
    ("hindi",     "🇮🇳 Hindi",     "hi"),
    ("malayalam", "🇮🇳 Malayalam", "ml"),
    ("tamil",     "🇮🇳 Tamil",     "ta"),
    ("telugu",    "🇮🇳 Telugu",    "te"),
    ("kannada",   "🇮🇳 Kannada",   "kn"),
    ("bengali",   "🇮🇳 Bengali",   "bn"),
    ("punjabi",   "🇮🇳 Punjabi",   "pa"),
    ("marathi",   "🇮🇳 Marathi",   "mr"),
    ("korean",    "🇰🇷 Korean",    "ko"),
    ("japanese",  "🇯🇵 Japanese",  "ja"),
    ("chinese",   "🇨🇳 Chinese",   "zh"),
    ("spanish",   "🇪🇸 Spanish",   "es"),
    ("turkish",   "🇹🇷 Turkish",   "tr"),
    ("arabic",    "🇸🇦 Arabic",    "ar"),
    ("french",    "🇫🇷 French",    "fr"),
    ("german",    "🇩🇪 German",    "de"),
    ("russian",   "🇷🇺 Russian",   "ru"),
    ("thai",      "🇹🇭 Thai",      "th"),
    ("indonesian","🇮🇩 Indonesian","id"),
    ("all",       "🌍 ALL",        "all"),
]
INDUSTRY_MAP = {c: (l, lang) for c, l, lang in INDUSTRIES}

MONTHS = ["Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"]
MONTHS_FULL = ["January","February","March","April","May","June",
               "July","August","September","October","November","December"]


# ── WEEK MATH ──
def weeks_of_month(year: int, month: int) -> List[Tuple[int, int, int]]:
    days = monthrange(year, month)[1]
    out, start, wk = [], 1, 1
    while start <= days:
        end = min(start + 6, days)
        out.append((wk, start, end))
        start = end + 1
        wk += 1
    return out


def date_range(year: int, month: int, week=None) -> Tuple[str, str]:
    if week is None:
        last = monthrange(year, month)[1]
        return f"{year:04d}-{month:02d}-01", f"{year:04d}-{month:02d}-{last:02d}"
    _, start, end = week
    return f"{year:04d}-{month:02d}-{start:02d}", f"{year:04d}-{month:02d}-{end:02d}"


# ── TMDB ──
async def _tmdb(path: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if not config.TMDB_API_KEY:
        return None
    try:
        import aiohttp
    except ImportError:
        return None
    p = {"api_key": config.TMDB_API_KEY, "language": "en-US", **params}
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get(f"{TMDB_BASE}{path}", params=p, timeout=15) as r:
                if r.status != 200:
                    return None
                return await r.json()
    except Exception as e:
        logger.debug(f"[MISS-TMDB] {path}: {e}")
        return None


async def fetch_movies_range(gte: str, lte: str, lang: str,
                              max_pages: int = 15) -> Tuple[List[Dict], int]:
    out: List[Dict] = []
    raw = 0
    page = 1
    while page <= max_pages:
        params: Dict[str, Any] = {
            "primary_release_date.gte": gte,
            "primary_release_date.lte": lte,
            "sort_by": "popularity.desc",
            "page": page,
        }
        if lang != "all":
            params["with_original_language"] = lang
            if lang in {"hi","ml","ta","te","kn","bn","pa","mr"}:
                params["region"] = "IN"

        data = await _tmdb("/discover/movie", params)
        if not data: break
        results = data.get("results") or []
        if not results: break
        raw += len(results)
        for r in results:
            out.append({
                "tmdb_id": r.get("id"),
                "title": r.get("title") or r.get("original_title") or "",
                "original_title": r.get("original_title") or "",
                "year": (r.get("release_date") or "")[:4],
                "release_date": r.get("release_date") or "",
                "rating": round(r.get("vote_average", 0) or 0, 1),
                "votes": r.get("vote_count", 0) or 0,
                "popularity": round(r.get("popularity", 0) or 0, 1),
                "lang": r.get("original_language") or "",
            })
        total_pages = data.get("total_pages", 1)
        if page >= total_pages: break
        page += 1
        await asyncio.sleep(0.15)
    return out, raw


async def fetch_series_range(gte: str, lte: str, lang: str,
                              max_pages: int = 15) -> Tuple[List[Dict], int]:
    out: List[Dict] = []
    raw = 0
    page = 1
    while page <= max_pages:
        params: Dict[str, Any] = {
            "first_air_date.gte": gte,
            "first_air_date.lte": lte,
            "sort_by": "popularity.desc",
            "page": page,
        }
        if lang != "all":
            params["with_original_language"] = lang

        data = await _tmdb("/discover/tv", params)
        if not data: break
        results = data.get("results") or []
        if not results: break
        raw += len(results)
        for r in results:
            out.append({
                "tmdb_id": r.get("id"),
                "title": r.get("name") or r.get("original_name") or "",
                "original_title": r.get("original_name") or "",
                "year": (r.get("first_air_date") or "")[:4],
                "release_date": r.get("first_air_date") or "",
                "rating": round(r.get("vote_average", 0) or 0, 1),
                "votes": r.get("vote_count", 0) or 0,
                "popularity": round(r.get("popularity", 0) or 0, 1),
                "lang": r.get("original_language") or "",
            })
        total_pages = data.get("total_pages", 1)
        if page >= total_pages: break
        page += 1
        await asyncio.sleep(0.15)
    return out, raw


# ── LOCAL DB SEARCH ──
async def find_local(title: str, year: str = "") -> List[Dict]:
    try:
        from database import db_registry
    except Exception:
        return []

    base = re.sub(r"[^\w\s]", " ", title or "").strip()
    base = " ".join(base.split()[:3])
    if not base:
        return []
    pat = re.compile(re.escape(base), re.IGNORECASE)

    clauses = [
        {"title": pat}, {"file_name": pat}, {"series_title": pat},
    ]
    query: Dict[str, Any] = {"$or": clauses}
    if year:
        try:
            y_int = int(year)
            query = {"$and": [
                {"$or": clauses},
                {"$or": [{"year": str(year)}, {"year": y_int}]},
            ]}
        except ValueError:
            pass

    out = []
    for entry in db_registry.media_entries():
        if not entry.online: continue
        try:
            cur = entry.db["media_files"].find(query).limit(3)
            docs = await cur.to_list(length=3)
            if docs: return docs
        except Exception:
            continue
    return out


async def find_missing(items: List[Dict]) -> Tuple[List[Dict], int]:
    missing, in_db = [], 0
    for it in items:
        matches = await find_local(it.get("title", ""), it.get("year", ""))
        if matches:
            in_db += 1
        else:
            missing.append(it)
    return missing, in_db


def dedupe_by_tmdb(items: List[Dict]) -> List[Dict]:
    seen, out = set(), []
    for it in items:
        tid = it.get("tmdb_id")
        if not tid or tid in seen: continue
        seen.add(tid)
        out.append(it)
    return out


def group_by_year(items: List[Dict]) -> Dict[str, List[Dict]]:
    out: Dict[str, List[Dict]] = {}
    for it in items:
        y = it.get("year") or "unknown"
        out.setdefault(y, []).append(it)
    return out


__all__ = [
    "INDUSTRIES", "INDUSTRY_MAP", "MONTHS", "MONTHS_FULL",
    "weeks_of_month", "date_range",
    "fetch_movies_range", "fetch_series_range",
    "find_local", "find_missing",
    "dedupe_by_tmdb", "group_by_year",
]
