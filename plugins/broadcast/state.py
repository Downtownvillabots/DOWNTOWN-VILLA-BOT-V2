# ============================================================
# 🏨 DOWNTOWN VILLA — BROADCAST STATE
# ============================================================
# Sessions · Jobs · Sources · Batches (multi-file)
# ============================================================

from __future__ import annotations
import secrets
import time
import uuid
from typing import Any, Dict, List, Optional

from plugins.broadcast.config import SESSION_TTL, SOURCE_TTL

# ─── SESSIONS ───
_SESSIONS: Dict[int, Dict[str, Any]] = {}

def new_session(user_id: int, action: str, **data) -> str:
    tok = secrets.token_urlsafe(8)[:10]
    _SESSIONS[int(user_id)] = {
        "token": tok, "action": action, "step": 1,
        "data": data, "expires": time.time() + SESSION_TTL,
    }
    return tok

def get_session(user_id: int) -> Optional[Dict[str, Any]]:
    s = _SESSIONS.get(int(user_id))
    if not s:
        return None
    if time.time() > s["expires"]:
        _SESSIONS.pop(int(user_id), None)
        return None
    return s

def clear_session(user_id: int) -> None:
    _SESSIONS.pop(int(user_id), None)

def cleanup_sessions() -> None:
    now = time.time()
    for uid in list(_SESSIONS.keys()):
        if _SESSIONS[uid]["expires"] < now:
            _SESSIONS.pop(uid, None)


# ─── JOBS ───
_ACTIVE_JOBS: Dict[str, Dict[str, Any]] = {}

def new_job(admin_id, kind, total, source_msg_id, source_chat_id,
            progress_chat_id, progress_msg_id,
            autodelete_seconds=0) -> str:
    jid = uuid.uuid4().hex[:10]
    _ACTIVE_JOBS[jid] = {
        "id": jid, "admin_id": admin_id, "kind": kind, "total": total,
        "sent": 0, "failed": 0, "blocked": 0, "deleted": 0,
        "started_at": time.time(), "status": "running",
        "cancel_flag": False, "last_edit": 0.0,
        "source_msg_id": source_msg_id, "source_chat_id": source_chat_id,
        "progress_chat_id": progress_chat_id,
        "progress_msg_id": progress_msg_id,
        "autodelete_seconds": int(autodelete_seconds or 0),
        "targets": [], "current_index": 0,
    }
    return jid

def get_job(jid):
    return _ACTIVE_JOBS.get(jid)

def finish_job(jid, status="completed"):
    j = _ACTIVE_JOBS.get(jid)
    if j:
        j["status"] = status
        j["finished_at"] = time.time()

def cleanup_jobs():
    now = time.time()
    for jid in list(_ACTIVE_JOBS.keys()):
        j = _ACTIVE_JOBS[jid]
        if j["status"] in ("completed", "cancelled", "failed"):
            if now - j.get("finished_at", now) > 300:
                _ACTIVE_JOBS.pop(jid, None)


# ─── SOURCES (single-file in-memory) ───
_SOURCES: Dict[str, Dict[str, Any]] = {}

def register_source(message) -> str:
    sid = uuid.uuid4().hex[:10]
    _SOURCES[sid] = {
        "message_id": message.id,
        "chat_id": message.chat.id,
        "created": time.time(),
        "expires": time.time() + SOURCE_TTL,
        "kind": (message.media.value if message.media else "text"),
    }
    return sid

def get_source(sid):
    s = _SOURCES.get(sid)
    if not s:
        return None
    if time.time() > s["expires"]:
        _SOURCES.pop(sid, None)
        return None
    return s

def cleanup_sources():
    now = time.time()
    for sid in list(_SOURCES.keys()):
        if _SOURCES[sid]["expires"] < now:
            _SOURCES.pop(sid, None)


# ─── BATCHES (multi-file via DB) ───
_SOURCE_COLL = "broadcast_sources"

def _src_coll():
    try:
        from database import db_registry
        db = db_registry.get_system_db()
        return db[_SOURCE_COLL] if db is not None else None
    except Exception:
        return None


async def save_source(message_id: int, chat_id: int, name: str) -> None:
    c = _src_coll()
    if c is None:
        return
    try:
        await c.update_one(
            {"message_id": int(message_id), "chat_id": int(chat_id)},
            {"$set": {
                "message_id": int(message_id),
                "chat_id": int(chat_id),
                "name": (name or "file")[:80],
                "created_at": time.time(),
            }},
            upsert=True,
        )
    except Exception:
        pass


async def list_sources(limit: int = 10) -> List[Dict[str, Any]]:
    """Newest-first list."""
    c = _src_coll()
    if c is None:
        return []
    try:
        cursor = c.find({}).sort("created_at", -1).limit(int(limit))
        docs = await cursor.to_list(length=int(limit))
        for d in docs:
            d.pop("_id", None)
        return docs
    except Exception:
        return []


async def clear_sources() -> int:
    c = _src_coll()
    if c is None:
        return 0
    try:
        r = await c.delete_many({})
        return r.deleted_count
    except Exception:
        return 0

# ─── BATCHES (channel uploads → one message with toggles) ───
_BATCHES: Dict[int, Dict[str, Any]] = {}
_BATCH_TTL = 3600


def new_batch(key: int, sid: str) -> Dict[str, Any]:
    b = {
        "sid": sid,
        "started_at": time.time(),
        "files": [],
        "reply_msg_id": None,
        "chat_id": int(key),
    }
    _BATCHES[int(key)] = b
    return b


def get_batch(key: int) -> Optional[Dict[str, Any]]:
    return _BATCHES.get(int(key))


def find_batch_by_sid(sid: str) -> Optional[Dict[str, Any]]:
    for b in _BATCHES.values():
        if b.get("sid") == sid:
            return b
    return None


def clear_batch(key: int) -> None:
    _BATCHES.pop(int(key), None)


def cleanup_batches() -> None:
    now = time.time()
    for k in list(_BATCHES.keys()):
        if now - _BATCHES[k].get("started_at", 0) > _BATCH_TTL:
            _BATCHES.pop(k, None)


# ─── DEBOUNCE ───
_DEBOUNCE: Dict[int, int] = {}

def set_debounce(key: int, msg_id: int) -> None:
    _DEBOUNCE[int(key)] = int(msg_id)

def get_debounce(key: int) -> Optional[int]:
    return _DEBOUNCE.get(int(key))

def clear_debounce(key: int) -> None:
    _DEBOUNCE.pop(int(key), None)


def snapshot() -> Dict[str, Any]:
    return {
        "sessions": len(_SESSIONS),
        "jobs": len(_ACTIVE_JOBS),
        "sources": len(_SOURCES),
        "debounce": len(_DEBOUNCE),
        "batches": len(_BATCHES),
    }
    
