# ============================================================
# 🏨 DOWNTOWN VILLA — BROADCAST TEMPLATES
# ============================================================

from __future__ import annotations
import logging
import re
from typing import Any, Dict, List, Optional

from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

logger = logging.getLogger(__name__)


# ─── CAPTION CLEANER ───
def clean_caption(text: str) -> str:
    """
    Remove links, @mentions, t.me URLs, JOIN lines.
    Keeps plain text + emojis.
    """
    if not text:
        return ""

    text = re.sub(r"https?://\S+", "", text)
    text = re.sub(r"\bt\.me/\S+", "", text)
    text = re.sub(r"\bjoinchat/\S+", "", text)
    text = re.sub(r"\btelegram\.me/\S+", "", text)
    text = re.sub(r"\btelegram\.dog/\S+", "", text)
    text = re.sub(r"@[A-Za-z0-9_]{3,}", "", text)
    text = re.sub(
        r"(?im)^\s*(join|subscribe|click here|join now|join us)"
        r"\s*[:.\-]?\s*.*$",
        "", text,
    )
    text = re.sub(r"\(\s*\)", "", text)
    text = re.sub(r"\[\s*\]", "", text)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    text = "\n".join(line.strip() for line in text.splitlines())
    return text.strip()


def _human_size(size) -> str:
    try:
        s = float(size or 0)
    except (TypeError, ValueError):
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while s >= 1024 and i < len(units) - 1:
        s /= 1024.0
        i += 1
    return f"{s:.2f} {units[i]}"


def build_caption(message, template: str) -> str:
    """Render a caption and clean it."""
    try:
        file_name = "file"
        file_size_str = "0 B"
        file_caption = message.caption or ""

        for attr in ("video", "document", "audio", "photo", "animation"):
            m = getattr(message, attr, None)
            if m:
                file_name = (
                    getattr(m, "file_name", None)
                    or file_caption[:80]
                    or "file"
                )
                size = getattr(m, "file_size", 0) or 0
                file_size_str = _human_size(size)
                break

        year = ""
        mm = re.search(r"\b(19[3-9]\d|20[0-4]\d)\b", file_name)
        if mm:
            year = mm.group(1)

        rendered = template.format(
            file_name=file_name[:100],
            file_size=file_size_str,
            rating="—",
            year=year or "—",
            file_caption=clean_caption(file_caption)[:200]
            if file_caption else "—",
        )
        return clean_caption(rendered)

    except Exception as e:
        logger.warning(f"[BC-TPL] build_caption: {e}")
        return template


def build_buttons_kb(
    buttons: List[Dict[str, Any]]
) -> Optional[InlineKeyboardMarkup]:
    if not buttons:
        return None
    rows: List[List[InlineKeyboardButton]] = []
    for b in buttons:
        name = (b.get("name") or "").strip()
        url = (b.get("url") or "").strip()
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
        rows.append([InlineKeyboardButton(name[:60], url=url)])
    return InlineKeyboardMarkup(rows) if rows else None


# ─── EFFECTIVE (per-channel fallback to global) ───
async def effective_caption(channel: Optional[Dict[str, Any]]) -> str:
    from plugins.broadcast.database import get_global_caption
    if channel is None or channel.get("caption") is None:
        return await get_global_caption()
    return channel["caption"]


async def effective_buttons(
    channel: Optional[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    from plugins.broadcast.database import get_global_buttons
    if channel is None or channel.get("buttons") is None:
        return await get_global_buttons()
    return list(channel["buttons"])


__all__ = [
    "clean_caption", "build_caption", "build_buttons_kb",
    "effective_caption", "effective_buttons",
]
