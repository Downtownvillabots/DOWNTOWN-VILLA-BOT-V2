# ============================================================
# 🏨 DOWNTOWN VILLA — INDEXING STATE LAYER
# ============================================================
#
# Persists indexing job state across restarts.
#
# Stored in: SYSTEM DB → indexing_jobs
#
# SCHEMA:
#   {
#     "_id": ObjectId,
#     "job_id": "INDEX-20260922-abc123",
#     "kind": "backward" | "auto" | "manual",
#     "channel_id": -100xxx,
#     "channel_title": "My Channel",
#     "mode": "movies" | "series" | "both",
#
#     "start_message_id": 5000,   # backward indexing
#     "current_message_id": 3500,
#     "end_message_id": 1,
#
#     "status": "running" | "paused" | "stopped"
#             | "completed" | "error",
#
#     "stats": {
#         "processed": 1234,
#         "saved": 1100,
#         "duplicate_id": 50,   ← exact same file_id only
#         "skipped_no_media": 40,
#         "skipped_no_file_id": 10,
#         "failed": 34,
#         "movies": 800,
#         "series": 300,
#     },
#
#     "started_at": ISODate,
#     "updated_at": ISODate,
#     "finished_at": ISODate | null,
#     "error": null,
#     "owner": 12345,
#   }
#
# ============================================================

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


COLLECTION = "indexing_jobs"


# ============================================================
# SECTION 1 — DB
# ============================================================

def _coll():
    try:
        from database import db_registry
        db = db_registry.get_system_db()
        if db is None:
            return None
        return db[COLLECTION]
    except Exception as e:
        logger.debug(f"[IDX-STATE] coll: {e}")
        return None


# ============================================================
# SECTION 2 — CREATE
# ============================================================

async def create_job(job: Dict[str, Any]) -> Optional[str]:
    """Insert a new job. Returns job_id."""
    c = _coll()
    if c is None:
        return None
    try:
        now = datetime.utcnow()
        doc = dict(job)
        doc.setdefault("created_at", now)
        doc["updated_at"] = now
        doc.setdefault("stats", _empty_stats())
        r = await c.insert_one(doc)
        return str(r.inserted_id)
    except Exception as e:
        logger.warning(f"[IDX-STATE] create: {e}")
        return None


def _empty_stats() -> Dict[str, int]:
    return {
        "processed": 0,
        "saved": 0,
        "duplicate_id": 0,
        "skipped_no_media": 0,
        "skipped_no_file_id": 0,
        "failed": 0,
        "movies": 0,
        "series": 0,
    }


# ============================================================
# SECTION 3 — UPDATE
# ============================================================

async def update_job(job_id: str, patch: Dict[str, Any]) -> bool:
    """Update one job."""
    c = _coll()
    if c is None or not job_id:
        return False
    try:
        from bson import ObjectId
        patch = dict(patch)
        patch["updated_at"] = datetime.utcnow()
        r = await c.update_one(
            {"_id": ObjectId(job_id)},
            {"$set": patch},
        )
        return r.matched_count > 0
    except Exception as e:
        logger.debug(f"[IDX-STATE] update: {e}")
        return False


async def update_stats(job_id: str, delta: Dict[str, int]) -> bool:
    """Increment stats counters."""
    c = _coll()
    if c is None or not job_id:
        return False
    try:
        from bson import ObjectId
        inc = {f"stats.{k}": int(v) for k, v in delta.items()}
        inc["updated_at"] = datetime.utcnow()
        r = await c.update_one(
            {"_id": ObjectId(job_id)},
            {"$inc": inc},
        )
        return r.matched_count > 0
    except Exception as e:
        logger.debug(f"[IDX-STATE] stats: {e}")
        return False


async def set_status(
    job_id: str,
    status: str,
    error: Optional[str] = None,
) -> bool:
    """Update status (+ optional error)."""
    patch: Dict[str, Any] = {"status": str(status)}
    if error:
        patch["error"] = str(error)[:500]
    if status in ("completed", "stopped", "error", "cancelled"):
        patch["finished_at"] = datetime.utcnow()
    return await update_job(job_id, patch)


async def set_checkpoint(job_id: str, message_id: int) -> bool:
    """Save current message id checkpoint."""
    return await update_job(job_id, {"current_message_id": int(message_id)})


# ============================================================
# SECTION 4 — READ
# ============================================================

async def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    c = _coll()
    if c is None or not job_id:
        return None
    try:
        from bson import ObjectId
        return await c.find_one({"_id": ObjectId(job_id)})
    except Exception:
        return None


async def get_by_job_id(job_id_str: str) -> Optional[Dict[str, Any]]:
    """Lookup by human-readable job_id string."""
    c = _coll()
    if c is None or not job_id_str:
        return None
    try:
        return await c.find_one({"job_id": str(job_id_str)})
    except Exception:
        return None


async def list_recent(limit: int = 20) -> List[Dict[str, Any]]:
    """Recent jobs, newest first."""
    c = _coll()
    if c is None:
        return []
    try:
        cursor = (
            c.find({})
            .sort("created_at", -1)
            .limit(int(limit))
        )
        return await cursor.to_list(length=int(limit))
    except Exception:
        return []


async def list_active() -> List[Dict[str, Any]]:
    """Jobs with status running or paused."""
    c = _coll()
    if c is None:
        return []
    try:
        cursor = c.find({
            "status": {"$in": ["running", "paused"]}
        })
        return await cursor.to_list(length=50)
    except Exception:
        return []


# ============================================================
# SECTION 5 — DELETE
# ============================================================

async def delete_job(job_id: str) -> bool:
    c = _coll()
    if c is None or not job_id:
        return False
    try:
        from bson import ObjectId
        r = await c.delete_one({"_id": ObjectId(job_id)})
        return r.deleted_count > 0
    except Exception:
        return False


async def clear_completed() -> int:
    """Remove finished jobs."""
    c = _coll()
    if c is None:
        return 0
    try:
        r = await c.delete_many({
            "status": {"$in": ["completed", "stopped", "error", "cancelled"]}
        })
        return r.deleted_count
    except Exception:
        return 0


async def clear_all() -> int:
    """Remove every job."""
    c = _coll()
    if c is None:
        return 0
    try:
        r = await c.delete_many({})
        return r.deleted_count
    except Exception:
        return 0


# ============================================================
# SECTION 6 — SNAPSHOT
# ============================================================

async def snapshot() -> Dict[str, Any]:
    """Compact overview for admin."""
    try:
        active = await list_active()
        recent = await list_recent(10)
        return {
            "active_count": len(active),
            "active": active[:5],
            "recent": recent,
        }
    except Exception:
        return {"active_count": 0, "active": [], "recent": []}


# ============================================================
# PUBLIC EXPORTS
# ============================================================

__all__ = [
    "COLLECTION",
    "create_job",
    "update_job",
    "update_stats",
    "set_status",
    "set_checkpoint",
    "get_job",
    "get_by_job_id",
    "list_recent",
    "list_active",
    "delete_job",
    "clear_completed",
    "clear_all",
    "snapshot",
]
