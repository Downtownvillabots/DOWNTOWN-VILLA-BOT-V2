# ============================================================
# 🏨 DOWNTOWN VILLA — PREMIUM ADMIN PANEL
# ============================================================
#
# Admin-only management panel for premium users.
# Opened from /admin → [💎 Premium] button.
#
# Callback format: adm:pma:<action>[:args...]
# Handler group: -9520 (runs before main admin router)
#
# ============================================================

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from core import config
from utils import fonts as F
from utils import format as FM

logger = logging.getLogger(__name__)

PREFIX = "adm:pma:"
FILTER_REGEX = r"^adm:pma:"
PAGE_SIZE = 8
SESSION_TTL = 600.0


# ============================================================
# CALLBACK BUILDER
# ============================================================

def cb(action: str) -> str:
    return PREFIX + str(action)


# ============================================================
# AUTH
# ============================================================

def _is_admin(uid) -> bool:
    try:
        return int(uid) in [int(a) for a in config.ADMINS]
    except Exception:
        return False


# ============================================================
# PENDING TEXT INPUT
# ============================================================

_pending: Dict[int, Dict[str, Any]] = {}


def _pending_set(uid: int, kind: str, **extra) -> None:
    _pending[int(uid)] = {
        "kind": kind,
        "expires": time.time() + SESSION_TTL,
        **extra,
    }


def _pending_get(uid: int) -> Optional[Dict[str, Any]]:
    s = _pending.get(int(uid))
    if not s:
        return None
    if time.time() > s.get("expires", 0):
        _pending.pop(int(uid), None)
        return None
    return s


def _pending_drop(uid: int) -> None:
    _pending.pop(int(uid), None)


# ============================================================
# STATS
# ============================================================

async def _gather_stats() -> Dict[str, int]:
    out = {
        "total": 0, "active": 0,
        "expiring_7d": 0, "expiring_3d": 0, "expired": 0,
    }
    try:
        from plugins.premium import state as S
        counts = await S.count_users()
        out["active"] = counts.get("active", 0)
        out["expiring_7d"] = counts.get("expiring_10d", 0)
        out["expiring_3d"] = counts.get("expiring_5d", 0)
        out["expired"] = counts.get("expired", 0)
        out["total"] = out["active"] + out["expired"]
    except Exception as e:
        logger.debug(f"[PMA] stats: {e}")
    return out


async def _gather_sessions() -> int:
    try:
        from plugins.premium import state as S
        return await S.count_sessions()
    except Exception:
        return 0


async def _gather_analytics() -> Dict[str, Any]:
    """Detailed analytics from real data."""
    out: Dict[str, Any] = {
        "new_week": 0,
        "new_month": 0,
        "new_total": 0,
        "by_plan": {},   # {months: count}
        "avg_days_remaining": 0,
    }

    try:
        from plugins.premium import state as S
        users = await S.list_users(limit=2000)
    except Exception:
        return out

    now = time.time()
    week_ago = now - 7 * 86400
    month_ago = now - 30 * 86400

    total_days = 0
    active_count = 0

    for u in users:
        added = float(u.get("added_at", 0) or 0)
        exp = float(u.get("expires_at", 0) or 0)
        plan = int(u.get("plan_months", 1) or 1)

        if added >= week_ago:
            out["new_week"] += 1
        if added >= month_ago:
            out["new_month"] += 1
        out["new_total"] += 1

        out["by_plan"][plan] = out["by_plan"].get(plan, 0) + 1

        if exp > now:
            total_days += int((exp - now) / 86400)
            active_count += 1

    if active_count > 0:
        out["avg_days_remaining"] = total_days // active_count

    return out


# ============================================================
# MAIN DASHBOARD
# ============================================================

def _kb_main() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"🔍 {F.sc('search user')}",
                callback_data=cb("search"),
            ),
            InlineKeyboardButton(
                f"👥 {F.sc('all users')}",
                callback_data=cb("list:all:0"),
            ),
        ],
        [
            InlineKeyboardButton(
                f"🟢 {F.sc('active')}",
                callback_data=cb("list:active:0"),
            ),
            InlineKeyboardButton(
                f"🟡 {F.sc('expiring 7d')}",
                callback_data=cb("list:expiring:0"),
            ),
        ],
        [
            InlineKeyboardButton(
                f"🔴 {F.sc('expired')}",
                callback_data=cb("list:expired:0"),
            ),
            InlineKeyboardButton(
                f"➕ {F.sc('add premium')}",
                callback_data=cb("add_prem"),
            ),
        ],
        [
            InlineKeyboardButton(
                f"📊 {F.sc('statistics')}",
                callback_data=cb("stats"),
            ),
            InlineKeyboardButton(
                f"📜 {F.sc('history')}",
                callback_data=cb("history"),
            ),
        ],
        [
            InlineKeyboardButton(
                f"🔄 {F.sc('refresh')}",
                callback_data=cb("home"),
            ),
            InlineKeyboardButton(
                f"❌ {F.sc('close')}",
                callback_data=cb("close"),
            ),
        ],
    ])


