# ============================================================
# 🏨 DOWNTOWN VILLA — BACKUP STATE LAYER (MULTI-SHARD)
# ============================================================
#
# Persistent state tracker for every file being backed up.
#
# WHY MULTI-SHARD:
#   A single backup run can process hundreds of thousands of
#   files. Storing all state in one collection can hit
#   MongoDB document limits or slow down writes.
#
#   → We spread state across every BACKUP_DATABASE shard
#   → Each file always maps to the SAME shard (deterministic)
#   → Queries can scan one shard or all shards
#
# COLLECTION SCHEMA (per shard):
#   {
#     "_id": ObjectId,
#     "source_db": "Media" | "Media2" | "Media3",
#     "file_id": "BQACAg...",
#     "file_name": "Movie.2024.mkv",
#     "file_size": 1057289339,
#     "backup_token": "DTV-BACKUP-Media-a3f5...",
#     "status": "UPLOADED",
#     "message_id": 15234,
#     "attempts": 1,
#     "last_error": null,
#     "created_at": ISODate,
#     "updated_at": ISODate,
#   }
#
# INDEXES:
#   • (source_db, file_id) unique
#   • (source_db, status)
#   • (status, updated_at)
#   • (backup_token) unique sparse
#
# ============================================================

from __future__ import annotations

import hashlib
import logging
import time
from datetime import datetime, timedelta
from typing import Any, AsyncIterator, Dict, List, Optional, Tuple

from database import db_registry

logger = logging.getLogger(__name__)


# ============================================================
# SECTION 1 — CONSTANTS
# ============================================================

STATE_COLLECTION = "backup_state"
RUNS_COLLECTION = "backup_runs"
TOKEN_PREFIX = "DTV-BACKUP"

STATUS_PENDING = "PENDING"
STATUS_UPLOADING = "UPLOADING"
STATUS_UPLOADED = "UPLOADED"
STATUS_FAILED = "FAILED"
STATUS_SKIPPED = "SKIPPED"

ALL_STATUSES = (
    STATUS_PENDING, STATUS_UPLOADING, STATUS_UPLOADED,
    STATUS_FAILED, STATUS_SKIPPED,
)

# Source databases (ordered for the backup worker)
SOURCE_DB_ORDER = ("Media", "Media2", "Media3")


# ============================================================
# SECTION 2 — SHARD DISCOVERY
# ============================================================

def list_shards() -> List[Any]:
    """Return every backup shard entry (from database registry)."""
    try:
        return db_registry.backup_entries()
    except Exception as e:
        logger.warning(f"[STATE] shard discovery failed: {e}")
        return []


def shard_count() -> int:
    return len(list_shards())


def shard_of(file_id: str, source_db: str = "") -> int:
    """
    Deterministic shard index for a file.
    Same file always maps to the same shard.
    """
    shards = list_shards()
    if not shards:
        return 0
    try:
        key = f"{source_db}|{file_id}".encode("utf-8")
        h = int.from_bytes(key[:4], "big")
        return h % len(shards)
    except Exception:
        return 0


def _state_coll(shard_index: Optional[int] = None):
    """Return state collection on a specific shard (or primary)."""
    shards = list_shards()
    if not shards:
        return None
    try:
        if shard_index is not None and 0 <= shard_index < len(shards):
            return shards[shard_index].db[STATE_COLLECTION]
        return shards[0].db[STATE_COLLECTION]
    except Exception as e:
        logger.debug(f"[STATE] coll: {e}")
        return None


def _all_state_colls():
    """Return every state collection (for cross-shard scans)."""
    out = []
    for entry in list_shards():
        try:
            if entry.online:
                out.append(entry.db[STATE_COLLECTION])
        except Exception:
            continue
    return out


def _runs_coll():
    """Runs history always lives on shard 0."""
    shards = list_shards()
    if not shards:
        return None
    try:
        return shards[0].db[RUNS_COLLECTION]
    except Exception:
        return None


# ============================================================
# SECTION 3 — BACKUP TOKEN
# ============================================================

def backup_token(source_db: str, file_id: str) -> str:
    """
    Deterministic token stored in the caption.
    Never rotates — same file → same token.
    """
    raw = f"{TOKEN_PREFIX}|{source_db}|{file_id}".encode("utf-8")
    digest = hashlib.sha256(raw).hexdigest()
    return f"{TOKEN_PREFIX}-{source_db}-{digest[:32]}"


