# ============================================================
# 🏨 DOWNTOWN VILLA — INDEXING WORKER (ULTIMATE)
# ============================================================
#
# THE actual indexing engine.
#
# RULES (LOCKED):
#   • Only skips files with SAME FILE_ID (exact duplicate)
#   • Every other file is imported
#   • Never skips for: no caption, bad name, missing metadata,
#     wrong year, unknown quality, etc.
#
# CONFIG (from /index panel):
#   channel_id       — source channel
#   mode             — movies | series | both
#   direction        — forward | backward
#   range_mode       — first | last | custom
#   start_msg_id     — custom start (if range=custom)
#   batch_size       — 50..500
#   concurrency      — 5..50
#   delay            — 0..1s
#   skip_duplicate   — True/False
#   auto_pause       — pause on flood
#
# CRASH SAFETY:
#   Every CHECKPOINT_EVERY processed messages → save checkpoint
#   On restart, resume from checkpoint via state.py
#
# ============================================================

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from pyrogram import Client
from pyrogram.errors import FloodWait, RPCError

from core import config
from utils import format as FM

logger = logging.getLogger(__name__)


# ============================================================
# SECTION 1 — CONSTANTS
# ============================================================

CHECKPOINT_EVERY = 25
PROGRESS_UPDATE_EVERY = 5     # seconds
MAX_RUNTIME = 24 * 3600        # safety cap
FLOOD_HARD_SLEEP = 3600        # if flood > this, we bail


# ============================================================
# SECTION 2 — RUNTIME STATE
# ============================================================

STATE: Dict[str, Any] = {
    # Status
    "running": False,
    "paused": False,
    "stop_requested": False,

    # Config (set on start)
    "channel_id": None,
    "channel_title": "",
    "mode": "both",
    "direction": "backward",
    "range_mode": "last",
    "start_msg_id": None,
    "batch_size": 100,
    "concurrency": 20,
    "delay": 0.3,
    "skip_duplicate": True,
    "auto_pause": True,
    "owner": 0,

    # Progress
    "job_id": None,
    "run_id": None,
    "started_at": None,
    "finished_at": None,

    "total_messages": 0,
    "current_message_id": 0,
    "end_message_id": 0,

    "processed": 0,
    "saved": 0,
    "duplicate_id": 0,
    "skipped_no_media": 0,
    "skipped_no_file_id": 0,
    "failed": 0,
    "movies": 0,
    "series": 0,

    # Speed
    "speed": 0.0,
    "eta_seconds": 0.0,
    "eta_text": "—",
    "last_progress_at": 0.0,

    # Errors
    "last_error": None,
    "flood_until": 0.0,
}


_task: Optional[asyncio.Task] = None
_state_lock = asyncio.Lock()


# ============================================================
# SECTION 3 — PUBLIC API
# ============================================================

def is_running() -> bool:
    return bool(STATE["running"])


def status() -> Dict[str, Any]:
    """Live snapshot for the panel."""
    return {
        "running": STATE["running"],
        "paused": STATE["paused"],
        "channel_id": STATE["channel_id"],
        "channel_title": STATE["channel_title"],
        "mode": STATE["mode"],
        "direction": STATE["direction"],
        "range_mode": STATE["range_mode"],
        "job_id": STATE["job_id"],
        "total_messages": STATE["total_messages"],
        "current_message_id": STATE["current_message_id"],
        "processed": STATE["processed"],
        "saved": STATE["saved"],
        "duplicate_id": STATE["duplicate_id"],
        "skipped_no_media": STATE["skipped_no_media"],
        "skipped_no_file_id": STATE["skipped_no_file_id"],
        "failed": STATE["failed"],
        "movies": STATE["movies"],
        "series": STATE["series"],
        "speed": STATE["speed"],
        "eta_seconds": STATE["eta_seconds"],
        "eta_text": STATE["eta_text"],
        "started_at": STATE["started_at"],
        "last_error": STATE["last_error"],
    }


