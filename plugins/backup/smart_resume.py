# ============================================================
# 🏨 DOWNTOWN VILLA — SMART RESUME (FAST SKIP)
# ============================================================
#
# FAST-PATH SKIP for already-uploaded files.
#
# THE PROBLEM:
#   When the worker starts, it iterates every source file and
#   checks state.py::get_status for each. On 500k+ files this
#   is slow — 500k DB round-trips = minutes of latency.
#
# THE SOLUTION:
#   Load every "recently uploaded" file_id into an in-memory
#   set ONCE at worker start. Then skip checks are O(1).
#
# WINDOW:
#   Default: 48 hours. Any file uploaded in this window is
#   considered "already done" and skipped. Older files are
#   re-checked via state.py (rare because full backup
#   completes within a day).
#
# SAFETY:
#   • Never skips a file that isn't in the window
#   • Cache is bounded (max 500k entries)
#   • Refreshed periodically
#   • Env-controlled window
#
# ============================================================

from __future__ import annotations

import asyncio
import logging
import os
import time
from datetime import datetime, timedelta
from typing import Any, Dict, Optional, Set, Tuple

from utils import format as FM

logger = logging.getLogger(__name__)


# ============================================================
# SECTION 1 — CONFIG
# ============================================================

# How long to consider a file "already uploaded"
def window_hours() -> int:
    try:
        return max(1, int(os.getenv("BACKUP_SMART_RESUME_HOURS", "48")))
    except (TypeError, ValueError):
        return 48


# Max entries in the cache (safety limit)
MAX_CACHE_ENTRIES = 500_000

# How often to refresh the cache from DB (seconds)
REFRESH_INTERVAL = 900.0   # 15 min


# ============================================================
# SECTION 2 — STATE
# ============================================================

# key: (source_db, file_id) → timestamp when cached
_uploaded_cache: Set[str] = set()
_cache_loaded_at: float = 0.0
_cache_size_at: int = 0
_cache_lock = asyncio.Lock()
_cache_ready: bool = False


def _key(source_db: str, file_id: str) -> str:
    return f"{source_db}|{file_id}"


# ============================================================
# SECTION 3 — PUBLIC API
# ============================================================

async def ensure_cache(force: bool = False) -> bool:
    """
    Load (or refresh) the smart-resume cache.
    Fast no-op if already loaded and fresh.
    """
    global _cache_loaded_at, _cache_ready

    # Already loaded and fresh?
    if not force and _cache_ready:
        age = time.time() - _cache_loaded_at
        if age < REFRESH_INTERVAL:
            return True

    async with _cache_lock:
        # Double-check inside lock
        if not force and _cache_ready:
            age = time.time() - _cache_loaded_at
            if age < REFRESH_INTERVAL:
                return True

        return await _load_cache()


async def refresh_cache() -> bool:
    """Force a reload from DB."""
    return await ensure_cache(force=True)


async def _load_cache() -> bool:
    """Load recent UPLOADED file_ids into memory."""
    global _cache_loaded_at, _cache_size_at, _cache_ready

    t0 = time.time()
    cutoff = datetime.utcnow() - timedelta(hours=window_hours())

    new_cache: Set[str] = set()
    scanned = 0

    try:
        from plugins.backup import state as ST

        # Query each online shard for recent UPLOADED docs
        for entry in ST.list_shards():
            if not entry.online:
                continue
            try:
                coll = entry.db[ST.STATE_COLLECTION]
                cursor = coll.find(
                    {
                        "status": ST.STATUS_UPLOADED,
                        "updated_at": {"$gte": cutoff},
                    },
                    {"source_db": 1, "file_id": 1, "_id": 0},
                ).batch_size(1000)

                async for doc in cursor:
                    scanned += 1
                    sdb = str(doc.get("source_db", ""))
                    fid = str(doc.get("file_id", ""))
                    if sdb and fid:
                        new_cache.add(_key(sdb, fid))
                    if len(new_cache) >= MAX_CACHE_ENTRIES:
                        logger.warning(
                            f"[SMART] cache cap reached "
                            f"({MAX_CACHE_ENTRIES} entries)"
                        )
                        break
            except Exception as e:
                logger.debug(f"[SMART] shard load: {e}")
                continue

            if len(new_cache) >= MAX_CACHE_ENTRIES:
                break

        # Swap in
        _uploaded_cache.clear()
        _uploaded_cache.update(new_cache)
        _cache_loaded_at = time.time()
        _cache_size_at = len(new_cache)
        _cache_ready = True

        elapsed = time.time() - t0
        logger.info(
            f"[SMART] loaded {len(new_cache)} recent uploads "
            f"in {elapsed:.2f}s (window={window_hours()}h)"
        )
        return True

    except Exception as e:
        logger.exception(f"[SMART] load failed: {e}")
        # Still mark ready so we don't block forever
        _cache_ready = True
        _cache_loaded_at = time.time()
        return False


