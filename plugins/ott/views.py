# ============================================================
# 🏨 DOWNTOWN VILLA — OTT VIEWS
# ============================================================

from __future__ import annotations
import logging
import datetime as _dt
from typing import Any, Dict, List, Optional, Tuple

from pyrogram.enums import ParseMode
from pyrogram.errors import MessageNotModified
from pyrogram.types import InlineKeyboardMarkup

from plugins.ott.config import (
    fb, sc, _esc, _fmt_int, DIV, DIV2,
    LANGUAGE_LABELS, FREQ_DAYS,
)
from plugins.ott import keyboards as KB
from plugins.ott import database as DB

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


def _week_range():
    now = _dt.datetime.now()
    mon = (now - _dt.timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0)
    sun = mon + _dt.timedelta(days=6)
    return mon, sun


def _header(title: str) -> str:
    return "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📅 <b>{fb(title)}</b>",
        DIV, "",
    ])


def _freq_label(freq: Dict[str, Any]) -> str:
    mode = freq.get("mode") or "off"
    if mode == "off":
        return "OFF"
    hour = freq.get("hour") or 0
    if mode == "daily":
        return f"DAILY · {hour:02d}:00"
    if mode == "weekly":
        d = int(freq.get("day_of_week") or 0)
        return f"WEEKLY · {FREQ_DAYS[d]} · {hour:02d}:00"
    if mode == "monthly":
        dm = int(freq.get("day_of_month") or 1)
        return f"MONTHLY · {dm} · {hour:02d}:00"
    return "OFF"


def _fmt_langs(langs: List[str]) -> str:
    return ",".join(x.upper() for x in langs) if langs else "NONE"


# ═══════════════════════════════════════════════════════════
# HOME
# ═══════════════════════════════════════════════════════════

async def view_home() -> Tuple[str, InlineKeyboardMarkup]:
    mon, sun = _week_range()
    fav = await DB.get_fav_languages()

    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📅 <b>{fb('OTT RELEASES')}</b>",
        DIV, "",
        f"🗓️ {sc('this week')} · "
        f"<code>{mon.strftime('%d %b')} → {sun.strftime('%d %b')}</code>",
        "",
        f"🎬 {sc('pick a language to see this week movies')}",
        "",
        DIV2,
        f"📌 {sc('only this week OTT releases')}",
        f"📌 {sc('updated live from TMDB')}",
    ])
    return text, KB.kb_home(fav)


# ═══════════════════════════════════════════════════════════
# LANGUAGE VIEW
# ═══════════════════════════════════════════════════════════

async def view_lang(lang: str) -> Tuple[str, InlineKeyboardMarkup]:
    from plugins.ott.tmdb import fetch_week_grouped_by_lang
    grouped = await fetch_week_grouped_by_lang(
        lang=lang, region="IN", min_vote=0)

    mon, sun = _week_range()
    counts = [len(grouped.get(i, [])) for i in range(7)]
    total = sum(counts)
    label = ("🌐 ALL LANGUAGES" if lang == "all"
             else f"🎬 {LANGUAGE_LABELS.get(lang, lang.upper())}")

    day_names = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY",
                 "FRIDAY", "SATURDAY", "SUNDAY"]

    lines = [
        _header("THIS WEEK"),
        f"{label}",
        f"🗓️ <code>{mon.strftime('%d %b')} → {sun.strftime('%d %b %Y')}</code>",
        f"📊 {sc('total')} · <b>{total}</b>",
        "", DIV2, "",
    ]
    if total == 0:
        lines.append(f"⚪ {sc('no releases this week')}")
    else:
        for i in range(7):
            day_date = mon + _dt.timedelta(days=i)
            c = counts[i]
            lines.append(
                f"📅 <b>{day_names[i]}</b> · "
                f"<code>{day_date.strftime('%d %b')}</code> · <b>{c}</b>"
            )
            for m in grouped.get(i, [])[:5]:
                title = str(m.get("title", "?"))[:42]
                rating = m.get("vote_average", 0) or 0
                r_str = f" ⭐{rating:.1f}" if rating else ""
                lines.append(f"   🎬 {sc(title)}{r_str}")
            if c > 5:
                lines.append(f"   <i>… +{c - 5} more</i>")
            lines.append("")

    return "\n".join(lines)[:4000], KB.kb_lang(lang, counts)