async def start_worker(
    channel_id: int,
    mode: str = "both",
    direction: str = "backward",
    start_msg_id: Optional[int] = None,
    range_mode: str = "last",
    batch_size: int = 100,
    concurrency: int = 20,
    delay: float = 0.3,
    skip_duplicate: bool = True,
    auto_pause: bool = True,
    owner: int = 0,
) -> bool:
    """Start a new indexing job."""
    global _task

    async with _state_lock:
        if STATE["running"]:
            return False
        if _task and not _task.done():
            return False

        # Apply config
        STATE["running"] = True
        STATE["paused"] = False
        STATE["stop_requested"] = False

        STATE["channel_id"] = int(channel_id)
        STATE["channel_title"] = ""
        STATE["mode"] = str(mode)
        STATE["direction"] = str(direction)
        STATE["range_mode"] = str(range_mode)
        STATE["start_msg_id"] = int(start_msg_id) if start_msg_id else None
        STATE["batch_size"] = max(10, min(1000, int(batch_size)))
        STATE["concurrency"] = max(1, min(100, int(concurrency)))
        STATE["delay"] = max(0.0, min(5.0, float(delay)))
        STATE["skip_duplicate"] = bool(skip_duplicate)
        STATE["auto_pause"] = bool(auto_pause)
        STATE["owner"] = int(owner)

        # Reset counters
        STATE["job_id"] = f"INDEX-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:4]}"
        STATE["run_id"] = None
        STATE["started_at"] = time.time()
        STATE["finished_at"] = None

        STATE["total_messages"] = 0
        STATE["current_message_id"] = 0
        STATE["end_message_id"] = 0

        STATE["processed"] = 0
        STATE["saved"] = 0
        STATE["duplicate_id"] = 0
        STATE["skipped_no_media"] = 0
        STATE["skipped_no_file_id"] = 0
        STATE["failed"] = 0
        STATE["movies"] = 0
        STATE["series"] = 0

        STATE["speed"] = 0.0
        STATE["eta_seconds"] = 0.0
        STATE["eta_text"] = "—"
        STATE["last_progress_at"] = 0.0

        STATE["last_error"] = None
        STATE["flood_until"] = 0.0

    _task = asyncio.create_task(_run())
    return True


async def stop_worker() -> bool:
    if not STATE["running"]:
        return False
    STATE["stop_requested"] = True
    return True


def pause_worker() -> bool:
    if not STATE["running"] or STATE["paused"]:
        return False
    STATE["paused"] = True
    return True


def resume_worker() -> bool:
    if not STATE["paused"]:
        return False
    STATE["paused"] = False
    return True


# ============================================================
# SECTION 4 — MAIN LOOP
# ============================================================

async def _run() -> None:
    """Main indexing worker coroutine."""
    logger.info(
        f"[INDEX-WORKER] starting — channel={STATE['channel_id']} "
        f"mode={STATE['mode']} dir={STATE['direction']}"
    )

    try:
        # Get client
        from core.client import client as C
        if C is None:
            STATE["last_error"] = "client not ready"
            return

        # Create job in DB
        try:
            from plugins.indexing import state as ST
            db_id = await ST.create_job({
                "job_id": STATE["job_id"],
                "kind": "manual",
                "channel_id": STATE["channel_id"],
                "channel_title": STATE["channel_title"],
                "mode": STATE["mode"],
                "direction": STATE["direction"],
                "start_message_id": STATE["start_msg_id"] or 0,
                "current_message_id": STATE["start_msg_id"] or 0,
                "status": "running",
                "owner": STATE["owner"],
                "batch_size": STATE["batch_size"],
                "concurrency": STATE["concurrency"],
                "delay": STATE["delay"],
                "skip_duplicate": STATE["skip_duplicate"],
            })
            STATE["run_id"] = db_id
        except Exception as e:
            logger.debug(f"[INDEX-WORKER] create job: {e}")

        # Resolve channel + start/end message ids
        try:
            chat = await C.get_chat(STATE["channel_id"])
            STATE["channel_title"] = chat.title or str(STATE["channel_id"])
        except Exception as e:
            STATE["last_error"] = f"cannot access channel: {e}"
            return

        start_id, end_id, total = await _resolve_range(C)
        STATE["start_msg_id"] = start_id
        STATE["current_message_id"] = start_id
        STATE["end_message_id"] = end_id
        STATE["total_messages"] = total

        logger.info(
            f"[INDEX-WORKER] range: {start_id} → {end_id} "
            f"(total={total})"
        )

        if total == 0:
            STATE["last_error"] = "no messages in range"
            return

        # Main loop
        await _walk_messages(C, start_id, end_id)

        # Finalize
        await _finalize()

    except asyncio.CancelledError:
        STATE["last_error"] = "cancelled"
        await _finalize("cancelled")
        raise
    except Exception as e:
        logger.exception(f"[INDEX-WORKER] crash: {e}")
        STATE["last_error"] = str(e)[:200]
        await _finalize("error")
    finally:
        STATE["running"] = False
        STATE["paused"] = False
        STATE["finished_at"] = time.time()


