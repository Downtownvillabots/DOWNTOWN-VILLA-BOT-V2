# ============================================================
# 🏨 DOWNTOWN VILLA — ADMIN MAIN ROUTER
# ============================================================
#
# ONE command: /admin
# Everything else is buttons inside.

#Menu:
#   📊 Dashboard        → live metrics
#   🗄️ Databases        → browse / clear / delete
#   🖥️ Server           → CPU / RAM / disk / net
#   📋 Tasks            → active task registry
#   🧾 Logs             → memory log stream
#   📈 Stats            → bot usage
#   ❤️ Health           → system health
#   💾 Backup           → backup panel
#   📚 Indexing         → indexing panel
#   📢 Broadcast        → broadcast panel
#   💎 Premium          → premium mgmt
#   📅 OTT              → weekly releases
#   🔎 Missing          → missing finder
#   🎯 Flow Editor      → search flow
#   👥 Groups           → group settings
#   🛠️ Maintenance      → toggle
#   ⚙️ Settings         → settings shortcuts
#   🔍 PM SEARCH        → pm settings
#
# Every panel has ❌ CANCEL button.
#
# ============================================================

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Dict, Optional

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from core import config
from core import rocket
from utils import fonts as F
from utils import format as FM
from utils import progress as P
from plugins.broadcast import panel as broadcast_panel

logger = logging.getLogger(__name__)


# ============================================================
# SECTION 1 — AUTH
# ============================================================

def is_admin(user_id: Optional[int]) -> bool:
    if user_id is None:
        return False
    try:
        return int(user_id) in [int(a) for a in config.ADMINS]
    except Exception:
        return False


# ============================================================
# SECTION 2 — CALLBACK PREFIX
# ============================================================

PFX = "adm"


def cb(*parts) -> str:
    """Build an admin callback string."""
    return ":".join([PFX] + [str(p) for p in parts])


# ============================================================
# SECTION 2b — LIVE REFRESH OPTIONS (NEW)
# ============================================================

REFRESH_OPTIONS = [
    (3,    "3s"),
    (5,    "5s"),
    (10,   "10s"),
    (15,   "15s"),
    (30,   "30s"),
    (60,   "1m"),
    (300,  "5m"),
    (1800, "30m"),
    (0,    "OFF"),
]
DEFAULT_REFRESH = 5

# chat_id → seconds between refreshes (0 = off)
_live_intervals: Dict[int, int] = {}


def _get_interval(chat_id: int) -> int:
    return _live_intervals.get(int(chat_id), DEFAULT_REFRESH)


def _set_interval(chat_id: int, seconds: int) -> None:
    _live_intervals[int(chat_id)] = max(0, int(seconds))


# ============================================================
# SECTION 3 — LIVE PANEL REGISTRY
# ============================================================

# panel_id → {chat_id, message_id, page, last_text, created, builder}
_panels: Dict[int, Dict[str, Any]] = {}


def register_panel(
    message_id: int,
    chat_id: int,
    page: str,
    text: str,
    builder: Optional[Callable] = None,
) -> None:
    _panels[message_id] = {
        "chat_id": chat_id,
        "message_id": message_id,
        "page": page,
        "last_text": text,
        "created": time.time(),
        "builder": builder,
    }


def unregister_panel(message_id: int) -> None:
    _panels.pop(message_id, None)
    _panel_revisions[message_id] = _panel_revisions.get(message_id, 0) + 1
    _last_refresh.pop(message_id, None)


async def suspend_panel(message_id: int) -> None:
    lock = _panel_locks.setdefault(message_id, asyncio.Lock())
    async with lock:
        unregister_panel(message_id)


def active_panel_count() -> int:
    return len(_panels)


# ============================================================
# SECTION 3b — PAGE BUILDERS (NEW)
# ============================================================

def _build_page_builder(page: str, chat_id: int = 0) -> Optional[Callable]:
    """Return an async builder for a page. None = static."""
    if page == "main":
        async def _main():
            return _render_main(chat_id)
        return _main
    if page == "dashboard":
        from plugins.admin import dashboard as D
        return D.build
    if page == "databases":
        from plugins.admin import databases as DB_
        return DB_.build_index
    if page == "server":
        from plugins.admin import server as SV
        return SV.build
    if page == "tasks":
        from plugins.admin import tasks as T
        return T.build
    if page == "logs":
        from plugins.admin import logs as L
        return L.build
    if page == "stats":
        from plugins.admin import stats as S
        return S.build
    if page == "health":
        from plugins.admin import health as H
        return H.build
    if page == "sparkline":
        from plugins.admin import sparkline as SP
        return SP.build
    if page == "flow":
        from plugins.admin import flow as FLW
        return FLW.build   
    if page == "groups":
        from plugins.groups import admin_list as GAL
        return GAL.build
        
    return None


# ============================================================
# SECTION 3c — REFRESH PICKER (NEW)
# ============================================================

