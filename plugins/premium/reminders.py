# ============================================================
# 🏨 DOWNTOWN VILLA — PREMIUM REMINDERS
# ============================================================
#
# Daily reminder loop:
#   • 10 days before expiry
#   • 5 days before expiry
#   • 1 day before expiry
#   • On expiry
#   • Daily admin report
#
# Also runs cleanup of inactive sessions + expired grace.
#
# ============================================================

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from pyrogram import Client
from pyrogram.enums import ParseMode
from pyrogram.errors import UserIsBlocked, FloodWait
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from core import config
from utils import fonts as F
from utils import format as FM

logger = logging.getLogger(__name__)


IST = timezone(timedelta(hours=5, minutes=30))

REMINDER_HOUR = 10
REMINDER_MINUTE = 0
LOOP_INTERVAL = 600      # 10 min
CLEANUP_INTERVAL = 6 * 3600


# ============================================================
# STATE
# ============================================================

STATE: Dict[str, Any] = {
    "reminders_loop": False,
    "cleanup_loop": False,
    "last_run_date": None,
    "last_cleanup": 0.0,
    "reminders_sent_total": 0,
    "cleanups_total": 0,
    "last_error": None,
}

_reminder_task: Optional[asyncio.Task] = None
_cleanup_task: Optional[asyncio.Task] = None


# ============================================================
# ENSURE
# ============================================================

def ensure_loops(client: Client) -> None:
    global _reminder_task, _cleanup_task

    if not _reminder_task or _reminder_task.done():
        try:
            loop = asyncio.get_running_loop()
            _reminder_task = loop.create_task(_reminder_loop(client))
            STATE["reminders_loop"] = True
            logger.info("[PREM-REMIND] reminders loop started")
        except RuntimeError:
            pass

    if not _cleanup_task or _cleanup_task.done():
        try:
            loop = asyncio.get_running_loop()
            _cleanup_task = loop.create_task(_cleanup_loop(client))
            STATE["cleanup_loop"] = True
            logger.info("[PREM-REMIND] cleanup loop started")
        except RuntimeError:
            pass


# ============================================================
# REMINDER LOOP
# ============================================================

async def _reminder_loop(client: Client) -> None:
    await asyncio.sleep(120)

    while True:
        try:
            now = datetime.now(IST)
            today = now.strftime("%Y-%m-%d")

            # Fire once per day at REMINDER_HOUR
            if (
                now.hour == REMINDER_HOUR
                and now.minute < 30
                and STATE["last_run_date"] != today
            ):
                STATE["last_run_date"] = today
                await _send_all_reminders(client)
                await _send_admin_report(client)

        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.warning(f"[PREM-REMIND] loop: {e}")
            STATE["last_error"] = str(e)[:200]

        await asyncio.sleep(LOOP_INTERVAL)


async def _send_all_reminders(client: Client) -> None:
    from plugins.premium import state as S

    users = await S.list_users(500)
    if not users:
        return

    now = time.time()

    for u in users:
        try:
            uid = u.get("user_id")
            expires = u.get("expires_at", 0)
            if not uid or not expires:
                continue

            # Expired
            if expires <= now:
                days_since = (now - expires) / 86400
                if (days_since <= 2
                        and not await S.was_reminder_sent(uid, "expired")):
                    await _send_reminder(client, uid, u, "expired")
                    await S.mark_reminder_sent(uid, "expired")
                continue

            days_left = (expires - now) / 86400

            if 9 < days_left <= 10 and not await S.was_reminder_sent(uid, "10d"):
                await _send_reminder(client, uid, u, "10d")
                await S.mark_reminder_sent(uid, "10d")
            elif 4 < days_left <= 5 and not await S.was_reminder_sent(uid, "5d"):
                await _send_reminder(client, uid, u, "5d")
                await S.mark_reminder_sent(uid, "5d")
            elif 0 < days_left <= 1 and not await S.was_reminder_sent(uid, "1d"):
                await _send_reminder(client, uid, u, "1d")
                await S.mark_reminder_sent(uid, "1d")
        except Exception as e:
            logger.debug(f"[PREM-REMIND] user: {e}")


