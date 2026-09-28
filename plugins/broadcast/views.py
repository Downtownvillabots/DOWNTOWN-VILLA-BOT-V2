# ============================================================
# 🏨 DOWNTOWN VILLA — BROADCAST VIEWS
# ============================================================

from __future__ import annotations
import logging
from datetime import datetime
from typing import Any, Dict, Optional, Tuple

from pyrogram.enums import ParseMode
from pyrogram.errors import MessageNotModified
from pyrogram.types import InlineKeyboardMarkup

from plugins.broadcast.config import (
    DIV, DIV2, fb, sc, _esc, _fmt_int, _fmt_duration,
    DEFAULT_BROADCAST_CAPTION,
)
from plugins.broadcast import database as DB
from plugins.broadcast import keyboards as KB

logger = logging.getLogger(__name__)


async def safe_edit(target, text: str, kb=None) -> bool:
    try:
        msg = getattr(target, "message", target)
        await msg.edit_text(
            text, reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        return True
    except MessageNotModified:
        return True
    except Exception as e:
        logger.warning(f"[BC] edit: {type(e).__name__}: {e}")
        return False


async def view_main() -> Tuple[str, InlineKeyboardMarkup]:
    u = await DB.count_users()
    g = await DB.count_groups()
    chans = await DB.get_saved_channels()
    btns = await DB.get_global_buttons()
    ad = await DB.count_scheduled_autodeletes()

    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📢 <b>{fb('BROADCAST CONTROL CENTER')}</b>",
        DIV, "",
        f"👤 {sc('users')} · <code>{_fmt_int(u)}</code>",
        f"👥 {sc('groups')} · <code>{_fmt_int(g)}</code>",
        f"📢 {sc('saved channels')} · <code>{len(chans)}</code>",
        f"🔘 {sc('default buttons')} · <code>{len(btns)}</code>",
        f"⏱️ {sc('pending auto-deletes')} · <code>{_fmt_int(ad)}</code>",
        "", DIV2, "",
        f"📌 {sc('each channel can have its own caption & buttons')}",
        f"📌 {sc('auto-delete works for channels, groups & users')}",
        "", DIV2,
        f"🕒 {sc('updated')} · "
        f"<code>{datetime.now().strftime('%H:%M:%S')}</code>",
    ])
    return text, KB.kb_main(u, g, len(chans), len(btns), ad)


async def view_channels() -> Tuple[str, InlineKeyboardMarkup]:
    chans = await DB.get_saved_channels()
    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📢 <b>{fb('BROADCAST CHANNELS')}</b>",
        DIV, "",
    ]
    if not chans:
        lines += [
            f"⚪ {sc('no channels saved yet')}", "",
            f"ᴄʟɪᴄᴋ {sc('add channel')} ᴛᴏ ꜱᴛᴀʀᴛ",
        ]
    else:
        lines.append("📝 = custom caption · 🔘 = custom buttons")
        lines.append("")
        for i, c in enumerate(chans, 1):
            markers = ""
            if c.get("caption") is not None:
                markers += "📝"
            if c.get("buttons") is not None:
                markers += "🔘"
            if not markers:
                markers = "⚪"
            lines.append(
                f"{i}. {markers} <b>{_esc(c.get('title'))}</b>"
            )
            lines.append(f"   <code>{c.get('chat_id')}</code>")
            lines.append("")
    return "\n".join(lines), KB.kb_channels(chans)


async def view_channel_detail(
    chat_id: int,
) -> Optional[Tuple[str, InlineKeyboardMarkup]]:
    ch = await DB.get_channel(chat_id)
    if not ch:
        return None
    cap_status = (
        "🌐 using default"
        if ch.get("caption") is None
        else "📝 custom"
    )
    btn_count = (
        len(ch.get("buttons") or [])
        if ch.get("buttons") is not None
        else None
    )
    btn_status = (
        "🌐 using default"
        if btn_count is None
        else f"🔘 {btn_count} custom"
    )
    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📢 <b>{fb('CHANNEL DETAILS')}</b>",
        DIV, "",
        f"📛 {sc('title')} · <b>{_esc(ch.get('title'))}</b>",
        f"🆔 {sc('chat id')} · <code>{ch.get('chat_id')}</code>",
    ]
    if ch.get("username"):
        lines.append(
            f"🔗 {sc('username')} · <code>@{ch.get('username')}</code>"
        )
    lines += [
        "", DIV2, "",
        f"📝 {sc('caption')} · {cap_status}",
        f"🔘 {sc('buttons')} · {btn_status}",
        f"⭐ {sc('primary')} · "
        f"{'✅' if ch.get('primary') else '❌'}",
        "", DIV2, "",
        f"📌 {sc('custom caption/buttons apply only when')}",
        f"📌 {sc('broadcasting to this channel')}",
    ]
    return "\n".join(lines), KB.kb_channel_view(int(chat_id))