def _render_refresh_page(chat_id: int) -> tuple:
    secs = _get_interval(chat_id)
    text = "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"🔄 <b>{F.fb('LIVE REFRESH')}</b>",
        F.DIV, "",
        f"⚙️ {F.sc('current')} · "
        f"<b>{'🔴 OFF' if secs == 0 else f'🟢 {secs}s'}</b>",
        "",
        f"📌 {F.sc('how often every open panel refreshes')}",
        f"📌 {F.sc('applies to all live pages below')}",
        f"   • dashboard · databases · server · tasks",
        f"   • logs · stats · health · sparkline",
        "",
        F.DIV_S,
        f"📌 {F.sc('tap a value below')}",
    ])
    return text, _refresh_kb(chat_id)


def _refresh_kb(chat_id: int) -> InlineKeyboardMarkup:
    current = _get_interval(chat_id)
    rows = []
    row = []
    for secs, label in REFRESH_OPTIONS:
        mark = "✅ " if secs == current else ""
        row.append(InlineKeyboardButton(
            f"{mark}{label}",
            callback_data=f"adm:refresh:{secs}",
        ))
        if len(row) == 5:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data=cb("home"),
        ),
        InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('close')}",
            callback_data=cb("close"),
        ),
    ])
    return InlineKeyboardMarkup(rows)


@Client.on_callback_query(
    filters.regex(r"^adm:refresh:\d+$"),
    group=-9510,
)
async def set_refresh_interval(client: Client, q: CallbackQuery):
    if not q.from_user or not is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)

    try:
        secs = int(str(q.data).split(":")[2])
    except (ValueError, IndexError):
        return await q.answer("❌")

    chat_id = q.message.chat.id
    _set_interval(chat_id, secs)

    label = "OFF" if secs == 0 else f"{secs}s"
    await q.answer(f"🔄 {label}")

    text, kb = _render_refresh_page(chat_id)
    await _safe_edit(q, text, kb)
    register_panel(q.message.id, chat_id, "refresh", text, builder=None)
    ensure_live()


# ============================================================
# SECTION 4 — MAIN MENU
# ============================================================

def _quick_stats() -> Dict[str, Any]:
    """Gather tiny stats for the header."""
    out = {
        "admins": len(config.ADMINS),
        "uptime": 0.0,
        "panels": active_panel_count(),
        "tasks": 0,
        "cache": 0,
        "flows": 0,
    }

    try:
        from utils import cache as CA
        out["cache"] = CA.cache.total_entries()
    except Exception:
        pass

    try:
        from core.client import client as _c
        if _c is not None and getattr(_c, "started_at", None):
            out["uptime"] = time.time() - _c.started_at
    except Exception:
        pass

    try:
        from core.flow_engine import list_flows
        out["flows"] = len(list_flows())
    except Exception:
        pass

    return out