async def _render_main() -> tuple:
    s = await _gather_stats()
    sessions = await _gather_sessions()

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"👑 <b>{F.fb('PREMIUM MANAGEMENT')}</b>",
        F.DIV, "",
        f"📊 <b>{F.fb('OVERVIEW')}</b>",
        "",
        f"👥 {F.sc('total premium')} · <b>{FM.num(s['total'])}</b>",
        f"🟢 {F.sc('active')} · <b>{FM.num(s['active'])}</b>",
        f"🟡 {F.sc('expiring soon')} · <b>{FM.num(s['expiring_7d'])}</b>",
        f"🔴 {F.sc('expired')} · <b>{FM.num(s['expired'])}</b>",
        "",
        F.DIV_S,
        f"📈 <b>{F.fb('ACTIVITY')}</b>",
        "",
        f"📺 {F.sc('watch sessions')} · <b>{FM.num(sessions)}</b>",
        "",
        F.DIV,
        f"🕒 <code>{FM.datetime_()}</code>",
    ]

    return "\n".join(lines), _kb_main()


# ============================================================
# USER LIST
# ============================================================

async def _render_user_list(filter_type: str, page: int) -> tuple:
    try:
        from plugins.premium import state as S
        all_users = await S.list_users(limit=500)
    except Exception as e:
        logger.debug(f"[PMA] list: {e}")
        all_users = []

    now = time.time()
    d7 = now + 7 * 86400
    d3 = now + 3 * 86400

    filtered: List[Dict[str, Any]] = []
    for u in all_users:
        exp = float(u.get("expires_at", 0) or 0)
        status = u.get("status", "active")

        if filter_type == "active":
            if status == "active" and exp > now:
                filtered.append(u)
        elif filter_type == "expiring":
            if status == "active" and now < exp <= d7:
                filtered.append(u)
        elif filter_type == "expired":
            if exp <= now:
                filtered.append(u)
        else:
            filtered.append(u)

    filtered.sort(key=lambda u: u.get("expires_at", 0))

    total = len(filtered)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    chunk = filtered[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"👥 <b>{F.fb('PREMIUM USERS')}</b>",
        F.DIV, "",
        f"🔖 {F.sc('filter')} · <b>{filter_type.upper()}</b>",
        f"📊 {F.sc('total')} · <b>{FM.num(total)}</b>",
        "",
    ]

    if not chunk:
        lines.append(f"⚪ {F.sc('no users in this filter')}")
    else:
        base = page * PAGE_SIZE
        for i, u in enumerate(chunk):
            exp = float(u.get("expires_at", 0) or 0)
            days = int((exp - now) / 86400)
            status_icon = "🟢" if exp > now else "🔴"
            if now < exp <= d3:
                status_icon = "🟠"
            elif now < exp <= d7:
                status_icon = "🟡"

            uname = u.get("username") or "—"
            plan = int(u.get("plan_months", 1) or 1)
            uid = u.get("user_id", 0)
            days_str = (
                f"⏳ {days}d" if days > 0 else f"⏳ {abs(days)}d ago"
            )

            lines.append(
                f"<b>{base + i + 1:02d}.</b> {status_icon} "
                f"<b>@{F.sc(str(uname)[:24])}</b>"
            )
            lines.append(f"   🆔 <code>{uid}</code>")
            lines.append(f"   💎 {plan}mo · {days_str}")
            lines.append("")

    lines.append(F.DIV)
    lines.append(f"📄 {F.sc('page')} · <b>{page + 1}/{total_pages}</b>")

    rows: List[List[InlineKeyboardButton]] = []
    btn_row: List[InlineKeyboardButton] = []
    for u in chunk:
        uid = u.get("user_id", 0)
        uname = str(u.get("username") or uid)[:18]
        btn_row.append(InlineKeyboardButton(
            f"👤 {uname}",
            callback_data=cb(f"user:{uid}"),
        ))
        if len(btn_row) == 2:
            rows.append(btn_row)
            btn_row = []
    if btn_row:
        rows.append(btn_row)

    nav = []
    if page > 0:
        nav.append(InlineKeyboardButton(
            f"⬅️ {F.sc('prev')}",
            callback_data=cb(f"list:{filter_type}:{page - 1}"),
        ))
    nav.append(InlineKeyboardButton(
        f"{page + 1}/{total_pages}",
        callback_data=cb("noop"),
    ))
    if page < total_pages - 1:
        nav.append(InlineKeyboardButton(
            f"{F.sc('next')} ➡️",
            callback_data=cb(f"list:{filter_type}:{page + 1}"),
        ))
    if nav:
        rows.append(nav)

    rows.append([
        InlineKeyboardButton(
            f"🏠 {F.sc('home')}",
            callback_data=cb("home"),
        ),
        InlineKeyboardButton(
            f"❌ {F.sc('close')}",
            callback_data=cb("close"),
        ),
    ])

    return "\n".join(lines)[:4000], InlineKeyboardMarkup(rows)


