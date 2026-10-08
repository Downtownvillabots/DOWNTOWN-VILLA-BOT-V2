# ============================================================
# 🏨 DOWNTOWN VILLA — OTT KEYBOARDS
# ============================================================

from __future__ import annotations
from typing import Any, Dict, List

from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from plugins.ott.config import (
    ALL_LANGS, FREQ_HOURS, FREQ_DAYS, FREQ_MONTH_DAYS,
)


def cb(*parts) -> str:
    return "ott:" + ":".join(str(p) for p in parts)


def _b(lbl: str, cd: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(lbl, callback_data=cd)


def _back_close(back_cb: str) -> List[List[InlineKeyboardButton]]:
    return [[
        _b("⬅️ BACK", back_cb),
        _b("❌ CLOSE", cb("close")),
    ]]


# ═══════════════════════════════════════════════════════════
# HOME
# ═══════════════════════════════════════════════════════════

def kb_home(fav_langs: List[str]) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []
    for code, label in ALL_LANGS:
        if code not in fav_langs:
            continue
        row.append(_b(f"🎬 {label}", cb(f"lang:{code}")))
        if len(row) == 2:
            rows.append(row); row = []
    if row:
        rows.append(row)

    rows.append([_b("🌐 ALL LANGUAGES", cb("lang:all"))])
    rows.append([
        _b("🔄 REFRESH", cb("home")),
        _b("⚙️ SETTINGS", cb("set")),
    ])
    rows.append([_b("❌ CLOSE", cb("close"))])
    return InlineKeyboardMarkup(rows)


def kb_lang(lang: str, counts: List[int]) -> InlineKeyboardMarkup:
    days = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
    rows: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []
    for i in range(7):
        c = counts[i] if i < len(counts) else 0
        lbl = days[i] + (f" ({c})" if c else "")
        row.append(_b(lbl, cb(f"day:{lang}:{i}")))
        if len(row) == 2:
            rows.append(row); row = []
    if row:
        rows.append(row)

    rows.append([
        _b("🔄 REFRESH", cb(f"lang:{lang}")),
        _b("⬅️ BACK", cb("home")),
    ])
    rows.append([_b("❌ CLOSE", cb("close"))])
    return InlineKeyboardMarkup(rows)


def kb_day(lang: str, day_idx: int,
           movies: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    for m in movies[:25]:
        title = str(m.get("title", "?"))[:32]
        rows.append([_b(
            f"🎬 {title}",
            cb(f"mv:{m.get('tmdb_id')}:{lang}:{day_idx}"),
        )])
    if not movies:
        rows.append([_b("⚪ NO MOVIES", cb("noop"))])
    rows.append([
        _b("🔄 REFRESH", cb(f"day:{lang}:{day_idx}")),
        _b("⬅️ BACK", cb(f"lang:{lang}")),
    ])
    rows.append([_b("❌ CLOSE", cb("close"))])
    return InlineKeyboardMarkup(rows)


def kb_movie(lang: str, day_idx: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        _b("⬅️ BACK", cb(f"day:{lang}:{day_idx}")),
        _b("❌ CLOSE", cb("close")),
    ]])


# ═══════════════════════════════════════════════════════════
# SETTINGS MAIN
# ═══════════════════════════════════════════════════════════

def kb_settings(ch: int, gr: int, u_on: bool, p_on: bool,
                fav: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            _b(f"🌐 LANGUAGES ({fav})", cb("fav_langs")),
            _b(f"📢 CHANNELS ({ch})", cb("ch_list")),
        ],
        [
            _b(f"👥 GROUPS ({gr})", cb("gr_list")),
            _b(f"👤 USERS · {'🟢' if u_on else '🔴'}", cb("us")),
        ],
        [_b(f"💎 PREMIUM · {'🟢' if p_on else '🔴'}", cb("pm"))],
        _back_close("home")[0],
    ])


# ═══════════════════════════════════════════════════════════
# FAVORITE LANGUAGES
# ═══════════════════════════════════════════════════════════

def kb_fav_langs(current: List[str]) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []
    for code, label in ALL_LANGS:
        mark = "✅" if code in current else "☐"
        row.append(_b(f"{mark} {label}", cb(f"fav_tog:{code}")))
        if len(row) == 2:
            rows.append(row); row = []
    if row:
        rows.append(row)
    rows.append([
        _b("✅ ALL", cb("fav_all")),
        _b("☐ NONE", cb("fav_none")),
    ])
    rows.extend(_back_close("set"))
    return InlineKeyboardMarkup(rows)


# ═══════════════════════════════════════════════════════════
# CHANNELS LIST
# ═══════════════════════════════════════════════════════════