def _render_main(chat_id: int = 0) -> tuple:
    """Build main admin panel text + keyboard."""
    s = _quick_stats()
    secs = _get_interval(chat_id)
    interval_label = "🔴 OFF" if secs == 0 else f"🟢 {secs}s"

    text = "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"{F.EMO['gear']} <b>{F.fb('ADMIN CONTROL CENTER')}</b>",
        F.DIV, "",
        f"{F.EMO['clock']} {F.sc('uptime')} · "
        f"<b>{FM.duration_short(s['uptime'])}</b>",
        f"{F.EMO['crown']} {F.sc('admins')} · <b>{s['admins']}</b>",
        f"{F.EMO['bar']} {F.sc('panels')} · <b>{s['panels']}</b>",
        f"{F.EMO['package']} {F.sc('cache')} · <b>{FM.num(s['cache'])}</b>",
        f"{F.EMO['spark']} {F.sc('flows')} · <b>{s.get('flows', 0)}</b>",
        "",
        f"🔄 {F.sc('live')} · <b>{interval_label}</b>",
        "",
        F.DIV_S,
        "",
        f"📌 {F.sc('choose a section below')}",
        f"📌 {F.sc('everything is live')}",
    ])

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"{F.EMO['bar']} {F.sc('dashboard')}",
                callback_data=cb("page", "dashboard"),
            ),
            InlineKeyboardButton(
                f"{F.EMO['db']} {F.sc('databases')}",
                callback_data=cb("page", "databases"),
            ),
        ],
        [
            InlineKeyboardButton(
                f"{F.EMO['server']} {F.sc('server')}",
                callback_data=cb("page", "server"),
            ),
            InlineKeyboardButton(
                f"{F.EMO['rocket']} {F.sc('tasks')}",
                callback_data=cb("page", "tasks"),
            ),
        ],
        [
            InlineKeyboardButton(
                f"{F.EMO['file']} {F.sc('logs')}",
                callback_data=cb("page", "logs"),
            ),
            InlineKeyboardButton(
                f"{F.EMO['chart']} {F.sc('stats')}",
                callback_data=cb("page", "stats"),
            ),
        ],
        [
            InlineKeyboardButton(
                f"❤️ {F.sc('health')}",
                callback_data=cb("page", "health"),
            ),
            InlineKeyboardButton(
                f"{F.EMO['spark']} {F.sc('sparkline')}",
                callback_data=cb("page", "sparkline"),
            ),
        ],
        [
            InlineKeyboardButton(
                f"💾 {F.sc('backup')}",
                callback_data=cb("mod", "backup"),
            ),
            InlineKeyboardButton(
                f"📚 {F.sc('indexing')}",
                callback_data=cb("mod", "indexing"),
            ),
        ],
        [
            InlineKeyboardButton(
                f"📢 {F.sc('broadcast')}",
                callback_data=cb("mod", "broadcast"),
            ),
            InlineKeyboardButton(
                f"💎 {F.sc('premium')}",
                callback_data=cb("mod", "premium"),
            ),
        ],
        [
            InlineKeyboardButton(
                f"📅 {F.sc('ott')}",
                callback_data=cb("mod", "ott"),
            ),
            InlineKeyboardButton(
                f"🔎 {F.sc('missing')}",
                callback_data=cb("mod", "missing"),
            ),
        ],
        [
            InlineKeyboardButton(
                f"🔍 {F.sc('pm search')}",
                callback_data=cb("mod", "pmsearch"),
            ),
        ],
        [
            InlineKeyboardButton(
                f"🎯 {F.sc('flow editor')}",
                callback_data=cb("page", "flow"),
            ),
            InlineKeyboardButton(
                f"👥 {F.sc('groups')}",
                callback_data=cb("page", "groups"),
            ),
        ],
        [
            InlineKeyboardButton(
                f"🛠️ {F.sc('maintenance')}",
                callback_data=cb("page", "maintenance"),
            ),
        ],
        [
            InlineKeyboardButton(
                f"⚙️ {F.sc('settings')}",
                callback_data=cb("page", "settings"),
            ),
            InlineKeyboardButton(
                f"🔄 {F.sc('refresh')} · {interval_label}",
                callback_data=cb("page", "refresh"),
            ),
        ],
        [
            InlineKeyboardButton(
                f"{F.EMO['refresh']} {F.sc('refresh now')}",
                callback_data=cb("home"),
            ),
            InlineKeyboardButton(
                f"{F.EMO['cross']} {F.sc('close')}",
                callback_data=cb("close"),
            ),
        ],
    ])

    return text, kb


# ============================================================
# SECTION 5 — COMMAND
# ============================================================

@Client.on_message(
    filters.command(["admin", "panel"]) & filters.private,
    group=-9500,
)
async def cmd_admin(client: Client, message: Message):
    """Open the admin panel."""
    if not message.from_user or not is_admin(message.from_user.id):
        return await message.reply_text(
            f"{F.EMO['cross']} <b>{F.fb('ACCESS DENIED')}</b>\n"
            f"<i>{F.sc('admins only')}</i>",
            parse_mode=ParseMode.HTML,
        )

    chat_id = message.chat.id
    with rocket.timer("admin.open", log=False):
        text, kb = _render_main(chat_id)

    sent = await message.reply_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )

    register_panel(
        sent.id, sent.chat.id, "main", text,
        builder=_build_page_builder("main", chat_id),
    )
    ensure_live()


# ============================================================
# SECTION 6 — SUB-ROUTERS (priority -9510, run BEFORE main)
# ============================================================

# ── DATABASES (adm:db_*) ──

