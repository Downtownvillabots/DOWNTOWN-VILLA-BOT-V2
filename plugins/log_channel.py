# ============================================================
# 🏨 DOWNTOWN VILLA — UNIFIED LOG CHANNEL
# ============================================================
#
# Every major event → sent to LOG_CHANNEL.
#
# Events logged:
#   • Bot started / restarted / stopped
#   • NEW USER (first /start)
#   • NEW GROUP (bot added)
#   • NEW CHANNEL (bot added as admin)
#   • Channel removed (bot kicked)
#   • Backup: started / completed / failed
#   • Indexing: started / completed / failed
#   • Broadcast: started / completed
#   • Premium user: added / expired
#   • Search request (from group or PM)
#   • Request channel actions
#   • Errors / warnings (optional)
#
# Format: clean header + structured info.
#
# Public API (call from anywhere):
#   await log_event("user", ...)
#   await log_new_user(...)
#   await log_new_group(...)
#   await log_new_channel(...)
#   await log_backup_started(...)
#   ...
#
# ============================================================

from __future__ import annotations
import asyncio
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from pyrogram import Client, filters
from pyrogram.enums import ChatType, ParseMode
from pyrogram.errors import FloodWait
from pyrogram.types import (
    ChatMemberUpdated, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from core import config
from utils import fonts as F
from utils import format as FM

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

_bot: Optional[Client] = None
_channel_id: Optional[int] = None
_initialized = False


# ============================================================
# INIT
# ============================================================

def set_bot(client: Client) -> None:
    global _bot
    _bot = client


def _get_channel_id() -> Optional[int]:
    global _channel_id
    if _channel_id is not None:
        return _channel_id if _channel_id != 0 else None

    raw = getattr(config, "LOG_CHANNEL", 0)
    try:
        if isinstance(raw, int) and raw != 0:
            _channel_id = raw
        elif isinstance(raw, str) and raw.strip():
            _channel_id = int(raw.strip())
        else:
            _channel_id = 0
    except (TypeError, ValueError):
        _channel_id = 0

    return _channel_id if _channel_id else None


# ============================================================
# LOW-LEVEL SEND
# ============================================================

async def _send(text: str,
                kb: Optional[InlineKeyboardMarkup] = None,
                photo: Optional[str] = None) -> bool:
    """Send a log entry. Never raises."""
    if not _bot:
        return False
    ch = _get_channel_id()
    if not ch:
        return False

    try:
        if photo:
            await _bot.send_photo(
                chat_id=ch,
                photo=photo,
                caption=text,
                reply_markup=kb,
                parse_mode=ParseMode.HTML,
            )
        else:
            await _bot.send_message(
                chat_id=ch,
                text=text,
                reply_markup=kb,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        return True
    except FloodWait as e:
        await asyncio.sleep(e.value + 2)
        try:
            await _bot.send_message(
                chat_id=ch,
                text=text,
                reply_markup=kb,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
            return True
        except Exception:
            return False
    except Exception as e:
        logger.debug(f"[LOG] send failed: {e}")
        return False


def _header(icon: str, title: str) -> str:
    return "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"{icon} <b>{F.fb(title)}</b>",
        F.DIV,
    ])


def _foot() -> str:
    return f"\n🕒 <code>{FM.datetime_()}</code>"


# ============================================================
# LIFECYCLE
# ============================================================

async def bot_started() -> bool:
    return await _send("\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"{F.EMO['rocket']} <b>{F.fb('BOT STARTED')}</b>",
        F.DIV, "",
        f"{F.EMO['check']} {F.sc('status')} · 🟢 <b>ONLINE</b>",
        f"{F.EMO['clock']} <code>{FM.datetime_()}</code>",
        "",
        f"{F.EMO['spark']} <i>{F.sc('all systems ready')}</i>",
    ]))


async def bot_restarted() -> bool:
    return await _send("\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"{F.EMO['refresh']} <b>{F.fb('BOT RESTARTED')}</b>",
        F.DIV, "",
        f"{F.EMO['check']} {F.sc('status')} · 🟢 <b>ONLINE</b>",
        f"{F.EMO['clock']} <code>{FM.datetime_()}</code>",
    ]))


async def bot_stopped() -> bool:
    return await _send("\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"{F.EMO['stop']} <b>{F.fb('BOT STOPPED')}</b>",
        F.DIV, "",
        f"{F.EMO['clock']} <code>{FM.datetime_()}</code>",
    ]))