def kb_ch_list(channels: List[Dict[str, Any]],
                enabled: List[int]) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    for c in channels[:20]:
        cid = int(c.get("chat_id") or 0)
        title = str(c.get("title") or cid)[:28]
        mark = "✅" if cid in enabled else "☐"
        rows.append([_b(f"{mark} 📢 {title}", cb(f"ch:{cid}"))])

    if not channels:
        rows.append([_b("⚪ NO CHANNELS IN BOT DB", cb("noop"))])
        rows.append([_b("➕ GO TO BROADCAST MODULE",
                       cb("ch_open_broadcast"))])
    else:
        rows.append([_b("➕ ADD NEW CHANNEL", cb("ch_add"))])

    rows.append([
        _b("🔄 REFRESH", cb("ch_list")),
        _b("⬅️ BACK", cb("set")),
    ])
    rows.append([_b("❌ CLOSE", cb("close"))])
    return InlineKeyboardMarkup(rows)


def kb_channel(cid: int, ch: Dict[str, Any],
                running: bool) -> InlineKeyboardMarkup:
    freq = ch.get("frequency") or {}
    mode = freq.get("mode") or "off"
    hour = freq.get("hour") or 0
    freq_lbl = ("OFF" if mode == "off"
                else f"{mode.upper()} · {hour:02d}:00")
    langs = ch.get("languages") or []
    lang_lbl = ",".join(x.upper() for x in langs) or "NONE"

    run_lbl = "⏹ STOP UPDATES" if running else "▶️ START UPDATES"

    return InlineKeyboardMarkup([
        [_b(run_lbl, cb(f"ch_run:{cid}"))],
        [
            _b(f"🌐 LANGS · {lang_lbl[:10]}", cb(f"ch_lang:{cid}")),
            _b(f"⏰ {freq_lbl[:14]}", cb(f"ch_freq:{cid}")),
        ],
        [_b("👁 PREVIEW", cb(f"ch_prev:{cid}"))],
        [_b("☐ DISABLE FOR OTT", cb(f"ch_off:{cid}"))],
        _back_close("ch_list")[0],
    ])


def kb_ch_langs(cid: int, current: List[str]) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []
    for code, label in ALL_LANGS:
        mark = "✅" if code in current else "☐"
        row.append(_b(f"{mark} {label}",
                       cb(f"ch_lang_tog:{cid}:{code}")))
        if len(row) == 2:
            rows.append(row); row = []
    if row:
        rows.append(row)
    rows.append([
        _b("✅ ALL", cb(f"ch_lang_all:{cid}")),
        _b("☐ NONE", cb(f"ch_lang_none:{cid}")),
    ])
    rows.extend(_back_close(f"ch:{cid}"))
    return InlineKeyboardMarkup(rows)


def kb_ch_freq(cid: int, mode: str) -> InlineKeyboardMarkup:
    def m(v: str, lbl: str):
        mark = "✅ " if mode == v else ""
        return _b(f"{mark}{lbl}", cb(f"ch_fmode:{cid}:{v}"))
    return InlineKeyboardMarkup([
        [m("off", "🔴 OFF")],
        [m("daily", "📅 DAILY"), m("weekly", "📅 WEEKLY")],
        [m("monthly", "📅 MONTHLY")],
        _back_close(f"ch:{cid}")[0],
    ])


def kb_hours(cid: int, hour: int, prefix: str) -> InlineKeyboardMarkup:
    rows, row = [], []
    for h in FREQ_HOURS:
        mark = "✅ " if h == hour else ""
        row.append(_b(f"{mark}{h:02d}:00", cb(f"{prefix}_fh:{cid}:{h}")))
        if len(row) == 3:
            rows.append(row); row = []
    if row:
        rows.append(row)
    rows.extend(_back_close(f"{prefix}_freq:{cid}"))
    return InlineKeyboardMarkup(rows)


def kb_days(cid: int, day: int, prefix: str) -> InlineKeyboardMarkup:
    rows, row = [], []
    for i, d in enumerate(FREQ_DAYS):
        mark = "✅ " if i == day else ""
        row.append(_b(f"{mark}{d}", cb(f"{prefix}_fd:{cid}:{i}")))
        if len(row) == 3:
            rows.append(row); row = []
    if row:
        rows.append(row)
    rows.extend(_back_close(f"{prefix}_freq:{cid}"))
    return InlineKeyboardMarkup(rows)


def kb_month_days(cid: int, day: int, prefix: str) -> InlineKeyboardMarkup:
    rows, row = [], []
    for d in FREQ_MONTH_DAYS:
        mark = "✅ " if d == day else ""
        row.append(_b(f"{mark}{d}", cb(f"{prefix}_fm:{cid}:{d}")))
        if len(row) == 4:
            rows.append(row); row = []
    if row:
        rows.append(row)
    rows.extend(_back_close(f"{prefix}_freq:{cid}"))
    return InlineKeyboardMarkup(rows)