# ============================================================
# USER DETAIL
# ============================================================

async def _render_user(user_id: int) -> tuple:
    try:
        from plugins.premium import state as S
        user = await S.get_user(user_id)
        sessions = await S.list_user_sessions(user_id, status=None)
    except Exception as e:
        logger.debug(f"[PMA] user detail: {e}")
        user = None
        sessions = []

    if not user:
        return (
            "\n".join([
                f"{F.EMO['cross']} <b>{F.fb('USER NOT FOUND')}</b>",
                F.DIV, "",
                f"🆔 <code>{user_id}</code>",
            ]),
            InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"⬅️ {F.sc('back')}",
                    callback_data=cb("home"),
                ),
            ]]),
        )

    now = time.time()
    exp = float(user.get("expires_at", 0) or 0)
    added = float(user.get("added_at", 0) or 0)
    days = int((exp - now) / 86400)
    is_active = exp > now and user.get("status") == "active"

    total_watched = 0
    completed_series = 0
    try:
        from plugins.premium import state as S
        for s in (sessions or []):
            p = S.compute_progress(s)
            total_watched += p.get("total_watched", 0)
            if s.get("status") == "completed":
                completed_series += 1
    except Exception:
        pass

    reminders = user.get("reminders_sent") or []

    added_str = "—"
    exp_str = "—"
    try:
        if added:
            added_str = FM.date_(datetime.fromtimestamp(added))
        if exp:
            exp_str = FM.date_(datetime.fromtimestamp(exp))
    except Exception:
        pass

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"👤 <b>{F.fb('PREMIUM USER')}</b>",
        F.DIV, "",
        f"👤 <b>{F.fb('ACCOUNT')}</b>",
        "",
        f"🆔 {F.sc('id')} · <code>{user_id}</code>",
        f"🔗 {F.sc('username')} · "
        f"<code>@{F.sc(str(user.get('username') or '—'))}</code>",
        "",
        F.DIV_S,
        f"💎 <b>{F.fb('PREMIUM')}</b>",
        "",
        f"🟢 {F.sc('status')} · "
        f"{'✅ ACTIVE' if is_active else '❌ INACTIVE'}",
        f"📦 {F.sc('plan')} · "
        f"<b>{int(user.get('plan_months', 1) or 1)} month</b>",
        "",
        f"📅 {F.sc('started')} · <code>{added_str}</code>",
        f"📅 {F.sc('expires')} · <code>{exp_str}</code>",
    ]

    if days > 0:
        lines.append(f"⏳ {F.sc('remaining')} · <b>{days} days</b>")
    else:
        lines.append(f"⏳ <b>expired</b>")

    notes = user.get("notes") or ""
    if notes:
        lines.append(f"📝 {F.sc('notes')} · "
                     f"<i>{F.sc(str(notes)[:60])}</i>")

    lines += [
        "",
        F.DIV_S,
        f"📊 <b>{F.fb('WATCH ACTIVITY')}</b>",
        "",
        f"📺 {F.sc('sessions')} · <b>{len(sessions)}</b>",
        f"🎬 {F.sc('episodes')} · <b>{FM.num(total_watched)}</b>",
        f"✅ {F.sc('completed')} · <b>{completed_series}</b>",
        "",
        F.DIV_S,
        f"🔔 <b>{F.fb('REMINDERS SENT')}</b>",
        "",
        f"📨 {F.sc('history')} · "
        f"<code>{', '.join(reminders) if reminders else '—'}</code>",
        "",
        F.DIV,
        f"🕒 <code>{FM.datetime_()}</code>",
    ]

    rows = [
        [InlineKeyboardButton(
            f"➕ {F.sc('extend')}",
            callback_data=cb(f"extend:{user_id}"),
        )],
        [InlineKeyboardButton(
            f"🔄 {F.sc('reset reminders')}",
            callback_data=cb(f"reset_rem:{user_id}"),
        )],
        [InlineKeyboardButton(
            f"❌ {F.sc('remove premium')}",
            callback_data=cb(f"remove:{user_id}"),
        )],
        [
            InlineKeyboardButton(
                f"⬅️ {F.sc('back')}",
                callback_data=cb("list:all:0"),
            ),
            InlineKeyboardButton(
                f"❌ {F.sc('close')}",
                callback_data=cb("close"),
            ),
        ],
    ]

    return "\n".join(lines)[:4000], InlineKeyboardMarkup(rows)


