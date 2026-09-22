# ============================================================
# 🏨 DOWNTOWN VILLA — /broadcast COMMAND (MAIN PANEL)
# ============================================================
#
# ONE COMMAND: /broadcast
#
# Layout:
#   📊 Live progress (if running)
#   [▶️ START NEW]
#   [📢 CHANNELS]   ← target manager
#   [📝 CAPTION]    ← edit global caption
#   [🔘 BUTTONS]    ← edit global buttons
#   [🧾 TEMPLATES]  ← pick caption preset
#   [🧾 HISTORY]    ← past runs
#   [🗑️ CLEAR AUTO] ← clear autodelete schedule
#   [🔄 REFRESH] [❌ CLOSE]
#
# START NEW flow:
#   1. Pick destination: channels / groups / users / both
#   2. Pick source (upload a file or forward)
#   3. Pick autodelete timer
#   4. Confirm → GO
#
# ============================================================

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from core import config
from utils import fonts as F
from utils import format as FM
from utils import progress as P

logger = logging.getLogger(__name__)

PFX = "bc"
AUTO_REFRESH_SEC = 5.0


# ============================================================
# AUTH
# ============================================================

def _is_admin(uid) -> bool:
    try:
        return int(uid) in [int(a) for a in config.ADMINS]
    except Exception:
        return False


# ============================================================
# SETUP SESSION STATE
# ============================================================

_setup: Dict[int, Dict[str, Any]] = {}
SETUP_TTL = 600.0


def _get_setup(uid: int) -> Optional[Dict[str, Any]]:
    s = _setup.get(int(uid))
    if not s:
        return None
    if time.time() > s.get("expires", 0):
        _setup.pop(int(uid), None)
        return None
    return s


def _new_setup(uid: int, step: str, **data) -> None:
    _setup[int(uid)] = {
        "step": step,
        "data": dict(data),
        "expires": time.time() + SETUP_TTL,
    }


def _update_setup(uid: int, **data) -> None:
    s = _setup.get(int(uid))
    if not s:
        return
    s["data"].update(data)
    s["expires"] = time.time() + SETUP_TTL


def _drop_setup(uid: int) -> None:
    _setup.pop(int(uid), None)


# ============================================================
# PANEL REGISTRY
# ============================================================

_panels: Dict[int, Dict[str, Any]] = {}


def _register_panel(mid: int, cid: int, page: str, text: str) -> None:
    _panels[mid] = {
        "chat_id": cid, "page": page,
        "last_text": text, "created": time.time(),
    }


def _unregister_panel(mid: int) -> None:
    _panels.pop(mid, None)


# ============================================================
# MAIN PANEL
# ============================================================

async def _build_main() -> Tuple[str, InlineKeyboardMarkup]:
    from plugins.broadcast import engine as E
    from plugins.broadcast import state as BS
    from plugins.broadcast import channels as CH

    st = E.status()
    running = st.get("running", False)

    channels = await CH.list_channels()
    autodel = await BS.count_scheduled()

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"📢 <b>{F.fb('BROADCAST CENTER')}</b>",
        F.DIV, "",
        f"{'🟢 ' + F.sc('running') if running else '⚪ ' + F.sc('idle')}",
        f"📢 {F.sc('channels')} · <b>{len(channels)}</b>",
        f"⏱️ {F.sc('auto-delete queue')} · <b>{autodel}</b>",
        "",
    ]

    if running:
        total = st.get("total", 0)
        sent = st.get("sent", 0)
        failed = st.get("failed", 0)
        blocked = st.get("blocked", 0)
        done = sent + failed + blocked
        pct = (done / total * 100) if total else 0.0

        lines += [
            F.DIV_S,
            f"{F.EMO['chart']} <b>{F.fb('LIVE PROGRESS')}</b>",
            F.DIV_S,
            "",
            f"<code>{P.bar(pct, 'indexing', width=16)}</code>",
            "",
            f"✅ {F.sc('sent')} · <b>{FM.num(sent)}</b>",
            f"❌ {F.sc('failed')} · <b>{FM.num(failed)}</b>",
            f"🚫 {F.sc('blocked')} · <b>{FM.num(blocked)}</b>",
            "",
            f"⚡ {F.sc('speed')} · <b>{st.get('speed', 0):.1f}/s</b>",
            f"⏱️ {F.sc('eta')} · <b>{st.get('eta_text', '—')}</b>",
            f"📊 {F.sc('progress')} · "
            f"<code>{done}/{total}</code>",
            "",
        ]

    lines.append(f"🕒 <code>{FM.datetime_()}</code>")

    rows: List[List[InlineKeyboardButton]] = []

    if running:
        rows.append([InlineKeyboardButton(
            f"{F.EMO['stop']} {F.sc('stop broadcast')}",
            callback_data=f"{PFX}:stop",
        )])
    else:
        rows.append([InlineKeyboardButton(
            f"{F.EMO['play']} {F.sc('start new')}",
            callback_data=f"{PFX}:start",
        )])

    rows.append([
        InlineKeyboardButton(
            f"📢 {F.sc('channels')}",
            callback_data=f"{PFX}:channels",
        ),
        InlineKeyboardButton(
            f"📝 {F.sc('caption')}",
            callback_data=f"{PFX}:caption",
        ),
    ])
    rows.append([
        InlineKeyboardButton(
            f"🔘 {F.sc('buttons')}",
            callback_data=f"{PFX}:buttons",
        ),
        InlineKeyboardButton(
            f"🧾 {F.sc('templates')}",
            callback_data=f"{PFX}:templates",
        ),
    ])
    rows.append([
        InlineKeyboardButton(
            f"🧾 {F.sc('history')}",
            callback_data=f"{PFX}:history",
        ),
        InlineKeyboardButton(
            f"🗑️ {F.sc('clear auto')}",
            callback_data=f"{PFX}:clear_auto",
        ),
    ])
    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['refresh']} {F.sc('refresh')}",
            callback_data=f"{PFX}:refresh",
        ),
        InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('close')}",
            callback_data=f"{PFX}:close",
        ),
    ])

    return "\n".join(lines)[:4000], InlineKeyboardMarkup(rows)


