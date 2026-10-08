# ============================================================
# 🏨 DOWNTOWN VILLA — OTT TEXT INPUT
# ============================================================

from __future__ import annotations
import logging

from pyrogram import Client, filters
from pyrogram.enums import ParseMode

from plugins.broadcast.config import _is_admin
from plugins.ott import database as DB
from plugins.ott import state as ST
from plugins.ott import views as V

logger = logging.getLogger(__name__)


@Client.on_message(
    filters.private & filters.text & ~filters.regex(r"^/"),
    group=-440,
)
async def ott_input(client: Client, message):
    if not message.from_user or not _is_admin(message.from_user.id):
        return
    sess = ST.get_session(message.from_user.id)
    if not sess:
        return

    action = sess["action"]
    text = (message.text or "").strip()

    try:
        message.stop_propagation()
    except Exception:
        pass

    # ── SET OTT BROADCAST CHANNEL ──
    if action == "set_ott_channel":
        if text == "-":
            ST.clear_session(message.from_user.id)
            return await message.reply_text("❌ Cancelled")
        try:
            cid = int(text) if text.lstrip("-").isdigit() else None
            if cid is None and text.startswith("@"):
                chat = await client.get_chat(text)
                cid = chat.id
            if not cid:
                raise ValueError
        except Exception:
            return await message.reply_text(
                "❌ Send a numeric chat id or @username",
                parse_mode=ParseMode.HTML)
        await DB.save_cfg(ott_broadcast_channel=int(cid))
        ST.clear_session(message.from_user.id)
        t, k = await V.view_settings()
        await message.reply_text(t, reply_markup=k,
                                 parse_mode=ParseMode.HTML,
                                 disable_web_page_preview=True)
        return

    ST.clear_session(message.from_user.id)


__all__ = []
