# ============================================================
# 🏨 DOWNTOWN VILLA — BACKUP PANEL (THE ONE COMMAND)
# ============================================================
#
# ONLY ONE COMMAND:
#     /backup
#
# Everything else is a button.
#
# Layout:
#   ┌─────────────────────────────────┐
#   │  📊 LIVE STATUS + PROGRESS BARS  │
#   │                                 │
#   │  [▶️ START] [⏸️ PAUSE] [⏹️ STOP] │
#   │  [📢 CHANNELS] [📊 STATUS]       │
#   │  [🧾 HISTORY] [❌ FAILURES]      │
#   │  [♻️ RECONCILE] [🗑️ RESET]       │
#   │  [🔄 REFRESH] [❌ CLOSE]         │
#   └─────────────────────────────────┘
#
# Integrates:
#   • channels.py      → channel manager (buttons)
#   • state.py         → live progress + counts
#   • worker.py        → start/pause/stop
#   • reconcile.py     → crash recovery
#   • reset.py         → wipe with confirm
#
# ============================================================

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

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

PFX = "dtvb"     # callback namespace for /backup panel
AUTO_REFRESH_SEC = 5.0


# ============================================================
# SECTION 2 — AUTH
# ============================================================

def _is_admin(uid) -> bool:
    try:
        return int(uid) in [int(a) for a in config.ADMINS]
    except Exception:
        return False


# ============================================================
# SECTION 3 — LIVE PANEL REGISTRY
# ============================================================

# message_id → {chat_id, page, last_text, created}
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
# SECTION 4 — BUILD THE MAIN PANEL
# ============================================================

