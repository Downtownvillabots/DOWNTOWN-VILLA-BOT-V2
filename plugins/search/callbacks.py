# ============================================================
# 🏨 DOWNTOWN VILLA — SEARCH CALLBACK ROUTER
# ============================================================
#
# Routes every search-flow callback to the flow engine.
#
# Handles:
#   • cancel:flow:{run_id}          → cancel flow
#   • flow:back:{run_id}            → go back one step
#   • lang:pick:{run_id}:{idx}      → step pick (via engine)
#   • seas:pick:{run_id}:{idx}      → step pick
#   • ep:pick:{run_id}:{idx}        → step pick
#   • ep:page:{run_id}:{page}       → step pagination
#   • qual:pick:{run_id}:{idx}      → step pick
#   • sug:pick:{run_id}:{idx}       → step pick
#   • sr:file:{sid}:{idx}           → PM delivery
#   • sr:more:{sid}                 → show next batch of files
#   • sr:sug:{sid}:{idx}            → suggestion → new search
#   • sr:cancel                     → close
#
# ============================================================

from __future__ import annotations

import logging
from typing import Any, Dict, List

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
)

from utils import fonts as F
from utils import format as FM

logger = logging.getLogger(__name__)


# ============================================================
# STEP PICK ROUTER
# ============================================================