# ═══════════════════════════════════════════════════════════
# GROUPS LIST (mirror)
# ═══════════════════════════════════════════════════════════

def kb_gr_list(groups: List[Dict[str, Any]],
                enabled: List[int]) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    for g in groups[:20]:
        gid = int(g.get("chat_id") or 0)
        title = str(g.get("title") or gid)[:28]
        mark = "✅" if gid in enabled else "☐"
        rows.append([_b(f"{mark} 👥 {title}", cb(f"gr:{gid}"))])

    if not groups:
        rows.append([_b("⚪ NO GROUPS IN BOT DB", cb("noop"))])
    else:
        rows.append([_b("➕ ADD NEW GROUP", cb("gr_add"))])

    rows.append([
        _b("🔄 REFRESH", cb("gr_list")),
        _b("⬅️ BACK", cb("set")),
    ])
    rows.append([_b("❌ CLOSE", cb("close"))])
    return InlineKeyboardMarkup(rows)


def kb_group(gid: int, gr: Dict[str, Any],
              running: bool) -> InlineKeyboardMarkup:
    freq = gr.get("frequency") or {}
    mode = freq.get("mode") or "off"
    hour = freq.get("hour") or 0
    freq_lbl = ("OFF" if mode == "off"
                else f"{mode.upper()} · {hour:02d}:00")
    langs = gr.get("languages") or []
    lang_lbl = ",".join(x.upper() for x in langs) or "NONE"

    run_lbl = "⏹ STOP UPDATES" if running else "▶️ START UPDATES"

    return InlineKeyboardMarkup([
        [_b(run_lbl, cb(f"gr_run:{gid}"))],
        [
            _b(f"🌐 LANGS · {lang_lbl[:10]}", cb(f"gr_lang:{gid}")),
            _b(f"⏰ {freq_lbl[:14]}", cb(f"gr_freq:{gid}")),
        ],
        [_b("👁 PREVIEW", cb(f"gr_prev:{gid}"))],
        [_b("☐ DISABLE FOR OTT", cb(f"gr_off:{gid}"))],
        _back_close("gr_list")[0],
    ])


def kb_gr_langs(gid: int, current: List[str]) -> InlineKeyboardMarkup:
    rows, row = [], []
    for code, label in ALL_LANGS:
        mark = "✅" if code in current else "☐"
        row.append(_b(f"{mark} {label}",
                       cb(f"gr_lang_tog:{gid}:{code}")))
        if len(row) == 2:
            rows.append(row); row = []
    if row:
        rows.append(row)
    rows.append([
        _b("✅ ALL", cb(f"gr_lang_all:{gid}")),
        _b("☐ NONE", cb(f"gr_lang_none:{gid}")),
    ])
    rows.extend(_back_close(f"gr:{gid}"))
    return InlineKeyboardMarkup(rows)


def kb_gr_freq(gid: int, mode: str) -> InlineKeyboardMarkup:
    def m(v: str, lbl: str):
        mark = "✅ " if mode == v else ""
        return _b(f"{mark}{lbl}", cb(f"gr_fmode:{gid}:{v}"))
    return InlineKeyboardMarkup([
        [m("off", "🔴 OFF")],
        [m("daily", "📅 DAILY"), m("weekly", "📅 WEEKLY")],
        [m("monthly", "📅 MONTHLY")],
        _back_close(f"gr:{gid}")[0],
    ])


def kb_hours_gr(gid: int, hour: int) -> InlineKeyboardMarkup:
    rows, row = [], []
    for h in FREQ_HOURS:
        mark = "✅ " if h == hour else ""
        row.append(_b(f"{mark}{h:02d}:00", cb(f"gr_fh:{gid}:{h}")))
        if len(row) == 3:
            rows.append(row); row = []
    if row:
        rows.append(row)
    rows.extend(_back_close(f"gr_freq:{gid}"))
    return InlineKeyboardMarkup(rows)


def kb_days_gr(gid: int, day: int) -> InlineKeyboardMarkup:
    rows, row = [], []
    for i, d in enumerate(FREQ_DAYS):
        mark = "✅ " if i == day else ""
        row.append(_b(f"{mark}{d}", cb(f"gr_fd:{gid}:{i}")))
        if len(row) == 3:
            rows.append(row); row = []
    if row:
        rows.append(row)
    rows.extend(_back_close(f"gr_freq:{gid}"))
    return InlineKeyboardMarkup(rows)


def kb_month_days_gr(gid: int, day: int) -> InlineKeyboardMarkup:
    rows, row = [], []
    for d in FREQ_MONTH_DAYS:
        mark = "✅ " if d == day else ""
        row.append(_b(f"{mark}{d}", cb(f"gr_fm:{gid}:{d}")))
        if len(row) == 4:
            rows.append(row); row = []
    if row:
        rows.append(row)
    rows.extend(_back_close(f"gr_freq:{gid}"))
    return InlineKeyboardMarkup(rows)


