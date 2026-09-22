# ============================================================
# 🏨 DOWNTOWN VILLA — BACKUP RECONCILE (CRASH RECOVERY)
# ============================================================
#
# Fixes the "crashed mid-upload" state.
#
# THE PROBLEM:
#   Backup worker marks a file UPLOADING, then calls Telegram.
#   If the bot crashes before Telegram replies, the file is
#   stuck as UPLOADING forever.
#
# THE SOLUTION:
#   1. Find every UPLOADING record.
#   2. For each, scan the backup channel for its token.
#      → If found: mark UPLOADED with the real message_id.
#      → If not found: reset to PENDING (safe to retry).
#
# SAFETY:
#   • Only scans last N messages per token (bounded).
#   • Respects FloodWait.
#   • Never deletes Telegram messages.
#   • Caches channel history to avoid re-scans.
#
# ============================================================

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from pyrogram import Client
from pyrogram.errors import FloodWait, RPCError
from pyrogram.types import Message

from utils import format as FM

logger = logging.getLogger(__name__)


# ============================================================
# SECTION 1 — CONFIG
# ============================================================

# Max messages to scan per reconcile pass
SCAN_LIMIT = 2000

# Delay between token lookups (avoid hammering)
TOKEN_DELAY = 0.05

# Max concurrent token checks
CONCURRENCY = 3


# ============================================================
# SECTION 2 — STATE
# ============================================================

STATE: Dict[str, Any] = {
    "running": False,
    "started_at": None,
    "finished_at": None,
    "scanned": 0,
    "recovered": 0,
    "reset": 0,
    "skipped": 0,
    "failed": 0,
    "last_error": None,
}


# ============================================================
# SECTION 3 — PUBLIC API
# ============================================================

def is_running() -> bool:
    return bool(STATE["running"])


async def reconcile_all(client: Optional[Client] = None) -> Dict[str, Any]:
    """
    Fix every stuck UPLOADING file.
    Returns result dict for the panel.
    """
    if STATE["running"]:
        return {"ok": False, "reason": "already running"}

    STATE["running"] = True
    STATE["started_at"] = time.time()
    STATE["scanned"] = 0
    STATE["recovered"] = 0
    STATE["reset"] = 0
    STATE["skipped"] = 0
    STATE["failed"] = 0
    STATE["last_error"] = None

    logger.info("[RECON] starting…")

    result: Dict[str, Any] = {
        "ok": True,
        "scanned": 0,
        "recovered": 0,
        "reset": 0,
        "pending": 0,
        "error": None,
    }

    try:
        # Get client
        if client is None:
            from core.client import client as C
            client = C
        if client is None:
            result["ok"] = False
            result["error"] = "no client"
            return result

        # Get backup channel
        backup_ch = await _get_backup_channel()
        if not backup_ch:
            result["ok"] = False
            result["error"] = "no primary backup channel"
            return result

        # Get stuck UPLOADING records
        from plugins.backup import state as ST
        stuck = await _list_stuck()

        if not stuck:
            logger.info("[RECON] nothing to reconcile")
            STATE["finished_at"] = time.time()
            return result

        result["scanned"] = len(stuck)
        STATE["scanned"] = len(stuck)

        logger.info(f"[RECON] scanning {len(stuck)} stuck records")

        # Scan channel history ONCE, cache results
        cache = await _build_message_cache(
            client, backup_ch, SCAN_LIMIT
        )
        logger.info(f"[RECON] cached {len(cache)} message tokens")

        # Process each stuck record
        sem = asyncio.Semaphore(CONCURRENCY)

        async def _one(rec: Dict[str, Any]):
            async with sem:
                return await _reconcile_one(
                    client, backup_ch, rec, cache
                )

        tasks = [_one(rec) for rec in stuck]
        outcomes = await asyncio.gather(*tasks, return_exceptions=True)

        for outcome in outcomes:
            if isinstance(outcome, Exception):
                STATE["failed"] += 1
                continue
            if outcome == "recovered":
                STATE["recovered"] += 1
                result["recovered"] += 1
            elif outcome == "reset":
                STATE["reset"] += 1
                result["reset"] += 1
            elif outcome == "skipped":
                STATE["skipped"] += 1

        # Count still pending
        try:
            pending = await ST.count_by_status(ST.STATUS_PENDING)
            result["pending"] = pending
        except Exception:
            pass

    except Exception as e:
        logger.exception(f"[RECON] failed: {e}")
        result["ok"] = False
        result["error"] = str(e)[:200]
        STATE["last_error"] = str(e)[:200]
    finally:
        STATE["running"] = False
        STATE["finished_at"] = time.time()

    logger.info(
        f"[RECON] done — scanned={STATE['scanned']} "
        f"recovered={STATE['recovered']} reset={STATE['reset']}"
    )
    return result


# ============================================================
# SECTION 4 — LIST STUCK RECORDS
# ============================================================

async def _list_stuck() -> List[Dict[str, Any]]:
    """Return every UPLOADING record across all shards."""
    from plugins.backup import state as ST
    out: List[Dict[str, Any]] = []
    try:
        async for doc in ST.iter_by_status(ST.STATUS_UPLOADING):
            out.append(doc)
            if len(out) >= 5000:
                break
    except Exception as e:
        logger.warning(f"[RECON] list stuck: {e}")
    return out


