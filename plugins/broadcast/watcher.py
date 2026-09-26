# ============================================================
# 🏨 DOWNTOWN VILLA — BROADCAST CENTER (v3 — FULL + TIMERS)
# ============================================================
#
# Upload to BROADCAST_CHANNEL_ID → full broadcast center.
#
# Features:
#   • Channel picker with real channels
#   • Per-channel caption/buttons editor
#   • Group picker
#   • User filters (all / premium)
#   • Timer picker for channels / groups / users
#   • Full preview + live progress + final report
#   • Send-to-all uses each channel's own config
#
# ============================================================

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.errors import FloodWait
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from core import config
from utils import fonts as F
from utils import format as FM
from utils import progress as P

logger = logging.getLogger(__name__)


# ============================================================
# SESSION STATE
# ============================================================

_sessions: Dict[int, Dict[str, Any]] = {}
SESSION_TTL = 900.0


def _ss_new(uid: int, **data) -> Dict[str, Any]:
    s = {
        "expires": time.time() + SESSION_TTL,
        "created": time.time(),
        **data,
    }
    _sessions[int(uid)] = s
    return s


def _ss_get(uid: int) -> Optional[Dict[str, Any]]:
    s = _sessions.get(int(uid))
    if not s:
        return None
    if time.time() > s.get("expires", 0):
        _sessions.pop(int(uid), None)
        return None
    return s


def _ss_update(uid: int, **data) -> None:
    s = _sessions.get(int(uid))
    if s:
        s.update(data)
        s["expires"] = time.time() + SESSION_TTL


def _ss_drop(uid: int) -> None:
    _sessions.pop(int(uid), None)


# ============================================================
# TIMER PRESETS
# ============================================================

TIMER_PRESETS = [
    (0,       "♾️ never"),
    (86400,   "⏱️ 1 day"),
    (259200,  "⏱️ 3 days"),
    (604800,  "⏱️ 7 days"),
    (2592000, "⏱️ 30 days"),
]


def _fmt_timer(secs: int) -> str:
    if secs == 0:
        return "♾️ never"
    return f"⏱️ {FM.duration_short(secs)}"


def _is_admin(uid) -> bool:
    try:
        return int(uid) in [int(a) for a in config.ADMINS]
    except Exception:
        return False


def _cb(*parts) -> str:
    return "bca:" + ":".join(str(p) for p in parts)


# ============================================================
# HELPERS
# ============================================================

async def _count_channels() -> int:
    from plugins.broadcast import channels as CH
    try:
        return len([
            c for c in (await CH.list_channels())
            if c.get("enabled", True)
        ])
    except Exception:
        return 0


async def _count_groups() -> int:
    from database import db_registry
    try:
        db = db_registry.get_user_db()
        if db is not None:
            return await db["groups"].count_documents({})
    except Exception:
        pass
    return 0


async def _channel_title(cid: int) -> str:
    from plugins.broadcast import channels as CH
    try:
        ch = await CH.get_channel(cid)
        if ch:
            return str(ch.get("title") or cid)[:40]
    except Exception:
        pass
    return str(cid)


async def _edit(q: CallbackQuery, text: str, kb=None) -> None:
    try:
        await q.message.edit_text(
            text, reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        if "not modified" not in str(e).lower():
            logger.debug(f"[BC-C] edit: {e}")


# ============================================================
# WATCHER — fires on upload to broadcast channel
# ============================================================

def _channel_filter():
    ch = getattr(config, "BROADCAST_CHANNEL_ID", None)
    if not ch:
        return None
    return filters.chat(ch) & ~filters.service


_FILTER = _channel_filter()


def _extract_name(message: Message) -> str:
    try:
        for attr in ("document", "video", "audio", "photo", "animation"):
            m = getattr(message, attr, None)
            if m:
                return (
                    getattr(m, "file_name", None)
                    or message.caption
                    or f"{attr} file"
                )
        if message.text:
            return message.text[:50]
    except Exception:
        pass
    return "media"


if _FILTER is not None:

    @Client.on_message(_FILTER, group=-8305)
    async def broadcast_watcher(client: Client, message: Message):
        try:
            uid = message.from_user.id if message.from_user else 0

            chat_id = int(message.chat.id)
            msg_id = int(message.id)

            file_name = _extract_name(message)
            file_type = (
                message.media.value if message.media else "text"
            )
            original_caption = message.caption or ""

            _ss_new(
                uid,
                source_chat_id=chat_id,
                source_msg_id=msg_id,
                source_file_name=file_name,
                source_file_type=file_type,
                source_original_caption=original_caption,
                caption_mode="auto",
                custom_caption=None,
                target_kind=None,
                target_channel_id=None,
                target_group_ids=None,
                target_user_filter=None,
                auto_delete_secs=0,
                timer_context=None,
                awaiting=None,
            )

            await _render_main(client, uid, reply_to=message)

        except Exception as e:
            logger.exception(f"[BC-C] watcher: {e}")


# ============================================================
# MAIN MENU
# ============================================================

async def _render_main(
    client: Client, uid: int,
    reply_to: Optional[Message] = None,
) -> None:
    s = _ss_get(uid)
    if not s:
        return

    name = s.get("source_file_name") or "file"
    ftype = s.get("source_file_type") or "media"

    from plugins.broadcast import channels as CH
    from database import db_registry

    chans = await CH.list_channels()
    ch_count = len([c for c in chans if c.get("enabled", True)])

    group_count = 0
    user_count = 0
    try:
        db = db_registry.get_user_db()
        if db is not None:
            group_count = await db["groups"].count_documents({})
            user_count = await db["users"].count_documents(
                {"blocked_bot": {"$ne": True}}
            )
    except Exception:
        pass

    cap_mode = s.get("caption_mode", "auto")
    cap_icon = {
        "auto": "🌐 global",
        "keep": "📄 original",
        "custom": "✏️ custom",
        "none": "🚫 none",
    }.get(cap_mode, "?")

    text = "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"📢 <b>{F.fb('BROADCAST CENTER')}</b>",
        F.DIV, "",
        f"📦 <b>{F.fb('SOURCE')}</b>",
        f"   📎 <code>{name[:40]}</code>",
        f"   🎞️ <b>{ftype}</b>",
        f"   📝 {F.sc('caption')} · <b>{cap_icon}</b>",
        "",
        F.DIV_S,
        f"🎯 <b>{F.fb('TARGETS')}</b>",
        f"   📢 {F.sc('channels')} · <b>{ch_count}</b>",
        f"   👥 {F.sc('groups')} · <b>{group_count}</b>",
        f"   👤 {F.sc('users')} · <b>{user_count}</b>",
        "",
        F.DIV_S,
        f"📌 {F.sc('pick where to send this')}",
    ])

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"📢 {F.sc('channels')} ({ch_count})",
                callback_data=_cb("channels"),
            ),
            InlineKeyboardButton(
                f"👥 {F.sc('groups')} ({group_count})",
                callback_data=_cb("groups"),
            ),
        ],
        [
            InlineKeyboardButton(
                f"👤 {F.sc('users')} ({user_count})",
                callback_data=_cb("users"),
            ),
            InlineKeyboardButton(
                f"📝 {F.sc('caption')}",
                callback_data=_cb("cap_menu"),
            ),
        ],
        [
            InlineKeyboardButton(
                f"👁 {F.sc('preview')}",
                callback_data=_cb("preview"),
            ),
            InlineKeyboardButton(
                f"📊 {F.sc('history')}",
                callback_data=_cb("history:0"),
            ),
        ],
        [
            InlineKeyboardButton(
                f"❌ {F.sc('cancel')}",
                callback_data=_cb("cancel"),
            ),
        ],
    ])

    if reply_to is not None:
        try:
            await reply_to.reply_text(
                text, reply_markup=kb,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                quote=True,
            )
        except Exception as e:
            logger.debug(f"[BC-C] main reply: {e}")
    else:
        try:
            from core.client import client as C
            if C is not None:
                await C.send_message(
                    chat_id=uid,
                    text=text,
                    reply_markup=kb,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
        except Exception as e:
            logger.debug(f"[BC-C] main send: {e}")


# ============================================================
# TIMER PICKER (generic)
# ============================================================

async def _render_timer_for(
    q: CallbackQuery,
    *,
    back_cb: str,
    confirm_cb_template: str,
    title: str,
    target_count: int,
) -> None:
    uid = q.from_user.id
    s = _ss_get(uid) or {}
    selected = s.get("auto_delete_secs", 0)

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"⏱️ <b>{F.fb('AUTO-DELETE TIMER')}</b>",
        F.DIV, "",
        f"🎯 {F.sc('target')} · <b>{F.sc(title)}</b>",
        f"📊 {F.sc('count')} · <b>{FM.num(target_count)}</b>",
        "",
        F.DIV_S,
        f"📌 {F.sc('choose how long the file stays')}",
        f"📌 {F.sc('never = stays forever')}",
        f"📌 {F.sc('others = auto-delete after that time')}",
        "",
        f"⏱️ {F.sc('current')} · <b>{_fmt_timer(selected)}</b>",
    ]

    rows: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []
    for secs, label in TIMER_PRESETS:
        mark = "✅ " if secs == selected else ""
        row.append(InlineKeyboardButton(
            f"{mark}{label}",
            callback_data=_cb(f"timer_set:{secs}"),
        ))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    rows.append([InlineKeyboardButton(
        f"✅ {F.sc('continue')}",
        callback_data=confirm_cb_template.replace(
            "{secs}", str(selected)
        ),
    )])
    rows.append([InlineKeyboardButton(
        f"⬅️ {F.sc('back')}",
        callback_data=back_cb,
    )])
    rows.append([InlineKeyboardButton(
        f"❌ {F.sc('cancel')}",
        callback_data=_cb("cancel"),
    )])

    await _edit(q, "\n".join(lines), InlineKeyboardMarkup(rows))
    await q.answer()


