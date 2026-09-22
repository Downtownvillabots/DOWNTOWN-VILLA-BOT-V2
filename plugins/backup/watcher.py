# ============================================================
# 🏨 DOWNTOWN VILLA — BACKUP WATCHER (ULTIMATE)
# ============================================================
#
# Auto-detects new files and starts the backup worker.
#
# WHY THIS EXISTS:
#   The user should never have to open /backup and tap
#   START. When a new file is indexed, the watcher sees
#   it within N seconds and auto-starts the backup.
#
# DESIGN:
#   • Polls state.py::count_by_status(PENDING) every N sec
#   • Respects env BACKUP_AUTO_START
#   • Respects manual stop (cooldown after user stops)
#   • Debounce (waits 2 consecutive ticks before starting)
#   • Never fights with manual start/stop
#   • Logs transitions clearly for debugging
#
# ============================================================

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Optional

from core import config
from utils import format as FM

logger = logging.getLogger(__name__)


# ============================================================
# SECTION 1 — CONFIG
# ============================================================

POLL_INTERVAL = max(
    3,
    int(getattr(config, "BACKUP_WATCH_INTERVAL", 5) or 5),
)

# How many consecutive "pending > 0" ticks before auto-start
DEBOUNCE_TICKS = 2

# How long to hold off auto-start after user stopped manually
COOLDOWN_AFTER_STOP = 300.0   # 5 minutes


# ============================================================
# SECTION 2 — STATE
# ============================================================

STATE: Dict[str, Any] = {
    "running": False,
    "started_at": None,
    "last_tick": None,
    "last_pending": 0,
    "last_started_worker_at": None,
    "last_stopped_by_user_at": None,
    "consecutive_pending": 0,
    "ticks": 0,
    "auto_starts": 0,
    "skipped_cooldown": 0,
    "skipped_no_pending": 0,
    "skipped_worker_busy": 0,
    "skipped_disabled": 0,
    "last_error": None,
}

_task: Optional[asyncio.Task] = None


# ============================================================
# SECTION 3 — PUBLIC API
# ============================================================

def is_running() -> bool:
    return bool(STATE["running"])


def ensure_watcher() -> bool:
    """
    Start the watcher (idempotent).
    Returns True if it started, False if already running.
    """
    global _task
    if STATE["running"]:
        return False
    if _task and not _task.done():
        return False

    try:
        loop = asyncio.get_running_loop()
        _task = loop.create_task(_loop())
        logger.info(f"[WATCHER] started (interval={POLL_INTERVAL}s)")
        return True
    except RuntimeError:
        logger.warning("[WATCHER] no running loop to start task")
        return False


async def stop_watcher() -> bool:
    """Stop the watcher cleanly."""
    global _task
    if not STATE["running"]:
        return False
    STATE["running"] = False
    if _task and not _task.done():
        _task.cancel()
        try:
            await _task
        except (asyncio.CancelledError, Exception):
            pass
    logger.info("[WATCHER] stopped")
    return True


def notify_user_stopped() -> None:
    """
    Call this when the user taps STOP in /backup.
    Puts auto-start on cooldown.
    """
    STATE["last_stopped_by_user_at"] = time.time()
    STATE["consecutive_pending"] = 0
    logger.info("[WATCHER] user stopped — cooling down")


def notify_user_started() -> None:
    """Call this when the user taps START in /backup."""
    STATE["last_started_worker_at"] = time.time()
    STATE["consecutive_pending"] = 0


# ============================================================
# SECTION 4 — MAIN LOOP
# ============================================================

async def _loop() -> None:
    """Poll and auto-start."""
    STATE["running"] = True
    STATE["started_at"] = time.time()

    # Small initial delay so startup finishes first
    await asyncio.sleep(15)

    while STATE["running"]:
        try:
            await _tick()
        except asyncio.CancelledError:
            return
        except Exception as e:
            STATE["last_error"] = str(e)[:200]
            logger.exception(f"[WATCHER] tick crashed: {e}")

        try:
            await asyncio.sleep(POLL_INTERVAL)
        except asyncio.CancelledError:
            return

    STATE["running"] = False


