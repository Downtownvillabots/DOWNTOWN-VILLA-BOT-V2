# ============================================================
# 🏨 DOWNTOWN VILLA — OTT KEYBOARDS (v3 — final layout)
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


def _row(*pairs) -> List[InlineKeyboardButton]:
    return [InlineKeyboardButton(lbl, callback_data=cd) for lbl, cd in pairs]


def _back_close(back_cb: str = "ott:home") -> List[List[InlineKeyboardButton]]:
    return [_row(("⬅️ Back", back_cb), ("❌ Close", "ott:close"))]


# ═══════════════════════════════════════════════════════════
# HOME (PM)
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
                     ("🔥 This Week", cb("week_all"))))
    rows.append(_row(("📊 Dashboard", cb("dash")),
                     ("⚙️ Settings", cb("set"))))
    rows.append(_row(("🔄 Refetch Week", cb("refetch")),
                     ("❌ Close", cb("close"))))
    return InlineKeyboardMarkup(rows)


# ═══════════════════════════════════════════════════════════
# LANGUAGE + DAY (PM)
# ═══════════════════════════════════════════════════════════

def kb_lang_days(lang: str, counts: List[int]) -> InlineKeyboardMarkup:
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    rows: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []

    for i in range(7):
        c = counts[i] if i < len(counts) else 0
        lbl = days[i] + (f" ({c})" if c else "")
        row.append(InlineKeyboardButton(
            lbl, callback_data=cb(f"lang_day:{lang}:{i}")))
        if len(row) == 2:
            rows.append(row); row = []
    if row:
        rows.append(row)

    rows.append([InlineKeyboardButton(
        "🌐 Show All This Week",
        callback_data=cb(f"lang_all:{lang}"))])
    rows.append(_row(("🔄 Refetch", cb(f"refetch_lang:{lang}")),
                     ("⬅️ Back", cb("home"))))
    rows.append([InlineKeyboardButton(
        "❌ Close", callback_data=cb("close"))])
    return InlineKeyboardMarkup(rows)


def kb_lang_day(lang: str, day_idx: int,
                 movies: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    for m in movies[:20]:
        title = str(m.get("title", "?"))[:28]
        rows.append([InlineKeyboardButton(
            f"🎬 {title}",
            callback_data=cb(f"mv:{m.get('tmdb_id')}:{lang}"),
        )])
    rows.append(_row(("⬅️ Back", cb(f"lang:{lang}")),
                     ("❌ Close", cb("close"))))
    return InlineKeyboardMarkup(rows)


# ═══════════════════════════════════════════════════════════
# MOVIE CARD (PM) — single button
# ═══════════════════════════════════════════════════════════

def kb_movie(tmdb_id: int, back_cb: str = "ott:home"
             ) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "📢 BROADCAST SETUP",
            callback_data=cb(f"csetup:{tmdb_id}"),
        )],
        _row(("⬅️ Back", back_cb), ("❌ Close", "ott:close")),
    ])


# ═══════════════════════════════════════════════════════════
# SETUP POST (ADMIN CHANNEL) — full control panel
# ═══════════════════════════════════════════════════════════