async def _build_main_panel() -> tuple:
    """Build the main /backup panel."""
    # Get state snapshot
    stats = {}
    state_ok = False
    try:
        from plugins.backup import state as ST
        stats = await ST.stats()
        state_ok = True
    except Exception as e:
        logger.debug(f"[BACKUP] stats: {e}")

    # Worker status
    worker_running = False
    worker_paused = False
    worker_mode = "idle"
    worker_speed = 0.0
    worker_eta = "—"
    try:
        from plugins.backup import worker as WK
        w_status = WK.status()
        worker_running = w_status.get("running", False)
        worker_paused = w_status.get("paused", False)
        worker_mode = w_status.get("mode", "idle")
        worker_speed = w_status.get("speed", 0.0)
        worker_eta = w_status.get("eta_text", "—")
    except Exception:
        pass

    # Channel info
    backup_ch = None
    storage_ch = None
    try:
        from plugins.backup import channels as CH
        backup_ch = await CH.primary_backup_id()
        storage_ch = await CH.primary_storage_id()
    except Exception:
        pass

    # Totals
    totals = stats.get("totals", {}) if state_ok else {}
    pending = totals.get("pending", 0)
    uploaded = totals.get("uploaded", 0)
    failed = totals.get("failed", 0)
    uploading = totals.get("uploading", 0)
    skipped = totals.get("skipped", 0)

    grand_total = pending + uploaded + failed + uploading
    pct = (uploaded / grand_total * 100) if grand_total > 0 else 0.0

    # ────────── STATUS ICON ──────────
    if worker_running and not worker_paused:
        status_icon = "🟢"
        status_text = "RUNNING"
    elif worker_paused:
        status_icon = "🟡"
        status_text = "PAUSED"
    else:
        status_icon = "⚪"
        status_text = "IDLE"

    # ────────── RENDER ──────────
    lines: List[str] = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"💾 <b>{F.fb('BACKUP CENTER')}</b>",
        F.DIV,
        "",
        f"{status_icon} <b>{F.sc(status_text)}</b> · "
        f"<i>{F.sc(worker_mode)}</i>",
        "",
    ]

    # Channel info
    if backup_ch:
        lines.append(
            f"📢 {F.sc('backup channel')} · <code>{backup_ch}</code>"
        )
    else:
        lines.append(f"📢 {F.sc('backup channel')} · 🔴 {F.sc('not set')}")

    if storage_ch:
        lines.append(
            f"📦 {F.sc('storage channel')} · <code>{storage_ch}</code>"
        )
    lines.append("")

    # Progress
    if grand_total > 0:
        lines.append(F.DIV_S)
        lines.append(f"{F.EMO['chart']} <b>{F.fb('PROGRESS')}</b>")
        lines.append(F.DIV_S)
        lines.append("")
        lines.append(f"<code>{P.bar(pct, 'indexing', width=18)}</code>")
        lines.append("")
        lines.append(
            f"✅ {F.sc('uploaded')} · <b>{FM.num(uploaded)}</b>"
        )
        lines.append(
            f"⏳ {F.sc('pending')}  · <b>{FM.num(pending)}</b>"
        )
        lines.append(
            f"🔄 {F.sc('uploading')} · <b>{FM.num(uploading)}</b>"
        )
        lines.append(
            f"❌ {F.sc('failed')}   · <b>{FM.num(failed)}</b>"
        )
        lines.append(
            f"⏭️ {F.sc('skipped')} · <b>{FM.num(skipped)}</b>"
        )
        lines.append("")

        if worker_running and worker_speed > 0:
            lines.append(
                f"⚡ {F.sc('speed')} · <b>{FM.rate(worker_speed)}</b>"
            )
            lines.append(
                f"⏱️ {F.sc('eta')} · <b>{worker_eta}</b>"
            )
            lines.append("")

    # Per-source breakdown
    if state_ok:
        src_data = stats.get("by_source_db", {})
        if any(v.get("uploaded", 0) or v.get("pending", 0)
               for v in src_data.values()):
            lines.append(F.DIV_S)
            lines.append(f"{F.EMO['folder']} <b>{F.fb('BY SOURCE')}</b>")
            lines.append(F.DIV_S)
            lines.append("")
            for src, s in src_data.items():
                up = s.get("uploaded", 0)
                pe = s.get("pending", 0)
                fa = s.get("failed", 0)
                tot = up + pe + fa
                p_pct = (up / tot * 100) if tot > 0 else 0.0
                lines.append(
                    f"• <b>{F.sc(src)}</b> · "
                    f"<code>{P.bar(p_pct, 'indexing', width=8, show_percent=False)}</code> "
                    f"<b>{up}</b>/{tot}"
                )
                lines.append("")

    # Per-shard breakdown
    if state_ok:
        shards = stats.get("shards", [])
        if shards:
            lines.append(F.DIV_S)
            lines.append(
                f"{F.EMO['db']} <b>{F.fb('BY SHARD')}</b> "
                f"· <b>{len(shards)}</b>"
            )
            lines.append(F.DIV_S)
            lines.append("")
            for s in shards[:5]:
                icon = "🟢" if s.get("online") else "🔴"
                lines.append(
                    f"{icon} <code>{str(s.get('label', '?'))[:20]}</code>"
                )
                lines.append(
                    f"   ✅ <b>{FM.num(s.get('uploaded', 0))}</b> · "
                    f"⏳ <b>{FM.num(s.get('pending', 0))}</b> · "
                    f"❌ <b>{FM.num(s.get('failed', 0))}</b>"
                )
            if len(shards) > 5:
                lines.append(f"<i>… +{len(shards) - 5} more</i>")
            lines.append("")

    lines += [
        F.DIV_S,
        f"🕒 <code>{FM.datetime_()}</code>",
    ]

    text = "\n".join(lines)[:4000]

    # ────────── KEYBOARD ──────────
    kb = _build_main_kb(
        running=worker_running,
        paused=worker_paused,
    )

    return text, kb


