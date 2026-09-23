# ============================================================
# 🏨 DOWNTOWN VILLA — PM SEARCH ENRICH (TMDB + DB fuzzy)
# ============================================================

from __future__ import annotations
import logging, re, time
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)

_cache: Dict[str, tuple] = {}
CACHE_TTL = 3600.0


# ============================================================
# CLEAN FILENAME
# ============================================================

_JUNK = re.compile(
    r"\b(?:"
    r"www\.[a-z0-9.-]+|t\.me/[a-z0-9_]+|"
    r"telegram\.me/[a-z0-9_]+|@[a-z0-9_]+|"
    r"\[(?:yts|yify|psa|rarbg|nf|amzn|hmax|pcok|dsnp|tinymkv|pahe)[^\]]*\]|"
    r"x264|x265|h\.?264|h\.?265|hevc|avc|aac|ac3|dts|"
    r"\d{1,2}bit|10bit|8bit|hdr|sdr|"
    r"web-?dl|webrip|web-?hd|bluray|blu-ray|brrip|bdrip|hdrip|dvdrip|"
    r"camrip|hdtv|dvdscr|esub|esubs|subs|sub|"
    r"proper|repack|extended|remastered|unrated|imax|"
    r"amzn|nf|dsnp|hmax|pcok"
    r")\b",
    re.IGNORECASE,
)
_BRACKETS = re.compile(r"[\[\{\(][^\]\}\)]*[\]\}\)]")
_EXT = re.compile(
    r"\.(mkv|mp4|avi|mov|wmv|flv|webm|m4v|ts|m2ts|mpg|mpeg)$",
    re.IGNORECASE,
)
_SEP = re.compile(r"[._\-]+")
_SPACE = re.compile(r"\s+")


def clean_filename(name: str) -> str:
    if not name:
        return ""
    t = str(name)
    t = _EXT.sub("", t)
    t = _BRACKETS.sub(" ", t)
    t = _SEP.sub(" ", t)
    t = _JUNK.sub(" ", t)
    t = _SPACE.sub(" ", t).strip(" -_.")
    return t or str(name)


# ============================================================
# ENRICH
# ============================================================

async def enrich(
    title: str,
    year: Optional[int] = None,
) -> Optional[Dict[str, Any]]:
    if not title:
        return None

    key = f"e:{title.lower()}:{year or ''}"
    c = _cache.get(key)
    if c and c[0] > time.time():
        return c[1]

    try:
        from providers import tmdb_provider as TP
        movies = await TP.search_movie(title)
        tv = await TP.search_tv(title)
    except Exception as e:
        logger.debug(f"[ENRICH] search: {e}")
        return None

    candidates = list(movies or []) + list(tv or [])
    if not candidates:
        return None

    chosen = None
    if year:
        for c_ in candidates:
            try:
                if int(str(c_.get("year") or 0)) == int(year):
                    chosen = c_
                    break
            except Exception:
                continue
    if chosen is None:
        chosen = candidates[0]

    out = {
        "title": chosen.get("title") or title,
        "year": str(chosen.get("year") or ""),
        "rating": float(chosen.get("rating") or 0),
        "votes": int(chosen.get("votes") or 0),
        "poster": chosen.get("poster"),
        "overview": (chosen.get("overview") or "")[:400],
        "tmdb_id": chosen.get("tmdb_id"),
        "kind": chosen.get("kind") or "movie",
    }
    _cache[key] = (time.time() + CACHE_TTL, out)
    return out


def poster_url(path: Optional[str], size: str = "w500") -> Optional[str]:
    if not path:
        return None
    return f"https://image.tmdb.org/t/p/{size}{path}"


# ============================================================
# DB TITLE CACHE (for fuzzy fallback)
# ============================================================

_db_titles_cache: List[Tuple[str, str]] = []
_db_titles_at: float = 0.0
DB_TITLES_TTL = 300.0