async def _send_reminder(
    client: Client,
    uid: int,
    user: Dict[str, Any],
    kind: str,
) -> None:
    from plugins.premium import state as S

    contact = await S.get_contact_admin() or "@admin"
    expires = user.get("expires_at", 0)
    exp_date = (
        datetime.fromtimestamp(expires, IST).strftime("%d %b %Y")
        if expires else "?"
    )
    username = user.get("username") or "friend"

    if kind == "10d":
        header = f"{F.EMO['bell']} <b>{F.fb('PREMIUM EXPIRING SOON')}</b>"
        body = (
            f"Hi <b>{F.sc(username)}</b>!\n\n"
            f"Your premium expires in 10 days:\n"
            f"{F.EMO['cal']} <b>{exp_date}</b>"
        )
    elif kind == "5d":
        header = f"{F.EMO['warn']} <b>{F.fb('EXPIRING IN 5 DAYS')}</b>"
        body = (
            f"Hi <b>{F.sc(username)}</b>!\n\n"
            f"{F.EMO['cal']} Ends: <b>{exp_date}</b>\n\n"
            f"{F.EMO['warn']} After expiry you'll lose:\n"
            f"  {F.EMO['cross']} Watch progress tracking\n"
            f"  {F.EMO['cross']} Watch Order Assistant\n"
            f"  {F.EMO['cross']} New episode deliveries\n\n"
            f"{F.EMO['ok']} Already delivered files stay with you."
        )
    elif kind == "1d":
        header = f"{F.EMO['fire']} <b>{F.fb('LAST DAY OF PREMIUM')}</b>"
        body = (
            f"Hi <b>{F.sc(username)}</b>!\n\n"
            f"{F.EMO['clock']} Expires <b>tomorrow</b>\n"
            f"{F.EMO['cal']} <b>{exp_date}</b>\n\n"
            f"{F.EMO['ok']} Progress saved for 30 days after expiry."
        )
    else:  # expired
        header = f"{F.EMO['cross']} <b>{F.fb('PREMIUM EXPIRED')}</b>"
        body = (
            f"Hi <b>{F.sc(username)}</b>!\n\n"
            f"{F.EMO['warn']} Your premium ended today.\n\n"
            f"{F.EMO['ok']} Files you received: yours forever\n"
            f"{F.EMO['pause']} Progress tracking: paused\n"
            f"{F.EMO['cross']} Watch companion: disabled\n\n"
            f"{F.EMO['fire']} Progress DELETED in 30 days if not renewed."
        )

    text = "\n".join([
        f"{F.EMO['crown']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        header,
        F.DIV, "",
        body,
        "", F.DIV_S,
        f"{F.EMO['crown']} Contact: <b>{F.sc(contact)}</b>",
    ])

    rows: List[List[InlineKeyboardButton]] = []
    if contact.startswith("@"):
        rows.append([InlineKeyboardButton(
            f"{F.EMO['crown']} {F.sc('message admin')}",
            url=f"https://t.me/{contact.lstrip('@')}",
        )])
    rows.append([InlineKeyboardButton(
        f"{F.EMO['cross']} {F.sc('dismiss')}",
        callback_data="pw:dismiss_reminder",
    )])

    try:
        await client.send_message(
            chat_id=uid,
            text=text,
            reply_markup=InlineKeyboardMarkup(rows),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        STATE["reminders_sent_total"] += 1
        logger.info(f"[PREM-REMIND] sent {kind} → {uid}")
    except UserIsBlocked:
        pass
    except FloodWait as e:
        await asyncio.sleep(e.value + 2)
    except Exception as e:
        logger.debug(f"[PREM-REMIND] send: {e}")


async def _send_admin_report(client: Client) -> None:
    from plugins.premium import state as S

    if not config.ADMINS:
        return

    stats = await S.count_users()
    sessions = await S.count_sessions()

    text = "\n".join([
        f"{F.EMO['crown']} <b>{F.fb('PREMIUM DAILY REPORT')}</b>",
        F.DIV, "",
        f"🕒 <code>{FM.datetime_()}</code>",
        "",
        f"{F.EMO['ok']} {F.sc('active')} · <b>{stats['active']}</b>",
        f"{F.EMO['clock']} {F.sc('expiring 10d')} · "
        f"<b>{stats['expiring_10d']}</b>",
        f"{F.EMO['warn']} {F.sc('expiring 5d')} · "
        f"<b>{stats['expiring_5d']}</b>",
        f"{F.EMO['fire']} {F.sc('expiring 1d')} · "
        f"<b>{stats['expiring_1d']}</b>",
        f"{F.EMO['cross']} {F.sc('expired')} · "
        f"<b>{stats['expired']}</b>",
        "",
        f"{F.EMO['tv']} {F.sc('active sessions')} · "
        f"<b>{sessions}</b>",
    ])

    for a in config.ADMINS:
        try:
            aid = int(a)
            await client.send_message(
                aid, text,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except Exception:
            pass


# ============================================================
# CLEANUP LOOP
# ============================================================

async def _cleanup_loop(client: Client) -> None:
    await asyncio.sleep(300)

    while True:
        try:
            now = time.time()
            if now - STATE["last_cleanup"] >= CLEANUP_INTERVAL:
                STATE["last_cleanup"] = now

                from plugins.premium import state as S
                n1 = await S.cleanup_inactive()
                n2 = await S.cleanup_expired()
                total = n1 + n2

                if total:
                    STATE["cleanups_total"] += total
                    logger.info(f"[PREM-CLEAN] removed {total} sessions")

        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.warning(f"[PREM-CLEAN] loop: {e}")

        await asyncio.sleep(CLEANUP_INTERVAL)


# ============================================================
# SNAPSHOT
# ============================================================

def snapshot() -> Dict[str, Any]:
    return {
        "reminders_loop": STATE["reminders_loop"],
        "cleanup_loop": STATE["cleanup_loop"],
        "last_run_date": STATE["last_run_date"],
        "reminders_sent": STATE["reminders_sent_total"],
        "cleanups": STATE["cleanups_total"],
        "last_error": STATE["last_error"],
    }


# ============================================================
# PUBLIC
# ============================================================

__all__ = ["ensure_loops", "snapshot"]
