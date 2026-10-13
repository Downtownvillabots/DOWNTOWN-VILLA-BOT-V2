# ============================================================
# 🏨 DOWNTOWN VILLA — GROUPS SHARED DELIVERY
# ============================================================
#
# Builds the file-list message + keyboard with deep-links to PM.
#
# Used by:
#   • groups/movie/handler.py
#   • groups/series/handler.py
#   • groups/shared/callbacks.py  (sr:more pagination)
#
# Public API:
#   show_file_list(message_or_status, query, hits, sid, cfg)
#       → sends or edits the file list
#
#   build_file_list_kb(sid, hits, page, cfg, bot_username)
#       → InlineKeyboardMarkup
#
#   clean_display_name(hit)
#       → user-friendly short name (no @tags, no extension)
#
#   build_file_list_text(query, total, page, total_pages)
#       → header text
#
# FILE BUTTON FORMAT:
#   📦 {size} · {quality} · {clean_title}
#
#   Examples:
#     📦 100 MB · 720P · Karnan 2021
#     📦 850 MB · 1080P · Karnan 2021
#     📦 1.4 GB · 1080P · Karnan 2021
#
# SORTED SMALL → BIG (configurable via cfg.per_row)
# 10 files per page (per_page from cfg, capped 15)
# Deep-link buttons to PM:  https://t.me/{bot}?start=file_{sid}_{idx}
# Fallback callback (no bot username):  sr:file:{sid}:{idx}
#
# ============================================================

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Tuple

