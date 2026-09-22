# ============================================================
# 🏨 DOWNTOWN VILLA — INDEXING CONTROL CENTER (ULTIMATE)
# ============================================================
#
# ONE COMMAND:  /index
#
# Everything else is a button.
#
# Full customization flow when user taps [▶️ START]:
#   1. Pick CHANNEL (or use forwarded message)
#   2. Pick MODE      (movies / series / both)
#   3. Pick DIRECTION (forward / backward)
#   4. Pick RANGE     (from first / from last / custom id)
#   5. Pick ADVANCED  (batch, concurrency, delay, options)
#   6. CONFIRM        → [START NOW] or [SAVE AS DEFAULT]
#
# Live panel shows:
#   • Color progress bar (indexing mode)
#   • Speed · ETA · current message id
#   • Stats: saved / duplicate_id / skipped / failed
#   • Per-mode counts (movies / series)
#
# Rules (LOCKED):
#   • Only skips files with SAME FILE_ID (exact duplicate)
#   • Never skips for missing metadata, bad name, etc.
#   • Every other file is imported.
#
# ============================================================

from __future__ import annotations

import asyncio
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


# ============================================================
# SECTION 1 — CONSTANTS
# ============================================================

PFX = "idx"
AUTO_REFRESH_SEC = 5.0

# Config steps stored per user during setup
_steps: Dict[int, Dict[str, Any]] = {}
STEP_TTL = 900.0


# ============================================================
# SECTION 2 — AUTH
# ============================================================

def _is_admin(uid) -> bool:
    try:
        return int(uid) in [int(a) for a in config.ADMINS]
    except Exception:
        return False


# ============================================================
# SECTION 3 — CONFIG STEP STATE
# ============================================================

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
    s = _steps.get(int(uid))
    if not s:
        return
    s["data"].update(data)
    s["expires"] = time.time() + STEP_TTL


def _drop_step(uid: int) -> None:
    _steps.pop(int(uid), None)


# ============================================================
# SECTION 4 — LIVE PANEL REGISTRY
# ============================================================

_panels: Dict[int, Dict[str, Any]] = {}


def _register_panel(msg_id: int, chat_id: int, page: str, text: str) -> None:
    _panels[msg_id] = {
        "chat_id": chat_id,
        "page": page,
        "last_text": text,
        "created": time.time(),
    }


def _unregister_panel(msg_id: int) -> None:
    _panels.pop(msg_id, None)


# ============================================================
# SECTION 5 — MAIN PANEL
# ============================================================

