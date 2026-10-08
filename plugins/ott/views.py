# ============================================================
# 🏨 DOWNTOWN VILLA — OTT VIEWS
# ============================================================

from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional, Tuple

from pyrogram.enums import ParseMode
from pyrogram.errors import MessageNotModified
from pyrogram.types import InlineKeyboardMarkup

from plugins.broadcast.config import (
    fb, sc, _esc, _fmt_int, _fmt_size, _fmt_duration,
    DIV, DIV2,
)
from plugins.ott import database as DB
from plugins.ott import keyboards as KB
from plugins.ott.config import LANGUAGE_LABELS

logger = logging.getLogger(__name__)


async def safe_edit(target, text: str, kb=None) -> bool:
    try:
        msg = getattr(target, "message", target)
        await msg.edit_text(
            text, reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        return True
    except MessageNotModified:
        return True
    except Exception as e:
        logger.debug(f"[OTT-V] edit: {type(e).__name__}: {e}")
        return False


def _header(title: str) -> str:
    return "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📅 <b>{fb(title)}</b>",
        DIV, "",
    ])


# ═══════════════════════════════════════════════════════════
# HOME / DASHBOARD / WEEK / DAY
# ═══════════════════════════════════════════════════════════

async def view_home() -> Tuple[str, InlineKeyboardMarkup]:
    wk = DB.week_key()
    w = await DB.get_week(wk)
    movies = []
    if w:
        for d in (w.get("days") or []):
            movies.extend(d)

    pending = await DB.pending_subs_total()
    bc7 = await DB.broadcast_recent_count(7)

    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📅 <b>{fb('OTT CONTROL CENTER')}</b>",
        DIV, "",
        f"🗓️ {sc('week')} · <code>{wk}</code>",
        f"🎬 {sc('movies this week')} · <b>{len(movies)}</b>",
        f"🔔 {sc('pending subscribers')} · <b>{_fmt_int(pending)}</b>",
        f"📢 {sc('broadcasts 7d')} · <b>{_fmt_int(bc7)}</b>",
        "", DIV2,
        f"📌 {sc('admin-only panel')}",
        f"📌 {sc('all data lives in SYSTEM db')}",
    ])
    return text, KB.kb_home()


async def view_dashboard() -> Tuple[str, InlineKeyboardMarkup]:
    wk = DB.week_key()
    w = await DB.get_week(wk)
    movies = []
    if w:
        for d in (w.get("days") or []):
            movies.extend(d)

    cache_n = await DB.cache_count()
    sent_7d = await DB.sent_count_last(7)
    bc_7d = await DB.broadcast_recent_count(7)
    bc_deliv = await DB.broadcast_total_delivered(30)
    pending = await DB.pending_subs_total()
    pend_msgs = await DB.pending_count()

    top = "—"
    top_c = 0
    try:
        rows = await DB.subs_overview(limit=1)
        if rows:
            top = rows[0].get("title") or "—"
            top_c = rows[0].get("count", 0)
    except Exception:
        pass

    cfg = await DB.get_cfg()

    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📊 <b>{fb('OTT DASHBOARD')}</b>",
        DIV, "",
        f"🗓️ {sc('week')} · <code>{wk}</code>",
        f"🎬 {sc('movies')} · <b>{len(movies)}</b>",
        "", DIV2, "",
        f"🔔 <b>{sc('NOTIFICATIONS')}</b>",
        f"📨 {sc('sent 7d')} · <b>{_fmt_int(sent_7d)}</b>",
        f"⏳ {sc('pending subs')} · <b>{_fmt_int(pending)}</b>",
        f"🗑️ {sc('pending auto-delete')} · <b>{_fmt_int(pend_msgs)}</b>",
        "", DIV2, "",
        f"📢 <b>{sc('BROADCASTS')}</b>",
        f"🎯 {sc('last 7d')} · <b>{_fmt_int(bc_7d)}</b>",
        f"📬 {sc('delivered 30d')} · <b>{_fmt_int(bc_deliv)}</b>",
        "", DIV2, "",
        f"🏆 {sc('top movie')} · <code>{_esc(str(top)[:40])}</code>",
        f"🔔 {sc('subs')} · <b>{top_c}</b>",
        "", DIV2, "",
        f"🌍 {sc('region')} · <code>{cfg.get('region')}</code>",
        f"🌐 {sc('langs')} · <code>{','.join(cfg.get('languages') or [])}</code>",
        f"⭐ {sc('min votes')} · <code>{cfg.get('min_vote_count')}</code>",
        f"🎬 {sc('cache')} · <b>{_fmt_int(cache_n)}</b>",
    ])
    return text, KB.kb_dashboard()


