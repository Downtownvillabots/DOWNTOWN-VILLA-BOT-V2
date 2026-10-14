# ============================================================
# 🏨 DOWNTOWN VILLA — GROUPS ROUTER
# ============================================================
#
# Single callback router for the entire group settings panel.
#
# Entry points:
#   • /settings inside a group  → commands.py renders panel
#   • /admin → 👥 Groups       → admin_list.py opens panel
#   • gs:{chat_id} deep link    → opens panel from PM
#
# Handles ALL ga:* callbacks.
#
# Sections (per panel.py):
#   main, search, content, flow, caption, buttons, welcome,
#   autodel, filters, fsub, verify, security, requests,
#   metadata, stats, view, reset, words
#
# Callback map (all routed here):
#   ga:close                 close panel
#   ga:back                  back to main
#   ga:s:{section}           navigate to section
#   ga:tog:{field}           toggle top-level bool
#   ga:set:content:{value}   set content mode
#   ga:flow:{step_key}       open flow step
#   ga:flow_tog:{step_key}   toggle step enabled
#   ga:flow_row:{key}:{n}    set step per_row
#   ga:flow_skip:{key}       toggle step auto_skip
#   ga:cap:edit              start caption edit session
#   ga:cap:reset             reset caption
#   ga:cap:preview           show preview
#   ga:btn:view:{idx}        view button
#   ga:btn:add               start button add session
#   ga:btn:tog:{idx}         toggle button
#   ga:btn:del:{idx}         delete button
#   ga:btn_row:{n}           set buttons per row
#   ga:w_tog                 welcome toggle
#   ga:w_edit                welcome edit session
#   ga:w_adtog               welcome auto-delete toggle
#   ga:ad_tog:{key}          toggle auto_delete.{key}
#   ga:ad_timer:{secs}       set auto_delete.bot_timer
#   ga:ad_keep:{n}           set auto_delete.keep_last_n
#   ga:flt_tog:{key}         toggle filters.{key}
#   ga:flt_add               start banned word add session
#   ga:flt_words             show words list
#   ga:flt_clear             clear banned words
#   ga:fs_tog                toggle fsub.enabled
#   ga:fs_add                add fsub channel session
#   ga:fs_rm:{idx}           remove channel by index
#   ga:v_tog                 toggle verify.enabled
#   ga:v_url                 set shortener URL session
#   ga:v_time                set verify time session
#   ga:sec:{key}             toggle security.{key}
#   ga:req_tog:{key}         toggle requests.{key}
#   ga:req_ch                set request channel session
#   ga:meta_tog:{key}        toggle metadata.{key}
#   ga:stats_reset           reset stats
#   ga:reset_do              execute full reset
#
# Session storage:
#   _sessions[user_id] = {step, chat_id, ...extra}
#   TTL = 15 min, auto-expires
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
from plugins.groups import state as S
from plugins.groups import panel as P
from utils import fonts as F

logger = logging.getLogger(__name__)

PFX = "ga"


# ============================================================
# SECTION 1 — SESSION STORE
# ============================================================

_sessions: Dict[int, Dict[str, Any]] = {}
_SESSION_TTL = 900.0   # 15 min


def _sess_new(uid: int, step: str, chat_id: int, **extra) -> None:
    _sessions[int(uid)] = {
        "step": step,
        "chat_id": int(chat_id),
        "expires": time.time() + _SESSION_TTL,
        **extra,
    }


def _sess_get(uid: int) -> Optional[Dict[str, Any]]:
    s = _sessions.get(int(uid))
    if not s:
        return None
    if time.time() > s.get("expires", 0):
        _sessions.pop(int(uid), None)
        return None
    return s


def _sess_set(uid: int, **fields) -> None:
    s = _sessions.get(int(uid))
    if not s:
        return
    s.update(fields)
    s["expires"] = time.time() + _SESSION_TTL


def _sess_drop(uid: int) -> None:
    _sessions.pop(int(uid), None)


def _sess_chat_id(uid: int) -> Optional[int]:
    """
    Return the target group chat_id from the session store.
    NEVER falls back to the callback message's own chat_id —
    that is the admin's PM and would write to a bogus group.
    """
    s = _sess_get(uid)
    if not s:
        return None
    cid = s.get("chat_id")
    if not cid:
        return None
    try:
        return int(cid)
    except (TypeError, ValueError):
        return None
        