# ============================================================
# COMMAND
# ============================================================

@Client.on_message(
    filters.command(["broadcast", "bc"]) & filters.private,
    group=-8300,
)
async def cmd_broadcast(client: Client, message: Message):
    if not message.from_user or not _is_admin(message.from_user.id):
        return await message.reply_text(
            f"{F.EMO['cross']} <b>{F.fb('ACCESS DENIED')}</b>",
            parse_mode=ParseMode.HTML,
        )

    try:
        from plugins.broadcast import state as BS
        await BS.ensure_indexes()
    except Exception:
        pass

    text, kb = await _build_main()
    sent = await message.reply_text(
        text, reply_markup=kb,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )
    _register_panel(sent.id, sent.chat.id, "main", text)
    _ensure_auto_refresh()


# ============================================================
# START FLOW
# ============================================================

async def _build_step_destination(uid: int) -> Tuple[str, InlineKeyboardMarkup]:
    from plugins.broadcast import channels as CH
    from database import db_registry

    ch_count = len(await CH.list_channels())

    user_count = 0
    try:
        db = db_registry.get_user_db()
        if db is not None:
            user_count = await db["users"].count_documents({})
    except Exception:
        pass

    group_count = 0
    try:
        db = db_registry.get_user_db()
        if db is not None:
            group_count = await db["groups"].count_documents({})
    except Exception:
        pass

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"📢 <b>{F.fb('STEP 1/4 — DESTINATION')}</b>",
        F.DIV, "",
        f"{F.EMO['info']} {F.sc('where to send the broadcast')}",
        "",
        f"📢 {F.sc('channels')} · <b>{ch_count}</b>",
        f"👥 {F.sc('groups')} · <b>{group_count}</b>",
        f"👤 {F.sc('users')} · <b>{user_count}</b>",
    ]

    rows = [
        [InlineKeyboardButton(
            f"📢 {F.sc('channels')} ({ch_count})",
            callback_data=f"{PFX}:dst:channels",
        )],
        [InlineKeyboardButton(
            f"👥 {F.sc('groups')} ({group_count})",
            callback_data=f"{PFX}:dst:groups",
        )],
        [InlineKeyboardButton(
            f"👤 {F.sc('users')} ({user_count})",
            callback_data=f"{PFX}:dst:users",
        )],
        [InlineKeyboardButton(
            f"🎯 {F.sc('both groups + users')}",
            callback_data=f"{PFX}:dst:both",
        )],
        [InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('cancel')}",
            callback_data=f"{PFX}:cancel_setup",
        )],
    ]
    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def _build_step_source(uid: int) -> Tuple[str, InlineKeyboardMarkup]:
    s = _get_setup(uid)
    data = s.get("data", {}) if s else {}
    kind = data.get("dest", "?")

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"📎 <b>{F.fb('STEP 2/4 — SOURCE')}</b>",
        F.DIV, "",
        f"🎯 {F.sc('destination')} · <b>{kind.upper()}</b>",
        "",
        f"{F.EMO['info']} {F.sc('how to pick the source message')}",
        "",
        f"📌 {F.sc('send any media file here in pm')}",
        f"📌 {F.sc('or')} {F.sc('forward a message from any chat')}",
        f"📌 {F.sc('the bot will use it as the source')}",
    ]

    rows = [[
        InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('cancel')}",
            callback_data=f"{PFX}:cancel_setup",
        ),
    ]]
    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def _build_step_timer(uid: int) -> Tuple[str, InlineKeyboardMarkup]:
    s = _get_setup(uid)
    data = s.get("data", {}) if s else {}
    kind = data.get("dest", "?")

    timer_options = [
        (0, "♾️ NEVER"),
        (3600, "⏱️ 1 HOUR"),
        (21600, "⏱️ 6 HOURS"),
        (86400, "⏱️ 1 DAY"),
        (259200, "⏱️ 3 DAYS"),
        (604800, "⏱️ 7 DAYS"),
        (2592000, "⏱️ 30 DAYS"),
    ]

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"⏱️ <b>{F.fb('STEP 3/4 — AUTO-DELETE')}</b>",
        F.DIV, "",
        f"🎯 {F.sc('destination')} · <b>{kind.upper()}</b>",
        "",
        f"{F.EMO['info']} {F.sc('when to delete sent messages')}",
        f"📌 {F.sc('only applies to user broadcasts')}",
        f"📌 {F.sc('groups and channels are not deleted')}",
    ]

    rows = []
    row = []
    for secs, label in timer_options:
        row.append(InlineKeyboardButton(
            label,
            callback_data=f"{PFX}:timer:{secs}",
        ))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    rows.append([InlineKeyboardButton(
        f"{F.EMO['cross']} {F.sc('cancel')}",
        callback_data=f"{PFX}:cancel_setup",
    )])

    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def _build_step_confirm(uid: int) -> Tuple[str, InlineKeyboardMarkup]:
    s = _get_setup(uid)
    data = s.get("data", {}) if s else {}
    kind = data.get("dest", "?")
    secs = data.get("timer", 0)
    source = data.get("source", {})

    label = "♾️ NEVER" if secs == 0 else FM.duration_short(secs)

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"✅ <b>{F.fb('STEP 4/4 — CONFIRM')}</b>",
        F.DIV, "",
        f"🎯 {F.sc('destination')} · <b>{kind.upper()}</b>",
        f"⏱️ {F.sc('auto-delete')} · <b>{label}</b>",
        f"📎 {F.sc('source')} · "
        f"<code>msg {source.get('message_id', '?')}</code>",
        "",
        F.DIV_S,
        f"{F.EMO['spark']} {F.sc('ready to broadcast')}",
    ]

    rows = [
        [InlineKeyboardButton(
            f"▶️ {F.sc('start broadcast')}",
            callback_data=f"{PFX}:go",
        )],
        [InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('cancel')}",
            callback_data=f"{PFX}:cancel_setup",
        )],
    ]
    return "\n".join(lines), InlineKeyboardMarkup(rows)


