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
_CHECK_INTERVAL = 60
_TASK: Optional[asyncio.Task] = None


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


async def _send_chat(client: Client, chat_id: int, text: str) -> bool:
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
        logger.debug(f"[OTT-WRK] chat {chat_id}: {e}")
        return False


async def _send_users(client: Client, text: str,
                       premium_only: bool = False) -> int:
    try:
        from plugins.broadcast import database as BDB
        if premium_only:
            from plugins.premium import state as PS
            users = await PS.list_users(limit=50000)
            ids = [int(u["user_id"]) for u in users if u.get("user_id")]
        else:
            ids = await BDB.get_all_users()
    except Exception:
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


async def _check(client: Client) -> None:
    now = datetime.now(IST)

    # ── CHANNELS ──
    live_ch = {int(c["chat_id"]) for c in await DB.get_live_channels()}
    for cid in await DB.get_enabled_channels():
        if cid not in live_ch:
            continue  # removed from bot DB
        cfg = await DB.get_channel_config(cid)
        if not cfg.get("running"):
            continue
        freq = cfg.get("frequency") or {}
        key = _expected_key(freq, now)
        if not key or key == cfg.get("last_sent_key"):
            continue
        langs = cfg.get("languages") or []
        if not langs:
            continue
        try:
            text = await V.build_update_text(langs)
            ok = await _send_chat(client, cid, text)
            if ok:
                await DB.update_channel_config(cid, last_sent_key=key)
                logger.info(f"[OTT-WRK] sent to ch {cid} key={key}")
        except Exception as e:
            logger.debug(f"[OTT-WRK] ch {cid}: {e}")
        await asyncio.sleep(0.5)

    # ── GROUPS ──
    live_gr = {int(g["chat_id"]) for g in await DB.get_live_groups()}
    for gid in await DB.get_enabled_groups():
        if gid not in live_gr:
            continue
        cfg = await DB.get_group_config(gid)
        if not cfg.get("running"):
            continue
        freq = cfg.get("frequency") or {}
        key = _expected_key(freq, now)
        if not key or key == cfg.get("last_sent_key"):
            continue
        langs = cfg.get("languages") or []
        if not langs:
            continue
        try:
            text = await V.build_update_text(langs)
            ok = await _send_chat(client, gid, text)
            if ok:
                await DB.update_group_config(gid, last_sent_key=key)
                logger.info(f"[OTT-WRK] sent to gr {gid} key={key}")
        except Exception as e:
            logger.debug(f"[OTT-WRK] gr {gid}: {e}")
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
                    n = await _send_users(client, text,
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
                    n = await _send_users(client, text,
                                           premium_only=True)
                    if n > 0:
                        await DB.update_premium(last_sent_key=key)
                        logger.info(f"[OTT-WRK] prem sent n={n} key={key}")
                except Exception as e:
                    logger.debug(f"[OTT-WRK] pm: {e}")


async def _loop(client: Client) -> None:
    await asyncio.sleep(30)
    while True:
        try:
            await _check(client)
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
