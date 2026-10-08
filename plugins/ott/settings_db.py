# ============================================================
# 🏨 DOWNTOWN VILLA — OTT SETTINGS DB
# ============================================================
# Stores caption + button config for OTT broadcasts.
# Per-target overrides fall back to global default.
#
# Document structure (single doc _id="ott"):
# {
#   "global_caption": str,
#   "global_buttons": {
#       "get_notified": bool,
#       "get_files": bool,
#       "watchlist": bool,
#       "custom": [{"name": str, "url": str}, ...]
#   },
#   "channel_overrides": {
#       "-100xxx": {"caption": str|None, "buttons": {...}|None}
#   },
#   "group_overrides":   { ... },
#   "user_caption":       str|None,
#   "user_buttons":       {...}|None,
#   "premium_caption":    str|None,
#   "premium_buttons":    {...}|None,
# }
# ============================================================

from __future__ import annotations
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

DOC_ID = "ott"

# ── Default caption (used when no override exists) ──
DEFAULT_CAPTION = (
    "🎬 <b>{title} ({year})</b>\n"
    "⭐ <b>{rating}</b>/10 · 🌐 <b>{lang}</b>\n"
    "🎭 {genres}\n"
    "📅 {release_date} · 📺 {platform}\n"
    "\n"
    "🔔 tap below to get notified"
)

DEFAULT_BUTTONS: Dict[str, Any] = {
    "get_notified": True,
    "get_files": True,
    "watchlist": True,
    "custom": [],
}


# ═══════════════════════════════════════════════════════════
# CAPTION TEMPLATES
# ═══════════════════════════════════════════════════════════

CAPTION_TEMPLATES: Dict[str, str] = {
    "default": DEFAULT_CAPTION,
    "minimal": (
        "🎬 <b>{title}</b> ({year})\n"
        "⭐ {rating}/10 · 🌐 {lang}"
    ),
    "detailed": (
        "🎬 <b>{title} ({year})</b>\n"
        "━━━━━━━━━━━━━━━━\n"
        "⭐ <b>Rating</b> · {rating}/10\n"
        "🌐 <b>Lang</b> · {lang}\n"
        "🎭 <b>Genres</b> · {genres}\n"
        "📅 <b>Release</b> · {release_date}\n"
        "📺 <b>Platform</b> · {platform}\n"
        "━━━━━━━━━━━━━━━━\n"
        "\n"
        "{overview}"
    ),
    "poster_only": "🎬 <b>{title} ({year})</b>",
    "hype": (
        "🔥 <b>COMING SOON</b>\n"
        "🎬 <b>{title}</b> ({year})\n"
        "⭐ {rating}/10 · 🌐 {lang}\n"
        "📺 {platform}\n"
        "\n"
        "🔔 tap below to be notified"
    ),
}


# ═══════════════════════════════════════════════════════════
# LOW-LEVEL DB
# ═══════════════════════════════════════════════════════════

def _coll():
    try:
        from database import db_registry
        db = db_registry.get_system_db()
        return db["ott_settings_v2"] if db is not None else None
    except Exception:
        return None


async def _load() -> Dict[str, Any]:
    c = _coll()
    if c is None:
        return _empty()
    try:
        d = await c.find_one({"_id": DOC_ID}) or {}
        out = _empty()
        out.update({k: v for k, v in d.items() if k != "_id"})
        return out
    except Exception as e:
        logger.debug(f"[OTT-SET] load: {e}")
        return _empty()


def _empty() -> Dict[str, Any]:
    return {
        "global_caption": DEFAULT_CAPTION,
        "global_buttons": dict(DEFAULT_BUTTONS),
        "channel_overrides": {},
        "group_overrides": {},
        "user_caption": None,
        "user_buttons": None,
        "premium_caption": None,
        "premium_buttons": None,
    }


async def _save(fields: Dict[str, Any]) -> bool:
    c = _coll()
    if c is None:
        return False
    try:
        fields["updated_at"] = time.time()
        await c.update_one({"_id": DOC_ID}, {"$set": fields}, upsert=True)
        return True
    except Exception as e:
        logger.debug(f"[OTT-SET] save: {e}")
        return False


# ═══════════════════════════════════════════════════════════
# GLOBAL CAPTION
# ═══════════════════════════════════════════════════════════

async def get_global_caption() -> str:
    d = await _load()
    return d.get("global_caption") or DEFAULT_CAPTION


async def set_global_caption(caption: str) -> bool:
    return await _save({"global_caption": caption or DEFAULT_CAPTION})


async def reset_global_caption() -> bool:
    return await _save({"global_caption": DEFAULT_CAPTION})


# ═══════════════════════════════════════════════════════════
# GLOBAL BUTTONS
# ═══════════════════════════════════════════════════════════

