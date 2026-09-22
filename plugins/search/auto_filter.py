# ============================================================
# 🏨 DOWNTOWN VILLA — AUTO FILTER (PM SEARCH)
# ============================================================
#
# Every non-command PM text triggers a search.
# Uses core/flow_engine for the pm_search flow.
#
# TOGGLE:
#   • bot_settings.pm_search (via /pm_search)
#
# ============================================================

from __future__ import annotations

import logging
import time
from typing import Any, Dict

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import Message

from core import config
from utils import fonts as F

logger = logging.getLogger(__name__)


PM_COOLDOWN = 2.0
_last_seen: Dict[int, float] = {}


def _is_admin(uid) -> bool:
    try:
        return int(uid) in [int(a) for a in config.ADMINS]
    except Exception:
        return False


async def _is_pm_search_enabled() -> bool:
    try:
        from database import db_registry
        db = db_registry.get_system_db()
        if db is None:
            return True
        doc = await db["bot_settings"].find_one({"_id": "pm_search"})
        if doc and "enabled" in doc:
            return bool(doc["enabled"])
    except Exception:
        pass
    return bool(getattr(config, "PM_SEARCH_ENABLED", True))


# ============================================================
# HANDLER
# ============================================================

@Client.on_message(
    filters.private
    & filters.text
    & ~filters.regex(r"^/")
    & ~filters.regex(r"^sr:")
    & ~filters.regex(r"^idx:")
    & ~filters.regex(r"^dtvb:")
    & ~filters.regex(r"^adm:"),
    group=-500,
)
async def pm_text_handler(client: Client, message: Message):
    """Any PM text triggers a search flow."""
    try:
        if not message.from_user:
            return

        txt = (message.text or "").strip()
        if not txt or len(txt) < 2 or len(txt) > 120:
            return
        if "http://" in txt.lower() or "https://" in txt.lower():
            return

        # PM search gate
        if not await _is_pm_search_enabled():
            return

        # Cooldown
        uid = message.from_user.id
        now = time.time()
        if now - _last_seen.get(uid, 0) < PM_COOLDOWN:
            return
        _last_seen[uid] = now

        # Start the flow
        from plugins.search import handlers as H
        started = await H.start_search(
            client=client,
            user_id=uid,
            chat_id=message.chat.id,
            query=txt,
            is_group=False,
            message=message,
        )
        if started:
            H.track_search_event()

        try:
            message.stop_propagation()
        except Exception:
            pass

    except Exception as e:
        logger.exception(f"[PM-SEARCH] handler: {e}")


# ============================================================
# /pm_search toggle (admin)
# ============================================================

@Client.on_message(
    filters.command(["pm_search"]) & filters.private,
    group=-499,
)
async def cmd_pm_search(client: Client, message: Message):
    if not message.from_user or not _is_admin(message.from_user.id):
        return await message.reply_text(
            f"{F.EMO['cross']} {F.sc('admins only')}",
            parse_mode=ParseMode.HTML,
        )

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or parts[1].strip().lower() not in (
        "on", "off", "true", "false"
    ):
        return await message.reply_text(
            f"ᴜꜱᴀɢᴇ: <code>/pm_search on</code> ᴏʀ <code>off</code>",
            parse_mode=ParseMode.HTML,
        )

    enable = parts[1].strip().lower() in ("on", "true")
    try:
        from database import db_registry
        db = db_registry.get_system_db()
        await db["bot_settings"].update_one(
            {"_id": "pm_search"},
            {"$set": {"enabled": enable}},
            upsert=True,
        )
        await message.reply_text(
            f"{F.EMO['check']} ᴘᴍ ꜱᴇᴀʀᴄʜ · "
            f"<b>{'ᴏɴ' if enable else 'ᴏꜰꜰ'}</b>",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        await message.reply_text(f"❌ {e}")


__all__ = ["pm_text_handler", "cmd_pm_search"]
