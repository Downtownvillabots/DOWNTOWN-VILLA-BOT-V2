# ============================================================
# 🏨 DOWNTOWN VILLA — PM SEARCH CONFIG
# ============================================================

from __future__ import annotations
import logging, time
from typing import Any, Dict

logger = logging.getLogger(__name__)

COLL = "pm_search_config"
CFG_ID = "global"


DEFAULT_CFG: Dict[str, Any] = {
    "enabled": True,

    # ── File list ──
    "per_row": 2,
    "max_buttons": 15,
    "sort_order": "small_to_big",
    "show_quality": True,
    "show_size": True,
    "show_languages": True,
    "show_file_name": False,

    # ── Poster card ──
    "show_poster": True,
    "show_rating": True,
    "show_year": True,
    "show_overview": True,

    # ── Suggestions ──
    "suggestion_enabled": True,
    "suggestion_count": 6,

    # ── Request ──
    "request_enabled": True,

    # ── Delivered caption ──
    "caption_template": (
        "🎬 <b>{title}</b>\n"
        "📁 {file_name}\n"
        "📅 {year}\n"
        "🎞️ {quality}\n"
        "🧬 {codec}\n"
        "🔊 {audio}\n"
        "📝 {subtitle}\n"
        "💾 {size}\n\n"
        "⚡ <b>DOWNTOWN VILLA</b>"
    ),

    # ── Delivered buttons ──
    "delivered_buttons": [
        {"name": "📢 Updates", "url": "https://t.me/", "enabled": True},
        {"name": "💬 Support", "url": "https://t.me/", "enabled": True},
    ],
    "delivered_buttons_per_row": 2,
    "share_button": True,

    # ── Auto-delete ──
    "auto_delete_enabled": False,
    "auto_delete_minutes": 10,
    "auto_delete_warning": (
        "⚠️ <b>This file will be deleted in {minutes} minutes</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📌 Please <b>forward this file</b> to your Saved Messages\n"
        "📌 Or share it with anyone you want\n"
        "📌 Once deleted, you'll need to search again"
    ),

    # ── Force-sub ──
    "fsub_enabled": False,
    "fsub_channels": [],
    "fsub_title": "🔒 JOIN REQUIRED",
    "fsub_message": (
        "🔒 <b>You must join our channels</b>\n"
        "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
        "📌 Join all the channels below\n"
        "📌 Then tap <b>Try Again</b> to get the file"
    ),
    "fsub_join_label": "🔔 JOIN",
    "fsub_try_label": "🔄 TRY AGAIN",

    "updated_at": None,
}


def _coll():
    try:
        from database import db_registry
        db = db_registry.get_system_db()
        return db[COLL] if db is not None else None
    except Exception as e:
        logger.debug(f"[PM-CFG] coll: {e}")
        return None


async def get_cfg() -> Dict[str, Any]:
    c = _coll()
    if c is None:
        return dict(DEFAULT_CFG)
    try:
        doc = await c.find_one({"_id": CFG_ID}) or {}
        out = dict(DEFAULT_CFG)
        out.update({k: v for k, v in doc.items() if k != "_id"})
        return out
    except Exception as e:
        logger.warning(f"[PM-CFG] load: {e}")
        return dict(DEFAULT_CFG)


async def set_cfg(**fields) -> bool:
    c = _coll()
    if c is None:
        return False
    try:
        fields["updated_at"] = time.time()
        await c.update_one({"_id": CFG_ID}, {"$set": fields}, upsert=True)
        return True
    except Exception as e:
        logger.warning(f"[PM-CFG] save: {e}")
        return False


async def reset_cfg() -> bool:
    c = _coll()
    if c is None:
        return False
    try:
        await c.delete_one({"_id": CFG_ID})
        return True
    except Exception:
        return False


__all__ = ["DEFAULT_CFG", "get_cfg", "set_cfg", "reset_cfg"]
