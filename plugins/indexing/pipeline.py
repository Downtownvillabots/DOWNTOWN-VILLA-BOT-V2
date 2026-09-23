# ============================================================
# 🏨 DOWNTOWN VILLA — INDEXING PIPELINE (fill-first, self-contained)
# ============================================================
#
# Writes to media shards in FILL-FIRST order:
#   DB1 until threshold → DB2 until threshold → DB3 ...
#
# Logs show the ACTUAL MongoDB database label from your env
# (e.g. 'DATA-BASE-01'), not a random hard-coded name.
#
# Cache: current shard cached 30s. On write failure cache is
# invalidated and shard is re-picked.
#
# Returns:
#   saved      → {"status": "saved",     "record": {...}}
#   duplicate  → {"status": "duplicate", "reason": "same file_id"}
#   skipped    → {"status": "skipped",   "reason": "..."}
#   error      → {"status": "error",     "reason": "..."}
# ============================================================

from __future__ import annotations

import hashlib
import logging
import os
import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from pyrogram import enums

logger = logging.getLogger(__name__)


# ============================================================
# CONSTANTS
# ============================================================

_SUPPORTED = (
    enums.MessageMediaType.VIDEO,
    enums.MessageMediaType.AUDIO,
    enums.MessageMediaType.DOCUMENT,
)

SHARD_CACHE_TTL = 30.0

try:
    DEFAULT_THRESHOLD_MB = int(os.getenv("INDEXING_THRESHOLD_MB", "400"))
except (TypeError, ValueError):
    DEFAULT_THRESHOLD_MB = 400
DEFAULT_THRESHOLD_MB = max(50, DEFAULT_THRESHOLD_MB)

_cached_shard: Optional[Tuple[Any, Any]] = None
_cached_shard_at: float = 0.0


# ============================================================
# REGEXES
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
# SHARD PICKER (self-contained fill-first)
# ============================================================

async def _shard_used_mb(entry) -> Optional[float]:
    """Return used storage MB for one shard, or None on error."""
    try:
        stats = await entry.db.command("dbStats")
        used = (stats.get("storageSize", 0) or 0) + (
            stats.get("indexSize", 0) or 0
        )
        return used / (1024 * 1024)
    except Exception as e:
        logger.debug(f"[PIPELINE] dbStats {entry.label}: {e}")
        return None


async def _pick_shard_fill_first() -> Tuple[Any, Any]:
    """
    Return (entry, db) for the FIRST shard whose used MB is
    under INDEXING_THRESHOLD_MB. Never distributes / hashes.
    """
    from database import db_registry

    entries = list(db_registry.media_entries())
    if not entries:
        raise RuntimeError("no media shards configured")

    threshold = DEFAULT_THRESHOLD_MB

    for entry in entries:
        if not entry.online:
            continue
        used = await _shard_used_mb(entry)
        if used is None:
            continue
        if used < threshold:
            return (entry, entry.db)

    # All full → use last online
    for entry in reversed(entries):
        if entry.online:
            logger.warning(
                f"[PIPELINE] all shards over {threshold} MB → "
                f"using last online '{entry.label}'"
            )
            return (entry, entry.db)

    raise RuntimeError("no online media shards")


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

        try:
            media.file_type = mt.value
        except Exception:
            pass
        try:
            media.caption = getattr(message, "caption", None)
        except Exception:
            pass

        ok, code = await save_file(
            media,
            message=message,
            metadata_source=metadata_source,
        )

        if ok and code == 1:
            rec = {
                "file_id": getattr(media, "file_id", None),
                "file_name": getattr(media, "file_name", None),
            }
            return {"status": "saved", "record": rec}

        if ok and code == 0:
            return {"status": "duplicate", "reason": "same file_id"}

        return {"status": "error", "reason": f"save_file code={code}"}

    except Exception as e:
        logger.exception(f"[PIPELINE] crash: {e}")
        return {"status": "error", "reason": str(e)[:200]}


# ============================================================
# SAVE_FILE — fill-first writer
# ============================================================

