# ============================================================
# 🏨 DOWNTOWN VILLA — OTT BOOT
# ============================================================

from __future__ import annotations
import logging

from pyrogram import Client, filters
from pyrogram.types import Message

from plugins.broadcast.config import _is_admin
from plugins.ott import watcher as W
from plugins.ott import database as DB
from plugins.ott import events as EVENTS

logger = logging.getLogger(__name__)


@Client.on_message(
    filters.private & filters.text & filters.regex(r"^/ott_boot$"),
    group=-8998,
)
async def _ott_boot(client: Client, message: Message):
    if not message.from_user or not _is_admin(message.from_user.id):
        return
    await DB.ensure_indexes()
    await EVENTS.ensure_indexes()
    W.ensure_loops(client)
    try:
        await message.delete()
    except Exception:
        pass


@Client.on_message(
    filters.private & filters.command(["ott", "releases", "weekly"]),
    group=-8998,
)
async def _ott_lazy(client: Client, message: Message):
    if not message.from_user or not _is_admin(message.from_user.id):
        return
    await DB.ensure_indexes()
    await EVENTS.ensure_indexes()
    W.ensure_loops(client)
    try:
        message.stop_propagation()
    except Exception:
        pass


__all__ = []
