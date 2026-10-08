# ============================================================
# 🏨 DOWNTOWN VILLA — OTT BROADCAST ENGINE
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
from pyrogram.types import CallbackQuery, InlineKeyboardMarkup

from plugins.broadcast.config import (
    fb, sc, _fmt_int, _fmt_duration, _progress_colored,
    DIV, DIV2, DEFAULT_DELAY, BROADCAST_CONCURRENCY,
    BROADCAST_BATCH_SIZE,
)
from plugins.ott import database as DB
from plugins.ott import state as ST
from plugins.ott import keyboards as KB
from plugins.ott.tmdb import poster_url

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# CAPTION + KB FOR THE BROADCAST POST
# ═══════════════════════════════════════════════════════════

def _build_broadcast_caption(movie: Dict[str, Any]) -> str:
    title = movie.get("title") or "?"
    year = (movie.get("release_date") or "")[:4]
    rating = movie.get("vote_average", 0) or 0
    lang = (movie.get("original_language") or "").upper()
    genres = (movie.get("genres") or "—")[:60]
    overview = (movie.get("overview") or "")[:280]
    rel = movie.get("release_date") or "—"

    lines = [
        f"🎬 <b>{fb('COMING SOON')}</b>",
        DIV, "",
        f"🎥 <b>{sc(str(title)[:60])}</b> ({year})",
        f"⭐ <code>{rating:.1f}/10</code> · 🌐 <code>{lang or '—'}</code>",
        f"🎭 <code>{sc(genres)}</code>",
        f"📅 <code>{rel}</code>",
    ]
    if overview:
        lines += ["", f"<i>{sc(overview)}</i>"]
    lines += ["", DIV2, f"🔔 {sc('tap below to get notified')}"]
    return "\n".join(lines)


def _build_broadcast_kb(movie: Dict[str, Any]) -> InlineKeyboardMarkup:
    tid = movie.get("tmdb_id")
    return InlineKeyboardMarkup([
        [{"text": f"🔔 {sc('Get Notified')}",
          "callback_data": f"ott:sub:{tid}"}],
        [{"text": f"🎁 {sc('Add to watchlist')}",
          "callback_data": f"ott:wl_add:{tid}"}],
    ])