async def view_week() -> Tuple[str, InlineKeyboardMarkup]:
    wk = DB.week_key()
    w = await DB.get_week(wk)
    if not w or not w.get("days"):
        text = "\n".join([
            _header("THIS WEEK"),
            f"⚪ {sc('no data yet')}",
            "", f"📌 {sc('tap refetch to load')}",
        ])
        return text, KB.kb_week([0] * 7)

    days = w.get("days") or []
    counts = [len(days[i]) if i < len(days) else 0 for i in range(7)]
    mon = DB.day_date(0).strftime("%d %b")
    sun = DB.day_date(6).strftime("%d %b %Y")
    total = sum(counts)

    text = "\n".join([
        _header("THIS WEEK"),
        f"🗓️ <code>{mon} → {sun}</code>",
        f"🎬 {sc('total')} · <b>{total}</b>",
        "", DIV2,
        f"📌 {sc('tap a day to see movies')}",
    ])
    return text, KB.kb_week(counts)


async def view_day(idx: int) -> Tuple[str, InlineKeyboardMarkup]:
    wk = DB.week_key()
    w = await DB.get_week(wk)
    days = (w or {}).get("days") or []
    movies = days[idx] if 0 <= idx < len(days) else []
    pretty = DB.day_date(idx).strftime("%A · %d %b %Y")

    lines = [
        _header("RELEASES"),
        f"<code>{pretty}</code>",
        "",
    ]
    if not movies:
        lines.append(f"⚪ {sc('no releases this day')}")
    else:
        for m in movies[:20]:
            title = str(m.get("title") or "?")[:50]
            year = (m.get("release_date") or "")[:4]
            rating = m.get("vote_average", 0)
            lang = (m.get("original_language") or "").upper()
            lines.append(f"⭐ <b>{sc(title)}</b> ({year})")
            meta = []
            if rating:
                meta.append(f"{rating:.1f}")
            if lang:
                meta.append(lang)
            if meta:
                lines.append(f"   <code>{' · '.join(meta)}</code>")
    return "\n".join(lines)[:4000], KB.kb_day(movies)


# ═══════════════════════════════════════════════════════════
# MOVIE
# ═══════════════════════════════════════════════════════════

