# ============================================================
# 🏨 DOWNTOWN VILLA — BACKUP RESET (3-STEP CONFIRM)
# ============================================================
#
# Safe wipe of every backup state + run history.
#
# Called from /backup → [🗑️ RESET ALL] button.
#
# 3-step confirmation:
#   1. Warning + current totals
#   2. Final warning
#   3. Confirm → executes
#
# Never deletes Telegram messages — only MongoDB state.
#
# ============================================================

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from pyrogram import Client
from pyrogram.enums import ParseMode
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
)

from utils import fonts as F
from utils import format as FM
from utils import progress as P

logger = logging.getLogger(__name__)


# ============================================================
# SECTION 1 — CONSTANTS
# ============================================================

PFX = "breset"
CONFIRM_TTL = 120.0


# ============================================================
# SECTION 2 — CONFIRM STATE
# ============================================================

_confirms: Dict[str, Dict[str, Any]] = {}


def _new_confirm(uid: int) -> str:
    token = f"r{int(time.time())}{uid % 10000:04d}"
    _confirms[token] = {
        "user_id": int(uid),
        "step": 1,
        "expires": time.time() + CONFIRM_TTL,
    }
    return token


def _get_confirm(token: str, uid: int) -> Optional[Dict[str, Any]]:
    c = _confirms.get(token)
    if not c:
        return None
    if c["user_id"] != int(uid):
        return None
    if time.time() > c["expires"]:
        _confirms.pop(token, None)
        return None
    return c


def _advance(token: str, uid: int) -> Optional[Dict[str, Any]]:
    c = _get_confirm(token, uid)
    if not c:
        return None
    c["step"] += 1
    c["expires"] = time.time() + CONFIRM_TTL
    return c


def _drop(token: str) -> None:
    _confirms.pop(token, None)


# ============================================================
# SECTION 3 — AUTH
# ============================================================

def _is_admin(uid) -> bool:
    try:
        from core import config
        return int(uid) in [int(a) for a in config.ADMINS]
    except Exception:
        return False


# ============================================================
# SECTION 4 — PANEL RENDERERS
# ============================================================

async def _build_step1() -> tuple:
    """Step 1/3 — warning + totals."""
    totals = {}
    try:
        from plugins.backup import state as ST
        totals = {
            "pending": await ST.count_by_status(ST.STATUS_PENDING),
            "uploading": await ST.count_by_status(ST.STATUS_UPLOADING),
            "uploaded": await ST.count_by_status(ST.STATUS_UPLOADED),
            "failed": await ST.count_by_status(ST.STATUS_FAILED),
            "skipped": await ST.count_by_status(ST.STATUS_SKIPPED),
        }
    except Exception as e:
        logger.debug(f"[RESET] totals: {e}")

    grand = sum(totals.values())

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"{F.EMO['warn']} <b>{F.fb('RESET BACKUP — STEP 1/3')}</b>",
        F.DIV,
        "",
        f"{F.EMO['warn']} {F.sc('this wipes every state doc')}",
        f"{F.EMO['info']} {F.sc('Telegram channels are NOT touched')}",
        "",
        F.DIV_S,
        f"{F.EMO['chart']} <b>{F.fb('CURRENT STATE')}</b>",
        F.DIV_S,
        "",
        f"✅ {F.sc('uploaded')} · <b>{FM.num(totals.get('uploaded', 0))}</b>",
        f"⏳ {F.sc('pending')} · <b>{FM.num(totals.get('pending', 0))}</b>",
        f"🔄 {F.sc('uploading')} · <b>{FM.num(totals.get('uploading', 0))}</b>",
        f"❌ {F.sc('failed')} · <b>{FM.num(totals.get('failed', 0))}</b>",
        f"⏭️ {F.sc('skipped')} · <b>{FM.num(totals.get('skipped', 0))}</b>",
        "",
        f"📊 {F.sc('total docs')} · <b>{FM.num(grand)}</b>",
        "",
        F.DIV,
        f"{F.EMO['warn']} <b>{F.sc('all of these will be DELETED')}</b>",
        "",
        F.DIV_S,
        f"📌 {F.sc('after reset, the next backup will re-upload from scratch')}",
    ]

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"{F.EMO['warn']} {F.sc('continue → step 2')}",
            callback_data=f"{PFX}:step2",
        )],
        [InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('cancel')}",
            callback_data=f"{PFX}:cancel",
        )],
    ])

    return "\n".join(lines)[:4000], kb