# ============================================================
# CHANNEL PICKER
# ============================================================

async def _render_channel_picker(q: CallbackQuery) -> None:
    uid = q.from_user.id
    s = _ss_get(uid)
    if not s:
        return await q.answer("session expired", show_alert=True)

    from plugins.broadcast import channels as CH
    channels = await CH.list_channels()
    enabled = [c for c in channels if c.get("enabled", True)]

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"📢 <b>{F.fb('SELECT CHANNELS')}</b>",
        F.DIV, "",
        f"📊 {F.sc('total')} · <b>{len(enabled)}</b>",
        "",
    ]

    if not enabled:
        lines.append(f"⚪ {F.sc('no channels registered')}")
        lines.append("")
        lines.append(f"📌 {F.sc('use /broadcast → channels to add')}")
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                f"⬅️ {F.sc('back')}",
                callback_data=_cb("main"),
            ),
        ]])
        await _edit(q, "\n".join(lines), kb)
        return await q.answer()

    lines += [
        F.DIV_S,
        f"📝 {F.sc('channels with custom caption')}",
        f"🔘 {F.sc('channels with custom buttons')}",
        "",
        f"📌 {F.sc('tap a channel to configure & send')}",
    ]

    rows: List[List[InlineKeyboardButton]] = []
    rows.append([InlineKeyboardButton(
        f"🎯 {F.sc('SEND TO ALL')} ({len(enabled)})",
        callback_data=_cb("ch_all_timer"),
    )])

    for c in enabled:
        cid = c.get("chat_id")
        title = str(c.get("title") or cid)[:26]
        marks = ""
        if c.get("caption") is not None:
            marks += "📝"
        if c.get("buttons") is not None:
            marks += "🔘"
        if c.get("primary"):
            marks = "⭐" + marks
        prefix = f"{marks} " if marks else "⚪ "
        rows.append([InlineKeyboardButton(
            f"{prefix}{title}",
            callback_data=_cb(f"ch:{cid}"),
        )])

    rows.append([InlineKeyboardButton(
        f"⬅️ {F.sc('back')}",
        callback_data=_cb("main"),
    )])

    await _edit(q, "\n".join(lines), InlineKeyboardMarkup(rows))
    await q.answer()


# ============================================================
# CHANNEL EDITOR
# ============================================================

async def _render_channel_editor(q: CallbackQuery, cid: int) -> None:
    uid = q.from_user.id
    from plugins.broadcast import channels as CH
    ch = await CH.get_channel(cid)
    if not ch:
        return await q.answer("channel not found", show_alert=True)

    title = str(ch.get("title") or cid)[:50]

    ch_cap = ch.get("caption")
    s = _ss_get(uid)
    override = (s or {}).get("custom_caption")
    mode = (s or {}).get("caption_mode", "auto")
    timer = (s or {}).get("auto_delete_secs", 0)

    if override:
        effective = override
        cap_src = "✏️ custom (this send)"
    elif ch_cap is not None:
        effective = ch_cap
        cap_src = "📝 channel custom"
    else:
        from plugins.broadcast import templates as T
        effective = await T.get_caption()
        cap_src = "🌐 global default"

    preview = (effective or "")[:200]
    if len(effective or "") > 200:
        preview += "…"

    ch_btns = ch.get("buttons")
    if ch_btns is not None:
        btn_src = f"🔘 custom ({len(ch_btns)})"
    else:
        from plugins.broadcast import templates as T
        g = await T.get_buttons()
        btn_src = f"🌐 global ({len(g)})"

    text = "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"📢 <b>{F.fb('CHANNEL EDITOR')}</b>",
        F.DIV, "",
        f"📛 <b>{F.sc(title)}</b>",
        f"🆔 <code>{cid}</code>",
        "",
        F.DIV_S,
        f"📝 <b>{F.fb('CAPTION')}</b>",
        f"   {F.sc('source')} · <b>{cap_src}</b>",
        "",
        f"<code>{F.sc(preview) if preview else '(empty)'}</code>",
        "",
        F.DIV_S,
        f"🔘 <b>{F.fb('BUTTONS')}</b>",
        f"   {F.sc('source')} · <b>{btn_src}</b>",
        "",
        F.DIV_S,
        f"⏱️ <b>{F.fb('AUTO-DELETE')}</b>",
        f"   {F.sc('current')} · <b>{_fmt_timer(timer)}</b>",
        "",
        F.DIV_S,
        f"📌 {F.sc('edit, then send')}",
    ])

    rows: List[List[InlineKeyboardButton]] = [
        [
            InlineKeyboardButton(
                f"✏️ {F.sc('edit caption')}",
                callback_data=_cb(f"ch_cap_edit:{cid}"),
            ),
            InlineKeyboardButton(
                f"🔄 {F.sc('replace')}",
                callback_data=_cb(f"ch_cap_replace:{cid}"),
            ),
        ],
        [
            InlineKeyboardButton(
                f"📄 {F.sc('use original')}",
                callback_data=_cb(f"ch_cap_original:{cid}"),
            ),
            InlineKeyboardButton(
                f"🌐 {F.sc('use global')}",
                callback_data=_cb(f"ch_cap_global:{cid}"),
            ),
        ],
        [
            InlineKeyboardButton(
                f"🗑 {F.sc('remove caption')}",
                callback_data=_cb(f"ch_cap_none:{cid}"),
            ),
            InlineKeyboardButton(
                f"↩️ {F.sc('reset')}",
                callback_data=_cb(f"ch_cap_reset:{cid}"),
            ),
        ],
        [
            InlineKeyboardButton(
                f"🔘 {F.sc('manage buttons')}",
                callback_data=_cb(f"ch_btns:{cid}"),
            ),
        ],
        [
            InlineKeyboardButton(
                f"⏱️ {F.sc('pick timer')} · {_fmt_timer(timer)}",
                callback_data=_cb(f"ch_timer:{cid}"),
            ),
        ],
        [
            InlineKeyboardButton(
                f"💾 {F.sc('save as channel default')}",
                callback_data=_cb(f"ch_save_default:{cid}"),
            ),
        ],
        [
            InlineKeyboardButton(
                f"🚀 {F.sc('send now')}",
                callback_data=_cb(f"ch_timer:{cid}"),
            ),
        ],
        [
            InlineKeyboardButton(
                f"⬅️ {F.sc('back')}",
                callback_data=_cb("channels"),
            ),
            InlineKeyboardButton(
                f"❌ {F.sc('cancel')}",
                callback_data=_cb("cancel"),
            ),
        ],
    ]

    await _edit(q, text, InlineKeyboardMarkup(rows))
    await q.answer()