@Client.on_callback_query(
    filters.regex(r"^adm:db_"), group=-9510,
)
async def admin_db_router(client: Client, q: CallbackQuery):
    if not q.from_user or not is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)

    from plugins.admin import databases as DB

    parts = str(q.data).split(":")
    action = parts[1] if len(parts) > 1 else ""

    try:
        # ── POOL ──
        if action == "db_pool":
            pool = parts[2] if len(parts) > 2 else ""
            text, kb = await DB.build_pool(pool)
            await _safe_edit(q, text, kb)
            return await q.answer()

        # ── SHARD ──
        if action == "db_shard":
            pool = parts[2] if len(parts) > 2 else ""
            idx = int(parts[3]) if len(parts) > 3 else 0
            text, kb = await DB.build_shard(pool, idx)
            await _safe_edit(q, text, kb)
            return await q.answer()

        # ── CLEAR SHARD → step 1 ──
        if action == "db_clear_shard":
            pool = parts[2]
            idx = int(parts[3])
            text, kb = DB.build_clear_shard_confirm(pool, idx, step=1)
            await _safe_edit(q, text, kb)
            return await q.answer("⚠️")

        # ── CLEAR POOL → step 1 ──
        if action == "db_clear_pool":
            pool = parts[2]
            text, kb = DB.build_clear_pool_confirm(pool, step=1)
            await _safe_edit(q, text, kb)
            return await q.answer("⚠️")

        # ── NUKE ALL → step 1 ──
        if action == "db_nuke_all":
            text, kb = DB.build_nuke_all_confirm(step=1)
            await _safe_edit(q, text, kb)
            return await q.answer("☢️")

        # ── CONFIRM (advance the token) ──
        if action == "db_confirm":
            token = parts[2] if len(parts) > 2 else ""
            confirm = DB._get_confirm(token)
            if not confirm:
                return await q.answer("⏱️ Expired", show_alert=True)

            kind = confirm.get("kind")
            step = int(confirm.get("step", 1))

            # Advance step
            DB._advance_confirm(token)

            # ── SHARD ──
            if kind == "shard":
                pool = confirm.get("pool")
                idx = int(confirm.get("index", 0))
                if step < 3:
                    text, kb = DB.build_clear_shard_confirm(
                        pool, idx, step=step + 1
                    )
                    await _safe_edit(q, text, kb)
                    DB._drop_confirm(token)
                    return await q.answer(f"⚠️ Step {step + 1}/3")

                DB._drop_confirm(token)
                await q.answer("🗑️ Wiping…")
                result = await DB.do_clear_shard(pool, idx)
                text, kb = DB.build_result_card(
                    "SHARD CLEARED", result,
                    back_cb=f"adm:db_shard:{pool}:{idx}",
                )
                await _safe_edit(q, text, kb)
                return

            # ── POOL ──
            if kind == "pool":
                pool = confirm.get("pool")
                if step < 3:
                    text, kb = DB.build_clear_pool_confirm(
                        pool, step=step + 1
                    )
                    await _safe_edit(q, text, kb)
                    DB._drop_confirm(token)
                    return await q.answer(f"⚠️ Step {step + 1}/3")

                DB._drop_confirm(token)
                await q.answer("🗑️ Wiping pool…")
                result = await DB.do_clear_pool(pool)
                text, kb = DB.build_result_card(
                    "POOL CLEARED", result,
                    back_cb=f"adm:db_pool:{pool}",
                )
                await _safe_edit(q, text, kb)
                return

            # ── NUKE ──
            if kind == "nuke":
                if step < 10:
                    text, kb = DB.build_nuke_all_confirm(step=step + 1)
                    await _safe_edit(q, text, kb)
                    DB._drop_confirm(token)
                    return await q.answer(f"☢️ {step + 1}/10")

                DB._drop_confirm(token)
                await q.answer("💀 NUKE IN PROGRESS…")
                result = await DB.do_nuke_all()
                text, kb = DB.build_result_card(
                    "ALL DATA NUKE", result,
                    back_cb="adm:page:databases",
                )
                await _safe_edit(q, text, kb)
                return

            return await q.answer("❓ Unknown kind")

        # ── CANCEL ──
        if action == "db_cancel":
            token = parts[2] if len(parts) > 2 else ""
            DB._drop_confirm(token)
            text, kb = await DB.build_index()
            await _safe_edit(q, text, kb)
            return await q.answer("❌ Cancelled")

    except Exception as e:
        logger.exception(f"[ADMIN] db router: {e}")
        try:
            await q.answer(f"❌ {type(e).__name__}", show_alert=True)
        except Exception:
            pass


# ── SERVER (adm:sv:*) ──

@Client.on_callback_query(
    filters.regex(r"^adm:sv:"), group=-9510,
)
async def admin_sv_router(client: Client, q: CallbackQuery):
    if not q.from_user or not is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)

    try:
        from plugins.admin import server as SV

        parts = str(q.data).split(":")
        page = parts[2] if len(parts) > 2 else "overview"
        arg = parts[3] if len(parts) > 3 else None

        text, kb = await SV.route(page, arg)
        await _safe_edit(q, text, kb)

        async def _b(_p=page, _a=arg):
            return await SV.route(_p, _a)
        register_panel(q.message.id, q.message.chat.id,
                       f"server:{page}", text, builder=_b)
        ensure_live()
        await q.answer()
    except Exception as e:
        logger.exception(f"[ADMIN] sv router: {e}")
        try:
            await q.answer(f"❌ {type(e).__name__}", show_alert=True)
        except Exception:
            pass


# ── LOGS (adm:lg:*) ──

