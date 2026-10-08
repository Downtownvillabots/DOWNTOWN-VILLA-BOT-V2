# ============================================================
# 🏨 DOWNTOWN VILLA — OTT PANEL + ROUTER
# ============================================================

from __future__ import annotations
import logging
import time
from typing import Any, Dict, Optional

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import CallbackQuery

from plugins.broadcast.config import _is_admin
from plugins.ott import views as V
from plugins.ott import keyboards as KB
from plugins.ott import database as DB
from plugins.ott.config import PREFIX, FREQ_MODES

logger = logging.getLogger(__name__)
PFX = PREFIX

# In-memory text-input sessions
_SESS: Dict[int, Dict[str, Any]] = {}
_SESS_TTL = 600


def _sess_set(uid: int, kind: str, **data) -> None:
    _SESS[int(uid)] = {
        "kind": kind, "data": data,
        "expires": time.time() + _SESS_TTL,
    }


def _sess_get(uid: int) -> Optional[Dict[str, Any]]:
    s = _SESS.get(int(uid))
    if not s:
        return None
    if time.time() > s["expires"]:
        _SESS.pop(int(uid), None)
        return None
    return s


def _sess_drop(uid: int) -> None:
    _SESS.pop(int(uid), None)


# ═══════════════════════════════════════════════════════════
# ENTRY FROM /admin
# ═══════════════════════════════════════════════════════════

