# ============================================================
# 🏨 DOWNTOWN VILLA — BROADCAST CHANNELS
# ============================================================
#
# Channel CRUD + per-channel caption/buttons storage.
#
# Each channel doc:
#   {
#     chat_id, title, username, enabled, primary,
#     caption: str | None,   # None = use global default
#     buttons: list | None,  # None = use global default
#   }
#
# ============================================================

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from pyrogram.errors import (
    ChannelPrivate, PeerIdInvalid, UsernameInvalid, UsernameNotOccupied,
)

logger = logging.getLogger(__name__)

COLL = "broadcast_channels"


def _coll():
    try:
        from database import db_registry
        db = db_registry.get_system_db()
        return db[COLL] if db is not None else None
    except Exception:
        return None


# ============================================================
# CRUD
# ============================================================

async def add_channel(
    chat_id: int,
    title: str,
    username: str = "",
    added_by: int = 0,
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
                    "added_by": int(added_by),
                    "enabled": True,
                    "primary": False,
                    "caption": None,
                    "buttons": None,
                },
                "$set": {
                    "title": str(title)[:120],
                    "username": str(username)[:64] or None,
                    "updated_at": now,
                },
            },
            upsert=True,
        )
        return True
    except Exception as e:
        logger.warning(f"[BC-CH] add: {e}")
        return False


async def list_channels() -> List[Dict[str, Any]]:
    c = _coll()
    if c is None:
        return []
    try:
        cursor = c.find({}).sort([("primary", -1), ("added_at", 1)])
        docs = await cursor.to_list(length=200)
        for d in docs:
            d.pop("_id", None)
        return docs
    except Exception:
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


async def update_channel(chat_id: int, **fields) -> bool:
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


async def remove_channel(chat_id: int) -> bool:
    c = _coll()
    if c is None:
        return False
    try:
        r = await c.delete_one({"chat_id": int(chat_id)})
        return r.deleted_count > 0
    except Exception:
        return False


async def set_primary(chat_id: int) -> bool:
    c = _coll()
    if c is None:
        return False
    try:
        await c.update_many(
            {"chat_id": {"$ne": int(chat_id)}},
            {"$set": {"primary": False}},
        )
        await c.update_one(
            {"chat_id": int(chat_id)},
            {"$set": {"primary": True, "updated_at": datetime.utcnow()}},
        )
        return True
    except Exception:
        return False


# ============================================================
# PER-CHANNEL CAPTION / BUTTONS
# ============================================================

async def set_caption(chat_id: int, caption: Optional[str]) -> bool:
    """Set (or clear with None) a channel's custom caption."""
    return await update_channel(chat_id, caption=caption)


async def set_buttons(chat_id: int, buttons: Optional[List[Dict]]) -> bool:
    """Set (or clear with None) a channel's custom buttons."""
    return await update_channel(chat_id, buttons=buttons)


async def reset_overrides(chat_id: int) -> bool:
    return await update_channel(chat_id, caption=None, buttons=None)


async def effective_caption(chat_id: int) -> str:
    ch = await get_channel(chat_id)
    if ch and ch.get("caption") is not None:
        return ch["caption"]
    try:
        from plugins.broadcast import templates as T
        return await T.get_caption()
    except Exception:
        return ""


async def effective_buttons(chat_id: int) -> List[Dict[str, Any]]:
    ch = await get_channel(chat_id)
    if ch and ch.get("buttons") is not None:
        return list(ch["buttons"])
    try:
        from plugins.broadcast import templates as T
        return await T.get_buttons()
    except Exception:
        return []


# ============================================================
# RESOLVE
# ============================================================

async def resolve_target(client, text: str) -> Dict[str, Any]:
    out = {"ok": False, "chat_id": None, "title": "",
           "username": "", "error": ""}
    text = (text or "").strip()
    try:
        if text.startswith("@"):
            chat = await client.get_chat(text)
        else:
            try:
                cid = int(text)
            except ValueError:
                out["error"] = "send channel id or @username"
                return out
            chat = await client.get_chat(cid)
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
        out["error"] = "add bot to the channel first"
        return out
    except Exception as e:
        out["error"] = str(e)[:80]
        return out

    out["ok"] = True
    out["chat_id"] = int(chat.id)
    out["title"] = chat.title or str(chat.id)
    out["username"] = chat.username or ""
    return out


async def test_channel(client, chat_id: int) -> bool:
    try:
        from utils import fonts as F
        from pyrogram.enums import ParseMode
        await client.send_message(
            chat_id=chat_id,
            text=(
                f"{F.EMO['check']} <b>{F.fb('BROADCAST TEST')}</b>\n"
                f"<i>if you see this, the bot can post here.</i>"
            ),
            parse_mode=ParseMode.HTML,
        )
        return True
    except Exception as e:
        logger.warning(f"[BC-CH] test: {e}")
        return False


__all__ = [
    "add_channel", "list_channels", "get_channel",
    "update_channel", "remove_channel", "set_primary",
    "set_caption", "set_buttons", "reset_overrides",
    "effective_caption", "effective_buttons",
    "resolve_target", "test_channel",
]