# ============================================================
# GROUP PICKER
# ============================================================

async def _render_group_picker(q: CallbackQuery) -> None:
    from database import db_registry
    groups: List[Dict[str, Any]] = []
    try:
        db = db_registry.get_user_db()
        if db is not None:
            cursor = db["groups"].find({}, {
                "chat_id": 1, "title": 1, "username": 1,
            }).limit(50)
            groups = await cursor.to_list(length=50)
    except Exception as e:
        logger.debug(f"[BC-C] groups: {e}")

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"👥 <b>{F.fb('SELECT GROUPS')}</b>",
        F.DIV, "",
        f"📊 {F.sc('total')} · <b>{len(groups)}</b>",
        "",
        F.DIV_S,
        f"📌 {F.sc('groups use global caption & buttons')}",
        f"📌 {F.sc('tap one, or send to all')}",
    ]

    rows: List[List[InlineKeyboardButton]] = []

    if groups:
        rows.append([InlineKeyboardButton(
            f"🎯 {F.sc('SEND TO ALL')} ({len(groups)})",
            callback_data=_cb("gr_all_timer"),
        )])

    for g in groups[:8]:
        cid = g.get("chat_id")
        title = str(g.get("title") or cid)[:30]
        rows.append([InlineKeyboardButton(
            f"👥 {title}",
            callback_data=_cb(f"gr_timer:{cid}"),
        )])

    if len(groups) > 8:
        rows.append([InlineKeyboardButton(
            f"📋 {F.sc('more')} ({len(groups) - 8})",
            callback_data=_cb("gr_more:1"),
        )])

    rows.append([InlineKeyboardButton(
        f"⬅️ {F.sc('back')}",
        callback_data=_cb("main"),
    )])

    await _edit(q, "\n".join(lines), InlineKeyboardMarkup(rows))
    await q.answer()


# ============================================================
# USER TARGET PICKER
# ============================================================

async def _render_user_picker(q: CallbackQuery) -> None:
    from database import db_registry
    counts = {"all": 0, "premium": 0, "blocked": 0}
    try:
        db = db_registry.get_user_db()
        if db is not None:
            counts["all"] = await db["users"].count_documents(
                {"blocked_bot": {"$ne": True}}
            )
            counts["blocked"] = await db["users"].count_documents(
                {"blocked_bot": True}
            )
            try:
                counts["premium"] = await db[
                    "premium_users"
                ].count_documents({"status": "active"})
            except Exception:
                pass
    except Exception:
        pass

    text = "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"👤 <b>{F.fb('SELECT USER TARGET')}</b>",
        F.DIV, "",
        f"📊 <b>{F.fb('AVAILABLE')}</b>",
        f"   👥 {F.sc('all users')} · <b>{FM.num(counts['all'])}</b>",
        f"   💎 {F.sc('premium')} · <b>{FM.num(counts['premium'])}</b>",
        f"   🚫 {F.sc('blocked')} · <b>{FM.num(counts['blocked'])}</b>",
        "",
        F.DIV_S,
        f"📌 {F.sc('pick a filter')}",
    ])

    rows = [
        [InlineKeyboardButton(
            f"👥 {F.sc('all users')} ({FM.num(counts['all'])})",
            callback_data=_cb("us_filter:all"),
        )],
        [InlineKeyboardButton(
            f"💎 {F.sc('premium only')} ({FM.num(counts['premium'])})",
            callback_data=_cb("us_filter:premium"),
        )],
        [
            InlineKeyboardButton(
                f"⬅️ {F.sc('back')}",
                callback_data=_cb("main"),
            ),
            InlineKeyboardButton(
                f"❌ {F.sc('cancel')}",
                callback_data=_cb("cancel"),
            ),
        ],
    ]

    await _edit(q, text, InlineKeyboardMarkup(rows))
    await q.answer()


# ============================================================
# USER TIMER PICKER (kept for the us_timer_menu route)
# ============================================================

async def _render_us_timer_picker(q: CallbackQuery) -> None:
    uid = q.from_user.id
    s = _ss_get(uid) or {}
    selected = s.get("auto_delete_secs", 0)
    flt = s.get("target_user_filter") or "all"

    text = "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"⏱️ <b>{F.fb('AUTO-DELETE TIMER')}</b>",
        F.DIV, "",
        f"👤 {F.sc('filter')} · <b>{F.sc(flt)}</b>",
        "",
        f"⏱️ {F.sc('current')} · <b>{_fmt_timer(selected)}</b>",
        "",
        F.DIV_S,
        f"📌 {F.sc('how long should the message stay?')}",
    ])

    rows: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []
    for secs, label in TIMER_PRESETS:
        mark = "✅ " if secs == selected else ""
        row.append(InlineKeyboardButton(
            f"{mark}{label}",
            callback_data=_cb(f"us_timer:{secs}"),
        ))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    rows.append([InlineKeyboardButton(
        f"✅ {F.sc('continue')}",
        callback_data=_cb("us_go"),
    )])
    rows.append([InlineKeyboardButton(
        f"⬅️ {F.sc('back')}",
        callback_data=_cb("users"),
    )])

    await _edit(q, text, InlineKeyboardMarkup(rows))
    await q.answer()


# ============================================================
# PREVIEW
# ============================================================

async def _render_preview(q: CallbackQuery) -> None:
    uid = q.from_user.id
    s = _ss_get(uid)
    if not s:
        return await q.answer("session expired", show_alert=True)

    cap = await _effective_caption(uid)
    btns = await _effective_buttons(uid)

    name = s.get("source_file_name") or "file"
    timer = s.get("auto_delete_secs", 0)

    preview = cap[:300] + ("…" if len(cap) > 300 else "")

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"👁 <b>{F.fb('BROADCAST PREVIEW')}</b>",
        F.DIV, "",
        f"📦 <b>{F.sc(name[:50])}</b>",
        "",
        F.DIV_S,
        f"📝 <b>{F.fb('CAPTION')}</b>",
        "",
        f"<code>{F.sc(preview) if preview else '(empty)'}</code>",
        "",
        F.DIV_S,
        f"🔘 <b>{F.fb('BUTTONS')}</b> · <b>{len(btns)}</b>",
    ]
    for b in btns[:6]:
        lines.append(
            f"   • <b>{F.sc(str(b.get('name'))[:40])}</b>"
        )

    lines += [
        "",
        F.DIV_S,
        f"⏱️ {F.sc('timer')} · <b>{_fmt_timer(timer)}</b>",
    ]

    rows = [
        [
            InlineKeyboardButton(
                f"📝 {F.sc('caption')}",
                callback_data=_cb("cap_menu"),
            ),
        ],
        [
            InlineKeyboardButton(
                f"⬅️ {F.sc('back')}",
                callback_data=_cb("main"),
            ),
        ],
    ]

    await _edit(q, "\n".join(lines), InlineKeyboardMarkup(rows))
    await q.answer()


# ============================================================
# CAPTION HELPERS
# ============================================================