# ============================================================
# SECTION 4 — INDEXES
# ============================================================

async def ensure_indexes() -> bool:
    """Create indexes on every backup shard."""
    colls = _all_state_colls()
    if not colls:
        return False

    ok = True
    for c in colls:
        try:
            await c.create_index(
                [("source_db", 1), ("file_id", 1)],
                unique=True, name="source_file_uq",
            )
            await c.create_index(
                [("source_db", 1), ("status", 1)],
                name="source_status",
            )
            await c.create_index(
                [("status", 1), ("updated_at", 1)],
                name="status_updated",
            )
            await c.create_index(
                [("backup_token", 1)],
                unique=True, sparse=True, name="token_uq",
            )
        except Exception as e:
            logger.warning(f"[STATE] index shard: {e}")
            ok = False

    # Runs index
    runs = _runs_coll()
    if runs is not None:
        try:
            await runs.create_index(
                [("started_at", -1)], name="runs_started",
            )
        except Exception:
            pass

    return ok


# ============================================================
# SECTION 5 — READ
# ============================================================

async def get_state(
    source_db: str,
    file_id: str,
) -> Optional[Dict[str, Any]]:
    """
    Fetch state for one file.
    Tries deterministic shard first, falls back to scan.
    """
    fid = str(file_id)
    idx = shard_of(fid, source_db)

    # Fast path: correct shard
    c = _state_coll(idx)
    if c is not None:
        try:
            doc = await c.find_one(
                {"source_db": source_db, "file_id": fid}
            )
            if doc:
                return doc
        except Exception:
            pass

    # Slow path: scan all shards
    for c in _all_state_colls():
        try:
            doc = await c.find_one(
                {"source_db": source_db, "file_id": fid}
            )
            if doc:
                return doc
        except Exception:
            continue

    return None


async def get_status(source_db: str, file_id: str) -> str:
    """Return status string (defaults to PENDING)."""
    doc = await get_state(source_db, file_id)
    if not doc:
        return STATUS_PENDING
    return str(doc.get("status", STATUS_PENDING)).upper()


async def find_by_token(token: str) -> Optional[Dict[str, Any]]:
    """Lookup a state doc by its backup token."""
    if not token:
        return None
    for c in _all_state_colls():
        try:
            doc = await c.find_one({"backup_token": token})
            if doc:
                return doc
        except Exception:
            continue
    return None


