# ============================================================
# 🏨 DOWNTOWN VILLA — ADMIN → BROADCAST (PANEL ENTRY)
# ============================================================
#
# Called from /admin → [📢 Broadcast].
# Opens the source picker in the admin's PM.
#
# Delegates to plugins/broadcast/watcher.py::bc_open_for_admin
# so both /broadcast and /admin button use the SAME flow.
#
# ============================================================

from __future__ import annotations

import logging

from pyrogram import Client
from pyrogram.enums import ParseMode
from pyrogram.types import CallbackQuery

from core import config

logger = logging.getLogger(__name__)


def _is_admin(uid) -> bool:
    try:
        return int(uid) in [int(a) for a in config.ADMINS]
    except Exception:
        return False


async def open_panel_for_admin(client: Client, q: CallbackQuery) -> None:
    """Called from /admin → [📢 Broadcast]. Opens panel in admin PM."""
    if not q.from_user or not _is_admin(q.from_user.id):
        return await q.answer("⛔ admin only", show_alert=True)

    uid = int(q.from_user.id)

    try:
        from plugins.broadcast import watcher as W
        await W.bc_open_for_admin(client, uid)
        await q.answer("📢 opening in PM…")
    except Exception as e:
        logger.exception(f"[ADMIN-BC] {e}")
        try:
            await q.answer(f"❌ {type(e).__name__}", show_alert=True)
        except Exception:
            pass


__all__ = ["open_panel_for_admin"]