# ============================================================
# EXTEND
# ============================================================

def _kb_extend(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ 1 month",
                callback_data=cb(f"extend_do:{user_id}:1")),
            InlineKeyboardButton("➕ 3 months",
                callback_data=cb(f"extend_do:{user_id}:3")),
        ],
        [
            InlineKeyboardButton("➕ 6 months",
                callback_data=cb(f"extend_do:{user_id}:6")),
            InlineKeyboardButton("➕ 12 months",
                callback_data=cb(f"extend_do:{user_id}:12")),
        ],
        [InlineKeyboardButton(
            f"⬅️ {F.sc('back')}",
            callback_data=cb(f"user:{user_id}"),
        )],
    ])


async def _render_extend(user_id: int) -> tuple:
    try:
        from plugins.premium import state as S
        user = await S.get_user(user_id)
    except Exception:
        user = None

    if not user:
        return ("❌ user not found", _kb_extend(user_id))

    uname = user.get("username") or user_id
    exp = float(user.get("expires_at", 0) or 0)
    days = int((exp - time.time()) / 86400)

    lines = [
        f"➕ <b>{F.fb('EXTEND PREMIUM')}</b>",
        F.DIV, "",
        f"👤 <b>@{F.sc(str(uname))}</b>",
        f"🆔 <code>{user_id}</code>",
        f"⏳ {F.sc('current expiry')} · <b>{days} days</b>",
        "",
        F.DIV_S,
        f"📌 {F.sc('pick a duration to add')}",
    ]
    return "\n".join(lines), _kb_extend(user_id)


# ============================================================
# REMOVE CONFIRM
# ============================================================

def _kb_confirm_remove(user_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"🗑️ {F.sc('yes, remove')}",
            callback_data=cb(f"remove_do:{user_id}"),
        )],
        [InlineKeyboardButton(
            f"⬅️ {F.sc('cancel')}",
            callback_data=cb(f"user:{user_id}"),
        )],
    ])


async def _render_confirm_remove(user_id: int) -> tuple:
    try:
        from plugins.premium import state as S
        user = await S.get_user(user_id)
    except Exception:
        user = None

    uname = (user or {}).get("username") or user_id

    lines = [
        f"⚠️ <b>{F.fb('REMOVE PREMIUM?')}</b>",
        F.DIV, "",
        f"👤 <b>@{F.sc(str(uname))}</b>",
        f"🆔 <code>{user_id}</code>",
        "",
        f"📌 {F.sc('this removes the premium user document')}",
        f"📌 {F.sc('watch sessions are NOT deleted')}",
    ]
    return "\n".join(lines), _kb_confirm_remove(user_id)


# ============================================================
# ADD PREMIUM
# ============================================================

async def _render_add_prem_prompt() -> tuple:
    lines = [
        f"➕ <b>{F.fb('ADD PREMIUM')}</b>",
        F.DIV, "",
        f"📌 {F.sc('send the user id')}",
        f"📌 {F.sc('example')} · <code>123456789</code>",
        "",
        f"💡 {F.sc('tips')}",
        f"• {F.sc('user must have started the bot first')}",
        f"• {F.sc('send')} <code>-</code> {F.sc('to cancel')}",
    ]
    return "\n".join(lines), InlineKeyboardMarkup([[
        InlineKeyboardButton(
            f"❌ {F.sc('cancel')}",
            callback_data=cb("home"),
        ),
    ]])


