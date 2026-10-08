# ============================================================
# 🏨 DOWNTOWN VILLA — OTT LIVE STATS SYNC
# ============================================================
# Every state change must edit the SAME channel message.
# This module serializes edits per-message so concurrent
# callbacks don't collide or spam Telegram.
# ============================================================

from __future__ import annotations
import asyncio
import logging
import time
from typing import Any, Dict, Optional

from pyrogram import Client
from pyrogram.enums import ParseMode
from pyrogram.errors import MessageNotModified, FloodWait

from plugins.ott import events as EVENTS

logger = logging.getLogger(__name__)

# ── Per-message locks ──
_locks: Dict[int, asyncio.Lock] = {}
_last_edit: Dict[int, float] = {}
_MIN_INTERVAL = 0.6          # seconds between edits per message


def _get_lock(msg_id: int) -> asyncio.Lock:
    if msg_id not in _locks:
        _locks[msg_id] = asyncio.Lock()
    return _locks[msg_id]


def drop_lock(msg_id: int) -> None:
    _locks.pop(msg_id, None)
    _last_edit.pop(msg_id, None)


# ═══════════════════════════════════════════════════════════
# PUBLIC: SYNC ADMIN POST
# ═══════════════════════════════════════════════════════════

async def sync_admin_post(
    client: Client,
    event_id: str,
    *,
    force: bool = False,
) -> bool:
    """
    Recount event stats, then edit the SAME admin channel message.
    Serialized per-message. Safe under concurrency.
    """
    ev = await EVENTS.get_event(event_id)
    if not ev:
        return False

    msg_id = int(ev.get("admin_msg_id") or 0)
    chat_id = int(ev.get("admin_channel_id") or 0)
    if not msg_id or not chat_id:
        return False

    # Recount first (cheap: 3 counts + 1 media query)
    await EVENTS.recount(event_id)

    # Refresh in-memory event
    ev = await EVENTS.get_event(event_id)
    if not ev:
        return False

    # Rate limit
    now = time.time()
    if not force and now - _last_edit.get(msg_id, 0) < _MIN_INTERVAL:
        # Still schedule a deferred sync
        asyncio.create_task(_deferred_sync(client, event_id))
        return True

    lock = _get_lock(msg_id)
    async with lock:
        return await _do_edit(client, ev)


async def _deferred_sync(client: Client, event_id: str) -> None:
    """Called when rate-limited: wait then sync."""
    await asyncio.sleep(_MIN_INTERVAL + 0.1)
    try:
        await sync_admin_post(client, event_id, force=True)
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════
# ACTUAL EDIT
# ═══════════════════════════════════════════════════════════

async def _do_edit(client: Client, ev: Dict[str, Any]) -> bool:
    from plugins.ott import views as V
    from plugins.ott import database as DB
    from plugins.ott.tmdb import enrich_movie

    msg_id = int(ev["admin_msg_id"])
    chat_id = int(ev["admin_channel_id"])

    try:
        movie = await DB.get_movie(ev["tmdb_id"]) or {}
        movie = await enrich_movie(movie)

        state = ev.get("state") or "setup"
        ended = state == "ended"

        # Build text + kb
        if state == "setup":
            text, kb = await V.view_setup(
                movie,
                ev["notify_enabled"],
                ev["get_files_enabled"],
                ev["auto_delete_hours"],
            )
        else:
            text, kb = await V.view_live(
                movie,
                notify=ev["notify_enabled"],
                show_file=ev["get_files_enabled"],
                is_admin_view=True,
                ended=ended,
            )

        _last_edit[msg_id] = time.time()

        # Try caption first (has photo), then text
        try:
            await client.edit_message_caption(
                chat_id=chat_id, message_id=msg_id,
                caption=text, reply_markup=kb,
                parse_mode=ParseMode.HTML,
            )
            return True
        except MessageNotModified:
            return True
        except Exception:
            pass

        try:
            await client.edit_message_text(
                chat_id=chat_id, message_id=msg_id,
                text=text, reply_markup=kb,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
            return True
        except MessageNotModified:
            return True
        except Exception as e:
            msg = str(e).lower()
            if "message to edit not found" in msg or "message_id_invalid" in msg:
                logger.warning(
                    f"[OTT-SYNC] admin msg {msg_id} gone — "
                    f"marking event {ev['_id']} orphaned"
                )
                await EVENTS.update_event(ev["_id"], admin_msg_id=0)
            else:
                logger.debug(f"[OTT-SYNC] edit: {e}")
            return False
    except Exception as e:
        logger.exception(f"[OTT-SYNC] crashed: {e}")
        return False


# ═══════════════════════════════════════════════════════════
# SYNC TARGET POSTS (channels/groups/DMs)
# ═══════════════════════════════════════════════════════════

async def sync_target_posts(client: Client, event_id: str) -> None:
    """Refresh all target posts (channels/groups) for this event."""
    ev = await EVENTS.get_event(event_id)
    if not ev:
        return

    from plugins.ott import views as V
    from plugins.ott import database as DB
    from plugins.ott.tmdb import enrich_movie

    movie = await DB.get_movie(ev["tmdb_id"]) or {}
    movie = await enrich_movie(movie)

    state = ev.get("state") or "setup"
    ended = state == "ended"

    text, kb = await V.view_live(
        movie,
        notify=ev["notify_enabled"],
        show_file=ev["get_files_enabled"],
        is_admin_view=False,
        ended=ended,
    )

    for tp in (ev.get("target_posts") or []):
        cid = int(tp.get("chat_id") or 0)
        mid = int(tp.get("msg_id") or 0)
        if not cid or not mid:
            continue
        lock = _get_lock(mid)
        async with lock:
            try:
                await client.edit_message_caption(
                    chat_id=cid, message_id=mid,
                    caption=text, reply_markup=kb,
                    parse_mode=ParseMode.HTML,
                )
            except MessageNotModified:
                pass
            except Exception:
                try:
                    await client.edit_message_text(
                        chat_id=cid, message_id=mid,
                        text=text, reply_markup=kb,
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=True,
                    )
                except Exception as e:
                    logger.debug(f"[OTT-SYNC] target {cid}/{mid}: {e}")
        await asyncio.sleep(0.15)   # flood safety


# ═══════════════════════════════════════════════════════════
# HIGH-LEVEL: sync EVERYTHING for an event
# ═══════════════════════════════════════════════════════════

async def sync_all(client: Client, event_id: str) -> None:
    await sync_admin_post(client, event_id)
    try:
        await sync_target_posts(client, event_id)
    except Exception as e:
        logger.debug(f"[OTT-SYNC] target sync: {e}")


__all__ = [
    "sync_admin_post", "sync_target_posts", "sync_all",
    "drop_lock",
]
