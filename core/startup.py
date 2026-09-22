# ============================================================
# 🏨 DOWNTOWN VILLA — STARTUP / BOOT SEQUENCE
# ============================================================
#
# Full boot sequence:
#
#   1. Validate config
#   2. Print banner + startup summary
#   3. Initialize database (System, User, Media, Backup)
#   4. Boot bot client (Pyrogram)
#   5. Warm identity cache
#   6. Ensure all module indexes
#   7. Start all background loops:
#        • Log channel
#        • Cache cleanup
#        • Locks cleanup
#        • Flow engine cleanup
#        • Backup watcher + autodelete
#        • Indexing auto-index handler (via plugin)
#        • OTT loops
#        • Premium reminder + cleanup
#        • Requests cleanup
#   8. Start web server (Render)
#   9. Notify log channel
#   10. Await idle
#   11. Graceful shutdown
#
# ============================================================

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys
import time
from typing import List, Optional

# ── Pyrogram ──
from pyrogram import idle

# ── Web server (for Render health checks) ──
try:
    from aiohttp import web
except ImportError:
    web = None

# ── Core ──
from core import config
from core import logger as CORE_LOGGER
from core import rocket
from core.client import get_client, boot as boot_client
from core.client import shutdown as shutdown_client

# ── Database ──
from database import db_manager, db_registry

# ── Logger ──
logger = logging.getLogger(__name__)


# ============================================================
# CONSTANTS
# ============================================================

APP_NAME = "DOWNTOWN VILLA"
APP_VERSION = "2.0.0"
SHUTDOWN_GRACE = 5.0


# ============================================================
# WEB SERVER
# ============================================================

async def _start_web(port: int) -> Optional["web.AppRunner"]:
    """Start web server for Render health checks."""
    if web is None:
        logger.warning("[BOOT] aiohttp missing — web server disabled")
        return None

    try:
        app = web.Application()

        async def health(request):
            return web.json_response({
                "status": "ok",
                "app": APP_NAME,
                "version": APP_VERSION,
                "uptime": round(time.time() - _BOOT_TIME, 1),
            })

        async def root(request):
            return web.Response(
                text=f"🏨 {APP_NAME} v{APP_VERSION} — running.",
                content_type="text/plain",
            )

        app.router.add_get("/", root)
        app.router.add_get("/health", health)
        app.router.add_get("/healthz", health)

        runner = web.AppRunner(app)
        await runner.setup()
        site = web.TCPSite(runner, host="0.0.0.0", port=port)
        await site.start()
        logger.info(f"[BOOT] ✅ Web server on :{port}")
        return runner
    except Exception as e:
        logger.warning(f"[BOOT] web server failed: {e}")
        return None


# ============================================================
# INDEX SETUP
# ============================================================

async def _setup_all_indexes() -> None:
    """Initialize indexes for every module. Non-fatal."""
    tasks = [
        ("series_group", _setup_series_indexes),
        ("ott", _setup_ott_indexes),
        ("broadcast", _setup_broadcast_indexes),
        ("requests", _setup_requests_indexes),
        ("flow_engine", _setup_flow_indexes),
        ("premium", _setup_premium_indexes),
    ]

    for name, fn in tasks:
        try:
            await fn()
            logger.info(f"[BOOT] ✅ {name} indexes")
        except Exception as e:
            logger.warning(f"[BOOT] {name} indexes failed: {e}")


async def _setup_series_indexes():
    try:
        from plugins.series_group import deep_link as DL
        await DL.ensure_indexes()
    except Exception:
        pass


async def _setup_ott_indexes():
    try:
        from plugins.ott import state as S
        await S.ensure_indexes()
    except Exception:
        pass


async def _setup_broadcast_indexes():
    try:
        from plugins.broadcast import state as BS
        await BS.ensure_indexes()
    except Exception:
        pass


async def _setup_requests_indexes():
    try:
        from plugins.requests import state as RS
        await RS.ensure_indexes()
    except Exception:
        pass


async def _setup_flow_indexes():
    try:
        from database import db_registry
        db = db_registry.get_system_db()
        if db is None:
            return
        c = db["flow_configs"]
        await c.create_index("chat_id", unique=True)
        await c.create_index("updated_at")
    except Exception:
        pass


async def _setup_premium_indexes():
    try:
        from database import db_registry
        db = db_registry.get_user_db()
        if db is None:
            return
        await db["premium_users"].create_index("user_id", unique=True)
        await db["premium_users"].create_index("expires_at")
        await db["watch_sessions"].create_index(
            [("user_id", 1), ("series_slug", 1)], unique=True
        )
        await db["watch_ratings"].create_index(
            [("user_id", 1), ("series_slug", 1)], unique=True
        )
        await db["groups"].create_index("chat_id", unique=True)
        await db["users"].create_index("user_id", unique=True)
    except Exception:
        pass


