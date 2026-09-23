# ============================================================
# 🏨 DOWNTOWN VILLA — DELIVER FILE (caption + buttons + share + auto-delete)
# ============================================================

from __future__ import annotations
import asyncio, logging
from typing import Any, Dict, List, Optional

from pyrogram import Client
from pyrogram.enums import ParseMode
from pyrogram.errors import FloodWait, UserIsBlocked
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from utils import fonts as F
from utils import format as FM

logger = logging.getLogger(__name__)


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
        str(s).replace("&", "&amp;")
        .replace("<", "&lt;").replace(">", "&gt;")
    )


# ============================================================
# CAPTION
# ============================================================

def build_caption(hit: Any, cfg: Dict[str, Any]) -> str:
    tpl = cfg.get("caption_template") or ""
    title = _get(hit, "title") or _get(hit, "series_title") or "?"
    year = _get(hit, "year") or "—"
    quality = (_get(hit, "quality") or "UNKNOWN").upper()
    codec = (_get(hit, "codec") or "—").upper()
    size = FM.size(_get(hit, "file_size") or 0)
    langs = _get(hit, "audio_languages") or []
    audio = ", ".join(str(x) for x in langs) or "—"
    subs = _get(hit, "subtitle_languages") or []
    subtitle = ", ".join(str(x) for x in subs) or "—"

    try:
        return tpl.format(
            title=_esc(str(title)[:80]),
            year=_esc(year),
            quality=_esc(quality),
            codec=_esc(codec),
            audio=_esc(audio),
            subtitle=_esc(subtitle),
            size=_esc(size),
            season=_esc(_get(hit, "season") or ""),
            episode=_esc(_get(hit, "episode") or ""),
        )[:1024]
    except Exception:
        return (
            f"🎬 <b>{_esc(str(title)[:80])}</b>\n"
            f"💾 <code>{size}</code>"
        )


# ============================================================
# BUTTONS
# ============================================================

def build_kb(hit: Any, cfg: Dict[str, Any]) -> Optional[InlineKeyboardMarkup]:
    per_row = max(1, min(3, int(cfg.get("delivered_buttons_per_row", 2) or 2)))
    rows: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []

    for b in (cfg.get("delivered_buttons") or []):
        if not isinstance(b, dict) or not b.get("enabled", True):
            continue
        name = str(b.get("name") or "")[:60]
        url = str(b.get("url") or "").strip()
        if not name or not url:
            continue
        if url.startswith("@"):
            url = f"https://t.me/{url[1:]}"
        elif not (url.startswith("http://")
                  or url.startswith("https://")
                  or url.startswith("tg://")):
            if "." in url and " " not in url:
                url = f"https://{url}"
            else:
                continue
        row.append(InlineKeyboardButton(name, url=url))
        if len(row) >= per_row:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    # Share button
    if cfg.get("share_button", True):
        title = _get(hit, "title") or _get(hit, "series_title") or "file"
        try:
            from urllib.parse import quote
            share_text = quote(str(title), safe="")
        except Exception:
            share_text = "Check%20this"
        share_url = (
            f"https://t.me/share/url?"
            f"url=https://t.me/&"
            f"text={share_text}"
        )
        rows.append([InlineKeyboardButton(
            f"📤 {F.sc('share')}", url=share_url,
        )])

    return InlineKeyboardMarkup(rows) if rows else None


# ============================================================
# SEND
# ============================================================

async def send_file(
    client: Client,
    user_id: int,
    hit: Any,
    cfg: Dict[str, Any],
) -> bool:
    file_id = _get(hit, "file_id")
    if not file_id:
        return False

    caption = build_caption(hit, cfg)
    kb = build_kb(hit, cfg)

    sent = None
    try:
        sent = await client.send_cached_media(
            chat_id=int(user_id),
            file_id=file_id,
            caption=caption,
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
        )
    except FloodWait as e:
        await asyncio.sleep(int(getattr(e, "value", 30) or 30) + 2)
        try:
            sent = await client.send_cached_media(
                chat_id=int(user_id),
                file_id=file_id,
                caption=caption,
                reply_markup=kb,
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            return False
    except UserIsBlocked:
        return False
    except Exception as e:
        logger.exception(f"[PM-DELIVER] send: {e}")
        return False

    if sent is None:
        return False

    try:
        from plugins.admin import stats as S
        S.track_file_sent(1)
    except Exception:
        pass

    # ── Auto-delete with warning ──
    if cfg.get("auto_delete_enabled", False):
        minutes = int(cfg.get("auto_delete_minutes", 10) or 10)
        if minutes > 0:
            asyncio.create_task(
                _auto_delete_with_warning(
                    client, user_id, sent.id, minutes, cfg
                )
            )

    return True


# ============================================================
# AUTO-DELETE + WARNING
# ============================================================

async def _auto_delete_with_warning(
    client: Client,
    chat_id: int,
    msg_id: int,
    minutes: int,
    cfg: Dict[str, Any],
) -> None:
    try:
        # Send warning message
        warn_text = str(cfg.get("auto_delete_warning") or
                        "⚠️ This file will be deleted in {minutes} minutes")
        try:
            warn_text = warn_text.format(minutes=minutes)
        except Exception:
            pass

        warn_msg = None
        try:
            warn_msg = await client.send_message(
                chat_id=int(chat_id),
                text=warn_text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except Exception:
            pass

        # Sleep
        await asyncio.sleep(minutes * 60)

        # Delete both
        try:
            await client.delete_messages(int(chat_id), int(msg_id))
        except Exception:
            pass
        if warn_msg is not None:
            try:
                await client.delete_messages(int(chat_id), warn_msg.id)
            except Exception:
                pass

    except Exception as e:
        logger.debug(f"[PM-DELIVER] auto-delete: {e}")


__all__ = ["build_caption", "build_kb", "send_file"]
