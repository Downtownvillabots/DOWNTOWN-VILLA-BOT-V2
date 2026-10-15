# ============================================================
# 🏨 DOWNTOWN VILLA — INDEXING CONTROL CENTER (THE ONE COMMAND)
# ============================================================
#
# ONE COMMAND: /index
#
# ============================================================

from __future__ import annotations

import asyncio
from html import escape as html_escape
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from core import config
from utils import fonts as F
from utils import format as FM
from utils import progress as P

logger = logging.getLogger(__name__)


PFX = "idx"
AUTO_REFRESH_SEC = 5.0


# ============================================================
# AUTH
# ============================================================

def _is_admin(uid) -> bool:
    try:
        return int(uid) in [int(a) for a in config.ADMINS]
    except Exception:
        return False


# ============================================================
# CONFIG STEP STATE
# ============================================================

_steps: Dict[int, Dict[str, Any]] = {}
STEP_TTL = 900.0


def _get_step(uid: int) -> Optional[Dict[str, Any]]:
    s = _steps.get(int(uid))
    if not s:
        return None
    if time.time() > s.get("expires", 0):
        _steps.pop(int(uid), None)
        return None
    return s


def _new_step(uid: int, step: str, **data) -> None:
    _steps[int(uid)] = {
        "step": step,
        "expires": time.time() + STEP_TTL,
        "data": dict(data),
    }


def _update_step(uid: int, **data) -> None:
    s = _steps.get(uid)
    if not s:
        return
    s["data"].update(data)
    s["expires"] = time.time() + STEP_TTL


def _set_step(uid: int, step: str, **data) -> None:
    s = _steps.get(uid)
    if not s:
        return
    s["step"] = step
    s["data"].update(data)
    s["expires"] = time.time() + STEP_TTL


def _drop_step(uid: int) -> None:
    _steps.pop(int(uid), None)


# ============================================================
# PANEL REGISTRY
# ============================================================

_panels: Dict[int, Dict[str, Any]] = {}

_live_intervals: Dict[int, int] = {}
LIVE_OPTIONS = [3, 5, 10, 30]
DEFAULT_LIVE = 3

# Job id whose report has already been dismissed (so /index
# returns to idle home after tapping ✅ Done)
_dismissed_job_id: Optional[str] = None


def _register_panel(msg_id: int, chat_id: int, page: str, text: str) -> None:
    _panels[msg_id] = {
        "chat_id": chat_id, "page": page,
        "last_text": text, "created": time.time(),
    }


def _unregister_panel(msg_id: int) -> None:
    _panels.pop(msg_id, None)


# ============================================================
# MAIN PANEL (dispatcher)
# ============================================================

async def _build_main_panel() -> Tuple[str, InlineKeyboardMarkup]:
    global _dismissed_job_id

    w = {}
    try:
        from plugins.indexing import worker as WK
        w = WK.status()
    except Exception:
        pass

    running = bool(w.get("running"))
    paused = bool(w.get("paused"))
    processed = int(w.get("processed", 0) or 0)
    job_id = w.get("job_id")

    if running or paused:
        return await _build_live_panel(w)

    if processed > 0 and job_id and job_id != _dismissed_job_id:
        return await _build_report_panel(w)

    return await _build_idle_panel(w)


# ============================================================
# LIVE PANEL
# ============================================================

async def _build_live_panel(w: Dict[str, Any]) -> Tuple[str, InlineKeyboardMarkup]:
    auto_mode = await _get_auto_mode()

    running = bool(w.get("running"))
    paused = bool(w.get("paused"))

    if running and not paused:
        s_icon, s_text = "🟢", "RUNNING"
    else:
        s_icon, s_text = "🟡", "PAUSED"

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"📚 <b>{F.fb('INDEXING CONTROL CENTER')}</b>",
        F.DIV, "",
        f"{s_icon} <b>{F.sc(s_text)}</b>",
        f"🎯 {F.sc('auto mode')} · "
        f"{'🟢 ' + F.sc('on') if auto_mode else '🔴 ' + F.sc('off')}",
        "",
    ]
    lines.extend(await _render_live_progress(w))
    lines += [F.DIV_S, f"🕒 <code>{FM.datetime_()}</code>"]

    rows: List[List[InlineKeyboardButton]] = []

    if paused:
        rows.append([
            InlineKeyboardButton(
                f"{F.EMO['play']} {F.sc('resume')}",
                callback_data=f"{PFX}:resume",
            ),
            InlineKeyboardButton(
                f"{F.EMO['cross']} {F.sc('cancel job')}",
                callback_data=f"{PFX}:cancel_confirm",
            ),
        ])
    else:
        rows.append([
            InlineKeyboardButton(
                f"{F.EMO['pause']} {F.sc('pause')}",
                callback_data=f"{PFX}:pause",
            ),
            InlineKeyboardButton(
                f"{F.EMO['cross']} {F.sc('cancel job')}",
                callback_data=f"{PFX}:cancel_confirm",
            ),
        ])

    cur_iv = _live_intervals.get(0, DEFAULT_LIVE)
    rows.append([InlineKeyboardButton(
        f"🔄 {F.sc('refresh rate')}",
        callback_data=f"{PFX}:noop",
    )])
    rows.append([InlineKeyboardButton(
        f"{'✅ ' if iv == cur_iv else ''}{iv}s",
        callback_data=f"{PFX}:live:{iv}",
    ) for iv in LIVE_OPTIONS])

    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['refresh']} {F.sc('refresh')}",
            callback_data=f"{PFX}:refresh",
        ),
        InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('close')}",
            callback_data=f"{PFX}:close",
        ),
    ])

    return "\n".join(lines)[:4000], InlineKeyboardMarkup(rows)