async def view_day(lang: str, day_idx: int
                    ) -> Tuple[str, InlineKeyboardMarkup]:
    from plugins.ott.tmdb import fetch_week_grouped_by_lang
    grouped = await fetch_week_grouped_by_lang(
        lang=lang, region="IN", min_vote=0)
    movies = grouped.get(day_idx, [])

    mon, _ = _week_range()
    day_date = mon + _dt.timedelta(days=day_idx)
    day_names = ["MONDAY", "TUESDAY", "WEDNESDAY", "THURSDAY",
                 "FRIDAY", "SATURDAY", "SUNDAY"]
    day_name = day_names[day_idx] if 0 <= day_idx <= 6 else "?"
    label = ("🌐 ALL LANGUAGES" if lang == "all"
             else f"🎬 {LANGUAGE_LABELS.get(lang, lang.upper())}")

    lines = [
        _header(f"{day_name} · THIS WEEK"),
        f"{label}",
        f"🗓️ <code>{day_date.strftime('%d %b %Y')}</code>",
        f"📊 {sc('movies')} · <b>{len(movies)}</b>",
        "", DIV2, "",
    ]
    if not movies:
        lines.append(f"⚪ {sc('no releases on this day')}")
    else:
        for i, m in enumerate(movies[:25], 1):
            title = str(m.get("title", "?"))[:50]
            year = (m.get("release_date") or "")[:4]
            rating = m.get("vote_average", 0) or 0
            lang_ = (m.get("original_language") or "").upper()
            lines.append(f"<b>{i:02d}.</b> 🎬 <b>{sc(title)}</b> ({year})")
            meta = []
            if rating:
                meta.append(f"⭐ {rating:.1f}")
            if lang_:
                meta.append(f"🌐 {lang_}")
            if meta:
                lines.append(f"   <code>{' · '.join(meta)}</code>")

    return "\n".join(lines)[:4000], KB.kb_day(lang, day_idx, movies)


# ═══════════════════════════════════════════════════════════
# MOVIE CARD
# ═══════════════════════════════════════════════════════════

async def view_movie(tmdb_id: int, lang: str, day_idx: int
                     ) -> Tuple[str, InlineKeyboardMarkup, Optional[str]]:
    from plugins.ott.tmdb import enrich_movie, poster_url

    movie = await enrich_movie({"tmdb_id": tmdb_id})

    title = movie.get("title") or "?"
    year = (movie.get("release_date") or "")[:4]
    rating = movie.get("vote_average", 0) or 0
    votes = movie.get("vote_count", 0) or 0
    runtime = movie.get("runtime", 0) or 0
    genres = (movie.get("genres") or "—")[:70]
    overview = (movie.get("overview") or "")[:500]
    provider = movie.get("provider") or "—"
    lang_code = (movie.get("original_language") or "").upper()
    imdb_id = movie.get("imdb_id") or ""
    rr = movie.get("region_release") or {}
    rel_date = rr.get("date") or movie.get("release_date") or "—"
    rel_type = rr.get("type") or "Digital"
    cert = rr.get("certification") or ""

    lines = [
        f"🎬 <b>{sc(str(title)[:70])}</b> ({year})",
        DIV, "",
        f"📅 <b>{sc('RELEASES')}</b> · <code>{rel_date}</code>",
        f"📺 <b>{sc('PLATFORM')}</b> · <b>{sc(provider)}</b>",
        f"🏷️ {sc('type')} · <code>{rel_type}</code>"
        + (f" · 🔒 <code>{cert}</code>" if cert else ""),
        f"🌐 {sc('language')} · <code>{lang_code or '—'}</code>",
    ]
    if imdb_id:
        lines.append(
            f"🔗 <b>IMDb</b> · "
            f"<a href=\"https://www.imdb.com/title/{imdb_id}/\">"
            f"{imdb_id}</a>"
        )
    lines += [
        "", DIV2,
        f"⭐ {sc('rating')} · <code>{rating:.1f}/10</code> "
        f"(<code>{_fmt_int(votes)}</code>)",
        f"🎭 {sc('genres')} · <code>{sc(genres)}</code>",
        f"⏱️ {sc('runtime')} · <code>{runtime} min</code>",
    ]
    if overview:
        lines += ["", DIV2, "", f"📖 <b>{sc('PLOT')}</b>",
                  f"<i>{sc(overview)}</i>"]

    poster = poster_url(movie.get("poster_path"), "w500")
    kb = KB.kb_movie(lang, day_idx)
    return "\n".join(lines)[:4000], kb, poster


