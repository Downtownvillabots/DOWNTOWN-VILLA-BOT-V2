# ============================================================
# 🏨 DOWNTOWN VILLA — OTT STATE (sessions/jobs/confirm)
# ============================================================

from __future__ import annotations
import secrets
import time
import uuid
from typing import Any, Dict, Optional

from plugins.ott.config import SESSION_TTL, CONFIRM_TTL, JOB_TTL

# ═══════════════════════════════════════════════════════════
# SESSIONS (text input)
# ═══════════════════════════════════════════════════════════

_SESSIONS: Dict[int, Dict[str, Any]] = {}


def new_session(user_id: int, action: str, **data) -> str:
    tok = secrets.token_urlsafe(8)[:10]
    _SESSIONS[int(user_id)] = {
        "token": tok, "action": action,
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


# ═══════════════════════════════════════════════════════════
# JOBS (broadcast progress)
# ═══════════════════════════════════════════════════════════

_JOBS: Dict[str, Dict[str, Any]] = {}


def new_job(admin_id: int, target: str, total: int,
            progress_chat: int, progress_msg: int,
            ttl_seconds: int = 0) -> str:
    jid = uuid.uuid4().hex[:10]
    _JOBS[jid] = {
        "id": jid, "admin_id": admin_id, "target": target,
        "total": total, "sent": 0, "failed": 0,
        "started_at": time.time(), "last_edit": 0.0,
        "cancel_flag": False,
        "progress_chat": progress_chat, "progress_msg": progress_msg,
        "ttl_seconds": int(ttl_seconds),
    }
    return jid


def get_job(jid: str) -> Optional[Dict[str, Any]]:
    return _JOBS.get(jid)


def finish_job(jid: str) -> None:
    j = _JOBS.get(jid)
    if j:
        j["finished_at"] = time.time()


def cleanup_jobs() -> None:
    now = time.time()
    for jid in list(_JOBS.keys()):
        j = _JOBS[jid]
        if now - j.get("finished_at", j["started_at"]) > JOB_TTL:
            _JOBS.pop(jid, None)


# ═══════════════════════════════════════════════════════════
# CONFIRM TOKENS (cancel / delete actions)
# ═══════════════════════════════════════════════════════════

_CONFIRMS: Dict[str, Dict[str, Any]] = {}


def new_confirm(kind: str, **payload) -> str:
    tok = uuid.uuid4().hex[:12]
    _CONFIRMS[tok] = {
        "kind": kind, "payload": payload,
        "created": time.time(),
        "expires": time.time() + CONFIRM_TTL,
    }
    return tok


def get_confirm(tok: str) -> Optional[Dict[str, Any]]:
    c = _CONFIRMS.get(tok)
    if not c:
        return None
    if time.time() > c["expires"]:
        _CONFIRMS.pop(tok, None)
        return None
    return c


def drop_confirm(tok: str) -> None:
    _CONFIRMS.pop(tok, None)


def cleanup_confirms() -> None:
    now = time.time()
    for tok in list(_CONFIRMS.keys()):
        if _CONFIRMS[tok]["expires"] < now:
            _CONFIRMS.pop(tok, None)


def snapshot() -> Dict[str, int]:
    return {
        "sessions": len(_SESSIONS),
        "jobs": len(_JOBS),
        "confirms": len(_CONFIRMS),
    }
