# ============================================================
# 🏨 DOWNTOWN VILLA — AUTO FILTER (PM SEARCH)
# ============================================================
#
# DEPRECATED — PM search text is now handled by
# plugins.pm_search.handlers.pm_text_handler.
#
# This file only keeps the /pm_search toggle command.
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
        from plugins.pm_search import state as CFG
        cfg = await CFG.get_cfg()
        return bool(cfg.get("enabled", True))
    except Exception:
        pass
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
# HANDLER — DISABLED
# ============================================================
#
# New PM search flow lives in plugins/pm_search/handlers.py.
# This handler is a no-op to avoid double replies.
#
# ============================================================

@Client.on_message(
    filters.private
    & filters.text
    & ~filters.regex(r"^/")
    & ~filters.regex(r"^sr:")
    & ~filters.regex(r"^pms:")
    & ~filters.regex(r"^pmsa:")
    & ~filters.regex(r"^idx:")
    & ~filters.regex(r"^dtvb:")
    & ~filters.regex(r"^adm:"),
    group=-500,
)
async def pm_text_handler(client: Client, message: Message):
    """Deprecated — plugins.pm_search.handlers handles PM text now."""
    return


# ============================================================
# /pm_search toggle (admin) — legacy quick toggle
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
            f"ᴜꜱᴀɢᴇ: <code>/pm_search on</code> ᴏʀ <code>off</code>\n"
            f"📌 ꜰᴜʟʟ ᴘᴀɴᴇʟ · <code>/pmsearch</code>",
            parse_mode=ParseMode.HTML,
        )

    enable = parts[1].strip().lower() in ("on", "true")

    # Save to new config
    saved = False
    try:
        from plugins.pm_search import state as CFG
        await CFG.set_cfg(enabled=enable)
        saved = True
    except Exception as e:
        logger.debug(f"[PM-SEARCH] cfg save: {e}")

    # Keep legacy doc in sync
    try:
        from database import db_registry
        db = db_registry.get_system_db()
        if db is not None:
            await db["bot_settings"].update_one(
                {"_id": "pm_search"},
                {"$set": {"enabled": enable}},
                upsert=True,
            )
            saved = True
    except Exception as e:
        logger.debug(f"[PM-SEARCH] legacy save: {e}")

    if not saved:
        return await message.reply_text("❌ Save failed")

    await message.reply_text(
        f"{F.EMO['check']} ᴘᴍ ꜱᴇᴀʀᴄʜ · "
        f"<b>{'ᴏɴ' if enable else 'ᴏꜰꜰ'}</b>",
        parse_mode=ParseMode.HTML,
    )


__all__ = ["pm_text_handler", "cmd_pm_search"]