async def view_movie(tmdb_id: int, back_cb: str = "ott:week"
                     ) -> Tuple[str, InlineKeyboardMarkup, Optional[str]]:
    from plugins.ott.tmdb import enrich_movie, poster_url

    wk = DB.week_key()
    w = await DB.get_week(wk)
    raw = None
    for d in ((w or {}).get("days") or []):
        for m in d:
            if int(m.get("tmdb_id", 0)) == int(tmdb_id):
                raw = m
                break
        if raw:
            break
    if raw is None:
        raw = await DB.get_movie(tmdb_id) or {"tmdb_id": tmdb_id, "title": "?"}

    movie = await enrich_movie(raw)
    sub_count = await DB.count_subs_for_movie(tmdb_id)
    bc_count = await DB.broadcast_count_for_movie(tmdb_id)

    title = movie.get("title") or "?"
    year = (movie.get("release_date") or "")[:4]
    rating = movie.get("vote_average", 0) or 0
    votes = movie.get("vote_count", 0) or 0
    runtime = movie.get("runtime", 0) or 0
    genres = (movie.get("genres") or "—")[:60]
    overview = (movie.get("overview") or "")[:400]
    provider = movie.get("provider") or "—"
    lang = (movie.get("original_language") or "").upper()

    lines = [
        f"🎬 <b>{sc(str(title)[:60])}</b> ({year})",
        DIV, "",
        f"⭐ {sc('rating')} · <code>{rating:.1f}/10</code> "
        f"(<code>{_fmt_int(votes)}</code>)",
        f"🎭 {sc('genres')} · <code>{sc(genres)}</code>",
        f"⏱️ {sc('runtime')} · <code>{runtime} min</code>",
        f"🌐 {sc('lang')} · <code>{lang or '—'}</code>",
        f"📺 {sc('streaming')} · <b>{sc(provider)}</b>",
        "", DIV2,
        f"📅 {sc('release')} · "
        f"<code>{(movie.get('region_release') or {}).get('date') or movie.get('release_date') or '—'}</code>",
        "", DIV2,
        f"🔔 {sc('subscribers')} · <b>{sub_count}</b>",
        f"📢 {sc('broadcasted')} · <b>{bc_count}</b>",
    ]
    if overview:
        lines += ["", f"📖 <b>{sc('plot')}</b>", f"<i>{sc(overview)}</i>"]

    poster = poster_url(movie.get("poster_path"), "w500")
    return "\n".join(lines)[:4000], KB.kb_movie(tmdb_id, sub_count, back_cb), poster


# ═══════════════════════════════════════════════════════════
# BROADCAST CENTER / SETUP
# ═══════════════════════════════════════════════════════════

async def view_bc_center() -> Tuple[str, InlineKeyboardMarkup]:
    wk = DB.week_key()
    w = await DB.get_week(wk)
    movies = []
    if w:
        for d in (w.get("days") or []):
            movies.extend(d)
    text = "\n".join([
        _header("BROADCAST CENTER"),
        f"🎬 {sc('movies this week')} · <b>{len(movies)}</b>",
        "", DIV2,
        f"📌 {sc('pick a movie to broadcast')}",
        f"📌 {sc('posts to your OTT channel with Notify button')}",
    ])
    return text, KB.kb_bc_center(movies)


async def view_bc_setup(tmdb_id: int, channel: int, notify: bool,
                         hours: int) -> Tuple[str, InlineKeyboardMarkup]:
    movie = await DB.get_movie(tmdb_id) or {}
    title = (movie.get("title") or "?")[:50]
    year = (movie.get("release_date") or "")[:4]
    rating = movie.get("vote_average", 0) or 0
    lang = (movie.get("original_language") or "").upper()

    notify_lbl = "🟢 on" if notify else "🔴 off"
    timer_lbl = "♾️ never" if hours <= 0 else f"⏱️ {hours}h"

    text = "\n".join([
        _header("BROADCAST SETUP"),
        f"🎬 <b>{sc(title)}</b> ({year})",
        f"⭐ <code>{rating:.1f}/10</code> · 🌐 <code>{lang or '—'}</code>",
        "", DIV2,
        f"📢 {sc('channel')} · <code>{channel or '— not set —'}</code>",
        f"🔔 {sc('notify button')} · <b>{notify_lbl}</b>",
        f"🗑️ {sc('auto-delete')} · <b>{timer_lbl}</b>",
        "", DIV2,
        f"📌 {sc('poster + caption + buttons will be sent')}",
        f"📌 {sc('users who tap Notify get DM\\'d when file lands')}",
    ])
    return text, KB.kb_bc_setup(tmdb_id, channel, notify, hours)


async def view_bcsetup_timer(tmdb_id: int, current: int
                              ) -> Tuple[str, InlineKeyboardMarkup]:
    text = "\n".join([
        _header("AUTO-DELETE TIMER"),
        f"📌 {sc('when should the channel post self-delete?')}",
        "", DIV2,
        f"📌 {sc('current')} · "
        f"{('♾️ never' if current <= 0 else f'⏱️ {current}h')}",
        "", DIV2,
        f"📌 {sc('💡 tip')} · {sc('users get the file link via DM')}",
        f"📌 {sc('the channel post is just the announcement')}",
    ])
    return text, KB.kb_bcsetup_timer(tmdb_id, current)


