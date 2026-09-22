# ============================================================
# 🏨 DOWNTOWN VILLA — INDEXING STATE LAYER
# ============================================================
#
# Persists indexing job state across restarts.
#
# Storage: SYSTEM DB → indexing_jobs
#
# ============================================================

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

COLLECTION = "indexing_jobs"


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


async def create_job(job: Dict[str, Any]) -> Optional[str]:
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


async def update_job(job_id: str, patch: Dict[str, Any]) -> bool:
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


async def set_status(job_id: str, status: str, error: Optional[str] = None) -> bool:
    patch: Dict[str, Any] = {"status": str(status)}
    if error:
        patch["error"] = str(error)[:500]
    if status in ("completed", "stopped", "error", "cancelled"):
        patch["finished_at"] = datetime.utcnow()
    return await update_job(job_id, patch)


async def set_checkpoint(job_id: str, message_id: int) -> bool:
    return await update_job(job_id, {"current_message_id": int(message_id)})


async def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    c = _coll()
    if c is None or not job_id:
        return None
    try:
        from bson import ObjectId
        return await c.find_one({"_id": ObjectId(job_id)})
    except Exception:
        return None


async def list_recent(limit: int = 20) -> List[Dict[str, Any]]:
    c = _coll()
    if c is None:
        return []
    try:
        cursor = c.find({}).sort("created_at", -1).limit(int(limit))
        return await cursor.to_list(length=int(limit))
    except Exception:
        return []


async def list_active() -> List[Dict[str, Any]]:
    c = _coll()
    if c is None:
        return []
    try:
        cursor = c.find({"status": {"$in": ["running", "paused"]}})
        return await cursor.to_list(length=50)
    except Exception:
        return []


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
    c = _coll()
    if c is None:
        return 0
    try:
        r = await c.delete_many({})
        return r.deleted_count
    except Exception:
        return 0


__all__ = [
    "COLLECTION", "create_job", "update_job", "update_stats",
    "set_status", "set_checkpoint", "get_job", "list_recent",
    "list_active", "delete_job", "clear_completed", "clear_all",
]
