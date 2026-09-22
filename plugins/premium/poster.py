# ============================================================
# 🏨 DOWNTOWN VILLA — PREMIUM POSTER RENDERER
# ============================================================
#
# Live poster — the persistent UI users see in PM.
#
# Layout:
#   [poster image]
#   🎬 Title (Year)
#   ⭐ Rating
#   📊 YOUR PROGRESS
#   S01 🟩🟩🟩⬛⬛⬛⬛⬛  3/7  🟡
#   S02 🟩🟩🟩🟩🟩🟩🟩⬛  5/7  🟢
#
#   ✅ Delivered: 8/14 (57%)
#   ⏱️ Time left: ~3 hours
#
#   [▶️ Resume S01E04] [📚 Seasons]
#   [🏆 Watch Order]  [📊 Missing]
#   [⭐ Rate]
#
# ============================================================

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from pyrogram.enums import ParseMode
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from utils import fonts as F
from utils import format as FM
from utils import progress as P

logger = logging.getLogger(__name__)


# ============================================================
# TEXT BUILDER
# ============================================================

def build_text(session: Dict[str, Any]) -> str:
    """Build the main poster caption."""
    from plugins.premium import state as S

    title = session.get("series_title") or "?"
    tmdb_id = session.get("tmdb_id")
    language = session.get("language") or ""
    p = S.compute_progress(session)
    seasons_raw = session.get("seasons") or {}
    seasons_ordered = sorted(int(k) for k in seasons_raw.keys() if k.isdigit())

    is_complete = (
        p["total_eps"] > 0
        and p["total_watched"] >= p["total_eps"]
    )

    lines: List[str] = []

    # ─── Header ───
    lines.append(f"{F.EMO['film']} <b>{F.sc(str(title)[:60])}</b>")
    if language:
        lines.append(f"{F.EMO['sound']} {F.sc(language)}")
    if is_complete:
        lines.append(f"{F.EMO['trophy']} <b>{F.fb('SERIES COMPLETE')}</b>")

    lines.append("")

    # ─── Per-season bars ───
    if seasons_ordered:
        lines.append(f"{F.EMO['chart']} <b>{F.fb('YOUR PROGRESS')}</b>")
        lines.append("")

        for sn in seasons_ordered:
            s_data = seasons_raw.get(str(sn)) or {}
            watched = len(s_data.get("watched") or [])
            total = int(s_data.get("total_eps", 0) or 0)

            if total == 0:
                bar = P.bar(0, "indexing", width=10, show_percent=False)
                icon = "⚪"
            else:
                pct = watched / total * 100
                bar = P.bar(pct, "indexing", width=10, show_percent=False)
                if watched >= total:
                    icon = "🟢"
                elif watched > 0:
                    icon = "🟡"
                else:
                    icon = "⚪"

            lines.append(
                f"S{sn:02d} {bar} "
                f"<b>{watched:02d}/{total:02d}</b> {icon}"
            )

        lines.append("")

        # ─── Overall ───
        lines.append(F.DIV_S)
        lines.append(
            f"{F.EMO['check']} {F.sc('delivered')} · "
            f"<b>{p['total_watched']}/{p['total_eps']}</b> "
            f"<code>({p['pct']}%)</code>"
        )

        if is_complete:
            started = session.get("started_at", 0)
            finished = session.get("completed_at", 0) or time.time()
            total_hours = int(p["total_eps"] * 22 / 60)
            lines.append(
                f"{F.EMO['clock']} {F.sc('total')} · "
                f"<b>~{total_hours} hours</b>"
            )
            if started:
                lines.append(
                    f"{F.EMO['cal']} {F.sc('started')} · "
                    f"<code>{FM.ago(started)}</code>"
                )
            if finished:
                lines.append(
                    f"{F.EMO['cal']} {F.sc('finished')} · "
                    f"<code>{FM.ago(finished)}</code>"
                )
            lines.append("")
            lines.append(f"{F.EMO['party']} <b>{F.fb('CONGRATULATIONS!')}</b>")
        else:
            remaining = p["total_eps"] - p["total_watched"]
            hours_left = remaining * 22 / 60
            lines.append(
                f"{F.EMO['clock']} {F.sc('time left')} · "
                f"<b>~{int(hours_left)} hours</b>"
            )

    lines.append("")
    lines.append(f"<code>{FM.datetime_()}</code>")

    return "\n".join(lines)


# ============================================================
# KEYBOARD BUILDER
# ============================================================

