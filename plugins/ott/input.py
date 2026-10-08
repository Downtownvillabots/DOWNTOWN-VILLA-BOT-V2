# ============================================================
# 🏨 DOWNTOWN VILLA — OTT TEXT INPUT (v4)
# ============================================================

from __future__ import annotations
import logging

from pyrogram import Client, filters
from pyrogram.enums import ParseMode

from plugins.broadcast.config import _is_admin
from plugins.ott import database as DB
from plugins.ott import settings_db as SD
from plugins.ott import state as ST
from plugins.ott import views as V

logger = logging.getLogger(__name__)


def _clean_url(url: str) -> str:
    url = (url or "").strip()
    if url.startswith("@"):
        return f"https://t.me/{url[1:]}"
    if url.startswith(("http://", "https://", "tg://")):
        return url
    if "." in url and " " not in url:
        return f"https://{url}"
    return ""


@Client.on_message(
    filters.private & filters.text & ~filters.regex(r"^/"),
    group=-440,
)
async def ott_input(client: Client, message):
    if not message.from_user or not _is_admin(message.from_user.id):
        return

    text = (message.text or "").strip()

    # ── Legacy: set_ott_channel ──
    sess = ST.get_session(message.from_user.id)
    if sess and sess.get("action") == "set_ott_channel":
        try:
            message.stop_propagation()
        except Exception:
            pass
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

    # ── Settings edit sessions ──
    s = ST.get_set_session(message.from_user.id)
    if not s:
        return

    try:
        message.stop_propagation()
    except Exception:
        pass

    kind = s["kind"]
    data = s.get("data") or {}

    if text == "-":
        ST.clear_set_session(message.from_user.id)
        return await message.reply_text("❌ Cancelled")

    # ── CAPTION EDITS ──
    if kind == "edit_caption_global":
        await SD.set_global_caption(text)
        ST.clear_set_session(message.from_user.id)
        return await message.reply_text("✅ Global caption updated")

    if kind == "edit_caption_ch":
        cid = data.get("cid")
        if cid is None:
            ST.clear_set_session(message.from_user.id)
            return
        await SD.set_channel_caption(int(cid), text)
        ST.clear_set_session(message.from_user.id)
        return await message.reply_text(f"✅ Caption for channel {cid} updated")

    if kind == "edit_caption_gr":
        gid = data.get("gid")
        if gid is None:
            ST.clear_set_session(message.from_user.id)
            return
        await SD.set_group_caption(int(gid), text)
        ST.clear_set_session(message.from_user.id)
        return await message.reply_text(f"✅ Caption for group {gid} updated")

    if kind == "edit_caption_us":
        await SD.set_user_caption(text)
        ST.clear_set_session(message.from_user.id)
        return await message.reply_text("✅ Users caption updated")

    if kind == "edit_caption_pm":
        await SD.set_premium_caption(text)
        ST.clear_set_session(message.from_user.id)
        return await message.reply_text("✅ Premium caption updated")

    # ── CUSTOM BUTTON ADDS ──
    if kind.startswith("btn_add_"):
        if "|" not in text:
            return await message.reply_text(
                "❌ Format: <code>Name | URL</code>",
                parse_mode=ParseMode.HTML)
        name, url = [p.strip() for p in text.split("|", 1)]
        clean = _clean_url(url)
        if not name or not clean:
            return await message.reply_text("❌ Invalid")

        entry = {"name": name[:64], "url": clean}

        if kind == "btn_add_global":
            gb = await SD.get_global_buttons()
            custom = list(gb.get("custom") or [])
            if len(custom) >= 6:
                ST.clear_set_session(message.from_user.id)
                return await message.reply_text("⚠️ Max 6 custom buttons")
            custom.append(entry)
            gb["custom"] = custom
            await SD.set_global_buttons(gb)
            ST.clear_set_session(message.from_user.id)
            return await message.reply_text("✅ Added (global)")

        if kind == "btn_add_ch":
            cid = data.get("cid")
            if cid is None:
                ST.clear_set_session(message.from_user.id)
                return
            ov = await SD.get_channel_override(int(cid))
            btn = dict(ov.get("buttons") or await SD.get_global_buttons())
            custom = list(btn.get("custom") or [])
            if len(custom) >= 6:
                ST.clear_set_session(message.from_user.id)
                return await message.reply_text("⚠️ Max 6")
            custom.append(entry)
            btn["custom"] = custom
            await SD.set_channel_buttons(int(cid), btn)
            ST.clear_set_session(message.from_user.id)
            return await message.reply_text(f"✅ Added (channel {cid})")

        if kind == "btn_add_gr":
            gid = data.get("gid")
            if gid is None:
                ST.clear_set_session(message.from_user.id)
                return
            ov = await SD.get_group_override(int(gid))
            btn = dict(ov.get("buttons") or await SD.get_global_buttons())
            custom = list(btn.get("custom") or [])
            if len(custom) >= 6:
                ST.clear_set_session(message.from_user.id)
                return await message.reply_text("⚠️ Max 6")
            custom.append(entry)
            btn["custom"] = custom
            await SD.set_group_buttons(int(gid), btn)
            ST.clear_set_session(message.from_user.id)
            return await message.reply_text(f"✅ Added (group {gid})")

        if kind == "btn_add_us":
            btn = dict(await SD.get_user_buttons()
                       or await SD.get_global_buttons())
            custom = list(btn.get("custom") or [])
            if len(custom) >= 6:
                ST.clear_set_session(message.from_user.id)
                return await message.reply_text("⚠️ Max 6")
            custom.append(entry)
            btn["custom"] = custom
            await SD.set_user_buttons(btn)
            ST.clear_set_session(message.from_user.id)
            return await message.reply_text("✅ Added (users)")

        if kind == "btn_add_pm":
            btn = dict(await SD.get_premium_buttons()
                       or await SD.get_global_buttons())
            custom = list(btn.get("custom") or [])
            if len(custom) >= 6:
                ST.clear_set_session(message.from_user.id)
                return await message.reply_text("⚠️ Max 6")
            custom.append(entry)
            btn["custom"] = custom
            await SD.set_premium_buttons(btn)
            ST.clear_set_session(message.from_user.id)
            return await message.reply_text("✅ Added (premium)")

    ST.clear_set_session(message.from_user.id)


__all__ = []
