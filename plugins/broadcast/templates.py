# ============================================================
# 🏨 DOWNTOWN VILLA — BROADCAST TEMPLATES
# ============================================================
#
# Caption + button templates (global + per-channel).
#
# Global default stored in SYSTEM DB → broadcast_settings
#
# ============================================================

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger(__name__)

SETTINGS_COLL = "broadcast_settings"
GLOBAL_ID = "global"


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


def _coll():
    try:
        from database import db_registry
        db = db_registry.get_system_db()
        if db is None:
            return None
        return db[SETTINGS_COLL]
    except Exception:
        return None


# ============================================================
# GLOBAL CAPTION
# ============================================================

async def get_caption() -> str:
    c = _coll()
    if c is None:
        return DEFAULT_CAPTION
    try:
        d = await c.find_one({"_id": GLOBAL_ID}) or {}
        return d.get("caption") or DEFAULT_CAPTION
    except Exception:
        return DEFAULT_CAPTION


async def set_caption(text: str) -> bool:
    c = _coll()
    if c is None:
        return False
    try:
        await c.update_one(
            {"_id": GLOBAL_ID},
            {"$set": {
                "caption": text,
                "updated_at": datetime.utcnow(),
            }},
            upsert=True,
        )
        return True
    except Exception:
        return False


# ============================================================
# GLOBAL BUTTONS
# ============================================================

async def get_buttons() -> List[Dict[str, Any]]:
    c = _coll()
    if c is None:
        return []
    try:
        d = await c.find_one({"_id": GLOBAL_ID}) or {}
        return list(d.get("buttons") or [])
    except Exception:
        return []


async def set_buttons(buttons: List[Dict[str, Any]]) -> bool:
    c = _coll()
    if c is None:
        return False
    try:
        await c.update_one(
            {"_id": GLOBAL_ID},
            {"$set": {
                "buttons": list(buttons),
                "updated_at": datetime.utcnow(),
            }},
            upsert=True,
        )
        return True
    except Exception:
        return False


# ============================================================
# BUILD CAPTION
# ============================================================

def build_caption(message, template: str) -> str:
    """Render a caption for a message using template."""
    try:
        file_name = "file"
        file_size_str = "0 B"
        file_caption = message.caption or ""

        for attr in ("video", "document", "audio", "photo", "animation"):
            m = getattr(message, attr, None)
            if m:
                file_name = (
                    getattr(m, "file_name", None)
                    or file_caption[:80]
                    or "file"
                )
                size = getattr(m, "file_size", 0) or 0
                file_size_str = _human(size)
                break

        year = ""
        import re
        mm = re.search(r"\b(19[3-9]\d|20[0-4]\d)\b", file_name)
        if mm:
            year = mm.group(1)

        return template.format(
            file_name=file_name[:100],
            file_size=file_size_str,
            rating="—",
            year=year or "—",
            file_caption=file_caption[:200] if file_caption else "—",
        )
    except Exception:
        return template


def _human(size) -> str:
    try:
        s = float(size or 0)
    except (TypeError, ValueError):
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while s >= 1024 and i < len(units) - 1:
        s /= 1024
        i += 1
    return f"{s:.2f} {units[i]}"


# ============================================================
# BUILD BUTTONS
# ============================================================

def build_buttons_kb(buttons: List[Dict[str, Any]]) -> Optional[InlineKeyboardMarkup]:
    if not buttons:
        return None
    rows: List[List[InlineKeyboardButton]] = []
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


__all__ = [
    "DEFAULT_CAPTION", "CAPTION_TEMPLATES",
    "get_caption", "set_caption", "get_buttons", "set_buttons",
    "build_caption", "build_buttons_kb",
]
