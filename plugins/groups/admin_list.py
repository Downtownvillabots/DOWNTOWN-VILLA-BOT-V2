# ============================================================
# 🏨 DOWNTOWN VILLA — GROUPS ADMIN LIST
# ============================================================
#
# Entry point from /admin → 👥 Groups.
#
# Shows every connected group (from `groups` collection)
# and every registered indexing channel (from `indexing_channels`).
#
# Admin picks one → opens its settings panel here in PM.
#
# Callback prefix: glist:
# Handler group: -8498 (runs AFTER router.py at -8500)
#
# Callback map:
#   glist:home              refresh list
#   glist:open:{chat_id}    open that group's panel
#   glist:close             close message
#
# This module intentionally uses a distinct prefix (glist:)
# so it never collides with the panel router's ga: prefix.
#
# ============================================================

from __future__ import annotations

import logging
from typing import Any, Dict, List, Tuple

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
)

from core import config
from plugins.groups import state as S
from plugins.groups import router as R
from utils import fonts as F
from utils import format as FM

logger = logging.getLogger(__name__)

PFX = "glist"


# ============================================================
# SECTION 1 — AUTH
# ============================================================

def _is_bot_admin(uid) -> bool:
    try:
        return int(uid) in [int(a) for a in config.ADMINS]
    except Exception:
        return False


# ============================================================
# SECTION 2 — DATA SOURCES
# ============================================================

async def _list_groups() -> List[Dict[str, Any]]:
    """Connected groups (from user DB `groups` collection)."""
    try:
        docs = await S.list_groups(limit=50)
        out: List[Dict[str, Any]] = []
        for d in docs:
            cid = d.get("chat_id")
            if not cid:
                continue
            title = str(d.get("title") or "").strip()
            username = str(d.get("username") or "").strip().lstrip("@")
            if (not title or title.lstrip("-").isdigit()
                    or title.casefold() in {"group", "channel"}):
                title = f"@{username}" if username else "Group"
            out.append({
                "chat_id": int(cid),
                "title": title[:60],
                "username": d.get("username") or "",
                "kind": "group",
                "content_mode": str(
                    d.get("content_mode") or "both"
                ).lower(),
                "enabled": bool(d.get("enabled", True)),
            })
        return out
    except Exception as e:
        logger.debug(f"[GLIST] groups: {e}")
        return []


async def _list_channels() -> List[Dict[str, Any]]:
    """Registered indexing channels (from system DB)."""
    try:
        from plugins.indexing import backward as BW
        docs = await BW.list_registered_channels()
        out: List[Dict[str, Any]] = []
        for d in docs:
            cid = d.get("chat_id")
            if not cid:
                continue
            title = str(d.get("title") or "").strip()
            username = str(d.get("username") or "").strip().lstrip("@")
            if (not title or title.lstrip("-").isdigit()
                    or title.casefold() in {"group", "channel"}):
                title = f"@{username}" if username else "Channel"
            out.append({
                "chat_id": int(cid),
                "title": title[:60],
                "username": d.get("username") or "",
                "kind": "channel",
                "enabled": bool(d.get("enabled", True)),
            })
        return out
    except Exception as e:
        logger.debug(f"[GLIST] channels: {e}")
        return []


# ============================================================
# SECTION 3 — MAIN RENDER
# ============================================================

async def build() -> Tuple[str, InlineKeyboardMarkup]:
    """Public entry — called by admin.py's _build_page_builder('groups')."""
    return await render_home()


