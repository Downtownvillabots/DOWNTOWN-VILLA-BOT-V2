# ============================================================
# 🏨 DOWNTOWN VILLA — OTT ENGINE (broadcast + targets)
# ============================================================

from __future__ import annotations
import asyncio
import logging
from typing import Any, Dict, List, Tuple

from pyrogram import Client
from pyrogram.enums import ParseMode
from pyrogram.errors import (
    FloodWait, UserIsBlocked, InputUserDeactivated,
    ChatWriteForbidden, ChatAdminRequired, ChannelPrivate,
    PeerIdInvalid, UserNotParticipant, UserDeactivated,
    UserDeactivatedBan, MessageNotModified,
)
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from plugins.broadcast.config import (
    fb, sc, _fmt_int, _fmt_duration, DIV, DIV2,
    DEFAULT_DELAY, BROADCAST_CONCURRENCY, BROADCAST_BATCH_SIZE,
)
from plugins.ott import database as DB
from plugins.ott import keyboards as KB
from plugins.ott.tmdb import poster_url

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# RESOLVE ADMIN CHANNEL
# ═══════════════════════════════════════════════════════════

async def get_ott_channel() -> int:
    cfg = await DB.get_cfg()
    ch = int(cfg.get("ott_broadcast_channel") or 0)
    if ch:
        return ch
    try:
        from plugins.broadcast.config import BROADCAST_CHANNEL_ID
        if BROADCAST_CHANNEL_ID:
            return int(BROADCAST_CHANNEL_ID)
    except Exception:
        pass
    return 0


# ═══════════════════════════════════════════════════════════
# CAPTION BUILDER
# ═══════════════════════════════════════════════════════════

def build_caption(movie: Dict[str, Any]) -> str:
    title = movie.get("title") or "?"
    year = (movie.get("release_date") or "")[:4]
    rating = movie.get("vote_average", 0) or 0
    votes = movie.get("vote_count", 0) or 0
    lang = (movie.get("original_language") or "").upper()
    genres = (movie.get("genres") or "—")[:70]
    overview = (movie.get("overview") or "")[:280]
    rel = (movie.get("region_release") or {}).get("date") \
        or movie.get("release_date") or "—"
    provider = movie.get("provider") or "—"

    lines = [
        f"🎬 <b>{fb('COMING SOON')}</b>",
        DIV, "",
        f"🎥 <b>{sc(str(title)[:60])}</b> ({year})",
        f"⭐ <code>{rating:.1f}/10</code> "
        f"(<code>{_fmt_int(votes)}</code>) · 🌐 <code>{lang or '—'}</code>",
        f"🎭 <code>{sc(genres)}</code>",
        f"📅 <code>{rel}</code>",
        f"📺 <code>{sc(provider)}</code>",
    ]
    if overview:
        lines += ["", f"<i>{sc(overview)}</i>"]
    lines += [
        "",
        DIV2,
        f"🔔 {sc('tap Get Notified to be DM-ed when the file lands')}",
    ]
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════
# SINGLE-CHANNEL POST (used by POST NOW in channel_flow)
# ═══════════════════════════════════════════════════════════