async def _render_live_progress(w: Dict[str, Any]) -> List[str]:
    scanned = int(w.get("scanned_ids", 0))
    total = int(w.get("total_messages", 0))
    current_id = int(w.get("current_message_id", 0))
    saved = int(w.get("saved", 0))
    dup = int(w.get("duplicate_id", 0))
    checked = int(w.get("dups_checked", 0))
    skipped = int(w.get("skipped_no_media", 0))
    failed = int(w.get("failed", 0))
    movies = int(w.get("movies", 0))
    series = int(w.get("series", 0))
    processed = int(w.get("processed", 0))
    eta_text = "paused" if w.get("paused") else w.get("eta_text", "—")

    started = w.get("started_at") or 0
    elapsed_str = "—"
    if started:
        elapsed_str = FM.duration_short(time.time() - started)

    pct = min(100.0, scanned / max(1, total) * 100) if total else 0.0

    bar = P.bar(pct, "indexing", width=14, show_percent=False)
    last_error = str(w.get("last_error") or w.get("fetch_error") or "")

    return [
        F.DIV_S,
        f"{F.EMO['chart']} <b>{F.fb('LIVE PROGRESS')}</b>",
        F.DIV_S, "",
        f"<code>{bar}</code> {pct:.0f}%",
        f"📍 {F.sc('message id')} · <code>{current_id:,}</code> / "
        f"<code>{total:,}</code>",
        "",
        f"📡 {F.sc('channel')} · "
        f"<code>{str(w.get('channel_title', '?'))[:30]}</code>",
        f"🎬 {F.sc('mode')} · <b>{str(w.get('mode', '?'))}</b>",
        f"⬇️ {F.sc('direction')} · <b>{str(w.get('direction', '?'))}</b>",
        f"⏱️ {F.sc('elapsed')} · <b>{elapsed_str}</b>",
        "",
        f"📥 {F.sc('scanned')} · <b>{FM.num(scanned)}</b>",
        f"🔢 {F.sc('processed')} · <b>{FM.num(processed)}</b>",
        "",
        F.DIV_S,
        f"✅ {F.sc('saved')} · <b>{FM.num(saved)}</b>",
        f"♻️ {F.sc('duplicate')} · <b>{FM.num(dup)}</b>",
        f"🔍 {F.sc('checked')} · <b>{FM.num(checked)}</b>",
        f"🚫 {F.sc('no media')} · <b>{FM.num(skipped)}</b>",
        f"🪪 {F.sc('no file id')} · "
        f"<b>{FM.num(int(w.get('skipped_no_file_id', 0)))}</b>",
        f"❌ {F.sc('failed')} · <b>{FM.num(failed)}</b>",
        "",
        f"🎬 {F.sc('movies')} · <b>{FM.num(movies)}</b>",
        f"📺 {F.sc('series')} · <b>{FM.num(series)}</b>",
        "",
        f"⚡ {F.sc('scan speed')} · <b>{w.get('speed', 0):.1f} IDs/s</b>",
        f"⏱️ {F.sc('eta')} · <b>{eta_text}</b>",
        *([f"⚠️ {F.sc('last error')} · "
           f"<code>{html_escape(last_error[:180])}</code>"] if last_error else []),
        "",
    ]


# ============================================================
# REPORT PANEL
# ============================================================

async def _build_report_panel(w: Dict[str, Any]) -> Tuple[str, InlineKeyboardMarkup]:
    saved = int(w.get("saved", 0))
    dup = int(w.get("duplicate_id", 0))
    checked = int(w.get("dups_checked", 0))
    skipped = int(w.get("skipped_no_media", 0))
    failed = int(w.get("failed", 0))
    movies = int(w.get("movies", 0))
    series = int(w.get("series", 0))
    processed = int(w.get("processed", 0))
    scanned = int(w.get("scanned_ids", 0))

    started = w.get("started_at") or 0
    finished = w.get("finished_at") or time.time()
    duration = 0
    if started:
        duration = int(finished - started)

    bar = P.bar(100, "indexing", width=14, show_percent=False)

    total_files = saved + dup + failed

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"✅ <b>{F.fb('INDEXING REPORT')}</b>",
        F.DIV, "",
        f"<code>{bar}</code> 100%",
        "",
        f"📡 {F.sc('channel')} · "
        f"<code>{str(w.get('channel_title', '?'))[:40]}</code>",
        f"🎬 {F.sc('mode')} · <b>{str(w.get('mode', '?'))}</b>",
        f"⬇️ {F.sc('direction')} · <b>{str(w.get('direction', '?'))}</b>",
        f"⏱️ {F.sc('duration')} · <b>{FM.duration_short(duration)}</b>",
        "",
        F.DIV_S,
        f"📥 {F.sc('scanned')} · <b>{FM.num(scanned)}</b>",
        f"🔢 {F.sc('processed')} · <b>{FM.num(processed)}</b>",
        "",
        F.DIV_S,
        f"✅ {F.sc('saved')} · <b>{FM.num(saved)}</b>",
        f"♻️ {F.sc('duplicate')} · <b>{FM.num(dup)}</b>",
        f"🔍 {F.sc('checked')} · <b>{FM.num(checked)}</b>",
        f"🚫 {F.sc('no media')} · <b>{FM.num(skipped)}</b>",
        f"❌ {F.sc('failed')} · <b>{FM.num(failed)}</b>",
        "",
        f"📁 {F.sc('total files')} · <b>{FM.num(total_files)}</b>",
        "",
        F.DIV_S,
        f"🎬 {F.sc('movies')} · <b>{FM.num(movies)}</b>",
        f"📺 {F.sc('series')} · <b>{FM.num(series)}</b>",
        "",
        F.DIV,
        f"🕒 <code>{FM.datetime_()}</code>",
    ]

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"✅ {F.sc('done — back to home')}",
            callback_data=f"{PFX}:dismiss_report",
        )],
        [InlineKeyboardButton(
            f"📤 {F.sc('save report')}",
            callback_data=f"{PFX}:save_report",
        )],
        [InlineKeyboardButton(
            f"{F.EMO['play']} {F.sc('start new job')}",
            callback_data=f"{PFX}:start",
        )],
        [
            InlineKeyboardButton(
                f"🧾 {F.sc('history')}",
                callback_data=f"{PFX}:history",
            ),
            InlineKeyboardButton(
                f"{F.EMO['cross']} {F.sc('close')}",
                callback_data=f"{PFX}:close",
            ),
        ],
    ])

    return "\n".join(lines)[:4000], kb


# ============================================================
# IDLE PANEL
# ============================================================

async def _build_idle_panel(w: Dict[str, Any]) -> Tuple[str, InlineKeyboardMarkup]:
    auto_mode = await _get_auto_mode()

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"📚 <b>{F.fb('INDEXING CONTROL CENTER')}</b>",
        F.DIV, "",
        f"⚪ <b>{F.sc('idle')}</b>",
        f"🎯 {F.sc('auto mode')} · "
        f"{'🟢 ' + F.sc('on') if auto_mode else '🔴 ' + F.sc('off')}",
        "",
        F.DIV_S,
        f"📌 {F.sc('no active job')}",
        f"📌 {F.sc('tap start new job to begin')}",
        "",
        f"🕒 <code>{FM.datetime_()}</code>",
    ]

    rows: List[List[InlineKeyboardButton]] = [
        [InlineKeyboardButton(
            f"{F.EMO['play']} {F.sc('start new job')}",
            callback_data=f"{PFX}:start",
        )],
        [
            InlineKeyboardButton(
                f"📢 {F.sc('channels')}",
                callback_data=f"{PFX}:channels",
            ),
            InlineKeyboardButton(
                f"🧾 {F.sc('history')}",
                callback_data=f"{PFX}:history",
            ),
        ],
        [
            InlineKeyboardButton(
                f"🎯 {F.sc('auto')} · {'🟢' if auto_mode else '🔴'}",
                callback_data=f"{PFX}:toggle_auto",
            ),
            InlineKeyboardButton(
                f"🧹 {F.sc('duplicates')}",
                callback_data=f"{PFX}:duplicates",
            ),
        ],
        [
            InlineKeyboardButton(
                f"{F.EMO['refresh']} {F.sc('refresh')}",
                callback_data=f"{PFX}:refresh",
            ),
            InlineKeyboardButton(
                f"{F.EMO['close']} {F.sc('close')}",
                callback_data=f"{PFX}:close",
            ),
        ],
    ]

    return "\n".join(lines)[:4000], InlineKeyboardMarkup(rows)


# ============================================================
# STEP 1/6 — CHANNEL
# ============================================================

