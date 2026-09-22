# ============================================================
# 🏨 DOWNTOWN VILLA — SEARCH SESSION STORE
# ============================================================
#
# Short-lived store for group-search results.
#
# A session binds (user, chat, query) to a list of candidate
# files. The user taps a button → deep-link → PM → the session
# is looked up here and the file is delivered.
#
# Used by:
#   • plugins/search/group_search.py   (create)
#   • plugins/search/handlers.py       (get + update)
#   • core/start_router.py             (get)
#
# Public API (singleton):
#   sessions.create(user_id, chat_id, query, ...) → Session
#   sessions.get(sid)                             → Session | None
#   sessions.update(sid, **kwargs)                → bool
#   sessions.delete(sid)                          → bool
#   sessions.cleanup()                            → int
#
# ============================================================

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from typing import Any, Dict, List, Optional

from media_search.models import Session

logger = logging.getLogger(__name__)


# ── CONFIG ──

DEFAULT_TTL = 1800.0         # 30 min
MAX_SESSIONS = 5000          # safety cap
CLEANUP_INTERVAL = 120.0     # purge every 2 min


# ============================================================
# STORE
# ============================================================

class SessionStore:
    """In-memory session registry."""

    def __init__(self) -> None:
        self._sessions: Dict[str, Session] = {}
        self._lock = asyncio.Lock()
        self._cleanup_task: Optional[asyncio.Task] = None

    # ── CREATE ──

    async def create(
        self,
        user_id: int,
        chat_id: int,
        query: str = "",
        normalized_query: str = "",
        mode: str = "movie",
        year: Optional[int] = None,
        candidates: Optional[List[Dict[str, Any]]] = None,
        ttl: float = DEFAULT_TTL,
    ) -> Optional[Session]:
        """Create + store a session. Returns the Session or None on error."""
        try:
            async with self._lock:
                # Cap check — evict oldest if over limit
                if len(self._sessions) >= MAX_SESSIONS:
                    self._evict_oldest(MAX_SESSIONS // 10)

                session = Session(
                    session_id=uuid.uuid4().hex[:12],
                    user_id=int(user_id),
                    chat_id=int(chat_id),
                    query=str(query or ""),
                    normalized_query=str(normalized_query or ""),
                    mode=str(mode or "movie"),
                    year=year,
                    candidates=list(candidates or []),
                    created_at=time.time(),
                    updated_at=time.time(),
                    expires_at=time.time() + float(ttl),
                )
                self._sessions[session.session_id] = session
                return session
        except Exception as e:
            logger.exception(f"[SESSION] create: {e}")
            return None

    # ── GET ──

    async def get(self, sid: str) -> Optional[Session]:
        """Return session if it exists and hasn't expired."""
        if not sid:
            return None
        try:
            async with self._lock:
                s = self._sessions.get(sid)
                if s is None:
                    return None
                if s.is_expired():
                    self._sessions.pop(sid, None)
                    return None
                s.touch()
                return s
        except Exception:
            return None

    def get_sync(self, sid: str) -> Optional[Session]:
        """Sync variant — safe because we never await inside."""
        if not sid:
            return None
        s = self._sessions.get(sid)
        if s is None:
            return None
        if s.is_expired():
            self._sessions.pop(sid, None)
            return None
        return s

    # ── UPDATE ──

    async def update(self, sid: str, **kwargs) -> bool:
        """Patch fields on an existing session."""
        if not sid:
            return False
        try:
            async with self._lock:
                s = self._sessions.get(sid)
                if s is None:
                    return False
                for k, v in kwargs.items():
                    if hasattr(s, k):
                        setattr(s, k, v)
                s.touch()
                return True
        except Exception:
            return False

    # ── DELETE ──

    async def delete(self, sid: str) -> bool:
        if not sid:
            return False
        async with self._lock:
            return self._sessions.pop(sid, None) is not None

    # ── CLEANUP ──

    async def cleanup(self) -> int:
        """Remove expired sessions. Returns count removed."""
        now = time.time()
        removed = 0
        async with self._lock:
            for sid in list(self._sessions.keys()):
                s = self._sessions.get(sid)
                if s is None:
                    continue
                if s.expires_at < now:
                    self._sessions.pop(sid, None)
                    removed += 1
        return removed

    def _evict_oldest(self, n: int) -> int:
        """Evict N oldest sessions (no lock — caller must hold)."""
        if not self._sessions or n <= 0:
            return 0
        ordered = sorted(
            self._sessions.items(),
            key=lambda kv: kv[1].created_at,
        )
        removed = 0
        for sid, _ in ordered[:n]:
            self._sessions.pop(sid, None)
            removed += 1
        return removed

    # ── BACKGROUND LOOP ──

    def start_cleanup(self, interval: float = CLEANUP_INTERVAL) -> None:
        if self._cleanup_task and not self._cleanup_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
            self._cleanup_task = loop.create_task(self._loop(interval))
        except RuntimeError:
            pass

    async def _loop(self, interval: float) -> None:
        while True:
            try:
                await asyncio.sleep(interval)
                n = await self.cleanup()
                if n:
                    logger.debug(f"[SESSION] purged {n} expired")
            except asyncio.CancelledError:
                return
            except Exception as e:
                logger.debug(f"[SESSION] cleanup: {e}")

    def stop_cleanup(self) -> None:
        if self._cleanup_task and not self._cleanup_task.done():
            self._cleanup_task.cancel()

    # ── STATS ──

    def stats(self) -> Dict[str, Any]:
        return {
            "active": len(self._sessions),
            "max": MAX_SESSIONS,
            "cleanup_running": bool(
                self._cleanup_task and not self._cleanup_task.done()
            ),
        }

    def count(self) -> int:
        return len(self._sessions)


# ============================================================
# SINGLETON
# ============================================================

sessions = SessionStore()


# ============================================================
# BOOT HELPER
# ============================================================

def ensure_cleanup(interval: float = CLEANUP_INTERVAL) -> None:
    """Wire from startup.py."""
    sessions.start_cleanup(interval)


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    "SessionStore",
    "sessions",
    "ensure_cleanup",
    "DEFAULT_TTL",
    "MAX_SESSIONS",
]