async def _effective_caption(uid: int) -> str:
    s = _ss_get(uid)
    if not s:
        return ""

    mode = s.get("caption_mode", "auto")

    if mode == "custom" and s.get("custom_caption") is not None:
        return s["custom_caption"]

    if mode == "keep":
        return s.get("source_original_caption") or ""

    if mode == "none":
        return ""

    cid = s.get("target_channel_id")
    if cid:
        from plugins.broadcast import channels as CH
        ch = await CH.get_channel(cid)
        if ch and ch.get("caption") is not None:
            return ch["caption"]

    from plugins.broadcast import templates as T
    return await T.get_caption()


async def _effective_buttons(uid: int) -> List[Dict[str, Any]]:
    s = _ss_get(uid)
    if not s:
        return []

    cid = s.get("target_channel_id")
    if cid:
        from plugins.broadcast import channels as CH
        ch = await CH.get_channel(cid)
        if ch and ch.get("buttons") is not None:
            return list(ch["buttons"])

    from plugins.broadcast import templates as T
    return await T.get_buttons()


# ============================================================
# CAPTION MENU
# ============================================================

async def _render_caption_menu(q: CallbackQuery) -> None:
    uid = q.from_user.id
    s = _ss_get(uid)
    if not s:
        return await q.answer("session expired", show_alert=True)

    cap = await _effective_caption(uid)
    mode = s.get("caption_mode", "auto")
    preview = cap[:250] + ("…" if len(cap) > 250 else "")

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"📝 <b>{F.fb('CAPTION MANAGER')}</b>",
        F.DIV, "",
        f"📌 {F.sc('mode')} · <b>{F.sc(mode)}</b>",
        "",
        F.DIV_S,
        f"<b>{F.sc('current caption')}:</b>",
        "",
        f"<code>{F.sc(preview) if preview else '(empty)'}</code>",
        "",
        F.DIV_S,
        f"📌 {F.sc('choose how to handle the caption')}",
    ]

    rows = [
        [
            InlineKeyboardButton(
                f"📄 {F.sc('original')}",
                callback_data=_cb("cap_mode:keep"),
            ),
            InlineKeyboardButton(
                f"🌐 {F.sc('global')}",
                callback_data=_cb("cap_mode:auto"),
            ),
        ],
        [
            InlineKeyboardButton(
                f"✏️ {F.sc('edit existing')}",
                callback_data=_cb("cap_edit"),
            ),
            InlineKeyboardButton(
                f"🔄 {F.sc('replace')}",
                callback_data=_cb("cap_replace"),
            ),
        ],
        [
            InlineKeyboardButton(
                f"🗑 {F.sc('remove')}",
                callback_data=_cb("cap_mode:none"),
            ),
            InlineKeyboardButton(
                f"↩️ {F.sc('reset')}",
                callback_data=_cb("cap_reset"),
            ),
        ],
        [
            InlineKeyboardButton(
                f"⬅️ {F.sc('back')}",
                callback_data=_cb("main"),
            ),
        ],
    ]

    await _edit(q, "\n".join(lines), InlineKeyboardMarkup(rows))
    await q.answer()


# ============================================================
# CONFIRM SCREENS
# ============================================================

async def _render_channels_all_confirm(q: CallbackQuery) -> None:
    from plugins.broadcast import channels as CH
    channels = await CH.list_channels()
    enabled = [c for c in channels if c.get("enabled", True)]

    custom_cap = sum(1 for c in enabled if c.get("caption") is not None)
    custom_btn = sum(1 for c in enabled if c.get("buttons") is not None)

    uid = q.from_user.id
    s = _ss_get(uid) or {}
    timer = s.get("auto_delete_secs", 0)

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"🎯 <b>{F.fb('SEND TO ALL CHANNELS')}</b>",
        F.DIV, "",
        f"📊 {F.sc('total')} · <b>{len(enabled)}</b>",
        f"⏱️ {F.sc('auto-delete')} · <b>{_fmt_timer(timer)}</b>",
        "",
        F.DIV_S,
        f"📝 {F.sc('with custom caption')} · <b>{custom_cap}</b>",
        f"🔘 {F.sc('with custom buttons')} · <b>{custom_btn}</b>",
        "",
        f"📌 {F.sc('each channel keeps its own caption')}",
        f"📌 {F.sc('others use global default')}",
    ]

    rows = [
        [InlineKeyboardButton(
            f"🚀 {F.sc('confirm & send')}",
            callback_data=_cb("ch_all_go"),
        )],
        [InlineKeyboardButton(
            f"⏱️ {F.sc('change timer')}",
            callback_data=_cb("ch_all_timer"),
        )],
        [
            InlineKeyboardButton(
                f"⬅️ {F.sc('back')}",
                callback_data=_cb("channels"),
            ),
            InlineKeyboardButton(
                f"❌ {F.sc('cancel')}",
                callback_data=_cb("cancel"),
            ),
        ],
    ]

    await _edit(q, "\n".join(lines), InlineKeyboardMarkup(rows))
    await q.answer()


async def _render_groups_all_confirm(q: CallbackQuery) -> None:
    from database import db_registry
    count = 0
    try:
        db = db_registry.get_user_db()
        if db is not None:
            count = await db["groups"].count_documents({})
    except Exception:
        pass

    uid = q.from_user.id
    s = _ss_get(uid) or {}
    timer = s.get("auto_delete_secs", 0)

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"🎯 <b>{F.fb('SEND TO ALL GROUPS')}</b>",
        F.DIV, "",
        f"👥 {F.sc('targets')} · <b>{FM.num(count)}</b>",
        f"⏱️ {F.sc('auto-delete')} · <b>{_fmt_timer(timer)}</b>",
        "",
        F.DIV_S,
        f"📌 {F.sc('uses global caption & buttons')}",
    ]

    rows = [
        [InlineKeyboardButton(
            f"🚀 {F.sc('confirm & send')}",
            callback_data=_cb("gr_all_go"),
        )],
        [InlineKeyboardButton(
            f"⏱️ {F.sc('change timer')}",
            callback_data=_cb("gr_all_timer"),
        )],
        [
            InlineKeyboardButton(
                f"⬅️ {F.sc('back')}",
                callback_data=_cb("groups"),
            ),
            InlineKeyboardButton(
                f"❌ {F.sc('cancel')}",
                callback_data=_cb("cancel"),
            ),
        ],
    ]

    await _edit(q, "\n".join(lines), InlineKeyboardMarkup(rows))
    await q.answer()


async def _render_groups_single_confirm(
    q: CallbackQuery, gid: int,
) -> None:
    uid = q.from_user.id
    s = _ss_get(uid) or {}
    timer = s.get("auto_delete_secs", 0)

    from database import db_registry
    title = str(gid)
    try:
        db = db_registry.get_user_db()
        if db is not None:
            doc = await db["groups"].find_one(
                {"chat_id": gid}, {"title": 1},
            )
            if doc:
                title = str(doc.get("title") or gid)[:50]
    except Exception:
        pass

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"🎯 <b>{F.fb('CONFIRM GROUP')}</b>",
        F.DIV, "",
        f"👥 <b>{F.sc(title)}</b>",
        f"🆔 <code>{gid}</code>",
        "",
        f"⏱️ {F.sc('auto-delete')} · <b>{_fmt_timer(timer)}</b>",
        "",
        F.DIV_S,
        f"📌 {F.sc('uses global caption & buttons')}",
    ]

    rows = [
        [InlineKeyboardButton(
            f"🚀 {F.sc('confirm & send')}",
            callback_data=_cb(f"gr_send:{gid}"),
        )],
        [InlineKeyboardButton(
            f"⏱️ {F.sc('change timer')}",
            callback_data=_cb(f"gr_timer:{gid}"),
        )],
        [
            InlineKeyboardButton(
                f"⬅️ {F.sc('back')}",
                callback_data=_cb("groups"),
            ),
            InlineKeyboardButton(
                f"❌ {F.sc('cancel')}",
                callback_data=_cb("cancel"),
            ),
        ],
    ]

    await _edit(q, "\n".join(lines), InlineKeyboardMarkup(rows))
    await q.answer()


