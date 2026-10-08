# ============================================================
# 🏨 DOWNTOWN VILLA — OTT PANEL + ROUTER
# ============================================================

from __future__ import annotations
import asyncio
import logging
from typing import Optional

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.errors import MessageNotModified
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from plugins.broadcast.config import fb, sc, DIV, _is_admin
from plugins.ott import database as DB
from plugins.ott import state as ST
from plugins.ott import views as V
from plugins.ott import keyboards as KB
from plugins.ott import engine as EG
from plugins.ott import watcher as W
from plugins.ott.config import PREFIX

logger = logging.getLogger(__name__)

PFX = PREFIX


# ═══════════════════════════════════════════════════════════
# /admin ENTRY POINT
# ═══════════════════════════════════════════════════════════

async def open_panel_for_admin(client: Client, q: CallbackQuery) -> None:
    """Called from /admin → [📅 OTT]"""
    if not q.from_user or not _is_admin(q.from_user.id):
        return await q.answer("⛔ admins only", show_alert=True)

    try:
        await DB.ensure_indexes()
        W.ensure_loops(client)
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
# MAIN ROUTER
# ═══════════════════════════════════════════════════════════

@Client.on_callback_query(filters.regex(rf"^{PFX}:"), group=-499)
async def ott_router(client: Client, q: CallbackQuery):
    if not q.from_user or not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)

    data = str(q.data)
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    args = parts[2:]

    try:
        # ── CLOSE ──
        if action == "close":
            ST.clear_session(q.from_user.id)
            try:
                await q.message.delete()
            except Exception:
                pass
            return await q.answer("Closed")

        # ── HOME ──
        if action == "home":
            text, kb = await V.view_home()
            await V.safe_edit(q, text, kb)
            return await q.answer()

        # ── DASHBOARD ──
        if action == "dash":
            text, kb = await V.view_dashboard()
            await V.safe_edit(q, text, kb)
            return await q.answer()

        # ── WEEK ──
        if action == "week":
            text, kb = await V.view_week()
            await V.safe_edit(q, text, kb)
            return await q.answer()

        # ── DAY ──
        if action == "day":
            try:
                idx = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            text, kb = await V.view_day(idx)
            await V.safe_edit(q, text, kb)
            return await q.answer()

        # ── MOVIE CARD ──
        if action == "mv":
            try:
                tmdb_id = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            text, kb, poster = await V.view_movie(tmdb_id, "ott:week")
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

        # ── REFETCH WEEK ──
        if action == "refetch":
            await q.answer("🔄 Fetching…")
            try:
                from plugins.ott.tmdb import fetch_weekly_multi_lang
                cfg = await DB.get_cfg()
                by_day = await fetch_weekly_multi_lang(
                    region=cfg.get("region", "IN"),
                    languages=cfg.get("languages") or [],
                    min_vote=int(cfg.get("min_vote_count", 5)),
                )
                days = [[dict(m) for m in by_day.get(i, [])] for i in range(7)]
                await DB.save_week(DB.week_key(), days, posted=True)
            except Exception as e:
                logger.exception(f"[OTT] refetch: {e}")
            text, kb = await V.view_week()
            await V.safe_edit(q, text, kb)
            return

        # ── BROADCAST CENTER ──
        if action == "bc":
            text, kb = await V.view_bc_center()
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "bc_mv":
            try:
                tmdb_id = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            text, kb = await V.view_bc_targets(tmdb_id)
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "bc_confirm":
            try:
                tmdb_id = int(args[0])
                target = args[1]
            except (ValueError, IndexError):
                return await q.answer("❌")
            text, kb = await V.view_bc_confirm(tmdb_id, target)
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "bc_do":
            try:
                tmdb_id = int(args[0])
                target = args[1]
            except (ValueError, IndexError):
                return await q.answer("❌")
            await q.answer("🚀 Starting…")
            return await EG.run_broadcast(client, q, tmdb_id, target)

        if action == "bc_stop":
            jid = args[0] if args else ""
            EG.cancel_job(jid)
            return await q.answer("⏹️ Cancelling…")

        if action == "bc_hist":
            text, kb = await V.view_bc_history()
            await V.safe_edit(q, text, kb)
            return await q.answer()

        # ── SUBSCRIBERS ──
        if action == "subs":
            text, kb = await V.view_subs_overview()
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "subs_mv":
            try:
                tmdb_id = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            text, kb = await V.view_subs_movie(tmdb_id)
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "notify_go":
            try:
                tmdb_id = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            await q.answer("📤 Notifying…")
            try:
                await W._notify_subscribers(client, tmdb_id)
            except Exception as e:
                logger.exception(f"[OTT] notify_go: {e}")
            text, kb = await V.view_subs_movie(tmdb_id)
            await V.safe_edit(q, text, kb)
            return

        if action == "cancel_mv":
            try:
                tmdb_id = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            tok = ST.new_confirm("cancel_movie", tmdb_id=tmdb_id)
            text, kb = await V.view_cancel_confirm(tmdb_id, tok)
            await V.safe_edit(q, text, kb)
            return await q.answer("⚠️")

        if action == "cancel_subs":
            try:
                tmdb_id = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            tok = ST.new_confirm("cancel_movie", tmdb_id=tmdb_id)
            text, kb = await V.view_cancel_confirm(tmdb_id, tok)
            await V.safe_edit(q, text, kb)
            return await q.answer("⚠️")

        if action == "cancel_do":
            try:
                tmdb_id = int(args[0])
                tok = args[1]
            except (ValueError, IndexError):
                return await q.answer("❌")
            c = ST.get_confirm(tok)
            if not c or c.get("kind") != "cancel_movie":
                return await q.answer("⏱️ expired", show_alert=True)
            ST.drop_confirm(tok)

            n = await DB.cancel_all_subs(tmdb_id)
            await DB.broadcast_mark_cancelled(tmdb_id)
            await q.answer(f"💥 {n} tokens deleted", show_alert=False)

            movie = await DB.get_movie(tmdb_id) or {}
            title = (movie.get("title") or "?")[:50]
            text = "\n".join([
                f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                f"💥 <b>{fb('CANCELLED')}</b>",
                DIV, "",
                f"🎬 <b>{sc(title)}</b>",
                "", DIV2,
                f"🗑️ {sc('pending subs deleted')} · <b>{n}</b>",
                f"🏷️ {sc('broadcast flagged')}",
                "", f"📌 {sc('channel post NOT touched')}",
                "", f"📌 {sc('tap below to open subscribers')}",
            ])
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "⬅️ Back",
                    callback_data=f"ott:subs_mv:{tmdb_id}")],
                [InlineKeyboardButton(
                    "❌ Close", callback_data="ott:close")],
            ])
            await V.safe_edit(q, text, kb)
            return

        if action == "del_post":
            try:
                tmdb_id = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            bc = await DB.broadcast_get_latest(tmdb_id)
            msg_id = bc.get("channel_msg_id") if bc else 0
            if not msg_id:
                return await q.answer(
                    "⚪ no channel post on record", show_alert=True)
            cfg = await DB.get_cfg()
            ch = int(cfg.get("primary_channel") or 0)
            if not ch:
                return await q.answer(
                    "⚪ no primary channel set", show_alert=True)
            try:
                await client.delete_messages(ch, msg_id)
                await q.answer("🗑️ Deleted")
            except Exception as e:
                await q.answer(f"❌ {type(e).__name__}", show_alert=True)
            text, kb = await V.view_subs_movie(tmdb_id)
            await V.safe_edit(q, text, kb)
            return

        if action == "enrich":
            try:
                tmdb_id = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            await q.answer("🔄 Re-enriching…")
            try:
                from plugins.ott.tmdb import enrich_movie, fetch_details
                raw = await DB.get_movie(tmdb_id)
                if raw:
                    details = await fetch_details(tmdb_id)
                    if details:
                        from plugins.ott import tmdb as T
                        # force refresh by clearing cache marker
                        raw["overview"] = ""
                        fresh = await T.enrich_movie(raw)
                        if fresh:
                            await DB.save_movie(fresh)
            except Exception as e:
                logger.exception(f"[OTT] enrich: {e}")
            text, kb, poster = await V.view_movie(tmdb_id, "ott:week")
            await V.safe_edit(q, text, kb)
            return

        # ── NOTIFICATIONS ──
        if action == "notif":
            text, kb = await V.view_notif()
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "notif_clear":
            n = await DB.sent_clear()
            await q.answer(f"🧹 Cleared {n}")
            text, kb = await V.view_notif()
            await V.safe_edit(q, text, kb)
            return

        # ── CACHE ──
        if action == "cache":
            text, kb = await V.view_cache()
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "cache_clear":
            n = await DB.cache_clear()
            await q.answer(f"🧹 Cleared {n} cached movies")
            text, kb = await V.view_cache()
            await V.safe_edit(q, text, kb)
            return

        # ── SETTINGS ──
        if action == "set":
            text, kb = await V.view_settings()
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "set_region":
            text, kb = await V.view_region()
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "set_region_do":
            r = args[0] if args else "IN"
            await DB.save_cfg(region=r)
            await q.answer(f"✅ {r}")
            text, kb = await V.view_region()
            await V.safe_edit(q, text, kb)
            return

        if action == "set_langs":
            text, kb = await V.view_langs()
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "set_lang_tog":
            code = args[0] if args else ""
            cfg = await DB.get_cfg()
            langs = list(cfg.get("languages") or [])
            if code in langs:
                langs.remove(code)
            else:
                langs.append(code)
            await DB.save_cfg(languages=langs)
            text, kb = await V.view_langs()
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "set_langs_reset":
            from plugins.ott.config import DEFAULT_LANGS
            await DB.save_cfg(languages=list(DEFAULT_LANGS))
            await q.answer("🔄 Reset")
            text, kb = await V.view_langs()
            await V.safe_edit(q, text, kb)
            return

        if action == "set_minvote":
            text, kb = await V.view_minvote()
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "set_minvote_do":
            try:
                n = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            await DB.save_cfg(min_vote_count=n)
            await q.answer(f"✅ {n}")
            text, kb = await V.view_minvote()
            await V.safe_edit(q, text, kb)
            return

        if action == "set_channel":
            ST.new_session(q.from_user.id, "set_channel")
            text = "\n".join([
                f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                f"📺 <b>{fb('SET PRIMARY CHANNEL')}</b>",
                DIV, "",
                f"📝 {sc('send a chat id or @username')}",
                f"📌 {sc('bot must be admin')}",
                "", f"📌 {sc('send')} <code>-</code> {sc('to cancel')}",
            ])
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "❌ Cancel", callback_data="ott:set")]])
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "set_notifttl":
            text, kb = await V.view_notifttl()
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "set_notifttl_do":
            try:
                n = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            await DB.save_cfg(notify_ttl_hours=n)
            await q.answer(f"✅ {n}h")
            text, kb = await V.view_notifttl()
            await V.safe_edit(q, text, kb)
            return

        if action == "set_bcttl":
            text, kb = await V.view_bcttl()
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "set_bcttl_do":
            try:
                n = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            await DB.save_cfg(broadcast_ttl_hours=n)
            await q.answer(f"✅ {n}h")
            text, kb = await V.view_bcttl()
            await V.safe_edit(q, text, kb)
            return

        if action == "set_tog":
            key = args[0] if args else ""
            cfg = await DB.get_cfg()
            field_map = {
                "hype": "hype_enabled",
                "weekly": "weekly_enabled",
                "share": "share_button",
                "autodel": "auto_delete_broadcast",
            }
            field = field_map.get(key, key)
            cur = bool(cfg.get(field))
            await DB.save_cfg(**{field: not cur})
            await q.answer(f"🟢 on" if not cur else f"🔴 off")
            text, kb = await V.view_settings()
            await V.safe_edit(q, text, kb)
            return

        # ── DIAGNOSTICS ──
        if action == "diag":
            text, kb = await V.view_diag()
            await V.safe_edit(q, text, kb)
            return await q.answer()

        # ── USER-SIDE: SUBSCRIBE / WATCHLIST / GET FILE ──
        if action == "sub":
            try:
                tmdb_id = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            uid = q.from_user.id
            if await DB.sub_exists(uid, tmdb_id):
                await DB.sub_remove(uid, tmdb_id)
                return await q.answer("🔕 Unsubscribed")
            movie = await DB.get_movie(tmdb_id) or {}
            title = movie.get("title") or "?"
            year = (movie.get("release_date") or "")[:4]
            rel = movie.get("release_date") or ""
            await DB.sub_add(uid, tmdb_id, title, year, rel)
            return await q.answer(
                f"✅ You will be notified when '{title}' is uploaded")

        if action == "wl_add":
            try:
                tmdb_id = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            movie = await DB.get_movie(tmdb_id) or {}
            from plugins.ott.database import _c as _coll
            c = _coll("ott_prefs")
            if c is not None:
                try:
                    await c.update_one(
                        {"user_id": int(q.from_user.id)},
                        {"$addToSet": {"watchlist": {
                            "tmdb_id": int(tmdb_id),
                            "title": movie.get("title") or "?",
                            "added_at": __import__("time").time(),
                        }}},
                        upsert=True,
                    )
                except Exception:
                    pass
            return await q.answer("🎁 Added to watchlist")

        if action == "getfile":
            return await q.answer(
                "📥 Search in the group to get the file",
                show_alert=True)

        if action == "share":
            try:
                tmdb_id = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            movie = await DB.get_movie(tmdb_id) or {}
            title = movie.get("title") or "?"
            await q.answer(
                f"📤 Share this: https://t.me/{q.message.chat.username or ''}",
                show_alert=True)
            return

        return await q.answer("❓ Unknown")

    except Exception as e:
        logger.exception(f"[OTT] router: {e}")
        try:
            await q.answer(f"❌ {type(e).__name__}", show_alert=True)
        except Exception:
            pass


__all__ = ["open_panel_for_admin"]
