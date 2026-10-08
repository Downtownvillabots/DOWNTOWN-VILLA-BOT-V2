# ============================================================
# 🏨 DOWNTOWN VILLA — OTT PANEL + ROUTER (v3 — final)
# ============================================================

from __future__ import annotations
import asyncio
import logging

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
)

from plugins.broadcast.config import fb, sc, DIV, _is_admin
from plugins.ott import database as DB
from plugins.ott import events as EVENTS
from plugins.ott import state as ST
from plugins.ott import views as V
from plugins.ott import keyboards as KB
from plugins.ott import channel_flow as CF
from plugins.ott import stats_sync as SYNC
from plugins.ott import watcher as W
from plugins.ott.config import PREFIX

logger = logging.getLogger(__name__)
PFX = PREFIX


# ═══════════════════════════════════════════════════════════
# /admin ENTRY
# ═══════════════════════════════════════════════════════════

async def open_panel_for_admin(client: Client, q: CallbackQuery) -> None:
    if not q.from_user or not _is_admin(q.from_user.id):
        return await q.answer("⛔ admins only", show_alert=True)
    try:
        await DB.ensure_indexes()
        await EVENTS.ensure_indexes()
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
# BACKGROUND SYNC (fire-and-forget)
# ═══════════════════════════════════════════════════════════

async def _bg_sync(client: Client, eid: str) -> None:
    try:
        await SYNC.sync_all(client, eid)
    except Exception as e:
        logger.debug(f"[OTT] bg sync: {e}")


# ═══════════════════════════════════════════════════════════
# MAIN ROUTER
# ═══════════════════════════════════════════════════════════

