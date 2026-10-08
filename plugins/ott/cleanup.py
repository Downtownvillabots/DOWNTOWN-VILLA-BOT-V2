# ============================================================
# 🏨 DOWNTOWN VILLA — OTT CLEANUP LOOP
# ============================================================

from __future__ import annotations
import asyncio
import logging

from plugins.ott import state as ST
from plugins.ott import events as EVENTS

logger = logging.getLogger(__name__)

_TASK = None


async def _loop():
    while True:
        try:
            await asyncio.sleep(120)
            ST.cleanup_sessions()
            ST.cleanup_jobs()
            ST.cleanup_confirms()
            ST.setup_cleanup()
            ST.cleanup_set_sessions()
        except asyncio.CancelledError:
            break
        except Exception:
            pass


async def _recount_loop():
    """Hourly recount of active events (drift protection)."""
    while True:
        try:
            await asyncio.sleep(3600)
            try:
                active = await EVENTS.list_active_events(limit=100)
            except Exception:
                continue
            for ev in active:
                try:
                    await EVENTS.recount(ev["_id"])
                except Exception:
                    pass
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
        loop.create_task(_loop())
        loop.create_task(_recount_loop())
    except Exception:
        pass


__all__ = ["start"]
