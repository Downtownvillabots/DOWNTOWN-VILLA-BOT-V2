# ============================================================
# 🏨 DOWNTOWN VILLA — INDEXING WORKER (final)
# ============================================================
#
# Bots cannot use messages.GetHistory (BOT_METHOD_INVALID).
# We walk message IDs via get_messages(...) — bot-safe.
#
# Duplicate detection checks EVERY online shard directly,
# trying every relevant key (_id, fingerprint, file_id,
# file_unique_id). No bloom shortcut.
#
# Indexes are auto-created on first run.
#
# ============================================================

from __future__ import annotations

import asyncio
import logging
import os
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
# CONSTANTS
# ============================================================

CHECKPOINT_EVERY = 25
PROGRESS_UPDATE_EVERY = 5.0
MAX_RUNTIME = 24 * 3600
FLOOD_HARD_SLEEP = 3600

try:
    MAX_PROBE_ID = int(os.getenv("INDEXING_MAX_ID", "100000"))
except (TypeError, ValueError):
    MAX_PROBE_ID = 100000
MAX_PROBE_ID = max(1000, MAX_PROBE_ID)

try:
    EMPTY_BATCH_LIMIT = int(os.getenv("INDEXING_EMPTY_BATCH_LIMIT", "5"))
except (TypeError, ValueError):
    EMPTY_BATCH_LIMIT = 5
EMPTY_BATCH_LIMIT = max(2, EMPTY_BATCH_LIMIT)

SUMMARY_EVERY = 100

# Guard so we only create indexes once per boot
_indexes_ready = False


# ============================================================
# STATE
# ============================================================

STATE: Dict[str, Any] = {
    "running": False,
    "paused": False,
    "stop_requested": False,

    "channel_id": None,
    "channel_title": "",
    "mode": "both",
    "direction": "backward",
    "range_mode": "last",
    "start_msg_id": None,
    "metadata_source": "both",
    "batch_size": 200,
    "concurrency": 20,
    "delay": 0.3,
    "skip_duplicate": True,
    "auto_pause": True,
    "owner": 0,

    "job_id": None,
    "run_id": None,
    "started_at": None,
    "finished_at": None,
    "total_messages": 0,
    "current_message_id": 0,
    "end_message_id": 0,
    "scanned_ids": 0,

    "processed": 0,
    "saved": 0,
    "duplicate_id": 0,
    "dups_checked": 0,
    "skipped_no_media": 0,
    "skipped_no_file_id": 0,
    "failed": 0,
    "movies": 0,
    "series": 0,

    "speed": 0.0,
    "eta_seconds": 0.0,
    "eta_text": "—",
    "last_progress_at": 0.0,

    "last_error": None,
    "flood_until": 0.0,
}

_task: Optional[asyncio.Task] = None
_state_lock = asyncio.Lock()


# ============================================================
# PUBLIC API
# ============================================================

def is_running() -> bool:
    return bool(STATE["running"])


def status() -> Dict[str, Any]:
    return {
        "running": STATE["running"],
        "paused": STATE["paused"],
        "channel_id": STATE["channel_id"],
        "channel_title": STATE["channel_title"],
        "mode": STATE["mode"],
        "direction": STATE["direction"],
        "range_mode": STATE["range_mode"],
        "metadata_source": STATE["metadata_source"],
        "job_id": STATE["job_id"],
        "total_messages": STATE["total_messages"],
        "current_message_id": STATE["current_message_id"],
        "scanned_ids": STATE["scanned_ids"],
        "processed": STATE["processed"],
        "saved": STATE["saved"],
        "duplicate_id": STATE["duplicate_id"],
        "dups_checked": STATE["dups_checked"],
        "skipped_no_media": STATE["skipped_no_media"],
        "skipped_no_file_id": STATE["skipped_no_file_id"],
        "failed": STATE["failed"],
        "movies": STATE["movies"],
        "series": STATE["series"],
        "speed": STATE["speed"],
        "eta_seconds": STATE["eta_seconds"],
        "eta_text": STATE["eta_text"],
        "started_at": STATE["started_at"],
        "finished_at": STATE["finished_at"],
        "last_error": STATE["last_error"],
    }