def _build_main_kb(running: bool, paused: bool) -> InlineKeyboardMarkup:
    """Build the main keyboard."""
    rows: List[List[InlineKeyboardButton]] = []

    # Row 1: START/PAUSE/STOP
    if not running:
        rows.append([
            InlineKeyboardButton(
                f"{F.EMO['play']} {F.sc('start')}",
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

    # Row 2: CHANNELS / STATUS
    rows.append([
        InlineKeyboardButton(
            f"📢 {F.sc('channels')}",
            callback_data=f"{PFX}:channels",
        ),
        InlineKeyboardButton(
            f"📊 {F.sc('full status')}",
            callback_data=f"{PFX}:status",
        ),
    ])

    # Row 3: HISTORY / FAILURES
    rows.append([
        InlineKeyboardButton(
            f"🧾 {F.sc('history')}",
            callback_data=f"{PFX}:history",
        ),
        InlineKeyboardButton(
            f"❌ {F.sc('failures')}",
            callback_data=f"{PFX}:failures",
        ),
    ])

    # Row 4: RECONCILE / RETRY FAILED
    rows.append([
        InlineKeyboardButton(
            f"♻️ {F.sc('reconcile')}",
            callback_data=f"{PFX}:reconcile",
        ),
        InlineKeyboardButton(
            f"🔁 {F.sc('retry failed')}",
            callback_data=f"{PFX}:retry_failed",
        ),
    ])

    # Row 5: RESET
    rows.append([
        InlineKeyboardButton(
            f"🗑️ {F.sc('reset all')}",
            callback_data=f"{PFX}:reset",
        ),
    ])

    # Row 6: REFRESH / CLOSE
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

    return InlineKeyboardMarkup(rows)


# ============================================================
# SECTION 5 — SUB-PANELS
# ============================================================

async def _build_status_panel() -> tuple:
    """Detailed per-shard per-source status."""
    try:
        from plugins.backup import state as ST
        stats = await ST.stats()
    except Exception:
        stats = {}

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"📊 <b>{F.fb('FULL STATUS')}</b>",
        F.DIV,
        "",
    ]

    # Totals
    totals = stats.get("totals", {})
    for k, icon in (
        ("uploaded", "✅"), ("pending", "⏳"),
        ("uploading", "🔄"), ("failed", "❌"), ("skipped", "⏭️"),
    ):
        lines.append(
            f"{icon} <b>{F.sc(k)}</b> · "
            f"<b>{FM.num(totals.get(k, 0))}</b>"
        )
    lines.append("")

    # Per-source
    src_data = stats.get("by_source_db", {})
    if src_data:
        lines.append(F.DIV_S)
        lines.append(f"{F.EMO['folder']} <b>{F.fb('BY SOURCE')}</b>")
        lines.append(F.DIV_S)
        lines.append("")
        for src in ("Media", "Media2", "Media3"):
            s = src_data.get(src, {})
            up = s.get("uploaded", 0)
            pe = s.get("pending", 0)
            fa = s.get("failed", 0)
            tot = up + pe + fa
            p_pct = (up / tot * 100) if tot > 0 else 0.0
            lines.append(f"<b>{F.sc(src)}</b>")
            lines.append(
                f"<code>{P.bar(p_pct, 'indexing', width=14)}</code>"
            )
            lines.append(
                f"  ✅ <b>{FM.num(up)}</b> · "
                f"⏳ <b>{FM.num(pe)}</b> · "
                f"❌ <b>{FM.num(fa)}</b>"
            )
            lines.append("")

    # Per-shard
    shards = stats.get("shards", [])
    if shards:
        lines.append(F.DIV_S)
        lines.append(f"{F.EMO['db']} <b>{F.fb('BY SHARD')}</b>")
        lines.append(F.DIV_S)
        lines.append("")
        for s in shards:
            icon = "🟢" if s.get("online") else "🔴"
            lines.append(
                f"{icon} <code>{str(s.get('label', '?'))[:24]}</code>"
            )
            lines.append(
                f"   ✅ <b>{FM.num(s.get('uploaded', 0))}</b> · "
                f"⏳ <b>{FM.num(s.get('pending', 0))}</b> · "
                f"❌ <b>{FM.num(s.get('failed', 0))}</b>"
            )
            lines.append("")

    lines.append(f"🕒 <code>{FM.datetime_()}</code>")

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"{F.EMO['refresh']} {F.sc('refresh')}",
                callback_data=f"{PFX}:status",
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
    ])

    return "\n".join(lines)[:4000], kb


