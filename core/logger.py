# ============================================================
# 🏨 DOWNTOWN VILLA — LOGGER ENGINE (FUTURISTIC)
# ============================================================
#
# Every log line goes to STDOUT (Render captures it) and to
# an in-memory ring buffer that the admin panel reads live.
#
# Features (all new in v2):
#   • Big DOWNTOWN VILLA ASCII banner on boot
#   • All logs → stdout (Render captures automatically)
#   • Color-coded console output (INFO/WARN/ERR)
#   • In-memory ring buffer (last 500 lines) for /admin
#   • Separate ERROR ring for fast error lookup
#   • Optional Telegram forwarder (LOG_CHANNEL)
#   • Rocket-aware formatter (shows module path + line)
#   • Auto-capture uncaught exceptions + asyncio warnings
#   • Logger hierarchy fixups (silence noisy libs)
#   • Zero duplicate log lines
#
# Used by: every file in the bot
#
# ============================================================

from __future__ import annotations

import io
import os
import sys
import time
import logging
import asyncio
import traceback
import threading
from collections import deque
from datetime import datetime, timezone, timedelta
from typing import Any, Callable, Deque, Dict, Optional

# ============================================================
# SECTION 1 — CONSTANTS
# ============================================================

IST = timezone(timedelta(hours=5, minutes=30))

MEMORY_MAX = int(os.getenv("LOG_MEMORY_MAX", "500"))
ERROR_MAX = int(os.getenv("LOG_ERROR_MAX", "200"))

# Render sets RENDER=true when running on their platform
IS_RENDER = os.getenv("RENDER", "").lower() in ("1", "true", "yes")

# Colors (ANSI) — auto-disabled if not TTY
USE_COLOR = sys.stdout.isatty() and not IS_RENDER


# ============================================================
# SECTION 2 — COLORS
# ============================================================

class _C:
    RESET = "\033[0m"  if USE_COLOR else ""
    BOLD  = "\033[1m"  if USE_COLOR else ""
    DIM   = "\033[2m"  if USE_COLOR else ""
    RED   = "\033[91m" if USE_COLOR else ""
    GREEN = "\033[92m" if USE_COLOR else ""
    YELLOW= "\033[93m" if USE_COLOR else ""
    BLUE  = "\033[94m" if USE_COLOR else ""
    MAGENTA="\033[95m" if USE_COLOR else ""
    CYAN  = "\033[96m" if USE_COLOR else ""
    WHITE = "\033[97m" if USE_COLOR else ""


# ============================================================
# SECTION 3 — MEMORY RING BUFFERS
# ============================================================

_memory: Deque[Dict[str, Any]] = deque(maxlen=MEMORY_MAX)
_errors: Deque[Dict[str, Any]] = deque(maxlen=ERROR_MAX)
_memory_lock = threading.Lock()


def _record(entry: Dict[str, Any]) -> None:
    with _memory_lock:
        _memory.append(entry)
        if entry.get("level") in ("ERROR", "CRITICAL"):
            _errors.append(entry)


def memory_logs(limit: int = 100) -> list:
    """Return last N memory entries (for /admin)."""
    with _memory_lock:
        if limit >= len(_memory):
            return list(_memory)
        return list(_memory)[-limit:]


def error_logs(limit: int = 50) -> list:
    """Return last N error entries."""
    with _memory_lock:
        if limit >= len(_errors):
            return list(_errors)
        return list(_errors)[-limit:]


def clear_logs() -> None:
    with _memory_lock:
        _memory.clear()
        _errors.clear()


# ============================================================
# SECTION 4 — TELEGRAM FORWARDER
# ============================================================

_forwarder: Optional[Callable] = None
_forward_enabled = False
_forward_queue: Deque[str] = deque(maxlen=200)


def enable_telegram_forward(forwarder: Callable) -> None:
    """
    Register an async forwarder:
        async def forward(text: str): ...
    Called for WARNING+ unless filtered.
    """
    global _forwarder, _forward_enabled
    _forwarder = forwarder
    _forward_enabled = True


def disable_telegram_forward() -> None:
    global _forward_enabled
    _forward_enabled = False


async def _flush_forward_queue() -> None:
    """Background task — send queued log messages to Telegram."""
    while True:
        try:
            await asyncio.sleep(3)
            if not _forward_enabled or _forwarder is None:
                continue
            while _forward_queue:
                msg = _forward_queue.popleft()
                try:
                    await _forwarder(msg)
                except Exception:
                    pass
        except asyncio.CancelledError:
            return
        except Exception:
            pass


# ============================================================
# SECTION 5 — FORMATTERS
# ============================================================

