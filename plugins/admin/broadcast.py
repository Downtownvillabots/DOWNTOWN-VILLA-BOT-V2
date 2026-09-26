# ============================================================
# 🏨 DOWNTOWN VILLA — BROADCAST ADMIN PANEL
# ============================================================
#
# Admin-only broadcast control center.
# Opened from /admin → [📢 Broadcast] button, OR /broadcast command.
#
# Callback format: adm:bc:<action>[:args...]
# Handler group: -9520 (runs before main admin router)
#
# Features:
#   • Channel manager (add/remove/toggle/primary)
#   • Per-channel caption + buttons editor
#   • Global caption + buttons editor
#   • Templates, History, Stats, Export/Import
#   • Broadcast to: channels / groups / users
#   • Timer for auto-delete (works for ALL targets)
#   • Channel watcher (upload → destination picker)
#   • Live progress + final report
#
# ============================================================

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
import time
import uuid
from datetime import datetime
from io import BytesIO
from typing import Any, Dict, List, Optional, Tuple

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.errors import (
    FloodWait, MessageNotModified, MessageIdInvalid,
    UserIsBlocked, InputUserDeactivated, PeerIdInvalid,
    ChatWriteForbidden, ChatAdminRequired, UserDeactivated,
    UserDeactivatedBan, ChannelPrivate, ChatForbidden,
    UserNotParticipant, MediaEmpty,
)
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from core import config
from utils import fonts as F
from utils import format as FM

logger = logging.getLogger(__name__)


# ============================================================
# PREFIX + CONSTANTS
# ============================================================

PREFIX = "adm:bc:"
FILTER_REGEX = r"^adm:bc:"

SESSION_TTL = 900.0
SOURCE_TTL = 3600.0
PROGRESS_EDIT_INTERVAL = 2.5
BROADCAST_BATCH_SIZE = 30
BROADCAST_CONCURRENCY = 5
DEFAULT_DELAY = 0.05
AUTODELETE_SCAN_INTERVAL = 60
PAGE_SIZE = 8

_RAW = os.getenv("BROADCAST_CHANNEL_ID", "0").strip()
try:
    BROADCAST_CHANNEL_ID = int(_RAW) or None
except (TypeError, ValueError):
    BROADCAST_CHANNEL_ID = None

DIV = "━" * 26
DIV2 = "─" * 26

DEFAULT_CAPTION = (
    "🎬 <b>{file_name}</b>\n"
    "📦 Size: <code>{file_size}</code>\n"
    "⭐ Rating: <b>{rating}</b>\n"
    "\n"
    "⚡ <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>"
)

CAPTION_TEMPLATES = {
    "default": DEFAULT_CAPTION,
    "movies": (
        "🎬 <b>{file_name}</b>\n"
        "📅 Year: <b>{year}</b>\n"
        "📦 Size: <code>{file_size}</code>\n"
        "⭐ Rating: <b>{rating}</b>\n\n"
        "⚡ <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>"
    ),
    "series": (
        "📺 <b>{file_name}</b>\n"
        "📅 Year: <b>{year}</b>\n"
        "📦 Size: <code>{file_size}</code>\n\n"
        "⚡ <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>"
    ),
    "minimal": "🎬 <b>{file_name}</b>\n📦 {file_size}",
}

AUTODELETE_PRESETS = [
    (1,  86400,   "1 DAY"),
    (3,  259200,  "3 DAYS"),
    (7,  604800,  "7 DAYS"),
    (10, 864000,  "10 DAYS"),
    (30, 2592000, "30 DAYS"),
    (0,  0,       "NEVER"),
]
AUTODELETE_LABELS = {d: label for _, d, label in AUTODELETE_PRESETS}
AUTODELETE_SECONDS = {d: s for d, s, _ in AUTODELETE_PRESETS}


# ============================================================
# CALLBACK BUILDER
# ============================================================

def cb(action: str) -> str:
    return PREFIX + str(action)


# ============================================================
# AUTH
# ============================================================

def _is_admin(uid) -> bool:
    try:
        return int(uid) in [int(a) for a in config.ADMINS]
    except Exception:
        return False


# ============================================================
# STATE — SESSIONS / JOBS / SOURCES
# ============================================================

_sessions: Dict[int, Dict[str, Any]] = {}
_jobs: Dict[str, Dict[str, Any]] = {}
_sources: Dict[str, Dict[str, Any]] = {}
_pending: Dict[int, Dict[str, Any]] = {}
_manual_targets: Dict[int, int] = {}
_bot_client: Optional[Client] = None


def _ss_set(uid: int, action: str, **data) -> str:
    tok = secrets.token_urlsafe(8)[:10]
    _sessions[int(uid)] = {
        "token": tok, "action": action, "step": 1,
        "data": data, "expires": time.time() + SESSION_TTL,
    }
    return tok


def _ss_get(uid: int) -> Optional[Dict[str, Any]]:
    s = _sessions.get(int(uid))
    if not s:
        return None
    if time.time() > s["expires"]:
        _sessions.pop(int(uid), None)
        return None
    return s


def _ss_drop(uid: int) -> None:
    _sessions.pop(int(uid), None)


def _pend_set(uid: int, kind: str, **extra) -> None:
    _pending[int(uid)] = {
        "kind": kind,
        "expires": time.time() + SESSION_TTL,
        **extra,
    }


def _pend_get(uid: int) -> Optional[Dict[str, Any]]:
    s = _pending.get(int(uid))
    if not s:
        return None
    if time.time() > s.get("expires", 0):
        _pending.pop(int(uid), None)
        return None
    return s


def _pend_drop(uid: int) -> None:
    _pending.pop(int(uid), None)


def _new_job(admin_id, kind, total, source_msg_id, source_chat_id,
             progress_chat_id, progress_msg_id,
             autodelete_seconds: int = 0) -> str:
    jid = uuid.uuid4().hex[:10]
    _jobs[jid] = {
        "id": jid, "admin_id": admin_id, "kind": kind, "total": total,
        "sent": 0, "failed": 0, "blocked": 0, "deleted": 0,
        "started_at": time.time(), "status": "running",
        "cancel_flag": False, "last_edit": 0.0,
        "source_msg_id": source_msg_id, "source_chat_id": source_chat_id,
        "progress_chat_id": progress_chat_id,
        "progress_msg_id": progress_msg_id,
        "autodelete_seconds": int(autodelete_seconds or 0),
        "targets": [], "current_index": 0,
    }
    return jid


def _get_job(jid: str):
    return _jobs.get(jid)


def _finish_job(jid: str, status: str = "completed") -> None:
    j = _jobs.get(jid)
    if j:
        j["status"] = status
        j["finished_at"] = time.time()


def _register_source(message: Message) -> str:
    sid = uuid.uuid4().hex[:10]
    _sources[sid] = {
        "message_id": message.id, "chat_id": message.chat.id,
        "created": time.time(), "expires": time.time() + SOURCE_TTL,
        "kind": (message.media.value if message.media else "text"),
    }
    return sid


def _get_source(sid: str) -> Optional[Dict[str, Any]]:
    s = _sources.get(sid)
    if not s:
        return None
    if time.time() > s["expires"]:
        _sources.pop(sid, None)
        return None
    return s


def _cleanup_state() -> None:
    now = time.time()
    for uid in list(_sessions.keys()):
        if _sessions[uid]["expires"] < now:
            _sessions.pop(uid, None)
    for sid in list(_sources.keys()):
        if _sources[sid]["expires"] < now:
            _sources.pop(sid, None)
    for jid in list(_jobs.keys()):
        j = _jobs[jid]
        if j["status"] in ("completed", "cancelled", "failed"):
            if now - j.get("finished_at", now) > 300:
                _jobs.pop(jid, None)
    for uid in list(_pending.keys()):
        if _pending[uid].get("expires", 0) < now:
            _pending.pop(uid, None)


# ============================================================
# DATABASE HELPERS
# ============================================================

def _sys_db():
    try:
        from database import db_registry
        return db_registry.get_system_db()
    except Exception:
        return None


def _user_db():
    try:
        from database import db_registry
        return db_registry.get_user_db()
    except Exception:
        return None


def _cfg_coll():
    db = _sys_db()
    return db["broadcast_config"] if db is not None else None


def _users_coll():
    db = _user_db()
    return db["users"] if db is not None else None


def _groups_coll():
    db = _user_db()
    return db["groups"] if db is not None else None


def _history_coll():
    db = _sys_db()
    return db["broadcast_history"] if db is not None else None


def _autodel_coll():
    db = _sys_db()
    return db["broadcast_autodelete"] if db is not None else None


# ── Users ──

async def _count_users() -> int:
    c = _users_coll()
    if c is None:
        return 0
    try:
        return await c.estimated_document_count()
    except Exception:
        return 0


async def _get_all_users() -> List[int]:
    c = _users_coll()
    if c is None:
        return []
    ids: List[int] = []
    try:
        async for doc in c.find({}, {"id": 1, "user_id": 1}):
            uid = doc.get("id") or doc.get("user_id")
            if uid:
                ids.append(int(uid))
    except Exception as e:
        logger.warning(f"[BC] users: {e}")
    return ids


async def _delete_user(user_id: int) -> None:
    c = _users_coll()
    if c is None:
        return
    try:
        await c.delete_many(
            {"$or": [{"id": int(user_id)}, {"user_id": int(user_id)}]}
        )
    except Exception:
        pass


# ── Groups ──

async def _count_groups() -> int:
    c = _groups_coll()
    if c is None:
        return 0
    try:
        return await c.estimated_document_count()
    except Exception:
        return 0


async def _get_all_groups() -> List[int]:
    c = _groups_coll()
    if c is None:
        return []
    ids: List[int] = []
    try:
        async for doc in c.find({}, {"chat_id": 1, "id": 1, "chat_status": 1}):
            cs = doc.get("chat_status") or {}
            if cs.get("is_disabled"):
                continue
            cid = doc.get("chat_id") or doc.get("id")
            if cid:
                ids.append(int(cid))
    except Exception as e:
        logger.warning(f"[BC] groups: {e}")
    return ids