# ============================================================
# USER EVENTS
# ============================================================

async def log_new_user(
    user_id: int,
    username: str = "",
    first_name: str = "",
    last_name: str = "",
    language_code: str = "",
    is_premium: bool = False,
    via_link: bool = False,
) -> bool:
    """Log a new user's first /start."""
    display_name = f"{first_name} {last_name}".strip() or "user"
    uname = f"@{username}" if username else "—"

    lines = [
        _header("🆕", "NEW USER"),
        "",
        f"{F.EMO['user']} {F.sc('name')} · <b>{F.sc(display_name)}</b>",
        f"{F.EMO['info']} {F.sc('username')} · <code>{uname}</code>",
        f"{F.EMO['id']} {F.sc('id')} · <code>{user_id}</code>",
        f"{F.EMO['spark']} {F.sc('lang')} · <code>{language_code or '?'}</code>",
        f"{F.EMO['crown']} {F.sc('premium')} · "
        f"{'🟢 yes' if is_premium else '⚪ no'}",
    ]
    if via_link:
        lines.append(f"{F.EMO['rocket']} {F.sc('via')} · <b>referral link</b>")

    lines.append(_foot())

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            f"👤 {F.sc('view profile')}",
            url=f"tg://user?id={user_id}",
        ),
    ]])

    return await _send("\n".join(lines), kb)


async def log_user_blocked(user_id: int, username: str = "") -> bool:
    """Log when a user blocks the bot."""
    uname = f"@{username}" if username else "—"
    return await _send("\n".join([
        _header("🚫", "USER BLOCKED BOT"),
        "",
        f"{F.EMO['user']} {F.sc('username')} · <code>{uname}</code>",
        f"{F.EMO['id']} {F.sc('id')} · <code>{user_id}</code>",
        "",
        f"{F.EMO['info']} <i>{F.sc('soft-flagged')}</i>",
        _foot(),
    ]))


# ============================================================
# GROUP EVENTS
# ============================================================

async def log_new_group(
    chat_id: int,
    title: str,
    username: str = "",
    member_count: int = 0,
    added_by_id: int = 0,
    added_by_name: str = "",
) -> bool:
    """Log when the bot is added to a group."""
    uname = f"@{username}" if username else "—"
    lines = [
        _header("🆕", "NEW GROUP"),
        "",
        f"{F.EMO['group']} {F.sc('title')} · <b>{F.sc(str(title)[:60])}</b>",
        f"{F.EMO['id']} {F.sc('id')} · <code>{chat_id}</code>",
        f"{F.EMO['info']} {F.sc('username')} · <code>{uname}</code>",
    ]
    if member_count:
        lines.append(
            f"{F.EMO['users']} {F.sc('members')} · "
            f"<b>{FM.num(member_count)}</b>"
        )
    if added_by_id:
        lines.append(
            f"{F.EMO['user']} {F.sc('added by')} · "
            f"<a href='tg://user?id={added_by_id}'>"
            f"{F.sc(added_by_name or str(added_by_id))}</a>"
        )
        lines.append(f"   🆔 <code>{added_by_id}</code>")

    lines.append(_foot())

    return await _send("\n".join(lines))


async def log_group_left(chat_id: int, title: str = "") -> bool:
    """Log when the bot is removed from a group."""
    return await _send("\n".join([
        _header("👋", "GROUP LEFT"),
        "",
        f"{F.EMO['group']} {F.sc('title')} · <b>{F.sc(str(title)[:60])}</b>",
        f"{F.EMO['id']} {F.sc('id')} · <code>{chat_id}</code>",
        "",
        f"{F.EMO['info']} <i>{F.sc('bot was removed')}</i>",
        _foot(),
    ]))


# ============================================================
# CHANNEL EVENTS
# ============================================================

async def log_new_channel(
    chat_id: int,
    title: str,
    username: str = "",
    added_by_id: int = 0,
    added_by_name: str = "",
) -> bool:
    """Log when the bot is added as admin to a channel."""
    uname = f"@{username}" if username else "—"
    lines = [
        _header("🆕", "NEW CHANNEL"),
        "",
        f"{F.EMO['channel']} {F.sc('title')} · <b>{F.sc(str(title)[:60])}</b>",
        f"{F.EMO['id']} {F.sc('id')} · <code>{chat_id}</code>",
        f"{F.EMO['info']} {F.sc('username')} · <code>{uname}</code>",
    ]
    if added_by_id:
        lines.append(
            f"{F.EMO['user']} {F.sc('added by')} · "
            f"<a href='tg://user?id={added_by_id}'>"
            f"{F.sc(added_by_name or str(added_by_id))}</a>"
        )
    lines += [
        "",
        f"{F.EMO['check']} <i>{F.sc('auto-registered for indexing')}</i>",
        _foot(),
    ]
    return await _send("\n".join(lines))