# ============================================================
# SECTION 4 — SKIP CHECK
# ============================================================

def should_skip(source_db: str, file_id: str) -> bool:
    """
    Fast check: was this file uploaded within the window?
    Returns True → skip without a DB round-trip.
    Returns False → caller must do a full state lookup.
    """
    if not _cache_ready:
        return False
    if not source_db or not file_id:
        return False
    return _key(source_db, file_id) in _uploaded_cache


def is_cache_ready() -> bool:
    return _cache_ready


def mark_uploaded_local(source_db: str, file_id: str) -> None:
    """
    Add a file to the local cache so subsequent checks skip it.
    Called by the worker right after a successful upload.
    """
    if not source_db or not file_id:
        return
    try:
        if len(_uploaded_cache) >= MAX_CACHE_ENTRIES:
            # Evict first 10% (FIFO-ish)
            evict = list(_uploaded_cache)[: MAX_CACHE_ENTRIES // 10]
            for k in evict:
                _uploaded_cache.discard(k)
        _uploaded_cache.add(_key(source_db, file_id))
    except Exception:
        pass


def remove_from_cache(source_db: str, file_id: str) -> None:
    """Remove a file from the cache (e.g. after reset)."""
    if not source_db or not file_id:
        return
    _uploaded_cache.discard(_key(source_db, file_id))


def clear_cache() -> None:
    """Wipe the in-memory cache."""
    global _cache_ready, _cache_loaded_at, _cache_size_at
    _uploaded_cache.clear()
    _cache_ready = False
    _cache_loaded_at = 0.0
    _cache_size_at = 0


# ============================================================
# SECTION 5 — BACKGROUND REFRESH
# ============================================================

_refresh_task: Optional[asyncio.Task] = None


def ensure_background_refresh() -> None:
    """Start a background loop that refreshes the cache."""
    global _refresh_task
    if _refresh_task and not _refresh_task.done():
        return
    try:
        loop = asyncio.get_running_loop()
        _refresh_task = loop.create_task(_refresh_loop())
    except RuntimeError:
        pass


async def _refresh_loop() -> None:
    """Refresh the cache periodically."""
    while True:
        try:
            await asyncio.sleep(REFRESH_INTERVAL)
            if _cache_ready:
                await refresh_cache()
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.debug(f"[SMART] refresh loop: {e}")


async def stop_refresh() -> None:
    global _refresh_task
    if _refresh_task and not _refresh_task.done():
        _refresh_task.cancel()
        try:
            await _refresh_task
        except (asyncio.CancelledError, Exception):
            pass
    _refresh_task = None


# ============================================================
# SECTION 6 — STATS
# ============================================================

def cache_age() -> float:
    if not _cache_loaded_at:
        return 0.0
    return time.time() - _cache_loaded_at


def snapshot() -> Dict[str, Any]:
    return {
        "ready": _cache_ready,
        "entries": len(_uploaded_cache),
        "entries_cap": MAX_CACHE_ENTRIES,
        "loaded_at": _cache_loaded_at,
        "age": cache_age(),
        "age_text": FM.duration_short(cache_age()) if _cache_loaded_at else "—",
        "window_hours": window_hours(),
        "refresh_interval": REFRESH_INTERVAL,
        "refresh_running": bool(
            _refresh_task and not _refresh_task.done()
        ),
    }


# ============================================================
# PUBLIC EXPORTS
# ============================================================

__all__ = [
    "ensure_cache",
    "refresh_cache",
    "should_skip",
    "is_cache_ready",
    "mark_uploaded_local",
    "remove_from_cache",
    "clear_cache",
    "ensure_background_refresh",
    "stop_refresh",
    "window_hours",
    "snapshot",
]