# ── Channels ──

async def _get_saved_channels() -> List[Dict[str, Any]]:
    c = _cfg_coll()
    if c is None:
        return []
    try:
        doc = await c.find_one({"_id": "channels"}) or {}
        return list(doc.get("list") or [])
    except Exception as e:
        logger.warning(f"[BC] channels: {e}")
        return []


async def _get_channel(chat_id: int) -> Optional[Dict[str, Any]]:
    for ch in await _get_saved_channels():
        if ch.get("chat_id") == int(chat_id):
            return ch
    return None


async def _save_channel(chat_id: int, title: str,
                        username: Optional[str] = None) -> bool:
    c = _cfg_coll()
    if c is None:
        return False
    try:
        doc = await c.find_one({"_id": "channels"}) or {"list": []}
        chans = [x for x in (doc.get("list") or [])
                 if x.get("chat_id") != int(chat_id)]
        chans.append({
            "chat_id": int(chat_id),
            "title": title or str(chat_id),
            "username": username,
            "caption": None,
            "buttons": None,
            "enabled": True,
            "primary": False,
            "added_at": time.time(),
        })
        await c.update_one(
            {"_id": "channels"},
            {"$set": {"list": chans, "updated_at": time.time()}},
            upsert=True,
        )
        return True
    except Exception as e:
        logger.warning(f"[BC] save channel: {e}")
        return False


async def _update_channel(chat_id: int, **fields) -> bool:
    c = _cfg_coll()
    if c is None:
        return False
    try:
        doc = await c.find_one({"_id": "channels"}) or {"list": []}
        chans = list(doc.get("list") or [])
        found = False
        for ch in chans:
            if ch.get("chat_id") == int(chat_id):
                ch.update(fields)
                found = True
                break
        if not found:
            return False
        await c.update_one(
            {"_id": "channels"},
            {"$set": {"list": chans, "updated_at": time.time()}},
        )
        return True
    except Exception as e:
        logger.warning(f"[BC] update channel: {e}")
        return False


async def _remove_channel(chat_id: int) -> bool:
    c = _cfg_coll()
    if c is None:
        return False
    try:
        doc = await c.find_one({"_id": "channels"}) or {"list": []}
        chans = list(doc.get("list") or [])
        new_list = [x for x in chans if x.get("chat_id") != int(chat_id)]
        await c.update_one(
            {"_id": "channels"},
            {"$set": {"list": new_list, "updated_at": time.time()}},
        )
        return len(new_list) < len(chans)
    except Exception:
        return False


# ── Global caption / buttons ──

async def _get_global_caption() -> str:
    c = _cfg_coll()
    if c is None:
        return DEFAULT_CAPTION
    try:
        doc = await c.find_one({"_id": "settings"}) or {}
        return doc.get("caption") or DEFAULT_CAPTION
    except Exception:
        return DEFAULT_CAPTION


async def _set_global_caption(caption: str) -> bool:
    c = _cfg_coll()
    if c is None:
        return False
    try:
        await c.update_one(
            {"_id": "settings"},
            {"$set": {"caption": caption, "updated_at": time.time()}},
            upsert=True,
        )
        return True
    except Exception:
        return False


async def _get_global_buttons() -> List[Dict[str, Any]]:
    c = _cfg_coll()
    if c is None:
        return []
    try:
        doc = await c.find_one({"_id": "settings"}) or {}
        return list(doc.get("buttons") or [])
    except Exception:
        return []


async def _set_global_buttons(buttons: List[Dict[str, Any]]) -> bool:
    c = _cfg_coll()
    if c is None:
        return False
    try:
        await c.update_one(
            {"_id": "settings"},
            {"$set": {"buttons": buttons, "updated_at": time.time()}},
            upsert=True,
        )
        return True
    except Exception:
        return False


# ── History ──

async def _log_history(data: Dict[str, Any]) -> None:
    c = _history_coll()
    if c is None:
        return
    try:
        data["created_at"] = time.time()
        await c.insert_one(data)
    except Exception:
        pass


async def _get_history(limit: int = 15) -> List[Dict[str, Any]]:
    c = _history_coll()
    if c is None:
        return []
    try:
        cursor = c.find({}).sort("created_at", -1).limit(limit)
        docs = await cursor.to_list(length=limit)
        for d in docs:
            d.pop("_id", None)
        return docs
    except Exception:
        return []


async def _clear_history() -> int:
    c = _history_coll()
    if c is None:
        return 0
    try:
        r = await c.delete_many({})
        return r.deleted_count
    except Exception:
        return 0


# ── Auto-delete ──

async def _schedule_autodelete(chat_id: int, message_id: int,
                               seconds: int, job_id: str) -> None:
    c = _autodel_coll()
    if c is None:
        return
    try:
        await c.insert_one({
            "chat_id": int(chat_id),
            "message_id": int(message_id),
            "delete_at": time.time() + int(seconds),
            "job_id": job_id or "",
            "created_at": time.time(),
        })
    except Exception as e:
        logger.debug(f"[BC-AD] schedule: {e}")


async def _count_scheduled() -> int:
    c = _autodel_coll()
    if c is None:
        return 0
    try:
        return await c.estimated_document_count()
    except Exception:
        return 0


async def _due_autodeletes(limit: int = 200) -> List[Dict[str, Any]]:
    c = _autodel_coll()
    if c is None:
        return []
    try:
        cursor = c.find({"delete_at": {"$lte": time.time()}}).limit(limit)
        return await cursor.to_list(length=limit)
    except Exception:
        return []


async def _remove_autodelete(doc_id) -> None:
    c = _autodel_coll()
    if c is None:
        return
    try:
        await c.delete_one({"_id": doc_id})
    except Exception:
        pass


# ============================================================
# FORMAT HELPERS
# ============================================================

def _fmt_size(size) -> str:
    try:
        return FM.size(size)
    except Exception:
        return "0 B"


def _progress_bar(current: int, total: int, width: int = 10) -> str:
    if total <= 0:
        return "⬛" * width + " 0%"
    pct = min(100.0, (current / total) * 100.0)
    filled = max(0, min(width, int(width * pct / 100.0)))
    empty = width - filled
    if pct >= 80:
        block = "🟩"
    elif pct >= 50:
        block = "🟨"
    elif pct >= 25:
        block = "🟧"
    else:
        block = "🟥"
    return block * filled + "⬛" * empty + f" {pct:.1f}%"


def _esc(text) -> str:
    if text is None:
        return ""
    return (str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;"))


def _effective_caption(channel: Optional[Dict[str, Any]]) -> str:
    if channel is None or channel.get("caption") is None:
        return ""
    return channel["caption"]


def _effective_buttons(channel: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    if channel is None or channel.get("buttons") is None:
        return []
    return list(channel["buttons"])


def _build_caption_for(message: Message, template: str) -> str:
    try:
        file_name = "file"
        file_size_h = "0 B"
        file_caption = message.caption or ""
        for attr in ("video", "document", "audio", "photo", "animation"):
            media = getattr(message, attr, None)
            if media:
                file_name = (
                    getattr(media, "file_name", None)
                    or file_caption[:80]
                    or "file"
                )
                size = getattr(media, "file_size", 0) or 0
                file_size_h = _fmt_size(size)
                break
        year = ""
        m = re.search(r"\b(19[3-9]\d|20[0-4]\d)\b", file_name)
        if m:
            year = m.group(1)
        return template.format(
            file_name=file_name[:100],
            file_size=file_size_h,
            rating="—",
            year=year or "—",
            file_caption=file_caption[:200] if file_caption else "—",
        )
    except Exception as e:
        logger.warning(f"[BC] caption render: {e}")
        return template


def _build_kb_from_list(
    buttons: List[Dict[str, Any]],
) -> Optional[InlineKeyboardMarkup]:
    if not buttons:
        return None
    rows = []
    for b in buttons:
        name = (b.get("name") or "").strip()
        url = (b.get("url") or "").strip()
        if not name or not url:
            continue
        if url.startswith("@"):
            url = f"https://t.me/{url[1:]}"
        elif not (url.startswith("http://")
                  or url.startswith("https://")
                  or url.startswith("tg://")):
            if "." in url and " " not in url:
                url = f"https://{url}"
            else:
                continue
        rows.append([InlineKeyboardButton(name[:60], url=url)])
    return InlineKeyboardMarkup(rows) if rows else None


# ============================================================
# SAFE EDIT
# ============================================================

async def _safe_edit(q: CallbackQuery, text: str, kb=None) -> None:
    try:
        await q.message.edit_text(
            text, reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        if "not modified" not in str(e).lower():
            logger.debug(f"[BC] edit: {e}")


# ============================================================
# KEYBOARD BUILDERS
# ============================================================

def kb_main(stats: Dict[str, Any]) -> InlineKeyboardMarkup:
    rows = [
        [
            InlineKeyboardButton(
                f"{F.EMO['brand']} {F.sc('broadcast')} {F.sc('panel')}",
                callback_data=cb("noop"),
            )
        ],
        [
            InlineKeyboardButton(
                f"📢 {F.sc('channels')} ({stats.get('channels', 0)})",
                callback_data=cb("ch:list:0"),
            ),
            InlineKeyboardButton(
                f"👥 {F.sc('groups')} ({stats.get('groups', 0)})",
                callback_data=cb("send:groups"),
            ),
        ],
        [
            InlineKeyboardButton(
                f"👤 {F.sc('users')} ({stats.get('users', 0)})",
                callback_data=cb("send:users"),
            ),
            InlineKeyboardButton(
                f"🎯 {F.sc('manual')}",
                callback_data=cb("send:manual"),
            ),
        ],
        [
            InlineKeyboardButton(
                f"📝 {F.sc('caption')}",
                callback_data=cb("cap:global"),
            ),
            InlineKeyboardButton(
                f"🔘 {F.sc('buttons')}",
                callback_data=cb("btn:global"),
            ),
        ],
        [
            InlineKeyboardButton(
                f"📋 {F.sc('templates')}",
                callback_data=cb("tpl:list"),
            ),
            InlineKeyboardButton(
                f"⏱️ {F.sc('autodelete')}",
                callback_data=cb("ad:panel"),
            ),
        ],
        [
            InlineKeyboardButton(
                f"📊 {F.sc('stats')}",
                callback_data=cb("stats"),
            ),
            InlineKeyboardButton(
                f"🕒 {F.sc('history')}",
                callback_data=cb("hist:0"),
            ),
        ],
        [
            InlineKeyboardButton(
                f"💾 {F.sc('export')}",
                callback_data=cb("io:export"),
            ),
            InlineKeyboardButton(
                f"📥 {F.sc('import')}",
                callback_data=cb("io:import"),
            ),
        ],
        [
            InlineKeyboardButton(
                f"🔄 {F.sc('refresh')}",
                callback_data=cb("refresh"),
            ),
            InlineKeyboardButton(
                "✖️ " + F.sc("close"),
                callback_data=cb("close"),
            ),
        ],
    ]
    return InlineKeyboardMarkup(rows)


def kb_back(target: str = "main") -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "◀️ " + F.sc("back"),
                callback_data=cb(target),
            ),
            InlineKeyboardButton(
                "✖️ " + F.sc("close"),
                callback_data=cb("close"),
            ),
        ]
    ])


