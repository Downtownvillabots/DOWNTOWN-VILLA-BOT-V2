# ============================================================
# 🏨 DOWNTOWN VILLA — AUTO TAGGER
# ============================================================
#
# Guesses genre / decade / collection marker / language hint.
# Never blocks a file. Empty tags are fine.
#
# NOTE ON LANGUAGE HINTS:
#   Only full-word aliases are used — no 2-letter codes and no
#   short 3-letter codes that collide with common English words
#   (ben, mar, pun, spa, etc.). This bot is primarily Tamil +
#   Malayalam, so false language hints would break search.
#
# ============================================================

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_SEQUEL_RE = re.compile(
    r"\b(part\s*\d|chapter\s*\d|vol\.?\s*\d|volume\s*\d)\b",
    re.IGNORECASE,
)
_COLLECTION_KEYWORDS = re.compile(
    r"\b(trilogy|collection|anthology|saga|universe|franchise)\b",
    re.IGNORECASE,
)

_GENRE_MAP = {
    "action":      ["action", "adventure", "fight", "war", "battle"],
    "comedy":      ["comedy", "comic", "funny", "humor"],
    "drama":       ["drama", "dramatic"],
    "horror":      ["horror", "scary", "zombie", "haunted"],
    "romance":     ["romance", "love", "romantic"],
    "thriller":    ["thriller", "suspense", "mystery"],
    "sci-fi":      ["sci-fi", "scifi", "science-fiction", "space", "alien"],
    "fantasy":     ["fantasy", "magic", "myth", "fairy"],
    "animation":   ["animated", "animation", "anime", "cartoon"],
    "documentary": ["documentary", "doc", "doco"],
    "biography":   ["biography", "biographical", "biopic"],
    "crime":       ["crime", "heist", "detective", "police"],
    "family":      ["family", "kids", "children"],
    "musical":     ["musical", "music"],
    "western":     ["western", "cowboy"],
}

# ── Only FULL-WORD, NON-AMBIGUOUS aliases ──
_LANG_HINTS = {
    "English":     ["english"],
    "Hindi":       ["hindi"],
    "Tamil":       ["tamil"],
    "Telugu":      ["telugu"],
    "Malayalam":   ["malayalam"],
    "Kannada":     ["kannada"],
    "Bengali":     ["bengali"],
    "Marathi":     ["marathi"],
    "Punjabi":     ["punjabi"],
    "Urdu":        ["urdu"],
    "Korean":      ["korean"],
    "Japanese":    ["japanese"],
    "Chinese":     ["chinese", "mandarin", "cantonese"],
    "Spanish":     ["spanish", "castellano", "espanol"],
    "French":      ["french", "francais"],
    "German":      ["german", "deutsch"],
    "Russian":     ["russian"],
    "Arabic":      ["arabic"],
    "Turkish":     ["turkish"],
    "Thai":        ["thai"],
    "Italian":     ["italian"],
    "Portuguese":  ["portuguese", "portugues"],
    "Dutch":       ["dutch"],
    "Polish":      ["polish"],
    "Indonesian":  ["indonesian"],
    "Vietnamese":  ["vietnamese"],
    "Filipino":    ["filipino", "tagalog"],
    "Nepali":      ["nepali"],
    "Sinhala":     ["sinhala", "sinhalese"],
    "Assamese":    ["assamese"],
    "Odia":        ["odia", "oriya"],
    "Bhojpuri":    ["bhojpuri"],
}


def tag(record: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    try:
        text = _build_text(record)
        g = _guess_genre(text)
        if g:
            out["genre_hint"] = g
        year = record.get("year")
        if isinstance(year, int) and year > 0:
            out["decade"] = (year // 10) * 10
        cm = _find_collection_marker(text)
        if cm:
            out["collection_marker"] = cm
        if _COLLECTION_KEYWORDS.search(text):
            out["is_collection"] = True
        if not record.get("audio_languages"):
            lh = _guess_language(text)
            if lh:
                out["language_hint"] = lh
    except Exception as e:
        logger.debug(f"[TAGGER] error: {e}")
    return out


def tag_and_merge(record: Dict[str, Any]) -> Dict[str, Any]:
    try:
        tags = tag(record)
        if not tags:
            return record
        merged = dict(record)
        merged.update(tags)
        return merged
    except Exception:
        return record


def _build_text(record: Dict[str, Any]) -> str:
    parts = [
        record.get("file_name") or "",
        record.get("title") or "",
        record.get("series_title") or "",
        record.get("caption") or "",
        record.get("normalized_name") or "",
    ]
    return " ".join(str(p) for p in parts if p).lower()


def _guess_genre(text: str) -> Optional[str]:
    for genre, keywords in _GENRE_MAP.items():
        for kw in keywords:
            if re.search(rf"\b{re.escape(kw)}\b", text):
                return genre
    return None


def _find_collection_marker(text: str) -> Optional[str]:
    m = _SEQUEL_RE.search(text)
    if m:
        return m.group(0).title()
    return None


def _guess_language(text: str) -> Optional[str]:
    """Only full-word aliases — no short codes, no false positives."""
    for lang, aliases in _LANG_HINTS.items():
        for alias in aliases:
            if re.search(rf"\b{re.escape(alias)}\b", text):
                return lang
    return None


def tag_many(records: list) -> List[Dict[str, Any]]:
    out = []
    for r in records:
        try:
            out.append(tag_and_merge(r) if isinstance(r, dict) else r)
        except Exception:
            out.append(r)
    return out


__all__ = ["tag", "tag_and_merge", "tag_many"]