async def _build_main_panel() -> Tuple[str, InlineKeyboardMarkup]:
    """Main /index panel."""
    # Worker status
    w = {}
    try:
        from plugins.indexing import worker as WK
        w = WK.status()
    except Exception:
        pass

    # Auto mode flag
    auto_mode = await _get_auto_mode()

    # Recent job counts
    history = []
    try:
        from plugins.indexing import state as ST
        history = await ST.list_recent(5)
    except Exception:
        pass

    # Determine status icon
    running = w.get("running", False)
    paused = w.get("paused", False)

    if running and not paused:
        status_icon = "🟢"
        status_text = "RUNNING"
    elif paused:
        status_icon = "🟡"
        status_text = "PAUSED"
    else:
        status_icon = "⚪"
        status_text = "IDLE"

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"📚 <b>{F.fb('INDEXING CONTROL CENTER')}</b>",
        F.DIV,
        "",
        f"{status_icon} <b>{F.sc(status_text)}</b>",
        f"🎯 {F.sc('auto mode')} · "
        f"{'🟢 ' + F.sc('on') if auto_mode else '🔴 ' + F.sc('off')}",
        "",
    ]

    # Live progress if running
    if running or paused:
        lines.extend(await _render_live_progress(w))

    # Recent jobs snippet
    if history and not running:
        lines.append(F.DIV_S)
        lines.append(f"{F.EMO['clock']} <b>{F.fb('RECENT')}</b>")
        lines.append(F.DIV_S)
        lines.append("")
        for h in history[:3]:
            h_status = str(h.get("status", "?"))
            icon = {
                "running": "🟢", "paused": "🟡",
                "completed": "✅", "stopped": "🛑",
                "error": "❌", "cancelled": "⛔",
            }.get(h_status, "⚪")
            jid = str(h.get("job_id", "?"))[:30]
            stats = h.get("stats", {})
            lines.append(f"{icon} <code>{jid}</code>")
            lines.append(
                f"   ✅ <b>{FM.num(stats.get('saved', 0))}</b> · "
                f"⏭️ <b>{FM.num(stats.get('duplicate_id', 0))}</b> · "
                f"❌ <b>{FM.num(stats.get('failed', 0))}</b>"
            )
        lines.append("")

    lines += [
        F.DIV_S,
        f"🕒 <code>{FM.datetime_()}</code>",
    ]

    text = "\n".join(lines)[:4000]

    # Keyboard
    rows: List[List[InlineKeyboardButton]] = []

    if not running:
        rows.append([
            InlineKeyboardButton(
                f"{F.EMO['play']} {F.sc('start new job')}",
                callback_data=f"{PFX}:start",
            ),
        ])
    elif paused:
        rows.append([
            InlineKeyboardButton(
                f"{F.EMO['play']} {F.sc('resume')}",
                callback_data=f"{PFX}:resume",
            ),
            InlineKeyboardButton(
                f"{F.EMO['stop']} {F.sc('stop')}",
                callback_data=f"{PFX}:stop",
            ),
        ])
    else:
        rows.append([
            InlineKeyboardButton(
                f"{F.EMO['pause']} {F.sc('pause')}",
                callback_data=f"{PFX}:pause",
            ),
            InlineKeyboardButton(
                f"{F.EMO['stop']} {F.sc('stop')}",
                callback_data=f"{PFX}:stop",
            ),
        ])

    rows.append([
        InlineKeyboardButton(
            f"📊 {F.sc('live status')}",
            callback_data=f"{PFX}:live",
        ),
        InlineKeyboardButton(
            f"🧾 {F.sc('history')}",
            callback_data=f"{PFX}:history",
        ),
    ])
    rows.append([
        InlineKeyboardButton(
            f"🎯 {F.sc('auto mode')} · "
            f"{'🟢' if auto_mode else '🔴'}",
            callback_data=f"{PFX}:toggle_auto",
        ),
        InlineKeyboardButton(
            f"🗄️ {F.sc('databases')}",
            callback_data=f"{PFX}:databases",
        ),
    ])
    rows.append([
        InlineKeyboardButton(
            f"🧹 {F.sc('duplicates')}",
            callback_data=f"{PFX}:duplicates",
        ),
        InlineKeyboardButton(
            f"🎬 {F.sc('movies')}",
            callback_data=f"{PFX}:filter:movies",
        ),
    ])
    rows.append([
        InlineKeyboardButton(
            f"📺 {F.sc('series')}",
            callback_data=f"{PFX}:filter:series",
        ),
        InlineKeyboardButton(
            f"🗑️ {F.sc('reset')}",
            callback_data=f"{PFX}:reset",
        ),
    ])
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

    return text, InlineKeyboardMarkup(rows)


async def _render_live_progress(w: Dict[str, Any]) -> List[str]:
    """Progress block for the live status section."""
    total = int(w.get("total_messages", 0) or 0)
    current = int(w.get("current_message_id", 0) or 0)
    done = int(w.get("processed", 0) or 0)
    saved = int(w.get("saved", 0) or 0)
    dup = int(w.get("duplicate_id", 0) or 0)
    skipped = int(w.get("skipped_no_media", 0) or 0)
    failed = int(w.get("failed", 0) or 0)
    movies = int(w.get("movies", 0) or 0)
    series = int(w.get("series", 0) or 0)

    speed = float(w.get("speed", 0.0) or 0.0)
    eta_text = w.get("eta_text", "—")

    # Progress percent
    if total > 0:
        pct = (1 - current / max(1, total)) * 100 if current > 0 else 0.0
    else:
        pct = 0.0

    out: List[str] = [
        F.DIV_S,
        f"{F.EMO['chart']} <b>{F.fb('LIVE PROGRESS')}</b>",
        F.DIV_S,
        "",
        f"<code>{P.bar(pct, 'indexing', width=18)}</code>",
        "",
        f"📢 {F.sc('channel')} · "
        f"<code>{str(w.get('channel_title', '?'))[:30]}</code>",
        f"🎬 {F.sc('mode')} · <b>{str(w.get('mode', '?'))}</b>",
        f"⬇️ {F.sc('direction')} · "
        f"<b>{str(w.get('direction', '?'))}</b>",
        "",
        f"✅ {F.sc('saved')} · <b>{FM.num(saved)}</b>",
        f"⏭️ {F.sc('duplicate')} · <b>{FM.num(dup)}</b>",
        f"🚫 {F.sc('no media')} · <b>{FM.num(skipped)}</b>",
        f"❌ {F.sc('failed')} · <b>{FM.num(failed)}</b>",
        "",
        f"🎬 {F.sc('movies')} · <b>{FM.num(movies)}</b>",
        f"📺 {F.sc('series')} · <b>{FM.num(series)}</b>",
        "",
        f"⚡ {F.sc('speed')} · <b>{FM.rate(speed)}</b>",
        f"⏱️ {F.sc('eta')} · <b>{eta_text}</b>",
        f"📍 {F.sc('current')} · <code>{FM.num(current)}</code>",
        "",
    ]
    return out


