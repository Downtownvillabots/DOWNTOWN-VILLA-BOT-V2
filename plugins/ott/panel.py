# ============================================================
# 🏨 DOWNTOWN VILLA — OTT PANEL + ROUTER
# ============================================================

from __future__ import annotations
import logging

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
)

from plugins.broadcast.config import fb, sc, DIV, _is_admin
from plugins.ott import database as DB
from plugins.ott import state as ST
from plugins.ott import views as V
from plugins.ott import channel_flow as CF
from plugins.ott import watcher as W
from plugins.ott import engine as EG
from plugins.ott import keyboards as KB
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
    data = str(q.data)
    parts = data.split(":")
    action = parts[1] if len(parts) > 1 else ""
    args = parts[2:]

    is_admin = bool(q.from_user and _is_admin(q.from_user.id))

    try:
        # ═══════════════════════════════════════════════════
        # PUBLIC ROUTES (any user)
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

        # ── USER: subscribe to a movie ──
        if action == "sub":
            try:
                tmdb_id = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            uid = q.from_user.id

            if await DB.is_movie_ended(tmdb_id):
                return await q.answer(
                    "💥 This event has ended.", show_alert=True)

            if await DB.sub_exists(uid, tmdb_id):
                await DB.sub_remove(uid, tmdb_id)
                # refresh admin post
                try:
                    await CF.refresh_admin_post(client, tmdb_id)
                except Exception:
                    pass
                return await q.answer("🔕 Unsubscribed")

            movie = await DB.get_movie(tmdb_id) or {}
            title = movie.get("title") or "?"
            year = (movie.get("release_date") or "")[:4]
            rel = movie.get("release_date") or ""
            await DB.sub_add(uid, tmdb_id, title, year, rel)

            try:
                await CF.refresh_admin_post(client, tmdb_id)
            except Exception:
                pass
            return await q.answer(
                f"✅ You will be notified when '{title}' is uploaded")

        # ── USER: add to watchlist ──
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

        # ── USER: view files list ──
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
                pass
            return await q.answer()

        # ── USER: get a specific file ──
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
            title = (movie.get("title") or "?")[:50]

            if not file_id:
                return await q.answer(
                    "⚠️ File reference missing", show_alert=True)

            await q.answer("📤 Sending…")
            try:
                # Try to forward/copy the original message
                if src_chat and src_msg:
                    try:
                        m = await client.copy_message(
                            chat_id=q.from_user.id,
                            from_chat_id=int(src_chat),
                            message_id=int(src_msg),
                        )
                    except Exception:
                        m = await client.send_cached_media(
                            chat_id=q.from_user.id,
                            file_id=file_id,
                        )
                else:
                    m = await client.send_cached_media(
                        chat_id=q.from_user.id,
                        file_id=file_id,
                    )

                # log
                try:
                    await DB.sent_log(q.from_user.id, tmdb_id,
                                      mode="file_sent")
                except Exception:
                    pass
            except Exception as e:
                logger.exception(f"[OTT] file_get: {e}")
                return await q.answer(
                    f"❌ {type(e).__name__}", show_alert=True)
            return

        # ── USER: get file (single, from old button) ──
        if action == "getfile":
            try:
                tmdb_id = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            return await q.answer(
                "📥 Tap Get Files to choose quality",
                show_alert=True)

        # ── USER: share ──
        if action == "share":
            try:
                tmdb_id = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            movie = await DB.get_movie(tmdb_id) or {}
            title = movie.get("title") or "?"
            await q.answer(
                f"📤 Share: {title}",
                show_alert=True)
            return

        # ── PUBLIC stats (any user taps) ──
        if action == "stats_pub":
            try:
                tmdb_id = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
            s = await DB.movie_stats(tmdb_id)
            movie = await DB.get_movie(tmdb_id) or {}
            title = (movie.get("title") or "?")[:40]
            await q.answer(
                f"🎬 {title}\n"
                f"🔔 {s['total_subs']} subscribed\n"
                f"✅ {s['notified']} notified\n"
                f"⏳ {s['pending']} pending",
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

        # ── DASHBOARD ──
        if action == "dash":
            text, kb = await V.view_dashboard()
            await V.safe_edit(q, text, kb)
            return await q.answer()

        # ── LANGUAGE → movie list ──
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

        # ── REFETCH ──
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
                days = [[dict(m) for m in by_day.get(i, [])] for i in range(7)]
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

        # ── CHANNEL SETUP (in admin channel) ──
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
            return await CF.confirm_bc(client, q, tmdb_id, "gr", 0)

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

        if action == "csetup_bc_send":
            try:
                tmdb_id = int(args[0])
                kind = args[1]
                tid = int(args[2])
            except (ValueError, IndexError):
                return await q.answer("❌")
            if kind == "ch":
                return await CF.confirm_bc(client, q, tmdb_id, "ch", tid)
            if kind == "chall":
                return await CF.confirm_bc(client, q, tmdb_id, "chall", 0)
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

        # ── STATS ──
        if action == "stats":
            try:
                tmdb_id = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌")
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
            # Edit in place if possible
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
            await q.answer(f"💥 {res['deleted']} tokens deleted")

            # Refresh admin post → ended view
            try:
                await CF.refresh_admin_post(client, tmdb_id)
            except Exception:
                pass
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
                f"📌 {sc('all OTT movie setup posts go here')}",
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
