# ============================================================
# 🏨 DOWNTOWN VILLA — BOT USAGE STATS (ULTIMATE)
# ============================================================
#
# Live bot usage dashboard.
#
# Sections:
#   • Overview: users, searches, files, commands, errors
#   • Top searches (with color bars)
#   • Top commands
#   • Daily users + searches (last 7 days)
#   • Live event rates
#   • Sparklines (searches / files / commands)
#   • Cache hit rate
#   • Per-user stats (top 10)
#
# Public API for other modules:
#   track_search(user_id, query)
#   track_command(user_id, command)
#   track_callback(user_id, callback)
#   track_message(user_id, type)
#   track_file_sent(count)
#   track_file_indexed(count)
#   track_error(message)
#   live_snapshot()
#
# ============================================================

from __future__ import annotations

import logging
import time
from collections import Counter, deque
from datetime import datetime, timedelta
from typing import Any, Deque, Dict, List, Optional, Tuple

from pyrogram.enums import ParseMode
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from core import config
from utils import fonts as F
from utils import format as FM
from utils import progress as P

logger = logging.getLogger(__name__)


# ============================================================
# SECTION 1 — TRACKERS (public, called from anywhere)
# ============================================================

STATS: Dict[str, int] = {
    "searches": 0,
    "users_seen": 0,
    "files_sent": 0,
    "files_indexed": 0,
    "files_skipped": 0,
    "errors": 0,
    "commands": 0,
    "callbacks": 0,
    "messages": 0,
    "downloads": 0,
    "uploads": 0,
}

KNOWN_USERS: set = set()
DAILY_USERS: Counter = Counter()
DAILY_SEARCHES: Counter = Counter()
USER_SEARCHES: Counter = Counter()
USER_COMMANDS: Counter = Counter()
USER_LAST_SEEN: Dict[int, float] = {}
SEARCH_TERMS: Counter = Counter()
COMMAND_TERMS: Counter = Counter()

# Sparkline buffers (30 samples)
_spark_searches: Deque[int] = deque(maxlen=30)
_spark_files: Deque[int] = deque(maxlen=30)
_spark_commands: Deque[int] = deque(maxlen=30)
_spark_users: Deque[int] = deque(maxlen=30)

# Recent activity counters (for rate calc)
_recent_events: Deque[Tuple[float, str]] = deque(maxlen=2000)


def _today() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d")


def _record_event(kind: str) -> None:
    _recent_events.append((time.time(), kind))


def track_user(user_id: Any) -> None:
    if not user_id:
        return
    try:
        uid = int(user_id)
        if uid not in KNOWN_USERS:
            KNOWN_USERS.add(uid)
            STATS["users_seen"] = len(KNOWN_USERS)
            DAILY_USERS[_today()] += 1
        USER_LAST_SEEN[uid] = time.time()
    except Exception:
        pass


def track_search(user_id: Any, query: str = "") -> None:
    try:
        track_user(user_id)
        STATS["searches"] += 1
        DAILY_SEARCHES[_today()] += 1
        if user_id:
            USER_SEARCHES[int(user_id)] += 1
        q = str(query or "").strip().lower()
        if q:
            SEARCH_TERMS[q] += 1
        _record_event("search")
    except Exception:
        pass


def track_command(user_id: Any, command: str = "") -> None:
    try:
        track_user(user_id)
        STATS["commands"] += 1
        if user_id:
            USER_COMMANDS[int(user_id)] += 1
        if command:
            COMMAND_TERMS[str(command)] += 1
        _record_event("command")
    except Exception:
        pass


def track_callback(user_id: Any, callback: str = "") -> None:
    try:
        track_user(user_id)
        STATS["callbacks"] += 1
        _record_event("callback")
    except Exception:
        pass


def track_message(user_id: Any = None, message_type: str = "message") -> None:
    try:
        track_user(user_id)
        STATS["messages"] += 1
        _record_event("message")
    except Exception:
        pass


def track_file_sent(count: int = 1) -> None:
    try:
        STATS["files_sent"] += int(count)
        _record_event("file_sent")
    except Exception:
        pass


def track_file_indexed(count: int = 1) -> None:
    try:
        STATS["files_indexed"] += int(count)
        _record_event("index")
    except Exception:
        pass


def track_file_skipped(count: int = 1) -> None:
    try:
        STATS["files_skipped"] += int(count)
    except Exception:
        pass


def track_error(message: str = "") -> None:
    try:
        STATS["errors"] += 1
        _record_event("error")
        logger.warning(f"[STATS] error tracked: {message[:120]}")
    except Exception:
        pass


