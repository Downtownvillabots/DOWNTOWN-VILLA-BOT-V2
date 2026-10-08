# ============================================================
# 🏨 DOWNTOWN VILLA — OTT EVENT MODEL
# ============================================================
# One document per active OTT event (per movie).
# Persists across restarts, drives every live message edit.
# ============================================================

from __future__ import annotations
import logging
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

EVENT_TTL_DAYS = 90


def _coll():
    try:
        from database import db_registry
        db = db_registry.get_system_db()
        return db["ott_events"] if db is not None else None
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════
# CREATE / LOAD
# ═══════════════════════════════════════════════════════════

async def create_event(
    tmdb_id: int,
    title: str,
    language: str,
    admin_id: int,
    admin_channel_id: int,
    admin_msg_id: int,
) -> str:
    c = _coll()
    if c is None:
        return ""
    eid = uuid.uuid4().hex[:16]
    now = time.time()
    doc = {
        "_id": eid,
        "tmdb_id": int(tmdb_id),
        "title": title,
        "language": language,
        "admin_id": int(admin_id),
        "admin_channel_id": int(admin_channel_id),
        "admin_msg_id": int(admin_msg_id),
        "state": "setup",         # setup | live | ended
        "notify_enabled": True,
        "get_files_enabled": True,
        "auto_delete_hours": 24,
        "caption": None,
        "custom_buttons": None,
        "target_posts": [],       # [{chat_id, msg_id, kind}]
        "subs_total": 0,
        "notified": 0,
        "pending": 0,
        "files_count": 0,
        "created_at": now,
        "updated_at": now,
        "ended_at": 0.0,
        "expires_at": datetime.now(timezone.utc)
            .replace(microsecond=0)
            + __import__("datetime").timedelta(days=EVENT_TTL_DAYS),
    }
    try:
        await c.insert_one(doc)
        return eid
    except Exception as e:
        logger.exception(f"[OTT-EV] create: {e}")
        return ""


async def get_event(eid: str) -> Optional[Dict[str, Any]]:
    c = _coll()
    if c is None or not eid:
        return None
    try:
        return await c.find_one({"_id": eid})
    except Exception:
        return None


async def get_active_for_movie(tmdb_id: int) -> Optional[Dict[str, Any]]:
    """Latest non-ended event for this movie, if any."""
    c = _coll()
    if c is None:
        return None
    try:
        return await c.find_one(
            {"tmdb_id": int(tmdb_id), "state": {"$ne": "ended"}},
            sort=[("created_at", -1)],
        )
    except Exception:
        return None


async def get_any_for_movie(tmdb_id: int) -> Optional[Dict[str, Any]]:
    c = _coll()
    if c is None:
        return None
    try:
        return await c.find_one(
            {"tmdb_id": int(tmdb_id)}, sort=[("created_at", -1)])
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════
# UPDATE FIELDS
# ═══════════════════════════════════════════════════════════

async def update_event(eid: str, **fields) -> bool:
    c = _coll()
    if c is None or not eid:
        return False
    try:
        fields["updated_at"] = time.time()
        r = await c.update_one({"_id": eid}, {"$set": fields})
        return r.matched_count > 0
    except Exception as e:
        logger.debug(f"[OTT-EV] update: {e}")
        return False


async def mark_ended(eid: str) -> bool:
    return await update_event(eid, state="ended", ended_at=time.time())


async def set_admin_msg(eid: str, chat_id: int, msg_id: int) -> bool:
    return await update_event(
        eid, admin_channel_id=int(chat_id), admin_msg_id=int(msg_id))


async def add_target_post(eid: str, chat_id: int, msg_id: int,
                           kind: str) -> bool:
    c = _coll()
    if c is None or not eid:
        return False
    try:
        await c.update_one(
            {"_id": eid},
            {"$push": {"target_posts": {
                "chat_id": int(chat_id),
                "msg_id": int(msg_id),
                "kind": kind,
                "added_at": time.time(),
            }},
             "$set": {"updated_at": time.time()}},
        )
        return True
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════
# RECOUNT STATS (source of truth = subs collection)
# ═══════════════════════════════════════════════════════════

async def recount(eid: str) -> Dict[str, int]:
    """Recalculate subs_total / notified / pending from real state."""
    ev = await get_event(eid)
    if not ev:
        return {"subs_total": 0, "notified": 0, "pending": 0, "files_count": 0}
    tmdb_id = ev["tmdb_id"]

    try:
        from plugins.ott import database as DB
        total = await DB.subs_coll().count_documents(
            {"tmdb_id": int(tmdb_id)})
        pending = await DB.subs_coll().count_documents(
            {"tmdb_id": int(tmdb_id), "notified": False})
        notified = total - pending

        # File count from media DB
        movie = await DB.get_movie(tmdb_id) or {}
        files = await DB.find_files_for_movie(movie, limit=200)
        files_count = len(files)
    except Exception as e:
        logger.debug(f"[OTT-EV] recount: {e}")
        total = pending = notified = files_count = 0

    await update_event(
        eid,
        subs_total=total, notified=notified,
        pending=pending, files_count=files_count,
    )
    return {
        "subs_total": total, "notified": notified,
        "pending": pending, "files_count": files_count,
    }


async def stats(eid: str) -> Dict[str, int]:
    ev = await get_event(eid)
    if not ev:
        return {"subs_total": 0, "notified": 0, "pending": 0, "files_count": 0}
    return {
        "subs_total": int(ev.get("subs_total") or 0),
        "notified": int(ev.get("notified") or 0),
        "pending": int(ev.get("pending") or 0),
        "files_count": int(ev.get("files_count") or 0),
    }


# ═══════════════════════════════════════════════════════════
# FIND EVENTS BY USER (for user-side checks)
# ═══════════════════════════════════════════════════════════

async def is_event_active_for_movie(tmdb_id: int) -> bool:
    ev = await get_active_for_movie(tmdb_id)
    return bool(ev)


async def list_active_events(limit: int = 50) -> List[Dict[str, Any]]:
    c = _coll()
    if c is None:
        return []
    try:
        cur = c.find({"state": {"$ne": "ended"}}).sort(
            "created_at", -1).limit(limit)
        return await cur.to_list(length=limit)
    except Exception:
        return []


# ═══════════════════════════════════════════════════════════
# INDEXES
# ═══════════════════════════════════════════════════════════

async def ensure_indexes() -> bool:
    c = _coll()
    if c is None:
        return False
    try:
        await c.create_index("expires_at", expireAfterSeconds=0)
        await c.create_index("tmdb_id")
        await c.create_index([("state", 1), ("created_at", -1)])
        return True
    except Exception as e:
        logger.warning(f"[OTT-EV] index: {e}")
        return False


__all__ = [
    "create_event", "get_event", "get_active_for_movie", "get_any_for_movie",
    "update_event", "mark_ended", "set_admin_msg", "add_target_post",
    "recount", "stats", "is_event_active_for_movie", "list_active_events",
    "ensure_indexes",
]