async def _build_step_channel() -> Tuple[str, InlineKeyboardMarkup]:
    try:
        from plugins.indexing import backward as BW
        channels = await BW.list_registered_channels()
    except Exception:
        channels = []

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"📢 <b>{F.fb('STEP 1/6 — CHANNEL')}</b>",
        F.DIV, "",
        f"{F.EMO['info']} {F.sc('pick the channel to index')}",
        "",
    ]

    rows: List[List[InlineKeyboardButton]] = []

    if not channels:
        lines.append(f"{F.EMO['warn']} {F.sc('no channels registered yet')}")
        lines.append("")
        lines.append(f"📌 {F.sc('add bot as admin to a channel')}")
        lines.append(f"📌 {F.sc('or forward a message from a channel')}")
    else:
        for ch in channels[:8]:
            icon = "🟢" if ch.get("enabled") else "🔴"
            title = str(ch.get("title", "?"))[:32]
            rows.append([InlineKeyboardButton(
                f"{icon} {title}",
                callback_data=f"{PFX}:pick_ch:{ch['chat_id']}",
            )])

    rows.append([
        InlineKeyboardButton(
            f"📎 {F.sc('forward media')}",
            callback_data=f"{PFX}:wait_forward",
        ),
    ])
    rows.append([
        InlineKeyboardButton(
            f"📢 {F.sc('manage channels')}",
            callback_data=f"{PFX}:channels",
        ),
    ])
    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('cancel')}",
            callback_data=f"{PFX}:cancel_config",
        ),
    ])

    return "\n".join(lines)[:4000], InlineKeyboardMarkup(rows)


# ============================================================
# STEP 2/6 — MODE
# ============================================================

async def _build_step_mode() -> Tuple[str, InlineKeyboardMarkup]:
    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"🎬 <b>{F.fb('STEP 2/6 — MODE')}</b>",
        F.DIV, "",
        f"{F.EMO['info']} {F.sc('what to index')}",
        "",
    ]
    rows = [
        [
            InlineKeyboardButton(
                f"🎬 {F.sc('movies')}",
                callback_data=f"{PFX}:pick_mode:movies",
            ),
            InlineKeyboardButton(
                f"📺 {F.sc('series')}",
                callback_data=f"{PFX}:pick_mode:series",
            ),
        ],
        [InlineKeyboardButton(
            f"🎬📺 {F.sc('both')}",
            callback_data=f"{PFX}:pick_mode:both",
        )],
        [
            InlineKeyboardButton(
                f"{F.EMO['back']} {F.sc('back')}",
                callback_data=f"{PFX}:start",
            ),
            InlineKeyboardButton(
                f"{F.EMO['cross']} {F.sc('cancel')}",
                callback_data=f"{PFX}:cancel_config",
            ),
        ],
    ]
    return "\n".join(lines)[:4000], InlineKeyboardMarkup(rows)


# ============================================================
# STEP 3/6 — DIRECTION
# ============================================================

async def _build_step_direction() -> Tuple[str, InlineKeyboardMarkup]:
    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"⬇️ <b>{F.fb('STEP 3/6 — DIRECTION')}</b>",
        F.DIV, "",
        f"⬇️ {F.sc('forward')}  — oldest → newest",
        f"⬆️ {F.sc('backward')} — newest → oldest",
        "",
        F.DIV_S,
        f"💡 {F.sc('backward is faster for recent files')}",
    ]
    rows = [
        [InlineKeyboardButton(
            f"⬇️ {F.sc('forward')}",
            callback_data=f"{PFX}:pick_dir:forward",
        )],
        [InlineKeyboardButton(
            f"⬆️ {F.sc('backward')}",
            callback_data=f"{PFX}:pick_dir:backward",
        )],
        [
            InlineKeyboardButton(
                f"{F.EMO['back']} {F.sc('back')}",
                callback_data=f"{PFX}:back_mode",
            ),
            InlineKeyboardButton(
                f"{F.EMO['cross']} {F.sc('cancel')}",
                callback_data=f"{PFX}:cancel_config",
            ),
        ],
    ]
    return "\n".join(lines)[:4000], InlineKeyboardMarkup(rows)


# ============================================================
# STEP 4/6 — RANGE
# ============================================================

async def _build_step_range() -> Tuple[str, InlineKeyboardMarkup]:
    from plugins.indexing.worker import MAX_PROBE_ID

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"📍 <b>{F.fb('STEP 4/6 — RANGE')}</b>",
        F.DIV, "",
        f"{F.EMO['info']} {F.sc('where to begin scanning')}",
        "",
        f"📦 {F.sc('full scan')}  — scan the full configured message ID range",
        f"📍 {F.sc('from first')} — start at msg id 1",
        f"📍 {F.sc('from last')}  — scan backward from ID {MAX_PROBE_ID}",
        f"✏️ {F.sc('custom')}     — enter a specific msg id",
        "",
        F.DIV_S,
        f"💡 {F.sc('full scan checks every message ID up to the configured limit')}",
        f"📌 INDEXING_MAX_ID · <code>{MAX_PROBE_ID}</code>",
    ]
    rows = [
        [InlineKeyboardButton(
            f"📦 {F.sc('FULL SCAN — EVERY FILE')}",
            callback_data=f"{PFX}:pick_range:full",
        )],
        [
            InlineKeyboardButton(
                f"📍 {F.sc('from first')}",
                callback_data=f"{PFX}:pick_range:first",
            ),
            InlineKeyboardButton(
                f"📍 {F.sc('from last')}",
                callback_data=f"{PFX}:pick_range:last",
            ),
        ],
        [InlineKeyboardButton(
            f"✏️ {F.sc('custom msg id')}",
            callback_data=f"{PFX}:pick_range:custom",
        )],
        [
            InlineKeyboardButton(
                f"{F.EMO['back']} {F.sc('back')}",
                callback_data=f"{PFX}:back_dir",
            ),
            InlineKeyboardButton(
                f"{F.EMO['cross']} {F.sc('cancel')}",
                callback_data=f"{PFX}:cancel_config",
            ),
        ],
    ]
    return "\n".join(lines)[:4000], InlineKeyboardMarkup(rows)


# ============================================================
# STEP 5/6 — METADATA SOURCE
# ============================================================

async def _build_step_metadata_source(uid: int) -> Tuple[str, InlineKeyboardMarkup]:
    s = _get_step(uid)
    data = s.get("data", {}) if s else {}
    current = str(data.get("metadata_source", "both"))

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"📄 <b>{F.fb('STEP 5/6 — METADATA SOURCE')}</b>",
        F.DIV, "",
        f"{F.EMO['info']} {F.sc('where to read file metadata from')}",
        "",
        f"📄 {F.sc('caption only')}   — read caption text",
        f"📝 {F.sc('filename only')} — read file name",
        f"📄📝 {F.sc('both')}          — merge (recommended)",
        "",
        F.DIV_S,
        f"📌 {F.sc('both: filename first, caption fills gaps')}",
        "",
        f"🎯 {F.sc('current')} · <b>{current}</b>",
    ]

    def _mark(v): return "✅ " if current == v else ""

    rows = [
        [InlineKeyboardButton(
            f"{_mark('caption')}📄 {F.sc('caption only')}",
            callback_data=f"{PFX}:set_meta_src:caption",
        )],
        [InlineKeyboardButton(
            f"{_mark('filename')}📝 {F.sc('filename only')}",
            callback_data=f"{PFX}:set_meta_src:filename",
        )],
        [InlineKeyboardButton(
            f"{_mark('both')}📄📝 {F.sc('both (recommended)')}",
            callback_data=f"{PFX}:set_meta_src:both",
        )],
        [
            InlineKeyboardButton(
                f"{F.EMO['back']} {F.sc('back')}",
                callback_data=f"{PFX}:back_range",
            ),
            InlineKeyboardButton(
                f"{F.EMO['cross']} {F.sc('cancel')}",
                callback_data=f"{PFX}:cancel_config",
            ),
        ],
    ]
    return "\n".join(lines)[:4000], InlineKeyboardMarkup(rows)