def kb_setup(tmdb_id: int, notify: bool, show_file: bool,
             hours: int) -> InlineKeyboardMarkup:
    notify_lbl = "🟢 ON" if notify else "🔴 OFF"
    file_lbl = "🟢 ON" if show_file else "🔴 OFF"
    timer_lbl = "♾️ Never" if hours <= 0 else f"⏱️ {hours}h"

    return InlineKeyboardMarkup([
        # ── Top row: Broadcast (full width) ──
        [InlineKeyboardButton(
            "📢 BROADCAST",
            callback_data=cb(f"csetup_bc:{tmdb_id}"),
        )],
        # ── Second row: End Task (full width) ──
        [InlineKeyboardButton(
            "💥 END TASK",
            callback_data=cb(f"end_mv:{tmdb_id}"),
        )],
        # ── Toggles (2 per row) ──
        [
            InlineKeyboardButton(
                f"🔔 Get Notified · {notify_lbl}",
                callback_data=cb(f"csetup_n:{tmdb_id}"),
            ),
            InlineKeyboardButton(
                f"📥 Get File · {file_lbl}",
                callback_data=cb(f"csetup_f:{tmdb_id}"),
            ),
        ],
        [
            InlineKeyboardButton(
                f"🗑️ Auto Delete · {timer_lbl}",
                callback_data=cb(f"csetup_t:{tmdb_id}"),
            ),
            InlineKeyboardButton(
                "📊 Live Stats",
                callback_data=cb(f"stats:{tmdb_id}"),
            ),
        ],
        # ── Back + Cancel ──
        [
            InlineKeyboardButton(
                "⬅️ Back",
                callback_data=cb(f"home"),
            ),
            InlineKeyboardButton(
                "❌ Cancel",
                callback_data=cb(f"csetup_x:{tmdb_id}"),
            ),
        ],
    ])


# ═══════════════════════════════════════════════════════════
# TIMER PICKER
# ═══════════════════════════════════════════════════════════

def kb_timer(tmdb_id: int, current: int) -> InlineKeyboardMarkup:
    rows, row = [], []
    for h in BC_DELETE_HOURS:
        label = "♾️ Never" if h == 0 else f"⏱️ {h}h"
        mark = "✅ " if h == current else ""
        row.append(InlineKeyboardButton(
            f"{mark}{label}",
            callback_data=cb(f"csetup_td:{tmdb_id}:{h}"),
        ))
        if len(row) == 3:
            rows.append(row); row = []
    if row:
        rows.append(row)

    rows.append([
        InlineKeyboardButton(
            "⬅️ Back",
            callback_data=cb(f"csetup:{tmdb_id}"),
        ),
        InlineKeyboardButton(
            "❌ Cancel",
            callback_data=cb(f"csetup_x:{tmdb_id}"),
        ),
    ])
    return InlineKeyboardMarkup(rows)


# ═══════════════════════════════════════════════════════════
# BROADCAST TARGET PICKER — 2 per row
# ═══════════════════════════════════════════════════════════

def kb_bc_targets(tmdb_id: int, counts: Dict[str, int]
                   ) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"📡 Channels ({counts.get('channels', 0)})",
                callback_data=cb(f"csetup_bc_ch:{tmdb_id}"),
            ),
            InlineKeyboardButton(
                f"👥 Groups ({counts.get('groups', 0)})",
                callback_data=cb(f"csetup_bc_gr:{tmdb_id}"),
            ),
        ],
        [
            InlineKeyboardButton(
                f"👤 All Users ({counts.get('all', 0):,})",
                callback_data=cb(f"csetup_bc_us:{tmdb_id}"),
            ),
            InlineKeyboardButton(
                f"💎 Premium ({counts.get('premium', 0)})",
                callback_data=cb(f"csetup_bc_pm:{tmdb_id}"),
            ),
        ],
        [InlineKeyboardButton(
            "✏️ Manual Target",
            callback_data=cb(f"csetup_bc_manual:{tmdb_id}"),
        )],
        [
            InlineKeyboardButton(
                "⬅️ Back",
                callback_data=cb(f"csetup:{tmdb_id}"),
            ),
            InlineKeyboardButton(
                "❌ Cancel",
                callback_data=cb(f"csetup_x:{tmdb_id}"),
            ),
        ],
    ])


# ═══════════════════════════════════════════════════════════
# CHANNEL PICKER — send-to-all + registered channels
# ═══════════════════════════════════════════════════════════