async def _render_add_prem_months(user_id: int) -> tuple:
    try:
        from plugins.premium import state as S
        existing = await S.get_user(user_id)
    except Exception:
        existing = None

    lines = [
        f"➕ <b>{F.fb('ADD PREMIUM')}</b>",
        F.DIV, "",
        f"🆔 {F.sc('user id')} · <code>{user_id}</code>",
    ]

    if existing:
        exp = float(existing.get("expires_at", 0) or 0)
        days = int((exp - time.time()) / 86400)
        uname = existing.get("username") or "—"
        lines += [
            f"👤 {F.sc('username')} · "
            f"<code>@{F.sc(str(uname))}</code>",
            "",
            f"⚠️ {F.sc('this user already has premium')}",
            f"⏳ {F.sc('currently')} · <b>{days} days</b>",
            f"📌 {F.sc('adding will stack on top')}",
        ]
    else:
        lines += [
            "",
            f"🆕 {F.sc('new premium user')}",
        ]

    lines += [
        "",
        F.DIV_S,
        f"📌 {F.sc('pick the duration')}",
    ]

    rows = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("➕ 1 month",
                callback_data=cb(f"add_prem_do:{user_id}:1")),
            InlineKeyboardButton("➕ 3 months",
                callback_data=cb(f"add_prem_do:{user_id}:3")),
        ],
        [
            InlineKeyboardButton("➕ 6 months",
                callback_data=cb(f"add_prem_do:{user_id}:6")),
            InlineKeyboardButton("➕ 12 months",
                callback_data=cb(f"add_prem_do:{user_id}:12")),
        ],
        [InlineKeyboardButton(
            f"❌ {F.sc('cancel')}",
            callback_data=cb("home"),
        )],
    ])

    return "\n".join(lines), rows


# ============================================================
# STATISTICS
# ============================================================

async def _render_stats() -> tuple:
    s = await _gather_stats()
    a = await _gather_analytics()
    sessions = await _gather_sessions()

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"📊 <b>{F.fb('PREMIUM STATISTICS')}</b>",
        F.DIV, "",
        f"👥 <b>{F.fb('USER COUNTS')}</b>",
        "",
        f"👥 {F.sc('total')} · <b>{FM.num(s['total'])}</b>",
        f"🟢 {F.sc('active')} · <b>{FM.num(s['active'])}</b>",
        f"🟡 {F.sc('expiring 7d')} · <b>{FM.num(s['expiring_7d'])}</b>",
        f"🔴 {F.sc('expired')} · <b>{FM.num(s['expired'])}</b>",
        "",
        F.DIV_S,
        f"📈 <b>{F.fb('GROWTH')}</b>",
        "",
        f"📅 {F.sc('new this week')} · <b>{FM.num(a['new_week'])}</b>",
        f"📆 {F.sc('new this month')} · <b>{FM.num(a['new_month'])}</b>",
        f"📊 {F.sc('total records')} · <b>{FM.num(a['new_total'])}</b>",
        "",
        F.DIV_S,
        f"💎 <b>{F.fb('BY PLAN')}</b>",
        "",
    ]

    plan_counts = a.get("by_plan") or {}
    if plan_counts:
        for months in sorted(plan_counts.keys()):
            cnt = plan_counts[months]
            lines.append(
                f"📦 {months} {F.sc('months')} · <b>{FM.num(cnt)}</b>"
            )
    else:
        lines.append(f"⚪ {F.sc('no data')}")

    lines += [
        "",
        F.DIV_S,
        f"⏳ <b>{F.fb('ENGAGEMENT')}</b>",
        "",
        f"📺 {F.sc('watch sessions')} · <b>{FM.num(sessions)}</b>",
        f"⏰ {F.sc('avg days remaining')} · "
        f"<b>{a.get('avg_days_remaining', 0)}</b>",
        "",
        F.DIV,
        f"🕒 <code>{FM.datetime_()}</code>",
    ]

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"🔄 {F.sc('refresh')}",
                callback_data=cb("stats"),
            ),
            InlineKeyboardButton(
                f"🏠 {F.sc('home')}",
                callback_data=cb("home"),
            ),
        ],
        [InlineKeyboardButton(
            f"❌ {F.sc('close')}",
            callback_data=cb("close"),
        )],
    ])

    return "\n".join(lines)[:4000], kb