async def view_groups() -> Tuple[str, InlineKeyboardMarkup]:
    groups = await DB.get_all_groups_full()
    count = len(groups)
    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"👥 <b>{fb('BROADCAST TO GROUPS')}</b>",
        DIV, "",
        f"📊 {sc('total groups')} · <code>{_fmt_int(count)}</code>",
        "", DIV2, "",
        f"📌 {sc('tap a group to customize')}",
        f"📌 {sc('or send to all at once')}",
    ]
    return "\n".join(lines), KB.kb_groups_list(groups)


async def view_group_detail(gid: int) -> Optional[Tuple[str, InlineKeyboardMarkup]]:
    groups = await DB.get_all_groups_full()
    group = None
    for g in groups:
        if g["chat_id"] == int(gid):
            group = g
            break
    if not group:
        return None

    # Group caption/buttons stored in broadcast_config under key groups_overrides
    overrides = await _get_group_override(gid)
    cap_state = (
        "✅ custom" if overrides.get("caption") else "🌐 global default"
    )
    btn_count = (
        len(overrides.get("buttons") or [])
        if overrides.get("buttons") is not None
        else None
    )
    btn_state = (
        "🌐 global default"
        if btn_count is None
        else f"🔘 {btn_count} custom"
    )

    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"👥 <b>{fb('GROUP')}</b>",
        DIV, "",
        f"📛 {sc('title')} · <b>{_esc(group.get('title'))}</b>",
        f"🆔 {sc('chat id')} · <code>{group.get('chat_id')}</code>",
        "",
        DIV2, "",
        f"📝 {sc('caption')} · <b>{cap_state}</b>",
        f"🔘 {sc('buttons')} · <b>{btn_state}</b>",
        "", DIV2, "",
        f"📌 {sc('custom caption/buttons apply only here')}",
    ]
    return "\n".join(lines), KB.kb_group_view(group)


async def _get_group_override(gid: int) -> Dict[str, Any]:
    c = DB._cfg_coll()
    if c is None:
        return {}
    try:
        doc = await c.find_one({"_id": "group_overrides"}) or {}
        return (doc.get("map") or {}).get(str(int(gid))) or {}
    except Exception:
        return {}


async def _set_group_override(gid: int, **fields) -> bool:
    c = DB._cfg_coll()
    if c is None:
        return False
    try:
        doc = await c.find_one({"_id": "group_overrides"}) or {}
        mp = dict(doc.get("map") or {})
        key = str(int(gid))
        mp[key] = {**(mp.get(key) or {}), **fields}
        await c.update_one(
            {"_id": "group_overrides"},
            {"$set": {"map": mp, "updated_at": __import__("time").time()}},
            upsert=True,
        )
        return True
    except Exception:
        return False


async def view_users_menu() -> Tuple[str, InlineKeyboardMarkup]:
    count = await DB.count_users()
    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"👤 <b>{fb('BROADCAST TO USERS')}</b>",
        DIV, "",
        f"📊 {sc('total users')} · <code>{_fmt_int(count)}</code>",
        "", DIV2,
        f"📌 {sc('user broadcasts support auto-delete timers')}",
        f"📌 {sc('you will pick a timer before starting')}",
        "", DIV2,
    ]
    return "\n".join(lines), KB.kb_users_menu(count)


async def view_caption() -> Tuple[str, InlineKeyboardMarkup]:
    cap = await DB.get_global_caption()
    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📝 <b>{fb('DEFAULT BROADCAST CAPTION')}</b>",
        DIV, "",
        f"<b>{sc('current')}:</b>", "",
        f"<code>{_esc(cap)}</code>",
        "", DIV2, "",
        f"📌 {sc('placeholders')}:",
        f"• <code>{{file_name}}</code> <code>{{file_size}}</code>",
        f"• <code>{{rating}}</code> <code>{{year}}</code> "
        f"<code>{{file_caption}}</code>",
    ]
    return "\n".join(lines), KB.kb_caption()


async def view_buttons() -> Tuple[str, InlineKeyboardMarkup]:
    btns = await DB.get_global_buttons()
    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🔘 <b>{fb('DEFAULT BROADCAST BUTTONS')}</b>",
        DIV, "",
    ]
    if not btns:
        lines.append(f"⚪ {sc('no buttons added yet')}")
    else:
        for i, b in enumerate(btns, 1):
            lines.append(f"{i}. <b>{_esc(b.get('name'))}</b>")
            lines.append(f"   <code>{_esc(b.get('url'))}</code>")
            lines.append("")
    lines += [
        DIV2,
        f"ᴛʜᴇꜱᴇ ᴀʀᴇ ᴜꜱᴇᴅ ꜰᴏʀ ɢʀᴏᴜᴘꜱ ᴀɴᴅ ᴜꜱᴇʀꜱ.",
    ]
    return "\n".join(lines), KB.kb_buttons(btns)


