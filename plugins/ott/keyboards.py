# ============================================================
# 🏨 DOWNTOWN VILLA — OTT KEYBOARDS
# ============================================================

from __future__ import annotations
from typing import Any, Dict, List

from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from plugins.broadcast.config import sc
from plugins.ott.config import (
    REGIONS, LANGUAGE_LABELS, MIN_VOTE_PRESETS,
    NOTIFY_TTL_PRESETS, BROADCAST_TTL_PRESETS, BC_DELETE_HOURS,
)


def cb(*parts) -> str:
    return "ott:" + ":".join(str(p) for p in parts)


def _row(*pairs):
    return [InlineKeyboardButton(lbl, callback_data=cd)
            for lbl, cd in pairs]


def _back_close(back_cb: str = "ott:home"):
    return [_row(("⬅️ Back", back_cb), ("❌ Close", "ott:close"))]


# ═══════════════════════════════════════════════════════════
# HOME
# ═══════════════════════════════════════════════════════════

def kb_home() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        _row(("📊 Dashboard", cb("dash")),
             ("📅 This Week", cb("week"))),
        _row(("📢 Broadcast", cb("bc")),
             ("👥 Subscribers", cb("subs"))),
        _row(("🔔 Notifications", cb("notif")),
             ("🎬 Movie Cache", cb("cache"))),
        _row(("⚙️ Settings", cb("set")),
             ("🧪 Diagnostics", cb("diag"))),
        _row(("🔄 Refetch Week", cb("refetch")),
             ("❌ Close", cb("close"))),
    ])


# ═══════════════════════════════════════════════════════════
# DASHBOARD / WEEK / DAY
# ═══════════════════════════════════════════════════════════

def kb_dashboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        _row(("🔄 Refresh", cb("dash")),
             ("📢 Broadcast", cb("bc"))),
        *_back_close("ott:home"),
    ])


def kb_week(counts: List[int]) -> InlineKeyboardMarkup:
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    rows = []
    row: List[InlineKeyboardButton] = []
    for i in range(7):
        lbl = days[i] + (f" ({counts[i]})" if counts[i] else "")
        row.append(InlineKeyboardButton(lbl, callback_data=cb(f"day:{i}")))
        if len(row) == 2:
            rows.append(row); row = []
    if row:
        rows.append(row)
    rows.append(_row(("🔄 Refetch", cb("refetch")),
                     ("📢 Broadcast", cb("bc"))))
    rows.extend(_back_close("ott:home"))
    return InlineKeyboardMarkup(rows)


def kb_day(movies: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    for m in movies[:12]:
        title = str(m.get("title", "?"))[:32]
        rows.append([InlineKeyboardButton(
            f"🎬 {title}",
            callback_data=cb(f"mv:{m.get('tmdb_id')}"),
        )])
    rows.extend(_back_close("ott:week"))
    return InlineKeyboardMarkup(rows)


# ═══════════════════════════════════════════════════════════
# MOVIE CARD
# ═══════════════════════════════════════════════════════════

def kb_movie(tmdb_id: int, sub_count: int, back_cb: str = "ott:week"
             ) -> InlineKeyboardMarkup:
    rows = [
        _row((f"📢 Broadcast this", cb(f"bc_mv:{tmdb_id}")),
             (f"🔔 Notify Now", cb(f"notify_go:{tmdb_id}"))),
        [InlineKeyboardButton(
            f"👥 Subscribers ({sub_count})",
            callback_data=cb(f"subs_mv:{tmdb_id}"))],
        [InlineKeyboardButton(
            f"💥 Cancel & Purge tokens",
            callback_data=cb(f"cancel_mv:{tmdb_id}"))],
        _row((f"🔄 Re-enrich", cb(f"enrich:{tmdb_id}")),),
    ]
    rows.extend(_back_close(back_cb))
    return InlineKeyboardMarkup(rows)


# ═══════════════════════════════════════════════════════════
# BROADCAST
# ═══════════════════════════════════════════════════════════

def kb_bc_center(movies: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    for m in movies[:12]:
        title = str(m.get("title", "?"))[:32]
        rows.append([InlineKeyboardButton(
            f"🎬 {title}",
            callback_data=cb(f"bc_mv:{m.get('tmdb_id')}"),
        )])
    rows.append(_row(("📜 History", cb("bc_hist")),
                     ("🔄 Refresh", cb("bc"))))
    rows.extend(_back_close("ott:home"))
    return InlineKeyboardMarkup(rows)


def kb_bc_setup(tmdb_id: int, channel: int, notify: bool,
                 hours: int) -> InlineKeyboardMarkup:
    notify_lbl = "🟢 on" if notify else "🔴 off"
    timer_lbl = ("♾️ never" if hours <= 0 else f"⏱️ {hours}h")
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"🔔 Notify button · {notify_lbl}",
            callback_data="ott:bcsetup_tog_notify")],
        [InlineKeyboardButton(
            f"🗑️ Auto-delete · {timer_lbl}",
            callback_data="ott:bcsetup_timer")],
        [InlineKeyboardButton(
            f"🚀 {sc('SEND TO CHANNEL NOW')}",
            callback_data="ott:bcsetup_send")],
        [InlineKeyboardButton("⬅️ Back",
                              callback_data=f"ott:bc_mv:{tmdb_id}"),
         InlineKeyboardButton("❌ Close", callback_data="ott:close")],
    ])


