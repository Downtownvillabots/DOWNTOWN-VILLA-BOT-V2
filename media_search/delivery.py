# ============================================================
# 🏨 DOWNTOWN VILLA — FILE DELIVERY
# ============================================================
#
# Sends a FileHit to a user's PM.
#
# Used by:
#   • plugins/search/handlers.py::deliver_file
#   • core/start_router.py::_handle_file
#   • plugins/requests/request.py::_handle_getfile
#
# Public API (singleton):
#   delivery.send_file(client, user_id, hit) → (ok, err)
#
# ============================================================

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional, Tuple

from pyrogram import Client
from pyrogram.enums import ParseMode
from pyrogram.errors import FloodWait, UserIsBlocked
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from core import config
from utils import fonts as F
from utils import format as FM

logger = logging.getLogger(__name__)


# ============================================================
# DELIVERY
# ============================================================

class Delivery:
    """Sends files to users."""

    async def send_file(
        self,
        client: Client,
        user_id: int,
        hit: Any,
    ) -> Tuple[bool, str]:
        """
        Send one file with caption + buttons.

        Returns (ok, error_message).
        """
        try:
            file_id = _get(hit, "file_id")
            if not file_id:
                return False, "❌ Invalid file"

            uid = int(user_id)
            caption = self._build_caption(hit)
            kb = self._build_buttons(hit)

            sent = None
            try:
                sent = await client.send_cached_media(
                    chat_id=uid,
                    file_id=file_id,
                    caption=caption,
                    reply_markup=kb,
                    parse_mode=ParseMode.HTML,
                )
            except FloodWait as e:
                wait = int(getattr(e, "value", 30) or 30)
                logger.warning(f"[DELIVERY] flood {wait}s")
                await asyncio.sleep(wait + 2)
                sent = await client.send_cached_media(
                    chat_id=uid,
                    file_id=file_id,
                    caption=caption,
                    reply_markup=kb,
                    parse_mode=ParseMode.HTML,
                )
            except UserIsBlocked:
                return False, "⚠️ Please unblock the bot first"
            except Exception as e:
                logger.exception(f"[DELIVERY] send: {e}")
                return False, f"❌ {type(e).__name__}"

            if sent is None:
                return False, "❌ Could not send file"

            # ── Track delivery event ──
            try:
                from plugins.admin import stats as S
                S.track_file_sent(1)
            except Exception:
                pass

            # ── Optional per-group auto-delete ──
            try:
                minutes = await self._autodelete_minutes()
                if minutes > 0:
                    asyncio.create_task(
                        self._schedule_autodelete(
                            client, uid, sent.id, minutes
                        )
                    )
            except Exception:
                pass

            return True, ""

        except Exception as e:
            logger.exception(f"[DELIVERY] crash: {e}")
            return False, f"❌ {type(e).__name__}"

    # ── CAPTION ──

    def _build_caption(self, hit: Any) -> str:
        title = _get(hit, "title") or _get(hit, "series_title") or "?"
        year = _get(hit, "year")
        quality = (_get(hit, "quality") or "").upper()
        codec = (_get(hit, "codec") or "").upper()
        size = FM.size(_get(hit, "file_size") or 0)

        langs = _get(hit, "audio_languages") or []
        audio = ", ".join(str(l) for l in langs) or "—"

        subs = _get(hit, "subtitle_languages") or []
        subtitle = ", ".join(str(l) for l in subs) or "—"

        season = _get(hit, "season")
        episode = _get(hit, "episode")

        lines = [f"🎬 <b>{_esc(str(title))}</b>"]
        if year:
            lines.append(f"📅 <code>{year}</code>")

        if season is not None and episode is not None:
            lines.append(
                f"📺 <b>S{int(season):02d}E{int(episode):02d}</b>"
            )

        lines.append("")

        if quality:
            lines.append(f"🎞️ {F.sc('quality')} · <code>{quality}</code>")
        if codec:
            lines.append(f"🧬 {F.sc('codec')} · <code>{codec}</code>")
        lines.append(f"🔊 {F.sc('audio')} · <code>{_esc(audio)}</code>")
        lines.append(f"📝 {F.sc('subtitle')} · <code>{_esc(subtitle)}</code>")
        lines.append(f"💾 {F.sc('size')} · <code>{size}</code>")

        lines.append("")
        lines.append(f"⚡ <b>{F.fb('DOWNTOWN VILLA')}</b>")

        return "\n".join(lines)

    # ── BUTTONS ──

    def _build_buttons(self, hit: Any) -> Optional[InlineKeyboardMarkup]:
        rows: list = []

        title = str(_get(hit, "title") or _get(hit, "series_title") or "file")
        share_url = (
            f"https://t.me/share/url?"
            f"url=https://t.me/&"
            f"text={_url_escape(title)}"
        )
        rows.append([InlineKeyboardButton("📤 SHARE", url=share_url)])

        try:
            if config.UPDATE_CHNL_LNK:
                rows.append([InlineKeyboardButton(
                    f"📢 {F.sc('updates')}",
                    url=config.UPDATE_CHNL_LNK,
                )])
        except Exception:
            pass

        return InlineKeyboardMarkup(rows) if rows else None

    # ── AUTO-DELETE ──

    async def _autodelete_minutes(self) -> int:
        try:
            if not getattr(config, "AUTO_DELETE_ENABLED", True):
                return 0
            return int(getattr(config, "AUTO_DELETE_MINUTES", 10) or 0)
        except Exception:
            return 0

    async def _schedule_autodelete(
        self,
        client: Client,
        chat_id: int,
        msg_id: int,
        minutes: int,
    ) -> None:
        try:
            await asyncio.sleep(minutes * 60)
            await client.delete_messages(chat_id, msg_id)
        except Exception:
            pass


# ============================================================
# HELPERS
# ============================================================

def _get(hit: Any, key: str) -> Any:
    if hit is None:
        return None
    if isinstance(hit, dict):
        return hit.get(key)
    return getattr(hit, key, None)


def _esc(s: Any) -> str:
    if s is None:
        return ""
    return (
        str(s)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )


def _url_escape(s: str) -> str:
    try:
        from urllib.parse import quote
        return quote(s, safe="")
    except Exception:
        return str(s)[:50]


# ============================================================
# SINGLETON
# ============================================================

delivery = Delivery()


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    "Delivery",
    "delivery",
]