@Client.on_callback_query(
    filters.regex(r"^(lang|seas|ep|qual|sug):(pick|page):"),
    group=-8100,
)
async def step_callback(client: Client, q: CallbackQuery):
    """Dispatch every step-pick to the flow engine."""
    try:
        from core import flow_engine as FE
        from core.flow_engine import get_run

        parts = str(q.data).split(":")
        if len(parts) < 3:
            return await q.answer("❌ Invalid")

        run_id = parts[2]
        run = get_run(run_id)
        if not run:
            return await q.answer("⏱️ Session expired", show_alert=True)

        result = await FE.engine.handle_input(run, q)

        if result is None:
            await q.answer()
            return

        action = result.action

        if action == "cancel":
            try:
                await q.message.delete()
            except Exception:
                pass
            return await q.answer("❌ Cancelled")

        if action == "done":
            try:
                await q.message.delete()
            except Exception:
                pass
            return await q.answer("✅ Done")

        render = await FE.engine.render(run)
        if render is None:
            try:
                await q.message.delete()
            except Exception:
                pass
            return await q.answer()

        try:
            await q.message.edit_text(
                render.text,
                reply_markup=render.keyboard,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except Exception as e:
            if "not modified" not in str(e).lower():
                logger.debug(f"[SEARCH-CB] edit: {e}")

        await q.answer()

    except Exception as e:
        logger.exception(f"[SEARCH-CB] step: {e}")
        try:
            await q.answer(f"❌ {type(e).__name__}", show_alert=True)
        except Exception:
            pass


# ============================================================
# CANCEL + BACK
# ============================================================

@Client.on_callback_query(
    filters.regex(r"^cancel:flow:"),
    group=-8099,
)
async def cancel_flow(client: Client, q: CallbackQuery):
    try:
        from core import flow_engine as FE
        from core.flow_engine import get_run
        run_id = str(q.data).split(":", 2)[2]
        run = get_run(run_id)
        if run is not None:
            await FE.engine.cancel(run)
        try:
            await q.message.delete()
        except Exception:
            pass
        await q.answer("❌ Cancelled")
    except Exception as e:
        logger.exception(f"[SEARCH-CB] cancel: {e}")
        try:
            await q.answer("❌")
        except Exception:
            pass


@Client.on_callback_query(
    filters.regex(r"^flow:back:"),
    group=-8098,
)
async def back_flow(client: Client, q: CallbackQuery):
    try:
        from core import flow_engine as FE
        from core.flow_engine import get_run
        run_id = str(q.data).split(":", 2)[2]
        run = get_run(run_id)
        if run is None:
            return await q.answer("⚠️ Session expired")

        render = await FE.engine.go_back(run)
        if render is None:
            return await q.answer("⚠️ Cannot go back")

        try:
            await q.message.edit_text(
                render.text,
                reply_markup=render.keyboard,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except Exception as e:
            if "not modified" not in str(e).lower():
                logger.debug(f"[SEARCH-CB] back: {e}")
        await q.answer()
    except Exception as e:
        logger.exception(f"[SEARCH-CB] back: {e}")


# ============================================================
# FILE DELIVERY (from group search)
# ============================================================

@Client.on_callback_query(
    filters.regex(r"^sr:file:"),
    group=-8097,
)
async def sr_file(client: Client, q: CallbackQuery):
    try:
        parts = str(q.data).split(":")
        if len(parts) < 4:
            return await q.answer("❌ Invalid")

        sid = parts[2]
        try:
            idx = int(parts[3])
        except ValueError:
            return await q.answer("❌ Invalid index")

        await q.answer("📤 Sending to your PM…")

        from plugins.search import handlers as H
        ok, err = await H.deliver_file(client, q.from_user.id, sid, idx)

        if not ok and err:
            try:
                await q.message.reply_text(err)
            except Exception:
                pass

    except Exception as e:
        logger.exception(f"[SEARCH-CB] file: {e}")
        try:
            await q.answer("❌ Error", show_alert=True)
        except Exception:
            pass


# ============================================================
# SHOW MORE (sr:more:{sid})
# ============================================================

@Client.on_callback_query(
    filters.regex(r"^sr:more:"),
    group=-8097,
)
async def sr_more(client: Client, q: CallbackQuery):
    """
    Show the next batch of files from a session.
    Session candidates are pre-sorted small → big.
    We page through in chunks of 10.
    """
    try:
        parts = str(q.data).split(":")
        sid = parts[2] if len(parts) > 2 else ""
        if not sid:
            return await q.answer("❌")

        from media_search import sessions as _sess_mod
        session = await _sess_mod.sessions.get(sid)
        if not session:
            return await q.answer("⏱️ Session expired", show_alert=True)

        # Compute how many we've already shown
        # Buttons currently visible → parse from inline keyboard
        shown = 0
        try:
            kb = q.message.reply_markup
            if kb and kb.inline_keyboard:
                for row in kb.inline_keyboard:
                    for btn in row:
                        cd = str(getattr(btn, "callback_data", "") or "")
                        if cd.startswith(f"sr:file:{sid}:"):
                            shown += 1
        except Exception:
            shown = 10

        # Fallback: assume 10 per page
        if shown <= 0:
            shown = 10

        # Current page index
        current_page = shown // 10

        # Next page
        next_start = current_page * 10
        next_end = next_start + 10

        candidates = session.candidates or []
        if next_start >= len(candidates):
            return await q.answer("✅ All shown")

        page_slice = candidates[next_start:next_end]

        # Build deep-link bot username
        bot_username = ""
        try:
            from core.client import client as C
            if C is not None:
                me = await C.identity()
                bot_username = me.username or ""
        except Exception:
            pass

        rows: List[List[InlineKeyboardButton]] = []
        for i, c in enumerate(page_slice):
            global_idx = next_start + i
            size = FM.size_short(c.get("file_size", 0))
            name = str(c.get("file_name") or "file")[:32]
            quality = str(c.get("quality") or "").upper()
            label = f"📦 {size}"
            if quality:
                label += f" · {quality}"
            label += f" · {name}"
            if len(label) > 58:
                label = label[:55] + "…"

            deep_link = (
                f"https://t.me/{bot_username}?start=file_{sid}_{global_idx}"
                if bot_username else None
            )

            if deep_link:
                rows.append([InlineKeyboardButton(label, url=deep_link)])
            else:
                rows.append([InlineKeyboardButton(
                    label,
                    callback_data=f"sr:file:{sid}:{global_idx}",
                )])

        # More button (if there are still more)
        if next_end < len(candidates):
            remaining = len(candidates) - next_end
            rows.append([InlineKeyboardButton(
                f"➕ {remaining} ᴍᴏʀᴇ ʀᴇʟᴇᴀꜱᴇꜱ",
                callback_data=f"sr:more:{sid}",
            )])

        rows.append([InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('close')}",
            callback_data="sr:cancel",
        )])

        # Keep the original header, just update the keyboard
        try:
            await q.message.edit_reply_markup(
                reply_markup=InlineKeyboardMarkup(rows)
            )
            await q.answer(f"📄 Page {current_page + 1}")
        except Exception as e:
            logger.debug(f"[SEARCH-CB] more edit: {e}")
            await q.answer("⚠️ Could not update")

    except Exception as e:
        logger.exception(f"[SEARCH-CB] more: {e}")
        try:
            await q.answer("❌ Error", show_alert=True)
        except Exception:
            pass


# ============================================================
# SUGGESTION PICK (sr:sug:{sid}:{idx})
# ============================================================

