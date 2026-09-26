# ============================================================
# 🏨 DOWNTOWN VILLA — OTT NOTIFY + LOOPS
# ============================================================
#
# Runs:
#   • Weekly post loop (Monday 10 AM IST)
#   • File checker (00-06 + 12-18 IST)
#   • Pending auto-delete loop
#   • Hype loop (send 24h-before message)
#
# ============================================================

from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from pyrogram import Client
from pyrogram.enums import ParseMode
from pyrogram.errors import FloodWait, UserIsBlocked
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from core import config
from plugins.ott import state as S
from plugins.ott import tmdb as T
from plugins.ott import features as FT
from utils import fonts as F
from utils import format as FM

logger = logging.getLogger(__name__)

# ── Windows ──
CHECK_WINDOWS = [(0, 6), (12, 18)]
CHECK_INTERVAL = 30 * 60
WEEKLY_DAY = 0
WEEKLY_HOUR = 10
PENDING_INTERVAL = 60

# ── Hype window ──
HYPE_HOUR = 20         # 8 PM IST — daily hype check


# ============================================================
# HELPERS
# ============================================================

def _in_check_window() -> bool:
    h = datetime.now(S.IST).hour
    for start, end in CHECK_WINDOWS:
        if start <= h < end:
            return True
    return False


async def _get_primary_channel() -> Optional[int]:
    try:
        from plugins.broadcast import channels as CH
        channels = await CH.list_channels()
        for c in channels:
            if c.get("primary") and c.get("enabled", True):
                return int(c["chat_id"])
        for c in channels:
            if c.get("enabled", True):
                return int(c["chat_id"])
    except Exception:
        pass
    return None


# ============================================================
# WEEKLY POST LOOP
# ============================================================

_last_post_key: Optional[str] = None


