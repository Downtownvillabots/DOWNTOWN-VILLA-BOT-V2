# ============================================================
# 🏨 DOWNTOWN VILLA — BROADCAST CENTER (FINAL — FULL)
# ============================================================
#
# Two entry points:
#   1. Upload file to BROADCAST_CHANNEL_ID
#   2. /broadcast in PM → pick recent file from channel
#
# Full customization:
#   • Per-channel caption (edit/keep/global/none)
#   • Per-channel buttons (custom/global/add/remove)
#   • Timer for channels/groups/users (never/1d/3d/7d/30d)
#   • Send to all channels (each with own caption)
#   • Send to all groups / selected
#   • Send to all users / premium only
#   • Preview, live progress, final report
#   • Session TTL = 24 hours
#   • Session keyed by chat_id (channel + PM both work)
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
# SESSION STATE — keyed by chat_id, 24h TTL
# ============================================================

_sessions: Dict[int, Dict[str, Any]] = {}
SESSION_TTL = 86400.0


def _s_set(key: int, **data) -> None:
    _sessions[int(key)] = {
        "expires": time.time() + SESSION_TTL,
        "created": time.time(),
        **data,
    }


def _s_get(key: int) -> Optional[Dict[str, Any]]:
    s = _sessions.get(int(key))
    if not s:
        return None
    if time.time() > s.get("expires", 0):
        _sessions.pop(int(key), None)
        return None
    return s


def _s_upd(key: int, **data) -> None:
    s = _sessions.get(int(key))
    if s:
        s.update(data)
        s["expires"] = time.time() + SESSION_TTL


def _s_drop(key: int) -> None:
    _sessions.pop(int(key), None)


# ============================================================
# TIMER PRESETS
# ============================================================

TIMERS = [
    (0,       "♾ never"),
    (86400,   "⏱ 1 day"),
    (259200,  "⏱ 3 days"),
    (604800,  "⏱ 7 days"),
    (2592000, "⏱ 30 days"),
]


def _fmt_timer(secs: int) -> str:
    if not secs:
        return "♾ never"
    return f"⏱ {FM.duration_short(secs)}"


def _is_admin(uid) -> bool:
    try:
        return int(uid) in [int(a) for a in config.ADMINS]
    except Exception:
        return False


def _cb(*parts) -> str:
    return "bca:" + ":".join(str(p) for p in parts)