async def view_button_detail(
    idx: int,
) -> Optional[Tuple[str, InlineKeyboardMarkup]]:
    btns = await DB.get_global_buttons()
    if idx < 0 or idx >= len(btns):
        return None
    b = btns[idx]
    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🔘 <b>{fb('BUTTON DETAILS')}</b>",
        DIV, "",
        f"📛 {sc('name')} · <b>{_esc(b.get('name'))}</b>",
        f"🔗 {sc('url')} · <code>{_esc(b.get('url'))}</code>",
    ]
    return "\n".join(lines), KB.kb_button_view(idx)


async def view_history() -> Tuple[str, InlineKeyboardMarkup]:
    hist = await DB.get_history(10)
    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📊 <b>{fb('BROADCAST HISTORY')}</b>",
        DIV, "",
    ]
    if not hist:
        lines.append(f"⚪ {sc('no broadcasts yet')}")
    else:
        for h in hist:
            kind = h.get("kind", "?")
            icon = {
                "users": "👤", "channels": "📢",
                "channel": "📢", "groups": "👥",
            }.get(kind, "📢")
            try:
                t = datetime.fromtimestamp(
                    h.get("created_at", 0)
                ).strftime("%d %b %H:%M")
            except Exception:
                t = "?"
            ad = h.get("autodelete_seconds", 0)
            ad_str = f" · ⏱️ {_fmt_duration(ad)}" if ad else ""
            lines.append(
                f"{icon} <b>{kind.upper()}</b> · "
                f"<code>{t}</code>{ad_str}"
            )
            lines.append(
                f"   ✅ {h.get('sent', 0)}/{h.get('total', 0)}"
            )
            lines.append("")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 REFRESH",
                              callback_data="bc:history")],
        [InlineKeyboardButton("◀️ BACK", callback_data="bc:main"),
         InlineKeyboardButton("❌ CLOSE", callback_data="bc:close")],
    ])
    return "\n".join(lines), kb


async def view_stats() -> Tuple[str, InlineKeyboardMarkup]:
    hist = await DB.get_history(100)
    total_b = len(hist)
    total_sent = sum(h.get("sent", 0) for h in hist)
    total_failed = sum(h.get("failed", 0) for h in hist)
    total_blocked = sum(h.get("blocked", 0) for h in hist)
    total_deleted = sum(h.get("deleted", 0) for h in hist)
    ad_pending = await DB.count_scheduled_autodeletes()

    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📊 <b>{fb('BROADCAST STATISTICS')}</b>",
        DIV, "",
        f"🔢 {sc('total broadcasts')} · "
        f"<code>{_fmt_int(total_b)}</code>",
        "", DIV2, "",
        f"✅ {sc('sent')} · <code>{_fmt_int(total_sent)}</code>",
        f"❌ {sc('failed')} · <code>{_fmt_int(total_failed)}</code>",
        f"🚫 {sc('blocked')} · <code>{_fmt_int(total_blocked)}</code>",
        f"👻 {sc('deleted')} · <code>{_fmt_int(total_deleted)}</code>",
        "", DIV2, "",
        f"⏱️ {sc('pending auto-deletes')} · "
        f"<code>{_fmt_int(ad_pending)}</code>",
    ]
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 REFRESH",
                              callback_data="bc:stats"),
         InlineKeyboardButton("◀️ BACK",
                              callback_data="bc:main")],
    ])
    return "\n".join(lines), kb


async def view_autodelete() -> Tuple[str, InlineKeyboardMarkup]:
    from plugins.broadcast.config import (
        AUTODELETE_PRESETS, AUTODELETE_SCAN_INTERVAL,
    )
    count = await DB.count_scheduled_autodeletes()
    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"⏱️ <b>{fb('AUTO-DELETE STATUS')}</b>",
        DIV, "",
        f"📊 {sc('pending deletions')} · "
        f"<code>{_fmt_int(count)}</code>",
        "", DIV2, "",
        f"📌 {sc('when broadcasting, you pick a timer')}",
        f"📌 {sc('after the timer expires, messages are deleted')}",
        f"📌 {sc('scheduler runs every')} "
        f"<code>{AUTODELETE_SCAN_INTERVAL}s</code>",
        "", DIV2, "",
        f"🎛️ {sc('available presets')}:",
    ]
    for d, s, label in AUTODELETE_PRESETS:
        icon = "♾️" if s == 0 else "⏱️"
        lines.append(f"• {icon} {label}")
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 REFRESH",
                              callback_data="bc:autodelete")],
        [InlineKeyboardButton("◀️ BACK", callback_data="bc:main"),
         InlineKeyboardButton("❌ CLOSE",
                              callback_data="bc:close")],
    ])
    return "\n".join(lines), kb


__all__ = [
    "safe_edit",
    "view_main", "view_channels", "view_channel_detail",
    "view_groups", "view_users_menu",
    "view_caption", "view_buttons", "view_button_detail",
    "view_history", "view_stats", "view_autodelete",
    "view_group_detail", "_get_group_override", "_set_group_override",
]
