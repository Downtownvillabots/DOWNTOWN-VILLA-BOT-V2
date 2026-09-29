# ============================================================
# 🏨 DOWNTOWN VILLA — MISSING SCANNER
# ============================================================
from __future__ import annotations
import asyncio, logging, os, re
from calendar import monthrange
from datetime import timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)
IST = timezone(timedelta(hours=5, minutes=30))
TMDB_BASE = "https://api.themoviedb.org/3"
MAX_PAGES = 15


# ── INDUSTRIES ──
INDUSTRIES = [
    ("hollywood", "🇺🇸 Hollywood",   "en"),
    ("hindi",     "🇮🇳 Hindi",       "hi"),
    ("malayalam", "🇮🇳 Malayalam",   "ml"),
    ("tamil",     "🇮🇳 Tamil",       "ta"),
    ("telugu",    "🇮🇳 Telugu",      "te"),
    ("kannada",   "🇮🇳 Kannada",     "kn"),
    ("bengali",   "🇮🇳 Bengali",     "bn"),
    ("punjabi",   "🇮🇳 Punjabi",     "pa"),
    ("marathi",   "🇮🇳 Marathi",     "mr"),
    ("korean",    "🇰🇷 Korean",      "ko"),
    ("japanese",  "🇯🇵 Japanese",    "ja"),
    ("chinese",   "🇨🇳 Chinese",     "zh"),
    ("spanish",   "🇪🇸 Spanish",     "es"),
    ("turkish",   "🇹🇷 Turkish",     "tr"),
    ("arabic",    "🇸🇦 Arabic",      "ar"),
    ("french",    "🇫🇷 French",      "fr"),
    ("german",    "🇩🇪 German",      "de"),
    ("russian",   "🇷🇺 Russian",     "ru"),
    ("thai",      "🇹🇭 Thai",        "th"),
    ("indonesian","🇮🇩 Indonesian",  "id"),
    ("all",       "🌍 ALL",          "all"),
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
    _, s, e = week
    return f"{year:04d}-{month:02d}-{s:02d}", f"{year:04d}-{month:02d}-{e:02d}"


# ── TMDB ──
async def _tmdb(path: str, params: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    key = os.getenv("TMDB_API_KEY", "").strip()
    if not key:
        logger.warning("[MISS-SCAN] TMDB_API_KEY missing")
        return None
    try:
        import aiohttp
    except ImportError:
        logger.warning("[MISS-SCAN] aiohttp not installed")
        return None
    p = {"api_key": key, "language": "en-US", **params}

    for attempt in range(3):
        try:
            async with aiohttp.ClientSession() as s:
                async with s.get(f"{TMDB_BASE}{path}", params=p, timeout=15) as r:
                    if r.status == 429:
                        await asyncio.sleep(2 + attempt * 2)
                        continue
                    if r.status != 200:
                        logger.debug(f"[MISS-SCAN] tmdb {path} status {r.status}")
                        return None
                    return await r.json()
        except Exception as e:
            logger.debug(f"[MISS-SCAN] tmdb {path} try {attempt+1}: {e}")
            await asyncio.sleep(1 + attempt)
    return None


async def fetch_movies_range(gte: str, lte: str, lang: str,
                             max_pages: int = MAX_PAGES) -> Tuple[List[Dict], int]:
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
        if page >= data.get("total_pages", 1): break
        page += 1
        await asyncio.sleep(0.15)
    return out, raw


async def fetch_series_range(gte: str, lte: str, lang: str,
                             max_pages: int = MAX_PAGES) -> Tuple[List[Dict], int]:
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
        if page >= data.get("total_pages", 1): break
        page += 1
        await asyncio.sleep(0.15)
    return out, raw


# ── LOCAL DB ──
def _get_db():
    try:
        from database import db_manager
        for name in ("get_user_db", "get_system_db", "get_media_db"):
            fn = getattr(db_manager, name, None)
            if callable(fn):
                try:
                    d = fn()
                    if d is not None: return d
                except Exception:
                    pass
        try:
            return db_manager._db
        except Exception:
            pass
    except Exception:
        pass
    try:
        from database import db_registry
        return db_registry.get_system_db()
    except Exception:
        return None


def _files_coll():
    d = _get_db()
    if d is None: return None
    for name in ("media_files", "files", "media"):
        try:
            c = d[name]
            if c is not None: return c
        except Exception: pass
    return None


async def find_local(title: str, year: str = "") -> List[Dict]:
    c = _files_coll()
    if c is None: return []
    try:
        base = re.sub(r"[^\w\s]", " ", title or "").strip()
        base = " ".join(base.split()[:3])
        if not base: return []
        pat = re.compile(re.escape(base), re.IGNORECASE)

        clauses = [{"title": pat}, {"file_name": pat}, {"series_title": pat}]
        query: Dict[str, Any] = {"$or": clauses}
        if year:
            y_int = int(year) if str(year).isdigit() else year
            query = {"$and": [
                {"$or": clauses},
                {"$or": [{"year": str(year)}, {"year": y_int}]},
            ]}
        return await c.find(query).limit(3).to_list(length=3)
    except Exception as e:
        logger.debug(f"[MISS-SCAN] find local: {e}")
        return []


async def find_missing(items: List[Dict]) -> Tuple[List[Dict], List[Dict]]:
    """Return (missing, present)."""
    missing, present = [], []
    for it in items:
        matches = await find_local(it.get("title", ""), it.get("year", ""))
        (present if matches else missing).append(it)
    return missing, present


def dedupe_by_tmdb(items: List[Dict]) -> List[Dict]:
    seen, out = set(), []
    for it in items:
        tid = it.get("tmdb_id")
        if not tid or tid in seen: continue
        seen.add(tid)
        out.append(it)
    return out


__all__ = [
    "INDUSTRIES", "INDUSTRY_MAP", "MONTHS", "MONTHS_FULL",
    "weeks_of_month", "date_range",
    "fetch_movies_range", "fetch_series_range",
    "find_local", "find_missing", "dedupe_by_tmdb",
]