async def _render_users_confirm(q: CallbackQuery) -> None:
    uid = q.from_user.id
    s = _ss_get(uid)
    if not s:
        return await q.answer("session expired", show_alert=True)

    flt = s.get("target_user_filter") or "all"
    timer = s.get("auto_delete_secs", 0)

    from database import db_registry
    count = 0
    try:
        db = db_registry.get_user_db()
        if db is not None:
            query = {"blocked_bot": {"$ne": True}}
            if flt == "premium":
                cursor = db["premium_users"].find(
                    {"status": "active"}, {"user_id": 1},
                )
                docs = await cursor.to_list(length=100000)
                premium_ids = [
                    int(d["user_id"]) for d in docs if d.get("user_id")
                ]
                if premium_ids:
                    query = {
                        "user_id": {"$in": premium_ids},
                        "blocked_bot": {"$ne": True},
                    }
                else:
                    query = {"user_id": -1}
            count = await db["users"].count_documents(query)
    except Exception:
        pass

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"✅ <b>{F.fb('CONFIRM USER BROADCAST')}</b>",
        F.DIV, "",
        f"👤 {F.sc('filter')} · <b>{F.sc(flt)}</b>",
        f"📊 {F.sc('targets')} · <b>{FM.num(count)}</b>",
        f"⏱️ {F.sc('auto-delete')} · <b>{_fmt_timer(timer)}</b>",
        "",
        F.DIV_S,
        f"📌 {F.sc('uses current caption mode')}",
    ]

    rows = [
        [InlineKeyboardButton(
            f"🚀 {F.sc('confirm & send')}",
            callback_data=_cb("us_go"),
        )],
        [
            InlineKeyboardButton(
                f"⏱️ {F.sc('change timer')}",
                callback_data=_cb("us_timer_menu"),
            ),
            InlineKeyboardButton(
                f"⬅️ {F.sc('back')}",
                callback_data=_cb("users"),
            ),
        ],
    ]

    await _edit(q, "\n".join(lines), InlineKeyboardMarkup(rows))
    await q.answer()


# ============================================================
# HISTORY
# ============================================================

async def _render_history(q: CallbackQuery, page: int) -> None:
    from plugins.broadcast import state as BS
    try:
        runs = await BS.list_runs(limit=50)
    except Exception:
        runs = []

    total = len(runs)
    per = 5
    tp = max(1, (total + per - 1) // per)
    page = max(0, min(page, tp - 1))
    chunk = runs[page * per:(page + 1) * per]

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"📊 <b>{F.fb('BROADCAST HISTORY')}</b>",
        F.DIV, "",
        f"📊 {F.sc('total runs')} · <b>{total}</b>",
        f"📄 {F.sc('page')} · <b>{page + 1}/{tp}</b>",
        "",
    ]

    if not chunk:
        lines.append(f"⚪ {F.sc('no runs yet')}")
    else:
        for r in chunk:
            started = r.get("started_at")
            ts = "?"
            try:
                if started:
                    ts = started.strftime("%d %b %H:%M")
            except Exception:
                pass
            status = str(r.get("status") or "?")
            icon = {
                "completed": "✅", "running": "🟢",
                "cancelled": "🛑", "failed": "❌",
            }.get(status, "⚪")
            lines.append(
                f"{icon} <b>{F.sc(status)}</b> · "
                f"<code>{ts}</code>"
            )
            lines.append(
                f"   📢 {F.sc('kind')} · "
                f"<code>{r.get('kind') or '?'}</code>"
            )
            lines.append(
                f"   ✅ {FM.num(r.get('sent', 0))} · "
                f"❌ {FM.num(r.get('failed', 0))} · "
                f"🚫 {FM.num(r.get('blocked', 0))}"
            )
            lines.append("")

    rows = []
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(
            f"⬅️ {F.sc('prev')}",
            callback_data=_cb(f"history:{page - 1}"),
        ))
    if page < tp - 1:
        nav.append(InlineKeyboardButton(
            f"{F.sc('next')} ➡️",
            callback_data=_cb(f"history:{page + 1}"),
        ))
    if nav:
        rows.append(nav)

    rows.append([InlineKeyboardButton(
        f"⬅️ {F.sc('back')}",
        callback_data=_cb("main"),
    )])

    await _edit(q, "\n".join(lines), InlineKeyboardMarkup(rows))
    await q.answer()


# ============================================================
# ROUTER
# ============================================================

