# ============================================================
# 🏨 DOWNTOWN VILLA — BROADCAST DATABASE
# ============================================================

from __future__ import annotations
import logging
import time
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def _sys_db():
    try:
        from database import db_registry
        return db_registry.get_system_db()
    except Exception:
        return None


def _user_db():
    try:
        from database import db_registry
        return db_registry.get_user_db()
    except Exception:
        return None


def _cfg_coll():
    db = _sys_db()
    return db["broadcast_config"] if db is not None else None


def _users_coll():
    db = _user_db()
    return db["users"] if db is not None else None


def _groups_coll():
    db = _user_db()
    return db["groups"] if db is not None else None


def _history_coll():
    db = _sys_db()
    return db["broadcast_history"] if db is not None else None


def _autodel_coll():
    db = _sys_db()
    return db["broadcast_autodelete"] if db is not None else None


# ─── Users ───
async def count_users() -> int:
    c = _users_coll()
    if c is None:
        return 0
    try:
        return await c.estimated_document_count()
    except Exception:
        return 0


async def get_all_users() -> List[int]:
    c = _users_coll()
    if c is None:
        return []
    ids: List[int] = []
    try:
        async for doc in c.find(
            {"blocked_bot": {"$ne": True}},
            {"id": 1, "user_id": 1},
        ):
            uid = doc.get("id") or doc.get("user_id")
            if uid:
                ids.append(int(uid))
    except Exception as e:
        logger.warning(f"[BC] users: {e}")
    return ids


async def delete_user(user_id: int) -> None:
    c = _users_coll()
    if c is None:
        return
    try:
        await c.delete_many(
            {"$or": [{"id": int(user_id)}, {"user_id": int(user_id)}]}
        )
    except Exception:
        pass


# ─── Groups ───
async def count_groups() -> int:
    c = _groups_coll()
    if c is None:
        return 0
    try:
        return await c.estimated_document_count()
    except Exception:
        return 0


async def get_all_groups() -> List[int]:
    c = _groups_coll()
    if c is None:
        return []
    ids: List[int] = []
    try:
        async for doc in c.find(
            {}, {"chat_id": 1, "id": 1, "chat_status": 1}
        ):
            cs = doc.get("chat_status") or {}
            if cs.get("is_disabled"):
                continue
            cid = doc.get("chat_id") or doc.get("id")
            if cid:
                ids.append(int(cid))
    except Exception as e:
        logger.warning(f"[BC] groups: {e}")
    return ids


# ─── Channels ───
async def get_saved_channels() -> List[Dict[str, Any]]:
    c = _cfg_coll()
    if c is None:
        return []
    try:
        doc = await c.find_one({"_id": "channels"}) or {}
        return list(doc.get("list") or [])
    except Exception as e:
        logger.warning(f"[BC] channels: {e}")
        return []


async def get_channel(chat_id: int) -> Optional[Dict[str, Any]]:
    for ch in await get_saved_channels():
        if ch.get("chat_id") == int(chat_id):
            return ch
    return None


async def save_channel(
    chat_id: int, title: str, username: Optional[str] = None
) -> bool:
    c = _cfg_coll()
    if c is None:
        return False
    try:
        doc = await c.find_one({"_id": "channels"}) or {"list": []}
        chans = [
            x for x in (doc.get("list") or [])
            if x.get("chat_id") != int(chat_id)
        ]
        chans.append({
            "chat_id": int(chat_id),
            "title": title or str(chat_id),
            "username": username,
            "caption": None,
            "buttons": None,
            "enabled": True,
            "primary": False,
            "added_at": time.time(),
        })
        await c.update_one(
            {"_id": "channels"},
            {"$set": {"list": chans, "updated_at": time.time()}},
            upsert=True,
        )
        return True
    except Exception as e:
        logger.warning(f"[BC] save channel: {e}")
        return False


async def update_channel(chat_id: int, **fields) -> bool:
    c = _cfg_coll()
    if c is None:
        return False
    try:
        doc = await c.find_one({"_id": "channels"}) or {"list": []}
        chans = list(doc.get("list") or [])
        found = False
        for ch in chans:
            if ch.get("chat_id") == int(chat_id):
                ch.update(fields)
                found = True
                break
        if not found:
            return False
        await c.update_one(
            {"_id": "channels"},
            {"$set": {"list": chans, "updated_at": time.time()}},
        )
        return True
    except Exception as e:
        logger.warning(f"[BC] update channel: {e}")
        return False


