# ============================================================
# 🏨 DOWNTOWN VILLA — OTT WATCHER (loops + notify)
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

from plugins.broadcast.config import fb, sc, DIV, DIV2, ADMINS
from plugins.ott import database as DB
from plugins.ott.tmdb import fetch_weekly_multi_lang, poster_url
from plugins.ott.config import (
    CHECK_WINDOWS, CHECK_INTERVAL_SEC, FILE_CHECK_LIMIT,
    WEEKLY_DAY, WEEKLY_HOUR, WEEKLY_MINUTE_WINDOW,
    HYPE_HOUR, PENDING_SCAN_INTERVAL,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# WEEKLY LOOP → admin PM
# ═══════════════════════════════════════════════════════════

_last_weekly: Optional[str] = None


async def _do_weekly_post(client: Client, force: bool = False) -> bool:
    global _last_weekly
    if not force and _last_weekly == DB.week_key():
        return False

    cfg = await DB.get_cfg()
    if not cfg.get("weekly_enabled", True) and not force:
        return False

    by_day = await fetch_weekly_multi_lang(
        region=cfg.get("region", "IN"),
        languages=cfg.get("languages") or [],
        min_vote=int(cfg.get("min_vote_count", 0)),
    )
    days = [[dict(m) for m in by_day.get(i, [])] for i in range(7)]
    await DB.save_week(DB.week_key(), days, posted=True)

    counts = [len(by_day.get(i, [])) for i in range(7)]
    total = sum(counts)
    mon = DB.day_date(0).strftime("%d %b")
    sun = DB.day_date(6).strftime("%d %b %Y")

    # Group language counts
    lang_counts: Dict[str, int] = {}
    for d in days:
        for m in d:
            code = (m.get("original_language") or "").upper()
            if code:
                lang_counts[code] = lang_counts.get(code, 0) + 1

    day_names = ["Monday", "Tuesday", "Wednesday", "Thursday",
                 "Friday", "Saturday", "Sunday"]

    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📅 <b>{fb('WEEKLY OTT UPDATE')}</b>",
        DIV, "",
        f"🗓️ <code>{mon} → {sun}</code>",
        f"🎬 {sc('total releases')} · <b>{total}</b>",
        "", DIV2,
        f"🌐 <b>{sc('BY LANGUAGE')}</b>",
    ]
    for code, n in sorted(lang_counts.items(), key=lambda x: -x[1])[:8]:
        lines.append(f"• <code>{code}</code> · <b>{n}</b>")

    lines += ["", DIV2, f"📌 <b>{sc('BY DAY')}</b>", ""]
    for i in range(7):
        day_date = DB.day_date(i)
        lines.append(
            f"📅 <b>{day_names[i]}</b> · "
            f"<code>{day_date.strftime('%d %b')}</code> · "
            f"<b>{counts[i]}</b>"
        )
        # Show top 3 per day
        for m in (days[i][:3] if i < len(days) else []):
            title = str(m.get("title", "?"))[:40]
            lines.append(f"   🎬 {sc(title)}")
        if counts[i] > 3:
            lines.append(f"   <i>… +{counts[i] - 3} more</i>")

    lines += [
        "", DIV2,
        f"📌 {sc('open /admin → 📅 OTT to broadcast')}",
    ]

    target = int(cfg.get("weekly_target_admin") or 0)
    if not target:
        target = int(ADMINS[0]) if ADMINS else 0
    if not target:
        logger.warning("[OTT-WK] no admin target")
        return False

    try:
        await client.send_message(
            chat_id=target, text="\n".join(lines),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        _last_weekly = DB.week_key()
        logger.info(f"[OTT-WK] posted to admin {target}")
        return True
    except Exception as e:
        logger.warning(f"[OTT-WK] send: {e}")
        return False

async def weekly_loop(client: Client) -> None:
    await asyncio.sleep(30)
    last_trigger: Optional[str] = None
    while True:
        try:
            now = datetime.now(DB.IST)
            today = now.strftime("%Y-%m-%d")
            if (now.weekday() == WEEKLY_DAY
                    and now.hour == WEEKLY_HOUR
                    and now.minute < WEEKLY_MINUTE_WINDOW
                    and last_trigger != today):
                last_trigger = today
                await _do_weekly_post(client)
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.debug(f"[OTT-WK] loop: {e}")
        await asyncio.sleep(60)


# ═══════════════════════════════════════════════════════════
# FILE CHECKER
# ═══════════════════════════════════════════════════════════

def _in_window() -> bool:
    h = datetime.now(DB.IST).hour
    for start, end in CHECK_WINDOWS:
        if start > end:
            if h >= start or h < end:
                return True
        else:
            if start <= h < end:
                return True
    return False


async def file_checker(client: Client) -> None:
    await asyncio.sleep(90)
    while True:
        try:
            if not _in_window():
                await asyncio.sleep(CHECK_INTERVAL_SEC)
                continue
            await _scan_latest_files(client)
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.warning(f"[OTT-FC] {e}")
        await asyncio.sleep(CHECK_INTERVAL_SEC)


async def _scan_latest_files(client: Client) -> None:
    pending = await DB.pending_movies_to_notify(limit=100)
    if not pending:
        return

    files = await _latest_files()
    if not files:
        return

    pending_map: Dict[str, Dict[str, Any]] = {}
    for p in pending:
        t = (p.get("title") or "").lower().strip()
        if t:
            pending_map[t] = p

    for f in files:
        name = (f.get("title") or f.get("file_name") or "").lower()
        if not name:
            continue
        for pt, pdata in pending_map.items():
            if pt and (pt[:20] in name or name[:20] in pt):
                tmdb_id = pdata.get("_id")
                if tmdb_id:
                    await _notify_subscribers(client, tmdb_id)
                break


async def _latest_files(limit: int = 100) -> List[Dict[str, Any]]:
    try:
        from database import db_registry
        db = db_registry.get_media_db(0) or db_registry.get_user_db()
        if db is None:
            return []
        names = await db.list_collection_names()
        for coll in ("media_files", "files", "catalog", "indexed_files"):
            if coll not in names:
                continue
            cur = db[coll].find(
                {}, {"title": 1, "file_name": 1, "year": 1, "added_at": 1}
            ).sort("added_at", -1).limit(limit)
            return await cur.to_list(length=limit)
    except Exception as e:
        logger.debug(f"[OTT-FC] files: {e}")
    return []


async def _notify_subscribers(client: Client, tmdb_id: int) -> None:
    subs = await DB.subs_for_movie(tmdb_id, only_pending=True, limit=5000)
    if not subs:
        return

    movie = await DB.get_movie(tmdb_id)
    if not movie:
        return

    cfg = await DB.get_cfg()
    ttl_secs = int(cfg.get("notify_ttl_hours", 12)) * 3600

    title = movie.get("title") or "?"
    year = (movie.get("release_date") or "")[:4]
    rating = movie.get("vote_average") or 0
    lang = (movie.get("original_language") or "").upper()
    provider = movie.get("provider") or "—"

    caption = "\n".join([
        f"🎉 <b>{fb('NOW AVAILABLE!')}</b>",
        DIV, "",
        f"🎬 <b>{sc(str(title)[:60])}</b> ({year})",
        f"⭐ <code>{rating:.1f}/10</code> · 🌐 <code>{lang or '—'}</code>",
        f"📺 <code>{sc(provider)}</code>",
        "", DIV2,
        f"✅ {sc('the file is now available')}",
        f"📌 {sc('tap Get Files to choose quality')}",
    ])
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"📥 {sc('Get Files')}",
            callback_data=f"ott:files:{tmdb_id}:0")],
        [InlineKeyboardButton(
            f"❌ {sc('Close')}",
            callback_data="ott:close")],
    ])
    poster = poster_url(movie.get("poster_path"), "w500")

    sent = failed = 0
    for sub in subs:
        uid = int(sub.get("user_id", 0))
        if not uid:
            continue
        try:
            msg = None
            if poster:
                try:
                    msg = await client.send_photo(
                        chat_id=uid, photo=poster,
                        caption=caption, reply_markup=kb,
                        parse_mode=ParseMode.HTML,
                    )
                except Exception:
                    pass
            if msg is None:
                msg = await client.send_message(
                    chat_id=uid, text=caption, reply_markup=kb,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
            sent += 1
            if msg and ttl_secs > 0:
                await DB.pending_add(uid, msg.id, ttl_secs)
            await DB.sent_log(uid, tmdb_id, mode="now_available")
            await asyncio.sleep(0.05)
        except FloodWait as e:
            await asyncio.sleep(int(e.value) + 2)
        except UserIsBlocked:
            failed += 1
        except Exception:
            failed += 1

    await DB.mark_subs_notified(tmdb_id)

    # Refresh admin channel post
    try:
        from plugins.ott.channel_flow import refresh_admin_post
        await refresh_admin_post(client, tmdb_id)
    except Exception:
        pass

    logger.info(f"[OTT-FC] now-available sent {sent} for '{title}'")


# ═══════════════════════════════════════════════════════════
# HYPE LOOP
# ═══════════════════════════════════════════════════════════

async def hype_loop(client: Client) -> None:
    await asyncio.sleep(120)
    last_sent: Optional[str] = None
    while True:
        try:
            now = datetime.now(DB.IST)
            today = now.strftime("%Y-%m-%d")
            if now.hour == HYPE_HOUR and last_sent != today:
                last_sent = today
                cfg = await DB.get_cfg()
                if cfg.get("hype_enabled", True):
                    await _send_hype(client)
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.debug(f"[OTT-HYPE] {e}")
        await asyncio.sleep(60 * 30)


async def _send_hype(client: Client) -> None:
    wk = DB.week_key()
    w = await DB.get_week(wk)
    if not w:
        return
    tomorrow = (datetime.now(DB.IST) + timedelta(days=1)).strftime("%Y-%m-%d")
    hyped: List[Dict[str, Any]] = []
    for d in (w.get("days") or []):
        for m in d:
            if m.get("release_date") == tomorrow:
                hyped.append(m)

    for movie in hyped:
        tmdb_id = movie.get("tmdb_id")
        if not tmdb_id:
            continue
        subs = await DB.subs_for_movie(tmdb_id, limit=5000)
        caption = "\n".join([
            f"🔥 <b>{fb('RELEASING TOMORROW!')}</b>",
            DIV, "",
            f"🎬 <b>{sc(str(movie.get('title'))[:50])}</b>",
            f"📅 <code>{movie.get('release_date')}</code>",
            "", f"🔔 {sc('be ready — we will notify you')}",
        ])
        poster = poster_url(movie.get("poster_path"))
        for sub in subs:
            uid = int(sub.get("user_id", 0))
            if not uid:
                continue
            try:
                if poster:
                    try:
                        await client.send_photo(
                            chat_id=uid, photo=poster,
                            caption=caption, parse_mode=ParseMode.HTML)
                        await asyncio.sleep(0.05)
                        continue
                    except Exception:
                        pass
                await client.send_message(
                    chat_id=uid, text=caption,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True)
                await asyncio.sleep(0.05)
            except UserIsBlocked:
                continue
            except Exception:
                continue


# ═══════════════════════════════════════════════════════════
# PENDING AUTO-DELETE LOOP
# ═══════════════════════════════════════════════════════════

async def pending_loop(client: Client) -> None:
    await asyncio.sleep(180)
    while True:
        try:
            due = await DB.pending_due(limit=200)
            for doc in due:
                cid = doc.get("chat_id")
                mid = doc.get("message_id")
                if cid and mid:
                    try:
                        await client.delete_messages(int(cid), int(mid))
                    except Exception:
                        pass
                await DB.pending_remove(doc.get("_id"))
        except asyncio.CancelledError:
            return
        except Exception:
            pass
        await asyncio.sleep(PENDING_SCAN_INTERVAL)


# ═══════════════════════════════════════════════════════════
# BOOT
# ═══════════════════════════════════════════════════════════

_loops_started = False


def ensure_loops(client: Client) -> None:
    global _loops_started
    if _loops_started:
        return
    _loops_started = True
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(weekly_loop(client))
        loop.create_task(file_checker(client))
        loop.create_task(hype_loop(client))
        loop.create_task(pending_loop(client))
        logger.info("[OTT] all loops started")
    except RuntimeError:
        pass


async def force_weekly(client: Client) -> bool:
    return await _do_weekly_post(client, force=True)


__all__ = [
    "ensure_loops", "force_weekly",
    "_do_weekly_post", "_notify_subscribers",
]
