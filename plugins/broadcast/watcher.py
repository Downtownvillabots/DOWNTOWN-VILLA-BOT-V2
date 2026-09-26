# ============================================================
# 🏨 DOWNTOWN VILLA — BROADCAST CHANNEL WATCHER (FULL)
# ============================================================
#
# Upload to BROADCAST_CHANNEL_ID → bot offers:
#   📢 CHANNELS  → [all] or [one specific]  (each uses own caption/buttons)
#   👥 GROUPS    → confirm → all groups      (global caption/buttons)
#   👤 USERS     → timer → confirm → all users (global + auto-delete)
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

# ── Source registry ──
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


# ── Timer presets ──
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


def _is_admin(uid) -> bool:
    try:
        return int(uid) in [int(a) for a in config.ADMINS]
    except Exception:
        return False


# ============================================================
# WATCHER
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

            from plugins.broadcast import channels as CH
            chans = await CH.list_channels()
            chan_count = len([c for c in chans if c.get("enabled", True)])

            text = "\n".join([
                f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                f"📢 <b>{F.fb('BROADCAST READY')}</b>",
                F.DIV, "",
                f"📌 {F.sc('pick where to send this')}",
                "",
                f"📢 {F.sc('channels')} · <b>{chan_count}</b>",
                f"👥 {F.sc('groups')}",
                f"👤 {F.sc('users')}",
                "",
                f"🆔 <code>{sid}</code>",
            ])

            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    f"📢 {F.sc('channels')} ({chan_count})",
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
# ROUTER
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

    # ── Global actions ──
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

    if action == "cancel":
        _SOURCES.pop(sid, None)
        try:
            await q.message.delete()
        except Exception:
            pass
        return await q.answer("❌ cancelled")

    # ── Everything else needs source ──
    src = _get_source(sid)
    if not src:
        return await q.answer(
            "⏱️ source expired — re-upload the file", show_alert=True,
        )

    try:
        if action == "back":
            return await _show_destination_picker(q, sid)

        if action == "channels":
            return await _show_channel_picker(q, sid)

        if action == "ch_pick_one":
            cid = int(parts[3]) if len(parts) > 3 else 0
            return await _run_channel_single(client, q, sid, src, cid)

        if action == "ch_pick_all":
            return await _show_channels_all_confirm(q, sid)

        if action == "ch_all_go":
            return await _run_channels_all(client, q, sid, src)

        if action == "groups":
            return await _show_groups_confirm(q, sid)

        if action == "groups_go":
            return await _run_groups(client, q, sid, src)

        if action == "users":
            return await _show_timer_picker(q, sid)

        if action == "users_t":
            timer = int(parts[3]) if len(parts) > 3 else 0
            return await _show_users_confirm(q, sid, timer)

        if action == "users_go":
            timer = int(parts[3]) if len(parts) > 3 else 0
            return await _run_users(client, q, sid, src, timer)

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
    from plugins.broadcast import channels as CH
    chans = await CH.list_channels()
    chan_count = len([c for c in chans if c.get("enabled", True)])

    text = "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"📢 <b>{F.fb('BROADCAST READY')}</b>",
        F.DIV, "",
        f"📌 {F.sc('pick where to send this')}",
        "",
        f"📢 {F.sc('channels')} · <b>{chan_count}</b>",
        "",
        f"🆔 <code>{sid}</code>",
    ])
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"📢 {F.sc('channels')} ({chan_count})",
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

    enabled = [c for c in channels if c.get("enabled", True)]

    if not enabled:
        lines.append(f"⚪ {F.sc('no channels registered')}")
        lines.append("")
        lines.append(f"📌 {F.sc('use /broadcast to add')}")
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                f"⬅️ {F.sc('back')}",
                callback_data=_cb(f"back:{sid}"),
            ),
        ]])
        return await _safe_edit(q, "\n".join(lines), kb) or await q.answer()

    lines += [
        f"📊 <b>{len(enabled)}</b> {F.sc('channels')}",
        "",
        f"📌 {F.sc('send to all or pick one')}",
        f"📌 {F.sc('each channel uses its own caption if set')}",
        "",
    ]

    rows: List[List[InlineKeyboardButton]] = []

    # ── SEND TO ALL ──
    rows.append([InlineKeyboardButton(
        f"🎯 {F.sc('SEND TO ALL')} ({len(enabled)})",
        callback_data=_cb(f"ch_pick_all:{sid}"),
    )])

    # ── Individual channels ──
    for c in enabled:
        cid = c.get("chat_id")
        title = str(c.get("title") or cid)[:28]
        markers = ""
        if c.get("caption") is not None:
            markers += "📝"
        if c.get("buttons") is not None:
            markers += "🔘"
        if c.get("primary"):
            markers = "⭐" + markers
        prefix = f"{markers} " if markers else ""
        rows.append([InlineKeyboardButton(
            f"{prefix}{title}",
            callback_data=_cb(f"ch_pick_one:{sid}:{cid}"),
        )])

    rows.append([InlineKeyboardButton(
        f"⬅️ {F.sc('back')}",
        callback_data=_cb(f"back:{sid}"),
    )])

    await _safe_edit(q, "\n".join(lines), InlineKeyboardMarkup(rows))
    await q.answer()