# ============================================================
# STEP 6/6 — ADVANCED
# ============================================================

async def _build_step_advanced(uid: int) -> Tuple[str, InlineKeyboardMarkup]:
    s = _get_step(uid)
    data = s.get("data", {}) if s else {}

    batch = int(data.get("batch_size", 100))
    conc = int(data.get("concurrency", 20))
    delay = float(data.get("delay", 0.3))
    auto_pause = bool(data.get("auto_pause", True))
    meta_src = str(data.get("metadata_source", "both"))

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"⚙️ <b>{F.fb('STEP 6/6 — ADVANCED')}</b>",
        F.DIV, "",
        f"📦 {F.sc('batch')} · <b>{batch}</b>",
        f"⚡ {F.sc('concurrency')} · <b>{conc}</b>",
        f"⏱️ {F.sc('delay')} · <b>{delay}s</b>",
        f"📄 {F.sc('metadata')} · <b>{meta_src}</b>",
        f"🧹 {F.sc('skip same file_id')} · 🟢",
        f"🛡️ {F.sc('auto-pause flood')} · "
        f"{'🟢' if auto_pause else '🔴'}",
        "",
        F.DIV_S,
        f"📌 {F.sc('every file imported except same file_id')}",
    ]

    rows = []

    batch_row = []
    for n in (25, 50, 100):
        mark = "✅ " if batch == n else ""
        batch_row.append(InlineKeyboardButton(
            f"{mark}{n}",
            callback_data=f"{PFX}:set_batch:{n}",
        ))
    rows.append(batch_row)

    conc_row = []
    for n in (5, 10, 20, 50):
        mark = "✅ " if conc == n else ""
        conc_row.append(InlineKeyboardButton(
            f"{mark}{n}",
            callback_data=f"{PFX}:set_conc:{n}",
        ))
    rows.append(conc_row)

    delay_row = []
    for d in (0.0, 0.3, 0.5, 1.0):
        mark = "✅ " if abs(delay - d) < 0.01 else ""
        label = f"{mark}{int(d)}s" if d == int(d) else f"{mark}{d}s"
        delay_row.append(InlineKeyboardButton(
            label,
            callback_data=f"{PFX}:set_delay:{d}",
        ))
    rows.append(delay_row)

    rows.append([InlineKeyboardButton(
        f"{'🟢' if auto_pause else '🔴'} {F.sc('auto-pause')}",
        callback_data=f"{PFX}:toggle_autopause",
    )])

    rows.append([
        InlineKeyboardButton(
            f"📄 {F.sc('metadata source')} · {meta_src}",
            callback_data=f"{PFX}:back_meta_src",
        ),
    ])

    rows.append([InlineKeyboardButton(
        f"💾 {F.sc('save as default')}",
        callback_data=f"{PFX}:save_default",
    )])
    rows.append([InlineKeyboardButton(
        f"▶️ {F.sc('review & start')}",
        callback_data=f"{PFX}:confirm",
    )])
    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data=f"{PFX}:back_meta_src",
        ),
        InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('cancel')}",
            callback_data=f"{PFX}:cancel_config",
        ),
    ])

    return "\n".join(lines)[:4000], InlineKeyboardMarkup(rows)


# ============================================================
# CONFIRM PANEL
# ============================================================

async def _build_confirm(uid: int) -> Tuple[str, InlineKeyboardMarkup]:
    s = _get_step(uid)
    if not s:
        return await _build_main_panel()
    data = s.get("data", {})

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"✅ <b>{F.fb('REVIEW & START')}</b>",
        F.DIV, "",
        f"📢 {F.sc('channel')} · <code>{data.get('channel_id', '?')}</code>",
        f"🎬 {F.sc('mode')} · <b>{data.get('mode', '?')}</b>",
        f"⬇️ {F.sc('direction')} · <b>{data.get('direction', '?')}</b>",
        f"📍 {F.sc('range')} · <b>{data.get('range', '?')}</b>",
    ]

    if data.get("range") == "full":
        lines.append(f"   📦 {F.sc('FULL SCAN — full configured ID range')}")
    elif data.get("range") == "custom":
        lines.append(f"   📌 {F.sc('start at')} · "
                     f"<code>{data.get('start_msg_id', '?')}</code>")

    lines += [
        f"📄 {F.sc('metadata')} · "
        f"<b>{data.get('metadata_source', 'both')}</b>",
        "",
        F.DIV_S,
        f"📦 {F.sc('batch')} · <b>{data.get('batch_size', 100)}</b>",
        f"⚡ {F.sc('conc')} · <b>{data.get('concurrency', 20)}</b>",
        f"⏱️ {F.sc('delay')} · <b>{data.get('delay', 0.3)}s</b>",
        f"🧹 {F.sc('skip same file_id')} · 🟢",
        "",
        F.DIV_S,
        f"{F.EMO['spark']} <b>{F.sc('ready to start')}</b>",
    ]

    rows = [
        [InlineKeyboardButton(
            f"▶️ {F.sc('start now')}",
            callback_data=f"{PFX}:do_start",
        )],
        [
            InlineKeyboardButton(
                f"{F.EMO['back']} {F.sc('back')}",
                callback_data=f"{PFX}:back_adv",
            ),
            InlineKeyboardButton(
                f"{F.EMO['cross']} {F.sc('cancel')}",
                callback_data=f"{PFX}:cancel_config",
            ),
        ],
    ]

    return "\n".join(lines)[:4000], InlineKeyboardMarkup(rows)


# ============================================================
# HISTORY
# ============================================================

