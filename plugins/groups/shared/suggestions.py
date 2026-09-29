# ============================================================
# 🏨 DOWNTOWN VILLA — GROUPS SHARED SUGGESTIONS
# ============================================================
#
# Spell correction + IMDb/TMDB suggestion engine.
# Used when DB has no exact match.
#
# Handles:
#   • Repeated chars        → karrrnnan  → karnan
#   • Missing chars         → karnne     → karnan
#   • Transposed chars      → karnna     → karnan
#   • Word splitting        → brking bad → breaking bad
#   • Word merging          → breakingbad → breaking bad
#   • Common OCR mistakes   → 0↔o, 1↔l, 5↔s
#
# Providers (in order of trust):
#   1. TMDB (movie + TV)     — primary
#   2. OMDB (IMDb)           — if key present
#   3. Local DB titles       — last resort (fuzzy over indexed titles)
#
# Public API:
#   clean_query(raw)                        → normalized string
#   ai_spell_check(text, is_series)         → corrected title | None
#   suggestions(query, year, kind, limit)   → list[dict]
#   to_dict(suggestion)                     → JSON-safe dict
#
# Suggestion dict shape:
#   {
#     "title":       "Karnan",
#     "year":        "2021",
#     "rating":      9.1,
#     "votes":       12500,
#     "kind":        "movie",      # or "series"
#     "tmdb_id":     789456,
#     "imdb_id":     "tt1234567",
#     "poster":      "/abc.jpg",
#     "overview":    "short plot...",
#     "score":       92.5,
#     "source":      "tmdb" | "imdb" | "db",
#   }
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


# Regex patterns
_RE_EXT = re.compile(
    r"\.(mkv|mp4|avi|mov|wmv|flv|webm|m4v|ts|m2ts|mpg|mpeg)$",
    re.IGNORECASE,
)
_RE_BRACKETS = re.compile(r"[\[\{\(][^\]\}\)]*[\]\}\)]")
_RE_NON_WORD = re.compile(r"[^\w\s]+")
_RE_SPACES = re.compile(r"\s+")

# Junk tokens to strip
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


# Common substitutions to normalize BEFORE fuzzy compare
_OCR_MAP = str.maketrans({
    "0": "o",
    "1": "l",
    "3": "e",
    "4": "a",
    "5": "s",
    "7": "t",
    "8": "b",
    "9": "g",
    "$": "s",
    "@": "a",
})


# ============================================================
# SECTION 2 — CACHING
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
# SECTION 3 — QUERY CLEANING
# ============================================================

def clean_query(raw: str) -> str:
    """
    Strip extension, brackets, junk tokens, punctuation.
    Returns a lowercase, space-collapsed string.
    """
    if not raw:
        return ""
    try:
        t = str(raw).strip()

        # Remove extension
        t = _RE_EXT.sub("", t)

        # Remove bracketed groups
        t = _RE_BRACKETS.sub(" ", t)

        # Remove junk tokens
        t = _RE_JUNK.sub(" ", t)

        # Replace separators with spaces
        t = t.replace(".", " ").replace("_", " ").replace("-", " ")

        # Strip non-word (keep spaces)
        t = _RE_NON_WORD.sub(" ", t)

        # Collapse whitespace
        t = _RE_SPACES.sub(" ", t).strip().lower()

        return t
    except Exception:
        return str(raw).strip().lower()


def _collapse_repeats(s: str) -> str:
    """
    Collapse 3+ same letters to 1, keep 2-letter pairs (e.g. "oo" in "book").
    karrrnnan → karnan
    """
    if not s:
        return ""
    return re.sub(r"(.)\1{2,}", r"\1", s)


def _apply_ocr_map(s: str) -> str:
    """0→o, 1→l, etc."""
    if not s:
        return ""
    return s.translate(_OCR_MAP)


def _tokens(s: str) -> List[str]:
    if not s:
        return []
    return [w for w in s.split() if len(w) >= 2]


# ============================================================
# SECTION 4 — FUZZY SCORING
# ============================================================