# ============================================================
# SECTION 5 — MESSAGE CACHE
# ============================================================

async def _build_message_cache(
    client: Client,
    chat_id: int,
    limit: int,
) -> Dict[str, int]:
    """
    Scan channel history once, build {token: message_id}.
    Capped at `limit` messages.
    """
    cache: Dict[str, int] = {}
    scanned = 0
    try:
        async for msg in client.get_chat_history(chat_id, limit=limit):
            scanned += 1
            token = _extract_token(msg)
            if token and token not in cache:
                cache[token] = msg.id
            if len(cache) >= 5000:
                # Cap cache size — safety
                break
    except FloodWait as e:
        wait = int(getattr(e, "value", 30) or 30)
        logger.warning(f"[RECON] flood during scan — {wait}s")
        await asyncio.sleep(wait + 2)
    except RPCError as e:
        logger.warning(f"[RECON] rpc during scan: {e}")
    except Exception as e:
        logger.exception(f"[RECON] scan failed: {e}")

    return cache


def _extract_token(msg: Message) -> Optional[str]:
    """Extract the DTV-BACKUP token from a message caption/text."""
    try:
        text = (msg.caption or msg.text or "")
        if not text:
            return None
        # Tokens start with DTV-BACKUP-
        import re
        m = re.search(r"(DTV-BACKUP-[A-Za-z0-9_]+-[A-Fa-f0-9]{32})", text)
        if m:
            return m.group(1)
        return None
    except Exception:
        return None


# ============================================================
# SECTION 6 — RECONCILE ONE
# ============================================================

async def _reconcile_one(
    client: Client,
    backup_ch: int,
    record: Dict[str, Any],
    cache: Dict[str, int],
) -> str:
    """
    Fix one stuck record.
    Returns: "recovered" | "reset" | "skipped"
    """
    from plugins.backup import state as ST

    source_db = str(record.get("source_db", ""))
    file_id = str(record.get("file_id", ""))
    token = str(record.get("backup_token") or "")

    if not source_db or not file_id:
        return "skipped"

    if not token:
        token = ST.backup_token(source_db, file_id)

    # Lookup in cache
    msg_id = cache.get(token)

    if msg_id:
        # Found in channel → mark uploaded
        try:
            doc = {
                "file_id": file_id,
                "file_name": record.get("file_name", ""),
                "file_size": record.get("file_size", 0),
            }
            await ST.mark_uploaded(source_db, doc, msg_id)
            logger.info(
                f"[RECON] ✅ recovered {source_db}/{file_id[:20]} "
                f"→ msg {msg_id}"
            )
            return "recovered"
        except Exception as e:
            logger.debug(f"[RECON] mark uploaded: {e}")
            return "skipped"

    # Not found → reset to PENDING
    try:
        doc = {
            "file_id": file_id,
            "file_name": record.get("file_name", ""),
            "file_size": record.get("file_size", 0),
        }
        await ST.set_state(source_db, doc, ST.STATUS_PENDING)
        logger.debug(
            f"[RECON] ♻️ reset {source_db}/{file_id[:20]} → PENDING"
        )
        return "reset"
    except Exception as e:
        logger.debug(f"[RECON] reset: {e}")
        return "skipped"


# ============================================================
# SECTION 7 — CHANNEL LOOKUP
# ============================================================

async def _get_backup_channel() -> Optional[int]:
    try:
        from plugins.backup import channels as CH
        return await CH.primary_backup_id()
    except Exception as e:
        logger.debug(f"[RECON] channel: {e}")
        return None


async def scan_channel_for_token(
    client: Client,
    chat_id: int,
    token: str,
    limit: int = 1000,
) -> Optional[int]:
    """
    Scan a channel for one specific token.
    Useful when cache miss happens.
    """
    if not token:
        return None
    scanned = 0
    try:
        async for msg in client.get_chat_history(chat_id, limit=limit):
            scanned += 1
            found = _extract_token(msg)
            if found == token:
                return msg.id
            if scanned % 100 == 0:
                await asyncio.sleep(0.05)
    except FloodWait as e:
        wait = int(getattr(e, "value", 30) or 30)
        await asyncio.sleep(wait + 2)
    except RPCError as e:
        logger.warning(f"[RECON] scan: {e}")
    except Exception as e:
        logger.debug(f"[RECON] scan: {e}")
    return None


# ============================================================
# SECTION 8 — SNAPSHOT
# ============================================================

def snapshot() -> Dict[str, Any]:
    uptime = 0.0
    if STATE["started_at"]:
        end = STATE["finished_at"] or time.time()
        uptime = end - STATE["started_at"]

    return {
        "running": STATE["running"],
        "uptime": uptime,
        "uptime_text": FM.duration_short(uptime),
        "scanned": STATE["scanned"],
        "recovered": STATE["recovered"],
        "reset": STATE["reset"],
        "skipped": STATE["skipped"],
        "failed": STATE["failed"],
        "last_error": STATE["last_error"],
    }


# ============================================================
# PUBLIC EXPORTS
# ============================================================

__all__ = [
    "reconcile_all",
    "scan_channel_for_token",
    "is_running",
    "snapshot",
]
