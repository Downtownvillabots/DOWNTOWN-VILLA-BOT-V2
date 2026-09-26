# ============================================================
# 🏨 DOWNTOWN VILLA — BROADCAST CHANNEL WATCHER (AUTO FLOW)
# ============================================================
#
# When a message lands in BROADCAST_CHANNEL_ID:
#   1. Register it as a source (in-memory, 1h TTL)
#   2. Post a destination picker in the channel
#
# Flow:
#   upload → [📢 CHANNELS] [👥 GROUPS] [👤 USERS]
#           ↓
#   channels → pick channel → send with per-channel caption
#   groups   → confirm → send with global caption
#   users    → pick auto-delete timer → confirm → send
#
# ============================================================

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

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


# ============================================================
# SOURCE REGISTRY (in-memory, 1h TTL)
# ============================================================

_SOURCES: Dict[str, Dict[str, Any]] = {}
SOURCE_TTL = 3600.0


def _register_source(message: Message) -> str:
    sid = uuid.uuid4().hex[:10]
    _SOURCES[sid] = {
        "chat_id": int(message.chat.id),
        "message_id": int(message.id),
        "created_at": time.time(),
        "expires_at": time.time() + SOURCE_TTL,
    }
    return sid


def _get_source(sid: str) -> Optional[Dict[str, Any]]:
    s = _SOURCES.get(sid)
    if not s:
        return None
    if time.time() > s.get("expires_at", 0):
        _SOURCES.pop(sid, None)
        return None
    return s


def _cb(action: str) -> str:
    return f"bca:{action}"


# ============================================================
# TIMER PRESETS (for user broadcasts)
# ============================================================

TIMER_PRESETS = [
    (0,       "♾️ never"),
    (86400,   "⏱️ 1 day"),
    (259200,  "⏱️ 3 days"),
    (604800,  "⏱️ 7 days"),
    (864000,  "⏱️ 10 days"),
    (2592000, "⏱️ 30 days"),
]


def _fmt_timer(seconds: int) -> str:
    if seconds == 0:
        return "♾️ never"
    return f"⏱️ {FM.duration_short(seconds)}"


# ============================================================
# AUTH
# ============================================================

def _is_admin(uid) -> bool:
    try:
        return int(uid) in [int(a) for a in config.ADMINS]
    except Exception:
        return False


# ============================================================
# WATCHER — fires on any message in the broadcast channel
# ============================================================

def _build_channel_filter():
    ch = getattr(config, "BROADCAST_CHANNEL_ID", None)
    if not ch:
        return None
    return filters.chat(ch) & ~filters.service


_CHANNEL_FILTER = _build_channel_filter()


if _CHANNEL_FILTER is not None:

    @Client.on_message(_CHANNEL_FILTER, group=-8305)
    async def broadcast_channel_watcher(client: Client, message: Message):
        try:
            sid = _register_source(message)
            logger.info(
                f"[BC-WATCH] sid={sid} msg={message.id} "
                f"media={(message.media.value if message.media else 'text')}"
            )

            text = "\n".join([
                f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                f"📢 <b>{F.fb('BROADCAST READY')}</b>",
                F.DIV, "",
                f"📌 {F.sc('pick where to send this')}",
                "",
                f"📢 {F.sc('channels')} · {F.sc('per-channel caption')}",
                f"👥 {F.sc('groups')} · {F.sc('global caption')}",
                f"👤 {F.sc('users')} · {F.sc('auto-delete timer')}",
                "",
                f"🆔 <code>{sid}</code>",
            ])

            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    f"📢 {F.sc('channels')}",
                    callback_data=_cb(f"channels:{sid}"),
                )],
                [InlineKeyboardButton(
                    f"👥 {F.sc('groups')}",
                    callback_data=_cb(f"groups:{sid}"),
                )],
                [InlineKeyboardButton(
                    f"👤 {F.sc('users')}",
                    callback_data=_cb(f"users:{sid}"),
                )],
                [InlineKeyboardButton(
                    f"❌ {F.sc('cancel')}",
                    callback_data=_cb(f"cancel:{sid}"),
                )],
            ])

            await message.reply_text(
                text,
                reply_markup=kb,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
                quote=True,
            )
        except Exception as e:
            logger.exception(f"[BC-WATCH] {e}")


