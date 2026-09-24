# ============================================================
# 🏨 DOWNTOWN VILLA — REQUEST TOKEN CLEANUP
# ============================================================
# Auto-starts a background task that purges expired delivery
# tokens every 24 hours. Request tokens are kept forever for
# the admin to review (they get deleted when admin taps a
# button anyway).
# ============================================================

from __future__ import annotations
import asyncio
import logging

logger = logging.getLogger(__name__)

_task: "asyncio.Task | None" = None
_STARTED = False

PURGE_INTERVAL = 86400   # 24 hours
FIRST_DELAY = 60         # wait 60s after boot before first purge


async def _purge_loop() -> None:
    await asyncio.sleep(FIRST_DELAY)
    while True:
        try:
            from plugins.requests import delivery as RD
            n = await RD.purge_expired()
            if n:
                logger.info(
                    f"[REQ-CLEANUP] 🧹 purged {n} expired delivery tokens"
                )
            else:
                logger.debug("[REQ-CLEANUP] nothing to purge")
        except Exception as e:
            logger.warning(f"[REQ-CLEANUP] purge failed: {e}")

        await asyncio.sleep(PURGE_INTERVAL)


def start_cleanup() -> None:
    """Idempotent — safe to call multiple times."""
    global _task, _STARTED
    if _STARTED:
        return
    try:
        loop = asyncio.get_event_loop()
        _task = loop.create_task(_purge_loop())
        _STARTED = True
        logger.info("[REQ-CLEANUP] ✅ scheduler started (24h interval)")
    except Exception as e:
        logger.warning(f"[REQ-CLEANUP] start failed: {e}")


# ── Auto-start on module import ──
try:
    start_cleanup()
except Exception:
    pass


__all__ = ["start_cleanup"]