# ============================================================
# SECTION 6 — CONFIG FLOW: STEP 1 — CHANNEL
# ============================================================

async def _build_step_channel() -> Tuple[str, InlineKeyboardMarkup]:
    channels = list(config.DATABASE_CHANNEL_IDS or [])

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"📢 <b>{F.fb('STEP 1/5 — CHANNEL')}</b>",
        F.DIV,
        "",
        f"{F.EMO['info']} {F.sc('pick the channel to index')}",
        "",
    ]

    rows: List[List[InlineKeyboardButton]] = []

    if not channels:
        lines.append(f"{F.EMO['warn']} {F.sc('no channels configured')}")
        lines.append("")
        lines.append(f"📌 {F.sc('forward any media from the channel')}")
        lines.append(f"📌 {F.sc('to detect it automatically')}")
    else:
        for i, ch in enumerate(channels[:8], 1):
            lines.append(f"{i:02d}. <code>{ch}</code>")
            rows.append([InlineKeyboardButton(
                f"📢 {F.sc(f'channel {i:02d}')} · {str(ch)[-8:]}",
                callback_data=f"{PFX}:pick_ch:{ch}",
            )])

    rows.append([
        InlineKeyboardButton(
            f"📎 {F.sc('forward media')}",
            callback_data=f"{PFX}:wait_forward",
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
# SECTION 7 — STEP 2 — MODE
# ============================================================

async def _build_step_mode() -> Tuple[str, InlineKeyboardMarkup]:
    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"🎬 <b>{F.fb('STEP 2/5 — MODE')}</b>",
        F.DIV,
        "",
        f"{F.EMO['info']} {F.sc('what to index from this channel')}",
        "",
        f"🎬 {F.sc('movies')} — only movie files",
        f"📺 {F.sc('series')} — only series files",
        f"🎬📺 {F.sc('both')} — everything",
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
        [
            InlineKeyboardButton(
                f"🎬📺 {F.sc('both')}",
                callback_data=f"{PFX}:pick_mode:both",
            ),
        ],
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
# SECTION 8 — STEP 3 — DIRECTION
# ============================================================

async def _build_step_direction() -> Tuple[str, InlineKeyboardMarkup]:
    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"⬇️ <b>{F.fb('STEP 3/5 — DIRECTION')}</b>",
        F.DIV,
        "",
        f"{F.EMO['info']} {F.sc('how should the scan walk')}",
        "",
        f"⬇️ {F.sc('forward')}  — oldest → newest",
        f"⬆️ {F.sc('backward')} — newest → oldest",
        "",
        F.DIV_S,
        f"💡 {F.sc('backward is usually faster for recent files')}",
    ]

    rows = [
        [
            InlineKeyboardButton(
                f"⬇️ {F.sc('forward')}",
                callback_data=f"{PFX}:pick_dir:forward",
            ),
        ],
        [
            InlineKeyboardButton(
                f"⬆️ {F.sc('backward')}",
                callback_data=f"{PFX}:pick_dir:backward",
            ),
        ],
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
# SECTION 9 — STEP 4 — RANGE
# ============================================================

async def _build_step_range() -> Tuple[str, InlineKeyboardMarkup]:
    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"📍 <b>{F.fb('STEP 4/5 — RANGE')}</b>",
        F.DIV,
        "",
        f"{F.EMO['info']} {F.sc('where to begin scanning')}",
        "",
        f"📍 {F.sc('from first')} — start at msg id 1",
        f"📍 {F.sc('from last')} — start at newest msg",
        f"📍 {F.sc('custom')} — enter a specific msg id",
    ]

    rows = [
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
        [
            InlineKeyboardButton(
                f"✏️ {F.sc('custom msg id')}",
                callback_data=f"{PFX}:pick_range:custom",
            ),
        ],
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
# SECTION 10 — STEP 5 — ADVANCED
# ============================================================

async def _build_step_advanced(uid: int) -> Tuple[str, InlineKeyboardMarkup]:
    s = _get_step(uid)
    data = s.get("data", {}) if s else {}

    batch = int(data.get("batch_size", 100))
    conc = int(data.get("concurrency", 20))
    delay = float(data.get("delay", 0.3))
    skip_dup = bool(data.get("skip_duplicate", True))
    auto_pause = bool(data.get("auto_pause", True))

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"⚙️ <b>{F.fb('STEP 5/5 — ADVANCED')}</b>",
        F.DIV,
        "",
        f"{F.EMO['info']} {F.sc('tune the indexer')}",
        "",
        f"📦 {F.sc('batch size')} · <b>{batch}</b>",
        f"⚡ {F.sc('concurrency')} · <b>{conc}</b>",
        f"⏱️ {F.sc('delay')} · <b>{delay}s</b>",
        f"🧹 {F.sc('skip same file_id')} · "
        f"{'🟢 ON' if skip_dup else '🔴 OFF'}",
        f"🛡️ {F.sc('auto-pause on flood')} · "
        f"{'🟢 ON' if auto_pause else '🔴 OFF'}",
        "",
        F.DIV_S,
        f"📌 {F.sc('every file is imported except exact same file_id')}",
    ]

    rows = []

    # Batch size row
    batch_row = []
    for n in (50, 100, 200, 500):
        mark = "✅ " if batch == n else ""
        batch_row.append(InlineKeyboardButton(
            f"{mark}{n}",
            callback_data=f"{PFX}:set_batch:{n}",
        ))
    rows.append(batch_row)

    # Concurrency row
    conc_row = []
    for n in (5, 10, 20, 50):
        mark = "✅ " if conc == n else ""
        conc_row.append(InlineKeyboardButton(
            f"{mark}{n}",
            callback_data=f"{PFX}:set_conc:{n}",
        ))
    rows.append(conc_row)

    # Delay row
    delay_row = []
    for d in (0.0, 0.3, 0.5, 1.0):
        mark = "✅ " if abs(delay - d) < 0.01 else ""
        label = f"{mark}{int(d)}s" if d == int(d) else f"{mark}{d}s"
        delay_row.append(InlineKeyboardButton(
            label,
            callback_data=f"{PFX}:set_delay:{d}",
        ))
    rows.append(delay_row)

    # Toggles
    rows.append([
        InlineKeyboardButton(
            f"{'🟢' if skip_dup else '🔴'} {F.sc('skip same file_id')}",
            callback_data=f"{PFX}:toggle_skipdup",
        ),
        InlineKeyboardButton(
            f"{'🟢' if auto_pause else '🔴'} {F.sc('auto-pause flood')}",
            callback_data=f"{PFX}:toggle_autopause",
        ),
    ])

    # Save as default + Next
    rows.append([
        InlineKeyboardButton(
            f"💾 {F.sc('save as default')}",
            callback_data=f"{PFX}:save_default",
        ),
    ])
    rows.append([
        InlineKeyboardButton(
            f"▶️ {F.sc('review & start')}",
            callback_data=f"{PFX}:confirm",
        ),
    ])
    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data=f"{PFX}:back_range",
        ),
        InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('cancel')}",
            callback_data=f"{PFX}:cancel_config",
        ),
    ])

    return "\n".join(lines)[:4000], InlineKeyboardMarkup(rows)