# ============================================================
# CAPTION / BUTTONS
# ============================================================

async def _build_caption_panel() -> Tuple[str, InlineKeyboardMarkup]:
    from plugins.broadcast import templates as T
    cap = await T.get_caption()
    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"📝 <b>{F.fb('GLOBAL CAPTION')}</b>",
        F.DIV, "",
        f"<code>{F.sc(cap[:300])}</code>",
        "",
        F.DIV_S,
        f"📌 {F.sc('placeholders')}:",
        f"<code>{{file_name}}</code> <code>{{file_size}}</code>",
        f"<code>{{year}}</code> <code>{{rating}}</code>",
    ]
    rows = [
        [InlineKeyboardButton(
            f"✏️ {F.sc('edit')}",
            callback_data=f"{PFX}:caption_edit",
        )],
        [InlineKeyboardButton(
            f"♻️ {F.sc('reset default')}",
            callback_data=f"{PFX}:caption_reset",
        )],
        [InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data=f"{PFX}:back",
        )],
    ]
    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def _build_buttons_panel() -> Tuple[str, InlineKeyboardMarkup]:
    from plugins.broadcast import templates as T
    btns = await T.get_buttons()

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"🔘 <b>{F.fb('GLOBAL BUTTONS')}</b>",
        F.DIV, "",
        f"📊 {F.sc('total')} · <b>{len(btns)}</b>",
        "",
    ]

    if not btns:
        lines.append(f"⚪ {F.sc('no buttons yet')}")
    else:
        for i, b in enumerate(btns, 1):
            lines.append(
                f"<b>{i:02d}.</b> {F.sc(str(b.get('name', '?'))[:30])}"
            )
            lines.append(f"   <code>{str(b.get('url', '?'))[:50]}</code>")

    rows = [
        [InlineKeyboardButton(
            f"➕ {F.sc('add button')}",
            callback_data=f"{PFX}:btn_add",
        )],
    ]
    if btns:
        rows.append([InlineKeyboardButton(
            f"🗑️ {F.sc('remove one')}",
            callback_data=f"{PFX}:btn_rm_menu",
        )])
        rows.append([InlineKeyboardButton(
            f"♻️ {F.sc('clear all')}",
            callback_data=f"{PFX}:btn_clear",
        )])
    rows.append([InlineKeyboardButton(
        f"{F.EMO['back']} {F.sc('back')}",
        callback_data=f"{PFX}:back",
    )])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def _build_templates_panel() -> Tuple[str, InlineKeyboardMarkup]:
    from plugins.broadcast import templates as T
    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"🧾 <b>{F.fb('CAPTION TEMPLATES')}</b>",
        F.DIV, "",
        f"📌 {F.sc('pick a template to load')}",
    ]
    rows = []
    for name in T.CAPTION_TEMPLATES.keys():
        rows.append([InlineKeyboardButton(
            f"📝 {name.upper()}",
            callback_data=f"{PFX}:tpl_use:{name}",
        )])
    rows.append([InlineKeyboardButton(
        f"{F.EMO['back']} {F.sc('back')}",
        callback_data=f"{PFX}:back",
    )])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def _build_history_panel() -> Tuple[str, InlineKeyboardMarkup]:
    from plugins.broadcast import state as BS
    runs = await BS.list_runs(15)

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"🧾 <b>{F.fb('BROADCAST HISTORY')}</b>",
        F.DIV, "",
    ]

    if not runs:
        lines.append(f"⚪ {F.sc('no runs yet')}")
    else:
        for r in runs:
            status = str(r.get("status", "?"))
            icon = {
                "running": "🟢", "completed": "✅", "cancelled": "🛑",
            }.get(status, "⚪")
            started = r.get("started_at")
            time_str = (
                started.strftime("%d %b %H:%M") if started else "?"
            )
            lines.append(f"{icon} <b>{F.sc(status)}</b> · "
                         f"<code>{time_str}</code>")
            lines.append(
                f"   📢 <b>{FM.num(r.get('sent', 0))}</b> · "
                f"❌ <b>{FM.num(r.get('failed', 0))}</b> · "
                f"🚫 <b>{FM.num(r.get('blocked', 0))}</b>"
            )
            lines.append("")

    rows = [
        [InlineKeyboardButton(
            f"🗑️ {F.sc('clear history')}",
            callback_data=f"{PFX}:hist_clear",
        )],
        [
            InlineKeyboardButton(
                f"{F.EMO['refresh']} {F.sc('refresh')}",
                callback_data=f"{PFX}:history",
            ),
            InlineKeyboardButton(
                f"{F.EMO['back']} {F.sc('back')}",
                callback_data=f"{PFX}:back",
            ),
        ],
    ]
    return "\n".join(lines)[:4000], InlineKeyboardMarkup(rows)