async def _build_history() -> Tuple[str, InlineKeyboardMarkup]:
    try:
        from plugins.indexing import state as ST
        jobs = await ST.list_recent(15)
    except Exception:
        jobs = []

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"🧾 <b>{F.fb('INDEXING HISTORY')}</b>",
        F.DIV, "",
    ]
    if not jobs:
        lines.append(f"⚪ {F.sc('no jobs yet')}")
    else:
        for h in jobs:
            status = str(h.get("status", "?"))
            icon = {
                "running": "🟢", "paused": "🟡",
                "completed": "✅", "stopped": "🛑",
                "error": "❌", "cancelled": "⛔",
            }.get(status, "⚪")
            jid = str(h.get("job_id", "?"))[:32]
            stats = h.get("stats", {})
            lines.append(f"{icon} <code>{jid}</code>")
            lines.append(
                f"   ✅ <b>{FM.num(stats.get('saved', 0))}</b> · "
                f"⏭️ <b>{FM.num(stats.get('duplicate_id', 0))}</b> · "
                f"❌ <b>{FM.num(stats.get('failed', 0))}</b>"
            )
            lines.append("")

    rows = [
        [InlineKeyboardButton(
            f"🗑️ {F.sc('clear history')}",
            callback_data=f"{PFX}:clear_history",
        )],
        [
            InlineKeyboardButton(
                f"{F.EMO['refresh']} {F.sc('refresh')}",
                callback_data=f"{PFX}:history",
            ),
            InlineKeyboardButton(
                f"{F.EMO['back']} {F.sc('back')}",
                callback_data=f"{PFX}:back",
            ),
        ],
        [InlineKeyboardButton(
            f"{F.EMO['close']} {F.sc('close')}",
            callback_data=f"{PFX}:close",
        )],
    ]
    return "\n".join(lines)[:4000], InlineKeyboardMarkup(rows)


# ============================================================
# DATABASES
# ============================================================

async def _build_databases() -> Tuple[str, InlineKeyboardMarkup]:
    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"🗄️ <b>{F.fb('DATABASES')}</b>",
        F.DIV, "",
    ]
    try:
        from database import db_registry

        snap = None
        if hasattr(db_registry, "snapshot"):
            try:
                snap = await db_registry.snapshot()
            except TypeError:
                snap = db_registry.snapshot()
            except Exception as e:
                logger.debug(f"[INDEX] snapshot(): {e}")

        if not snap and hasattr(db_registry, "media_entries"):
            try:
                entries = list(db_registry.media_entries())
                lines.append(
                    f"🎬 <b>media</b> · "
                    f"{len(entries)} shard(s) online"
                )
            except Exception as e:
                lines.append(f"❌ <code>{str(e)[:60]}</code>")

        if snap and isinstance(snap, dict):
            for pool_name, info in (snap.get("pools") or {}).items():
                icon = {"system": "⚙️", "user": "👤",
                        "media": "🎬", "backup": "💾"}.get(pool_name, "📦")
                lines.append(
                    f"{icon} <b>{F.sc(pool_name)}</b> · "
                    f"{info.get('online', 0)}/{info.get('total', 0)} · "
                    f"{FM.size(info.get('total_used_mb', 0) * 1024 * 1024)}"
                )
    except Exception as e:
        lines.append(f"❌ <code>{str(e)[:60]}</code>")

    rows = [[
        InlineKeyboardButton(
            f"{F.EMO['refresh']} {F.sc('refresh')}",
            callback_data=f"{PFX}:databases",
        ),
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data=f"{PFX}:back",
        ),
    ], [InlineKeyboardButton(
        f"{F.EMO['close']} {F.sc('close')}",
        callback_data=f"{PFX}:close",
    )]]
    return "\n".join(lines)[:4000], InlineKeyboardMarkup(rows)


# ============================================================
# DUPLICATES
# ============================================================

async def _build_duplicates() -> Tuple[str, InlineKeyboardMarkup]:
    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"🧹 <b>{F.fb('DUPLICATE CONTROL')}</b>",
        F.DIV, "",
        f"{F.EMO['info']} {F.sc('duplicates = same file_id only')}",
        "",
        F.DIV_S,
        f"✅ {F.sc('import every file')}",
        f"⏭️ {F.sc('skip only if file_id matches exactly')}",
        f"🚫 {F.sc('never skip for missing metadata')}",
    ]
    rows = [[
        InlineKeyboardButton(
            f"{F.EMO['refresh']} {F.sc('refresh')}",
            callback_data=f"{PFX}:duplicates",
        ),
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data=f"{PFX}:back",
        ),
    ], [InlineKeyboardButton(
        f"{F.EMO['close']} {F.sc('close')}",
        callback_data=f"{PFX}:close",
    )]]
    return "\n".join(lines)[:4000], InlineKeyboardMarkup(rows)


# ============================================================
# AUTO MODE
# ============================================================

async def _get_auto_mode() -> bool:
    try:
        from plugins.indexing import auto as A
        return await A.is_auto_enabled()
    except Exception:
        return True


async def _set_auto_mode(value: bool) -> bool:
    try:
        from plugins.indexing import auto as A
        return await A.set_auto_enabled(value)
    except Exception:
        return False


# ============================================================
# COMMAND
# ============================================================

@Client.on_message(
    filters.command(["index", "indexing"]) & filters.private,
    group=-8200,
)
async def cmd_index(client: Client, message: Message):
    if not message.from_user or not _is_admin(message.from_user.id):
        return await message.reply_text(
            f"{F.EMO['cross']} <b>{F.fb('ACCESS DENIED')}</b>",
            parse_mode=ParseMode.HTML,
        )

    text, kb = await _build_main_panel()
    sent = await message.reply_text(
        text, reply_markup=kb,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )
    _register_panel(sent.id, sent.chat.id, "main", text)
    _ensure_auto_refresh()


# ============================================================
# ROUTER
# ============================================================

