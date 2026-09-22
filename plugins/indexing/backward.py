# ============================================================
# 🏨 DOWNTOWN VILLA — CHANNEL AUTO-DETECT + BACKWARD SCAN
# ============================================================
#
# TWO WAYS a channel gets registered:
#
#   1. AUTO:  Bot is added as admin to a channel
#             → ChatMemberUpdated event fires
#             → channel saved to DB
#             → appears in /index picker
#
#   2. MANUAL: User forwards a message from any channel
#              → bot detects the source channel
#              → saves + opens the config flow
#
# STORAGE: SYSTEM DB → indexing_channels
#
# SCHEMA:
#   {
#     "_id": ObjectId,
#     "chat_id": -100xxx,
#     "title": "My Channel",
#     "username": "mychannel",
#     "kind": "auto" | "manual",
#     "enabled": True,
#     "added_by": 123456,
#     "added_at": ISODate,
#     "updated_at": ISODate,
#     "last_seen_at": ISODate,
#   }
#
# ============================================================

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from pyrogram import Client, filters
from pyrogram.enums import ChatType, ChatMemberStatus, ParseMode
from pyrogram.types import (
    CallbackQuery, ChatMemberUpdated, InlineKeyboardButton,
    InlineKeyboardMarkup, Message,
)

from core import config
from utils import fonts as F
from utils import format as FM

logger = logging.getLogger(__name__)


# ============================================================
# SECTION 1 — CONSTANTS
# ============================================================

COLLECTION = "indexing_channels"
PFX = "ich"     # callback prefix for channel manager


# ============================================================
# SECTION 2 — AUTH
# ============================================================

def _is_admin(uid) -> bool:
    try:
        return int(uid) in [int(a) for a in config.ADMINS]
    except Exception:
        return False


# ============================================================
# SECTION 3 — DB
# ============================================================

def _coll():
    try:
        from database import db_registry
        db = db_registry.get_system_db()
        if db is None:
            return None
        return db[COLLECTION]
    except Exception:
        return None


async def register_channel(
    chat_id: int,
    title: str = "",
    username: str = "",
    kind: str = "auto",
    added_by: int = 0,
) -> bool:
    """Save (or refresh) a channel in the registry."""
    c = _coll()
    if c is None:
        return False
    try:
        now = datetime.utcnow()
        await c.update_one(
            {"chat_id": int(chat_id)},
            {
                "$setOnInsert": {
                    "chat_id": int(chat_id),
                    "kind": str(kind),
                    "added_by": int(added_by),
                    "added_at": now,
                    "enabled": True,
                },
                "$set": {
                    "title": str(title)[:120],
                    "username": str(username)[:64] if username else None,
                    "last_seen_at": now,
                    "updated_at": now,
                },
            },
            upsert=True,
        )
        logger.info(
            f"[CH-AUTO] registered chat_id={chat_id} "
            f"title='{title[:40]}' kind={kind}"
        )
        return True
    except Exception as e:
        logger.warning(f"[CH-AUTO] register: {e}")
        return False


async def list_registered_channels() -> List[Dict[str, Any]]:
    """Return every registered channel, newest first."""
    c = _coll()
    if c is None:
        return []
    try:
        cursor = c.find({}).sort("last_seen_at", -1)
        docs = await cursor.to_list(length=200)
        for d in docs:
            d.pop("_id", None)
        return docs
    except Exception as e:
        logger.debug(f"[CH-AUTO] list: {e}")
        return []


async def get_channel(chat_id: int) -> Optional[Dict[str, Any]]:
    c = _coll()
    if c is None:
        return None
    try:
        d = await c.find_one({"chat_id": int(chat_id)})
        if d:
            d.pop("_id", None)
        return d
    except Exception:
        return None


async def unregister_channel(chat_id: int) -> bool:
    c = _coll()
    if c is None:
        return False
    try:
        r = await c.delete_one({"chat_id": int(chat_id)})
        return r.deleted_count > 0
    except Exception:
        return False


async def set_enabled(chat_id: int, enabled: bool) -> bool:
    c = _coll()
    if c is None:
        return False
    try:
        r = await c.update_one(
            {"chat_id": int(chat_id)},
            {"$set": {
                "enabled": bool(enabled),
                "updated_at": datetime.utcnow(),
            }},
        )
        return r.matched_count > 0
    except Exception:
        return False