def kb_channels(channels: List[Dict[str, Any]],
                page: int = 0) -> InlineKeyboardMarkup:
    rows = []
    total = len(channels)
    start = page * PAGE_SIZE
    end = min(start + PAGE_SIZE, total)
    for ch in channels[start:end]:
        status = "✅" if ch.get("enabled", True) else "⛔"
        primary = "⭐ " if ch.get("primary") else ""
        title = (ch.get("title") or str(ch.get("chat_id")))[:28]
        rows.append([
            InlineKeyboardButton(
                f"{primary}{status} {title}",
                callback_data=cb(f"ch:view:{ch['chat_id']}"),
            )
        ])
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️", callback_data=cb(f"ch:list:{page-1}")))
    if end < total:
        nav.append(InlineKeyboardButton("▶️", callback_data=cb(f"ch:list:{page+1}")))
    if nav:
        rows.append(nav)
    rows.append([
        InlineKeyboardButton(f"➕ {F.sc('add')}", callback_data=cb("ch:add")),
        InlineKeyboardButton(f"🔄 {F.sc('refresh')}", callback_data=cb(f"ch:list:{page}")),
    ])
    rows.append([
        InlineKeyboardButton("◀️ " + F.sc("back"), callback_data=cb("main")),
        InlineKeyboardButton("✖️ " + F.sc("close"), callback_data=cb("close")),
    ])
    return InlineKeyboardMarkup(rows)


def kb_channel_view(ch: Dict[str, Any]) -> InlineKeyboardMarkup:
    cid = ch["chat_id"]
    enabled = ch.get("enabled", True)
    primary = ch.get("primary", False)
    rows = [
        [
            InlineKeyboardButton(
                f"📝 {F.sc('caption')}",
                callback_data=cb(f"ch:cap:{cid}"),
            ),
            InlineKeyboardButton(
                f"🔘 {F.sc('buttons')}",
                callback_data=cb(f"ch:btn:{cid}"),
            ),
        ],
        [
            InlineKeyboardButton(
                ("⛔ " + F.sc("disable")) if enabled else ("✅ " + F.sc("enable")),
                callback_data=cb(f"ch:toggle:{cid}"),
            ),
            InlineKeyboardButton(
                ("⭐ " + F.sc("unprimary")) if primary else ("☆ " + F.sc("primary")),
                callback_data=cb(f"ch:primary:{cid}"),
            ),
        ],
        [
            InlineKeyboardButton(
                f"📤 {F.sc('send here')}",
                callback_data=cb(f"send:ch:{cid}"),
            ),
        ],
        [
            InlineKeyboardButton(
                "🗑️ " + F.sc("remove"),
                callback_data=cb(f"ch:remove:{cid}"),
            ),
        ],
        [
            InlineKeyboardButton("◀️ " + F.sc("back"), callback_data=cb("ch:list:0")),
            InlineKeyboardButton("✖️ " + F.sc("close"), callback_data=cb("close")),
        ],
    ]
    return InlineKeyboardMarkup(rows)


def kb_autodelete_picker(prefix: str, current: int = 0) -> InlineKeyboardMarkup:
    rows = []
    row = []
    for days, seconds, label in AUTODELETE_PRESETS:
        mark = "✅ " if seconds == current else ""
        row.append(
            InlineKeyboardButton(
                f"{mark}{label}",
                callback_data=cb(f"{prefix}:{seconds}"),
            )
        )
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([
        InlineKeyboardButton("◀️ " + F.sc("back"), callback_data=cb("main")),
        InlineKeyboardButton("✖️ " + F.sc("close"), callback_data=cb("close")),
    ])
    return InlineKeyboardMarkup(rows)


def kb_confirm(yes_data: str, no_data: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ " + F.sc("yes"), callback_data=yes_data),
            InlineKeyboardButton("❌ " + F.sc("no"), callback_data=no_data),
        ]
    ])


# ============================================================
# VIEW BUILDERS
# ============================================================

async def view_main() -> Tuple[str, InlineKeyboardMarkup]:
    _cleanup_state()

    channels = await _get_saved_channels()
    users = await _count_users()
    groups = await _count_groups()
    scheduled = await _count_scheduled()
    history = await _get_history(1)

    last = "—"
    if history:
        h = history[0]
        try:
            last = datetime.fromtimestamp(h.get("created_at", 0)).strftime("%d %b %H:%M")
        except Exception:
            last = "—"

    stats = {
        "channels": len(channels),
        "users": users,
        "groups": groups,
        "scheduled": scheduled,
        "last": last,
    }

    text = (
        f"{F.EMO['brand']} <b>{F.fb('BROADCAST CONTROL')}</b>\n"
        f"{DIV}\n"
        f"\n"
        f"📢 {F.sc('channels')}   : <b>{len(channels)}</b>\n"
        f"👥 {F.sc('groups')}     : <b>{groups:,}</b>\n"
        f"👤 {F.sc('users')}      : <b>{users:,}</b>\n"
        f"⏱️ {F.sc('scheduled')}  : <b>{scheduled:,}</b>\n"
        f"🕒 {F.sc('last')}       : <b>{last}</b>\n"
        f"\n"
        f"{DIV2}\n"
        f"<i>{F.sc('upload to broadcast channel or pick a target below')}</i>"
    )
    return text, kb_main(stats)


async def view_channels(page: int = 0) -> Tuple[str, InlineKeyboardMarkup]:
    channels = await _get_saved_channels()
    if not channels:
        text = (
            f"{F.EMO['brand']} <b>{F.fb('CHANNELS')}</b>\n"
            f"{DIV}\n\n"
            f"<i>No channels added yet.</i>\n\n"
            f"Tap ➕ <b>{F.sc('add')}</b> to add one."
        )
        return text, kb_channels([], 0)

    total = len(channels)
    enabled = sum(1 for c in channels if c.get("enabled", True))
    primary = next((c for c in channels if c.get("primary")), None)

    text = (
        f"{F.EMO['brand']} <b>{F.fb('CHANNELS')}</b>\n"
        f"{DIV}\n"
        f"\n"
        f"📢 {F.sc('total')}    : <b>{total}</b>\n"
        f"✅ {F.sc('enabled')}  : <b>{enabled}</b>\n"
        f"⛔ {F.sc('disabled')} : <b>{total - enabled}</b>\n"
        f"⭐ {F.sc('primary')}  : <b>{(primary or {}).get('title', '—')[:30]}</b>\n"
        f"\n"
        f"{DIV2}\n"
        f"<i>Tap a channel to manage it.</i>"
    )
    return text, kb_channels(channels, page)


async def view_channel_detail(chat_id: int) -> Optional[Tuple[str, InlineKeyboardMarkup]]:
    ch = await _get_channel(chat_id)
    if not ch:
        return None

    cap = ch.get("caption")
    btns = ch.get("buttons")
    cap_state = "✅ " + F.sc("custom") if cap else "— " + F.sc("global default")
    btn_state = f"✅ {len(btns)}" if btns else "— " + F.sc("global default")

    text = (
        f"{F.EMO['brand']} <b>{F.fb('CHANNEL')}</b>\n"
        f"{DIV}\n"
        f"\n"
        f"📢 {F.sc('title')}    : <b>{_esc(ch.get('title'))}</b>\n"
        f"🆔 {F.sc('chat id')}  : <code>{chat_id}</code>\n"
        f"🔗 {F.sc('username')} : {('@' + ch['username']) if ch.get('username') else '—'}\n"
        f"\n"
        f"📝 {F.sc('caption')}  : {cap_state}\n"
        f"🔘 {F.sc('buttons')}  : {btn_state}\n"
        f"✅ {F.sc('enabled')}  : {'Yes' if ch.get('enabled', True) else 'No'}\n"
        f"⭐ {F.sc('primary')}  : {'Yes' if ch.get('primary') else 'No'}\n"
        f"\n"
        f"{DIV2}"
    )
    return text, kb_channel_view(ch)


async def view_caption_global() -> Tuple[str, InlineKeyboardMarkup]:
    cap = await _get_global_caption()
    text = (
        f"{F.EMO['brand']} <b>{F.fb('GLOBAL CAPTION')}</b>\n"
        f"{DIV}\n"
        f"\n"
        f"<b>{F.sc('current')}:</b>\n"
        f"<pre>{_esc(cap)[:600]}</pre>\n"
        f"\n"
        f"{DIV2}\n"
        f"<i>Variables:</i>\n"
        f"<code>{{file_name}}</code> <code>{{file_size}}</code> "
        f"<code>{{rating}}</code> <code>{{year}}</code> <code>{{file_caption}}</code>"
    )
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"✏️ {F.sc('edit')}", callback_data=cb("cap:edit:global")),
            InlineKeyboardButton(f"🔄 {F.sc('reset')}", callback_data=cb("cap:reset:global")),
        ],
        [
            InlineKeyboardButton("◀️ " + F.sc("back"), callback_data=cb("main")),
            InlineKeyboardButton("✖️ " + F.sc("close"), callback_data=cb("close")),
        ],
    ])
    return text, kb