@Client.on_callback_query(
    filters.regex(rf"^{PFX}:"),
    group=-8200,
)
async def router_handler(client: Client, q: CallbackQuery):
    global _dismissed_job_id

    if not q.from_user or not _is_admin(q.from_user.id):
        return await q.answer("❌ Admin only", show_alert=True)

    parts = str(q.data).split(":")
    action = parts[1] if len(parts) > 1 else ""
    arg = parts[2] if len(parts) > 2 else ""
    uid = q.from_user.id

    try:
        # ── MAIN ──
        if action in ("back", "refresh"):
            text, kb = await _build_main_panel()
            await _safe_edit(q, text, kb)
            _register_panel(q.message.id, q.message.chat.id, "main", text)
            return await q.answer()

        # ── CHANNELS ──
        if action == "channels":
            from plugins.indexing import backward as BW
            return await BW.open_channel_manager(client, q)

        # ── START FLOW ──
        if action == "start":
            _drop_step(uid)
            _new_step(uid, "channel")
            text, kb = await _build_step_channel()
            await _safe_edit(q, text, kb)
            return await q.answer()

        if action == "start_ch":
            try:
                cid = int(arg)
            except ValueError:
                return await q.answer("❌ Invalid", show_alert=True)
            _drop_step(uid)
            _new_step(uid, "mode", channel_id=cid)
            text, kb = await _build_step_mode()
            await _safe_edit(q, text, kb)
            return await q.answer()

        if action == "wait_forward":
            _new_step(uid, "channel_forward")
            text = "\n".join([
                f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                f"📎 <b>{F.fb('FORWARD A MESSAGE')}</b>",
                F.DIV, "",
                f"📌 {F.sc('forward any media from the source channel')}",
            ])
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"{F.EMO['cross']} {F.sc('cancel')}",
                    callback_data=f"{PFX}:cancel_config",
                ),
            ]])
            await _safe_edit(q, text, kb)
            return await q.answer()

        if action == "pick_ch":
            _update_step(uid, channel_id=int(arg))
            text, kb = await _build_step_mode()
            await _safe_edit(q, text, kb)
            return await q.answer()

        if action == "back_mode":
            text, kb = await _build_step_mode()
            await _safe_edit(q, text, kb)
            return await q.answer()

        if action == "pick_mode":
            _update_step(uid, mode=arg)
            text, kb = await _build_step_direction()
            await _safe_edit(q, text, kb)
            return await q.answer()

        if action == "back_dir":
            text, kb = await _build_step_direction()
            await _safe_edit(q, text, kb)
            return await q.answer()

        if action == "pick_dir":
            _update_step(uid, direction=arg)
            text, kb = await _build_step_range()
            await _safe_edit(q, text, kb)
            return await q.answer()

        if action == "back_range":
            text, kb = await _build_step_range()
            await _safe_edit(q, text, kb)
            return await q.answer()

        if action == "pick_range":
            if arg == "custom":
                _update_step(uid, range="custom")
                text = "\n".join([
                    f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                    f"✏️ <b>{F.fb('CUSTOM MESSAGE ID')}</b>",
                    F.DIV, "",
                    f"📌 {F.sc('send the message id as text')}",
                    f"📌 {F.sc('example')} · <code>5000</code>",
                ])
                kb = InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        f"{F.EMO['cross']} {F.sc('cancel')}",
                        callback_data=f"{PFX}:cancel_config",
                    ),
                ]])
                await _safe_edit(q, text, kb)
                return await q.answer()

            if arg == "full":
                _update_step(uid,
                             range="full",
                             direction="forward",
                             start_msg_id=1)
                text, kb = await _build_step_metadata_source(uid)
                await _safe_edit(q, text, kb)
                return await q.answer("📦 Full scan")

            if arg == "first":
                _update_step(uid, range=arg, direction="forward")
            elif arg == "last":
                _update_step(uid, range=arg, direction="backward")
            else:
                _update_step(uid, range=arg)
            text, kb = await _build_step_metadata_source(uid)
            await _safe_edit(q, text, kb)
            return await q.answer()

        if action == "back_meta_src":
            text, kb = await _build_step_metadata_source(uid)
            await _safe_edit(q, text, kb)
            return await q.answer()

        if action == "set_meta_src":
            _update_step(uid, metadata_source=arg)
            text, kb = await _build_step_advanced(uid)
            await _safe_edit(q, text, kb)
            return await q.answer(f"✅ {arg}")

        if action == "back_adv":
            text, kb = await _build_step_advanced(uid)
            await _safe_edit(q, text, kb)
            return await q.answer()

        if action == "set_batch":
            _update_step(uid, batch_size=int(arg))
            text, kb = await _build_step_advanced(uid)
            await _safe_edit(q, text, kb)
            return await q.answer()

        if action == "set_conc":
            _update_step(uid, concurrency=int(arg))
            text, kb = await _build_step_advanced(uid)
            await _safe_edit(q, text, kb)
            return await q.answer()

        if action == "set_delay":
            _update_step(uid, delay=float(arg))
            text, kb = await _build_step_advanced(uid)
            await _safe_edit(q, text, kb)
            return await q.answer()

        if action == "toggle_skipdup":
            _update_step(uid, skip_duplicate=True)
            text, kb = await _build_step_advanced(uid)
            await _safe_edit(q, text, kb)
            return await q.answer(
                "Same file_id entries are always skipped.",
                show_alert=True,
            )

        if action == "toggle_autopause":
            s = _get_step(uid)
            cur = s.get("data", {}).get("auto_pause", True) if s else True
            _update_step(uid, auto_pause=not cur)
            text, kb = await _build_step_advanced(uid)
            await _safe_edit(q, text, kb)
            return await q.answer("🔄")

        if action == "save_default":
            s = _get_step(uid)
            if s:
                ok = await _save_default_config(s.get("data", {}))
                return await q.answer(
                    "💾 Saved" if ok else "❌ Save failed",
                    show_alert=not ok,
                )
            return await q.answer("⚠️ No session")

        # ── CONFIRM ──
        if action == "confirm":
            text, kb = await _build_confirm(uid)
            await _safe_edit(q, text, kb)
            return await q.answer()

        if action == "do_start":
            s = _get_step(uid)
            if not s:
                return await q.answer("⚠️ Session expired", show_alert=True)
            data = s.get("data", {})
            if not data.get("channel_id"):
                return await q.answer("⚠️ Missing channel", show_alert=True)
            _drop_step(uid)
            try:
                from plugins.indexing import worker as WK
                ok = await WK.start_worker(
                    channel_id=int(data["channel_id"]),
                    mode=str(data.get("mode", "both")),
                    direction=str(data.get("direction", "backward")),
                    start_msg_id=data.get("start_msg_id"),
                    range_mode=str(data.get("range", "last")),
                    metadata_source=str(data.get("metadata_source", "both")),
                    batch_size=int(data.get("batch_size", 100)),
                    concurrency=int(data.get("concurrency", 20)),
                    delay=float(data.get("delay", 0.3)),
                    skip_duplicate=True,
                    auto_pause=bool(data.get("auto_pause", True)),
                    owner=uid,
                )
                await q.answer("▶️ Started" if ok else "⚠️ Already running")
            except Exception as e:
                logger.exception(f"[INDEX] start: {e}")
                await q.answer(f"❌ {type(e).__name__}", show_alert=True)
                return

            _dismissed_job_id = None

            text, kb = await _build_main_panel()
            await _safe_edit(q, text, kb)
            _ensure_auto_refresh()
            return

        if action == "cancel_config":
            _drop_step(uid)
            text, kb = await _build_main_panel()
            await _safe_edit(q, text, kb)
            return await q.answer("❌ Cancelled")

        # ── WORKER CONTROLS ──
        if action == "pause":
            try:
                from plugins.indexing import worker as WK
                ok = WK.pause_worker()
                await q.answer("⏸️" if ok else "⚠️")
            except Exception:
                pass
            text, kb = await _build_main_panel()
            await _safe_edit(q, text, kb)
            return

        if action == "resume":
            try:
                from plugins.indexing import worker as WK
                ok = WK.resume_worker()
                await q.answer("▶️" if ok else "⚠️")
            except Exception:
                pass
            text, kb = await _build_main_panel()
            await _safe_edit(q, text, kb)
            return

        # ── LIVE REFRESH RATE ──
        if action == "live":
            try:
                iv = int(arg)
            except ValueError:
                iv = DEFAULT_LIVE
            _live_intervals[q.message.chat.id] = iv
            await q.answer(f"🔄 {iv}s")
            text, kb = await _build_main_panel()
            await _safe_edit(q, text, kb)
            _register_panel(q.message.id, q.message.chat.id, "main", text)
            return

        if action == "noop":
            return await q.answer()

        # ── DISMISS REPORT ──
        if action == "dismiss_report":
            try:
                from plugins.indexing import worker as WK
                w = WK.status()
                _dismissed_job_id = w.get("job_id")
            except Exception:
                _dismissed_job_id = None
            text, kb = await _build_main_panel()
            await _safe_edit(q, text, kb)
            _register_panel(q.message.id, q.message.chat.id, "main", text)
            return await q.answer("✅ Done")

        # ── CANCEL CONFIRM ──
        if action == "cancel_confirm":
            text = "\n".join([
                f"{F.EMO['warn']} <b>{F.fb('CANCEL JOB?')}</b>",
                F.DIV, "",
                f"{F.EMO['warn']} {F.sc('this stops the indexing job')}",
                f"{F.EMO['info']} {F.sc('files already saved are kept')}",
                "",
                f"📌 {F.sc('continue?')}",
            ])
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    f"🛑 {F.sc('yes, cancel')}",
                    callback_data=f"{PFX}:cancel_do",
                )],
                [InlineKeyboardButton(
                    f"{F.EMO['back']} {F.sc('no, keep running')}",
                    callback_data=f"{PFX}:back",
                )],
            ])
            await _safe_edit(q, text, kb)
            return await q.answer()

        # ── SAVE REPORT AS MESSAGE ──
        if action == "save_report":
            try:
                from plugins.indexing import worker as WK
                w = WK.status()
            except Exception:
                w = {}

            saved = int(w.get("saved", 0))
            dup = int(w.get("duplicate_id", 0))
            checked = int(w.get("dups_checked", 0))
            skipped = int(w.get("skipped_no_media", 0))
            failed = int(w.get("failed", 0))
            movies = int(w.get("movies", 0))
            series = int(w.get("series", 0))
            processed = int(w.get("processed", 0))
            scanned = int(w.get("scanned_ids", 0))

            started = w.get("started_at") or 0
            finished = w.get("finished_at") or time.time()
            duration = 0
            if started:
                duration = int(finished - started)

            bar = P.bar(100, "indexing", width=14, show_percent=False)

            total_files = saved + dup + failed

            report_lines = [
                f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                f"✅ <b>{F.fb('INDEXING REPORT')}</b>",
                F.DIV, "",
                f"<code>{bar}</code> 100%",
                "",
                f"📡 {F.sc('channel')} · "
                f"<code>{str(w.get('channel_title', '?'))[:40]}</code>",
                f"🎬 {F.sc('mode')} · <b>{str(w.get('mode', '?'))}</b>",
                f"⬇️ {F.sc('direction')} · "
                f"<b>{str(w.get('direction', '?'))}</b>",
                f"⏱️ {F.sc('duration')} · "
                f"<b>{FM.duration_short(duration)}</b>",
                "",
                F.DIV_S,
                f"📥 {F.sc('scanned')} · <b>{FM.num(scanned)}</b>",
                f"🔢 {F.sc('processed')} · <b>{FM.num(processed)}</b>",
                "",
                F.DIV_S,
                f"✅ {F.sc('saved')} · <b>{FM.num(saved)}</b>",
                f"♻️ {F.sc('duplicate')} · <b>{FM.num(dup)}</b>",
                f"🔍 {F.sc('checked')} · <b>{FM.num(checked)}</b>",
                f"🚫 {F.sc('no media')} · <b>{FM.num(skipped)}</b>",
                f"❌ {F.sc('failed')} · <b>{FM.num(failed)}</b>",
                "",
                f"📁 {F.sc('total files')} · <b>{FM.num(total_files)}</b>",
                "",
                F.DIV_S,
                f"🎬 {F.sc('movies')} · <b>{FM.num(movies)}</b>",
                f"📺 {F.sc('series')} · <b>{FM.num(series)}</b>",
                "",
                F.DIV,
                f"🕒 <code>{FM.datetime_()}</code>",
            ]

            try:
                await client.send_message(
                    chat_id=q.message.chat.id,
                    text="\n".join(report_lines),
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
                await q.answer("📤 Report sent")
            except Exception as e:
                logger.exception(f"[INDEX] save_report: {e}")
                await q.answer(
                    f"❌ {type(e).__name__}",
                    show_alert=True,
                )
            return

        if action == "cancel_do":
            try:
                from plugins.indexing import worker as WK
                await WK.stop_worker()
                await q.answer("🛑 Cancelling…")
            except Exception as e:
                await q.answer(f"❌ {type(e).__name__}", show_alert=True)
                return

            try:
                from plugins.indexing import worker as WK
                for _ in range(10):
                    if not WK.is_running():
                        break
                    await asyncio.sleep(0.5)
            except Exception:
                pass

            text, kb = await _build_report_panel(_safe_worker_status())
            await _safe_edit(q, text, kb)
            _register_panel(q.message.id, q.message.chat.id, "main", text)
            return

        if action == "stop":
            try:
                from plugins.indexing import worker as WK
                ok = await WK.stop_worker()
                await q.answer("⏹️ Stopping" if ok else "⚠️")
            except Exception:
                pass
            text, kb = await _build_main_panel()
            await _safe_edit(q, text, kb)
            return

        if action == "history":
            text, kb = await _build_history()
            await _safe_edit(q, text, kb)
            return await q.answer()

        if action == "databases":
            text, kb = await _build_databases()
            await _safe_edit(q, text, kb)
            return await q.answer()

        if action == "duplicates":
            text, kb = await _build_duplicates()
            await _safe_edit(q, text, kb)
            return await q.answer()

        if action == "clear_history":
            try:
                from plugins.indexing import state as ST
                n = await ST.clear_completed()
                await q.answer(f"🗑️ Cleared {n}")
            except Exception:
                await q.answer("❌")
            text, kb = await _build_history()
            await _safe_edit(q, text, kb)
            return

        if action == "toggle_auto":
            cur = await _get_auto_mode()
            await _set_auto_mode(not cur)
            await q.answer("🟢 ON" if not cur else "🔴 OFF")
            text, kb = await _build_main_panel()
            await _safe_edit(q, text, kb)
            return

        if action == "reset":
            text = "\n".join([
                f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                f"🗑️ <b>{F.fb('CLEAR INDEXING HISTORY')}</b>",
                F.DIV, "",
                f"{F.EMO['warn']} {F.sc('clears job history only')}",
                f"{F.EMO['info']} {F.sc('indexed files are NOT removed')}",
            ])
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    f"🗑️ {F.sc('yes, clear')}",
                    callback_data=f"{PFX}:do_reset",
                )],
                [InlineKeyboardButton(
                    f"{F.EMO['back']} {F.sc('cancel')}",
                    callback_data=f"{PFX}:back",
                )],
            ])
            await _safe_edit(q, text, kb)
            return await q.answer()

        if action == "do_reset":
            try:
                from plugins.indexing import state as ST
                n = await ST.clear_all()
                await q.answer(f"🗑️ Cleared {n}")
            except Exception:
                await q.answer("❌")
            text, kb = await _build_main_panel()
            await _safe_edit(q, text, kb)
            return

        if action == "close":
            _unregister_panel(q.message.id)
            try:
                await q.message.delete()
            except Exception:
                pass
            return await q.answer("Closed")

        await q.answer("❓ Unknown", show_alert=True)

    except Exception as e:
        logger.exception(f"[INDEX] router: {e}")
        try:
            await q.answer(f"❌ {type(e).__name__}", show_alert=True)
        except Exception:
            pass