async def list_enabled_channel_ids() -> List[int]:
    """IDs of channels with enabled=True (used by indexing watcher)."""
    c = _coll()
    if c is None:
        return []
    try:
        cursor = c.find({"enabled": True}, {"chat_id": 1})
        docs = await cursor.to_list(length=500)
        return [int(d["chat_id"]) for d in docs if d.get("chat_id")]
    except Exception:
        return []


# ============================================================
# SECTION 4 — CHAT MEMBER UPDATE (auto-detect)
# ============================================================

@Client.on_chat_member_updated(group=-295)
async def on_chat_member_update(client: Client, update: ChatMemberUpdated):
    """
    Detect when the bot is added/promoted in a channel.
    Register the channel automatically.
    """
    try:
        chat = update.chat
        if chat.type != ChatType.CHANNEL:
            return

        new_member = getattr(update, "new_chat_member", None)
        if not new_member:
            return

        # Is this the bot?
        try:
            me = await client.identity()
        except Exception:
            try:
                me = await client.get_me()
            except Exception:
                return

        user = getattr(new_member, "user", None)
        if not user or getattr(user, "id", None) != me.id:
            return

        status = getattr(new_member, "status", None)
        status_str = (
            status.name.lower() if hasattr(status, "name") else str(status).lower()
        )

        # Only care when promoted/added
        if status_str not in ("administrator", "creator", "owner"):
            # Bot was removed or demoted
            if status_str in ("left", "kicked", "restricted"):
                await set_enabled(chat.id, False)
                logger.info(
                    f"[CH-AUTO] bot removed from {chat.id} — disabled"
                )
            return

        # Register
        registered = await register_channel(
            chat_id=chat.id,
            title=chat.title or "",
            username=chat.username or "",
            kind="auto",
            added_by=0,
        )

        if registered:
            # Optional: notify the log channel
            await _notify_added(client, chat)

    except Exception as e:
        logger.exception(f"[CH-AUTO] member update: {e}")