# ============================================================
# HISTORY
# ============================================================

async def _render_history(page: int = 0) -> tuple:
    try:
        from plugins.premium import state as S
        users = await S.list_users(limit=200)
    except Exception:
        users = []

    # Sort by added_at desc (most recent first)
    users.sort(key=lambda u: u.get("added_at", 0), reverse=True)

    total = len(users)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = max(0, min(page, total_pages - 1))
    chunk = users[page * PAGE_SIZE:(page + 1) * PAGE_SIZE]

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"📜 <b>{F.fb('PREMIUM HISTORY')}</b>",
        F.DIV, "",
        f"📊 {F.sc('total records')} · <b>{FM.num(total)}</b>",
        f"📄 {F.sc('page')} · <b>{page + 1}/{total_pages}</b>",
        "",
        F.DIV_S,
        "",
    ]

    if not chunk:
        lines.append(f"⚪ {F.sc('no premium records yet')}")
    else:
        for i, u in enumerate(chunk):
            added = float(u.get("added_at", 0) or 0)
            exp = float(u.get("expires_at", 0) or 0)
            uid = u.get("user_id", 0)
            uname = u.get("username") or "—"
            plan = int(u.get("plan_months", 1) or 1)
            added_by = u.get("added_by", 0)

            added_str = "—"
            try:
                if added:
                    added_str = FM.datetime_(
                        datetime.fromtimestamp(added)
                    )
            except Exception:
                pass

            is_active = exp > time.time()
            icon = "🟢" if is_active else "🔴"

            lines.append(
                f"<b>{page * PAGE_SIZE + i + 1:02d}.</b> {icon} "
                f"<b>@{F.sc(str(uname)[:24])}</b>"
            )
            lines.append(f"   🆔 <code>{uid}</code>")
            lines.append(f"   💎 {plan}mo · 📅 {added_str}")
            if added_by:
                lines.append(f"   👤 by <code>{added_by}</code>")
            lines.append("")

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"⬅️ {F.sc('prev')}",
                callback_data=cb(f"history:{max(0, page - 1)}"),
            ),
            InlineKeyboardButton(
                f"{F.sc('next')} ➡️",
                callback_data=cb(f"history:{min(total_pages - 1, page + 1)}"),
            ),
        ],
        [
            InlineKeyboardButton(
                f"🔄 {F.sc('refresh')}",
                callback_data=cb(f"history:{page}"),
            ),
            InlineKeyboardButton(
                f"🏠 {F.sc('home')}",
                callback_data=cb("home"),
            ),
        ],
        [InlineKeyboardButton(
            f"❌ {F.sc('close')}",
            callback_data=cb("close"),
        )],
    ])

    return "\n".join(lines)[:4000], kb


# ============================================================
# SEARCH
# ============================================================

async def _render_search_prompt() -> tuple:
    lines = [
        f"🔍 <b>{F.fb('SEARCH PREMIUM USER')}</b>",
        F.DIV, "",
        f"📌 {F.sc('send any of the following')}",
        "",
        f"• 🆔 {F.sc('user id')} · <code>123456789</code>",
        f"• 🔗 {F.sc('username')} · <code>@john</code> {F.sc('or')} <code>john</code>",
        "",
        f"📌 {F.sc('send')} <code>-</code> {F.sc('to cancel')}",
    ]
    return "\n".join(lines), InlineKeyboardMarkup([[
        InlineKeyboardButton(
            f"❌ {F.sc('cancel')}",
            callback_data=cb("home"),
        ),
    ]])


async def _do_search(query: str) -> tuple:
    q = query.strip()
    if q.startswith("@"):
        q = q[1:]

    found = []
    try:
        from plugins.premium import state as S
        if q.isdigit():
            user = await S.get_user(int(q))
            if user:
                found.append(user)
        else:
            user = await S.find_by_username(q)
            if user:
                found.append(user)
    except Exception as e:
        logger.debug(f"[PMA] search: {e}")

    if not found:
        return (
            "\n".join([
                f"❌ <b>{F.fb('NOT FOUND')}</b>",
                F.DIV, "",
                f"🔍 <code>{F.sc(q)}</code>",
            ]),
            InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"🔍 {F.sc('search again')}",
                    callback_data=cb("search"),
                ),
                InlineKeyboardButton(
                    f"🏠 {F.sc('home')}",
                    callback_data=cb("home"),
                ),
            ]]),
        )

    return await _render_user(found[0].get("user_id"))


