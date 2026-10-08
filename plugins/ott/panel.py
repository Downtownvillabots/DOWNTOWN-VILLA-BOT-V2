# ============================================================
# 🏨 DOWNTOWN VILLA — OTT PANEL + ROUTER
# ============================================================

from __future__ import annotations
import logging

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import CallbackQuery

from plugins.broadcast.config import _is_admin
from plugins.ott import views as V
from plugins.ott.config import PREFIX

logger = logging.getLogger(__name__)
PFX = PREFIX


# ═══════════════════════════════════════════════════════════
# /admin → 📅 OTT
# ═══════════════════════════════════════════════════════════

async def open_panel_for_admin(client: Client, q: CallbackQuery) -> None:
    if not q.from_user or not _is_admin(q.from_user.id):
        return await q.answer("⛔ admins only", show_alert=True)

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

        # ── HOME ──
        if action == "home":
            text, kb = await V.view_home()
            await V.safe_edit(q, text, kb)
            return await q.answer()

        # ── LANGUAGE ──
        if action == "lang":
            lang = args[0] if args else "all"
            await q.answer("🎬 Loading…")
            text, kb = await V.view_language(lang)
            await V.safe_edit(q, text, kb)
            return

        # ── DAY ──
        if action == "day":
            try:
                lang = args[0]
                day_idx = int(args[1])
            except (ValueError, IndexError):
                return await q.answer("❌")
            text, kb = await V.view_day(lang, day_idx)
            await V.safe_edit(q, text, kb)
            return await q.answer()

        # ── MOVIE CARD ──
        if action == "mv":
            try:
                tmdb_id = int(args[0])
                lang = args[1] if len(args) > 1 else "all"
            except (ValueError, IndexError):
                return await q.answer("❌")

            # Get day index from lang view (compute from date)
            from plugins.ott.tmdb import fetch_week_grouped_by_lang
            grouped = await fetch_week_grouped_by_lang(
                lang=lang, region="IN", min_vote=0)
            day_idx = 0
            for i in range(7):
                if any(int(m.get("tmdb_id", 0)) == tmdb_id
                       for m in grouped.get(i, [])):
                    day_idx = i
                    break

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

        return await q.answer("❓ Unknown")

    except Exception as e:
        logger.exception(f"[OTT] router: {e}")
        try:
            await q.answer(f"❌ {type(e).__name__}", show_alert=True)
        except Exception:
            pass


__all__ = ["open_panel_for_admin"]