# ============================================================
# CALLBACK ROUTER (bca:*)
# ============================================================

@Client.on_callback_query(
    filters.regex(r"^bca:"), group=-8304,
)
async def broadcast_auto_router(client: Client, q: CallbackQuery):
    if not q.from_user or not _is_admin(q.from_user.id):
        return await q.answer("❌ admin only", show_alert=True)

    parts = str(q.data or "").split(":")
    action = parts[1] if len(parts) > 1 else ""
    sid = parts[2] if len(parts) > 2 else ""

    # ── STOP / DONE (no sid needed) ──
    if action == "stop":
        from plugins.broadcast import engine as E
        ok = E.cancel()
        return await q.answer("⏹️ stopping..." if ok else "⚠️ idle")

    if action == "done":
        try:
            await q.message.delete()
        except Exception:
            pass
        return await q.answer("done")

    # ── CANCEL ──
    if action == "cancel":
        _SOURCES.pop(sid, None)
        try:
            await q.message.delete()
        except Exception:
            pass
        return await q.answer("❌ cancelled")

    # ── everything else needs the source ──
    src = _get_source(sid)
    if not src:
        return await q.answer(
            "⏱️ source expired — re-upload the file", show_alert=True,
        )

    try:
        # ── BACK to destination picker ──
        if action == "back":
            return await _show_destination_picker(q, sid)

        # ── CHANNELS ──
        if action == "channels":
            return await _show_channel_picker(q, sid)

        if action == "ch_pick":
            cid = int(parts[3]) if len(parts) > 3 else 0
            return await _run_channel(client, q, sid, src, cid)

        # ── GROUPS ──
        if action == "groups":
            return await _show_confirm(q, sid, "groups", 0)

        if action == "groups_go":
            return await _run_auto(
                client, q, sid, src, kind="groups", timer=0,
            )

        # ── USERS ──
        if action == "users":
            return await _show_timer_picker(q, sid)

        if action == "users_t":
            timer = int(parts[3]) if len(parts) > 3 else 0
            return await _show_confirm(q, sid, "users", timer)

        if action == "users_go":
            timer = int(parts[3]) if len(parts) > 3 else 0
            return await _run_auto(
                client, q, sid, src, kind="users", timer=timer,
            )

        return await q.answer("❓ unknown")

    except Exception as e:
        logger.exception(f"[BC-AUTO] router: {e}")
        try:
            await q.answer(f"❌ {type(e).__name__}", show_alert=True)
        except Exception:
            pass


# ============================================================
# RENDERERS
# ============================================================

async def _show_destination_picker(q: CallbackQuery, sid: str) -> None:
    text = "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"📢 <b>{F.fb('BROADCAST READY')}</b>",
        F.DIV, "",
        f"📌 {F.sc('pick where to send this')}",
        "",
        f"🆔 <code>{sid}</code>",
    ])
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"📢 {F.sc('channels')}",
            callback_data=_cb(f"channels:{sid}"),
        )],
        [InlineKeyboardButton(
            f"👥 {F.sc('groups')}",
            callback_data=_cb(f"groups:{sid}"),
        )],
        [InlineKeyboardButton(
            f"👤 {F.sc('users')}",
            callback_data=_cb(f"users:{sid}"),
        )],
        [InlineKeyboardButton(
            f"❌ {F.sc('cancel')}",
            callback_data=_cb(f"cancel:{sid}"),
        )],
    ])
    await _safe_edit(q, text, kb)
    await q.answer()


async def _show_channel_picker(q: CallbackQuery, sid: str) -> None:
    from plugins.broadcast import channels as CH
    channels = await CH.list_channels()

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"📢 <b>{F.fb('PICK CHANNEL')}</b>",
        F.DIV, "",
    ]

    if not channels:
        lines.append(f"⚪ {F.sc('no channels registered')}")
        lines.append("")
        lines.append(f"📌 {F.sc('use /broadcast → channels to add')}")
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                f"⬅️ {F.sc('back')}",
                callback_data=_cb(f"back:{sid}"),
            ),
        ]])
        await _safe_edit(q, "\n".join(lines), kb)
        return await q.answer()

    enabled = [c for c in channels if c.get("enabled", True)]
    lines.append(f"📊 <b>{len(enabled)}</b> {F.sc('channels')}")
    lines.append("")

    rows: List[List[InlineKeyboardButton]] = []
    for c in enabled:
        cid = c.get("chat_id")
        title = str(c.get("title") or cid)[:30]
        icon = "⭐" if c.get("primary") else "📢"
        rows.append([InlineKeyboardButton(
            f"{icon} {title}",
            callback_data=_cb(f"ch_pick:{sid}:{cid}"),
        )])

    rows.append([InlineKeyboardButton(
        f"⬅️ {F.sc('back')}",
        callback_data=_cb(f"back:{sid}"),
    )])

    await _safe_edit(q, "\n".join(lines), InlineKeyboardMarkup(rows))
    await q.answer()


