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
    fb, sc, _esc, _fmt_int, _fmt_duration, DIV, DIV2,
)
from plugins.ott import database as DB
from plugins.ott import keyboards as KB
from plugins.ott.config import LANGUAGE_LABELS, PRIMARY_LANGS

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
# HOME
# ═══════════════════════════════════════════════════════════

async def view_home() -> Tuple[str, InlineKeyboardMarkup]:
    pending = await DB.pending_subs_total()
    bc7 = await DB.broadcast_recent_count(7)

    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📅 <b>{fb('OTT CONTROL CENTER')}</b>",
        DIV, "",
        f"🎬 {sc('pick a language to browse OTT releases')}",
        "",
        DIV2,
        f"🔔 {sc('pending subscribers')} · <b>{_fmt_int(pending)}</b>",
        f"📢 {sc('broadcasts 7d')} · <b>{_fmt_int(bc7)}</b>",
        "", DIV2,
        f"📌 {sc('only OTT/digital releases are shown')}",
        f"📌 {sc('all data lives in SYSTEM db')}",
    ])
    return text, KB.kb_home()


# ═══════════════════════════════════════════════════════════
# LANGUAGE MENU
# ═══════════════════════════════════════════════════════════

async def view_lang(lang: str) -> Tuple[str, InlineKeyboardMarkup]:
    from plugins.ott.tmdb import fetch_ott_by_language

    if lang == "all":
        label = "🌐 All Languages"
    else:
        label = f"🎬 {LANGUAGE_LABELS.get(lang, lang.upper())}"

    cfg = await DB.get_cfg()
    movies = await fetch_ott_by_language(
        lang=lang,
        region=cfg.get("region", "IN"),
        min_vote=int(cfg.get("min_vote_count", 5)),
        limit=40,
    )

    lines = [
        _header("OTT RELEASES"),
        f"{label}",
        f"📊 {sc('found')} · <b>{len(movies)}</b>",
        "", DIV2,
        "",
    ]
    for m in movies[:15]:
        title = str(m.get("title", "?"))[:45]
        year = (m.get("release_date") or "")[:4]
        rating = m.get("vote_average", 0)
        lines.append(f"🎬 <b>{sc(title)}</b> ({year})")
        if rating:
            lines.append(f"   ⭐ <code>{rating:.1f}</code>")
    if not movies:
        lines.append(f"⚪ {sc('no OTT releases found')}")

    return "\n".join(lines)[:4000], KB.kb_lang_movies(lang, movies)


# ═══════════════════════════════════════════════════════════
# MOVIE CARD
# ═══════════════════════════════════════════════════════════

async def view_movie(tmdb_id: int, back_cb: str = "ott:home"
                     ) -> Tuple[str, InlineKeyboardMarkup, Optional[str]]:
    from plugins.ott.tmdb import enrich_movie, poster_url

    raw = await DB.get_movie(tmdb_id) or {"tmdb_id": tmdb_id, "title": "?"}
    movie = await enrich_movie(raw)
    stats = await DB.movie_stats(tmdb_id)

    title = movie.get("title") or "?"
    year = (movie.get("release_date") or "")[:4]
    rating = movie.get("vote_average", 0) or 0
    votes = movie.get("vote_count", 0) or 0
    runtime = movie.get("runtime", 0) or 0
    genres = (movie.get("genres") or "—")[:60]
    overview = (movie.get("overview") or "")[:400]
    provider = movie.get("provider") or "—"
    lang = (movie.get("original_language") or "").upper()
    release_date = movie.get("release_date") or "—"

    rr = movie.get("region_release") or {}
    rel_date = rr.get("date") or release_date
    rel_type = rr.get("type") or "—"
    cert = rr.get("certification") or ""
    ended = stats.get("ended")

    lines = [
        f"🎬 <b>{sc(str(title)[:60])}</b> ({year})",
        DIV, "",
        # ── DATE + PLATFORM block (the important one) ──
        f"📅 <b>{sc('RELEASES')}</b> · <code>{rel_date}</code>",
        f"📺 <b>{sc('PLATFORM')}</b> · <b>{sc(provider)}</b>",
        f"🏷️ {sc('type')} · <code>{rel_type}</code>"
        + (f" · 🔒 <code>{cert}</code>" if cert else ""),
        f"🌐 {sc('language')} · <code>{lang or '—'}</code>",
        "",
        DIV2,
        f"⭐ {sc('rating')} · <code>{rating:.1f}/10</code> "
        f"(<code>{_fmt_int(votes)}</code>)",
        f"🎭 {sc('genres')} · <code>{sc(genres)}</code>",
        f"⏱️ {sc('runtime')} · <code>{runtime} min</code>",
        "", DIV2,
        f"🔔 {sc('subscribers')} · <b>{stats['total_subs']}</b>",
        f"✅ {sc('notified')} · <b>{stats['notified']}</b>",
        f"⏳ {sc('pending')} · <b>{stats['pending']}</b>",
        f"📥 {sc('files sent')} · <b>{stats['files_sent']}</b>",
    ]
    if ended:
        lines += ["", f"💥 <b>{sc('EVENT ENDED')}</b>"]
    if overview:
        lines += ["", f"📖 <b>{sc('plot')}</b>", f"<i>{sc(overview)}</i>"]

    poster = poster_url(movie.get("poster_path"), "w500")
    is_bc = bool(stats.get("broadcast"))
    kb = KB.kb_movie(tmdb_id, stats["total_subs"], is_bc, back_cb)
    return "\n".join(lines)[:4000], kb, poster