async def get_global_buttons() -> Dict[str, Any]:
    d = await _load()
    btn = d.get("global_buttons") or {}
    out = dict(DEFAULT_BUTTONS)
    for k in ("get_notified", "get_files", "watchlist"):
        if k in btn:
            out[k] = bool(btn[k])
    custom = btn.get("custom") or []
    if isinstance(custom, list):
        out["custom"] = [
            {"name": str(c.get("name") or "")[:64],
             "url": str(c.get("url") or "")}
            for c in custom if isinstance(c, dict)
        ]
    return out


async def set_global_buttons(buttons: Dict[str, Any]) -> bool:
    return await _save({"global_buttons": buttons or dict(DEFAULT_BUTTONS)})


async def toggle_global_button(key: str) -> Optional[bool]:
    if key not in ("get_notified", "get_files", "watchlist"):
        return None
    b = await get_global_buttons()
    b[key] = not bool(b.get(key))
    await set_global_buttons(b)
    return b[key]


# ═══════════════════════════════════════════════════════════
# PER-CHANNEL / GROUP OVERRIDES
# ═══════════════════════════════════════════════════════════

async def get_channel_override(cid: int) -> Dict[str, Any]:
    d = await _load()
    mp = d.get("channel_overrides") or {}
    return mp.get(str(int(cid))) or {}


async def set_channel_caption(cid: int, caption: Optional[str]) -> bool:
    d = await _load()
    mp = dict(d.get("channel_overrides") or {})
    key = str(int(cid))
    cur = mp.get(key) or {}
    cur["caption"] = caption
    mp[key] = cur
    return await _save({"channel_overrides": mp})


async def set_channel_buttons(cid: int, buttons: Optional[Dict[str, Any]]) -> bool:
    d = await _load()
    mp = dict(d.get("channel_overrides") or {})
    key = str(int(cid))
    cur = mp.get(key) or {}
    cur["buttons"] = buttons
    mp[key] = cur
    return await _save({"channel_overrides": mp})


async def clear_channel_override(cid: int) -> bool:
    d = await _load()
    mp = dict(d.get("channel_overrides") or {})
    mp.pop(str(int(cid)), None)
    return await _save({"channel_overrides": mp})


async def get_group_override(gid: int) -> Dict[str, Any]:
    d = await _load()
    mp = d.get("group_overrides") or {}
    return mp.get(str(int(gid))) or {}


async def set_group_caption(gid: int, caption: Optional[str]) -> bool:
    d = await _load()
    mp = dict(d.get("group_overrides") or {})
    key = str(int(gid))
    cur = mp.get(key) or {}
    cur["caption"] = caption
    mp[key] = cur
    return await _save({"group_overrides": mp})


async def set_group_buttons(gid: int, buttons: Optional[Dict[str, Any]]) -> bool:
    d = await _load()
    mp = dict(d.get("group_overrides") or {})
    key = str(int(gid))
    cur = mp.get(key) or {}
    cur["buttons"] = buttons
    mp[key] = cur
    return await _save({"group_overrides": mp})


async def clear_group_override(gid: int) -> bool:
    d = await _load()
    mp = dict(d.get("group_overrides") or {})
    mp.pop(str(int(gid)), None)
    return await _save({"group_overrides": mp})


# ═══════════════════════════════════════════════════════════
# USERS / PREMIUM
# ═══════════════════════════════════════════════════════════

async def get_user_caption() -> Optional[str]:
    d = await _load()
    return d.get("user_caption")


async def set_user_caption(caption: Optional[str]) -> bool:
    return await _save({"user_caption": caption})


async def get_user_buttons() -> Optional[Dict[str, Any]]:
    d = await _load()
    return d.get("user_buttons")


async def set_user_buttons(buttons: Optional[Dict[str, Any]]) -> bool:
    return await _save({"user_buttons": buttons})


async def get_premium_caption() -> Optional[str]:
    d = await _load()
    return d.get("premium_caption")


async def set_premium_caption(caption: Optional[str]) -> bool:
    return await _save({"premium_caption": caption})


async def get_premium_buttons() -> Optional[Dict[str, Any]]:
    d = await _load()
    return d.get("premium_buttons")


async def set_premium_buttons(buttons: Optional[Dict[str, Any]]) -> bool:
    return await _save({"premium_buttons": buttons})


# ═══════════════════════════════════════════════════════════
# RESOLVE EFFECTIVE CONFIG (used by engine)
# ═══════════════════════════════════════════════════════════

async def resolve_caption_and_buttons(
    kind: str,
    target_id: int = 0,
) -> Dict[str, Any]:
    """
    Return {"caption": str, "buttons": dict} for a target.
    kind: "global" | "channel" | "group" | "user" | "premium"
    Falls back to global if no override exists.
    """
    gc = await get_global_caption()
    gb = await get_global_buttons()

    if kind == "channel" and target_id:
        ov = await get_channel_override(int(target_id))
        cap = ov.get("caption") if ov.get("caption") is not None else gc
        btn = ov.get("buttons") if ov.get("buttons") is not None else gb
        return {"caption": cap, "buttons": btn}

    if kind == "group" and target_id:
        ov = await get_group_override(int(target_id))
        cap = ov.get("caption") if ov.get("caption") is not None else gc
        btn = ov.get("buttons") if ov.get("buttons") is not None else gb
        return {"caption": cap, "buttons": btn}

    if kind == "user":
        uc = await get_user_caption()
        ub = await get_user_buttons()
        return {"caption": uc if uc is not None else gc,
                "buttons": ub if ub is not None else gb}

    if kind == "premium":
        pc = await get_premium_caption()
        pb = await get_premium_buttons()
        return {"caption": pc if pc is not None else gc,
                "buttons": pb if pb is not None else gb}

    # global fallback
    return {"caption": gc, "buttons": gb}