# ============================================================
# BACKGROUND LOOPS
# ============================================================

async def _start_all_loops(bot) -> None:
    """Start every background task. Non-fatal failures."""
    loop = asyncio.get_running_loop()

    started: List[str] = []

    # ── Cache cleanup ──
    try:
        from utils import cache as C
        C.ensure_cleanup_loop(interval=60)
        started.append("cache")
    except Exception as e:
        logger.debug(f"[BOOT] cache loop: {e}")

    # ── Locks cleanup ──
    try:
        from utils import locks as LK
        LK.ensure_cleanup(interval=300)
        started.append("locks")
    except Exception as e:
        logger.debug(f"[BOOT] locks loop: {e}")

    # ── Flow engine cleanup ──
    try:
        from core.flow_engine import ensure_cleanup as fe_cleanup
        fe_cleanup(interval=120)
        started.append("flow_engine")
    except Exception as e:
        logger.debug(f"[BOOT] flow cleanup: {e}")

    # ── Backup watcher + autodelete ──
    try:
        from plugins.backup import watcher as W
        W.ensure_watcher()
        started.append("backup_watcher")
    except Exception as e:
        logger.debug(f"[BOOT] backup watcher: {e}")

    try:
        from plugins.backup import smart_resume as SR
        SR.ensure_background_refresh()
        started.append("smart_resume")
    except Exception as e:
        logger.debug(f"[BOOT] smart resume: {e}")

    # ── Broadcast autodelete loop ──
    try:
        from plugins.broadcast import engine as BE
        BE.ensure_autodelete_loop(bot)
        started.append("broadcast_autodelete")
    except Exception as e:
        logger.debug(f"[BOOT] broadcast autodel: {e}")

    # ── OTT loops ──
    try:
        from plugins.ott import notify as ON
        ON.ensure_loops(bot)
        started.append("ott_loops")
    except Exception as e:
        logger.debug(f"[BOOT] ott loops: {e}")

    # ── Premium reminders + cleanup ──
    try:
        from plugins.premium import reminders as PR
        PR.ensure_loops(bot)
        started.append("premium_reminders")
    except Exception as e:
        logger.debug(f"[BOOT] premium loops: {e}")

    # ── Requests cleanup ──
    try:
        loop.create_task(_requests_cleanup_loop())
        started.append("requests_cleanup")
    except Exception as e:
        logger.debug(f"[BOOT] requests cleanup: {e}")

    # ── Admin tasks cleanup ──
    try:
        from plugins.admin import tasks as AT
        AT.ensure_cleanup()
        started.append("tasks_cleanup")
    except Exception as e:
        logger.debug(f"[BOOT] admin tasks: {e}")

    # ── Indexing: load saved auto-mode setting ──
    try:
        from plugins.indexing import auto as IA
        enabled = await IA.is_auto_enabled()
        logger.info(f"[BOOT] auto-indexing: {'ON' if enabled else 'OFF'}")
        started.append("auto_indexing")
    except Exception as e:
        logger.debug(f"[BOOT] auto indexing: {e}")

    logger.info(
        f"[BOOT] ✅ Started {len(started)} background loops: "
        f"{', '.join(started)}"
    )


async def _requests_cleanup_loop() -> None:
    """Delete expired request tokens every hour."""
    while True:
        try:
            await asyncio.sleep(3600)
            from plugins.requests import state as RS
            n = await RS.cleanup_expired()
            if n:
                logger.info(f"[BOOT] cleaned {n} expired requests")
        except asyncio.CancelledError:
            return
        except Exception:
            pass


# ============================================================
# LOG CHANNEL NOTIFY
# ============================================================

async def _notify_log_channel(bot) -> None:
    try:
        from plugins import log_channel as LC
        LC.set_bot(bot)
        await LC.bot_started()
    except Exception as e:
        logger.debug(f"[BOOT] log notify: {e}")


# ============================================================
# BANNER
# ============================================================

def _print_startup_summary() -> None:
    """Print all boot info."""
    try:
        sys_config = config.snapshot()
    except Exception:
        sys_config = {}

    lines = [
        f"🏨 {APP_NAME} v{APP_VERSION}",
        "─" * 60,
        f"• Session       : {sys_config.get('session', '?')}",
        f"• Admins        : {sys_config.get('admins', 0)}",
        f"• Log channel   : {sys_config.get('log_channel', '?')}",
        f"• DB channels   : {sys_config.get('database_channels', [])}",
        f"• Backup chan   : {sys_config.get('backup_channel', '?')}",
        f"• Reqst channel : {sys_config.get('reqst_channel', '?')}",
        f"• Broadcast ch  : {sys_config.get('broadcast_channel', '?')}",
        "─" * 60,
        f"• DB shards     : {sys_config.get('shards', {})}",
        "─" * 60,
        f"• Features      : {sys_config.get('features', {})}",
    ]
    for line in lines:
        logger.info(line)


