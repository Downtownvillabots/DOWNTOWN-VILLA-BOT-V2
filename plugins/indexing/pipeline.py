# ============================================================
# 🏨 DOWNTOWN VILLA — INDEXING PIPELINE (fill-first, self-contained)
# ============================================================
#
# Writes to media shards in FILL-FIRST order:
#   DB1 until threshold → DB2 until threshold → DB3 ...
#
# Logs show the ACTUAL MongoDB database label from your env
# (e.g. 'DATA-BASE-01').
#
# Writes search-ready fields:
#   title · normalized_title
#   series_title · normalized_series_title
#   type (never empty) · year · quality · codec · languages
#
# The target shard is selected for each write so threshold crossings
# take effect immediately.
#
# ============================================================

from __future__ import annotations

import logging
import re
from contextvars import ContextVar
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from pyrogram import enums

from core import config

logger = logging.getLogger(__name__)


# ============================================================
# CONSTANTS
# ============================================================

_ALLOWED_MEDIA_TYPES = {
    "document", "video", "audio", "photo",
    "animation", "voice", "video_note", "sticker",
}
_configured_media_types = {
    str(media_type).strip().lower()
    for media_type in config.INDEX_MEDIA_TYPES
    if str(media_type).strip()
}
_invalid_media_types = _configured_media_types - _ALLOWED_MEDIA_TYPES
if _invalid_media_types:
    logger.warning(
        "[PIPELINE] ignoring unsupported INDEX_MEDIA_TYPES: %s",
        ", ".join(sorted(_invalid_media_types)),
    )
_configured_media_types &= _ALLOWED_MEDIA_TYPES
if not _configured_media_types:
    logger.warning(
        "[PIPELINE] INDEX_MEDIA_TYPES has no supported values; "
        "falling back to all supported media types"
    )
    _configured_media_types = set(_ALLOWED_MEDIA_TYPES)

_SUPPORTED = tuple(
    media_type
    for media_type in enums.MessageMediaType
    if media_type.value in _configured_media_types
)
_dedup_mode = str(config.INDEX_DEDUP_MODE or "both").strip().lower()
if _dedup_mode not in {"file_id", "name_size", "both"}:
    logger.warning(
        "[PIPELINE] invalid INDEX_DEDUP_MODE=%r; using both",
        _dedup_mode,
    )
    _dedup_mode = "both"

