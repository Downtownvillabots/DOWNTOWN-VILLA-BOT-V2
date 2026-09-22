# ============================================================
# 🏨 DOWNTOWN VILLA — MISSING TEMPLATES (FANCY)
# ============================================================
#
# Fully customizable captions + buttons for missing finder.
# Static labels are pre-rendered with fancy fonts.
# Dynamic values ({PERIOD}, {MISSING}, etc.) are placeholders.
#
# ============================================================

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from utils import fonts as F

logger = logging.getLogger(__name__)

SETTINGS_COLL = "missing_templates"


def _coll():
    try:
        from database import db_registry
        db = db_registry.get_system_db()
        return db[SETTINGS_COLL] if db is not None else None
    except Exception:
        return None


# ============================================================
# DEFAULT TEMPLATES
# ============================================================
#
# IMPORTANT: inside these strings, any `{...}` will be replaced
# by .format() at render time. Static labels use F.sc()/F.fb()
# and are pre-baked into the string at import time.
#
# ============================================================

DEFAULT_HEADER = (
    f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>\n"
    f"🔍 <b>{F.fb('MISSING')} {{TYPE}}</b>\n"
    f"{F.DIV}\n"
    f"\n"
    f"📅 {F.sc('period')} · <code>{{PERIOD}}</code>\n"
    f"🌍 {F.sc('industry')} · <b>{{INDUSTRY}}</b>\n"
    f"\n"
    f"📥 {F.sc('fetched')} · <code>{{FETCHED}}</code>\n"
    f"✅ {F.sc('in db')} · <code>{{IN_DB}}</code>\n"
    f"❌ {F.sc('missing')} · <code>{{MISSING}}</code>\n"
)

DEFAULT_FOOTER = (
    f"\n{F.DIV}\n"
    f"📌 <i>{F.sc('copy any name and search it anywhere')}</i>\n"
    f"🕒 <code>{{TIME}}</code>"
)

DEFAULT_ITEM_LINE = (
    f"<b>{{N}}.</b>\n"
    f"<code>{{NAME}}</code>\n"
    f"{{STARS}} {{POP}} {{LANG}}\n"
)


# ============================================================
# TEMPLATE PRESETS
# ============================================================

TEMPLATES = {
    "default": {
        "header": DEFAULT_HEADER,
        "footer": DEFAULT_FOOTER,
        "item_line": DEFAULT_ITEM_LINE,
    },

    "minimal": {
        "header": (
            f"🔍 <b>{F.fb('MISSING')} {{TYPE}}</b>\n"
            f"📅 <code>{{PERIOD}}</code>\n\n"
        ),
        "footer": f"\n🕒 <code>{{TIME}}</code>",
        "item_line": f"<b>{{N}}.</b> <code>{{NAME}}</code>\n",
    },

    "fancy": {
        "header": (
            f"╔════════════════════════════════╗\n"
            f"║  {F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>  ║\n"
            f"║  🔍 <b>{F.fb('MISSING')} {{TYPE}}</b>\n"
            f"╚════════════════════════════════╝\n"
            f"\n"
            f"📅 {F.sc('period')}   · <code>{{PERIOD}}</code>\n"
            f"🌍 {F.sc('industry')} · <b>{{INDUSTRY}}</b>\n"
            f"\n"
            f"📥 {F.sc('fetched')}  · <code>{{FETCHED}}</code>\n"
            f"✅ {F.sc('in db')}   · <code>{{IN_DB}}</code>\n"
            f"❌ {F.sc('missing')} · <code>{{MISSING}}</code>\n"
        ),
        "footer": (
            f"\n{F.DIV}\n"
            f"🕒 <code>{{TIME}}</code>"
        ),
        "item_line": f"◪ <b>{{N}}.</b> <code>{{NAME}}</code>\n",
    },

    "compact": {
        "header": (
            f"{F.EMO['brand']} <b>{F.fb('MISSING')} {{TYPE}}</b>\n"
            f"<code>{{PERIOD}}</code> · <b>{{INDUSTRY}}</b>\n"
            f"\n"
        ),
        "footer": f"\n🕒 <code>{{TIME}}</code>",
        "item_line": f"<b>{{N}}.</b> <code>{{NAME}}</code>\n",
    },
}


# ============================================================
# GET / SET
# ============================================================

async def get_template(key: str = "template") -> Optional[Dict[str, Any]]:
    c = _coll()
    if c is None:
        return None
    try:
        d = await c.find_one({"_id": key})
        if d:
            d.pop("_id", None)
        return d
    except Exception:
        return None


async def set_template(key: str, value: Dict[str, Any]) -> bool:
    c = _coll()
    if c is None:
        return False
    try:
        value["updated_at"] = datetime.utcnow()
        await c.update_one({"_id": key}, {"$set": value}, upsert=True)
        return True
    except Exception:
        return False


# ============================================================
# BUTTONS
# ============================================================

async def get_buttons() -> List[Dict[str, Any]]:
    c = _coll()
    if c is None:
        return []
    try:
        d = await c.find_one({"_id": "buttons"})
        return list(d.get("list") or []) if d else []
    except Exception:
        return []


async def set_buttons(buttons: List[Dict[str, Any]]) -> bool:
    c = _coll()
    if c is None:
        return False
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


# ============================================================
# RENDER
# ============================================================
#
# Because headers use F.sc() on STATIC labels only, .format()
# still works — placeholders like {PERIOD} survive.
#
# ============================================================

def render_header(t: Dict[str, Any], ctx: Dict[str, Any]) -> str:
    try:
        return t.get("header", DEFAULT_HEADER).format(**ctx)
    except Exception as e:
        logger.debug(f"[MISS-TPL] header: {e}")
        return DEFAULT_HEADER.format(**ctx) if ctx else DEFAULT_HEADER


def render_item(t: Dict[str, Any], ctx: Dict[str, Any]) -> str:
    try:
        return t.get("item_line", DEFAULT_ITEM_LINE).format(**ctx)
    except Exception as e:
        logger.debug(f"[MISS-TPL] item: {e}")
        return DEFAULT_ITEM_LINE.format(**ctx) if ctx else DEFAULT_ITEM_LINE


def render_footer(t: Dict[str, Any], ctx: Dict[str, Any]) -> str:
    try:
        return t.get("footer", DEFAULT_FOOTER).format(**ctx)
    except Exception as e:
        logger.debug(f"[MISS-TPL] footer: {e}")
        return DEFAULT_FOOTER.format(**ctx) if ctx else DEFAULT_FOOTER


# ============================================================
# PUBLIC
# ============================================================

__all__ = [
    "TEMPLATES", "DEFAULT_HEADER", "DEFAULT_FOOTER", "DEFAULT_ITEM_LINE",
    "get_template", "set_template",
    "get_buttons", "set_buttons", "build_button_kb",
    "render_header", "render_item", "render_footer",
]