async def view_caption_channel(chat_id: int) -> Optional[Tuple[str, InlineKeyboardMarkup]]:
    ch = await _get_channel(chat_id)
    if not ch:
        return None
    cap = ch.get("caption")
    effective = cap if cap else await _get_global_caption()
    state = "✅ " + F.sc("custom") if cap else "— " + F.sc("global default")
    text = (
        f"{F.EMO['brand']} <b>{F.fb('CHANNEL CAPTION')}</b>\n"
        f"{DIV}\n"
        f"\n"
        f"📢 <b>{_esc(ch.get('title'))}</b>\n"
        f"📝 {F.sc('state')}    : {state}\n"
        f"\n"
        f"<b>{F.sc('effective caption')}:</b>\n"
        f"<pre>{_esc(effective)[:600]}</pre>"
    )
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"✏️ {F.sc('edit')}", callback_data=cb(f"cap:edit:ch:{chat_id}")),
            InlineKeyboardButton(f"🔄 {F.sc('reset')}", callback_data=cb(f"cap:reset:ch:{chat_id}")),
        ],
        [
            InlineKeyboardButton("◀️ " + F.sc("back"), callback_data=cb(f"ch:view:{chat_id}")),
            InlineKeyboardButton("✖️ " + F.sc("close"), callback_data=cb("close")),
        ],
    ])
    return text, kb


async def view_buttons_global() -> Tuple[str, InlineKeyboardMarkup]:
    btns = await _get_global_buttons()
    lines = []
    for i, b in enumerate(btns[:10], 1):
        lines.append(f"{i}. <b>{_esc(b.get('name'))}</b> → <code>{_esc(b.get('url'))[:50]}</code>")
    body = "\n".join(lines) if lines else "<i>No buttons.</i>"
    text = (
        f"{F.EMO['brand']} <b>{F.fb('GLOBAL BUTTONS')}</b>\n"
        f"{DIV}\n"
        f"\n{body}\n\n"
        f"{DIV2}\n"
        f"<i>Total: {len(btns)}</i>"
    )
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"➕ {F.sc('add')}", callback_data=cb("btn:add:global")),
            InlineKeyboardButton(f"🗑️ {F.sc('clear')}", callback_data=cb("btn:clear:global")),
        ],
        [
            InlineKeyboardButton("◀️ " + F.sc("back"), callback_data=cb("main")),
            InlineKeyboardButton("✖️ " + F.sc("close"), callback_data=cb("close")),
        ],
    ])
    return text, kb


async def view_buttons_channel(chat_id: int) -> Optional[Tuple[str, InlineKeyboardMarkup]]:
    ch = await _get_channel(chat_id)
    if not ch:
        return None
    btns = ch.get("buttons")
    if btns is None:
        state = "— " + F.sc("global default")
        display = await _get_global_buttons()
    else:
        state = "✅ " + F.sc("custom")
        display = btns
    lines = []
    for i, b in enumerate(display[:10], 1):
        lines.append(f"{i}. <b>{_esc(b.get('name'))}</b> → <code>{_esc(b.get('url'))[:50]}</code>")
    body = "\n".join(lines) if lines else "<i>No buttons.</i>"
    text = (
        f"{F.EMO['brand']} <b>{F.fb('CHANNEL BUTTONS')}</b>\n"
        f"{DIV}\n"
        f"\n"
        f"📢 <b>{_esc(ch.get('title'))}</b>\n"
        f"🔘 {F.sc('state')} : {state}\n"
        f"\n{body}"
    )
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(f"➕ {F.sc('add')}", callback_data=cb(f"btn:add:ch:{chat_id}")),
            InlineKeyboardButton(f"🗑️ {F.sc('clear')}", callback_data=cb(f"btn:clear:ch:{chat_id}")),
        ],
        [
            InlineKeyboardButton("◀️ " + F.sc("back"), callback_data=cb(f"ch:view:{chat_id}")),
            InlineKeyboardButton("✖️ " + F.sc("close"), callback_data=cb("close")),
        ],
    ])
    return text, kb


async def view_templates() -> Tuple[str, InlineKeyboardMarkup]:
    lines = []
    for key in CAPTION_TEMPLATES:
        lines.append(f"• <b>{key}</b>")
    text = (
        f"{F.EMO['brand']} <b>{F.fb('TEMPLATES')}</b>\n"
        f"{DIV}\n"
        f"\n"
        f"<i>Tap to apply to global caption.</i>\n\n"
        + "\n".join(lines)
    )
    rows = []
    row = []
    for key in CAPTION_TEMPLATES:
        row.append(
            InlineKeyboardButton(
                key, callback_data=cb(f"tpl:use:{key}")
            )
        )
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([
        InlineKeyboardButton("◀️ " + F.sc("back"), callback_data=cb("main")),
        InlineKeyboardButton("✖️ " + F.sc("close"), callback_data=cb("close")),
    ])
    return text, InlineKeyboardMarkup(rows)


async def view_history(page: int = 0) -> Tuple[str, InlineKeyboardMarkup]:
    history = await _get_history(50)
    total = len(history)
    start = page * PAGE_SIZE
    end = min(start + PAGE_SIZE, total)
    slice_ = history[start:end]

    lines = []
    for h in slice_:
        try:
            ts = datetime.fromtimestamp(h.get("created_at", 0)).strftime("%d %b %H:%M")
        except Exception:
            ts = "—"
        kind = (h.get("kind") or "?")[:6]
        sent = h.get("sent", 0)
        failed = h.get("failed", 0)
        lines.append(
            f"• <code>{ts}</code> <b>{kind}</b> "
            f"✅{sent} ❌{failed}"
        )
    body = "\n".join(lines) if lines else "<i>No history.</i>"

    text = (
        f"{F.EMO['brand']} <b>{F.fb('HISTORY')}</b>\n"
        f"{DIV}\n"
        f"\n{body}\n\n"
        f"{DIV2}\n"
        f"<i>Total: {total}</i>"
    )

    rows = []
    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton("◀️", callback_data=cb(f"hist:{page-1}")))
    if end < total:
        nav.append(InlineKeyboardButton("▶️", callback_data=cb(f"hist:{page+1}")))
    if nav:
        rows.append(nav)
    rows.append([
        InlineKeyboardButton(f"🗑️ {F.sc('clear')}", callback_data=cb("hist:clear")),
        InlineKeyboardButton("◀️ " + F.sc("back"), callback_data=cb("main")),
    ])
    rows.append([
        InlineKeyboardButton("✖️ " + F.sc("close"), callback_data=cb("close")),
    ])
    return text, InlineKeyboardMarkup(rows)


async def view_stats() -> Tuple[str, InlineKeyboardMarkup]:
    channels = await _get_saved_channels()
    users = await _count_users()
    groups = await _count_groups()
    scheduled = await _count_scheduled()
    history = await _get_history(100)

    total_sent = sum(h.get("sent", 0) for h in history)
    total_failed = sum(h.get("failed", 0) for h in history)
    total_blocked = sum(h.get("blocked", 0) for h in history)

    text = (
        f"{F.EMO['brand']} <b>{F.fb('BROADCAST STATS')}</b>\n"
        f"{DIV}\n"
        f"\n"
        f"📢 {F.sc('channels')}    : <b>{len(channels)}</b>\n"
        f"👥 {F.sc('groups')}      : <b>{groups:,}</b>\n"
        f"👤 {F.sc('users')}       : <b>{users:,}</b>\n"
        f"⏱️ {F.sc('scheduled')}   : <b>{scheduled:,}</b>\n"
        f"\n"
        f"{DIV2}\n"
        f"<b>{F.sc('all time')}:</b>\n"
        f"✅ {F.sc('sent')}    : <b>{total_sent:,}</b>\n"
        f"❌ {F.sc('failed')}  : <b>{total_failed:,}</b>\n"
        f"🚫 {F.sc('blocked')} : <b>{total_blocked:,}</b>\n"
        f"🕒 {F.sc('runs')}    : <b>{len(history)}</b>"
    )
    return text, kb_back("main")


async def view_autodelete_panel() -> Tuple[str, InlineKeyboardMarkup]:
    scheduled = await _count_scheduled()
    text = (
        f"{F.EMO['brand']} <b>{F.fb('AUTO-DELETE')}</b>\n"
        f"{DIV}\n"
        f"\n"
        f"⏱️ {F.sc('pending')} : <b>{scheduled:,}</b>\n"
        f"\n"
        f"{DIV2}\n"
        f"<i>Auto-delete works for:</i>\n"
        f"• 📢 Channels\n"
        f"• 👥 Groups\n"
        f"• 👤 Users\n"
        f"\n"
        f"<i>Set the timer when you pick a destination.</i>"
    )
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"🧹 {F.sc('purge due now')}",
                callback_data=cb("ad:purge"),
            ),
        ],
        [
            InlineKeyboardButton("◀️ " + F.sc("back"), callback_data=cb("main")),
            InlineKeyboardButton("✖️ " + F.sc("close"), callback_data=cb("close")),
        ],
    ])
    return text, kb


