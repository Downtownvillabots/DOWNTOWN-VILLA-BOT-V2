# ============================================================
# 🏨 DOWNTOWN VILLA — OTT KEYBOARDS
# ============================================================

from __future__ import annotations
from typing import Any, Dict, List

from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from plugins.broadcast.config import sc
from plugins.ott.config import (
    REGIONS, LANGUAGE_LABELS, PRIMARY_LANGS, MIN_VOTE_PRESETS,
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
# HOME — language-first
# ═══════════════════════════════════════════════════════════

def kb_home() -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []
    for code, label in PRIMARY_LANGS:
        row.append(InlineKeyboardButton(
            f"🎬 {label}",
            callback_data=cb(f"lang:{code}"),
        ))
        if len(row) == 2:
            rows.append(row); row = []
    if row:
        rows.append(row)

    rows.append(_row(("🌐 All Languages", cb("lang:all")),
                     ("🔥 Trending", cb("trending"))))
    rows.append(_row(("📊 Dashboard", cb("dash")),
                     ("📢 Broadcasts", cb("bc"))))
    rows.append(_row(("⚙️ Settings", cb("set")),
                     ("🧪 Diagnostics", cb("diag"))))
    rows.append(_row(("🔄 Refetch Week", cb("refetch")),
                     ("❌ Close", cb("close"))))
    return InlineKeyboardMarkup(rows)


# ═══════════════════════════════════════════════════════════
# LANGUAGE VIEW
# ═══════════════════════════════════════════════════════════

def kb_lang_movies(lang: str, movies: List[Dict[str, Any]]
                   ) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    for m in movies[:20]:
        title = str(m.get("title", "?"))[:32]
        year = (m.get("release_date") or "")[:4]
        rows.append([InlineKeyboardButton(
            f"🎬 {title} ({year})",
            callback_data=cb(f"mv:{m.get('tmdb_id')}:{lang}"),
        )])
    if not movies:
        rows.append([InlineKeyboardButton(
            "🔄 Refetch", callback_data=cb(f"lang:{lang}"))])
    rows.append(_row(("🔄 Refresh", cb(f"lang:{lang}")),
                     ("🌐 All Languages", cb("lang:all"))))
    rows.extend(_back_close("ott:home"))
    return InlineKeyboardMarkup(rows)


# ═══════════════════════════════════════════════════════════
# MOVIE CARD
# ═══════════════════════════════════════════════════════════

def kb_movie(tmdb_id: int, sub_count: int, is_broadcasted: bool,
             back_cb: str = "ott:home") -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            f"📢 {'Re-post to channel' if is_broadcasted else 'Post to channel'}",
            callback_data=cb(f"bc_mv:{tmdb_id}"))],
    ]
    if sub_count > 0:
        rows.append([InlineKeyboardButton(
            f"🔔 Notify {sub_count} subscribers now",
            callback_data=cb(f"notify_go:{tmdb_id}"))])
    rows.append([InlineKeyboardButton(
        f"📊 Statistics",
        callback_data=cb(f"stats:{tmdb_id}"))])
    rows.append([InlineKeyboardButton(
        f"💥 END EVENT · delete all tokens",
        callback_data=cb(f"end_mv:{tmdb_id}"))])
    rows.extend(_back_close(back_cb))
    return InlineKeyboardMarkup(rows)


# ═══════════════════════════════════════════════════════════
# BROADCAST SETUP
# ═══════════════════════════════════════════════════════════