async def _edit(q: CallbackQuery, text: str, kb=None) -> None:
    try:
        await q.message.edit_text(
            text, reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        if "not modified" not in str(e).lower():
            logger.debug(f"[BC] edit: {e}")


def _extract_name(message: Message) -> str:
    try:
        for attr in ("document", "video", "audio", "photo", "animation"):
            m = getattr(message, attr, None)
            if m:
                return (
                    getattr(m, "file_name", None)
                    or (message.caption or "")[:60]
                    or f"{attr} file"
                )
    except Exception:
        pass
    return "file"


# ============================================================
# COUNTS
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


async def _count_users() -> int:
    from database import db_registry
    try:
        db = db_registry.get_user_db()
        if db is not None:
            return await db["users"].count_documents(
                {"blocked_bot": {"$ne": True}}
            )
    except Exception:
        pass
    return 0


# ============================================================
# WATCHER — fires on upload to BROADCAST_CHANNEL_ID
# ============================================================

def _channel_filter():
    ch = getattr(config, "BROADCAST_CHANNEL_ID", None)
    if not ch:
        return None
    return filters.chat(ch) & ~filters.service


_FILTER = _channel_filter()


if _FILTER is not None:

    @Client.on_message(_FILTER, group=-8306)
    async def bc_channel_watcher(client: Client, message: Message):
        try:
            key = int(message.chat.id)

            _s_set(
                key,
                source_chat_id=key,
                source_msg_id=int(message.id),
                source_name=_extract_name(message),
                original_caption=message.caption or "",
                caption_mode="auto",
                custom_caption=None,
                timer_secs=0,
                user_filter="all",
                timer_context=None,
                awaiting=None,
            )

            await _show_main(message, key)

        except Exception as e:
            logger.exception(f"[BC] watcher: {e}")


# ============================================================
# /broadcast COMMAND (PM)
# ============================================================

@Client.on_message(
    filters.command(["broadcast", "bc"]) & filters.private,
    group=-8307,
)
async def bc_cmd(client: Client, message: Message):
    if not message.from_user or not _is_admin(message.from_user.id):
        return

    key = int(message.chat.id)

    ch = getattr(config, "BROADCAST_CHANNEL_ID", None)
    if not ch:
        return await message.reply_text(
            f"{F.EMO['warn']} <b>BROADCAST_CHANNEL_ID not set</b>",
            parse_mode=ParseMode.HTML,
        )

    try:
        msgs = []
        async for m in client.get_chat_history(ch, limit=40):
            if m.media and not m.service:
                msgs.append(m)
            if len(msgs) >= 10:
                break
    except Exception as e:
        logger.exception(f"[BC-PM] fetch: {e}")
        return await message.reply_text(
            f"{F.EMO['cross']} {F.sc('cannot read channel')}\n"
            f"<code>{type(e).__name__}</code>",
            parse_mode=ParseMode.HTML,
        )

    if not msgs:
        return await message.reply_text(
            "\n".join([
                f"{F.EMO['warn']} <b>{F.fb('NO FILES')}</b>",
                F.DIV, "",
                f"📌 {F.sc('upload a file to the broadcast channel')}",
                f"📌 {F.sc('then run /broadcast again')}",
            ]),
            parse_mode=ParseMode.HTML,
        )

    src_list = [(int(m.id), _extract_name(m)) for m in msgs]

    _s_set(
        key,
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
            callback_data=_cb(f"src:{i}"),
        )])
    rows.append([InlineKeyboardButton(
        f"❌ {F.sc('cancel')}",
        callback_data=_cb("cancel"),
    )])

    try:
        message.stop_propagation()
    except Exception:
        pass

    await message.reply_text(
        text,
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


# ============================================================
# MAIN PANEL
# ============================================================

async def _show_main(reply_to: Message, key: int) -> None:
    s = _s_get(key)
    if not s:
        return

    s["_ch_count"] = await _count_channels()
    s["_group_count"] = await _count_groups()
    s["_user_count"] = await _count_users()

    text, kb = _main_text_kb(s)

    try:
        await reply_to.reply_text(
            text, reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            quote=True,
        )
    except Exception as e:
        logger.debug(f"[BC] main reply: {e}")


def _main_text_kb(s: Dict[str, Any]) -> tuple:
    name = (s.get("source_name") or "file")[:40]
    cap_mode = s.get("caption_mode", "auto")
    cap_icon = {
        "auto": "🌐 global",
        "keep": "📄 original",
        "custom": "✏ custom",
        "none": "🚫 none",
    }.get(cap_mode, "?")
    timer = s.get("timer_secs", 0)

    ch_count = s.get("_ch_count", 0)
    group_count = s.get("_group_count", 0)
    user_count = s.get("_user_count", 0)

    text = "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"📢 <b>{F.fb('BROADCAST CENTER')}</b>",
        F.DIV, "",
        f"📦 <code>{name}</code>",
        f"📝 {F.sc('caption')} · <b>{cap_icon}</b>",
        f"⏱ {F.sc('timer')} · <b>{_fmt_timer(timer)}</b>",
        "",
        F.DIV_S,
        f"📢 {F.sc('channels')} · <b>{ch_count}</b>",
        f"👥 {F.sc('groups')} · <b>{group_count}</b>",
        f"👤 {F.sc('users')} · <b>{user_count}</b>",
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
                callback_data=_cb("cap"),
            ),
        ],
        [
            InlineKeyboardButton(
                f"⏱ {F.sc('timer')} · {_fmt_timer(timer)}",
                callback_data=_cb("main_timer"),
            ),
            InlineKeyboardButton(
                f"👁 {F.sc('preview')}",
                callback_data=_cb("preview"),
            ),
        ],
        [
            InlineKeyboardButton(
                f"❌ {F.sc('cancel')}",
                callback_data=_cb("cancel"),
            ),
        ],
    ])

    return text, kb



# ============================================================
# CHANNEL PICKER
# ============================================================

async def _show_channels(q: CallbackQuery, key: int) -> None:
    from plugins.broadcast import channels as CH
    channels = await CH.list_channels()
    enabled = [c for c in channels if c.get("enabled", True)]

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"📢 <b>{F.fb('SELECT CHANNELS')}</b>",
        F.DIV, "",
        f"📊 {F.sc('total')} · <b>{len(enabled)}</b>",
    ]

    rows: List[List[InlineKeyboardButton]] = []

    if not enabled:
        lines.append("")
        lines.append(f"⚪ {F.sc('no channels registered')}")
        lines.append(f"📌 {F.sc('add via /broadcast → channels')}")
    else:
        rows.append([InlineKeyboardButton(
            f"🎯 {F.sc('SEND TO ALL')} ({len(enabled)})",
            callback_data=_cb("ch_all_timer"),
        )])
        for c in enabled:
            cid = c.get("chat_id")
            t = str(c.get("title") or cid)[:26]
            marks = ""
            if c.get("caption") is not None:
                marks += "📝"
            if c.get("buttons") is not None:
                marks += "🔘"
            if c.get("primary"):
                marks = "⭐" + marks
            prefix = f"{marks} " if marks else "⚪ "
            rows.append([InlineKeyboardButton(
                f"{prefix}{t}",
                callback_data=_cb(f"ch:{cid}"),
            )])

    rows.append([InlineKeyboardButton(
        f"⬅ {F.sc('back')}",
        callback_data=_cb("home"),
    )])

    await _edit(q, "\n".join(lines), InlineKeyboardMarkup(rows))
    await q.answer()


# ============================================================
# CHANNEL EDITOR
# ============================================================