async def _post_weekly(client: Client, force: bool = False) -> bool:
    global _last_post_key

    if not force and _last_post_key == S.week_key():
        return False

    ch = await _get_primary_channel()
    if not ch:
        logger.warning("[OTT] no primary channel for weekly post")
        return False

    cfg = await S.get_cfg()
    if not cfg.get("weekly_enabled", True) and not force:
        return False

    by_day = await T.fetch_weekly()
    days = [[dict(m) for m in by_day.get(i, [])] for i in range(7)]
    await S.save_week(S.week_key(), days, posted=True)

    counts = [len(by_day.get(i, [])) for i in range(7)]
    text = _build_weekly_text(S.week_key(), by_day, counts)
    kb = _build_weekly_kb(counts)

    try:
        await client.send_message(
            chat_id=ch,
            text=text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        _last_post_key = S.week_key()
        logger.info(f"[OTT] weekly posted: {S.week_key()}")
        return True
    except Exception as e:
        logger.warning(f"[OTT] weekly post: {e}")
        return False


async def _weekly_loop(client: Client) -> None:
    await asyncio.sleep(30)
    last_trigger: Optional[str] = None
    while True:
        try:
            now = datetime.now(S.IST)
            today = now.strftime("%Y-%m-%d")
            if (
                now.weekday() == WEEKLY_DAY
                and now.hour == WEEKLY_HOUR
                and now.minute < 5
                and last_trigger != today
            ):
                last_trigger = today
                await _post_weekly(client)
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.debug(f"[OTT] weekly loop: {e}")
        await asyncio.sleep(60)


# ============================================================
# FILE CHECKER LOOP
# ============================================================

async def _file_checker(client: Client) -> None:
    await asyncio.sleep(90)
    while True:
        try:
            if not _in_check_window():
                await asyncio.sleep(CHECK_INTERVAL)
                continue

            pending = await S.pending_movies_to_notify(limit=30)
            for item in pending:
                tmdb_id = item.get("_id")
                if not tmdb_id:
                    continue
                await _notify_movie_subscribers(client, tmdb_id)

        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.warning(f"[OTT] checker: {e}")
        await asyncio.sleep(CHECK_INTERVAL)


async def _notify_movie_subscribers(client: Client, tmdb_id: int) -> None:
    """Notify every pending subscriber for a movie."""
    subs = await S.subs_for_movie(tmdb_id, limit=5000)
    if not subs:
        return

    movie = await S.get_movie(tmdb_id)
    if not movie:
        return

    cfg = await S.get_cfg()
    notify_ttl = int(cfg.get("notify_ttl_hours", 12)) * 3600
    share_enabled = bool(cfg.get("share_button", True))

    # Build caption
    text = _build_notify_text(movie)
    kb = _build_notify_kb(movie, share_enabled)

    sent = 0
    failed = 0

    for sub in subs:
        uid = int(sub.get("user_id", 0))
        if not uid:
            continue
        try:
            msg = None
            poster = T.poster_url(movie.get("poster_path"), "w500")
            if poster:
                try:
                    msg = await client.send_photo(
                        chat_id=uid,
                        photo=poster,
                        caption=text,
                        reply_markup=kb,
                        parse_mode=ParseMode.HTML,
                    )
                except Exception:
                    pass
            if not msg:
                msg = await client.send_message(
                    chat_id=uid,
                    text=text,
                    reply_markup=kb,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
            sent += 1
            if msg and notify_ttl > 0:
                await S.pending_add(uid, msg.id, notify_ttl)
            await S.sent_log(uid, tmdb_id, mode="notify")
            await asyncio.sleep(0.05)
        except FloodWait as e:
            await asyncio.sleep(e.value + 2)
        except UserIsBlocked:
            failed += 1
        except Exception as e:
            logger.debug(f"[OTT] notify {uid}: {e}")
            failed += 1

    await S.mark_subs_notified(tmdb_id)
    logger.info(f"[OTT] notified {sent} for '{movie.get('title')}'")


# ============================================================
# HYPE LOOP (24h pre-release)
# ============================================================

async def _hype_loop(client: Client) -> None:
    await asyncio.sleep(120)
    last_sent_date: Optional[str] = None
    while True:
        try:
            now = datetime.now(S.IST)
            today = now.strftime("%Y-%m-%d")

            if now.hour == HYPE_HOUR and last_sent_date != today:
                last_sent_date = today
                cfg = await S.get_cfg()
                if cfg.get("hype_enabled", True):
                    await _send_hype(client)

        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.debug(f"[OTT] hype loop: {e}")
        await asyncio.sleep(60 * 30)


async def _send_hype(client: Client) -> None:
    """Send hype messages for movies releasing tomorrow."""
    tomorrow = await FT.get_releasing_tomorrow()
    if not tomorrow:
        return

    # Send to all subscribers of these movies
    for movie in tomorrow:
        tmdb_id = movie.get("tmdb_id")
        if not tmdb_id:
            continue
        subs = await S.subs_for_movie(tmdb_id, limit=5000)
        for sub in subs:
            uid = int(sub.get("user_id", 0))
            if not uid:
                continue
            try:
                text = "\n".join([
                    f"{F.EMO['fire']} <b>{F.fb('RELEASING TOMORROW!')}</b>",
                    F.DIV, "",
                    f"🎬 <b>{F.sc(str(movie.get('title'))[:50])}</b>",
                    f"📅 <code>{movie.get('release_date')}</code>",
                    "",
                    f"🔔 {F.sc('be ready — we will notify you')}",
                ])
                poster = T.poster_url(movie.get("poster_path"))

                sent = False
                if poster:
                    try:
                        await client.send_photo(
                            chat_id=uid, photo=poster,
                            caption=text,
                            parse_mode=ParseMode.HTML,
                        )
                        sent = True
                    except FloodWait as e:
                        wait = int(getattr(e, "value", 30) or 30)
                        logger.warning(f"[OTT] hype flood {wait}s")
                        await asyncio.sleep(wait + 2)
                    except Exception:
                        pass

                if not sent:
                    await client.send_message(
                        chat_id=uid, text=text,
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=True,
                    )

                await asyncio.sleep(0.05)
            except FloodWait as e:
                wait = int(getattr(e, "value", 30) or 30)
                logger.warning(f"[OTT] hype text flood {wait}s")
                await asyncio.sleep(wait + 2)
            except UserIsBlocked:
                continue
            except Exception:
                continue

# ============================================================
# PENDING AUTO-DELETE LOOP
# ============================================================

async def _pending_loop(client: Client) -> None:
    await asyncio.sleep(180)
    while True:
        try:
            due = await S.pending_due(limit=200)
            for doc in due:
                cid = doc.get("chat_id")
                mid = doc.get("message_id")
                if cid and mid:
                    try:
                        await client.delete_messages(int(cid), int(mid))
                    except Exception:
                        pass
                await S.pending_remove(doc.get("_id"))
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.debug(f"[OTT] pending: {e}")
        await asyncio.sleep(PENDING_INTERVAL)


# ============================================================
# BOOT ALL LOOPS
# ============================================================

_loops_started = False


def ensure_loops(client: Client) -> None:
    global _loops_started
    if _loops_started:
        return
    _loops_started = True

    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_weekly_loop(client))
        loop.create_task(_file_checker(client))
        loop.create_task(_hype_loop(client))
        loop.create_task(_pending_loop(client))
        logger.info("[OTT] all loops started")
    except RuntimeError:
        pass


# ============================================================
# RENDERERS (shared)
# ============================================================

def _build_weekly_text(
    wk: str,
    by_day: Dict[int, List[Dict[str, Any]]],
    counts: List[int],
) -> str:
    days_short = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    mon = S.day_date(0).strftime("%d %b")
    sun = S.day_date(6).strftime("%d %b %Y")
    total = sum(counts)

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"{F.EMO['cal']} <b>{F.fb('WEEKLY OTT RELEASES')}</b>",
        F.DIV, "",
        f"🗓️ <code>{mon} → {sun}</code>",
        f"🎬 {F.sc('total')} · <b>{total}</b> {F.sc('releases')}",
        "",
        F.DIV_S, "",
        f"📌 {F.sc('tap a day to see movies')}",
        f"📌 {F.sc('tap any movie for full details')}",
        "",
        F.DIV_S,
    ]

    for i in range(7):
        cnt = counts[i]
        if cnt == 0:
            lines.append(f"📅 {days_short[i]} · —")
        else:
            lines.append(
                f"📅 <b>{days_short[i]}</b> · "
                f"<code>{cnt}</code>"
            )

    lines.append("")
    lines.append(f"🆔 <code>{wk}</code>")
    return "\n".join(lines)