@Client.on_callback_query(
    filters.regex(r"^bca:"), group=-8304,
)
async def broadcast_center_router(client: Client, q: CallbackQuery):
    if not q.from_user or not _is_admin(q.from_user.id):
        return await q.answer("❌ admin only", show_alert=True)

    uid = q.from_user.id
    parts = str(q.data or "").split(":")
    action = parts[1] if len(parts) > 1 else ""

    try:
        # ── CANCEL ──
        if action == "cancel":
            _ss_drop(uid)
            try:
                await q.message.delete()
            except Exception:
                pass
            return await q.answer("cancelled")

        # ── MAIN ──
        if action == "main":
            await _render_main(client, uid)
            try:
                await q.message.delete()
            except Exception:
                pass
            return await q.answer()

        # ── HISTORY ──
        if action == "history":
            p = int(parts[2]) if len(parts) > 2 else 0
            return await _render_history(q, p)

        # ── CHANNELS ──
        if action == "channels":
            return await _render_channel_picker(q)

        if action == "ch_all":
            return await _render_channels_all_confirm(q)

        if action == "ch_all_go":
            return await _run_channels_all(client, q)

        if action == "ch":
            cid = int(parts[2]) if len(parts) > 2 else 0
            return await _render_channel_editor(q, cid)

        if action == "ch_send":
            cid = int(parts[2]) if len(parts) > 2 else 0
            return await _run_channel_single(client, q, cid)

        # ── CHANNEL TIMER FLOW ──
        if action == "ch_all_timer":
            _ss_update(uid, timer_context="ch_all")
            return await _render_timer_for(
                q,
                back_cb=_cb("channels"),
                confirm_cb_template=_cb("ch_all_confirm"),
                title="all channels",
                target_count=await _count_channels(),
            )

        if action == "ch_timer":
            cid = int(parts[2]) if len(parts) > 2 else 0
            _ss_update(uid, timer_context=f"ch:{cid}",
                       target_channel_id=cid)
            return await _render_timer_for(
                q,
                back_cb=_cb(f"ch:{cid}"),
                confirm_cb_template=_cb(f"ch_send:{cid}"),
                title=await _channel_title(cid),
                target_count=1,
            )

        if action == "ch_all_confirm":
            return await _render_channels_all_confirm(q)

        # ── GROUPS ──
        if action == "groups":
            return await _render_group_picker(q)

        if action == "gr_all":
            return await _render_groups_all_confirm(q)

        if action == "gr_all_go":
            return await _run_groups_all(client, q)

        if action == "gr_send":
            gid = int(parts[2]) if len(parts) > 2 else 0
            return await _run_groups_single(client, q, gid)

        if action == "gr_all_timer":
            _ss_update(uid, timer_context="gr_all")
            return await _render_timer_for(
                q,
                back_cb=_cb("groups"),
                confirm_cb_template=_cb("gr_all_confirm"),
                title="all groups",
                target_count=await _count_groups(),
            )

        if action == "gr_timer":
            gid = int(parts[2]) if len(parts) > 2 else 0
            _ss_update(uid, timer_context=f"gr:{gid}")
            return await _render_timer_for(
                q,
                back_cb=_cb("groups"),
                confirm_cb_template=_cb(f"gr_confirm:{gid}"),
                title=await _channel_title(gid),
                target_count=1,
            )

        if action == "gr_confirm":
            gid = int(parts[2]) if len(parts) > 2 else 0
            return await _render_groups_single_confirm(q, gid)

        if action == "gr_all_confirm":
            return await _render_groups_all_confirm(q)

        # ── USERS ──
        if action == "users":
            return await _render_user_picker(q)

        if action == "us_filter":
            flt = parts[2] if len(parts) > 2 else "all"
            _ss_update(uid, target_user_filter=flt)
            return await _render_us_timer_picker(q)

        if action == "us_timer_menu":
            return await _render_us_timer_picker(q)

        if action == "us_timer":
            secs = int(parts[2]) if len(parts) > 2 else 0
            _ss_update(uid, auto_delete_secs=secs)
            return await _render_us_timer_picker(q)

        if action == "us_go":
            return await _run_users(client, q)

        # ── CAPTION ──
        if action == "cap_menu":
            return await _render_caption_menu(q)

        if action == "cap_mode":
            mode = parts[2] if len(parts) > 2 else "auto"
            _ss_update(uid, caption_mode=mode)
            return await _render_caption_menu(q)

        if action == "cap_reset":
            _ss_update(uid, caption_mode="auto", custom_caption=None)
            return await _render_caption_menu(q)

        if action in ("cap_edit", "cap_replace"):
            _ss_update(uid, caption_mode="custom", awaiting="caption")
            text = "\n".join([
                f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                f"✏️ <b>{F.fb('SEND NEW CAPTION')}</b>",
                F.DIV, "",
                f"📌 {F.sc('send the caption as next message')}",
                f"📌 {F.sc('placeholders')}: "
                f"<code>{{file_name}}</code>",
                f"📌 {F.sc('send')} <code>-</code> {F.sc('to remove')}",
            ])
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"❌ {F.sc('cancel')}",
                    callback_data=_cb("cap_menu"),
                ),
            ]])
            await _edit(q, text, kb)
            return await q.answer()

        # ── PREVIEW ──
        if action == "preview":
            return await _render_preview(q)

        # ── PER-CHANNEL CAPTION ACTIONS ──
        if action == "ch_cap_edit":
            cid = int(parts[2])
            _ss_update(uid, awaiting="caption", target_channel_id=cid)
            text = "\n".join([
                f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                f"✏️ <b>{F.fb('EDIT CHANNEL CAPTION')}</b>",
                F.DIV, "",
                f"📌 {F.sc('send the new caption')}",
                f"📌 {F.sc('send')} <code>-</code> {F.sc('for empty')}",
            ])
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"❌ {F.sc('cancel')}",
                    callback_data=_cb(f"ch:{cid}"),
                ),
            ]])
            await _edit(q, text, kb)
            return await q.answer()

        if action == "ch_cap_replace":
            cid = int(parts[2])
            _ss_update(uid, awaiting="caption", target_channel_id=cid)
            text = "\n".join([
                f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                f"🔄 <b>{F.fb('REPLACE CAPTION')}</b>",
                F.DIV, "",
                f"📌 {F.sc('send the new caption')}",
            ])
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"❌ {F.sc('cancel')}",
                    callback_data=_cb(f"ch:{cid}"),
                ),
            ]])
            await _edit(q, text, kb)
            return await q.answer()

        if action == "ch_cap_original":
            cid = int(parts[2])
            _ss_update(uid, caption_mode="keep",
                       target_channel_id=cid, custom_caption=None)
            return await _render_channel_editor(q, cid)

        if action == "ch_cap_global":
            cid = int(parts[2])
            _ss_update(uid, caption_mode="auto",
                       target_channel_id=cid, custom_caption=None)
            return await _render_channel_editor(q, cid)

        if action == "ch_cap_none":
            cid = int(parts[2])
            _ss_update(uid, caption_mode="none",
                       target_channel_id=cid, custom_caption=None)
            return await _render_channel_editor(q, cid)

        if action == "ch_cap_reset":
            cid = int(parts[2])
            _ss_update(uid, caption_mode="auto",
                       target_channel_id=cid, custom_caption=None)
            return await _render_channel_editor(q, cid)

        if action == "ch_save_default":
            cid = int(parts[2])
            from plugins.broadcast import channels as CH
            cap = await _effective_caption(uid)
            await CH.set_caption(cid, cap)
            await q.answer("saved as channel default")
            return await _render_channel_editor(q, cid)

        if action == "ch_btns":
            cid = int(parts[2])
            return await _render_channel_buttons(q, cid)

        # ── TIMER SET (generic preset) ──
        if action == "timer_set":
            secs = int(parts[2]) if len(parts) > 2 else 0
            _ss_update(uid, auto_delete_secs=secs)

            s = _ss_get(uid) or {}
            nxt = s.get("timer_context")
            if nxt == "ch_all":
                return await _render_timer_for(
                    q,
                    back_cb=_cb("channels"),
                    confirm_cb_template=_cb("ch_all_confirm"),
                    title="all channels",
                    target_count=await _count_channels(),
                )
            if nxt and nxt.startswith("ch:"):
                cid = int(nxt.split(":", 1)[1])
                return await _render_timer_for(
                    q,
                    back_cb=_cb(f"ch:{cid}"),
                    confirm_cb_template=_cb(f"ch_send:{cid}"),
                    title=await _channel_title(cid),
                    target_count=1,
                )
            if nxt == "gr_all":
                return await _render_timer_for(
                    q,
                    back_cb=_cb("groups"),
                    confirm_cb_template=_cb("gr_all_confirm"),
                    title="all groups",
                    target_count=await _count_groups(),
                )
            if nxt and nxt.startswith("gr:"):
                gid = int(nxt.split(":", 1)[1])
                return await _render_timer_for(
                    q,
                    back_cb=_cb("groups"),
                    confirm_cb_template=_cb(f"gr_confirm:{gid}"),
                    title=await _channel_title(gid),
                    target_count=1,
                )
            return await _render_main(client, uid)

        # ── STOP (broadcast stop) ──
        if action == "stop":
            from plugins.broadcast import engine as E
            ok = E.cancel()
            return await q.answer(
                "⏹️ stopping..." if ok else "⚠️ idle"
            )

        # ── fallback ──
        return await q.answer(f"unknown: {action}")

    except Exception as e:
        logger.exception(f"[BC-C] router: {e}")
        try:
            await q.answer(f"❌ {type(e).__name__}", show_alert=True)
        except Exception:
            pass


# ============================================================
# PER-CHANNEL BUTTONS EDITOR
# ============================================================

async def _render_channel_buttons(q: CallbackQuery, cid: int) -> None:
    from plugins.broadcast import channels as CH
    from plugins.broadcast import templates as T
    ch = await CH.get_channel(cid)
    if not ch:
        return await q.answer("not found", show_alert=True)

    custom = ch.get("buttons")
    using_default = custom is None
    btns = (await T.get_buttons()) if using_default else custom

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"🔘 <b>{F.fb('CHANNEL BUTTONS')}</b>",
        F.DIV, "",
        f"📢 {F.sc('channel')} · "
        f"<b>{F.sc(str(ch.get('title'))[:40])}</b>",
        "",
        f"📌 {F.sc('source')} · "
        + ("🌐 global" if using_default else "🔘 custom"),
        "",
        F.DIV_S,
    ]
    for i, b in enumerate(btns, 1):
        lines.append(f"{i}. <b>{F.sc(str(b.get('name'))[:40])}</b>")
        lines.append(f"   <code>{str(b.get('url'))[:60]}</code>")

    rows = []
    if using_default:
        rows.append([InlineKeyboardButton(
            f"✏️ {F.sc('create custom')}",
            callback_data=_cb(f"ch_btns_custom:{cid}"),
        )])
    else:
        for i, b in enumerate(btns, 1):
            rows.append([InlineKeyboardButton(
                f"🗑 {i}. {str(b.get('name'))[:30]}",
                callback_data=_cb(f"ch_btns_rm:{cid}:{i-1}"),
            )])
        rows.append([InlineKeyboardButton(
            f"➕ {F.sc('add button')}",
            callback_data=_cb(f"ch_btns_add:{cid}"),
        )])
        rows.append([InlineKeyboardButton(
            f"♻️ {F.sc('reset to global')}",
            callback_data=_cb(f"ch_btns_rst:{cid}"),
        )])

    rows.append([InlineKeyboardButton(
        f"⬅️ {F.sc('back')}",
        callback_data=_cb(f"ch:{cid}"),
    )])

    await _edit(q, "\n".join(lines), InlineKeyboardMarkup(rows))
    await q.answer()