async def _show_channel_editor(
    q: CallbackQuery, key: int, cid: int,
) -> None:
    from plugins.broadcast import channels as CH
    ch = await CH.get_channel(cid)
    if not ch:
        return await q.answer("channel not found", show_alert=True)

    s = _s_get(key) or {}
    timer = s.get("timer_secs", 0)
    ch_cap = ch.get("caption")
    title = str(ch.get("title") or cid)[:50]

    if ch_cap is not None:
        cap_src = "📝 channel custom"
        preview = ch_cap[:150]
    else:
        from plugins.broadcast import templates as T
        preview = (await T.get_caption())[:150]
        cap_src = "🌐 global default"

    ch_btns = ch.get("buttons")
    btn_src = (
        f"🔘 custom ({len(ch_btns)})"
        if ch_btns is not None
        else "🌐 global"
    )

    text = "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"📢 <b>{F.fb('CHANNEL EDITOR')}</b>",
        F.DIV, "",
        f"📛 <b>{F.sc(title)}</b>",
        f"🆔 <code>{cid}</code>",
        "",
        F.DIV_S,
        f"📝 {F.sc('caption')} · <b>{cap_src}</b>",
        f"<code>{F.sc(preview) if preview else '(empty)'}</code>",
        "",
        f"🔘 {F.sc('buttons')} · <b>{btn_src}</b>",
        f"⏱ {F.sc('timer')} · <b>{_fmt_timer(timer)}</b>",
    ])

    rows = [
        [
            InlineKeyboardButton(
                f"✏ {F.sc('edit caption')}",
                callback_data=_cb(f"cap_edit_ch:{cid}"),
            ),
            InlineKeyboardButton(
                f"📄 {F.sc('use original')}",
                callback_data=_cb(f"cap_keep_ch:{cid}"),
            ),
        ],
        [
            InlineKeyboardButton(
                f"🌐 {F.sc('use global')}",
                callback_data=_cb(f"cap_global_ch:{cid}"),
            ),
            InlineKeyboardButton(
                f"🗑 {F.sc('remove caption')}",
                callback_data=_cb(f"cap_none_ch:{cid}"),
            ),
        ],
        [
            InlineKeyboardButton(
                f"🎛 {F.sc('manage buttons')}",
                callback_data=_cb(f"ch_btns:{cid}"),
            ),
        ],
        [
            InlineKeyboardButton(
                f"⏱ {F.sc('timer')} · {_fmt_timer(timer)}",
                callback_data=_cb(f"ch_timer:{cid}"),
            ),
        ],
        [
            InlineKeyboardButton(
                f"🚀 {F.sc('send now')}",
                callback_data=_cb(f"ch_send:{cid}"),
            ),
        ],
        [
            InlineKeyboardButton(
                f"⬅ {F.sc('back')}",
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
# PER-CHANNEL BUTTONS EDITOR
# ============================================================

async def _show_channel_buttons(q: CallbackQuery, cid: int) -> None:
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
            f"✏ {F.sc('create custom')}",
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
            f"♻ {F.sc('reset to global')}",
            callback_data=_cb(f"ch_btns_rst:{cid}"),
        )])

    rows.append([InlineKeyboardButton(
        f"⬅ {F.sc('back')}",
        callback_data=_cb(f"ch:{cid}"),
    )])

    await _edit(q, "\n".join(lines), InlineKeyboardMarkup(rows))
    await q.answer()


# ============================================================
# TIMER PICKER
# ============================================================

async def _show_timer(
    q: CallbackQuery, key: int, context: str,
) -> None:
    s = _s_get(key) or {}
    timer = s.get("timer_secs", 0)

    text = "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"⏱ <b>{F.fb('AUTO-DELETE TIMER')}</b>",
        F.DIV, "",
        f"🎯 {F.sc('context')} · <b>{F.sc(context)}</b>",
        "",
        f"📌 {F.sc('never = stays forever')}",
        f"📌 {F.sc('others = auto-delete after')}",
        "",
        f"⏱ {F.sc('current')} · <b>{_fmt_timer(timer)}</b>",
    ])

    rows: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []
    for secs, label in TIMERS:
        mark = "✅ " if secs == timer else ""
        row.append(InlineKeyboardButton(
            f"{mark}{label}",
            callback_data=_cb(f"timer_set:{secs}:{context}"),
        ))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    rows.append([InlineKeyboardButton(
        f"⬅ {F.sc('back')}",
        callback_data=_cb("home"),
    )])

    await _edit(q, text, InlineKeyboardMarkup(rows))
    await q.answer()


# ============================================================
# GROUP PICKER
# ============================================================

async def _show_groups(q: CallbackQuery, key: int) -> None:
    from database import db_registry
    groups: List[Dict[str, Any]] = []
    try:
        db = db_registry.get_user_db()
        if db is not None:
            cursor = db["groups"].find(
                {}, {"chat_id": 1, "title": 1}
            ).limit(50)
            groups = await cursor.to_list(length=50)
    except Exception:
        pass

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"👥 <b>{F.fb('SELECT GROUPS')}</b>",
        F.DIV, "",
        f"📊 {F.sc('total')} · <b>{len(groups)}</b>",
    ]

    rows: List[List[InlineKeyboardButton]] = []

    if groups:
        rows.append([InlineKeyboardButton(
            f"🎯 {F.sc('SEND TO ALL')} ({len(groups)})",
            callback_data=_cb("gr_all_timer"),
        )])
        for g in groups[:10]:
            gid = g.get("chat_id")
            t = str(g.get("title") or gid)[:30]
            rows.append([InlineKeyboardButton(
                f"👥 {t}",
                callback_data=_cb(f"gr:{gid}"),
            )])

    rows.append([InlineKeyboardButton(
        f"⬅ {F.sc('back')}",
        callback_data=_cb("home"),
    )])

    await _edit(q, "\n".join(lines), InlineKeyboardMarkup(rows))
    await q.answer()