# ═══════════════════════════════════════════════════════════
# BROADCAST SETUP
# ═══════════════════════════════════════════════════════════

async def view_bc_setup(tmdb_id: int, channel: int, notify: bool,
                         hours: int, show_file: bool = True
                         ) -> Tuple[str, InlineKeyboardMarkup]:
    movie = await DB.get_movie(tmdb_id) or {}
    title = (movie.get("title") or "?")[:50]
    year = (movie.get("release_date") or "")[:4]
    rating = movie.get("vote_average", 0) or 0
    lang = (movie.get("original_language") or "").upper()

    notify_lbl = "🟢 on" if notify else "🔴 off"
    file_lbl = "🟢 on" if show_file else "🔴 off"
    timer_lbl = "♾️ never" if hours <= 0 else f"⏱️ {hours}h"

    text = "\n".join([
        _header("BROADCAST SETUP"),
        f"🎬 <b>{sc(title)}</b> ({year})",
        f"⭐ <code>{rating:.1f}/10</code> · 🌐 <code>{lang or '—'}</code>",
        "", DIV2,
        f"📢 {sc('channel')} · <code>{channel or '— not set —'}</code>",
        f"🔔 {sc('notify button')} · <b>{notify_lbl}</b>",
        f"📥 {sc('get file button')} · <b>{file_lbl}</b>",
        f"🗑️ {sc('auto-delete')} · <b>{timer_lbl}</b>",
        "", DIV2,
        f"📌 {sc('poster + caption + buttons under it')}",
        f"📌 {sc('users tap Notify → saved → DM-ed when file lands')}",
    ])
    return text, KB.kb_bc_setup(tmdb_id, channel, notify, hours, show_file)


