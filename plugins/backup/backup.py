# ============================================================
# 🏨 DOWNTOWN VILLA — BACKUP CHANNEL MANAGER (IN-PANEL)
# ============================================================
#
# Channel management is INSIDE the /backup panel.
# No separate command.
#
# Exposed as:
#   open_channels_panel(client, q_or_msg)   ← called from /backup
#   router_handler(client, q)               ← handles bch:* callbacks
#   text_handler(client, msg)               ← handles text input
#
# Two kinds of channels:
#   • BACKUP   — where files are copied (multiple allowed)
#   • STORAGE  — long-term archive (multiple allowed)
#
# Every action is a button. Zero commands.
#
# ============================================================

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from pyrogram import Client
from pyrogram.enums import ParseMode
from pyrogram.errors import (
    ChannelPrivate, PeerIdInvalid, UsernameInvalid, UsernameNotOccupied,
)
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from core import config
from utils import fonts as F
from utils import format as FM

logger = logging.getLogger(__name__)


# ============================================================
# SECTION 1 — CONSTANTS
# ============================================================

PFX = "bch"          # callback namespace
KIND_BACKUP = "backup"
KIND_STORAGE = "storage"


# ============================================================
# SECTION 2 — AUTH
# ============================================================

def _is_admin(uid) -> bool:
    try:
        return int(uid) in [int(a) for a in config.ADMINS]
    except Exception:
        return False


# ============================================================
# SECTION 3 — DB ACCESS (system DB → backup_channels)
# ============================================================

def _coll():
    try:
        from database import db_registry
        db = db_registry.get_system_db()
        if db is None:
            return None
        return db["backup_channels"]
    except Exception:
        return None


async def _list_channels(kind: Optional[str] = None) -> List[Dict[str, Any]]:
    c = _coll()
    if c is None:
        return []
    query = {}
    if kind:
        query["kind"] = kind
    try:
        cursor = c.find(query).sort([("primary", -1), ("added_at", 1)])
        docs = await cursor.to_list(length=200)
        for d in docs:
            d.pop("_id", None)
        return docs
    except Exception as e:
        logger.warning(f"[CH] list: {e}")
        return []


async def _get_channel(chat_id: int) -> Optional[Dict[str, Any]]:
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


async def _add_channel(
    chat_id: int,
    title: str,
    kind: str,
    added_by: int,
) -> bool:
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
                    "added_at": now,
                    "primary": False,
                    "enabled": True,
                    "added_by": int(added_by),
                },
                "$set": {
                    "title": str(title)[:120],
                    "kind": str(kind),
                    "updated_at": now,
                },
            },
            upsert=True,
        )
        return True
    except Exception as e:
        logger.warning(f"[CH] add: {e}")
        return False


async def _update_channel(chat_id: int, **fields) -> bool:
    c = _coll()
    if c is None:
        return False
    try:
        fields["updated_at"] = datetime.utcnow()
        r = await c.update_one(
            {"chat_id": int(chat_id)},
            {"$set": fields},
        )
        return r.matched_count > 0
    except Exception:
        return False


async def _remove_channel(chat_id: int) -> bool:
    c = _coll()
    if c is None:
        return False
    try:
        r = await c.delete_one({"chat_id": int(chat_id)})
        return r.deleted_count > 0
    except Exception:
        return False


async def _set_primary(chat_id: int, kind: str) -> bool:
    c = _coll()
    if c is None:
        return False
    try:
        await c.update_many(
            {"kind": str(kind), "chat_id": {"$ne": int(chat_id)}},
            {"$set": {"primary": False}},
        )
        await c.update_one(
            {"chat_id": int(chat_id)},
            {"$set": {"primary": True, "updated_at": datetime.utcnow()}},
        )
        return True
    except Exception:
        return False


async def _primary(kind: str) -> Optional[Dict[str, Any]]:
    c = _coll()
    if c is None:
        return None
    try:
        d = await c.find_one(
            {"kind": str(kind), "primary": True, "enabled": True}
        )
        if d:
            d.pop("_id", None)
            return d
        d = await c.find_one({"kind": str(kind), "enabled": True})
        if d:
            d.pop("_id", None)
            return d
        return None
    except Exception:
        return None


async def primary_backup_id() -> Optional[int]:
    d = await _primary(KIND_BACKUP)
    return int(d["chat_id"]) if d else None


