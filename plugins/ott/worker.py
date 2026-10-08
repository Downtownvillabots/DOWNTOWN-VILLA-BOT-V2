# ============================================================
# 🏨 DOWNTOWN VILLA — OTT AUTO-UPDATE WORKER
# ============================================================

from __future__ import annotations
import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional

from pyrogram import Client
from pyrogram.enums import ParseMode
from pyrogram.errors import FloodWait

from plugins.ott import database as DB
from plugins.ott import views as V

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

_CHECK_INTERVAL = 60   # every minute
_TASK: Optional[asyncio.Task] = None


# ═══════════════════════════════════════════════════════════
# KEY COMPUTATION
# ═══════════════════════════════════════════════════════════

def _expected_key(freq: Dict[str, Any], now: datetime) -> Optional[str]:
    mode = freq.get("mode") or "off"
    if mode == "off":
        return None
    hour = int(freq.get("hour") or 0)
    if now.hour != hour:
        return None

    if mode == "daily":
        return f"daily:{now.strftime('%Y-%m-%d')}:{hour}"

    if mode == "weekly":
        want_day = int(freq.get("day_of_week") or 0)
        if now.weekday() != want_day:
            return None
        iso = now.isocalendar()
        return f"weekly:{iso[0]}-W{iso[1]:02d}:{want_day}:{hour}"

    if mode == "monthly":
        want_day = int(freq.get("day_of_month") or 1)
        if now.day != want_day:
            return None
        return f"monthly:{now.strftime('%Y-%m')}:{want_day}:{hour}"

    return None


# ═══════════════════════════════════════════════════════════
# SEND HELPERS
# ═══════════════════════════════════════════════════════════

async def _send_to_chat(client: Client, chat_id: int,
                         text: str) -> bool:
    try:
        await client.send_message(
            chat_id=int(chat_id), text=text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        return True
    except FloodWait as e:
        await asyncio.sleep(int(e.value) + 2)
        return False
    except Exception as e:
        logger.debug(f"[OTT-WRK] send {chat_id}: {e}")
        return False


async def _send_to_users(client: Client, text: str,
                          premium_only: bool = False) -> int:
    try:
        from plugins.broadcast import database as BDB
        if premium_only:
            from plugins.premium import state as PS
            users = await PS.list_users(limit=50000)
            ids = [int(u["user_id"]) for u in users if u.get("user_id")]
        else:
            ids = await BDB.get_all_users()
    except Exception as e:
        logger.debug(f"[OTT-WRK] list users: {e}")
        return 0

    sent = 0
    for uid in ids:
        try:
            await client.send_message(
                chat_id=uid, text=text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
            sent += 1
            await asyncio.sleep(0.05)
        except FloodWait as e:
            await asyncio.sleep(int(e.value) + 2)
        except Exception:
            continue
    return sent


# ═══════════════════════════════════════════════════════════
# MAIN CHECK
# ═══════════════════════════════════════════════════════════

async def _check_once(client: Client) -> None:
    now = datetime.now(IST)

    # ── CHANNELS ──
    for c in await DB.get_channels():
        if not c.get("running"):
            continue
        freq = c.get("frequency") or {}
        key = _expected_key(freq, now)
        if not key or key == c.get("last_sent_key"):
            continue
        langs = c.get("languages") or []
        if not langs:
            continue
        try:
            text = await V.build_update_text(langs)
            ok = await _send_to_chat(client, int(c["chat_id"]), text)
            if ok:
                await DB.update_channel(int(c["chat_id"]),
                                         last_sent_key=key)
                logger.info(
                    f"[OTT-WRK] sent to channel {c['chat_id']} key={key}")
        except Exception as e:
            logger.debug(f"[OTT-WRK] ch {c.get('chat_id')}: {e}")
        await asyncio.sleep(0.5)

    # ── GROUPS ──
    for g in await DB.get_groups():
        if not g.get("running"):
            continue
        freq = g.get("frequency") or {}
        key = _expected_key(freq, now)
        if not key or key == g.get("last_sent_key"):
            continue
        langs = g.get("languages") or []
        if not langs:
            continue
        try:
            text = await V.build_update_text(langs)
            ok = await _send_to_chat(client, int(g["chat_id"]), text)
            if ok:
                await DB.update_group(int(g["chat_id"]),
                                       last_sent_key=key)
                logger.info(
                    f"[OTT-WRK] sent to group {g['chat_id']} key={key}")
        except Exception as e:
            logger.debug(f"[OTT-WRK] gr {g.get('chat_id')}: {e}")
        await asyncio.sleep(0.5)

    # ── USERS ──
    us = await DB.get_users()
    if us.get("running"):
        freq = us.get("frequency") or {}
        key = _expected_key(freq, now)
        if key and key != us.get("last_sent_key"):
            langs = us.get("languages") or []
            if langs:
                try:
                    text = await V.build_update_text(langs)
                    n = await _send_to_users(client, text,
                                              premium_only=False)
                    if n > 0:
                        await DB.update_users(last_sent_key=key)
                        logger.info(f"[OTT-WRK] users sent n={n} key={key}")
                except Exception as e:
                    logger.debug(f"[OTT-WRK] us: {e}")

    # ── PREMIUM ──
    pm = await DB.get_premium()
    if pm.get("running"):
        freq = pm.get("frequency") or {}
        key = _expected_key(freq, now)
        if key and key != pm.get("last_sent_key"):
            langs = pm.get("languages") or []
            if langs:
                try:
                    text = await V.build_update_text(langs)
                    n = await _send_to_users(client, text,
                                              premium_only=True)
                    if n > 0:
                        await DB.update_premium(last_sent_key=key)
                        logger.info(f"[OTT-WRK] prem sent n={n} key={key}")
                except Exception as e:
                    logger.debug(f"[OTT-WRK] pm: {e}")


# ═══════════════════════════════════════════════════════════
# LOOP
# ═══════════════════════════════════════════════════════════

async def _loop(client: Client) -> None:
    await asyncio.sleep(30)
    while True:
        try:
            await _check_once(client)
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.debug(f"[OTT-WRK] loop: {e}")
        await asyncio.sleep(_CHECK_INTERVAL)


def ensure_worker(client: Client) -> None:
    global _TASK
    if _TASK and not _TASK.done():
        return
    try:
        loop = asyncio.get_running_loop()
        _TASK = loop.create_task(_loop(client))
        logger.info("[OTT-WRK] worker started")
    except RuntimeError:
        pass


__all__ = ["ensure_worker"]