def track_download(count: int = 1) -> None:
    try:
        STATS["downloads"] += int(count)
    except Exception:
        pass


def track_upload(count: int = 1) -> None:
    try:
        STATS["uploads"] += int(count)
    except Exception:
        pass


# Convenience aliases for legacy code
def track_indexed(count: int = 1) -> None:
    track_file_indexed(count)


def track_skipped(count: int = 1) -> None:
    track_file_skipped(count)


# ============================================================
# SECTION 2 — LIVE SNAPSHOT (used by dashboard)
# ============================================================

def live_snapshot() -> Dict[str, Any]:
    """Compact stats dict for other panels."""
    return {
        "users": len(KNOWN_USERS),
        "searches": STATS["searches"],
        "commands": STATS["commands"],
        "callbacks": STATS["callbacks"],
        "files_sent": STATS["files_sent"],
        "files_indexed": STATS["files_indexed"],
        "errors": STATS["errors"],
        "downloads": STATS["downloads"],
        "uploads": STATS["uploads"],
    }


# ============================================================
# SECTION 3 — SPARKLINE
# ============================================================

_SPARK_CHARS = "▁▂▃▄▅▆▇█"


def _sparkline(samples: Deque[int], width: int = 20) -> str:
    if not samples:
        return "—"
    data = list(samples)[-width:]
    if len(data) < 2:
        return "—"
    lo = min(data)
    hi = max(data)
    span = max(0.001, hi - lo)
    out = []
    for v in data:
        idx = int((v - lo) / span * (len(_SPARK_CHARS) - 1))
        idx = max(0, min(len(_SPARK_CHARS) - 1, idx))
        out.append(_SPARK_CHARS[idx])
    return "".join(out)


def _sample_sparklines() -> None:
    """Compute events in last minute for each category."""
    cutoff = time.time() - 60
    counts = Counter()
    for ts, kind in _recent_events:
        if ts < cutoff:
            continue
        counts[kind] += 1

    _spark_searches.append(counts.get("search", 0))
    _spark_files.append(
        counts.get("file_sent", 0) + counts.get("index", 0)
    )
    _spark_commands.append(counts.get("command", 0))
    _spark_users.append(counts.get("message", 0) + counts.get("callback", 0))


# ============================================================
# SECTION 4 — RATE HELPERS
# ============================================================

def _rate(kind: str, window: float = 300.0) -> float:
    """Return events per minute over the last N seconds."""
    cutoff = time.time() - window
    count = sum(1 for ts, k in _recent_events if ts >= cutoff and k == kind)
    return round(count / (window / 60.0), 2)


# ============================================================
# SECTION 5 — COLOR BAR RENDER
# ============================================================

def _term_bar(count: int, max_count: int, width: int = 8) -> str:
    """Small color bar for a search term's popularity."""
    if max_count <= 0:
        return P.bar(0, "indexing", width=width, show_percent=False)
    pct = min(100.0, (count / max_count) * 100)
    return P.bar(pct, "indexing", width=width, show_percent=False)


# ============================================================
# SECTION 6 — KEYBOARD BUILDERS
# ============================================================

def _nav_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"{F.EMO['refresh']} {F.sc('refresh')}",
                callback_data="adm:page:stats",
            ),
            InlineKeyboardButton(
                f"{F.EMO['chart']} {F.sc('top users')}",
                callback_data="adm:st:view:users",
            ),
        ],
        [
            InlineKeyboardButton(
                f"{F.EMO['trash']} {F.sc('reset stats')}",
                callback_data="adm:st:confirm_reset",
            ),
        ],
        [
            InlineKeyboardButton(
                f"{F.EMO['back']} {F.sc('back')}",
                callback_data="adm:home",
            ),
            InlineKeyboardButton(
                f"{F.EMO['cross']} {F.sc('close')}",
                callback_data="adm:close",
            ),
        ],
    ])


# ============================================================
# SECTION 7 — MAIN BUILDER
# ============================================================