async def primary_storage_id() -> Optional[int]:
    d = await _primary(KIND_STORAGE)
    return int(d["chat_id"]) if d else None


# ============================================================
# SECTION 4 — RESOLVE CHANNEL
# ============================================================

async def _resolve_channel(client: Client, text: str) -> Dict[str, Any]:
    out = {"ok": False, "chat_id": None, "title": "", "username": "",
           "error": ""}
    text = (text or "").strip()

    try:
        if text.startswith("@"):
            chat = await client.get_chat(text)
        else:
            try:
                chat_id = int(text)
            except ValueError:
                out["error"] = "send a channel id or @username"
                return out
            chat = await client.get_chat(chat_id)
    except UsernameInvalid:
        out["error"] = "invalid username"
        return out
    except UsernameNotOccupied:
        out["error"] = "username not found"
        return out
    except ChannelPrivate:
        out["error"] = "channel is private"
        return out
    except PeerIdInvalid:
        out["error"] = "add the bot to the channel first"
        return out
    except Exception as e:
        out["error"] = str(e)[:80]
        return out

    out["ok"] = True
    out["chat_id"] = int(chat.id)
    out["title"] = chat.title or str(chat.id)
    out["username"] = chat.username or ""
    return out


# ============================================================
# SECTION 5 — SESSIONS (text input state)
# ============================================================

_sessions: Dict[int, Dict[str, Any]] = {}
SESSION_TTL = 300.0


def _new_session(uid: int, action: str, **data) -> None:
    _sessions[int(uid)] = {
        "action": action,
        "expires": time.time() + SESSION_TTL,
        **data,
    }


def _get_session(uid: int) -> Optional[Dict[str, Any]]:
    s = _sessions.get(int(uid))
    if not s:
        return None
    if time.time() > s["expires"]:
        _sessions.pop(int(uid), None)
        return None
    return s


def _drop_session(uid: int) -> None:
    _sessions.pop(int(uid), None)


def has_session(uid: int) -> bool:
    return _get_session(uid) is not None


# ============================================================
# SECTION 6 — KEYBOARDS
# ============================================================

def _kb_home() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"💾 {F.sc('backup channels')}",
                callback_data=f"{PFX}:list:{KIND_BACKUP}",
            ),
            InlineKeyboardButton(
                f"📦 {F.sc('storage channels')}",
                callback_data=f"{PFX}:list:{KIND_STORAGE}",
            ),
        ],
        [
            InlineKeyboardButton(
                f"➕ {F.sc('add backup')}",
                callback_data=f"{PFX}:add:{KIND_BACKUP}",
            ),
            InlineKeyboardButton(
                f"➕ {F.sc('add storage')}",
                callback_data=f"{PFX}:add:{KIND_STORAGE}",
            ),
        ],
        [
            InlineKeyboardButton(
                f"{F.EMO['refresh']} {F.sc('refresh')}",
                callback_data=f"{PFX}:home",
            ),
            InlineKeyboardButton(
                f"{F.EMO['back']} {F.sc('back to backup')}",
                callback_data="dtvb:back",  # goes back to /backup main
            ),
        ],
        [
            InlineKeyboardButton(
                f"{F.EMO['cross']} {F.sc('close')}",
                callback_data="dtvb:close",
            ),
        ],
    ])


def _kb_list(kind: str, channels: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []

    for ch in channels:
        icon = "🟢" if ch.get("enabled") else "🔴"
        primary = "⭐ " if ch.get("primary") else ""
        title = str(ch.get("title", "?"))[:32]
        rows.append([InlineKeyboardButton(
            f"{primary}{icon} {title}",
            callback_data=f"{PFX}:view:{kind}:{ch['chat_id']}",
        )])

    rows.append([
        InlineKeyboardButton(
            f"➕ {F.sc('add new')}",
            callback_data=f"{PFX}:add:{kind}",
        ),
    ])
    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data=f"{PFX}:home",
        ),
        InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('close')}",
            callback_data="dtvb:close",
        ),
    ])
    return InlineKeyboardMarkup(rows)