# ============================================================
# GRACEFUL SHUTDOWN
# ============================================================

_BOOT_TIME = time.time()
_shutdown_event: Optional[asyncio.Event] = None


def _install_signal_handlers(loop: asyncio.AbstractEventLoop) -> None:
    def _request_stop(sig_name: str):
        logger.warning(f"[BOOT] received {sig_name} — shutting down")
        if _shutdown_event:
            _shutdown_event.set()

    try:
        loop.add_signal_handler(
            signal.SIGINT,
            _request_stop, "SIGINT",
        )
    except (NotImplementedError, AttributeError):
        pass

    try:
        loop.add_signal_handler(
            signal.SIGTERM,
            _request_stop, "SIGTERM",
        )
    except (NotImplementedError, AttributeError):
        pass


# ============================================================
# MAIN BOOT
# ============================================================

async def start_bot() -> None:
    global _shutdown_event

    started_at = time.time()
    _shutdown_event = asyncio.Event()

    logger.info("=" * 60)
    logger.info(f"  🏨 {APP_NAME} v{APP_VERSION} — starting…")
    logger.info("=" * 60)

    # ── 1. Validate config ──
    try:
        errors = config.validate()
        if errors:
            for e in errors:
                logger.error(f"[BOOT] config: {e}")
            if any("missing" in e.lower() for e in errors):
                logger.critical("[BOOT] aborting — fix config first")
                return
    except Exception as e:
        logger.warning(f"[BOOT] validation crashed: {e}")

    # ── 2. Startup summary ──
    _print_startup_summary()

    # ── 3. Initialize database ──
    try:
        with rocket.timer("boot.database"):
            await db_manager.initialize()
    except Exception as e:
        logger.exception(f"[BOOT] database init crashed: {e}")

    if not db_manager.enabled:
        logger.warning("[BOOT] database disabled — running limited")

    # ── 4. Boot bot client ──
    bot = None
    try:
        with rocket.timer("boot.client"):
            bot = await boot_client()
    except Exception as e:
        logger.exception(f"[BOOT] client boot failed: {e}")
        return

    # Set bot for log channel
    try:
        from plugins import log_channel as LC
        LC.set_bot(bot)
    except Exception:
        pass

    # ── 5. Indexes ──
    try:
        with rocket.timer("boot.indexes"):
            await _setup_all_indexes()
    except Exception as e:
        logger.warning(f"[BOOT] index setup: {e}")

    # ── 6. Signal handlers ──
    loop = asyncio.get_running_loop()
    _install_signal_handlers(loop)

    # ── 7. Web server ──
    runner = None
    try:
        runner = await _start_web(config.PORT)
    except Exception as e:
        logger.warning(f"[BOOT] web: {e}")

    # ── 8. Background loops ──
    try:
        with rocket.timer("boot.loops"):
            await _start_all_loops(bot)
    except Exception as e:
        logger.warning(f"[BOOT] loops: {e}")

    # ── 9. Notify log channel ──
    await _notify_log_channel(bot)

    # ── 10. Idle ──
    total_time = time.time() - started_at
    logger.info("=" * 60)
    logger.info(f"  ✅ {APP_NAME} READY in {total_time:.2f}s")
    logger.info("=" * 60)

    try:
        # Run until shutdown signal
        await _shutdown_event.wait()
    except asyncio.CancelledError:
        pass

    # ── 11. Graceful shutdown ──
    logger.info("=" * 60)
    logger.info("  🛑 SHUTDOWN SEQUENCE")
    logger.info("=" * 60)

    # Notify log
    try:
        from plugins import log_channel as LC
        await LC.bot_stopped()
    except Exception:
        pass

    # Stop loops
    try:
        from plugins.backup import watcher as BW
        await BW.stop_watcher()
    except Exception:
        pass

    try:
        from plugins.backup import smart_resume as SR
        await SR.stop_refresh()
    except Exception:
        pass

    # Stop web
    if runner is not None:
        try:
            await runner.cleanup()
        except Exception:
            pass

    # Stop client
    try:
        await shutdown_client()
    except Exception:
        pass

    # Close DB
    try:
        await db_manager.close()
    except Exception:
        pass

    logger.info("[BOOT] ✅ Shutdown complete")


# ============================================================
# ENTRY
# ============================================================

def run() -> None:
    """Synchronous entry — called from main.py."""
    try:
        asyncio.run(start_bot())
    except KeyboardInterrupt:
        logger.info("[BOOT] interrupted")
    except Exception as e:
        logger.exception(f"[BOOT] fatal: {e}")


__all__ = ["run", "start_bot"]