async def start_worker(
    channel_id: int,
    mode: str = "both",
    direction: str = "backward",
    start_msg_id: Optional[int] = None,
    range_mode: str = "last",
    metadata_source: str = "both",
    batch_size: int = 200,
    concurrency: int = 20,
    delay: float = 0.3,
    skip_duplicate: bool = True,
    auto_pause: bool = True,
    owner: int = 0,
) -> bool:
    global _task

    logger.info(
        f"[INDEX-WORKER] ▶️ start_worker — "
        f"channel={channel_id} mode={mode} dir={direction} "
        f"range={range_mode} meta={metadata_source}"
    )

    async with _state_lock:
        if STATE["running"]:
            logger.warning("[INDEX-WORKER] already running")
            return False
        if _task and not _task.done():
            logger.warning("[INDEX-WORKER] task exists")
            return False

        STATE.update({
            "running": True,
            "paused": False,
            "stop_requested": False,
            "channel_id": int(channel_id),
            "channel_title": "",
            "mode": str(mode),
            "direction": str(direction),
            "range_mode": str(range_mode),
            "start_msg_id": int(start_msg_id) if start_msg_id else None,
            "metadata_source": str(metadata_source or "both"),
            "batch_size": max(10, min(1000, int(batch_size))),
            "concurrency": max(1, min(100, int(concurrency))),
            "delay": max(0.0, min(5.0, float(delay))),
            "skip_duplicate": bool(skip_duplicate),
            "auto_pause": bool(auto_pause),
            "owner": int(owner),
            "job_id": (
                f"INDEX-{datetime.utcnow().strftime('%Y%m%d-%H%M%S')}"
                f"-{uuid.uuid4().hex[:4]}"
            ),
            "run_id": None,
            "started_at": time.time(),
            "finished_at": None,
            "total_messages": 0,
            "current_message_id": 0,
            "end_message_id": 0,
            "scanned_ids": 0,
            "processed": 0,
            "saved": 0,
            "duplicate_id": 0,
            "dups_checked": 0,
            "skipped_no_media": 0,
            "skipped_no_file_id": 0,
            "failed": 0,
            "movies": 0,
            "series": 0,
            "speed": 0.0,
            "eta_seconds": 0.0,
            "eta_text": "—",
            "last_progress_at": 0.0,
            "last_error": None,
            "flood_until": 0.0,
        })

    _task = asyncio.create_task(_run())
    logger.info("[INDEX-WORKER] ▶️ task created")
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
# INDEX SETUP (auto, once per boot)
# ============================================================

async def _ensure_indexes() -> None:
    """
    Create indexes on every online media shard.
    Called once at the start of _run(); skips if already done.
    """
    global _indexes_ready
    if _indexes_ready:
        return

    try:
        from database import db_registry
        entries = db_registry.media_entries()
    except Exception as e:
        logger.warning(f"[INDEX-WORKER] cannot list shards: {e}")
        return

    for e in entries:
        if not e.online:
            continue
        try:
            coll = e.db["media_files"]
            await coll.create_index("file_id", name="file_id_idx",
                                    background=True)
            await coll.create_index("file_unique_id",
                                    name="file_unique_id_idx",
                                    background=True, sparse=True)
            await coll.create_index("fingerprint",
                                    name="fingerprint_idx",
                                    background=True, sparse=True)
            await coll.create_index("file_type",
                                    name="file_type_idx",
                                    background=True, sparse=True)
            await coll.create_index("normalized_title",
                                    name="norm_title_idx",
                                    background=True, sparse=True)
            await coll.create_index("created_at",
                                    name="created_at_idx",
                                    background=True)
            logger.info(f"[INDEX-WORKER] 🧩 indexes ok on {e.label}")
        except Exception as ex:
            logger.debug(f"[INDEX-WORKER] index {e.label}: {ex}")

    _indexes_ready = True


# ============================================================
# MAIN LOOP
# ============================================================