async def view_destination_picker(sid: str) -> Tuple[str, InlineKeyboardMarkup]:
    """Shown after upload to broadcast channel."""
    channels = await _get_saved_channels()
    enabled = [c for c in channels if c.get("enabled", True)]
    users = await _count_users()
    groups = await _count_groups()

    text = (
        f"{F.EMO['brand']} <b>{F.fb('PICK DESTINATION')}</b>\n"
        f"{DIV}\n"
        f"\n"
        f"📢 {F.sc('channels')} : <b>{len(enabled)}</b>\n"
        f"👥 {F.sc('groups')}   : <b>{groups:,}</b>\n"
        f"👤 {F.sc('users')}    : <b>{users:,}</b>\n"
        f"\n"
        f"{DIV2}\n"
        f"<i>Choose where to send this file.</i>"
    )
    rows = [
        [
            InlineKeyboardButton(
                f"📢 {F.sc('channels')}",
                callback_data=cb(f"pick:ch:{sid}"),
            ),
            InlineKeyboardButton(
                f"👥 {F.sc('groups')}",
                callback_data=cb(f"pick:gr:{sid}"),
            ),
        ],
        [
            InlineKeyboardButton(
                f"👤 {F.sc('users')}",
                callback_data=cb(f"pick:us:{sid}"),
            ),
            InlineKeyboardButton(
                f"🎯 {F.sc('manual')}",
                callback_data=cb(f"pick:mn:{sid}"),
            ),
        ],
        [
            InlineKeyboardButton(
                "✖️ " + F.sc("cancel"),
                callback_data=cb(f"pick:no:{sid}"),
            ),
        ],
    ]
    return text, InlineKeyboardMarkup(rows)


async def view_channel_picker(sid: str) -> Tuple[str, InlineKeyboardMarkup]:
    channels = await _get_saved_channels()
    enabled = [c for c in channels if c.get("enabled", True)]
    rows = []
    for ch in enabled[:20]:
        title = (ch.get("title") or str(ch["chat_id"]))[:28]
        rows.append([
            InlineKeyboardButton(
                f"📢 {title}",
                callback_data=cb(f"pick:ch1:{sid}:{ch['chat_id']}"),
            )
        ])
    rows.append([
        InlineKeyboardButton(
            f"📢 {F.sc('all channels')}",
            callback_data=cb(f"pick:chall:{sid}"),
        )
    ])
    rows.append([
        InlineKeyboardButton("◀️ " + F.sc("back"), callback_data=cb(f"back:pick:{sid}")),
        InlineKeyboardButton("✖️ " + F.sc("cancel"), callback_data=cb(f"pick:no:{sid}")),
    ])
    text = (
        f"{F.EMO['brand']} <b>{F.fb('PICK CHANNEL')}</b>\n"
        f"{DIV}\n\n"
        f"<i>{len(enabled)} channel(s) available.</i>"
    )
    return text, InlineKeyboardMarkup(rows)


async def view_timer_picker(sid: str, kind: str, target: str) -> Tuple[str, InlineKeyboardMarkup]:
    text = (
        f"{F.EMO['brand']} <b>{F.fb('AUTO-DELETE TIMER')}</b>\n"
        f"{DIV}\n"
        f"\n"
        f"🎯 {F.sc('target')} : <b>{kind}</b>\n"
        f"📌 {F.sc('value')}  : <code>{target[:40]}</code>\n"
        f"\n"
        f"{DIV2}\n"
        f"<i>How long should the message stay?</i>\n"
        f"<i>Works for channels, groups AND users.</i>"
    )
    rows = []
    row = []
    for days, seconds, label in AUTODELETE_PRESETS:
        row.append(
            InlineKeyboardButton(
                label,
                callback_data=cb(f"pick:timer:{sid}:{kind}:{target}:{seconds}"),
            )
        )
        if len(row) == 3:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([
        InlineKeyboardButton("◀️ " + F.sc("back"), callback_data=cb(f"back:pick:{sid}")),
        InlineKeyboardButton("✖️ " + F.sc("cancel"), callback_data=cb(f"pick:no:{sid}")),
    ])
    return text, InlineKeyboardMarkup(rows)


# ============================================================
# BROADCAST ENGINE
# ============================================================

async def _run_broadcast(client, q, sid, kind,
                         targets=None, autodelete_seconds=0):
    src = _get_source(sid)
    if not src:
        return await q.answer("⏱️ ᴇxᴘɪʀᴇᴅ", show_alert=True)

    if kind == "channel":
        if not targets:
            return await q.answer("⚠️ ɴᴏ ᴛᴀʀɢᴇᴛ", show_alert=True)
        target_list = list(targets)
    elif kind == "groups":
        target_list = await _get_all_groups()
    else:
        target_list = await _get_all_users()

    total = len(target_list)
    if total == 0:
        return await q.answer("⚠️ ɴᴏ ᴛᴀʀɢᴇᴛꜱ", show_alert=True)

    # Per-channel caption/buttons for single-channel send
    if kind == "channel" and len(target_list) == 1:
        ch = await _get_channel(target_list[0])
        cap_template = _effective_caption(ch) or await _get_global_caption()
        buttons_list = _effective_buttons(ch) or await _get_global_buttons()
    else:
        cap_template = await _get_global_caption()
        buttons_list = await _get_global_buttons()

    try:
        src_msg = await client.get_messages(src["chat_id"], src["message_id"])
    except Exception as e:
        return await q.answer(
            f"⚠️ ᴄᴀɴɴᴏᴛ ꜰᴇᴛᴄʜ ꜱᴏᴜʀᴄᴇ: {e}"[:180],
            show_alert=True,
        )
    if not src_msg or src_msg.empty:
        return await q.answer("⚠️ ꜱᴏᴜʀᴄᴇ ᴅᴇʟᴇᴛᴇᴅ", show_alert=True)

    caption = _build_caption_for(src_msg, cap_template)
    kb = _build_kb_from_list(buttons_list)

    progress_chat_id = q.message.chat.id
    try:
        progress_msg = await q.message.edit_text(
            f"{F.EMO['brand']} <b>{F.fb('BROADCAST STARTED')}</b>\n"
            f"{DIV}\n\n"
            f"📤 {F.sc('sending to')} <b>{total:,}</b> {kind}...",
            parse_mode=ParseMode.HTML,
        )
    except MessageNotModified:
        progress_msg = q.message
    except Exception as e:
        logger.warning(f"[BC-RUN] progress: {e}")
        progress_msg = q.message

    job_id = _new_job(
        admin_id=q.from_user.id, kind=kind, total=total,
        source_msg_id=src["message_id"], source_chat_id=src["chat_id"],
        progress_chat_id=progress_chat_id,
        progress_msg_id=progress_msg.id,
        autodelete_seconds=autodelete_seconds,
    )
    job = _get_job(job_id)
    job["targets"] = target_list
    job["current_index"] = 0

    task = asyncio.create_task(
        _broadcast_worker(client, job_id, src_msg, caption, kb)
    )
    job["task"] = task


async def _broadcast_worker(client, job_id, src_msg, caption, kb):
    job = _get_job(job_id)
    if not job:
        return

    targets = job["targets"]
    total = job["total"]
    ad_seconds = job.get("autodelete_seconds", 0)
    start_time = time.time()
    sem = asyncio.Semaphore(BROADCAST_CONCURRENCY)
    lock = asyncio.Lock()

    async def _send_one(target_id):
        if job["cancel_flag"]:
            return "cancelled"
        async with sem:
            if job["cancel_flag"]:
                return "cancelled"
            try:
                sent = await client.copy_message(
                    chat_id=target_id,
                    from_chat_id=src_msg.chat.id,
                    message_id=src_msg.id,
                    caption=caption, reply_markup=kb,
                )
                # Auto-delete for ALL kinds (channels / groups / users)
                if ad_seconds and ad_seconds > 0 and sent:
                    try:
                        await _schedule_autodelete(
                            target_id, sent.id, ad_seconds, job_id
                        )
                    except Exception as e:
                        logger.debug(f"[BC-AD] schedule: {e}")

                await asyncio.sleep(DEFAULT_DELAY)
                return "sent"

            except FloodWait as e:
                await asyncio.sleep(max(1, int(e.value)) + 2)
                try:
                    sent = await client.copy_message(
                        chat_id=target_id,
                        from_chat_id=src_msg.chat.id,
                        message_id=src_msg.id,
                        caption=caption, reply_markup=kb,
                    )
                    if ad_seconds and ad_seconds > 0 and sent:
                        try:
                            await _schedule_autodelete(
                                target_id, sent.id, ad_seconds, job_id
                            )
                        except Exception:
                            pass
                    return "sent"
                except Exception:
                    return "failed"

            except UserIsBlocked:
                return "blocked"
            except (InputUserDeactivated, UserDeactivated,
                    UserDeactivatedBan):
                return "deleted"
            except (ChatWriteForbidden, ChatForbidden,
                    ChatAdminRequired, ChannelPrivate,
                    PeerIdInvalid, UserNotParticipant):
                return "failed"
            except MediaEmpty:
                try:
                    sent = await client.copy_message(
                        chat_id=target_id,
                        from_chat_id=src_msg.chat.id,
                        message_id=src_msg.id,
                    )
                    if ad_seconds and ad_seconds > 0 and sent:
                        await _schedule_autodelete(
                            target_id, sent.id, ad_seconds, job_id
                        )
                    return "sent"
                except Exception:
                    return "failed"
            except Exception as e:
                logger.debug(f"[BC-RUN] fail {target_id}: {type(e).__name__}: {e}")
                return "failed"

    async def _worker(tid):
        result = await _send_one(tid)
        async with lock:
            job["current_index"] += 1
            if result == "sent":
                job["sent"] += 1
            elif result == "blocked":
                job["blocked"] += 1
                if job["kind"] == "users":
                    asyncio.create_task(_delete_user(tid))
            elif result == "deleted":
                job["deleted"] += 1
                if job["kind"] == "users":
                    asyncio.create_task(_delete_user(tid))
            elif result == "failed":
                job["failed"] += 1

    try:
        for i in range(0, total, BROADCAST_BATCH_SIZE):
            if job["cancel_flag"]:
                break
            batch = targets[i:i + BROADCAST_BATCH_SIZE]
            await asyncio.gather(*[_worker(t) for t in batch])
            await _update_progress(client, job)
            _cleanup_state()

        if job["cancel_flag"]:
            _finish_job(job_id, "cancelled")
            await _render_done(client, job, cancelled=True)
        else:
            _finish_job(job_id, "completed")
            await _render_done(client, job, cancelled=False)

        await _log_history({
            "job_id": job_id, "kind": job["kind"],
            "admin_id": job["admin_id"], "total": total,
            "sent": job["sent"], "failed": job["failed"],
            "blocked": job["blocked"], "deleted": job["deleted"],
            "elapsed": time.time() - start_time,
            "status": job["status"],
            "autodelete_seconds": ad_seconds,
        })
    except asyncio.CancelledError:
        _finish_job(job_id, "cancelled")
        await _render_done(client, job, cancelled=True)
        raise
    except Exception as e:
        logger.exception(f"[BC-RUN] crashed: {e}")
        _finish_job(job_id, "failed")
        try:
            await client.edit_message_text(
                chat_id=job["progress_chat_id"],
                message_id=job["progress_msg_id"],
                text=(
                    f"❌ <b>{F.fb('BROADCAST FAILED')}</b>\n"
                    f"{DIV}\n\n"
                    f"<code>{type(e).__name__}: {_esc(str(e))[:200]}</code>"
                ),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass


async def _update_progress(client, job) -> None:
    now = time.time()
    if now - job.get("last_edit", 0) < PROGRESS_EDIT_INTERVAL:
        return
    job["last_edit"] = now

    elapsed = max(0.001, now - job["started_at"])
    done = job["current_index"]
    total = job["total"]
    rate = done / elapsed

    text = (
        f"{F.EMO['brand']} <b>{F.fb('BROADCAST RUNNING')}</b>\n"
        f"{DIV}\n"
        f"\n"
        f"{_progress_bar(done, total)}\n"
        f"\n"
        f"📤 {F.sc('sent')}    : <b>{job['sent']:,}</b>\n"
        f"❌ {F.sc('failed')}  : <b>{job['failed']:,}</b>\n"
        f"🚫 {F.sc('blocked')} : <b>{job['blocked']:,}</b>\n"
        f"🗑️ {F.sc('deleted')} : <b>{job['deleted']:,}</b>\n"
        f"\n"
        f"{DIV2}\n"
        f"🎯 {F.sc('progress')} : <b>{done:,}/{total:,}</b>\n"
        f"⚡ {F.sc('speed')}   : <b>{rate:.1f}/s</b>"
    )
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"🛑 {F.sc('cancel')}",
                callback_data=cb(f"stop:{job['id']}"),
            ),
        ],
    ])
    try:
        await client.edit_message_text(
            chat_id=job["progress_chat_id"],
            message_id=job["progress_msg_id"],
            text=text, reply_markup=kb,
            parse_mode=ParseMode.HTML,
        )
    except MessageNotModified:
        pass
    except Exception as e:
        logger.debug(f"[BC-RUN] edit: {e}")