@Client.on_callback_query(
    filters.regex(r"^sr:sug:"),
    group=-8097,
)
async def sr_sug(client: Client, q: CallbackQuery):
    """User picked a suggestion from the group 'did you mean?'."""
    try:
        parts = str(q.data).split(":")
        if len(parts) < 4:
            return await q.answer("❌")
        sid = parts[2]
        try:
            idx = int(parts[3])
        except ValueError:
            return await q.answer("❌")

        from media_search import sessions as _sess_mod
        session = await _sess_mod.sessions.get(sid)
        if not session:
            return await q.answer("⏱️ Expired", show_alert=True)

        candidates = session.candidates or []
        if idx < 0 or idx >= len(candidates):
            return await q.answer("❌ Invalid", show_alert=True)

        chosen = candidates[idx]
        title = chosen.get("title") or ""
        year_str = chosen.get("year") or ""
        tmdb_id = chosen.get("tmdb_id")
        kind = chosen.get("kind") or "movie"

        if not title:
            return await q.answer("❌ Empty", show_alert=True)

        await q.answer(f"🔎 Searching {title}…")

        # Re-query DB with exact title + year
        from media_search.engine import engine
        from media_search.normalizer import parse_query

        norm, _, _ = parse_query(title)
        y = int(year_str) if str(year_str).isdigit() else None

        result = await engine.search_any(norm, year=y)
        hits = list(result.hits or []) if result else []

        if not hits:
            # Retry without year
            result = await engine.search_any(norm, year=None)
            hits = list(result.hits or []) if result else []

        # ── HITS FOUND → show file list ──
        if hits:
            new_candidates = []
            for h in hits[:30]:
                try:
                    new_candidates.append(h.to_dict())
                except Exception:
                    if isinstance(h, dict):
                        new_candidates.append(h)
            new_candidates.sort(key=lambda x: x.get("file_size", 0) or 0)

            await _sess_mod.sessions.update(
                sid,
                query=title,
                normalized_query=norm,
                candidates=new_candidates,
            )
            try:
                from plugins.search.group_search import _show_file_list  # type: ignore
                await _show_file_list(q.message, title, sid, hits)
            except Exception as e:
                logger.debug(f"[SEARCH-CB] show: {e}")
            return

        # ── NO HITS → request flow ──
        user = q.from_user
        user_id = user.id
        username = user.username or ""
        full_name = user.first_name or ""

        try:
            from plugins.search import deferred as DF
            is_reg = await DF.is_registered(user_id)
        except Exception:
            is_reg = True  # assume registered on error → safest

        # ── Registered user → post request normally ──
        if is_reg:
            try:
                from plugins.requests import poster as RP
                token = await RP.post_request(
                    client=client,
                    user_id=user_id,
                    username=username,
                    full_name=full_name,
                    movie_name=title,
                    kind=kind,
                    tmdb_id=tmdb_id,
                    year=str(year_str) if year_str else None,
                    user_query=title,
                )
                if token:
                    await q.message.edit_text(
                        "\n".join([
                            f"{F.EMO['check']} <b>{F.fb('REQUEST SENT')}</b>",
                            F.DIV, "",
                            f"🎬 <b>{F.sc(title[:60])}</b>",
                            "",
                            f"📌 {F.sc('admins have been notified')}",
                            f"📌 {F.sc('you will be messaged once uploaded')}",
                        ]),
                        parse_mode=ParseMode.HTML,
                    )
                else:
                    await q.answer("⚠️ Could not send", show_alert=True)
            except Exception as e:
                logger.exception(f"[SEARCH-CB] req post: {e}")
                await q.answer("❌ Error", show_alert=True)
            return

        # ── New user → create deferred request + redirect ──
        try:
            from plugins.search import deferred as DF
            token = await DF.create_deferred_request(
                user_id=user_id,
                username=username,
                full_name=full_name,
                title=title,
                year=str(year_str) if year_str else None,
                kind=kind,
                tmdb_id=tmdb_id,
                user_query=title,
            )
            if not token:
                return await q.answer("⚠️ Could not create request", show_alert=True)

            await DF.send_redirect_panel(
                client=client,
                target=q.message,
                title=title,
                year=str(year_str) if year_str else None,
                token=token,
            )
        except Exception as e:
            logger.exception(f"[SEARCH-CB] deferred: {e}")
            await q.answer("❌ Error", show_alert=True)

    except Exception as e:
        logger.exception(f"[SEARCH-CB] sug: {e}")
        try:
            await q.answer("❌ Error", show_alert=True)
        except Exception:
            pass

# ============================================================
# SEARCH CANCEL
# ============================================================

@Client.on_callback_query(
    filters.regex(r"^sr:cancel$"),
    group=-8096,
)
async def sr_cancel(client: Client, q: CallbackQuery):
    try:
        await q.message.delete()
    except Exception:
        pass
    await q.answer("❌ Cancelled")


# ============================================================
# SNAPSHOT
# ============================================================

def snapshot() -> dict:
    return {"router": "search"}


__all__ = ["snapshot"]