def _kb_view(kind: str, chat_id: int, ch: Dict[str, Any]) -> InlineKeyboardMarkup:
    enabled = ch.get("enabled", True)
    primary = ch.get("primary", False)

    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"{'🔴 ' + F.sc('disable') if enabled else '🟢 ' + F.sc('enable')}",
                callback_data=f"{PFX}:toggle:{kind}:{chat_id}",
            ),
            InlineKeyboardButton(
                f"{'⭐ ' + F.sc('unset primary') if primary else '⭐ ' + F.sc('set primary')}",
                callback_data=f"{PFX}:primary:{kind}:{chat_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                f"✏️ {F.sc('rename')}",
                callback_data=f"{PFX}:rename:{kind}:{chat_id}",
            ),
            InlineKeyboardButton(
                f"🧪 {F.sc('test')}",
                callback_data=f"{PFX}:test:{kind}:{chat_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                f"🗑️ {F.sc('remove')}",
                callback_data=f"{PFX}:confirm_rm:{kind}:{chat_id}",
            ),
        ],
        [
            InlineKeyboardButton(
                f"{F.EMO['back']} {F.sc('back')}",
                callback_data=f"{PFX}:list:{kind}",
            ),
            InlineKeyboardButton(
                f"{F.EMO['cross']} {F.sc('close')}",
                callback_data="dtvb:close",
            ),
        ],
    ])


def _kb_cancel(target: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('cancel')}",
            callback_data=target,
        ),
    ]])


# ============================================================
# SECTION 7 — PANEL TEXT RENDERERS
# ============================================================

def _home_text(ch_backup: List[Dict[str, Any]],
               ch_storage: List[Dict[str, Any]]) -> str:
    bcount = len(ch_backup)
    scount = len(ch_storage)
    b_primary = next((c for c in ch_backup if c.get("primary")), None)
    s_primary = next((c for c in ch_storage if c.get("primary")), None)

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"{F.EMO['channel']} <b>{F.fb('CHANNEL MANAGER')}</b>",
        F.DIV,
        "",
        f"💾 <b>{F.sc('backup channels')}</b> · <b>{bcount}</b>",
    ]
    if b_primary:
        lines.append(
            f"   ⭐ {F.sc('primary')} · "
            f"<code>{str(b_primary.get('title', '?'))[:32]}</code>"
        )
    else:
        lines.append(f"   ⚪ {F.sc('no primary set')}")

    lines += [
        "",
        f"📦 <b>{F.sc('storage channels')}</b> · <b>{scount}</b>",
    ]
    if s_primary:
        lines.append(
            f"   ⭐ {F.sc('primary')} · "
            f"<code>{str(s_primary.get('title', '?'))[:32]}</code>"
        )
    else:
        lines.append(f"   ⚪ {F.sc('no primary set')}")

    lines += [
        "",
        F.DIV_S,
        f"📌 {F.sc('everything is editable from Telegram')}",
        f"📌 {F.sc('no env changes needed')}",
    ]
    return "\n".join(lines)


def _list_text(kind: str, channels: List[Dict[str, Any]]) -> str:
    icon = "💾" if kind == KIND_BACKUP else "📦"
    label = "Backup" if kind == KIND_BACKUP else "Storage"

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"{icon} <b>{F.fb(f'{label.upper()} CHANNELS')}</b>",
        F.DIV,
        "",
        f"📊 {F.sc('total')} · <b>{len(channels)}</b>",
        "",
        F.DIV_S,
        "",
    ]

    if not channels:
        lines.append(f"⚪ {F.sc('no channels yet')}")
        lines.append("")
        lines.append(f"📌 {F.sc('tap ADD NEW to add one')}")
        return "\n".join(lines)

    for i, ch in enumerate(channels, 1):
        enabled = ch.get("enabled", True)
        primary = ch.get("primary", False)
        title = str(ch.get("title", "?"))[:40]
        cid = ch.get("chat_id")

        status_icon = "🟢" if enabled else "🔴"
        star = "⭐ " if primary else ""

        lines.append(
            f"<b>{i:02d}.</b> {status_icon} {star}<b>{F.sc(title)}</b>"
        )
        lines.append(f"    🆔 <code>{cid}</code>")
        lines.append("")

    return "\n".join(lines)