async def view_bcsetup_timer(tmdb_id: int, current: int
                              ) -> Tuple[str, InlineKeyboardMarkup]:
    text = "\n".join([
        _header("AUTO-DELETE TIMER"),
        f"📌 {sc('when should the channel post self-delete?')}",
        "", DIV2,
        f"📌 {sc('current')} · "
        f"{('♾️ never' if current <= 0 else f'⏱️ {current}h')}",
        "", DIV2,
        f"📌 {sc('💡 users still get the file via DM')}",
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
            cancelled = "💥 ENDED" if it.get("cancelled") else "✅"
            lines += [
                f"{cancelled} <b>{sc(title)}</b>",
                f"   🎯 <code>{it.get('target')}</code>",
                f"   📬 <b>{it.get('delivered', 0)}</b> · "
                f"❌ <b>{it.get('failed', 0)}</b>",
                "",
            ]
    return "\n".join(lines)[:4000], KB.kb_bc_history()


async def view_bc_center() -> Tuple[str, InlineKeyboardMarkup]:
    w = await DB.get_week(DB.week_key())
    movies = []
    if w:
        for d in (w.get("days") or []):
            movies.extend(d)
    text = "\n".join([
        _header("BROADCAST CENTER"),
        f"🎬 {sc('movies this week')} · <b>{len(movies)}</b>",
        "", DIV2,
        f"📌 {sc('pick a movie to post to channel')}",
    ])
    return text, KB.kb_bc_center(movies)


# ═══════════════════════════════════════════════════════════
# STATS
# ═══════════════════════════════════════════════════════════

async def view_stats(tmdb_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    movie = await DB.get_movie(tmdb_id) or {}
    stats = await DB.movie_stats(tmdb_id)
    title = (movie.get("title") or "?")[:50]

    bc = stats.get("broadcast") or {}
    bc_line = "—"
    if bc:
        bc_line = (
            f"{'💥 ENDED' if bc.get('cancelled') else '✅ ACTIVE'} · "
            f"<code>{bc.get('target')}</code>"
        )

    text = "\n".join([
        _header("STATISTICS"),
        f"🎬 <b>{sc(title)}</b>",
        "", DIV2,
        f"🔔 {sc('total subscribers')} · <b>{stats['total_subs']}</b>",
        f"✅ {sc('notified')} · <b>{stats['notified']}</b>",
        f"⏳ {sc('still pending')} · <b>{stats['pending']}</b>",
        f"📥 {sc('files sent')} · <b>{stats['files_sent']}</b>",
        "", DIV2,
        f"📢 {sc('broadcast')} · {bc_line}",
        "", DIV2,
        f"📌 {sc('press END EVENT to wipe all tokens')}",
    ])
    return text, KB.kb_stats(tmdb_id)


async def view_end_confirm(tmdb_id: int, tok: str
                            ) -> Tuple[str, InlineKeyboardMarkup]:
    movie = await DB.get_movie(tmdb_id) or {}
    title = (movie.get("title") or "?")[:50]
    stats = await DB.movie_stats(tmdb_id)

    text = "\n".join([
        _header("CONFIRM END EVENT"),
        f"🎬 <b>{sc(title)}</b>",
        "", DIV2,
        f"⚠️ {sc('this will')}:",
        f"• 💥 {sc('delete')} <b>{stats['pending']}</b> {sc('pending tokens')}",
        f"• 🚫 {sc('block new Get Notified taps')}",
        f"• 🏷️ {sc('mark broadcast as ENDED')}",
        f"• ✅ {sc('keep')} <b>{stats['notified']}</b> {sc('notified users')}",
        "", DIV2,
        f"⚠️ {sc('cannot be undone.')}",
    ])
    return text, KB.kb_end_confirm(tmdb_id, tok)


# ═══════════════════════════════════════════════════════════
# SUBSCRIBERS
# ═══════════════════════════════════════════════════════════

async def view_subs_overview() -> Tuple[str, InlineKeyboardMarkup]:
    items = await DB.subs_overview(limit=15)
    lines = [_header("SUBSCRIBERS")]
    if not items:
        lines.append(f"⚪ {sc('no subscribers yet')}")
    else:
        for it in items:
            title = str(it.get("title") or "?")[:40]
            cnt = it.get("count", 0)
            n = it.get("notified", 0)
            lines.append(f"🎬 <b>{sc(title)}</b>")
            lines.append(f"   🔔 <b>{cnt}</b> · ✅ {n}")
    return "\n".join(lines)[:4000], KB.kb_subs_overview(items)


async def view_subs_movie(tmdb_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    movie = await DB.get_movie(tmdb_id) or {}
    subs = await DB.subs_for_movie(tmdb_id, limit=200)
    notified = sum(1 for s in subs if s.get("notified"))
    pending = len(subs) - notified
    title = (movie.get("title") or "?")[:50]

    lines = [
        _header("SUBSCRIBERS OF MOVIE"),
        f"🎬 <b>{sc(title)}</b>",
        "", DIV2,
        f"📊 {sc('total')} · <b>{len(subs)}</b>",
        f"✅ {sc('notified')} · <b>{notified}</b>",
        f"🔔 {sc('pending')} · <b>{pending}</b>",
        "", DIV2,
    ]
    for s in subs[:20]:
        uid = s.get("user_id", 0)
        flag = "✅" if s.get("notified") else "🔔"
        lines.append(f"{flag} <code>{uid}</code>")
    if len(subs) > 20:
        lines.append(f"<i>… +{len(subs) - 20} more</i>")
    return "\n".join(lines)[:4000], KB.kb_subs_movie(tmdb_id)


# ═══════════════════════════════════════════════════════════
# NOTIFICATIONS / CACHE / SETTINGS / DIAG
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
        f"📌 {sc('file checker')} · <code>23-06 & 12-18 IST hourly</code>",
        f"📌 {sc('scans last 100 files')}",
    ])
    return text, KB.kb_notif()


async def view_cache() -> Tuple[str, InlineKeyboardMarkup]:
    n = await DB.cache_count()
    text = "\n".join([
        _header("MOVIE CACHE"),
        f"🎬 {sc('cached movies')} · <b>{_fmt_int(n)}</b>",
        "", DIV2,
        f"📌 {sc('TMDB metadata cached 30 days')}",
    ])
    return text, KB.kb_cache()


async def view_settings() -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await DB.get_cfg()
    langs = cfg.get("languages") or []
    lang_labels = [LANGUAGE_LABELS.get(x, x.upper()) for x in langs]

    text = "\n".join([
        _header("SETTINGS"),
        f"🌍 {sc('region')} · <code>{cfg.get('region')}</code>",
        f"🌐 {sc('languages')} · <code>{','.join(langs) or '—'}</code>",
        f"   <i>{sc(', '.join(lang_labels)[:120] or '—')}</i>",
        f"📢 {sc('OTT channel')} · "
        f"<code>{cfg.get('ott_broadcast_channel') or '—'}</code>",
        f"⭐ {sc('min votes')} · <code>{cfg.get('min_vote_count')}</code>",
        f"🔔 {sc('notify TTL')} · <code>{cfg.get('notify_ttl_hours')}h</code>",
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
        f"📌 {sc('affects release discovery & providers')}",
    ])
    return text, KB.kb_region(cfg.get("region", "IN"))


async def view_langs() -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await DB.get_cfg()
    langs = cfg.get("languages") or []
    text = "\n".join([
        _header("LANGUAGES"),
        f"🌐 {sc('selected')} · <code>{','.join(langs) or '—'}</code>",
        "", DIV2,
        f"📌 {sc('priority')} · <code>ML → TA → EN → HI</code>",
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
        f"📌 {sc('how long NOW AVAILABLE msgs persist')}",
    ])
    return text, KB.kb_notifttl(int(cfg.get("notify_ttl_hours", 12)))


async def view_bcttl() -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await DB.get_cfg()
    text = "\n".join([
        _header("BROADCAST TTL"),
        f"📢 {sc('current')} · <code>{cfg.get('broadcast_ttl_hours')}h</code>",
    ])
    return text, KB.kb_bcttl(int(cfg.get("broadcast_ttl_hours", 24)))


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

    ch_id = int(cfg.get("ott_broadcast_channel") or 0)
    now_ist = DB.datetime.now(DB.IST).strftime("%H:%M IST")

    text = "\n".join([
        _header("DIAGNOSTICS"),
        f"🔑 {sc('TMDB key')} · "
        f"{'🟢 set' if tmdb_ok else '🔴 missing'}",
        f"🗄️ {sc('system DB')} · "
        f"{'🟢 online' if db_ok else '🔴 offline'}",
        f"📺 {sc('OTT channel')} · "
        f"{('🟢 ' + str(ch_id)) if ch_id else '⚪ none'}",
        f"📅 {sc('week data')} · "
        f"{'🟢 loaded' if w else '⚪ not fetched'}",
        f"🌍 {sc('region')} · <code>{cfg.get('region')}</code>",
        f"🌐 {sc('langs')} · "
        f"<code>{','.join(cfg.get('languages') or [])}</code>",
        "", DIV2,
        f"⏰ {sc('now')} · <code>{now_ist}</code>",
        f"🕐 {sc('weekly fires')} · <code>Mon 10:00 → admin PM</code>",
        f"🕐 {sc('file checker')} · "
        f"<code>23-06 & 12-18 · hourly · 100 files</code>",
    ])
    return text, KB.kb_diag()


__all__ = [
    "safe_edit",
    "view_home", "view_lang", "view_movie",
    "view_bc_setup", "view_bcsetup_timer", "view_bc_history",
    "view_bc_center",
    "view_stats", "view_end_confirm",
    "view_subs_overview", "view_subs_movie",
    "view_notif", "view_cache",
    "view_settings", "view_region", "view_langs", "view_minvote",
    "view_notifttl", "view_bcttl", "view_diag",
]