# ============================================================
# USER PICKER
# ============================================================

async def _show_users(q: CallbackQuery, key: int) -> None:
    from database import db_registry
    counts = {"all": 0, "premium": 0}
    try:
        db = db_registry.get_user_db()
        if db is not None:
            counts["all"] = await db["users"].count_documents(
                {"blocked_bot": {"$ne": True}}
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
        f"👥 {F.sc('all users')} · <b>{FM.num(counts['all'])}</b>",
        f"💎 {F.sc('premium')} · <b>{FM.num(counts['premium'])}</b>",
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
        [InlineKeyboardButton(
            f"⬅ {F.sc('back')}",
            callback_data=_cb("home"),
        )],
    ]

    await _edit(q, text, InlineKeyboardMarkup(rows))
    await q.answer()


# ============================================================
# CAPTION MENU
# ============================================================

async def _show_caption(q: CallbackQuery, key: int) -> None:
    s = _s_get(key) or {}
    mode = s.get("caption_mode", "auto")

    from plugins.broadcast import templates as T
    if mode == "custom" and s.get("custom_caption") is not None:
        cap = s["custom_caption"]
    elif mode == "keep":
        cap = s.get("original_caption") or ""
    elif mode == "none":
        cap = ""
    else:
        cap = await T.get_caption()

    preview = cap[:200] + ("…" if len(cap) > 200 else "")

    text = "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"📝 <b>{F.fb('CAPTION MANAGER')}</b>",
        F.DIV, "",
        f"📌 {F.sc('mode')} · <b>{F.sc(mode)}</b>",
        "",
        f"<code>{F.sc(preview) if preview else '(empty)'}</code>",
    ])

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
                f"✏ {F.sc('edit')}",
                callback_data=_cb("cap_edit"),
            ),
            InlineKeyboardButton(
                f"🗑 {F.sc('remove')}",
                callback_data=_cb("cap_mode:none"),
            ),
        ],
        [InlineKeyboardButton(
            f"⬅ {F.sc('back')}",
            callback_data=_cb("home"),
        )],
    ]

    await _edit(q, text, InlineKeyboardMarkup(rows))
    await q.answer()


# ============================================================
# CAPTION / BUTTONS HELPERS
# ============================================================

async def _effective_caption(key: int) -> str:
    s = _s_get(key) or {}
    mode = s.get("caption_mode", "auto")

    if mode == "custom" and s.get("custom_caption") is not None:
        return s["custom_caption"]
    if mode == "keep":
        return s.get("original_caption") or ""
    if mode == "none":
        return ""

    from plugins.broadcast import templates as T
    return await T.get_caption()


async def _effective_buttons(key: int) -> List[Dict[str, Any]]:
    from plugins.broadcast import templates as T
    return await T.get_buttons()


# ============================================================
# ROUTER
# ============================================================

