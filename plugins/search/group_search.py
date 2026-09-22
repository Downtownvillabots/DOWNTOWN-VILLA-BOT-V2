# ============================================================
# 🏨 DOWNTOWN VILLA — GROUP SEARCH
# ============================================================
#
# Group text → search → file list → deep link to PM.
#
# FLOW:
#   1. User types in group
#   2. Bot searches DB
#   3. Shows file list with buttons
#   4. Button tap → deep-link to bot PM (?start=file_{sid}_{idx})
#   5. core/start_router handles delivery
#
# NEW USER:
#   Telegram shows "START" button if user never used the bot.
#   Tap → bot opens → file delivered. Zero friction.
#
# ============================================================

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from pyrogram import Client, filters
from pyrogram.enums import ChatType, ParseMode
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from core import config
from utils import fonts as F
from utils import format as FM

logger = logging.getLogger(__name__)


GROUP_COOLDOWN = 3.0
_last_seen: Dict[int, float] = {}


# ============================================================
# GATE — allow only in groups
# ============================================================

GROUP_FILTER = (
    filters.group
    & filters.text
    & ~filters.regex(r"^/")
    & ~filters.regex(r"^sr:")
)


# ============================================================
# HANDLER
# ============================================================

@Client.on_message(GROUP_FILTER, group=-510)
async def group_text_handler(client: Client, message: Message):
    """Group text → search → file list."""
    try:
        if not message.from_user:
            return

        txt = (message.text or "").strip()
        if not txt or len(txt) < 2 or len(txt) > 100:
            return
        if "http://" in txt.lower() or "https://" in txt.lower():
            return

        # Cooldown
        uid = message.from_user.id
        now = time.time()
        if now - _last_seen.get(uid, 0) < GROUP_COOLDOWN:
            return
        _last_seen[uid] = now

        # Show progress
        try:
            status = await message.reply_text("🔎 ꜱᴇᴀʀᴄʜɪɴɢ…")
        except Exception:
            return

        # Run search
        from plugins.search import handlers as H
        hits, complete = await H.quick_search(txt)
        H.track_search_event()

        if not hits:
            if not complete:
                await _edit(status, "\n".join([
                    f"{F.EMO['warn']} ᴏɴᴇ ᴏʀ ᴍᴏʀᴇ ᴅᴀᴛᴀʙᴀꜱᴇꜱ ᴜɴʀᴇᴀᴄʜᴀʙʟᴇ.",
                    f"📌 ᴛʀʏ ᴀɢᴀɪɴ ɪɴ ᴀ ᴍᴏᴍᴇɴᴛ.",
                ]))
                return
            await _no_results(client, message, status, txt)
            return

        # Create a session for the file list
        sid = await _create_session(message, txt, hits)
        if not sid:
            await _edit(status, "❌ ꜱᴇꜱꜱɪᴏɴ ᴇʀʀᴏʀ")
            return

        # Show file list
        await _show_file_list(status, txt, sid, hits)

        try:
            message.stop_propagation()
        except Exception:
            pass

    except Exception as e:
        logger.exception(f"[GROUP-SEARCH] handler: {e}")


# ============================================================
# SESSION CREATION
# ============================================================

async def _create_session(
    message: Message,
    query: str,
    hits: List[Any],
) -> Optional[str]:
    """Create a search session and return its id."""
    try:
        from media_search import sessions as _sess_mod
        from media_search.normalizer import normalize

        candidates = []
        for h in hits[:30]:
            candidates.append({
                "file_id": getattr(h, "file_id", ""),
                "file_unique_id": getattr(h, "file_unique_id", None),
                "file_name": getattr(h, "file_name", None),
                "file_size": getattr(h, "file_size", 0),
                "title": getattr(h, "title", "") or "",
                "year": getattr(h, "year", None),
                "quality": getattr(h, "quality", None),
                "codec": getattr(h, "codec", None),
                "audio_languages": list(
                    getattr(h, "audio_languages", []) or []
                ),
                "subtitle_languages": list(
                    getattr(h, "subtitle_languages", []) or []
                ),
                "has_subtitle": bool(getattr(h, "has_subtitle", False)),
                "type": getattr(h, "type", "movie"),
                "series_title": getattr(h, "series_title", None),
                "season": getattr(h, "season", None),
                "episode": getattr(h, "episode", None),
            })

        session = await _sess_mod.sessions.create(
            user_id=message.from_user.id,
            chat_id=message.chat.id,
            query=query,
            normalized_query=normalize(query),
            mode="movie",
            candidates=candidates,
        )
        return session.session_id if session else None

    except Exception as e:
        logger.exception(f"[GROUP-SEARCH] session: {e}")
        return None


# ============================================================
# FILE LIST RENDER
# ============================================================