# ============================================================
# SECTION 5 — ONE TICK
# ============================================================

async def _tick() -> None:
    STATE["ticks"] += 1
    STATE["last_tick"] = time.time()

    # ── Check env flag ──
    auto_start = bool(getattr(config, "BACKUP_AUTO_START", True))
    if not auto_start:
        STATE["skipped_disabled"] += 1
        return

    # ── Check worker state ──
    worker_running = False
    worker_paused = False
    try:
        from plugins.backup import worker as WK
        w = WK.status()
        worker_running = w.get("running", False)
        worker_paused = w.get("paused", False)
    except Exception as e:
        STATE["last_error"] = f"worker import: {e}"
        return

    if worker_running:
        STATE["skipped_worker_busy"] += 1
        STATE["consecutive_pending"] = 0
        return

    # ── Check cooldown after user stop ──
    last_stop = STATE.get("last_stopped_by_user_at")
    if last_stop:
        elapsed = time.time() - last_stop
        if elapsed < COOLDOWN_AFTER_STOP:
            STATE["skipped_cooldown"] += 1
            STATE["consecutive_pending"] = 0
            return

    # ── Check pending count ──
    pending = 0
    try:
        from plugins.backup import state as ST
        pending = await ST.count_by_status(ST.STATUS_PENDING)
    except Exception as e:
        STATE["last_error"] = f"count: {e}"
        return

    STATE["last_pending"] = pending

    if pending <= 0:
        STATE["skipped_no_pending"] += 1
        STATE["consecutive_pending"] = 0
        return

    # ── Debounce: require N consecutive ticks ──
    STATE["consecutive_pending"] += 1
    if STATE["consecutive_pending"] < DEBOUNCE_TICKS:
        logger.debug(
            f"[WATCHER] pending={pending} "
            f"(debounce {STATE['consecutive_pending']}/{DEBOUNCE_TICKS})"
        )
        return

    # ── Auto-start ──
    logger.info(
        f"[WATCHER] pending={pending} → auto-starting worker"
    )
    try:
        ok = await WK.start_worker(owner=0)
        if ok:
            STATE["auto_starts"] += 1
            STATE["last_started_worker_at"] = time.time()
            STATE["consecutive_pending"] = 0
        else:
            STATE["consecutive_pending"] = 0
    except Exception as e:
        STATE["last_error"] = f"start: {e}"
        logger.exception(f"[WATCHER] auto-start failed: {e}")
        STATE["consecutive_pending"] = 0


# ============================================================
# SECTION 6 — SNAPSHOT
# ============================================================

def snapshot() -> Dict[str, Any]:
    uptime = 0.0
    if STATE["started_at"]:
        uptime = time.time() - STATE["started_at"]

    last_tick_age = None
    if STATE["last_tick"]:
        last_tick_age = time.time() - STATE["last_tick"]

    return {
        "running": STATE["running"],
        "uptime": uptime,
        "uptime_text": FM.duration_short(uptime),
        "interval": POLL_INTERVAL,
        "ticks": STATE["ticks"],
        "pending": STATE["last_pending"],
        "consecutive_pending": STATE["consecutive_pending"],
        "auto_starts": STATE["auto_starts"],
        "skipped_cooldown": STATE["skipped_cooldown"],
        "skipped_no_pending": STATE["skipped_no_pending"],
        "skipped_worker_busy": STATE["skipped_worker_busy"],
        "skipped_disabled": STATE["skipped_disabled"],
        "last_tick_age": last_tick_age,
        "last_error": STATE["last_error"],
    }


# ============================================================
# PUBLIC EXPORTS
# ============================================================

__all__ = [
    "ensure_watcher",
    "stop_watcher",
    "notify_user_stopped",
    "notify_user_started",
    "is_running",
    "snapshot",
]