@Client.on_callback_query(
    filters.regex(r"^bca:"), group=-8304,
)
async def bc_router(client: Client, q: CallbackQuery):
    if not q.from_user or not _is_admin(q.from_user.id):
        return await q.answer("❌ admin only", show_alert=True)

    key = int(q.message.chat.id)
    s = _s_get(key)

    parts = str(q.data or "").split(":")
    action = parts[1] if len(parts) > 1 else ""

    # ── CANCEL works without session ──
    if action == "cancel":
        _s_drop(key)
        try:
            await q.message.delete()
        except Exception:
            pass
        return await q.answer("cancelled")

    if not s:
        return await q.answer(
            "⏱ session expired — re-upload the file",
            show_alert=True,
        )

    try:
        # ── HOME ──
        if action == "home":
            s["_ch_count"] = await _count_channels()
            s["_group_count"] = await _count_groups()
            s["_user_count"] = await _count_users()
            text, kb = _main_text_kb(s)
            await _edit(q, text, kb)
            return await q.answer()

        # ── SOURCE PICK ──
        if action == "src":
            idx = int(parts[2]) if len(parts) > 2 else 0
            srcs = s.get("source_list") or []
            if idx < 0 or idx >= len(srcs):
                return await q.answer("❌ invalid", show_alert=True)
            mid, name = srcs[idx]
            ch_id = s.get("broadcast_channel_id")

            _s_upd(
                key,
                source_chat_id=int(ch_id),
                source_msg_id=int(mid),
                source_name=name,
                original_caption="",
                caption_mode="auto",
                custom_caption=None,
                timer_secs=0,
                user_filter="all",
            )

            s2 = _s_get(key) or {}
            s2["_ch_count"] = await _count_channels()
            s2["_group_count"] = await _count_groups()
            s2["_user_count"] = await _count_users()
            text, kb = _main_text_kb(s2)
            await _edit(q, text, kb)
            return await q.answer("✅ source loaded")

        # ── CHANNELS ──
        if action == "channels":
            return await _show_channels(q, key)

        if action == "ch_all_timer":
            _s_upd(key, timer_context="ch_all")
            return await _show_timer(q, key, "all channels")

        if action == "ch":
            cid = int(parts[2]) if len(parts) > 2 else 0
            _s_upd(key, target_channel_id=cid)
            return await _show_channel_editor(q, key, cid)

        if action == "ch_timer":
            cid = int(parts[2]) if len(parts) > 2 else 0
            _s_upd(key, timer_context=f"ch:{cid}", target_channel_id=cid)
            return await _show_timer(q, key, f"channel {cid}")

        if action == "ch_send":
            cid = int(parts[2]) if len(parts) > 2 else 0
            return await _run_single_channel(client, q, key, cid)

        if action == "ch_all_go":
            return await _run_channels_all(client, q, key)

        if action == "ch_btns":
            cid = int(parts[2]) if len(parts) > 2 else 0
            return await _show_channel_buttons(q, cid)

        if action == "ch_btns_custom":
            cid = int(parts[2]) if len(parts) > 2 else 0
            from plugins.broadcast import channels as CH
            await CH.set_buttons(cid, [])
            await q.answer("✏ empty custom list")
            return await _show_channel_buttons(q, cid)

        if action == "ch_btns_rst":
            cid = int(parts[2]) if len(parts) > 2 else 0
            from plugins.broadcast import channels as CH
            await CH.set_buttons(cid, None)
            await q.answer("♻ reset to global")
            return await _show_channel_buttons(q, cid)

        if action == "ch_btns_rm":
            cid = int(parts[2]) if len(parts) > 2 else 0
            idx = int(parts[3]) if len(parts) > 3 else 0
            from plugins.broadcast import channels as CH
            ch = await CH.get_channel(cid)
            if ch and ch.get("buttons") is not None:
                btns = list(ch["buttons"])
                if 0 <= idx < len(btns):
                    btns.pop(idx)
                    await CH.set_buttons(cid, btns)
                    await q.answer("🗑 removed")
            return await _show_channel_buttons(q, cid)

        if action == "ch_btns_add":
            cid = int(parts[2]) if len(parts) > 2 else 0
            _s_upd(key, awaiting="btn_add_ch", cap_target_ch=cid)
            text = "\n".join([
                f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                f"➕ <b>{F.fb('ADD BUTTON')}</b>",
                F.DIV, "",
                f"📌 {F.sc('send')} <code>Name | URL</code>",
            ])
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"❌ {F.sc('cancel')}",
                    callback_data=_cb(f"ch_btns:{cid}"),
                ),
            ]])
            await _edit(q, text, kb)
            return await q.answer()

        # ── GROUPS ──
        if action == "groups":
            return await _show_groups(q, key)

        if action == "gr_all_timer":
            _s_upd(key, timer_context="gr_all")
            return await _show_timer(q, key, "all groups")

        if action == "gr":
            gid = int(parts[2]) if len(parts) > 2 else 0
            _s_upd(key, target_group_id=gid, timer_context=f"gr:{gid}")
            return await _show_timer(q, key, f"group {gid}")

        if action == "gr_all_go":
            return await _run_groups_all(client, q, key)

        if action == "gr_send":
            gid = int(parts[2]) if len(parts) > 2 else 0
            return await _run_single_group(client, q, key, gid)

        # ── USERS ──
        if action == "users":
            return await _show_users(q, key)

        if action == "us_filter":
            flt = parts[2] if len(parts) > 2 else "all"
            _s_upd(key, user_filter=flt, timer_context="us")
            return await _show_timer(q, key, f"users · {flt}")

        if action == "us_go":
            return await _run_users(client, q, key)

        # ── MAIN TIMER ──
        if action == "main_timer":
            _s_upd(key, timer_context="main")
            return await _show_timer(q, key, "general")

        # ── TIMER SET ──
        if action == "timer_set":
            secs = int(parts[2]) if len(parts) > 2 else 0
            ctx = ":".join(parts[3:]) if len(parts) > 3 else ""
            _s_upd(key, timer_secs=secs)

            if ctx == "ch_all":
                return await _show_timer(q, key, "all channels")
            if ctx.startswith("ch:"):
                cid = int(ctx.split(":", 1)[1])
                return await _show_channel_editor(q, key, cid)
            if ctx == "gr_all":
                return await _show_timer(q, key, "all groups")
            if ctx.startswith("gr:"):
                gid = int(ctx.split(":", 1)[1])
                return await _show_timer(q, key, f"group {gid}")
            if ctx == "us":
                s2 = _s_get(key) or {}
                return await _show_timer(
                    q, key,
                    f"users · {s2.get('user_filter', 'all')}",
                )
            if ctx == "main":
                s2 = _s_get(key) or {}
                s2["_ch_count"] = await _count_channels()
                s2["_group_count"] = await _count_groups()
                s2["_user_count"] = await _count_users()
                text, kb = _main_text_kb(s2)
                await _edit(q, text, kb)
                return await q.answer()

            return await _show_timer(q, key, ctx or "general")

        # ── CAPTION ──
        if action == "cap":
            return await _show_caption(q, key)

        if action == "cap_mode":
            mode = parts[2] if len(parts) > 2 else "auto"
            _s_upd(key, caption_mode=mode, custom_caption=None)
            return await _show_caption(q, key)

        if action == "cap_edit":
            _s_upd(key, awaiting="caption")
            text = "\n".join([
                f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                f"✏ <b>{F.fb('SEND NEW CAPTION')}</b>",
                F.DIV, "",
                f"📌 {F.sc('send the caption as next message')}",
                f"📌 {F.sc('send')} <code>-</code> {F.sc('to remove')}",
            ])
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"❌ {F.sc('cancel')}",
                    callback_data=_cb("cap"),
                ),
            ]])
            await _edit(q, text, kb)
            return await q.answer()

        if action == "cap_edit_ch":
            cid = int(parts[2])
            _s_upd(key, awaiting="caption_ch", cap_target_ch=cid)
            text = "\n".join([
                f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                f"✏ <b>{F.fb('CHANNEL CAPTION')}</b>",
                F.DIV, "",
                f"📌 {F.sc('send new caption for this channel')}",
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

        if action == "cap_keep_ch":
            cid = int(parts[2])
            _s_upd(key, caption_mode="keep", custom_caption=None)
            return await _show_channel_editor(q, key, cid)

        if action == "cap_global_ch":
            cid = int(parts[2])
            _s_upd(key, caption_mode="auto", custom_caption=None)
            return await _show_channel_editor(q, key, cid)

        if action == "cap_none_ch":
            cid = int(parts[2])
            _s_upd(key, caption_mode="none", custom_caption=None)
            return await _show_channel_editor(q, key, cid)

        # ── PREVIEW ──
        if action == "preview":
            return await _show_preview(q, key)

        # ── STOP ──
        if action == "stop":
            from plugins.broadcast import engine as E
            ok = E.cancel()
            return await q.answer(
                "⏹ stopping..." if ok else "⚠ idle"
            )

        return await q.answer(f"unknown: {action}")

    except Exception as e:
        logger.exception(f"[BC] router: {e}")
        try:
            await q.answer(f"❌ {type(e).__name__}", show_alert=True)
        except Exception:
            pass


# ============================================================
# PREVIEW
# ============================================================

async def _show_preview(q: CallbackQuery, key: int) -> None:
    s = _s_get(key) or {}
    cap = await _effective_caption(key)
    btns = await _effective_buttons(key)

    name = s.get("source_name") or "file"
    timer = s.get("timer_secs", 0)

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
        f"⏱ {F.sc('timer')} · <b>{_fmt_timer(timer)}</b>",
    ]

    rows = [
        [
            InlineKeyboardButton(
                f"📝 {F.sc('caption')}",
                callback_data=_cb("cap"),
            ),
            InlineKeyboardButton(
                f"⏱ {F.sc('timer')}",
                callback_data=_cb("main_timer"),
            ),
        ],
        [InlineKeyboardButton(
            f"⬅ {F.sc('back')}",
            callback_data=_cb("home"),
        )],
    ]

    await _edit(q, "\n".join(lines), InlineKeyboardMarkup(rows))
    await q.answer()


# ============================================================
# RUNNERS
# ============================================================

async def _run_single_channel(
    client: Client, q: CallbackQuery, key: int, cid: int,
) -> None:
    s = _s_get(key)
    if not s:
        return await q.answer("session expired", show_alert=True)

    from plugins.broadcast import channels as CH
    ch = await CH.get_channel(cid)
    if not ch:
        return await q.answer("channel not found", show_alert=True)

    ch_cap = ch.get("caption")
    ch_btns = ch.get("buttons")

    mode = s.get("caption_mode", "auto")
    if mode == "custom" and s.get("custom_caption") is not None:
        cap = s["custom_caption"]
    elif mode == "keep":
        cap = s.get("original_caption") or ""
    elif mode == "none":
        cap = ""
    elif ch_cap is not None:
        cap = ch_cap
    else:
        from plugins.broadcast import templates as T
        cap = await T.get_caption()

    if ch_btns is not None:
        btns = ch_btns
    else:
        btns = await _effective_buttons(key)

    timer = s.get("timer_secs", 0)

    _s_drop(key)
    await q.answer("🚀 starting...")

    asyncio.create_task(_do_send(
        client, q.message.chat.id, q.message.id,
        s["source_chat_id"], s["source_msg_id"],
        [cid], "channel", timer, cap, btns,
    ))


async def _run_single_group(
    client: Client, q: CallbackQuery, key: int, gid: int,
) -> None:
    s = _s_get(key)
    if not s:
        return await q.answer("session expired", show_alert=True)

    cap = await _effective_caption(key)
    btns = await _effective_buttons(key)
    timer = s.get("timer_secs", 0)

    _s_drop(key)
    await q.answer("🚀 starting...")

    asyncio.create_task(_do_send(
        client, q.message.chat.id, q.message.id,
        s["source_chat_id"], s["source_msg_id"],
        [gid], "group", timer, cap, btns,
    ))


async def _run_groups_all(
    client: Client, q: CallbackQuery, key: int,
) -> None:
    s = _s_get(key)
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

    cap = await _effective_caption(key)
    btns = await _effective_buttons(key)
    timer = s.get("timer_secs", 0)

    _s_drop(key)
    await q.answer(f"🚀 starting · {len(targets)} groups")

    asyncio.create_task(_do_send(
        client, q.message.chat.id, q.message.id,
        s["source_chat_id"], s["source_msg_id"],
        targets, "groups", timer, cap, btns,
    ))


async def _run_users(
    client: Client, q: CallbackQuery, key: int,
) -> None:
    s = _s_get(key)
    if not s:
        return await q.answer("session expired", show_alert=True)

    flt = s.get("user_filter") or "all"
    timer = s.get("timer_secs", 0)

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
                prem_ids = [
                    int(d["user_id"]) for d in pdocs if d.get("user_id")
                ]
                if prem_ids:
                    cursor = db["users"].find(
                        {"user_id": {"$in": prem_ids},
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
                    int(d["user_id"]) for d in docs if d.get("user_id")
                ]
    except Exception:
        pass

    if not targets:
        return await q.answer("no users", show_alert=True)

    cap = await _effective_caption(key)
    btns = await _effective_buttons(key)

    _s_drop(key)
    await q.answer(f"🚀 starting · {len(targets)} users")

    asyncio.create_task(_do_send(
        client, q.message.chat.id, q.message.id,
        s["source_chat_id"], s["source_msg_id"],
        targets, "users", timer, cap, btns,
    ))


async def _run_channels_all(
    client: Client, q: CallbackQuery, key: int,
) -> None:
    s = _s_get(key)
    if not s:
        return await q.answer("session expired", show_alert=True)

    from plugins.broadcast import channels as CH
    channels = await CH.list_channels()
    enabled = [c for c in channels if c.get("enabled", True)]
    if not enabled:
        return await q.answer("no channels", show_alert=True)

    timer = s.get("timer_secs", 0)

    _s_drop(key)
    await q.answer(f"🚀 starting · {len(enabled)} channels")

    asyncio.create_task(_do_channels_all(
        client, q.message.chat.id, q.message.id,
        s["source_chat_id"], s["source_msg_id"],
        enabled, timer,
    ))


# ============================================================
# SEND ENGINE (standard)
# ============================================================

async def _do_send(
    client: Client,
    panel_chat: int, panel_msg: int,
    source_chat: int, source_msg: int,
    targets: List[int],
    kind: str,
    timer: int,
    cap_tpl: Optional[str] = None,
    btns: Optional[List[Dict]] = None,
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
                    f"⏱ {F.sc('timer')} · <b>{_fmt_timer(timer)}</b>"
                )
            lines += [
                "",
                f"<code>{bar}</code>",
                "",
                f"✅ {F.sc('sent')} · <b>{FM.num(st.get('sent', 0))}</b>",
                f"❌ {F.sc('failed')} · <b>{FM.num(st.get('failed', 0))}</b>",
                f"🚫 {F.sc('blocked')} · <b>{FM.num(st.get('blocked', 0))}</b>",
                "",
                f"📊 <code>{done}/{total}</code>",
            ]
            await client.edit_message_text(
                chat_id=panel_chat, message_id=panel_msg,
                text="\n".join(lines),
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        f"⏹ {F.sc('stop')}",
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
            source_chat_id=source_chat,
            source_msg_id=source_msg,
            targets=targets,
            kind=kind,
            caption_template=cap_tpl,
            buttons_list=btns,
            autodelete_seconds=timer,
            owner=0,
            progress_cb=_progress,
        )
        elapsed = time.time() - started
        await _render_done(
            client, panel_chat, panel_msg, kind, total, result,
            elapsed, timer,
        )
    except Exception as e:
        logger.exception(f"[BC] send: {e}")
        try:
            await client.edit_message_text(
                chat_id=panel_chat, message_id=panel_msg,
                text=f"❌ {F.sc('failed')}: <code>{type(e).__name__}</code>",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass


# ============================================================
# SEND ENGINE (channels all — per-channel caption)
# ============================================================

async def _do_channels_all(
    client: Client,
    panel_chat: int, panel_msg: int,
    source_chat: int, source_msg: int,
    channels: List[Dict[str, Any]],
    timer: int,
) -> None:
    from plugins.broadcast import templates as T
    from plugins.broadcast import state as BS

    total = len(channels)
    started = time.time()
    sent = 0
    failed = 0

    try:
        src_msg = await client.get_messages(source_chat, source_msg)
    except Exception:
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
                from_chat_id=source_chat,
                message_id=source_msg,
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
                    from_chat_id=source_chat,
                    message_id=source_msg,
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
                    f"⏱ {F.sc('timer')} · <b>{_fmt_timer(timer)}</b>"
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
                chat_id=panel_chat, message_id=panel_msg,
                text="\n".join(lines),
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        f"⏹ {F.sc('stop')}",
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
        client, panel_chat, panel_msg,
        "channels (all)", total,
        {"sent": sent, "failed": failed, "blocked": 0},
        elapsed, timer,
    )


# ============================================================
# FINAL REPORT
# ============================================================

async def _render_done(
    client: Client,
    panel_chat: int, panel_msg: int,
    kind: str, total: int,
    result: Dict[str, Any],
    elapsed: float, timer: int,
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
            f"⏱ {F.sc('auto-delete')} · <b>{_fmt_timer(timer)}</b>"
        )

    lines += [
        "",
        f"⏱ {F.sc('time')} · <b>{FM.duration_short(elapsed)}</b>",
    ]

    try:
        await client.edit_message_text(
            chat_id=panel_chat, message_id=panel_msg,
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
# TEXT INPUT (caption entry + channel button add)
# ============================================================

@Client.on_message(
    filters.private & filters.text & ~filters.regex(r"^/"),
    group=-8303,
)
async def bc_text_input(client: Client, message: Message):
    if not message.from_user:
        return
    if not _is_admin(message.from_user.id):
        return

    key = int(message.chat.id)
    s = _s_get(key)
    if not s:
        return

    awaiting = s.get("awaiting")
    if awaiting not in ("caption", "caption_ch", "btn_add_ch"):
        return

    text = (message.text or "").strip()

    try:
        message.stop_propagation()
    except Exception:
        pass

    if awaiting == "caption":
        if text == "-":
            _s_upd(key, caption_mode="none",
                   custom_caption=None, awaiting=None)
            new = "🚫 none"
        else:
            _s_upd(key, caption_mode="custom",
                   custom_caption=text, awaiting=None)
            new = "✏ custom"
        await message.reply_text(
            f"{F.EMO['check']} <b>Caption:</b> {new}",
            parse_mode=ParseMode.HTML,
        )
        return

    if awaiting == "caption_ch":
        cid = s.get("cap_target_ch")
        _s_upd(key, awaiting=None)
        if cid:
            from plugins.broadcast import channels as CH
            new_cap = "" if text == "-" else text
            await CH.set_caption(int(cid), new_cap)
            await message.reply_text(
                f"{F.EMO['check']} <b>Channel caption saved</b>",
                parse_mode=ParseMode.HTML,
            )
        return

    if awaiting == "btn_add_ch":
        cid = s.get("cap_target_ch")
        _s_upd(key, awaiting=None)
        if cid and "|" in text:
            name, url = [p.strip() for p in text.split("|", 1)]
            if name and url:
                if url.startswith("@"):
                    url = f"https://t.me/{url[1:]}"
                elif not url.startswith(("http://", "https://", "tg://")):
                    if "." in url and " " not in url:
                        url = f"https://{url}"
                    else:
                        return
                from plugins.broadcast import channels as CH
                ch = await CH.get_channel(int(cid))
                existing = ch.get("buttons") if ch else None
                btns = list(existing) if existing is not None else []
                btns.append({"name": name[:60], "url": url})
                await CH.set_buttons(int(cid), btns)
                await message.reply_text(
                    f"{F.EMO['check']} <b>Button added</b>",
                    parse_mode=ParseMode.HTML,
                )
        return


# ============================================================
# ADMIN PANEL ENTRY — open flow in admin's PM
# ============================================================

async def bc_open_for_admin(client: Client, user_id: int) -> None:
    """
    Called from /admin → [📢 Broadcast].
    Sends the source picker to the admin's PM.
    """
    key = int(user_id)

    ch = getattr(config, "BROADCAST_CHANNEL_ID", None)
    if not ch:
        try:
            await client.send_message(
                chat_id=user_id,
                text=(
                    f"{F.EMO['warn']} <b>BROADCAST_CHANNEL_ID not set</b>"
                ),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
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
        try:
            await client.send_message(
                chat_id=user_id,
                text=(
                    f"{F.EMO['cross']} {F.sc('cannot read channel')}\n"
                    f"<code>{type(e).__name__}</code>"
                ),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        return

    if not msgs:
        try:
            await client.send_message(
                chat_id=user_id,
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
        return

    src_list = [(int(m.id), _extract_name(m)) for m in msgs]

    _s_set(
        key,
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
            callback_data=_cb(f"src:{i}"),
        )])
    rows.append([InlineKeyboardButton(
        f"❌ {F.sc('cancel')}",
        callback_data=_cb("cancel"),
    )])

    try:
        await client.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=InlineKeyboardMarkup(rows),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.exception(f"[BC-ADMIN] send: {e}")

# ============================================================
# PUBLIC
# ============================================================

def snapshot() -> Dict[str, Any]:
    return {
        "watcher_enabled": _FILTER is not None,
        "active_sessions": len(_sessions),
    }


__all__ = ["snapshot"]
