# ============================================================
# 🏨 DOWNTOWN VILLA — AUTO TAGGER
# ============================================================
#
# Guesses extra metadata from filename + record:
#   • genre (best effort from keywords)
#   • decade
#   • language (already parsed but re-derives if missing)
#   • collection/series name (part 1, part 2, etc.)
#
# RULE: NEVER blocks a file. Empty tags are fine.
#
# ============================================================

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ============================================================
# SECTION 1 — PATTERNS
# ============================================================

# Franchise / sequel markers
_SEQUEL_RE = re.compile(
    r"\b(part\s*\d|chapter\s*\d|vol\.?\s*\d|volume\s*\d)\b",
    re.IGNORECASE,
)

# Collections / trilogies (keyword based)
_COLLECTION_KEYWORDS = re.compile(
    r"\b(trilogy|collection|anthology|saga|universe|"
    r"franchise|series\s*collection)\b",
    re.IGNORECASE,
)

# Genre keyword map (best effort)
_GENRE_MAP = {
    "action":     ["action", "adventure", "fight", "war", "battle"],
    "comedy":     ["comedy", "comic", "funny", "humor"],
    "drama":      ["drama", "dramatic"],
    "horror":     ["horror", "scary", "zombie", "haunted"],
    "romance":    ["romance", "love", "romantic"],
    "thriller":   ["thriller", "suspense", "mystery"],
    "sci-fi":     ["sci-fi", "scifi", "science-fiction", "space", "alien"],
    "fantasy":    ["fantasy", "magic", "myth", "fairy"],
    "animation":  ["animated", "animation", "anime", "cartoon"],
    "documentary":["documentary", "doc", "doco"],
    "biography":  ["biography", "biographical", "bio-pic", "biopic"],
    "crime":      ["crime", "heist", "detective", "police"],
    "family":     ["family", "kids", "children"],
    "musical":    ["musical", "music"],
    "western":    ["western", "cowboy"],
}

# Language fallback map (only used if record has none)
_LANG_HINTS = {
    "English":  ["english", "eng", "en"],
    "Hindi":    ["hindi", "hin", "hi"],
    "Tamil":    ["tamil", "tam", "ta"],
    "Telugu":   ["telugu", "tel", "te"],
    "Malayalam":["malayalam", "mal", "ml"],
    "Kannada":  ["kannada", "kan", "kn"],
    "Bengali":  ["bengali", "ben", "bn"],
    "Marathi":  ["marathi", "mar", "mr"],
    "Punjabi":  ["punjabi", "pun", "pa"],
    "Korean":   ["korean", "kor", "ko"],
    "Japanese": ["japanese", "jpn", "ja"],
    "Chinese":  ["chinese", "chi", "zh"],
    "Spanish":  ["spanish", "spa", "es"],
    "French":   ["french", "fre", "fr"],
    "German":   ["german", "ger", "de"],
    "Russian":  ["russian", "rus", "ru"],
    "Arabic":   ["arabic", "ara", "ar"],
    "Turkish":  ["turkish", "tur", "tr"],
    "Thai":     ["thai", "tha", "th"],
}


# ============================================================
# SECTION 2 — PUBLIC TAGGER
# ============================================================

