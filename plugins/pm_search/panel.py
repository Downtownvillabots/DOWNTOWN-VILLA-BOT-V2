# ============================================================
# 🏨 DOWNTOWN VILLA — PM SEARCH PANEL (poster + buttons)
# ============================================================

from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional

from pyrogram import Client
from pyrogram.enums import ParseMode
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from utils import fonts as F
from utils import format as FM
from plugins.pm_search import enrich as IE

logger = logging.getLogger(__name__)

DIV = F.DIV


# ============================================================
# SORT
# ============================================================

def sort_hits(hits: List[Any], order: str) -> List[Any]:
    reverse = (order == "big_to_small")
    try:
        return sorted(
            hits,
            key=lambda h: int(
                (h.get("file_size") if isinstance(h, dict)
                 else getattr(h, "file_size", 0)) or 0
            ),
            reverse=reverse,
        )
    except Exception:
        return list(hits)


# ============================================================
# HEADER
# ============================================================

def build_header(
    query: str,
    count: int,
    meta: Optional[Dict[str, Any]],
    cfg: Dict[str, Any],
) -> str:
    lines: List[str] = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"🎬 <b>{F.fb('SEARCH RESULTS')}</b>",
        DIV, "",
    ]

    if meta and cfg.get("show_poster", True):
        title = str(meta.get("title") or query)[:60]
        lines.append(f"🎬 <b>{F.sc(title)}</b>")

        sub: List[str] = []
        if cfg.get("show_year", True) and meta.get("year"):
            sub.append(f"📅 <code>{meta['year']}</code>")
        if cfg.get("show_rating", True) and meta.get("rating"):
            sub.append(f"⭐ <b>{meta['rating']:.1f}</b>")
            if meta.get("votes"):
                sub.append(f"👥 <code>{FM.num(meta['votes'])}</code>")
        if sub:
            lines.append(" · ".join(sub))

        if cfg.get("show_overview", True) and meta.get("overview"):
            lines.append("")
            lines.append(f"<i>{F.sc(meta['overview'][:220])}</i>")
    else:
        lines.append(f"🔍 <code>{query[:60]}</code>")

    lines += [
        "",
        DIV,
        f"📦 {F.sc('files found')} · <b>{FM.num(count)}</b>",
        f"📌 {F.sc('tap a file to receive it')}",
        "",
        f"🕒 <code>{FM.datetime_()}</code>",
    ]
    return "\n".join(lines)


# ============================================================
# FILE BUTTONS
# ============================================================

def file_buttons(
    sid: str,
    hits: List[Any],
    cfg: Dict[str, Any],
    offset: int = 0,
) -> List[List[InlineKeyboardButton]]:
    per_row = max(1, min(3, int(cfg.get("per_row", 2) or 2)))
    rows: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []

    for i, h in enumerate(hits):
        quality = (
            h.get("quality") if isinstance(h, dict)
            else getattr(h, "quality", "")
        )
        file_size = (
            h.get("file_size", 0) if isinstance(h, dict)
            else getattr(h, "file_size", 0)
        )
        q = str(quality or "").upper()
        s = FM.size_short(file_size)
        label = f"📁 {offset + i + 1}"
        if q:
            label += f" · {q}"
        if s:
            label += f" · {s}"
        if len(label) > 60:
            label = label[:57] + "…"
        row.append(InlineKeyboardButton(
            label,
            callback_data=f"pms:get:{sid}:{offset + i}",
        ))
        if len(row) >= per_row:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    return rows


def close_row(sid: str) -> List[InlineKeyboardButton]:
    return [InlineKeyboardButton(
        f"{F.EMO['close']} {F.sc('close')}",
        callback_data=f"pms:close:{sid}",
    )]


# ============================================================
# SEND PANEL
# ============================================================

async def send_panel(
    client: Client,
    user_id: int,
    chat_id: int,
    query: str,
    hits: List[Any],
    sid: str,
    cfg: Dict[str, Any],
    meta: Optional[Dict[str, Any]] = None,
) -> bool:
    try:
        order = str(cfg.get("sort_order", "small_to_big"))
        hits = sort_hits(hits, order)
        max_b = max(1, min(30, int(cfg.get("max_buttons", 15) or 15)))
        shown = hits[:max_b]

        header = build_header(query, len(hits), meta, cfg)
        rows = file_buttons(sid, shown, cfg)
        rows.append(close_row(sid))
        kb = InlineKeyboardMarkup(rows)

        # ── Try poster ──
        poster_path = None
        if meta and cfg.get("show_poster", True):
            poster_path = meta.get("poster")

        if poster_path:
            url = IE.poster_url(poster_path, "w500")
            if url:
                try:
                    await client.send_photo(
                        chat_id=chat_id,
                        photo=url,
                        caption=header[:1024],
                        reply_markup=kb,
                        parse_mode=ParseMode.HTML,
                    )
                    return True
                except Exception as e:
                    logger.debug(f"[PM-PANEL] photo: {e}")

        # ── Fallback to text ──
        await client.send_message(
            chat_id=chat_id,
            text=header[:4000],
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        return True

    except Exception as e:
        logger.exception(f"[PM-PANEL] send: {e}")
        return False


# ============================================================
# SUGGESTIONS
# ============================================================

def suggestion_buttons(
    sid: str,
    items: List[Dict[str, Any]],
) -> List[List[InlineKeyboardButton]]:
    rows: List[List[InlineKeyboardButton]] = []
    for i, s in enumerate(items):
        title = str(s.get("title") or "?")[:34]
        year = s.get("year")
        label = f"🎬 {title}"
        if year:
            label += f" ({year})"
        if len(label) > 60:
            label = label[:57] + "…"
        rows.append([InlineKeyboardButton(
            label,
            callback_data=f"pms:sug:{sid}:{i}",
        )])
    rows.append(close_row(sid))
    return rows


async def send_suggestions(
    client: Client,
    chat_id: int,
    query: str,
    items: List[Dict[str, Any]],
    sid: str,
) -> bool:
    if not items:
        return False

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"🔍 <b>{F.fb('DID YOU MEAN?')}</b>",
        DIV, "",
        f"🔍 <code>{query[:60]}</code>",
        f"📝 {len(items)} {F.sc('suggestions')}",
        "",
        f"📌 {F.sc('tap a title to search files')}",
    ]

    try:
        await client.send_message(
            chat_id=chat_id,
            text="\n".join(lines)[:4000],
            reply_markup=InlineKeyboardMarkup(suggestion_buttons(sid, items)),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        return True
    except Exception as e:
        logger.exception(f"[PM-PANEL] suggest: {e}")
        return False


__all__ = [
    "sort_hits",
    "build_header",
    "file_buttons",
    "send_panel",
    "send_suggestions",
]