async def _run() -> None:
    logger.info(
        f"[INDEX-WORKER] 🚀 _run channel={STATE['channel_id']} "
        f"mode={STATE['mode']} dir={STATE['direction']} "
        f"range={STATE['range_mode']}"
    )

    try:
        from core.client import client as C
        if C is None:
            STATE["last_error"] = "client not ready"
            logger.error("[INDEX-WORKER] ❌ client None")
            return
        logger.info("[INDEX-WORKER] ✅ client ready")

        # Ensure indexes (fast no-op after first run)
        try:
            await _ensure_indexes()
        except Exception as e:
            logger.debug(f"[INDEX-WORKER] index setup: {e}")

        # Job doc
        try:
            from plugins.indexing import state as ST
            STATE["run_id"] = await ST.create_job({
                "job_id": STATE["job_id"],
                "kind": "manual",
                "channel_id": STATE["channel_id"],
                "channel_title": STATE["channel_title"],
                "mode": STATE["mode"],
                "direction": STATE["direction"],
                "range_mode": STATE["range_mode"],
                "metadata_source": STATE["metadata_source"],
                "start_message_id": STATE["start_msg_id"] or 0,
                "current_message_id": STATE["start_msg_id"] or 0,
                "status": "running",
                "owner": STATE["owner"],
                "batch_size": STATE["batch_size"],
                "concurrency": STATE["concurrency"],
                "delay": STATE["delay"],
                "skip_duplicate": STATE["skip_duplicate"],
            })
            logger.info(f"[INDEX-WORKER] 📋 job_id={STATE['run_id']}")
        except Exception as e:
            logger.warning(f"[INDEX-WORKER] create job: {e}")

        # Channel title
        try:
            chat = await C.get_chat(STATE["channel_id"])
            STATE["channel_title"] = chat.title or str(STATE["channel_id"])
            logger.info(
                f"[INDEX-WORKER] ✅ channel: '{STATE['channel_title']}'"
            )
        except Exception as e:
            STATE["last_error"] = f"cannot access channel: {e}"
            logger.error(f"[INDEX-WORKER] ❌ cannot access: {e}")
            return

        # Range
        start_id, end_id = _resolve_range()
        STATE["start_msg_id"] = start_id
        STATE["current_message_id"] = start_id
        STATE["end_message_id"] = end_id
        total_ids = abs(end_id - start_id) + 1
        STATE["total_messages"] = total_ids

        logger.info(
            f"[INDEX-WORKER] 📊 range: {start_id} → {end_id} "
            f"({total_ids} IDs)"
        )

        await _walk_messages(C, start_id, end_id)
        await _finalize()

    except asyncio.CancelledError:
        STATE["last_error"] = "cancelled"
        await _finalize("cancelled")
        raise
    except Exception as e:
        logger.exception(f"[INDEX-WORKER] ❌ crash: {e}")
        STATE["last_error"] = str(e)[:200]
        await _finalize("error")
    finally:
        STATE["running"] = False
        STATE["paused"] = False
        STATE["finished_at"] = time.time()
        logger.info(
            f"[INDEX-WORKER] 🏁 DONE — "
            f"scanned={STATE['scanned_ids']} processed={STATE['processed']} "
            f"saved={STATE['saved']} dup={STATE['duplicate_id']} "
            f"checked={STATE['dups_checked']} "
            f"no_media={STATE['skipped_no_media']} failed={STATE['failed']}"
        )


# ============================================================
# RANGE
# ============================================================

def _resolve_range() -> Tuple[int, int]:
    range_mode = STATE["range_mode"]
    direction = STATE["direction"]
    user_start = STATE["start_msg_id"]

    if range_mode == "custom" and user_start:
        start = max(1, int(user_start))
    elif range_mode == "last":
        start = MAX_PROBE_ID
    else:
        start = 1

    if direction == "forward":
        end = MAX_PROBE_ID
    else:
        end = 1

    return (start, end)


# ============================================================
# WALK
# ============================================================