async def open_panel_for_admin(client: Client, q: CallbackQuery) -> None:
    if not q.from_user or not _is_admin(q.from_user.id):
        return await q.answer("⛔ admins only", show_alert=True)

    try:
        from plugins.ott import worker
        worker.ensure_worker(client)
    except Exception:
        pass

    try:
        text, kb = await V.view_home()
        await client.send_message(
            chat_id=q.from_user.id,
            text=text, reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        await q.answer("📅 Opening OTT…")
    except Exception as e:
        logger.exception(f"[OTT-PANEL] open: {e}")
        try:
            await q.answer(f"❌ {type(e).__name__}", show_alert=True)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════

async def _recount_channel(cid: int) -> bool:
    """Return True if channel exists."""
    return await DB.get_channel(cid) is not None


async def _recount_group(gid: int) -> bool:
    return await DB.get_group(gid) is not None


# ═══════════════════════════════════════════════════════════
# ROUTER
# ═══════════════════════════════════════════════════════════

@Client.on_callback_query(filters.regex(rf"^{PFX}:"), group=-499)
async def ott_router(client: Client, q: CallbackQuery):
    if not q.from_user or not _is_admin(q.from_user.id):
        return await q.answer("⛔ admins only", show_alert=True)

    data = str(q.data)
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    args = parts[2:]

    try:
        # ── CLOSE ──
        if action == "close":
            try:
                await q.message.delete()
            except Exception:
                pass
            return await q.answer("Closed")

        if action == "noop":
            return await q.answer()

        # ═══════════════════════════════════════════════════
        # HOME / BROWSE
        # ═══════════════════════════════════════════════════

        if action == "home":
            text, kb = await V.view_home()
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "lang":
            lang = args[0] if args else "all"
            await q.answer("🎬 Loading…")
            text, kb = await V.view_lang(lang)
            await V.safe_edit(q, text, kb)
            return

        if action == "day":
            try:
                lang = args[0]
                day_idx = int(args[1])
            except (ValueError, IndexError):
                return await q.answer("❌")
            text, kb = await V.view_day(lang, day_idx)
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "mv":
            try:
                tmdb_id = int(args[0])
                lang = args[1] if len(args) > 1 else "all"
                day_idx = int(args[2]) if len(args) > 2 else 0
            except (ValueError, IndexError):
                return await q.answer("❌")

            text, kb, poster = await V.view_movie(tmdb_id, lang, day_idx)

            if poster:
                try:
                    await q.message.delete()
                except Exception:
                    pass
                try:
                    await client.send_photo(
                        chat_id=q.message.chat.id,
                        photo=poster, caption=text,
                        reply_markup=kb,
                        parse_mode=ParseMode.HTML,
                    )
                    return await q.answer()
                except Exception:
                    pass

            await V.safe_edit(q, text, kb)
            return await q.answer()

        # ═══════════════════════════════════════════════════
        # SETTINGS
        # ═══════════════════════════════════════════════════

        if action == "set":
            text, kb = await V.view_settings()
            await V.safe_edit(q, text, kb)
            return await q.answer()

        # ── FAVORITE LANGUAGES ──
        if action == "fav_langs":
            text, kb = await V.view_fav_langs()
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "fav_tog":
            code = args[0] if args else ""
            fav = await DB.get_fav_languages()
            if code in fav:
                fav.remove(code)
            else:
                fav.append(code)
            await DB.set_fav_languages(fav)
            text, kb = await V.view_fav_langs()
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "fav_all":
            from plugins.ott.config import PRIMARY_LANGS
            await DB.set_fav_languages([c for c, _ in PRIMARY_LANGS])
            text, kb = await V.view_fav_langs()
            await V.safe_edit(q, text, kb)
            return await q.answer("✅")

        if action == "fav_none":
            await DB.set_fav_languages([])
            text, kb = await V.view_fav_langs()
            await V.safe_edit(q, text, kb)
            return await q.answer("☐")

        # ═══════════════════════════════════════════════════
        # CHANNELS
        # ═══════════════════════════════════════════════════

        if action == "ch_list":
            text, kb = await V.view_ch_list()
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "ch_add":
            _sess_set(q.from_user.id, "add_channel")
            text, kb = V.prompt_add_channel()
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "ch":
            try:
                cid = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            text, kb = await V.view_channel(cid)
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "ch_run":
            try:
                cid = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            ch = await DB.get_channel(cid)
            if not ch:
                return await q.answer("❌")
            new_val = not bool(ch.get("running"))
            await DB.update_channel(cid, running=new_val)
            await q.answer("🟢 STARTED" if new_val else "🔴 STOPPED")
            text, kb = await V.view_channel(cid)
            await V.safe_edit(q, text, kb)
            return

        if action == "ch_lang":
            try:
                cid = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            text, kb = await V.view_ch_langs(cid)
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "ch_lang_tog":
            try:
                cid = int(args[0])
                code = args[1]
            except (ValueError, IndexError):
                return await q.answer("❌")
            ch = await DB.get_channel(cid)
            if not ch:
                return await q.answer("❌")
            langs = list(ch.get("languages") or [])
            if code in langs:
                langs.remove(code)
            else:
                langs.append(code)
            await DB.update_channel(cid, languages=langs)
            text, kb = await V.view_ch_langs(cid)
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "ch_lang_all":
            try:
                cid = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            from plugins.ott.config import PRIMARY_LANGS
            await DB.update_channel(cid,
                languages=[c for c, _ in PRIMARY_LANGS])
            text, kb = await V.view_ch_langs(cid)
            await V.safe_edit(q, text, kb)
            return await q.answer("✅")

        if action == "ch_lang_none":
            try:
                cid = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            await DB.update_channel(cid, languages=[])
            text, kb = await V.view_ch_langs(cid)
            await V.safe_edit(q, text, kb)
            return await q.answer("☐")

        if action == "ch_freq":
            try:
                cid = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            text, kb = await V.view_ch_freq(cid)
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "ch_fmode":
            try:
                cid = int(args[0])
                mode = args[1]
            except (ValueError, IndexError):
                return await q.answer("❌")
            if mode not in FREQ_MODES:
                return await q.answer("❌")
            ch = await DB.get_channel(cid)
            if not ch:
                return await q.answer("❌")
            freq = dict(ch.get("frequency") or {})
            freq["mode"] = mode
            await DB.update_channel(cid, frequency=freq, last_sent_key="")
            await q.answer(f"✅ {mode.upper()}")

            # Route to next step
            if mode == "off":
                text, kb = await V.view_channel(cid)
            elif mode == "daily":
                text, kb = await V.view_ch_freq_hours(cid, "daily")
            elif mode == "weekly":
                text, kb = await V.view_ch_freq_days(cid)
            elif mode == "monthly":
                text, kb = await V.view_ch_freq_month_days(cid)
            else:
                text, kb = await V.view_channel(cid)
            await V.safe_edit(q, text, kb)
            return

        if action == "ch_fh":
            try:
                cid = int(args[0])
                h = int(args[1])
            except (ValueError, IndexError):
                return await q.answer("❌")
            ch = await DB.get_channel(cid)
            if not ch:
                return await q.answer("❌")
            freq = dict(ch.get("frequency") or {})
            freq["hour"] = h
            await DB.update_channel(cid, frequency=freq, last_sent_key="")
            await q.answer(f"✅ {h:02d}:00")
            text, kb = await V.view_channel(cid)
            await V.safe_edit(q, text, kb)
            return

        if action == "ch_fd":
            try:
                cid = int(args[0])
                d = int(args[1])
            except (ValueError, IndexError):
                return await q.answer("❌")
            ch = await DB.get_channel(cid)
            if not ch:
                return await q.answer("❌")
            freq = dict(ch.get("frequency") or {})
            freq["day_of_week"] = d
            await DB.update_channel(cid, frequency=freq, last_sent_key="")
            await q.answer(f"✅ {['MON','TUE','WED','THU','FRI','SAT','SUN'][d]}")
            # Move to hour picker
            text, kb = await V.view_ch_freq_hours(cid, "weekly")
            await V.safe_edit(q, text, kb)
            return

        if action == "ch_fm":
            try:
                cid = int(args[0])
                d = int(args[1])
            except (ValueError, IndexError):
                return await q.answer("❌")
            ch = await DB.get_channel(cid)
            if not ch:
                return await q.answer("❌")
            freq = dict(ch.get("frequency") or {})
            freq["day_of_month"] = d
            await DB.update_channel(cid, frequency=freq, last_sent_key="")
            await q.answer(f"✅ day {d}")
            text, kb = await V.view_ch_freq_hours(cid, "monthly")
            await V.safe_edit(q, text, kb)
            return

        if action == "ch_prev":
            try:
                cid = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            ch = await DB.get_channel(cid)
            if not ch:
                return await q.answer("❌")
            text, kb = await V.view_preview(ch.get("languages") or [])
            # override back button
            from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ BACK",
                    callback_data=f"ott:ch:{cid}")],
            ])
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "ch_rm":
            try:
                cid = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            await DB.remove_channel(cid)
            await q.answer("🗑️ Removed")
            text, kb = await V.view_ch_list()
            await V.safe_edit(q, text, kb)
            return

        if action == "ch_start_all":
            for c in await DB.get_channels():
                await DB.update_channel(int(c["chat_id"]), running=True)
            await q.answer("▶️ STARTED ALL")
            text, kb = await V.view_ch_list()
            await V.safe_edit(q, text, kb)
            return

        if action == "ch_stop_all":
            for c in await DB.get_channels():
                await DB.update_channel(int(c["chat_id"]), running=False)
            await q.answer("⏹ STOPPED ALL")
            text, kb = await V.view_ch_list()
            await V.safe_edit(q, text, kb)
            return

        # ═══════════════════════════════════════════════════
        # GROUPS
        # ═══════════════════════════════════════════════════

        if action == "gr_list":
            text, kb = await V.view_gr_list()
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "gr_add":
            _sess_set(q.from_user.id, "add_group")
            text, kb = V.prompt_add_group()
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "gr":
            try:
                gid = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            text, kb = await V.view_group(gid)
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "gr_run":
            try:
                gid = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            gr = await DB.get_group(gid)
            if not gr:
                return await q.answer("❌")
            new_val = not bool(gr.get("running"))
            await DB.update_group(gid, running=new_val)
            await q.answer("🟢 STARTED" if new_val else "🔴 STOPPED")
            text, kb = await V.view_group(gid)
            await V.safe_edit(q, text, kb)
            return

        if action == "gr_lang":
            try:
                gid = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            text, kb = await V.view_gr_langs(gid)
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "gr_lang_tog":
            try:
                gid = int(args[0])
                code = args[1]
            except (ValueError, IndexError):
                return await q.answer("❌")
            gr = await DB.get_group(gid)
            if not gr:
                return await q.answer("❌")
            langs = list(gr.get("languages") or [])
            if code in langs:
                langs.remove(code)
            else:
                langs.append(code)
            await DB.update_group(gid, languages=langs)
            text, kb = await V.view_gr_langs(gid)
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "gr_lang_all":
            try:
                gid = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            from plugins.ott.config import PRIMARY_LANGS
            await DB.update_group(gid,
                languages=[c for c, _ in PRIMARY_LANGS])
            text, kb = await V.view_gr_langs(gid)
            await V.safe_edit(q, text, kb)
            return await q.answer("✅")

        if action == "gr_lang_none":
            try:
                gid = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            await DB.update_group(gid, languages=[])
            text, kb = await V.view_gr_langs(gid)
            await V.safe_edit(q, text, kb)
            return await q.answer("☐")

        if action == "gr_freq":
            try:
                gid = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            text, kb = await V.view_gr_freq(gid)
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "gr_fmode":
            try:
                gid = int(args[0])
                mode = args[1]
            except (ValueError, IndexError):
                return await q.answer("❌")
            if mode not in FREQ_MODES:
                return await q.answer("❌")
            gr = await DB.get_group(gid)
            if not gr:
                return await q.answer("❌")
            freq = dict(gr.get("frequency") or {})
            freq["mode"] = mode
            await DB.update_group(gid, frequency=freq, last_sent_key="")
            await q.answer(f"✅ {mode.upper()}")

            if mode == "off":
                text, kb = await V.view_group(gid)
            elif mode == "daily":
                text, kb = await V.view_gr_freq_hours(gid, "daily")
            elif mode == "weekly":
                text, kb = await V.view_gr_freq_days(gid)
            elif mode == "monthly":
                text, kb = await V.view_gr_freq_month_days(gid)
            else:
                text, kb = await V.view_group(gid)
            await V.safe_edit(q, text, kb)
            return

        if action == "gr_fh":
            try:
                gid = int(args[0])
                h = int(args[1])
            except (ValueError, IndexError):
                return await q.answer("❌")
            gr = await DB.get_group(gid)
            if not gr:
                return await q.answer("❌")
            freq = dict(gr.get("frequency") or {})
            freq["hour"] = h
            await DB.update_group(gid, frequency=freq, last_sent_key="")
            await q.answer(f"✅ {h:02d}:00")
            text, kb = await V.view_group(gid)
            await V.safe_edit(q, text, kb)
            return

        if action == "gr_fd":
            try:
                gid = int(args[0])
                d = int(args[1])
            except (ValueError, IndexError):
                return await q.answer("❌")
            gr = await DB.get_group(gid)
            if not gr:
                return await q.answer("❌")
            freq = dict(gr.get("frequency") or {})
            freq["day_of_week"] = d
            await DB.update_group(gid, frequency=freq, last_sent_key="")
            await q.answer("✅")
            text, kb = await V.view_gr_freq_hours(gid, "weekly")
            await V.safe_edit(q, text, kb)
            return

        if action == "gr_fm":
            try:
                gid = int(args[0])
                d = int(args[1])
            except (ValueError, IndexError):
                return await q.answer("❌")
            gr = await DB.get_group(gid)
            if not gr:
                return await q.answer("❌")
            freq = dict(gr.get("frequency") or {})
            freq["day_of_month"] = d
            await DB.update_group(gid, frequency=freq, last_sent_key="")
            await q.answer("✅")
            text, kb = await V.view_gr_freq_hours(gid, "monthly")
            await V.safe_edit(q, text, kb)
            return

        if action == "gr_prev":
            try:
                gid = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            gr = await DB.get_group(gid)
            if not gr:
                return await q.answer("❌")
            text, _ = await V.view_preview(gr.get("languages") or [])
            from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton("⬅️ BACK",
                    callback_data=f"ott:gr:{gid}")],
            ])
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "gr_rm":
            try:
                gid = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            await DB.remove_group(gid)
            await q.answer("🗑️ Removed")
            text, kb = await V.view_gr_list()
            await V.safe_edit(q, text, kb)
            return

        if action == "gr_start_all":
            for g in await DB.get_groups():
                await DB.update_group(int(g["chat_id"]), running=True)
            await q.answer("▶️ STARTED ALL")
            text, kb = await V.view_gr_list()
            await V.safe_edit(q, text, kb)
            return

        if action == "gr_stop_all":
            for g in await DB.get_groups():
                await DB.update_group(int(g["chat_id"]), running=False)
            await q.answer("⏹ STOPPED ALL")
            text, kb = await V.view_gr_list()
            await V.safe_edit(q, text, kb)
            return

        # ═══════════════════════════════════════════════════
        # USERS
        # ═══════════════════════════════════════════════════

        if action == "us":
            text, kb = await V.view_users()
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "us_run":
            cfg = await DB.get_users()
            new_val = not bool(cfg.get("running"))
            await DB.update_users(running=new_val, last_sent_key="")
            await q.answer("🟢 STARTED" if new_val else "🔴 STOPPED")
            text, kb = await V.view_users()
            await V.safe_edit(q, text, kb)
            return

        if action == "us_lang":
            text, kb = await V.view_kind_langs("us")
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "us_lang_tog":
            code = args[0] if args else ""
            cfg = await DB.get_users()
            langs = list(cfg.get("languages") or [])
            if code in langs:
                langs.remove(code)
            else:
                langs.append(code)
            await DB.update_users(languages=langs, last_sent_key="")
            text, kb = await V.view_kind_langs("us")
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "us_lang_all":
            from plugins.ott.config import PRIMARY_LANGS
            await DB.update_users(
                languages=[c for c, _ in PRIMARY_LANGS], last_sent_key="")
            text, kb = await V.view_kind_langs("us")
            await V.safe_edit(q, text, kb)
            return await q.answer("✅")

        if action == "us_lang_none":
            await DB.update_users(languages=[], last_sent_key="")
            text, kb = await V.view_kind_langs("us")
            await V.safe_edit(q, text, kb)
            return await q.answer("☐")

        if action == "us_freq":
            text, kb = await V.view_kind_freq("us")
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "us_fmode":
            mode = args[0] if args else "off"
            if mode not in FREQ_MODES:
                return await q.answer("❌")
            cfg = await DB.get_users()
            freq = dict(cfg.get("frequency") or {})
            freq["mode"] = mode
            await DB.update_users(frequency=freq, last_sent_key="")
            await q.answer(f"✅ {mode.upper()}")
            if mode == "off":
                text, kb = await V.view_users()
            elif mode == "daily":
                text, kb = await V.view_kind_freq_hours("us", "daily")
            elif mode == "weekly":
                text, kb = await V.view_kind_freq_days("us")
            else:
                text, kb = await V.view_kind_freq_month_days("us")
            await V.safe_edit(q, text, kb)
            return

        if action == "us_fh":
            try:
                h = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            cfg = await DB.get_users()
            freq = dict(cfg.get("frequency") or {})
            freq["hour"] = h
            await DB.update_users(frequency=freq, last_sent_key="")
            await q.answer(f"✅ {h:02d}:00")
            text, kb = await V.view_users()
            await V.safe_edit(q, text, kb)
            return

        if action == "us_fd":
            try:
                d = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            cfg = await DB.get_users()
            freq = dict(cfg.get("frequency") or {})
            freq["day_of_week"] = d
            await DB.update_users(frequency=freq, last_sent_key="")
            await q.answer("✅")
            text, kb = await V.view_kind_freq_hours("us", "weekly")
            await V.safe_edit(q, text, kb)
            return

        if action == "us_fm":
            try:
                d = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            cfg = await DB.get_users()
            freq = dict(cfg.get("frequency") or {})
            freq["day_of_month"] = d
            await DB.update_users(frequency=freq, last_sent_key="")
            await q.answer("✅")
            text, kb = await V.view_kind_freq_hours("us", "monthly")
            await V.safe_edit(q, text, kb)
            return

        if action == "us_prev":
            cfg = await DB.get_users()
            text, _ = await V.view_preview(cfg.get("languages") or [])
            from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ BACK",
                    callback_data="ott:us"),
            ]])
            await V.safe_edit(q, text, kb)
            return await q.answer()

        # ═══════════════════════════════════════════════════
        # PREMIUM
        # ═══════════════════════════════════════════════════

        if action == "pm":
            text, kb = await V.view_premium()
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "pm_run":
            cfg = await DB.get_premium()
            new_val = not bool(cfg.get("running"))
            await DB.update_premium(running=new_val, last_sent_key="")
            await q.answer("🟢 STARTED" if new_val else "🔴 STOPPED")
            text, kb = await V.view_premium()
            await V.safe_edit(q, text, kb)
            return

        if action == "pm_lang":
            text, kb = await V.view_kind_langs("pm")
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "pm_lang_tog":
            code = args[0] if args else ""
            cfg = await DB.get_premium()
            langs = list(cfg.get("languages") or [])
            if code in langs:
                langs.remove(code)
            else:
                langs.append(code)
            await DB.update_premium(languages=langs, last_sent_key="")
            text, kb = await V.view_kind_langs("pm")
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "pm_lang_all":
            from plugins.ott.config import PRIMARY_LANGS
            await DB.update_premium(
                languages=[c for c, _ in PRIMARY_LANGS], last_sent_key="")
            text, kb = await V.view_kind_langs("pm")
            await V.safe_edit(q, text, kb)
            return await q.answer("✅")

        if action == "pm_lang_none":
            await DB.update_premium(languages=[], last_sent_key="")
            text, kb = await V.view_kind_langs("pm")
            await V.safe_edit(q, text, kb)
            return await q.answer("☐")

        if action == "pm_freq":
            text, kb = await V.view_kind_freq("pm")
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "pm_fmode":
            mode = args[0] if args else "off"
            if mode not in FREQ_MODES:
                return await q.answer("❌")
            cfg = await DB.get_premium()
            freq = dict(cfg.get("frequency") or {})
            freq["mode"] = mode
            await DB.update_premium(frequency=freq, last_sent_key="")
            await q.answer(f"✅ {mode.upper()}")
            if mode == "off":
                text, kb = await V.view_premium()
            elif mode == "daily":
                text, kb = await V.view_kind_freq_hours("pm", "daily")
            elif mode == "weekly":
                text, kb = await V.view_kind_freq_days("pm")
            else:
                text, kb = await V.view_kind_freq_month_days("pm")
            await V.safe_edit(q, text, kb)
            return

        if action == "pm_fh":
            try:
                h = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            cfg = await DB.get_premium()
            freq = dict(cfg.get("frequency") or {})
            freq["hour"] = h
            await DB.update_premium(frequency=freq, last_sent_key="")
            await q.answer(f"✅ {h:02d}:00")
            text, kb = await V.view_premium()
            await V.safe_edit(q, text, kb)
            return

        if action == "pm_fd":
            try:
                d = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            cfg = await DB.get_premium()
            freq = dict(cfg.get("frequency") or {})
            freq["day_of_week"] = d
            await DB.update_premium(frequency=freq, last_sent_key="")
            await q.answer("✅")
            text, kb = await V.view_kind_freq_hours("pm", "weekly")
            await V.safe_edit(q, text, kb)
            return

        if action == "pm_fm":
            try:
                d = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            cfg = await DB.get_premium()
            freq = dict(cfg.get("frequency") or {})
            freq["day_of_month"] = d
            await DB.update_premium(frequency=freq, last_sent_key="")
            await q.answer("✅")
            text, kb = await V.view_kind_freq_hours("pm", "monthly")
            await V.safe_edit(q, text, kb)
            return

        if action == "pm_prev":
            cfg = await DB.get_premium()
            text, _ = await V.view_preview(cfg.get("languages") or [])
            from pyrogram.types import InlineKeyboardMarkup, InlineKeyboardButton
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("⬅️ BACK",
                    callback_data="ott:pm"),
            ]])
            await V.safe_edit(q, text, kb)
            return await q.answer()

        return await q.answer("❓ Unknown")

    except Exception as e:
        logger.exception(f"[OTT] router: {e}")
        try:
            await q.answer(f"❌ {type(e).__name__}", show_alert=True)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════