async def build() -> Tuple[str, InlineKeyboardMarkup]:
    _sample_sparklines()

    today = _today()
    today_users = DAILY_USERS.get(today, 0)
    today_searches = DAILY_SEARCHES.get(today, 0)

    # Event rates
    search_rate = _rate("search", 300)
    file_rate = _rate("file_sent", 300)
    cmd_rate = _rate("command", 300)

    # Cache info
    cache_hit_rate = 0.0
    try:
        from utils import cache as C
        ns_list = C.cache.stats()
        total_hits = sum(n.hits for n in ns_list)
        total_miss = sum(n.misses for n in ns_list)
        total_req = total_hits + total_miss
        if total_req > 0:
            cache_hit_rate = (total_hits / total_req) * 100
    except Exception:
        pass

    lines: List[str] = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"{F.EMO['chart']} <b>{F.fb('BOT STATS')}</b>",
        F.DIV,
        "",
    ]

    # Overview
    lines.append(f"{F.EMO['users']} <b>{F.sc('users')}</b>")
    lines.append(f"   Total · <b>{FM.num(len(KNOWN_USERS))}</b>")
    lines.append(f"   Today · <b>{FM.num(today_users)}</b>")
    lines.append("")

    lines.append(f"{F.EMO['search']} <b>{F.sc('searches')}</b>")
    lines.append(f"   Total · <b>{FM.num(STATS['searches'])}</b>")
    lines.append(f"   Today · <b>{FM.num(today_searches)}</b>")
    lines.append(f"   Rate · <b>{search_rate}/min</b>")
    lines.append("")

    lines.append(f"{F.EMO['send']} <b>{F.sc('files sent')}</b>")
    lines.append(f"   Total · <b>{FM.num(STATS['files_sent'])}</b>")
    lines.append(f"   Rate · <b>{file_rate}/min</b>")
    lines.append("")

    lines.append(f"⌨️ <b>{F.sc('commands')}</b>")
    lines.append(f"   Total · <b>{FM.num(STATS['commands'])}</b>")
    lines.append(f"   Rate · <b>{cmd_rate}/min</b>")
    lines.append("")

    lines.append(f"{F.EMO['warn']} <b>{F.sc('errors')}</b> · "
                 f"<b>{FM.num(STATS['errors'])}</b>")
    lines.append("")

    # Cache bar
    lines.append(F.DIV_S)
    lines.append(f"{F.EMO['package']} <b>{F.fb('CACHE')}</b>")
    lines.append(F.DIV_S)
    lines.append(f"{P.bar(cache_hit_rate, 'indexing', width=14)}")
    lines.append(f"Hit rate · <b>{cache_hit_rate:.1f}%</b>")
    lines.append("")

    # Top searches
    lines.append(F.DIV_S)
    lines.append(f"🏆 <b>{F.fb('TOP SEARCHES')}</b>")
    lines.append(F.DIV_S)
    lines.append("")

    top_searches = SEARCH_TERMS.most_common(10)
    if not top_searches:
        lines.append(f"⚪ {F.sc('no searches yet')}")
        lines.append("")
    else:
        max_c = top_searches[0][1]
        for i, (term, count) in enumerate(top_searches, 1):
            bar = _term_bar(count, max_c, width=6)
            lines.append(
                f"<b>{i:02d}.</b> <code>{term[:24]}</code>"
            )
            lines.append(
                f"    {bar} <b>{FM.num(count)}</b>"
            )
        lines.append("")

    # Top commands
    lines.append(F.DIV_S)
    lines.append(f"⌨️ <b>{F.fb('TOP COMMANDS')}</b>")
    lines.append(F.DIV_S)
    lines.append("")

    top_cmds = COMMAND_TERMS.most_common(8)
    if not top_cmds:
        lines.append(f"⚪ {F.sc('no commands yet')}")
        lines.append("")
    else:
        max_c = top_cmds[0][1]
        for i, (cmd, count) in enumerate(top_cmds, 1):
            bar = _term_bar(count, max_c, width=6)
            lines.append(
                f"<b>{i:02d}.</b> <code>{cmd[:20]}</code> "
                f"{bar} <b>{FM.num(count)}</b>"
            )
        lines.append("")

    # 7-day history
    lines.append(F.DIV_S)
    lines.append(f"{F.EMO['cal']} <b>{F.fb('LAST 7 DAYS')}</b>")
    lines.append(F.DIV_S)
    lines.append("")

    today_dt = datetime.utcnow().date()
    for i in range(6, -1, -1):
        day = (today_dt - timedelta(days=i)).strftime("%Y-%m-%d")
        u = DAILY_USERS.get(day, 0)
        s = DAILY_SEARCHES.get(days:=day, 0)
        label = "today" if i == 0 else f"{i}d ago"
        lines.append(
            f"<code>{day}</code> · "
            f"👤 <b>{u}</b> · "
            f"🔎 <b>{s}</b> · "
            f"<i>{label}</i>"
        )
    lines.append("")

    # Sparklines
    lines.append(F.DIV_S)
    lines.append(f"{F.EMO['spark']} <b>{F.fb('LIVE RATES')}</b>")
    lines.append(F.DIV_S)
    lines.append(f"🔎 <code>{_sparkline(_spark_searches, 20)}</code>")
    lines.append(f"📤 <code>{_sparkline(_spark_files, 20)}</code>")
    lines.append(f"⌨️ <code>{_sparkline(_spark_commands, 20)}</code>")
    lines.append("")

    lines.append(f"🕒 <code>{FM.datetime_()}</code>")

    text = "\n".join(lines)[:4000]
    return text, _nav_kb()