async def _show_timer_picker(q: CallbackQuery, sid: str) -> None:
    from database import db_registry

    user_count = 0
    try:
        db = db_registry.get_user_db()
        if db is not None:
            user_count = await db["users"].count_documents(
                {"blocked_bot": {"$ne": True}}
            )
    except Exception:
        pass

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"⏱️ <b>{F.fb('AUTO-DELETE TIMER')}</b>",
        F.DIV, "",
        f"👤 {F.sc('target users')} · <b>{FM.num(user_count)}</b>",
        "",
        F.DIV_S,
        f"📌 {F.sc('how long should the message stay')}",
        f"📌 {F.sc('after expiry, messages auto-delete')}",
    ]

    rows = []
    row = []
    for secs, label in TIMER_PRESETS:
        row.append(InlineKeyboardButton(
            label,
            callback_data=_cb(f"users_t:{sid}:{secs}"),
        ))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    rows.append([InlineKeyboardButton(
        f"⬅️ {F.sc('back')}",
        callback_data=_cb(f"back:{sid}"),
    )])

    await _safe_edit(q, "\n".join(lines), InlineKeyboardMarkup(rows))
    await q.answer()


async def _show_confirm(
    q: CallbackQuery, sid: str, kind: str, timer: int,
) -> None:
    from database import db_registry

    count = 0
    try:
        db = db_registry.get_user_db()
        if db is not None:
            if kind == "users":
                count = await db["users"].count_documents(
                    {"blocked_bot": {"$ne": True}}
                )
            else:
                count = await db["groups"].count_documents({})
    except Exception:
        pass

    label = "👤 users" if kind == "users" else "👥 groups"

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"✅ <b>{F.fb('CONFIRM BROADCAST')}</b>",
        F.DIV, "",
        f"🎯 {F.sc('target')} · <b>{label}</b>",
        f"📊 {F.sc('count')} · <b>{FM.num(count)}</b>",
    ]

    if kind == "users":
        lines.append(
            f"⏱️ {F.sc('auto-delete')} · <b>{_fmt_timer(timer)}</b>"
        )

    lines += [
        "",
        F.DIV_S,
        f"📌 {F.sc('using global caption and buttons')}",
    ]

    go_action = f"{kind}_go:{sid}"
    if kind == "users":
        go_action += f":{timer}"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"🚀 {F.sc('yes, start')}",
            callback_data=f"bca:{go_action}",
        )],
        [InlineKeyboardButton(
            f"⬅️ {F.sc('back')}",
            callback_data=_cb(f"back:{sid}"),
        )],
        [InlineKeyboardButton(
            f"❌ {F.sc('cancel')}",
            callback_data=_cb(f"cancel:{sid}"),
        )],
    ])

    await _safe_edit(q, "\n".join(lines), kb)
    await q.answer()


# ============================================================
# EXECUTORS
# ============================================================

async def _run_channel(
    client: Client, q: CallbackQuery,
    sid: str, src: Dict[str, Any], target_chat_id: int,
) -> None:
    from plugins.broadcast import channels as CH

    ch = await CH.get_channel(target_chat_id)
    if not ch:
        return await q.answer("⚠️ channel not found", show_alert=True)

    _SOURCES.pop(sid, None)
    await q.answer("🚀 starting...")

    asyncio.create_task(_do_run(
        client=client,
        panel_chat_id=q.message.chat.id,
        panel_msg_id=q.message.id,
        source_chat_id=src["chat_id"],
        source_msg_id=src["message_id"],
        targets=[int(target_chat_id)],
        kind="channels",
        timer=0,
        caption_override=ch.get("caption"),
        buttons_override=ch.get("buttons"),
    ))