async def save_file(
    media,
    message=None,
    metadata_source: str = "both",
) -> Tuple[bool, int]:
    """
    Returns:
        (True, 1)  → saved
        (True, 0)  → duplicate
        (False, 2) → error
    """
    global _cached_shard, _cached_shard_at

    try:
        file_id = getattr(media, "file_id", None)
        if not file_id:
            return (False, 2)

        file_unique_id = getattr(media, "file_unique_id", None)
        fingerprint = hashlib.md5(str(file_id).encode()).hexdigest()

        # ── 1. Duplicate check across EVERY online shard ──
        try:
            from database import db_registry
            entries = list(db_registry.media_entries())
        except Exception as e:
            logger.error(f"[PIPELINE] registry error: {e}")
            return (False, 2)

        if not entries:
            logger.error("[PIPELINE] no media shards")
            return (False, 2)

        queries: List[Dict[str, Any]] = [
            {"_id": fingerprint},
            {"fingerprint": fingerprint},
            {"file_id": file_id},
        ]
        if file_unique_id:
            queries.append({"file_unique_id": file_unique_id})

        for entry in entries:
            if not entry.online:
                continue
            for q in queries:
                try:
                    existing = await entry.db["media_files"].find_one(
                        q, {"_id": 1}
                    )
                    if existing:
                        return (True, 0)
                except Exception as e:
                    logger.debug(
                        f"[PIPELINE] dup check '{entry.label}': {e}"
                    )

        # ── 2. Pick target shard (fill-first, cached 30s) ──
        now = time.time()
        if _cached_shard is None or (now - _cached_shard_at) > SHARD_CACHE_TTL:
            try:
                entry, db = await _pick_shard_fill_first()
                _cached_shard = (entry, db)
                _cached_shard_at = now
            except Exception as e:
                logger.error(f"[PIPELINE] no shard available: {e}")
                return (False, 2)

        entry, target_db = _cached_shard
        shard_label = entry.label
        shard_index = entry.index

        # ── 3. Build record + upsert ──
        record = _build_record(media, message, fingerprint, metadata_source)
        record["shard_index"] = shard_index
        record["shard_label"] = shard_label

        try:
            await target_db["media_files"].update_one(
                {"_id": fingerprint},
                {"$set": record},
                upsert=True,
            )
        except Exception as e:
            # Cache stale → force re-pick and retry
            _cached_shard = None
            _cached_shard_at = 0.0
            logger.warning(
                f"[PIPELINE] write failed, re-picking shard: {e}"
            )
            try:
                entry, target_db = await _pick_shard_fill_first()
                _cached_shard = (entry, target_db)
                _cached_shard_at = time.time()
                shard_label = entry.label
                shard_index = entry.index
                record["shard_index"] = shard_index
                record["shard_label"] = shard_label
                await target_db["media_files"].update_one(
                    {"_id": fingerprint},
                    {"$set": record},
                    upsert=True,
                )
            except Exception as e2:
                logger.exception(f"[PIPELINE] retry save failed: {e2}")
                return (False, 2)

        # ── 4. Best-effort bloom add ──
        try:
            from services.duplicate import _bloom_add
            _bloom_add(fingerprint)
        except Exception:
            pass

        logger.info(
            f"[PIPELINE] ✅ saved to '{shard_label}' "
            f"file='{str(record.get('file_name', '?'))[:60]}'"
        )
        return (True, 1)

    except Exception as e:
        logger.exception(f"[PIPELINE] save_file: {e}")
        return (False, 2)


# ============================================================
# RECORD BUILDER
# ============================================================

def _build_record(
    media,
    message,
    fingerprint: str,
    metadata_source: str,
) -> Dict[str, Any]:
    fname = str(getattr(media, "file_name", "") or "").strip()
    caption = str(getattr(media, "caption", "") or "").strip()

    if metadata_source == "filename":
        raw = fname
    elif metadata_source == "caption":
        raw = caption or fname
    else:
        raw = " ".join(p for p in (fname, caption) if p).strip()

    parsed = _parse(raw)

    chat = getattr(message, "chat", None) if message else None
    source_channel_id = getattr(chat, "id", None) if chat else None
    source_msg_id = getattr(message, "id", None) if message else None

    rec: Dict[str, Any] = {
        "_id": fingerprint,
        "fingerprint": fingerprint,

        "file_id": getattr(media, "file_id", None),
        "file_unique_id": getattr(media, "file_unique_id", None),
        "file_name": fname,
        "file_size": int(getattr(media, "file_size", 0) or 0),
        "mime_type": getattr(media, "mime_type", None),
        "duration": int(getattr(media, "duration", 0) or 0),
        "file_type": getattr(media, "file_type", None),

        "title": parsed["title"],
        "series_title": parsed["title"] if parsed["type"] == "series" else None,
        "type": parsed["type"],
        "year": parsed["year"],
        "season": parsed["season"],
        "episode": parsed["episode"],
        "quality": parsed["quality"] or "UNKNOWN",
        "audio_languages": parsed["languages"],
        "languages": parsed["languages"],

        "source_channel_id": source_channel_id,
        "source_message_id": source_msg_id,
        "caption": caption[:1000],
        "raw_text": raw[:2000],

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

    m = _RE_QUALITY.search(t)
    if m:
        out["quality"] = m.group(1).upper()

    m = _RE_YEAR.search(t)
    if m:
        out["year"] = int(m.group(1))

    m = _RE_SEASON_EP.search(t)
    if m:
        g = m.groups()
        out["season"] = int(g[0] or g[2])
        out["episode"] = int(g[1] or g[3])
        out["type"] = "series"

    out["languages"] = _extract_languages(t)

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
