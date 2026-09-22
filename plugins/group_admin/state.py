# ============================================================
# 🏨 DOWNTOWN VILLA — GROUP ADMIN STATE
# ============================================================
#
# FULL group config schema with every customisable field.
#
# Stored in USER DB → groups
# Unique key: chat_id
#
# ============================================================

from __future__ import annotations
import logging, time
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ── FULL DEFAULT SCHEMA ──
DEFAULT_CFG: Dict[str, Any] = {
    # ── basic ──
    "enabled": True,
    "content_mode": "both",         # movies / series / both
    "search_enabled": True,
    "pm_search_enabled": True,
    "welcome_enabled": False,
    "welcome_text": None,
    "welcome_buttons": [],

    # ── search flow ──
    "flow": {
        "search":         {"enabled": True,  "per_row": 1, "max_items": 10},
        "spell_check":    {"enabled": True,  "threshold": 85},
        "suggestions":    {"enabled": True,  "per_row": 1, "max_items": 8},
        "language":       {"enabled": True,  "per_row": 2, "auto_skip": True},
        "season":         {"enabled": True,  "per_row": 2, "auto_skip": True},
        "episode":        {"enabled": True,  "per_row": 4, "per_page": 20},
        "quality":        {"enabled": True,  "per_row": 2},
        "file_delivery":  {"enabled": True,  "auto_delete": True},
    },

    # ── caption ──
    "caption_template": None,       # None → use global
    "caption_variables": {
        "title": "{title}",
        "quality": "{quality}",
        "size": "{size}",
        "audio": "{audio}",
        "subtitle": "{subtitle}",
    },

    # ── buttons (result) ──
    "result_buttons": [],           # [{name, url, row, enabled}]
    "buttons_per_row": 2,

    # ── welcome ──
    "welcome_auto_delete": True,
    "welcome_delete_after": 600,

    # ── auto-delete ──
    "auto_delete": {
        "bot_messages": True,
        "bot_timer": 600,
        "user_messages": True,
        "keep_last_n": 10,
        "command_messages": True,
    },

    # ── filters ──
    "filters": {
        "banned_words": [],
        "banned_links": True,
        "block_forward": False,
        "block_media": False,
    },

    # ── force sub ──
    "fsub": {
        "enabled": False,
        "channels": [],
    },

    # ── verification ──
    "verify": {
        "enabled": False,
        "shortener_url": None,
        "verify_time": 1200,
    },

    # ── security ──
    "security": {
        "url_blocking": True,
        "telegram_links": True,
        "admin_bypass": True,
        "search_flood_control": True,
        "search_limit": 5,
    },

    # ── request ──
    "requests": {
        "enabled": True,
        "channel": None,
        "user_pm_update": True,
        "duplicate_check": True,
    },

    # ── metadata ──
    "metadata": {
        "poster": True,
        "rating": True,
        "genre": True,
        "year": True,
        "language": True,
    },

    # ── stats (bounded) ──
    "stats": {
        "searches_today": 0,
        "results_found": 0,
        "not_found": 0,
        "files_sent": 0,
        "updated_at": None,
    },

    # ── timestamps ──
    "created_at": None,
    "updated_at": None,
    "title": None,
    "username": None,
}


# ── CACHE ──
_CACHE: Dict[int, Dict[str, Any]] = {}
_CACHE_TS: Dict[int, float] = {}
_TTL = 300


def _cg(chat_id: int):
    ts = _CACHE_TS.get(chat_id)
    if not ts or time.time() - ts > _TTL:
        _CACHE.pop(chat_id, None)
        _CACHE_TS.pop(chat_id, None)
        return None
    return _CACHE.get(chat_id)


def _cs(chat_id: int, value: Dict[str, Any]):
    _CACHE[chat_id] = value
    _CACHE_TS[chat_id] = time.time()


def _ci(chat_id: int):
    _CACHE.pop(chat_id, None)
    _CACHE_TS.pop(chat_id, None)


def _coll():
    try:
        from database import db_registry
        db = db_registry.get_user_db()
        return db["groups"] if db is not None else None
    except Exception:
        return None


def _merge(base: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for k, v in (patch or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


async def get_config(chat_id: int, use_cache: bool = True) -> Dict[str, Any]:
    if use_cache:
        c = _cg(chat_id)
        if c is not None:
            return c

    coll = _coll()
    if coll is None:
        return {"chat_id": chat_id, **DEFAULT_CFG}

    try:
        doc = await coll.find_one({"chat_id": int(chat_id)})
    except Exception as e:
        logger.debug(f"[GADMIN] read: {e}")
        doc = None

    if not doc:
        merged = {"chat_id": int(chat_id), **DEFAULT_CFG}
        if use_cache: _cs(chat_id, merged)
        return merged

    doc.pop("_id", None)
    merged = _merge(DEFAULT_CFG, doc)
    merged["chat_id"] = int(chat_id)

    if use_cache: _cs(chat_id, merged)
    return merged


async def save_field(chat_id: int, field_path: str, value: Any) -> bool:
    coll = _coll()
    if coll is None:
        return False
    try:
        now = datetime.utcnow()
        update = {
            "$set": {
                field_path: value,
                "updated_at": now,
            },
            "$setOnInsert": {
                "chat_id": int(chat_id),
                "created_at": now,
            },
        }
        await coll.update_one(
            {"chat_id": int(chat_id)},
            update,
            upsert=True,
        )
        _ci(chat_id)
        return True
    except Exception as e:
        logger.warning(f"[GADMIN] save: {e}")
        return False


async def register_group(chat_id: int, title: str = "", username: str = "") -> bool:
    coll = _coll()
    if coll is None:
        return False
    try:
        now = datetime.utcnow()
        await coll.update_one(
            {"chat_id": int(chat_id)},
            {
                "$setOnInsert": {
                    "chat_id": int(chat_id),
                    "created_at": now,
                    **{k: v for k, v in DEFAULT_CFG.items()
                       if k not in ("created_at", "updated_at")},
                },
                "$set": {
                    "title": title,
                    "username": username,
                    "updated_at": now,
                },
            },
            upsert=True,
        )
        _ci(chat_id)
        return True
    except Exception as e:
        logger.warning(f"[GADMIN] register: {e}")
        return False


async def reset_config(chat_id: int) -> bool:
    coll = _coll()
    if coll is None:
        return False
    try:
        doc = await coll.find_one({"chat_id": int(chat_id)}) or {}
        title = doc.get("title")
        username = doc.get("username")
        now = datetime.utcnow()
        await coll.replace_one(
            {"chat_id": int(chat_id)},
            {
                "chat_id": int(chat_id),
                "title": title,
                "username": username,
                "created_at": doc.get("created_at", now),
                "updated_at": now,
                **{k: v for k, v in DEFAULT_CFG.items()
                   if k not in ("created_at", "updated_at", "title", "username")},
            },
            upsert=True,
        )
        _ci(chat_id)
        return True
    except Exception as e:
        logger.warning(f"[GADMIN] reset: {e}")
        return False


async def list_groups(limit: int = 20) -> List[Dict[str, Any]]:
    coll = _coll()
    if coll is None:
        return []
    try:
        cur = coll.find({}).sort("title", 1).limit(int(limit))
        return await cur.to_list(length=int(limit))
    except Exception:
        return []


__all__ = [
    "DEFAULT_CFG",
    "get_config", "save_field", "register_group",
    "reset_config", "list_groups",
]