async def view_bc_history() -> Tuple[str, InlineKeyboardMarkup]:
    items = await DB.broadcast_list(limit=15)
    lines = [_header("BROADCAST HISTORY")]
    if not items:
        lines.append(f"⚪ {sc('no broadcasts yet')}")
    else:
        for it in items:
            movie = await DB.get_movie(it.get("tmdb_id")) or {}
            title = (movie.get("title") or "?")[:32]
            cancelled = "💥 CANCELLED" if it.get("cancelled") else "✅"
            lines += [
                f"{cancelled} <b>{sc(title)}</b>",
                f"   🎯 <code>{it.get('target')}</code>",
                f"   📬 <b>{it.get('delivered', 0)}</b> · "
                f"❌ <b>{it.get('failed', 0)}</b>",
                "",
            ]
    return "\n".join(lines)[:4000], KB.kb_bc_history()


# ═══════════════════════════════════════════════════════════
# SUBSCRIBERS
# ═══════════════════════════════════════════════════════════

async def view_subs_overview() -> Tuple[str, InlineKeyboardMarkup]:
    items = await DB.subs_overview(limit=15)
    lines = [_header("SUBSCRIBERS")]
    if not items:
        lines.append(f"⚪ {sc('no subscribers yet')}")
    else:
        lines.append(f"🏆 {sc('top by subs')}")
        lines.append("")
        for it in items:
            title = str(it.get("title") or "?")[:40]
            cnt = it.get("count", 0)
            n = it.get("notified", 0)
            lines.append(f"🎬 <b>{sc(title)}</b>")
            lines.append(f"   🔔 <b>{cnt}</b> · ✅ {n} notified")
    return "\n".join(lines)[:4000], KB.kb_subs_overview(items)


