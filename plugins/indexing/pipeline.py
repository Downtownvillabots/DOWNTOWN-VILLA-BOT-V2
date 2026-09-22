# ============================================================
# 🏨 DOWNTOWN VILLA — INDEXING PIPELINE (self-contained)
# ============================================================
#
# Same pattern as the reference filter-bot:
#
#     media = getattr(message, message.media.value, None)
#     media.file_type = message.media.value
#     media.caption   = message.caption
#     ok, code = await save_file(media)
#
# save_file() is defined right here — no external module needed.
# It writes to db_registry media shards → collection "media_files"
# with the exact schema series_group.search expects.
#
# Returns:
#   saved      → (True, 1)
#   duplicate  → (True, 0)
#   error      → (False, 2)
# ============================================================

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from pyrogram import enums

logger = logging.getLogger(__name__)


_SUPPORTED = (
    enums.MessageMediaType.VIDEO,
    enums.MessageMediaType.AUDIO,
    enums.MessageMediaType.DOCUMENT,
)


# ============================================================
# REGEXES — for inline metadata extraction
# ============================================================

_RE_QUALITY = re.compile(
    r"\b(2160p|1440p|1080p|720p|576p|480p|360p|"
    r"4k|uhd|fhd|hd|bluray|blu-ray|brrip|bdrip|"
    r"web-?dl|webrip|hdrip|dvdrip|dvdscr|camrip|hdtv)\b",
    re.IGNORECASE,
)
_RE_YEAR = re.compile(r"\b(19[3-9]\d|20[0-4]\d)\b")
_RE_SEASON_EP = re.compile(
    r"(?:(?<![A-Za-z])S(\d{1,2})\s*[\s._-]?\s*E(\d{1,3})"
    r"|(?<![A-Za-z])(\d{1,2})x(\d{1,3}))",
    re.IGNORECASE,
)
_RE_EXT = re.compile(
    r"\.(mkv|mp4|avi|mov|wmv|flv|webm|m4v|ts|m2ts|mpg|mpeg)$",
    re.IGNORECASE,
)

_LANGS = {
    "tamil": "Tamil", "tam": "Tamil",
    "malayalam": "Malayalam", "mal": "Malayalam",
    "hindi": "Hindi", "hin": "Hindi",
    "telugu": "Telugu", "tel": "Telugu",
    "kannada": "Kannada", "kan": "Kannada",
    "english": "English", "eng": "English",
    "bengali": "Bengali",
    "marathi": "Marathi",
    "punjabi": "Punjabi",
    "urdu": "Urdu",
    "korean": "Korean",
    "japanese": "Japanese",
    "chinese": "Chinese",
    "spanish": "Spanish",
    "french": "French",
    "german": "German",
    "russian": "Russian",
    "arabic": "Arabic",
    "turkish": "Turkish",
    "thai": "Thai",
}


# ============================================================
# PUBLIC — called by worker.py / auto.py
# ============================================================

async def process_message(
    message,
    mode: str = "auto",
    metadata_source: str = "both",
) -> Dict[str, Any]:
    try:
        mt = getattr(message, "media", None)
        if not mt:
            return {"status": "skipped", "reason": "no media"}

        if mt not in _SUPPORTED:
            return {"status": "skipped", "reason": f"unsupported media: {mt}"}

        media = getattr(message, mt.value, None)
        if not media:
            return {"status": "skipped", "reason": "no media object"}

        # attach the two attrs save_file() reads — exact reference pattern
        try:
            media.file_type = mt.value
        except Exception:
            pass
        try:
            media.caption = getattr(message, "caption", None)
        except Exception:
            pass

        ok, code = await save_file(media, message=message,
                                   metadata_source=metadata_source)

        if ok and code == 1:
            rec = {
                "file_id": getattr(media, "file_id", None),
                "file_name": getattr(media, "file_name", None),
            }
            logger.info(
                f"[PIPELINE] ✅ saved "
                f"file='{rec.get('file_name') or rec.get('file_id')}'"
            )
            return {"status": "saved", "record": rec}

        if ok and code == 0:
            return {"status": "duplicate", "reason": "same file_id"}

        return {"status": "error", "reason": f"save_file code={code}"}

    except Exception as e:
        logger.exception(f"[PIPELINE] crash: {e}")
        return {"status": "error", "reason": str(e)[:200]}


# ============================================================
# SAVE_FILE — the actual writer
# ============================================================

