# ============================================================
# 🏨 DOWNTOWN VILLA — GROUPS SHARED SUGGESTIONS (v2)
# ============================================================
#
# Spell correction + IMDb/TMDB suggestion engine.
# Every accuracy setting is now PER-GROUP:
#
#   • Spell check threshold (60-95)      → cfg.flow.spell_check.threshold
#   • Max corrections (1-3)              → cfg.flow.spell_check.max_corrections
#   • Suggestion min score (30-80)       → cfg.flow.suggestions.min_score
#   • Provider (tmdb | imdb | both)      → cfg.flow.suggestions.provider
#   • Show rating/year/icon              → cfg.flow.suggestions.show_*
#
# Handles typos:
#   karrrnnan  → Karnan       (repeat collapse)
#   karnne     → Karnan       (missing letter)
#   kar4nan    → Karnan       (OCR: 4→a)
#   brking bad → Breaking Bad (word split)
#   breakingbad→ Breaking Bad (word merge)
#
# Public API:
#   clean_query(raw)                        → str
#   get_suggestions_for_group(chat_id, query, kind, limit) → list[dict]
#   ai_spell_check_for_group(chat_id, text, is_series) → str | None
#
#   # Low-level (still available for direct use):
#   suggestions(query, year, kind, limit, cfg)  → list[dict]
#   ai_spell_check(text, is_series, cfg)        → str | None
#   to_dict(s) / to_many(list)
#
# ============================================================

from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger(__name__)


# ============================================================
# SECTION 1 — CONSTANTS
# ============================================================

_CACHE_TTL = 3600.0
_cache: Dict[str, Tuple[float, Any]] = {}

# ── Regex ──
_RE_EXT = re.compile(
    r"\.(mkv|mp4|avi|mov|wmv|flv|webm|m4v|ts|m2ts|mpg|mpeg)$",
    re.IGNORECASE,
)
_RE_BRACKETS = re.compile(r"[\[\{\(][^\]\}\)]*[\]\}\)]")
_RE_NON_WORD = re.compile(r"[^\w\s]+")
_RE_SPACES = re.compile(r"\s+")

_RE_JUNK = re.compile(
    r"\b(?:"
    r"www\.[a-z0-9.-]+|t\.me/[a-z0-9_]+|telegram\.me/[a-z0-9_]+|"
    r"@[a-z0-9_]+|"
    r"x264|x265|h\.?264|h\.?265|hevc|avc|av1|"
    r"aac|ac3|dts|ddp|"
    r"\d{1,2}bit|10bit|8bit|hdr|sdr|dolby|atmos|"
    r"web-?dl|webrip|web-?hd|bluray|blu-ray|brrip|bdrip|"
    r"hdrip|dvdrip|dvdscr|camrip|hdtv|"
    r"esub|esubs|subs|sub|dual\s*audio|multi\s*audio|"
    r"proper|repack|extended|remastered|unrated|imax|"
    r"amzn|nf|dsnp|hmax|pcok|yts|yify|psa|rarbg|"
    r"complete|season|series|"
    r"s\d{1,2}|e\d{1,3}|"
    r"s\d{1,2}\s*e\d{1,3}"
    r")\b",
    re.IGNORECASE,
)

# OCR map
_OCR_MAP = str.maketrans({
    "0": "o", "1": "l", "3": "e", "4": "a", "5": "s",
    "7": "t", "8": "b", "9": "g", "$": "s", "@": "a",
})


# ============================================================
# SECTION 2 — DEFAULT CFG (used when caller doesn't pass one)
# ============================================================

_DEFAULT_CFG: Dict[str, Any] = {
    "spell_threshold": 82,
    "max_corrections": 1,
    "min_corrections_score": 80,
    "suggestion_min_score": 45,
    "suggestion_provider": "both",
    "suggestion_count": 6,
    "show_rating": True,
    "show_year": True,
    "show_icon": True,
}


# ============================================================
# SECTION 3 — CACHE
# ============================================================

def _cache_get(key: str) -> Optional[Any]:
    entry = _cache.get(key)
    if not entry:
        return None
    if entry[0] < time.time():
        _cache.pop(key, None)
        return None
    return entry[1]