async def find_by_message_id(
    message_id: int,
    source_db: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Lookup by Telegram message id."""
    query: Dict[str, Any] = {"message_id": int(message_id)}
    if source_db:
        query["source_db"] = source_db
    for c in _all_state_colls():
        try:
            doc = await c.find_one(query)
            if doc:
                return doc
        except Exception:
            continue
    return None


# ============================================================
# SECTION 6 — WRITE
# ============================================================

async def set_state(
    source_db: str,
    document: Dict[str, Any],
    status: str,
    *,
    message_id: Optional[int] = None,
    error: Optional[str] = None,
    attempts: Optional[int] = None,
) -> bool:
    """
    Upsert state for one file.
    Writes to the file's deterministic shard.
    """
    file_id = _extract_file_id(document)
    if not file_id:
        logger.debug("[STATE] no file_id in document")
        return False

    fid = str(file_id)
    idx = shard_of(fid, source_db)
    c = _state_coll(idx)
    if c is None:
        return False

    token = backup_token(source_db, fid)
    now = datetime.utcnow()

    update: Dict[str, Any] = {
        "$set": {
            "source_db": source_db,
            "file_id": fid,
            "file_name": _extract_file_name(document),
            "file_size": _extract_file_size(document),
            "backup_token": token,
            "status": str(status).upper(),
            "updated_at": now,
            "shard_index": idx,
        },
        "$setOnInsert": {"created_at": now},
    }

    if message_id is not None:
        update["$set"]["message_id"] = int(message_id)
    if error is not None:
        update["$set"]["last_error"] = str(error)[:2000]
    if attempts is not None:
        update["$set"]["attempts"] = int(attempts)

    try:
        await c.update_one(
            {"source_db": source_db, "file_id": fid},
            update,
            upsert=True,
        )
        return True
    except Exception as e:
        logger.warning(f"[STATE] set_state: {e}")
        return False


async def mark_pending(source_db: str, document: Dict[str, Any]) -> bool:
    return await set_state(source_db, document, STATUS_PENDING)


async def mark_uploading(
    source_db: str,
    document: Dict[str, Any],
) -> bool:
    """Mark UPLOADING + increment attempts."""
    file_id = _extract_file_id(document)
    existing = await get_state(source_db, file_id) if file_id else None
    attempts = int(existing.get("attempts", 0)) if existing else 0
    return await set_state(
        source_db, document, STATUS_UPLOADING,
        attempts=attempts + 1,
    )


async def mark_uploaded(
    source_db: str,
    document: Dict[str, Any],
    message_id: int,
) -> bool:
    return await set_state(
        source_db, document, STATUS_UPLOADED,
        message_id=message_id,
    )


async def mark_failed(
    source_db: str,
    document: Dict[str, Any],
    error: str,
) -> bool:
    file_id = _extract_file_id(document)
    existing = await get_state(source_db, file_id) if file_id else None
    attempts = int(existing.get("attempts", 1)) if existing else 1
    return await set_state(
        source_db, document, STATUS_FAILED,
        error=str(error)[:2000],
        attempts=attempts,
    )


async def mark_skipped(
    source_db: str,
    document: Dict[str, Any],
    reason: str = "",
) -> bool:
    return await set_state(
        source_db, document, STATUS_SKIPPED,
        error=reason or None,
    )


# ============================================================
# SECTION 7 — COUNTS
# ============================================================

async def count_by_status(
    status: Optional[str] = None,
    source_db: Optional[str] = None,
) -> int:
    """Total count across every shard for a status."""
    query: Dict[str, Any] = {}
    if status:
        query["status"] = str(status).upper()
    if source_db:
        query["source_db"] = source_db

    total = 0
    for c in _all_state_colls():
        try:
            total += await c.count_documents(query)
        except Exception:
            pass
    return total


async def count_per_shard(
    status: Optional[str] = None,
    source_db: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Per-shard breakdown of a status."""
    query: Dict[str, Any] = {}
    if status:
        query["status"] = str(status).upper()
    if source_db:
        query["source_db"] = source_db

    shards = list_shards()
    out: List[Dict[str, Any]] = []

    for i, entry in enumerate(shards):
        info = {
            "index": i,
            "label": entry.label,
            "online": entry.online,
            "count": 0,
            "pending": 0,
            "uploaded": 0,
            "failed": 0,
            "uploading": 0,
        }
        if not entry.online:
            out.append(info)
            continue

        try:
            c = entry.db[STATE_COLLECTION]
            info["count"] = await c.count_documents(query)
            info["pending"] = await c.count_documents(
                {**query, "status": STATUS_PENDING}
            )
            info["uploaded"] = await c.count_documents(
                {**query, "status": STATUS_UPLOADED}
            )
            info["failed"] = await c.count_documents(
                {**query, "status": STATUS_FAILED}
            )
            info["uploading"] = await c.count_documents(
                {**query, "status": STATUS_UPLOADING}
            )
        except Exception as e:
            logger.debug(f"[STATE] count shard: {e}")

        out.append(info)

    return out


async def count_by_source_db() -> Dict[str, Dict[str, int]]:
    """Return per-source-db totals."""
    out: Dict[str, Dict[str, int]] = {}
    for sdb in SOURCE_DB_ORDER:
        out[sdb] = {
            "pending": await count_by_status(STATUS_PENDING, sdb),
            "uploading": await count_by_status(STATUS_UPLOADING, sdb),
            "uploaded": await count_by_status(STATUS_UPLOADED, sdb),
            "failed": await count_by_status(STATUS_FAILED, sdb),
            "skipped": await count_by_status(STATUS_SKIPPED, sdb),
        }
    return out


# ============================================================
# SECTION 8 — ASYNC ITERATOR
# ============================================================

async def iter_by_status(
    status: str,
    source_db: Optional[str] = None,
    batch_size: int = 200,
) -> AsyncIterator[Dict[str, Any]]:
    """Iterate state docs with a status, across every shard."""
    query: Dict[str, Any] = {"status": str(status).upper()}
    if source_db:
        query["source_db"] = source_db

    for c in _all_state_colls():
        try:
            cursor = c.find(query).batch_size(batch_size)
            async for doc in cursor:
                yield doc
        except Exception as e:
            logger.debug(f"[STATE] iter shard: {e}")
            continue


async def list_failed(
    limit: int = 50,
    source_db: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return recent FAILED records."""
    out: List[Dict[str, Any]] = []
    query: Dict[str, Any] = {"status": STATUS_FAILED}
    if source_db:
        query["source_db"] = source_db

    for c in _all_state_colls():
        try:
            cursor = (
                c.find(query)
                .sort("updated_at", -1)
                .limit(max(1, limit - len(out)))
            )
            docs = await cursor.to_list(length=limit)
            out.extend(docs)
            if len(out) >= limit:
                break
        except Exception:
            continue

    return out[:limit]


async def list_recent(
    limit: int = 20,
    status: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Return most recently updated records."""
    query: Dict[str, Any] = {}
    if status:
        query["status"] = str(status).upper()

    out: List[Dict[str, Any]] = []
    for c in _all_state_colls():
        try:
            cursor = (
                c.find(query)
                .sort("updated_at", -1)
                .limit(limit)
            )
            docs = await cursor.to_list(length=limit)
            out.extend(docs)
        except Exception:
            continue
        if len(out) >= limit * 2:
            break

    # Deduplicate + sort
    out.sort(key=lambda d: d.get("updated_at", 0), reverse=True)
    return out[:limit]


# ============================================================
# SECTION 9 — BULK OPERATIONS
# ============================================================

async def reset_failed() -> int:
    """Mark every FAILED → PENDING (for retry)."""
    total = 0
    for c in _all_state_colls():
        try:
            r = await c.update_many(
                {"status": STATUS_FAILED},
                {
                    "$set": {
                        "status": STATUS_PENDING,
                        "updated_at": datetime.utcnow(),
                        "last_error": None,
                    }
                },
            )
            total += r.modified_count
        except Exception:
            pass
    logger.info(f"[STATE] reset {total} failed → pending")
    return total


async def reset_uploading() -> int:
    """Reset stuck UPLOADING → PENDING (for crash reconcile)."""
    total = 0
    for c in _all_state_colls():
        try:
            r = await c.update_many(
                {"status": STATUS_UPLOADING},
                {
                    "$set": {
                        "status": STATUS_PENDING,
                        "updated_at": datetime.utcnow(),
                    }
                },
            )
            total += r.modified_count
        except Exception:
            pass
    return total


async def wipe_all() -> Dict[str, Any]:
    """Delete every state doc on every shard."""
    out = {"per_shard": [], "total": 0}
    for i, entry in enumerate(list_shards()):
        if not entry.online:
            out["per_shard"].append({
                "index": i, "label": entry.label,
                "deleted": 0, "error": "offline",
            })
            continue
        try:
            c = entry.db[STATE_COLLECTION]
            r = await c.delete_many({})
            out["per_shard"].append({
                "index": i, "label": entry.label,
                "deleted": r.deleted_count, "error": None,
            })
            out["total"] += r.deleted_count
        except Exception as e:
            out["per_shard"].append({
                "index": i, "label": entry.label,
                "deleted": 0, "error": str(e)[:80],
            })

    # Also wipe runs on shard 0
    runs = _runs_coll()
    if runs is not None:
        try:
            r = await runs.delete_many({})
            out["runs_deleted"] = r.deleted_count
        except Exception:
            out["runs_deleted"] = 0

    logger.warning(f"[STATE] wiped {out['total']} docs")
    return out


async def delete_file_state(
    source_db: str,
    file_id: str,
) -> bool:
    """Delete state for one file (across shards)."""
    fid = str(file_id)
    deleted = False
    for c in _all_state_colls():
        try:
            r = await c.delete_many(
                {"source_db": source_db, "file_id": fid}
            )
            if r.deleted_count:
                deleted = True
        except Exception:
            pass
    return deleted


# ============================================================
# SECTION 10 — STATS SNAPSHOT
# ============================================================

async def stats() -> Dict[str, Any]:
    """Full state snapshot for admin panel."""
    return {
        "shards": await count_per_shard(),
        "by_source_db": await count_by_source_db(),
        "totals": {
            "pending": await count_by_status(STATUS_PENDING),
            "uploading": await count_by_status(STATUS_UPLOADING),
            "uploaded": await count_by_status(STATUS_UPLOADED),
            "failed": await count_by_status(STATUS_FAILED),
            "skipped": await count_by_status(STATUS_SKIPPED),
        },
        "shard_count": shard_count(),
        "generated_at": time.time(),
    }


# ============================================================
# SECTION 11 — EXTRACTION HELPERS
# ============================================================

def _extract_file_id(doc: Dict[str, Any]) -> Optional[str]:
    if not doc:
        return None
    for k in ("file_id", "_id", "id"):
        v = doc.get(k)
        if v:
            return str(v)
    return None


def _extract_file_name(doc: Dict[str, Any]) -> str:
    for k in ("file_name", "name", "title"):
        v = doc.get(k)
        if v:
            return str(v)[:200]
    return ""


def _extract_file_size(doc: Dict[str, Any]) -> int:
    try:
        return int(doc.get("file_size", 0) or 0)
    except Exception:
        return 0


# ============================================================
# SECTION 12 — RUN HISTORY
# ============================================================

async def create_run(
    started_by: int = 0,
) -> Optional[str]:
    """Start a new backup run. Returns run id."""
    c = _runs_coll()
    if c is None:
        return None
    try:
        doc = {
            "started_at": datetime.utcnow(),
            "started_by": int(started_by),
            "status": "RUNNING",
            "uploaded": 0,
            "failed": 0,
            "skipped": 0,
            "total": 0,
        }
        r = await c.insert_one(doc)
        return str(r.inserted_id)
    except Exception as e:
        logger.warning(f"[STATE] create run: {e}")
        return None


async def finish_run(
    run_id: str,
    status: str = "COMPLETED",
    stats: Optional[Dict[str, int]] = None,
) -> bool:
    """Close a run with final stats."""
    c = _runs_coll()
    if c is None or not run_id:
        return False

    try:
        from bson import ObjectId
        patch: Dict[str, Any] = {
            "status": str(status),
            "finished_at": datetime.utcnow(),
        }
        if stats:
            patch.update({
                "uploaded": int(stats.get("uploaded", 0)),
                "failed": int(stats.get("failed", 0)),
                "skipped": int(stats.get("skipped", 0)),
                "total": int(stats.get("total", 0)),
            })
        await c.update_one(
            {"_id": ObjectId(run_id)},
            {"$set": patch},
        )
        return True
    except Exception as e:
        logger.debug(f"[STATE] finish run: {e}")
        return False


async def list_runs(limit: int = 12) -> List[Dict[str, Any]]:
    """Return most recent runs."""
    c = _runs_coll()
    if c is None:
        return []
    try:
        cursor = c.find({}).sort("started_at", -1).limit(int(limit))
        docs = await cursor.to_list(length=int(limit))
        return docs
    except Exception:
        return []


async def clear_runs() -> int:
    """Delete all run history."""
    c = _runs_coll()
    if c is None:
        return 0
    try:
        r = await c.delete_many({})
        return r.deleted_count
    except Exception:
        return 0


# ============================================================
# SECTION 13 — PUBLIC EXPORTS
# ============================================================

__all__ = [
    # Constants
    "STATE_COLLECTION", "RUNS_COLLECTION",
    "TOKEN_PREFIX", "SOURCE_DB_ORDER",
    "STATUS_PENDING", "STATUS_UPLOADING", "STATUS_UPLOADED",
    "STATUS_FAILED", "STATUS_SKIPPED",
    "ALL_STATUSES",
    # Shard helpers
    "list_shards", "shard_count", "shard_of",
    # Token
    "backup_token",
    # Setup
    "ensure_indexes",
    # Read
    "get_state", "get_status", "find_by_token", "find_by_message_id",
    # Write
    "set_state",
    "mark_pending", "mark_uploading", "mark_uploaded",
    "mark_failed", "mark_skipped",
    # Counts
    "count_by_status", "count_per_shard", "count_by_source_db",
    # Iterate
    "iter_by_status", "list_failed", "list_recent",
    # Bulk
    "reset_failed", "reset_uploading", "wipe_all",
    "delete_file_state",
    # Stats
    "stats",
    # Runs
    "create_run", "finish_run", "list_runs", "clear_runs",
]
