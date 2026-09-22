# ============================================================
# 🏨 DOWNTOWN VILLA — REQUEST POSTER
# ============================================================
#
# Posts a request to the admin channel with action buttons.
# Format matches the screenshot: title, tmdb, user, token.
#
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


def _esc(s: Any) -> str:
    if s is None:
        return ""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


async def post_request(
    client: Client,
    user_id: int,
    username: str = "",
    full_name: str = "",
    movie_name: str = "",
    kind: str = "movie",           # "movie" | "series"
    imdb_id: Optional[str] = None,
    tmdb_id: Optional[int] = None,
    year: Optional[str] = None,
    user_query: str = "",
) -> Optional[str]:
    """Post a request to REQST_CHANNEL. Returns the token_id."""
    ch = getattr(config, "REQST_CHANNEL", None)
    if not ch:
        logger.debug("[REQ] REQST_CHANNEL not configured")
        return None

    token = await RS.create_request(
        user_id=user_id,
        username=username,
        full_name=full_name,
        movie_name=movie_name,
        kind=kind,
        imdb_id=imdb_id,
        tmdb_id=tmdb_id,
        year=year,
        user_query=user_query,
    )
    if not token:
        return None

    # Title display
    title_disp = _esc(movie_name)
    if year:
        title_disp += f" ({_esc(year)})"

    is_series = (kind or "").lower() == "series"
    kind_icon = "📺" if is_series else "🎬"
    kind_label = "SERIES" if is_series else "MOVIE"

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"{kind_icon} <b>{F.fb(f'NEW {kind_label} REQUEST')}</b>",
        DIV,
        "",
        f"{kind_icon} {F.sc(kind_label.lower())} · <b>{title_disp}</b>",
    ]
    if imdb_id:
        lines.append(f"{F.EMO['id']} ɪᴍᴅʙ · <code>{_esc(imdb_id)}</code>")
    if tmdb_id:
        lines.append(f"{F.EMO['id']} ᴛᴍᴅʙ · <code>{tmdb_id}</code>")

    # User mention
    user_mention = f"<a href='tg://user?id={user_id}'>{_esc(full_name or 'user')}</a>"

    lines += [
        "",
        f"{F.EMO['user']} ᴜꜱᴇʀ · {user_mention}",
        f"{F.EMO['id']} ɪᴅ · <code>{user_id}</code>",
    ]
    if username:
        lines.append(f"{F.EMO['info']} ᴜꜱᴇʀɴᴀᴍᴇ · @{_esc(username.lstrip('@'))}")
    else:
        lines.append(f"{F.EMO['info']} ᴜꜱᴇʀɴᴀᴍᴇ · —")

    lines += [
        "",
        f"{F.EMO['key']} ᴛᴏᴋᴇɴ · <code>{token}</code>",
        DIV,
        "",
        f"<i>{F.sc('admin')} · {F.sc('choose an action below')}</i>",
    ]

    # Buttons
    kind_btn_label = "📺 SERIES UPDATED ✅" if is_series else "🎬 MOVIE UPDATED ✅"

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            kind_btn_label,
            callback_data=f"req:updated:{token}",
        )],
        [
            InlineKeyboardButton(
                "📅 NOT RELEASED",
                callback_data=f"req:notreleased:{token}",
            ),
            InlineKeyboardButton(
                "🔎 NOT FOUND",
                callback_data=f"req:notfound:{token}",
            ),
        ],
        [InlineKeyboardButton(
            "❌ CANCEL",
            callback_data=f"req:cancel:{token}",
        )],
    ])

    try:
        await client.send_message(
            chat_id=ch,
            text="\n".join(lines),
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        logger.info(f"[REQ] posted token={token} title={movie_name!r}")
        return token
    except Exception as e:
        logger.warning(f"[REQ] post failed: {e}")
        await RS.delete_request(token)
        return None


__all__ = ["post_request"]