class _RenderFormatter(logging.Formatter):
    """Plain, structured — best for Render logs."""

    def format(self, record: logging.LogRecord) -> str:
        dt = datetime.now(IST).strftime("%H:%M:%S")
        level = record.levelname.ljust(8)
        name = (record.name or "").ljust(28)[:28]
        msg = record.getMessage()

        base = f"{dt} | {level} | {name} | {msg}"

        if record.exc_info:
            tb = "".join(traceback.format_exception(*record.exc_info))
            base += "\n" + tb.rstrip()

        return base


class _ColoredFormatter(logging.Formatter):
    """Fancy console formatter for local dev."""

    LEVEL_COLORS = {
        "DEBUG":    _C.DIM,
        "INFO":     _C.CYAN,
        "WARNING":  _C.YELLOW,
        "ERROR":    _C.RED,
        "CRITICAL": _C.MAGENTA + _C.BOLD,
    }

    def format(self, record: logging.LogRecord) -> str:
        dt = datetime.now(IST).strftime("%H:%M:%S")
        level = record.levelname.ljust(8)
        name = (record.name or "").ljust(28)[:28]
        msg = record.getMessage()

        color = self.LEVEL_COLORS.get(record.levelname, "")

        base = (
            f"{_C.DIM}{dt}{_C.RESET} "
            f"{color}{level}{_C.RESET} "
            f"{_C.DIM}{name}{_C.RESET} "
            f"{msg}"
        )

        if record.exc_info:
            tb = "".join(traceback.format_exception(*record.exc_info))
            base += "\n" + _C.RED + tb.rstrip() + _C.RESET

        return base


# ============================================================
# SECTION 6 — MEMORY HANDLER
# ============================================================

class MemoryHandler(logging.Handler):
    """Captures logs into the in-memory ring buffer."""

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry = {
                "time": datetime.now(IST).strftime("%H:%M:%S"),
                "timestamp": time.time(),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }
            if record.exc_info:
                entry["traceback"] = "".join(
                    traceback.format_exception(*record.exc_info)
                )
            _record(entry)

            # Queue WARNING+ for Telegram forward
            if record.levelname in ("WARNING", "ERROR", "CRITICAL"):
                _forward_queue.append(
                    f"⚠️ <b>{record.levelname}</b>\n"
                    f"<code>{record.name}</code>\n"
                    f"{record.getMessage()[:3800]}"
                )
        except Exception:
            pass


# ============================================================
# SECTION 7 — BANNER
# ============================================================

BANNER = r"""
╔══════════════════════════════════════════════════════════════════╗
║                                                                  ║
║    ██████╗  ██████╗ ██╗    ██╗███╗   ██╗████████╗ ██████╗       ║
║    ██╔══██╗██╔═══██╗██║    ██║████╗  ██║╚══██╔══╝██╔═══██╗      ║
║    ██║  ██║██║   ██║██║ █╗ ██║██╔██╗ ██║   ██║   ██║   ██║      ║
║    ██║  ██║██║   ██║██║███╗██║██║╚██╗██║   ██║   ██║   ██║      ║
║    ██████╔╝╚██████╔╝╚███╔███╔╝██║ ╚████║   ██║   ╚██████╔╝      ║
║    ╚═════╝  ╚═════╝  ╚══╝╚══╝ ╚═╝  ╚═══╝   ╚═╝    ╚═════╝       ║
║                                                                  ║
║                   V  I  L  L  A                                  ║
║                                                                  ║
║            🏨 DOWNTOWN VILLA — MEDIA EMPIRE BOT 🏨               ║
║                                                                  ║
║                    ⚡ Powered by DreamXBotz ⚡                    ║
║                                                                  ║
╚══════════════════════════════════════════════════════════════════╝
"""

BANNER_SMALL = """
╔═══════════════════════════════════════════╗
║  🏨  D O W N T O W N   V I L L A  🏨     ║
║     ⚡ Media Empire Bot • v2 Rocket ⚡    ║
╚═══════════════════════════════════════════╝
"""


def print_banner(big: bool = True) -> None:
    """Print the DOWNTOWN VILLA banner to stdout (Render captures)."""
    sys.stdout.write(BANNER if big else BANNER_SMALL)
    sys.stdout.flush()


# ============================================================
# SECTION 8 — SETUP
# ============================================================

_setup_done = False


