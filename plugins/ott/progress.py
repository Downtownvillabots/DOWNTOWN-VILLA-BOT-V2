# ============================================================
# 🏨 DOWNTOWN VILLA — OTT PROGRESS BAR (colored cubes)
# ============================================================
# Color scale (single color per bar, never mixed):
#   0-20%   → 🟥 red
#   20-40%  → 🟧 orange
#   40-60%  → 🟨 yellow
#   60-80%  → 🟩 green
#   80-100% → 🟩 green (fully filled look)
# ============================================================

from __future__ import annotations
from typing import Tuple


_CUBE_EMPTY = "⬛"

_TIERS: Tuple[Tuple[float, str, str], ...] = (
    (20.0,  "🟥", "red"),
    (40.0,  "🟧", "orange"),
    (60.0,  "🟨", "yellow"),
    (80.0,  "🟩", "green"),
    (100.0, "🟩", "green"),
)


def _pick_cube(pct: float) -> Tuple[str, str]:
    try:
        p = float(pct)
    except (TypeError, ValueError):
        p = 0.0
    if p < 0:
        p = 0.0
    if p > 100:
        p = 100.0
    for ub, cube, name in _TIERS:
        if p <= ub:
            return cube, name
    return _TIERS[-1][1], _TIERS[-1][2]


def bar(current: int, total: int, width: int = 10,
        show_percent: bool = True, show_count: bool = False) -> str:
    """
    Build a colored cube bar.

    Examples:
        bar(5, 10)          → "🟨🟨🟨🟨🟨⬛⬛⬛⬛⬛ 50%"
        bar(1, 10, width=8) → "🟥⬛⬛⬛⬛⬛⬛⬛ 10%"
        bar(10, 10)         → "🟩🟩🟩🟩🟩🟩🟩🟩🟩🟩 100%"
    """
    try:
        c = int(current)
        t = int(total)
    except (TypeError, ValueError):
        c, t = 0, 0

    if t <= 0:
        pct = 0.0
        filled = 0
    else:
        pct = min(100.0, (c / t) * 100.0)
        filled = int(round(width * pct / 100.0))

    if filled < 0:
        filled = 0
    if filled > width:
        filled = width

    cube, _ = _pick_cube(pct)
    empty = width - filled
    line = (cube * filled) + (_CUBE_EMPTY * empty)

    if show_percent and show_count:
        return f"{line} {pct:.0f}%  ({c}/{t})"
    if show_percent:
        return f"{line} {pct:.0f}%"
    if show_count:
        return f"{line}  ({c}/{t})"
    return line


def pct_of(current: int, total: int) -> float:
    try:
        c = int(current)
        t = int(total)
    except (TypeError, ValueError):
        return 0.0
    if t <= 0:
        return 0.0
    p = (c / t) * 100.0
    return min(100.0, max(0.0, p))


def color_name(current: int, total: int) -> str:
    _, name = _pick_cube(pct_of(current, total))
    return name


def color_emoji(current: int, total: int) -> str:
    cube, _ = _pick_cube(pct_of(current, total))
    return cube


def header_line(current: int, total: int, width: int = 10) -> str:
    cube, _ = _pick_cube(pct_of(current, total))
    p = pct_of(current, total)
    filled = int(round(width * p / 100.0)) if total > 0 else 0
    filled = max(0, min(width, filled))
    empty = width - filled
    line = (cube * filled) + (_CUBE_EMPTY * empty)
    return f"{line} · {p:.0f}% · {current}/{total}"


__all__ = [
    "bar", "pct_of", "color_name", "color_emoji", "header_line",
]
