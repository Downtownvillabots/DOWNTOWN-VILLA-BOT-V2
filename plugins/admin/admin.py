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
#   🚫 Ban / Filter     → ban + filter
#   🛠️ Maintenance      → toggle
#   ⚙️ Settings         → bot config
#   🔍 PM SEARCH        → pm settings
#
# Every panel has ❌ CANCEL button.
#
# ============================================================

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Dict, Optional

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
# SECTION 3 — LIVE PANEL REGISTRY
# ============================================================

# panel_id → {chat_id, message_id, page, last_text, created}
_panels: Dict[int, Dict[str, Any]] = {}


def register_panel(message_id: int, chat_id: int, page: str, text: str) -> None:
    _panels[message_id] = {
        "chat_id": chat_id,
        "message_id": message_id,
        "page": page,
        "last_text": text,
        "created": time.time(),
    }


def unregister_panel(message_id: int) -> None:
    _panels.pop(message_id, None)


def active_panel_count() -> int:
    return len(_panels)


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


def _render_main() -> tuple:
    """Build main admin panel text + keyboard."""
    s = _quick_stats()

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
                f"🚫 {F.sc('ban / filter')}",
                callback_data=cb("page", "ban"),
            ),
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
        ],
        [
            InlineKeyboardButton(
                f"{F.EMO['refresh']} {F.sc('refresh')}",
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

    with rocket.timer("admin.open", log=False):
        text, kb = _render_main()

    sent = await message.reply_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )

    register_panel(sent.id, sent.chat.id, "main", text)


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
            return await q.answer()

        # ── REFRESH ──
        if action == "refresh":
            text, kb = await LG.build()
            await _safe_edit(q, text, kb)
            return await q.answer()

        # ── RESET FILTERS ──
        if action == "reset":
            LG._reset_filters()
            text, kb = await LG.build()
            await _safe_edit(q, text, kb)
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
            else:
                text, kb = await ST.build()
            await _safe_edit(q, text, kb)
            return await q.answer()

        # ── CONFIRM RESET ──
        if action == "confirm_reset":
            text, kb = await ST.build_reset_confirm()
            await _safe_edit(q, text, kb)
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
            return await q.answer(f"✅ {key}={val}")

        # ── REFRESH ──
        if action == "refresh":
            text, kb = await TK.build()
            await _safe_edit(q, text, kb)
            return await q.answer()

        # ── CLEAR DONE ──
        if action == "clear_done":
            n = TK._clear_finished()
            await q.answer(f"🗑️ Cleared {n}")
            text, kb = await TK.build()
            await _safe_edit(q, text, kb)
            return

        # ── DETAIL ──
        if action == "detail":
            tid = parts[3] if len(parts) > 3 else ""
            text, kb = await TK.build_task_detail(tid)
            await _safe_edit(q, text, kb)
            return await q.answer()

        # ── CONFIRM CANCEL ──
        if action == "confirm_cancel":
            tid = parts[3] if len(parts) > 3 else ""
            text, kb = await TK.build_cancel_confirm(tid)
            await _safe_edit(q, text, kb)
            return await q.answer("⚠️")

        # ── DO CANCEL ──
        if action == "do_cancel":
            tid = parts[3] if len(parts) > 3 else ""
            ok = await TK.cancel_task(tid)
            await q.answer("🛑 Cancelled" if ok else "⚠️ Failed")
            text, kb = await TK.build()
            await _safe_edit(q, text, kb)
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

    # ────────── HOME ──────────
    if action == "home":
        text, kb = _render_main()
        await _safe_edit(q, text, kb)
        register_panel(q.message.id, q.message.chat.id, "main", text)
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
        if page == "dashboard":
            from plugins.admin import dashboard as D
            text, kb = await D.build()
        elif page == "databases":
            from plugins.admin import databases as DB_
            text, kb = await DB_.build_index()
        elif page == "server":
            from plugins.admin import server as SV
            text, kb = await SV.build()
        elif page == "tasks":
            from plugins.admin import tasks as T
            text, kb = await T.build()
        elif page == "logs":
            from plugins.admin import logs as L
            text, kb = await L.build()
        elif page == "stats":
            from plugins.admin import stats as S
            text, kb = await S.build()
        elif page == "health":
            from plugins.admin import health as H
            text, kb = await H.build()
        elif page == "sparkline":
            from plugins.admin import sparkline as SP
            text, kb = await SP.build()
        elif page == "flow":
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
        elif page == "ban":
            text = "\n".join([
                f"{F.EMO['warn']} <b>{F.fb('BAN / FILTER')}</b>",
                F.DIV, "",
                f"📌 {F.sc('coming soon')}",
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
                f"{F.EMO['info']} {F.sc('or use /flow for search flows')}",
                "",
                F.DIV_S,
                f"{F.EMO['spark']} <b>{F.sc('quick links')}</b>",
                f"• /flow — search flow editor",
                f"• /settings — per-group settings (in group)",
                f"• /backup — backup panel",
            ])
            kb = _back_kb()
        else:
            text = f"❓ Unknown page: <code>{page}</code>"
            kb = _back_kb()

        await _safe_edit(q, text, kb)
        register_panel(q.message.id, q.message.chat.id, page, text)

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
            from plugins.admin import broadcast_panel as BP
            fn = getattr(BP, "open_panel_for_admin", None)
            if fn is not None:
                await fn(client, q)
            else:
                await q.answer("Broadcast panel unavailable", show_alert=True)
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
            from plugins.ott import ott as OTT
            fn = getattr(OTT, "open_panel_for_admin", None)
            if fn is not None:
                await fn(client, q.message)
            else:
                await q.answer("Use /ott", show_alert=True)
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
# SECTION 12 — LIVE UPDATER
# ============================================================

async def _live_loop(interval: float = 5.0) -> None:
    """Refresh every open dashboard panel every N seconds."""
    while True:
        try:
            await asyncio.sleep(interval)
            for panel_id, panel in list(_panels.items()):
                if panel.get("page") != "dashboard":
                    continue
                try:
                    from core.client import client as _c
                    if _c is None:
                        continue
                    from plugins.admin import dashboard as D
                    text, kb = await D.build()
                    if text == panel.get("last_text"):
                        continue
                    await _c.edit_message_text(
                        chat_id=panel["chat_id"],
                        message_id=panel["message_id"],
                        text=text,
                        reply_markup=kb,
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=True,
                    )
                    panel["last_text"] = text
                except Exception:
                    pass
        except asyncio.CancelledError:
            return
        except Exception:
            pass


_live_task: Optional[asyncio.Task] = None


def ensure_live() -> None:
    global _live_task
    if _live_task and not _live_task.done():
        return
    try:
        loop = asyncio.get_running_loop()
        _live_task = loop.create_task(_live_loop())
    except RuntimeError:
        pass


# ============================================================
# SECTION 13 — SNAPSHOT
# ============================================================

def snapshot() -> Dict[str, Any]:
    return {
        "panels": active_panel_count(),
        "admins": len(config.ADMINS),
    }


# ============================================================
# PUBLIC EXPORTS
# ============================================================

__all__ = [
    "cmd_admin",
    "is_admin",
    "register_panel",
    "unregister_panel",
    "snapshot",
]
