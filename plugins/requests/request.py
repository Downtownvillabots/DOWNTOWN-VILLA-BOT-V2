# ============================================================
# 🏨 DOWNTOWN VILLA — REQUEST CALLBACKS
# ============================================================
#
# Admin clicks a button in the request channel:
#   📺 SERIES UPDATED ✅ / 🎬 MOVIE UPDATED ✅
#   📅 NOT RELEASED
#   🔎 NOT FOUND
#   ❌ CANCEL
#
# → user gets notified in PM
# → channel message is struck through
#
# ============================================================

from __future__ import annotations
import logging
from typing import Optional

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.errors import UserIsBlocked, FloodWait
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from core import config
from plugins.requests import state as RS
from utils import fonts as F

logger = logging.getLogger(__name__)

DIV = "━" * 26


def _is_admin(uid) -> bool:
    try:
        return int(uid) in [int(a) for a in config.ADMINS]
    except Exception:
        return False


async def _is_channel_admin(client, chat_id, user_id) -> bool:
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
# CALLBACK ROUTER
# ============================================================

@Client.on_callback_query(
    filters.regex(r"^req:"),
    group=-8600,
)
async def request_router(client: Client, q: CallbackQuery):
    try:
        parts = str(q.data).split(":", 2)
        if len(parts) < 3:
            return await q.answer("❌")
        action = parts[1]
        token = parts[2]
    except Exception:
        return await q.answer("❌")

    # Auth
    if not await _is_channel_admin(client, q.message.chat.id, q.from_user.id):
        return await q.answer("⛔ Admins only", show_alert=True)

    req = await RS.get_request(token)
    if not req:
        return await q.answer("⏱️ Request not found", show_alert=True)

    # Dispatch
    if action == "updated":
        await _handle_updated(client, q, req, token)
    elif action == "notreleased":
        await _handle_notreleased(client, q, req, token)
    elif action == "notfound":
        await _handle_notfound(client, q, req, token)
    elif action == "cancel":
        await _handle_cancel(client, q, req, token)
    elif action == "noop":
        await q.answer()
    elif action == "getfile":
        await _handle_getfile(client, q, req, token)
    else:
        await q.answer("❓")


# ============================================================
# HANDLERS
# ============================================================

async def _handle_updated(client, q, req, token):
    user_id = int(req.get("user_id", 0))
    movie_name = req.get("movie_name") or "?"
    kind = req.get("kind", "movie")
    is_series = kind == "series"
    kind_icon = "📺" if is_series else "🎬"
    kind_label = "SERIES" if is_series else "MOVIE"

    text = "\n".join([
        f"{F.EMO['party']} <b>{F.fb('GOOD NEWS!')}</b>",
        DIV, "",
        f"{kind_icon} <b>{F.sc(movie_name)}</b>",
        "",
        f"{F.EMO['check']} Your requested {kind_label.lower()} "
        f"has been <b>uploaded</b>!",
        "",
        DIV,
        "",
        f"{F.EMO['search']} Search it in the group to get it",
        f"{F.EMO['spark']} Or tap the button below",
    ])

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"{F.EMO['rocket']} {F.sc('get file')}",
            callback_data=f"req:getfile:{token}",
        )],
        [InlineKeyboardButton(
            f"📢 {F.sc('updates')}",
            url=config.UPDATE_CHNL_LNK or "https://t.me/",
        )],
    ])

    # ── Try to send with poster ──
    sent = False
    poster_path = req.get("poster")
    tmdb_id = req.get("tmdb_id")
    year = req.get("year")

    if not poster_path and tmdb_id:
        try:
            from plugins.pm_search import enrich as IE
            meta = await IE.enrich(movie_name, year=int(year) if year and str(year).isdigit() else None)
            if meta:
                poster_path = meta.get("poster")
        except Exception as e:
            logger.debug(f"[REQ] poster fetch: {e}")

    if poster_path:
        url = f"https://image.tmdb.org/t/p/w500{poster_path}"
        try:
            await client.send_photo(
                chat_id=user_id,
                photo=url,
                caption=text[:1024],
                reply_markup=kb,
                parse_mode=ParseMode.HTML,
            )
            sent = True
        except Exception as e:
            logger.debug(f"[REQ] DM photo: {e}")

    if not sent:
        try:
            await client.send_message(
                chat_id=user_id,
                text=text,
                reply_markup=kb,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except UserIsBlocked:
            pass
        except FloodWait as e:
            await asyncio.sleep(e.value + 2)
        except Exception as e:
            logger.debug(f"[REQ] DM updated: {e}")

    await RS.delete_request(token)

    # Strike through the original message
    try:
        original = q.message.text or q.message.caption or ""
        new_text = (
            f"<b><strike>{original}</strike></b>\n\n"
            f"<b>{kind_icon} {kind_label} UPDATED ✅</b>"
        )
        await q.message.edit_text(
            new_text,
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"✅ {F.sc('notified')}",
                    callback_data=f"req:noop:{token}",
                ),
            ]]),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.debug(f"[REQ] edit updated: {e}")

    await q.answer("✅ User notified")


