# ============================================================
# 🏨 DOWNTOWN VILLA — LIVE LOG STREAM (ULTIMATE)
# ============================================================
#
# Live memory log viewer.
#
# Features:
#   • Last N lines from memory ring (from core.logger)
#   • Filter by level (DEBUG/INFO/WARNING/ERROR/CRITICAL)
#   • Filter by logger name
#   • Search across messages
#   • Auto-refresh every 3s
#   • Pagination
#   • Clear logs button
#   • Export as file
#   • Error-only quick view
#   • Sparkline of error rate
#   • Cancel button everywhere
#
# ============================================================

from __future__ import annotations

import asyncio
import io
import logging
import time
from collections import deque, Counter
from typing import Any, Deque, Dict, List, Optional, Tuple

from pyrogram.enums import ParseMode
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from core import config
from utils import fonts as F
from utils import format as FM

logger = logging.getLogger(__name__)


# ============================================================
# SECTION 1 — FILTER STATE
# ============================================================

_filters = {
    "level": "all",   # all | debug | info | warning | error | critical
    "logger": "all",  # all | <logger name>
    "search": "",     # substring
    "page": 0,
    "per_page": 15,
}


def _set_filter(key: str, value: Any) -> None:
    if key in _filters:
        _filters[key] = value


def _reset_filters() -> None:
    _filters.update({
        "level": "all",
        "logger": "all",
        "search": "",
        "page": 0,
    })


# ============================================================
# SECTION 2 — LOG LEVEL ICONS
# ============================================================

def _level_icon(level: str) -> str:
    return {
        "DEBUG":    "🔵",
        "INFO":     "🟢",
        "WARNING":  "🟡",
        "WARN":     "🟡",
        "ERROR":    "🔴",
        "CRITICAL": "💀",
    }.get(str(level).upper(), "⚪")


def _level_color(level: str) -> str:
    return {
        "DEBUG":    "🔵",
        "INFO":     "🟢",
        "WARNING":  "🟡",
        "WARN":     "🟡",
        "ERROR":    "🔴",
        "CRITICAL": "💀",
    }.get(str(level).upper(), "⚪")


# ============================================================
# SECTION 3 — LOG FETCH
# ============================================================

def _get_logs() -> List[Dict[str, Any]]:
    """Fetch logs from the memory ring."""
    try:
        from core import logger as _log
        return list(_log.memory_logs(limit=1000))
    except Exception:
        return []


