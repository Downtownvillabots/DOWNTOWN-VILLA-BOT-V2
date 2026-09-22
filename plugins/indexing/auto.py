# ============================================================
# 🏨 DOWNTOWN VILLA — AUTO-INDEXING HANDLER
# ============================================================
#
# Runs when new messages arrive in watched channels.
#
# RULE (LOCKED):
#   • Only skip if SAME file_id exists
#   • Everything else is imported silently
#
# Metadata source is read from bot_settings.indexing_default.
#
# ============================================================

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from pyrogram import Client, filters
from pyrogram.errors import FloodWait

from core import config
from utils import format as FM

logger = logging.getLogger(__name__)


STATE: Dict[str, Any] = {
    "enabled": True,
    "processed": 0,
    "saved": 0,
    "duplicate_id": 0,
    "skipped_no_media": 0,
    "skipped_no_file_id": 0,
    "failed": 0,
    "movies": 0,
    "series": 0,
    "last_error": None,
    "last_message_at": 0.0,
    "started_at": time.time(),
}

_recent_msg_ids: Dict[int, float] = {}
_RECENT_TTL = 60.0


# ============================================================
# ENABLE / DISABLE
# ============================================================

async def is_auto_enabled() -> bool:
    try:
        from database import db_registry
        db = db_registry.get_system_db()
        if db is not None:
            doc = await db["bot_settings"].find_one({"_id": "indexing"})
            if doc and "auto_mode" in doc:
                return bool(doc["auto_mode"])
    except Exception:
        pass
    return bool(getattr(config, "AUTO_INDEXING_ENABLED", True))


async def set_auto_enabled(value: bool) -> bool:
    try:
        from database import db_registry
        db = db_registry.get_system_db()
        if db is None:
            return False
        await db["bot_settings"].update_one(
            {"_id": "indexing"},
            {"$set": {"auto_mode": bool(value),
                      "updated_at": datetime.utcnow()}},
            upsert=True,
        )
        STATE["enabled"] = bool(value)
        return True
    except Exception as e:
        logger.warning(f"[AUTO-INDEX] toggle: {e}")
        return False


async def _get_default_metadata_source() -> str:
    try:
        from database import db_registry
        db = db_registry.get_system_db()
        if db is not None:
            doc = await db["bot_settings"].find_one({"_id": "indexing_default"})
            if doc and "metadata_source" in doc:
                return str(doc["metadata_source"])
    except Exception:
        pass
    return "both"


# ============================================================
# CHANNEL FILTER
# ============================================================

def _get_channels() -> List[int]:
    try:
        chans = list(getattr(config, "DATABASE_CHANNEL_IDS", []) or [])
        if chans:
            return [int(c) for c in chans if c]
        single = getattr(config, "DATABASE_CHANNEL_ID", None)
        if single:
            return [int(single)]
    except Exception:
        pass
    return []


def _build_filter():
    chans = _get_channels()
    if not chans:
        return None
    return filters.chat(chans) & ~filters.service


_CHANNEL_FILTER = _build_filter()


# ============================================================
# HANDLER
# ============================================================

if _CHANNEL_FILTER is not None:

    @Client.on_message(_CHANNEL_FILTER, group=-300)
    async def auto_index_handler(client: Client, message):
        try:
            if _is_recent(message):
                return

            enabled = await is_auto_enabled()
            STATE["enabled"] = enabled
            if not enabled:
                return

            if not _has_media(message):
                STATE["skipped_no_media"] += 1
                return

            STATE["processed"] += 1
            STATE["last_message_at"] = time.time()

            await _handle(client, message)

        except FloodWait as e:
            wait = int(getattr(e, "value", 30) or 30)
            logger.warning(f"[AUTO-INDEX] flood {wait}s")
            await asyncio.sleep(wait + 2)
        except Exception as e:
            logger.exception(f"[AUTO-INDEX] handler: {e}")
            STATE["failed"] += 1
            STATE["last_error"] = str(e)[:200]


