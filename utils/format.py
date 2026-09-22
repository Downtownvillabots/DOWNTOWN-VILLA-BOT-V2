# ============================================================
# 🏨 DOWNTOWN VILLA — FORMATTING ENGINE
# ============================================================
#
# THE single source of truth for every number / size / time
# formatting in the bot.
#
# Previously scattered across 10+ files. Now ONE place.
#
# Provides:
#   • size()        → "1.42 GB"       (bytes to human)
#   • size_short()  → "1.4G"           (compact)
#   • bytes_from()  → 1523456789       (parse "1.42 GB" → bytes)
#   • num()         → "1,234,567"      (comma groups)
#   • num_short()   → "1.2M"           (compact)
#   • time_()       → "12:34:56"       (clock)
#   • duration()    → "2d 3h 12m 5s"   (friendly)
#   • duration_s()  → "2d 3h"          (short)
#   • eta()         → "in 12m 30s"     (future)
#   • ago()         → "5m ago"         (past)
#   • date_()       → "22 Sep 2026"    (date only)
#   • datetime_()   → "22 Sep · 14:55" (date+time)
#   • date_iso()    → "2026-09-22"     (ISO)
#
# Every function is:
#   • safe on None / bad input
#   • never raises
#   • deterministic
#   • timezone-aware (IST default, configurable)
#
# ============================================================

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional, Union


# ============================================================
# SECTION 1 — CONSTANTS
# ============================================================

IST = timezone(timedelta(hours=5, minutes=30))

_SIZE_UNITS = ("B", "KB", "MB", "GB", "TB", "PB", "EB")
_SIZE_STEP = 1024.0

_SHORT_SUFFIX = ("", "K", "M", "B", "T", "P", "E")

_MONTHS_SHORT = (
    "Jan", "Feb", "Mar", "Apr", "May", "Jun",
    "Jul", "Aug", "Sep", "Oct", "Nov", "Dec",
)


# ============================================================
# SECTION 2 — FILE SIZE
# ============================================================

def size(value: Union[int, float, None]) -> str:
    """
    Convert bytes to human-readable size.

    >>> size(0)          → "0 B"
    >>> size(1024)       → "1.00 KB"
    >>> size(1523456789) → "1.42 GB"
    >>> size(None)       → "0 B"
    """
    try:
        v = float(value or 0)
    except (TypeError, ValueError):
        return "0 B"

    if v < 0:
        v = 0.0
    if v < 1:
        return "0 B"

    idx = 0
    while v >= _SIZE_STEP and idx < len(_SIZE_UNITS) - 1:
        v /= _SIZE_STEP
        idx += 1

    if idx == 0:
        return f"{int(v)} B"

    return f"{v:.2f} {_SIZE_UNITS[idx]}"


def size_short(value: Union[int, float, None]) -> str:
    """
    Compact size: "1.4G", "500M", "12K".

    >>> size_short(1523456789) → "1.4G"
    >>> size_short(1048576)    → "1.0M"
    """
    try:
        v = float(value or 0)
    except (TypeError, ValueError):
        return "0B"

    if v < 0:
        v = 0.0
    if v < 1:
        return "0B"

    idx = 0
    while v >= _SIZE_STEP and idx < len(_SHORT_SUFFIX) - 1:
        v /= _SIZE_STEP
        idx += 1

    suffix = _SHORT_SUFFIX[idx]

    if idx == 0:
        return f"{int(v)}{suffix}"

    if v >= 100:
        return f"{int(v)}{suffix}"
    return f"{v:.1f}{suffix}"