# ============================================================
# CHANNEL MANAGER
# ============================================================

async def _build_channels_panel() -> Tuple[str, InlineKeyboardMarkup]:
    from plugins.broadcast import channels as CH
    channels = await CH.list_channels()

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"📢 <b>{F.fb('BROADCAST CHANNELS')}</b>",
        F.DIV, "",
        f"📊 {F.sc('total')} · <b>{len(channels)}</b>",
        "",
    ]

    if not channels:
        lines.append(f"⚪ {F.sc('no channels yet')}")
    else:
        for i, ch in enumerate(channels, 1):
            icon = "🟢" if ch.get("enabled") else "🔴"
            star = "⭐ " if ch.get("primary") else ""
            title = str(ch.get("title", "?"))[:40]
            lines.append(f"<b>{i:02d}.</b> {icon} {star}{F.sc(title)}")
            lines.append(f"    🆔 <code>{ch.get('chat_id')}</code>")

    rows: List[List[InlineKeyboardButton]] = []
    for ch in channels[:8]:
        icon = "🟢" if ch.get("enabled") else "🔴"
        star = "⭐ " if ch.get("primary") else ""
        title = str(ch.get("title", "?"))[:26]
        rows.append([InlineKeyboardButton(
            f"{star}{icon} {title}",
            callback_data=f"{PFX}:ch_view:{ch['chat_id']}",
        )])

    rows.append([InlineKeyboardButton(
        f"➕ {F.sc('add channel')}",
        callback_data=f"{PFX}:ch_add",
    )])
    rows.append([InlineKeyboardButton(
        f"{F.EMO['back']} {F.sc('back')}",
        callback_data=f"{PFX}:back",
    )])
    return "\n".join(lines)[:4000], InlineKeyboardMarkup(rows)