def kb_bcsetup_timer(tmdb_id: int, current: int) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []
    for h in BC_DELETE_HOURS:
        label = "♾️ never" if h == 0 else f"{h}h"
        mark = "✅ " if h == current else ""
        row.append(InlineKeyboardButton(
            f"{mark}{label}",
            callback_data=f"ott:bcsetup_timer_do:{h}"))
        if len(row) == 3:
            rows.append(row); row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(
        "⬅️ Back", callback_data=f"ott:bcsetup:{tmdb_id}")])
    return InlineKeyboardMarkup(rows)


def ott_channel_kb(tmdb_id: int, notify: bool = True) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    if notify:
        rows.append([InlineKeyboardButton(
            f"🔔 {sc('Get Notified')}",
            callback_data=f"ott:sub:{tmdb_id}")])
        rows.append([InlineKeyboardButton(
            f"🎁 {sc('Add to watchlist')}",
            callback_data=f"ott:wl_add:{tmdb_id}")])
    rows.append([InlineKeyboardButton(
        f"📤 {sc('Share')}",
        callback_data=f"ott:share:{tmdb_id}")])
    return InlineKeyboardMarkup(rows)


def kb_bc_history() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        _row(("🔄 Refresh", cb("bc_hist")),
             ("📢 Center", cb("bc"))),
        *_back_close("ott:home"),
    ])


# ═══════════════════════════════════════════════════════════
# SUBSCRIBERS
# ═══════════════════════════════════════════════════════════

def kb_subs_overview(items: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    for it in items[:15]:
        title = str(it.get("title") or "?")[:28]
        cnt = it.get("count", 0)
        rows.append([InlineKeyboardButton(
            f"🎬 {title} ({cnt})",
            callback_data=cb(f"subs_mv:{it.get('_id')}"),
        )])
    rows.extend(_back_close("ott:home"))
    return InlineKeyboardMarkup(rows)


def kb_subs_movie(tmdb_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🔔 Notify now",
            callback_data=cb(f"notify_go:{tmdb_id}"))],
        [InlineKeyboardButton(
            "💥 Cancel ALL pending subs",
            callback_data=cb(f"cancel_subs:{tmdb_id}"))],
        *_back_close("ott:subs"),
    ])


def kb_cancel_confirm(tmdb_id: int, tok: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "💥 YES, FULL CANCEL",
            callback_data=cb(f"cancel_do:{tmdb_id}:{tok}"))],
        [InlineKeyboardButton(
            "⬅️ No, keep it",
            callback_data=cb(f"subs_mv:{tmdb_id}"))],
    ])


# ═══════════════════════════════════════════════════════════
# NOTIFICATIONS / CACHE
# ═══════════════════════════════════════════════════════════