# ============================================================
# SECTION 11 — CONFIRM PANEL
# ============================================================

async def _build_confirm(uid: int) -> Tuple[str, InlineKeyboardMarkup]:
    s = _get_step(uid)
    if not s:
        return await _build_main_panel()

    data = s.get("data", {})

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"✅ <b>{F.fb('REVIEW & START')}</b>",
        F.DIV,
        "",
        f"📢 {F.sc('channel')} · "
        f"<code>{data.get('channel_id', '?')}</code>",
        f"🎬 {F.sc('mode')} · <b>{data.get('mode', '?')}</b>",
        f"⬇️ {F.sc('direction')} · <b>{data.get('direction', '?')}</b>",
        f"📍 {F.sc('range')} · <b>{data.get('range', '?')}</b>",
    ]

    if data.get("range") == "custom":
        lines.append(
            f"   📌 {F.sc('custom start')} · "
            f"<code>{data.get('start_msg_id', '?')}</code>"
        )

    lines += [
        "",
        F.DIV_S,
        f"📦 {F.sc('batch')} · <b>{data.get('batch_size', 100)}</b>",
        f"⚡ {F.sc('conc')} · <b>{data.get('concurrency', 20)}</b>",
        f"⏱️ {F.sc('delay')} · <b>{data.get('delay', 0.3)}s</b>",
        f"🧹 {F.sc('skip same file_id')} · "
        f"{'🟢' if data.get('skip_duplicate', True) else '🔴'}",
        f"🛡️ {F.sc('auto-pause flood')} · "
        f"{'🟢' if data.get('auto_pause', True) else '🔴'}",
        "",
        F.DIV_S,
        f"{F.EMO['spark']} <b>{F.sc('ready to start')}</b>",
    ]

    rows = [
        [
            InlineKeyboardButton(
                f"▶️ {F.sc('start now')}",
                callback_data=f"{PFX}:do_start",
            ),
        ],
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
# SECTION 12 — HISTORY / STATUS / DUPLICATES / DATABASES
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
        F.DIV,
        "",
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
            started = h.get("started_at")

            lines.append(f"{icon} <code>{jid}</code>")
            if started:
                try:
                    lines.append(
                        f"   🕒 {started.strftime('%d %b · %H:%M')}"
                    )
                except Exception:
                    pass
            lines.append(
                f"   ✅ <b>{FM.num(stats.get('saved', 0))}</b> · "
                f"⏭️ <b>{FM.num(stats.get('duplicate_id', 0))}</b> · "
                f"❌ <b>{FM.num(stats.get('failed', 0))}</b>"
            )
            lines.append("")

    rows = [
        [
            InlineKeyboardButton(
                f"🗑️ {F.sc('clear history')}",
                callback_data=f"{PFX}:clear_history",
            ),
        ],
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
        [
            InlineKeyboardButton(
                f"{F.EMO['cross']} {F.sc('close')}",
                callback_data=f"{PFX}:close",
            ),
        ],
    ]

    return "\n".join(lines)[:4000], InlineKeyboardMarkup(rows)


async def _build_databases() -> Tuple[str, InlineKeyboardMarkup]:
    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"🗄️ <b>{F.fb('DATABASES')}</b>",
        F.DIV,
        "",
    ]

    try:
        from database import db_registry
        snap = await db_registry.snapshot()
        pools = snap.get("pools", {})
        for pool_name, info in pools.items():
            icon = {"system": "⚙️", "user": "👤",
                    "media": "🎬", "backup": "💾"}.get(pool_name, "📦")
            lines.append(
                f"{icon} <b>{F.sc(pool_name)}</b> · "
                f"{info.get('online', 0)}/{info.get('total', 0)} · "
                f"{FM.size(info.get('total_used_mb', 0) * 1024 * 1024)}"
            )
    except Exception as e:
        lines.append(f"❌ {F.sc('error')} · <code>{str(e)[:60]}</code>")

    rows = [[
        InlineKeyboardButton(
            f"{F.EMO['refresh']} {F.sc('refresh')}",
            callback_data=f"{PFX}:databases",
        ),
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data=f"{PFX}:back",
        ),
    ], [
        InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('close')}",
            callback_data=f"{PFX}:close",
        ),
    ]]

    return "\n".join(lines)[:4000], InlineKeyboardMarkup(rows)