async def save_file(media, message=None, metadata_source="both") -> Tuple[bool, int]:
    """
    Returns:
        (True, 1)  → saved
        (True, 0)  → duplicate
        (False, 2) → error
    """
    try:
        file_id = getattr(media, "file_id", None)
        if not file_id:
            return (False, 2)

        fingerprint = hashlib.md5(str(file_id).encode()).hexdigest()

        # ── build the record ──
        record = _build_record(media, message, fingerprint, metadata_source)

        # ── duplicate check: same _id OR same file_id ──
        from database import db_registry
        entries = list(db_registry.media_entries())
        if not entries:
            logger.error("[PIPELINE] no media shards available")
            return (False, 2)

        for entry in entries:
            try:
                existing = await entry.db["media_files"].find_one(
                    {"$or": [
                        {"_id": fingerprint},
                        {"file_id": file_id},
                    ]},
                    {"_id": 1},
                )
                if existing:
                    return (True, 0)  # duplicate
            except Exception as e:
                logger.debug(f"[PIPELINE] dup check on shard: {e}")

        # ── pick shard by fingerprint (deterministic) ──
        idx = int(fingerprint, 16) % len(entries)
        target = entries[idx]

        # ── upsert (idempotent) ──
        await target.db["media_files"].update_one(
            {"_id": fingerprint},
            {"$set": record},
            upsert=True,
        )

        # ── best-effort bloom ──
        try:
            from services.duplicate import _bloom_add
            _bloom_add(fingerprint)
        except Exception:
            pass

        return (True, 1)

    except Exception as e:
        logger.exception(f"[PIPELINE] save_file: {e}")
        return (False, 2)


# ============================================================
# RECORD BUILDER
# ============================================================

def _build_record(media, message, fingerprint: str,
                  metadata_source: str) -> Dict[str, Any]:
    # raw text — filename + caption merged per chosen source
    fname = str(getattr(media, "file_name", "") or "").strip()
    caption = str(getattr(media, "caption", "") or "").strip()

    if metadata_source == "filename":
        raw = fname
    elif metadata_source == "caption":
        raw = caption or fname
    else:
        raw = " ".join(p for p in (fname, caption) if p).strip()

    parsed = _parse(raw)

    # source info
    chat = getattr(message, "chat", None) if message else None
    source_channel_id = getattr(chat, "id", None) if chat else None
    source_msg_id = getattr(message, "id", None) if message else None

    rec: Dict[str, Any] = {
        "_id": fingerprint,
        "fingerprint": fingerprint,

        # media
        "file_id": getattr(media, "file_id", None),
        "file_unique_id": getattr(media, "file_unique_id", None),
        "file_name": fname,
        "file_size": int(getattr(media, "file_size", 0) or 0),
        "mime_type": getattr(media, "mime_type", None),
        "duration": int(getattr(media, "duration", 0) or 0),
        "file_type": getattr(media, "file_type", None),

        # parsed
        "title": parsed["title"],
        "series_title": parsed["title"] if parsed["type"] == "series" else None,
        "type": parsed["type"],
        "year": parsed["year"],
        "season": parsed["season"],
        "episode": parsed["episode"],
        "quality": parsed["quality"] or "UNKNOWN",
        "audio_languages": parsed["languages"],
        "languages": parsed["languages"],   # alias for search compat

        # provenance
        "source_channel_id": source_channel_id,
        "source_message_id": source_msg_id,
        "caption": caption[:1000],
        "raw_text": raw[:2000],

        # flags
        "indexed_by": "pipeline",
        "created_at": datetime.utcnow(),
    }
    return rec


# ============================================================
# PARSER
# ============================================================

def _parse(text: str) -> Dict[str, Any]:
    out = {
        "title": None,
        "type": "unknown",
        "year": None,
        "season": None,
        "episode": None,
        "quality": None,
        "languages": [],
    }
    if not text:
        return out

    t = _RE_EXT.sub("", str(text))

    # quality
    m = _RE_QUALITY.search(t)
    if m:
        out["quality"] = m.group(1).upper()

    # year
    m = _RE_YEAR.search(t)
    if m:
        out["year"] = int(m.group(1))

    # season + episode
    m = _RE_SEASON_EP.search(t)
    if m:
        g = m.groups()
        out["season"] = int(g[0] or g[2])
        out["episode"] = int(g[1] or g[3])
        out["type"] = "series"

    # languages
    out["languages"] = _extract_languages(t)

    # title — strip everything from quality/year/SxxExx onward
    title = t
    cut = None
    for pat in (_RE_QUALITY, _RE_SEASON_EP, _RE_YEAR):
        mm = pat.search(title)
        if mm and (cut is None or mm.start() < cut):
            cut = mm.start()
    if cut is not None:
        title = title[:cut]
    title = re.split(r"[\[\{\(]", title, maxsplit=1)[0]
    title = re.sub(r"[._\-]+", " ", title)
    title = re.sub(r"\s+", " ", title).strip(" -|·")
    out["title"] = title[:200] or None

    # if we still don't know type: has year + title → movie
    if out["type"] == "unknown" and out["title"] and out["year"]:
        out["type"] = "movie"

    return out


def _extract_languages(text: str) -> List[str]:
    found: List[str] = []
    low = text.lower()
    for alias, name in _LANGS.items():
        if len(alias) < 3:
            continue
        if re.search(rf"\b{re.escape(alias)}\b", low):
            if name not in found:
                found.append(name)
    return found


__all__ = ["process_message", "save_file"]