def _cache_set(key: str, value: Any) -> None:
    _cache[key] = (time.time() + _CACHE_TTL, value)


# ============================================================
# SECTION 4 — QUERY CLEANING
# ============================================================

def clean_query(raw: str) -> str:
    if not raw:
        return ""
    try:
        t = str(raw).strip()
        t = _RE_EXT.sub("", t)
        t = _RE_BRACKETS.sub(" ", t)
        t = _RE_JUNK.sub(" ", t)
        t = t.replace(".", " ").replace("_", " ").replace("-", " ")
        t = _RE_NON_WORD.sub(" ", t)
        t = _RE_SPACES.sub(" ", t).strip().lower()
        return t
    except Exception:
        return str(raw).strip().lower()


def _collapse_repeats(s: str) -> str:
    if not s:
        return ""
    return re.sub(r"(.)\1{2,}", r"\1", s)


def _apply_ocr_map(s: str) -> str:
    if not s:
        return ""
    return s.translate(_OCR_MAP)


def _tokens(s: str) -> List[str]:
    if not s:
        return []
    return [w for w in s.split() if len(w) >= 2]


# ============================================================
# SECTION 5 — FUZZY SCORING
# ============================================================

def _score_pair(query: str, candidate: str) -> float:
    if not query or not candidate:
        return 0.0
    q = query.lower().strip()
    c = candidate.lower().strip()
    if not q or not c:
        return 0.0
    if q == c:
        return 100.0

    try:
        from rapidfuzz import fuzz
        scores = [
            fuzz.ratio(q, c),
            fuzz.partial_ratio(q, c),
            fuzz.token_sort_ratio(q, c),
            fuzz.token_set_ratio(q, c),
            fuzz.WRatio(q, c),
        ]
        return float(max(scores))
    except Exception:
        return _simple_ratio(q, c) * 100


def _simple_ratio(a: str, b: str) -> float:
    if not a or not b:
        return 0.0
    la, lb = len(a), len(b)
    if la == 0 or lb == 0:
        return 0.0
    dp = [[0] * (lb + 1) for _ in range(la + 1)]
    for i in range(la):
        for j in range(lb):
            if a[i] == b[j]:
                dp[i + 1][j + 1] = dp[i][j] + 1
            else:
                dp[i + 1][j + 1] = max(dp[i][j + 1], dp[i + 1][j])
    lcs = dp[la][lb]
    return 2.0 * lcs / (la + lb)


def _fuzzy_score_variants(query: str, candidate: str) -> float:
    if not query or not candidate:
        return 0.0

    q_variants = {
        query,
        _collapse_repeats(query),
        _apply_ocr_map(query),
        _collapse_repeats(_apply_ocr_map(query)),
        query.replace(" ", ""),
        _collapse_repeats(query.replace(" ", "")),
    }

    best = 0.0
    for q in q_variants:
        if not q:
            continue
        s = _score_pair(q, candidate)
        if s > best:
            best = s
    return best


# ============================================================
# SECTION 6 — PROVIDERS
# ============================================================

