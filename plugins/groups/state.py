# ============================================================
# 🏨 DOWNTOWN VILLA — GROUPS STATE (v2 — FULL CUSTOMIZATION)
# ============================================================
#
# Per-group configuration layer. EVERY feature is controllable
# per group from Telegram. No code deploy needed.
#
# Storage:  USER DB → `groups` collection
# Cache:    in-memory, 5 min TTL
#
# Sections:
#   basic       → enabled, content_mode, search_enabled, pm_search_enabled
#   flow        → per-step enable + per_row + order + auto_skip
#   search      → spell_check threshold, suggestions count, thresholds
#   imdb        → provider toggles, fuzzy thresholds
#   buttons     → result buttons, per_row, size, quality format
#   caption     → template
#   welcome     → welcome message + auto-delete
#   auto_delete → bot/user/command timers
#   filters     → banned words + links
#   fsub        → force-sub channels
#   verify      → shortener + timer
#   security    → url/telegram link blocking, flood control
#   requests    → enabled, channel, PM update
#   metadata    → poster/rating/genre/year toggles
#   stats       → counters
#
# ============================================================

from __future__ import annotations

import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ============================================================
# SECTION 1 — DEFAULT SCHEMA
# ============================================================

DEFAULT_CFG: Dict[str, Any] = {

    # ── BASIC ──
    "enabled": True,
    "content_mode": "both",              # movie | series | both
    "search_enabled": True,
    "pm_search_enabled": True,

    # ── FLOW ORDER (per group, list of step keys) ──
    # If empty → use plugin defaults
    "flow_order": {
        "series": [],
        "movie": [],
    },

    # ── FLOW PER-STEP CONFIG ──
    "flow": {
        "base_search":   {"enabled": True, "per_row": 1},
        "spell_check":   {"enabled": True, "threshold": 82, "max_corrections": 1},
        "suggestions":   {"enabled": True, "per_row": 1, "max_items": 6,
                          "min_score": 45, "provider": "both"},
        "language":      {"enabled": True, "per_row": 2, "auto_skip": True,
                          "max_items": 12},
        "season":        {"enabled": True, "per_row": 2, "auto_skip": True,
                          "max_items": 12},
        "episode":       {"enabled": True, "per_row": 4, "auto_skip": True,
                          "max_items": 20, "per_page": 20},
        "quality":       {"enabled": True, "per_row": 2, "auto_skip": True,
                          "max_items": 8},
        "file_delivery": {"enabled": True, "per_row": 1, "max_items": 10,
                          "sort_order": "small_to_big"},
    },

    # ── SEARCH TUNING ──
    "search": {
        # Spell check accuracy (0-100, higher = stricter)
        "spell_threshold": 82,
        # How many times to retry with corrections
        "max_corrections": 1,
        # Auto-correct confidence threshold (never below this)
        "min_correction_score": 80,
        # Search cache TTL (seconds)
        "cache_ttl": 300,
        # Case-insensitive matching
        "case_insensitive": True,
        # Max results from DB before paging
        "search_per_page": 10,
        "search_per_row": 1,
    },

    # ── IMDb / PROVIDERS ──
    "imdb": {
        # Enable IMDb suggestions
        "enabled": True,
        # Enable TMDB suggestions
        "tmdb_enabled": True,
        # Min fuzzy score to accept a suggestion (0-100)
        "min_match_score": 45,
        # How many providers to query
        "max_providers": 2,
        # Boost year match
        "year_boost": 5,
        # Show ratings in suggestion buttons
        "show_rating": True,
        # Show year in suggestion buttons
        "show_year": True,
        # Show type icon (🎬/📺)
        "show_icon": True,
        # Suggestion action: "search" | "request" | "both"
        "on_pick": "both",
    },

    # ── CAPTION ──
    "caption_template": None,            # None → global default
    "caption_variables": {
        "title": "{title}",
        "quality": "{quality}",
        "size": "{size}",
        "audio": "{audio}",
        "subtitle": "{subtitle}",
    },

    # ── RESULT BUTTONS ──
    "result_buttons": [],
    "buttons_per_row": 2,
    "button_size_format": "short",       # short | full
    "button_show_quality": True,
    "button_show_name": True,
    "button_name_max_len": 34,

    # ── WELCOME ──
    "welcome_enabled": False,
    "welcome_text": None,
    "welcome_buttons": [],
    "welcome_auto_delete": True,
    "welcome_delete_after": 600,

    # ── AUTO-DELETE ──
    "auto_delete": {
        "bot_messages": True,
        "bot_timer": 600,
        "user_messages": True,
        "keep_last_n": 10,
        "command_messages": True,
    },

    # ── FILTERS ──
    "filters": {
        "banned_words": [],
        "banned_links": True,
        "block_forward": False,
        "block_media": False,
    },

    # ── FORCE-SUB ──
    "fsub": {
        "enabled": False,
        "channels": [],
        "title": "🔒 JOIN REQUIRED",
        "message": (
            "You must join our channels to use this bot.\n"
            "Tap the buttons below, then press Try Again."
        ),
        "join_label": "🔔 JOIN",
        "try_label": "🔄 TRY AGAIN",
    },

    # ── VERIFICATION ──
    "verify": {
        "enabled": False,
        "shortener_url": None,
        "verify_time": 1200,
    },

    # ── SECURITY ──
    "security": {
        "url_blocking": True,
        "telegram_links": True,
        "admin_bypass": True,
        "search_flood_control": True,
        "search_limit": 5,
    },

    # ── REQUESTS ──
    "requests": {
        "enabled": True,
        "channel": None,
        "user_pm_update": True,
        "duplicate_check": True,
    },

    # ── METADATA ──
    "metadata": {
        "poster": True,
        "rating": True,
        "genre": True,
        "year": True,
        "language": True,
    },

    # ── STATS ──
    "stats": {
        "searches_today": 0,
        "results_found": 0,
        "not_found": 0,
        "files_sent": 0,
        "updated_at": None,
    },

    # ── META ──
    "created_at": None,
    "updated_at": None,
    "title": None,
    "username": None,
}