@Client.on_callback_query(
    filters.regex(r"^adm:lg:"), group=-9510,
)
async def admin_lg_router(client: Client, q: CallbackQuery):
    if not q.from_user or not is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)

    try:
        from plugins.admin import logs as LG

        parts = str(q.data).split(":")
        action = parts[2] if len(parts) > 2 else ""

        # ── FILTER ──
        if action == "filter":
            key = parts[3] if len(parts) > 3 else ""
            val = parts[4] if len(parts) > 4 else ""
            LG._set_filter(key, val)
            LG._set_filter("page", 0)
            text, kb = await LG.build()
            await _safe_edit(q, text, kb)
            register_panel(q.message.id, q.message.chat.id,
                           "logs", text, builder=LG.build)
            ensure_live()
            return await q.answer(f"✅ {key}={val}")

        # ── PAGE ──
        if action == "page":
            try:
                page = int(parts[3])
            except (ValueError, IndexError):
                page = 0
            LG._set_filter("page", page)
            text, kb = await LG.build()
            await _safe_edit(q, text, kb)
            register_panel(q.message.id, q.message.chat.id,
                           "logs", text, builder=LG.build)
            return await q.answer()

        # ── REFRESH ──
        if action == "refresh":
            text, kb = await LG.build()
            await _safe_edit(q, text, kb)
            register_panel(q.message.id, q.message.chat.id,
                           "logs", text, builder=LG.build)
            return await q.answer()

        # ── RESET FILTERS ──
        if action == "reset":
            LG._reset_filters()
            text, kb = await LG.build()
            await _safe_edit(q, text, kb)
            register_panel(q.message.id, q.message.chat.id,
                           "logs", text, builder=LG.build)
            return await q.answer("♻️ Reset")

        # ── SEARCH ──
        if action == "search":
            text = "\n".join([
                f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                f"{F.EMO['search']} <b>{F.fb('SEARCH LOGS')}</b>",
                F.DIV, "",
                f"📌 {F.sc('send a keyword to search')}",
                "",
                f"📌 {F.sc('send')} <code>-</code> {F.sc('to clear search')}",
            ])
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"{F.EMO['cross']} {F.sc('cancel')}",
                    callback_data="adm:lg:refresh",
                ),
            ]])
            await _safe_edit(q, text, kb)
            unregister_panel(q.message.id)
            return await q.answer()

        # ── EXPORT ──
        if action == "export":
            bio = await LG.export_logs()
            if not bio:
                return await q.answer("⚠️ No logs", show_alert=True)
            try:
                await client.send_document(
                    chat_id=q.from_user.id,
                    document=bio,
                    caption=f"{F.EMO['file']} <b>Logs export</b>",
                    parse_mode=ParseMode.HTML,
                )
                await q.answer("📤 Sent to PM")
            except Exception as e:
                await q.answer(f"❌ {type(e).__name__}", show_alert=True)
            return

        # ── CONFIRM CLEAR ──
        if action == "confirm_clear":
            text, kb = await LG.build_clear_confirm()
            await _safe_edit(q, text, kb)
            unregister_panel(q.message.id)
            return await q.answer("⚠️")

        # ── DO CLEAR ──
        if action == "do_clear":
            try:
                from core import logger as CL
                CL.clear_logs()
                await q.answer("🗑️ Cleared")
            except Exception:
                await q.answer("❌")
            text, kb = await LG.build()
            await _safe_edit(q, text, kb)
            register_panel(q.message.id, q.message.chat.id,
                           "logs", text, builder=LG.build)
            return

    except Exception as e:
        logger.exception(f"[ADMIN] lg router: {e}")
        try:
            await q.answer(f"❌ {type(e).__name__}", show_alert=True)
        except Exception:
            pass


# ── STATS (adm:st:*) ──

@Client.on_callback_query(
    filters.regex(r"^adm:st:"), group=-9510,
)
async def admin_st_router(client: Client, q: CallbackQuery):
    if not q.from_user or not is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)

    try:
        from plugins.admin import stats as ST

        parts = str(q.data).split(":")
        action = parts[2] if len(parts) > 2 else ""

        # ── VIEW ──
        if action == "view":
            sub = parts[3] if len(parts) > 3 else ""
            if sub == "users":
                text, kb = await ST.build_top_users()
                async def _b(): return await ST.build_top_users()
            else:
                text, kb = await ST.build()
                async def _b(): return await ST.build()
            await _safe_edit(q, text, kb)
            register_panel(q.message.id, q.message.chat.id,
                           "stats", text, builder=_b)
            ensure_live()
            return await q.answer()

        # ── CONFIRM RESET ──
        if action == "confirm_reset":
            text, kb = await ST.build_reset_confirm()
            await _safe_edit(q, text, kb)
            unregister_panel(q.message.id)
            return await q.answer("⚠️")

        # ── DO RESET ──
        if action == "do_reset":
            try:
                ST.do_reset()
                await q.answer("♻️ Reset")
            except Exception:
                await q.answer("❌")
            text, kb = await ST.build()
            await _safe_edit(q, text, kb)
            register_panel(q.message.id, q.message.chat.id,
                           "stats", text, builder=ST.build)
            return

    except Exception as e:
        logger.exception(f"[ADMIN] st router: {e}")
        try:
            await q.answer(f"❌ {type(e).__name__}", show_alert=True)
        except Exception:
            pass


# ── TASKS (adm:tk:*) ──