async def _tmdb_search(query: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    try:
        from providers import tmdb_provider as TP
    except Exception:
        return out

    try:
        movies = await TP.search_movie(query)
    except Exception:
        movies = []
    try:
        tv = await TP.search_tv(query)
    except Exception:
        tv = []

    for r in list(movies or []):
        out.append({
            "title": r.get("title") or "",
            "year": str(r.get("year") or ""),
            "rating": float(r.get("rating") or 0),
            "votes": int(r.get("votes") or 0),
            "kind": "movie",
            "poster": r.get("poster"),
            "overview": (r.get("overview") or "")[:200],
            "tmdb_id": r.get("tmdb_id"),
            "imdb_id": None,
            "source": "tmdb",
        })
    for r in list(tv or []):
        out.append({
            "title": r.get("title") or "",
            "year": str(r.get("year") or ""),
            "rating": float(r.get("rating") or 0),
            "votes": int(r.get("votes") or 0),
            "kind": "series",
            "poster": r.get("poster"),
            "overview": (r.get("overview") or "")[:200],
            "tmdb_id": r.get("tmdb_id"),
            "imdb_id": None,
            "source": "tmdb",
        })
    return out


async def _imdb_search(query: str) -> List[Dict[str, Any]]:
    """
    IMDb search via IMDBKit/cinemagoer (from requirements.txt).
    Only imports if provider modules are installed.
    """
    # Try providers.imdb_provider first
    try:
        from providers import imdb_provider as IP  # type: ignore
        try:
            results = await IP.search(query)  # type: ignore
        except Exception:
            results = []
        out = []
        for r in (results or []):
            t = r.get("title") or r.get("Title")
            if not t:
                continue
            try:
                rating = float(str(r.get("rating") or r.get("imdbRating") or 0)
                               .replace("N/A", "0") or 0)
            except (TypeError, ValueError):
                rating = 0.0
            year_raw = str(r.get("year") or r.get("Year") or "")
            year = re.sub(r"\D", "", year_raw)[:4]
            out.append({
                "title": t,
                "year": year,
                "rating": rating,
                "votes": int(r.get("votes") or 0),
                "kind": r.get("kind") or "movie",
                "poster": r.get("poster") or r.get("Poster"),
                "overview": (r.get("overview") or r.get("Plot") or "")[:200],
                "tmdb_id": None,
                "imdb_id": r.get("imdb_id") or r.get("imdbID"),
                "source": "imdb",
            })
        return out
    except ImportError:
        return []
    except Exception as e:
        logger.debug(f"[SUGG] imdb: {e}")
        return []


async def _db_fuzzy(query: str, limit: int = 6, min_score: float = 60.0) -> List[Dict[str, Any]]:
    if not query:
        return []
    try:
        from database import db_registry
    except Exception:
        return []

    titles: Set[Tuple[str, str]] = set()
    for entry in db_registry.media_entries():
        if not entry.online:
            continue
        try:
            cursor = entry.db["media_files"].find(
                {"title": {"$exists": True, "$ne": ""}},
                {"title": 1, "year": 1, "_id": 0},
            ).limit(2000)
            async for doc in cursor:
                t = doc.get("title")
                y = doc.get("year")
                if t:
                    titles.add((str(t).strip(), str(y) if y else ""))
        except Exception:
            continue

    if not titles:
        return []

    q_clean = _collapse_repeats(clean_query(query))
    if not q_clean or len(q_clean) < 3:
        return []

    lookup: Dict[str, Tuple[str, str]] = {}
    for t, y in titles:
        c = clean_query(t)
        if c and c not in lookup:
            lookup[c] = (t, y)

    scored: List[Tuple[float, str, str]] = []
    for c_clean, (orig, year) in lookup.items():
        s = _fuzzy_score_variants(q_clean, c_clean)
        if s >= min_score:
            scored.append((s, orig, year))

    scored.sort(key=lambda x: x[0], reverse=True)

    out: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for s, title, year in scored[:limit]:
        key = title.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "title": title,
            "year": year,
            "rating": 0.0,
            "votes": 0,
            "kind": "movie",
            "poster": None,
            "overview": "",
            "tmdb_id": None,
            "imdb_id": None,
            "score": round(s, 1),
            "source": "db",
        })
    return out


# ============================================================
# SECTION 7 — SCORE + DEDUPE + RANK
# ============================================================

def _dedupe_and_score(
    query: str,
    items: List[Dict[str, Any]],
    min_score: float = 45.0,
    limit: int = 6,
) -> List[Dict[str, Any]]:
    if not items:
        return []
    q_clean = _collapse_repeats(clean_query(query))

    grouped: Dict[str, Dict[str, Any]] = {}
    for it in items:
        title = it.get("title") or ""
        if not title:
            continue
        t_clean = clean_query(title)
        if not t_clean:
            continue
        score = _fuzzy_score_variants(q_clean, t_clean)
        key = f"{t_clean}|{it.get('year') or ''}"
        existing = grouped.get(key)
        if existing is None or score > existing.get("score", 0):
            grouped[key] = {**it, "score": round(score, 1)}

    ranked = sorted(
        grouped.values(),
        key=lambda x: (
            x.get("score", 0),
            x.get("rating", 0),
            x.get("votes", 0),
        ),
        reverse=True,
    )
    return [x for x in ranked if x.get("score", 0) >= min_score][:limit]


