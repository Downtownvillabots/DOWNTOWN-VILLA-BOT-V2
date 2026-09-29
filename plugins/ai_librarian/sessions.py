# ============================================================
# 🎛️ AI LIBRARIAN — SESSIONS + LIVE TASK TRACKING
# ============================================================
from __future__ import annotations
import asyncio, logging, time
from typing import Any, Dict, Optional

from plugins.ai_librarian.fonts import SESSION_TTL

logger = logging.getLogger(__name__)

_SESSIONS: Dict[int, Dict[str, Any]] = {}
_LIVE_TASKS: Dict[int, asyncio.Task] = {}


def _new_session(uid, action, **data):
    _kill_live_task(uid)
    _SESSIONS[uid] = {
        "action": action,
        "expires": time.time() + SESSION_TTL,
        **data,
    }


def _get_session(uid):
    s = _SESSIONS.get(uid)
    if not s: return None
    if time.time() > s.get("expires", 0):
        _SESSIONS.pop(uid, None); return None
    return s


def _clear_session(uid):
    _kill_live_task(uid)
    _SESSIONS.pop(uid, None)


def _kill_live_task(uid):
    t = _LIVE_TASKS.pop(uid, None)
    if t and not t.done():
        try: t.cancel()
        except Exception: pass


def _cleanup_sessions():
    now = time.time()
    for uid in list(_SESSIONS.keys()):
        s = _SESSIONS.get(uid) or {}
        if s.get("expires", 0) < now:
            _kill_live_task(uid)
            _SESSIONS.pop(uid, None)


__all__ = [
    "_SESSIONS", "_LIVE_TASKS",
    "_new_session", "_get_session", "_clear_session",
    "_kill_live_task", "_cleanup_sessions",
]
