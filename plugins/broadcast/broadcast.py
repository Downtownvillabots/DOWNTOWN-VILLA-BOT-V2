# ============================================================
# 🏨 DOWNTOWN VILLA — BROADCAST COMMAND (DISABLED)
# ============================================================
#
# The old /broadcast command is now handled by:
#     plugins/broadcast/watcher.py::bc_cmd
#
# This file is kept for backward compatibility (import safety).
# All handlers here are disabled.
#
# ============================================================

from __future__ import annotations

import logging
from typing import Any, Dict

from pyrogram import Client, filters
from pyrogram.types import Message

from core import config

logger = logging.getLogger(__name__)


def _is_admin(uid) -> bool:
    try:
        return int(uid) in [int(a) for a in config.ADMINS]
    except Exception:
        return False


# ============================================================
# /broadcast — disabled here, handled in watcher.py
# ============================================================

@Client.on_message(
    filters.command(["broadcast", "bc"]) & filters.private,
    group=-8299,   # runs AFTER the watcher.py handler (-8307)
)
async def cmd_broadcast(client: Client, message: Message):
    # Do nothing — the real handler lives in watcher.py
    return


# ============================================================
# Placeholder for admin panel delegate
# ============================================================

async def open_panel_for_admin(client: Client, message: Message) -> None:
    """Compatibility shim — routes to watcher."""
    try:
        from plugins.broadcast import watcher as W
        await W.bc_cmd(client, message)
    except Exception as e:
        logger.exception(f"[BC] open_panel_for_admin: {e}")


def snapshot() -> Dict[str, Any]:
    return {"module": "broadcast_disabled"}


__all__ = ["open_panel_for_admin", "snapshot"]