def tag(record: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return a dict of extra tags to merge into the record.

    Fields returned (all optional):
        genre_hint:         str | None
        decade:             int | None  (e.g. 2020)
        collection_marker:  str | None  ("Part 1", "Vol 2")
        is_collection:      bool
        language_hint:      str | None
    """
    out: Dict[str, Any] = {}

    try:
        # Build combined text
        text = _build_text(record)

        # Genre hint
        g = _guess_genre(text)
        if g:
            out["genre_hint"] = g

        # Decade
        year = record.get("year")
        if isinstance(year, int) and year > 0:
            out["decade"] = (year // 10) * 10

        # Collection marker (Part 1, Vol 2, etc.)
        cm = _find_collection_marker(text)
        if cm:
            out["collection_marker"] = cm

        # Is collection / trilogy
        if _COLLECTION_KEYWORDS.search(text):
            out["is_collection"] = True

        # Language hint (only if record has none)
        if not record.get("audio_languages"):
            lh = _guess_language(text)
            if lh:
                out["language_hint"] = lh

    except Exception as e:
        logger.debug(f"[TAGGER] error: {e}")

    return out


def tag_and_merge(record: Dict[str, Any]) -> Dict[str, Any]:
    """Convenience: tag(record) merged back into record (returns new dict)."""
    try:
        tags = tag(record)
        if not tags:
            return record
        merged = dict(record)
        merged.update(tags)
        return merged
    except Exception:
        return record


# ============================================================
# SECTION 3 — HELPERS
# ============================================================

def _build_text(record: Dict[str, Any]) -> str:
    """Combine filename + title + caption for pattern matching."""
    parts = [
        record.get("file_name") or "",
        record.get("title") or "",
        record.get("series_title") or "",
        record.get("caption") or "",
        record.get("normalized_name") or "",
    ]
    return " ".join(str(p) for p in parts if p).lower()


def _guess_genre(text: str) -> Optional[str]:
    """Return the FIRST matching genre keyword."""
    for genre, keywords in _GENRE_MAP.items():
        for kw in keywords:
            if re.search(rf"\b{re.escape(kw)}\b", text):
                return genre
    return None


def _find_collection_marker(text: str) -> Optional[str]:
    """Find 'Part N' / 'Chapter N' / 'Vol N' markers."""
    m = _SEQUEL_RE.search(text)
    if m:
        return m.group(0).title()
    return None


def _guess_language(text: str) -> Optional[str]:
    """Find first language hint in text."""
    for lang, aliases in _LANG_HINTS.items():
        for alias in aliases:
            if re.search(rf"\b{re.escape(alias)}\b", text):
                return lang
    return None


# ============================================================
# SECTION 4 — BATCH HELPER
# ============================================================

def tag_many(records: list) -> List[Dict[str, Any]]:
    """Tag a list of records (returns new list)."""
    out = []
    for r in records:
        try:
            if isinstance(r, dict):
                out.append(tag_and_merge(r))
            else:
                out.append(r)
        except Exception:
            out.append(r)
    return out


def tag_stats(records: list) -> Dict[str, int]:
    """Summary counts for a batch."""
    stats = {"total": 0, "with_genre": 0, "with_decade": 0,
             "with_collection": 0, "with_language": 0}
    for r in records:
        try:
            if not isinstance(r, dict):
                continue
            stats["total"] += 1
            t = tag(r)
            if t.get("genre_hint"):
                stats["with_genre"] += 1
            if t.get("decade"):
                stats["with_decade"] += 1
            if t.get("is_collection"):
                stats["with_collection"] += 1
            if t.get("language_hint"):
                stats["with_language"] += 1
        except Exception:
            continue
    return stats


# ============================================================
# SELF-CHECK
# ============================================================

def _self_check() -> bool:
    ok = True

    t = tag({"file_name": "Inception.2010.1080p.mkv", "year": 2010})
    if t.get("decade") != 2010:
        ok = False

    t = tag({"file_name": "The.Dark.Knight.Trilogy.Part.2.2012.mkv"})
    if not t.get("collection_marker"):
        ok = False
    if not t.get("is_collection"):
        ok = False

    t = tag({"file_name": "Some.Movie.2024.English.mkv"})
    if t.get("language_hint") != "English":
        ok = False

    return ok


try:
    _SELF_CHECK_PASS = _self_check()
except Exception:
    _SELF_CHECK_PASS = False


# ============================================================
# PUBLIC EXPORTS
# ============================================================

__all__ = [
    "tag",
    "tag_and_merge",
    "tag_many",
    "tag_stats",
]