def _score_pair(query: str, candidate: str) -> float:
    """
    Return 0-100 score. Tries multiple rapidfuzz scorers,
    picks the highest.
    """
    if not query or not candidate:
        return 0.0

    q = query.lower().strip()
    c = candidate.lower().strip()

    if not q or not c:
        return 0.0

    # Exact match
    if q == c:
        return 100.0

    try:
        from rapidfuzz import fuzz
    except Exception:
        # Fallback: simple ratio
        return _simple_ratio(q, c) * 100

    # Multiple scorers — best wins
    try:
        scores = [
            fuzz.ratio(q, c),           # strict
            fuzz.partial_ratio(q, c),   # substring
            fuzz.token_sort_ratio(q, c),# word order independent
            fuzz.token_set_ratio(q, c), # word set
            fuzz.WRatio(q, c),          # weighted
        ]
        return float(max(scores))
    except Exception:
        return _simple_ratio(q, c) * 100


def _simple_ratio(a: str, b: str) -> float:
    """Fallback ratio when rapidfuzz is missing."""
    if not a or not b:
        return 0.0
    la, lb = len(a), len(b)
    if la == 0 or lb == 0:
        return 0.0
    # Simple LCS length
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
    """
    Score with multiple query variants to catch:
      - repeated chars (karrrnnan)
      - OCR noise
      - no-space joining (breakingbad)
    """
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
# SECTION 5 — PROVIDERS
# ============================================================

async def _tmdb_search(query: str) -> List[Dict[str, Any]]:
    """Fetch movie + TV results from TMDB."""
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
            "original_title": r.get("original_title") or "",
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
            "original_title": r.get("original_title") or "",
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


async def _omdb_search(query: str) -> List[Dict[str, Any]]:
    """Fetch from OMDb (IMDb) if module + API key exist."""
    try:
        from providers import omdb_provider as OP  # type: ignore
    except Exception:
        return []

    try:
        results = await OP.search(query)  # type: ignore
    except Exception as e:
        logger.debug(f"[SUGG] omdb: {e}")
        return []

    out: List[Dict[str, Any]] = []
    for r in (results or []):
        title = r.get("title") or r.get("Title")
        if not title:
            continue
        rating_raw = str(r.get("rating") or r.get("imdbRating") or "0")
        try:
            rating = float(rating_raw.replace("N/A", "0") or 0)
        except (TypeError, ValueError):
            rating = 0.0

        year_raw = str(r.get("year") or r.get("Year") or "")
        year = re.sub(r"\D", "", year_raw)[:4]

        out.append({
            "title": title,
            "original_title": title,
            "year": year,
            "rating": rating,
            "votes": 0,
            "kind": "movie",
            "poster": r.get("poster") or r.get("Poster"),
            "overview": (r.get("overview") or r.get("Plot") or "")[:200],
            "tmdb_id": None,
            "imdb_id": r.get("imdb_id") or r.get("imdbID"),
            "source": "imdb",
        })
    return out


# ============================================================
# SECTION 6 — LOCAL DB FUZZY FALLBACK
# ============================================================

_db_titles_cache: List[Tuple[str, str]] = []
_db_cache_at: float = 0.0
_DB_CACHE_TTL = 300.0


async def _load_db_titles() -> List[Tuple[str, str]]:
    global _db_titles_cache, _db_cache_at
    now = time.time()
    if _db_titles_cache and (now - _db_cache_at) < _DB_CACHE_TTL:
        return _db_titles_cache

    try:
        from database import db_registry
    except Exception:
        return _db_titles_cache

    titles: Set[Tuple[str, str]] = set()
    for entry in db_registry.media_entries():
        if not entry.online:
            continue
        try:
            cursor = entry.db["media_files"].find(
                {"title": {"$exists": True, "$ne": ""}},
                {"title": 1, "year": 1, "type": 1, "_id": 0},
            ).limit(2000)
            async for doc in cursor:
                t = doc.get("title")
                y = doc.get("year")
                if t:
                    titles.add((
                        str(t).strip(),
                        str(y) if y else "",
                    ))
        except Exception:
            continue

    _db_titles_cache = list(titles)
    _db_cache_at = now
    logger.debug(f"[SUGG] loaded {len(_db_titles_cache)} DB titles")
    return _db_titles_cache