# ============================================================
# SAFE EDIT
# ============================================================

async def _safe_edit(q: CallbackQuery, text: str, kb) -> None:
    try:
        await q.message.edit_text(
            text, reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        if "not modified" not in str(e).lower():
            logger.debug(f"[PMA] edit: {e}")


# ============================================================
# ROUTER
# ============================================================

@Client.on_callback_query(
    filters.regex(FILTER_REGEX), group=-9520,
)
async def premium_admin_router(client: Client, q: CallbackQuery):
    if not q.from_user or not _is_admin(q.from_user.id):
        return await q.answer("⛔ Admins only", show_alert=True)

    data = str(q.data or "")
    if not data.startswith(PREFIX):
        return await q.answer("❌ invalid")

    rest = data[len(PREFIX):]
    parts = rest.split(":")
    action = parts[0] if parts else ""
    args = parts[1:]

    try:
        # ── CLOSE ──
        if action == "close":
            try:
                await q.message.delete()
            except Exception:
                pass
            return await q.answer("Closed")

        # ── NOOP ──
        if action == "noop":
            return await q.answer()

        # ── HOME ──
        if action == "home":
            text, kb = await _render_main()
            await _safe_edit(q, text, kb)
            return await q.answer()

        # ── LIST ──
        if action == "list":
            filter_type = args[0] if args else "all"
            try:
                page = int(args[1]) if len(args) > 1 else 0
            except ValueError:
                page = 0
            text, kb = await _render_user_list(filter_type, page)
            await _safe_edit(q, text, kb)
            return await q.answer()

        # ── USER DETAIL ──
        if action == "user":
            try:
                uid = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌ invalid id", show_alert=True)
            text, kb = await _render_user(uid)
            await _safe_edit(q, text, kb)
            return await q.answer()

        # ── EXTEND MENU ──
        if action == "extend":
            try:
                uid = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌", show_alert=True)
            text, kb = await _render_extend(uid)
            await _safe_edit(q, text, kb)
            return await q.answer()

        # ── EXTEND DO ──
        if action == "extend_do":
            try:
                uid = int(args[0])
                months = int(args[1])
            except (ValueError, IndexError):
                return await q.answer("❌", show_alert=True)

            try:
                from plugins.premium import state as S
                user = await S.get_user(uid)
                uname = (user or {}).get("username") or ""
                ok = await S.add_premium_user(
                    user_id=uid,
                    username=uname,
                    months=months,
                    added_by=q.from_user.id,
                    notes="extended via admin panel",
                )
                await q.answer(
                    f"✅ Extended by {months} months" if ok
                    else "❌ Extend failed"
                )
            except Exception as e:
                logger.exception(f"[PMA] extend: {e}")
                return await q.answer(
                    f"❌ {type(e).__name__}", show_alert=True
                )

            text, kb = await _render_user(uid)
            await _safe_edit(q, text, kb)
            return

        # ── RESET REMINDERS ──
        if action == "reset_rem":
            try:
                uid = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌", show_alert=True)

            try:
                from database import db_registry
                db = db_registry.get_user_db()
                if db is not None:
                    await db["premium_users"].update_one(
                        {"user_id": uid},
                        {"$set": {"reminders_sent": []}},
                    )
                    await q.answer("✅ Reminders reset")
                else:
                    await q.answer("❌ DB error", show_alert=True)
            except Exception as e:
                logger.exception(f"[PMA] reset_rem: {e}")
                return await q.answer("❌ failed", show_alert=True)

            text, kb = await _render_user(uid)
            await _safe_edit(q, text, kb)
            return

        # ── REMOVE (confirm screen) ──
        if action == "remove":
            try:
                uid = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌", show_alert=True)
            text, kb = await _render_confirm_remove(uid)
            await _safe_edit(q, text, kb)
            return await q.answer()

        # ── REMOVE DO ──
        if action == "remove_do":
            try:
                uid = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌", show_alert=True)

            try:
                from plugins.premium import state as S
                ok = await S.remove_user(uid)
                await q.answer("🗑️ Removed" if ok else "⚠️ Not found")
            except Exception as e:
                logger.exception(f"[PMA] remove: {e}")
                return await q.answer("❌ failed", show_alert=True)

            text, kb = await _render_user_list("all", 0)
            await _safe_edit(q, text, kb)
            return

        # ── SEARCH ──
        if action == "search":
            _pending_set(q.from_user.id, kind="search")
            text, kb = await _render_search_prompt()
            await _safe_edit(q, text, kb)
            return await q.answer()

        # ── ADD PREMIUM (prompt for user ID) ──
        if action == "add_prem":
            _pending_set(q.from_user.id, kind="add_prem")
            text, kb = await _render_add_prem_prompt()
            await _safe_edit(q, text, kb)
            return await q.answer()

        # ── ADD PREMIUM (months picker after user ID given) ──
        if action == "add_prem_months":
            try:
                uid = int(args[0])
            except (ValueError, IndexError):
                return await q.answer("❌", show_alert=True)
            text, kb = await _render_add_prem_months(uid)
            await _safe_edit(q, text, kb)
            return await q.answer()

        # ── ADD PREMIUM (execute) ──
        if action == "add_prem_do":
            try:
                uid = int(args[0])
                months = int(args[1])
            except (ValueError, IndexError):
                return await q.answer("❌", show_alert=True)

            try:
                from plugins.premium import state as S
                # Try to fetch username from bot (if user started it)
                username = ""
                try:
                    chat = await client.get_chat(uid)
                    username = chat.username or ""
                except Exception:
                    pass

                ok = await S.add_premium_user(
                    user_id=uid,
                    username=username,
                    months=months,
                    added_by=q.from_user.id,
                    notes="added via admin panel",
                )
                await q.answer(
                    f"✅ Added {months} months" if ok
                    else "❌ Failed"
                )
            except Exception as e:
                logger.exception(f"[PMA] add_prem_do: {e}")
                return await q.answer(
                    f"❌ {type(e).__name__}", show_alert=True
                )

            # Show user detail
            text, kb = await _render_user(uid)
            await _safe_edit(q, text, kb)
            return

        # ── STATS ──
        if action == "stats":
            text, kb = await _render_stats()
            await _safe_edit(q, text, kb)
            return await q.answer()

        # ── HISTORY ──
        if action == "history":
            try:
                page = int(args[0]) if args else 0
            except ValueError:
                page = 0
            text, kb = await _render_history(page)
            await _safe_edit(q, text, kb)
            return await q.answer()

        return await q.answer(f"❓ Unknown: {action}")

    except Exception as e:
        logger.exception(f"[PMA] router: {e}")
        try:
            await q.answer(f"❌ {type(e).__name__}", show_alert=True)
        except Exception:
            pass


# ============================================================
# TEXT INPUT (search + add premium)
# ============================================================

@Client.on_message(
    filters.private & filters.text & ~filters.regex(r"^/"),
    group=-9511,
)
async def premium_admin_text_input(client: Client, message: Message):
    if not message.from_user or not _is_admin(message.from_user.id):
        return

    pending = _pending_get(message.from_user.id)
    if not pending:
        return

    kind = pending.get("kind")
    text = (message.text or "").strip()

    # ── SEARCH ──
    if kind == "search":
        _pending_drop(message.from_user.id)

        if text == "-" or not text:
            t, k = await _render_main()
        else:
            t, k = await _do_search(text)

        await message.reply_text(
            t, reply_markup=k,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        try:
            message.stop_propagation()
        except Exception:
            pass
        return

    # ── ADD PREMIUM (user ID input) ──
    if kind == "add_prem":
        if text == "-" or not text:
            _pending_drop(message.from_user.id)
            t, k = await _render_main()
            await message.reply_text(
                t, reply_markup=k,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
            try:
                message.stop_propagation()
            except Exception:
                pass
            return

        if not text.isdigit():
            return await message.reply_text(
                f"{F.EMO['cross']} {F.sc('send a numeric user id')}",
                parse_mode=ParseMode.HTML,
            )

        _pending_drop(message.from_user.id)
        user_id = int(text)

        t, k = await _render_add_prem_months(user_id)
        await message.reply_text(
            t, reply_markup=k,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        try:
            message.stop_propagation()
        except Exception:
            pass
        return


# ============================================================
# PUBLIC ENTRY (called from admin.py)
# ============================================================

async def open_panel_for_admin(client: Client, message: Message) -> None:
    """Called from /admin → [💎 Premium]."""
    text, kb = await _render_main()

    try:
        await message.reply_text(
            text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.exception(f"[PMA] open: {e}")


def snapshot() -> Dict[str, Any]:
    return {"pending_searches": len(_pending)}


__all__ = ["open_panel_for_admin", "snapshot"]