@Client.on_callback_query(
    filters.regex(r"^adm:tk:"), group=-9510,
)
async def admin_tk_router(client: Client, q: CallbackQuery):
    if not q.from_user or not is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)

    try:
        from plugins.admin import tasks as TK

        parts = str(q.data).split(":")
        action = parts[2] if len(parts) > 2 else ""

        # ── FILTER ──
        if action == "filter":
            key = parts[3] if len(parts) > 3 else ""
            val = parts[4] if len(parts) > 4 else ""
            TK._set_filter(key, val)
            text, kb = await TK.build()
            await _safe_edit(q, text, kb)
            register_panel(q.message.id, q.message.chat.id,
                           "tasks", text, builder=TK.build)
            ensure_live()
            return await q.answer(f"✅ {key}={val}")

        # ── REFRESH ──
        if action == "refresh":
            text, kb = await TK.build()
            await _safe_edit(q, text, kb)
            register_panel(q.message.id, q.message.chat.id,
                           "tasks", text, builder=TK.build)
            return await q.answer()

        # ── CLEAR DONE ──
        if action == "clear_done":
            n = TK._clear_finished()
            await q.answer(f"🗑️ Cleared {n}")
            text, kb = await TK.build()
            await _safe_edit(q, text, kb)
            register_panel(q.message.id, q.message.chat.id,
                           "tasks", text, builder=TK.build)
            return

        # ── DETAIL ──
        if action == "detail":
            tid = parts[3] if len(parts) > 3 else ""
            text, kb = await TK.build_task_detail(tid)
            await _safe_edit(q, text, kb)
            unregister_panel(q.message.id)
            return await q.answer()

        # ── CONFIRM CANCEL ──
        if action == "confirm_cancel":
            tid = parts[3] if len(parts) > 3 else ""
            text, kb = await TK.build_cancel_confirm(tid)
            await _safe_edit(q, text, kb)
            unregister_panel(q.message.id)
            return await q.answer("⚠️")

        # ── DO CANCEL ──
        if action == "do_cancel":
            tid = parts[3] if len(parts) > 3 else ""
            ok = await TK.cancel_task(tid)
            await q.answer("🛑 Cancelled" if ok else "⚠️ Failed")
            text, kb = await TK.build()
            await _safe_edit(q, text, kb)
            register_panel(q.message.id, q.message.chat.id,
                           "tasks", text, builder=TK.build)
            return

    except Exception as e:
        logger.exception(f"[ADMIN] tk router: {e}")
        try:
            await q.answer(f"❌ {type(e).__name__}", show_alert=True)
        except Exception:
            pass


# ============================================================
# SECTION 7 — MAIN CALLBACK ROUTER
# ============================================================

@Client.on_callback_query(
    filters.regex(rf"^{PFX}:"),
    group=-9500,
)
async def admin_router(client: Client, q: CallbackQuery):
    if not q.from_user or not is_admin(q.from_user.id):
        return await q.answer("❌ Admin only", show_alert=True)

    parts = str(q.data).split(":")
    action = parts[1] if len(parts) > 1 else ""

    # These callback namespaces are handled by their dedicated routers.
    if action.startswith(("dbc_", "db_", "sv", "lg", "st", "tk")):
        return

    # ────────── HOME ──────────
    if action == "home":
        chat_id = q.message.chat.id
        text, kb = _render_main(chat_id)
        await _safe_edit(q, text, kb)
        register_panel(q.message.id, chat_id, "main", text,
                       builder=_build_page_builder("main", chat_id))
        ensure_live()
        return await q.answer()

    # ────────── CLOSE ──────────
    if action == "close":
        unregister_panel(q.message.id)
        try:
            await q.message.delete()
        except Exception:
            pass
        return await q.answer("Closed")

    # ────────── PAGE ──────────
    if action == "page":
        page = parts[2] if len(parts) > 2 else "dashboard"
        return await _open_page(client, q, page)

    # ────────── MODULE ──────────
    if action == "mod":
        module = parts[2] if len(parts) > 2 else ""
        return await _open_module(client, q, module)

    # ────────── CANCEL ──────────
    if action == "cancel":
        unregister_panel(q.message.id)
        try:
            await q.message.delete()
        except Exception:
            pass
        return await q.answer("❌ Cancelled")

    return await q.answer("❓ Unknown", show_alert=True)


# ============================================================
# SECTION 8 — PAGE OPENER
# ============================================================