async def _load_db_titles() -> List[Tuple[str, str]]:
    """
    Return list of (title, year_str) from every media shard.
    Cached 5 min.
    """
    global _db_titles_cache, _db_titles_at
    now = time.time()
    if _db_titles_cache and (now - _db_titles_at) < DB_TITLES_TTL:
        return _db_titles_cache

    try:
        from database import db_registry
    except Exception:
        return _db_titles_cache

    titles: Set[Tuple[str, str]] = set()
    for e in db_registry.media_entries():
        if not e.online:
            continue
        try:
            cursor = e.db["media_files"].find(
                {"title": {"$exists": True, "$ne": ""}},
                {"title": 1, "year": 1, "type": 1, "_id": 0},
            ).limit(3000)
            async for doc in cursor:
                t = doc.get("title")
                y = doc.get("year")
                if t:
                    titles.add((str(t).strip(), str(y) if y else ""))
        except Exception:
            continue

    _db_titles_cache = list(titles)
    _db_titles_at = now
    logger.debug(f"[SUGG] loaded {len(_db_titles_cache)} unique titles")
    return _db_titles_cache


async def _db_fuzzy_suggestions(
    query: str,
    limit: int = 6,
    min_score: float = 60.0,
) -> List[Dict[str, Any]]:
    """
    Fuzzy match the query against every title in the DB.
    Used when TMDB search returns nothing.
    """
    if not query:
        return []

    try:
        from rapidfuzz import process as rf, fuzz
    except Exception:
        return []

    titles = await _load_db_titles()
    if not titles:
        return []

    q_clean = clean_filename(query).lower().strip()
    if not q_clean:
        return []

    # Build lookup: cleaned_title → (original_title, year)
    lookup: Dict[str, Tuple[str, str]] = {}
    for t, y in titles:
        c = clean_filename(t).lower().strip()
        if c and c not in lookup:
            lookup[c] = (t, y)

    if not lookup:
        return []

    choices = list(lookup.keys())

    try:
        results = rf.extract(
            q_clean,
            choices,
            scorer=fuzz.WRatio,
            limit=limit,
        )
    except Exception:
        return []

    out: List[Dict[str, Any]] = []
    for match in results:
        try:
            matched_clean, score, _ = match
        except Exception:
            continue
        if score < min_score:
            continue
        orig, year_str = lookup.get(matched_clean, (matched_clean, ""))
        out.append({
            "title": orig,
            "year": year_str,
            "rating": 0,
            "kind": "movie",
            "poster": None,
            "tmdb_id": None,
            "score": score,
            "source": "db",
        })
    return out


# ============================================================
# SUGGESTIONS (TMDB first, DB fuzzy fallback)
# ============================================================

async def suggestions(
    query: str,
    year: Optional[int] = None,
    limit: int = 6,
) -> List[Dict[str, Any]]:
    if not query:
        return []

    key = f"s:{query.lower()}:{year or ''}:{limit}"
    c = _cache.get(key)
    if c and c[0] > time.time():
        return c[1]

    # ── 1. TMDB ──
    raw: List[Dict[str, Any]] = []
    try:
        from providers import tmdb_provider as TP
        movies = await TP.search_movie(query)
        tv = await TP.search_tv(query)
        raw = list(movies or []) + list(tv or [])
    except Exception as e:
        logger.debug(f"[SUGG] TMDB: {e}")

    try:
        from rapidfuzz import fuzz
        have_fuzz = True
    except Exception:
        have_fuzz = False

    q_clean = clean_filename(query).lower()
    out: List[Dict[str, Any]] = []
    seen: Set[str] = set()

    for r in raw[:20]:
        title = r.get("title") or ""
        if not title:
            continue
        tkey = title.lower()
        if tkey in seen:
            continue
        seen.add(tkey)

        if have_fuzz:
            score = fuzz.WRatio(q_clean, clean_filename(title).lower())
        else:
            score = 100 if q_clean in clean_filename(title).lower() else 50

        out.append({
            "title": title,
            "year": str(r.get("year") or ""),
            "rating": float(r.get("rating") or 0),
            "kind": r.get("kind") or "movie",
            "poster": r.get("poster"),
            "tmdb_id": r.get("tmdb_id"),
            "score": score,
            "source": "tmdb",
        })

    out.sort(key=lambda x: (x["score"], x["rating"]), reverse=True)
    out = [x for x in out if x["score"] >= 55][:limit]

    # ── 2. Fallback: DB fuzzy ──
    if not out:
        logger.info(f"[SUGG] TMDB empty for '{query}' → DB fuzzy fallback")
        try:
            out = await _db_fuzzy_suggestions(query, limit=limit)
        except Exception as e:
            logger.debug(f"[SUGG] db fallback: {e}")

    _cache[key] = (time.time() + CACHE_TTL, out)
    return out


__all__ = [
    "clean_filename",
    "enrich",
    "poster_url",
    "suggestions",
]