async def log_channel_removed(chat_id: int, title: str = "") -> bool:
    """Log when bot loses admin/access to a channel."""
    return await _send("\n".join([
        _header("🚫", "CHANNEL REMOVED"),
        "",
        f"{F.EMO['channel']} {F.sc('title')} · <b>{F.sc(str(title)[:60])}</b>",
        f"{F.EMO['id']} {F.sc('id')} · <code>{chat_id}</code>",
        "",
        f"{F.EMO['info']} <i>{F.sc('bot removed from channel')}</i>",
        _foot(),
    ]))


# ============================================================
# BACKUP EVENTS
# ============================================================

async def log_backup_started(
    owner_id: int = 0,
    channel: Optional[int] = None,
    total: int = 0,
) -> bool:
    lines = [
        _header("💾", "BACKUP STARTED"),
        "",
        f"{F.EMO['channel']} {F.sc('channel')} · "
        f"<code>{channel or '?'}</code>",
        f"{F.EMO['package']} {F.sc('total files')} · "
        f"<b>{FM.num(total)}</b>",
    ]
    if owner_id:
        lines.append(f"{F.EMO['user']} {F.sc('by')} · <code>{owner_id}</code>")
    lines.append(_foot())
    return await _send("\n".join(lines))


async def log_backup_completed(
    uploaded: int = 0,
    failed: int = 0,
    skipped: int = 0,
    duration: str = "?",
) -> bool:
    return await _send("\n".join([
        _header("✅", "BACKUP COMPLETED"),
        "",
        f"{F.EMO['check']} {F.sc('uploaded')} · "
        f"<b>{FM.num(uploaded)}</b>",
        f"{F.EMO['cross']} {F.sc('failed')} · "
        f"<b>{FM.num(failed)}</b>",
        f"⏭️ {F.sc('skipped')} · <b>{FM.num(skipped)}</b>",
        f"⏱️ {F.sc('took')} · <b>{duration}</b>",
        _foot(),
    ]))


async def log_backup_failed(reason: str = "") -> bool:
    return await _send("\n".join([
        _header("❌", "BACKUP FAILED"),
        "",
        f"{F.EMO['warn']} <code>{F.sc(str(reason)[:200])}</code>",
        _foot(),
    ]))


# ============================================================
# INDEXING EVENTS
# ============================================================

async def log_indexing_started(
    channel_id: int = 0,
    channel_title: str = "",
    mode: str = "both",
    direction: str = "backward",
    range_mode: str = "last",
    metadata_source: str = "both",
) -> bool:
    return await _send("\n".join([
        _header("📚", "INDEXING STARTED"),
        "",
        f"{F.EMO['channel']} {F.sc('channel')} · "
        f"<b>{F.sc(str(channel_title)[:60])}</b>",
        f"{F.EMO['id']} <code>{channel_id}</code>",
        "",
        f"🎬 {F.sc('mode')} · <b>{mode}</b>",
        f"⬇️ {F.sc('direction')} · <b>{direction}</b>",
        f"📍 {F.sc('range')} · <b>{range_mode}</b>",
        f"📄 {F.sc('metadata')} · <b>{metadata_source}</b>",
        _foot(),
    ]))


async def log_indexing_completed(
    channel_title: str = "",
    saved: int = 0,
    duplicate: int = 0,
    failed: int = 0,
    movies: int = 0,
    series: int = 0,
    duration: str = "?",
) -> bool:
    return await _send("\n".join([
        _header("✅", "INDEXING COMPLETED"),
        "",
        f"{F.EMO['channel']} <b>{F.sc(str(channel_title)[:50])}</b>",
        "",
        f"{F.EMO['check']} {F.sc('saved')} · <b>{FM.num(saved)}</b>",
        f"⏭️ {F.sc('duplicates')} · <b>{FM.num(duplicate)}</b>",
        f"{F.EMO['cross']} {F.sc('failed')} · <b>{FM.num(failed)}</b>",
        "",
        f"🎬 {F.sc('movies')} · <b>{FM.num(movies)}</b>",
        f"📺 {F.sc('series')} · <b>{FM.num(series)}</b>",
        f"⏱️ {F.sc('took')} · <b>{duration}</b>",
        _foot(),
    ]))


