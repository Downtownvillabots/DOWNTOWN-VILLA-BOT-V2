# ============================================================
# 🏨 DOWNTOWN VILLA — PROGRESS BAR ENGINE
# ============================================================
#
# THE single source of truth for every colored bar in the bot.
#
# Used by:
#   • Admin dashboard       (storage, CPU, RAM, disk)
#   • Indexing panel        (job progress)
#   • Backup panel          (upload progress)
#   • Broadcast panel       (send progress)
#   • OTT panel             (weekly stats)
#   • Premium watch         (series/episode progress)
#   • Missing finder        (scan progress)
#   • Tasks / Live status   (any task with %)
#
# RULES (locked):
# ------------------------------------------------------------
#  STORAGE (mode="storage")
#    0-49   → 🟩 GREEN
#    50-69  → 🟨 YELLOW
#    70-84  → 🟧 ORANGE
#    85-100 → 🟥 RED
#
#  INDEXING (mode="indexing")
#    0-24   → 🟥 RED
#    25-49  → 🟧 ORANGE
#    50-74  → 🟨 YELLOW
#    75-100 → 🟩 GREEN
#
#  UNIVERSAL RULES
#    • ONE color for ALL filled blocks (never mixed)
#    • Unfilled blocks ALWAYS "⬛"
#    • Percent shown at end: " 42%"
#    • Width default: 8 blocks
#
# ============================================================

from __future__ import annotations

from typing import Optional


# ============================================================
# SECTION 1 — CONSTANTS
# ============================================================

FILLED_STORAGE = {
    "green":  "🟩",
    "yellow": "🟨",
    "orange": "🟧",
    "red":    "🟥",
}

FILLED_INDEXING = {
    "red":    "🟥",
    "orange": "🟧",
    "yellow": "🟨",
    "green":  "🟩",
}

EMPTY_BLOCK = "⬛"

DEFAULT_WIDTH = 8
MIN_WIDTH = 3
MAX_WIDTH = 20


# ============================================================
# SECTION 2 — CORE BAR
# ============================================================

def bar(
    percent: float,
    mode: str = "storage",
    width: int = DEFAULT_WIDTH,
    show_percent: bool = True,
) -> str:
    """
    Return a single-color progress bar.

    Args:
        percent:      0–100 (clamped automatically)
        mode:         "storage" | "indexing"
        width:        number of blocks (clamped 3–20)
        show_percent: append " NN%" at end

    Returns:
        "🟩🟩🟩⬛⬛⬛⬛⬛ 38%"

    Example:
        >>> bar(38, "storage")
        "🟩🟩🟩⬛⬛⬛⬛⬛ 38%"

        >>> bar(38, "indexing")
        "🟧🟧🟧⬛⬛⬛⬛⬛ 38%"
    """
    pct = _clamp(percent)
    w = _clamp_width(width)

    filled_count = int(round(w * pct / 100.0))
    filled_count = max(0, min(w, filled_count))
    empty_count = w - filled_count

    color = _pick_color(pct, mode)
    filled = color * filled_count
    empty = EMPTY_BLOCK * empty_count

    result = filled + empty

    if show_percent:
        result += f" {int(round(pct))}%"

    return result


def _clamp(value: float) -> float:
    """Clamp to 0–100, safe on bad input."""
    try:
        v = float(value)
    except (TypeError, ValueError):
        return 0.0
    if v < 0:
        return 0.0
    if v > 100:
        return 100.0
    return v


def _clamp_width(width: int) -> int:
    """Clamp width to safe range."""
    try:
        w = int(width)
    except (TypeError, ValueError):
        return DEFAULT_WIDTH
    return max(MIN_WIDTH, min(MAX_WIDTH, w))


def _pick_color(pct: float, mode: str) -> str:
    """
    Single color for all filled blocks based on percent + mode.
    NEVER mixed within a bar.
    """
    mode = (mode or "storage").lower()

    if mode == "indexing":
        # 0-24 red | 25-49 orange | 50-74 yellow | 75-100 green
        if pct >= 75:
            return FILLED_INDEXING["green"]
        if pct >= 50:
            return FILLED_INDEXING["yellow"]
        if pct >= 25:
            return FILLED_INDEXING["orange"]
        return FILLED_INDEXING["red"]

    # Default: storage
    # 0-49 green | 50-69 yellow | 70-84 orange | 85-100 red
    if pct >= 85:
        return FILLED_STORAGE["red"]
    if pct >= 70:
        return FILLED_STORAGE["orange"]
    if pct >= 50:
        return FILLED_STORAGE["yellow"]
    return FILLED_STORAGE["green"]


# ============================================================
# SECTION 3 — CONVENIENCE WRAPPERS
# ============================================================