async def _show_file_list(
    status: Message,
    query: str,
    sid: str,
    hits: List[Any],
) -> None:
    """Render the file list buttons."""
    try:
        bot_username = ""
        try:
            from core.client import client as C
            if C is not None:
                me = await C.identity()
                bot_username = me.username or ""
        except Exception:
            pass

        # Sort small → big
        sorted_hits = sorted(
            hits[:30],
            key=lambda h: (getattr(h, "file_size", 0) or 0),
        )

        rows: List[List[InlineKeyboardButton]] = []
        shown = sorted_hits[:10]

        for i, h in enumerate(shown):
            size = FM.size_short(getattr(h, "file_size", 0))
            name = str(getattr(h, "file_name", "") or "file")[:32]
            quality = str(getattr(h, "quality", "") or "").upper()
            label = f"📦 {size}"
            if quality:
                label += f" · {quality}"
            label += f" · {name}"
            if len(label) > 58:
                label = label[:55] + "…"

            deep_link = (
                f"https://t.me/{bot_username}?start=file_{sid}_{i}"
                if bot_username else None
            )

            if deep_link:
                rows.append([InlineKeyboardButton(
                    label, url=deep_link,
                )])
            else:
                rows.append([InlineKeyboardButton(
                    label,
                    callback_data=f"sr:file:{sid}:{i}",
                )])

        if len(sorted_hits) > 10:
            rows.append([InlineKeyboardButton(
                f"➕ {len(sorted_hits) - 10} ᴍᴏʀᴇ ʀᴇʟᴇᴀꜱᴇꜱ",
                callback_data=f"sr:more:{sid}",
            )])

        rows.append([InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('close')}",
            callback_data="sr:cancel",
        )])

        text = "\n".join([
            f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
            F.DIV, "",
            f"🎬 <b>{F.sc(query.title()[:50])}</b>",
            f"📦 <b>{len(hits)}</b> ꜰɪʟᴇꜱ · ꜱᴍᴀʟʟ → ʙɪɢ",
            "",
            f"📌 ᴛᴀᴘ ᴀ ꜰɪʟᴇ ᴛᴏ ʀᴇᴄᴇɪᴠᴇ ɪᴛ ɪɴ ᴘᴍ",
        ])

        try:
            await status.edit_text(
                text,
                reply_markup=InlineKeyboardMarkup(rows),
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except Exception as e:
            logger.debug(f"[GROUP-SEARCH] edit: {e}")

    except Exception as e:
        logger.exception(f"[GROUP-SEARCH] show: {e}")


# ============================================================
# NO RESULTS
# ============================================================

async def _no_results(
    client: Client,
    message: Message,
    status: Message,
    query: str,
) -> None:
    """Handle no results — suggestions via shared engine."""
    try:
        from media_search.spell_check import get_suggestions, clean_query
    except Exception:
        await _edit(status, f"❌ ɴᴏ ᴍᴀᴛᴄʜ ꜰᴏʀ <code>{query}</code>")
        return

    cleaned = clean_query(query)
    suggestions: List[Dict[str, Any]] = []
    try:
        suggestions = await get_suggestions(cleaned)
        if not suggestions and cleaned != query:
            suggestions = await get_suggestions(query)
    except Exception as e:
        logger.debug(f"[GROUP-SEARCH] suggest: {e}")

    if not suggestions:
        await _edit(
            status,
            "\n".join([
                f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                F.DIV, "",
                f"❌ ɴᴏ ᴍᴀᴛᴄʜ ꜰᴏʀ <code>{F.sc(query[:50])}</code>",
                "",
                f"📌 ᴘʟᴇᴀꜱᴇ ᴄʜᴇᴄᴋ ꜱᴘᴇʟʟɪɴɢ ᴀɴᴅ ᴛʀʏ ᴀɢᴀɪɴ.",
            ]),
        )
        return

    # Session for suggestions
    sid = await _create_session(
        message, query, []
    )  # empty hits for now
    if not sid:
        await _edit(status, "❌ ꜱᴇꜱꜱɪᴏɴ ᴇʀʀᴏʀ")
        return

    # Store suggestions in session
    try:
        from media_search import sessions as _sess_mod
        await _sess_mod.sessions.update(
            sid, candidates=suggestions
        )
    except Exception:
        pass

    rows: List[List[InlineKeyboardButton]] = []
    for i, s in enumerate(suggestions[:8]):
        title = str(s.get("title", "?"))[:34]
        year = s.get("year")
        label = f"🎬 {title}"
        if year:
            label += f" ({year})"
        rows.append([InlineKeyboardButton(
            label,
            callback_data=f"sr:sug:{sid}:{i}",
        )])

    rows.append([InlineKeyboardButton(
        f"🔍 ᴄʜᴇᴄᴋ ᴏɴ ɢᴏᴏɢʟᴇ",
        url=f"https://www.google.com/search?q={query}",
    )])
    rows.append([InlineKeyboardButton(
        f"{F.EMO['cross']} {F.sc('close')}",
        callback_data="sr:cancel",
    )])

    text = "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"{F.EMO['search']} <b>{F.fb('DID YOU MEAN?')}</b>",
        F.DIV, "",
        f"🔍 <code>{F.sc(query[:50])}</code>",
        f"📝 {len(suggestions)} ꜱᴜɢɢᴇꜱᴛɪᴏɴꜱ",
        "",
        f"ᴘɪᴄᴋ ᴛʜᴇ ᴏɴᴇ ʏᴏᴜ ᴍᴇᴀɴᴛ:",
    ])

    try:
        await status.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(rows),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception:
        pass


# ============================================================
# HELPER
# ============================================================

async def _edit(target, text: str) -> None:
    try:
        await target.edit_text(text, parse_mode=ParseMode.HTML)
    except Exception as e:
        if "not modified" not in str(e).lower():
            logger.debug(f"[GROUP-SEARCH] edit: {e}")


__all__ = ["group_text_handler"]