# ═══════════════════════════════════════════════════════════
# USERS / PREMIUM (single config)
# ═══════════════════════════════════════════════════════════

def kb_kind_cfg(cfg: Dict[str, Any], kind: str,
                 total: int) -> InlineKeyboardMarkup:
    running = bool(cfg.get("running"))
    freq = cfg.get("frequency") or {}
    mode = freq.get("mode") or "off"
    hour = freq.get("hour") or 0
    freq_lbl = ("OFF" if mode == "off"
                else f"{mode.upper()} · {hour:02d}:00")
    langs = cfg.get("languages") or []
    lang_lbl = ",".join(x.upper() for x in langs) or "NONE"

    run_lbl = "⏹ STOP UPDATES" if running else "▶️ START UPDATES"

    return InlineKeyboardMarkup([
        [_b(run_lbl, cb(f"{kind}_run"))],
        [
            _b(f"🌐 LANGS · {lang_lbl[:10]}", cb(f"{kind}_lang")),
            _b(f"⏰ {freq_lbl[:14]}", cb(f"{kind}_freq")),
        ],
        [_b("👁 PREVIEW", cb(f"{kind}_prev"))],
        _back_close("set")[0],
    ])


def kb_kind_langs(kind: str, current: List[str]) -> InlineKeyboardMarkup:
    rows, row = [], []
    for code, label in ALL_LANGS:
        mark = "✅" if code in current else "☐"
        row.append(_b(f"{mark} {label}", cb(f"{kind}_lang_tog:{code}")))
        if len(row) == 2:
            rows.append(row); row = []
    if row:
        rows.append(row)
    rows.append([
        _b("✅ ALL", cb(f"{kind}_lang_all")),
        _b("☐ NONE", cb(f"{kind}_lang_none")),
    ])
    rows.extend(_back_close(kind))
    return InlineKeyboardMarkup(rows)


def kb_kind_freq(kind: str, mode: str) -> InlineKeyboardMarkup:
    def m(v: str, lbl: str):
        mark = "✅ " if mode == v else ""
        return _b(f"{mark}{lbl}", cb(f"{kind}_fmode:{v}"))
    return InlineKeyboardMarkup([
        [m("off", "🔴 OFF")],
        [m("daily", "📅 DAILY"), m("weekly", "📅 WEEKLY")],
        [m("monthly", "📅 MONTHLY")],
        _back_close(kind)[0],
    ])


def kb_kind_hours(kind: str, hour: int) -> InlineKeyboardMarkup:
    rows, row = [], []
    for h in FREQ_HOURS:
        mark = "✅ " if h == hour else ""
        row.append(_b(f"{mark}{h:02d}:00", cb(f"{kind}_fh:{h}")))
        if len(row) == 3:
            rows.append(row); row = []
    if row:
        rows.append(row)
    rows.extend(_back_close(f"{kind}_freq"))
    return InlineKeyboardMarkup(rows)


def kb_kind_days(kind: str, day: int) -> InlineKeyboardMarkup:
    rows, row = [], []
    for i, d in enumerate(FREQ_DAYS):
        mark = "✅ " if i == day else ""
        row.append(_b(f"{mark}{d}", cb(f"{kind}_fd:{i}")))
        if len(row) == 3:
            rows.append(row); row = []
    if row:
        rows.append(row)
    rows.extend(_back_close(f"{kind}_freq"))
    return InlineKeyboardMarkup(rows)


def kb_kind_month_days(kind: str, day: int) -> InlineKeyboardMarkup:
    rows, row = [], []
    for d in FREQ_MONTH_DAYS:
        mark = "✅ " if d == day else ""
        row.append(_b(f"{mark}{d}", cb(f"{kind}_fm:{d}")))
        if len(row) == 4:
            rows.append(row); row = []
    if row:
        rows.append(row)
    rows.extend(_back_close(f"{kind}_freq"))
    return InlineKeyboardMarkup(rows)


__all__ = [
    "cb", "kb_home", "kb_lang", "kb_day", "kb_movie",
    "kb_settings", "kb_fav_langs",
    "kb_ch_list", "kb_channel", "kb_ch_langs",
    "kb_ch_freq", "kb_hours", "kb_days", "kb_month_days",
    "kb_gr_list", "kb_group", "kb_gr_langs",
    "kb_gr_freq", "kb_hours_gr", "kb_days_gr", "kb_month_days_gr",
    "kb_kind_cfg", "kb_kind_langs", "kb_kind_freq",
    "kb_kind_hours", "kb_kind_days", "kb_kind_month_days",
]
