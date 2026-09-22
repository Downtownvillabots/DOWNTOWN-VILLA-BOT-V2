# ============================================================
# 🏨 DOWNTOWN VILLA — GROUP ADMIN MAIN ENTRY + ROUTER
# ============================================================
#
# ONE main callback router for the whole group admin panel.
# Every button goes through here.
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
from plugins.group_admin import state as S
from plugins.group_admin import panel as P
from utils import fonts as F

logger = logging.getLogger(__name__)

PFX = "ga"


# ── SESSION ──
_sessions: Dict[int, Dict[str, Any]] = {}
TTL = 900.0


def _ss_get(uid: int) -> Optional[Dict[str, Any]]:
    s = _sessions.get(int(uid))
    if not s: return None
    if time.time() > s["exp"]:
        _sessions.pop(int(uid), None)
        return None
    return s


def _ss_new(uid: int, **data):
    _sessions[int(uid)] = {"exp": time.time() + TTL, **data}


def _ss_set(uid: int, **data):
    s = _sessions.get(int(uid))
    if s:
        s.update(data)
        s["exp"] = time.time() + TTL


def _ss_drop(uid: int):
    _sessions.pop(int(uid), None)


# ── AUTH ──
def _is_admin(uid) -> bool:
    try:
        return int(uid) in [int(a) for a in config.ADMINS]
    except Exception:
        return False


async def _is_group_admin(client, chat_id, user_id) -> bool:
    if _is_admin(user_id):
        return True
    try:
        m = await client.get_chat_member(chat_id, user_id)
        st = getattr(m, "status", None)
        st = st.name.lower() if hasattr(st, "name") else str(st).lower()
        return st in ("administrator", "creator", "owner")
    except Exception:
        return False


# ============================================================
# PM /start handler for group links: gs:<chat_id>
# ============================================================

@Client.on_message(
    filters.command("start") & filters.private,
    group=-8510,
)
async def start_group_settings(client: Client, message: Message):
    try:
        if not message.from_user:
            return
        args = (message.text or "").split(maxsplit=1)
        if len(args) < 2: return
        payload = args[1]

        if not payload.startswith("gs:"):
            return

        try:
            chat_id = int(payload[3:])
        except ValueError:
            return

        # Verify admin
        if not await _is_group_admin(client, chat_id, message.from_user.id):
            return await message.reply_text(
                f"{F.EMO['cross']} <b>You are not admin of that group.</b>",
                parse_mode=ParseMode.HTML,
            )

        await S.register_group(chat_id)

        text, kb = await P.render_main(chat_id)
        await message.reply_text(
            text, reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )

        try:
            message.stop_propagation()
        except Exception:
            pass

    except Exception as e:
        logger.exception(f"[GADMIN] start hook: {e}")


# ============================================================
# MAIN ROUTER
# ============================================================

