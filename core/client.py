# ============================================================
# 🏨 DOWNTOWN VILLA — CLIENT ENGINE (FUTURISTIC)
# ============================================================
#
# Custom Pyrogram Client with v2 enhancements.
#
# Features (new in v2):
#   • Bot identity cached after first get_me()
#   • Live bot username + id available everywhere
#   • Safe start/stop hooks with timing
#   • Auto plugin discovery from plugins/
#   • Session name from env
#   • Config snapshot for /admin
#   • Graceful shutdown
#   • Register as global singleton
#   • Rocket-timed boot
#
# ============================================================

from __future__ import annotations

import os
import time
import asyncio
import logging
from typing import Any, Dict, Optional

from pyrogram import Client as _PyroClient
from pyrogram.enums import ParseMode
from pyrogram.types import User

from core import config
from core import rocket

logger = logging.getLogger(__name__)


# ============================================================
# SECTION 1 — CLIENT
# ============================================================

class VillaClient(_PyroClient):
    """
    DOWNTOWN VILLA's custom Pyrogram client.

    Usage:
        from core.client import client
        await client.start()
        ...
        await client.stop()
    """

    def __init__(self) -> None:
        super().__init__(
            name=config.SESSION,
            api_id=config.API_ID,
            api_hash=config.API_HASH,
            bot_token=config.BOT_TOKEN,
            workers=50,
            plugins=dict(root="plugins"),
            sleep_threshold=5,
            parse_mode=ParseMode.HTML,
            # Disable Pyrogram's noisy update logs
            no_updates=False,
        )

        # ── Cached identity ──
        self._identity: Optional[User] = None
        self._identity_locked = asyncio.Lock()

        # ── Boot metrics ──
        self.started_at: Optional[float] = None
        self.start_duration: float = 0.0
        self.stop_duration: float = 0.0

    # ────────── IDENTITY CACHE ──────────

    async def identity(self) -> User:
        """
        Return bot's own User object, cached.
        First call hits Telegram, subsequent calls are instant.
        """
        if self._identity is not None:
            return self._identity

        async with self._identity_locked:
            if self._identity is not None:
                return self._identity
            self._identity = await self.get_me()
            logger.info(
                f"[CLIENT] Identity: @{self._identity.username} "
                f"(id={self._identity.id})"
            )
            return self._identity

    @property
    def bot_id(self) -> int:
        return int(self._identity.id) if self._identity else 0

    @property
    def bot_username(self) -> str:
        return (self._identity.username or "") if self._identity else ""

    def bot_link(self, payload: str = "") -> str:
        u = self.bot_username
        if not u:
            return "https://t.me/"
        if payload:
            return f"https://t.me/{u}?start={payload}"
        return f"https://t.me/{u}"

    # ────────── SAFE START ──────────

    async def start(self) -> "VillaClient":
        """Boot the client + measure time."""
        t0 = time.perf_counter()
        await super().start()
        self.start_duration = time.perf_counter() - t0
        self.started_at = time.time()

        # Warm identity cache
        await self.identity()

        logger.info(
            f"[CLIENT] ✅ Started in {self.start_duration:.2f}s "
            f"as @{self.bot_username}"
        )
        return self

    # ────────── SAFE STOP ──────────

    async def stop(self, *args, **kwargs) -> None:
        """Stop the client + measure time."""
        t0 = time.perf_counter()
        try:
            await super().stop(*args, **kwargs)
        except Exception as e:
            logger.warning(f"[CLIENT] Stop error: {e}")
        self.stop_duration = time.perf_counter() - t0
        logger.info(f"[CLIENT] Stopped in {self.stop_duration:.2f}s")

    # ────────── UPTIME ──────────

    @property
    def uptime(self) -> float:
        if not self.started_at:
            return 0.0
        return time.time() - self.started_at

    # ────────── SNAPSHOT ──────────

    def snapshot(self) -> Dict[str, Any]:
        """Safe identity snapshot for /admin."""
        return {
            "id": self.bot_id,
            "username": self.bot_username,
            "session": config.SESSION,
            "started": bool(self.started_at),
            "uptime": round(self.uptime, 1),
            "start_duration": round(self.start_duration, 3),
            "workers": 50,
        }


# ============================================================
# SECTION 2 — SINGLETON
# ============================================================

client: Optional[VillaClient] = None


def get_client() -> VillaClient:
    """Get-or-create the global client."""
    global client
    if client is None:
        client = VillaClient()
    return client


# ============================================================
# SECTION 3 — LIFECYCLE HELPERS
# ============================================================

async def boot() -> VillaClient:
    """
    Boot sequence with timing + banner + config validation.

    Usage:
        c = await boot()
    """
    errors = config.validate()
    if errors:
        for e in errors:
            logger.critical(f"[CLIENT] Config error: {e}")
        raise RuntimeError("Invalid configuration")

    c = get_client()
    with rocket.timer("client.boot"):
        await c.start()

    return c


async def shutdown() -> None:
    """Graceful shutdown with timing."""
    global client
    if client is None:
        return
    with rocket.timer("client.shutdown"):
        await client.stop()
    client = None


# ============================================================
# SECTION 4 — DECORATORS (convenience)
# ============================================================

def require_client(fn):
    """
    Decorator: injects global client as first arg if not passed.

    >>> @require_client
    ... async def send(chat_id): ...
    """
    import functools

    @functools.wraps(fn)
    async def _wrapped(*args, **kwargs):
        c = get_client()
        return await fn(c, *args, **kwargs)

    return _wrapped


# ============================================================
# SECTION 5 — PUBLIC EXPORTS
# ============================================================

__all__ = [
    "VillaClient",
    "client",
    "get_client",
    "boot",
    "shutdown",
    "require_client",
]
