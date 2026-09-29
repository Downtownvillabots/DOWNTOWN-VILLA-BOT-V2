# ============================================================
# 🏨 DOWNTOWN VILLA — MISSING TEMPLATES (FANCY)
# ============================================================
from __future__ import annotations
import logging
from string import Formatter
from typing import Any, Dict, Optional

from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from plugins.missing import fonts as F

logger = logging.getLogger(__name__)
COLL_NAME = "missing_templates"


def _coll():
    try:
        from database import db_manager
        for n in ("get_system_db", "get_user_db"):
            fn = getattr(db_manager, n, None)
            if callable(fn):
                try:
                    d = fn()
                    if d is not None: return d[COLL_NAME]
                except Exception:
                    pass
    except Exception:
        pass
    try:
        from database import db_registry
        d = db_registry.get_system_db()
        return d[COLL_NAME] if d is not None else None
    except Exception:
        return None


# ── Safe format (never crashes on missing keys) ──
class _SafeDict(dict):
    def __missing__(self, key): return "{" + key + "}"


def _safe_format(tpl: str, ctx: Dict[str, Any]) -> str:
    try:
        return Formatter().vformat(tpl, (), _SafeDict(**ctx))
    except Exception as e:
        logger.debug(f"[MISS-TPL] format: {e}")
        return tpl


# ── Default templates ──
DEFAULT_HEADER = (
    f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>\n"
    f"🔍 <b>{F.fb('MISSING')} {{TYPE}}</b>\n"
    f"{F.DIV}\n\n"
    f"📅 {F.sc('period')} · <code>{{PERIOD}}</code>\n"
    f"🌍 {F.sc('industry')} · <b>{{INDUSTRY}}</b>\n\n"
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
    "compact": {
        "header": (
            f"{F.EMO['brand']} <b>{F.fb('MISSING')} {{TYPE}}</b>\n"
            f"<code>{{PERIOD}}</code> · <b>{{INDUSTRY}}</b>\n\n"
        ),
        "footer": f"\n🕒 <code>{{TIME}}</code>",
        "item_line": f"<b>{{N}}.</b> <code>{{NAME}}</code>\n",
    },
}


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
        await c.update_one({"_id": key}, {"$set": value}, upsert=True)
        return True
    except Exception:
        return False


def build_button_kb(buttons: list) -> Optional[InlineKeyboardMarkup]:
    if not buttons: return None
    rows = []
    for b in buttons:
        name = (b.get("name") or "").strip()
        url = (b.get("url") or "").strip()
        if not name or not url: continue
        if url.startswith("@"):
            url = f"https://t.me/{url[1:]}"
        elif not url.startswith(("http://", "https://", "tg://")):
            if "." in url and " " not in url:
                url = f"https://{url}"
            else:
                continue
        rows.append([InlineKeyboardButton(name[:60], url=url)])
    return InlineKeyboardMarkup(rows) if rows else None


# ── Render ──
def render_header(t: Dict[str, Any], ctx: Dict[str, Any]) -> str:
    return _safe_format(t.get("header") or DEFAULT_HEADER, ctx)


def render_item(t: Dict[str, Any], ctx: Dict[str, Any]) -> str:
    return _safe_format(t.get("item_line") or DEFAULT_ITEM_LINE, ctx)


def render_footer(t: Dict[str, Any], ctx: Dict[str, Any]) -> str:
    return _safe_format(t.get("footer") or DEFAULT_FOOTER, ctx)


__all__ = [
    "TEMPLATES", "DEFAULT_HEADER", "DEFAULT_FOOTER", "DEFAULT_ITEM_LINE",
    "get_template", "set_template", "build_button_kb",
    "render_header", "render_item", "render_footer",
]