async def _show_channels_all_confirm(q: CallbackQuery, sid: str) -> None:
    from plugins.broadcast import channels as CH
    channels = await CH.list_channels()
    enabled = [c for c in channels if c.get("enabled", True)]

    custom_cap = sum(1 for c in enabled if c.get("caption") is not None)
    custom_btn = sum(1 for c in enabled if c.get("buttons") is not None)

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"🎯 <b>{F.fb('SEND TO ALL CHANNELS')}</b>",
        F.DIV, "",
        f"📊 {F.sc('total')} · <b>{len(enabled)}</b>",
        "",
        F.DIV_S,
        f"📝 {F.sc('custom captions')} · <b>{custom_cap}</b>",
        f"🔘 {F.sc('custom buttons')} · <b>{custom_btn}</b>",
        "",
        f"📌 {F.sc('each channel gets its own caption if set')}",
        f"📌 {F.sc('others use global default')}",
    ]

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"🚀 {F.sc('yes, start')}",
            callback_data=_cb(f"ch_all_go:{sid}"),
        )],
        [InlineKeyboardButton(
            f"⬅️ {F.sc('back')}",
            callback_data=_cb(f"channels:{sid}"),
        )],
        [InlineKeyboardButton(
            f"❌ {F.sc('cancel')}",
            callback_data=_cb(f"cancel:{sid}"),
        )],
    ])
    await _safe_edit(q, "\n".join(lines), kb)
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


async def _show_users_confirm(q: CallbackQuery, sid: str, timer: int) -> None:
    from database import db_registry
    count = 0
    try:
        db = db_registry.get_user_db()
        if db is not None:
            count = await db["users"].count_documents(
                {"blocked_bot": {"$ne": True}}
            )
    except Exception:
        pass

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"✅ <b>{F.fb('CONFIRM USER BROADCAST')}</b>",
        F.DIV, "",
        f"👤 {F.sc('target')} · <b>{FM.num(count)}</b> users",
        f"⏱️ {F.sc('auto-delete')} · <b>{_fmt_timer(timer)}</b>",
        "",
        F.DIV_S,
        f"📌 {F.sc('uses global caption and buttons')}",
    ]

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"🚀 {F.sc('yes, start')}",
            callback_data=_cb(f"users_go:{sid}:{timer}"),
        )],
        [InlineKeyboardButton(
            f"⬅️ {F.sc('change timer')}",
            callback_data=_cb(f"users:{sid}"),
        )],
        [InlineKeyboardButton(
            f"❌ {F.sc('cancel')}",
            callback_data=_cb(f"cancel:{sid}"),
        )],
    ])
    await _safe_edit(q, "\n".join(lines), kb)
    await q.answer()


async def _show_groups_confirm(q: CallbackQuery, sid: str) -> None:
    from database import db_registry
    count = 0
    try:
        db = db_registry.get_user_db()
        if db is not None:
            count = await db["groups"].count_documents({})
    except Exception:
        pass

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"✅ <b>{F.fb('CONFIRM GROUP BROADCAST')}</b>",
        F.DIV, "",
        f"👥 {F.sc('target')} · <b>{FM.num(count)}</b> groups",
        "",
        F.DIV_S,
        f"📌 {F.sc('uses global caption and buttons')}",
    ]

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"🚀 {F.sc('yes, start')}",
            callback_data=_cb(f"groups_go:{sid}"),
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