async def _db_fuzzy(query: str, limit: int = 6, min_score: float = 60.0) -> List[Dict[str, Any]]:
    if not query:
        return []

    titles = await _load_db_titles()
    if not titles:
        return []

    q_clean = _collapse_repeats(clean_query(query))
    if not q_clean or len(q_clean) < 3:
        return []

    # Dedupe by clean title
    lookup: Dict[str, Tuple[str, str]] = {}
    for t, y in titles:
        c = clean_query(t)
        if c and c not in lookup:
            lookup[c] = (t, y)

    scored: List[Tuple[float, str, str]] = []
    for c_clean, (orig, year) in lookup.items():
        score = _fuzzy_score_variants(q_clean, c_clean)
        if score >= min_score:
            scored.append((score, orig, year))

    scored.sort(key=lambda x: x[0], reverse=True)

    out: List[Dict[str, Any]] = []
    seen: Set[str] = set()
    for score, title, year in scored[:limit]:
        key = title.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append({
            "title": title,
            "original_title": title,
            "year": year,
            "rating": 0.0,
            "votes": 0,
            "kind": "movie",
            "poster": None,
            "overview": "",
            "tmdb_id": None,
            "imdb_id": None,
            "score": round(score, 1),
            "source": "db",
        })
    return out


# ============================================================
# SECTION 7 — SCORING + DEDUP + RANK
# ============================================================

def _dedupe_and_score(
    query: str,
    items: List[Dict[str, Any]],
    min_score: float = 45.0,
    limit: int = 6,
) -> List[Dict[str, Any]]:
    """Score every candidate against query, dedupe, sort, cap."""
    if not items:
        return []

    q_clean = _collapse_repeats(clean_query(query))

    # Group by (title, year) — keep highest-scored
    grouped: Dict[str, Dict[str, Any]] = {}

    for it in items:
        title = it.get("title") or ""
        if not title:
            continue

        t_clean = clean_query(title)
        if not t_clean:
            continue

        # Score
        score = _fuzzy_score_variants(q_clean, t_clean)

        # Bonus: exact year match
        # (no query year here — handled upstream)

        key = f"{t_clean}|{it.get('year') or ''}"
        existing = grouped.get(key)
        if existing is None or score > existing.get("score", 0):
            grouped[key] = {
                **it,
                "score": round(score, 1),
            }

    # Sort by (score, rating, votes)
    ranked = sorted(
        grouped.values(),
        key=lambda x: (
            x.get("score", 0),
            x.get("rating", 0),
            x.get("votes", 0),
        ),
        reverse=True,
    )

    # Filter by min score
    filtered = [x for x in ranked if x.get("score", 0) >= min_score]

    return filtered[:limit]


# ============================================================
# SECTION 8 — PUBLIC: SUGGESTIONS
# ============================================================