async def _open_page(client: Client, q: CallbackQuery, page: str) -> None:
    """Dispatch to the right page builder."""
    try:
        chat_id = q.message.chat.id

        # Refresh picker
        if page == "refresh":
            text, kb = _render_refresh_page(chat_id)
            await _safe_edit(q, text, kb)
            register_panel(q.message.id, chat_id, "refresh",
                           text, builder=None)
            ensure_live()
            return await q.answer()

        # Try live builder
        builder = _build_page_builder(page, chat_id)
        if builder is not None:
            text, kb = await builder()
            await _safe_edit(q, text, kb)
            register_panel(q.message.id, chat_id, page, text,
                           builder=builder)
            ensure_live()
            return await q.answer()

        # Static pages
        if page == "flow":
            text = "\n".join([
                f"{F.EMO['spark']} <b>{F.fb('FLOW EDITOR')}</b>",
                F.DIV, "",
                f"📌 {F.sc('use /flow to edit')}",
                f"📌 {F.sc('or tap a flow below')}",
            ])
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"{F.EMO['back']} {F.sc('back')}",
                    callback_data=cb("home"),
                ),
                InlineKeyboardButton(
                    f"{F.EMO['cross']} {F.sc('close')}",
                    callback_data=cb("close"),
                ),
            ]])
        elif page == "groups":
            text = "\n".join([
                f"{F.EMO['users']} <b>{F.fb('GROUPS')}</b>",
                F.DIV, "",
                f"📌 {F.sc('manage groups from /settings in group')}",
                f"📌 {F.sc('or /flow to edit search flow per group')}",
            ])
            kb = _back_kb()
        elif page == "maintenance":
            text = "\n".join([
                f"🛠️ <b>{F.fb('MAINTENANCE')}</b>",
                F.DIV, "",
                f"📌 {F.sc('current')} · "
                f"{'🟢 ON' if config.MAINTENANCE_MODE else '🔴 OFF'}",
            ])
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    f"{'🔴 ' + F.sc('turn off') if config.MAINTENANCE_MODE else '🟢 ' + F.sc('turn on')}",
                    callback_data=cb("toggle_maint"),
                )],
                [InlineKeyboardButton(
                    f"{F.EMO['back']} {F.sc('back')}",
                    callback_data=cb("home"),
                )],
            ])
        elif page == "settings":
            text = "\n".join([
                f"{F.EMO['gear']} <b>{F.fb('BOT SETTINGS')}</b>",
                F.DIV, "",
                f"{F.EMO['info']} {F.sc('edit settings via env')}",
                f"{F.EMO['info']} {F.sc('use the buttons below for live settings')}",
                "",
                F.DIV_S,
            ])
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    f"👥 {F.sc('group settings')}",
                    callback_data=cb("page", "groups"),
                )],
                [InlineKeyboardButton(
                    f"🎯 {F.sc('flow editor')}",
                    callback_data=cb("page", "flow"),
                )],
                [InlineKeyboardButton(
                    f"💾 {F.sc('backup')}",
                    callback_data=cb("mod", "backup"),
                )],
                [
                    InlineKeyboardButton(
                        f"{F.EMO['back']} {F.sc('back')}",
                        callback_data=cb("home"),
                    ),
                    InlineKeyboardButton(
                        f"{F.EMO['cross']} {F.sc('close')}",
                        callback_data=cb("close"),
                    ),
                ],
            ])
        else:
            text = f"❓ Unknown page: <code>{page}</code>"
            kb = _back_kb()

        await _safe_edit(q, text, kb)
        register_panel(q.message.id, chat_id, page, text, builder=None)

    except Exception as e:
        logger.exception(f"[ADMIN] page {page} failed: {e}")
        try:
            await q.answer(f"❌ {type(e).__name__}", show_alert=True)
        except Exception:
            pass

    try:
        await q.answer()
    except Exception:
        pass


# ============================================================
# SECTION 9 — MODULE OPENER
# ============================================================

async def _open_module(client: Client, q: CallbackQuery, module: str) -> None:
    """Point user to the right command / panel."""
    try:
        if module == "backup":
            from plugins.backup import backup as B
            fn = getattr(B, "open_panel_for_admin", None)
            if fn is not None:
                await fn(client, q.message)
            else:
                await q.answer("Use /backup", show_alert=True)
            return

        if module == "indexing":
            from plugins.indexing import indexing as IDX
            fn = getattr(IDX, "open_panel_for_admin", None)
            if fn is not None:
                await fn(client, q.message)
            else:
                await q.answer("Use /index", show_alert=True)
            return

        if module == "broadcast":
            from plugins.broadcast import panel as P
            fn = getattr(P, "open_panel_for_admin", None)
            if fn is not None:
                await fn(client, q)
            else:
                await q.answer("Broadcast unavailable", show_alert=True)
            return

        if module == "premium":
            from plugins.admin import premium as PA
            fn = getattr(PA, "open_panel_for_admin", None)
            if fn is not None:
                await fn(client, q.message)
            else:
                await q.answer("Premium panel unavailable", show_alert=True)
            return

        if module == "ott":
            from plugins.ott import panel as OTT
            fn = getattr(OTT, "open_panel_for_admin", None)
            if fn is not None:
                await fn(client, q)
            else:
                await q.answer("OTT panel unavailable", show_alert=True)
            return

        if module == "missing":
            from plugins.missing import missing as MS
            fn = getattr(MS, "open_panel_for_admin", None)
            if fn is not None:
                await fn(client, q.message)
            else:
                await q.answer("Use /missing", show_alert=True)
            return

        if module == "pmsearch":
            try:
                from plugins.pm_search import admin as PMA
                fn = getattr(PMA, "open_panel_for_admin", None)
                if fn is not None:
                    await fn(client, q.message)
                else:
                    await q.answer("Use /pmsearch", show_alert=True)
            except Exception as e:
                logger.exception(f"[ADMIN] pmsearch: {e}")
                await q.answer("❌ Failed", show_alert=True)
            return

        await q.answer(f"❓ Unknown module", show_alert=True)
    except ImportError:
        await q.answer(f"Use /{module} command", show_alert=True)
    except Exception as e:
        logger.exception(f"[ADMIN] module {module}: {e}")
        try:
            await q.answer(f"❌ {type(e).__name__}", show_alert=True)
        except Exception:
            pass


