# ============================================================
# 🏨 DOWNTOWN VILLA — BROADCAST CHANNEL MANAGEMENT
# ============================================================

from __future__ import annotations
import logging
from typing import Any, Dict

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
)

from plugins.broadcast.config import (
    DIV, DIV2, fb, sc, _is_admin, _esc,
)
from plugins.broadcast import database as DB
from plugins.broadcast import keyboards as KB
from plugins.broadcast import state as ST
from plugins.broadcast import views as V

logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════
# CHANNEL LIST
# ═════════════════════════════════════════════════════════════
@Client.on_callback_query(
    filters.regex(r"^bc:channels$"), group=-500
)
async def cb_channels(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    text, kb = await V.view_channels()
    await V.safe_edit(q, text, kb)
    await q.answer()


@Client.on_callback_query(
    filters.regex(r"^bc:ch_view:(-?\d+)$"), group=-500
)
async def cb_ch_view(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    cid = int(q.matches[0].group(1))
    r = await V.view_channel_detail(cid)
    if r is None:
        return await q.answer("⚠️ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)
    await V.safe_edit(q, r[0], r[1])
    await q.answer()


@Client.on_callback_query(
    filters.regex(r"^bc:ch_add$"), group=-500
)
async def cb_ch_add(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    ST.new_session(q.from_user.id, "add_channel")
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"➕ <b>{fb('ADD BROADCAST CHANNEL')}</b>",
        DIV, "",
        f"📝 {sc('send the channel id or @username')}",
        "", DIV2, "",
        f"📌 {sc('examples')}:",
        f"• <code>-1001234567890</code>",
        f"• <code>@mychannel</code>",
        "", f"⚠️ {sc('bot must be admin in that channel')}",
    ])
    await V.safe_edit(q, text, KB.kb_cancel_session())
    await q.answer()


@Client.on_callback_query(
    filters.regex(r"^bc:ch_rm:(-?\d+)$"), group=-500
)
async def cb_ch_rm(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    cid = int(q.matches[0].group(1))
    ok = await DB.remove_channel(cid)
    await q.answer("✅ ʀᴇᴍᴏᴠᴇᴅ" if ok else "⚠️ ɴᴏᴛ ꜰᴏᴜɴᴅ")
    text, kb = await V.view_channels()
    await V.safe_edit(q, text, kb)


@Client.on_callback_query(
    filters.regex(r"^bc:ch_reset:(-?\d+)$"), group=-500
)
async def cb_ch_reset(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    cid = int(q.matches[0].group(1))
    ok = await DB.update_channel(cid, caption=None, buttons=None)
    await q.answer("♻️ ʀᴇꜱᴇᴛ" if ok else "⚠️ ꜰᴀɪʟᴇᴅ")
    r = await V.view_channel_detail(cid)
    if r:
        await V.safe_edit(q, r[0], r[1])


@Client.on_callback_query(
    filters.regex(r"^bc:ch_primary:(-?\d+)$"), group=-500
)
async def cb_ch_primary(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    cid = int(q.matches[0].group(1))
    channels = await DB.get_saved_channels()
    ch = await DB.get_channel(cid)
    new_val = not (ch.get("primary") if ch else False)
    for c in channels:
        await DB.update_channel(
            c["chat_id"],
            primary=(c["chat_id"] == cid and new_val),
        )
    await q.answer("⭐ ᴛᴏɢɢʟᴇᴅ" if new_val else "☆ ᴜɴꜱᴇᴛ")
    r = await V.view_channel_detail(cid)
    if r:
        await V.safe_edit(q, r[0], r[1])


# ═════════════════════════════════════════════════════════════
# PER-CHANNEL CAPTION
# ═════════════════════════════════════════════════════════════
@Client.on_callback_query(
    filters.regex(r"^bc:ch_cap:(-?\d+)$"), group=-500
)
async def cb_ch_cap(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    cid = int(q.matches[0].group(1))
    ch = await DB.get_channel(cid)
    if not ch:
        return await q.answer("⚠️ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)
    cur = ch.get("caption")
    cur_disp = (
        "(using global default)" if cur is None
        else (cur or "(empty)")
    )
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📝 <b>{fb('EDIT CHANNEL CAPTION')}</b>",
        DIV, "",
        f"📢 {sc('channel')} · <b>{_esc(ch.get('title'))}</b>",
        "", DIV2, "",
        f"<b>{sc('current caption')}:</b>",
        f"<code>{_esc(cur_disp)}</code>",
        "", DIV2, "",
        f"📌 {sc('placeholders')}:",
        f"• <code>{{file_name}}</code> <code>{{file_size}}</code>",
        f"• <code>{{rating}}</code> <code>{{year}}</code>",
    ])
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "✏️ SET CUSTOM CAPTION",
            callback_data=f"bc:ch_cap_set:{cid}")],
        [InlineKeyboardButton(
            "📚 LOAD TEMPLATE",
            callback_data=f"bc:ch_cap_tpl:{cid}")],
        [InlineKeyboardButton(
            "♻️ RESET TO DEFAULT",
            callback_data=f"bc:ch_cap_rst:{cid}")],
        [InlineKeyboardButton(
            "◀️ BACK", callback_data=f"bc:ch_view:{cid}"),
         InlineKeyboardButton(
            "❌ CLOSE", callback_data="bc:close")],
    ])
    await V.safe_edit(q, text, kb)
    await q.answer()


@Client.on_callback_query(
    filters.regex(r"^bc:ch_cap_set:(-?\d+)$"), group=-500
)
async def cb_ch_cap_set(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    cid = int(q.matches[0].group(1))
    ST.new_session(q.from_user.id, "ch_edit_caption", chat_id=cid)
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"✏️ <b>{fb('SET CHANNEL CAPTION')}</b>",
        DIV, "",
        f"📝 {sc('send the new caption as next message')}",
        f"📌 {sc('send')} <code>-</code> {sc('to use empty caption')}",
    ])
    await V.safe_edit(q, text, KB.kb_cancel_session())
    await q.answer()