async def _run_channel_single(
    client: Client, q: CallbackQuery,
    sid: str, src: Dict[str, Any], target_chat_id: int,
) -> None:
    from plugins.broadcast import channels as CH

    ch = await CH.get_channel(target_chat_id)
    if not ch:
        return await q.answer("⚠️ channel not found", show_alert=True)

    cap = await CH.effective_caption(target_chat_id)
    btns = await CH.effective_buttons(target_chat_id)

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
        caption_template=cap,
        buttons_list=btns,
    ))


async def _run_channels_all(
    client: Client, q: CallbackQuery,
    sid: str, src: Dict[str, Any],
) -> None:
    """
    Send to every enabled channel — each with its own caption.
    engine.run_broadcast doesn't support per-target caption, so we
    loop manually and call copy_message per channel.
    """
    from plugins.broadcast import channels as CH

    channels = await CH.list_channels()
    enabled = [c for c in channels if c.get("enabled", True)]

    if not enabled:
        return await q.answer("⚠️ no channels", show_alert=True)

    _SOURCES.pop(sid, None)
    await q.answer(f"🚀 starting · {len(enabled)} channels")

    asyncio.create_task(_do_channels_all(
        client=client,
        panel_chat_id=q.message.chat.id,
        panel_msg_id=q.message.id,
        source_chat_id=src["chat_id"],
        source_msg_id=src["message_id"],
        channels=enabled,
    ))


async def _run_groups(
    client: Client, q: CallbackQuery,
    sid: str, src: Dict[str, Any],
) -> None:
    from database import db_registry
    from plugins.broadcast import templates as T

    targets: List[int] = []
    try:
        db = db_registry.get_user_db()
        if db is not None:
            cursor = db["groups"].find({}, {"chat_id": 1})
            docs = await cursor.to_list(length=10000)
            targets = [int(d["chat_id"]) for d in docs if d.get("chat_id")]
    except Exception as e:
        logger.exception(f"[BC-AUTO] groups: {e}")

    if not targets:
        return await q.answer("⚠️ no groups", show_alert=True)

    _SOURCES.pop(sid, None)
    await q.answer(f"🚀 starting · {len(targets)} groups")

    cap = await T.get_caption()
    btns = await T.get_buttons()

    asyncio.create_task(_do_run(
        client=client,
        panel_chat_id=q.message.chat.id,
        panel_msg_id=q.message.id,
        source_chat_id=src["chat_id"],
        source_msg_id=src["message_id"],
        targets=targets,
        kind="groups",
        timer=0,
        caption_template=cap,
        buttons_list=btns,
    ))


async def _run_users(
    client: Client, q: CallbackQuery,
    sid: str, src: Dict[str, Any], timer: int,
) -> None:
    from database import db_registry
    from plugins.broadcast import templates as T

    targets: List[int] = []
    try:
        db = db_registry.get_user_db()
        if db is not None:
            cursor = db["users"].find(
                {"blocked_bot": {"$ne": True}},
                {"user_id": 1},
            )
            docs = await cursor.to_list(length=100000)
            targets = [
                int(d["user_id"]) for d in docs if d.get("user_id")
            ]
    except Exception as e:
        logger.exception(f"[BC-AUTO] users: {e}")

    if not targets:
        return await q.answer("⚠️ no users", show_alert=True)

    _SOURCES.pop(sid, None)
    await q.answer(f"🚀 starting · {len(targets)} users")

    cap = await T.get_caption()
    btns = await T.get_buttons()

    asyncio.create_task(_do_run(
        client=client,
        panel_chat_id=q.message.chat.id,
        panel_msg_id=q.message.id,
        source_chat_id=src["chat_id"],
        source_msg_id=src["message_id"],
        targets=targets,
        kind="users",
        timer=timer,
        caption_template=cap,
        buttons_list=btns,
    ))


# ============================================================
# RUNNERS
# ============================================================