def _build_weekly_kb(counts: List[int]) -> InlineKeyboardMarkup:
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    rows = []
    row = []
    for i in range(7):
        label = f"{days[i]}"
        if counts[i] > 0:
            label += f" ({counts[i]})"
        row.append(InlineKeyboardButton(
            label,
            callback_data=f"ott:day:{i}",
        ))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    rows.append([InlineKeyboardButton(
        f"🔥 {F.sc('trending')}",
        callback_data="ott:trending",
    )])
    rows.append([InlineKeyboardButton(
        f"🔔 {F.sc('my notifications')}",
        callback_data="ott:mysubs",
    )])
    rows.append([InlineKeyboardButton(
        f"{F.EMO['cross']} {F.sc('close')}",
        callback_data="ott:close",
    )])
    return InlineKeyboardMarkup(rows)


def _build_notify_text(movie: Dict[str, Any]) -> str:
    title = movie.get("title") or "?"
    year = (movie.get("release_date") or "")[:4]
    rating = movie.get("vote_average") or 0
    provider = movie.get("provider") or "—"
    overview = (movie.get("overview") or "")[:300]
    rel_date = movie.get("release_date") or "—"

    lines = [
        f"{F.EMO['party']} <b>{F.fb('NOW AVAILABLE!')}</b>",
        F.DIV, "",
        f"🎬 <b>{F.sc(str(title)[:60])}</b> ({year})",
        f"⭐ {rating:.1f} · 📺 {F.sc(provider)}",
        f"📅 <code>{rel_date}</code>",
    ]
    if overview:
        lines += ["", f"<i>{F.sc(overview)}</i>"]
    return "\n".join(lines)


def _build_notify_kb(movie: Dict[str, Any], share: bool = True) -> InlineKeyboardMarkup:
    tmdb_id = movie.get("tmdb_id")
    rows = [[InlineKeyboardButton(
        f"{F.EMO['send']} {F.sc('get file')}",
        callback_data=f"ott:getfile:{tmdb_id}",
    )]]
    if share:
        rows.append([InlineKeyboardButton(
            f"{F.EMO['send']} {F.sc('share')}",
            callback_data=f"ott:share:{tmdb_id}",
        )])
    rows.append([InlineKeyboardButton(
        f"{F.EMO['cross']} {F.sc('close')}",
        callback_data="ott:close",
    )])
    return InlineKeyboardMarkup(rows)


__all__ = ["ensure_loops", "_build_weekly_text", "_build_weekly_kb"]