def storage_bar(
    used_mb: float,
    total_mb: float = 512.0,
    width: int = DEFAULT_WIDTH,
) -> str:
    """
    Storage bar from MB values.
    Green = healthy (empty) → Red = critical (full).
    """
    try:
        used = float(used_mb)
        total = float(total_mb)
    except (TypeError, ValueError):
        return bar(0, "storage", width)

    if total <= 0:
        return bar(0, "storage", width)

    pct = (used / total) * 100.0
    return bar(pct, "storage", width)


def indexing_bar(
    current: int,
    total: int,
    width: int = DEFAULT_WIDTH,
) -> str:
    """
    Indexing bar from counts.
    Red = just started → Green = done.
    """
    try:
        c = float(current)
        t = float(total)
    except (TypeError, ValueError):
        return bar(0, "indexing", width)

    if t <= 0:
        return bar(0, "indexing", width)

    pct = (c / t) * 100.0
    return bar(pct, "indexing", width)


def backup_bar(
    uploaded: int,
    total: int,
    width: int = DEFAULT_WIDTH,
) -> str:
    """Backup uses indexing mode (more-is-better)."""
    return indexing_bar(uploaded, total, width)


def broadcast_bar(
    sent: int,
    total: int,
    width: int = DEFAULT_WIDTH,
) -> str:
    """Broadcast uses indexing mode."""
    return indexing_bar(sent, total, width)


def task_bar(
    current: int,
    total: int,
    width: int = DEFAULT_WIDTH,
) -> str:
    """Generic task — indexing mode."""
    return indexing_bar(current, total, width)


def premium_bar(
    watched: int,
    total: int,
    width: int = DEFAULT_WIDTH,
) -> str:
    """Premium watch progress — indexing mode."""
    return indexing_bar(watched, total, width)


def ratio_bar(
    value: float,
    maximum: float,
    mode: str = "storage",
    width: int = DEFAULT_WIDTH,
) -> str:
    """
    Generic ratio bar.
    Choose mode based on what full means:
      • storage  → full is BAD (green → red)
      • indexing → full is GOOD (red → green)
    """
    try:
        v = float(value)
        m = float(maximum)
    except (TypeError, ValueError):
        return bar(0, mode, width)

    if m <= 0:
        return bar(0, mode, width)

    pct = (v / m) * 100.0
    return bar(pct, mode, width)


# ============================================================
# SECTION 4 — PERCENT-ONLY HELPER
# ============================================================

def percent(value: float, total: float) -> float:
    """Return clamped 0–100 percent."""
    try:
        v = float(value)
        t = float(total)
    except (TypeError, ValueError):
        return 0.0
    if t <= 0:
        return 0.0
    return _clamp((v / t) * 100.0)


def percent_text(value: float, total: float, digits: int = 1) -> str:
    """Return formatted percent text without a bar."""
    p = percent(value, total)
    return f"{p:.{digits}f}%"


# ============================================================
# SECTION 5 — COLOR-ONLY HELPERS
# ============================================================

def storage_color(pct: float) -> str:
    """Return only the color emoji (no bar)."""
    return _pick_color(_clamp(pct), "storage")


def indexing_color(pct: float) -> str:
    """Return only the color emoji (no bar)."""
    return _pick_color(_clamp(pct), "indexing")


# ============================================================
# SECTION 6 — LABEL + BAR (ready-made line)
# ============================================================

def labeled(
    label: str,
    pct: float,
    mode: str = "storage",
    width: int = DEFAULT_WIDTH,
) -> str:
    """
    Return "LABEL  🟩🟩🟩⬛⬛⬛⬛⬛ 38%"

    Use for dashboards where label + bar sit on one line.
    """
    return f"{label}  {bar(pct, mode, width)}"


def stacked(
    label: str,
    pct: float,
    mode: str = "storage",
    width: int = DEFAULT_WIDTH,
) -> str:
    """
    Return two lines:
      COLOR LABEL · 38.2%
      🟩🟩🟩⬛⬛⬛⬛⬛

    Use for panels where the bar gets its own line.
    """
    color = _pick_color(_clamp(pct), mode)
    line1 = f"{color} {label} · {_clamp(pct):.1f}%"
    line2 = bar(pct, mode, width, show_percent=False)
    return f"{line1}\n{line2}"


# ============================================================
# SECTION 7 — HEALTH BADGE
# ============================================================

def health_badge(pct: float, mode: str = "storage") -> str:
    """
    Return a short health icon based on percent + mode.
    Useful for compact rows.
    """
    pct = _clamp(pct)

    if mode == "indexing":
        if pct >= 75:
            return "🟢"
        if pct >= 50:
            return "🟡"
        if pct >= 25:
            return "🟠"
        return "🔴"

    # storage
    if pct >= 85:
        return "🔴"
    if pct >= 70:
        return "🟠"
    if pct >= 50:
        return "🟡"
    return "🟢"