# ═══════════════════════════════════════════════════════════
# SETTINGS
# ═══════════════════════════════════════════════════════════

async def view_settings() -> Tuple[str, InlineKeyboardMarkup]:
    fav = await DB.get_fav_languages()
    live_ch = await DB.get_live_channels()
    live_gr = await DB.get_live_groups()
    en_ch = await DB.get_enabled_channels()
    en_gr = await DB.get_enabled_groups()
    us = await DB.get_users()
    pm = await DB.get_premium()

    text = "\n".join([
        _header("SETTINGS"),
        f"🌐 {sc('favorite languages')} · <b>{len(fav)}</b>",
        f"📢 {sc('channels in bot')} · <b>{len(live_ch)}</b>",
        f"   ✅ {sc('enabled for OTT')} · <b>{len(en_ch)}</b>",
        f"👥 {sc('groups in bot')} · <b>{len(live_gr)}</b>",
        f"   ✅ {sc('enabled for OTT')} · <b>{len(en_gr)}</b>",
        f"👤 {sc('send to users')} · "
        f"{'🟢 ON' if us.get('running') else '🔴 OFF'}",
        f"💎 {sc('send to premium')} · "
        f"{'🟢 ON' if pm.get('running') else '🔴 OFF'}",
        "", DIV2,
        f"📌 {sc('channels/groups come from bot DB')}",
    ])
    kb = KB.kb_settings(len(live_ch), len(live_gr),
                        us.get("running"), pm.get("running"),
                        len(fav))
    return text, kb


# ═══════════════════════════════════════════════════════════
# FAVORITE LANGUAGES
# ═══════════════════════════════════════════════════════════

async def view_fav_langs() -> Tuple[str, InlineKeyboardMarkup]:
    fav = await DB.get_fav_languages()
    lines = [
        _header("FAVORITE LANGUAGES"),
        f"📌 {sc('these appear as buttons on home')}",
        "",
        DIV2, "",
    ]
    for code in fav:
        lines.append(f"✅ {sc(LANGUAGE_LABELS.get(code, code.upper()))}")
    if not fav:
        lines.append(f"⚪ {sc('none selected')}")
    return "\n".join(lines), KB.kb_fav_langs(fav)


# ═══════════════════════════════════════════════════════════
# CHANNELS
# ═══════════════════════════════════════════════════════════

async def view_ch_list() -> Tuple[str, InlineKeyboardMarkup]:
    channels = await DB.get_live_channels()
    enabled = await DB.get_enabled_channels()

    lines = [_header("OTT UPDATE CHANNELS")]
    lines.append(f"📢 {sc('total in bot')} · <b>{len(channels)}</b>")
    lines.append(f"✅ {sc('enabled for OTT')} · <b>{len(enabled)}</b>")
    lines.append("")
    lines.append(DIV2)
    lines.append("")

    if not channels:
        lines.append(f"⚪ {sc('no channels in bot DB yet')}")
        lines.append("")
        lines.append(f"📌 {sc('use')} <b>/broadcast</b> {sc('to add')}")
    else:
        for c in channels[:20]:
            cid = int(c["chat_id"])
            mark = "✅" if cid in enabled else "☐"
            lines.append(f"{mark} 📢 <b>{_esc(c['title'])}</b>")
            lines.append(f"   <code>{cid}</code>")

    return "\n".join(lines)[:4000], KB.kb_ch_list(channels, enabled)