async def _notify_added(client: Client, chat) -> None:
    """Send a small log message (optional)."""
    try:
        log_ch = getattr(config, "LOG_CHANNEL", 0)
        if not log_ch:
            return
        await client.send_message(
            chat_id=log_ch,
            text="\n".join([
                f"{F.EMO['check']} <b>{F.fb('NEW CHANNEL DETECTED')}</b>",
                F.DIV,
                "",
                f"📢 <b>{F.sc(str(chat.title or '?'))[:60]}</b>",
                f"🆔 <code>{chat.id}</code>",
                "",
                f"📌 {F.sc('channel auto-registered for indexing')}",
                f"📌 {F.sc('open /index to configure')}",
            ]),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception:
        pass


# ============================================================
# SECTION 5 — FORWARD DETECT (manual)
# ============================================================

@Client.on_message(
    filters.private
    & filters.forwarded
    & ~filters.service,
    group=-294,
)
async def detect_forwarded_channel(client: Client, message: Message):
    """
    Detect a forwarded message from a channel.
    Register the source channel + prompt to start.
    """
    try:
        # Only handle forwarded from channels
        fwd_chat = getattr(message, "forward_from_chat", None)
        if not fwd_chat:
            return
        if fwd_chat.type != ChatType.CHANNEL:
            return

        # Only admins
        if not message.from_user or not _is_admin(message.from_user.id):
            return

        channel_id = fwd_chat.id
        title = fwd_chat.title or str(channel_id)
        username = fwd_chat.username or ""

        # Register
        await register_channel(
            chat_id=channel_id,
            title=title,
            username=username,
            kind="manual",
            added_by=message.from_user.id,
        )

        # Show a quick confirmation with a start button
        kb = InlineKeyboardMarkup([
            [
                InlineKeyboardButton(
                    f"{F.EMO['play']} {F.sc('start indexing')}",
                    callback_data=f"idx:start_ch:{channel_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    f"📢 {F.sc('manage channels')}",
                    callback_data=f"idx:databases",
                ),
                InlineKeyboardButton(
                    f"{F.EMO['cross']} {F.sc('dismiss')}",
                    callback_data=f"{PFX}:dismiss",
                ),
            ],
        ])

        await message.reply_text(
            "\n".join([
                f"{F.EMO['check']} <b>{F.fb('CHANNEL DETECTED')}</b>",
                F.DIV,
                "",
                f"📛 <b>{F.sc(title[:60])}</b>",
                f"🆔 <code>{channel_id}</code>",
                *([f"🔗 @{username}"] if username else []),
                "",
                F.DIV_S,
                f"📌 {F.sc('channel registered for indexing')}",
                f"📌 {F.sc('tap start to configure')}",
            ]),
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )

    except Exception as e:
        logger.exception(f"[CH-AUTO] forward detect: {e}")


# ============================================================
# SECTION 6 — CHANNEL MANAGER PANEL (from /index)
# ============================================================

async def open_channel_manager(client: Client, q: CallbackQuery) -> None:
    """Open the channel manager panel (called from /index)."""
    if not q.from_user or not _is_admin(q.from_user.id):
        return await q.answer("❌ Admin only", show_alert=True)

    channels = await list_registered_channels()

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"📢 <b>{F.fb('INDEXING CHANNELS')}</b>",
        F.DIV,
        "",
        f"📊 {F.sc('registered')} · <b>{len(channels)}</b>",
        "",
        F.DIV_S,
        "",
    ]

    if not channels:
        lines.append(f"⚪ {F.sc('no channels yet')}")
        lines.append("")
        lines.append(f"📌 {F.sc('add bot as admin to a channel')}")
        lines.append(f"📌 {F.sc('or forward any message from a channel')}")
    else:
        for i, ch in enumerate(channels, 1):
            icon = "🟢" if ch.get("enabled") else "🔴"
            kind = str(ch.get("kind", "?"))
            kind_icon = {"auto": "🤖", "manual": "👤"}.get(kind, "📌")
            title = str(ch.get("title", "?"))[:40]
            lines.append(
                f"<b>{i:02d}.</b> {icon} {kind_icon} "
                f"<b>{F.sc(title)}</b>"
            )
            lines.append(f"    🆔 <code>{ch.get('chat_id')}</code>")
            lines.append("")

    rows: List[List[InlineKeyboardButton]] = []

    for ch in channels[:8]:
        icon = "🟢" if ch.get("enabled") else "🔴"
        title = str(ch.get("title", "?"))[:28]
        rows.append([InlineKeyboardButton(
            f"{icon} {title}",
            callback_data=f"{PFX}:view:{ch['chat_id']}",
        )])

    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['refresh']} {F.sc('refresh')}",
            callback_data=f"{PFX}:home",
        ),
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data="idx:back",
        ),
    ])
    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('close')}",
            callback_data="idx:close",
        ),
    ])

    try:
        await q.message.edit_text(
            "\n".join(lines)[:4000],
            reply_markup=InlineKeyboardMarkup(rows),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        if "not modified" not in str(e).lower():
            logger.debug(f"[CH-AUTO] edit: {e}")
    await q.answer()


async def view_channel(client: Client, q: CallbackQuery, chat_id: int) -> None:
    """Show a single channel's detail + actions."""
    ch = await get_channel(chat_id)
    if not ch:
        return await q.answer("⚠️ Not found", show_alert=True)

    enabled = ch.get("enabled", True)
    title = str(ch.get("title", "?"))[:60]
    username = ch.get("username") or ""
    kind = str(ch.get("kind", "?"))

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"📢 <b>{F.fb('CHANNEL DETAIL')}</b>",
        F.DIV,
        "",
        f"📛 {F.sc('title')} · <b>{F.sc(title)}</b>",
        f"🆔 {F.sc('chat id')} · <code>{chat_id}</code>",
    ]
    if username:
        lines.append(f"🔗 {F.sc('username')} · <code>@{username}</code>")
    lines += [
        f"🏷️ {F.sc('kind')} · <code>{kind}</code>",
        f"⚙️ {F.sc('status')} · "
        f"{'🟢 ' + F.sc('enabled') if enabled else '🔴 ' + F.sc('disabled')}",
        "",
        F.DIV_S,
    ]

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"{'🔴 ' + F.sc('disable') if enabled else '🟢 ' + F.sc('enable')}",
                callback_data=f"{PFX}:toggle:{chat_id}",
            ),
            InlineKeyboardButton(
                f"{F.EMO['play']} {F.sc('index now')}",
                callback_data=f"idx:start_ch:{chat_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                f"🗑️ {F.sc('remove')}",
                callback_data=f"{PFX}:confirm_rm:{chat_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                f"{F.EMO['back']} {F.sc('back')}",
                callback_data=f"{PFX}:home",
            ),
            InlineKeyboardButton(
                f"{F.EMO['cross']} {F.sc('close')}",
                callback_data="idx:close",
            ),
        ],
    ])

    try:
        await q.message.edit_text(
            "\n".join(lines)[:4000],
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception:
        pass
    await q.answer()


# ============================================================
# SECTION 7 — ROUTER
# ============================================================

@Client.on_callback_query(
    filters.regex(rf"^{PFX}:"),
    group=-295,
)
async def channel_manager_router(client: Client, q: CallbackQuery):
    if not q.from_user or not _is_admin(q.from_user.id):
        return await q.answer("❌ Admin only", show_alert=True)

    parts = str(q.data).split(":")
    action = parts[1] if len(parts) > 1 else ""
    arg = parts[2] if len(parts) > 2 else ""

    try:
        if action == "home":
            return await open_channel_manager(client, q)

        if action == "view":
            try:
                cid = int(arg)
            except ValueError:
                return await q.answer("❌ Invalid", show_alert=True)
            return await view_channel(client, q, cid)

        if action == "toggle":
            try:
                cid = int(arg)
            except ValueError:
                return await q.answer("❌ Invalid", show_alert=True)
            ch = await get_channel(cid)
            if not ch:
                return await q.answer("⚠️ Not found", show_alert=True)
            new_state = not ch.get("enabled", True)
            await set_enabled(cid, new_state)
            await q.answer("🟢 Enabled" if new_state else "🔴 Disabled")
            return await view_channel(client, q, cid)

        if action == "confirm_rm":
            try:
                cid = int(arg)
            except ValueError:
                return await q.answer("❌ Invalid", show_alert=True)
            text = "\n".join([
                f"{F.EMO['warn']} <b>{F.fb('REMOVE CHANNEL?')}</b>",
                F.DIV,
                "",
                f"🆔 <code>{cid}</code>",
                "",
                f"📌 {F.sc('only removes from the registry')}",
                f"📌 {F.sc('the Telegram channel stays intact')}",
            ])
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    f"🗑️ {F.sc('yes, remove')}",
                    callback_data=f"{PFX}:do_rm:{cid}",
                )],
                [InlineKeyboardButton(
                    f"{F.EMO['back']} {F.sc('cancel')}",
                    callback_data=f"{PFX}:view:{cid}",
                )],
            ])
            try:
                await q.message.edit_text(
                    text, reply_markup=kb,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
            except Exception:
                pass
            return await q.answer()

        if action == "do_rm":
            try:
                cid = int(arg)
            except ValueError:
                return await q.answer("❌ Invalid", show_alert=True)
            ok = await unregister_channel(cid)
            await q.answer("🗑️ Removed" if ok else "⚠️ Not found")
            return await open_channel_manager(client, q)

        if action == "dismiss":
            try:
                await q.message.delete()
            except Exception:
                pass
            return await q.answer()

        return await q.answer("❓ Unknown", show_alert=True)

    except Exception as e:
        logger.exception(f"[CH-AUTO] router: {e}")
        try:
            await q.answer(f"❌ {type(e).__name__}", show_alert=True)
        except Exception:
            pass


# ============================================================
# SECTION 8 — SNAPSHOT
# ============================================================

async def snapshot() -> Dict[str, Any]:
    channels = await list_registered_channels()
    enabled = [c for c in channels if c.get("enabled")]
    return {
        "total": len(channels),
        "enabled": len(enabled),
        "channels": channels[:20],
    }


# ============================================================
# PUBLIC EXPORTS
# ============================================================

__all__ = [
    "register_channel",
    "list_registered_channels",
    "get_channel",
    "unregister_channel",
    "set_enabled",
    "list_enabled_channel_ids",
    "open_channel_manager",
    "view_channel",
    "snapshot",
]