# ============================================================
# TEXT INPUT
# ============================================================

@Client.on_message(
    filters.private & filters.text & ~filters.regex(r"^/"),
    group=-8190,
)
async def indexing_text_input(client: Client, message: Message):
    if not message.from_user or not _is_admin(message.from_user.id):
        return

    s = _steps.get(message.from_user.id)
    if not s:
        return

    data = s.get("data", {})
    if data.get("range") != "custom":
        return

    text = (message.text or "").strip()
    if not text.isdigit():
        await message.reply_text(
            f"{F.EMO['cross']} {F.sc('send a numeric message id')}",
            parse_mode=ParseMode.HTML,
        )
        try:
            message.stop_propagation()
        except Exception:
            pass
        return

    _update_step(message.from_user.id, start_msg_id=int(text))

    txt, kb = await _build_step_metadata_source(message.from_user.id)
    await message.reply_text(
        txt, reply_markup=kb,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )

    try:
        message.stop_propagation()
    except Exception:
        pass


# ============================================================
# SAVE DEFAULT
# ============================================================

_DEFAULT_KEYS = (
    "mode",
    "metadata_source",
    "batch_size",
    "concurrency",
    "delay",
    "skip_duplicate",
    "auto_pause",
)


async def _save_default_config(data: Dict[str, Any]) -> bool:
    try:
        from database import db_registry
        db = db_registry.get_system_db()
        if db is None:
            return False

        clean = {k: data[k] for k in _DEFAULT_KEYS if k in data}
        clean["skip_duplicate"] = True
        clean["updated_at"] = datetime.utcnow()

        await db["bot_settings"].update_one(
            {"_id": "indexing_default"},
            {"$set": clean},
            upsert=True,
        )
        logger.info(f"[INDEX] default saved: {list(clean.keys())}")
        return True
    except Exception as e:
        logger.exception(f"[INDEX] save_default FAILED: {e}")
        return False


