# ============================================================
# 🏨 DOWNTOWN VILLA — MISSING TEMPLATES
# ============================================================
#
# Fully customizable captions + buttons for missing finder.
# ============================================================

from __future__ import annotations
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger(__name__)

SETTINGS_COLL = "missing_templates"


def _coll():
    try:
        from database import db_registry
        db = db_registry.get_system_db()
        return db[SETTINGS_COLL] if db is not None else None
    except Exception:
        return None


# ── DEFAULT TEMPLATES ──
DEFAULT_HEADER = (
    "🏨 <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>\n"
    "🔍 <b>𝗠𝗜𝗦𝗦𝗜𝗡𝗚 {TYPE}</b>\n"
    "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
    "📅 𝗣𝗲𝗿𝗶𝗼𝗱 · <code>{PERIOD}</code>\n"
    "🌍 𝗜𝗻𝗱𝘂𝘀𝘁𝗿𝘆 · <b>{INDUSTRY}</b>\n\n"
    "📥 𝗙𝗲𝘁𝗰𝗵𝗲𝗱 · <code>{FETCHED}</code>\n"
    "✅ 𝗜𝗻 𝗬𝗼𝘂𝗿 𝗗𝗕 · <code>{IN_DB}</code>\n"
    "❌ 𝗠𝗶𝘀𝘀𝗶𝗻𝗴 · <code>{MISSING}</code>\n"
)

DEFAULT_FOOTER = (
    "\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
    "📌 <i>Copy any name and search it anywhere</i>\n"
    "🕒 <code>{TIME}</code>"
)

DEFAULT_ITEM_LINE = "<b>{N}.</b>\n<code>{NAME}</code>\n{STARS} {POP} {LANG}\n"


TEMPLATES = {
    "default": {
        "header": DEFAULT_HEADER,
        "footer": DEFAULT_FOOTER,
        "item_line": DEFAULT_ITEM_LINE,
    },
    "minimal": {
        "header": "🔍 <b>MISSING {TYPE}</b> · {PERIOD}\n\n",
        "footer": "\n<code>{TIME}</code>",
        "item_line": "{N}. <code>{NAME}</code>\n",
    },
    "fancy": {
        "header": (
            "╔══════════════════════════╗\n"
            "║ 🏨 <b>DOWNTOWN VILLA</b>      ║\n"
            "║ 🔍 <b>MISSING {TYPE}</b>          ║\n"
            "╚══════════════════════════╝\n\n"
            "📅 {PERIOD}\n🌍 {INDUSTRY}\n\n"
            "📥 <code>{FETCHED}</code> · ✅ <code>{IN_DB}</code> · ❌ <code>{MISSING}</code>\n"
        ),
        "footer": "\n━━━━━━━━━━━━━━━━━━━━━━━━━━\n🕒 <code>{TIME}</code>",
        "item_line": "▫️ <b>{N}.</b> <code>{NAME}</code>\n",
    },
}


# ── GET / SET ──
async def get_template(key: str = "template") -> Optional[Dict[str, Any]]:
    c = _coll()
    if c is None: return None
    try:
        d = await c.find_one({"_id": key})
        if d: d.pop("_id", None)
        return d
    except Exception:
        return None


async def set_template(key: str, value: Dict[str, Any]) -> bool:
    c = _coll()
    if c is None: return False
    try:
        value["updated_at"] = datetime.utcnow()
        await c.update_one({"_id": key}, {"$set": value}, upsert=True)
        return True
    except Exception:
        return False


# ── BUTTONS ──
async def get_buttons() -> List[Dict[str, Any]]:
    c = _coll()
    if c is None: return []
    try:
        d = await c.find_one({"_id": "buttons"})
        return list(d.get("list") or []) if d else []
    except Exception:
        return []


async def set_buttons(buttons: List[Dict[str, Any]]) -> bool:
    c = _coll()
    if c is None: return False
    try:
        await c.update_one(
            {"_id": "buttons"},
            {"$set": {"list": buttons, "updated_at": datetime.utcnow()}},
            upsert=True,
        )
        return True
    except Exception:
        return False


def build_button_kb(buttons: List[Dict]) -> Optional[InlineKeyboardMarkup]:
    if not buttons: return None
    rows: List[List[InlineKeyboardButton]] = []
    for b in buttons:
        name = (b.get("name") or "").strip()
        url = (b.get("url") or "").strip()
        if not name or not url: continue
        if url.startswith("@"): url = f"https://t.me/{url[1:]}"
        elif not (url.startswith("http://") or url.startswith("https://") or url.startswith("tg://")):
            if "." in url and " " not in url: url = f"https://{url}"
            else: continue
        rows.append([InlineKeyboardButton(name[:60], url=url)])
    return InlineKeyboardMarkup(rows) if rows else None


# ── RENDER ──
def render_header(t: Dict[str, Any], ctx: Dict[str, Any]) -> str:
    try:
        return t.get("header", DEFAULT_HEADER).format(**ctx)
    except Exception:
        return DEFAULT_HEADER


def render_item(t: Dict[str, Any], ctx: Dict[str, Any]) -> str:
    try:
        return t.get("item_line", DEFAULT_ITEM_LINE).format(**ctx)
    except Exception:
        return DEFAULT_ITEM_LINE


def render_footer(t: Dict[str, Any], ctx: Dict[str, Any]) -> str:
    try:
        return t.get("footer", DEFAULT_FOOTER).format(**ctx)
    except Exception:
        return DEFAULT_FOOTER


__all__ = [
    "TEMPLATES", "DEFAULT_HEADER", "DEFAULT_FOOTER", "DEFAULT_ITEM_LINE",
    "get_template", "set_template",
    "get_buttons", "set_buttons", "build_button_kb",
    "render_header", "render_item", "render_footer",
]