# ═══════════════════════════════════════════════════════════
# RENDER: fill placeholders in a caption
# ═══════════════════════════════════════════════════════════

def fill_caption(template: str, movie: Dict[str, Any]) -> str:
    """Fill {title}, {year}, etc. in a caption template."""
    title = movie.get("title") or "?"
    year = (movie.get("release_date") or "")[:4] or "—"
    rating = movie.get("vote_average", 0) or 0
    lang_raw = (movie.get("original_language") or "").upper() or "—"
    genres = (movie.get("genres") or "—")[:80]
    provider = movie.get("provider") or "—"
    rel = ((movie.get("region_release") or {}).get("date")
           or movie.get("release_date") or "—")
    overview = (movie.get("overview") or "")[:300]
    imdb_id = movie.get("imdb_id") or ""
    imdb_url = (f"https://www.imdb.com/title/{imdb_id}/"
                if imdb_id else "—")

    try:
        return template.format(
            title=title, year=year,
            rating=f"{rating:.1f}", lang=lang_raw,
            genres=genres, platform=provider,
            release_date=rel, overview=overview,
            imdb_url=imdb_url, imdb_id=imdb_id or "—",
        )
    except (KeyError, IndexError, ValueError) as e:
        logger.debug(f"[OTT-SET] fill: {e}")
        return template


# ═══════════════════════════════════════════════════════════
# BUILD KEYBOARD FROM BUTTON CONFIG
# ═══════════════════════════════════════════════════════════

def build_ott_keyboard(buttons: Dict[str, Any], tmdb_id: int,
                        is_admin_view: bool = False,
                        ended: bool = False):
    """Return InlineKeyboardMarkup for OTT poster buttons."""
    from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    if ended:
        return InlineKeyboardMarkup([[
            InlineKeyboardButton(
                "📊 Final Stats",
                callback_data=f"ott:stats_pub:{tmdb_id}",
            )
        ]])

    rows: List[List[InlineKeyboardButton]] = []
    user_row: List[InlineKeyboardButton] = []

    if buttons.get("get_notified", True):
        user_row.append(InlineKeyboardButton(
            "🔔 Get Notified",
            callback_data=f"ott:sub:{tmdb_id}",
        ))
    if buttons.get("get_files", True):
        user_row.append(InlineKeyboardButton(
            "📥 Get Files",
            callback_data=f"ott:files:{tmdb_id}:0",
        ))
    if user_row:
        rows.append(user_row)

    if buttons.get("watchlist", True):
        rows.append([InlineKeyboardButton(
            "🎁 Add to Watchlist",
            callback_data=f"ott:wl_add:{tmdb_id}",
        )])

    # Custom URL buttons
    for c in (buttons.get("custom") or [])[:6]:
        name = (c.get("name") or "").strip()[:64]
        url = (c.get("url") or "").strip()
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
        rows.append([InlineKeyboardButton(name, url=url)])

    # Admin controls
    if is_admin_view:
        rows.append([
            InlineKeyboardButton("📊 Live Stats",
                                 callback_data=f"ott:stats:{tmdb_id}"),
            InlineKeyboardButton("📢 Broadcast",
                                 callback_data=f"ott:csetup_bc:{tmdb_id}"),
        ])
        rows.append([
            InlineKeyboardButton("🔔 Notify",
                                 callback_data=f"ott:notify_go:{tmdb_id}"),
            InlineKeyboardButton("💥 END TASK",
                                 callback_data=f"ott:end_mv:{tmdb_id}"),
        ])

    return InlineKeyboardMarkup(rows)


__all__ = [
    "DEFAULT_CAPTION", "DEFAULT_BUTTONS", "CAPTION_TEMPLATES",
    # global
    "get_global_caption", "set_global_caption", "reset_global_caption",
    "get_global_buttons", "set_global_buttons", "toggle_global_button",
    # channel
    "get_channel_override", "set_channel_caption",
    "set_channel_buttons", "clear_channel_override",
    # group
    "get_group_override", "set_group_caption",
    "set_group_buttons", "clear_group_override",
    # users / premium
    "get_user_caption", "set_user_caption",
    "get_user_buttons", "set_user_buttons",
    "get_premium_caption", "set_premium_caption",
    "get_premium_buttons", "set_premium_buttons",
    # resolve + render
    "resolve_caption_and_buttons",
    "fill_caption", "build_ott_keyboard",
]