# ============================================================
# SECTION 8 — PUBLIC: SUGGESTIONS (with per-group cfg)
# ============================================================

async def suggestions(
    query: str,
    year: Optional[int] = None,
    kind: str = "any",
    limit: int = 6,
    cfg: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """
    Main entry — accepts per-group cfg.
    cfg keys used:
      min_score          (default 45)
      provider           (tmdb|imdb|both, default both)
    """
    if not query or len(query.strip()) < 2:
        return []

    cfg = cfg or _DEFAULT_CFG
    min_score = int(cfg.get("suggestion_min_score", 45))
    min_score = max(20, min(90, min_score))
    provider = str(cfg.get("suggestion_provider", "both")).lower()
    if provider not in ("tmdb", "imdb", "both"):
        provider = "both"

    key = f"sg:{query.lower()}|{year or ''}|{kind}|{limit}|{min_score}|{provider}"
    cached = _cache_get(key)
    if cached is not None:
        return list(cached)

    cleaned = clean_query(query)
    if not cleaned:
        return []

    buffer: List[Dict[str, Any]] = []

    # ── Provider: TMDB ──
    if provider in ("tmdb", "both"):
        buffer.extend(await _tmdb_search(query))

        collapsed = _collapse_repeats(cleaned)
        if collapsed and collapsed != cleaned:
            buffer.extend(await _tmdb_search(collapsed))

        tokens = _tokens(cleaned)
        if len(tokens) > 1:
            for n in range(len(tokens) - 1, 0, -1):
                short = " ".join(tokens[:n])
                if len(short) < 3:
                    break
                sub = await _tmdb_search(short)
                if sub:
                    buffer.extend(sub)

        if len(buffer) < 4:
            for tok in tokens:
                if len(tok) < 4:
                    continue
                sub = await _tmdb_search(tok)
                buffer.extend(sub[:3])
                if len(buffer) >= 8:
                    break

    # ── Provider: IMDb ──
    if provider in ("imdb", "both") and len(buffer) < 8:
        buffer.extend(await _imdb_search(query))
        tokens = _tokens(cleaned)
        if len(tokens) >= 2:
            short = " ".join(tokens[:2])
            buffer.extend(await _imdb_search(short))

    # ── Score + rank ──
    ranked = _dedupe_and_score(
        query, buffer, min_score=float(min_score), limit=limit * 2,
    )

    # ── DB fuzzy fallback if thin ──
    if not ranked or ranked[0].get("score", 0) < 60:
        db_hits = await _db_fuzzy(query, limit=limit)
        seen = {f"{clean_query(x['title'])}|{x.get('year') or ''}"
                for x in ranked}
        for d in db_hits:
            k = f"{clean_query(d['title'])}|{d.get('year') or ''}"
            if k not in seen:
                ranked.append(d)
                seen.add(k)

    # ── Final sort + kind filter ──
    ranked.sort(
        key=lambda x: (
            x.get("score", 0),
            x.get("rating", 0),
            x.get("votes", 0),
        ),
        reverse=True,
    )

    if kind == "movie":
        ranked = [r for r in ranked if r.get("kind") == "movie"] or ranked
    elif kind == "series":
        ranked = [r for r in ranked if r.get("kind") == "series"] or ranked

    # ── Year boost ──
    if year:
        try:
            y = int(year)
            boost = int(cfg.get("year_boost", 5))
            for r in ranked:
                try:
                    if int(str(r.get("year") or 0)) == y:
                        r["score"] = min(100.0, r.get("score", 0) + boost)
                except (TypeError, ValueError):
                    pass
            ranked.sort(
                key=lambda x: (x.get("score", 0), x.get("rating", 0)),
                reverse=True,
            )
        except (TypeError, ValueError):
            pass

    result = ranked[:limit]
    _cache_set(key, result)
    return result


# ============================================================
# SECTION 9 — PUBLIC: SPELL CHECK (with per-group cfg)
# ============================================================

async def ai_spell_check(
    text: str,
    is_series: bool = False,
    cfg: Optional[Dict[str, Any]] = None,
) -> Optional[str]:
    """
    Return corrected title if confident, else None.
    Uses cfg.spell_threshold (default 82).
    """
    if not text:
        return None

    cfg = cfg or _DEFAULT_CFG
    threshold = int(cfg.get("spell_threshold", 82))
    threshold = max(60, min(95, threshold))

    base = clean_query(text)
    if not base or len(base) < 3:
        return None

    kind = "series" if is_series else "any"
    results = await suggestions(text, kind=kind, limit=3, cfg=cfg)
    if not results:
        return None

    top = results[0]
    score = float(top.get("score", 0))
    corrected_title = str(top.get("title") or "")

    if not corrected_title:
        return None
    if clean_query(corrected_title) == base:
        return None
    if score < threshold:
        return None

    year = top.get("year")
    if year:
        return f"{corrected_title} {year}"
    return corrected_title


# ============================================================
# SECTION 10 — HIGH-LEVEL: READ CFG FROM DB
# ============================================================

async def _load_group_cfg(chat_id: int) -> Dict[str, Any]:
    """Read suggestion-related settings from the group's config."""
    try:
        from plugins.groups import state as GS

        cfg = await GS.get_config(chat_id)
        flow = cfg.get("flow") or {}
        spell = flow.get("spell_check") or {}
        sugg = flow.get("suggestions") or {}

        return {
            "spell_threshold": int(spell.get("threshold", 82)),
            "max_corrections": int(spell.get("max_corrections", 1)),
            "min_corrections_score": 80,
            "suggestion_min_score": int(sugg.get("min_score", 45)),
            "suggestion_provider": str(sugg.get("provider", "both")),
            "suggestion_count": int(sugg.get("max_items", 6)),
            "show_rating": bool(sugg.get("show_rating", True)),
            "show_year": bool(sugg.get("show_year", True)),
            "show_icon": bool(sugg.get("show_icon", True)),
            "year_boost": 5,
        }
    except Exception as e:
        logger.debug(f"[SUGG] load cfg: {e}")
        return dict(_DEFAULT_CFG)


async def get_suggestions_for_group(
    chat_id: int,
    query: str,
    year: Optional[int] = None,
    kind: str = "any",
    limit: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Read group config + return suggestions."""
    cfg = await _load_group_cfg(chat_id)
    use_limit = int(limit or cfg.get("suggestion_count", 6))
    return await suggestions(
        query, year=year, kind=kind, limit=use_limit, cfg=cfg,
    )


async def ai_spell_check_for_group(
    chat_id: int,
    text: str,
    is_series: bool = False,
) -> Optional[str]:
    """Read group config + run spell check."""
    cfg = await _load_group_cfg(chat_id)
    return await ai_spell_check(text, is_series=is_series, cfg=cfg)


async def get_max_corrections_for_group(chat_id: int) -> int:
    cfg = await _load_group_cfg(chat_id)
    return max(1, min(3, int(cfg.get("max_corrections", 1))))


# ============================================================
# SECTION 11 — OUTPUT NORMALIZER
# ============================================================

def to_dict(s: Dict[str, Any]) -> Dict[str, Any]:
    if not s:
        return {}
    return {
        "title": str(s.get("title") or ""),
        "year": str(s.get("year") or ""),
        "rating": float(s.get("rating") or 0),
        "votes": int(s.get("votes") or 0),
        "kind": str(s.get("kind") or "movie"),
        "tmdb_id": s.get("tmdb_id"),
        "imdb_id": s.get("imdb_id"),
        "poster": s.get("poster"),
        "overview": (s.get("overview") or "")[:300],
        "score": float(s.get("score") or 0),
        "source": str(s.get("source") or "tmdb"),
    }


def to_many(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [to_dict(x) for x in (items or []) if x]


# ============================================================
# SECTION 12 — PUBLIC EXPORTS
# ============================================================

__all__ = [
    # Cleaning
    "clean_query",
    # High-level (reads DB config)
    "get_suggestions_for_group",
    "ai_spell_check_for_group",
    "get_max_corrections_for_group",
    # Low-level (with explicit cfg)
    "suggestions",
    "ai_spell_check",
    # Output
    "to_dict",
    "to_many",
    # Defaults
    "_DEFAULT_CFG",
]