async def _build_channel_view(chat_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    from plugins.broadcast import channels as CH
    ch = await CH.get_channel(chat_id)
    if not ch:
        return ("⚠️ Channel not found",
                InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        f"{F.EMO['back']} {F.sc('back')}",
                        callback_data=f"{PFX}:channels",
                    )
                ]]))

    enabled = ch.get("enabled", True)
    primary = ch.get("primary", False)
    title = str(ch.get("title", "?"))[:60]
    username = ch.get("username") or ""

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"📢 <b>{F.fb('CHANNEL DETAIL')}</b>",
        F.DIV, "",
        f"📛 <b>{F.sc(title)}</b>",
        f"🆔 <code>{chat_id}</code>",
    ]
    if username:
        lines.append(f"🔗 <code>@{username}</code>")
    lines += [
        "",
        f"⚙️ {F.sc('status')} · "
        f"{'🟢 enabled' if enabled else '🔴 disabled'}",
        f"⭐ {F.sc('primary')} · "
        f"{'🟢 yes' if primary else '🔴 no'}",
    ]

    rows = [
        [
            InlineKeyboardButton(
                f"{'🔴 disable' if enabled else '🟢 enable'}",
                callback_data=f"{PFX}:ch_toggle:{chat_id}",
            ),
            InlineKeyboardButton(
                f"{'⭐ unset' if primary else '⭐ set primary'}",
                callback_data=f"{PFX}:ch_primary:{chat_id}",
            ),
        ],
        [InlineKeyboardButton(
            f"🧪 {F.sc('test')}",
            callback_data=f"{PFX}:ch_test:{chat_id}",
        )],
        [InlineKeyboardButton(
            f"🗑️ {F.sc('remove')}",
            callback_data=f"{PFX}:ch_confirm_rm:{chat_id}",
        )],
        [
            InlineKeyboardButton(
                f"{F.EMO['back']} {F.sc('back')}",
                callback_data=f"{PFX}:channels",
            ),
            InlineKeyboardButton(
                f"{F.EMO['cross']} {F.sc('close')}",
                callback_data=f"{PFX}:close",
            ),
        ],
    ]
    return "\n".join(lines), InlineKeyboardMarkup(rows)


# ============================================================
# CALLBACK ROUTER
# ============================================================