@Client.on_callback_query(filters.regex(rf"^{PFX}:"), group=-499)
async def ott_router(client: Client, q: CallbackQuery):
    data = str(q.data)
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    args = parts[2:]
    is_admin = bool(q.from_user and _is_admin(q.from_user.id))

    try:
        # ═══════════════════════════════════════════════════
        # PUBLIC ROUTES — any user
        # ═══════════════════════════════════════════════════

        if action == "close":
            if is_admin:
                ST.clear_session(q.from_user.id)
            try:
                await q.message.delete()
            except Exception:
                pass
            return await q.answer("Closed")

        if action == "noop":
            return await q.answer()

        # ── USER: Get Notified ──
        if action == "sub":
            try:
                tmdb_id = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")

            uid = q.from_user.id
            ev = await EVENTS.get_active_for_movie(tmdb_id)
            if not ev:
                return await q.answer("💥 This event has ended.",
                                      show_alert=True)

            if await DB.sub_exists(uid, tmdb_id):
                return await q.answer("ℹ️ You are already subscribed.",
                                      show_alert=True)

            movie = await DB.get_movie(tmdb_id) or {}
            title = movie.get("title") or "?"
            year = (movie.get("release_date") or "")[:4]
            rel = movie.get("release_date") or ""

            added = await DB.sub_add_atomic(uid, tmdb_id, title, year, rel)
            if not added:
                return await q.answer("ℹ️ You are already subscribed.",
                                      show_alert=True)

            # Fire-and-forget live sync
            asyncio.create_task(_bg_sync(client, ev["_id"]))

            return await q.answer(
                f"✅ You will be notified when '{title}' is available.")

        # ── USER: watchlist ──
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

        # ── USER: file list ──
        if action == "files":
            try:
                tmdb_id = int(args[0])
                page = int(args[1]) if len(args) > 1 else 0
            except (ValueError, IndexError):
                return await q.answer("❌")
            text, kb = await V.view_files(tmdb_id, page)
            try:
                await q.message.edit_text(
                    text, reply_markup=kb,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
            except Exception:
                try:
                    await q.message.edit_caption(
                        caption=text, reply_markup=kb,
                        parse_mode=ParseMode.HTML,
                    )
                except Exception:
                    pass
            return await q.answer()

        # ── USER: get a file ──
        if action == "file_get":
            try:
                tmdb_id = int(args[0])
                idx = int(args[1])
            except (ValueError, IndexError):
                return await q.answer("❌")

            movie = await DB.get_movie(tmdb_id) or {}
            files = await DB.find_files_for_movie(movie, limit=50)
            if idx < 0 or idx >= len(files):
                return await q.answer("⚠️ File not found", show_alert=True)

            f = files[idx]
            file_id = f.get("file_id")
            src_chat = f.get("source_chat_id")
            src_msg = f.get("source_msg_id")

            if not file_id:
                return await q.answer("⚠️ File reference missing",
                                      show_alert=True)

            await q.answer("📤 Sending…")
            try:
                if src_chat and src_msg:
                    try:
                        await client.copy_message(
                            chat_id=q.from_user.id,
                            from_chat_id=int(src_chat),
                            message_id=int(src_msg),
                        )
                    except Exception:
                        await client.send_cached_media(
                            chat_id=q.from_user.id, file_id=file_id)
                else:
                    await client.send_cached_media(
                        chat_id=q.from_user.id, file_id=file_id)

                try:
                    await DB.sent_log(q.from_user.id, tmdb_id,
                                      mode="file_sent")
                except Exception:
                    pass

                ev = await EVENTS.get_any_for_movie(tmdb_id)
                if ev:
                    asyncio.create_task(_bg_sync(client, ev["_id"]))
            except Exception as e:
                logger.exception(f"[OTT] file_get: {e}")
                return await q.answer(f"❌ {type(e).__name__}",
                                      show_alert=True)
            return

        if action == "getfile":
            return await q.answer("📥 Tap Get Files to choose quality",
                                  show_alert=True)

        if action == "share":
            return await q.answer("📤 Share this post", show_alert=True)

        if action == "stats_pub":
            try:
                tmdb_id = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            ev = await EVENTS.get_any_for_movie(tmdb_id)
            if ev:
                await EVENTS.recount(ev["_id"])
                ev = await EVENTS.get_event(ev["_id"])
            movie = await DB.get_movie(tmdb_id) or {}
            title = (movie.get("title") or "?")[:40]
            total = int((ev or {}).get("subs_total", 0))
            notified = int((ev or {}).get("notified", 0))
            pending = int((ev or {}).get("pending", 0))
            files = int((ev or {}).get("files_count", 0))
            await q.answer(
                f"🎬 {title}\n"
                f"🔔 {total} subscribed\n"
                f"✅ {notified} notified\n"
                f"⏳ {pending} pending\n"
                f"📥 {files} files",
                show_alert=True)
            return

        # ═══════════════════════════════════════════════════
        # ADMIN ONLY
        # ═══════════════════════════════════════════════════
        if not is_admin:
            return await q.answer("⛔ admins only", show_alert=True)

        # ── HOME / DASH ──
        if action == "home":
            text, kb = await V.view_home()
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "dash":
            text, kb = await V.view_dashboard()
            await V.safe_edit(q, text, kb)
            return await q.answer()

        # ── LANGUAGE ──
        if action == "lang":
            lang = args[0] if args else "all"
            await q.answer("🎬 Loading…")
            text, kb = await V.view_lang(lang)
            await V.safe_edit(q, text, kb)
            return

        if action == "lang_day":
            try:
                lang = args[0]
                day_idx = int(args[1])
            except (ValueError, IndexError):
                return await q.answer("❌")
            text, kb = await V.view_lang_day(lang, day_idx)
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "lang_all":
            lang = args[0] if args else "all"
            await q.answer("🌐 Loading…")
            text, kb = await V.view_lang(lang)
            await V.safe_edit(q, text, kb)
            return

        if action == "week_all":
            await q.answer("🌐 Loading…")
            text, kb = await V.view_lang("all")
            await V.safe_edit(q, text, kb)
            return

        if action == "refetch":
            await q.answer("🔄 Fetching…")
            try:
                from plugins.ott.tmdb import fetch_weekly_multi_lang
                cfg = await DB.get_cfg()
                by_day = await fetch_weekly_multi_lang(
                    region=cfg.get("region", "IN"),
                    languages=cfg.get("languages") or [],
                    min_vote=int(cfg.get("min_vote_count", 0)),
                )
                days = [[dict(m) for m in by_day.get(i, [])]
                        for i in range(7)]
                await DB.save_week(DB.week_key(), days, posted=True)
            except Exception as e:
                logger.exception(f"[OTT] refetch: {e}")
            text, kb = await V.view_home()
            await V.safe_edit(q, text, kb)
            return

        if action == "refetch_lang":
            lang = args[0] if args else "all"
            await q.answer("🔄 Fetching…")
            text, kb = await V.view_lang(lang)
            await V.safe_edit(q, text, kb)
            return

        # ── MOVIE CARD (PM) ──
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

        # ── CHANNEL SETUP (PM → channel transition) ──
        if action == "csetup":
            try:
                tmdb_id = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            return await CF.open_setup(client, q, tmdb_id)

        if action == "csetup_n":
            try:
                tmdb_id = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            return await CF.toggle_notify(client, q, tmdb_id)

        if action == "csetup_f":
            try:
                tmdb_id = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            return await CF.toggle_file(client, q, tmdb_id)

        if action == "csetup_t":
            try:
                tmdb_id = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            return await CF.show_timer(client, q, tmdb_id)

        if action == "csetup_td":
            try:
                tmdb_id = int(args[0])
                h = int(args[1])
            except (ValueError, IndexError):
                return await q.answer("❌")
            return await CF.set_timer(client, q, tmdb_id, h)

        if action == "csetup_x":
            try:
                tmdb_id = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            return await CF.cancel_setup(client, q, tmdb_id)

        # ── BROADCAST TARGET PICKER ──
        if action == "csetup_bc":
            try:
                tmdb_id = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            return await CF.open_bc_picker(client, q, tmdb_id)

        if action == "csetup_bc_ch":
            try:
                tmdb_id = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            return await CF.show_channel_list(client, q, tmdb_id)

        if action == "csetup_bc_gr":
            try:
                tmdb_id = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            return await CF.show_group_list(client, q, tmdb_id)

        if action == "csetup_bc_us":
            try:
                tmdb_id = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            return await CF.confirm_bc(client, q, tmdb_id, "us", 0)

        if action == "csetup_bc_pm":
            try:
                tmdb_id = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            return await CF.confirm_bc(client, q, tmdb_id, "pm", 0)

        if action == "csetup_bc_manual":
            try:
                tmdb_id = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            return await CF.start_manual_target(client, q, tmdb_id)

        if action == "csetup_bc_send":
            try:
                tmdb_id = int(args[0])
                kind = args[1]
                tid = int(args[2]) if len(args) > 2 else 0
            except (ValueError, IndexError):
                return await q.answer("❌")
            if kind == "ch":
                return await CF.confirm_bc(client, q, tmdb_id, "ch", tid)
            if kind == "chall":
                return await CF.confirm_bc(client, q, tmdb_id, "chall", 0)
            if kind == "gr":
                return await CF.confirm_bc(client, q, tmdb_id, "gr_single",
                                            tid)
            if kind == "grall":
                return await CF.confirm_bc(client, q, tmdb_id, "gr", 0)
            return await q.answer("❓")

        if action == "csetup_bc_do":
            try:
                tmdb_id = int(args[0])
                kind = args[1]
                tid = int(args[2])
            except (ValueError, IndexError):
                return await q.answer("❌")
            return await CF.do_broadcast(client, q, tmdb_id, kind, tid)

        if action == "csetup_go":
            try:
                tmdb_id = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            return await CF.post_now(client, q, tmdb_id)

        # ── BROADCAST STOP ──
        if action == "bc_stop":
            eid = args[0] if args else ""
            if eid:
                ev = await EVENTS.get_event(eid)
                if ev:
                    await EVENTS.update_event(eid, state="live")
            return await q.answer("⏹ Stopped")

        # ── STATS ──
        if action == "stats":
            try:
                tmdb_id = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            ev = await EVENTS.get_any_for_movie(tmdb_id)
            if ev:
                await EVENTS.recount(ev["_id"])
            text, kb = await V.view_stats(tmdb_id)
            await V.safe_edit(q, text, kb)
            return await q.answer()

        # ── END TASK ──
        if action == "end_mv":
            try:
                tmdb_id = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            tok = ST.new_confirm("end_movie", tmdb_id=tmdb_id)
            text, kb = await V.view_end_confirm(tmdb_id, tok)
            try:
                await q.message.edit_text(
                    text, reply_markup=kb,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
            except Exception:
                try:
                    await q.message.edit_caption(
                        caption=text, reply_markup=kb,
                        parse_mode=ParseMode.HTML,
                    )
                except Exception:
                    pass
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
            ev = await EVENTS.get_active_for_movie(tmdb_id)
            if not ev:
                ev = await EVENTS.get_any_for_movie(tmdb_id)
            if ev:
                await EVENTS.mark_ended(ev["_id"])
                asyncio.create_task(_bg_sync(client, ev["_id"]))

            await q.answer(f"💥 {res['deleted']} tokens deleted")
            return

        # ── NOTIFY NOW ──
        if action == "notify_go":
            try:
                tmdb_id = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            await q.answer("📤 Notifying…")
            ev = await EVENTS.get_active_for_movie(tmdb_id)
            try:
                await W._notify_subscribers(client, tmdb_id)
            except Exception as e:
                logger.exception(f"[OTT] notify_go: {e}")
            if ev:
                asyncio.create_task(_bg_sync(client, ev["_id"]))
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
                f"📌 {sc('all OTT setup posts go here')}",
                "", f"📌 {sc('send')} <code>-</code> {sc('to cancel')}",
            ])
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ Cancel",
                                     callback_data="ott:set")]])
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

                # ═══════════════════════════════════════════════════
        # SETTINGS — CAPTION
        # ═══════════════════════════════════════════════════
        if action == "cap_settings":
            from plugins.ott import settings_ui as SUI
            text, kb = await SUI.view_caption_settings()
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "cap_global":
            from plugins.ott import settings_ui as SUI
            text, kb = await SUI.view_caption_global()
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "cap_global_tpl":
            from plugins.ott import settings_ui as SUI
            text, kb = await SUI.view_caption_global_templates()
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "cap_global_tpl_use":
            from plugins.ott import settings_db as SD
            from plugins.ott import settings_ui as SUI
            name = args[0] if args else "default"
            tpl = SD.CAPTION_TEMPLATES.get(name)
            if tpl:
                await SD.set_global_caption(tpl)
            await q.answer(f"✅ {name}")
            text, kb = await SUI.view_caption_global()
            await V.safe_edit(q, text, kb)
            return

        if action == "cap_global_edit":
            from plugins.ott import settings_ui as SUI
            ST.new_set_session(q.from_user.id, "edit_caption_global")
            text, kb = SUI.prompt_caption_edit("GLOBAL", "ott:cap_global")
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "cap_global_rst":
            from plugins.ott import settings_db as SD
            from plugins.ott import settings_ui as SUI
            await SD.reset_global_caption()
            await q.answer("♻️ reset")
            text, kb = await SUI.view_caption_global()
            await V.safe_edit(q, text, kb)
            return

        if action == "cap_global_prev":
            from plugins.ott import settings_ui as SUI
            text, kb = await SUI.view_caption_global_preview()
            await V.safe_edit(q, text, kb)
            return await q.answer()

        # ── CHANNEL CAPTION ──
        if action == "cap_ch_list":
            from plugins.ott import settings_ui as SUI
            text, kb = await SUI.view_caption_ch_list()
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "cap_ch":
            from plugins.ott import settings_ui as SUI
            try:
                cid = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            text, kb = await SUI.view_caption_channel(cid)
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "cap_ch_edit":
            from plugins.ott import settings_ui as SUI
            try:
                cid = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            ST.new_set_session(q.from_user.id, "edit_caption_ch", cid=cid)
            text, kb = SUI.prompt_caption_edit(f"CHANNEL {cid}",
                                                f"ott:cap_ch:{cid}")
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "cap_ch_tpl":
            from plugins.ott import settings_ui as SUI
            try:
                cid = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            text, kb = await SUI.view_caption_channel_templates(cid)
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "cap_ch_tpl_use":
            from plugins.ott import settings_db as SD
            from plugins.ott import settings_ui as SUI
            try:
                cid = int(args[0])
                name = args[1]
            except (ValueError, IndexError):
                return await q.answer("❌")
            tpl = SD.CAPTION_TEMPLATES.get(name)
            if tpl:
                await SD.set_channel_caption(cid, tpl)
            await q.answer(f"✅ {name}")
            text, kb = await SUI.view_caption_channel(cid)
            await V.safe_edit(q, text, kb)
            return

        if action == "cap_ch_rst":
            from plugins.ott import settings_db as SD
            from plugins.ott import settings_ui as SUI
            try:
                cid = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            await SD.set_channel_caption(cid, None)
            await q.answer("♻️ reset")
            text, kb = await SUI.view_caption_channel(cid)
            await V.safe_edit(q, text, kb)
            return

        # ── GROUP CAPTION ──
        if action == "cap_gr_list":
            from plugins.ott import settings_ui as SUI
            text, kb = await SUI.view_caption_gr_list()
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "cap_gr":
            from plugins.ott import settings_ui as SUI
            try:
                gid = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            text, kb = await SUI.view_caption_group(gid)
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "cap_gr_edit":
            from plugins.ott import settings_ui as SUI
            try:
                gid = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            ST.new_set_session(q.from_user.id, "edit_caption_gr", gid=gid)
            text, kb = SUI.prompt_caption_edit(f"GROUP {gid}",
                                                f"ott:cap_gr:{gid}")
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "cap_gr_rst":
            from plugins.ott import settings_db as SD
            from plugins.ott import settings_ui as SUI
            try:
                gid = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            await SD.set_group_caption(gid, None)
            await q.answer("♻️ reset")
            text, kb = await SUI.view_caption_group(gid)
            await V.safe_edit(q, text, kb)
            return

        # ── USERS / PREMIUM CAPTION ──
        if action == "cap_us":
            from plugins.ott import settings_ui as SUI
            text, kb = await SUI.view_caption_users("user")
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "cap_us_edit":
            from plugins.ott import settings_ui as SUI
            ST.new_set_session(q.from_user.id, "edit_caption_us")
            text, kb = SUI.prompt_caption_edit("USERS", "ott:cap_us")
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "cap_us_rst":
            from plugins.ott import settings_db as SD
            from plugins.ott import settings_ui as SUI
            await SD.set_user_caption(None)
            await q.answer("♻️ reset")
            text, kb = await SUI.view_caption_users("user")
            await V.safe_edit(q, text, kb)
            return

        if action == "cap_pm":
            from plugins.ott import settings_ui as SUI
            text, kb = await SUI.view_caption_users("premium")
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "cap_pm_edit":
            from plugins.ott import settings_ui as SUI
            ST.new_set_session(q.from_user.id, "edit_caption_pm")
            text, kb = SUI.prompt_caption_edit("PREMIUM", "ott:cap_pm")
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "cap_pm_rst":
            from plugins.ott import settings_db as SD
            from plugins.ott import settings_ui as SUI
            await SD.set_premium_caption(None)
            await q.answer("♻️ reset")
            text, kb = await SUI.view_caption_users("premium")
            await V.safe_edit(q, text, kb)
            return

        # ═══════════════════════════════════════════════════
        # SETTINGS — BUTTONS
        # ═══════════════════════════════════════════════════
        if action == "btn_settings":
            from plugins.ott import settings_ui as SUI
            text, kb = await SUI.view_buttons_settings()
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "btn_global":
            from plugins.ott import settings_ui as SUI
            text, kb = await SUI.view_buttons_global()
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "btn_global_tog":
            from plugins.ott import settings_db as SD
            from plugins.ott import settings_ui as SUI
            key = args[0] if args else ""
            r = await SD.toggle_global_button(key)
            if r is None:
                return await q.answer("❌")
            await q.answer("🟢 ON" if r else "🔴 OFF")
            text, kb = await SUI.view_buttons_global()
            await V.safe_edit(q, text, kb)
            return

        if action == "btn_global_add":
            from plugins.ott import settings_ui as SUI
            ST.new_set_session(q.from_user.id, "btn_add_global")
            text, kb = SUI.prompt_add_custom_button("GLOBAL",
                                                     "ott:btn_global")
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "btn_global_rm":
            from plugins.ott import settings_db as SD
            from plugins.ott import settings_ui as SUI
            try:
                idx = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            gb = await SD.get_global_buttons()
            custom = list(gb.get("custom") or [])
            if 0 <= idx < len(custom):
                custom.pop(idx)
                gb["custom"] = custom
                await SD.set_global_buttons(gb)
            await q.answer("🗑️ removed")
            text, kb = await SUI.view_buttons_global()
            await V.safe_edit(q, text, kb)
            return

        if action == "btn_global_rst":
            from plugins.ott import settings_db as SD
            from plugins.ott import settings_ui as SUI
            await SD.set_global_buttons(dict(SD.DEFAULT_BUTTONS))
            await q.answer("♻️ reset")
            text, kb = await SUI.view_buttons_global()
            await V.safe_edit(q, text, kb)
            return

        # Channel buttons
        if action == "btn_ch_list":
            from plugins.ott import settings_ui as SUI
            text, kb = await SUI.view_buttons_ch_list()
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "btn_ch":
            from plugins.ott import settings_ui as SUI
            try:
                cid = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            text, kb = await SUI.view_buttons_channel(cid)
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "btn_ch_custom":
            from plugins.ott import settings_db as SD
            from plugins.ott import settings_ui as SUI
            try:
                cid = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            await SD.set_channel_buttons(cid, dict(SD.DEFAULT_BUTTONS))
            await q.answer("✏️ custom created")
            text, kb = await SUI.view_buttons_channel(cid)
            await V.safe_edit(q, text, kb)
            return

        if action == "btn_ch_tog":
            from plugins.ott import settings_db as SD
            from plugins.ott import settings_ui as SUI
            try:
                cid = int(args[0])
                key = args[1]
            except (ValueError, IndexError):
                return await q.answer("❌")
            if key not in ("get_notified", "get_files", "watchlist"):
                return await q.answer("❌")
            ov = await SD.get_channel_override(cid)
            btn = dict(ov.get("buttons") or await SD.get_global_buttons())
            btn[key] = not bool(btn.get(key, True))
            await SD.set_channel_buttons(cid, btn)
            await q.answer("🟢 ON" if btn[key] else "🔴 OFF")
            text, kb = await SUI.view_buttons_channel(cid)
            await V.safe_edit(q, text, kb)
            return

        if action == "btn_ch_add":
            from plugins.ott import settings_ui as SUI
            try:
                cid = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            ST.new_set_session(q.from_user.id, "btn_add_ch", cid=cid)
            text, kb = SUI.prompt_add_custom_button(f"CHANNEL {cid}",
                                                     f"ott:btn_ch:{cid}")
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "btn_ch_rm":
            from plugins.ott import settings_db as SD
            from plugins.ott import settings_ui as SUI
            try:
                cid = int(args[0])
                idx = int(args[1])
            except (ValueError, IndexError):
                return await q.answer("❌")
            ov = await SD.get_channel_override(cid)
            btn = dict(ov.get("buttons") or await SD.get_global_buttons())
            custom = list(btn.get("custom") or [])
            if 0 <= idx < len(custom):
                custom.pop(idx)
                btn["custom"] = custom
                await SD.set_channel_buttons(cid, btn)
            await q.answer("🗑️ removed")
            text, kb = await SUI.view_buttons_channel(cid)
            await V.safe_edit(q, text, kb)
            return

        if action == "btn_ch_rst":
            from plugins.ott import settings_db as SD
            from plugins.ott import settings_ui as SUI
            try:
                cid = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            await SD.set_channel_buttons(cid, None)
            await q.answer("♻️ reset")
            text, kb = await SUI.view_buttons_channel(cid)
            await V.safe_edit(q, text, kb)
            return

        # Group buttons
        if action == "btn_gr_list":
            from plugins.ott import settings_ui as SUI
            text, kb = await SUI.view_buttons_gr_list()
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "btn_gr":
            from plugins.ott import settings_ui as SUI
            try:
                gid = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            text, kb = await SUI.view_buttons_group(gid)
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "btn_gr_custom":
            from plugins.ott import settings_db as SD
            from plugins.ott import settings_ui as SUI
            try:
                gid = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            await SD.set_group_buttons(gid, dict(SD.DEFAULT_BUTTONS))
            await q.answer("✏️ custom created")
            text, kb = await SUI.view_buttons_group(gid)
            await V.safe_edit(q, text, kb)
            return

        if action == "btn_gr_tog":
            from plugins.ott import settings_db as SD
            from plugins.ott import settings_ui as SUI
            try:
                gid = int(args[0])
                key = args[1]
            except (ValueError, IndexError):
                return await q.answer("❌")
            if key not in ("get_notified", "get_files", "watchlist"):
                return await q.answer("❌")
            ov = await SD.get_group_override(gid)
            btn = dict(ov.get("buttons") or await SD.get_global_buttons())
            btn[key] = not bool(btn.get(key, True))
            await SD.set_group_buttons(gid, btn)
            await q.answer("🟢 ON" if btn[key] else "🔴 OFF")
            text, kb = await SUI.view_buttons_group(gid)
            await V.safe_edit(q, text, kb)
            return

        if action == "btn_gr_add":
            from plugins.ott import settings_ui as SUI
            try:
                gid = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            ST.new_set_session(q.from_user.id, "btn_add_gr", gid=gid)
            text, kb = SUI.prompt_add_custom_button(f"GROUP {gid}",
                                                     f"ott:btn_gr:{gid}")
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "btn_gr_rm":
            from plugins.ott import settings_db as SD
            from plugins.ott import settings_ui as SUI
            try:
                gid = int(args[0])
                idx = int(args[1])
            except (ValueError, IndexError):
                return await q.answer("❌")
            ov = await SD.get_group_override(gid)
            btn = dict(ov.get("buttons") or await SD.get_global_buttons())
            custom = list(btn.get("custom") or [])
            if 0 <= idx < len(custom):
                custom.pop(idx)
                btn["custom"] = custom
                await SD.set_group_buttons(gid, btn)
            await q.answer("🗑️ removed")
            text, kb = await SUI.view_buttons_group(gid)
            await V.safe_edit(q, text, kb)
            return

        if action == "btn_gr_rst":
            from plugins.ott import settings_db as SD
            from plugins.ott import settings_ui as SUI
            try:
                gid = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            await SD.set_group_buttons(gid, None)
            await q.answer("♻️ reset")
            text, kb = await SUI.view_buttons_group(gid)
            await V.safe_edit(q, text, kb)
            return

        # Users / Premium buttons
        if action == "btn_us":
            from plugins.ott import settings_ui as SUI
            text, kb = await SUI.view_buttons_users("user")
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "btn_us_custom":
            from plugins.ott import settings_db as SD
            from plugins.ott import settings_ui as SUI
            await SD.set_user_buttons(dict(SD.DEFAULT_BUTTONS))
            await q.answer("✏️ custom created")
            text, kb = await SUI.view_buttons_users("user")
            await V.safe_edit(q, text, kb)
            return

        if action == "btn_us_tog":
            from plugins.ott import settings_db as SD
            from plugins.ott import settings_ui as SUI
            key = args[0] if args else ""
            if key not in ("get_notified", "get_files", "watchlist"):
                return await q.answer("❌")
            btn = dict(await SD.get_user_buttons()
                       or await SD.get_global_buttons())
            btn[key] = not bool(btn.get(key, True))
            await SD.set_user_buttons(btn)
            await q.answer("🟢 ON" if btn[key] else "🔴 OFF")
            text, kb = await SUI.view_buttons_users("user")
            await V.safe_edit(q, text, kb)
            return

        if action == "btn_us_add":
            from plugins.ott import settings_ui as SUI
            ST.new_set_session(q.from_user.id, "btn_add_us")
            text, kb = SUI.prompt_add_custom_button("USERS", "ott:btn_us")
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "btn_us_rm":
            from plugins.ott import settings_db as SD
            from plugins.ott import settings_ui as SUI
            try:
                idx = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            btn = dict(await SD.get_user_buttons()
                       or await SD.get_global_buttons())
            custom = list(btn.get("custom") or [])
            if 0 <= idx < len(custom):
                custom.pop(idx)
                btn["custom"] = custom
                await SD.set_user_buttons(btn)
            await q.answer("🗑️")
            text, kb = await SUI.view_buttons_users("user")
            await V.safe_edit(q, text, kb)
            return

        if action == "btn_us_rst":
            from plugins.ott import settings_db as SD
            from plugins.ott import settings_ui as SUI
            await SD.set_user_buttons(None)
            await q.answer("♻️")
            text, kb = await SUI.view_buttons_users("user")
            await V.safe_edit(q, text, kb)
            return

        if action == "btn_pm":
            from plugins.ott import settings_ui as SUI
            text, kb = await SUI.view_buttons_users("premium")
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "btn_pm_custom":
            from plugins.ott import settings_db as SD
            from plugins.ott import settings_ui as SUI
            await SD.set_premium_buttons(dict(SD.DEFAULT_BUTTONS))
            await q.answer("✏️ custom created")
            text, kb = await SUI.view_buttons_users("premium")
            await V.safe_edit(q, text, kb)
            return

        if action == "btn_pm_tog":
            from plugins.ott import settings_db as SD
            from plugins.ott import settings_ui as SUI
            key = args[0] if args else ""
            if key not in ("get_notified", "get_files", "watchlist"):
                return await q.answer("❌")
            btn = dict(await SD.get_premium_buttons()
                       or await SD.get_global_buttons())
            btn[key] = not bool(btn.get(key, True))
            await SD.set_premium_buttons(btn)
            await q.answer("🟢 ON" if btn[key] else "🔴 OFF")
            text, kb = await SUI.view_buttons_users("premium")
            await V.safe_edit(q, text, kb)
            return

        if action == "btn_pm_add":
            from plugins.ott import settings_ui as SUI
            ST.new_set_session(q.from_user.id, "btn_add_pm")
            text, kb = SUI.prompt_add_custom_button("PREMIUM", "ott:btn_pm")
            await V.safe_edit(q, text, kb)
            return await q.answer()

        if action == "btn_pm_rm":
            from plugins.ott import settings_db as SD
            from plugins.ott import settings_ui as SUI
            try:
                idx = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            btn = dict(await SD.get_premium_buttons()
                       or await SD.get_global_buttons())
            custom = list(btn.get("custom") or [])
            if 0 <= idx < len(custom):
                custom.pop(idx)
                btn["custom"] = custom
                await SD.set_premium_buttons(btn)
            await q.answer("🗑️")
            text, kb = await SUI.view_buttons_users("premium")
            await V.safe_edit(q, text, kb)
            return

        if action == "btn_pm_rst":
            from plugins.ott import settings_db as SD
            from plugins.ott import settings_ui as SUI
            await SD.set_premium_buttons(None)
            await q.answer("♻️")
            text, kb = await SUI.view_buttons_users("premium")
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


# ═══════════════════════════════════════════════════════════
# MANUAL TARGET TEXT INPUT
# ═══════════════════════════════════════════════════════════

@Client.on_message(
    filters.private & filters.text & ~filters.regex(r"^/"),
    group=-441,
)
async def ott_manual_input(client: Client, message):
    if not message.from_user or not _is_admin(message.from_user.id):
        return
    sess = ST.get_session(message.from_user.id)
    if not sess or sess["action"] != "manual_target":
        return

    text = (message.text or "").strip()
    try:
        message.stop_propagation()
    except Exception:
        pass

    tmdb_id = sess["data"].get("tmdb_id")

    if text == "-":
        ST.clear_session(message.from_user.id)
        return await message.reply_text("❌ Cancelled")

    try:
        from plugins.ott import channel_flow as CF
        await CF.handle_manual_target_input(
            client, message, tmdb_id, text)
    except Exception as e:
        logger.exception(f"[OTT] manual: {e}")
        await message.reply_text(f"❌ {type(e).__name__}")

    ST.clear_session(message.from_user.id)


__all__ = ["open_panel_for_admin"]