def _view_text(kind: str, ch: Dict[str, Any]) -> str:
    icon = "💾" if kind == KIND_BACKUP else "📦"
    label = "Backup" if kind == KIND_BACKUP else "Storage"

    enabled = ch.get("enabled", True)
    primary = ch.get("primary", False)

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"{icon} <b>{F.fb('CHANNEL DETAIL')}</b>",
        F.DIV,
        "",
        f"📛 {F.sc('title')} · "
        f"<b>{F.sc(str(ch.get('title', '?'))[:40])}</b>",
        f"🏷️ {F.sc('kind')} · <code>{label}</code>",
        f"🆔 {F.sc('chat id')} · <code>{ch.get('chat_id')}</code>",
        "",
        f"⚙️ {F.sc('status')} · "
        f"{'🟢 ' + F.sc('enabled') if enabled else '🔴 ' + F.sc('disabled')}",
        f"⭐ {F.sc('primary')} · "
        f"{'🟢 yes' if primary else '🔴 no'}",
        "",
        F.DIV_S,
        "",
        f"📌 {F.sc('used for')} <b>{F.sc(label.lower())}</b> operations",
    ]

    added = ch.get("added_at")
    if added:
        try:
            ts = added.timestamp() if hasattr(added, "timestamp") else 0
            if ts:
                lines.append(
                    f"📅 {F.sc('added')} · "
                    f"<code>{FM.datetime_(datetime.fromtimestamp(ts))}</code>"
                )
        except Exception:
            pass

    return "\n".join(lines)


# ============================================================
# SECTION 8 — PUBLIC: OPEN PANEL (called from /backup)
# ============================================================