async def _render_done(client, job, cancelled=False) -> None:
    elapsed = max(0.001, time.time() - job["started_at"])
    rate = job["current_index"] / elapsed
    title = "BROADCAST CANCELLED" if cancelled else "BROADCAST COMPLETE"
    emo = "🛑" if cancelled else "✅"
    ad = job.get("autodelete_seconds", 0)
    ad_label = AUTODELETE_LABELS.get(
        next((d for d, s, _ in AUTODELETE_PRESETS if s == ad), 0),
        "—",
    )
    text = (
        f"{emo} <b>{F.fb(title)}</b>\n"
        f"{DIV}\n"
        f"\n"
        f"✅ {F.sc('sent')}    : <b>{job['sent']:,}</b>\n"
        f"❌ {F.sc('failed')}  : <b>{job['failed']:,}</b>\n"
        f"🚫 {F.sc('blocked')} : <b>{job['blocked']:,}</b>\n"
        f"🗑️ {F.sc('deleted')} : <b>{job['deleted']:,}</b>\n"
        f"\n"
        f"{DIV2}\n"
        f"🎯 {F.sc('total')}   : <b>{job['total']:,}</b>\n"
        f"⚡ {F.sc('speed')}   : <b>{rate:.1f}/s</b>\n"
        f"⏱️ {F.sc('elapsed')} : <b>{int(elapsed)}s</b>\n"
        f"🗓️ {F.sc('autodelete')} : <b>{ad_label}</b>"
    )
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "◀️ " + F.sc("back to panel"),
                callback_data=cb("main"),
            ),
            InlineKeyboardButton(
                "✖️ " + F.sc("close"),
                callback_data=cb("close"),
            ),
        ]
    ])
    try:
        await client.edit_message_text(
            chat_id=job["progress_chat_id"],
            message_id=job["progress_msg_id"],
            text=text, reply_markup=kb,
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        logger.debug(f"[BC-RUN] done edit: {e}")


# ============================================================
# AUTO-DELETE LOOP
# ============================================================

async def _autodelete_loop(client: Client) -> None:
    while True:
        try:
            due = await _due_autodeletes(200)
            for doc in due:
                try:
                    await client.delete_messages(
                        chat_id=int(doc["chat_id"]),
                        message_ids=int(doc["message_id"]),
                    )
                except Exception:
                    pass
                await _remove_autodelete(doc["_id"])
        except asyncio.CancelledError:
            raise
        except Exception as e:
            logger.debug(f"[BC-AD] loop: {e}")
        await asyncio.sleep(AUTODELETE_SCAN_INTERVAL)


# ============================================================
# CALLBACK ROUTER
# ============================================================

@Client.on_callback_query(filters.regex(FILTER_REGEX), group=-9520)
async def bc_router(client: Client, q: CallbackQuery):
    global _bot_client
    _bot_client = client

    if not q.from_user or not _is_admin(q.from_user.id):
        return await q.answer("⛔ ᴀᴅᴍɪɴꜱ ᴏɴʟʏ", show_alert=True)

    data = q.data or ""
    parts = data[len(PREFIX):].split(":") if data.startswith(PREFIX) else []
    action = parts[0] if parts else "main"

    try:
        # ── Main ──
        if action in ("main", "refresh"):
            text, kb = await view_main()
            await _safe_edit(q, text, kb)
            return await q.answer("🔄")

        if action == "noop":
            return await q.answer()

        if action == "close":
            try:
                await q.message.delete()
            except Exception:
                pass
            return await q.answer("✖️")

        # ── Channels ──
        if action == "ch":
            sub = parts[1] if len(parts) > 1 else "list"

            if sub == "list":
                page = int(parts[2]) if len(parts) > 2 else 0
                text, kb = await view_channels(page)
                await _safe_edit(q, text, kb)
                return await q.answer()

            if sub == "view":
                cid = int(parts[2])
                res = await view_channel_detail(cid)
                if not res:
                    return await q.answer("⚠️ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)
                text, kb = res
                await _safe_edit(q, text, kb)
                return await q.answer()

            if sub == "add":
                _pend_set(q.from_user.id, "ch_add")
                await _safe_edit(
                    q,
                    f"{F.EMO['brand']} <b>{F.fb('ADD CHANNEL')}</b>\n"
                    f"{DIV}\n\n"
                    f"<i>Send me one of:</i>\n"
                    f"• <code>-1001234567890</code> (chat id)\n"
                    f"• <code>@username</code>\n\n"
                    f"<i>Bot must be admin in the channel.</i>",
                    kb_back("ch:list:0"),
                )
                return await q.answer("📝 ᴛʏᴘᴇ ɴᴏᴡ")

            if sub == "remove":
                cid = int(parts[2])
                _pend_set(q.from_user.id, "ch_remove_confirm", chat_id=cid)
                await _safe_edit(
                    q,
                    f"⚠️ <b>{F.fb('REMOVE CHANNEL')}</b>\n"
                    f"{DIV}\n\n"
                    f"<i>Are you sure?</i>",
                    kb_confirm(cb(f"ch:remove_yes:{cid}"), cb(f"ch:view:{cid}")),
                )
                return await q.answer()

            if sub == "remove_yes":
                cid = int(parts[2])
                await _remove_channel(cid)
                text, kb = await view_channels(0)
                await _safe_edit(q, text, kb)
                return await q.answer("🗑️ ʀᴇᴍᴏᴠᴇᴅ")

            if sub == "toggle":
                cid = int(parts[2])
                ch = await _get_channel(cid)
                if ch:
                    await _update_channel(cid, enabled=not ch.get("enabled", True))
                res = await view_channel_detail(cid)
                if res:
                    text, kb = res
                    await _safe_edit(q, text, kb)
                return await q.answer("✅")

            if sub == "primary":
                cid = int(parts[2])
                channels = await _get_saved_channels()
                for ch in channels:
                    await _update_channel(
                        ch["chat_id"], primary=(ch["chat_id"] == cid)
                    )
                res = await view_channel_detail(cid)
                if res:
                    text, kb = res
                    await _safe_edit(q, text, kb)
                return await q.answer("⭐")

            if sub == "cap":
                cid = int(parts[2])
                res = await view_caption_channel(cid)
                if not res:
                    return await q.answer("⚠️", show_alert=True)
                text, kb = res
                await _safe_edit(q, text, kb)
                return await q.answer()

            if sub == "btn":
                cid = int(parts[2])
                res = await view_buttons_channel(cid)
                if not res:
                    return await q.answer("⚠️", show_alert=True)
                text, kb = res
                await _safe_edit(q, text, kb)
                return await q.answer()

        # ── Caption ──
        if action == "cap":
            sub = parts[1] if len(parts) > 1 else "global"

            if sub == "global":
                text, kb = await view_caption_global()
                await _safe_edit(q, text, kb)
                return await q.answer()

            if sub == "edit":
                target = parts[2]
                if target == "global":
                    _pend_set(q.from_user.id, "cap_edit_global")
                    await _safe_edit(
                        q,
                        f"{F.EMO['brand']} <b>{F.fb('EDIT GLOBAL CAPTION')}</b>\n"
                        f"{DIV}\n\n"
                        f"<i>Send the new caption.</i>\n"
                        f"<i>Use HTML tags + variables.</i>",
                        kb_back("cap:global"),
                    )
                    return await q.answer("📝")
                if target == "ch":
                    cid = int(parts[3])
                    _pend_set(q.from_user.id, "cap_edit_ch", chat_id=cid)
                    await _safe_edit(
                        q,
                        f"{F.EMO['brand']} <b>{F.fb('EDIT CHANNEL CAPTION')}</b>\n"
                        f"{DIV}\n\n"
                        f"<i>Send the new caption for this channel.</i>",
                        kb_back(f"ch:view:{cid}"),
                    )
                    return await q.answer("📝")

            if sub == "reset":
                target = parts[2]
                if target == "global":
                    await _set_global_caption(DEFAULT_CAPTION)
                    text, kb = await view_caption_global()
                    await _safe_edit(q, text, kb)
                    return await q.answer("🔄 ʀᴇꜱᴇᴛ")
                if target == "ch":
                    cid = int(parts[3])
                    await _update_channel(cid, caption=None)
                    res = await view_caption_channel(cid)
                    if res:
                        text, kb = res
                        await _safe_edit(q, text, kb)
                    return await q.answer("🔄 ʀᴇꜱᴇᴛ")

        # ── Buttons ──
        if action == "btn":
            sub = parts[1] if len(parts) > 1 else "global"

            if sub == "global":
                text, kb = await view_buttons_global()
                await _safe_edit(q, text, kb)
                return await q.answer()

            if sub == "add":
                target = parts[2]
                if target == "global":
                    _pend_set(q.from_user.id, "btn_add_global")
                    await _safe_edit(
                        q,
                        f"{F.EMO['brand']} <b>{F.fb('ADD GLOBAL BUTTON')}</b>\n"
                        f"{DIV}\n\n"
                        f"<i>Send as:</i>\n"
                        f"<code>Name | https://url</code>\n\n"
                        f"<i>Example:</i>\n"
                        f"<code>Join Channel | https://t.me/xxx</code>",
                        kb_back("btn:global"),
                    )
                    return await q.answer("📝")
                if target == "ch":
                    cid = int(parts[3])
                    _pend_set(q.from_user.id, "btn_add_ch", chat_id=cid)
                    await _safe_edit(
                        q,
                        f"{F.EMO['brand']} <b>{F.fb('ADD CHANNEL BUTTON')}</b>\n"
                        f"{DIV}\n\n"
                        f"<i>Send as:</i>\n"
                        f"<code>Name | https://url</code>",
                        kb_back(f"ch:view:{cid}"),
                    )
                    return await q.answer("📝")

            if sub == "clear":
                target = parts[2]
                if target == "global":
                    await _set_global_buttons([])
                    text, kb = await view_buttons_global()
                    await _safe_edit(q, text, kb)
                    return await q.answer("🗑️ ᴄʟᴇᴀʀᴇᴅ")
                if target == "ch":
                    cid = int(parts[3])
                    await _update_channel(cid, buttons=[])
                    res = await view_buttons_channel(cid)
                    if res:
                        text, kb = res
                        await _safe_edit(q, text, kb)
                    return await q.answer("🗑️ ᴄʟᴇᴀʀᴇᴅ")

        # ── Templates ──
        if action == "tpl":
            sub = parts[1] if len(parts) > 1 else "list"
            if sub == "list":
                text, kb = await view_templates()
                await _safe_edit(q, text, kb)
                return await q.answer()
            if sub == "use":
                key = parts[2]
                if key in CAPTION_TEMPLATES:
                    await _set_global_caption(CAPTION_TEMPLATES[key])
                    return await q.answer(f"✅ {key} ᴀᴘᴘʟɪᴇᴅ")

        # ── History ──
        if action == "hist":
            sub = parts[1] if len(parts) > 1 else "0"
            if sub == "clear":
                _pend_set(q.from_user.id, "hist_clear")
                await _safe_edit(
                    q,
                    f"⚠️ <b>{F.fb('CLEAR HISTORY')}</b>\n"
                    f"{DIV}\n\n"
                    f"<i>Are you sure?</i>",
                    kb_confirm(cb("hist:clear_yes"), cb("hist:0")),
                )
                return await q.answer()
            if sub == "clear_yes":
                await _clear_history()
                text, kb = await view_history(0)
                await _safe_edit(q, text, kb)
                return await q.answer("🗑️ ᴄʟᴇᴀʀᴇᴅ")
            try:
                page = int(sub)
            except ValueError:
                page = 0
            text, kb = await view_history(page)
            await _safe_edit(q, text, kb)
            return await q.answer()

        # ── Stats ──
        if action == "stats":
            text, kb = await view_stats()
            await _safe_edit(q, text, kb)
            return await q.answer()

        # ── Auto-delete ──
        if action == "ad":
            sub = parts[1] if len(parts) > 1 else "panel"
            if sub == "panel":
                text, kb = await view_autodelete_panel()
                await _safe_edit(q, text, kb)
                return await q.answer()
            if sub == "purge":
                due = await _due_autodeletes(500)
                count = 0
                for d in due:
                    try:
                        await client.delete_messages(
                            chat_id=int(d["chat_id"]),
                            message_ids=int(d["message_id"]),
                        )
                        count += 1
                    except Exception:
                        pass
                    await _remove_autodelete(d["_id"])
                return await q.answer(f"🧹 ᴘᴜʀɢᴇᴅ {count}", show_alert=True)

        # ── Send / destination pickers ──
        if action == "send":
            sub = parts[1] if len(parts) > 1 else "users"
            _pend_set(q.from_user.id, "await_source", kind=sub)
            await _safe_edit(
                q,
                f"{F.EMO['brand']} <b>{F.fb('SEND TO ' + sub.upper())}</b>\n"
                f"{DIV}\n\n"
                f"<i>Forward or send a message to broadcast.</i>\n"
                f"<i>It can be media, text, or anything.</i>",
                kb_back("main"),
            )
            return await q.answer("📤 ꜱᴇɴᴅ ᴛʜᴇ ꜰɪʟᴇ")

        # ── Pick (from watcher) ──
        if action == "pick":
            sub = parts[1] if len(parts) > 1 else ""
            if sub == "no":
                sid = parts[2] if len(parts) > 2 else ""
                _sources.pop(sid, None)
                try:
                    await q.message.delete()
                except Exception:
                    pass
                return await q.answer("✖️ ᴄᴀɴᴄᴇʟʟᴇᴅ")

            sid = parts[2] if len(parts) > 2 else ""

            if sub == "ch":
                text, kb = await view_channel_picker(sid)
                await _safe_edit(q, text, kb)
                return await q.answer()

            if sub == "gr":
                return await _do_send(q, client, sid, "groups")

            if sub == "us":
                return await _do_send(q, client, sid, "users")

            if sub == "mn":
                _pend_set(
                    q.from_user.id, "manual_target", sid=sid, kind="manual"
                )
                await _safe_edit(
                    q,
                    f"{F.EMO['brand']} <b>{F.fb('MANUAL TARGET')}</b>\n"
                    f"{DIV}\n\n"
                    f"<i>Send the target chat id.</i>\n"
                    f"<code>-1001234567890</code>",
                    kb_back("main"),
                )
                return await q.answer("📝")

            if sub == "chall":
                channels = await _get_saved_channels()
                enabled = [c["chat_id"] for c in channels if c.get("enabled", True)]
                _pend_set(
                    q.from_user.id, "timer_pick",
                    sid=sid, kind="channel", target="all",
                )
                text, kb = await view_timer_picker(sid, "channel", "all")
                await _safe_edit(q, text, kb)
                return await q.answer()

            if sub == "ch1":
                cid = int(parts[3]) if len(parts) > 3 else 0
                _pend_set(
                    q.from_user.id, "timer_pick",
                    sid=sid, kind="channel", target=str(cid),
                )
                text, kb = await view_timer_picker(sid, "channel", str(cid))
                await _safe_edit(q, text, kb)
                return await q.answer()

            if sub == "timer":
                # pick:timer:<sid>:<kind>:<target>:<seconds>
                kind = parts[3] if len(parts) > 3 else "users"
                target = parts[4] if len(parts) > 4 else ""
                seconds = int(parts[5]) if len(parts) > 5 else 0

                if kind == "channel":
                    if target == "all":
                        channels = await _get_saved_channels()
                        targets = [
                            c["chat_id"] for c in channels
                            if c.get("enabled", True)
                        ]
                    else:
                        targets = [int(target)]
                    await _run_broadcast(
                        client, q, sid, "channel",
                        targets=targets, autodelete_seconds=seconds,
                    )
                else:
                    await _run_broadcast(
                        client, q, sid, kind,
                        autodelete_seconds=seconds,
                    )
                return

        # ── Back shortcuts ──
        if action == "back":
            sub = parts[1] if len(parts) > 1 else ""
            if sub == "pick":
                sid = parts[2] if len(parts) > 2 else ""
                text, kb = await view_destination_picker(sid)
                await _safe_edit(q, text, kb)
                return await q.answer()

        # ── Stop ──
        if action == "stop":
            jid = parts[1] if len(parts) > 1 else ""
            j = _get_job(jid)
            if j:
                j["cancel_flag"] = True
                return await q.answer("🛑 ᴄᴀɴᴄᴇʟʟɪɴɢ...")
            return await q.answer("⚠️ ɴᴏᴛ ꜰᴏᴜɴᴅ")

        # ── Export / Import ──
        if action == "io":
            sub = parts[1] if len(parts) > 1 else "export"
            if sub == "export":
                data = {
                    "channels": await _get_saved_channels(),
                    "caption": await _get_global_caption(),
                    "buttons": await _get_global_buttons(),
                    "exported_at": time.time(),
                }
                buf = BytesIO(json.dumps(data, indent=2, default=str).encode())
                buf.name = "broadcast_config.json"
                try:
                    await client.send_document(
                        chat_id=q.from_user.id,
                        document=buf,
                        caption=f"💾 {F.sc('broadcast config export')}",
                    )
                    return await q.answer("💾 ꜱᴇɴᴛ ᴛᴏ ᴘᴍ")
                except Exception as e:
                    return await q.answer(f"❌ {type(e).__name__}", show_alert=True)

            if sub == "import":
                _pend_set(q.from_user.id, "io_import")
                await _safe_edit(
                    q,
                    f"{F.EMO['brand']} <b>{F.fb('IMPORT CONFIG')}</b>\n"
                    f"{DIV}\n\n"
                    f"<i>Send the JSON file.</i>",
                    kb_back("main"),
                )
                return await q.answer("📥 ꜱᴇɴᴅ ꜰɪʟᴇ")

        return await q.answer()

    except Exception as e:
        logger.exception(f"[BC] router {data}: {e}")
        try:
            await q.answer(f"❌ {type(e).__name__}", show_alert=True)
        except Exception:
            pass


async def _do_send(q, client, sid, kind):
    """Route to timer picker (so auto-delete can be configured)."""
    _pend_set(
        q.from_user.id, "timer_pick",
        sid=sid, kind=kind, target="all",
    )
    text, kb = await view_timer_picker(sid, kind, "all")
    try:
        await q.message.edit_text(
            text, reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception:
        pass
    try:
        await q.answer()
    except Exception:
        pass


# ============================================================
# CHANNEL WATCHER — upload → destination picker
# ============================================================

@Client.on_message(
    filters.chat(BROADCAST_CHANNEL_ID) & ~filters.service
    if BROADCAST_CHANNEL_ID else filters.chat(0) & filters.outgoing,
    group=-8305,
)
async def bc_watcher(client: Client, message: Message):
    if not BROADCAST_CHANNEL_ID:
        return
    if message.chat.id != BROADCAST_CHANNEL_ID:
        return
    if message.from_user and not _is_admin(message.from_user.id):
        return

    sid = _register_source(message)
    text, kb = await view_destination_picker(sid)
    try:
        await client.send_message(
            chat_id=message.chat.id,
            text=text, reply_markup=kb,
            parse_mode=ParseMode.HTML,
            reply_to_message_id=message.id,
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.warning(f"[BC-WATCH] {e}")


# ============================================================
# TEXT INPUT HANDLER
# ============================================================

@Client.on_message(filters.private & filters.text, group=-9511)
async def bc_text_input(client: Client, message: Message):
    if not message.from_user or not _is_admin(message.from_user.id):
        return

    uid = message.from_user.id
    pending = _pend_get(uid)
    if not pending:
        return

    kind = pending.get("kind")

    try:
        # Channel add
        if kind == "ch_add":
            _pend_drop(uid)
            raw = message.text.strip()
            try:
                if raw.startswith("@"):
                    chat = await client.get_chat(raw)
                else:
                    cid = int(raw)
                    chat = await client.get_chat(cid)
                await _save_channel(
                    chat.id,
                    chat.title or str(chat.id),
                    chat.username,
                )
                text, kb = await view_channels(0)
                await message.reply_text(
                    text, reply_markup=kb,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
            except Exception as e:
                await message.reply_text(
                    f"❌ <code>{type(e).__name__}: {_esc(str(e))[:120]}</code>",
                    parse_mode=ParseMode.HTML,
                )
            return

        # Caption edit (global)
        if kind == "cap_edit_global":
            _pend_drop(uid)
            await _set_global_caption(message.text)
            text, kb = await view_caption_global()
            await message.reply_text(
                text, reply_markup=kb,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
            return

        # Caption edit (channel)
        if kind == "cap_edit_ch":
            _pend_drop(uid)
            cid = pending.get("chat_id")
            await _update_channel(cid, caption=message.text)
            res = await view_caption_channel(cid)
            if res:
                text, kb = res
                await message.reply_text(
                    text, reply_markup=kb,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
            return

        # Button add (global)
        if kind == "btn_add_global":
            _pend_drop(uid)
            if "|" not in message.text:
                await message.reply_text("❌ Use: <code>Name | https://url</code>",
                                         parse_mode=ParseMode.HTML)
                return
            name, url = [x.strip() for x in message.text.split("|", 1)]
            btns = await _get_global_buttons()
            btns.append({"name": name, "url": url})
            await _set_global_buttons(btns)
            text, kb = await view_buttons_global()
            await message.reply_text(
                text, reply_markup=kb,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
            return

        # Button add (channel)
        if kind == "btn_add_ch":
            _pend_drop(uid)
            cid = pending.get("chat_id")
            if "|" not in message.text:
                await message.reply_text("❌ Use: <code>Name | https://url</code>",
                                         parse_mode=ParseMode.HTML)
                return
            name, url = [x.strip() for x in message.text.split("|", 1)]
            ch = await _get_channel(cid)
            btns = list(ch.get("buttons") or []) if ch else []
            btns.append({"name": name, "url": url})
            await _update_channel(cid, buttons=btns)
            res = await view_buttons_channel(cid)
            if res:
                text, kb = res
                await message.reply_text(
                    text, reply_markup=kb,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
            return

        # Manual target
        if kind == "manual_target":
            _pend_drop(uid)
            try:
                tid = int(message.text.strip())
            except ValueError:
                await message.reply_text("❌ Invalid id")
                return
            sid = pending.get("sid")
            _pend_set(uid, "timer_pick", sid=sid, kind="channel", target=str(tid))
            text, kb = await view_timer_picker(sid, "channel", str(tid))
            await message.reply_text(
                text, reply_markup=kb,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
            return

        # Awaiting source for send:xxx
        if kind == "await_source":
            _pend_drop(uid)
            sub = pending.get("kind")
            # Re-pend: forward this message to bot, user will send file next
            _pend_set(uid, "await_source_file", kind=sub)
            await message.reply_text(
                f"{F.EMO['brand']} <b>{F.fb('NOW SEND THE FILE')}</b>\n"
                f"{DIV}\n\n"
                f"<i>Send / forward / upload the message to broadcast.</i>",
                parse_mode=ParseMode.HTML,
            )
            return

        return

    except Exception as e:
        logger.exception(f"[BC-TEXT] {kind}: {e}")
        try:
            await message.reply_text(
                f"❌ <code>{type(e).__name__}: {_esc(str(e))[:150]}</code>",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass


@Client.on_message(filters.private & ~filters.text & ~filters.service, group=-9511)
async def bc_media_input(client: Client, message: Message):
    if not message.from_user or not _is_admin(message.from_user.id):
        return
    uid = message.from_user.id
    pending = _pend_get(uid)
    if not pending:
        return
    if pending.get("kind") != "await_source_file":
        return

    _pend_drop(uid)
    sub = pending.get("kind") if False else "users"

    # Register this as source
    sid = _register_source(message)
    _pend_set(
        uid, "timer_pick",
        sid=sid, kind=sub, target="all",
    )
    text, kb = await view_timer_picker(sid, sub, "all")
    await message.reply_text(
        text, reply_markup=kb,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


@Client.on_message(filters.private & filters.document, group=-9510)
async def bc_import_file(client: Client, message: Message):
    if not message.from_user or not _is_admin(message.from_user.id):
        return
    uid = message.from_user.id
    pending = _pend_get(uid)
    if not pending or pending.get("kind") != "io_import":
        return

    _pend_drop(uid)
    try:
        path = await message.download()
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        channels = data.get("channels") or []
        for ch in channels:
            await _save_channel(
                int(ch.get("chat_id")),
                ch.get("title") or str(ch.get("chat_id")),
                ch.get("username"),
            )
            await _update_channel(
                int(ch.get("chat_id")),
                caption=ch.get("caption"),
                buttons=ch.get("buttons"),
                enabled=ch.get("enabled", True),
                primary=ch.get("primary", False),
            )
        if data.get("caption"):
            await _set_global_caption(data["caption"])
        if data.get("buttons") is not None:
            await _set_global_buttons(data["buttons"])
        await message.reply_text(
            f"✅ <b>{F.fb('IMPORTED')}</b>\n{DIV}\n\n"
            f"📢 {len(channels)} channel(s)",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        await message.reply_text(f"❌ <code>{type(e).__name__}</code>",
                                 parse_mode=ParseMode.HTML)


# ============================================================
# /broadcast COMMAND
# ============================================================

@Client.on_message(filters.command("broadcast") & filters.private, group=-9500)
async def cmd_broadcast(client: Client, message: Message):
    global _bot_client
    _bot_client = client

    if not message.from_user or not _is_admin(message.from_user.id):
        return

    text, kb = await view_main()
    await message.reply_text(
        text, reply_markup=kb,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


# ============================================================
# PUBLIC ENTRY — called from /admin → [📢 Broadcast]
# ============================================================

async def open_panel_for_admin(client: Client, q: CallbackQuery) -> None:
    """Called from /admin → [📢 Broadcast]."""
    global _bot_client
    _bot_client = client

    try:
        if not q.from_user or not _is_admin(q.from_user.id):
            return await q.answer("⛔ ᴀᴅᴍɪɴꜱ ᴏɴʟʏ", show_alert=True)

        text, kb = await view_main()
        await client.send_message(
            chat_id=q.from_user.id,
            text=text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        await q.answer("📢 ᴏᴘᴇɴɪɴɢ ɪɴ ᴘᴍ…")
    except Exception as e:
        logger.exception(f"[BC-ADMIN] {e}")
        try:
            await q.answer(f"❌ {type(e).__name__}", show_alert=True)
        except Exception:
            pass


def snapshot() -> Dict[str, Any]:
    return {
        "active_jobs": len(_jobs),
        "active_sources": len(_sources),
        "sessions": len(_sessions),
        "pending": len(_pending),
    }


__all__ = [
    "open_panel_for_admin",
    "cmd_broadcast",
    "bc_watcher",
    "snapshot",
]