# ============================================================
# SECTION 8 — TOP USERS PAGE
# ============================================================

async def build_top_users() -> Tuple[str, InlineKeyboardMarkup]:
    top = USER_SEARCHES.most_common(20)

    lines: List[str] = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"🏆 <b>{F.fb('TOP USERS')}</b>",
        F.DIV,
        "",
        f"📊 Ranked by searches",
        "",
        F.DIV_S,
        "",
    ]

    if not top:
        lines.append(f"⚪ {F.sc('no data yet')}")
    else:
        max_c = top[0][1]
        for i, (uid, count) in enumerate(top, 1):
            bar = _term_bar(count, max_c, width=10)
            last_seen = USER_LAST_SEEN.get(uid, 0)
            age = FM.ago(last_seen) if last_seen else "?"
            cmds = USER_COMMANDS.get(uid, 0)
            lines.append(f"<b>{i:02d}.</b> <code>{uid}</code>")
            lines.append(f"   {bar} <b>{FM.num(count)}</b> searches")
            lines.append(f"   ⌨️ {cmds} cmds · 🕒 {age}")
            lines.append("")

    lines.append(f"🕒 <code>{FM.datetime_()}</code>")

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"{F.EMO['refresh']} {F.sc('refresh')}",
                callback_data="adm:st:view:users",
            ),
            InlineKeyboardButton(
                f"{F.EMO['back']} {F.sc('back')}",
                callback_data="adm:page:stats",
            ),
        ],
        [
            InlineKeyboardButton(
                f"{F.EMO['cross']} {F.sc('close')}",
                callback_data="adm:close",
            ),
        ],
    ])

    return "\n".join(lines)[:4000], kb


# ============================================================
# SECTION 9 — RESET
# ============================================================

async def build_reset_confirm() -> Tuple[str, InlineKeyboardMarkup]:
    text = "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"{F.EMO['warn']} <b>{F.fb('RESET STATS')}</b>",
        F.DIV,
        "",
        f"{F.EMO['warn']} {F.sc('this wipes all counters')}",
        f"{F.EMO['info']} {F.sc('users/searches/commands reset to 0')}",
        f"{F.EMO['info']} {F.sc('known users list is kept')}",
        "",
        F.DIV_S,
    ])

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"🗑️ {F.sc('yes, reset')}",
            callback_data="adm:st:do_reset",
        )],
        [InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('cancel')}",
            callback_data="adm:page:stats",
        )],
    ])
    return text, kb


def do_reset() -> Dict[str, int]:
    """Reset all counters (safe)."""
    old = {k: v for k, v in STATS.items()}
    for k in STATS:
        STATS[k] = 0
    SEARCH_TERMS.clear()
    COMMAND_TERMS.clear()
    DAILY_SEARCHES.clear()
    DAILY_USERS.clear()
    USER_SEARCHES.clear()
    USER_COMMANDS.clear()
    _recent_events.clear()
    _spark_searches.clear()
    _spark_files.clear()
    _spark_commands.clear()
    _spark_users.clear()
    return old


# ============================================================
# SECTION 10 — SNAPSHOT
# ============================================================

def snapshot() -> Dict[str, Any]:
    return {
        "users": len(KNOWN_USERS),
        "searches": STATS["searches"],
        "commands": STATS["commands"],
        "errors": STATS["errors"],
        "cache_users": len(USER_SEARCHES),
    }


# ============================================================
# PUBLIC EXPORTS
# ============================================================

__all__ = [
    # Trackers
    "track_user", "track_search", "track_command", "track_callback",
    "track_message", "track_file_sent", "track_file_indexed",
    "track_file_skipped", "track_error", "track_download", "track_upload",
    "track_indexed", "track_skipped",
    # Builders
    "build", "build_top_users", "build_reset_confirm", "do_reset",
    # Snapshot
    "live_snapshot", "snapshot",
    # Counters (for other modules)
    "STATS", "SEARCH_TERMS", "COMMAND_TERMS",
]