_SAVE_COMMIT_ERROR: ContextVar[bool] = ContextVar(
    "index_save_commit_error",
    default=False,
)
_SAVE_DUPLICATE_REASON: ContextVar[str] = ContextVar(
    "index_save_duplicate_reason",
    default="",
)
_PAID_MEDIA_TYPES = {"photo", "video", "animation"}

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
    r"(?:(?<![A-Za-z])S(?P<s_season>\d{1,2})\s*[\s._-]?"
    r"E(?P<s_episode>\d{1,3})"
    r"|(?<![A-Za-z])(?P<x_season>\d{1,2})x(?P<x_episode>\d{1,3})"
    r"|\bSeason[\s._-]*(?P<word_season>\d{1,2})"
    r"(?:[\s._-]*Episode[\s._-]*(?P<word_episode>\d{1,3}))?"
    r"|(?<![A-Za-z])S(?P<only_season>\d{1,2})(?![A-Za-z0-9]))",
    re.IGNORECASE,
)
_RE_EXT = re.compile(
    r"\.(mkv|mp4|avi|mov|wmv|flv|webm|m4v|ts|m2ts|mpg|mpeg)$",
    re.IGNORECASE,
)
_RE_SUBTITLE = re.compile(
    r"\b(?:subs?|subtitles?|softsubs?|hardsubs?|esubs?)\b",
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
# NORMALIZER (imported lazily to avoid circular imports)
# ============================================================

def _normalize(text: str) -> str:
    """Lowercase, collapse separators, strip punctuation."""
    try:
        from media_search.normalizer import normalize
        return normalize(text or "")
    except Exception:
        if not text:
            return ""
        t = str(text).lower()
        t = re.sub(r"[.\-_/,;:\\]+", " ", t)
        t = re.sub(r"[^\w\s]+", " ", t)
        t = re.sub(r"\s+", " ", t).strip()
        return t


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
    from database.connection import _pool_config

    entries = list(db_registry.media_entries())
    if not entries:
        raise RuntimeError("no media shards configured")

    threshold = _pool_config("media").threshold_mb

    for entry in entries:
        if not entry.online:
            continue
        used = await _shard_used_mb(entry)
        if used is None:
            continue
        if used < threshold:
            return (entry, entry.db)

    raise RuntimeError(
        f"all online media shards reached the {threshold} MB threshold"
    )


# ============================================================
# PUBLIC — called by worker.py / auto.py
# ============================================================

async def process_message(
    message,
    mode: str = "auto",
    metadata_source: str = "both",
    content_mode: str = "both",
) -> Dict[str, Any]:
    try:
        media_items = extract_media_items(message)
        if not media_items:
            return {"status": "skipped", "reason": "no supported media"}

        results = [
            await _process_media_item(
                message,
                media,
                file_type,
                metadata_source,
                content_mode,
            )
            for media, file_type in media_items
        ]
        if len(results) == 1:
            return results[0]
        return {"status": "multiple", "results": results}

    except Exception as e:
        logger.exception(f"[PIPELINE] crash: {e}")
        return {"status": "error", "reason": str(e)[:200]}


def extract_media_items(message) -> List[Tuple[Any, str]]:
    """Return every indexable attachment, including media inside paid posts."""
    media_type = getattr(message, "media", None)
    if not media_type:
        return []

    if media_type == enums.MessageMediaType.PAID_MEDIA:
        paid_media = getattr(message, "paid_media", None)
        items = getattr(paid_media, "extended_media", None) or []
        return [
            (item, type(item).__name__.lower())
            for item in items
            if (
                type(item).__name__.lower() in _PAID_MEDIA_TYPES
                and type(item).__name__.lower() in _configured_media_types
            )
        ]

    if media_type not in _SUPPORTED:
        return []
    media = getattr(message, media_type.value, None)
    if not media:
        return []
    return [(media, media_type.value)]


async def _process_media_item(
    message,
    media,
    file_type: str,
    metadata_source: str,
    content_mode: str,
) -> Dict[str, Any]:
    file_id = getattr(media, "file_id", None)
    file_unique_id = getattr(media, "file_unique_id", None)
    if not file_id:
        return {"status": "skipped", "reason": "missing file_id"}

    try:
        media.file_type = file_type
        media.caption = getattr(message, "caption", None)
    except Exception:
        pass
    file_name = getattr(media, "file_name", None)
    if not file_name:
        identity = str(file_unique_id or file_id)[:12]
        file_name = f"{file_type}_{identity}"
        try:
            media.file_name = file_name
        except Exception as e:
            logger.warning(
                "[PIPELINE] could not set synthetic file_name "
                "for %s: %s",
                file_type,
                e,
            )
    if not getattr(media, "file_size", 0):
        logger.debug(
            "[PIPELINE] file size unavailable for %s file=%s; storing 0",
            file_type,
            file_name,
        )

    from services.duplicate import file_identity_lock
    async with file_identity_lock(
        str(media.file_id),
        str(file_unique_id or ""),
    ):
        ok, code = await save_file(
            media,
            message=message,
            metadata_source=metadata_source,
            content_mode=content_mode,
        )

    if ok and code == 1:
        from services.duplicate import compute_fingerprint
        record = _build_record(
            media,
            message,
            compute_fingerprint(str(media.file_id)),
            metadata_source,
        )
        return {"status": "saved", "record": record}
    if ok and code == 0:
        return {
            "status": "duplicate",
            "reason": _SAVE_DUPLICATE_REASON.get() or "same file identity",
            "file_name": file_name,
        }
    if ok and code == -1:
        return {"status": "skipped", "reason": "filtered by content mode"}
    return {
        "status": "error",
        "reason": f"save_file code={code}",
        "file_name": file_name,
        "commit_error": _SAVE_COMMIT_ERROR.get(),
    }


# ============================================================
# SAVE_FILE — fill-first writer
# ============================================================

async def save_file(
    media,
    message=None,
    metadata_source: str = "both",
    content_mode: str = "both",
) -> Tuple[bool, int]:
    """
    Returns:
        (True, 1)  → saved
        (True, 0)  → duplicate
        (False, 2) → error
    """
    _SAVE_COMMIT_ERROR.set(False)
    _SAVE_DUPLICATE_REASON.set("")
    try:
        file_id = getattr(media, "file_id", None)
        if not file_id:
            logger.warning("[PIPELINE] save_file skipped: missing file_id")
            return (False, 2)
        file_unique_id = str(getattr(media, "file_unique_id", None) or "")

        from services.duplicate import (
            canonical_file_id,
            compute_fingerprint,
            find_exact_file_id,
        )
        fingerprint = compute_fingerprint(str(file_id))
        if not fingerprint:
            logger.warning("[PIPELINE] failed to compute file_id fingerprint")
            return (False, 2)

        # ── 1. Exact duplicate check across all configured MEDIA shards ──
        try:
            from database import db_registry
            entries = list(db_registry.media_entries())
        except Exception as e:
            logger.warning(f"[PIPELINE] registry error: {e}")
            return (False, 2)

        if not entries:
            logger.warning("[PIPELINE] no media shards configured")
            return (False, 2)

        if _dedup_mode in {"file_id", "both"}:
            try:
                if await find_exact_file_id(
                    str(file_id),
                    entries,
                    file_unique_id,
                ):
                    _SAVE_DUPLICATE_REASON.set("file_id")
                    return (True, 0)
            except Exception as e:
                logger.warning(f"[PIPELINE] file_id duplicate check failed: {e}")
                return (False, 2)

        # ── 2. Pick target shard using current usage (fill-first) ──
        try:
            entry, target_db = await _pick_shard_fill_first()
        except Exception as e:
            logger.warning(f"[PIPELINE] no shard available: {e}")
            return (False, 2)

        shard_label = entry.label
        shard_index = entry.index

        # ── 3. Build record + upsert ──
        record = _build_record(media, message, fingerprint, metadata_source)
        mode = str(content_mode or "both").lower()
        if mode in {"movie", "movies"} and record["type"] != "movie":
            return (True, -1)
        if mode in {"series", "tv"} and record["type"] != "series":
            return (True, -1)
        record["shard_index"] = shard_index
        record["shard_label"] = shard_label
        document_fields = {
            key: value for key, value in record.items() if key != "_id"
        }
        file_name = record["file_name"]
        file_size = record["file_size"]
        if _dedup_mode in {"name_size", "both"}:
            try:
                existing = await target_db["media_files"].find_one(
                    {"file_name": file_name, "file_size": file_size},
                    {"_id": 1},
                )
            except Exception as e:
                logger.warning(
                    "[PIPELINE] name+size duplicate check failed "
                    "file=%r size=%s: %s",
                    file_name,
                    file_size,
                    e,
                )
                return (False, 2)
            if existing:
                _SAVE_DUPLICATE_REASON.set("name+size")
                logger.info("[DUP] name+size %s %s", file_name, file_size)
                return (True, 0)
        document_id = (
            file_unique_id
            or canonical_file_id(str(file_id))
            or str(file_id)
        )

        try:
            await target_db["media_files"].update_one(
                {"_id": document_id},
                {"$set": document_fields},
                upsert=True,
            )
        except Exception as e:
            from pymongo.errors import DuplicateKeyError
            if isinstance(e, DuplicateKeyError):
                if _dedup_mode in {"file_id", "both"}:
                    try:
                        if await find_exact_file_id(
                            str(file_id),
                            entries,
                            file_unique_id,
                        ):
                            _SAVE_DUPLICATE_REASON.set("file_id")
                            return (True, 0)
                    except Exception as check_error:
                        logger.warning(
                            "[PIPELINE] duplicate recheck failed: %s",
                            check_error,
                        )
                _SAVE_COMMIT_ERROR.set(True)
                logger.warning("[PIPELINE] duplicate-key write failed: %s", e)
                return (False, 2)

            # The selected shard failed; re-check all shards and retry.
            logger.warning(
                f"[PIPELINE] write failed, re-picking shard: {e}"
            )
            try:
                if _dedup_mode in {"file_id", "both"}:
                    if await find_exact_file_id(
                        str(file_id),
                        entries,
                        file_unique_id,
                    ):
                        _SAVE_DUPLICATE_REASON.set("file_id")
                        return (True, 0)
                entry, target_db = await _pick_shard_fill_first()
                shard_label = entry.label
                shard_index = entry.index
                document_fields["shard_index"] = shard_index
                document_fields["shard_label"] = shard_label
                await target_db["media_files"].update_one(
                    {"_id": document_id},
                    {"$set": document_fields},
                    upsert=True,
                )
            except Exception as e2:
                from pymongo.errors import DuplicateKeyError
                if (
                    isinstance(e2, DuplicateKeyError)
                    and _dedup_mode in {"file_id", "both"}
                ):
                    try:
                        if await find_exact_file_id(
                            str(file_id),
                            entries,
                            file_unique_id,
                        ):
                            _SAVE_DUPLICATE_REASON.set("file_id")
                            return (True, 0)
                    except Exception as check_error:
                        logger.warning(
                            f"[PIPELINE] duplicate recheck failed: {check_error}"
                        )
                _SAVE_COMMIT_ERROR.set(True)
                logger.warning(f"[PIPELINE] retry save failed: {e2}")
                return (False, 2)

        # ── 4. Best-effort bloom add ──
        try:
            from services.duplicate import _bloom_add
            _bloom_add(fingerprint)
        except Exception:
            pass

        logger.info(
            f"[PIPELINE] ✅ saved to MEDIA DB #{shard_index:02d} "
            f"('{shard_label}') "
            f"file='{str(record.get('file_name', '?'))[:60]}'"
        )
        return (True, 1)

    except Exception as e:
        logger.warning(f"[PIPELINE] save_file failed: {e}")
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
    from services.duplicate import canonical_file_id

    fname = str(getattr(media, "file_name", "") or "").strip()
    if not fname:
        media_type = str(
            getattr(media, "file_type", None)
            or getattr(getattr(message, "media", None), "value", None)
            or "media"
        )
        identity = str(
            getattr(media, "file_unique_id", None)
            or getattr(media, "file_id", "")
        )[:12]
        fname = f"{media_type}_{identity}"

    raw_size = getattr(media, "file_size", 0) or 0
    try:
        file_size = int(raw_size)
    except (TypeError, ValueError):
        file_size = 0
        logger.debug(
            "[PIPELINE] invalid file size %r for %s; storing 0",
            raw_size,
            fname,
        )
    caption = str(
        getattr(media, "caption", None)
        or getattr(message, "caption", "")
        or ""
    ).strip()

    filename_parsed = _parse(fname)
    caption_parsed = _parse(caption)
    source = str(metadata_source or "both").lower()
    if source == "filename":
        parsed = filename_parsed
        raw = fname
    elif source == "caption":
        parsed = caption_parsed if caption else filename_parsed
        raw = caption or fname
    else:
        parsed = _merge_parsed_metadata(filename_parsed, caption_parsed)
        raw = " ".join(p for p in (fname, caption) if p).strip()

    chat = getattr(message, "chat", None) if message else None
    source_channel_id = getattr(chat, "id", None) if chat else None
    source_msg_id = getattr(message, "id", None) if message else None

    title_clean = parsed["title"] or ""
    if not title_clean and fname:
        title_clean = _fallback_title(fname)
    normalized_title = _normalize(title_clean)

    # ── Guarantee type is set ──
    rtype = parsed["type"]
    if rtype not in ("movie", "series"):
        if parsed.get("season") is not None or parsed.get("episode") is not None:
            rtype = "series"
        else:
            rtype = "movie"

    # Series-specific
    is_series = (rtype == "series")
    series_title_val = title_clean if is_series else None
    normalized_series_title = normalized_title if is_series else None

    rec: Dict[str, Any] = {
        "_id": str(
            getattr(media, "file_unique_id", None)
            or canonical_file_id(getattr(media, "file_id", None))
            or getattr(media, "file_id", "")
        ),
        "fingerprint": fingerprint,

        "file_id": getattr(media, "file_id", None),
        "file_unique_id": getattr(media, "file_unique_id", None),
        "file_name": fname,
        "file_size": file_size,
        "mime_type": getattr(media, "mime_type", None),
        "duration": int(getattr(media, "duration", 0) or 0),
        "file_type": (
            getattr(media, "file_type", None)
            or getattr(getattr(message, "media", None), "value", None)
        ),

        # ── Search fields ──
        "title": title_clean,
        "normalized_title": normalized_title,
        "series_title": series_title_val,
        "normalized_series_title": normalized_series_title,
        "type": rtype,

        # ── Metadata ──
        "year": parsed["year"],
        "season": parsed["season"],
        "episode": parsed["episode"],
        "quality": parsed["quality"] or "UNKNOWN",
        "codec": parsed["codec"] or None,
        "audio_languages": parsed["audio_languages"],
        "languages": parsed["audio_languages"],
        "subtitle_languages": parsed["subtitle_languages"],
        "has_subtitle": parsed["has_subtitle"],

        # ── Provenance ──
        "source_channel_id": source_channel_id,
        "source_message_id": source_msg_id,
        "caption": caption[:1000],
        "raw_text": raw[:2000],
        "metadata_source": source,
        "filename_metadata": _metadata_fields(filename_parsed),
        "caption_metadata": _metadata_fields(caption_parsed),

        "indexed_by": "pipeline",
        "created_at": datetime.utcnow(),
    }
    return rec


def _metadata_fields(parsed: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: parsed.get(key)
        for key in (
            "title", "type", "year", "season", "episode", "quality",
            "codec", "audio_languages", "subtitle_languages", "has_subtitle",
        )
    }


def _merge_parsed_metadata(
    filename: Dict[str, Any],
    caption: Dict[str, Any],
) -> Dict[str, Any]:
    """Prefer filename values, filling missing fields from caption metadata."""
    merged: Dict[str, Any] = {}
    for key in ("title", "year", "season", "episode", "quality", "codec"):
        merged[key] = filename.get(key) or caption.get(key)

    types = {filename.get("type"), caption.get("type")}
    if "series" in types:
        merged["type"] = "series"
    elif "movie" in types:
        merged["type"] = "movie"
    else:
        merged["type"] = "unknown"

    for key in ("languages", "audio_languages", "subtitle_languages"):
        merged[key] = list(dict.fromkeys(
            (filename.get(key) or []) + (caption.get(key) or [])
        ))
    merged["has_subtitle"] = bool(
        filename.get("has_subtitle") or caption.get("has_subtitle")
    )
    return merged


def _fallback_title(fname: str) -> str:
    """Best-effort title from a raw filename."""
    try:
        t = _RE_EXT.sub("", str(fname))
        t = re.sub(r"[._\-]+", " ", t)
        t = re.split(r"[\[\{\(]", t, maxsplit=1)[0]
        t = re.sub(r"\s+", " ", t).strip(" -_|·")
        return t[:200]
    except Exception:
        return str(fname)[:200]


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
        "codec": None,
        "languages": [],
        "audio_languages": [],
        "subtitle_languages": [],
        "has_subtitle": False,
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
        groups = m.groupdict()
        season = next(
            (value for key, value in groups.items()
             if key.endswith("season") and value is not None),
            None,
        )
        episode = next(
            (value for key, value in groups.items()
             if key.endswith("episode") and value is not None),
            None,
        )
        out["season"] = int(season) if season is not None else None
        out["episode"] = int(episode) if episode is not None else None
        out["type"] = "series"
    else:
        try:
            from plugins.indexing.classify import classify
            if classify(text=t) == "series":
                out["type"] = "series"
        except Exception as e:
            logger.debug(f"[PIPELINE] series classification failed: {e}")

    out["languages"] = _extract_languages(t)
    out["subtitle_languages"] = _extract_subtitle_languages(t)
    out["audio_languages"] = [
        language for language in out["languages"]
        if language not in out["subtitle_languages"]
    ]
    out["has_subtitle"] = bool(_RE_SUBTITLE.search(t))
    out["codec"] = _extract_codec(t)

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


def _extract_subtitle_languages(text: str) -> List[str]:
    found: List[str] = []
    marker = r"(?:subs?|subtitles?|softsubs?|hardsubs?|esubs?)"
    for alias, name in _LANGS.items():
        if len(alias) < 3:
            continue
        language = re.escape(alias)
        patterns = (
            rf"\b{language}\b[\s._-]*{marker}\b",
            rf"\b{marker}[\s._-]*{language}\b",
        )
        if any(re.search(pattern, text, re.IGNORECASE) for pattern in patterns):
            if name not in found:
                found.append(name)
    return found


_RE_CODEC = re.compile(
    r"\b(hevc|h\.?265|x265|h\.?264|x264|avc|av1|vp9|"
    r"xvid|divx|mpeg-?4|mpeg-?2)\b",
    re.IGNORECASE,
)


def _extract_codec(text: str) -> Optional[str]:
    m = _RE_CODEC.search(text)
    if not m:
        return None
    return m.group(1).upper().replace(".", "").replace("-", "")


__all__ = ["process_message", "save_file"]