async def _build_duplicates() -> Tuple[str, InlineKeyboardMarkup]:
    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"🧹 <b>{F.fb('DUPLICATE CONTROL')}</b>",
        F.DIV,
        "",
        f"{F.EMO['info']} {F.sc('duplicates = same file_id only')}",
        f"{F.EMO['info']} {F.sc('other similar files are NOT duplicates')}",
        "",
        F.DIV_S,
        f"{F.EMO['spark']} <b>{F.sc('duplicate policy')}</b>",
        F.DIV_S,
        "",
        f"✅ {F.sc('import every file')}",
        f"⏭️ {F.sc('skip only if file_id matches exactly')}",
        f"🚫 {F.sc('never skip for missing metadata')}",
        "",
    ]

    # Recent counts
    try:
        from plugins.indexing import state as ST
        jobs = await ST.list_recent(20)
        total_dup = sum(
            j.get("stats", {}).get("duplicate_id", 0) for j in jobs
        )
        lines.append(
            f"📊 {F.sc('total duplicates found')} · "
            f"<b>{FM.num(total_dup)}</b>"
        )
        lines.append(f"   <i>{F.sc('across last 20 jobs')}</i>")
    except Exception:
        pass

    rows = [[
        InlineKeyboardButton(
            f"{F.EMO['refresh']} {F.sc('refresh')}",
            callback_data=f"{PFX}:duplicates",
        ),
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data=f"{PFX}:back",
        ),
    ], [
        InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('close')}",
            callback_data=f"{PFX}:close",
        ),
    ]]

    return "\n".join(lines)[:4000], InlineKeyboardMarkup(rows)