async def render_home() -> Tuple[str, InlineKeyboardMarkup]:
    """
    Entry point from /admin → 👥 Groups.
    Shows 4 category filter buttons.
    """
    groups = await _list_groups()
    channels = await _list_channels()

    series = [g for g in groups if g.get("content_mode") == "series"]
    movies = [g for g in groups if g.get("content_mode") == "movie"]
    both = [g for g in groups if g.get("content_mode") == "both"]

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"👥 <b>{F.fb('GROUPS')}</b>",
        F.DIV, "",
        f"📊 {F.sc('summary')}",
        "",
        f"📺 {F.sc('series groups')} · <b>{len(series)}</b>",
        f"🎬 {F.sc('movie groups')} · <b>{len(movies)}</b>",
        f"🎬📺 {F.sc('both')} · <b>{len(both)}</b>",
        f"👥 {F.sc('total groups')} · <b>{len(groups)}</b>",
        f"📢 {F.sc('indexing channels')} · <b>{len(channels)}</b>",
        "",
        F.DIV_S,
        f"📌 {F.sc('pick a category to manage')}",
        f"📌 {F.sc('settings apply instantly — no restart')}",
        "",
        f"🕒 <code>{FM.datetime_()}</code>",
    ]

    rows: List[List[InlineKeyboardButton]] = [
        [InlineKeyboardButton(
            f"📺 {F.sc('series groups')} ({len(series)})",
            callback_data="glist:filter:series",
        )],
        [InlineKeyboardButton(
            f"🎬 {F.sc('movie groups')} ({len(movies)})",
            callback_data="glist:filter:movie",
        )],
        [InlineKeyboardButton(
            f"🎬📺 {F.sc('both')} ({len(both)})",
            callback_data="glist:filter:both",
        )],
        [InlineKeyboardButton(
            f"👥 {F.sc('all groups')} ({len(groups)})",
            callback_data="glist:filter:all",
        )],
    ]

    if channels:
        rows.append([InlineKeyboardButton(
            f"📢 {F.sc('indexing channels')} ({len(channels)})",
            callback_data="glist:filter:channels",
        )])

    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['refresh']} {F.sc('refresh')}",
            callback_data="glist:home",
        ),
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('admin')}",
            callback_data="adm:home",
        ),
    ])
    rows.append([InlineKeyboardButton(
        f"{F.EMO['cross']} {F.sc('close')}",
        callback_data="glist:close",
    )])

    return "\n".join(lines)[:4000], InlineKeyboardMarkup(rows)


async def render_filter_list(mode: str) -> Tuple[str, InlineKeyboardMarkup]:
    """
    List groups filtered by content_mode.

    mode = series | movie | both | all | channels
    """
    groups = await _list_groups()

    # ── Channels special case ──
    if mode == "channels":
        return await _render_channels_list()

    # ── Pick list + header ──
    if mode == "series":
        filtered = [g for g in groups if g.get("content_mode") == "series"]
        icon, label = "📺", "SERIES GROUPS"
    elif mode == "movie":
        filtered = [g for g in groups if g.get("content_mode") == "movie"]
        icon, label = "🎬", "MOVIE GROUPS"
    elif mode == "both":
        filtered = [g for g in groups if g.get("content_mode") == "both"]
        icon, label = "🎬📺", "BOTH GROUPS"
    else:  # "all" or unknown
        filtered = groups
        icon, label = "👥", "ALL GROUPS"

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"{icon} <b>{F.fb(label)}</b>",
        F.DIV, "",
        f"📊 {F.sc('total')} · <b>{len(filtered)}</b>",
        "",
    ]

    rows: List[List[InlineKeyboardButton]] = []

    if not filtered:
        lines.append(f"⚪ {F.sc('no groups in this category')}")
        lines.append("")
        lines.append(
            f"📌 {F.sc('set content mode from the group panel')}"
        )
        lines.append(
            f"📌 {F.sc('content mode')} · "
            f"<code>{F.sc(mode)}</code>"
        )
    else:
        # Show up to 40 groups
        for g in filtered[:40]:
            cid = g["chat_id"]
            title = g["title"][:36]
            enabled = g.get("enabled", True)
            marker = "🟢" if enabled else "🔴"
            mode_icon = {
                "series": "📺",
                "movie": "🎬",
                "both": "🎬📺",
            }.get(g.get("content_mode"), "🎬📺")

            lines.append(f"{marker} {mode_icon} {F.sc(title)}")

            rows.append([InlineKeyboardButton(
                f"{marker} {mode_icon} {title}",
                callback_data=f"glist:open:{cid}",
            )])

    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data="glist:home",
        ),
        InlineKeyboardButton(
            f"{F.EMO['refresh']} {F.sc('refresh')}",
            callback_data=f"glist:filter:{mode}",
        ),
    ])
    rows.append([InlineKeyboardButton(
        f"{F.EMO['cross']} {F.sc('close')}",
        callback_data="glist:close",
    )])

    return "\n".join(lines)[:4000], InlineKeyboardMarkup(rows)