# ============================================================
# SECTION 8 — SPECIAL FORMATS
# ============================================================

def capacity_line(
    used_mb: float,
    total_mb: float = 512.0,
    width: int = DEFAULT_WIDTH,
) -> str:
    """
    One-line capacity summary for DB pages:

    "💾 320.5 MB / 512 MB  🟩🟩🟩🟩⬛⬛⬛⬛ 62.6%"
    """
    try:
        used = float(used_mb)
        total = float(total_mb)
    except (TypeError, ValueError):
        used, total = 0.0, 512.0

    pct = percent(used, total)
    b = bar(pct, "storage", width, show_percent=False)

    return (
        f"💾 {_human_mb(used)} / {_human_mb(total)}  "
        f"{b} {pct:.1f}%"
    )


def _human_mb(mb: float) -> str:
    """Format MB nicely: 320.5 MB → '320.5 MB'."""
    try:
        v = float(mb)
    except (TypeError, ValueError):
        return "0 MB"

    if v < 1024:
        return f"{v:.1f} MB"

    gb = v / 1024.0
    return f"{gb:.2f} GB"


def progress_line(
    current: int,
    total: int,
    label: str = "progress",
    mode: str = "indexing",
    width: int = DEFAULT_WIDTH,
) -> str:
    """
    "PROGRESS  🟩🟩🟩🟩⬛⬛⬛⬛ 42%   (420/1000)"
    """
    pct = percent(current, total)
    b = bar(pct, mode, width, show_percent=False)

    return (
        f"{label.upper()}  {b} "
        f"{pct:.0f}%   ({current:,}/{total:,})"
    )


# ============================================================
# SECTION 9 — COMPACT SHARD BARS
# ============================================================

def shard_bar(
    index: int,
    used_mb: float,
    total_mb: float = 512.0,
    label: str = "",
) -> str:
    """
    Single-line shard status for admin DB page:

    "🟢 SHARD 01  🟩🟩🟩⬛⬛⬛⬛⬛ 38%  195.2 MB / 512 MB"
    """
    try:
        used = float(used_mb)
        total = float(total_mb)
    except (TypeError, ValueError):
        used, total = 0.0, 512.0

    pct = percent(used, total)
    color = storage_color(pct)
    b = bar(pct, "storage", DEFAULT_WIDTH, show_percent=False)

    name = label or f"SHARD {index:02d}"

    return (
        f"{color} <b>{name}</b>  "
        f"{b} {pct:.1f}%  "
        f"<code>{_human_mb(used)} / {_human_mb(total)}</code>"
    )


# ============================================================
# SECTION 10 — MODULE SELF-CHECK
# ============================================================

def _self_check() -> bool:
    """
    Sanity check — every rule from the spec must pass.
    Called once at import time. Safe to disable.
    """
    ok = True

    # Storage: 40 → green
    if "🟩" not in bar(40, "storage"):
        ok = False

    # Storage: 60 → yellow
    if "🟨" not in bar(60, "storage"):
        ok = False

    # Storage: 75 → orange
    if "🟧" not in bar(75, "storage"):
        ok = False

    # Storage: 90 → red
    if "🟥" not in bar(90, "storage"):
        ok = False

    # Indexing: 20 → red
    if "🟥" not in bar(20, "indexing"):
        ok = False

    # Indexing: 40 → orange
    if "🟧" not in bar(40, "indexing"):
        ok = False

    # Indexing: 60 → yellow
    if "🟨" not in bar(60, "indexing"):
        ok = False

    # Indexing: 75 → green
    if "🟩" not in bar(75, "indexing"):
        ok = False

    # Unfilled always ⬛
    if "⬛" not in bar(0, "storage"):
        ok = False

    # Never mixed (40% storage: only green + black)
    b40 = bar(40, "storage")
    if "🟨" in b40 or "🟧" in b40 or "🟥" in b40:
        ok = False

    return ok


# Run check on import (non-fatal)
try:
    _SELF_CHECK_PASS = _self_check()
except Exception:
    _SELF_CHECK_PASS = False


# ============================================================
# SECTION 11 — PUBLIC EXPORTS
# ============================================================

__all__ = [
    # Core
    "bar",
    "percent",
    "percent_text",
    # Convenience
    "storage_bar",
    "indexing_bar",
    "backup_bar",
    "broadcast_bar",
    "task_bar",
    "premium_bar",
    "ratio_bar",
    # Colors
    "storage_color",
    "indexing_color",
    "health_badge",
    # Layouts
    "labeled",
    "stacked",
    "capacity_line",
    "progress_line",
    "shard_bar",
    # Constants
    "DEFAULT_WIDTH",
    "EMPTY_BLOCK",
    "FILLED_STORAGE",
    "FILLED_INDEXING",
]


# ============================================================
# END OF utils/progress.py
# ============================================================
