# ============================================================
# 🏨 DOWNTOWN VILLA — PM SEARCH ENRICH (TMDB + clean)
# ============================================================

from __future__ import annotations
import logging, re, time
from typing import Any, Dict, List, Optional

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
    r"\[(?:yts|yify|psa|rarbg|nf|amzn|hmax|pcok|dsnp)[^\]]*\]|"
    r"x264|x265|h\.?264|h\.?265|hevc|avc|aac|ac3|dts|"
    r"\d{1,2}bit|10bit|8bit|hdr|sdr|"
    r"web-?dl|webrip|bluray|blu-ray|brrip|bdrip|hdrip|dvdrip|"
    r"camrip|hdtv|dvdscr|esub|esubs|subs|sub|"
    r"proper|repack|extended|remastered|unrated|imax"
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
# SUGGESTIONS
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

    try:
        from providers import tmdb_provider as TP
        movies = await TP.search_movie(query)
        tv = await TP.search_tv(query)
    except Exception as e:
        logger.debug(f"[SUGG] search: {e}")
        return []

    raw = list(movies or []) + list(tv or [])

    try:
        from rapidfuzz import fuzz
        have_fuzz = True
    except Exception:
        have_fuzz = False

    q_clean = clean_filename(query).lower()
    out: List[Dict[str, Any]] = []
    seen = set()

    for r in raw[:20]:
        title = r.get("title") or ""
        if not title:
            continue
        tkey = title.lower()
        if tkey in seen:
            continue
        seen.add(tkey)

        if have_fuzz:
            score = fuzz.ratio(q_clean, clean_filename(title).lower())
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
        })

    out.sort(key=lambda x: (x["score"], x["rating"]), reverse=True)
    out = [x for x in out if x["score"] >= 55][:limit]
    _cache[key] = (time.time() + CACHE_TTL, out)
    return out


__all__ = ["clean_filename", "enrich", "poster_url", "suggestions"]
