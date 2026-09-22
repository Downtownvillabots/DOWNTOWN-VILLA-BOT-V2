# ============================================================
# 🏨 DOWNTOWN VILLA — ADMIN MAIN ROUTER
# ============================================================
#
# ONE command: /admin
# Everything else is buttons inside.
#
# Menu:
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
#
# Every panel has ❌ CANCEL button.
#
# ============================================================

from __future__ import annotations

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
    }
    try:
        from utils import locks as LK
        pass
    except Exception:
        pass

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
        from core import flow_engine as FE
        from core.flow_engine import list_flows
        out["flows"] = len(list_flows())
    except Exception:
        out["flows"] = 0

    return out


def _render_main() -> tuple:
    """Build main admin panel text + keyboard."""
    s = _quick_stats()

    text = "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"{F.EMO['gear']} <b>{F.fb('ADMIN CONTROL CENTER')}</b>",
        F.DIV,
        "",
        f"{F.EMO['clock']} {F.sc('uptime')} · <b>{FM.duration_short(s['uptime'])}</b>",
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
# SECTION 6 — CALLBACK ROUTER
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

    # ────────── UNIVERSAL CANCEL ──────────
    if action == "cancel":
        unregister_panel(q.message.id)
        try:
            await q.message.delete()
        except Exception:
            pass
        return await q.answer("❌ Cancelled")

    return await q.answer("❓ Unknown", show_alert=True)


# ============================================================
# SECTION 7 — PAGE OPENER
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
                F.DIV,
                "",
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
                F.DIV,
                "",
                f"📌 {F.sc('manage groups from /settings in group')}",
                f"📌 {F.sc('or /flow to edit search flow per group')}",
            ])
            kb = _back_kb()
        elif page == "ban":
            text = "\n".join([
                f"{F.EMO['warn']} <b>{F.fb('BAN / FILTER')}</b>",
                F.DIV,
                "",
                f"📌 {F.sc('coming soon')}",
            ])
            kb = _back_kb()
        elif page == "maintenance":
            text = "\n".join([
                f"🛠️ <b>{F.fb('MAINTENANCE')}</b>",
                F.DIV,
                "",
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
                F.DIV,
                "",
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
# SECTION 8 — MODULE OPENER
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
            from plugins.broadcast import broadcast as BC
            fn = getattr(BC, "open_panel_for_admin", None)
            if fn is not None:
                await fn(client, q.message)
            else:
                await q.answer("Use /broadcast", show_alert=True)
            return

        if module == "premium":
            from plugins.premium import premium_watch as PW
            fn = getattr(PW, "open_panel_for_admin", None)
            if fn is not None:
                await fn(client, q.message)
            else:
                await q.answer("Use /seriesgroupsettings", show_alert=True)
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
# SECTION 9 — TOGGLES
# ============================================================

@Client.on_callback_query(
    filters.regex(rf"^{PFX}:toggle_maint$"),
    group=-9500,
)
async def toggle_maintenance(client: Client, q: CallbackQuery):
    if not q.from_user or not is_admin(q.from_user.id):
        return await q.answer("❌", show_alert=True)
    try:
        # Runtime toggle only (persist via env for permanent)
        config.MAINTENANCE_MODE = not config.MAINTENANCE_MODE
        await q.answer(
            f"{'🟢 ON' if config.MAINTENANCE_MODE else '🔴 OFF'}"
        )
        await _open_page(client, q, "maintenance")
    except Exception as e:
        await q.answer(f"❌ {e}", show_alert=True)


# ============================================================
# SECTION 10 — HELPERS
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
# SECTION 11 — LIVE UPDATER (optional)
# ============================================================

async def _live_loop(interval: float = 5.0) -> None:
    """Refresh every open panel every N seconds."""
    while True:
        try:
            await asyncio.sleep(interval)
            for panel_id, panel in list(_panels.items()):
                # Only auto-refresh dashboard
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
# SECTION 12 — SNAPSHOT
# ============================================================

def snapshot() -> Dict[str, Any]:
    return {
        "panels": active_panel_count(),
        "admins": len(config.ADMINS),
    }


# ============================================================
# SECTION 13 — IMPORTS
# ============================================================

import asyncio  # noqa: E402


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