async def _build_history_panel() -> tuple:
    """Backup run history."""
    try:
        from plugins.backup import state as ST
        runs = await ST.list_runs(limit=12)
    except Exception:
        runs = []

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"🧾 <b>{F.fb('BACKUP HISTORY')}</b>",
        F.DIV,
        "",
    ]

    if not runs:
        lines.append(f"⚪ {F.sc('no runs yet')}")
    else:
        for r in runs:
            status = str(r.get("status", "?"))
            icon = {
                "RUNNING": "🟢",
                "COMPLETED": "✅",
                "STOPPED": "🛑",
                "FAILED": "❌",
                "ERROR": "💥",
            }.get(status, "⚪")

            started = r.get("started_at")
            finished = r.get("finished_at")

            start_str = "?"
            duration_str = "running"
            if started:
                try:
                    start_str = started.strftime("%d %b · %H:%M")
                    if finished:
                        d = (finished - started).total_seconds()
                        duration_str = FM.duration_short(d)
                except Exception:
                    pass

            lines.append(
                f"{icon} <b>{F.sc(status)}</b>"
            )
            lines.append(f"   🕒 <code>{start_str}</code> · "
                         f"⏱️ {duration_str}")
            lines.append(
                f"   ✅ <b>{FM.num(r.get('uploaded', 0))}</b> · "
                f"❌ <b>{FM.num(r.get('failed', 0))}</b>"
            )
            lines.append("")

    lines.append(f"🕒 <code>{FM.datetime_()}</code>")

    kb = InlineKeyboardMarkup([
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
    ])

    return "\n".join(lines)[:4000], kb


async def _build_failures_panel() -> tuple:
    """Failed files list."""
    try:
        from plugins.backup import state as ST
        failures = await ST.list_failed(limit=15)
    except Exception:
        failures = []

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"❌ <b>{F.fb('FAILURES')}</b>",
        F.DIV,
        "",
    ]

    if not failures:
        lines.append(f"🟢 {F.sc('no failures')}")
        lines.append("")
        lines.append(f"📌 {F.sc('everything is uploading cleanly')}")
    else:
        for i, f_ in enumerate(failures, 1):
            name = str(f_.get("file_name", "?"))[:40]
            src = str(f_.get("source_db", "?"))
            attempts = f_.get("attempts", 0)
            err = str(f_.get("last_error", ""))[:100]

            lines.append(
                f"<b>{i:02d}.</b> {F.EMO['film']} <code>{name}</code>"
            )
            lines.append(
                f"   📁 {F.sc(src)} · "
                f"🔁 attempts <b>{attempts}</b>"
            )
            if err:
                lines.append(f"   ⚠️ <i>{F.sc(err)}</i>")
            lines.append("")

    lines.append(f"🕒 <code>{FM.datetime_()}</code>")

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"🔁 {F.sc('retry all failed')}",
                callback_data=f"{PFX}:retry_failed",
            ),
        ],
        [
            InlineKeyboardButton(
                f"{F.EMO['refresh']} {F.sc('refresh')}",
                callback_data=f"{PFX}:failures",
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
    ])

    return "\n".join(lines)[:4000], kb


# ============================================================
# SECTION 6 — COMMAND
# ============================================================

@Client.on_message(
    filters.command(["backup"]) & filters.private,
    group=-8300,
)
async def cmd_backup(client: Client, message: Message):
    """THE one backup command."""
    if not message.from_user or not _is_admin(message.from_user.id):
        return await message.reply_text(
            f"{F.EMO['cross']} <b>{F.fb('ACCESS DENIED')}</b>\n"
            f"<i>{F.sc('admins only')}</i>",
            parse_mode=ParseMode.HTML,
        )

    text, kb = await _build_main_panel()

    sent = await message.reply_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )

    _register_panel(sent.id, sent.chat.id, "main", text)

    # Start auto-refresh
    _ensure_auto_refresh()


# ============================================================
# SECTION 7 — CALLBACK ROUTER
# ============================================================