async def _render_channels_list() -> Tuple[str, InlineKeyboardMarkup]:
    """Channels view — extracted from old render_home."""
    channels = await _list_channels()

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"📢 <b>{F.fb('INDEXING CHANNELS')}</b>",
        F.DIV, "",
        f"📊 {F.sc('total')} · <b>{len(channels)}</b>",
        "",
    ]

    rows: List[List[InlineKeyboardButton]] = []

    if not channels:
        lines.append(f"⚪ {F.sc('no channels registered yet')}")
        lines.append("")
        lines.append(f"📌 {F.sc('add bot as admin to a channel')}")
        lines.append(f"📌 {F.sc('or forward a message from a channel')}")
    else:
        for ch in channels[:30]:
            cid = ch["chat_id"]
            title = ch["title"][:36]
            marker = "🟢" if ch.get("enabled", True) else "🔴"
            lines.append(f"{marker} 📢 {F.sc(title)}")
            rows.append([InlineKeyboardButton(
                f"{marker} 📢 {title}",
                callback_data=f"glist:open:{cid}",
            )])

    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data="glist:home",
        ),
        InlineKeyboardButton(
            f"{F.EMO['refresh']} {F.sc('refresh')}",
            callback_data="glist:filter:channels",
        ),
    ])
    rows.append([InlineKeyboardButton(
        f"{F.EMO['cross']} {F.sc('close')}",
        callback_data="glist:close",
    )])

    return "\n".join(lines)[:4000], InlineKeyboardMarkup(rows)


# ============================================================
# SECTION 4 — CALLBACK ROUTER
# ============================================================

@Client.on_callback_query(
    filters.regex(rf"^{PFX}:"),
    group=-8498,
)
async def admin_list_router(client: Client, q: CallbackQuery):
    if not q.from_user or not _is_bot_admin(q.from_user.id):
        return await q.answer("⛔ bot admins only", show_alert=True)

    parts = str(q.data).split(":")
    action = parts[1] if len(parts) > 1 else ""
    uid = q.from_user.id

    try:
        # ── NO-OP (divider rows) ──
        if action == "noop":
            return await q.answer()

        # ── REFRESH LIST ──
        if action == "home":
            text, kb = await render_home()
            await _safe_edit(q, text, kb)
            return await q.answer()

        # ── FILTER BY MODE ──
        if action == "filter":
            mode = parts[2] if len(parts) > 2 else "all"
            text, kb = await render_filter_list(mode)
            await _safe_edit(q, text, kb)
            return await q.answer()

        # ── CLOSE ──
        if action == "close":
            try:
                await q.message.delete()
            except Exception:
                pass
            return await q.answer("Closed")

        # ── OPEN GROUP PANEL ──
        if action == "open":
            try:
                chat_id = int(parts[2])
            except (ValueError, IndexError):
                return await q.answer("❌ invalid chat id")

            # Ensure the group exists in state DB
            await S.register_group(chat_id)

            # Set session so the panel router knows the target chat.
            # step name is "view" — text_input.py silently ignores
            # unknown steps, so this is safe.
            R._sess_new(uid, "view", chat_id)

            # Render the panel and edit the existing message
            await R.open_panel_edit(client, q, chat_id)
            return await q.answer("⚙️ Opening…")

        return await q.answer("❓ Unknown", show_alert=True)

    except Exception as e:
        logger.exception(f"[GLIST] router: {e}")
        try:
            await q.answer(f"❌ {type(e).__name__}", show_alert=True)
        except Exception:
            pass


# ============================================================
# SECTION 5 — SAFE EDIT
# ============================================================

async def _safe_edit(q: CallbackQuery, text: str, kb) -> None:
    try:
        await q.message.edit_text(
            text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        if "not modified" in str(e).lower():
            return
        logger.debug(f"[GLIST] edit: {e}")


# ============================================================
# SECTION 6 — PUBLIC EXPORTS
# ============================================================

__all__ = [
    "build",
    "render_home",
    "render_filter_list",
]
