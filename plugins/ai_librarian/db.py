# ============================================================
# 🎛️ AI LIBRARIAN — DB ACCESS · SETTINGS · COMPLETED
# ============================================================
from __future__ import annotations
import logging, time
from typing import Any, Dict, List, Optional

from database import db_registry

logger = logging.getLogger(__name__)


def _get_system_db():
    try:
        return db_registry.get_system_db()
    except Exception:
        return None


def _get_user_db():
    try:
        return db_registry.get_user_db()
    except Exception:
        return None


def _completed_coll():
    d = _get_system_db()
    return d["ai_completed"] if d is not None else None


def _prefs_coll():
    d = _get_user_db()
    return d["ai_prefs"] if d is not None else None


def _settings_coll():
    d = _get_system_db()
    return d["ai_settings"] if d is not None else None


async def _is_completed(slug):
    c = _completed_coll()
    if c is None: return False
    try: return (await c.find_one({"title_slug": slug})) is not None
    except Exception: return False


async def _mark_completed(title, slug, count):
    c = _completed_coll()
    if c is None: return False
    try:
        await c.update_one({"title_slug": slug},
            {"$set": {"title": title, "title_slug": slug,
                      "total_files": count, "completed_at": time.time()}},
            upsert=True)
        return True
    except Exception: return False


async def _unmark_completed(slug):
    c = _completed_coll()
    if c is None: return False
    try: return (await c.delete_one({"title_slug": slug})).deleted_count > 0
    except Exception: return False


async def _list_completed(limit=100):
    c = _completed_coll()
    if c is None: return []
    try: return await c.find({}).sort("completed_at", -1).to_list(limit)
    except Exception: return []


async def _count_completed():
    c = _completed_coll()
    if c is None: return 0
    try: return await c.count_documents({})
    except Exception: return 0


async def _get_setting(key, default=None):
    c = _settings_coll()
    if c is None: return default
    try:
        doc = await c.find_one({"_id": "settings"}) or {}
        return doc.get(key, default)
    except Exception: return default


async def _set_setting(key, value):
    c = _settings_coll()
    if c is None: return False
    try:
        await c.update_one({"_id": "settings"},
                           {"$set": {key: value, "updated_at": time.time()}},
                           upsert=True)
        return True
    except Exception: return False


__all__ = [
    "_get_system_db", "_get_user_db",
    "_completed_coll", "_prefs_coll", "_settings_coll",
    "_is_completed", "_mark_completed", "_unmark_completed",
    "_list_completed", "_count_completed",
    "_get_setting", "_set_setting",
]