# ============================================================
# SECTION 10 — TOGGLES
# ============================================================

@Client.on_callback_query(
    filters.regex(rf"^{PFX}:toggle_maint$"),
    group=-9510,
)
async def toggle_maintenance(client: Client, q: CallbackQuery):
    if not q.from_user or not is_admin(q.from_user.id):
        return await q.answer("❌", show_alert=True)
    try:
        config.MAINTENANCE_MODE = not config.MAINTENANCE_MODE
        await q.answer(
            f"{'🟢 ON' if config.MAINTENANCE_MODE else '🔴 OFF'}"
        )
        await _open_page(client, q, "maintenance")
    except Exception as e:
        await q.answer(f"❌ {e}", show_alert=True)


# ============================================================
# SECTION 11 — HELPERS
# ============================================================

def _back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"{F.EMO['back']} {F.sc('back')}",
                callback_data=cb("home"),
            ),
            InlineKeyboardButton(
                f"{F.EMO['cross']} {F.sc('close')}",
                callback_data=cb("close"),
            ),
        ],
    ])


async def _safe_edit(q: CallbackQuery, text: str, kb) -> None:
    if not q.message:
        return
    message_id = q.message.id
    lock = _panel_locks.setdefault(message_id, asyncio.Lock())
    async with lock:
        _panel_revisions[message_id] = _panel_revisions.get(message_id, 0) + 1
        panel = _panels.get(message_id)
        if panel:
            panel["builder"] = None
            panel["last_text"] = text
        await _safe_edit_unlocked(q, text, kb)


async def _safe_edit_unlocked(q: CallbackQuery, text: str, kb) -> None:
    try:
        await q.message.edit_text(
            text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        msg = str(e).lower()
        if "not modified" in msg:
            return
        logger.debug(f"[ADMIN] edit: {e}")


# ============================================================
# SECTION 12 — LIVE UPDATER (NOW REFRESHES ALL PAGES)
# ============================================================

_live_task: Optional[asyncio.Task] = None
_last_refresh: Dict[int, float] = {}
_panel_revisions: Dict[int, int] = {}
_panel_locks: Dict[int, asyncio.Lock] = {}


async def _live_loop() -> None:
    """
    Refresh every registered panel (any page with a builder)
    at its chat's chosen interval.
    """
    while True:
        try:
            await asyncio.sleep(1.0)

            if not _panels:
                continue

            from core.client import client as _c
            if _c is None:
                continue

            now = time.time()

            for msg_id, panel in list(_panels.items()):
                builder = panel.get("builder")
                if builder is None:
                    continue

                chat_id = panel["chat_id"]
                revision = _panel_revisions.get(msg_id, 0)
                interval = _get_interval(chat_id)
                if interval <= 0:
                    continue

                last = _last_refresh.get(msg_id, 0)
                if now - last < interval:
                    continue
                _last_refresh[msg_id] = now

                try:
                    result = await builder()
                    if not result:
                        continue
                    text, kb = result
                    lock = _panel_locks.setdefault(msg_id, asyncio.Lock())
                    async with lock:
                        if (
                            _panels.get(msg_id) is not panel
                            or _panel_revisions.get(msg_id, 0) != revision
                            or panel.get("builder") is not builder
                        ):
                            continue
                        if text == panel.get("last_text"):
                            continue

                        await _c.edit_message_text(
                            chat_id=chat_id,
                            message_id=msg_id,
                            text=text,
                            reply_markup=kb,
                            parse_mode=ParseMode.HTML,
                            disable_web_page_preview=True,
                        )
                        panel["last_text"] = text
                except Exception as e:
                    err = str(e).lower()
                    if "not modified" in err:
                        continue
                    if "message to edit not found" in err:
                        _panels.pop(msg_id, None)
                        _last_refresh.pop(msg_id, None)
                        continue
                    logger.debug(f"[ADMIN-LIVE] {msg_id}: {e}")

        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.debug(f"[ADMIN-LIVE] loop: {e}")


def ensure_live() -> None:
    global _live_task
    if _live_task and not _live_task.done():
        return
    try:
        loop = asyncio.get_running_loop()
        _live_task = loop.create_task(_live_loop())
        logger.info("[ADMIN-LIVE] started")
    except RuntimeError:
        pass


# ============================================================
# SECTION 13 — SNAPSHOT
# ============================================================

def snapshot() -> Dict[str, Any]:
    return {
        "panels": active_panel_count(),
        "admins": len(config.ADMINS),
        "live_intervals": dict(_live_intervals),
        "live_task_running": bool(
            _live_task and not _live_task.done()
        ),
    }


# ============================================================
# PUBLIC EXPORTS
# ============================================================

__all__ = [
    "cmd_admin",
    "is_admin",
    "register_panel",
    "unregister_panel",
    "suspend_panel",
    "snapshot",
]
