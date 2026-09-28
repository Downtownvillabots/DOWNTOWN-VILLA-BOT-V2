# ============================================================
# 🏨 DOWNTOWN VILLA — AUTO-DELETE LOOP
# ============================================================

from __future__ import annotations
import asyncio
import logging

from pyrogram import Client

from plugins.broadcast.config import AUTODELETE_SCAN_INTERVAL
from plugins.broadcast import database as DB

logger = logging.getLogger(__name__)

_BOT_CLIENT: Client = None
_TASK = None


def set_client(client: Client) -> None:
    global _BOT_CLIENT
    _BOT_CLIENT = client


async def _loop():
    while True:
        try:
            await asyncio.sleep(AUTODELETE_SCAN_INTERVAL)
            if _BOT_CLIENT is None:
                continue
            due = await DB.get_due_autodeletes(limit=200)
            if not due:
                continue
            deleted = 0
            failed = 0
            for doc in due:
                cid = doc.get("chat_id")
                mid = doc.get("message_id")
                if not cid or not mid:
                    await DB.remove_autodelete(doc.get("_id"))
                    continue
                try:
                    await _BOT_CLIENT.delete_messages(
                        int(cid), int(mid)
                    )
                    deleted += 1
                except Exception as e:
                    failed += 1
                    logger.debug(
                        f"[BC-AD] {cid}/{mid}: {type(e).__name__}"
                    )
                await DB.remove_autodelete(doc.get("_id"))
            if deleted or failed:
                logger.info(
                    f"[BC-AD] processed {len(due)} · "
                    f"deleted={deleted} failed={failed}"
                )
        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.warning(f"[BC-AD] loop: {e}")


def start(client: Client) -> None:
    global _TASK
    set_client(client)
    if _TASK and not _TASK.done():
        return
    try:
        loop = asyncio.get_event_loop()
        _TASK = loop.create_task(_loop())
        logger.info("[BC-AD] auto-delete loop started")
    except Exception as e:
        logger.warning(f"[BC-AD] start: {e}")


__all__ = ["start", "set_client"]
