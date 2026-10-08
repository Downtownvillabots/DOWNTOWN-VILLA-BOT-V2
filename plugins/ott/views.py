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
    LANGUAGE_LABELS,
)
from plugins.ott import keyboards as KB

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# SAFE EDIT
# ═══════════════════════════════════════════════════════════

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


# ═══════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════

def _week_range():
    """Monday and Sunday of current week (IST)."""
    now = _dt.datetime.now()
    mon = (now - _dt.timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0)
    sun = mon + _dt.timedelta(days=6)
    return mon, sun


def _week_bounds_iso():
    mon, sun = _week_range()
    return mon.strftime("%Y-%m-%d"), sun.strftime("%Y-%m-%d")


def _human(size) -> str:
    try:
        s = float(size or 0)
    except (TypeError, ValueError):
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while s >= 1024 and i < len(units) - 1:
        s /= 1024.0
        i += 1
    return f"{s:.2f} {units[i]}"


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
    mon, sun = _week_range()

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
        f"📌 {sc('only this week OTT releases are shown')}",
        f"📌 {sc('updated live from TMDB')}",
    ])
    return text, KB.kb_home()


# ═══════════════════════════════════════════════════════════
# LANGUAGE VIEW (grouped by day)
# ═══════════════════════════════════════════════════════════

async def view_language(lang: str) -> Tuple[str, InlineKeyboardMarkup]:
    from plugins.ott.tmdb import fetch_week_grouped_by_lang

    grouped = await fetch_week_grouped_by_lang(
        lang=lang, region="IN", min_vote=0)

    mon, sun = _week_range()
    counts = [len(grouped.get(i, [])) for i in range(7)]
    total = sum(counts)

    label = ("🌐 All Languages" if lang == "all"
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
        lines.append("")
        lines.append(f"📌 {sc('try again later or refresh')}")
    else:
        for i in range(7):
            day_date = mon + _dt.timedelta(days=i)
            c = counts[i]
            lines.append(
                f"📅 <b>{day_names[i]}</b> · "
                f"<code>{day_date.strftime('%d %b')}</code> · "
                f"<b>{c}</b>"
            )
            for m in grouped.get(i, [])[:5]:
                title = str(m.get("title", "?"))[:42]
                rating = m.get("vote_average", 0) or 0
                r_str = f" ⭐{rating:.1f}" if rating else ""
                lines.append(f"   🎬 {sc(title)}{r_str}")
            if c > 5:
                lines.append(f"   <i>… +{c - 5} more</i>")
            lines.append("")

    lines += [
        DIV2,
        f"📌 {sc('tap a day button below')}",
    ]
    return "\n".join(lines)[:4000], KB.kb_language(lang, counts)


# ═══════════════════════════════════════════════════════════
# DAY VIEW
# ═══════════════════════════════════════════════════════════

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

    label = ("🌐 All Languages" if lang == "all"
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
# MOVIE CARD (with IMDb)
# ═══════════════════════════════════════════════════════════

async def view_movie(tmdb_id: int, lang: str, day_idx: int
                     ) -> Tuple[str, InlineKeyboardMarkup, Optional[str]]:
    from plugins.ott.tmdb import enrich_movie, poster_url

    # Fetch enriched movie from TMDB
    raw = {"tmdb_id": tmdb_id}
    movie = await enrich_movie(raw)

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
        "",
        DIV2,
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


__all__ = [
    "safe_edit",
    "view_home", "view_language", "view_day", "view_movie",
]