async def remove_channel(chat_id: int) -> bool:
    c = _cfg_coll()
    if c is None:
        return False
    try:
        doc = await c.find_one({"_id": "channels"}) or {"list": []}
        chans = list(doc.get("list") or [])
        new_list = [x for x in chans if x.get("chat_id") != int(chat_id)]
        await c.update_one(
            {"_id": "channels"},
            {"$set": {"list": new_list, "updated_at": time.time()}},
        )
        return len(new_list) < len(chans)
    except Exception:
        return False


# ─── Global caption / buttons ───
async def get_global_caption() -> str:
    from plugins.broadcast.config import DEFAULT_BROADCAST_CAPTION
    c = _cfg_coll()
    if c is None:
        return DEFAULT_BROADCAST_CAPTION
    try:
        doc = await c.find_one({"_id": "settings"}) or {}
        return doc.get("caption") or DEFAULT_BROADCAST_CAPTION
    except Exception:
        return DEFAULT_BROADCAST_CAPTION


async def set_global_caption(caption: str) -> bool:
    c = _cfg_coll()
    if c is None:
        return False
    try:
        await c.update_one(
            {"_id": "settings"},
            {"$set": {"caption": caption, "updated_at": time.time()}},
            upsert=True,
        )
        return True
    except Exception:
        return False


async def get_global_buttons() -> List[Dict[str, Any]]:
    c = _cfg_coll()
    if c is None:
        return []
    try:
        doc = await c.find_one({"_id": "settings"}) or {}
        return list(doc.get("buttons") or [])
    except Exception:
        return []


async def set_global_buttons(buttons: List[Dict[str, Any]]) -> bool:
    c = _cfg_coll()
    if c is None:
        return False
    try:
        await c.update_one(
            {"_id": "settings"},
            {"$set": {"buttons": buttons, "updated_at": time.time()}},
            upsert=True,
        )
        return True
    except Exception:
        return False


# ─── History ───
async def log_broadcast(data: Dict[str, Any]) -> None:
    c = _history_coll()
    if c is None:
        return
    try:
        data["created_at"] = time.time()
        await c.insert_one(data)
    except Exception:
        pass


async def get_history(limit: int = 10) -> List[Dict[str, Any]]:
    c = _history_coll()
    if c is None:
        return []
    try:
        cursor = c.find({}).sort("created_at", -1).limit(limit)
        docs = await cursor.to_list(length=limit)
        for d in docs:
            d.pop("_id", None)
        return docs
    except Exception:
        return []


# ─── Auto-delete ───
async def schedule_autodelete(
    chat_id: int, message_id: int, seconds: int, job_id: str
) -> None:
    c = _autodel_coll()
    if c is None:
        return
    try:
        await c.insert_one({
            "chat_id": int(chat_id),
            "message_id": int(message_id),
            "delete_at": time.time() + int(seconds),
            "job_id": job_id or "",
            "created_at": time.time(),
        })
    except Exception as e:
        logger.debug(f"[BC-AD] schedule: {e}")


async def count_scheduled_autodeletes() -> int:
    c = _autodel_coll()
    if c is None:
        return 0
    try:
        return await c.estimated_document_count()
    except Exception:
        return 0


async def get_due_autodeletes(limit: int = 200) -> List[Dict[str, Any]]:
    c = _autodel_coll()
    if c is None:
        return []
    try:
        cursor = c.find(
            {"delete_at": {"$lte": time.time()}}
        ).limit(limit)
        return await cursor.to_list(length=limit)
    except Exception:
        return []


async def remove_autodelete(doc_id) -> None:
    c = _autodel_coll()
    if c is None:
        return
    try:
        await c.delete_one({"_id": doc_id})
    except Exception:
        pass


async def get_all_groups_full() -> List[Dict[str, Any]]:
    """Return full group docs with id + title."""
    c = _groups_coll()
    if c is None:
        return []
    out: List[Dict[str, Any]] = []
    try:
        async for doc in c.find(
            {}, {"chat_id": 1, "id": 1, "title": 1, "chat_status": 1}
        ):
            cs = doc.get("chat_status") or {}
            if cs.get("is_disabled"):
                continue
            cid = doc.get("chat_id") or doc.get("id")
            if not cid:
                continue
            out.append({
                "chat_id": int(cid),
                "title": doc.get("title") or str(cid),
            })
    except Exception as e:
        logger.warning(f"[BC] groups full: {e}")
    return out


async def save_group_manual(chat_id: int, title: str) -> bool:
    """Insert a group doc manually (if bot is already in it)."""
    c = _groups_coll()
    if c is None:
        return False
    try:
        await c.update_one(
            {"chat_id": int(chat_id)},
            {"$set": {
                "chat_id": int(chat_id),
                "title": (title or str(chat_id))[:120],
                "manual": True,
            }},
            upsert=True,
        )
        return True
    except Exception as e:
        logger.warning(f"[BC] save group: {e}")
        return False
