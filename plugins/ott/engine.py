# ============================================================
# 🏨 DOWNTOWN VILLA — OTT ENGINE (channel broadcast)
# ============================================================

from __future__ import annotations
import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from pyrogram import Client
from pyrogram.enums import ParseMode
from pyrogram.errors import (
    FloodWait, UserIsBlocked, InputUserDeactivated,
    ChatWriteForbidden, ChatAdminRequired, ChannelPrivate,
    PeerIdInvalid, UserNotParticipant, UserDeactivated,
    UserDeactivatedBan, MessageNotModified,
)
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
)

from plugins.broadcast.config import (
    fb, sc, _fmt_int, _fmt_duration, _progress_colored,
    DIV, DIV2, DEFAULT_DELAY,
)
from plugins.ott import database as DB
from plugins.ott import state as ST
from plugins.ott import keyboards as KB
from plugins.ott.tmdb import poster_url

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# OTT BROADCAST CHANNEL RESOLVER
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
# CAPTION + KB
# ═══════════════════════════════════════════════════════════

def build_caption(movie: Dict[str, Any]) -> str:
    title = movie.get("title") or "?"
    year = (movie.get("release_date") or "")[:4]
    rating = movie.get("vote_average", 0) or 0
    votes = movie.get("vote_count", 0) or 0
    lang = (movie.get("original_language") or "").upper()
    genres = (movie.get("genres") or "—")[:70]
    overview = (movie.get("overview") or "")[:280]
    rel = movie.get("release_date") or "—"
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
        f"🔔 {sc('tap below to get notified')}",
        f"📥 {sc('we will DM you when the file is uploaded')}",
    ]
    return "\n".join(lines)


def build_kb(movie: Dict[str, Any], notify: bool = True) -> InlineKeyboardMarkup:
    tid = movie.get("tmdb_id")
    rows: List[List[InlineKeyboardButton]] = []
    if notify:
        rows.append([InlineKeyboardButton(
            f"🔔 {sc('Get Notified')}",
            callback_data=f"ott:sub:{tid}",
        )])
        rows.append([InlineKeyboardButton(
            f"🎁 {sc('Add to watchlist')}",
            callback_data=f"ott:wl_add:{tid}",
        )])
    rows.append([InlineKeyboardButton(
        f"📤 {sc('Share')}",
        callback_data=f"ott:share:{tid}",
    )])
    return InlineKeyboardMarkup(rows)


# ═══════════════════════════════════════════════════════════
# SEND ONE BROADCAST (setup-driven)
# ═══════════════════════════════════════════════════════════

async def send_channel_broadcast(
    client: Client,
    q: CallbackQuery,
    setup: Dict[str, Any],
) -> None:
    """Post the movie to the OTT broadcast channel with the setup options."""
    tmdb_id = setup.get("tmdb_id")
    ch = int(setup.get("channel_id") or 0)
    if not ch:
        return await q.answer("⚠️ no OTT channel set", show_alert=True)

    movie = await DB.get_movie(tmdb_id)
    if not movie:
        return await q.answer("⚠️ movie missing", show_alert=True)

    notify = bool(setup.get("notify", True))
    hours = int(setup.get("auto_delete_hours", 0))
    ttl = hours * 3600 if hours > 0 else 0

    caption = setup.get("caption") or build_caption(movie)
    kb = KB.ott_channel_kb(tmdb_id, notify=notify)
    poster = poster_url(movie.get("poster_path"), "w500")

    # Notify "sending"
    await q.answer("📤 Sending…")
    try:
        await q.message.edit_text(
            "\n".join([
                f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                f"📤 <b>{fb('POSTING TO CHANNEL…')}</b>",
                DIV, "",
                f"🎬 <code>{(movie.get('title') or '?')[:50]}</code>",
                f"📢 <code>{ch}</code>",
            ]),
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass

    # Send
    sent = None
    try:
        if poster:
            try:
                sent = await client.send_photo(
                    chat_id=ch, photo=poster, caption=caption,
                    reply_markup=kb, parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass
        if sent is None:
            sent = await client.send_message(
                chat_id=ch, text=caption, reply_markup=kb,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
    except Exception as e:
        logger.exception(f"[OTT-ENGINE] send: {e}")
        try:
            await q.message.edit_text(
                f"❌ <b>{fb('FAILED')}</b>\n{DIV}\n<code>{type(e).__name__}</code>",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        return

    # Schedule auto-delete of the CHANNEL POST
    if ttl > 0 and sent:
        try:
            await DB.pending_add(ch, sent.id, ttl)
        except Exception:
            pass

    # Log broadcast
    try:
        await DB.broadcast_log(
            tmdb_id=tmdb_id, target="ott_channel",
            delivered=1, failed=0, total=1,
            admin_id=q.from_user.id,
            channel_msg_id=sent.id if sent else 0,
        )
    except Exception:
        pass

    # Update the message with done card
    movie_title = (movie.get("title") or "?")[:50]
    ttl_line = (f"🗑️ {sc('auto-delete')} · {_fmt_duration(ttl)}"
                if ttl else f"🗑️ {sc('auto-delete')} · ♾️ off")

    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"✅ <b>{fb('POSTED TO CHANNEL')}</b>",
        DIV, "",
        f"🎬 <b>{sc(movie_title)}</b>",
        f"📢 <code>{ch}</code>",
        f"🔔 {sc('notify button')} · "
        f"{'🟢 on' if notify else '🔴 off'}",
        ttl_line,
        "", DIV2,
        f"📌 {sc('users who tap Notify will be DM\\'d when file lands')}",
        f"📌 {sc('view subscribers from the movie card')}",
    ])
    kb2 = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"👥 {sc('Subscribers')}",
            callback_data=f"ott:subs_mv:{tmdb_id}")],
        [InlineKeyboardButton(
            f"📢 {sc('Broadcast center')}",
            callback_data="ott:bc")],
        [InlineKeyboardButton(
            f"❌ {sc('Close')}",
            callback_data="ott:close")],
    ])
    try:
        await q.message.edit_text(
            text, reply_markup=kb2,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception:
        pass

    ST.setup_drop(q.from_user.id)


__all__ = [
    "get_ott_channel",
    "build_caption", "build_kb",
    "send_channel_broadcast",
]