# ============================================================
# AUTO REFRESH
# ============================================================

_refresh_task: Optional[asyncio.Task] = None


def _ensure_auto_refresh() -> None:
    global _refresh_task
    if _refresh_task and not _refresh_task.done():
        return
    try:
        loop = asyncio.get_running_loop()
        _refresh_task = loop.create_task(_auto_refresh_loop())
        logger.info("[INDEX] auto-refresh loop started")
    except RuntimeError:
        pass


async def _auto_refresh_loop() -> None:
    last_refresh: Dict[int, float] = {}

    while True:
        try:
            await asyncio.sleep(1.0)
            if not _panels:
                continue

            from core.client import client as C
            if C is None:
                continue

            now = time.time()

            for msg_id, panel in list(_panels.items()):
                if panel.get("page") not in ("main", "live"):
                    continue

                chat_id = panel["chat_id"]
                iv = _live_intervals.get(chat_id, DEFAULT_LIVE)

                if now - last_refresh.get(msg_id, 0) < iv:
                    continue
                last_refresh[msg_id] = now

                try:
                    text, kb = await _build_main_panel()
                    if text == panel.get("last_text"):
                        continue

                    await C.edit_message_text(
                        chat_id=chat_id,
                        message_id=msg_id,
                        text=text, reply_markup=kb,
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=True,
                    )
                    panel["last_text"] = text
                except Exception as e:
                    err = str(e).lower()
                    if "not modified" in err:
                        continue
                    if "message to edit not found" in err:
                        _unregister_panel(msg_id)
                        last_refresh.pop(msg_id, None)
                        continue
        except asyncio.CancelledError:
            return
        except Exception:
            pass


# ============================================================
# HELPERS
# ============================================================

def _safe_worker_status() -> Dict[str, Any]:
    try:
        from plugins.indexing import worker as WK
        return WK.status()
    except Exception:
        return {}


async def _safe_edit(q: CallbackQuery, text: str, kb) -> None:
    try:
        await q.message.edit_text(
            text, reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        if "not modified" not in str(e).lower():
            logger.debug(f"[INDEX] edit: {e}")


async def open_panel_for_admin(client: Client, message: Message) -> None:
    text, kb = await _build_main_panel()
    sent = await message.reply_text(
        text, reply_markup=kb,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )
    _register_panel(sent.id, sent.chat.id, "main", text)
    _ensure_auto_refresh()


def snapshot() -> Dict[str, Any]:
    return {"panels": len(_panels), "pending_steps": len(_steps)}


# ============================================================
# FORWARD DETECTION
# ============================================================

@Client.on_message(
    filters.private
    & filters.forwarded
    & ~filters.service,
    group=-8199,
)
async def idx_forward_handler(client: Client, message: Message):
    if not message.from_user or not _is_admin(message.from_user.id):
        return

    s = _get_step(message.from_user.id)
    if not s or s.get("step") != "channel_forward":
        return

    fwd_chat = getattr(message, "forward_from_chat", None)
    if not fwd_chat:
        return await message.reply_text(
            "\n".join([
                f"{F.EMO['warn']} <b>{F.fb('CANNOT DETECT CHANNEL')}</b>",
                F.DIV, "",
                f"📌 {F.sc('forward was from a hidden user')}",
                f"📌 {F.sc('please forward from the channel itself')}",
            ]),
            parse_mode=ParseMode.HTML,
        )

    channel_id = int(fwd_chat.id)
    title = getattr(fwd_chat, "title", None) or str(channel_id)
    username = getattr(fwd_chat, "username", "") or ""

    try:
        from plugins.indexing import backward as BW
        await BW.register_channel(
            chat_id=channel_id,
            title=title,
            username=username,
            kind="manual",
            added_by=message.from_user.id,
        )
    except Exception as e:
        logger.debug(f"[INDEX] register on forward: {e}")

    _set_step(message.from_user.id, "mode", channel_id=channel_id)

    txt, kb = await _build_step_mode()
    await message.reply_text(
        txt, reply_markup=kb,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )

    try:
        await message.reply_text(
            f"{F.EMO['check']} <b>Channel registered</b>\n"
            f"📛 {F.sc(str(title)[:60])}\n"
            f"🆔 <code>{channel_id}</code>",
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass

    try:
        message.stop_propagation()
    except Exception:
        pass


@Client.on_message(
    filters.private
    & (filters.video | filters.document | filters.audio | filters.animation)
    & ~filters.forwarded,
    group=-8199,
)
async def idx_media_handler(client: Client, message: Message):
    if not message.from_user or not _is_admin(message.from_user.id):
        return

    s = _get_step(message.from_user.id)
    if not s or s.get("step") != "channel_forward":
        return

    channel_id = int(message.chat.id)
    title = getattr(message.chat, "title", None) or str(channel_id)

    try:
        from plugins.indexing import backward as BW
        await BW.register_channel(
            chat_id=channel_id,
            title=title,
            username="",
            kind="manual",
            added_by=message.from_user.id,
        )
    except Exception as e:
        logger.debug(f"[INDEX] register on media: {e}")

    _set_step(message.from_user.id, "mode", channel_id=channel_id)

    txt, kb = await _build_step_mode()
    await message.reply_text(
        txt, reply_markup=kb,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )

    try:
        message.stop_propagation()
    except Exception:
        pass


__all__ = [
    "cmd_index", "open_panel_for_admin", "snapshot",
]