async def view_channel(cid: int) -> Tuple[str, InlineKeyboardMarkup]:
    live = await DB.get_live_channels()
    title = None
    for c in live:
        if int(c["chat_id"]) == int(cid):
            title = c["title"]
            break
    if title is None:
        return (f"❌ {sc('channel not found')}",
                KB.kb_ch_list(live, []))

    cfg = await DB.get_channel_config(cid)
    running = bool(cfg.get("running"))

    lines = [
        _header("CHANNEL CONFIG"),
        f"📢 <b>{_esc(title)}</b>",
        f"🆔 <code>{cid}</code>",
        "", DIV2,
        f"🔘 {sc('status')} · "
        f"{'🟢 RUNNING' if running else '🔴 STOPPED'}",
        f"🌐 {sc('languages')} · "
        f"<code>{_fmt_langs(cfg.get('languages') or [])}</code>",
        f"⏰ {sc('frequency')} · "
        f"<code>{_freq_label(cfg.get('frequency') or {})}</code>",
    ]
    return "\n".join(lines), KB.kb_channel(cid, cfg, running)


async def view_ch_langs(cid: int) -> Tuple[str, InlineKeyboardMarkup]:
    live = await DB.get_live_channels()
    title = next((c["title"] for c in live
                  if int(c["chat_id"]) == int(cid)), str(cid))
    cfg = await DB.get_channel_config(cid)
    langs = cfg.get("languages") or []

    lines = [
        _header("CHANNEL LANGUAGES"),
        f"📢 <b>{_esc(title)}</b>",
        "", DIV2,
        f"📌 {sc('only selected languages will be sent')}",
        "",
    ]
    if not langs:
        lines.append(f"⚪ {sc('none selected')}")
    else:
        for code in langs:
            lines.append(
                f"✅ {sc(LANGUAGE_LABELS.get(code, code.upper()))}")
    return "\n".join(lines), KB.kb_ch_langs(cid, langs)


async def view_ch_freq(cid: int) -> Tuple[str, InlineKeyboardMarkup]:
    live = await DB.get_live_channels()
    title = next((c["title"] for c in live
                  if int(c["chat_id"]) == int(cid)), str(cid))
    cfg = await DB.get_channel_config(cid)
    freq = cfg.get("frequency") or {}
    mode = freq.get("mode") or "off"

    lines = [
        _header("CHANNEL FREQUENCY"),
        f"📢 <b>{_esc(title)}</b>",
        "", DIV2,
        f"⏰ {sc('current')} · <code>{_freq_label(freq)}</code>",
        "", DIV2,
        f"📌 {sc('pick a mode')}",
    ]
    return "\n".join(lines), KB.kb_ch_freq(cid, mode)


async def view_ch_hours(cid: int, mode: str
                         ) -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await DB.get_channel_config(cid)
    hour = int((cfg.get("frequency") or {}).get("hour") or 10)
    lines = [
        _header(f"{mode.upper()} · HOUR"),
        f"📌 {sc('current')} · <code>{hour:02d}:00</code>",
        "", f"📌 {sc('pick hour (IST)')}",
    ]
    return "\n".join(lines), KB.kb_hours(cid, hour, "ch")


async def view_ch_days(cid: int) -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await DB.get_channel_config(cid)
    day = int((cfg.get("frequency") or {}).get("day_of_week") or 0)
    lines = [
        _header("WEEKLY · DAY"),
        f"📌 {sc('current')} · <code>{FREQ_DAYS[day]}</code>",
        "", f"📌 {sc('pick day of week')}",
    ]
    return "\n".join(lines), KB.kb_days(cid, day, "ch")


async def view_ch_month_days(cid: int
                               ) -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await DB.get_channel_config(cid)
    d = int((cfg.get("frequency") or {}).get("day_of_month") or 1)
    lines = [
        _header("MONTHLY · DAY"),
        f"📌 {sc('current')} · <code>{d}</code>",
        "", f"📌 {sc('pick day of month')}",
    ]
    return "\n".join(lines), KB.kb_month_days(cid, d, "ch")


# ═══════════════════════════════════════════════════════════
# GROUPS
# ═══════════════════════════════════════════════════════════

