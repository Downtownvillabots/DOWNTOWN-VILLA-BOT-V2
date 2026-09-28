# ============================================================
# 🏨 DOWNTOWN VILLA — BROADCAST CLEANUP LOOP
# ============================================================

from __future__ import annotations
import asyncio
import logging

from pyrogram import Client

from plugins.broadcast import state as ST

logger = logging.getLogger(__name__)

_TASK = None


async def _loop():
    while True:
        try:
            await asyncio.sleep(120)
            ST.cleanup_sessions()
            ST.cleanup_jobs()
            ST.cleanup_sources()
            ST.cleanup_batches()
        
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.debug(f"[BC-CLEAN] {e}")


def start() -> None:
    global _TASK
    if _TASK and not _TASK.done():
        return
    try:
        loop = asyncio.get_event_loop()
        _TASK = loop.create_task(_loop())
    except Exception:
        pass

def _cleanup_conf():
    """Remove stale confirmation entries."""
    import time
    now = time.time()
    for sid in list(W._CONF.keys()):
        c = W._CONF[sid]
        if now - c.get("created", 0) > 3600:
            W._CONF.pop(sid, None)


__all__ = ["start"]
