# ============================================================
# 🏨 DOWNTOWN VILLA — DEFERRED REQUEST (for new users)
# ============================================================

from __future__ import annotations
import logging
from typing import Any, Dict, Optional

from pyrogram import Client
from pyrogram.enums import ParseMode
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from core import config
from plugins.requests import state as RS
from utils import fonts as F

logger = logging.getLogger(__name__)
DIV = "━" * 26


async def is_registered(user_id: int) -> bool:
    """True if user has ever started the bot."""
    try:
        from database import db_registry
        db = db_registry.get_user_db()
        if db is None:
            return False
        doc = await db["users"].find_one(
            {"user_id": int(user_id)}, {"_id": 1}
        )
        return doc is not None
    except Exception:
        return False


async def get_bot_username(client: Client) -> str:
    try:
        me = await client.identity()
        return me.username or ""
    except Exception:
        try:
            me = await client.get_me()
            return me.username or ""
        except Exception:
            return ""


async def create_deferred_request(
    user_id: int,
    username: str,
    full_name: str,
    title: str,
    year: Optional[str],
    kind: str,
    tmdb_id: Optional[int],
    user_query: str,
) -> Optional[str]:
    """Create a request doc that will be posted when user taps the deep link."""
    try:
        token = await RS.create_request(
            user_id=user_id,
            username=username or "",
            full_name=full_name or "",
            movie_name=title,
            kind=kind or "movie",
            tmdb_id=tmdb_id,
            year=str(year) if year else None,
            user_query=user_query or title,
        )
        return token
    except Exception as e:
        logger.warning(f"[DEFERRED] create: {e}")
        return None


async def send_redirect_panel(
    client: Client,
    target,
    title: str,
    year: Optional[str],
    token: str,
) -> bool:
    """
    Send a group message with a button to bot PM.
    `target` can be a Message or a status message.
    """
    bot_username = await get_bot_username(client)
    if not bot_username:
        return False

    deep_link = f"https://t.me/{bot_username}?start=req_{token}"

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"{F.EMO['warn']} <b>{F.fb('NOT IN OUR DATABASE')}</b>",
        DIV, "",
        f"🎬 <b>{F.sc(str(title)[:60])}</b>",
    ]
    if year:
        lines.append(f"📅 <code>{year}</code>")

    lines += [
        "",
        f"📌 {F.sc('this title is not indexed yet')}",
        f"📌 {F.sc('tap the button below to send a request')}",
        f"📌 {F.sc('the admin will be notified')}",
    ]

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"{F.EMO['rocket']} {F.sc('send request to admin')}",
            url=deep_link,
        )],
        [InlineKeyboardButton(
            f"{F.EMO['close']} {F.sc('close')}",
            callback_data=f"pms:noop:0",
        )],
    ])

    try:
        if hasattr(target, "edit_text"):
            await target.edit_text(
                "\n".join(lines)[:4000],
                reply_markup=kb,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        else:
            await target.reply_text(
                "\n".join(lines)[:4000],
                reply_markup=kb,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        return True
    except Exception as e:
        logger.exception(f"[DEFERRED] send: {e}")
        return False


async def handle_req_token(
    client: Client,
    message,
    token: str,
) -> bool:
    """
    Called by /start router when payload is req_{token}.
    Posts the deferred request to the admin channel.
    """
    try:
        req = await RS.get_request(token)
        if not req:
            await message.reply_text(
                "\n".join([
                    f"{F.EMO['warn']} <b>{F.fb('LINK EXPIRED')}</b>",
                    DIV, "",
                    f"📌 {F.sc('search again in the group')}",
                ]),
                parse_mode=ParseMode.HTML,
            )
            return True

        # Confirm the token belongs to this user
        uid = message.from_user.id
        if int(req.get("user_id", 0)) != int(uid):
            await message.reply_text(
                f"{F.EMO['cross']} {F.sc('this link is not for you')}",
                parse_mode=ParseMode.HTML,
            )
            return True

        # Post to admin channel using existing token
        from plugins.requests import poster as RP
        posted = await RP.post_request(
            client=client,
            user_id=int(req.get("user_id", 0)),
            username=str(req.get("username") or ""),
            full_name=str(req.get("full_name") or ""),
            movie_name=str(req.get("movie_name") or "?"),
            kind=str(req.get("kind") or "movie"),
            tmdb_id=req.get("tmdb_id"),
            year=req.get("year"),
            user_query=str(req.get("user_query") or ""),
            existing_token=token,
        )

        if posted:
            await message.reply_text(
                "\n".join([
                    f"{F.EMO['check']} <b>{F.fb('REQUEST SENT')}</b>",
                    DIV, "",
                    f"🎬 <b>{F.sc(str(req.get('movie_name') or '?')[:60])}</b>",
                    "",
                    f"📌 {F.sc('admins have been notified')}",
                    f"📌 {F.sc('you will receive a message once uploaded')}",
                ]),
                parse_mode=ParseMode.HTML,
            )
        else:
            await message.reply_text(
                f"{F.EMO['cross']} {F.sc('could not send — try again')}",
                parse_mode=ParseMode.HTML,
            )
        return True
    except Exception as e:
        logger.exception(f"[DEFERRED] handle: {e}")
        return False


__all__ = [
    "is_registered",
    "get_bot_username",
    "create_deferred_request",
    "send_redirect_panel",
    "handle_req_token",
]