from pyrogram import Client
from pyrogram.enums import ParseMode
from pyrogram.types import (
    InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from plugins.groups import state as S
from plugins.groups.shared import search as SEARCH
from utils import fonts as F
from utils import format as FM

logger = logging.getLogger(__name__)


# ============================================================
# SECTION 1 — CONSTANTS
# ============================================================

_PER_PAGE_DEFAULT = 10
_PER_PAGE_MAX = 15

# Regex patterns for name cleaning
_RE_EXT = re.compile(
    r"\.(mkv|mp4|avi|mov|wmv|flv|webm|m4v|ts|m2ts|mpg|mpeg)$",
    re.IGNORECASE,
)
_RE_HANDLE = re.compile(r"@[A-Za-z0-9_]{3,}")
_RE_URL = re.compile(
    r"(?:https?://|www\.|t\.me/|telegram\.me/|telegram\.dog/)"
    r"[A-Za-z0-9._\-/?#=&%]+",
    re.IGNORECASE,
)
_RE_BRACKETS = re.compile(r"[\[\{\(][^\]\}\)]*[\]\}\)]")
_RE_JUNK = re.compile(
    r"\b(?:"
    r"x264|x265|h\.?264|h\.?265|hevc|avc|av1|"
    r"aac|ac3|dts|ddp|eac3|opus|"
    r"\d{1,2}bit|10bit|8bit|hdr|sdr|dv|"
    r"web-?dl|webrip|web-?hd|bluray|blu-ray|brrip|bdrip|"
    r"hdrip|dvdrip|dvdscr|camrip|hdtv|"
    r"esub|esubs|subs|sub|dual\s*audio|multi\s*audio|"
    r"proper|repack|extended|remastered|unrated|imax|"
    r"amzn|nf|dsnp|hmax|pcok|yts|yify|psa|rarbg|"
    r"1xbet|1x"
    r")\b",
    re.IGNORECASE,
)
_RE_SEPARATORS = re.compile(r"[._\-|]+")
_RE_SPACES = re.compile(r"\s+")


# ============================================================
# SECTION 2 — CLEAN DISPLAY NAME
# ============================================================

def clean_display_name(hit: Dict[str, Any], max_len: int = 34) -> str:
    """
    Return a short user-friendly name from a hit.
    Rules:
      • Prefer hit['title'] or hit['series_title']
      • Fall back to cleaned file_name
      • Strip extension, @handles, URLs, bracket groups, junk tokens
      • Keep year if present
      • Cap length
    """
    # Try a real title first
    raw = (
        hit.get("title")
        or hit.get("series_title")
        or hit.get("file_name")
        or ""
    )
    if not raw:
        return "file"

    t = str(raw)

    # Strip file extension
    t = _RE_EXT.sub("", t)

    # Strip URLs (whole matches)
    t = _RE_URL.sub(" ", t)

    # Strip @handles
    t = _RE_HANDLE.sub(" ", t)

    # Strip bracketed groups [YTS], {GROUP}, (EXTRA)
    t = _RE_BRACKETS.sub(" ", t)

    # Strip junk tokens
    t = _RE_JUNK.sub(" ", t)

    # Replace separators with space
    t = _RE_SEPARATORS.sub(" ", t)

    # Collapse whitespace
    t = _RE_SPACES.sub(" ", t).strip(" -_.|·")

    if not t:
        # Ultra-fallback: take file_name up to first dot
        fallback = str(hit.get("file_name") or "file")
        t = fallback.split(".")[0]
        t = _RE_SPACES.sub(" ", t).strip()

    # Add year if missing and available
    year = hit.get("year")
    if year and str(year) not in t:
        # Avoid dup year
        t = f"{t} {year}"

    # Cap length
    if len(t) > max_len:
        t = t[: max_len - 1].rstrip() + "…"

    return t or "file"


# ============================================================
# SECTION 3 — BUTTON LABEL
# ============================================================

def build_button_label(hit: Dict[str, Any]) -> str:
    """
    One-line label for a file button.

    Format:  📦 {size} · {quality} · {clean_name}
    Example: 📦 850 MB · 1080P · Karnan 2021
    """
    size = FM.size_short(hit.get("file_size") or 0)
    quality = str(hit.get("quality") or "").upper()
    name = clean_display_name(hit, max_len=34)

    parts = [f"📦 {size}"]
    if quality and quality != "UNKNOWN":
        parts.append(quality)
    parts.append(name)

    label = " · ".join(parts)

    # Telegram button label cap (soft 64 chars)
    if len(label) > 60:
        label = label[:57] + "…"
    return label


# ============================================================
# SECTION 4 — HEADER TEXT
# ============================================================

def build_file_list_text(
    query: str,
    total: int,
    page: int = 1,
    total_pages: int = 1,
) -> str:
    """
    Header message above the file list.
    """
    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        F.DIV, "",
        f"🎬 <b>{F.sc(str(query)[:50])}</b>",
        f"📦 <b>{FM.num(total)}</b> ꜰɪʟᴇꜱ · ꜱᴍᴀʟʟ → ʙɪɢ",
    ]
    if total_pages > 1:
        lines.append(
            f"📄 {F.sc('page')} · <b>{page}</b> / {total_pages}"
        )
    lines += [
        "",
        f"📌 ᴛᴀᴘ ᴀ ꜰɪʟᴇ ᴛᴏ ʀᴇᴄᴇɪᴠᴇ ɪᴛ ɪɴ ᴘᴍ",
    ]
    return "\n".join(lines)


# ============================================================
# SECTION 5 — KEYBOARD BUILDER
# ============================================================

