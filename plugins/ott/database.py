# ============================================================
# 🏨 DOWNTOWN VILLA — OTT DATABASE
# ============================================================

from __future__ import annotations
import logging
import time
from typing import Any, Dict, List, Optional

from plugins.ott.config import DEFAULT_FAV_LANGS

logger = logging.getLogger(__name__)

DOC_ID = "ott_config"


def _coll():
    try:
        from database import db_registry
        db = db_registry.get_system_db()
        return db["ott_config"] if db is not None else None
    except Exception:
        return None


def _default_freq() -> Dict[str, Any]:
    return {"mode": "off", "hour": 10,
            "day_of_week": 0, "day_of_month": 1}


def _empty() -> Dict[str, Any]:
    return {
        "fav_languages": list(DEFAULT_FAV_LANGS),
        "channels": [],
        "groups": [],
        "users": {"running": False, "languages": [],
                  "frequency": _default_freq(), "last_sent_key": ""},
        "premium": {"running": False, "languages": [],
                    "frequency": _default_freq(), "last_sent_key": ""},
    }


async def load() -> Dict[str, Any]:
    c = _coll()
    if c is None:
        return _empty()
    try:
        d = await c.find_one({"_id": DOC_ID}) or {}
        out = _empty()
        for k, v in d.items():
            if k == "_id":
                continue
            out[k] = v
        return out
    except Exception as e:
        logger.debug(f"[OTT-DB] load: {e}")
        return _empty()


async def save(**fields) -> bool:
    c = _coll()
    if c is None:
        return False
    try:
        fields["updated_at"] = time.time()
        await c.update_one({"_id": DOC_ID}, {"$set": fields}, upsert=True)
        return True
    except Exception as e:
        logger.debug(f"[OTT-DB] save: {e}")
        return False


# ═══════════════════════════════════════════════════════════
# FAVORITE LANGUAGES
# ═══════════════════════════════════════════════════════════

async def get_fav_languages() -> List[str]:
    d = await load()
    return list(d.get("fav_languages") or DEFAULT_FAV_LANGS)


async def set_fav_languages(langs: List[str]) -> bool:
    return await save(fav_languages=list(langs))


# ═══════════════════════════════════════════════════════════
# CHANNELS
# ═══════════════════════════════════════════════════════════

async def get_channels() -> List[Dict[str, Any]]:
    d = await load()
    return list(d.get("channels") or [])


async def get_channel(chat_id: int) -> Optional[Dict[str, Any]]:
    for c in await get_channels():
        if int(c.get("chat_id", 0)) == int(chat_id):
            return c
    return None


async def add_channel(chat_id: int, title: str) -> bool:
    d = await load()
    chans = [c for c in (d.get("channels") or [])
             if int(c.get("chat_id", 0)) != int(chat_id)]
    chans.append({
        "chat_id": int(chat_id),
        "title": title or str(chat_id),
        "running": True,
        "languages": list(d.get("fav_languages") or DEFAULT_FAV_LANGS),
        "frequency": _default_freq(),
        "last_sent_key": "",
        "created_at": time.time(),
    })
    return await save(channels=chans)


async def remove_channel(chat_id: int) -> bool:
    d = await load()
    chans = [c for c in (d.get("channels") or [])
             if int(c.get("chat_id", 0)) != int(chat_id)]
    return await save(channels=chans)


async def update_channel(chat_id: int, **fields) -> bool:
    d = await load()
    chans = list(d.get("channels") or [])
    found = False
    for c in chans:
        if int(c.get("chat_id", 0)) == int(chat_id):
            c.update(fields)
            found = True
            break
    if not found:
        return False
    return await save(channels=chans)


# ═══════════════════════════════════════════════════════════
# GROUPS
# ═══════════════════════════════════════════════════════════

async def get_groups() -> List[Dict[str, Any]]:
    d = await load()
    return list(d.get("groups") or [])


async def get_group(chat_id: int) -> Optional[Dict[str, Any]]:
    for g in await get_groups():
        if int(g.get("chat_id", 0)) == int(chat_id):
            return g
    return None


async def add_group(chat_id: int, title: str) -> bool:
    d = await load()
    grps = [g for g in (d.get("groups") or [])
            if int(g.get("chat_id", 0)) != int(chat_id)]
    grps.append({
        "chat_id": int(chat_id),
        "title": title or str(chat_id),
        "running": True,
        "languages": list(d.get("fav_languages") or DEFAULT_FAV_LANGS),
        "frequency": _default_freq(),
        "last_sent_key": "",
        "created_at": time.time(),
    })
    return await save(groups=grps)


async def remove_group(chat_id: int) -> bool:
    d = await load()
    grps = [g for g in (d.get("groups") or [])
            if int(g.get("chat_id", 0)) != int(chat_id)]
    return await save(groups=grps)


async def update_group(chat_id: int, **fields) -> bool:
    d = await load()
    grps = list(d.get("groups") or [])
    found = False
    for g in grps:
        if int(g.get("chat_id", 0)) == int(chat_id):
            g.update(fields)
            found = True
            break
    if not found:
        return False
    return await save(groups=grps)


# ═══════════════════════════════════════════════════════════
# USERS / PREMIUM
# ═══════════════════════════════════════════════════════════

async def get_users() -> Dict[str, Any]:
    d = await load()
    return d.get("users") or _empty()["users"]


async def update_users(**fields) -> bool:
    cur = await get_users()
    cur.update(fields)
    return await save(users=cur)


async def get_premium() -> Dict[str, Any]:
    d = await load()
    return d.get("premium") or _empty()["premium"]


async def update_premium(**fields) -> bool:
    cur = await get_premium()
    cur.update(fields)
    return await save(premium=cur)


__all__ = [
    "load", "save",
    "get_fav_languages", "set_fav_languages",
    "get_channels", "get_channel", "add_channel",
    "remove_channel", "update_channel",
    "get_groups", "get_group", "add_group",
    "remove_group", "update_group",
    "get_users", "update_users",
    "get_premium", "update_premium",
]