@Client.on_callback_query(
    filters.regex(rf"^{PFX}:"),
    group=-8300,
)
async def backup_router(client: Client, q: CallbackQuery):
    """Route every dtvb:* callback."""
    if not q.from_user or not _is_admin(q.from_user.id):
        return await q.answer("❌ Admin only", show_alert=True)

    action = str(q.data).split(":")[1] if ":" in q.data else ""

    try:
        # ────────── CHANNEL MANAGER (delegate) ──────────
        if action == "channels":
            from plugins.backup import channels as CH
            return await CH.open_channels_panel(client, q)

        # ────────── BACK TO MAIN ──────────
        if action in ("back", "refresh"):
            text, kb = await _build_main_panel()
            await _safe_edit(q, text, kb)
            _register_panel(q.message.id, q.message.chat.id, "main", text)
            return await q.answer()

        # ────────── START ──────────
        if action == "start":
            try:
                from plugins.backup import worker as WK
                ok = await WK.start_worker(owner=q.from_user.id)
                await q.answer(
                    "▶️ Backup started" if ok else "⚠️ Already running",
                )
            except Exception as e:
                logger.exception(f"[BACKUP] start: {e}")
                await q.answer(f"❌ {type(e).__name__}", show_alert=True)
                return
            text, kb = await _build_main_panel()
            await _safe_edit(q, text, kb)
            _ensure_auto_refresh()
            return

        # ────────── PAUSE ──────────
        if action == "pause":
            try:
                from plugins.backup import worker as WK
                ok = WK.pause_worker()
                await q.answer("⏸️ Paused" if ok else "⚠️ Not running")
            except Exception as e:
                await q.answer(f"❌ {type(e).__name__}", show_alert=True)
                return
            text, kb = await _build_main_panel()
            await _safe_edit(q, text, kb)
            return

        # ────────── RESUME ──────────
        if action == "resume":
            try:
                from plugins.backup import worker as WK
                ok = WK.resume_worker()
                await q.answer("▶️ Resumed" if ok else "⚠️ Not paused")
            except Exception as e:
                await q.answer(f"❌ {type(e).__name__}", show_alert=True)
                return
            text, kb = await _build_main_panel()
            await _safe_edit(q, text, kb)
            return

        # ────────── STOP ──────────
        if action == "stop":
            try:
                from plugins.backup import worker as WK
                ok = WK.stop_worker()
                await q.answer("⏹️ Stopping…" if ok else "⚠️ Not running")
            except Exception as e:
                await q.answer(f"❌ {type(e).__name__}", show_alert=True)
                return
            text, kb = await _build_main_panel()
            await _safe_edit(q, text, kb)
            return

        # ────────── STATUS ──────────
        if action == "status":
            text, kb = await _build_status_panel()
            await _safe_edit(q, text, kb)
            _register_panel(q.message.id, q.message.chat.id, "status", text)
            return await q.answer()

        # ────────── HISTORY ──────────
        if action == "history":
            text, kb = await _build_history_panel()
            await _safe_edit(q, text, kb)
            _register_panel(q.message.id, q.message.chat.id, "history", text)
            return await q.answer()

        # ────────── FAILURES ──────────
        if action == "failures":
            text, kb = await _build_failures_panel()
            await _safe_edit(q, text, kb)
            _register_panel(q.message.id, q.message.chat.id, "failures", text)
            return await q.answer()

        # ────────── RETRY FAILED ──────────
        if action == "retry_failed":
            try:
                from plugins.backup import state as ST
                from plugins.backup import worker as WK

                n = await ST.reset_failed()
                await q.answer(f"🔁 {n} queued for retry")

                if n > 0:
                    await WK.start_worker(owner=q.from_user.id)
            except Exception as e:
                await q.answer(f"❌ {type(e).__name__}", show_alert=True)
                return

            text, kb = await _build_main_panel()
            await _safe_edit(q, text, kb)
            return

        # ────────── RECONCILE ──────────
        if action == "reconcile":
            await q.answer("♻️ Reconciling…")
            try:
                from plugins.backup import reconcile as RC
                result = await RC.reconcile_all(client=client)
                await q.message.reply_text(
                    "\n".join([
                        f"{F.EMO['check']} <b>{F.fb('RECONCILE DONE')}</b>",
                        F.DIV,
                        "",
                        f"🔍 {F.sc('scanned')} · "
                        f"<b>{FM.num(result.get('scanned', 0))}</b>",
                        f"✅ {F.sc('recovered')} · "
                        f"<b>{FM.num(result.get('recovered', 0))}</b>",
                        f"⏳ {F.sc('still pending')} · "
                        f"<b>{FM.num(result.get('pending', 0))}</b>",
                    ]),
                    parse_mode=ParseMode.HTML,
                )
            except Exception as e:
                logger.exception(f"[BACKUP] reconcile: {e}")
                await q.message.reply_text(
                    f"❌ {F.sc('reconcile failed')}: "
                    f"<code>{type(e).__name__}</code>",
                    parse_mode=ParseMode.HTML,
                )
            return

        # ────────── RESET ──────────
        if action == "reset":
            try:
                from plugins.backup import reset as RS
                return await RS.open_reset_panel(client, q)
            except Exception as e:
                logger.exception(f"[BACKUP] reset: {e}")
                await q.answer(f"❌ {type(e).__name__}", show_alert=True)
                return

        # ────────── CLOSE ──────────
        if action == "close":
            _unregister_panel(q.message.id)
            try:
                await q.message.delete()
            except Exception:
                pass
            return await q.answer("Closed")

        # ────────── UNKNOWN ──────────
        await q.answer("❓ Unknown", show_alert=True)

    except Exception as e:
        logger.exception(f"[BACKUP] router: {e}")
        try:
            await q.answer(f"❌ {type(e).__name__}", show_alert=True)
        except Exception:
            pass