def build_file_list_kb(
    sid: str,
    hits: List[Dict[str, Any]],
    page: int,
    per_page: int,
    per_row: int,
    bot_username: str = "",
) -> Tuple[InlineKeyboardMarkup, int, int]:
    """
    Build the file-list keyboard.

    Returns: (keyboard, total_pages, page)

    Notes:
      • Deep-link buttons when bot_username is set (preferred)
      • Fallback to sr:file:{sid}:{idx} callback when not set
      • Pagination via sr:more:{sid} callback (page-based)
    """
    total = len(hits)
    per_page = max(1, min(_PER_PAGE_MAX, int(per_page or _PER_PAGE_DEFAULT)))
    per_row = max(1, min(3, int(per_row or 1)))

    if total == 0:
        # Empty → just a close button
        return (
            InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"{F.EMO['cross']} {F.sc('close')}",
                    callback_data="sr:cancel",
                ),
            ]]),
            1,
            1,
        )

    total_pages = max(1, (total + per_page - 1) // per_page)
    page = max(1, min(total_pages, int(page or 1)))

    start = (page - 1) * per_page
    end = min(start + per_page, total)
    slice_hits = hits[start:end]

    rows: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []

    for i, h in enumerate(slice_hits):
        global_idx = start + i
        label = build_button_label(h)

        # Prefer deep-link (real button, works even if user hasn't started bot)
        if bot_username:
            deep = (
                f"https://t.me/{bot_username}"
                f"?start=file_{sid}_{global_idx}"
            )
            row.append(InlineKeyboardButton(label, url=deep))
        else:
            row.append(InlineKeyboardButton(
                label,
                callback_data=f"sr:file:{sid}:{global_idx}",
            ))

        if len(row) >= per_row:
            rows.append(row)
            row = []

    if row:
        rows.append(row)

    # Pagination row
    nav: List[InlineKeyboardButton] = []
    if page > 1:
        nav.append(InlineKeyboardButton(
            f"⬅️ {F.sc('prev')}",
            callback_data=f"sr:more:{sid}:{page - 1}",
        ))
    if page < total_pages:
        nav.append(InlineKeyboardButton(
            f"{F.sc('next')} ➡️",
            callback_data=f"sr:more:{sid}:{page + 1}",
        ))
    if nav:
        rows.append(nav)

    # Close button
    rows.append([InlineKeyboardButton(
        f"{F.EMO['cross']} {F.sc('close')}",
        callback_data="sr:cancel",
    )])

    return InlineKeyboardMarkup(rows), total_pages, page


# ============================================================
# SECTION 6 — SHOW FILE LIST (send or edit)
# ============================================================

async def show_file_list(
    target: Any,
    query: str,
    hits: List[Dict[str, Any]],
    sid: str,
    cfg: Dict[str, Any],
    client: Optional[Client] = None,
    page: int = 1,
) -> bool:
    """
    Send (or edit) the file list message.

    target: Message (send new) or status Message (edit)
    client: used to fetch bot username for deep-links
    """
         # Sort by the delivery step setting (not a top-level key)
        flow = cfg.get("flow") or {}
        fd = flow.get("file_delivery") or {}
        mode = str(fd.get("sort_order", "small_to_big") or "small_to_big")
        if mode not in ("small_to_big", "big_to_small"):
            mode = "small_to_big"
        sorted_hits = SEARCH.sort_hits(hits, mode=mode)

        # Resolve bot username
        bot_username = ""
        if client is not None:
            try:
                me = await client.identity()
                bot_username = me.username or ""
            except Exception:
                try:
                    me = await client.get_me()
                    bot_username = me.username or ""
                except Exception:
                    bot_username = ""

        # Per-page and per-row from the nested `search` section
        s_cfg = cfg.get("search") or {}
        try:
            per_page = int(
                s_cfg.get("search_per_page", _PER_PAGE_DEFAULT)
                or _PER_PAGE_DEFAULT
            )
        except (TypeError, ValueError):
            per_page = _PER_PAGE_DEFAULT
        try:
            per_row = int(s_cfg.get("search_per_row", 1) or 1)
        except (TypeError, ValueError):
            per_row = 1

        # Max items — from the delivery step (default 15, capped by _PER_PAGE_MAX
        # times pages). If 0/unset → no cap.
        try:
            max_items = int(fd.get("max_items", 15) or 15)
        except (TypeError, ValueError):
            max_items = 15
        max_items = max(1, min(30, max_items))
        if len(sorted_hits) > max_items:
            sorted_hits = sorted_hits[:max_items]

        total = len(sorted_hits)

        kb, total_pages, page = build_file_list_kb(
            sid=sid,
            hits=sorted_hits,
            page=page,
            per_page=per_page,
            per_row=per_row,
            bot_username=bot_username,
        )

        text = build_file_list_text(
            query=query,
            total=total,
            page=page,
            total_pages=total_pages,
        )

        try:
            try:
                await target.edit_text(
                    text,
                    reply_markup=kb,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
            except Exception as e_edit:
                if "not modified" in str(e_edit).lower():
                    return True
                # Can't edit (media message, deleted, etc.) → fall back
                await target.reply_text(
                    text,
                    reply_markup=kb,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
            return True
        except Exception as e:
            logger.debug(f"[DELIVERY] show: {e}")
            return False

# ============================================================
# SECTION 7 — SESSION CREATION
# ============================================================

async def create_session(
    user_id: int,
    chat_id: int,
    query: str,
    hits: List[Dict[str, Any]],
) -> str:
    """
    Create a media_search session for these hits.
    Returns sid or "" on failure.
    """
    try:
        from media_search import sessions as _sess_mod
        from media_search.normalizer import normalize

        session = await _sess_mod.sessions.create(
            user_id=user_id,
            chat_id=chat_id,
            query=query,
            normalized_query=normalize(query),
            mode="movie",
            candidates=list(hits),
        )
        return session.session_id if session else ""
    except Exception as e:
        logger.debug(f"[DELIVERY] session create: {e}")
        return ""


# ============================================================
# SECTION 8 — EMPTY RESULT CARD
# ============================================================

def build_empty_card(
    query: str,
    reason: str = "not_found",
) -> Tuple[str, InlineKeyboardMarkup]:
    """Message shown when nothing found."""
    if reason == "incomplete":
        title = "DBs unreachable"
        detail = "Try again in a moment."
    else:
        title = "No results"
        detail = "Try a different spelling or check the year."

    text = "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        F.DIV, "",
        f"❌ <b>{F.fb(title.upper())}</b>",
        "",
        f"🔍 <code>{F.sc(str(query)[:60])}</code>",
        "",
        f"📌 {F.sc(detail)}",
    ])

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('close')}",
            callback_data="sr:cancel",
        ),
    ]])
    return text, kb