def kb_notif() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        _row(("🔄 Refresh", cb("notif")),
             ("🧹 Clear log", cb("notif_clear"))),
        *_back_close("ott:home"),
    ])


def kb_cache() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧹 Clear cache",
                              callback_data=cb("cache_clear"))],
        *_back_close("ott:home"),
    ])


# ═══════════════════════════════════════════════════════════
# SETTINGS
# ═══════════════════════════════════════════════════════════

def kb_settings() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        _row(("🌍 Region", cb("set_region")),
             ("🌐 Languages", cb("set_langs"))),
        _row(("📢 OTT Channel", cb("set_ott_channel")),
             ("⭐ Min votes", cb("set_minvote"))),
        _row(("🔔 Notify TTL", cb("set_notifttl")),
             ("📢 Broadcast TTL", cb("set_bcttl"))),
        _row(("🔄 Hype loop", cb("set_tog:hype")),
             ("📅 Weekly loop", cb("set_tog:weekly"))),
        _row(("🔔 Share button", cb("set_tog:share")),
             ("📊 Auto-delete", cb("set_tog:autodel"))),
        _row(("🔄 Refresh", cb("set")),
             ("⬅️ Back", cb("home"))),
        [InlineKeyboardButton("❌ Close", callback_data=cb("close"))],
    ])


def kb_region(current: str) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []
    for r in REGIONS:
        mark = "✅ " if r == current else ""
        row.append(InlineKeyboardButton(
            f"{mark}{r}", callback_data=cb(f"set_region_do:{r}")))
        if len(row) == 4:
            rows.append(row); row = []
    if row:
        rows.append(row)
    rows.extend(_back_close("ott:set"))
    return InlineKeyboardMarkup(rows)


def kb_langs(current: List[str]) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []
    for code, label in LANGUAGE_LABELS.items():
        mark = "✅ " if code in current else ""
        row.append(InlineKeyboardButton(
            f"{mark}{code.upper()}",
            callback_data=cb(f"set_lang_tog:{code}")))
        if len(row) == 5:
            rows.append(row); row = []
    if row:
        rows.append(row)
    rows.append(_row(("✅ Done", cb("set")),
                     ("🔄 Reset", cb("set_langs_reset"))))
    rows.extend(_back_close("ott:set"))
    return InlineKeyboardMarkup(rows)


def kb_minvote(current: int) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(
        f"{'✅ ' if n == current else ''}{n} votes",
        callback_data=cb(f"set_minvote_do:{n}"))]
        for n in MIN_VOTE_PRESETS]
    rows.extend(_back_close("ott:set"))
    return InlineKeyboardMarkup(rows)


def kb_notifttl(current: int) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(
        f"{'✅ ' if n == current else ''}{n} hours",
        callback_data=cb(f"set_notifttl_do:{n}"))]
        for n in NOTIFY_TTL_PRESETS]
    rows.extend(_back_close("ott:set"))
    return InlineKeyboardMarkup(rows)


def kb_bcttl(current: int) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(
        f"{'✅ ' if n == current else ''}{n} hours",
        callback_data=cb(f"set_bcttl_do:{n}"))]
        for n in BROADCAST_TTL_PRESETS]
    rows.extend(_back_close("ott:set"))
    return InlineKeyboardMarkup(rows)


# ═══════════════════════════════════════════════════════════
# DIAGNOSTICS
# ═══════════════════════════════════════════════════════════

def kb_diag() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Recheck", callback_data=cb("diag"))],
        *_back_close("ott:home"),
    ])


__all__ = [
    "cb",
    "kb_home", "kb_dashboard", "kb_week", "kb_day", "kb_movie",
    "kb_bc_center", "kb_bc_setup", "kb_bcsetup_timer",
    "kb_bc_history", "ott_channel_kb",
    "kb_subs_overview", "kb_subs_movie", "kb_cancel_confirm",
    "kb_notif", "kb_cache",
    "kb_settings", "kb_region", "kb_langs", "kb_minvote",
    "kb_notifttl", "kb_bcttl", "kb_diag",
]