def _sanitize_import(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Whitelist-merge for restore. Keeps only DEFAULT_CFG keys."""
    if not isinstance(cfg, dict):
        return {}
    out: Dict[str, Any] = {}
    strip = {
        "chat_id", "_id", "title", "username",
        "created_at", "updated_at", "stats",
    }
    for k, v in cfg.items():
        if k in strip:
            continue
        if k not in S.DEFAULT_CFG:
            continue
        out[k] = v
    return out

def _has_pending(uid: int) -> bool:
    return _sess_get(uid) is not None


# ============================================================
# SECTION 2 — AUTH
# ============================================================

def _is_bot_admin(uid: int) -> bool:
    try:
        return int(uid) in [int(a) for a in config.ADMINS]
    except Exception:
        return False


async def _is_group_admin(client: Client, chat_id: int, user_id: int) -> bool:
    if _is_bot_admin(user_id):
        return True
    try:
        m = await client.get_chat_member(chat_id, user_id)
        st = getattr(m, "status", None)
        st = st.name.lower() if hasattr(st, "name") else str(st).lower()
        return st in ("administrator", "creator", "owner")
    except Exception:
        return False


# ============================================================
# SECTION 3 — SECTION DISPATCHER
# ============================================================

async def _render_section(
    section: str, chat_id: int,
) -> Optional[tuple]:
    """Route section name to the right panel renderer."""
    if section == "refresh":
        return await P.render_main(chat_id)

    if section == "search":
        return await P.render_search(chat_id)
    if section == "content":
        return await P.render_content(chat_id)
    if section == "flow":
        # Preserve the last-active flow tab per-user
        sess = _sess_get(uid_for_section) or {}
        flow_type = sess.get("flow_type") or "movie"
        return await P.render_flow(chat_id, flow_type)
    if section == "caption":
        return await P.render_caption(chat_id)
    if section == "buttons":
        return await P.render_buttons(chat_id)
    if section == "welcome":
        return await P.render_welcome(chat_id)
    if section == "autodel":
        return await P.render_autodel(chat_id)
    if section == "filters":
        return await P.render_filters(chat_id)
    if section == "fsub":
        return await P.render_fsub(chat_id)
    if section == "verify":
        return await P.render_verify(chat_id)
    if section == "security":
        return await P.render_security(chat_id)
    if section == "requests":
        return await P.render_requests(chat_id)
    if section == "metadata":
        return await P.render_metadata(chat_id)
    if section == "stats":
        return await P.render_stats(chat_id)
    if section == "view":
        return await P.render_view(chat_id)
    if section == "reset":
        return await P.render_reset(chat_id)

    return await P.render_main(chat_id)


# ============================================================
# SECTION 4 — SAFE EDIT
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
        logger.debug(f"[GROUPS] edit: {e}")


# ============================================================
# SECTION 5 — PUBLIC HELPERS (used by other files)
# ============================================================

async def open_panel_for_chat(
    client: Client, chat_id: int, message: Message,
) -> None:
    """
    Send a fresh settings panel for a group into a chat.
    Used by:
      • commands.py /settings in group
      • commands.py /settings in PM  (list flow)
      • admin_list.py  /admin → 👥 Groups → open
      • deep-link gs:{chat_id}  (via start_router)
    """
    try:
        await S.register_group(chat_id)
        text, kb = await P.render_main(chat_id)
        await message.reply_text(
            text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.exception(f"[GROUPS] open panel: {e}")


async def open_panel_edit(
    client: Client, q: CallbackQuery, chat_id: int,
) -> None:
    """Edit the existing callback message to show the panel."""
    try:
        await S.register_group(chat_id)
        text, kb = await P.render_main(chat_id)
        await _safe_edit(q, text, kb)
    except Exception as e:
        logger.exception(f"[GROUPS] open panel edit: {e}")


# ============================================================
# SECTION 6 — MAIN ROUTER
# ============================================================

@Client.on_callback_query(
    filters.regex(rf"^{PFX}:"),
    group=-8500,
)
async def group_router(client: Client, q: CallbackQuery):
    if not q.from_user:
        return await q.answer()

    parts = str(q.data).split(":")
    action = parts[1] if len(parts) > 1 else ""
    uid = q.from_user.id

    try:
        # ── CLOSE ──
        if action == "close":
            _sess_drop(uid)
            try:
                await q.message.delete()
            except Exception:
                pass
            return await q.answer("Closed")

        # ── BACK → main panel ──
        if action == "back":
            chat_id = _sess_chat_id(uid)
            if not chat_id:
                return await q.answer(
                    "⚠️ Session expired — reopen the panel",
                    show_alert=True,
                )

            text, kb = await P.render_main(chat_id)
            await _safe_edit(q, text, kb)
            return await q.answer()

        # ── NAVIGATE SECTION ──
        if action == "s":
            section = parts[2] if len(parts) > 2 else ""
            section_arg = parts[3] if len(parts) > 3 else ""

            # For "flow", an extra arg selects the flow_type
            if section == "flow" and section_arg in ("movie", "series"):
                _sess_set(uid, flow_type=section_arg)

            chat_id = _sess_chat_id(uid)
            if not chat_id:
                return await q.answer(
                    "⚠️ Session expired — reopen the panel",
                    show_alert=True,
                )

            if not await _is_group_admin(client, chat_id, uid):
                return await q.answer("⛔ Admin only", show_alert=True)

            if section == "flow":
                ftype = (_sess_get(uid) or {}).get("flow_type", "movie")
                text, kb = await P.render_flow(chat_id, ftype)
                await _safe_edit(q, text, kb)
                return await q.answer()

            result = await _render_section(section, chat_id)
            if result is None:
                return await q.answer("❓ Unknown section", show_alert=True)

            text, kb = result
            await _safe_edit(q, text, kb)
            return await q.answer()

        # ── TOGGLE TOP-LEVEL BOOL ──
        if action == "tog":
            field = parts[2] if len(parts) > 2 else ""
            sess = _sess_get(uid) or {}
            chat_id = _sess_chat_id(uid)
            if not chat_id or not field:
                return await q.answer("❌")

            if not await _is_group_admin(client, chat_id, uid):
                return await q.answer("⛔ Admin only", show_alert=True)

            cfg = await S.get_config(chat_id)
            cur = bool(cfg.get(field, False))
            await S.save_field(chat_id, field, not cur)

            await q.answer(f"{'🟢' if not cur else '🔴'}")

            text, kb = await P.render_search(chat_id)
            await _safe_edit(q, text, kb)
            return

        # ── SET CONTENT MODE ──
        # ── SEARCH COOLDOWN ──
        if action == "cd":
            try:
                n = int(parts[2])
            except (ValueError, IndexError):
                return await q.answer("❌")
            n = max(0, min(300, n))
            chat_id = _sess_chat_id(uid)
            if not chat_id:
                return await q.answer(
                    "⚠️ Session expired — reopen the panel",
                    show_alert=True,
                )
            if not await _is_group_admin(client, chat_id, uid):
                return await q.answer("⛔ Admin only", show_alert=True)

            await S.save_field(
                chat_id, "search.cooldown_seconds", n,
            )
            await q.answer(
                "⏱️ Cooldown OFF" if n == 0
                else f"⏱️ Cooldown {n}s"
            )
            text, kb = await P.render_search(chat_id)
            await _safe_edit(q, text, kb)
            return

        # ── SEARCH NO-OP ──
        if action == "search_noop":
            return await q.answer()

        # ── SET CONTENT MODE ──
        if action == "set":
        if action == "set":
            sub = parts[2] if len(parts) > 2 else ""
            val = parts[3] if len(parts) > 3 else ""
            sess = _sess_get(uid) or {}
            chat_id = _sess_chat_id(uid)
            if not chat_id:
                return await q.answer("❌")
            if not await _is_group_admin(client, chat_id, uid):
                return await q.answer("⛔ Admin only", show_alert=True)

            if sub == "content" and val in ("movie", "series", "both"):
                await S.save_field(chat_id, "content_mode", val)
                await q.answer(f"✅ {val.upper()}")
                text, kb = await P.render_content(chat_id)
                await _safe_edit(q, text, kb)
                return

            return await q.answer("❓")

        # ── FLOW: OPEN STEP ──
        # Two shapes:
        #   ga:flow:{key}                  (from render_flow)
        #   ga:flow:{flow_type}:{key}      (from step_advanced back button)
        if action == "flow":
            chat_id = _sess_chat_id(uid)
            if not chat_id:
                return await q.answer(
                    "⚠️ Session expired — reopen the panel",
                    show_alert=True,
                )
            if not await _is_group_admin(client, chat_id, uid):
                return await q.answer("⛔ Admin only", show_alert=True)

            # Detect shape
            if len(parts) >= 4 and parts[2] in ("movie", "series"):
                ftype = parts[2]
                key = parts[3]
                _sess_set(uid, flow_type=ftype)
            else:
                key = parts[2] if len(parts) > 2 else ""
                ftype = "movie"

            if not key:
                return await q.answer("❌")

            text, kb = await P.render_flow_step(chat_id, key, ftype)
            await _safe_edit(q, text, kb)
            return await q.answer()
        # ── FLOW: TOGGLE STEP ──
        if action == "flow_tog":
            key = parts[2] if len(parts) > 2 else ""
            sess = _sess_get(uid) or {}
            chat_id = _sess_chat_id(uid)
            if not chat_id or not key:
                return await q.answer("❌")
            if not await _is_group_admin(client, chat_id, uid):
                return await q.answer("⛔ Admin only", show_alert=True)

            cfg = await S.get_config(chat_id)
            flow = cfg.get("flow") or {}
            cur = bool((flow.get(key) or {}).get("enabled", True))
            await S.save_field(
                chat_id, f"flow.{key}.enabled", not cur,
            )
            await q.answer(f"{'🟢' if not cur else '🔴'}")
            text, kb = await P.render_flow_step(chat_id, key)
            await _safe_edit(q, text, kb)
            return

        # ── FLOW: SET PER_ROW ──
        if action == "flow_row":
            key = parts[2] if len(parts) > 2 else ""
            try:
                n = int(parts[3])
            except (ValueError, IndexError):
                return await q.answer("❌")
            sess = _sess_get(uid) or {}
            chat_id = _sess_chat_id(uid)
            if not chat_id or not key:
                return await q.answer("❌")
            if not await _is_group_admin(client, chat_id, uid):
                return await q.answer("⛔ Admin only", show_alert=True)

            await S.save_field(chat_id, f"flow.{key}.per_row", n)
            await q.answer(f"📐 {n}/row")
            text, kb = await P.render_flow_step(chat_id, key)
            await _safe_edit(q, text, kb)
            return

         # ── FLOW: OPEN ADVANCED ──
        if action == "flow_adv":
            chat_id = _sess_chat_id(uid)
            if not chat_id:
                return await q.answer(
                    "⚠️ Session expired — reopen the panel",
                    show_alert=True,
                )
            if not await _is_group_admin(client, chat_id, uid):
                return await q.answer("⛔ Admin only", show_alert=True)

            # Detect shape: ga:flow_adv:{key} or ga:flow_adv:{ftype}:{key}
            if len(parts) >= 4 and parts[2] in ("movie", "series"):
                ftype = parts[2]
                key = parts[3]
            else:
                key = parts[2] if len(parts) > 2 else ""
                ftype = (_sess_get(uid) or {}).get("flow_type", "movie")

            if not key:
                return await q.answer("❌")

            text, kb = await P.render_flow_step_advanced(
                chat_id, key, ftype,
            )
            await _safe_edit(q, text, kb)
            return await q.answer()
        # ── FLOW: SET ADVANCED FIELD ─
        if action == "flow_set":
            # ga:flow_set:{step_key}:{field}:{value}
            key = parts[2] if len(parts) > 2 else ""
            field = parts[3] if len(parts) > 3 else ""
            raw_val = parts[4] if len(parts) > 4 else ""
            chat_id = _sess_chat_id(uid)
            if not chat_id or not key or not field:
                return await q.answer(
                    "⚠️ Session expired — reopen the panel",
                    show_alert=True,
                )
            if not await _is_group_admin(client, chat_id, uid):
                return await q.answer("⛔ Admin only", show_alert=True)

            # Cast value: int if numeric, else str
            try:
                value: Any = int(raw_val)
            except (TypeError, ValueError):
                value = raw_val

            await S.save_field(
                chat_id, f"flow.{key}.{field}", value,
            )
            await q.answer(f"✅ {field}={value}")
            text, kb = await P.render_flow_step_advanced(chat_id, key)
            await _safe_edit(q, text, kb)
            return

        # ── FLOW: TOGGLE ADVANCED FIELD ──
        if action == "flow_togf":
            key = parts[2] if len(parts) > 2 else ""
            field = parts[3] if len(parts) > 3 else ""
            chat_id = _sess_chat_id(uid)
            if not chat_id or not key or not field:
                return await q.answer(
                    "⚠️ Session expired — reopen the panel",
                    show_alert=True,
                )
            if not await _is_group_admin(client, chat_id, uid):
                return await q.answer("⛔ Admin only", show_alert=True)

            cfg = await S.get_config(chat_id)
            flow = cfg.get("flow") or {}
            step = flow.get(key) or {}
            cur = bool(step.get(field, False))
            await S.save_field(
                chat_id, f"flow.{key}.{field}", not cur,
            )
            await q.answer(f"{'🟢' if not cur else '🔴'}")
            text, kb = await P.render_flow_step_advanced(chat_id, key)
            await _safe_edit(q, text, kb)
            return

        # ── FLOW: SWITCH TAB (movie / series) ──
        if action == "flow_tab":
            ftype = parts[2] if len(parts) > 2 else "movie"
            if ftype not in ("movie", "series"):
                ftype = "movie"
            chat_id = _sess_chat_id(uid)
            if not chat_id:
                return await q.answer(
                    "⚠️ Session expired — reopen the panel",
                    show_alert=True,
                )
            if not await _is_group_admin(client, chat_id, uid):
                return await q.answer("⛔ Admin only", show_alert=True)

            # Remember the tab for this user
            _sess_set(uid, flow_type=ftype)

            text, kb = await P.render_flow(chat_id, ftype)
            await _safe_edit(q, text, kb)
            return await q.answer()

        # ── FLOW: MOVE STEP UP ──
        if action == "flow_up":
            ftype = parts[2] if len(parts) > 2 else "movie"
            try:
                idx = int(parts[3])
            except (ValueError, IndexError):
                return await q.answer("❌")
            chat_id = _sess_chat_id(uid)
            if not chat_id:
                return await q.answer(
                    "⚠️ Session expired — reopen the panel",
                    show_alert=True,
                )
            if not await _is_group_admin(client, chat_id, uid):
                return await q.answer("⛔ Admin only", show_alert=True)

            cfg = await S.get_config(chat_id)
            order = list(P._resolve_flow_order(cfg, ftype))

            if 0 < idx < len(order):
                order[idx - 1], order[idx] = order[idx], order[idx - 1]
                flow_order = dict(cfg.get("flow_order") or {})
                flow_order[ftype] = order
                await S.save_field(chat_id, "flow_order", flow_order)
                await q.answer("⬆️")
            else:
                await q.answer("⚠️ top")

            text, kb = await P.render_flow(chat_id, ftype)
            await _safe_edit(q, text, kb)
            return

        # ── FLOW: MOVE STEP DOWN ──
        if action == "flow_down":
            ftype = parts[2] if len(parts) > 2 else "movie"
            try:
                idx = int(parts[3])
            except (ValueError, IndexError):
                return await q.answer("❌")
            chat_id = _sess_chat_id(uid)
            if not chat_id:
                return await q.answer(
                    "⚠️ Session expired — reopen the panel",
                    show_alert=True,
                )
            if not await _is_group_admin(client, chat_id, uid):
                return await q.answer("⛔ Admin only", show_alert=True)

            cfg = await S.get_config(chat_id)
            order = list(P._resolve_flow_order(cfg, ftype))

            if 0 <= idx < len(order) - 1:
                order[idx], order[idx + 1] = order[idx + 1], order[idx]
                flow_order = dict(cfg.get("flow_order") or {})
                flow_order[ftype] = order
                await S.save_field(chat_id, "flow_order", flow_order)
                await q.answer("⬇️")
            else:
                await q.answer("⚠️ bottom")

            text, kb = await P.render_flow(chat_id, ftype)
            await _safe_edit(q, text, kb)
            return

        # ── FLOW: RESET ORDER ──
        if action == "flow_rst_order":
            ftype = parts[2] if len(parts) > 2 else "movie"
            if ftype not in ("movie", "series"):
                ftype = "movie"
            chat_id = _sess_chat_id(uid)
            if not chat_id:
                return await q.answer(
                    "⚠️ Session expired — reopen the panel",
                    show_alert=True,
                )
            if not await _is_group_admin(client, chat_id, uid):
                return await q.answer("⛔ Admin only", show_alert=True)

            cfg = await S.get_config(chat_id)
            flow_order = dict(cfg.get("flow_order") or {})
            flow_order[ftype] = []
            await S.save_field(chat_id, "flow_order", flow_order)
            await q.answer("♻️ order reset")

            text, kb = await P.render_flow(chat_id, ftype)
            await _safe_edit(q, text, kb)
            return

        # ── FLOW: NO-OP (section label rows) ──
        if action == "flow_noop":
            return await q.answer()

                # ── RESTORE ALL: CONFIRM ──
        if action == "rstall_do":
            if not _is_bot_admin(uid):
                return await q.answer(
                    "⛔ Admin only", show_alert=True,
                )

            sess = _sess_get(uid) or {}
            payload = sess.get("payload") or {}
            if not isinstance(payload, dict) or not payload:
                return await q.answer(
                    "⚠️ Session expired", show_alert=True,
                )

            # Execute restore
            from datetime import datetime
            now = datetime.utcnow()
            applied = 0
            failed = 0
            coll = S._coll()

            if coll is None:
                return await q.answer(
                    "❌ DB error", show_alert=True,
                )

            for cid_str, entry in payload.items():
                try:
                    cid = int(cid_str)
                except (TypeError, ValueError):
                    failed += 1
                    continue

                if not isinstance(entry, dict):
                    failed += 1
                    continue

                raw_cfg = entry.get("config") or entry
                clean = _sanitize_import(raw_cfg)
                if not clean:
                    failed += 1
                    continue

                try:
                    existing = await S.get_config(
                        cid, use_cache=False,
                    )
                except Exception:
                    existing = {}

                doc = {
                    "chat_id": cid,
                    "title": existing.get("title"),
                    "username": existing.get("username"),
                    "created_at": existing.get("created_at", now),
                    "updated_at": now,
                    "stats": existing.get("stats") or {
                        "searches_today": 0,
                        "results_found": 0,
                        "not_found": 0,
                        "files_sent": 0,
                        "updated_at": now,
                    },
                }

                template = await S.get_default_template()
                merged = dict(template)
                for k, v in clean.items():
                    merged[k] = v

                for k in (
                    "chat_id", "_id", "title", "username",
                    "created_at", "updated_at", "stats",
                ):
                    merged.pop(k, None)

                doc.update(merged)

                try:
                    await coll.replace_one(
                        {"chat_id": cid}, doc, upsert=True,
                    )
                    S._cache_invalidate(cid)
                    applied += 1
                except Exception as e:
                    logger.debug(f"[GROUPS] restore {cid}: {e}")
                    failed += 1

            _sess_drop(uid)

            text = "\n".join([
                f"{F.EMO['check']} <b>{F.fb('RESTORE DONE')}</b>",
                F.DIV, "",
                f"✅ {F.sc('applied')} · <b>{applied}</b>",
                f"❌ {F.sc('failed')} · <b>{failed}</b>",
            ])
            try:
                await q.message.edit_text(
                    text, parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass
            return await q.answer("✅ Restored")

        # ── RESTORE ALL: CANCEL ──
        if action == "rstall_no":
            _sess_drop(uid)
            try:
                await q.message.delete()
            except Exception:
                pass
            return await q.answer("❌ Cancelled")

        # ── FLOW: NO-OP (section label rows) ──
        if action == "flow_noop":
            return await q.answer()

        

        # ── CAPTION: EDIT SESSION ──
        if action == "cap":
            sub = parts[2] if len(parts) > 2 else ""
            sess = _sess_get(uid) or {}
            chat_id = _sess_chat_id(uid)
            if not chat_id:
                return await q.answer("❌")
            if not await _is_group_admin(client, chat_id, uid):
                return await q.answer("⛔ Admin only", show_alert=True)

            if sub == "edit":
                _sess_new(uid, "cap_edit", chat_id)
                text = "\n".join([
                    f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                    f"📝 <b>{F.fb('EDIT CAPTION')}</b>",
                    F.DIV, "",
                    f"📌 {F.sc('send the new caption')}",
                    f"📌 {F.sc('or send')} <code>-</code> "
                    f"{F.sc('to reset')}",
                    "",
                    F.DIV_S,
                    f"📌 {F.sc('variables')}:",
                    "<code>{title} {year} {quality} {codec}</code>",
                    "<code>{audio} {subtitle} {size}</code>",
                    "<code>{season} {episode} {bot_username}</code>",
                ])
                kb = InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        f"{F.EMO['cross']} {F.sc('cancel')}",
                        callback_data="ga:s:caption",
                    ),
                ]])
                await _safe_edit(q, text, kb)
                return await q.answer()

            if sub == "reset":
                await S.save_field(chat_id, "caption_template", None)
                await q.answer("♻️ Reset")
                text, kb = await P.render_caption(chat_id)
                await _safe_edit(q, text, kb)
                return

            if sub == "preview":
                text, kb = await P.render_caption_preview(chat_id)
                await _safe_edit(q, text, kb)
                return await q.answer()

            return await q.answer("❓")

        # ── BUTTONS ──
        if action == "btn":
            sub = parts[2] if len(parts) > 2 else ""
            sess = _sess_get(uid) or {}
            chat_id = _sess_chat_id(uid)
            if not chat_id:
                return await q.answer("❌")
            if not await _is_group_admin(client, chat_id, uid):
                return await q.answer("⛔ Admin only", show_alert=True)

            if sub == "view":
                try:
                    idx = int(parts[3])
                except (ValueError, IndexError):
                    return await q.answer("❌")
                text, kb = await P.render_button_view(chat_id, idx)
                await _safe_edit(q, text, kb)
                return await q.answer()

            if sub == "add":
                _sess_new(uid, "btn_add", chat_id)
                text = "\n".join([
                    f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                    f"➕ <b>{F.fb('ADD BUTTON')}</b>",
                    F.DIV, "",
                    f"📌 {F.sc('send')} <code>Name | URL</code>",
                    "",
                    f"📌 {F.sc('example')}:",
                    "<code>Join Channel | https://t.me/example</code>",
                ])
                kb = InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        f"{F.EMO['cross']} {F.sc('cancel')}",
                        callback_data="ga:s:buttons",
                    ),
                ]])
                await _safe_edit(q, text, kb)
                return await q.answer()

            if sub == "tog":
                try:
                    idx = int(parts[3])
                except (ValueError, IndexError):
                    return await q.answer("❌")
                cfg = await S.get_config(chat_id)
                btns = list(cfg.get("result_buttons") or [])
                if 0 <= idx < len(btns):
                    btns[idx]["enabled"] = not btns[idx].get("enabled", True)
                    await S.save_field(chat_id, "result_buttons", btns)
                await q.answer("🔄")
                text, kb = await P.render_button_view(chat_id, idx)
                await _safe_edit(q, text, kb)
                return

            if sub == "del":
                try:
                    idx = int(parts[3])
                except (ValueError, IndexError):
                    return await q.answer("❌")
                cfg = await S.get_config(chat_id)
                btns = list(cfg.get("result_buttons") or [])
                if 0 <= idx < len(btns):
                    btns.pop(idx)
                    for i, b in enumerate(btns, 1):
                        b["position"] = i
                    await S.save_field(chat_id, "result_buttons", btns)
                await q.answer("🗑️")
                text, kb = await P.render_buttons(chat_id)
                await _safe_edit(q, text, kb)
                return

            return await q.answer("❓")

        # ── BUTTONS: PER ROW ──
        if action == "btn_row":
            try:
                n = int(parts[2])
            except (ValueError, IndexError):
                return await q.answer("❌")
            sess = _sess_get(uid) or {}
            chat_id = _sess_chat_id(uid)
            if not chat_id:
                return await q.answer("❌")
            await S.save_field(chat_id, "buttons_per_row", n)
            await q.answer(f"📐 {n}/row")
            text, kb = await P.render_buttons(chat_id)
            await _safe_edit(q, text, kb)
            return

        # ── WELCOME ──
        if action in ("w_tog", "w_edit", "w_adtog"):
            sess = _sess_get(uid) or {}
            chat_id = _sess_chat_id(uid)
            if not chat_id:
                return await q.answer("❌")
            if not await _is_group_admin(client, chat_id, uid):
                return await q.answer("⛔ Admin only", show_alert=True)

            if action == "w_tog":
                cfg = await S.get_config(chat_id)
                cur = bool(cfg.get("welcome_enabled", False))
                await S.save_field(chat_id, "welcome_enabled", not cur)
                await q.answer("🟢" if not cur else "🔴")
                text, kb = await P.render_welcome(chat_id)
                await _safe_edit(q, text, kb)
                return

            if action == "w_adtog":
                cfg = await S.get_config(chat_id)
                cur = bool(cfg.get("welcome_auto_delete", True))
                await S.save_field(
                    chat_id, "welcome_auto_delete", not cur,
                )
                await q.answer("🔄")
                text, kb = await P.render_welcome(chat_id)
                await _safe_edit(q, text, kb)
                return

            if action == "w_edit":
                _sess_new(uid, "w_edit", chat_id)
                text = "\n".join([
                    f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                    f"✏️ <b>{F.fb('EDIT WELCOME TEXT')}</b>",
                    F.DIV, "",
                    f"📌 {F.sc('send the welcome message')}",
                ])
                kb = InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        f"{F.EMO['cross']} {F.sc('cancel')}",
                        callback_data="ga:s:welcome",
                    ),
                ]])
                await _safe_edit(q, text, kb)
                return await q.answer()

        # ── AUTO-DELETE ──
        if action == "ad_tog":
            key = parts[2] if len(parts) > 2 else ""
            sess = _sess_get(uid) or {}
            chat_id = _sess_chat_id(uid)
            if not chat_id or not key:
                return await q.answer("❌")
            if not await _is_group_admin(client, chat_id, uid):
                return await q.answer("⛔ Admin only", show_alert=True)

            cfg = await S.get_config(chat_id)
            ad = cfg.get("auto_delete") or {}
            cur = bool(ad.get(key, True))
            await S.save_field(chat_id, f"auto_delete.{key}", not cur)
            await q.answer("🔄")
            text, kb = await P.render_autodel(chat_id)
            await _safe_edit(q, text, kb)
            return

        if action == "ad_timer":
            try:
                secs = int(parts[2])
            except (ValueError, IndexError):
                return await q.answer("❌")
            sess = _sess_get(uid) or {}
            chat_id = _sess_chat_id(uid)
            if not chat_id:
                return await q.answer("❌")
            await S.save_field(
                chat_id, "auto_delete.bot_timer", secs,
            )
            await q.answer(f"⏱️ {secs}s")
            text, kb = await P.render_autodel(chat_id)
            await _safe_edit(q, text, kb)
            return

        if action == "ad_keep":
            try:
                n = int(parts[2])
            except (ValueError, IndexError):
                return await q.answer("❌")
            sess = _sess_get(uid) or {}
            chat_id = _sess_chat_id(uid)
            if not chat_id:
                return await q.answer("❌")
            await S.save_field(
                chat_id, "auto_delete.keep_last_n", n,
            )
            await q.answer(f"🔢 {n}")
            text, kb = await P.render_autodel(chat_id)
            await _safe_edit(q, text, kb)
            return

        # ── FILTERS ──
        if action == "flt_tog":
            key = parts[2] if len(parts) > 2 else ""
            sess = _sess_get(uid) or {}
            chat_id =_sess_chat_id(uid)
            if not chat_id or not key:
                return await q.answer("❌")
            if not await _is_group_admin(client, chat_id, uid):
                return await q.answer("⛔ Admin only", show_alert=True)

            cfg = await S.get_config(chat_id)
            filt = cfg.get("filters") or {}
            cur = bool(filt.get(key, False))
            await S.save_field(chat_id, f"filters.{key}", not cur)
            await q.answer("🔄")
            text, kb = await P.render_filters(chat_id)
            await _safe_edit(q, text, kb)
            return

        if action == "flt_add":
            sess = _sess_get(uid) or {}
            chat_id = _sess_chat_id(uid)
            if not chat_id:
                return await q.answer("❌")
            if not await _is_group_admin(client, chat_id, uid):
                return await q.answer("⛔ Admin only", show_alert=True)

            _sess_new(uid, "flt_add", chat_id)
            text = "\n".join([
                f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                f"➕ <b>{F.fb('ADD BANNED WORD')}</b>",
                F.DIV, "",
                f"📌 {F.sc('send the word as text')}",
            ])
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"{F.EMO['cross']} {F.sc('cancel')}",
                    callback_data="ga:s:filters",
                ),
            ]])
            await _safe_edit(q, text, kb)
            return await q.answer()

        if action == "flt_words":
            sess = _sess_get(uid) or {}
            chat_id = _sess_chat_id(uid)
            if not chat_id:
                return await q.answer("❌")
            text, kb = await P.render_words_list(chat_id)
            await _safe_edit(q, text, kb)
            return await q.answer()

        if action == "flt_clear":
            sess = _sess_get(uid) or {}
            chat_id = _sess_chat_id(uid)
            if not chat_id:
                return await q.answer("❌")
            if not await _is_group_admin(client, chat_id, uid):
                return await q.answer("⛔ Admin only", show_alert=True)
            await S.save_field(chat_id, "filters.banned_words", [])
            await q.answer("🗑️ Cleared")
            text, kb = await P.render_filters(chat_id)
            await _safe_edit(q, text, kb)
            return

        # ── FORCE-SUB ──
        if action == "fs_tog":
            sess = _sess_get(uid) or {}
            chat_id = _sess_chat_id(uid)
            if not chat_id:
                return await q.answer("❌")
            if not await _is_group_admin(client, chat_id, uid):
                return await q.answer("⛔ Admin only", show_alert=True)
            cfg = await S.get_config(chat_id)
            cur = bool((cfg.get("fsub") or {}).get("enabled", False))
            await S.save_field(chat_id, "fsub.enabled", not cur)
            await q.answer("🟢" if not cur else "🔴")
            text, kb = await P.render_fsub(chat_id)
            await _safe_edit(q, text, kb)
            return

        if action == "fs_add":
            sess = _sess_get(uid) or {}
            chat_id = _sess_chat_id(uid)
            if not chat_id:
                return await q.answer("❌")
            if not await _is_group_admin(client, chat_id, uid):
                return await q.answer("⛔ Admin only", show_alert=True)
            _sess_new(uid, "fs_add", chat_id)
            text = "\n".join([
                f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                f"➕ <b>{F.fb('ADD FSUB CHANNEL')}</b>",
                F.DIV, "",
                f"📌 {F.sc('send channel id or @username')}",
                f"📌 {F.sc('bot must be admin there')}",
            ])
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"{F.EMO['cross']} {F.sc('cancel')}",
                    callback_data="ga:s:fsub",
                ),
            ]])
            await _safe_edit(q, text, kb)
            return await q.answer()

        if action == "fs_rm":
            try:
                idx = int(parts[2])
            except (ValueError, IndexError):
                return await q.answer("❌")
            sess = _sess_get(uid) or {}
            chat_id = _sess_chat_id(uid)
            if not chat_id:
                return await q.answer("❌")
            if not await _is_group_admin(client, chat_id, uid):
                return await q.answer("⛔ Admin only", show_alert=True)
            cfg = await S.get_config(chat_id)
            chans = list((cfg.get("fsub") or {}).get("channels") or [])
            if 0 <= idx < len(chans):
                chans.pop(idx)
                await S.save_field(chat_id, "fsub.channels", chans)
            await q.answer("🗑️")
            text, kb = await P.render_fsub(chat_id)
            await _safe_edit(q, text, kb)
            return

        # ── VERIFY ──
        if action in ("v_tog", "v_url", "v_time"):
            sess = _sess_get(uid) or {}
            chat_id = _sess_chat_id(uid)
            if not chat_id:
                return await q.answer("❌")
            if not await _is_group_admin(client, chat_id, uid):
                return await q.answer("⛔ Admin only", show_alert=True)

            if action == "v_tog":
                cfg = await S.get_config(chat_id)
                cur = bool((cfg.get("verify") or {}).get("enabled", False))
                await S.save_field(chat_id, "verify.enabled", not cur)
                await q.answer("🟢" if not cur else "🔴")
                text, kb = await P.render_verify(chat_id)
                await _safe_edit(q, text, kb)
                return

            if action == "v_url":
                _sess_new(uid, "v_url", chat_id)
                text = "\n".join([
                    f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                    f"🔗 <b>{F.fb('SET SHORTENER URL')}</b>",
                    F.DIV, "",
                    f"📌 {F.sc('send the shortener URL')}",
                    f"📌 {F.sc('example')} · "
                    "<code>https://short.link/api?key=X&url=</code>",
                ])
                kb = InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        f"{F.EMO['cross']} {F.sc('cancel')}",
                        callback_data="ga:s:verify",
                    ),
                ]])
                await _safe_edit(q, text, kb)
                return await q.answer()

            if action == "v_time":
                _sess_new(uid, "v_time", chat_id)
                text = "\n".join([
                    f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                    f"⏱️ <b>{F.fb('SET VERIFY TIME')}</b>",
                    F.DIV, "",
                    f"📌 {F.sc('send seconds')}",
                    f"📌 {F.sc('example')} · <code>1200</code>",
                ])
                kb = InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        f"{F.EMO['cross']} {F.sc('cancel')}",
                        callback_data="ga:s:verify",
                    ),
                ]])
                await _safe_edit(q, text, kb)
                return await q.answer()

        # ── SECURITY ──
        if action == "sec":
            key = parts[2] if len(parts) > 2 else ""
            sess = _sess_get(uid) or {}
            chat_id = _sess_chat_id(uid)
            if not chat_id or not key:
                return await q.answer("❌")
            if not await _is_group_admin(client, chat_id, uid):
                return await q.answer("⛔ Admin only", show_alert=True)
            cfg = await S.get_config(chat_id)
            cur = bool((cfg.get("security") or {}).get(key, True))
            await S.save_field(chat_id, f"security.{key}", not cur)
            await q.answer("🔄")
            text, kb = await P.render_security(chat_id)
            await _safe_edit(q, text, kb)
            return

        # ── REQUESTS ──
        if action == "req_tog":
            key = parts[2] if len(parts) > 2 else ""
            sess = _sess_get(uid) or {}
            chat_id = _sess_chat_id(uid)
            if not chat_id or not key:
                return await q.answer("❌")
            if not await _is_group_admin(client, chat_id, uid):
                return await q.answer("⛔ Admin only", show_alert=True)
            cfg = await S.get_config(chat_id)
            cur = bool((cfg.get("requests") or {}).get(key, True))
            await S.save_field(chat_id, f"requests.{key}", not cur)
            await q.answer("🔄")
            text, kb = await P.render_requests(chat_id)
            await _safe_edit(q, text, kb)
            return

        if action == "req_ch":
            sess = _sess_get(uid) or {}
            chat_id = _sess_chat_id(uid)
            if not chat_id:
                return await q.answer("❌")
            if not await _is_group_admin(client, chat_id, uid):
                return await q.answer("⛔ Admin only", show_alert=True)
            _sess_new(uid, "req_ch", chat_id)
            text = "\n".join([
                f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                f"📢 <b>{F.fb('SET REQUEST CHANNEL')}</b>",
                F.DIV, "",
                f"📌 {F.sc('send channel id or @username')}",
            ])
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"{F.EMO['cross']} {F.sc('cancel')}",
                    callback_data="ga:s:requests",
                ),
            ]])
            await _safe_edit(q, text, kb)
            return await q.answer()

        # ── METADATA ──
        if action == "meta_tog":
            key = parts[2] if len(parts) > 2 else ""
            sess = _sess_get(uid) or {}
            chat_id = _sess_chat_id(uid)
            if not chat_id or not key:
                return await q.answer("❌")
            if not await _is_group_admin(client, chat_id, uid):
                return await q.answer("⛔ Admin only", show_alert=True)
            cfg = await S.get_config(chat_id)
            cur = bool((cfg.get("metadata") or {}).get(key, True))
            await S.save_field(chat_id, f"metadata.{key}", not cur)
            await q.answer("🔄")
            text, kb = await P.render_metadata(chat_id)
            await _safe_edit(q, text, kb)
            return

        # ── STATS RESET ──
        if action == "stats_reset":
            chat_id = _sess_chat_id(uid)
            if not chat_id:
                return await q.answer(
                    "⚠️ Session expired — reopen the panel",
                    show_alert=True,
                )
            if not await _is_group_admin(client, chat_id, uid):
                return await q.answer("⛔ Admin only", show_alert=True)

            from datetime import datetime
            await S.save_field(chat_id, "stats", {
                "searches_today": 0,
                "results_found": 0,
                "not_found": 0,
                "files_sent": 0,
                "updated_at": datetime.utcnow(),
            })
            await q.answer("♻️ Reset")
            text, kb = await P.render_stats(chat_id)
            await _safe_edit(q, text, kb)
            return

        # ── RESET ALL ──
        if action == "reset_do":
            sess = _sess_get(uid) or {}
            chat_id = _sess_chat_id(uid)
            if not chat_id:
                return await q.answer("❌")
            if not await _is_group_admin(client, chat_id, uid):
                return await q.answer("⛔ Admin only", show_alert=True)
            await S.reset_config(chat_id)
            await q.answer("♻️ Reset complete")
            text, kb = await P.render_main(chat_id)
            await _safe_edit(q, text, kb)
            return

        # ── UNKNOWN ──
        return await q.answer("❓ Unknown")

    except Exception as e:
        logger.exception(f"[GROUPS] router: {e}")
        try:
            await q.answer(f"❌ {type(e).__name__}", show_alert=True)
        except Exception:
            pass


# ============================================================
# SECTION 7 — PUBLIC API
# ============================================================

def has_pending(uid: int) -> bool:
    """Used by text_input.py to check for active sessions."""
    return _has_pending(uid)


def get_session(uid: int) -> Optional[Dict[str, Any]]:
    return _sess_get(uid)


def drop_session(uid: int) -> None:
    _sess_drop(uid)


def snapshot() -> Dict[str, Any]:
    return {
        "pending_sessions": len(_sessions),
        "active_chat_ids": list({
            s["chat_id"] for s in _sessions.values()
        }),
    }


__all__ = [
    "open_panel_for_chat",
    "open_panel_edit",
    "has_pending",
    "get_session",
    "drop_session",
    "snapshot",
]
