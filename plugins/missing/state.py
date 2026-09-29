# ============================================================
# 🏨 DOWNTOWN VILLA — MISSING STATE
# ============================================================
from __future__ import annotations
import logging, time
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


def _get_db():
    try:
        from database import db_manager
        for name in ("get_system_db", "get_user_db"):
            fn = getattr(db_manager, name, None)
            if callable(fn):
                try:
                    d = fn()
                    if d is not None: return d
                except Exception:
                    pass
    except Exception:
        pass
    try:
        from database import db_registry
        return db_registry.get_system_db()
    except Exception:
        return None


def _c(name):
    db = _get_db()
    return db[name] if db is not None else None


def settings_coll():  return _c("missing_settings")
def history_coll():   return _c("missing_history")
def buttons_coll():   return _c("missing_templates")


# ── DEFAULTS ──
DEFAULT_CFG = {
    "default_industry": "hollywood",
    "movies_per_part": 25,
    "show_rating": True,
    "show_popularity": True,
    "show_lang_code": True,
    "include_year": True,
}


async def get_cfg() -> Dict[str, Any]:
    c = settings_coll()
    if c is None: return dict(DEFAULT_CFG)
    try:
        d = await c.find_one({"_id": "config"}) or {}
        out = dict(DEFAULT_CFG)
        out.update({k: v for k, v in d.items() if k != "_id"})
        return out
    except Exception:
        return dict(DEFAULT_CFG)


async def save_cfg(**fields) -> bool:
    c = settings_coll()
    if c is None: return False
    try:
        fields["updated_at"] = time.time()
        await c.update_one({"_id": "config"}, {"$set": fields}, upsert=True)
        return True
    except Exception:
        return False


# ── HISTORY ──
async def log_scan(data: Dict[str, Any]) -> bool:
    c = history_coll()
    if c is None: return False
    try:
        await c.insert_one({**data, "created_at": time.time()})
        return True
    except Exception:
        return False


async def recent_scans(limit: int = 15) -> List[Dict[str, Any]]:
    c = history_coll()
    if c is None: return []
    try:
        cur = c.find({}).sort("created_at", -1).limit(limit)
        return await cur.to_list(length=limit)
    except Exception:
        return []


async def clear_history() -> int:
    c = history_coll()
    if c is None: return 0
    try:
        r = await c.delete_many({})
        return r.deleted_count
    except Exception:
        return 0


# ── BUTTONS ──
async def get_buttons() -> List[Dict[str, Any]]:
    c = buttons_coll()
    if c is None: return []
    try:
        d = await c.find_one({"_id": "buttons"})
        return list(d.get("list") or []) if d else []
    except Exception:
        return []


async def set_buttons(buttons: List[Dict[str, Any]]) -> bool:
    c = buttons_coll()
    if c is None: return False
    try:
        await c.update_one(
            {"_id": "buttons"},
            {"$set": {"list": buttons, "updated_at": time.time()}},
            upsert=True,
        )
        return True
    except Exception:
        return False


__all__ = [
    "get_cfg", "save_cfg", "DEFAULT_CFG",
    "log_scan", "recent_scans", "clear_history",
    "get_buttons", "set_buttons",
]