@Client.on_callback_query(
    filters.regex(r"^bc:ch_cap_rst:(-?\d+)$"), group=-500
)
async def cb_ch_cap_rst(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    cid = int(q.matches[0].group(1))
    ok = await DB.update_channel(cid, caption=None)
    await q.answer("♻️ ʀᴇꜱᴇᴛ" if ok else "⚠️ ꜰᴀɪʟᴇᴅ")
    await cb_ch_cap(client, q)


@Client.on_callback_query(
    filters.regex(r"^bc:ch_cap_tpl:(-?\d+)$"), group=-500
)
async def cb_ch_cap_tpl(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    cid = int(q.matches[0].group(1))
    from plugins.broadcast.config import CAPTION_TEMPLATES
    rows = [
        [InlineKeyboardButton(
            f"📝 {name.upper()}",
            callback_data=f"bc:ch_cap_use:{cid}:{name}")]
        for name in CAPTION_TEMPLATES
    ]
    rows.append([InlineKeyboardButton(
        "◀️ BACK", callback_data=f"bc:ch_cap:{cid}"
    )])
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📚 <b>{fb('LOAD CAPTION TEMPLATE')}</b>",
        DIV, "",
        f"📌 {sc('pick a template for this channel')}",
    ])
    await V.safe_edit(q, text, InlineKeyboardMarkup(rows))
    await q.answer()