def kb_bc_setup(tmdb_id: int, channel: int, notify: bool,
                 hours: int, show_file: bool = True
                 ) -> InlineKeyboardMarkup:
    notify_lbl = "🟢 on" if notify else "🔴 off"
    file_lbl = "🟢 on" if show_file else "🔴 off"
    timer_lbl = ("♾️ never" if hours <= 0 else f"⏱️ {hours}h")
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"🔔 Notify button · {notify_lbl}",
            callback_data="ott:bcsetup_tog_notify")],
        [InlineKeyboardButton(
            f"📥 Get File button · {file_lbl}",
            callback_data="ott:bcsetup_tog_file")],
        [InlineKeyboardButton(
            f"🗑️ Auto-delete · {timer_lbl}",
            callback_data="ott:bcsetup_timer")],
        [InlineKeyboardButton(
            f"🚀 {sc('POST TO CHANNEL NOW')}",
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


# ═══════════════════════════════════════════════════════════
# CHANNEL POST KB (buttons UNDER the poster)
# ═══════════════════════════════════════════════════════════

def kb_channel_post(tmdb_id: int, notify: bool = True,
                    show_file: bool = True) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    if notify:
        rows.append([InlineKeyboardButton(
            f"🔔 Get Notified",
            callback_data=f"ott:sub:{tmdb_id}")])
    if show_file:
        rows.append([InlineKeyboardButton(
            f"📥 Get File",
            callback_data=f"ott:getfile:{tmdb_id}")])
    rows.append([InlineKeyboardButton(
        f"🎁 Add to Watchlist",
        callback_data=f"ott:wl_add:{tmdb_id}")])
    rows.append([InlineKeyboardButton(
        f"📊 Live Stats",
        callback_data=f"ott:stats_pub:{tmdb_id}")])
    return InlineKeyboardMarkup(rows)


# ═══════════════════════════════════════════════════════════
# STATS + END CONFIRM
# ═══════════════════════════════════════════════════════════

def kb_stats(tmdb_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"🔄 Refresh",
            callback_data=cb(f"stats:{tmdb_id}"))],
        [InlineKeyboardButton(
            f"🔔 Notify pending now",
            callback_data=cb(f"notify_go:{tmdb_id}"))],
        [InlineKeyboardButton(
            f"👥 View subscribers",
            callback_data=cb(f"subs_mv:{tmdb_id}"))],
        [InlineKeyboardButton(
            f"💥 END EVENT",
            callback_data=cb(f"end_mv:{tmdb_id}"))],
        *_back_close("ott:home"),
    ])


def kb_end_confirm(tmdb_id: int, tok: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"💥 YES, END EVERYTHING",
            callback_data=cb(f"end_do:{tmdb_id}:{tok}"))],
        [InlineKeyboardButton(
            f"⬅️ No, keep it",
            callback_data=cb(f"stats:{tmdb_id}"))],
    ])


# ═══════════════════════════════════════════════════════════
# BROADCAST HISTORY
# ═══════════════════════════════════════════════════════════

def kb_bc_history() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        _row(("🔄 Refresh", cb("bc_hist")),
             ("📢 Center", cb("bc"))),
        *_back_close("ott:home"),
    ])


def kb_bc_center(movies: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    for m in movies[:20]:
        title = str(m.get("title", "?"))[:32]
        rows.append([InlineKeyboardButton(
            f"🎬 {title}",
            callback_data=cb(f"bc_mv:{m.get('tmdb_id')}"),
        )])
    rows.append(_row(("📜 History", cb("bc_hist")),
                     ("🔄 Refresh", cb("bc"))))
    rows.extend(_back_close("ott:home"))
    return InlineKeyboardMarkup(rows)


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
            "📊 Statistics",
            callback_data=cb(f"stats:{tmdb_id}"))],
        [InlineKeyboardButton(
            "💥 Cancel ALL pending subs",
            callback_data=cb(f"end_mv:{tmdb_id}"))],
        *_back_close("ott:subs"),
    ])


# ═══════════════════════════════════════════════════════════
# NOTIFICATIONS / CACHE / SETTINGS / DIAG
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


def kb_diag() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Recheck", callback_data=cb("diag"))],
        *_back_close("ott:home"),
    ])


__all__ = [
    "cb",
    "kb_home", "kb_lang_movies", "kb_movie",
    "kb_bc_setup", "kb_bcsetup_timer", "kb_channel_post",
    "kb_stats", "kb_end_confirm",
    "kb_bc_history", "kb_bc_center",
    "kb_subs_overview", "kb_subs_movie",
    "kb_notif", "kb_cache",
    "kb_settings", "kb_region", "kb_langs", "kb_minvote",
    "kb_notifttl", "kb_bcttl", "kb_diag",
]