async def view_gr_list() -> Tuple[str, InlineKeyboardMarkup]:
    groups = await DB.get_live_groups()
    enabled = await DB.get_enabled_groups()

    lines = [_header("OTT UPDATE GROUPS")]
    lines.append(f"👥 {sc('total in bot')} · <b>{len(groups)}</b>")
    lines.append(f"✅ {sc('enabled for OTT')} · <b>{len(enabled)}</b>")
    lines.append("")
    lines.append(DIV2)
    lines.append("")

    if not groups:
        lines.append(f"⚪ {sc('no groups in bot DB yet')}")
    else:
        for g in groups[:20]:
            gid = int(g["chat_id"])
            mark = "✅" if gid in enabled else "☐"
            lines.append(f"{mark} 👥 <b>{_esc(g['title'])}</b>")
            lines.append(f"   <code>{gid}</code>")

    return "\n".join(lines)[:4000], KB.kb_gr_list(groups, enabled)


async def view_group(gid: int) -> Tuple[str, InlineKeyboardMarkup]:
    live = await DB.get_live_groups()
    title = next((g["title"] for g in live
                  if int(g["chat_id"]) == int(gid)), None)
    if title is None:
        return (f"❌ {sc('group not found')}",
                KB.kb_gr_list(live, []))

    cfg = await DB.get_group_config(gid)
    running = bool(cfg.get("running"))

    lines = [
        _header("GROUP CONFIG"),
        f"👥 <b>{_esc(title)}</b>",
        f"🆔 <code>{gid}</code>",
        "", DIV2,
        f"🔘 {sc('status')} · "
        f"{'🟢 RUNNING' if running else '🔴 STOPPED'}",
        f"🌐 {sc('languages')} · "
        f"<code>{_fmt_langs(cfg.get('languages') or [])}</code>",
        f"⏰ {sc('frequency')} · "
        f"<code>{_freq_label(cfg.get('frequency') or {})}</code>",
    ]
    return "\n".join(lines), KB.kb_group(gid, cfg, running)


async def view_gr_langs(gid: int) -> Tuple[str, InlineKeyboardMarkup]:
    live = await DB.get_live_groups()
    title = next((g["title"] for g in live
                  if int(g["chat_id"]) == int(gid)), str(gid))
    cfg = await DB.get_group_config(gid)
    langs = cfg.get("languages") or []

    lines = [
        _header("GROUP LANGUAGES"),
        f"👥 <b>{_esc(title)}</b>",
        "", DIV2,
        f"📌 {sc('only selected languages will be sent')}",
        "",
    ]
    for code in langs or []:
        lines.append(
            f"✅ {sc(LANGUAGE_LABELS.get(code, code.upper()))}")
    if not langs:
        lines.append(f"⚪ {sc('none selected')}")
    return "\n".join(lines), KB.kb_gr_langs(gid, langs)


async def view_gr_freq(gid: int) -> Tuple[str, InlineKeyboardMarkup]:
    live = await DB.get_live_groups()
    title = next((g["title"] for g in live
                  if int(g["chat_id"]) == int(gid)), str(gid))
    cfg = await DB.get_group_config(gid)
    freq = cfg.get("frequency") or {}
    mode = freq.get("mode") or "off"
    lines = [
        _header("GROUP FREQUENCY"),
        f"👥 <b>{_esc(title)}</b>",
        "", DIV2,
        f"⏰ {sc('current')} · <code>{_freq_label(freq)}</code>",
    ]
    return "\n".join(lines), KB.kb_gr_freq(gid, mode)


async def view_gr_hours(gid: int, mode: str
                         ) -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await DB.get_group_config(gid)
    hour = int((cfg.get("frequency") or {}).get("hour") or 10)
    lines = [
        _header(f"{mode.upper()} · HOUR"),
        f"📌 {sc('current')} · <code>{hour:02d}:00</code>",
    ]
    return "\n".join(lines), KB.kb_hours_gr(gid, hour)


async def view_gr_days(gid: int) -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await DB.get_group_config(gid)
    day = int((cfg.get("frequency") or {}).get("day_of_week") or 0)
    lines = [
        _header("WEEKLY · DAY"),
        f"📌 {sc('current')} · <code>{FREQ_DAYS[day]}</code>",
    ]
    return "\n".join(lines), KB.kb_days_gr(gid, day)