@Client.on_callback_query(
    filters.regex(rf"^{PFX}:"),
    group=-8300,
)
async def broadcast_router(client: Client, q: CallbackQuery):
    if not q.from_user or not _is_admin(q.from_user.id):
        return await q.answer("❌ Admin only", show_alert=True)

    parts = str(q.data).split(":")
    action = parts[1] if len(parts) > 1 else ""
    arg = parts[2] if len(parts) > 2 else ""
    uid = q.from_user.id

    try:
        # ── MAIN ──
        if action in ("back", "refresh"):
            text, kb = await _build_main()
            await _safe_edit(q, text, kb)
            return await q.answer()

        if action == "close":
            _unregister_panel(q.message.id)
            try:
                await q.message.delete()
            except Exception:
                pass
            return await q.answer("Closed")

        if action == "stop":
            from plugins.broadcast import engine as E
            ok = E.cancel()
            await q.answer("⏹️ Stopping…" if ok else "⚠️ Not running")
            return

        # ── START FLOW ──
        if action == "start":
            _drop_setup(uid)
            _new_setup(uid, "destination")
            text, kb = await _build_step_destination(uid)
            await _safe_edit(q, text, kb)
            return await q.answer()

        if action == "dst":
            _update_setup(uid, dest=arg)
            _new_setup(uid, "source", dest=arg)
            text, kb = await _build_step_source(uid)
            await _safe_edit(q, text, kb)
            return await q.answer()

        if action == "cancel_setup":
            _drop_setup(uid)
            text, kb = await _build_main()
            await _safe_edit(q, text, kb)
            return await q.answer("❌ Cancelled")

        if action == "timer":
            try:
                secs = int(arg)
            except ValueError:
                return await q.answer("❌")
            _update_setup(uid, timer=secs)
            text, kb = await _build_step_confirm(uid)
            await _safe_edit(q, text, kb)
            return await q.answer()

        if action == "go":
            s = _get_setup(uid)
            if not s:
                return await q.answer("⚠️ Session expired")
            data = s.get("data", {})
            src = data.get("source") or {}
            if not src.get("message_id"):
                return await q.answer("⚠️ No source", show_alert=True)

            dest = data.get("dest", "users")
            timer = int(data.get("timer", 0))

            # Collect targets
            targets = await _collect_targets(dest)
            if not targets:
                return await q.answer("⚠️ No targets", show_alert=True)

            _drop_setup(uid)
            await q.answer(f"🚀 Broadcasting to {len(targets)}…")

            # Show progress card
            text, kb = await _build_main()
            await _safe_edit(q, text, kb)

            # Run broadcast (async)
            asyncio.create_task(_run_broadcast_bg(
                client, src, targets, dest, timer, uid,
                q.message.chat.id, q.message.id,
            ))
            return

        # ── SUB PANELS ──
        if action == "channels":
            text, kb = await _build_channels_panel()
            await _safe_edit(q, text, kb)
            return await q.answer()

        if action == "caption":
            text, kb = await _build_caption_panel()
            await _safe_edit(q, text, kb)
            return await q.answer()

        if action == "buttons":
            text, kb = await _build_buttons_panel()
            await _safe_edit(q, text, kb)
            return await q.answer()

        if action == "templates":
            text, kb = await _build_templates_panel()
            await _safe_edit(q, text, kb)
            return await q.answer()

        if action == "history":
            text, kb = await _build_history_panel()
            await _safe_edit(q, text, kb)
            return await q.answer()

        if action == "hist_clear":
            from plugins.broadcast import state as BS
            n = await BS.clear_runs()
            await q.answer(f"🗑️ Cleared {n}")
            text, kb = await _build_history_panel()
            await _safe_edit(q, text, kb)
            return

        if action == "clear_auto":
            from plugins.broadcast import state as BS
            due = await BS.due_autodeletes(limit=10000)
            for d in due:
                await BS.remove_autodelete(d.get("_id"))
            await q.answer(f"🗑️ Cleared queue")
            text, kb = await _build_main()
            await _safe_edit(q, text, kb)
            return

        # ── CAPTION EDIT ──
        if action == "caption_edit":
            _new_setup(uid, "caption_edit")
            text = "\n".join([
                f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                f"✏️ <b>{F.fb('EDIT CAPTION')}</b>",
                F.DIV, "",
                f"📌 {F.sc('send the new caption as next message')}",
            ])
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"{F.EMO['cross']} {F.sc('cancel')}",
                    callback_data=f"{PFX}:caption",
                ),
            ]])
            await _safe_edit(q, text, kb)
            return await q.answer()

        if action == "caption_reset":
            from plugins.broadcast import templates as T
            await T.set_caption(T.DEFAULT_CAPTION)
            await q.answer("♻️ Reset")
            text, kb = await _build_caption_panel()
            await _safe_edit(q, text, kb)
            return

        if action == "tpl_use":
            from plugins.broadcast import templates as T
            tpl = T.CAPTION_TEMPLATES.get(arg)
            if tpl:
                await T.set_caption(tpl)
                await q.answer(f"✅ {arg}")
            text, kb = await _build_caption_panel()
            await _safe_edit(q, text, kb)
            return

        # ── BUTTONS EDIT ──
        if action == "btn_add":
            _new_setup(uid, "btn_add")
            text = "\n".join([
                f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                f"➕ <b>{F.fb('ADD BUTTON')}</b>",
                F.DIV, "",
                f"📌 {F.sc('send')} <code>Name | URL</code>",
            ])
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"{F.EMO['cross']} {F.sc('cancel')}",
                    callback_data=f"{PFX}:buttons",
                ),
            ]])
            await _safe_edit(q, text, kb)
            return await q.answer()

        if action == "btn_clear":
            from plugins.broadcast import templates as T
            await T.set_buttons([])
            await q.answer("♻️ Cleared")
            text, kb = await _build_buttons_panel()
            await _safe_edit(q, text, kb)
            return

        # ── CHANNEL VIEW ──
        if action == "ch_view":
            try:
                cid = int(arg)
            except ValueError:
                return await q.answer("❌")
            text, kb = await _build_channel_view(cid)
            await _safe_edit(q, text, kb)
            return await q.answer()

        if action == "ch_add":
            _new_setup(uid, "ch_add")
            text = "\n".join([
                f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                f"➕ <b>{F.fb('ADD CHANNEL')}</b>",
                F.DIV, "",
                f"📌 {F.sc('send channel id or @username')}",
            ])
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"{F.EMO['cross']} {F.sc('cancel')}",
                    callback_data=f"{PFX}:channels",
                ),
            ]])
            await _safe_edit(q, text, kb)
            return await q.answer()

        if action == "ch_toggle":
            from plugins.broadcast import channels as CH
            try:
                cid = int(arg)
            except ValueError:
                return await q.answer("❌")
            ch = await CH.get_channel(cid)
            if not ch:
                return await q.answer("⚠️ Not found")
            new = not ch.get("enabled", True)
            await CH.update_channel(cid, enabled=new)
            await q.answer("🟢" if new else "🔴")
            text, kb = await _build_channel_view(cid)
            await _safe_edit(q, text, kb)
            return

        if action == "ch_primary":
            from plugins.broadcast import channels as CH
            try:
                cid = int(arg)
            except ValueError:
                return await q.answer("❌")
            await CH.set_primary(cid)
            await q.answer("⭐ Primary set")
            text, kb = await _build_channel_view(cid)
            await _safe_edit(q, text, kb)
            return

        if action == "ch_test":
            from plugins.broadcast import channels as CH
            try:
                cid = int(arg)
            except ValueError:
                return await q.answer("❌")
            ok = await CH.test_channel(client, cid)
            await q.answer("✅ Sent" if ok else "❌ Failed",
                          show_alert=True)
            return

        if action == "ch_confirm_rm":
            try:
                cid = int(arg)
            except ValueError:
                return await q.answer("❌")
            text = "\n".join([
                f"{F.EMO['warn']} <b>{F.fb('REMOVE CHANNEL?')}</b>",
                F.DIV, "",
                f"🆔 <code>{cid}</code>",
                "",
                f"📌 {F.sc('only removes from broadcast manager')}",
            ])
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    f"🗑️ {F.sc('yes, remove')}",
                    callback_data=f"{PFX}:ch_do_rm:{cid}",
                )],
                [InlineKeyboardButton(
                    f"{F.EMO['back']} {F.sc('cancel')}",
                    callback_data=f"{PFX}:ch_view:{cid}",
                )],
            ])
            await _safe_edit(q, text, kb)
            return await q.answer()

        if action == "ch_do_rm":
            from plugins.broadcast import channels as CH
            try:
                cid = int(arg)
            except ValueError:
                return await q.answer("❌")
            await CH.remove_channel(cid)
            await q.answer("🗑️ Removed")
            text, kb = await _build_channels_panel()
            await _safe_edit(q, text, kb)
            return

        return await q.answer("❓ Unknown")

    except Exception as e:
        logger.exception(f"[BC] router: {e}")
        try:
            await q.answer(f"❌ {type(e).__name__}", show_alert=True)
        except Exception:
            pass