async def _run_auto(
    client: Client, q: CallbackQuery,
    sid: str, src: Dict[str, Any],
    kind: str, timer: int,
) -> None:
    from database import db_registry

    targets: List[int] = []
    try:
        db = db_registry.get_user_db()
        if db is not None:
            if kind == "users":
                cursor = db["users"].find(
                    {"blocked_bot": {"$ne": True}},
                    {"user_id": 1},
                )
                docs = await cursor.to_list(length=100000)
                targets = [
                    int(d["user_id"]) for d in docs if d.get("user_id")
                ]
            else:
                cursor = db["groups"].find({}, {"chat_id": 1})
                docs = await cursor.to_list(length=10000)
                targets = [
                    int(d["chat_id"]) for d in docs if d.get("chat_id")
                ]
    except Exception as e:
        logger.exception(f"[BC-AUTO] targets: {e}")

    if not targets:
        return await q.answer("⚠️ no targets", show_alert=True)

    _SOURCES.pop(sid, None)
    await q.answer(f"🚀 starting · {len(targets)} targets")

    asyncio.create_task(_do_run(
        client=client,
        panel_chat_id=q.message.chat.id,
        panel_msg_id=q.message.id,
        source_chat_id=src["chat_id"],
        source_msg_id=src["message_id"],
        targets=targets,
        kind=kind,
        timer=timer,
        caption_override=None,
        buttons_override=None,
    ))


async def _do_run(
    client: Client,
    panel_chat_id: int,
    panel_msg_id: int,
    source_chat_id: int,
    source_msg_id: int,
    targets: List[int],
    kind: str,
    timer: int,
    caption_override: Optional[str] = None,
    buttons_override: Optional[Any] = None,
) -> None:
    from plugins.broadcast import engine as E

    total = len(targets)
    started = time.time()
    last_edit = {"t": 0.0}

    async def _progress(st: Dict[str, Any]) -> None:
        now = time.time()
        if now - last_edit["t"] < 2.0 and st.get("sent", 0) < total:
            return
        last_edit["t"] = now
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
                f"📢 <b>{F.fb('BROADCAST RUNNING')}</b>",
                F.DIV, "",
                f"🎯 {F.sc('target')} · <b>{kind}</b>",
            ]
            if kind == "users" and timer > 0:
                lines.append(
                    f"⏱️ {F.sc('timer')} · <b>{_fmt_timer(timer)}</b>"
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
            caption_template=caption_override,
            buttons_list=buttons_override,
            autodelete_seconds=timer,
            owner=0,
            progress_cb=_progress,
        )
        elapsed = time.time() - started
        sent = result.get("sent", 0)
        failed = result.get("failed", 0)
        blocked = result.get("blocked", 0)

        lines = [
            f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
            f"✅ <b>{F.fb('BROADCAST DONE')}</b>",
            F.DIV, "",
            f"🎯 {F.sc('target')} · <b>{kind}</b>",
            f"📊 {F.sc('total')} · <b>{FM.num(total)}</b>",
            "",
            f"✅ {F.sc('sent')} · <b>{FM.num(sent)}</b>",
            f"❌ {F.sc('failed')} · <b>{FM.num(failed)}</b>",
            f"🚫 {F.sc('blocked')} · <b>{FM.num(blocked)}</b>",
            "",
            f"⏱️ {F.sc('time')} · <b>{FM.duration_short(elapsed)}</b>",
        ]
        await client.edit_message_text(
            chat_id=panel_chat_id,
            message_id=panel_msg_id,
            text="\n".join(lines),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"❌ {F.sc('close')}",
                    callback_data="bca:done",
                ),
            ]]),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.exception(f"[BC-AUTO] run failed: {e}")
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
# HELPERS
# ============================================================

async def _safe_edit(q: CallbackQuery, text: str, kb) -> None:
    try:
        await q.message.edit_text(
            text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        if "not modified" not in str(e).lower():
            logger.debug(f"[BC-AUTO] edit: {e}")


def snapshot() -> Dict[str, Any]:
    return {
        "watcher_enabled": _CHANNEL_FILTER is not None,
        "sources_active": len(_SOURCES),
    }


__all__ = ["snapshot"]