async def log_indexing_failed(reason: str = "") -> bool:
    return await _send("\n".join([
        _header("❌", "INDEXING FAILED"),
        "",
        f"{F.EMO['warn']} <code>{F.sc(str(reason)[:200])}</code>",
        _foot(),
    ]))


# ============================================================
# BROADCAST EVENTS
# ============================================================

async def log_broadcast_started(
    kind: str = "?",
    total: int = 0,
    owner_id: int = 0,
) -> bool:
    return await _send("\n".join([
        _header("📢", "BROADCAST STARTED"),
        "",
        f"🎯 {F.sc('target')} · <b>{kind.upper()}</b>",
        f"📊 {F.sc('total')} · <b>{FM.num(total)}</b>",
    ] + (
        [f"{F.EMO['user']} {F.sc('by')} · <code>{owner_id}</code>"]
        if owner_id else []
    ) + [_foot()]))


async def log_broadcast_completed(
    sent: int = 0,
    failed: int = 0,
    blocked: int = 0,
    duration: str = "?",
) -> bool:
    return await _send("\n".join([
        _header("✅", "BROADCAST COMPLETED"),
        "",
        f"{F.EMO['check']} {F.sc('sent')} · <b>{FM.num(sent)}</b>",
        f"{F.EMO['cross']} {F.sc('failed')} · <b>{FM.num(failed)}</b>",
        f"🚫 {F.sc('blocked')} · <b>{FM.num(blocked)}</b>",
        f"⏱️ {F.sc('took')} · <b>{duration}</b>",
        _foot(),
    ]))


# ============================================================
# PREMIUM EVENTS
# ============================================================

async def log_premium_added(
    user_id: int,
    username: str = "",
    months: int = 1,
    added_by: int = 0,
    expires_at: Optional[float] = None,
) -> bool:
    uname = f"@{username}" if username else "—"
    exp = ""
    if expires_at:
        try:
            exp = datetime.fromtimestamp(expires_at, IST).strftime("%d %b %Y")
        except Exception:
            exp = "?"
    return await _send("\n".join([
        _header("👑", "PREMIUM ADDED"),
        "",
        f"{F.EMO['user']} {F.sc('username')} · <code>{uname}</code>",
        f"{F.EMO['id']} {F.sc('id')} · <code>{user_id}</code>",
        f"{F.EMO['crown']} {F.sc('plan')} · <b>{months} months</b>",
        f"{F.EMO['cal']} {F.sc('expires')} · <code>{exp}</code>",
    ] + (
        [f"{F.EMO['user']} {F.sc('added by')} · <code>{added_by}</code>"]
        if added_by else []
    ) + [_foot()]))


async def log_premium_removed(user_id: int, username: str = "") -> bool:
    uname = f"@{username}" if username else "—"
    return await _send("\n".join([
        _header("❌", "PREMIUM REMOVED"),
        "",
        f"{F.EMO['user']} {F.sc('username')} · <code>{uname}</code>",
        f"{F.EMO['id']} {F.sc('id')} · <code>{user_id}</code>",
        _foot(),
    ]))


async def log_premium_expired(user_id: int, username: str = "") -> bool:
    uname = f"@{username}" if username else "—"
    return await _send("\n".join([
        _header("⏰", "PREMIUM EXPIRED"),
        "",
        f"{F.EMO['user']} {F.sc('username')} · <code>{uname}</code>",
        f"{F.EMO['id']} {F.sc('id')} · <code>{user_id}</code>",
        "",
        f"{F.EMO['info']} <i>{F.sc('30-day grace period started')}</i>",
        _foot(),
    ]))


# ============================================================
# REQUEST EVENTS
# ============================================================

async def log_request(
    user_id: int,
    movie_name: str,
    kind: str = "movie",
    imdb_id: Optional[str] = None,
) -> bool:
    is_series = kind == "series"
    icon = "📺" if is_series else "🎬"
    return await _send("\n".join([
        _header(icon, f"NEW {kind.upper()} REQUEST"),
        "",
        f"{icon} <b>{F.sc(str(movie_name)[:60])}</b>",
    ] + (
        [f"{F.EMO['id']} ɪᴍᴅʙ · <code>{imdb_id}</code>"]
        if imdb_id else []
    ) + [
        "",
        f"{F.EMO['user']} {F.sc('user id')} · <code>{user_id}</code>",
        _foot(),
    ]))