def kb_bc_channels(tmdb_id: int, channels: List[Dict[str, Any]]
                    ) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []

    # Send-to-all row
    rows.append([InlineKeyboardButton(
        "🌐 Send to ALL Channels",
        callback_data=cb(f"csetup_bc_send:{tmdb_id}:chall:0"),
    )])

    # Individual channels
    for c in channels[:15]:
        title = str(c.get("title") or c.get("chat_id") or "?")[:32]
        cid = c.get("chat_id")
        rows.append([InlineKeyboardButton(
            f"📢 {title}",
            callback_data=cb(f"csetup_bc_send:{tmdb_id}:ch:{cid}"),
        )])

    rows.append([
        InlineKeyboardButton(
            "⬅️ Back",
            callback_data=cb(f"csetup_bc:{tmdb_id}"),
        ),
        InlineKeyboardButton(
            "❌ Cancel",
            callback_data=cb(f"csetup_x:{tmdb_id}"),
        ),
    ])
    return InlineKeyboardMarkup(rows)


# ═══════════════════════════════════════════════════════════
# GROUP PICKER — send-to-all + registered groups
# ═══════════════════════════════════════════════════════════

def kb_bc_groups(tmdb_id: int, groups: List[Dict[str, Any]]
                  ) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []

    rows.append([InlineKeyboardButton(
        "🌐 Send to ALL Groups",
        callback_data=cb(f"csetup_bc_send:{tmdb_id}:grall:0"),
    )])

    for g in groups[:15]:
        title = str(g.get("title") or g.get("chat_id") or "?")[:32]
        gid = g.get("chat_id")
        rows.append([InlineKeyboardButton(
            f"👥 {title}",
            callback_data=cb(f"csetup_bc_send:{tmdb_id}:gr:{gid}"),
        )])

    rows.append([
        InlineKeyboardButton(
            "⬅️ Back",
            callback_data=cb(f"csetup_bc:{tmdb_id}"),
        ),
        InlineKeyboardButton(
            "❌ Cancel",
            callback_data=cb(f"csetup_x:{tmdb_id}"),
        ),
    ])
    return InlineKeyboardMarkup(rows)


# ═══════════════════════════════════════════════════════════
# CONFIRM SCREEN
# ═══════════════════════════════════════════════════════════

def kb_bc_confirm(tmdb_id: int, kind: str, target_id: int,
                  label: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"✅ Yes, Send to {label}",
            callback_data=cb(f"csetup_bc_do:{tmdb_id}:{kind}:{target_id}"),
        )],
        [
            InlineKeyboardButton(
                "⬅️ Back",
                callback_data=cb(f"csetup_bc:{tmdb_id}"),
            ),
            InlineKeyboardButton(
                "❌ Cancel",
                callback_data=cb(f"csetup_x:{tmdb_id}"),
            ),
        ],
    ])


# ═══════════════════════════════════════════════════════════
# LIVE POST (target + admin views)
# ═══════════════════════════════════════════════════════════

def kb_live(tmdb_id: int, notify: bool, show_file: bool,
            is_admin_view: bool = False,
            ended: bool = False) -> InlineKeyboardMarkup:
    # Ended: no buttons, poster becomes a monument
    if ended:
        return InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "📊 Final Stats",
                callback_data=cb(f"stats_pub:{tmdb_id}"),
            )],
        ])

    rows: List[List[InlineKeyboardButton]] = []

    # ── User-facing row ──
    user_row: List[InlineKeyboardButton] = []
    if notify:
        user_row.append(InlineKeyboardButton(
            "🔔 Get Notified",
            callback_data=cb(f"sub:{tmdb_id}"),
        ))
    if show_file:
        user_row.append(InlineKeyboardButton(
            "📥 Get Files",
            callback_data=cb(f"files:{tmdb_id}:0"),
        ))
    if user_row:
        rows.append(user_row)

    rows.append([InlineKeyboardButton(
        "🎁 Add to Watchlist",
        callback_data=cb(f"wl_add:{tmdb_id}"),
    )])

    # ── Admin controls (only in admin channel view) ──
    if is_admin_view:
        rows.append([
            InlineKeyboardButton(
                "📊 Live Stats",
                callback_data=cb(f"stats:{tmdb_id}"),
            ),
            InlineKeyboardButton(
                "📢 Broadcast",
                callback_data=cb(f"csetup_bc:{tmdb_id}"),
            ),
        ])
        rows.append([
            InlineKeyboardButton(
                "🔔 Notify Now",
                callback_data=cb(f"notify_go:{tmdb_id}"),
            ),
            InlineKeyboardButton(
                "💥 END TASK",
                callback_data=cb(f"end_mv:{tmdb_id}"),
            ),
        ])

    return InlineKeyboardMarkup(rows)


