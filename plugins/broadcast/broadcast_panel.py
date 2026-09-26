# ============================================================
# 🏨 DOWNTOWN VILLA — ADMIN → BROADCAST (PANEL ENTRY)
# ============================================================
#
# Called from /admin → [📢 Broadcast].
# Opens the source picker in the admin's PM (same flow as /broadcast).
#
# ============================================================

from __future__ import annotations

import logging

from pyrogram import Client
from pyrogram.enums import ParseMode
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
)

from core import config
from utils import fonts as F

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

    ch = getattr(config, "BROADCAST_CHANNEL_ID", None)
    if not ch:
        await q.answer("⚠ BROADCAST_CHANNEL_ID not set", show_alert=True)
        return

    try:
        msgs = []
        async for m in client.get_chat_history(ch, limit=40):
            if m.media and not m.service:
                msgs.append(m)
            if len(msgs) >= 10:
                break
    except Exception as e:
        logger.exception(f"[BC-ADMIN] fetch: {e}")
        return await q.answer(f"❌ {type(e).__name__}", show_alert=True)

    from plugins.broadcast import watcher as W

    if not msgs:
        try:
            await client.send_message(
                chat_id=uid,
                text="\n".join([
                    f"{F.EMO['warn']} <b>{F.fb('NO FILES')}</b>",
                    F.DIV, "",
                    f"📌 {F.sc('upload a file to the broadcast channel')}",
                    f"📌 {F.sc('then try again')}",
                ]),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        return await q.answer("📢 check your PM")

    src_list = [(int(m.id), W._extract_name(m)) for m in msgs]

    W._s_set(
        uid,
        source_list=src_list,
        broadcast_channel_id=int(ch),
        awaiting=None,
    )

    text = "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"📢 <b>{F.fb('SELECT SOURCE')}</b>",
        F.DIV, "",
        f"📌 {F.sc('pick a file from the broadcast channel')}",
    ])

    rows = []
    for i, (mid, name) in enumerate(src_list):
        rows.append([InlineKeyboardButton(
            f"📦 {name[:42]}",
            callback_data=W._cb("src", i),
        )])
    rows.append([InlineKeyboardButton(
        f"❌ {F.sc('cancel')}",
        callback_data=W._cb("cancel"),
    )])

    try:
        await client.send_message(
            chat_id=uid,
            text=text,
            reply_markup=InlineKeyboardMarkup(rows),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        await q.answer("📢 opening in PM…")
    except Exception as e:
        logger.exception(f"[BC-ADMIN] send: {e}")
        try:
            await q.answer(f"❌ {type(e).__name__}", show_alert=True)
        except Exception:
            pass


__all__ = ["open_panel_for_admin"]
