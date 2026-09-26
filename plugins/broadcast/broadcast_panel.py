# ============================================================
# 🏨 DOWNTOWN VILLA — BROADCAST ADMIN PANEL (DELEGATE)
# ============================================================
#
# Called from /admin → [📢 Broadcast].
# Opens the same flow as /broadcast in PM.
#
# ============================================================

from __future__ import annotations

import logging

from pyrogram import Client
from pyrogram.enums import ParseMode
from pyrogram.types import Message

from core import config
from utils import fonts as F

logger = logging.getLogger(__name__)


def _is_admin(uid) -> bool:
    try:
        return int(uid) in [int(a) for a in config.ADMINS]
    except Exception:
        return False


async def open_panel_for_admin(client: Client, message: Message) -> None:
    """
    Called from /admin → [📢 Broadcast].
    Delegates to plugins.broadcast.watcher.bc_cmd.
    """
    if not message.from_user or not _is_admin(message.from_user.id):
        return

    try:
        from plugins.broadcast import watcher as W
        await W.bc_cmd(client, message)
    except Exception as e:
        logger.exception(f"[ADMIN-BC] {e}")
        try:
            await message.reply_text(
                f"{F.EMO['cross']} <b>Broadcast panel error</b>\n"
                f"<code>{type(e).__name__}</code>",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass


__all__ = ["open_panel_for_admin"]