# ============================================================
# GENERIC EVENT
# ============================================================

async def log_event(
    icon: str,
    title: str,
    lines: List[str] = None,
    kb: Optional[InlineKeyboardMarkup] = None,
) -> bool:
    """Custom event logger."""
    body = [
        _header(icon, title),
        "",
    ]
    if lines:
        body.extend(lines)
    body.append(_foot())
    return await _send("\n".join(body), kb)


# ============================================================
# AUTO HOOKS (fires on events)
# ============================================================

# ── NEW USER (first /start) ──
@Client.on_message(filters.command("start") & filters.private, group=-9999)
async def _hook_new_user(client: Client, message: Message):
    try:
        global _bot
        if _bot is None:
            _bot = client

        if not message.from_user:
            return

        # Check if user is new (query DB)
        try:
            from database import db_registry
            db = db_registry.get_user_db()
            if db is None:
                return
            uid = message.from_user.id
            existing = await db["users"].find_one({"user_id": uid})
            # Only log if truly new
            if not existing:
                await log_new_user(
                    user_id=uid,
                    username=message.from_user.username or "",
                    first_name=message.from_user.first_name or "",
                    last_name=message.from_user.last_name or "",
                    language_code=message.from_user.language_code or "",
                    is_premium=bool(getattr(message.from_user, "is_premium", False)),
                    via_link=bool(
                        message.command and len(message.command) > 1
                        and message.command[1].startswith("ref_")
                    ),
                )
        except Exception:
            pass
    except Exception as e:
        logger.debug(f"[LOG] new user hook: {e}")


# ── NEW GROUP / NEW CHANNEL (chat member updated) ──
@Client.on_chat_member_updated(group=-9998)
async def _hook_member_update(client: Client, update: ChatMemberUpdated):
    try:
        global _bot
        if _bot is None:
            _bot = client

        chat = update.chat
        new_member = getattr(update, "new_chat_member", None)
        old_member = getattr(update, "old_chat_member", None)
        if not new_member:
            return

        # Was this the bot?
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
            status.name.lower() if hasattr(status, "name")
            else str(status).lower()
        )

        old_status = None
        if old_member:
            os_ = getattr(old_member, "status", None)
            old_status = (
                os_.name.lower() if hasattr(os_, "name")
                else str(os_).lower()
            )

        # Added/joined
        if status_str in ("administrator", "creator", "owner", "member"):
            if old_status in (None, "left", "kicked", "banned"):
                # Just joined
                if chat.type == ChatType.CHANNEL:
                    await log_new_channel(
                        chat_id=chat.id,
                        title=chat.title or str(chat.id),
                        username=chat.username or "",
                        added_by_id=update.from_user.id if update.from_user else 0,
                        added_by_name=(
                            update.from_user.first_name
                            if update.from_user else ""
                        ),
                    )
                elif chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
                    member_count = 0
                    try:
                        member_count = await client.get_chat_members_count(chat.id)
                    except Exception:
                        pass
                    await log_new_group(
                        chat_id=chat.id,
                        title=chat.title or str(chat.id),
                        username=chat.username or "",
                        member_count=member_count,
                        added_by_id=update.from_user.id if update.from_user else 0,
                        added_by_name=(
                            update.from_user.first_name
                            if update.from_user else ""
                        ),
                    )

        # Removed
        elif status_str in ("left", "kicked", "banned"):
            if chat.type == ChatType.CHANNEL:
                await log_channel_removed(chat.id, chat.title or "")
            elif chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
                await log_group_left(chat.id, chat.title or "")

    except Exception as e:
        logger.debug(f"[LOG] member update hook: {e}")


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    "set_bot",
    "bot_started", "bot_restarted", "bot_stopped",
    "log_new_user", "log_user_blocked",
    "log_new_group", "log_group_left",
    "log_new_channel", "log_channel_removed",
    "log_backup_started", "log_backup_completed", "log_backup_failed",
    "log_indexing_started", "log_indexing_completed", "log_indexing_failed",
    "log_broadcast_started", "log_broadcast_completed",
    "log_premium_added", "log_premium_removed", "log_premium_expired",
    "log_request",
    "log_event",
]
