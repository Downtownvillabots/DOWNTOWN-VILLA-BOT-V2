# ============================================================
# 🏨 DOWNTOWN VILLA — OTT DATABASE
# ============================================================
# Reads channels/groups/users from BOT DB (broadcast module).
# Stores only: enabled chat_ids + per-target configs + fav langs.
# ============================================================

from __future__ import annotations
import logging
import time
from typing import Any, Dict, List, Optional

from plugins.ott.config import DEFAULT_FAV_LANGS, LANG_CODES

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
    return {
        "mode": "off",
        "hour": 10,
        "day_of_week": 0,
        "day_of_month": 1,
    }


def _empty() -> Dict[str, Any]:
    return {
        "fav_languages": list(DEFAULT_FAV_LANGS),
        "enabled_channels": [],
        "channel_configs": {},
        "enabled_groups": [],
        "group_configs": {},
        "users": {
            "running": False,
            "languages": [],
            "frequency": _default_freq(),
            "last_sent_key": "",
        },
        "premium": {
            "running": False,
            "languages": [],
            "frequency": _default_freq(),
            "last_sent_key": "",
        },
    }


# ═══════════════════════════════════════════════════════════
# LOAD / SAVE
# ═══════════════════════════════════════════════════════════

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
    langs = [c for c in langs if c in LANG_CODES]
    return await save(fav_languages=langs)


# ═══════════════════════════════════════════════════════════
# LIVE CHANNELS FROM BROADCAST MODULE
# ═══════════════════════════════════════════════════════════

async def get_live_channels() -> List[Dict[str, Any]]:
    """Read channel list from broadcast module."""
    try:
        from plugins.broadcast import database as BDB
        chans = await BDB.get_saved_channels()
        return [
            {"chat_id": int(c["chat_id"]),
             "title": c.get("title") or str(c["chat_id"])}
            for c in chans if c.get("chat_id")
        ]
    except Exception as e:
        logger.debug(f"[OTT-DB] live channels: {e}")
        return []


async def get_live_groups() -> List[Dict[str, Any]]:
    """Read groups from users_db."""
    try:
        from plugins.broadcast import database as BDB
        return await BDB.get_all_groups_full()
    except Exception as e:
        logger.debug(f"[OTT-DB] live groups: {e}")
        return []


async def count_live_users() -> int:
    try:
        from plugins.broadcast import database as BDB
        return await BDB.count_users()
    except Exception:
        return 0


async def count_live_premium() -> int:
    try:
        from plugins.premium import state as PS
        return len(await PS.list_users(limit=50000))
    except Exception:
        return 0


# ═══════════════════════════════════════════════════════════
# CHANNELS (enabled + config)
# ═══════════════════════════════════════════════════════════

async def get_enabled_channels() -> List[int]:
    d = await load()
    return [int(x) for x in (d.get("enabled_channels") or [])]


async def is_channel_enabled(cid: int) -> bool:
    return int(cid) in await get_enabled_channels()


async def toggle_channel(cid: int) -> bool:
    """Returns True if now enabled, False if disabled."""
    d = await load()
    enabled = [int(x) for x in (d.get("enabled_channels") or [])]
    cid = int(cid)
    if cid in enabled:
        enabled.remove(cid)
        new_state = False
    else:
        enabled.append(cid)
        new_state = True
    cfg = dict(d.get("channel_configs") or {})
    if new_state and str(cid) not in cfg:
        cfg[str(cid)] = {
            "running": True,
            "languages": list(d.get("fav_languages") or DEFAULT_FAV_LANGS),
            "frequency": _default_freq(),
            "last_sent_key": "",
        }
    await save(enabled_channels=enabled, channel_configs=cfg)
    return new_state