# ═══════════════════════════════════════════════════════════
# FILE LIST (user side)
# ═══════════════════════════════════════════════════════════

def _human(size) -> str:
    try:
        s = float(size or 0)
    except (TypeError, ValueError):
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while s >= 1024 and i < len(units) - 1:
        s /= 1024.0
        i += 1
    return f"{s:.2f} {units[i]}"


def kb_file_list(tmdb_id: int, files: List[Dict[str, Any]],
                 page: int = 0, per_page: int = 8
                 ) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    start = page * per_page
    chunk = files[start:start + per_page]

    for i, f in enumerate(chunk):
        idx = start + i
        quality = str(f.get("quality") or "HD")[:10]
        size = _human(f.get("file_size") or 0)
        rows.append([InlineKeyboardButton(
            f"📥 {quality} · {size}",
            callback_data=cb(f"file_get:{tmdb_id}:{idx}"),
        )])

    nav: List[InlineKeyboardButton] = []
    total_pages = max(1, (len(files) + per_page - 1) // per_page)
    if page > 0:
        nav.append(InlineKeyboardButton(
            "⬅️ Prev",
            callback_data=cb(f"files:{tmdb_id}:{page - 1}"),
        ))
    if total_pages > 1:
        nav.append(InlineKeyboardButton(
            f"{page + 1}/{total_pages}",
            callback_data=cb("noop"),
        ))
    if (page + 1) < total_pages:
        nav.append(InlineKeyboardButton(
            "Next ➡️",
            callback_data=cb(f"files:{tmdb_id}:{page + 1}"),
        ))
    if nav:
        rows.append(nav)

    rows.append([InlineKeyboardButton(
        "❌ Close",
        callback_data=cb("close"),
    )])
    return InlineKeyboardMarkup(rows)


# ═══════════════════════════════════════════════════════════
# STATS + END
# ═══════════════════════════════════════════════════════════

def kb_stats(tmdb_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "🔄 Refresh",
                callback_data=cb(f"stats:{tmdb_id}"),
            ),
            InlineKeyboardButton(
                "📢 Broadcast",
                callback_data=cb(f"csetup_bc:{tmdb_id}"),
            ),
        ],
        [
            InlineKeyboardButton(
                "🔔 Notify Now",
                callback_data=cb(f"notify_go:{tmdb_id}"),
            ),
            InlineKeyboardButton(
                "💥 END TASK",
                callback_data=cb(f"end_mv:{tmdb_id}"),
            ),
        ],
        [
            InlineKeyboardButton(
                "⬅️ Back",
                callback_data=cb(f"csetup:{tmdb_id}"),
            ),
            InlineKeyboardButton(
                "❌ Cancel",
                callback_data=cb(f"csetup_x:{tmdb_id}"),
            ),
        ],
    ])


def kb_end_confirm(tmdb_id: int, tok: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "💥 YES, END EVERYTHING",
            callback_data=cb(f"end_do:{tmdb_id}:{tok}"),
        )],
        [InlineKeyboardButton(
            "⬅️ No, Keep Task",
            callback_data=cb(f"csetup:{tmdb_id}"),
        )],
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
            "🔔 Notify Now",
            callback_data=cb(f"notify_go:{tmdb_id}"),
        )],
        [InlineKeyboardButton(
            "📊 Statistics",
            callback_data=cb(f"stats:{tmdb_id}"),
        )],
        [InlineKeyboardButton(
            "💥 END TASK",
            callback_data=cb(f"end_mv:{tmdb_id}"),
        )],
        *_back_close("ott:subs"),
    ])