@Client.on_callback_query(
    filters.regex(r"^bc:ch_cap_use:(-?\d+):(\w+)$"), group=-500
)
async def cb_ch_cap_use(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    cid = int(q.matches[0].group(1))
    name = q.matches[0].group(2)
    from plugins.broadcast.config import CAPTION_TEMPLATES
    tpl = CAPTION_TEMPLATES.get(name)
    if not tpl:
        return await q.answer("⚠️ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)
    ok = await DB.update_channel(cid, caption=tpl)
    await q.answer(f"✅ ʟᴏᴀᴅᴇᴅ {name}" if ok else "⚠️ ꜰᴀɪʟᴇᴅ")
    await cb_ch_cap(client, q)


# ═════════════════════════════════════════════════════════════
# PER-CHANNEL BUTTONS
# ═════════════════════════════════════════════════════════════
@Client.on_callback_query(
    filters.regex(r"^bc:ch_btn:(-?\d+)$"), group=-500
)
async def cb_ch_btn(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    cid = int(q.matches[0].group(1))
    ch = await DB.get_channel(cid)
    if not ch:
        return await q.answer("⚠️ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)

    custom = ch.get("buttons")
    using_default = custom is None
    btns = (
        await DB.get_global_buttons()
        if using_default else custom
    )

    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🔘 <b>{fb('CHANNEL BUTTONS')}</b>",
        DIV, "",
        f"📢 {sc('channel')} · <b>{_esc(ch.get('title'))}</b>",
        "",
        f"📌 {sc('source')} · "
        + ("🌐 <b>global default</b>" if using_default
           else "🔘 <b>custom</b>"),
        "", DIV2, "",
    ]
    if not btns:
        lines.append("⚪ ɴᴏ ʙᴜᴛᴛᴏɴꜱ")
    else:
        for i, b in enumerate(btns, 1):
            lines.append(f"{i}. <b>{_esc(b.get('name'))}</b>")
            lines.append(f"   <code>{_esc(b.get('url'))}</code>")
            lines.append("")

    rows = []
    if not using_default:
        for i, b in enumerate(btns, 1):
            rows.append([InlineKeyboardButton(
                f"🗑️ {i}. {(b.get('name') or '?')[:30]}",
                callback_data=f"bc:ch_btn_rm:{cid}:{i-1}")])
        rows.append([InlineKeyboardButton(
            "➕ ADD BUTTON",
            callback_data=f"bc:ch_btn_add:{cid}")])
        rows.append([InlineKeyboardButton(
            "♻️ RESET TO DEFAULT",
            callback_data=f"bc:ch_btn_rst:{cid}")])
    else:
        rows.append([InlineKeyboardButton(
            "✏️ SET CUSTOM BUTTONS",
            callback_data=f"bc:ch_btn_custom:{cid}")])

    rows.append([
        InlineKeyboardButton(
            "◀️ BACK", callback_data=f"bc:ch_view:{cid}"),
        InlineKeyboardButton(
            "❌ CLOSE", callback_data="bc:close"),
    ])
    await V.safe_edit(q, "\n".join(lines), InlineKeyboardMarkup(rows))
    await q.answer()


@Client.on_callback_query(
    filters.regex(r"^bc:ch_btn_custom:(-?\d+)$"), group=-500
)
async def cb_ch_btn_custom(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    cid = int(q.matches[0].group(1))
    await DB.update_channel(cid, buttons=[])
    await q.answer("✏️ ᴇᴍᴘᴛʏ ᴄᴜꜱᴛᴏᴍ ꜱᴇᴛ ᴄʀᴇᴀᴛᴇᴅ")
    await cb_ch_btn(client, q)


@Client.on_callback_query(
    filters.regex(r"^bc:ch_btn_rst:(-?\d+)$"), group=-500
)
async def cb_ch_btn_rst(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    cid = int(q.matches[0].group(1))
    ok = await DB.update_channel(cid, buttons=None)
    await q.answer("♻️ ʀᴇꜱᴇᴛ" if ok else "⚠️ ꜰᴀɪʟᴇᴅ")
    await cb_ch_btn(client, q)


@Client.on_callback_query(
    filters.regex(r"^bc:ch_btn_add:(-?\d+)$"), group=-500
)
async def cb_ch_btn_add(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    cid = int(q.matches[0].group(1))
    ST.new_session(q.from_user.id, "ch_add_button", chat_id=cid)
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"➕ <b>{fb('ADD BUTTON TO CHANNEL')}</b>",
        DIV, "",
        f"📝 {sc('send')} <code>Name | URL</code>",
        "", f"📌 {sc('example')}:",
        f"<code>Join Backups | https://t.me/backups</code>",
    ])
    await V.safe_edit(q, text, KB.kb_cancel_session())
    await q.answer()


@Client.on_callback_query(
    filters.regex(r"^bc:ch_btn_rm:(-?\d+):(\d+)$"), group=-500
)
async def cb_ch_btn_rm(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    cid = int(q.matches[0].group(1))
    idx = int(q.matches[0].group(2))
    ch = await DB.get_channel(cid)
    if not ch or ch.get("buttons") is None:
        return await q.answer("⚠️ ɴᴏ ᴄᴜꜱᴛᴏᴍ ʙᴜᴛᴛᴏɴꜱ",
                              show_alert=True)
    btns = list(ch["buttons"])
    if idx < 0 or idx >= len(btns):
        return await q.answer("⚠️ ɪɴᴠᴀʟɪᴅ", show_alert=True)
    btns.pop(idx)
    await DB.update_channel(cid, buttons=btns)
    await q.answer("🗑️ ʀᴇᴍᴏᴠᴇᴅ")
    await cb_ch_btn(client, q)


__all__ = []