# ============================================================
# RUN HELPERS
# ============================================================

async def _run_channel_single(
    client: Client, q: CallbackQuery, cid: int,
) -> None:
    uid = q.from_user.id
    s = _ss_get(uid)
    if not s:
        return await q.answer("session expired", show_alert=True)

    from plugins.broadcast import channels as CH
    ch = await CH.get_channel(cid)
    if not ch:
        return await q.answer("channel not found", show_alert=True)

    cap = await _effective_caption(uid)
    btns = await _effective_buttons(uid)
    timer = s.get("auto_delete_secs", 0)

    _ss_drop(uid)
    await q.answer("starting...")

    asyncio.create_task(_do_send(
        client=client,
        panel_chat_id=q.message.chat.id,
        panel_msg_id=q.message.id,
        source_chat_id=s["source_chat_id"],
        source_msg_id=s["source_msg_id"],
        targets=[cid],
        kind="channel",
        timer=timer,
        caption_template=cap,
        buttons_list=btns,
    ))


async def _run_groups_single(
    client: Client, q: CallbackQuery, gid: int,
) -> None:
    uid = q.from_user.id
    s = _ss_get(uid)
    if not s:
        return await q.answer("session expired", show_alert=True)

    cap = await _effective_caption(uid)
    btns = await _effective_buttons(uid)
    timer = s.get("auto_delete_secs", 0)

    _ss_drop(uid)
    await q.answer("starting...")

    asyncio.create_task(_do_send(
        client=client,
        panel_chat_id=q.message.chat.id,
        panel_msg_id=q.message.id,
        source_chat_id=s["source_chat_id"],
        source_msg_id=s["source_msg_id"],
        targets=[gid],
        kind="group",
        timer=timer,
        caption_template=cap,
        buttons_list=btns,
    ))


async def _run_groups_all(
    client: Client, q: CallbackQuery,
) -> None:
    uid = q.from_user.id
    s = _ss_get(uid)
    if not s:
        return await q.answer("session expired", show_alert=True)

    from database import db_registry
    targets: List[int] = []
    try:
        db = db_registry.get_user_db()
        if db is not None:
            cursor = db["groups"].find({}, {"chat_id": 1})
            docs = await cursor.to_list(length=10000)
            targets = [
                int(d["chat_id"]) for d in docs if d.get("chat_id")
            ]
    except Exception:
        pass

    if not targets:
        return await q.answer("no groups", show_alert=True)

    cap = await _effective_caption(uid)
    btns = await _effective_buttons(uid)
    timer = s.get("auto_delete_secs", 0)

    _ss_drop(uid)
    await q.answer(f"starting · {len(targets)}")

    asyncio.create_task(_do_send(
        client=client,
        panel_chat_id=q.message.chat.id,
        panel_msg_id=q.message.id,
        source_chat_id=s["source_chat_id"],
        source_msg_id=s["source_msg_id"],
        targets=targets,
        kind="groups",
        timer=timer,
        caption_template=cap,
        buttons_list=btns,
    ))


async def _run_users(
    client: Client, q: CallbackQuery,
) -> None:
    uid = q.from_user.id
    s = _ss_get(uid)
    if not s:
        return await q.answer("session expired", show_alert=True)

    flt = s.get("target_user_filter") or "all"
    timer = s.get("auto_delete_secs", 0)

    from database import db_registry
    targets: List[int] = []
    try:
        db = db_registry.get_user_db()
        if db is not None:
            if flt == "premium":
                pcursor = db["premium_users"].find(
                    {"status": "active"}, {"user_id": 1},
                )
                pdocs = await pcursor.to_list(length=100000)
                premium_ids = [
                    int(d["user_id"]) for d in pdocs
                    if d.get("user_id")
                ]
                if premium_ids:
                    cursor = db["users"].find(
                        {"user_id": {"$in": premium_ids},
                         "blocked_bot": {"$ne": True}},
                        {"user_id": 1},
                    )
                else:
                    cursor = None
            else:
                cursor = db["users"].find(
                    {"blocked_bot": {"$ne": True}},
                    {"user_id": 1},
                )

            if cursor is not None:
                docs = await cursor.to_list(length=100000)
                targets = [
                    int(d["user_id"]) for d in docs
                    if d.get("user_id")
                ]
    except Exception:
        pass

    if not targets:
        return await q.answer("no users", show_alert=True)

    cap = await _effective_caption(uid)
    btns = await _effective_buttons(uid)

    _ss_drop(uid)
    await q.answer(f"starting · {len(targets)}")

    asyncio.create_task(_do_send(
        client=client,
        panel_chat_id=q.message.chat.id,
        panel_msg_id=q.message.id,
        source_chat_id=s["source_chat_id"],
        source_msg_id=s["source_msg_id"],
        targets=targets,
        kind="users",
        timer=timer,
        caption_template=cap,
        buttons_list=btns,
    ))


async def _run_channels_all(
    client: Client, q: CallbackQuery,
) -> None:
    uid = q.from_user.id
    s = _ss_get(uid)
    if not s:
        return await q.answer("session expired", show_alert=True)

    from plugins.broadcast import channels as CH
    channels = await CH.list_channels()
    enabled = [c for c in channels if c.get("enabled", True)]
    if not enabled:
        return await q.answer("no channels", show_alert=True)

    timer = s.get("auto_delete_secs", 0)

    _ss_drop(uid)
    await q.answer(f"starting · {len(enabled)}")

    asyncio.create_task(_do_channels_all(
        client=client,
        panel_chat_id=q.message.chat.id,
        panel_msg_id=q.message.id,
        source_chat_id=s["source_chat_id"],
        source_msg_id=s["source_msg_id"],
        channels=enabled,
        timer=timer,
    ))


# ============================================================
# SEND ENGINE (standard)
# ============================================================