# ============================================================
# SECTION 5 — RESOLVE RANGE
# ============================================================

async def _resolve_range(C: Client) -> Tuple[int, int, int]:
    """Return (start_id, end_id, total_count)."""
    channel_id = STATE["channel_id"]
    range_mode = STATE["range_mode"]
    direction = STATE["direction"]

    # Get newest message
    newest_id = 1
    try:
        async for msg in C.get_chat_history(channel_id, limit=1):
            newest_id = msg.id
            break
    except Exception as e:
        logger.debug(f"[INDEX-WORKER] newest: {e}")
        return (1, 1, 0)

    if range_mode == "custom" and STATE["start_msg_id"]:
        start_id = int(STATE["start_msg_id"])
    elif range_mode == "first":
        start_id = 1
    else:  # "last"
        start_id = newest_id

    if direction == "forward":
        # start at start_id, go up to newest_id
        start = max(1, min(start_id, newest_id))
        end = newest_id
    else:
        # backward: start at start_id, go down to 1
        start = max(1, min(start_id, newest_id))
        end = 1

    total = abs(start - end) + 1
    return (start, end, total)


# ============================================================
# SECTION 6 — WALK MESSAGES
# ============================================================

async def _walk_messages(C: Client, start_id: int, end_id: int) -> None:
    """Walk from start_id → end_id in chosen direction."""
    direction = STATE["direction"]
    batch_size = STATE["batch_size"]

    if direction == "forward":
        step = 1
        next_id = start_id
        stop_when = lambda x: x > end_id
    else:
        step = -1
        next_id = start_id
        stop_when = lambda x: x < end_id

    last_checkpoint = start_id
    last_progress_update = 0.0
    start_time = time.time()

    while not stop_when(next_id):
        # Check runtime cap
        if time.time() - start_time > MAX_RUNTIME:
            STATE["last_error"] = "runtime cap reached"
            break

        # Check stop
        if STATE["stop_requested"]:
            break

        # Handle pause
        while STATE["paused"] and not STATE["stop_requested"]:
            await asyncio.sleep(1.0)

        if STATE["stop_requested"]:
            break

        # Wait if flood cooldown is active
        if STATE["flood_until"] > time.time():
            await asyncio.sleep(min(5.0, STATE["flood_until"] - time.time()))
            continue

        # Build batch
        batch = []
        for _ in range(batch_size):
            if stop_when(next_id):
                break
            batch.append(next_id)
            next_id += step

        if not batch:
            break

        # Process batch
        await _process_batch(C, batch)

        # Update checkpoint
        if abs(next_id - last_checkpoint) >= CHECKPOINT_EVERY:
            last_checkpoint = next_id
            await _save_checkpoint(next_id)

        # Update speed/ETA every few seconds
        if time.time() - last_progress_update >= PROGRESS_UPDATE_EVERY:
            last_progress_update = time.time()
            _update_speed()

        # Small delay between batches
        if STATE["delay"] > 0:
            await asyncio.sleep(STATE["delay"])


# ============================================================
# SECTION 7 — PROCESS BATCH
# ============================================================

