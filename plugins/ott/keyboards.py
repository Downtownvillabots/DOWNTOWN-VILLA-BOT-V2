# ============================================================
# 🏨 DOWNTOWN VILLA — OTT KEYBOARDS
# ============================================================

from __future__ import annotations
from typing import Any, Dict, List

from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from plugins.broadcast.config import sc
from plugins.ott.config import (
    REGIONS, LANGUAGE_LABELS,
    MIN_VOTE_PRESETS, NOTIFY_TTL_PRESETS, BROADCAST_TTL_PRESETS,
)


def cb(*parts) -> str:
    return "ott:" + ":".join(str(p) for p in parts)


def _row(*pairs):
    """pairs: (label, callback) tuples → list of button rows."""
    return [InlineKeyboardButton(lbl, callback_data=cd)
            for lbl, cd in pairs]


def _back_close(back_cb: str = "ott:home") -> List[List[InlineKeyboardButton]]:
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


def kb_bc_targets(tmdb_id: int, counts: Dict[str, int]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"📡 Channels ({counts.get('channels', 0)})",
            callback_data=cb(f"bc_confirm:{tmdb_id}:channels"))],
        [InlineKeyboardButton(
            f"👥 Groups ({counts.get('groups', 0)})",
            callback_data=cb(f"bc_confirm:{tmdb_id}:groups"))],
        [InlineKeyboardButton(
            f"👤 Subscribers of this movie ({counts.get('subs', 0)})",
            callback_data=cb(f"bc_confirm:{tmdb_id}:users"))],
        [InlineKeyboardButton(
            f"💎 Premium users ({counts.get('premium', 0)})",
            callback_data=cb(f"bc_confirm:{tmdb_id}:premium"))],
        [InlineKeyboardButton(
            f"🌐 ALL users ({counts.get('all', 0):,})",
            callback_data=cb(f"bc_confirm:{tmdb_id}:all"))],
        *_back_close("ott:bc"),
    ])


def kb_bc_confirm(tmdb_id: int, target: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "✅ Yes, send now",
            callback_data=cb(f"bc_do:{tmdb_id}:{target}"))],
        [InlineKeyboardButton(
            "❌ Cancel",
            callback_data=cb(f"bc_mv:{tmdb_id}"))],
    ])


def kb_bc_progress(jid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "⏹️ CANCEL",
            callback_data=cb(f"bc_stop:{jid}"))],
    ])


def kb_bc_done(tmdb_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "👥 View subscribers",
            callback_data=cb(f"subs_mv:{tmdb_id}"))],
        *_back_close("ott:bc"),
    ])


def kb_bc_history(items: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
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
        [InlineKeyboardButton(
            "🗑️ Delete channel broadcast post",
            callback_data=cb(f"del_post:{tmdb_id}"))],
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
        [InlineKeyboardButton(
            "🧹 Clear cache",
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
        _row(("⭐ Min votes", cb("set_minvote")),
             ("📺 Channel", cb("set_channel"))),
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
    "kb_home", "kb_dashboard", "kb_week", "kb_day",
    "kb_movie",
    "kb_bc_center", "kb_bc_targets", "kb_bc_confirm",
    "kb_bc_progress", "kb_bc_done", "kb_bc_history",
    "kb_subs_overview", "kb_subs_movie", "kb_cancel_confirm",
    "kb_notif", "kb_cache",
    "kb_settings", "kb_region", "kb_langs", "kb_minvote",
    "kb_notifttl", "kb_bcttl", "kb_diag",
    "_back_close",
]