# TEXT INPUT (add channel / add group)
# ═══════════════════════════════════════════════════════════

@Client.on_message(
    filters.private & filters.text & ~filters.regex(r"^/"),
    group=-442,
)
async def ott_text_input(client: Client, message):
    if not message.from_user or not _is_admin(message.from_user.id):
        return
    sess = _sess_get(message.from_user.id)
    if not sess:
        return

    text = (message.text or "").strip()

    try:
        message.stop_propagation()
    except Exception:
        pass

    if text == "-":
        _sess_drop(message.from_user.id)
        return await message.reply_text("❌ Cancelled")

    kind = sess["kind"]

    if kind not in ("add_channel", "add_group"):
        _sess_drop(message.from_user.id)
        return

    # Resolve chat
    try:
        if text.startswith("@"):
            chat = await client.get_chat(text)
            cid = chat.id
            title = chat.title or text
        else:
            cid = int(text)
            try:
                chat = await client.get_chat(cid)
                title = chat.title or str(cid)
            except Exception:
                title = str(cid)
    except Exception as e:
        return await message.reply_text(f"❌ Could not resolve: {e}")

    # Verify bot can post
    try:
        me = await client.get_me()
        m = await client.get_chat_member(cid, me.id)
        st = getattr(m, "status", None)
        st = st.name.lower() if hasattr(st, "name") else str(st).lower()
        if kind == "add_channel":
            if st not in ("administrator", "creator", "owner"):
                return await message.reply_text(
                    f"⚠️ Bot must be admin in <b>{_esc(title)}</b>",
                    parse_mode=ParseMode.HTML)
        else:
            if st not in ("administrator", "creator", "owner", "member"):
                return await message.reply_text(
                    f"⚠️ Bot must be in <b>{_esc(title)}</b>",
                    parse_mode=ParseMode.HTML)
    except Exception as e:
        return await message.reply_text(f"❌ Check failed: {e}")

    if kind == "add_channel":
        await DB.add_channel(cid, title)
        _sess_drop(message.from_user.id)
        text_out, kb = await V.view_channel(cid)
        await message.reply_text(
            text_out, reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        return

    if kind == "add_group":
        await DB.add_group(cid, title)
        _sess_drop(message.from_user.id)
        text_out, kb = await V.view_group(cid)
        await message.reply_text(
            text_out, reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        return


__all__ = ["open_panel_for_admin"]
