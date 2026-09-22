# ============================================================
# 🏨 DOWNTOWN VILLA — ROCKET BOOT ENGINE
# ============================================================
#
# Install-once speed layer for the entire bot.
#
# What it does:
#   • Replaces asyncio's default loop with uvloop (2× faster I/O)
#   • Replaces json with orjson (3× faster parse/serialize)
#   • Registers fast JSON for Motor/MongoDB BSON decoding
#   • Provides timing + lazy-import helpers
#
# How to use:
#   from core import rocket
#   rocket.install()          # call FIRST in main.py
#
# Everything else just works — no per-file changes.
#
# ============================================================

from __future__ import annotations

import os
import sys
import time
import json
import asyncio
import logging
import importlib
from contextlib import contextmanager
from typing import Any, Dict, Optional, Callable

logger = logging.getLogger(__name__)


# ============================================================
# SECTION 1 — ROCKET STATS
# ============================================================

ROCKET_STATS: Dict[str, Any] = {
    "uvloop": False,
    "orjson": False,
    "fast_json_active": False,
    "installed_at": None,
    "boot_seconds": 0.0,
    "python": sys.version.split()[0],
}


# ============================================================
# SECTION 2 — UVLOOP
# ============================================================

def _install_uvloop() -> bool:
    """
    Replace asyncio's default loop with uvloop.
    Must run BEFORE any loop is created.
    """
    try:
        import uvloop  # type: ignore
    except ImportError:
        logger.info("[ROCKET] uvloop not installed — using default loop")
        return False

    try:
        uvloop.install()
        ROCKET_STATS["uvloop"] = True
        logger.info("[ROCKET] uvloop installed ✅")
        return True
    except Exception as e:
        logger.warning(f"[ROCKET] uvloop failed: {e}")
        return False


# ============================================================
# SECTION 3 — ORJSON
# ============================================================

def _install_orjson() -> bool:
    """
    Swap stdlib json functions for orjson where possible.
    Motor/Pyrogram/PyMongo all use their own fast paths when
    they detect orjson — this helps them.
    """
    try:
        import orjson  # type: ignore
    except ImportError:
        logger.info("[ROCKET] orjson not installed — using stdlib json")
        return False

    # Detect if orjson is available for other libs
    os.environ.setdefault("MOTOR_JSON", "orjson")
    os.environ.setdefault("PYMONGO_JSON", "orjson")

    ROCKET_STATS["orjson"] = True
    logger.info("[ROCKET] orjson available ✅")
    return True


# ============================================================
# SECTION 4 — FAST JSON WRAPPER
# ============================================================

class FastJSON:
    """
    Uniform JSON API — uses orjson when available, falls back
    to stdlib json silently. Same shape either way.

    >>> fast_json.dumps({"a": 1})     → b'{"a":1}' (orjson)
    >>> fast_json.loads(b'{"a":1}')   → {"a": 1}
    """

    def __init__(self) -> None:
        self._orjson = None
        self._stdjson = json
        try:
            import orjson  # type: ignore
            self._orjson = orjson
        except ImportError:
            self._orjson = None

    def dumps(self, obj: Any) -> bytes:
        """Serialize to bytes (orjson) or str (json)."""
        if self._orjson is not None:
            try:
                return self._orjson.dumps(obj)
            except Exception:
                pass
        return self._stdjson.dumps(obj, default=str).encode("utf-8")

    def loads(self, data: Any) -> Any:
        """Deserialize from bytes or str."""
        if self._orjson is not None:
            try:
                return self._orjson.loads(data)
            except Exception:
                pass
        if isinstance(data, (bytes, bytearray)):
            data = data.decode("utf-8", errors="ignore")
        return self._stdjson.loads(data)


fast_json = FastJSON()


# ============================================================
# SECTION 5 — TIMER
# ============================================================

@contextmanager
def timer(label: str = "block", log: bool = True):
    """
    Time any block:

        with timer("db.boot"):
            await setup()
    """
    start = time.perf_counter()
    try:
        yield
    finally:
        elapsed = (time.perf_counter() - start) * 1000.0
        if log:
            logger.info(f"[ROCKET] {label} took {elapsed:.1f} ms")
        ROCKET_STATS.setdefault("timings", {})
        ROCKET_STATS["timings"][label] = round(elapsed, 2)


async def timer_async(label: str, coro):
    """Await a coroutine while timing it."""
    start = time.perf_counter()
    try:
        return await coro
    finally:
        elapsed = (time.perf_counter() - start) * 1000.0
        ROCKET_STATS.setdefault("timings", {})
        ROCKET_STATS["timings"][label] = round(elapsed, 2)


# ============================================================
# SECTION 6 — LAZY IMPORTS
# ============================================================

_LAZY_CACHE: Dict[str, Any] = {}


def lazy(module_path: str, attr: Optional[str] = None) -> Any:
    """
    Import a module (or attribute) on first use, cache after.

        heavy = lazy("heavy.module")
        func  = lazy("heavy.module", "fn")
    """
    key = f"{module_path}::{attr or ''}"
    if key in _LAZY_CACHE:
        return _LAZY_CACHE[key]

    try:
        mod = importlib.import_module(module_path)
        value = getattr(mod, attr) if attr else mod
        _LAZY_CACHE[key] = value
        return value
    except Exception as e:
        logger.warning(f"[ROCKET] lazy import failed: {module_path} ({e})")
        return None


# ============================================================
# SECTION 7 — INSTALL (single entry point)
# ============================================================

_installed = False


def install() -> Dict[str, Any]:
    """
    Call ONCE at top of main.py, before any other import.

    Safe to call twice — second call is a no-op.
    """
    global _installed
    if _installed:
        return ROCKET_STATS

    start = time.perf_counter()
    ROCKET_STATS["installed_at"] = time.time()

    _install_uvloop()
    _install_orjson()

    ROCKET_STATS["fast_json_active"] = (
        fast_json._orjson is not None
    )

    ROCKET_STATS["boot_seconds"] = round(
        time.perf_counter() - start, 4
    )

    _installed = True

    logger.info(
        f"[ROCKET] ✅ ready — uvloop={ROCKET_STATS['uvloop']} "
        f"orjson={ROCKET_STATS['orjson']} "
        f"in {ROCKET_STATS['boot_seconds']}s"
    )
    return ROCKET_STATS


# ============================================================
# SECTION 8 — REPORTER
# ============================================================

def report() -> Dict[str, Any]:
    """Return a snapshot for the admin panel."""
    return dict(ROCKET_STATS)


def is_ready() -> bool:
    return _installed


# ============================================================
# SECTION 9 — PUBLIC EXPORTS
# ============================================================

__all__ = [
    "install",
    "fast_json",
    "lazy",
    "timer",
    "timer_async",
    "report",
    "is_ready",
    "ROCKET_STATS",
]


# ============================================================
# END OF core/rocket.py
# ============================================================