async def open_channels_panel(client: Client, q_or_msg) -> None:
    """
    Open the channel manager panel.
    Called from /backup panel via callback or message.
    """
    try:
        ch_backup = await _list_channels(KIND_BACKUP)
        ch_storage = await _list_channels(KIND_STORAGE)
        text = _home_text(ch_backup, ch_storage)

        # If it's a callback, edit the message
        if isinstance(q_or_msg, CallbackQuery):
            try:
                await q_or_msg.message.edit_text(
                    text,
                    reply_markup=_kb_home(),
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
            except Exception as e:
                if "not modified" not in str(e).lower():
                    logger.debug(f"[CH] edit: {e}")
            await q_or_msg.answer()
        else:
            # It's a Message
            await q_or_msg.reply_text(
                text,
                reply_markup=_kb_home(),
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
    except Exception as e:
        logger.exception(f"[CH] open panel: {e}")


# ============================================================
# SECTION 9 — PUBLIC: CALLBACK ROUTER
# ============================================================

async def router_handler(client: Client, q: CallbackQuery) -> bool:
    """
    Handle bch:* callbacks.
    Returns True if handled.
    """
    if not str(q.data or "").startswith(f"{PFX}:"):
        return False

    if not q.from_user or not _is_admin(q.from_user.id):
        await q.answer("❌ Admin only", show_alert=True)
        return True

    parts = str(q.data).split(":")
    action = parts[1] if len(parts) > 1 else ""

    try:
        # ────────── HOME ──────────
        if action == "home":
            ch_backup = await _list_channels(KIND_BACKUP)
            ch_storage = await _list_channels(KIND_STORAGE)
            text = _home_text(ch_backup, ch_storage)
            await _safe_edit(q, text, _kb_home())
            return True

        # ────────── LIST ──────────
        if action == "list":
            kind = parts[2] if len(parts) > 2 else KIND_BACKUP
            channels = await _list_channels(kind)
            text = _list_text(kind, channels)
            await _safe_edit(q, text, _kb_list(kind, channels))
            return True

        # ────────── VIEW ──────────
        if action == "view":
            kind = parts[2] if len(parts) > 2 else KIND_BACKUP
            cid = int(parts[3]) if len(parts) > 3 else 0
            ch = await _get_channel(cid)
            if ch is None:
                await q.answer("⚠️ Not found", show_alert=True)
                return True
            text = _view_text(kind, ch)
            await _safe_edit(q, text, _kb_view(kind, cid, ch))
            return True

        # ────────── TOGGLE ──────────
        if action == "toggle":
            kind = parts[2] if len(parts) > 2 else KIND_BACKUP
            cid = int(parts[3]) if len(parts) > 3 else 0
            ch = await _get_channel(cid)
            if ch is None:
                await q.answer("⚠️ Not found", show_alert=True)
                return True
            new_state = not ch.get("enabled", True)
            await _update_channel(cid, enabled=new_state)
            await q.answer("🟢 Enabled" if new_state else "🔴 Disabled")
            ch = await _get_channel(cid)
            text = _view_text(kind, ch)
            await _safe_edit(q, text, _kb_view(kind, cid, ch))
            return True

        # ────────── PRIMARY ──────────
        if action == "primary":
            kind = parts[2] if len(parts) > 2 else KIND_BACKUP
            cid = int(parts[3]) if len(parts) > 3 else 0
            ch = await _get_channel(cid)
            if ch is None:
                await q.answer("⚠️ Not found", show_alert=True)
                return True

            if ch.get("primary"):
                await _update_channel(cid, primary=False)
                await q.answer("⭐ Unset primary")
            else:
                await _set_primary(cid, kind)
                await q.answer("⭐ Set as primary")

            ch = await _get_channel(cid)
            text = _view_text(kind, ch)
            await _safe_edit(q, text, _kb_view(kind, cid, ch))
            return True

        # ────────── ADD ──────────
        if action == "add":
            kind = parts[2] if len(parts) > 2 else KIND_BACKUP
            _new_session(q.from_user.id, "add_channel", kind=kind)
            label = "Backup" if kind == KIND_BACKUP else "Storage"
            text = "\n".join([
                f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                f"➕ <b>{F.fb(f'ADD {label.upper()} CHANNEL')}</b>",
                F.DIV,
                "",
                f"📝 {F.sc('send the channel id or @username')}",
                "",
                F.DIV_S,
                "",
                f"📌 {F.sc('examples')}",
                f"• <code>-1001234567890</code>",
                f"• <code>@mychannel</code>",
                "",
                f"{F.EMO['warn']} {F.sc('bot must be admin in the channel')}",
            ])
            await _safe_edit(q, text, _kb_cancel(f"{PFX}:home"))
            return True

        # ────────── RENAME ──────────
        if action == "rename":
            kind = parts[2] if len(parts) > 2 else KIND_BACKUP
            cid = int(parts[3]) if len(parts) > 3 else 0
            _new_session(q.from_user.id, "rename", kind=kind, chat_id=cid)
            text = "\n".join([
                f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                f"✏️ <b>{F.fb('RENAME CHANNEL')}</b>",
                F.DIV,
                "",
                f"📝 {F.sc('send the new title')}",
                f"📌 {F.sc('max 60 characters')}",
            ])
            await _safe_edit(q, text, _kb_cancel(f"{PFX}:view:{kind}:{cid}"))
            return True

        # ────────── TEST ──────────
        if action == "test":
            kind = parts[2] if len(parts) > 2 else KIND_BACKUP
            cid = int(parts[3]) if len(parts) > 3 else 0
            ok = await _test_channel(client, cid)
            await q.answer(
                "✅ Message sent!" if ok else "❌ Failed to send",
                show_alert=True,
            )
            return True

        # ────────── CONFIRM REMOVE ──────────
        if action == "confirm_rm":
            kind = parts[2] if len(parts) > 2 else KIND_BACKUP
            cid = int(parts[3]) if len(parts) > 3 else 0
            text = "\n".join([
                f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                f"{F.EMO['warn']} <b>{F.fb('REMOVE CHANNEL?')}</b>",
                F.DIV,
                "",
                f"🆔 <code>{cid}</code>",
                "",
                f"{F.EMO['warn']} {F.sc('only removes from manager')}",
                f"{F.EMO['info']} {F.sc('Telegram channel stays intact')}",
            ])
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    f"🗑️ {F.sc('yes, remove')}",
                    callback_data=f"{PFX}:do_rm:{kind}:{cid}",
                )],
                [InlineKeyboardButton(
                    f"{F.EMO['back']} {F.sc('cancel')}",
                    callback_data=f"{PFX}:view:{kind}:{cid}",
                )],
            ])
            await _safe_edit(q, text, kb)
            return True

        # ────────── DO REMOVE ──────────
        if action == "do_rm":
            kind = parts[2] if len(parts) > 2 else KIND_BACKUP
            cid = int(parts[3]) if len(parts) > 3 else 0
            ok = await _remove_channel(cid)
            await q.answer("✅ Removed" if ok else "⚠️ Not found")
            channels = await _list_channels(kind)
            text = _list_text(kind, channels)
            await _safe_edit(q, text, _kb_list(kind, channels))
            return True

        return False

    except Exception as e:
        logger.exception(f"[CH] callback error: {e}")
        try:
            await q.answer(f"❌ {type(e).__name__}", show_alert=True)
        except Exception:
            pass
        return True