def _build_step2() -> tuple:
    """Step 2/3 — final warning."""
    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"🚨 <b>{F.fb('RESET BACKUP — STEP 2/3')}</b>",
        F.DIV,
        "",
        f"{F.EMO['warn']} <b>{F.sc('FINAL WARNING')}</b>",
        "",
        f"📌 {F.sc('every state doc across every shard will be deleted')}",
        f"📌 {F.sc('run history will be cleared')}",
        f"📌 {F.sc('the next backup run starts fresh')}",
        "",
        F.DIV_S,
        f"⚠️ <b>{F.sc('THIS CANNOT BE UNDONE')}</b>",
    ]

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"🚨 {F.sc('yes, i understand')}",
            callback_data=f"{PFX}:step3",
        )],
        [InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('go back')}",
            callback_data=f"{PFX}:back",
        )],
    ])

    return "\n".join(lines)[:4000], kb


def _build_step3() -> tuple:
    """Step 3/3 — final confirm."""
    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"☢️ <b>{F.fb('RESET BACKUP — STEP 3/3')}</b>",
        F.DIV,
        "",
        f"📌 {F.sc('tap DELETE NOW to wipe everything')}",
        "",
        F.DIV_S,
        f"{F.EMO['spark']} <i>{F.sc('this is the last chance to cancel')}</i>",
    ]

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"🗑️ {F.sc('DELETE NOW')}",
            callback_data=f"{PFX}:execute",
        )],
        [InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('cancel')}",
            callback_data=f"{PFX}:cancel",
        )],
    ])

    return "\n".join(lines)[:4000], kb


# ============================================================
# SECTION 5 — EXECUTE WIPE
# ============================================================

async def _execute_wipe() -> Dict[str, Any]:
    """Run the actual wipe via state.wipe_all()."""
    result: Dict[str, Any] = {
        "ok": False,
        "total_state": 0,
        "total_runs": 0,
        "per_shard": [],
        "error": None,
    }
    try:
        from plugins.backup import state as ST
        r = await ST.wipe_all()
        result["ok"] = True
        result["total_state"] = r.get("total", 0)
        result["total_runs"] = r.get("runs_deleted", 0)
        result["per_shard"] = r.get("per_shard", [])
        logger.warning(
            f"[RESET] wiped {result['total_state']} state + "
            f"{result['total_runs']} runs"
        )
    except Exception as e:
        logger.exception(f"[RESET] wipe: {e}")
        result["error"] = str(e)[:200]
    return result


def _build_result_panel(result: Dict[str, Any]) -> tuple:
    """Show the wipe result."""
    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
    ]

    if result.get("ok"):
        lines += [
            f"{F.EMO['check']} <b>{F.fb('RESET COMPLETE')}</b>",
            F.DIV,
            "",
            f"{F.EMO['trash']} {F.sc('state docs deleted')} · "
            f"<b>{FM.num(result.get('total_state', 0))}</b>",
            f"{F.EMO['trash']} {F.sc('runs deleted')} · "
            f"<b>{FM.num(result.get('total_runs', 0))}</b>",
            "",
        ]

        shards = result.get("per_shard", [])
        if shards:
            lines.append(F.DIV_S)
            lines.append(f"{F.EMO['db']} <b>{F.fb('PER SHARD')}</b>")
            lines.append(F.DIV_S)
            lines.append("")
            for s in shards[:8]:
                icon = "🟢" if not s.get("error") else "🔴"
                lines.append(
                    f"{icon} <code>{str(s.get('label', '?'))[:20]}</code> "
                    f"· <b>{FM.num(s.get('deleted', 0))}</b>"
                )
            lines.append("")

        lines += [
            F.DIV_S,
            f"{F.EMO['spark']} {F.sc('ready for a fresh start')}",
        ]
    else:
        lines += [
            f"{F.EMO['cross']} <b>{F.fb('RESET FAILED')}</b>",
            F.DIV,
            "",
            f"⚠️ <code>{result.get('error', '?')}</code>",
        ]

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"{F.EMO['refresh']} {F.sc('back to backup')}",
                callback_data="dtvb:back",
            ),
        ],
        [
            InlineKeyboardButton(
                f"{F.EMO['cross']} {F.sc('close')}",
                callback_data="dtvb:close",
            ),
        ],
    ])

    return "\n".join(lines)[:4000], kb


