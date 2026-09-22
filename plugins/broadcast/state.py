# ============================================================
# 🏨 DOWNTOWN VILLA — BROADCAST STATE
# ============================================================
#
# Persists broadcast runs + auto-delete schedule.
#
# Collections (SYSTEM DB):
#   broadcast_runs        — one doc per run
#   broadcast_autodelete  — msgs to auto-delete
#
# ============================================================

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

RUNS_COLL = "broadcast_runs"
AUTODELETE_COLL = "broadcast_autodelete"


def _coll(name: str):
    try:
        from database import db_registry
        db = db_registry.get_system_db()
        if db is None:
            return None
        return db[name]
    except Exception:
        return None


def _runs():
    return _coll(RUNS_COLL)


def _autodel():
    return _coll(AUTODELETE_COLL)


# ============================================================
# RUN HISTORY
# ============================================================

async def create_run(
    owner: int,
    target_kind: str,
    target_count: int,
    source_msg_id: int,
    source_chat_id: int,
    autodelete_seconds: int = 0,
) -> Optional[str]:
    c = _runs()
    if c is None:
        return None
    try:
        job_id = uuid.uuid4().hex[:10]
        await c.insert_one({
            "job_id": job_id,
            "owner": int(owner),
            "kind": target_kind,
            "total": int(target_count),
            "sent": 0,
            "failed": 0,
            "blocked": 0,
            "deleted": 0,
            "source_msg_id": int(source_msg_id),
            "source_chat_id": int(source_chat_id),
            "autodelete_seconds": int(autodelete_seconds),
            "status": "running",
            "started_at": datetime.utcnow(),
            "finished_at": None,
        })
        return job_id
    except Exception as e:
        logger.warning(f"[BC-STATE] create: {e}")
        return None


async def update_run(job_id: str, patch: Dict[str, Any]) -> bool:
    c = _runs()
    if c is None or not job_id:
        return False
    try:
        await c.update_one(
            {"job_id": job_id},
            {"$set": patch},
        )
        return True
    except Exception:
        return False


async def increment_run(job_id: str, **fields) -> bool:
    c = _runs()
    if c is None or not job_id:
        return False
    try:
        inc = {k: int(v) for k, v in fields.items()}
        await c.update_one(
            {"job_id": job_id},
            {"$inc": inc},
        )
        return True
    except Exception:
        return False


async def finish_run(job_id: str, status: str = "completed") -> bool:
    return await update_run(job_id, {
        "status": status,
        "finished_at": datetime.utcnow(),
    })


async def list_runs(limit: int = 15) -> List[Dict[str, Any]]:
    c = _runs()
    if c is None:
        return []
    try:
        cursor = c.find({}).sort("started_at", -1).limit(int(limit))
        return await cursor.to_list(length=int(limit))
    except Exception:
        return []


async def clear_runs() -> int:
    c = _runs()
    if c is None:
        return 0
    try:
        r = await c.delete_many({})
        return r.deleted_count
    except Exception:
        return 0


# ============================================================
# AUTO-DELETE SCHEDULE
# ============================================================

async def schedule_autodelete(
    chat_id: int,
    message_id: int,
    seconds: int,
    job_id: str = "",
) -> bool:
    c = _autodel()
    if c is None:
        return False
    try:
        await c.insert_one({
            "chat_id": int(chat_id),
            "message_id": int(message_id),
            "delete_at": time.time() + int(seconds),
            "job_id": job_id or "",
            "created_at": time.time(),
        })
        return True
    except Exception:
        return False


async def due_autodeletes(limit: int = 200) -> List[Dict[str, Any]]:
    c = _autodel()
    if c is None:
        return []
    try:
        cursor = c.find({
            "delete_at": {"$lte": time.time()}
        }).limit(int(limit))
        return await cursor.to_list(length=int(limit))
    except Exception:
        return []


async def remove_autodelete(doc_id) -> None:
    c = _autodel()
    if c is None:
        return
    try:
        await c.delete_one({"_id": doc_id})
    except Exception:
        pass


async def count_scheduled() -> int:
    c = _autodel()
    if c is None:
        return 0
    try:
        return await c.estimated_document_count()
    except Exception:
        return 0


async def ensure_indexes() -> bool:
    try:
        c1 = _runs()
        if c1 is not None:
            await c1.create_index("started_at")
            await c1.create_index("job_id", unique=True)

        c2 = _autodel()
        if c2 is not None:
            await c2.create_index("delete_at")
        return True
    except Exception:
        return False


__all__ = [
    "create_run", "update_run", "increment_run", "finish_run",
    "list_runs", "clear_runs",
    "schedule_autodelete", "due_autodeletes", "remove_autodelete",
    "count_scheduled", "ensure_indexes",
]