def bytes_from(text: str) -> int:
    """
    Parse "1.42 GB" → 1523970867 bytes.

    >>> bytes_from("1 GB")     → 1073741824
    >>> bytes_from("500 MB")   → 524288000
    >>> bytes_from("")         → 0
    """
    if not text:
        return 0

    s = str(text).strip().upper()
    if not s:
        return 0

    # Split numeric prefix + unit
    num_part = ""
    unit_part = ""
    for ch in s:
        if ch.isdigit() or ch in ".-":
            if not unit_part:
                num_part += ch
        else:
            unit_part += ch

    try:
        n = float(num_part or 0)
    except (TypeError, ValueError):
        return 0

    unit_part = unit_part.strip()

    multiplier = {
        "B":  1,
        "KB": _SIZE_STEP,
        "MB": _SIZE_STEP ** 2,
        "GB": _SIZE_STEP ** 3,
        "TB": _SIZE_STEP ** 4,
        "PB": _SIZE_STEP ** 5,
        "EB": _SIZE_STEP ** 6,
        "K":  _SIZE_STEP,
        "M":  _SIZE_STEP ** 2,
        "G":  _SIZE_STEP ** 3,
        "T":  _SIZE_STEP ** 4,
        "P":  _SIZE_STEP ** 5,
    }.get(unit_part, 1)

    return int(n * multiplier)


# ============================================================
# SECTION 3 — NUMBERS
# ============================================================

def num(value: Union[int, float, None]) -> str:
    """
    Comma-grouped number.

    >>> num(1234567)     → "1,234,567"
    >>> num(None)        → "0"
    """
    try:
        return f"{int(value or 0):,}"
    except (TypeError, ValueError):
        return "0"


def num_short(value: Union[int, float, None]) -> str:
    """
    Compact number: 1.2M, 45.3K, 999.

    >>> num_short(1234567) → "1.2M"
    >>> num_short(45000)   → "45.0K"
    >>> num_short(999)     → "999"
    """
    try:
        v = float(value or 0)
    except (TypeError, ValueError):
        return "0"

    if v < 0:
        return f"-{num_short(-v)}"

    if v < 1000:
        return str(int(v))

    idx = 0
    while v >= 1000 and idx < len(_SHORT_SUFFIX) - 1:
        v /= 1000.0
        idx += 1

    suffix = _SHORT_SUFFIX[idx]

    if v >= 100:
        return f"{int(v)}{suffix}"
    return f"{v:.1f}{suffix}"


def float_(value: Union[int, float, None], digits: int = 2) -> str:
    """
    Safe float with N digits.

    >>> float_(3.14159, 2)  → "3.14"
    >>> float_(None)        → "0.00"
    """
    try:
        return f"{float(value or 0):.{digits}f}"
    except (TypeError, ValueError):
        return f"{0:.{digits}f}"