async def view_gr_month_days(gid: int
                               ) -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await DB.get_group_config(gid)
    d = int((cfg.get("frequency") or {}).get("day_of_month") or 1)
    lines = [
        _header("MONTHLY · DAY"),
        f"📌 {sc('current')} · <code>{d}</code>",
    ]
    return "\n".join(lines), KB.kb_month_days_gr(gid, d)


# ═══════════════════════════════════════════════════════════
# USERS / PREMIUM
# ═══════════════════════════════════════════════════════════

async def view_users() -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await DB.get_users()
    total = await DB.count_live_users()
    running = bool(cfg.get("running"))

    lines = [
        _header("SEND TO ALL USERS"),
        f"👥 {sc('total users in bot')} · <b>{_fmt_int(total)}</b>",
        "", DIV2,
        f"🔘 {sc('status')} · "
        f"{'🟢 RUNNING' if running else '🔴 STOPPED'}",
        f"🌐 {sc('languages')} · "
        f"<code>{_fmt_langs(cfg.get('languages') or [])}</code>",
        f"⏰ {sc('frequency')} · "
        f"<code>{_freq_label(cfg.get('frequency') or {})}</code>",
        "", DIV2,
        f"📌 {sc('when ON, DMs every user')}",
    ]
    return "\n".join(lines), KB.kb_kind_cfg(cfg, "us", total)


async def view_premium() -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await DB.get_premium()
    total = await DB.count_live_premium()
    running = bool(cfg.get("running"))

    lines = [
        _header("SEND TO PREMIUM"),
        f"💎 {sc('total premium users')} · <b>{_fmt_int(total)}</b>",
        "", DIV2,
        f"🔘 {sc('status')} · "
        f"{'🟢 RUNNING' if running else '🔴 STOPPED'}",
        f"🌐 {sc('languages')} · "
        f"<code>{_fmt_langs(cfg.get('languages') or [])}</code>",
        f"⏰ {sc('frequency')} · "
        f"<code>{_freq_label(cfg.get('frequency') or {})}</code>",
    ]
    return "\n".join(lines), KB.kb_kind_cfg(cfg, "pm", total)


async def view_kind_langs(kind: str
                           ) -> Tuple[str, InlineKeyboardMarkup]:
    cfg = (await DB.get_users() if kind == "us"
           else await DB.get_premium())
    langs = cfg.get("languages") or []
    title = "USERS LANGUAGES" if kind == "us" else "PREMIUM LANGUAGES"

    lines = [_header(title), DIV2, ""]
    for code in langs or []:
        lines.append(
            f"✅ {sc(LANGUAGE_LABELS.get(code, code.upper()))}")
    if not langs:
        lines.append(f"⚪ {sc('none selected')}")
    return "\n".join(lines), KB.kb_kind_langs(kind, langs)


async def view_kind_freq(kind: str) -> Tuple[str, InlineKeyboardMarkup]:
    cfg = (await DB.get_users() if kind == "us"
           else await DB.get_premium())
    freq = cfg.get("frequency") or {}
    mode = freq.get("mode") or "off"
    lines = [
        _header("FREQUENCY"),
        f"⏰ {sc('current')} · <code>{_freq_label(freq)}</code>",
    ]
    return "\n".join(lines), KB.kb_kind_freq(kind, mode)


async def view_kind_hours(kind: str, mode: str
                           ) -> Tuple[str, InlineKeyboardMarkup]:
    cfg = (await DB.get_users() if kind == "us"
           else await DB.get_premium())
    hour = int((cfg.get("frequency") or {}).get("hour") or 10)
    lines = [
        _header(f"{mode.upper()} · HOUR"),
        f"📌 {sc('current')} · <code>{hour:02d}:00</code>",
    ]
    return "\n".join(lines), KB.kb_kind_hours(kind, hour)