@Client.on_callback_query(
    filters.regex(rf"^{PFX}:"),
    group=-8500,
)
async def group_admin_router(client: Client, q: CallbackQuery):
    if not q.from_user:
        return await q.answer()

    parts = str(q.data).split(":")
    action = parts[1] if len(parts) > 1 else ""

    try:
        # ── CLOSE ──
        if action == "close":
            try: await q.message.delete()
            except Exception: pass
            return await q.answer("Closed")

        # ── LIST (owner PM) ──
        if action == "list":
            if not _is_admin(q.from_user.id):
                return await q.answer("⛔", show_alert=True)
            from plugins.group_admin.commands import _show_group_list
            try: await q.message.delete()
            except Exception: pass
            await _show_group_list(q.message)
            return await q.answer()

        # ── OPEN (from any chat) ──
        if action == "open":
            try:
                chat_id = int(parts[2])
            except (ValueError, IndexError):
                return await q.answer("❌")
            if not await _is_group_admin(client, chat_id, q.from_user.id):
                return await q.answer("⛔", show_alert=True)

            await S.register_group(chat_id)
            text, kb = await P.render_main(chat_id)
            await _safe_edit(q, text, kb)
            return await q.answer()

        # ── BACK → main panel ──
        if action == "back":
            sess = _ss_get(q.from_user.id)
            chat_id = (sess or {}).get("chat_id")
            if not chat_id:
                # try parse from callback? fallback: use message chat id
                chat_id = q.message.chat.id if q.message.chat else 0
            text, kb = await P.render_main(chat_id)
            await _safe_edit(q, text, kb)
            return await q.answer()

        # ── SECTION: navigate ──
        if action == "s":
            section = parts[2] if len(parts) > 2 else ""

            sess = _ss_get(q.from_user.id) or {}
            chat_id = sess.get("chat_id")

            if not chat_id:
                # From group context
                chat_id = q.message.chat.id if q.message.chat else 0

            if not chat_id:
                return await q.answer("❌ Chat not found", show_alert=True)

            if not await _is_group_admin(client, chat_id, q.from_user.id):
                return await q.answer("⛔", show_alert=True)

            await S.register_group(chat_id)

            # Render the section
            if section == "refresh":
                text, kb = await P.render_main(chat_id)
            elif section == "search":
                text, kb = await P.render_search(chat_id)
            elif section == "content":
                text, kb = await P.render_content(chat_id)
            elif section == "flow":
                text, kb = await P.render_flow(chat_id)
            elif section == "caption":
                text, kb = await P.render_caption(chat_id)
            elif section == "buttons":
                text, kb = await P.render_buttons(chat_id)
            elif section == "welcome":
                text, kb = await P.render_welcome(chat_id)
            elif section == "autodel":
                text, kb = await P.render_autodel(chat_id)
            elif section == "filters":
                text, kb = await P.render_filters(chat_id)
            elif section == "fsub":
                text, kb = await P.render_fsub(chat_id)
            elif section == "verify":
                text, kb = await P.render_verify(chat_id)
            elif section == "security":
                text, kb = await P.render_security(chat_id)
            elif section == "requests":
                text, kb = await P.render_requests(chat_id)
            elif section == "metadata":
                text, kb = await P.render_metadata(chat_id)
            elif section == "stats":
                text, kb = await P.render_stats(chat_id)
            elif section == "view":
                text, kb = await P.render_view(chat_id)
            elif section == "reset":
                text, kb = await P.render_reset(chat_id)
            else:
                text, kb = await P.render_main(chat_id)

            await _safe_edit(q, text, kb)
            return await q.answer()

        # ── TOGGLE (generic) ──
        if action == "tog":
            field = parts[2] if len(parts) > 2 else ""
            sess = _ss_get(q.from_user.id) or {}
            chat_id = sess.get("chat_id") or (q.message.chat.id if q.message.chat else 0)
            if not chat_id:
                return await q.answer("❌")
            if not await _is_group_admin(client, chat_id, q.from_user.id):
                return await q.answer("⛔", show_alert=True)

            cfg = await S.get_config(chat_id)
            cur = bool(cfg.get(field, False))
            await S.save_field(chat_id, field, not cur)
            await q.answer(f"{'🟢 ON' if not cur else '🔴 OFF'}")

            text, kb = await P.render_search(chat_id)
            await _safe_edit(q, text, kb)
            return

        # ── SET (content mode etc) ──
        if action == "set":
            sub = parts[2] if len(parts) > 2 else ""
            val = parts[3] if len(parts) > 3 else ""
            sess = _ss_get(q.from_user.id) or {}
            chat_id = sess.get("chat_id") or (q.message.chat.id if q.message.chat else 0)
            if not chat_id:
                return await q.answer("❌")
            if not await _is_group_admin(client, chat_id, q.from_user.id):
                return await q.answer("⛔", show_alert=True)

            if sub == "content":
                await S.save_field(chat_id, "content_mode", val)
                await q.answer(f"✅ {val}")

            text, kb = await P.render_content(chat_id)
            await _safe_edit(q, text, kb)
            return

        # ── FLOW ──
        if action == "flow":
            key = parts[2] if len(parts) > 2 else ""
            sess = _ss_get(q.from_user.id) or {}
            chat_id = sess.get("chat_id") or (q.message.chat.id if q.message.chat else 0)
            if not chat_id:
                return await q.answer("❌")
            text, kb = await P.render_flow_step(chat_id, key)
            await _safe_edit(q, text, kb)
            return await q.answer()

        if action == "flow_tog":
            key = parts[2]
            sess = _ss_get(q.from_user.id) or {}
            chat_id = sess.get("chat_id") or (q.message.chat.id if q.message.chat else 0)
            if not chat_id:
                return await q.answer("❌")

            cfg = await S.get_config(chat_id)
            flow = cfg.get("flow") or {}
            cur = bool((flow.get(key) or {}).get("enabled", True))
            await S.save_field(chat_id, f"flow.{key}.enabled", not cur)
            await q.answer(f"{'🟢' if not cur else '🔴'}")
            text, kb = await P.render_flow_step(chat_id, key)
            await _safe_edit(q, text, kb)
            return

        if action == "flow_row":
            key = parts[2]
            n = int(parts[3])
            sess = _ss_get(q.from_user.id) or {}
            chat_id = sess.get("chat_id") or (q.message.chat.id if q.message.chat else 0)
            if not chat_id:
                return await q.answer("❌")
            await S.save_field(chat_id, f"flow.{key}.per_row", n)
            await q.answer(f"✅ {n}/row")
            text, kb = await P.render_flow_step(chat_id, key)
            await _safe_edit(q, text, kb)
            return

        if action == "flow_skip":
            key = parts[2]
            sess = _ss_get(q.from_user.id) or {}
            chat_id = sess.get("chat_id") or (q.message.chat.id if q.message.chat else 0)
            if not chat_id:
                return await q.answer("❌")
            cfg = await S.get_config(chat_id)
            cur = bool(((cfg.get("flow") or {}).get(key) or {}).get("auto_skip", True))
            await S.save_field(chat_id, f"flow.{key}.auto_skip", not cur)
            await q.answer("Toggled")
            text, kb = await P.render_flow_step(chat_id, key)
            await _safe_edit(q, text, kb)
            return

        # ── CAPTION edit ──
        if action == "cap":
            sub = parts[2] if len(parts) > 2 else ""
            sess = _ss_get(q.from_user.id) or {}
            chat_id = sess.get("chat_id") or (q.message.chat.id if q.message.chat else 0)
            if not chat_id:
                return await q.answer("❌")

            if sub == "edit":
                _ss_new(q.from_user.id, chat_id=chat_id, step="cap_edit")
                text = "\n".join([
                    f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                    f"📝 <b>{F.fb('EDIT CAPTION')}</b>",
                    F.DIV, "",
                    f"📌 {F.sc('send the new caption as next message')}",
                    f"📌 {F.sc('or send')} <code>-</code> "
                    f"{F.sc('to reset')}",
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
                cfg = await S.get_config(chat_id)
                tpl = cfg.get("caption_template")
                if not tpl:
                    await q.answer("⚠️ No custom caption set", show_alert=True)
                    return
                sample = {
                    "title": "Example Movie",
                    "year": 2024,
                    "quality": "1080p",
                    "codec": "HEVC",
                    "audio": "English",
                    "subtitle": "English",
                    "size": "2.4 GB",
                    "season": "",
                    "episode": "",
                    "bot_username": "examplebot",
                }
                try:
                    preview = str(tpl).format(**sample)
                except Exception as e:
                    preview = f"(error: {e})\n\n{tpl}"
                text = "\n".join([
                    f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                    f"👁️ <b>{F.fb('PREVIEW')}</b>",
                    F.DIV, "",
                    preview,
                ])
                kb = InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        f"{F.EMO['back']} {F.sc('back')}",
                        callback_data="ga:s:caption",
                    ),
                ]])
                await _safe_edit(q, text, kb)
                return await q.answer()

        # ── BUTTONS ──
        if action == "btn":
            sub = parts[2] if len(parts) > 2 else ""
            sess = _ss_get(q.from_user.id) or {}
            chat_id = sess.get("chat_id") or (q.message.chat.id if q.message.chat else 0)
            if not chat_id:
                return await q.answer("❌")

            if sub == "view":
                idx = int(parts[3])
                text, kb = await P.render_button_view(chat_id, idx)
                await _safe_edit(q, text, kb)
                return await q.answer()

            if sub == "add":
                _ss_new(q.from_user.id, chat_id=chat_id, step="btn_add")
                text = "\n".join([
                    f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                    f"➕ <b>{F.fb('ADD BUTTON')}</b>",
                    F.DIV, "",
                    f"📌 {F.sc('send')} <code>Name | URL</code>",
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
                idx = int(parts[3])
                cfg = await S.get_config(chat_id)
                btns = list(cfg.get("result_buttons") or [])
                if 0 <= idx < len(btns):
                    btns[idx]["enabled"] = not btns[idx].get("enabled", True)
                    await S.save_field(chat_id, "result_buttons", btns)
                await q.answer("Toggled")
                text, kb = await P.render_button_view(chat_id, idx)
                await _safe_edit(q, text, kb)
                return

            if sub == "del":
                idx = int(parts[3])
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

        if action == "btn_row":
            n = int(parts[2])
            sess = _ss_get(q.from_user.id) or {}
            chat_id = sess.get("chat_id") or (q.message.chat.id if q.message.chat else 0)
            if not chat_id:
                return await q.answer("❌")
            await S.save_field(chat_id, "buttons_per_row", n)
            await q.answer(f"✅ {n}/row")
            text, kb = await P.render_buttons(chat_id)
            await _safe_edit(q, text, kb)
            return

        if action in ("btn_edit_name", "btn_edit_url"):
            idx = int(parts[2])
            sess = _ss_get(q.from_user.id) or {}
            chat_id = sess.get("chat_id") or (q.message.chat.id if q.message.chat else 0)
            if not chat_id:
                return await q.answer("❌")
            kind = "name" if action == "btn_edit_name" else "url"
            _ss_new(q.from_user.id, chat_id=chat_id, step=f"btn_{kind}", idx=idx)
            text = "\n".join([
                f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                f"✏️ <b>{F.fb(f'EDIT {kind.upper()}')}</b>",
                F.DIV, "",
                f"📌 {F.sc(f'send the new {kind} as text')}",
            ])
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"{F.EMO['cross']} {F.sc('cancel')}",
                    callback_data=f"ga:btn:view:{idx}",
                ),
            ]])
            await _safe_edit(q, text, kb)
            return await q.answer()

        # ── WELCOME ──
        if action == "w_tog":
            sess = _ss_get(q.from_user.id) or {}
            chat_id = sess.get("chat_id") or (q.message.chat.id if q.message.chat else 0)
            cfg = await S.get_config(chat_id)
            cur = bool(cfg.get("welcome_enabled", False))
            await S.save_field(chat_id, "welcome_enabled", not cur)
            await q.answer("🟢" if not cur else "🔴")
            text, kb = await P.render_welcome(chat_id)
            await _safe_edit(q, text, kb)
            return

        if action == "w_edit":
            sess = _ss_get(q.from_user.id) or {}
            chat_id = sess.get("chat_id") or (q.message.chat.id if q.message.chat else 0)
            _ss_new(q.from_user.id, chat_id=chat_id, step="w_edit")
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

        if action == "w_adtog":
            sess = _ss_get(q.from_user.id) or {}
            chat_id = sess.get("chat_id") or (q.message.chat.id if q.message.chat else 0)
            cfg = await S.get_config(chat_id)
            cur = bool(cfg.get("welcome_auto_delete", True))
            await S.save_field(chat_id, "welcome_auto_delete", not cur)
            await q.answer("Toggled")
            text, kb = await P.render_welcome(chat_id)
            await _safe_edit(q, text, kb)
            return

        # ── AUTO-DELETE ──
        if action == "ad_tog":
            key = parts[2]
            sess = _ss_get(q.from_user.id) or {}
            chat_id = sess.get("chat_id") or (q.message.chat.id if q.message.chat else 0)
            cfg = await S.get_config(chat_id)
            cur = bool((cfg.get("auto_delete") or {}).get(key, True))
            await S.save_field(chat_id, f"auto_delete.{key}", not cur)
            await q.answer("Toggled")
            text, kb = await P.render_autodel(chat_id)
            await _safe_edit(q, text, kb)
            return

        if action == "ad_timer":
            secs = int(parts[2])
            sess = _ss_get(q.from_user.id) or {}
            chat_id = sess.get("chat_id") or (q.message.chat.id if q.message.chat else 0)
            await S.save_field(chat_id, "auto_delete.bot_timer", secs)
            await q.answer(f"✅ {secs}s")
            text, kb = await P.render_autodel(chat_id)
            await _safe_edit(q, text, kb)
            return

        if action == "ad_keep":
            n = int(parts[2])
            sess = _ss_get(q.from_user.id) or {}
            chat_id = sess.get("chat_id") or (q.message.chat.id if q.message.chat else 0)
            await S.save_field(chat_id, "auto_delete.keep_last_n", n)
            await q.answer(f"✅ {n}")
            text, kb = await P.render_autodel(chat_id)
            await _safe_edit(q, text, kb)
            return

        # ── FILTERS ──
        if action == "flt_tog":
            key = parts[2]
            sess = _ss_get(q.from_user.id) or {}
            chat_id = sess.get("chat_id") or (q.message.chat.id if q.message.chat else 0)
            cfg = await S.get_config(chat_id)
            cur = bool((cfg.get("filters") or {}).get(key, False))
            await S.save_field(chat_id, f"filters.{key}", not cur)
            await q.answer("Toggled")
            text, kb = await P.render_filters(chat_id)
            await _safe_edit(q, text, kb)
            return

        if action == "flt_add":
            sess = _ss_get(q.from_user.id) or {}
            chat_id = sess.get("chat_id") or (q.message.chat.id if q.message.chat else 0)
            _ss_new(q.from_user.id, chat_id=chat_id, step="flt_add")
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

        if action == "flt_clear":
            sess = _ss_get(q.from_user.id) or {}
            chat_id = sess.get("chat_id") or (q.message.chat.id if q.message.chat else 0)
            await S.save_field(chat_id, "filters.banned_words", [])
            await q.answer("🗑️ Cleared")
            text, kb = await P.render_filters(chat_id)
            await _safe_edit(q, text, kb)
            return

        if action == "flt_words":
            sess = _ss_get(q.from_user.id) or {}
            chat_id = sess.get("chat_id") or (q.message.chat.id if q.message.chat else 0)
            cfg = await S.get_config(chat_id)
            words = (cfg.get("filters") or {}).get("banned_words") or []
            lines = [
                f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                f"🔤 <b>{F.fb('BANNED WORDS')}</b>",
                F.DIV, "",
            ]
            if not words:
                lines.append(f"⚪ {F.sc('no words yet')}")
            else:
                for i, w in enumerate(words, 1):
                    lines.append(f"<b>{i:02d}.</b> <code>{w}</code>")
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"{F.EMO['back']} {F.sc('back')}",
                    callback_data="ga:s:filters",
                ),
            ]])
            await _safe_edit(q, "\n".join(lines), kb)
            return await q.answer()

        # ── FSUB ──
        if action == "fs_tog":
            sess = _ss_get(q.from_user.id) or {}
            chat_id = sess.get("chat_id") or (q.message.chat.id if q.message.chat else 0)
            cfg = await S.get_config(chat_id)
            cur = bool((cfg.get("fsub") or {}).get("enabled", False))
            await S.save_field(chat_id, "fsub.enabled", not cur)
            await q.answer("Toggled")
            text, kb = await P.render_fsub(chat_id)
            await _safe_edit(q, text, kb)
            return

        if action == "fs_add":
            sess = _ss_get(q.from_user.id) or {}
            chat_id = sess.get("chat_id") or (q.message.chat.id if q.message.chat else 0)
            _ss_new(q.from_user.id, chat_id=chat_id, step="fs_add")
            text = "\n".join([
                f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                f"➕ <b>{F.fb('ADD FSUB CHANNEL')}</b>",
                F.DIV, "",
                f"📌 {F.sc('send channel id or @username')}",
            ])
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"{F.EMO['cross']} {F.sc('cancel')}",
                    callback_data="ga:s:fsub",
                ),
            ]])
            await _safe_edit(q, text, kb)
            return await q.answer()

        if action == "fs_rm_menu":
            sess = _ss_get(q.from_user.id) or {}
            chat_id = sess.get("chat_id") or (q.message.chat.id if q.message.chat else 0)
            cfg = await S.get_config(chat_id)
            chans = (cfg.get("fsub") or {}).get("channels") or []
            rows = []
            for c in chans:
                rows.append([InlineKeyboardButton(
                    f"🗑️ {c}",
                    callback_data=f"ga:fs_rm:{c}",
                )])
            rows.append([InlineKeyboardButton(
                f"{F.EMO['back']} {F.sc('back')}",
                callback_data="ga:s:fsub",
            )])
            text = "\n".join([
                f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                f"🗑️ <b>{F.fb('REMOVE CHANNEL')}</b>",
                F.DIV, "",
                f"📌 {F.sc('pick one to remove')}",
            ])
            await _safe_edit(q, text, InlineKeyboardMarkup(rows))
            return await q.answer()

        if action == "fs_rm":
            try:
                target = int(parts[2])
            except ValueError:
                target = parts[2]
            sess = _ss_get(q.from_user.id) or {}
            chat_id = sess.get("chat_id") or (q.message.chat.id if q.message.chat else 0)
            cfg = await S.get_config(chat_id)
            chans = list((cfg.get("fsub") or {}).get("channels") or [])
            try:
                ti = int(target)
            except ValueError:
                ti = target
            if ti in chans:
                chans.remove(ti)
            await S.save_field(chat_id, "fsub.channels", chans)
            await q.answer("🗑️")
            text, kb = await P.render_fsub(chat_id)
            await _safe_edit(q, text, kb)
            return

        # ── VERIFY ──
        if action == "v_tog":
            sess = _ss_get(q.from_user.id) or {}
            chat_id = sess.get("chat_id") or (q.message.chat.id if q.message.chat else 0)
            cfg = await S.get_config(chat_id)
            cur = bool((cfg.get("verify") or {}).get("enabled", False))
            await S.save_field(chat_id, "verify.enabled", not cur)
            await q.answer("Toggled")
            text, kb = await P.render_verify(chat_id)
            await _safe_edit(q, text, kb)
            return

        if action == "v_url":
            sess = _ss_get(q.from_user.id) or {}
            chat_id = sess.get("chat_id") or (q.message.chat.id if q.message.chat else 0)
            _ss_new(q.from_user.id, chat_id=chat_id, step="v_url")
            text = "\n".join([
                f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                f"🔗 <b>{F.fb('SET SHORTENER URL')}</b>",
                F.DIV, "",
                f"📌 {F.sc('send the shortener URL')}",
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
            sess = _ss_get(q.from_user.id) or {}
            chat_id = sess.get("chat_id") or (q.message.chat.id if q.message.chat else 0)
            _ss_new(q.from_user.id, chat_id=chat_id, step="v_time")
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
            sess = _ss_get(q.from_user.id) or {}
            chat_id = sess.get("chat_id") or (q.message.chat.id if q.message.chat else 0)
            cfg = await S.get_config(chat_id)
            cur = bool((cfg.get("security") or {}).get(key, True))
            await S.save_field(chat_id, f"security.{key}", not cur)
            await q.answer("Toggled")
            text, kb = await P.render_security(chat_id)
            await _safe_edit(q, text, kb)
            return

        # ── REQUESTS ──
        if action == "req_tog":
            key = parts[2] if len(parts) > 2 else ""
            sess = _ss_get(q.from_user.id) or {}
            chat_id = sess.get("chat_id") or (q.message.chat.id if q.message.chat else 0)
            cfg = await S.get_config(chat_id)
            cur = bool((cfg.get("requests") or {}).get(key, True))
            await S.save_field(chat_id, f"requests.{key}", not cur)
            await q.answer("Toggled")
            text, kb = await P.render_requests(chat_id)
            await _safe_edit(q, text, kb)
            return

        if action == "req_channel":
            sess = _ss_get(q.from_user.id) or {}
            chat_id = sess.get("chat_id") or (q.message.chat.id if q.message.chat else 0)
            _ss_new(q.from_user.id, chat_id=chat_id, step="req_channel")
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
            sess = _ss_get(q.from_user.id) or {}
            chat_id = sess.get("chat_id") or (q.message.chat.id if q.message.chat else 0)
            cfg = await S.get_config(chat_id)
            cur = bool((cfg.get("metadata") or {}).get(key, True))
            await S.save_field(chat_id, f"metadata.{key}", not cur)
            await q.answer("Toggled")
            text, kb = await P.render_metadata(chat_id)
            await _safe_edit(q, text, kb)
            return

        # ── STATS reset ──
        if action == "stats_reset":
            sess = _ss_get(q.from_user.id) or {}
            chat_id = sess.get("chat_id") or (q.message.chat.id if q.message.chat else 0)
            await S.save_field(chat_id, "stats", {
                "searches_today": 0,
                "results_found": 0,
                "not_found": 0,
                "files_sent": 0,
                "updated_at": __import__("time").time(),
            })
            await q.answer("♻️ Reset")
            text, kb = await P.render_stats(chat_id)
            await _safe_edit(q, text, kb)
            return

        # ── RESET ALL ──
        if action == "reset_do":
            sess = _ss_get(q.from_user.id) or {}
            chat_id = sess.get("chat_id") or (q.message.chat.id if q.message.chat else 0)
            await S.reset_config(chat_id)
            await q.answer("♻️ Reset all")
            text, kb = await P.render_main(chat_id)
            await _safe_edit(q, text, kb)
            return

        return await q.answer("❓")

    except Exception as e:
        logger.exception(f"[GADMIN] router: {e}")
        try:
            await q.answer(f"❌ {type(e).__name__}", show_alert=True)
        except Exception:
            pass


# ============================================================
# TEXT INPUT
# ============================================================

@Client.on_message(
    filters.private & filters.text & ~filters.regex(r"^/"),
    group=-8490,
)
async def group_admin_text_input(client: Client, message: Message):
    if not message.from_user:
        return
    s = _ss_get(message.from_user.id)
    if not s: return

    step = s.get("step")
    chat_id = s.get("chat_id")
    text = (message.text or "").strip()
    if not step or not chat_id:
        return

    # ── CAPTION edit ──
    if step == "cap_edit":
        if text == "-":
            await S.save_field(chat_id, "caption_template", None)
            reply = "♻️ Reset to global"
        else:
            if len(text) < 3:
                return await message.reply_text("❌ Too short.")
            await S.save_field(chat_id, "caption_template", text)
            reply = "✅ Caption saved"
        _ss_drop(message.from_user.id)
        await message.reply_text(reply)
        try: message.stop_propagation()
        except Exception: pass
        return

    # ── BUTTON add ──
    if step == "btn_add":
        if "|" not in text:
            return await message.reply_text("❌ Format: <code>Name | URL</code>",
                                            parse_mode=ParseMode.HTML)
        name, url = [p.strip() for p in text.split("|", 1)]
        if not name or not url:
            return await message.reply_text("❌ Empty.")
        if url.startswith("@"): url = f"https://t.me/{url[1:]}"
        elif not (url.startswith("http://") or url.startswith("https://")
                  or url.startswith("tg://")):
            if "." in url and " " not in url:
                url = f"https://{url}"
            else:
                return await message.reply_text("❌ Invalid URL.")
        cfg = await S.get_config(chat_id)
        btns = list(cfg.get("result_buttons") or [])
        if len(btns) >= 8:
            _ss_drop(message.from_user.id)
            return await message.reply_text("⚠️ Max 8 buttons.")
        btns.append({"name": name[:60], "url": url, "enabled": True,
                     "position": len(btns) + 1})
        await S.save_field(chat_id, "result_buttons", btns)
        _ss_drop(message.from_user.id)
        await message.reply_text(f"✅ Added: <b>{F.sc(name)}</b>",
                                 parse_mode=ParseMode.HTML)
        try: message.stop_propagation()
        except Exception: pass
        return

    # ── BUTTON edit name/url ──
    if step in ("btn_name", "btn_url"):
        idx = int(s.get("idx", 0))
        cfg = await S.get_config(chat_id)
        btns = list(cfg.get("result_buttons") or [])
        if idx < 0 or idx >= len(btns):
            _ss_drop(message.from_user.id)
            return await message.reply_text("❌ Invalid index.")

        if step == "btn_name":
            btns[idx]["name"] = text[:60]
        else:
            url = text
            if url.startswith("@"): url = f"https://t.me/{url[1:]}"
            elif not (url.startswith("http://") or url.startswith("https://")
                      or url.startswith("tg://")):
                if "." in url and " " not in url:
                    url = f"https://{url}"
                else:
                    return await message.reply_text("❌ Invalid URL.")
            btns[idx]["url"] = url

        await S.save_field(chat_id, "result_buttons", btns)
        _ss_drop(message.from_user.id)
        await message.reply_text(f"✅ Updated.")
        try: message.stop_propagation()
        except Exception: pass
        return

    # ── WELCOME edit ──
    if step == "w_edit":
        if len(text) < 3:
            return await message.reply_text("❌ Too short.")
        await S.save_field(chat_id, "welcome_text", text)
        _ss_drop(message.from_user.id)
        await message.reply_text(f"✅ Saved.")
        try: message.stop_propagation()
        except Exception: pass
        return

    # ── FILTER add ──
    if step == "flt_add":
        word = text.lower().strip()
        if not word:
            return await message.reply_text("❌ Empty.")
        cfg = await S.get_config(chat_id)
        words = list((cfg.get("filters") or {}).get("banned_words") or [])
        if word not in words:
            words.append(word)
            await S.save_field(chat_id, "filters.banned_words", words)
        _ss_drop(message.from_user.id)
        await message.reply_text(f"✅ Added: <code>{word}</code>",
                                 parse_mode=ParseMode.HTML)
        try: message.stop_propagation()
        except Exception: pass
        return

    # ── FSUB add channel ──
    if step == "fs_add":
        target = None
        if text.startswith("@"):
            try:
                ch = await client.get_chat(text)
                target = ch.id
            except Exception as e:
                return await message.reply_text(f"❌ {e}")
        else:
            try:
                target = int(text)
            except ValueError:
                return await message.reply_text("❌ Invalid.")

        cfg = await S.get_config(chat_id)
        chans = list((cfg.get("fsub") or {}).get("channels") or [])
        if target not in chans:
            chans.append(target)
            await S.save_field(chat_id, "fsub.channels", chans)
        _ss_drop(message.from_user.id)
        await message.reply_text(f"✅ Added: <code>{target}</code>",
                                 parse_mode=ParseMode.HTML)
        try: message.stop_propagation()
        except Exception: pass
        return

    # ── VERIFY url ──
    if step == "v_url":
        if not text.startswith("http"):
            return await message.reply_text("❌ Invalid URL.")
        await S.save_field(chat_id, "verify.shortener_url", text)
        _ss_drop(message.from_user.id)
        await message.reply_text(f"✅ URL saved.")
        try: message.stop_propagation()
        except Exception: pass
        return

    # ── VERIFY time ──
    if step == "v_time":
        try:
            secs = int(text)
            if secs < 60:
                raise ValueError
        except ValueError:
            return await message.reply_text("❌ Invalid seconds.")
        await S.save_field(chat_id, "verify.verify_time", secs)
        _ss_drop(message.from_user.id)
        await message.reply_text(f"✅ Time set to {secs}s.")
        try: message.stop_propagation()
        except Exception: pass
        return

    # ── REQUEST channel ──
    if step == "req_channel":
        target = None
        if text.startswith("@"):
            try:
                ch = await client.get_chat(text)
                target = ch.id
            except Exception as e:
                return await message.reply_text(f"❌ {e}")
        else:
            try:
                target = int(text)
            except ValueError:
                return await message.reply_text("❌ Invalid.")
        await S.save_field(chat_id, "requests.channel", target)
        _ss_drop(message.from_user.id)
        await message.reply_text(f"✅ Channel set.")
        try: message.stop_propagation()
        except Exception: pass
        return

    _ss_drop(message.from_user.id)


# ============================================================
# HELPERS
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
            logger.debug(f"[GADMIN] edit: {e}")


def snapshot() -> Dict[str, Any]:
    return {"module": "group_admin"}


__all__ = ["start_group_settings", "snapshot"]