# ============================================================
# SECTION 10 — PUBLIC: TEXT INPUT HANDLER
# ============================================================

async def text_handler(client: Client, message: Message) -> bool:
    """
    Handle text input for add / rename.
    Returns True if handled (caller should stop_propagation).
    """
    if not message.from_user or not _is_admin(message.from_user.id):
        return False

    s = _get_session(message.from_user.id)
    if not s:
        return False

    action = s.get("action")
    if action not in ("add_channel", "rename"):
        return False

    text = (message.text or "").strip()
    if not text:
        return False

    # ────────── ADD ──────────
    if action == "add_channel":
        kind = s.get("kind", KIND_BACKUP)
        resolved = await _resolve_channel(client, text)
        _drop_session(message.from_user.id)

        if not resolved["ok"]:
            await message.reply_text(
                f"{F.EMO['cross']} <b>{F.fb('FAILED')}</b>\n"
                f"<i>{F.sc(resolved.get('error', '?'))}</i>",
                parse_mode=ParseMode.HTML,
            )
            return True

        ok = await _add_channel(
            chat_id=resolved["chat_id"],
            title=resolved["title"],
            kind=kind,
            added_by=message.from_user.id,
        )

        if not ok:
            await message.reply_text(
                f"{F.EMO['cross']} {F.sc('could not save')}",
                parse_mode=ParseMode.HTML,
            )
            return True

        # Auto-test
        await _test_channel(client, resolved["chat_id"])

        label = "Backup" if kind == KIND_BACKUP else "Storage"
        await message.reply_text(
            "\n".join([
                f"{F.EMO['check']} <b>{F.fb('CHANNEL ADDED')}</b>",
                F.DIV,
                "",
                f"📛 <b>{F.sc(resolved['title'][:40])}</b>",
                f"🆔 <code>{resolved['chat_id']}</code>",
                f"🏷️ {F.sc('kind')} · <code>{label}</code>",
                "",
                f"{F.EMO['spark']} {F.sc('test message sent')}",
                "",
                F.DIV_S,
                f"📌 {F.sc('open /backup → channels to manage')}",
            ]),
            parse_mode=ParseMode.HTML,
        )
        return True

    # ────────── RENAME ──────────
    if action == "rename":
        cid = int(s.get("chat_id", 0))
        _drop_session(message.from_user.id)

        if len(text) < 2:
            await message.reply_text(
                f"{F.EMO['cross']} {F.sc('too short')}",
                parse_mode=ParseMode.HTML,
            )
            return True

        ok = await _update_channel(cid, title=text[:60])
        await message.reply_text(
            f"{F.EMO['check'] if ok else F.EMO['cross']} "
            f"{F.sc('renamed') if ok else F.sc('failed')}",
            parse_mode=ParseMode.HTML,
        )
        return True

    return False


# ============================================================
# SECTION 11 — HELPERS
# ============================================================

async def _test_channel(client: Client, chat_id: int) -> bool:
    try:
        await client.send_message(
            chat_id=chat_id,
            text=(
                f"{F.EMO['check']} <b>{F.fb('CHANNEL TEST')}</b>\n"
                f"{F.DIV}\n"
                f"<i>{F.sc('if you see this, the bot can post here.')}</i>"
            ),
            parse_mode=ParseMode.HTML,
        )
        return True
    except Exception as e:
        logger.warning(f"[CH] test failed: {e}")
        return False


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
            logger.debug(f"[CH] edit: {e}")


# ============================================================
# SECTION 12 — SNAPSHOT
# ============================================================

async def snapshot() -> Dict[str, Any]:
    b = await _list_channels(KIND_BACKUP)
    s = await _list_channels(KIND_STORAGE)
    return {
        "backup_channels": len(b),
        "storage_channels": len(s),
        "primary_backup": await primary_backup_id(),
        "primary_storage": await primary_storage_id(),
    }


# ============================================================
# PUBLIC EXPORTS
# ============================================================

__all__ = [
    # Called from /backup
    "open_channels_panel",
    "router_handler",
    "text_handler",
    "has_session",
    # Helpers
    "primary_backup_id",
    "primary_storage_id",
    "snapshot",
]