async def view_subs_movie(tmdb_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    movie = await DB.get_movie(tmdb_id) or {}
    subs = await DB.subs_for_movie(tmdb_id, limit=200)
    notified = sum(1 for s in subs if s.get("notified"))
    pending = len(subs) - notified

    title = movie.get("title") or "?"
    bc = await DB.broadcast_get_latest(tmdb_id)
    bc_status = "—"
    if bc:
        if bc.get("cancelled"):
            bc_status = "💥 CANCELLED"
        else:
            bc_status = (
                f"✅ {bc.get('target')} · "
                f"{bc.get('delivered', 0)} delivered"
            )

    lines = [
        _header("SUBSCRIBERS OF MOVIE"),
        f"🎬 <b>{sc(str(title)[:50])}</b>",
        "", DIV2,
        f"📊 {sc('total')} · <b>{len(subs)}</b>",
        f"✅ {sc('notified')} · <b>{notified}</b>",
        f"🔔 {sc('pending')} · <b>{pending}</b>",
        "", DIV2,
        f"📢 {sc('last broadcast')} · {bc_status}",
        "", DIV2,
    ]
    for s in subs[:20]:
        uid = s.get("user_id", 0)
        flag = "✅" if s.get("notified") else "🔔"
        lines.append(f"{flag} <code>{uid}</code>")
    if len(subs) > 20:
        lines.append(f"<i>… +{len(subs) - 20} more</i>")
    return "\n".join(lines)[:4000], KB.kb_subs_movie(tmdb_id)


async def view_cancel_confirm(tmdb_id: int, tok: str
                              ) -> Tuple[str, InlineKeyboardMarkup]:
    movie = await DB.get_movie(tmdb_id) or {}
    title = movie.get("title") or "?"
    count = await DB.count_subs_for_movie(tmdb_id)

    text = "\n".join([
        _header("CONFIRM FULL CANCEL"),
        f"🎬 <b>{sc(str(title)[:50])}</b>",
        "", DIV2,
        f"⚠️ {sc('this will')}:",
        f"• 💥 {sc('delete')} <b>{count}</b> {sc('pending subs')}",
        f"• 🚫 {sc('refuse any future Get Notified for this token')}",
        f"• 🏷️ {sc('flag the broadcast as cancelled')}",
        "", DIV2,
        f"⚠️ {sc('cannot be undone.')}",
    ])
    return text, KB.kb_cancel_confirm(tmdb_id, tok)


# ═══════════════════════════════════════════════════════════
# NOTIFICATIONS / CACHE
# ═══════════════════════════════════════════════════════════

async def view_notif() -> Tuple[str, InlineKeyboardMarkup]:
    sent7 = await DB.sent_count_last(7)
    sent30 = await DB.sent_count_last(30)
    pend = await DB.pending_subs_total()
    pmsg = await DB.pending_count()

    text = "\n".join([
        _header("NOTIFICATIONS"),
        f"📨 {sc('sent 7d')} · <b>{_fmt_int(sent7)}</b>",
        f"📨 {sc('sent 30d')} · <b>{_fmt_int(sent30)}</b>",
        f"🔔 {sc('pending subs')} · <b>{_fmt_int(pend)}</b>",
        f"🗑️ {sc('pending auto-delete msgs')} · <b>{_fmt_int(pmsg)}</b>",
        "", DIV2,
        f"📌 {sc('file checker runs hourly')}",
        f"📌 {sc('windows')} · <code>23-06</code>, <code>12-18</code> {sc('IST')}",
        f"📌 {sc('scans last')} <code>100</code> {sc('files only')}",
    ])
    return text, KB.kb_notif()


async def view_cache() -> Tuple[str, InlineKeyboardMarkup]:
    n = await DB.cache_count()
    text = "\n".join([
        _header("MOVIE CACHE"),
        f"🎬 {sc('cached movies')} · <b>{_fmt_int(n)}</b>",
        "", DIV2,
        f"📌 {sc('TMDB metadata is cached 30 days')}",
    ])
    return text, KB.kb_cache()


# ═══════════════════════════════════════════════════════════
# SETTINGS
# ═══════════════════════════════════════════════════════════

async def view_settings() -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await DB.get_cfg()
    langs = cfg.get("languages") or []
    lang_labels = [LANGUAGE_LABELS.get(x, x.upper()) for x in langs]

    text = "\n".join([
        _header("SETTINGS"),
        f"🌍 {sc('region')} · <code>{cfg.get('region')}</code>",
        f"🌐 {sc('languages')} · "
        f"<code>{','.join(langs) or '—'}</code>",
        f"   <i>{sc(', '.join(lang_labels)[:120] or '—')}</i>",
        f"📢 {sc('OTT channel')} · "
        f"<code>{cfg.get('ott_broadcast_channel') or '—'}</code>",
        f"⭐ {sc('min votes')} · <code>{cfg.get('min_vote_count')}</code>",
        f"🔔 {sc('notify TTL')} · "
        f"<code>{cfg.get('notify_ttl_hours')}h</code>",
        f"📢 {sc('broadcast TTL')} · "
        f"<code>{cfg.get('broadcast_ttl_hours')}h</code>",
        "", DIV2,
        f"🔄 {sc('hype loop')} · "
        f"{'🟢 on' if cfg.get('hype_enabled') else '🔴 off'}",
        f"📅 {sc('weekly loop')} · "
        f"{'🟢 on' if cfg.get('weekly_enabled') else '🔴 off'}",
        f"🔔 {sc('share button')} · "
        f"{'🟢 on' if cfg.get('share_button') else '🔴 off'}",
        f"🗑️ {sc('auto-delete')} · "
        f"{'🟢 on' if cfg.get('auto_delete_broadcast') else '🔴 off'}",
    ])
    return text, KB.kb_settings()


async def view_region() -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await DB.get_cfg()
    text = "\n".join([
        _header("REGION"),
        f"🌍 {sc('current')} · <code>{cfg.get('region')}</code>",
        "", DIV2,
        f"📌 {sc('affects release discovery & streaming providers')}",
    ])
    return text, KB.kb_region(cfg.get("region", "IN"))


async def view_langs() -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await DB.get_cfg()
    langs = cfg.get("languages") or []
    text = "\n".join([
        _header("LANGUAGES"),
        f"🌐 {sc('selected')} · <code>{','.join(langs) or '—'}</code>",
        "", DIV2,
        f"📌 {sc('priority order')} · "
        f"<code>ML → TA → EN → HI</code>",
        f"📌 {sc('tap a code to toggle')}",
    ])
    return text, KB.kb_langs(langs)


async def view_minvote() -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await DB.get_cfg()
    text = "\n".join([
        _header("MIN VOTES"),
        f"⭐ {sc('current')} · <code>{cfg.get('min_vote_count')}</code>",
    ])
    return text, KB.kb_minvote(int(cfg.get("min_vote_count", 5)))


async def view_notifttl() -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await DB.get_cfg()
    text = "\n".join([
        _header("NOTIFY TTL"),
        f"🔔 {sc('current')} · <code>{cfg.get('notify_ttl_hours')}h</code>",
        "", DIV2,
        f"📌 {sc('how long NOW AVAILABLE messages persist')}",
    ])
    return text, KB.kb_notifttl(int(cfg.get("notify_ttl_hours", 12)))


async def view_bcttl() -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await DB.get_cfg()
    text = "\n".join([
        _header("BROADCAST TTL"),
        f"📢 {sc('current')} · <code>{cfg.get('broadcast_ttl_hours')}h</code>",
        "", DIV2,
        f"📌 {sc('how long broadcast messages persist')}",
    ])
    return text, KB.kb_bcttl(int(cfg.get("broadcast_ttl_hours", 24)))


# ═══════════════════════════════════════════════════════════
# DIAGNOSTICS
# ═══════════════════════════════════════════════════════════

async def view_diag() -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await DB.get_cfg()
    tmdb_ok = False
    try:
        from core import config as _cfg
        tmdb_ok = bool(getattr(_cfg, "TMDB_API_KEY", None))
    except Exception:
        pass

    db_ok = DB._db() is not None
    wk = DB.week_key()
    w = await DB.get_week(wk)

    ch_ok = False
    ch_id = 0
    try:
        ch_id = int(cfg.get("ott_broadcast_channel") or 0)
        ch_ok = ch_id != 0
    except Exception:
        pass

    now_ist = DB.datetime.now(DB.IST).strftime("%H:%M IST")

    text = "\n".join([
        _header("DIAGNOSTICS"),
        f"🔑 {sc('TMDB key')} · "
        f"{'🟢 set' if tmdb_ok else '🔴 missing'}",
        f"🗄️ {sc('system DB')} · "
        f"{'🟢 online' if db_ok else '🔴 offline'}",
        f"📺 {sc('OTT channel')} · "
        f"{('🟢 ' + str(ch_id)) if ch_ok else '⚪ none'}",
        f"📅 {sc('week data')} · "
        f"{'🟢 loaded' if w else '⚪ not fetched'}",
        f"🌍 {sc('region')} · <code>{cfg.get('region')}</code>",
        f"🌐 {sc('langs')} · "
        f"<code>{','.join(cfg.get('languages') or [])}</code>",
        "", DIV2,
        f"⏰ {sc('now')} · <code>{now_ist}</code>",
        f"🕐 {sc('weekly fires')} · "
        f"<code>Mon 10:00 → admin PM</code>",
        f"🕐 {sc('file checker')} · "
        f"<code>23-06 & 12-18 · hourly · 100 files</code>",
        f"🕐 {sc('hype loop')} · <code>20:00 IST</code>",
    ])
    return text, KB.kb_diag()


__all__ = [
    "safe_edit",
    "view_home", "view_dashboard", "view_week", "view_day",
    "view_movie",
    "view_bc_center", "view_bc_setup", "view_bcsetup_timer",
    "view_bc_history",
    "view_subs_overview", "view_subs_movie", "view_cancel_confirm",
    "view_notif", "view_cache",
    "view_settings", "view_region", "view_langs", "view_minvote",
    "view_notifttl", "view_bcttl", "view_diag",
]
