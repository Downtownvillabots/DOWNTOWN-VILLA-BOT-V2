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
from core import config

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
    """
    Reply markup for a PM-delivered file.

    Reads `result_buttons` (the current group schema), falling
    back to `delivered_buttons` (legacy PM schema) for safety.
    """
    # Accept both new + legacy key names
    buttons = (
        cfg.get("result_buttons")
        or cfg.get("delivered_buttons")
        or []
    )

    per_row = 2
    for key in ("buttons_per_row", "delivered_buttons_per_row"):
        try:
            v = int(cfg.get(key, 0) or 0)
            if v:
                per_row = v
                break
        except (TypeError, ValueError):
            continue
    per_row = max(1, min(3, per_row))

    rows: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []

    for b in buttons:
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

    # ── Share button ──
    if cfg.get("share_button", True):
        title = _get(hit, "title") or _get(hit, "series_title") or "file"
        try:
            from urllib.parse import quote
            share_target = (
                getattr(config, "UPDATE_CHNL_LNK", None)
                or getattr(config, "BOT_LINK", None)
                or "https://t.me/"
            )
            share_text = quote(str(title), safe="")
            share_url = (
                f"https://t.me/share/url?"
                f"url={quote(share_target, safe='')}&"
                f"text={share_text}"
            )
        except Exception:
            share_url = "https://t.me/"

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
        except UserIsBlocked:
            from services.users import mark_user_blocked
            await mark_user_blocked(user_id)
            return False
        except Exception:
            return False
    except UserIsBlocked:
        from services.users import mark_user_blocked
        await mark_user_blocked(user_id)
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
    # Support nested group settings and PM Search's flat minute settings.
    ad = cfg.get("auto_delete")
    if isinstance(ad, dict):
        enabled = bool(ad.get("bot_messages", False))
        try:
            seconds = int(ad.get("bot_timer", 600) or 0)
        except (TypeError, ValueError):
            seconds = 0
    else:
        enabled = bool(cfg.get("auto_delete_enabled", False))
        try:
            seconds = int(cfg.get("auto_delete_minutes", 10) or 0) * 60
        except (TypeError, ValueError):
            seconds = 0
    if enabled and seconds > 0:
        asyncio.create_task(
            _auto_delete_with_warning(
                client, user_id, sent.id, seconds, cfg
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
    seconds: int,
    cfg: Dict[str, Any],
) -> None:
    """
    Send a warning, wait, then delete the file + the warning.
    seconds — how long until deletion (was: minutes)
    """
    try:
        # Human-friendly time
        if seconds < 60:
            t_str = f"{seconds}s"
        elif seconds < 3600:
            t_str = f"{seconds // 60} min"
        else:
            t_str = f"{seconds // 3600}h"

        # Prefer the group-configurable warning text (if provided)
        warn_text = str(cfg.get("auto_delete_warning") or "")
        if not warn_text:
            warn_text = (
                f"⚠️ <b>This file will be deleted in {t_str}</b>\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "📌 Forward it to Saved Messages or share it now\n"
                "📌 Once deleted, search again"
            )
        else:
            # Support both {minutes} (legacy) and {seconds}/{time}
            try:
                warn_text = warn_text.format(
                    minutes=max(1, seconds // 60),
                    seconds=seconds,
                    time=t_str,
                )
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
        await asyncio.sleep(seconds)

        # Delete file + warning
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