# ============================================================
# TEXT INPUT HANDLER
# ============================================================

@Client.on_message(
    filters.private & filters.text & ~filters.regex(r"^/"),
    group=-8290,
)
async def broadcast_text_input(client: Client, message: Message):
    if not message.from_user or not _is_admin(message.from_user.id):
        return

    s = _get_setup(message.from_user.id)
    if not s:
        return

    step = s.get("step", "")
    text = (message.text or "").strip()

    # ── CAPTION EDIT ──
    if step == "caption_edit":
        from plugins.broadcast import templates as T
        await T.set_caption(text)
        _drop_setup(message.from_user.id)
        await message.reply_text(
            f"{F.EMO['check']} <b>Caption updated</b>",
            parse_mode=ParseMode.HTML,
        )
        try:
            message.stop_propagation()
        except Exception:
            pass
        return

    # ── BUTTON ADD ──
    if step == "btn_add":
        if "|" not in text:
            return await message.reply_text(
                f"{F.EMO['cross']} <code>Name | URL</code>",
                parse_mode=ParseMode.HTML,
            )
        name, url = [p.strip() for p in text.split("|", 1)]
        from plugins.broadcast import templates as T
        btns = await T.get_buttons()
        if len(btns) >= 8:
            _drop_setup(message.from_user.id)
            return await message.reply_text("⚠️ Max 8 buttons")
        btns.append({"name": name[:60], "url": url})
        await T.set_buttons(btns)
        _drop_setup(message.from_user.id)
        await message.reply_text(
            f"{F.EMO['check']} <b>Added</b>",
            parse_mode=ParseMode.HTML,
        )
        try:
            message.stop_propagation()
        except Exception:
            pass
        return

    # ── CHANNEL ADD ──
    if step == "ch_add":
        from plugins.broadcast import channels as CH
        r = await CH.resolve_target(client, text)
        if not r.get("ok"):
            return await message.reply_text(
                f"{F.EMO['cross']} {F.sc(r.get('error', '?'))}",
                parse_mode=ParseMode.HTML,
            )
        await CH.add_channel(
            r["chat_id"], r["title"], r["username"],
            message.from_user.id,
        )
        _drop_setup(message.from_user.id)
        await CH.test_channel(client, r["chat_id"])
        await message.reply_text(
            f"{F.EMO['check']} <b>Channel added</b>\n"
            f"📛 {F.sc(r['title'])}\n"
            f"🆔 <code>{r['chat_id']}</code>",
            parse_mode=ParseMode.HTML,
        )
        try:
            message.stop_propagation()
        except Exception:
            pass
        return

    # ── SOURCE (media) ──
    if step == "source":
        # Waiting for user to send a media file — handle in media handler below
        return


# ============================================================
# SOURCE MEDIA DETECTION (any media when in source step)
# ============================================================