# ============================================================
# SECTION 8b — AUTO-DELETE WARNING
# ============================================================

def build_autodelete_warning(
    seconds: int,
    title: str = "",
    count: int = 1,
) -> str:
    """
    Build the "this will be deleted" warning text.
    seconds — how long until deletion
    title   — movie/series name (optional)
    count   — number of files about to be sent
    """
    if seconds <= 0:
        return ""

    # Human-friendly time
    if seconds < 60:
        t_str = f"{seconds}s"
    elif seconds < 3600:
        mins = seconds // 60
        t_str = f"{mins} min"
    else:
        hrs = seconds // 3600
        t_str = f"{hrs}h"

    lines = [
        f"⚠️ <b>{F.fb('AUTO-DELETE ENABLED')}</b>",
        F.DIV, "",
    ]
    if title:
        lines.append(f"🎬 <b>{F.sc(title[:60])}</b>")

    if count > 1:
        lines.append(
            f"📁 <b>{count}</b> ꜰɪʟᴇꜱ · ᴡɪʟʟ ʙᴇ ᴅᴇʟᴇᴛᴇᴅ ɪɴ "
            f"<b>{t_str}</b>"
        )
    else:
        lines.append(
            f"📁 {F.sc('will be deleted in')} <b>{t_str}</b>"
        )

    lines += [
        "",
        F.DIV_S,
        f"📌 {F.sc('forward or save now')}",
        f"📌 {F.sc('once deleted, search again')}",
    ]
    return "\n".join(lines)


def read_autodelete_cfg(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """
    Return auto-delete settings for this group, in a form the
    delivery code can use directly.

    {
      "enabled": bool,       # overall
      "seconds": int,        # 0 = off
      "warn_first": bool,    # send warning before files
    }
    """
    ad = cfg.get("auto_delete") or {}
    enabled = bool(ad.get("bot_messages", True))
    try:
        seconds = int(ad.get("bot_timer", 600) or 0)
    except (TypeError, ValueError):
        seconds = 0

    if not enabled or seconds <= 0:
        return {"enabled": False, "seconds": 0, "warn_first": False}

    return {
        "enabled": True,
        "seconds": seconds,
        "warn_first": True,
    }


# ============================================================
# SECTION 9 — PUBLIC EXPORTS
# ============================================================

__all__ = [
    # Name + label helpers
    "clean_display_name",
    "build_button_label",
    "build_file_list_text",
    # Keyboards
    "build_file_list_kb",
    # High-level
    "show_file_list",
    "create_session",
    "build_empty_card",
    # Auto-delete
    "build_autodelete_warning",
    "read_autodelete_cfg",
]