# ═══════════════════════════════════════════════════════════
# NOTIFICATIONS / CACHE
# ═══════════════════════════════════════════════════════════

def kb_notif() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        _row(("🔄 Refresh", cb("notif")),
             ("🧹 Clear Log", cb("notif_clear"))),
        *_back_close("ott:home"),
    ])


def kb_cache() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🧹 Clear Cache",
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
             ("⭐ Min Votes", cb("set_minvote"))),
        _row(("🔔 Notify TTL", cb("set_notifttl")),
             ("📢 Broadcast TTL", cb("set_bcttl"))),
        _row(("🔄 Hype Loop", cb("set_tog:hype")),
             ("📅 Weekly Loop", cb("set_tog:weekly"))),
        _row(("🔄 Refresh", cb("set")),
             ("⬅️ Back", cb("home"))),
        [InlineKeyboardButton("❌ Close", callback_data=cb("close"))],
    ])


def kb_region(current: str) -> InlineKeyboardMarkup:
    rows, row = [], []
    for r in REGIONS:
        mark = "✅ " if r == current else ""
        row.append(InlineKeyboardButton(
            f"{mark}{r}",
            callback_data=cb(f"set_region_do:{r}"),
        ))
        if len(row) == 4:
            rows.append(row); row = []
    if row:
        rows.append(row)
    rows.extend(_back_close("ott:set"))
    return InlineKeyboardMarkup(rows)


def kb_langs(current: List[str]) -> InlineKeyboardMarkup:
    rows, row = [], []
    for code, label in LANGUAGE_LABELS.items():
        mark = "✅ " if code in current else ""
        row.append(InlineKeyboardButton(
            f"{mark}{code.upper()}",
            callback_data=cb(f"set_lang_tog:{code}"),
        ))
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
        callback_data=cb(f"set_minvote_do:{n}"),
    )] for n in MIN_VOTE_PRESETS]
    rows.extend(_back_close("ott:set"))
    return InlineKeyboardMarkup(rows)


def kb_notifttl(current: int) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(
        f"{'✅ ' if n == current else ''}{n} hours",
        callback_data=cb(f"set_notifttl_do:{n}"),
    )] for n in NOTIFY_TTL_PRESETS]
    rows.extend(_back_close("ott:set"))
    return InlineKeyboardMarkup(rows)


def kb_bcttl(current: int) -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(
        f"{'✅ ' if n == current else ''}{n} hours",
        callback_data=cb(f"set_bcttl_do:{n}"),
    )] for n in BROADCAST_TTL_PRESETS]
    rows.extend(_back_close("ott:set"))
    return InlineKeyboardMarkup(rows)


# ═══════════════════════════════════════════════════════════
# DASHBOARD / DIAGNOSTICS
# ═══════════════════════════════════════════════════════════

def kb_dashboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        _row(("🔄 Refresh", cb("dash")),
             ("🔄 Refetch", cb("refetch"))),
        *_back_close("ott:home"),
    ])


def kb_diag() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 Recheck", callback_data=cb("diag"))],
        *_back_close("ott:home"),
    ])


__all__ = [
    "cb",
    # PM
    "kb_home", "kb_lang_days", "kb_lang_day", "kb_movie",
    # Channel setup
    "kb_setup", "kb_timer",
    # Broadcast
    "kb_bc_targets", "kb_bc_channels", "kb_bc_groups",
    "kb_bc_confirm",
    # Live
    "kb_live", "kb_file_list",
    # Stats / end
    "kb_stats", "kb_end_confirm",
    # Subs
    "kb_subs_overview", "kb_subs_movie",
    # Misc
    "kb_notif", "kb_cache",
    "kb_settings", "kb_region", "kb_langs", "kb_minvote",
    "kb_notifttl", "kb_bcttl",
    "kb_dashboard", "kb_diag",
]
