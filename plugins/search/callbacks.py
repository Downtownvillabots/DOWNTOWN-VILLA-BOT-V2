# ============================================================
# 🏨 DOWNTOWN VILLA — SEARCH CALLBACK ROUTER
# ============================================================
#
# Routes every search-flow callback to the flow engine.
#
# Handles:
#   • cancel:flow:{run_id}
#   • flow:back:{run_id}
#   • lang:pick:{run_id}:{idx}
#   • seas:pick:{run_id}:{idx}
#   • ep:pick:{run_id}:{idx}
#   • ep:page:{run_id}:{page}
#   • qual:pick:{run_id}:{idx}
#   • sug:pick:{run_id}:{idx}
#   • sr:file:{session_id}:{idx}  → file delivery
#   • sr:cancel
#
# ============================================================

from __future__ import annotations

import logging

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import CallbackQuery, InlineKeyboardMarkup

logger = logging.getLogger(__name__)


# ============================================================
# STEP PICK ROUTER
# ============================================================

STEP_PREFIXES = (
    "lang:pick:",
    "seas:pick:",
    "ep:pick:",
    "ep:page:",
    "qual:pick:",
    "sug:pick:",
)


@Client.on_callback_query(
    filters.regex(r"^(lang|seas|ep|qual|sug):(pick|page):"),
    group=-8100,
)
async def step_callback(client: Client, q: CallbackQuery):
    """Dispatch every step-pick to the flow engine."""
    try:
        from core import flow_engine as FE
        from core.flow_engine import get_run

        # Extract run_id from the callback data
        parts = str(q.data).split(":")
        # format: prefix:action:run_id:arg...
        if len(parts) < 3:
            return await q.answer("❌ Invalid")

        run_id = parts[2]
        run = get_run(run_id)
        if not run:
            return await q.answer("⏱️ Session expired", show_alert=True)

        # Hand off to engine — it delegates to the current step's on_input
        result = await FE.engine.handle_input(run, q)

        # Handle the result
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

        # Re-render next step
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
# UNIVERSAL CANCEL + BACK
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
# FILE DELIVERY (from group session)
# ============================================================

@Client.on_callback_query(
    filters.regex(r"^sr:file:"),
    group=-8097,
)
async def sr_file(client: Client, q: CallbackQuery):
    try:
        parts = str(q.data).split(":")
        # sr:file:{session_id}:{idx}
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
# SEARCH CANCEL (generic)
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
# STATS
# ============================================================

def snapshot() -> dict:
    return {"router": "search"}


__all__ = ["snapshot"]