# ============================================================
# SECTION 2 — CACHE
# ============================================================

_CACHE: Dict[int, Dict[str, Any]] = {}
_CACHE_TS: Dict[int, float] = {}
_CACHE_TTL = 300.0


def _cache_get(chat_id: int) -> Optional[Dict[str, Any]]:
    ts = _CACHE_TS.get(chat_id)
    if not ts or time.time() - ts > _CACHE_TTL:
        _CACHE.pop(chat_id, None)
        _CACHE_TS.pop(chat_id, None)
        return None
    return _CACHE.get(chat_id)


def _cache_set(chat_id: int, value: Dict[str, Any]) -> None:
    _CACHE[chat_id] = value
    _CACHE_TS[chat_id] = time.time()


def _cache_invalidate(chat_id: int) -> None:
    _CACHE.pop(chat_id, None)
    _CACHE_TS.pop(chat_id, None)


def invalidate_all() -> None:
    _CACHE.clear()
    _CACHE_TS.clear()


# ============================================================
# SECTION 3 — DB ACCESS
# ============================================================

def _coll():
    try:
        from database import db_registry
        db = db_registry.get_user_db()
        return db["groups"] if db is not None else None
    except Exception as e:
        logger.debug(f"[GROUPS] coll: {e}")
        return None


# ============================================================
# SECTION 4 — DEEP MERGE
# ============================================================

