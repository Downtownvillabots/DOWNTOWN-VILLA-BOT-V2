# ============================================================
# 🏨 DOWNTOWN VILLA — OTT PANEL + ROUTER
# ============================================================

from __future__ import annotations
import logging

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from plugins.broadcast.config import fb, sc, DIV, _is_admin
from plugins.ott import database as DB
from plugins.ott import state as ST
from plugins.ott import views as V
from plugins.ott import engine as EG
from plugins.ott import watcher as W
from plugins.ott.config import PREFIX

logger = logging.getLogger(__name__)

PFX = PREFIX


async def open_panel_for_admin(client: Client, q: CallbackQuery) -> None:
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
            chat_id=q.from_user.id, text=text, reply_markup=kb,
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


@Client.on_callback_query(filters.regex(rf"^{PFX}:"), group=-499)
async def ott_router(client: Client, q: CallbackQuery):
    # Admins + end-users both hit this router.
    data = str(q.data)
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    args = parts[2:]

    is_admin = bool(q.from_user and _is_admin(q.from_user.id))

    try:
        # ═══════════════════════════════════════════════════
        # PUBLIC (any user)
        # ═══════════════════════════════════════════════════

        if action == "close":
            if is_admin:
                ST.clear_session(q.from_user.id)
            try:
                await q.message.delete()
            except Exception:
                pass
            return await q.answer("Closed")

        if action == "sub":
            try:
                tmdb_id = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            uid = q.from_user.id
            # Check if event ended
            if await DB.is_movie_ended(tmdb_id):
                return await q.answer(
                    "💥 This event has ended.", show_alert=True)
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
            c = DB.prefs_coll()
            if c is not None:
                try:
                    import time as _t
                    await c.update_one(
                        {"user_id": int(q.from_user.id)},
                        {"$addToSet": {"watchlist": {
                            "tmdb_id": int(tmdb_id),
                            "title": movie.get("title") or "?",
                            "added_at": _t.time(),
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
            return await q.answer("📤 Share this post", show_alert=True)

        if action == "stats_pub":
            try:
                tmdb_id = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            stats = await DB.movie_stats(tmdb_id)
            movie = await DB.get_movie(tmdb_id) or {}
            title = (movie.get("title") or "?")[:40]
            await q.answer(
                f"🎬 {title}\n"
                f"🔔 {stats['total_subs']} subscribed\n"
                f"✅ {stats['notified']} notified\n"
                f"⏳ {stats['pending']} pending",
                show_alert=True)
            return

        # ═══════════════════════════════════════════════════
        # ADMIN ONLY BELOW
        # ═══════════════════════════════════════════════════
        if not is_admin:
            return await q.answer("⛔ admins only", show_alert=True)

        # ── HOME ──
        if action == "home":
            text, kb = await V.view_home()
            await V.safe_edit(q, text, kb)
            return await q.answer()

        # ── LANGUAGE MENU ──
        if action == "lang":
            lang = args[0] if args else "all"
            await q.answer("🎬 Loading…")
            text, kb = await V.view_lang(lang)
            await V.safe_edit(q, text, kb)
            return

        # ── DASHBOARD ──
        if action == "dash":
            text = "\n".join([
                f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                f"📊 <b>{fb('OTT DASHBOARD')}</b>",
                DIV, "",
                f"🔔 {sc('pending subs')} · <b>{await DB.pending_subs_total()}</b>",
                f"📢 {sc('broadcasts 7d')} · <b>{await DB.broadcast_recent_count(7)}</b>",
                f"📨 {sc('sent 7d')} · <b>{await DB.sent_count_last(7)}</b>",
                f"🎬 {sc('cache')} · <b>{await DB.cache_count()}</b>",
            ])
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "🔄 Refresh", callback_data="ott:dash")],
                [InlineKeyboardButton("⬅️ Back", callback_data="ott:home"),
                 InlineKeyboardButton("❌ Close", callback_data="ott:close")],
            ])
            await V.safe_edit(q, text, kb)
            return await q.answer()

        # ── REFETCH ──
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
            text, kb = await V.view_home()
            await V.safe_edit(q, text, kb)
            return

        # ── TRENDING ──
        if action == "trending":
            await q.answer("🔥 Loading…")
            text, kb = await V.view_lang("all")
            await V.safe_edit(q, text, kb)
            return

        # ── MOVIE ──
        if action == "mv":
            try:
                tmdb_id = int(args[0])
                back = args[1] if len(args) > 1 else None
            except (ValueError, IndexError):
                return await q.answer("❌")
            back_cb = f"ott:lang:{back}" if back else "ott:home"
            text, kb, poster = await V.view_movie(tmdb_id, back_cb)
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

        # ── BROADCAST SETUP ──
        if action == "bc_mv":
            try:
                tmdb_id = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            ch = await EG.get_ott_channel()
            if not ch:
                return await q.answer(
                    "⚠️ Set OTT channel first (Settings → 📢 OTT Channel)",
                    show_alert=True)
            ST.setup_new(q.from_user.id, tmdb_id, ch)
            s = ST.setup_get(q.from_user.id)
            if s is not None:
                s["show_file"] = True
            text, kb = await V.view_bc_setup(
                tmdb_id, ch, s["notify"], s["auto_delete_hours"],
                s.get("show_file", True))
            await V.safe_edit(q, text, kb)
            return await q.answer()


        # ── CHANNEL SETUP (in-channel broadcast setup) ──
        if action == "csetup":
            try:
                tmdb_id = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            from plugins.ott import channel_flow as CF
            return await CF.open_setup(client, q, tmdb_id)

        if action == "csetup_n":
            try:
                tmdb_id = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            from plugins.ott import channel_flow as CF
            return await CF.toggle_notify(client, q, tmdb_id)

        if action == "csetup_f":
            try:
                tmdb_id = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            from plugins.ott import channel_flow as CF
            return await CF.toggle_file(client, q, tmdb_id)

        if action == "csetup_t":
            try:
                tmdb_id = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            from plugins.ott import channel_flow as CF
            return await CF.show_timer(client, q, tmdb_id)

        if action == "csetup_td":
            try:
                tmdb_id = int(args[0])
                h = int(args[1])
            except (ValueError, IndexError):
                return await q.answer("❌")
            from plugins.ott import channel_flow as CF
            return await CF.set_timer(client, q, tmdb_id, h)

        if action == "csetup_go":
            try:
                tmdb_id = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            from plugins.ott import channel_flow as CF
            return await CF.post_now(client, q, tmdb_id)

        if action == "csetup_x":
            from plugins.ott import channel_flow as CF
            return await CF.cancel_setup(client, q)

        if action == "bcsetup":
            try:
                tmdb_id = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            s = ST.setup_get(q.from_user.id)
            if not s or s["tmdb_id"] != tmdb_id:
                ch = await EG.get_ott_channel()
                ST.setup_new(q.from_user.id, tmdb_id, ch)
                s = ST.setup_get(q.from_user.id)
                s["show_file"] = True
            text, kb = await V.view_bc_setup(
                tmdb_id, s["channel_id"], s["notify"],
                s["auto_delete_hours"], s.get("show_file", True))
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "bcsetup_tog_notify":
            s = ST.setup_get(q.from_user.id)
            if not s:
                return await q.answer("⏱️ expired", show_alert=True)
            s["notify"] = not s["notify"]
            text, kb = await V.view_bc_setup(
                s["tmdb_id"], s["channel_id"], s["notify"],
                s["auto_delete_hours"], s.get("show_file", True))
            await V.safe_edit(q, text, kb)
            return await q.answer("🟢 on" if s["notify"] else "🔴 off")

        if action == "bcsetup_tog_file":
            s = ST.setup_get(q.from_user.id)
            if not s:
                return await q.answer("⏱️ expired", show_alert=True)
            s["show_file"] = not s.get("show_file", True)
            text, kb = await V.view_bc_setup(
                s["tmdb_id"], s["channel_id"], s["notify"],
                s["auto_delete_hours"], s["show_file"])
            await V.safe_edit(q, text, kb)
            return await q.answer("🟢 on" if s["show_file"] else "🔴 off")

        if action == "bcsetup_timer":
            s = ST.setup_get(q.from_user.id)
            if not s:
                return await q.answer("⏱️ expired", show_alert=True)
            text, kb = await V.view_bcsetup_timer(
                s["tmdb_id"], s["auto_delete_hours"])
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "bcsetup_timer_do":
            try:
                h = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            s = ST.setup_get(q.from_user.id)
            if not s:
                return await q.answer("⏱️ expired", show_alert=True)
            s["auto_delete_hours"] = h
            text, kb = await V.view_bc_setup(
                s["tmdb_id"], s["channel_id"], s["notify"],
                s["auto_delete_hours"], s.get("show_file", True))
            await V.safe_edit(q, text, kb)
            return await q.answer("✅" if h else "♾️")

        if action == "bcsetup_send":
            s = ST.setup_get(q.from_user.id)
            if not s:
                return await q.answer("⏱️ expired", show_alert=True)
            return await EG.send_channel_broadcast(client, q, s)

        # ── STATS ──
        if action == "stats":
            try:
                tmdb_id = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            text, kb = await V.view_stats(tmdb_id)
            await V.safe_edit(q, text, kb)
            return await q.answer()

        # ── END EVENT ──
        if action == "end_mv":
            try:
                tmdb_id = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            tok = ST.new_confirm("end_movie", tmdb_id=tmdb_id)
            text, kb = await V.view_end_confirm(tmdb_id, tok)
            await V.safe_edit(q, text, kb)
            return await q.answer("⚠️")

        if action == "end_do":
            try:
                tmdb_id = int(args[0])
                tok = args[1]
            except (ValueError, IndexError):
                return await q.answer("❌")
            c = ST.get_confirm(tok)
            if not c or c.get("kind") != "end_movie":
                return await q.answer("⏱️ expired", show_alert=True)
            ST.drop_confirm(tok)

            res = await DB.end_movie(tmdb_id)
            await q.answer(f"💥 {res['deleted']} tokens deleted")

            movie = await DB.get_movie(tmdb_id) or {}
            title = (movie.get("title") or "?")[:50]
            text = "\n".join([
                f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                f"💥 <b>{fb('EVENT ENDED')}</b>",
                DIV, "",
                f"🎬 <b>{sc(title)}</b>",
                "", DIV2,
                f"🗑️ {sc('pending tokens deleted')} · <b>{res['deleted']}</b>",
                f"🏷️ {sc('broadcasts ended')} · <b>{res['broadcasts_cancelled']}</b>",
                "", DIV2,
                f"📌 {sc('new Notify taps will be refused')}",
                f"📌 {sc('already-notified users are unaffected')}",
            ])
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    "📊 Statistics",
                    callback_data=f"ott:stats:{tmdb_id}")],
                [InlineKeyboardButton("🏠 Home",
                                      callback_data="ott:home"),
                 InlineKeyboardButton("❌ Close",
                                      callback_data="ott:close")],
            ])
            await V.safe_edit(q, text, kb)
            return

        # ── NOTIFY NOW ──
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
            text, kb = await V.view_stats(tmdb_id)
            await V.safe_edit(q, text, kb)
            return

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

        # ── BROADCASTS ──
        if action == "bc":
            text, kb = await V.view_bc_center()
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "bc_hist":
            text, kb = await V.view_bc_history()
            await V.safe_edit(q, text, kb)
            return await q.answer()

        # ── NOTIFICATIONS / CACHE ──
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

        if action == "cache":
            text, kb = await V.view_cache()
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "cache_clear":
            n = await DB.cache_clear()
            await q.answer(f"🧹 Cleared {n}")
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

        if action == "set_ott_channel":
            ST.new_session(q.from_user.id, "set_ott_channel")
            text = "\n".join([
                f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                f"📢 <b>{fb('SET OTT BROADCAST CHANNEL')}</b>",
                DIV, "",
                f"📝 {sc('send a chat id or @username')}",
                f"📌 {sc('all OTT movie posts go here')}",
                "", f"📌 {sc('send')} <code>-</code> {sc('to cancel')}",
            ])
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Cancel", callback_data="ott:set")]])
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
            await q.answer("🟢 on" if not cur else "🔴 off")
            text, kb = await V.view_settings()
            await V.safe_edit(q, text, kb)
            return

        if action == "diag":
            text, kb = await V.view_diag()
            await V.safe_edit(q, text, kb)
            return await q.answer()

        return await q.answer("❓ Unknown")

    except Exception as e:
        logger.exception(f"[OTT] router: {e}")
        try:
            await q.answer(f"❌ {type(e).__name__}", show_alert=True)
        except Exception:
            pass


__all__ = ["open_panel_for_admin"]
