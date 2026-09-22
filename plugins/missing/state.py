# ============================================================
# 🏨 DOWNTOWN VILLA — MISSING STATE
# ============================================================
#
# Collections (SYSTEM DB):
#   missing_presets  — saved scan presets
#   missing_history  — scan history
#   missing_settings — singleton config
# ============================================================

from __future__ import annotations
import logging, time
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _db():
    try:
        from database import db_registry
        return db_registry.get_system_db()
    except Exception:
        return None


def _c(name):
    db = _db()
    return db[name] if db is not None else None


def presets(): return _c("missing_presets")
def history(): return _c("missing_history")
def settings(): return _c("missing_settings")


# ── DEFAULTS ──
DEFAULT_CFG = {
    "default_industry": "hollywood",
    "default_max_pages": 15,
    "movies_per_part": 25,
    "show_rating": True,
    "show_popularity": True,
    "show_lang_code": True,
    "caption_template": None,
    "copy_friendly": True,      # wrap name in <code> for tap-to-copy
    "include_year": True,
}


async def get_cfg() -> Dict[str, Any]:
    c = settings()
    if c is None: return dict(DEFAULT_CFG)
    try:
        d = await c.find_one({"_id": "config"}) or {}
        out = dict(DEFAULT_CFG)
        out.update({k: v for k, v in d.items() if k != "_id"})
        return out
    except Exception:
        return dict(DEFAULT_CFG)


async def save_cfg(**fields) -> bool:
    c = settings()
    if c is None: return False
    try:
        fields["updated_at"] = time.time()
        await c.update_one({"_id": "config"}, {"$set": fields}, upsert=True)
        return True
    except Exception:
        return False


# ── PRESETS ──
async def save_preset(name: str, data: Dict[str, Any]) -> bool:
    c = presets()
    if c is None: return False
    try:
        await c.update_one(
            {"name": name},
            {"$set": {**data, "name": name, "saved_at": time.time()}},
            upsert=True,
        )
        return True
    except Exception:
        return False


async def list_presets() -> List[Dict[str, Any]]:
    c = presets()
    if c is None: return []
    try:
        cur = c.find({}).sort("saved_at", -1).limit(30)
        docs = await cur.to_list(length=30)
        for d in docs: d.pop("_id", None)
        return docs
    except Exception:
        return []


async def delete_preset(name: str) -> bool:
    c = presets()
    if c is None: return False
    try:
        r = await c.delete_one({"name": name})
        return r.deleted_count > 0
    except Exception:
        return False


# ── HISTORY ──
async def log_scan(data: Dict[str, Any]) -> bool:
    c = history()
    if c is None: return False
    try:
        await c.insert_one({**data, "created_at": time.time()})
        return True
    except Exception:
        return False


async def recent_scans(limit: int = 15) -> List[Dict[str, Any]]:
    c = history()
    if c is None: return []
    try:
        cur = c.find({}).sort("created_at", -1).limit(limit)
        return await cur.to_list(length=limit)
    except Exception:
        return []


async def clear_history() -> int:
    c = history()
    if c is None: return 0
    try:
        r = await c.delete_many({})
        return r.deleted_count
    except Exception:
        return 0


__all__ = [
    "get_cfg", "save_cfg", "DEFAULT_CFG",
    "save_preset", "list_presets", "delete_preset",
    "log_scan", "recent_scans", "clear_history",
]