async def _do_send(
    client: Client,
    panel_chat_id: int,
    panel_msg_id: int,
    source_chat_id: int,
    source_msg_id: int,
    targets: List[int],
    kind: str,
    timer: int,
    caption_template: Optional[str] = None,
    buttons_list: Optional[List[Dict]] = None,
) -> None:
    from plugins.broadcast import engine as E

    total = len(targets)
    started = time.time()
    last = {"t": 0.0}

    async def _progress(st: Dict[str, Any]) -> None:
        now = time.time()
        if now - last["t"] < 2.0:
            return
        last["t"] = now
        try:
            done = (
                st.get("sent", 0)
                + st.get("failed", 0)
                + st.get("blocked", 0)
            )
            pct = (done / total * 100) if total else 0
            bar = P.bar(pct, "indexing", width=14)
            lines = [
                f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                f"🚀 <b>{F.fb('BROADCASTING')}</b>",
                F.DIV, "",
                f"🎯 {F.sc('target')} · <b>{kind}</b>",
            ]
            if timer > 0:
                lines.append(
                    f"⏱️ {F.sc('timer')} · "
                    f"<b>{_fmt_timer(timer)}</b>"
                )
            lines += [
                "",
                f"<code>{bar}</code>",
                "",
                f"✅ {F.sc('sent')} · "
                f"<b>{FM.num(st.get('sent', 0))}</b>",
                f"❌ {F.sc('failed')} · "
                f"<b>{FM.num(st.get('failed', 0))}</b>",
                f"🚫 {F.sc('blocked')} · "
                f"<b>{FM.num(st.get('blocked', 0))}</b>",
                "",
                f"📊 <code>{done}/{total}</code>",
                f"⚡ <code>{st.get('speed', 0):.1f}/s</code>",
                f"⏱️ ETA · <b>{st.get('eta_text', '—')}</b>",
            ]
            await client.edit_message_text(
                chat_id=panel_chat_id,
                message_id=panel_msg_id,
                text="\n".join(lines),
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        f"⏹️ {F.sc('stop')}",
                        callback_data="bca:stop",
                    ),
                ]]),
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except Exception:
            pass

    try:
        result = await E.run_broadcast(
            client=client,
            source_chat_id=source_chat_id,
            source_msg_id=source_msg_id,
            targets=targets,
            kind=kind,
            caption_template=caption_template,
            buttons_list=buttons_list,
            autodelete_seconds=timer,
            owner=0,
            progress_cb=_progress,
        )

        elapsed = time.time() - started
        await _render_done(
            client, panel_chat_id, panel_msg_id,
            kind, total, result, elapsed, timer,
        )
    except Exception as e:
        logger.exception(f"[BC-C] run: {e}")
        try:
            await client.edit_message_text(
                chat_id=panel_chat_id,
                message_id=panel_msg_id,
                text=(
                    f"❌ {F.sc('broadcast failed')}\n"
                    f"<code>{type(e).__name__}</code>"
                ),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass


# ============================================================
# SEND ENGINE (channels all — per-channel caption)
# ============================================================

async def _do_channels_all(
    client: Client,
    panel_chat_id: int,
    panel_msg_id: int,
    source_chat_id: int,
    source_msg_id: int,
    channels: List[Dict[str, Any]],
    timer: int = 0,
) -> None:
    from plugins.broadcast import templates as T
    from plugins.broadcast import state as BS

    total = len(channels)
    started = time.time()
    sent = 0
    failed = 0

    try:
        src_msg = await client.get_messages(source_chat_id, source_msg_id)
        if not src_msg or src_msg.empty:
            raise RuntimeError("source gone")
    except Exception as e:
        await client.edit_message_text(
            chat_id=panel_chat_id, message_id=panel_msg_id,
            text=f"❌ source fetch failed: <code>{e}</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    global_cap = await T.get_caption()
    global_btns = await T.get_buttons()

    for ch in channels:
        cid = ch.get("chat_id")
        custom_cap = ch.get("caption")
        custom_btns = ch.get("buttons")
        cap_tpl = custom_cap if custom_cap is not None else global_cap
        btns = custom_btns if custom_btns is not None else global_btns

        caption = T.build_caption(src_msg, cap_tpl)
        kb = T.build_buttons_kb(btns)

        try:
            sent_msg = await client.copy_message(
                chat_id=int(cid),
                from_chat_id=source_chat_id,
                message_id=source_msg_id,
                caption=caption,
                reply_markup=kb,
            )
            sent += 1
            if timer > 0 and sent_msg:
                try:
                    await BS.schedule_autodelete(
                        int(cid), sent_msg.id, timer, "",
                    )
                except Exception:
                    pass
        except FloodWait as e:
            await asyncio.sleep(int(e.value) + 2)
            try:
                sent_msg = await client.copy_message(
                    chat_id=int(cid),
                    from_chat_id=source_chat_id,
                    message_id=source_msg_id,
                    caption=caption,
                    reply_markup=kb,
                )
                sent += 1
                if timer > 0 and sent_msg:
                    try:
                        await BS.schedule_autodelete(
                            int(cid), sent_msg.id, timer, "",
                        )
                    except Exception:
                        pass
            except Exception:
                failed += 1
        except Exception:
            failed += 1

        try:
            done = sent + failed
            pct = (done / total * 100) if total else 0
            bar = P.bar(pct, "indexing", width=14)
            lines = [
                f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                f"🚀 <b>{F.fb('SENDING TO ALL CHANNELS')}</b>",
                F.DIV, "",
            ]
            if timer > 0:
                lines.append(
                    f"⏱️ {F.sc('timer')} · "
                    f"<b>{_fmt_timer(timer)}</b>"
                )
                lines.append("")
            lines += [
                f"<code>{bar}</code>",
                "",
                f"✅ {F.sc('sent')} · <b>{sent}</b>",
                f"❌ {F.sc('failed')} · <b>{failed}</b>",
                "",
                f"📊 <code>{done}/{total}</code>",
                f"📢 {F.sc('now')} · "
                f"<code>{str(ch.get('title', '?'))[:30]}</code>",
            ]
            await client.edit_message_text(
                chat_id=panel_chat_id,
                message_id=panel_msg_id,
                text="\n".join(lines),
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        f"⏹️ {F.sc('stop')}",
                        callback_data="bca:stop",
                    ),
                ]]),
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except Exception:
            pass

        await asyncio.sleep(0.4)

    elapsed = time.time() - started
    await _render_done(
        client, panel_chat_id, panel_msg_id,
        "channels (all)", total,
        {"sent": sent, "failed": failed, "blocked": 0},
        elapsed, timer,
    )


# ============================================================
# FINAL REPORT
# ============================================================

async def _render_done(
    client: Client,
    panel_chat_id: int,
    panel_msg_id: int,
    kind: str,
    total: int,
    result: Dict[str, Any],
    elapsed: float,
    timer: int,
) -> None:
    sent = result.get("sent", 0)
    failed = result.get("failed", 0)
    blocked = result.get("blocked", 0)

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"✅ <b>{F.fb('BROADCAST COMPLETE')}</b>",
        F.DIV, "",
        f"🎯 {F.sc('target')} · <b>{kind}</b>",
        f"📊 {F.sc('total')} · <b>{FM.num(total)}</b>",
        "",
        f"✅ {F.sc('sent')} · <b>{FM.num(sent)}</b>",
        f"❌ {F.sc('failed')} · <b>{FM.num(failed)}</b>",
        f"🚫 {F.sc('blocked')} · <b>{FM.num(blocked)}</b>",
    ]
    if timer > 0:
        lines.append("")
        lines.append(
            f"⏱️ {F.sc('auto-delete')} · <b>{_fmt_timer(timer)}</b>"
        )

    lines += [
        "",
        f"⏱️ {F.sc('time')} · <b>{FM.duration_short(elapsed)}</b>",
    ]

    try:
        await client.edit_message_text(
            chat_id=panel_chat_id,
            message_id=panel_msg_id,
            text="\n".join(lines),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"❌ {F.sc('close')}",
                    callback_data="bca:cancel",
                ),
            ]]),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception:
        pass


# ============================================================
# TEXT INPUT (caption entry)
# ============================================================

@Client.on_message(
    filters.private & filters.text & ~filters.regex(r"^/"),
    group=-8303,
)
async def broadcast_center_text_input(client: Client, message: Message):
    if not message.from_user:
        return
    uid = message.from_user.id
    if not _is_admin(uid):
        return

    s = _ss_get(uid)
    if not s:
        return

    awaiting = s.get("awaiting")
    if awaiting != "caption":
        return

    text = (message.text or "").strip()

    try:
        message.stop_propagation()
    except Exception:
        pass

    if text == "-":
        _ss_update(uid, caption_mode="none",
                   custom_caption=None, awaiting=None)
        new_cap = "🚫 none"
    else:
        _ss_update(uid, caption_mode="custom",
                   custom_caption=text, awaiting=None)
        new_cap = "✏️ custom"

    await message.reply_text(
        f"{F.EMO['check']} <b>Caption set to</b> {new_cap}",
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# PUBLIC
# ============================================================

def snapshot() -> Dict[str, Any]:
    return {
        "watcher_enabled": _FILTER is not None,
        "active_sessions": len(_sessions),
    }


__all__ = ["snapshot"]