def _apply_filters(logs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filter by level / logger / search."""
    out = list(logs)

    level = _filters["level"].upper()
    if level != "ALL":
        out = [
            l for l in out
            if str(l.get("level", "")).upper() == level
            or (level == "WARNING" and str(l.get("level", "")).upper() == "WARN")
        ]

    lg = _filters["logger"]
    if lg != "all":
        out = [l for l in out if str(l.get("logger", "")) == lg]

    search = (_filters.get("search") or "").strip().lower()
    if search:
        out = [
            l for l in out
            if search in str(l.get("message", "")).lower()
        ]

    return out


def _known_loggers(logs: List[Dict[str, Any]]) -> List[str]:
    """Return sorted unique logger names."""
    c = Counter(str(l.get("logger", "")) for l in logs)
    return [name for name, _ in c.most_common(12) if name]


# ============================================================
# SECTION 4 — ERROR SPARKLINE
# ============================================================

_spark_errors: Deque[int] = deque(maxlen=30)
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


def _track_error_sparkline(logs: List[Dict[str, Any]]) -> None:
    recent = [
        l for l in logs
        if time.time() - float(l.get("timestamp", 0)) < 60
    ]
    errors = sum(1 for l in recent if str(l.get("level", "")).upper() in ("ERROR", "CRITICAL"))
    _spark_errors.append(errors)


# ============================================================
# SECTION 5 — KEYBOARD BUILDERS
# ============================================================

def _nav_kb() -> InlineKeyboardMarkup:
    def lvl(value: str, icon: str, label: str):
        mark = "✅ " if _filters["level"] == value else ""
        return InlineKeyboardButton(
            f"{mark}{icon} {F.sc(label)}",
            callback_data=f"adm:lg:filter:level:{value}",
        )

    rows = [
        [
            lvl("all", "🌐", "all"),
            lvl("info", "🟢", "info"),
            lvl("warning", "🟡", "warn"),
        ],
        [
            lvl("error", "🔴", "error"),
            lvl("critical", "💀", "critical"),
            lvl("debug", "🔵", "debug"),
        ],
        [
            InlineKeyboardButton(
                f"{F.EMO['refresh']} {F.sc('refresh')}",
                callback_data="adm:lg:refresh",
            ),
            InlineKeyboardButton(
                f"{F.EMO['search']} {F.sc('search')}",
                callback_data="adm:lg:search",
            ),
        ],
        [
            InlineKeyboardButton(
                f"{F.EMO['file']} {F.sc('export')}",
                callback_data="adm:lg:export",
            ),
            InlineKeyboardButton(
                f"{F.EMO['trash']} {F.sc('clear logs')}",
                callback_data="adm:lg:confirm_clear",
            ),
        ],
        [
            InlineKeyboardButton(
                f"{F.EMO['refresh']} {F.sc('reset filters')}",
                callback_data="adm:lg:reset",
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
    ]
    return InlineKeyboardMarkup(rows)


def _pager_kb(total_pages: int) -> Optional[InlineKeyboardMarkup]:
    page = int(_filters["page"])
    rows: List[List[InlineKeyboardButton]] = []

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(
            f"{F.EMO['prev']} {F.sc('prev')}",
            callback_data=f"adm:lg:page:{page - 1}",
        ))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(
            f"{F.sc('next')} {F.EMO['next']}",
            callback_data=f"adm:lg:page:{page + 1}",
        ))

    if nav:
        rows.append(nav)
        return InlineKeyboardMarkup(rows)
    return None


# ============================================================
# SECTION 6 — MAIN BUILDER
# ============================================================

async def build() -> Tuple[str, InlineKeyboardMarkup]:
    logs = _get_logs()
    _track_error_sparkline(logs)

    filtered = _apply_filters(logs)

    # Reverse → newest first
    filtered = list(reversed(filtered))

    per = int(_filters["per_page"])
    total = len(filtered)
    total_pages = max(1, (total + per - 1) // per)
    page = min(int(_filters["page"]), total_pages - 1)
    _filters["page"] = page

    start = page * per
    slice_ = filtered[start:start + per]

    # Level counts
    counts = Counter(str(l.get("level", "?")).upper() for l in logs)

    lines: List[str] = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"📋 <b>{F.fb('LIVE LOG STREAM')}</b>",
        F.DIV,
        "",
        f"{F.EMO['file']} {F.sc('total')} · <b>{len(logs)}</b>",
        f"🔴 errors · <b>{counts.get('ERROR', 0)}</b>",
        f"🟡 warnings · <b>{counts.get('WARNING', 0) + counts.get('WARN', 0)}</b>",
        f"🟢 info · <b>{counts.get('INFO', 0)}</b>",
        "",
        f"{F.EMO['bar']} {F.sc('filters')} · "
        f"level=<code>{_filters['level']}</code> "
        f"logger=<code>{_filters['logger']}</code>",
    ]
    if _filters.get("search"):
        lines.append(f"🔍 {F.sc('search')} · "
                     f"<code>{_filters['search'][:30]}</code>")

    lines += [
        "",
        f"📄 {F.sc('showing')} · "
        f"<b>{start + 1}</b>-<b>{min(total, start + per)}</b> / {total}",
        "",
        F.DIV_S,
        "",
    ]

    if not slice_:
        lines.append(f"⚪ {F.sc('no logs match')}")
        lines.append("")
    else:
        for entry in slice_:
            lines.extend(_render_log_entry(entry))

    # Sparkline
    lines.append(F.DIV_S)
    lines.append(f"{F.EMO['spark']} {F.sc('error rate (last 30m)')}")
    lines.append(F.DIV_S)
    lines.append(f"<code>{_sparkline(_spark_errors, 24)}</code>")
    lines.append("")
    lines.append(f"🕒 <code>{FM.datetime_()}</code>")

    text = "\n".join(lines)[:4000]

    # Build full keyboard
    main_kb = _nav_kb()
    pager = _pager_kb(total_pages)

    if pager is not None:
        # Merge pager above nav
        rows = list(pager.inline_keyboard) + list(main_kb.inline_keyboard)
        return text, InlineKeyboardMarkup(rows)

    return text, main_kb


def _render_log_entry(entry: Dict[str, Any]) -> List[str]:
    """Render one log line as multi-line HTML."""
    out: List[str] = []
    ts = entry.get("time", "??:??:??")
    level = str(entry.get("level", "INFO")).upper()
    name = str(entry.get("logger", ""))[:22]
    msg = str(entry.get("message", ""))
    msg = msg[:200] + "…" if len(msg) > 200 else msg

    icon = _level_icon(level)

    out.append(
        f"<code>{ts}</code> {icon} <b>{level[:4]}</b> "
        f"<code>{name}</code>"
    )
    out.append(f"  {msg}")

    if entry.get("traceback"):
        tb = str(entry["traceback"])[:300]
        out.append(f"  <code>{tb}</code>")

    out.append("")
    return out


# ============================================================
# SECTION 7 — CONFIRM CLEAR
# ============================================================

async def build_clear_confirm() -> Tuple[str, InlineKeyboardMarkup]:
    text = "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"{F.EMO['warn']} <b>{F.fb('CLEAR LOGS')}</b>",
        F.DIV,
        "",
        f"{F.EMO['warn']} {F.sc('this empties the memory ring')}",
        f"{F.EMO['info']} {F.sc('stdout logs are not affected')}",
        f"{F.EMO['info']} {F.sc('Render logs stay intact')}",
        "",
        F.DIV_S,
        f"{F.EMO['spark']} <i>{F.sc('you can still see new logs after')}</i>",
    ])

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"🗑️ {F.sc('yes, clear')}",
            callback_data="adm:lg:do_clear",
        )],
        [InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('cancel')}",
            callback_data="adm:page:logs",
        )],
    ])
    return text, kb


# ============================================================
# SECTION 8 — EXPORT
# ============================================================

async def export_logs() -> Optional[io.BytesIO]:
    """Build a text file with all current logs."""
    logs = _get_logs()
    if not logs:
        return None

    buf = io.StringIO()
    for entry in logs:
        line = (
            f"[{entry.get('time', '?')}] "
            f"{entry.get('level', '?'):8} "
            f"{entry.get('logger', '?'):30} "
            f"{entry.get('message', '')}"
        )
        buf.write(line + "\n")
        if entry.get("traceback"):
            buf.write("  " + entry["traceback"].replace("\n", "\n  ") + "\n")

    data = buf.getvalue().encode("utf-8")
    bio = io.BytesIO(data)
    bio.name = f"downtown_villa_logs_{int(time.time())}.txt"
    return bio


# ============================================================
# SECTION 9 — SNAPSHOT
# ============================================================

def snapshot() -> Dict[str, Any]:
    logs = _get_logs()
    return {
        "total": len(logs),
        "filters": dict(_filters),
    }


# ============================================================
# PUBLIC EXPORTS
# ============================================================

__all__ = [
    "build",
    "build_clear_confirm",
    "export_logs",
    "snapshot",
]