async def post_to_single_channel(client: Client, tmdb_id: int,
                                    chat_id: int,
                                    notify: bool = True,
                                    show_file: bool = True
                                    ) -> int:
    """Post live post to a single channel. Returns message id or 0."""
    movie = await DB.get_movie(tmdb_id)
    if not movie:
        return 0

    from plugins.ott.tmdb import enrich_movie
    movie = await enrich_movie(movie)

    caption = build_caption(movie)
    kb = KB.kb_live(tmdb_id, notify, show_file, is_admin_view=False)
    poster = poster_url(movie.get("poster_path"), "w500")

    try:
        if poster:
            try:
                m = await client.send_photo(
                    chat_id=chat_id, photo=poster, caption=caption,
                    reply_markup=kb, parse_mode=ParseMode.HTML,
                )
                return m.id
            except Exception:
                pass
        m = await client.send_message(
            chat_id=chat_id, text=caption, reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        return m.id
    except Exception as e:
        logger.debug(f"[OTT-ENGINE] post_to_channel {chat_id}: {e}")
        return 0


# ═══════════════════════════════════════════════════════════
# SEND TO TARGETS (channels / groups / users / premium)
# ═══════════════════════════════════════════════════════════

async def send_to_targets(
    client: Client,
    tmdb_id: int,
    notify: bool,
    show_file: bool,
    kind: str,
    target_id: int = 0,
    admin_id: int = 0,
) -> Tuple[int, int, int]:
    """
    Returns (delivered, failed, total).
    kind: ch | chall | gr | us | pm
    """
    movie = await DB.get_movie(tmdb_id)
    if not movie:
        return 0, 0, 0
    from plugins.ott.tmdb import enrich_movie
    movie = await enrich_movie(movie)

    caption = build_caption(movie)
    kb = KB.kb_live(tmdb_id, notify, show_file, is_admin_view=False)
    poster = poster_url(movie.get("poster_path"), "w500")

    # Resolve targets
    targets: List[int] = []
    if kind == "ch":
        targets = [int(target_id)]
    elif kind == "chall":
        try:
            from plugins.broadcast import database as BDB
            chans = await BDB.get_saved_channels()
            targets = [int(c["chat_id"]) for c in chans
                       if c.get("enabled", True)]
        except Exception:
            pass
    elif kind == "gr":
        try:
            from plugins.broadcast import database as BDB
            targets = await BDB.get_all_groups()
        except Exception:
            pass
    elif kind == "us":
        try:
            from plugins.broadcast import database as BDB
            targets = await BDB.get_all_users()
        except Exception:
            pass
    elif kind == "pm":
        try:
            from plugins.premium import state as PS
            users = await PS.list_users(limit=50000)
            targets = [int(u["user_id"]) for u in users if u.get("user_id")]
        except Exception:
            pass

    targets = [t for t in targets if t]
    if not targets:
        return 0, 0, 0

    total = len(targets)
    sent = failed = 0
    sem = asyncio.Semaphore(BROADCAST_CONCURRENCY)
    lock = asyncio.Lock()

    async def _one(tid: int) -> str:
        async with sem:
            try:
                m = None
                if poster:
                    try:
                        m = await client.send_photo(
                            chat_id=tid, photo=poster,
                            caption=caption, reply_markup=kb,
                            parse_mode=ParseMode.HTML,
                        )
                    except Exception:
                        pass
                if m is None:
                    m = await client.send_message(
                        chat_id=tid, text=caption, reply_markup=kb,
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=True,
                    )
                await asyncio.sleep(DEFAULT_DELAY)
                return "sent"
            except FloodWait as e:
                await asyncio.sleep(int(e.value) + 2)
                try:
                    await client.send_message(
                        chat_id=tid, text=caption, reply_markup=kb,
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=True,
                    )
                    return "sent"
                except Exception:
                    return "fail"
            except (UserIsBlocked, InputUserDeactivated,
                    UserDeactivated, UserDeactivatedBan):
                return "block"
            except (ChatWriteForbidden, ChatAdminRequired,
                    ChannelPrivate, PeerIdInvalid,
                    UserNotParticipant):
                return "fail"
            except Exception:
                return "fail"

    async def _wrap(tid: int):
        r = await _one(tid)
        async with lock:
            nonlocal sent, failed
            if r == "sent":
                sent += 1
            else:
                failed += 1

    # Run in batches
    try:
        for i in range(0, total, BROADCAST_BATCH_SIZE):
            batch = targets[i:i + BROADCAST_BATCH_SIZE]
            await asyncio.gather(*[_wrap(t) for t in batch])
    except Exception as e:
        logger.exception(f"[OTT-ENGINE] broadcast batch: {e}")

    # Log
    try:
        await DB.broadcast_log(
            tmdb_id=tmdb_id, target=kind,
            delivered=sent, failed=failed, total=total,
            admin_id=admin_id,
        )
    except Exception:
        pass

    return sent, failed, total


__all__ = [
    "get_ott_channel",
    "build_caption",
    "post_to_single_channel",
    "send_to_targets",
]