def setup(
    level: str = "INFO",
    show_banner: bool = True,
    quiet_libs: bool = True,
) -> None:
    """
    Install all handlers on the root logger.

    • stdout stream (Render captures automatically)
    • memory ring buffer
    • colored output when TTY, plain when on Render
    """
    global _setup_done
    if _setup_done:
        return
    _setup_done = True

    root = logging.getLogger()
    root.setLevel(level.upper())

    # Remove existing handlers (avoid duplicates)
    for h in list(root.handlers):
        root.removeHandler(h)

    # ── Stdout handler ──
    stream = logging.StreamHandler(sys.stdout)
    stream.setLevel(level.upper())

    if IS_RENDER or not USE_COLOR:
        stream.setFormatter(_RenderFormatter())
    else:
        stream.setFormatter(_ColoredFormatter())

    root.addHandler(stream)

    # ── Memory handler ──
    mem = MemoryHandler()
    mem.setLevel(logging.INFO)
    root.addHandler(mem)

    # ── Quiet noisy libs ──
    if quiet_libs:
        logging.getLogger("pyrogram").setLevel(logging.WARNING)
        logging.getLogger("pyrogram.session").setLevel(logging.WARNING)
        logging.getLogger("pyrogram.connection").setLevel(logging.WARNING)
        logging.getLogger("pyrogram.dispatcher").setLevel(logging.ERROR)
        logging.getLogger("aiohttp").setLevel(logging.WARNING)
        logging.getLogger("motor").setLevel(logging.WARNING)
        logging.getLogger("pymongo").setLevel(logging.WARNING)
        logging.getLogger("asyncio").setLevel(logging.WARNING)
        logging.getLogger("urllib3").setLevel(logging.WARNING)

    # ── Banner ──
    if show_banner:
        print_banner(big=True)

    root.info("Logging initialized — DOWNTOWN VILLA v2")


# ============================================================
# SECTION 9 — UNCAUGHT EXCEPTION HOOKS
# ============================================================

def install_exception_hooks() -> None:
    """Capture uncaught sync + async exceptions and log them."""
    logger = logging.getLogger("downtown.uncaught")

    def _sync_hook(exc_type, exc_value, exc_tb):
        logger.critical(
            "Uncaught exception",
            exc_info=(exc_type, exc_value, exc_tb),
        )
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = _sync_hook

    # asyncio loop exception handler — set in startup.py
    def _loop_handler(loop, context):
        msg = context.get("message", "loop error")
        exc = context.get("exception")
        if exc:
            logger.error(f"Async loop: {msg} — {exc}")
        else:
            logger.error(f"Async loop: {msg}")

    return _loop_handler


# ============================================================
# SECTION 10 — FORWARD LOOP (call once from startup)
# ============================================================

_forward_task: Optional[asyncio.Task] = None


def start_forward_loop() -> None:
    """Start the Telegram forward background task."""
    global _forward_task
    if _forward_task and not _forward_task.done():
        return
    try:
        loop = asyncio.get_running_loop()
        _forward_task = loop.create_task(_flush_forward_queue())
    except RuntimeError:
        pass


def stop_forward_loop() -> None:
    if _forward_task and not _forward_task.done():
        _forward_task.cancel()


# ============================================================
# SECTION 11 — QUICK HELPERS
# ============================================================

def get_logger(name: str) -> logging.Logger:
    """Get a namespaced logger."""
    return logging.getLogger(f"downtown.{name}")


def log_startup_summary(app_name: str, version: str, extras: Dict[str, Any] = None) -> None:
    """Fancy startup summary printed after banner."""
    logger = logging.getLogger("downtown.startup")
    logger.info("=" * 66)
    logger.info(f"  🏨 {app_name} v{version} — starting...")
    if extras:
        for k, v in extras.items():
            logger.info(f"  • {k}: {v}")
    logger.info("=" * 66)


# ============================================================
# SECTION 12 — SNAPSHOT FOR ADMIN
# ============================================================

def snapshot() -> Dict[str, Any]:
    """Quick stats for admin panel."""
    with _memory_lock:
        return {
            "memory_lines": len(_memory),
            "memory_max": MEMORY_MAX,
            "error_lines": len(_errors),
            "error_max": ERROR_MAX,
            "forward_enabled": _forward_enabled,
            "forward_queue": len(_forward_queue),
            "render": IS_RENDER,
            "color": USE_COLOR,
        }


# ============================================================
# SECTION 13 — PUBLIC EXPORTS
# ============================================================

__all__ = [
    # Setup
    "setup",
    "get_logger",
    "log_startup_summary",
    # Banner
    "print_banner",
    "BANNER",
    "BANNER_SMALL",
    # Memory
    "memory_logs",
    "error_logs",
    "clear_logs",
    # Telegram forward
    "enable_telegram_forward",
    "disable_telegram_forward",
    "start_forward_loop",
    "stop_forward_loop",
    # Exceptions
    "install_exception_hooks",
    # Snapshot
    "snapshot",
]