async def view_kind_days(kind: str
                          ) -> Tuple[str, InlineKeyboardMarkup]:
    cfg = (await DB.get_users() if kind == "us"
           else await DB.get_premium())
    day = int((cfg.get("frequency") or {}).get("day_of_week") or 0)
    lines = [
        _header("WEEKLY · DAY"),
        f"📌 {sc('current')} · <code>{FREQ_DAYS[day]}</code>",
    ]
    return "\n".join(lines), KB.kb_kind_days(kind, day)


async def view_kind_month_days(kind: str
                                 ) -> Tuple[str, InlineKeyboardMarkup]:
    cfg = (await DB.get_users() if kind == "us"
           else await DB.get_premium())
    d = int((cfg.get("frequency") or {}).get("day_of_month") or 1)
    lines = [
        _header("MONTHLY · DAY"),
        f"📌 {sc('current')} · <code>{d}</code>",
    ]
    return "\n".join(lines), KB.kb_kind_month_days(kind, d)


# ═══════════════════════════════════════════════════════════
# PREVIEW + TEXT BUILDER
# ═══════════════════════════════════════════════════════════

async def build_update_text(languages: List[str]) -> str:
    """Build text list for a set of languages."""
    from plugins.ott.tmdb import fetch_week_grouped_by_lang, enrich_movie

    mon, sun = _week_range()
    header = "\n".join([
        f"📅 <b>{fb('OTT UPDATE')}</b>",
        f"🗓️ <code>{mon.strftime('%d %b')} → {sun.strftime('%d %b %Y')}</code>",
        "",
    ])

    if not languages:
        return header + f"⚪ {sc('no languages configured')}"

    sections: List[str] = []
    for code in languages:
        grouped = await fetch_week_grouped_by_lang(
            lang=code, region="IN", min_vote=0)
        all_movies = []
        for i in range(7):
            all_movies.extend(grouped.get(i, []))

        if not all_movies:
            continue

        label = ("🌐 ALL" if code == "all"
                 else LANGUAGE_LABELS.get(code, code.upper()).upper())

        block = [f"<b>🎬 {sc(label)}</b>", ""]
        for m in all_movies[:15]:
            title = str(m.get("title", "?"))[:60]
            year = (m.get("release_date") or "")[:4]
            rating = m.get("vote_average", 0) or 0
            r_str = f" ⭐{rating:.1f}" if rating else ""

            block.append(f"• <b>{sc(title)}</b> ({year}){r_str}")

            imdb_id = m.get("imdb_id") or ""
            provider = m.get("provider") or "—"
            if not imdb_id:
                enriched = await enrich_movie(m)
                imdb_id = enriched.get("imdb_id") or ""
                provider = enriched.get("provider") or provider

            if provider and provider != "—":
                block.append(f"   📺 {sc(provider)}")
            if imdb_id:
                block.append(
                    f"   🔗 https://www.imdb.com/title/{imdb_id}/"
                )
            block.append("")

        if len(block) > 2:
            sections.append("\n".join(block))

    if not sections:
        return header + f"⚪ {sc('no releases this week')}"

    return header + "\n".join(sections)


async def view_preview(languages: List[str], back_cb: str
                        ) -> Tuple[str, InlineKeyboardMarkup]:
    text = await build_update_text(languages)
    if len(text) > 4000:
        text = text[:3950] + "\n…truncated"
    from pyrogram.types import InlineKeyboardButton
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("⬅️ BACK", callback_data=back_cb),
        InlineKeyboardButton("❌ CLOSE", callback_data="ott:close"),
    ]])
    return text, kb


__all__ = [
    "safe_edit",
    "view_home", "view_lang", "view_day", "view_movie",
    "view_settings", "view_fav_langs",
    "view_ch_list", "view_channel", "view_ch_langs",
    "view_ch_freq", "view_ch_hours", "view_ch_days",
    "view_ch_month_days",
    "view_gr_list", "view_group", "view_gr_langs",
    "view_gr_freq", "view_gr_hours", "view_gr_days",
    "view_gr_month_days",
    "view_users", "view_premium",
    "view_kind_langs", "view_kind_freq",
    "view_kind_hours", "view_kind_days", "view_kind_month_days",
    "view_preview", "build_update_text",
]