# ============================================================
# SECTION 8 — TEXT INPUT DELEGATION
# ============================================================

@Client.on_message(
    filters.private & filters.text & ~filters.regex(r"^/"),
    group=-8290,
)
async def backup_text_input(client: Client, message: Message):
    """Route text input to channels.py (add/rename)."""
    if not message.from_user:
        return
    try:
        from plugins.backup import channels as CH
        handled = await CH.text_handler(client, message)
        if handled:
            try:
                message.stop_propagation()
            except Exception:
                pass
    except Exception as e:
        logger.debug(f"[BACKUP] text: {e}")


# ============================================================
# SECTION 9 — AUTO REFRESH
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
    """Refresh every open panel every 5s (only if worker is active)."""
    while True:
        try:
            await asyncio.sleep(AUTO_REFRESH_SEC)

            if not _panels:
                continue

            # Check if worker is running
            running = False
            try:
                from plugins.backup import worker as WK
                running = WK.status().get("running", False)
            except Exception:
                pass

            # Only auto-refresh main panel when worker is active
            if not running:
                continue

            from core.client import client as C
            if C is None:
                continue

            for msg_id, panel in list(_panels.items()):
                if panel.get("page") != "main":
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
                    if "not modified" in str(e).lower():
                        continue
                    if "message to edit not found" in str(e).lower():
                        _unregister_panel(msg_id)
                        continue

        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.debug(f"[BACKUP] auto-refresh: {e}")


# ============================================================
# SECTION 10 — PUBLIC: OPEN PANEL FOR ADMIN
# ============================================================

async def open_panel_for_admin(client: Client, message: Message) -> None:
    """
    Called from /admin panel when user taps [💾 BACKUP].
    Opens the same /backup panel.
    """
    try:
        text, kb = await _build_main_panel()
        sent = await message.reply_text(
            text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        _register_panel(sent.id, sent.chat.id, "main", text)
        _ensure_auto_refresh()
    except Exception as e:
        logger.exception(f"[BACKUP] open panel: {e}")


# ============================================================
# SECTION 11 — HELPERS
# ============================================================

async def _safe_edit(q: CallbackQuery, text: str, kb) -> None:
    try:
        await q.message.edit_text(
            text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        if "not modified" in str(e).lower():
            return
        logger.debug(f"[BACKUP] edit: {e}")


# ============================================================
# SECTION 12 — SNAPSHOT
# ============================================================

def snapshot() -> Dict[str, Any]:
    return {
        "panels": len(_panels),
        "auto_refresh": bool(
            _refresh_task and not _refresh_task.done()
        ),
    }


# ============================================================
# PUBLIC EXPORTS
# ============================================================

__all__ = [
    "cmd_backup",
    "open_panel_for_admin",
    "snapshot",
]