async def suggestions(
    query: str,
    year: Optional[int] = None,
    kind: str = "any",
    limit: int = 6,
) -> List[Dict[str, Any]]:
    """
    Main entry — multi-provider fuzzy suggestion engine.
    """
    if not query or len(query.strip()) < 2:
        return []

    key = f"sg:{query.lower()}|{year or ''}|{kind}|{limit}"
    cached = _cache_get(key)
    if cached is not None:
        return list(cached)

    cleaned = clean_query(query)
    if not cleaned:
        return []

    # Aggregation buffer
    buffer: List[Dict[str, Any]] = []

    # ── 1. TMDB with full query ──
    tmdb_full = await _tmdb_search(query)
    buffer.extend(tmdb_full)

    # ── 2. TMDB with collapsed repeats ──
    collapsed = _collapse_repeats(cleaned)
    if collapsed and collapsed != cleaned:
        tmdb_coll = await _tmdb_search(collapsed)
        buffer.extend(tmdb_coll)

    # ── 3. TMDB with progressive shortening ──
    tokens = _tokens(cleaned)
    if len(tokens) > 1:
        for n in range(len(tokens) - 1, 0, -1):
            short = " ".join(tokens[:n])
            if len(short) < 3:
                break
            sub = await _tmdb_search(short)
            if sub:
                buffer.extend(sub)

    # ── 4. TMDB with each token (only if buffer thin) ──
    if len(buffer) < 4:
        for tok in tokens:
            if len(tok) < 4:
                continue
            sub = await _tmdb_search(tok)
            buffer.extend(sub[:3])
            if len(buffer) >= 8:
                break

    # ── 5. OMDb with full query ──
    if len(buffer) < 4:
        omdb = await _omdb_search(query)
        buffer.extend(omdb)
        if not omdb and len(tokens) >= 2:
            short = " ".join(tokens[:2])
            buffer.extend(await _omdb_search(short))

    # ── 6. Score + dedupe ──
    ranked = _dedupe_and_score(
        query, buffer, min_score=45.0, limit=limit * 2,
    )

    # ── 7. DB fuzzy fallback (only if nothing scored well) ──
    if not ranked or ranked[0].get("score", 0) < 60:
        db_hits = await _db_fuzzy(query, limit=limit)
        # Merge: DB entries only fill gaps
        seen_keys = {f"{clean_query(x['title'])}|{x.get('year') or ''}"
                     for x in ranked}
        for d in db_hits:
            k = f"{clean_query(d['title'])}|{d.get('year') or ''}"
            if k not in seen_keys:
                ranked.append(d)
                seen_keys.add(k)

    # ── 8. Sort again after merge ──
    ranked.sort(
        key=lambda x: (
            x.get("score", 0),
            x.get("rating", 0),
            x.get("votes", 0),
        ),
        reverse=True,
    )

    # ── 9. Filter by kind ──
    if kind == "movie":
        ranked = [r for r in ranked if r.get("kind") == "movie"] or ranked
    elif kind == "series":
        ranked = [r for r in ranked if r.get("kind") == "series"] or ranked

    # ── 10. Boost year match ──
    if year:
        y = int(year)
        for r in ranked:
            try:
                if int(str(r.get("year") or 0)) == y:
                    r["score"] = min(100.0, r.get("score", 0) + 5.0)
            except (TypeError, ValueError):
                pass
        ranked.sort(
            key=lambda x: (x.get("score", 0), x.get("rating", 0)),
            reverse=True,
        )

    result = ranked[:limit]
    _cache_set(key, result)
    return result


# ============================================================
# SECTION 9 — PUBLIC: SPELL CHECK
# ============================================================

async def ai_spell_check(
    text: str,
    is_series: bool = False,
) -> Optional[str]:
    """
    Returns corrected title if a confident match exists, else None.
    Confident = top suggestion score ≥ 82 AND different from input.
    """
    if not text:
        return None

    base = clean_query(text)
    if not base or len(base) < 3:
        return None

    kind = "series" if is_series else "any"
    results = await suggestions(text, kind=kind, limit=3)
    if not results:
        return None

    top = results[0]
    score = float(top.get("score", 0))
    corrected_title = str(top.get("title") or "")

    if not corrected_title:
        return None

    # Same as input → not a correction
    if clean_query(corrected_title) == base:
        return None

    # Confident enough?
    if score < 82.0:
        return None

    # Preserve year in corrected title
    year = top.get("year")
    if year:
        return f"{corrected_title} {year}"

    return corrected_title


# ============================================================
# SECTION 10 — OUTPUT NORMALIZER
# ============================================================

def to_dict(s: Dict[str, Any]) -> Dict[str, Any]:
    """Normalize a suggestion dict for JSON storage."""
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
# SECTION 11 — PUBLIC EXPORTS
# ============================================================

__all__ = [
    "clean_query",
    "ai_spell_check",
    "suggestions",
    "to_dict",
    "to_many",
]
