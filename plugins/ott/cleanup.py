# ============================================================
# 🏨 DOWNTOWN VILLA — OTT CLEANUP LOOP
# ============================================================

from __future__ import annotations
import asyncio
import logging

from plugins.ott import state as ST

logger = logging.getLogger(__name__)

_TASK = None


async def _loop():
    while True:
        try:
            await asyncio.sleep(120)
            ST.cleanup_sessions()
            ST.cleanup_jobs()
            ST.cleanup_confirms()
        except asyncio.CancelledError:
            break
        except Exception:
            pass


def start() -> None:
    global _TASK
    if _TASK and not _TASK.done():
        return
    try:
        loop = asyncio.get_event_loop()
        _TASK = loop.create_task(_loop())
    except Exception:
        pass


__all__ = ["start"]