async def _handle(client: Client, message) -> None:
    try:
        file_id = _extract_file_id(message)
        if not file_id:
            STATE["skipped_no_file_id"] += 1
            return

        if await _is_exact_duplicate(file_id):
            STATE["duplicate_id"] += 1
            return

        metadata_source = await _get_default_metadata_source()

        try:
            from indexing.pipeline import process_message
            result = await process_message(
                message,
                mode="auto",
                metadata_source=metadata_source,
            )
        except Exception as e:
            logger.exception(f"[AUTO-INDEX] pipeline: {e}")
            STATE["failed"] += 1
            STATE["last_error"] = str(e)[:200]
            return

        status = result.get("status")

        if status == "saved":
            STATE["saved"] += 1
            rec = result.get("record") or {}
            rtype = str(rec.get("type") or "").lower()
            if rtype == "movie":
                STATE["movies"] += 1
            elif rtype == "series":
                STATE["series"] += 1
            logger.info(
                f"[AUTO-INDEX] ✅ msg={getattr(message, 'id', '?')} "
                f"title='{rec.get('title') or rec.get('series_title') or '?'}'"
            )
        elif status == "duplicate":
            STATE["duplicate_id"] += 1
        elif status == "skipped":
            reason = str(result.get("reason") or "")
            if "file_id" in reason:
                STATE["skipped_no_file_id"] += 1
            else:
                STATE["skipped_no_media"] += 1
        else:
            STATE["failed"] += 1
            STATE["last_error"] = str(result.get("reason") or "?")[:200]
    except Exception as e:
        logger.exception(f"[AUTO-INDEX] _handle: {e}")


# ============================================================
# HELPERS
# ============================================================

def _is_recent(message) -> bool:
    try:
        mid = getattr(message, "id", 0)
        if not mid:
            return False
        now = time.time()
        for k in list(_recent_msg_ids.keys()):
            if now - _recent_msg_ids[k] > _RECENT_TTL:
                _recent_msg_ids.pop(k, None)
        if mid in _recent_msg_ids:
            return True
        _recent_msg_ids[mid] = now
        return False
    except Exception:
        return False


def _has_media(message) -> bool:
    try:
        return bool(
            getattr(message, "video", None)
            or getattr(message, "document", None)
            or getattr(message, "audio", None)
            or getattr(message, "animation", None)
        )
    except Exception:
        return False


def _extract_file_id(message) -> Optional[str]:
    try:
        if getattr(message, "video", None):
            return message.video.file_id
        if getattr(message, "document", None):
            return message.document.file_id
        if getattr(message, "audio", None):
            return message.audio.file_id
        if getattr(message, "animation", None):
            return message.animation.file_id
    except Exception:
        pass
    return None


async def _is_exact_duplicate(file_id: str) -> bool:
    fp = None
    try:
        from services.duplicate import compute_fingerprint, _bloom_check
        fp = compute_fingerprint(file_id)
        if _bloom_check(fp):
            return True
    except Exception:
        pass

    try:
        from database import db_registry
        for entry in db_registry.media_entries():
            try:
                q = {"_id": fp} if fp else {"file_id": file_id}
                exists = await entry.db["media_files"].find_one(q, {"_id": 1})
                if exists:
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


def snapshot() -> Dict[str, Any]:
    uptime = time.time() - STATE.get("started_at", time.time())
    last_age = 0.0
    if STATE.get("last_message_at"):
        last_age = time.time() - STATE["last_message_at"]

    return {
        "enabled": STATE["enabled"],
        "processed": STATE["processed"],
        "saved": STATE["saved"],
        "duplicate_id": STATE["duplicate_id"],
        "skipped_no_media": STATE["skipped_no_media"],
        "skipped_no_file_id": STATE["skipped_no_file_id"],
        "failed": STATE["failed"],
        "movies": STATE["movies"],
        "series": STATE["series"],
        "uptime_text": FM.duration_short(uptime),
        "last_message_age": last_age,
        "last_error": STATE["last_error"],
        "channels": _get_channels(),
    }


__all__ = ["is_auto_enabled", "set_auto_enabled", "snapshot"]
