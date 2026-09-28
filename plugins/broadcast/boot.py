# ============================================================
# 🏨 DOWNTOWN VILLA — BROADCAST BOOTSTRAP
# ============================================================
# Starts auto-delete + cleanup loops.
# Imported last by __init__ auto-discovery.
# ============================================================

from __future__ import annotations
import logging

from pyrogram import Client, filters
from pyrogram.types import Message

from plugins.broadcast import autodelete as AD
from plugins.broadcast import cleanup as CL
from plugins.broadcast import state as ST

logger = logging.getLogger(__name__)


@Client.on_message(filters.private & filters.command("bc_boot"), group=-9000)
async def _bc_boot(client: Client, message: Message):
    """Silent trigger to start loops after bot is up."""
    try:
        await message.delete()
    except Exception:
        pass
    AD.start(client)
    CL.start()


# auto-start on first private message (any)
@Client.on_message(filters.private, group=-8999)
async def _bc_lazy_boot(client: Client, message: Message):
    AD.start(client)
    CL.start()
    try:
        message.stop_propagation()
    except Exception:
        pass


__all__ = []