async def _walk_messages(C: Client, start_id: int, end_id: int) -> None:
    direction = STATE["direction"]
    batch_size = STATE["batch_size"]

    if direction == "forward":
        step = 1
        def stop_when(x): return x > end_id
    else:
        step = -1
        def stop_when(x): return x < end_id

    next_id = start_id
    last_checkpoint = start_id
    last_progress_update = 0.0
    start_time = time.time()
    batch_num = 0
    consecutive_empty = 0
    seen_any = False

    while not stop_when(next_id):
        if time.time() - start_time > MAX_RUNTIME:
            STATE["last_error"] = "runtime cap reached"
            break

        if STATE["stop_requested"]:
            break

        while STATE["paused"] and not STATE["stop_requested"]:
            fu = float(STATE.get("flood_until") or 0.0)
            if fu and fu <= time.time():
                STATE["flood_until"] = 0.0
                STATE["paused"] = False
                break
            await asyncio.sleep(1.0)

        if STATE["stop_requested"]:
            break

        if STATE["flood_until"] > time.time():
            await asyncio.sleep(min(5.0, STATE["flood_until"] - time.time()))
            continue

        batch: List[int] = []
        for _ in range(batch_size):
            if stop_when(next_id):
                break
            batch.append(next_id)
            next_id += step

        if not batch:
            break

        batch_num += 1

        got_any = await _process_batch(C, batch)
        STATE["scanned_ids"] += len(batch)

        if got_any:
            consecutive_empty = 0
            seen_any = True
        else:
            consecutive_empty += 1
            if seen_any and consecutive_empty >= EMPTY_BATCH_LIMIT:
                logger.info(
                    f"[INDEX-WORKER] ⏹️ {consecutive_empty} empty "
                    f"batches → stopping early"
                )
                break
            if not seen_any and consecutive_empty >= EMPTY_BATCH_LIMIT * 3:
                logger.warning(
                    f"[INDEX-WORKER] ⚠️ {consecutive_empty} empty "
                    f"from start → channel empty or IDs high"
                )
                break

        if batch_num <= 3 or batch_num % 10 == 0:
            logger.info(
                f"[INDEX-WORKER] 📦 batch #{batch_num} "
                f"ids={batch[0]}..{batch[-1]}"
            )

        if abs(next_id - last_checkpoint) >= CHECKPOINT_EVERY:
            last_checkpoint = next_id
            await _save_checkpoint(next_id)

        if time.time() - last_progress_update >= PROGRESS_UPDATE_EVERY:
            last_progress_update = time.time()
            _update_speed()
            logger.info(
                f"[INDEX-WORKER] 📈 scanned={STATE['scanned_ids']} "
                f"processed={STATE['processed']} saved={STATE['saved']} "
                f"dup={STATE['duplicate_id']} "
                f"checked={STATE['dups_checked']} "
                f"failed={STATE['failed']}"
            )

        if STATE["delay"] > 0:
            await asyncio.sleep(STATE["delay"])


# ============================================================
# BATCH
# ============================================================

async def _process_batch(C: Client, batch: List[int]) -> bool:
    try:
        msgs = await C.get_messages(STATE["channel_id"], message_ids=batch)
        if not isinstance(msgs, list):
            msgs = [msgs]
    except FloodWait as e:
        wait = int(getattr(e, "value", 30) or 30)
        if wait > FLOOD_HARD_SLEEP:
            STATE["last_error"] = f"flood too long ({wait}s)"
            STATE["stop_requested"] = True
            return False
        STATE["flood_until"] = time.time() + wait
        if STATE["auto_pause"]:
            STATE["paused"] = True
        return False
    except RPCError as e:
        STATE["last_error"] = str(e)[:200]
        return False
    except Exception:
        return False

    valid = [
        m for m in msgs
        if m is not None and not getattr(m, "empty", False)
    ]
    if not valid:
        return False

    sem = asyncio.Semaphore(STATE["concurrency"])
    tasks = [_process_one(C, m, sem) for m in valid]
    await asyncio.gather(*tasks, return_exceptions=True)

    try:
        STATE["current_message_id"] = max(m.id for m in valid)
    except Exception:
        pass

    return True


async def _process_one(C: Client, msg, sem: asyncio.Semaphore) -> None:
    async with sem:
        if STATE["stop_requested"]:
            return
        await _handle_message(C, msg)