async def _process_batch(C: Client, batch: List[int]) -> None:
    """Fetch + process a batch of messages."""
    try:
        msgs = await C.get_messages(STATE["channel_id"], message_ids=batch)
        if not isinstance(msgs, list):
            msgs = [msgs]
    except FloodWait as e:
        wait = int(getattr(e, "value", 30) or 30)
        if wait > FLOOD_HARD_SLEEP:
            STATE["last_error"] = f"flood too long ({wait}s)"
            STATE["stop_requested"] = True
            return
        logger.warning(f"[INDEX-WORKER] flood wait {wait}s")
        STATE["flood_until"] = time.time() + wait
        if STATE["auto_pause"]:
            STATE["paused"] = True
        return
    except RPCError as e:
        logger.warning(f"[INDEX-WORKER] rpc: {e}")
        STATE["last_error"] = str(e)[:200]
        return
    except Exception as e:
        logger.exception(f"[INDEX-WORKER] batch fetch: {e}")
        return

    # Filter out None (deleted) messages
    valid = [m for m in msgs if m is not None and not getattr(m, "empty", False)]

    if not valid:
        return

    # Process concurrently
    sem = asyncio.Semaphore(STATE["concurrency"])
    tasks = [_process_one(C, m, sem) for m in valid]
    await asyncio.gather(*tasks, return_exceptions=True)

    # Update current message id to last in batch
    try:
        last = max(m.id for m in valid)
        STATE["current_message_id"] = last
    except Exception:
        pass


# ============================================================
# SECTION 8 — PROCESS ONE MESSAGE
# ============================================================

async def _process_one(C: Client, msg, sem: asyncio.Semaphore) -> None:
    """Process one message — save or skip."""
    async with sem:
        if STATE["stop_requested"]:
            return

        await _handle_message(C, msg)


async def _handle_message(C: Client, msg) -> None:
    """
    Handle ONE message.
    RULE: only skip if same file_id was already saved.
    Everything else gets imported (or fails loudly).
    """
    STATE["processed"] += 1

    try:
        # 1. Determine media presence
        media = _pick_media(msg)
        if not media:
            STATE["skipped_no_media"] += 1
            return

        file_id = media.get("file_id")
        if not file_id:
            STATE["skipped_no_file_id"] += 1
            return

        # 2. Check exact duplicate (same file_id) — the ONLY skip reason
        if STATE["skip_duplicate"]:
            is_dup = await _check_exact_duplicate(file_id)
            if is_dup:
                STATE["duplicate_id"] += 1
                return

        # 3. Process via pipeline
        try:
            from indexing.pipeline import process_message
            result = await process_message(msg, mode="manual")
        except Exception as e:
            logger.exception(f"[INDEX-WORKER] pipeline: {e}")
            STATE["failed"] += 1
            STATE["last_error"] = str(e)[:200]
            return

        status = result.get("status")

        # 4. Update counters
        if status == "saved":
            STATE["saved"] += 1
            rec = result.get("record") or {}
            rtype = str(rec.get("type") or "").lower()
            if rtype == "movie":
                STATE["movies"] += 1
            elif rtype == "series":
                STATE["series"] += 1
        elif status == "duplicate":
            STATE["duplicate_id"] += 1
        elif status == "skipped":
            # Pipeline didn't have media or file_id — count appropriately
            reason = str(result.get("reason") or "")
            if "file_id" in reason:
                STATE["skipped_no_file_id"] += 1
            else:
                STATE["skipped_no_media"] += 1
        else:
            STATE["failed"] += 1
            STATE["last_error"] = str(result.get("reason") or "unknown")[:200]

    except Exception as e:
        logger.exception(f"[INDEX-WORKER] handle: {e}")
        STATE["failed"] += 1


# ============================================================
# SECTION 9 — MEDIA PICKER
# ============================================================

def _pick_media(msg) -> Optional[Dict[str, Any]]:
    """Return the media dict for a message, or None."""
    try:
        if getattr(msg, "video", None):
            v = msg.video
            return {
                "file_id": v.file_id,
                "file_unique_id": v.file_unique_id,
                "kind": "video",
            }
        if getattr(msg, "document", None):
            d = msg.document
            return {
                "file_id": d.file_id,
                "file_unique_id": d.file_unique_id,
                "kind": "document",
            }
        if getattr(msg, "audio", None):
            a = msg.audio
            return {
                "file_id": a.file_id,
                "file_unique_id": a.file_unique_id,
                "kind": "audio",
            }
        if getattr(msg, "animation", None):
            anim = msg.animation
            return {
                "file_id": anim.file_id,
                "file_unique_id": anim.file_unique_id,
                "kind": "animation",
            }
    except Exception:
        pass
    return None