async def _do_run(
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
    """Standard flow — one caption for all targets."""
    from plugins.broadcast import engine as E

    total = len(targets)
    started = time.time()
    last_edit = {"t": 0.0}

    async def _progress(st: Dict[str, Any]) -> None:
        now = time.time()
        if now - last_edit["t"] < 2.0:
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
            caption_template=caption_template,
            buttons_list=buttons_list,
            autodelete_seconds=timer,
            owner=0,
            progress_cb=_progress,
        )

        elapsed = time.time() - started
        await _render_done(
            client, panel_chat_id, panel_msg_id,
            kind=kind, total=total, result=result, elapsed=elapsed, timer=timer,
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


async def _do_channels_all(
    client: Client,
    panel_chat_id: int,
    panel_msg_id: int,
    source_chat_id: int,
    source_msg_id: int,
    channels: List[Dict[str, Any]],
) -> None:
    """
    Send to all channels — each uses its own caption/buttons.
    Runs sequentially so per-channel config works cleanly.
    """
    from plugins.broadcast import templates as T
    from pyrogram.errors import FloodWait

    total = len(channels)
    started = time.time()
    sent = 0
    failed = 0

    # Load the source message once
    try:
        src_msg = await client.get_messages(source_chat_id, source_msg_id)
        if not src_msg or src_msg.empty:
            raise RuntimeError("source gone")
    except Exception as e:
        await client.edit_message_text(
            chat_id=panel_chat_id, message_id=panel_msg_id,
            text=f"❌ {F.sc('source fetch failed')}: <code>{e}</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    # Global fallbacks
    global_cap = await T.get_caption()
    global_btns = await T.get_buttons()

    for i, ch in enumerate(channels):
        if not ch.get("enabled", True):
            continue

        cid = ch.get("chat_id")
        custom_cap = ch.get("caption")
        custom_btns = ch.get("buttons")

        cap_tpl = custom_cap if custom_cap is not None else global_cap
        btns = custom_btns if custom_btns is not None else global_btns

        caption = T.build_caption(src_msg, cap_tpl)
        kb = T.build_buttons_kb(btns)

        try:
            await client.copy_message(
                chat_id=int(cid),
                from_chat_id=source_chat_id,
                message_id=source_msg_id,
                caption=caption,
                reply_markup=kb,
            )
            sent += 1
        except FloodWait as e:
            await asyncio.sleep(int(e.value) + 2)
            try:
                await client.copy_message(
                    chat_id=int(cid),
                    from_chat_id=source_chat_id,
                    message_id=source_msg_id,
                    caption=caption,
                    reply_markup=kb,
                )
                sent += 1
            except Exception:
                failed += 1
        except Exception as e:
            logger.debug(f"[BC-AUTO] ch {cid}: {e}")
            failed += 1

        # Progress
        try:
            done = sent + failed
            pct = (done / total * 100) if total else 0
            bar = P.bar(pct, "indexing", width=14)
            await client.edit_message_text(
                chat_id=panel_chat_id,
                message_id=panel_msg_id,
                text="\n".join([
                    f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                    f"📢 <b>{F.fb('SENDING TO ALL CHANNELS')}</b>",
                    F.DIV, "",
                    f"<code>{bar}</code>",
                    "",
                    f"✅ {F.sc('sent')} · <b>{sent}</b>",
                    f"❌ {F.sc('failed')} · <b>{failed}</b>",
                    "",
                    f"📊 <code>{done}/{total}</code>",
                    f"📢 {F.sc('now')} · <code>{str(ch.get('title','?'))[:30]}</code>",
                ]),
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
        kind="channels (all)", total=total,
        result={"sent": sent, "failed": failed,
                "blocked": 0, "total": total},
        elapsed=elapsed, timer=0,
    )


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
        f"✅ <b>{F.fb('BROADCAST DONE')}</b>",
        F.DIV, "",
        f"🎯 {F.sc('target')} · <b>{kind}</b>",
        f"📊 {F.sc('total')} · <b>{FM.num(total)}</b>",
        "",
        f"✅ {F.sc('sent')} · <b>{FM.num(sent)}</b>",
        f"❌ {F.sc('failed')} · <b>{FM.num(failed)}</b>",
        f"🚫 {F.sc('blocked')} · <b>{FM.num(blocked)}</b>",
    ]
    if kind == "users" and timer > 0:
        lines.append("")
        lines.append(f"⏱️ {F.sc('auto-delete')} · <b>{_fmt_timer(timer)}</b>")

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
                    callback_data="bca:done",
                ),
            ]]),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
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
