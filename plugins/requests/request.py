# ============================================================
# 🏨 DOWNTOWN VILLA — REQUEST CALLBACKS
# ============================================================

from __future__ import annotations
import logging

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.errors import UserIsBlocked
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
)

from core import config
from plugins.requests import state as RS
from plugins.requests import delivery as RD
from utils import fonts as F

logger = logging.getLogger(__name__)
DIV = "━" * 26

# Only these actions require admin rights
_ADMIN_ACTIONS = {"updated", "notreleased", "notfound", "cancel"}


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
# ROUTER
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

    # ── GET FILE uses delivery tokens, not request tokens ──
    if action == "getfile":
        return await _handle_getfile(client, q, token)

    # ── Admin-only actions ──
    if action in _ADMIN_ACTIONS:
        if not await _is_channel_admin(
            client, q.message.chat.id, q.from_user.id,
        ):
            return await q.answer("⛔ Admins only", show_alert=True)

        req = await RS.get_request(token)
        if not req:
            return await q.answer("⏱️ Request expired", show_alert=True)

        if action == "updated":
            await _handle_updated(client, q, req, token)
        elif action == "notreleased":
            await _handle_notreleased(client, q, req, token)
        elif action == "notfound":
            await _handle_notfound(client, q, req, token)
        elif action == "cancel":
            await _handle_cancel(client, q, req, token)
        return

    if action == "noop":
        return await q.answer()

    return await q.answer("❓")


# ============================================================
# ADMIN: UPDATED
# ============================================================

async def _handle_updated(client, q, req, token):
    user_id = int(req.get("user_id", 0))
    movie_name = req.get("movie_name") or "?"
    kind = req.get("kind", "movie")
    year = req.get("year")
    is_series = kind == "series"
    kind_icon = "📺" if is_series else "🎬"
    kind_label = "SERIES" if is_series else "MOVIE"

    # ── 1. Create delivery token (only info needed for GET FILE) ──
    delivery_token = await RD.create_delivery(
        user_id=user_id,
        movie_name=str(movie_name),
        year=str(year) if year else None,
        kind=kind,
    )

    if not delivery_token:
        delivery_token = token
        logger.warning("[REQ] delivery create failed — reusing request token")

    if delivery_token != token:
        await RS.delete_request(token)

    # ── 3. Message to user ──
    text = "\n".join([
        f"{F.EMO['party']} <b>{F.fb('GOOD NEWS!')}</b>",
        DIV, "",
        f"{kind_icon} <b>{F.sc(movie_name)}</b>",
        "",
        f"{F.EMO['check']} Your requested {kind_label.lower()} "
        f"has been <b>uploaded</b>!",
        "",
        DIV, "",
        f"{F.EMO['spark']} Tap the button below to get the file",
    ])

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"{F.EMO['rocket']} {F.sc('get file')}",
            callback_data=f"req:getfile:{delivery_token}",
        )],
        [InlineKeyboardButton(
            f"📢 {F.sc('updates')}",
            url=config.UPDATE_CHNL_LNK or "https://t.me/",
        )],
    ])

    # Try poster
    sent = False
    poster_path = req.get("poster")
    if not poster_path:
        try:
            from plugins.pm_search import enrich as IE
            meta = await IE.enrich(movie_name)
            if meta:
                poster_path = meta.get("poster")
        except Exception:
            pass

    if poster_path:
        try:
            await client.send_photo(
                chat_id=user_id,
                photo=f"https://image.tmdb.org/t/p/w500{poster_path}",
                caption=text[:1024],
                reply_markup=kb,
                parse_mode=ParseMode.HTML,
            )
            sent = True
        except Exception:
            pass

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
        except Exception as e:
            logger.debug(f"[REQ] DM updated: {e}")

    # ── 4. Strike the admin message ──
    try:
        original = q.message.text or q.message.caption or ""
        await q.message.edit_text(
            f"<b><strike>{original}</strike></b>\n\n"
            f"<b>{kind_icon} {kind_label} UPDATED ✅</b>",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"✅ {F.sc('notified')}",
                    callback_data="req:noop:done",
                ),
            ]]),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception:
        pass

    await q.answer("✅ User notified")


# ============================================================
# ADMIN: NOT RELEASED
# ============================================================

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
            chat_id=user_id, text=text, reply_markup=kb,
            parse_mode=ParseMode.HTML, disable_web_page_preview=True,
        )
    except Exception:
        pass

    # Expire request token
    await RS.delete_request(token)

    try:
        original = q.message.text or q.message.caption or ""
        await q.message.edit_text(
            f"<b><strike>{original}</strike></b>\n\n<b>📅 NOT RELEASED</b>",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception:
        pass
    await q.answer("✅ Notified")


# ============================================================
# ADMIN: NOT FOUND
# ============================================================

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
            chat_id=user_id, text=text, reply_markup=kb,
            parse_mode=ParseMode.HTML, disable_web_page_preview=True,
        )
    except Exception:
        pass

    await RS.delete_request(token)

    try:
        original = q.message.text or q.message.caption or ""
        await q.message.edit_text(
            f"<b><strike>{original}</strike></b>\n\n<b>🔎 NOT FOUND</b>",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception:
        pass
    await q.answer("✅ Notified")


# ============================================================
# ADMIN: CANCEL
# ============================================================

async def _handle_cancel(client, q, req, token):
    await RS.delete_request(token)
    try:
        original = q.message.text or q.message.caption or ""
        await q.message.edit_text(
            f"<b><strike>{original}</strike></b>\n\n<b>❌ CANCELLED</b>",
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception:
        pass
    await q.answer("✅ Cancelled")


# ============================================================
# USER: GET FILE (uses delivery token)
# ============================================================

async def _handle_getfile(client, q, delivery_token):
    # ── 1. Lookup delivery record ──
    delivery = await RD.get_delivery(delivery_token)

    # Fallback: maybe it's still a request token (legacy)
    if not delivery:
        legacy = await RS.get_request(delivery_token)
        if legacy:
            delivery = {
                "user_id": legacy.get("user_id"),
                "movie_name": legacy.get("movie_name"),
                "year": legacy.get("year"),
                "kind": legacy.get("kind", "movie"),
            }

    if not delivery:
        return await q.answer("⏱️ Link expired", show_alert=True)

    user_id = int(delivery.get("user_id", 0))
    if int(q.from_user.id) != user_id:
        return await q.answer("⛔ Not your request", show_alert=True)

    movie_name = delivery.get("movie_name") or "?"
    year = delivery.get("year")

    await q.answer("🔎 Searching…")

    # ── 2. Fresh DB search for that movie ──
    try:
        from plugins.pm_search import handlers as PMH
        ok = await PMH.show_results_for_request(
            client=client,
            user_id=user_id,
            chat_id=q.message.chat.id,
            query=movie_name,
            year=str(year) if year else None,
        )
    except Exception as e:
        logger.exception(f"[REQ] getfile: {e}")
        return await q.answer(f"❌ {type(e).__name__}", show_alert=True)

    if ok:
        try:
            await q.message.delete()
        except Exception:
            pass
        # Delivery done — clean up
        await RD.delete_delivery(delivery_token)
        # Also clean the legacy request if we fell back
        try:
            await RS.delete_request(delivery_token)
        except Exception:
            pass
    else:
        await q.answer(
            "⏳ File is still indexing — try again in a moment",
            show_alert=True,
        )


__all__ = ["request_router"]
