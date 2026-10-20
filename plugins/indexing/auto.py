# ============================================================
# 🏨 DOWNTOWN VILLA — AUTO-INDEXING HANDLER
# ============================================================
#
# Runs when new messages arrive in watched channels.
#
# RULE (LOCKED):
#   • Only skip if the same file_unique_id exists
#   • Everything else is imported silently
#
# Metadata source is read from bot_settings.indexing_default.
#
# WATCH LIST SOURCE:
#   1. DB collection `indexing_channels` (enabled=True)
#   2. Fallback: config.DATABASE_CHANNEL_IDS / DATABASE_CHANNEL_ID
#
# ============================================================

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Set, Tuple

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

# recent-id dedup — keyed by (chat_id, msg_id)
_recent_keys: Dict[Tuple[int, int], float] = {}
_RECENT_TTL = 60.0

# watch-list cache
_WATCH_CACHE: Set[int] = set()
_cache_loaded_at: float = 0.0
_CACHE_TTL = 30.0


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
# CONFIG FALLBACK CHANNELS
# ============================================================

def _get_config_channels() -> List[int]:
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


# ============================================================
# WATCH CACHE (dynamic)
# ============================================================

async def _refresh_watch_cache(force: bool = False) -> None:
    """
    Reload the set of watched channel IDs.
    Priority:
        1. DB `indexing_channels` (enabled=True)
        2. config fallback
    """
    global _cache_loaded_at
    now = time.time()
    if not force and (now - _cache_loaded_at) < _CACHE_TTL:
        return

    new_set: Set[int] = set()

    # 1. DB
    try:
        from plugins.indexing import backward as BW
        ids = await BW.list_enabled_channel_ids()
        for x in (ids or []):
            try:
                new_set.add(int(x))
            except Exception:
                continue
    except Exception as e:
        logger.debug(f"[AUTO-INDEX] DB watch list: {e}")

    # 2. config fallback
    if not new_set:
        for x in _get_config_channels():
            try:
                new_set.add(int(x))
            except Exception:
                continue

    if new_set != _WATCH_CACHE:
        logger.info(
            f"[AUTO-INDEX] watch list updated → "
            f"{sorted(new_set)}"
        )

    _WATCH_CACHE.clear()
    _WATCH_CACHE.update(new_set)
    _cache_loaded_at = now


def _watched_channel_ids() -> Set[int]:
    return set(_WATCH_CACHE)


async def force_refresh() -> None:
    """Public — call from backward.py after register/toggle/remove."""
    await _refresh_watch_cache(force=True)


# ============================================================
# DYNAMIC FILTER
# ============================================================

async def _filter_func(_, __, message) -> bool:
    try:
        chat = getattr(message, "chat", None)
        if chat is None:
            return False
        cid = int(getattr(chat, "id", 0) or 0)
        if not cid:
            return False

        await _refresh_watch_cache()

        if cid not in _WATCH_CACHE:
            return False

        # service messages never carry media we care about
        if getattr(message, "service", None):
            return False

        return True
    except Exception:
        return False


_CHANNEL_FILTER = filters.create(_filter_func)


# ============================================================
# HANDLER
# ============================================================

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
        media_items = _extract_media_items(message)
        if not any(item.get("file_id") for item in media_items):
            STATE["skipped_no_file_id"] += 1
            return

        metadata_source = await _get_default_metadata_source()

        try:
            from plugins.indexing.pipeline import process_message
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

        results = (
            result.get("results", [])
            if result.get("status") == "multiple"
            else [result]
        )
        for item_result in results:
            _record_result(message, item_result)
    except Exception as e:
        STATE["failed"] += 1
        STATE["last_error"] = str(e)[:200]
        logger.exception(f"[AUTO-INDEX] _handle: {e}")


# ============================================================
# HELPERS
# ============================================================

def _is_recent(message) -> bool:
    """Dedup by (chat_id, message_id) — cross-channel safe."""
    try:
        mid = int(getattr(message, "id", 0) or 0)
        chat = getattr(message, "chat", None)
        cid = int(getattr(chat, "id", 0) or 0) if chat else 0
        if not mid or not cid:
            return False

        key = (cid, mid)
        now = time.time()

        # cleanup
        for k in list(_recent_keys.keys()):
            if now - _recent_keys[k] > _RECENT_TTL:
                _recent_keys.pop(k, None)

        if key in _recent_keys:
            return True
        _recent_keys[key] = now
        return False
    except Exception:
        return False


def _has_media(message) -> bool:
    try:
        return bool(_extract_media_items(message))
    except Exception:
        return False


def _extract_file_id(message) -> Optional[str]:
    try:
        return next(
            (
                item["file_id"]
                for item in _extract_media_items(message)
                if item.get("file_id")
            ),
            None,
        )
    except Exception:
        logger.exception("[AUTO-INDEX] media extraction failed")
    return None


def _extract_media_items(message) -> List[Dict[str, Any]]:
    from plugins.indexing.pipeline import extract_media_items
    return [
        {
            "file_id": getattr(media, "file_id", None),
            "file_unique_id": getattr(media, "file_unique_id", None),
            "file_type": file_type,
        }
        for media, file_type in extract_media_items(message)
    ]


def _record_result(message, result: Dict[str, Any]) -> None:
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
        logger.info(
            f"[AUTO-INDEX] ♻️ Telegram file identity duplicate "
            f"msg={getattr(message, 'id', '?')}"
        )
    elif status == "skipped":
        reason = str(result.get("reason") or "")
        if "file_id" in reason:
            STATE["skipped_no_file_id"] += 1
        else:
            STATE["skipped_no_media"] += 1
    else:
        STATE["failed"] += 1
        STATE["last_error"] = str(result.get("reason") or "?")[:200]
        logger.warning(
            "[CHANNEL] save failed reason=%s file=%s",
            STATE["last_error"],
            result.get("file_name") or "?",
        )


async def _is_exact_duplicate(
    file_id: str,
    file_unique_id: Optional[str] = None,
) -> bool:
    from services.duplicate import find_exact_file_id
    return await find_exact_file_id(file_id, file_unique_id=file_unique_id)


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
        "channels": sorted(_WATCH_CACHE) or _get_config_channels(),
    }


__all__ = [
    "is_auto_enabled", "set_auto_enabled",
    "snapshot", "force_refresh",
]