def _merge(base: Dict[str, Any], patch: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(base)
    for k, v in (patch or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


# ============================================================
# SECTION 5 — READ
# ============================================================

async def get_config(chat_id: int, use_cache: bool = True) -> Dict[str, Any]:
    cid = int(chat_id)
    if use_cache:
        cached = _cache_get(cid)
        if cached is not None:
            return cached

    coll = _coll()
    if coll is None:
        return {"chat_id": cid, **DEFAULT_CFG}

    try:
        doc = await coll.find_one({"chat_id": cid})
    except Exception as e:
        logger.debug(f"[GROUPS] read: {e}")
        doc = None

    if not doc:
        merged = {"chat_id": cid, **DEFAULT_CFG}
        if use_cache:
            _cache_set(cid, merged)
        return merged

    doc.pop("_id", None)
    merged = _merge(DEFAULT_CFG, doc)
    merged["chat_id"] = cid

    if use_cache:
        _cache_set(cid, merged)
    return merged


# ============================================================
# SECTION 6 — WRITE
# ============================================================

async def save_field(chat_id: int, field_path: str, value: Any) -> bool:
    coll = _coll()
    if coll is None:
        return False
    try:
        now = datetime.utcnow()
        await coll.update_one(
            {"chat_id": int(chat_id)},
            {
                "$set": {
                    field_path: value,
                    "updated_at": now,
                },
                "$setOnInsert": {
                    "chat_id": int(chat_id),
                    "created_at": now,
                },
            },
            upsert=True,
        )
        _cache_invalidate(int(chat_id))
        return True
    except Exception as e:
        logger.warning(f"[GROUPS] save: {e}")
        return False


async def save_fields(chat_id: int, fields: Dict[str, Any]) -> bool:
    coll = _coll()
    if coll is None:
        return False
    try:
        now = datetime.utcnow()
        payload = dict(fields)
        payload["updated_at"] = now
        await coll.update_one(
            {"chat_id": int(chat_id)},
            {
                "$set": payload,
                "$setOnInsert": {
                    "chat_id": int(chat_id),
                    "created_at": now,
                },
            },
            upsert=True,
        )
        _cache_invalidate(int(chat_id))
        return True
    except Exception as e:
        logger.warning(f"[GROUPS] save_many: {e}")
        return False


# ============================================================
# SECTION 7 — LIFECYCLE
# ============================================================

async def register_group(
    chat_id: int,
    title: str = "",
    username: str = "",
) -> bool:
    coll = _coll()
    if coll is None:
        return False
    try:
        now = datetime.utcnow()
        payload = {k: v for k, v in DEFAULT_CFG.items()
                   if k not in ("created_at", "updated_at",
                                "title", "username")}
        await coll.update_one(
            {"chat_id": int(chat_id)},
            {
                "$setOnInsert": {
                    "chat_id": int(chat_id),
                    "created_at": now,
                    **payload,
                },
                "$set": {
                    "title": title or str(chat_id),
                    "username": username or "",
                    "updated_at": now,
                },
            },
            upsert=True,
        )
        _cache_invalidate(int(chat_id))
        return True
    except Exception as e:
        logger.warning(f"[GROUPS] register: {e}")
        return False


async def reset_config(chat_id: int) -> bool:
    coll = _coll()
    if coll is None:
        return False
    try:
        doc = await coll.find_one({"chat_id": int(chat_id)}) or {}
        now = datetime.utcnow()
        fresh = {
            "chat_id": int(chat_id),
            "title": doc.get("title"),
            "username": doc.get("username"),
            "created_at": doc.get("created_at", now),
            "updated_at": now,
        }
        for k, v in DEFAULT_CFG.items():
            if k in ("created_at", "updated_at", "title", "username"):
                continue
            fresh[k] = v
        await coll.replace_one(
            {"chat_id": int(chat_id)},
            fresh,
            upsert=True,
        )
        _cache_invalidate(int(chat_id))
        return True
    except Exception as e:
        logger.warning(f"[GROUPS] reset: {e}")
        return False


async def delete_group(chat_id: int) -> bool:
    coll = _coll()
    if coll is None:
        return False
    try:
        r = await coll.delete_one({"chat_id": int(chat_id)})
        _cache_invalidate(int(chat_id))
        return r.deleted_count > 0
    except Exception as e:
        logger.warning(f"[GROUPS] delete: {e}")
        return False


async def list_groups(limit: int = 50) -> List[Dict[str, Any]]:
    coll = _coll()
    if coll is None:
        return []
    try:
        cursor = coll.find({}).sort("title", 1).limit(int(limit))
        docs = await cursor.to_list(length=int(limit))
        for d in docs:
            d.pop("_id", None)
        return docs
    except Exception:
        return []


async def count_groups() -> int:
    coll = _coll()
    if coll is None:
        return 0
    try:
        return await coll.count_documents({})
    except Exception:
        return 0


# ============================================================
# SECTION 8 — STATS
# ============================================================

async def bump_stat(chat_id: int, key: str, amount: int = 1) -> bool:
    coll = _coll()
    if coll is None:
        return False
    try:
        await coll.update_one(
            {"chat_id": int(chat_id)},
            {
                "$inc": {f"stats.{key}": int(amount)},
                "$set": {
                    "stats.updated_at": datetime.utcnow(),
                    "updated_at": datetime.utcnow(),
                },
            },
            upsert=True,
        )
        _cache_invalidate(int(chat_id))
        return True
    except Exception as e:
        logger.debug(f"[GROUPS] stat {key}: {e}")
        return False


# ============================================================
# SECTION 9 — PUBLIC EXPORTS
# ============================================================

__all__ = [
    "DEFAULT_CFG",
    "get_config",
    "save_field", "save_fields",
    "register_group", "reset_config", "delete_group",
    "list_groups", "count_groups",
    "invalidate_all",
    "bump_stat",
]