# ============================================================
# SECTION 6 — PUBLIC: OPEN PANEL
# ============================================================

async def open_reset_panel(client: Client, q: CallbackQuery) -> None:
    """Called from /backup → [🗑️ RESET ALL]."""
    if not q.from_user or not _is_admin(q.from_user.id):
        return await q.answer("❌ Admin only", show_alert=True)

    text, kb = await _build_step1()

    try:
        await q.message.edit_text(
            text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        if "not modified" not in str(e).lower():
            logger.debug(f"[RESET] edit: {e}")

    await q.answer()


# ============================================================
# SECTION 7 — PUBLIC: ROUTER
# ============================================================

async def router_handler(client: Client, q: CallbackQuery) -> bool:
    """
    Handle breset:* callbacks.
    Returns True if handled.
    """
    if not str(q.data or "").startswith(f"{PFX}:"):
        return False

    if not q.from_user or not _is_admin(q.from_user.id):
        await q.answer("❌ Admin only", show_alert=True)
        return True

    action = str(q.data).split(":", 1)[1] if ":" in q.data else ""

    try:
        if action == "step2":
            text, kb = _build_step2()
            await _safe_edit(q, text, kb)
            return True

        if action == "step3":
            text, kb = _build_step3()
            await _safe_edit(q, text, kb)
            return True

        if action == "back":
            text, kb = await _build_step1()
            await _safe_edit(q, text, kb)
            return True

        if action == "cancel":
            # Go back to main backup panel
            try:
                await q.message.edit_text(
                    f"{F.EMO['cross']} <b>{F.fb('RESET CANCELLED')}</b>\n"
                    f"{F.DIV}\n"
                    f"<i>{F.sc('nothing was deleted')}</i>",
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton(
                            f"{F.EMO['back']} {F.sc('back to backup')}",
                            callback_data="dtvb:back",
                        ),
                    ]]),
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass
            await q.answer("❌ Cancelled")
            return True

        if action == "execute":
            await q.answer("🗑️ Deleting…")
            # Show progress
            try:
                await q.message.edit_text(
                    "\n".join([
                        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                        f"{F.EMO['warn']} <b>{F.fb('WIPING…')}</b>",
                        F.DIV,
                        "",
                        f"<i>{F.sc('deleting state across all shards…')}</i>",
                    ]),
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass

            result = await _execute_wipe()
            text, kb = _build_result_panel(result)
            await _safe_edit(q, text, kb)
            return True

        return False

    except Exception as e:
        logger.exception(f"[RESET] callback: {e}")
        try:
            await q.answer(f"❌ {type(e).__name__}", show_alert=True)
        except Exception:
            pass
        return True


# ============================================================
# SECTION 8 — HELPERS
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
        if "not modified" not in str(e).lower():
            logger.debug(f"[RESET] edit: {e}")


# ============================================================
# SECTION 9 — SNAPSHOT
# ============================================================

def snapshot() -> Dict[str, Any]:
    return {"pending_confirms": len(_confirms)}


# ============================================================
# PUBLIC EXPORTS
# ============================================================

__all__ = [
    "open_reset_panel",
    "router_handler",
    "snapshot",
]