async def _handle_notreleased(client, q, req, token):
    user_id = int(req.get("user_id", 0))
    movie_name = req.get("movie_name") or "?"

    text = "\n".join([
        f"{F.EMO['cal']} <b>{F.fb('NOT RELEASED YET')}</b>",
        DIV, "",
        f"🎬 <b>{F.sc(movie_name)}</b>",
        "",
        f"📌 Your request hasn't been released yet.",
        f"{F.EMO['bell']} We'll notify you when it arrives.",
    ])

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            f"📢 {F.sc('updates')}",
            url=config.UPDATE_CHNL_LNK or "https://t.me/",
        ),
    ]])

    try:
        await client.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.debug(f"[REQ] DM notreleased: {e}")

        await RS.delete_request(token)

    try:
        original = q.message.text or q.message.caption or ""
        await q.message.edit_text(
            f"<b><strike>{original}</strike></b>\n\n"
            f"<b>📅 NOT RELEASED</b>",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception:
        pass

    await q.answer("✅ Notified")


async def _handle_notfound(client, q, req, token):
    user_id = int(req.get("user_id", 0))
    movie_name = req.get("movie_name") or "?"

    text = "\n".join([
        f"{F.EMO['search']} <b>{F.fb('NOT FOUND')}</b>",
        DIV, "",
        f"🎬 <b>{F.sc(movie_name)}</b>",
        "",
        f"📌 We couldn't find this title.",
        f"{F.EMO['spark']} Please check the spelling and try again.",
    ])

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            f"💬 {F.sc('support')}",
            url=config.SUPPORT_CHAT or "https://t.me/",
        ),
    ]])

    try:
        await client.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.debug(f"[REQ] DM notfound: {e}")

    await RS.delete_request(token)

    try:
        original = q.message.text or q.message.caption or ""
        await q.message.edit_text(
            f"<b><strike>{original}</strike></b>\n\n"
            f"<b>🔎 NOT FOUND</b>",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception:
        pass

    await q.answer("✅ Notified")


async def _handle_cancel(client, q, req, token):
    await RS.delete_request(token)

    try:
        original = q.message.text or q.message.caption or ""
        await q.message.edit_text(
            f"<b><strike>{original}</strike></b>\n\n"
            f"<b>❌ CANCELLED</b>",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception:
        pass

    await q.answer("✅ Cancelled")


async def _handle_getfile(client, q, req, token):
    """
    User clicked get-file in their PM.
    Routes to PM search panel — shows all matching files as buttons.
    """
    user_id = int(req.get("user_id", 0))
    if q.from_user.id != user_id:
        return await q.answer("⛔ Not your request", show_alert=True)

    movie_name = req.get("movie_name") or "?"
    year = req.get("year")

    await q.answer("🔎 Searching…")

    try:
        from plugins.pm_search import handlers as PMH
        ok = await PMH.show_results_for_request(
            client=client,
            user_id=user_id,
            chat_id=q.message.chat.id,
            query=movie_name,
            year=str(year) if year else None,
        )
        if ok:
            try:
                await q.message.delete()
            except Exception:
                pass
        else:
            await q.answer("⏳ Still not uploaded", show_alert=True)
    except Exception as e:
        logger.exception(f"[REQ] getfile: {e}")
        await q.answer(f"❌ {type(e).__name__}", show_alert=True)


# ============================================================
# IMPORTS AT END
# ============================================================

import asyncio  # noqa: E402


__all__ = ["request_router"]