def build_keyboard(session: Dict[str, Any], slug: str) -> Optional[InlineKeyboardMarkup]:
    from plugins.premium import state as S

    next_ep = S.find_next_episode(session)
    complete = S.is_series_complete(session)
    has_lang = bool(session.get("language"))
    has_seasons = bool(session.get("seasons"))
    rated = session.get("rated", False)

    if not has_lang and not has_seasons:
        return None

    rows: List[List[InlineKeyboardButton]] = []

    # Complete → mark + rate
    if complete:
        if not rated:
            rows.append([InlineKeyboardButton(
                f"{F.EMO['star']} {F.sc('rate series')}",
                callback_data=f"pw:rate_menu:{slug}",
            )])
        rows.append([InlineKeyboardButton(
            f"{F.EMO['trophy']} {F.sc('mark complete')}",
            callback_data=f"pw:complete:{slug}",
        )])
    elif next_ep:
        sn, ep = next_ep
        rows.append([InlineKeyboardButton(
            f"{F.EMO['play']} {F.sc('resume')} S{sn:02d}E{ep:02d}",
            callback_data=f"pw:play:{slug}:{sn}:{ep}",
        )])

    if has_seasons:
        rows.append([
            InlineKeyboardButton(
                f"{F.EMO['tv']} {F.sc('seasons')}",
                callback_data=f"pw:seasons:{slug}",
            ),
            InlineKeyboardButton(
                f"{F.EMO['book']} {F.sc('watch order')}",
                callback_data=f"pw:wo:{slug}",
            ),
        ])
        if not complete:
            rows.append([InlineKeyboardButton(
                f"{F.EMO['chart']} {F.sc('missing episodes')}",
                callback_data=f"pw:missing:{slug}",
            )])

    rows.append([InlineKeyboardButton(
        f"{F.EMO['crown']} {F.sc('premium menu')}",
        callback_data="pw:menu",
    )])
    rows.append([InlineKeyboardButton(
        f"{F.EMO['cross']} {F.sc('close')}",
        callback_data=f"pw:close_session",
    )])

    return InlineKeyboardMarkup(rows)


# ============================================================
# POSTER SENDER (initial)
# ============================================================

async def send_poster(
    client,
    user_id: int,
    session: Dict[str, Any],
    slug: str,
) -> Optional[int]:
    """Send a new poster (with image if available)."""
    try:
        text = build_text(session)
        kb = build_keyboard(session, slug)
        poster_path = session.get("poster")

        msg = None
        if poster_path:
            poster_url = (
                poster_path if poster_path.startswith("http")
                else f"https://image.tmdb.org/t/p/w500{poster_path}"
            )
            try:
                msg = await client.send_photo(
                    chat_id=user_id,
                    photo=poster_url,
                    caption=text,
                    reply_markup=kb,
                    parse_mode=ParseMode.HTML,
                )
            except Exception as e:
                logger.debug(f"[PREM-POSTER] photo: {e}")

        if not msg:
            msg = await client.send_message(
                chat_id=user_id,
                text=text,
                reply_markup=kb,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        return msg.id if msg else None
    except Exception as e:
        logger.exception(f"[PREM-POSTER] send: {e}")
        return None


# ============================================================
# LIVE UPDATE (edit existing poster)
# ============================================================

async def render_update(
    client,
    session: Dict[str, Any],
) -> bool:
    """Edit the existing poster with new progress."""
    try:
        uid = session.get("user_id")
        chat_id = session.get("poster_chat_id") or uid
        msg_id = session.get("poster_msg_id")
        slug = session.get("series_slug") or ""

        if not msg_id:
            return False

        text = build_text(session)
        kb = build_keyboard(session, slug)
        if kb is None:
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"{F.EMO['cross']} {F.sc('close')}",
                    callback_data="pw:close_session",
                ),
            ]])

        # Try caption first (photo message)
        try:
            await client.edit_message_caption(
                chat_id=chat_id,
                message_id=msg_id,
                caption=text,
                reply_markup=kb,
                parse_mode=ParseMode.HTML,
            )
            return True
        except Exception as e:
            if "not modified" in str(e).lower():
                return True
            logger.debug(f"[PREM-POSTER] caption edit: {e}")

        # Fallback: text message
        try:
            await client.edit_message_text(
                chat_id=chat_id,
                message_id=msg_id,
                text=text,
                reply_markup=kb,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
            return True
        except Exception as e:
            if "not modified" in str(e).lower():
                return True
            logger.debug(f"[PREM-POSTER] text edit: {e}")
            return False
    except Exception as e:
        logger.exception(f"[PREM-POSTER] update: {e}")
        return False


# ============================================================
# PUBLIC
# ============================================================

__all__ = ["build_text", "build_keyboard", "send_poster", "render_update"]