@Client.on_message(
    filters.private
    & (filters.photo | filters.video | filters.document
       | filters.audio | filters.animation),
    group=-8289,
)
async def broadcast_source_media(client: Client, message: Message):
    if not message.from_user or not _is_admin(message.from_user.id):
        return
    s = _get_setup(message.from_user.id)
    if not s or s.get("step") != "source":
        return

    _update_setup(
        message.from_user.id,
        source={
            "chat_id": message.chat.id,
            "message_id": message.id,
        },
        step="timer",
    )
    try:
        message.stop_propagation()
    except Exception:
        pass

    text, kb = await _build_step_timer(message.from_user.id)
    await message.reply_text(
        text, reply_markup=kb,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


# ============================================================
# SOURCE FORWARD DETECTION
# ============================================================

@Client.on_message(
    filters.private & filters.forwarded & ~filters.service,
    group=-8288,
)
async def broadcast_source_forward(client: Client, message: Message):
    if not message.from_user or not _is_admin(message.from_user.id):
        return
    s = _get_setup(message.from_user.id)
    if not s or s.get("step") != "source":
        return

    origin_chat = getattr(message, "forward_from_chat", None)
    origin_msg = getattr(message, "forward_from_message_id", None)

    if not origin_chat or not origin_msg:
        return

    _update_setup(
        message.from_user.id,
        source={
            "chat_id": origin_chat.id,
            "message_id": origin_msg,
        },
        step="timer",
    )
    try:
        message.stop_propagation()
    except Exception:
        pass

    text, kb = await _build_step_timer(message.from_user.id)
    await message.reply_text(
        text, reply_markup=kb,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


# ============================================================
# TARGETS COLLECTOR
# ============================================================

async def _collect_targets(dest: str) -> List[int]:
    targets: List[int] = []

    if dest == "channels":
        from plugins.broadcast import channels as CH
        channels = await CH.list_channels()
        targets = [
            int(c["chat_id"]) for c in channels
            if c.get("enabled", True)
        ]
    elif dest == "groups":
        targets = await _all_groups()
    elif dest == "users":
        targets = await _all_users()
    elif dest == "both":
        targets = await _all_groups() + await _all_users()

    return targets


async def _all_users() -> List[int]:
    try:
        from database import db_registry
        db = db_registry.get_user_db()
        if db is None:
            return []
        cursor = db["users"].find(
            {"blocked_bot": {"$ne": True}}, {"user_id": 1}
        )
        docs = await cursor.to_list(length=100000)
        return [int(d["user_id"]) for d in docs if d.get("user_id")]
    except Exception:
        return []


async def _all_groups() -> List[int]:
    try:
        from database import db_registry
        db = db_registry.get_user_db()
        if db is None:
            return []
        cursor = db["groups"].find({}, {"chat_id": 1})
        docs = await cursor.to_list(length=10000)
        return [int(d["chat_id"]) for d in docs if d.get("chat_id")]
    except Exception:
        return []


# ============================================================
# BACKGROUND BROADCAST
# ============================================================

async def _run_broadcast_bg(
    client: Client,
    source: Dict[str, Any],
    targets: List[int],
    kind: str,
    timer: int,
    owner: int,
    panel_chat_id: int,
    panel_msg_id: int,
) -> None:
    from plugins.broadcast import engine as E
    try:
        result = await E.run_broadcast(
            client=client,
            source_chat_id=source["chat_id"],
            source_msg_id=source["message_id"],
            targets=targets,
            kind=kind,
            autodelete_seconds=timer,
            owner=owner,
        )
        logger.info(f"[BC-BG] done: {result}")
    except Exception as e:
        logger.exception(f"[BC-BG] crashed: {e}")

    # Final refresh of panel
    try:
        text, kb = await _build_main()
        await client.edit_message_text(
            chat_id=panel_chat_id,
            message_id=panel_msg_id,
            text=text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception:
        pass


# ============================================================
# AUTO REFRESH
# ============================================================

_refresh_task: Optional[asyncio.Task] = None


def _ensure_auto_refresh() -> None:
    global _refresh_task
    if _refresh_task and not _refresh_task.done():
        return
    try:
        loop = asyncio.get_running_loop()
        _refresh_task = loop.create_task(_auto_refresh_loop())
    except RuntimeError:
        pass


async def _auto_refresh_loop() -> None:
    while True:
        try:
            await asyncio.sleep(AUTO_REFRESH_SEC)
            if not _panels:
                continue
            from plugins.broadcast import engine as E
            if not E.is_running():
                continue
            from core.client import client as C
            if C is None:
                continue
            for mid, panel in list(_panels.items()):
                if panel.get("page") != "main":
                    continue
                try:
                    text, kb = await _build_main()
                    if text == panel.get("last_text"):
                        continue
                    await C.edit_message_text(
                        chat_id=panel["chat_id"],
                        message_id=mid,
                        text=text, reply_markup=kb,
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=True,
                    )
                    panel["last_text"] = text
                except Exception as e:
                    if "not found" in str(e).lower():
                        _unregister_panel(mid)
        except asyncio.CancelledError:
            return
        except Exception:
            pass


# ============================================================
# HELPERS
# ============================================================

async def _safe_edit(q: CallbackQuery, text: str, kb) -> None:
    try:
        await q.message.edit_text(
            text, reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        if "not modified" not in str(e).lower():
            logger.debug(f"[BC] edit: {e}")


async def open_panel_for_admin(client: Client, message: Message) -> None:
    try:
        from plugins.broadcast import state as BS
        await BS.ensure_indexes()
    except Exception:
        pass
    text, kb = await _build_main()
    sent = await message.reply_text(
        text, reply_markup=kb,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )
    _register_panel(sent.id, sent.chat.id, "main", text)
    _ensure_auto_refresh()


def snapshot() -> Dict[str, Any]:
    return {
        "panels": len(_panels),
        "pending_setups": len(_setup),
    }


__all__ = [
    "cmd_broadcast",
    "open_panel_for_admin",
    "snapshot",
]