# ============================================================
# SECTION 10 — EXACT DUPLICATE CHECK
# ============================================================

async def _check_exact_duplicate(file_id: str) -> bool:
    """
    Return True ONLY if the SAME file_id exists in any shard.
    This is the ONLY reason to skip a file.
    """
    try:
        from services.duplicate import compute_fingerprint, _bloom_check
    except Exception:
        # Fall back to direct check
        try:
            return await _check_by_file_id(file_id)
        except Exception:
            return False

    try:
        # Fast bloom check
        fp = compute_fingerprint(file_id)
        if _bloom_check(fp):
            return True

        # DB check across shards
        try:
            from database import db_registry
            for entry in db_registry.media_entries():
                try:
                    exists = await entry.db["media_files"].find_one(
                        {"_id": fp}, {"_id": 1}
                    )
                    if exists:
                        return True
                except Exception:
                    continue
        except Exception:
            pass

        return False

    except Exception:
        return False


async def _check_by_file_id(file_id: str) -> bool:
    """Fallback: check by file_id directly."""
    try:
        from database import db_registry
        for entry in db_registry.media_entries():
            try:
                exists = await entry.db["media_files"].find_one(
                    {"file_id": file_id}, {"_id": 1}
                )
                if exists:
                    return True
            except Exception:
                continue
    except Exception:
        pass
    return False


# ============================================================
# SECTION 11 — SPEED / ETA
# ============================================================

def _update_speed() -> None:
    """Recompute speed + ETA from started_at + counters."""
    try:
        if not STATE["started_at"]:
            return
        elapsed = max(0.001, time.time() - STATE["started_at"])
        STATE["speed"] = STATE["processed"] / elapsed

        # Remaining from total_messages
        total = STATE["total_messages"]
        done = STATE["processed"]

        if total > 0 and STATE["speed"] > 0:
            remaining = max(0, total - done)
            eta = remaining / STATE["speed"]
            STATE["eta_seconds"] = eta
            STATE["eta_text"] = FM.duration_short(eta) if eta > 0 else "—"
        else:
            STATE["eta_seconds"] = 0.0
            STATE["eta_text"] = "—"
    except Exception:
        pass


# ============================================================
# SECTION 12 — CHECKPOINT
# ============================================================

async def _save_checkpoint(current_msg_id: int) -> None:
    """Persist checkpoint to DB."""
    if not STATE["run_id"]:
        return
    try:
        from plugins.indexing import state as ST
        await ST.set_checkpoint(STATE["run_id"], current_msg_id)
    except Exception as e:
        logger.debug(f"[INDEX-WORKER] checkpoint: {e}")


# ============================================================
# SECTION 13 — FINALIZE
# ============================================================

async def _finalize(status: Optional[str] = None) -> None:
    """Mark job complete in DB."""
    if not STATE["run_id"]:
        return

    if status is None:
        if STATE["stop_requested"]:
            status = "stopped"
        elif STATE["last_error"]:
            status = "error"
        else:
            status = "completed"

    try:
        from plugins.indexing import state as ST
        await ST.set_status(STATE["run_id"], status, STATE["last_error"])

        # Update final stats
        await ST.update_stats(STATE["run_id"], {
            "processed": STATE["processed"],
            "saved": STATE["saved"],
            "duplicate_id": STATE["duplicate_id"],
            "skipped_no_media": STATE["skipped_no_media"],
            "skipped_no_file_id": STATE["skipped_no_file_id"],
            "failed": STATE["failed"],
            "movies": STATE["movies"],
            "series": STATE["series"],
        })

        logger.info(
            f"[INDEX-WORKER] finalized — status={status} "
            f"saved={STATE['saved']} dup={STATE['duplicate_id']} "
            f"failed={STATE['failed']}"
        )
    except Exception as e:
        logger.debug(f"[INDEX-WORKER] finalize: {e}")


# ============================================================
# SECTION 14 — SNAPSHOT
# ============================================================

def snapshot() -> Dict[str, Any]:
    return status()


# ============================================================
# PUBLIC EXPORTS
# ============================================================

__all__ = [
    "start_worker",
    "stop_worker",
    "pause_worker",
    "resume_worker",
    "is_running",
    "status",
    "snapshot",
]
