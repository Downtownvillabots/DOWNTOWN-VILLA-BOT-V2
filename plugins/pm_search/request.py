# ============================================================
# 🏨 DOWNTOWN VILLA — PM SEARCH → REQUEST WRAPPER
# ============================================================

from __future__ import annotations
import logging
from typing import Any, Dict, Optional

from pyrogram import Client
from pyrogram.enums import ParseMode

logger = logging.getLogger(__name__)


async def send_request(
    client: Client,
    user_id: int,
    username: str = "",
    full_name: str = "",
    title: str = "",
    year: Optional[str] = None,
    kind: str = "movie",
    tmdb_id: Optional[int] = None,
    user_query: str = "",
) -> Optional[str]:
    """
    Post the request to REQST_CHANNEL using the existing requests module.
    Returns token_id or None.
    """
    try:
        from plugins.requests import poster as REQ
        token = await REQ.post_request(
            client=client,
            user_id=user_id,
            username=username,
            full_name=full_name,
            movie_name=title,
            kind=kind,
            tmdb_id=tmdb_id,
            year=str(year) if year else None,
            user_query=user_query or title,
        )
        return token
    except Exception as e:
        logger.exception(f"[PM-REQ] post: {e}")
        return None


async def notify_sent(
    client: Client,
    user_id: int,
    title: str,
    year: Optional[str] = None,
) -> None:
    """Notify user that request was received."""
    try:
        lines = [
            "📩 <b>REQUEST SENT</b>",
            "━━━━━━━━━━━━━━━━━━━━━━━━━━",
            "",
            f"🎬 <b>{str(title)[:60]}</b>",
        ]
        if year:
            lines.append(f"📅 <code>{year}</code>")
        lines += [
            "",
            "✅ Your request has been sent to admins.",
            "📌 You'll be notified once it's uploaded.",
        ]
        await client.send_message(
            chat_id=int(user_id),
            text="\n".join(lines),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.debug(f"[PM-REQ] notify: {e}")


__all__ = ["send_request", "notify_sent"]