async def _handle_message(C: Client, msg) -> None:
    STATE["processed"] += 1

    try:
        media = _pick_media(msg)
        if not media:
            STATE["skipped_no_media"] += 1
            return

        file_id = media.get("file_id")
        if not file_id:
            STATE["skipped_no_file_id"] += 1
            return

        if STATE["skip_duplicate"]:
            STATE["dups_checked"] += 1
            try:
                file_unique_id = media.get("file_unique_id")
                if await _is_exact_duplicate(file_id, file_unique_id):
                    STATE["duplicate_id"] += 1
                    logger.info(
                        f"[INDEX-WORKER] ♻️ DUP msg={msg.id} "
                        f"file_id={file_id[:30]}..."
                    )
                    return
            except Exception as e:
                logger.debug(f"[INDEX-WORKER] dup: {e}")

        try:
            from plugins.indexing.pipeline import process_message
            result = await process_message(
                msg,
                mode="manual",
                metadata_source=STATE["metadata_source"],
            )
        except Exception as e:
            logger.exception(f"[INDEX-WORKER] pipeline crash: {e}")
            STATE["failed"] += 1
            STATE["last_error"] = str(e)[:200]
            return

        status = result.get("status")

        if status == "saved":
            STATE["saved"] += 1
            rec = result.get("record") or {}
            rtype = str(rec.get("type") or "").lower()
            title_dbg = (
                rec.get("title")
                or rec.get("series_title")
                or rec.get("file_name")
                or "?"
            )
            if rtype == "movie":
                STATE["movies"] += 1
            elif rtype == "series":
                STATE["series"] += 1
            logger.info(
                f"[INDEX-WORKER] ✅ SAVED msg={msg.id} "
                f"type={rtype or 'unknown'} "
                f"title='{str(title_dbg)[:60]}'"
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

        if STATE["processed"] % SUMMARY_EVERY == 0:
            logger.info(
                f"[INDEX-WORKER] 📊 summary @{STATE['processed']} — "
                f"saved={STATE['saved']} dup={STATE['duplicate_id']} "
                f"checked={STATE['dups_checked']} "
                f"fail={STATE['failed']}"
            )

    except Exception:
        STATE["failed"] += 1


# ============================================================
# HELPERS
# ============================================================

def _pick_media(msg) -> Optional[Dict[str, Any]]:
    try:
        if getattr(msg, "video", None):
            v = msg.video
            return {"file_id": v.file_id,
                    "file_unique_id": v.file_unique_id}
        if getattr(msg, "document", None):
            d = msg.document
            return {"file_id": d.file_id,
                    "file_unique_id": d.file_unique_id}
        if getattr(msg, "audio", None):
            a = msg.audio
            return {"file_id": a.file_id,
                    "file_unique_id": a.file_unique_id}
        if getattr(msg, "animation", None):
            an = msg.animation
            return {"file_id": an.file_id,
                    "file_unique_id": an.file_unique_id}
    except Exception:
        pass
    return None


async def _is_exact_duplicate(
    file_id: str,
    file_unique_id: Optional[str] = None,
) -> bool:
    """
    Walk every online media shard, try every key:
      _id, fingerprint, file_id, file_unique_id
    """
    if not file_id and not file_unique_id:
        return False

    fp: Optional[str] = None
    try:
        from services.duplicate import compute_fingerprint
        fp = compute_fingerprint(file_id) if file_id else None
    except Exception:
        fp = None

    queries: List[Dict[str, Any]] = []
    if fp:
        queries.append({"_id": fp})
        queries.append({"fingerprint": fp})
    if file_id:
        queries.append({"file_id": file_id})
    if file_unique_id:
        queries.append({"file_unique_id": file_unique_id})

    if not queries:
        return False

    try:
        from database import db_registry
        entries = db_registry.media_entries()
    except Exception:
        return False

    for entry in entries:
        if not entry.online:
            continue
        for q in queries:
            try:
                doc = await entry.db["media_files"].find_one(q, {"_id": 1})
                if doc:
                    key_name = list(q.keys())[0]
                    logger.info(
                        f"[INDEX-WORKER] ♻️ DUP hit "
                        f"shard=DB{entry.index} key={key_name}"
                    )
                    return True
            except Exception:
                continue

    return False


def _update_speed() -> None:
    try:
        if not STATE["started_at"]:
            return
        elapsed = max(0.001, time.time() - STATE["started_at"])
        STATE["speed"] = STATE["processed"] / elapsed
    except Exception:
        pass


async def _save_checkpoint(current_msg_id: int) -> None:
    if not STATE["run_id"]:
        return
    try:
        from plugins.indexing import state as ST
        await ST.set_checkpoint(STATE["run_id"], current_msg_id)
    except Exception:
        pass


async def _finalize(status: Optional[str] = None) -> None:
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
        await ST.update_stats(STATE["run_id"], {
            "processed": STATE["processed"],
            "saved": STATE["saved"],
            "duplicate_id": STATE["duplicate_id"],
            "dups_checked": STATE["dups_checked"],
            "skipped_no_media": STATE["skipped_no_media"],
            "skipped_no_file_id": STATE["skipped_no_file_id"],
            "failed": STATE["failed"],
            "movies": STATE["movies"],
            "series": STATE["series"],
        })
    except Exception as e:
        logger.debug(f"[INDEX-WORKER] finalize: {e}")


__all__ = [
    "start_worker", "stop_worker", "pause_worker", "resume_worker",
    "is_running", "status",
]