# ============================================================
# SECTION 13 — AUTO MODE
# ============================================================

async def _get_auto_mode() -> bool:
    try:
        from database import db_registry
        db = db_registry.get_system_db()
        if db is None:
            return True
        doc = await db["bot_settings"].find_one({"_id": "indexing"})
        if doc and "auto_mode" in doc:
            return bool(doc["auto_mode"])
        return True
    except Exception:
        return True


async def _set_auto_mode(value: bool) -> bool:
    try:
        from database import db_registry
        db = db_registry.get_system_db()
        if db is None:
            return False
        await db["bot_settings"].update_one(
            {"_id": "indexing"},
            {"$set": {"auto_mode": bool(value), "updated_at": datetime.utcnow()}},
            upsert=True,
        )
        return True
    except Exception:
        return False


# ============================================================
# SECTION 14 — COMMAND
# ============================================================

@Client.on_message(
    filters.command(["index", "indexing"]) & filters.private,
    group=-8200,
)
async def cmd_index(client: Client, message: Message):
    """THE one indexing command."""
    if not message.from_user or not _is_admin(message.from_user.id):
        return await message.reply_text(
            f"{F.EMO['cross']} <b>{F.fb('ACCESS DENIED')}</b>\n"
            f"<i>{F.sc('admins only')}</i>",
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
# SECTION 15 — ROUTER
# ============================================================

@Client.on_callback_query(
    filters.regex(rf"^{PFX}:"),
    group=-8200,
)
async def router_handler(client: Client, q: CallbackQuery):
    """Handle idx:* callbacks."""
    if not q.from_user or not _is_admin(q.from_user.id):
        return await q.answer("❌ Admin only", show_alert=True)

    parts = str(q.data).split(":")
    action = parts[1] if len(parts) > 1 else ""
    arg = parts[2] if len(parts) > 2 else ""
    uid = q.from_user.id

    try:
        # ────────── MAIN ──────────
        if action in ("back", "refresh"):
            text, kb = await _build_main_panel()
            await _safe_edit(q, text, kb)
            _register_panel(q.message.id, q.message.chat.id, "main", text)
            return await q.answer()

        # ────────── START FLOW ──────────
        if action == "start":
            _drop_step(uid)
            _new_step(uid, "channel")
            text, kb = await _build_step_channel()
            await _safe_edit(q, text, kb)
            return await q.answer()

        if action == "wait_forward":
            _new_step(uid, "channel_forward")
            text = "\n".join([
                f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                f"📎 <b>{F.fb('FORWARD A MESSAGE')}</b>",
                F.DIV,
                "",
                f"📌 {F.sc('forward any media message')}",
                f"📌 {F.sc('from the source channel')}",
                "",
                F.DIV_S,
                f"💡 {F.sc('the bot will detect the channel')}",
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
                    F.DIV,
                    "",
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

            _update_step(uid, range=arg)
            text, kb = await _build_step_advanced(uid)
            await _safe_edit(q, text, kb)
            return await q.answer()

        if action == "back_adv":
            text, kb = await _build_step_advanced(uid)
            await _safe_edit(q, text, kb)
            return await q.answer()

        # ────────── ADVANCED SETTERS ──────────
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
            s = _get_step(uid)
            cur = s.get("data", {}).get("skip_duplicate", True) if s else True
            _update_step(uid, skip_duplicate=not cur)
            text, kb = await _build_step_advanced(uid)
            await _safe_edit(q, text, kb)
            return await q.answer("🔄 Toggled")

        if action == "toggle_autopause":
            s = _get_step(uid)
            cur = s.get("data", {}).get("auto_pause", True) if s else True
            _update_step(uid, auto_pause=not cur)
            text, kb = await _build_step_advanced(uid)
            await _safe_edit(q, text, kb)
            return await q.answer("🔄 Toggled")

        if action == "save_default":
            s = _get_step(uid)
            if s:
                await _save_default_config(s.get("data", {}))
            await q.answer("💾 Saved as default")
            return

        # ────────── CONFIRM ──────────
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

            # Start worker
            try:
                from plugins.indexing import worker as WK
                ok = await WK.start_worker(
                    channel_id=int(data["channel_id"]),
                    mode=str(data.get("mode", "both")),
                    direction=str(data.get("direction", "backward")),
                    start_msg_id=data.get("start_msg_id"),
                    range_mode=str(data.get("range", "last")),
                    batch_size=int(data.get("batch_size", 100)),
                    concurrency=int(data.get("concurrency", 20)),
                    delay=float(data.get("delay", 0.3)),
                    skip_duplicate=bool(data.get("skip_duplicate", True)),
                    auto_pause=bool(data.get("auto_pause", True)),
                    owner=uid,
                )
                await q.answer("▶️ Started" if ok else "⚠️ Already running")
            except Exception as e:
                logger.exception(f"[INDEX] start: {e}")
                await q.answer(f"❌ {type(e).__name__}", show_alert=True)
                return

            text, kb = await _build_main_panel()
            await _safe_edit(q, text, kb)
            _ensure_auto_refresh()
            return

        if action == "cancel_config":
            _drop_step(uid)
            text, kb = await _build_main_panel()
            await _safe_edit(q, text, kb)
            return await q.answer("❌ Cancelled")

        # ────────── WORKER CONTROLS ──────────
        if action == "pause":
            try:
                from plugins.indexing import worker as WK
                ok = WK.pause_worker()
                await q.answer("⏸️ Paused" if ok else "⚠️ Not running")
            except Exception:
                pass
            text, kb = await _build_main_panel()
            await _safe_edit(q, text, kb)
            return

        if action == "resume":
            try:
                from plugins.indexing import worker as WK
                ok = WK.resume_worker()
                await q.answer("▶️ Resumed" if ok else "⚠️ Not paused")
            except Exception:
                pass
            text, kb = await _build_main_panel()
            await _safe_edit(q, text, kb)
            return

        if action == "stop":
            try:
                from plugins.indexing import worker as WK
                ok = WK.stop_worker()
                await q.answer("⏹️ Stopping…" if ok else "⚠️ Not running")
            except Exception:
                pass
            text, kb = await _build_main_panel()
            await _safe_edit(q, text, kb)
            return

        # ────────── VIEWS ──────────
        if action == "live":
            text, kb = await _build_main_panel()
            await _safe_edit(q, text, kb)
            return await q.answer()

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
                await q.answer("❌ Failed")
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

        # ────────── RESET ──────────
        if action == "reset":
            text = "\n".join([
                f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                f"🗑️ <b>{F.fb('CLEAR INDEXING HISTORY')}</b>",
                F.DIV,
                "",
                f"{F.EMO['warn']} {F.sc('this clears only job history')}",
                f"{F.EMO['info']} {F.sc('indexed files are NOT removed')}",
                "",
                F.DIV_S,
                f"{F.EMO['spark']} <i>{F.sc('safe to do anytime')}</i>",
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
                await q.answer(f"🗑️ Cleared {n} jobs")
            except Exception:
                await q.answer("❌ Failed")
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
# SECTION 16 — TEXT INPUT (custom msg id / forward detection)
# ============================================================

@Client.on_message(
    filters.private & filters.text & ~filters.regex(r"^/"),
    group=-8190,
)
async def indexing_text_input(client: Client, message: Message):
    """Handle custom message id text input."""
    if not message.from_user or not _is_admin(message.from_user.id):
        return

    s = _get_step(message.from_user.id)
    if not s or s.get("step") != "range_custom":
        # Also try direct
        pass

    s = _steps.get(message.from_user.id)
    if not s:
        return

    data = s.get("data", {})
    if data.get("range") != "custom":
        return

    text = (message.text or "").strip()
    if not text.isdigit():
        return await message.reply_text(
            f"{F.EMO['cross']} {F.sc('send a numeric message id')}",
            parse_mode=ParseMode.HTML,
        )

    _update_step(message.from_user.id, start_msg_id=int(text))

    # Show advanced
    txt, kb = await _build_step_advanced(message.from_user.id)
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
# SECTION 17 — DEFAULT CONFIG
# ============================================================

async def _save_default_config(data: Dict[str, Any]) -> bool:
    try:
        from database import db_registry
        db = db_registry.get_system_db()
        if db is None:
            return False
        await db["bot_settings"].update_one(
            {"_id": "indexing_default"},
            {"$set": {**data, "updated_at": datetime.utcnow()}},
            upsert=True,
        )
        return True
    except Exception:
        return False


# ============================================================
# SECTION 18 — AUTO REFRESH
# ============================================================

_refresh_task: Optional[asyncio.Task] = None


def _ensure_auto_refresh() -> None:
    global _refresh_task
    if _refresh_task and not _refresh_task.done():
        return
    try:
        loop = asyncio.get_running_loop()
        _refresh_task = loop.create_task(_auto_refresh_loop())
    except RuntimeError:
        pass


async def _auto_refresh_loop() -> None:
    while True:
        try:
            await asyncio.sleep(AUTO_REFRESH_SEC)
            if not _panels:
                continue

            running = False
            try:
                from plugins.indexing import worker as WK
                running = WK.status().get("running", False)
            except Exception:
                pass

            if not running:
                continue

            from core.client import client as C
            if C is None:
                continue

            for msg_id, panel in list(_panels.items()):
                if panel.get("page") not in ("main", "live"):
                    continue
                try:
                    text, kb = await _build_main_panel()
                    if text == panel.get("last_text"):
                        continue
                    await C.edit_message_text(
                        chat_id=panel["chat_id"],
                        message_id=msg_id,
                        text=text,
                        reply_markup=kb,
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=True,
                    )
                    panel["last_text"] = text
                except Exception as e:
                    if "message to edit not found" in str(e).lower():
                        _unregister_panel(msg_id)
                    continue
        except asyncio.CancelledError:
            return
        except Exception:
            pass


# ============================================================
# SECTION 19 — PUBLIC: OPEN FOR ADMIN
# ============================================================

async def open_panel_for_admin(client: Client, message: Message) -> None:
    text, kb = await _build_main_panel()
    sent = await message.reply_text(
        text, reply_markup=kb,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )
    _register_panel(sent.id, sent.chat.id, "main", text)
    _ensure_auto_refresh()


# ============================================================
# SECTION 20 — HELPERS
# ============================================================

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


def has_pending_step(uid: int) -> bool:
    return _get_step(uid) is not None


def snapshot() -> Dict[str, Any]:
    return {
        "panels": len(_panels),
        "pending_steps": len(_steps),
    }


# ============================================================
# PUBLIC EXPORTS
# ============================================================

__all__ = [
    "cmd_index",
    "open_panel_for_admin",
    "has_pending_step",
    "snapshot",
]