async def get_channel_config(cid: int) -> Dict[str, Any]:
    d = await load()
    cfg = dict(d.get("channel_configs") or {})
    cur = cfg.get(str(int(cid))) or {}
    out = {
        "running": cur.get("running", True),
        "languages": cur.get("languages") or list(
            d.get("fav_languages") or DEFAULT_FAV_LANGS),
        "frequency": cur.get("frequency") or _default_freq(),
        "last_sent_key": cur.get("last_sent_key") or "",
    }
    return out


async def update_channel_config(cid: int, **fields) -> bool:
    d = await load()
    cfg = dict(d.get("channel_configs") or {})
    key = str(int(cid))
    cur = dict(cfg.get(key) or {})
    cur.update(fields)
    cfg[key] = cur
    return await save(channel_configs=cfg)


# ═══════════════════════════════════════════════════════════
# GROUPS
# ═══════════════════════════════════════════════════════════

async def get_enabled_groups() -> List[int]:
    d = await load()
    return [int(x) for x in (d.get("enabled_groups") or [])]


async def is_group_enabled(gid: int) -> bool:
    return int(gid) in await get_enabled_groups()


async def toggle_group(gid: int) -> bool:
    d = await load()
    enabled = [int(x) for x in (d.get("enabled_groups") or [])]
    gid = int(gid)
    if gid in enabled:
        enabled.remove(gid)
        new_state = False
    else:
        enabled.append(gid)
        new_state = True
    cfg = dict(d.get("group_configs") or {})
    if new_state and str(gid) not in cfg:
        cfg[str(gid)] = {
            "running": True,
            "languages": list(d.get("fav_languages") or DEFAULT_FAV_LANGS),
            "frequency": _default_freq(),
            "last_sent_key": "",
        }
    await save(enabled_groups=enabled, group_configs=cfg)
    return new_state


async def get_group_config(gid: int) -> Dict[str, Any]:
    d = await load()
    cfg = dict(d.get("group_configs") or {})
    cur = cfg.get(str(int(gid))) or {}
    return {
        "running": cur.get("running", True),
        "languages": cur.get("languages") or list(
            d.get("fav_languages") or DEFAULT_FAV_LANGS),
        "frequency": cur.get("frequency") or _default_freq(),
        "last_sent_key": cur.get("last_sent_key") or "",
    }


async def update_group_config(gid: int, **fields) -> bool:
    d = await load()
    cfg = dict(d.get("group_configs") or {})
    key = str(int(gid))
    cur = dict(cfg.get(key) or {})
    cur.update(fields)
    cfg[key] = cur
    return await save(group_configs=cfg)


# ═══════════════════════════════════════════════════════════
# USERS / PREMIUM
# ═══════════════════════════════════════════════════════════

async def get_users() -> Dict[str, Any]:
    d = await load()
    u = d.get("users") or {}
    return {
        "running": bool(u.get("running")),
        "languages": u.get("languages") or [],
        "frequency": u.get("frequency") or _default_freq(),
        "last_sent_key": u.get("last_sent_key") or "",
    }


async def update_users(**fields) -> bool:
    cur = await get_users()
    cur.update(fields)
    return await save(users=cur)


async def get_premium() -> Dict[str, Any]:
    d = await load()
    p = d.get("premium") or {}
    return {
        "running": bool(p.get("running")),
        "languages": p.get("languages") or [],
        "frequency": p.get("frequency") or _default_freq(),
        "last_sent_key": p.get("last_sent_key") or "",
    }


async def update_premium(**fields) -> bool:
    cur = await get_premium()
    cur.update(fields)
    return await save(premium=cur)


__all__ = [
    "load", "save",
    "get_fav_languages", "set_fav_languages",
    "get_live_channels", "get_live_groups",
    "count_live_users", "count_live_premium",
    "get_enabled_channels", "is_channel_enabled",
    "toggle_channel", "get_channel_config", "update_channel_config",
    "get_enabled_groups", "is_group_enabled",
    "toggle_group", "get_group_config", "update_group_config",
    "get_users", "update_users",
    "get_premium", "update_premium",
]