def int_(value) -> int:
    """Safe int conversion, never raises."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def pct_(value: Union[int, float, None], digits: int = 1) -> str:
    """
    Percentage string.

    >>> pct_(42.3456)    → "42.3%"
    >>> pct_(None)       → "0.0%"
    """
    try:
        v = float(value or 0)
    except (TypeError, ValueError):
        v = 0.0
    return f"{v:.{digits}f}%"


# ============================================================
# SECTION 4 — DURATION
# ============================================================

def duration(seconds: Union[int, float, None]) -> str:
    """
    Friendly duration: "2d 3h 12m 5s".

    >>> duration(0)      → "0s"
    >>> duration(90)     → "1m 30s"
    >>> duration(93784)  → "1d 2h 3m 4s"
    >>> duration(None)   → "0s"
    """
    try:
        s = int(max(0, float(seconds or 0)))
    except (TypeError, ValueError):
        return "0s"

    if s == 0:
        return "0s"

    days, s = divmod(s, 86400)
    hours, s = divmod(s, 3600)
    mins, s = divmod(s, 60)

    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if mins:
        parts.append(f"{mins}m")
    if s or not parts:
        parts.append(f"{s}s")

    return " ".join(parts)


def duration_short(seconds: Union[int, float, None]) -> str:
    """
    Short duration: "2d 3h", "12m".

    >>> duration_short(93784)  → "1d 2h"
    >>> duration_short(90)     → "1m"
    """
    try:
        s = int(max(0, float(seconds or 0)))
    except (TypeError, ValueError):
        return "0s"

    if s < 60:
        return f"{s}s"

    mins, s = divmod(s, 60)
    if mins < 60:
        return f"{mins}m"

    hours, mins = divmod(mins, 60)
    if hours < 24:
        return f"{hours}h {mins}m"

    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h"


def clock(seconds: Union[int, float, None]) -> str:
    """
    Clock format: "12:34:56" or "34:56".

    >>> clock(3723)   → "01:02:03"
    >>> clock(123)    → "02:03"
    """
    try:
        s = int(max(0, float(seconds or 0)))
    except (TypeError, ValueError):
        return "00:00"

    hours, rem = divmod(s, 3600)
    mins, secs = divmod(rem, 60)

    if hours:
        return f"{hours:02d}:{mins:02d}:{secs:02d}"
    return f"{mins:02d}:{secs:02d}"


# ============================================================
# SECTION 5 — ETA & AGO
# ============================================================

def eta(
    current: Union[int, float, None],
    total: Union[int, float, None],
    speed: Union[int, float, None],
) -> str:
    """
    Estimated time of arrival.

    >>> eta(50, 100, 2)   → "25s"
    >>> eta(0, 100, 0)    → "—"
    """
    try:
        c = float(current or 0)
        t = float(total or 0)
        sp = float(speed or 0)
    except (TypeError, ValueError):
        return "—"

    if sp <= 0 or t <= 0 or c >= t:
        return "—"

    remaining = max(0.0, t - c)
    return duration_short(remaining / sp)


def eta_text(
    current: Union[int, float, None],
    total: Union[int, float, None],
    speed: Union[int, float, None],
) -> str:
    """ETA with "in" prefix."""
    e = eta(current, total, speed)
    return "—" if e == "—" else f"in {e}"


def ago(timestamp: Union[int, float, None]) -> str:
    """
    Relative past time.

    >>> ago(now - 30)   → "30s ago"
    >>> ago(now - 300)  → "5m ago"
    """
    try:
        ts = float(timestamp or 0)
    except (TypeError, ValueError):
        return "?"

    if ts <= 0:
        return "?"

    delta = datetime.now(IST).timestamp() - ts
    if delta < 0:
        return "just now"
    if delta < 60:
        return f"{int(delta)}s ago"
    if delta < 3600:
        return f"{int(delta // 60)}m ago"
    if delta < 86400:
        return f"{int(delta // 3600)}h ago"

    days = int(delta // 86400)
    if days == 1:
        return "yesterday"
    if days < 30:
        return f"{days}d ago"
    if days < 365:
        return f"{days // 30}mo ago"
    return f"{days // 365}y ago"


# ============================================================
# SECTION 6 — DATE / TIME
# ============================================================

def date_(dt: Optional[datetime] = None) -> str:
    """
    Date only: "22 Sep 2026".
    """
    try:
        d = dt or datetime.now(IST)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc).astimezone(IST)
        return f"{d.day:02d} {_MONTHS_SHORT[d.month - 1]} {d.year}"
    except Exception:
        return "?"


def date_short(dt: Optional[datetime] = None) -> str:
    """Date short: "22 Sep"."""
    try:
        d = dt or datetime.now(IST)
        return f"{d.day:02d} {_MONTHS_SHORT[d.month - 1]}"
    except Exception:
        return "?"


def time_(dt: Optional[datetime] = None, seconds: bool = True) -> str:
    """
    Time only: "14:55:32" or "14:55".
    """
    try:
        d = dt or datetime.now(IST)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc).astimezone(IST)
        if seconds:
            return d.strftime("%H:%M:%S")
        return d.strftime("%H:%M")
    except Exception:
        return "?"


def datetime_(dt: Optional[datetime] = None, tz_short: bool = True) -> str:
    """
    Date + time: "22 Sep · 14:55 IST".
    """
    try:
        d = dt or datetime.now(IST)
        if d.tzinfo is None:
            d = d.replace(tzinfo=timezone.utc).astimezone(IST)
        tz = " IST" if tz_short else ""
        return f"{date_short(d)} · {time_(d, seconds=False)}{tz}"
    except Exception:
        return "?"


def datetime_full(dt: Optional[datetime] = None) -> str:
    """Full: "22 Sep 2026 · 14:55:32 IST"."""
    try:
        d = dt or datetime.now(IST)
        return f"{date_(d)} · {time_(d, seconds=True)} IST"
    except Exception:
        return "?"


def date_iso(dt: Optional[datetime] = None) -> str:
    """ISO format: "2026-09-22"."""
    try:
        d = dt or datetime.now(IST)
        return d.strftime("%Y-%m-%d")
    except Exception:
        return "?"


# ============================================================
# SECTION 7 — RATE & SPEED
# ============================================================

def rate(per_second: Union[int, float, None]) -> str:
    """
    Rate string: "1.4/s", "500/s".

    >>> rate(1.42) → "1.4/s"
    >>> rate(500)  → "500.0/s"
    """
    try:
        v = float(per_second or 0)
    except (TypeError, ValueError):
        return "0/s"

    if v < 10:
        return f"{v:.1f}/s"
    if v < 100:
        return f"{int(v)}/s"
    return f"{num_short(v)}/s"


def speed(bytes_per_second: Union[int, float, None]) -> str:
    """
    Byte rate: "2.4 MB/s".

    >>> speed(2411724) → "2.30 MB/s"
    """
    try:
        v = float(bytes_per_second or 0)
    except (TypeError, ValueError):
        return "0 B/s"

    if v < 1:
        return "0 B/s"

    return f"{size(v)}/s"


# ============================================================
# SECTION 8 — SHARD LABELS
# ============================================================

def shard_label(index: int, total: int = 0) -> str:
    """Format a shard label: "SHARD 01" or "SHARD 01/05"."""
    try:
        i = int(index)
    except (TypeError, ValueError):
        return "SHARD ?"

    base = f"SHARD {i:02d}"
    if total > 0:
        return f"{base}/{int(total):02d}"
    return base


# ============================================================
# SECTION 9 — NICE CLIFFS
# ============================================================

def clamp(value: Union[int, float, None],
          low: float = 0.0,
          high: float = 100.0) -> float:
    """Clamp value between low and high."""
    try:
        v = float(value or 0)
    except (TypeError, ValueError):
        return low
    if v < low:
        return low
    if v > high:
        return high
    return v


def safe_div(a: Union[int, float, None],
             b: Union[int, float, None],
             default: float = 0.0) -> float:
    """Division that never raises."""
    try:
        fa = float(a or 0)
        fb = float(b or 0)
    except (TypeError, ValueError):
        return default
    if fb == 0:
        return default
    return fa / fb


# ============================================================
# SECTION 10 — SELF CHECK
# ============================================================

def _self_check() -> bool:
    ok = True

    if size(1024) != "1.00 KB":
        ok = False
    if size(0) != "0 B":
        ok = False
    if num(1234567) != "1,234,567":
        ok = False
    if num_short(1234567) != "1.2M":
        ok = False
    if duration(90) != "1m 30s":
        ok = False
    if clock(3723) != "01:02:03":
        ok = False
    if size(None) != "0 B":
        ok = False
    if num(None) != "0":
        ok = False

    return ok


try:
    _SELF_CHECK_PASS = _self_check()
except Exception:
    _SELF_CHECK_PASS = False


# ============================================================
# SECTION 11 — PUBLIC EXPORTS
# ============================================================

__all__ = [
    # Size
    "size", "size_short", "bytes_from",
    # Numbers
    "num", "num_short", "float_", "int_", "pct_",
    # Duration
    "duration", "duration_short", "clock",
    # ETA / Ago
    "eta", "eta_text", "ago",
    # Date / time
    "date_", "date_short", "time_",
    "datetime_", "datetime_full", "date_iso",
    # Rate / speed
    "rate", "speed",
    # Labels
    "shard_label",
    # Math
    "clamp", "safe_div",
    # Constants
    "IST",
]


# ============================================================
# END OF utils/format.py
# ============================================================
