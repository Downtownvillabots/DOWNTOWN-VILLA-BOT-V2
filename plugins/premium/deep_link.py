# ============================================================
# 🏨 DOWNTOWN VILLA — PREMIUM DEEP LINK HANDLER
# ============================================================
#
# Handles prem_{token} deep links from series group.
#
# When user taps "Open Premium Watch" button in series group:
#   https://t.me/bot?start=prem_{token}
#   → this module runs
#   → opens premium watch panel in PM
#
# Also exposes is_premium() for group search to check.
#
# ============================================================

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from pyrogram import Client
from pyrogram.enums import ParseMode
from pyrogram.types import Message

from utils import fonts as F

logger = logging.getLogger(__name__)


# ============================================================
# PUBLIC: is_premium wrapper
# ============================================================

async def is_premium(user_id: int) -> bool:
    from plugins.premium import state as S
    return await S.is_premium(user_id)


# ============================================================
# HANDLE prem_{token}
# ============================================================

async def handle_prem_token(
    client: Client,
    message: Message,
    token: str,
) -> bool:
    """
    Called by core/start_router when payload is `prem_{token}`.
    Returns True if handled.
    """
    try:
        from plugins.series_group import deep_link as DL

        data = await DL.get_token(token)
        if not data:
            await message.reply_text(
                "\n".join([
                    f"{F.EMO['warn']} <b>{F.fb('LINK EXPIRED')}</b>",
                    F.DIV, "",
                    f"📌 {F.sc('please search again in the group')}",
                ]),
                parse_mode=ParseMode.HTML,
            )
            return True

        if data.get("kind") != "premium":
            return False

        uid = message.from_user.id
        if int(data.get("user_id", 0)) != int(uid):
            await message.reply_text(
                f"{F.EMO['cross']} {F.sc('this link is not for you')}",
                parse_mode=ParseMode.HTML,
            )
            return True

        # Check premium still active
        from plugins.premium import state as S
        if not await S.is_premium(uid):
            await message.reply_text(
                "\n".join([
                    f"{F.EMO['crown']} <b>{F.fb('PREMIUM REQUIRED')}</b>",
                    F.DIV, "",
                    f"📌 {F.sc('your premium access has ended')}",
                    f"📌 {F.sc('contact admin to renew')}",
                ]),
                parse_mode=ParseMode.HTML,
            )
            return True

        # Prepare watch session in PM
        from plugins.premium import premium_watch as PW
        await PW.open_from_token(client, message, data)

        # Mark token used
        await DL.mark_used(token)
        return True

    except Exception as e:
        logger.exception(f"[PREM-LINK] handle: {e}")
        return False


# ============================================================
# PUBLIC
# ============================================================

__all__ = ["is_premium", "handle_prem_token"]
