# ============================================================
# 🏨 DOWNTOWN VILLA — OTT KEYBOARDS
# ============================================================

from __future__ import annotations
from typing import Any, Dict, List

from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from plugins.ott.config import PRIMARY_LANGS


def cb(*parts) -> str:
    return "ott:" + ":".join(str(p) for p in parts)


def _btn(lbl: str, cd: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(lbl, callback_data=cd)


# ═══════════════════════════════════════════════════════════
# HOME — language picker
# ═══════════════════════════════════════════════════════════

def kb_home() -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []
    for code, label in PRIMARY_LANGS:
        row.append(_btn(f"🎬 {label}", cb(f"lang:{code}")))
        if len(row) == 2:
            rows.append(row); row = []
    if row:
        rows.append(row)

    rows.append([
        _btn("🌐 ALL LANGUAGES", cb("lang:all")),
        _btn("🔥 THIS WEEK", cb("lang:all")),
    ])
    rows.append([
        _btn("🔄 REFRESH", cb("home")),
        _btn("❌ CLOSE", cb("close")),
    ])
    return InlineKeyboardMarkup(rows)


# ═══════════════════════════════════════════════════════════
# LANGUAGE — day picker (Mon-Sun)
# ═══════════════════════════════════════════════════════════

def kb_language(lang: str, counts: List[int]) -> InlineKeyboardMarkup:
    days = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
    rows: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []

    for i in range(7):
        c = counts[i] if i < len(counts) else 0
        lbl = days[i] + (f" ({c})" if c else "")
        row.append(_btn(lbl, cb(f"day:{lang}:{i}")))
        if len(row) == 2:
            rows.append(row); row = []
    if row:
        rows.append(row)

    rows.append([
        _btn("🔄 REFRESH", cb(f"lang:{lang}")),
        _btn("⬅️ BACK", cb("home")),
    ])
    rows.append([_btn("❌ CLOSE", cb("close"))])
    return InlineKeyboardMarkup(rows)


# ═══════════════════════════════════════════════════════════
# DAY — movie list
# ═══════════════════════════════════════════════════════════

def kb_day(lang: str, day_idx: int,
           movies: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    for m in movies[:25]:
        title = str(m.get("title", "?"))[:32]
        rows.append([_btn(
            f"🎬 {title}",
            cb(f"mv:{m.get('tmdb_id')}:{lang}"),
        )])

    if not movies:
        rows.append([_btn("⚪ NO MOVIES", cb("noop"))])

    rows.append([
        _btn("🔄 REFRESH", cb(f"day:{lang}:{day_idx}")),
        _btn("⬅️ BACK", cb(f"lang:{lang}")),
    ])
    rows.append([_btn("❌ CLOSE", cb("close"))])
    return InlineKeyboardMarkup(rows)


# ═══════════════════════════════════════════════════════════
# MOVIE CARD — back + close only
# ═══════════════════════════════════════════════════════════

def kb_movie(lang: str, day_idx: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            _btn("⬅️ BACK", cb(f"day:{lang}:{day_idx}")),
            _btn("❌ CLOSE", cb("close")),
        ],
    ])


__all__ = ["cb", "kb_home", "kb_language", "kb_day", "kb_movie"]
