# ============================================================
# 🏨 DOWNTOWN VILLA — /ott COMMAND
# ============================================================
#
# ONE COMMAND: /ott
#
# Full weekly releases panel + trends + spotlight + hype + watchlist + prefs + admin.
#
# ============================================================

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from core import config
from plugins.ott import state as S
from plugins.ott import tmdb as T
from plugins.ott import features as FT
from plugins.ott import notify as N
from utils import fonts as F
from utils import format as FM

logger = logging.getLogger(__name__)

PFX = "ott"


# ============================================================
# AUTH
# ============================================================

def _is_admin(uid) -> bool:
    try:
        return int(uid) in [int(a) for a in config.ADMINS]
    except Exception:
        return False


# ============================================================
# HELPERS
# ============================================================

async def _ensure_week() -> Dict[str, Any]:
    wk = S.week_key()
    w = await S.get_week(wk)
    if not w or not w.get("days"):
        by_day = await T.fetch_weekly()
        days = [[dict(m) for m in by_day.get(i, [])] for i in range(7)]
        await S.save_week(wk, days, posted=bool(w and w.get("posted")))
        w = await S.get_week(wk)
    return w or {"days": [[] for _ in range(7)]}


# ============================================================
# MAIN PANEL
# ============================================================

async def _build_weekly_panel() -> Tuple[str, InlineKeyboardMarkup]:
    w = await _ensure_week()
    days = w.get("days") or []
    counts = [len(days[i]) if i < len(days) else 0 for i in range(7)]
    text = N._build_weekly_text(S.week_key(), {i: days[i] for i in range(7)}, counts)
    kb = _build_main_kb(counts)
    return text, kb


def _build_main_kb(counts: List[int]) -> InlineKeyboardMarkup:
    days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    rows = []
    row = []
    for i in range(7):
        label = days[i]
        if counts[i] > 0:
            label += f" ({counts[i]})"
        row.append(InlineKeyboardButton(
            label, callback_data=f"{PFX}:day:{i}",
        ))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    rows.append([
        InlineKeyboardButton(
            f"🔥 {F.sc('trending')}",
            callback_data=f"{PFX}:trending",
        ),
        InlineKeyboardButton(
            f"⭐ {F.sc('spotlight')}",
            callback_data=f"{PFX}:spotlight",
        ),
    ])
    rows.append([
        InlineKeyboardButton(
            f"🎯 {F.sc('for you')}",
            callback_data=f"{PFX}:reco",
        ),
        InlineKeyboardButton(
            f"🔔 {F.sc('my subs')}",
            callback_data=f"{PFX}:mysubs",
        ),
    ])
    rows.append([
        InlineKeyboardButton(
            f"🎁 {F.sc('watchlist')}",
            callback_data=f"{PFX}:watchlist",
        ),
        InlineKeyboardButton(
            f"📊 {F.sc('digest')}",
            callback_data=f"{PFX}:digest",
        ),
    ])
    rows.append([
        InlineKeyboardButton(
            f"⚙️ {F.sc('prefs')}",
            callback_data=f"{PFX}:prefs",
        ),
        InlineKeyboardButton(
            f"{F.EMO['refresh']} {F.sc('refresh')}",
            callback_data=f"{PFX}:refresh",
        ),
    ])
    rows.append([InlineKeyboardButton(
        f"{F.EMO['cross']} {F.sc('close')}",
        callback_data=f"{PFX}:close",
    )])
    return InlineKeyboardMarkup(rows)


# ============================================================
# COMMAND
# ============================================================

@Client.on_message(
    filters.command(["ott", "releases", "weekly"]) & filters.private,
    group=-8400,
)
async def cmd_ott(client: Client, message: Message):
    """Open OTT panel (anyone)."""
    try:
        from plugins.ott import state as S
        await S.ensure_indexes()
        N.ensure_loops(client)
    except Exception:
        pass

    try:
        panel = await message.reply_text("📅 ʟᴏᴀᴅɪɴɢ ᴡᴇᴇᴋʟʏ ʀᴇʟᴇᴀꜱᴇꜱ…")
    except Exception:
        return

    text, kb = await _build_weekly_panel()
    try:
        await panel.edit_text(
            text, reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.debug(f"[OTT] cmd: {e}")


# ============================================================
# DAY VIEW
# ============================================================

async def _build_day_panel(day_idx: int) -> Tuple[str, InlineKeyboardMarkup]:
    w = await _ensure_week()
    days = w.get("days") or []
    movies = days[day_idx] if 0 <= day_idx < len(days) else []
    pretty = S.day_date(day_idx).strftime("%A · %d %b %Y")
    days_short = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"📅 <b>{F.fb('RELEASES')}</b>",
        f"<code>{pretty}</code>",
        F.DIV, "",
    ]

    if not movies:
        lines.append(f"⚪ {F.sc('no releases this day')}")
    else:
        lines.append(f"🎬 <b>{len(movies)}</b> releases")
        lines.append("")
        for m in movies[:20]:
            title = m.get("title") or "?"
            year = (m.get("release_date") or "")[:4]
            rating = m.get("vote_average", 0)
            lang = (m.get("original_language") or "").upper()
            lines.append(f"⭐ <b>{F.sc(str(title)[:50])}</b> ({year})")
            meta = []
            if rating:
                meta.append(f"{rating:.1f}/10")
            if lang:
                meta.append(lang)
            if meta:
                lines.append(f"   🎯 <code>{' · '.join(meta)}</code>")
            lines.append("")

    rows = []
    for m in movies[:10]:
        title = str(m.get("title", "?"))[:32]
        rows.append([InlineKeyboardButton(
            f"🎬 {title}",
            callback_data=f"{PFX}:mv:{m.get('tmdb_id')}",
        )])

    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data=f"{PFX}:refresh",
        ),
        InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('close')}",
            callback_data=f"{PFX}:close",
        ),
    ])

    return "\n".join(lines)[:4000], InlineKeyboardMarkup(rows)


# ============================================================
# MOVIE CARD
# ============================================================

async def _build_movie_panel(
    tmdb_id: int,
    user_id: int,
) -> Tuple[str, InlineKeyboardMarkup, Optional[str]]:
    w = await _ensure_week()
    days = w.get("days") or []
    raw = None
    for d in days:
        for m in d:
            if int(m.get("tmdb_id", 0)) == int(tmdb_id):
                raw = m
                break
        if raw:
            break

    if raw is None:
        raw = await S.get_movie(tmdb_id)
    if raw is None:
        raw = {"tmdb_id": tmdb_id, "title": "?"}

    movie = await T.enrich_movie(raw)
    is_admin = _is_admin(user_id)
    subscribed = False
    if not is_admin:
        subscribed = await S.sub_exists(user_id, tmdb_id)
    sub_count = await S.count_subs_for_movie(tmdb_id) if is_admin else 0

    title = movie.get("title") or "?"
    year = (movie.get("release_date") or "")[:4]
    rating = movie.get("vote_average", 0) or 0
    votes = movie.get("vote_count", 0) or 0
    runtime = movie.get("runtime", 0) or 0
    genres = movie.get("genres") or "—"
    overview = (movie.get("overview") or "")[:500]
    provider = movie.get("provider") or "—"
    orig_lang = (movie.get("original_language") or "").upper()
    director = movie.get("director") or "—"
    cast = movie.get("cast") or "—"
    rel = movie.get("region_release") or {}

    lines = [
        f"🎬 <b>{F.sc(str(title)[:60])}</b> ({year})",
        F.DIV, "",
        f"⭐ {F.sc('rating')} · <code>{rating:.1f}/10</code> "
        f"(<code>{FM.num(votes)}</code>)",
        f"🎭 {F.sc('genres')} · <code>{F.sc(genres[:50])}</code>",
        f"⏱️ {F.sc('runtime')} · <code>{runtime} min</code>",
        f"🌐 {F.sc('lang')} · <code>{orig_lang or '—'}</code>",
        f"🎥 {F.sc('director')} · <code>{F.sc(director)}</code>",
        f"👥 {F.sc('cast')} · <code>{F.sc(cast[:50])}</code>",
        "",
        F.DIV_S, "",
        f"📅 {F.sc('release')} · "
        f"<code>{rel.get('date') or movie.get('release_date') or '—'}</code>",
        f"📺 {F.sc('streaming on')} · <b>{F.sc(provider)}</b>",
    ]

    if overview:
        lines += ["", f"📖 <b>{F.sc('plot')}</b>", f"<i>{F.sc(overview)}</i>"]

    if is_admin:
        lines += [
            "",
            F.DIV_S,
            f"🔔 {F.sc('subscribers')} · <b>{sub_count}</b>",
        ]

    poster = T.poster_url(movie.get("poster_path"), "w500")

    # Buttons
    rows: List[List[InlineKeyboardButton]] = []
    if is_admin:
        rows.append([InlineKeyboardButton(
            f"📢 {F.sc('broadcast this')}",
            callback_data=f"{PFX}:bc:{tmdb_id}",
        )])
    else:
        rows.append([InlineKeyboardButton(
            f"{'🔕' if subscribed else '🔔'} "
            f"{F.sc('unnotify' if subscribed else 'notify me')}",
            callback_data=f"{PFX}:sub:{tmdb_id}",
        )])
        rows.append([InlineKeyboardButton(
            f"🎁 {F.sc('add to watchlist')}",
            callback_data=f"{PFX}:wl_add:{tmdb_id}",
        )])

    rows.append([
        InlineKeyboardButton(
            f"📥 {F.sc('get file')}",
            callback_data=f"{PFX}:getfile:{tmdb_id}",
        ),
    ])
    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data=f"{PFX}:refresh",
        ),
        InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('close')}",
            callback_data=f"{PFX}:close",
        ),
    ])

    return "\n".join(lines)[:4000], InlineKeyboardMarkup(rows), poster


# ============================================================
# CALLBACK ROUTER
# ============================================================

@Client.on_callback_query(
    filters.regex(rf"^{PFX}:"),
    group=-8400,
)
async def ott_router(client: Client, q: CallbackQuery):
    if not q.from_user:
        return await q.answer()

    parts = str(q.data).split(":")
    action = parts[1] if len(parts) > 1 else ""
    arg = parts[2] if len(parts) > 2 else ""

    try:
        # ── CLOSE ──
        if action == "close":
            try:
                await q.message.delete()
            except Exception:
                pass
            return await q.answer("Closed")

        # ── REFRESH ──
        if action == "refresh":
            text, kb = await _build_weekly_panel()
            await _safe_edit(q, text, kb)
            return await q.answer()

        # ── DAY ──
        if action == "day":
            try:
                d = int(arg)
            except ValueError:
                return await q.answer("❌")
            text, kb = await _build_day_panel(d)
            await _safe_edit(q, text, kb)
            return await q.answer()

        # ── MOVIE ──
        if action == "mv":
            try:
                tmdb_id = int(arg)
            except ValueError:
                return await q.answer("❌")
            text, kb, poster = await _build_movie_panel(tmdb_id, q.from_user.id)
            if poster:
                try:
                    await q.message.delete()
                except Exception:
                    pass
                try:
                    await client.send_photo(
                        chat_id=q.message.chat.id,
                        photo=poster,
                        caption=text,
                        reply_markup=kb,
                        parse_mode=ParseMode.HTML,
                    )
                    return await q.answer()
                except Exception:
                    pass
            await _safe_edit(q, text, kb)
            return await q.answer()

        # ── SUBSCRIBE ──
        if action == "sub":
            try:
                tmdb_id = int(arg)
            except ValueError:
                return await q.answer("❌")
            uid = q.from_user.id
            exists = await S.sub_exists(uid, tmdb_id)
            if exists:
                await S.sub_remove(uid, tmdb_id)
                await q.answer("🔕 Unnotified")
            else:
                m = await S.get_movie(tmdb_id) or {}
                title = m.get("title") or "?"
                year = (m.get("release_date") or "")[:4]
                rel_date = m.get("release_date") or ""
                await S.sub_add(uid, tmdb_id, title, year, rel_date)
                await q.answer("🔔 You'll be notified")
            text, kb, poster = await _build_movie_panel(tmdb_id, uid)
            if poster:
                try:
                    await q.message.edit_caption(
                        caption=text, reply_markup=kb,
                        parse_mode=ParseMode.HTML,
                    )
                    return
                except Exception:
                    pass
            await _safe_edit(q, text, kb)
            return

        # ── TRENDING ──
        if action == "trending":
            trending = await FT.get_trending(limit=10)
            lines = [
                f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                f"🔥 <b>{F.fb('TRENDING THIS WEEK')}</b>",
                F.DIV, "",
            ]
            rows = []
            if not trending:
                lines.append(f"⚪ {F.sc('no trending data yet')}")
            else:
                for i, m in enumerate(trending, 1):
                    title = str(m.get("title", "?"))[:40]
                    rating = m.get("vote_average", 0)
                    lines.append(
                        f"<b>{i:02d}.</b> ⭐ <b>{F.sc(title)}</b>"
                    )
                    lines.append(f"   <code>{rating:.1f}/10</code>")
                    rows.append([InlineKeyboardButton(
                        f"{i:02d}. {title}",
                        callback_data=f"{PFX}:mv:{m.get('tmdb_id')}",
                    )])

            rows.append([
                InlineKeyboardButton(
                    f"{F.EMO['back']} {F.sc('back')}",
                    callback_data=f"{PFX}:refresh",
                ),
                InlineKeyboardButton(
                    f"{F.EMO['cross']} {F.sc('close')}",
                    callback_data=f"{PFX}:close",
                ),
            ])
            await _safe_edit(q, "\n".join(lines)[:4000], InlineKeyboardMarkup(rows))
            return await q.answer()

        # ── SPOTLIGHT ──
        if action == "spotlight":
            m = await FT.get_spotlight()
            if not m:
                return await q.answer("⚠️ No spotlight", show_alert=True)
            text, kb, poster = await _build_movie_panel(m.get("tmdb_id"), q.from_user.id)
            if poster:
                try:
                    await q.message.delete()
                except Exception:
                    pass
                try:
                    await client.send_photo(
                        chat_id=q.message.chat.id,
                        photo=poster,
                        caption=text,
                        reply_markup=kb,
                        parse_mode=ParseMode.HTML,
                    )
                    return await q.answer()
                except Exception:
                    pass
            await _safe_edit(q, text, kb)
            return await q.answer()

        # ── MY SUBS ──
        if action == "mysubs":
            subs = await S.subs_for_user(q.from_user.id)
            lines = [
                f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                f"🔔 <b>{F.fb('MY NOTIFICATIONS')}</b>",
                F.DIV, "",
            ]
            if not subs:
                lines.append(f"⚪ {F.sc('no subscriptions yet')}")
                lines.append("")
                lines.append(f"📌 {F.sc('tap a movie → notify to start')}")
            else:
                lines.append(f"📊 <b>{len(subs)}</b> movies")
                lines.append("")
                for s in subs[:15]:
                    icon = "✅" if s.get("notified") else "🔔"
                    title = str(s.get("title", "?"))[:40]
                    lines.append(f"{icon} <b>{F.sc(title)}</b>")
                    if s.get("release_date"):
                        lines.append(f"   📅 <code>{s['release_date']}</code>")

            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"{F.EMO['back']} {F.sc('back')}",
                    callback_data=f"{PFX}:refresh",
                ),
                InlineKeyboardButton(
                    f"{F.EMO['cross']} {F.sc('close')}",
                    callback_data=f"{PFX}:close",
                ),
            ]])
            await _safe_edit(q, "\n".join(lines)[:4000], kb)
            return await q.answer()

        # ── RECOMMENDATIONS ──
        if action == "reco":
            recs = await FT.get_recommendations(q.from_user.id, limit=8)
            lines = [
                f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                f"🎯 <b>{F.fb('FOR YOU')}</b>",
                F.DIV, "",
            ]
            rows = []
            if not recs:
                lines.append(f"⚪ {F.sc('subscribe to movies to get recommendations')}")
            else:
                for i, m in enumerate(recs, 1):
                    title = str(m.get("title", "?"))[:40]
                    lines.append(f"<b>{i:02d}.</b> 🎬 {F.sc(title)}")
                    rows.append([InlineKeyboardButton(
                        f"{i:02d}. {title}",
                        callback_data=f"{PFX}:mv:{m.get('tmdb_id')}",
                    )])
            rows.append([
                InlineKeyboardButton(
                    f"{F.EMO['back']} {F.sc('back')}",
                    callback_data=f"{PFX}:refresh",
                ),
                InlineKeyboardButton(
                    f"{F.EMO['cross']} {F.sc('close')}",
                    callback_data=f"{PFX}:close",
                ),
            ])
            await _safe_edit(q, "\n".join(lines)[:4000], InlineKeyboardMarkup(rows))
            return await q.answer()

        # ── WATCHLIST ──
        if action == "watchlist":
            wl = await FT.get_watchlist(q.from_user.id)
            lines = [
                f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                f"🎁 <b>{F.fb('MY WATCHLIST')}</b>",
                F.DIV, "",
            ]
            rows = []
            if not wl:
                lines.append(f"⚪ {F.sc('watchlist is empty')}")
            else:
                for w in wl[:15]:
                    title = str(w.get("title", "?"))[:40]
                    lines.append(f"🎬 <b>{F.sc(title)}</b>")
                    rows.append([InlineKeyboardButton(
                        f"🎬 {title}",
                        callback_data=f"{PFX}:mv:{w.get('tmdb_id')}",
                    )])
            rows.append([
                InlineKeyboardButton(
                    f"{F.EMO['back']} {F.sc('back')}",
                    callback_data=f"{PFX}:refresh",
                ),
                InlineKeyboardButton(
                    f"{F.EMO['cross']} {F.sc('close')}",
                    callback_data=f"{PFX}:close",
                ),
            ])
            await _safe_edit(q, "\n".join(lines)[:4000], InlineKeyboardMarkup(rows))
            return await q.answer()

        # ── WATCHLIST ADD ──
        if action == "wl_add":
            try:
                tmdb_id = int(arg)
            except ValueError:
                return await q.answer("❌")
            await FT.add_to_watchlist(q.from_user.id, tmdb_id)
            await q.answer("🎁 Added to watchlist")

        # ── DIGEST ──
        if action == "digest":
            d = await FT.get_weekly_digest()
            lines = [
                f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                f"📊 <b>{F.fb('WEEKLY DIGEST')}</b>",
                F.DIV, "",
            ]
            if not d:
                lines.append(f"⚪ {F.sc('no data yet')}")
            else:
                lines += [
                    f"📅 <code>{d['week']}</code>",
                    f"🎬 {F.sc('total')} · <b>{d['total']}</b>",
                    f"⭐ {F.sc('avg rating')} · <b>{d['avg_rating']}</b>",
                    "",
                    F.DIV_S,
                    f"🎭 <b>{F.sc('top genres')}</b>",
                ]
                for g, n in d.get("top_genres", []):
                    lines.append(f"• {F.sc(g)} · <b>{n}</b>")
                lines.append("")
                lines.append(f"🌐 <b>{F.sc('top languages')}</b>")
                for l, n in d.get("top_languages", []):
                    lines.append(f"• <code>{l.upper()}</code> · <b>{n}</b>")

            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"{F.EMO['back']} {F.sc('back')}",
                    callback_data=f"{PFX}:refresh",
                ),
                InlineKeyboardButton(
                    f"{F.EMO['cross']} {F.sc('close')}",
                    callback_data=f"{PFX}:close",
                ),
            ]])
            await _safe_edit(q, "\n".join(lines)[:4000], kb)
            return await q.answer()

        # ── PREFS ──
        if action == "prefs":
            p = await S.get_prefs(q.from_user.id)
            langs = p.get("languages") or []
            genres = p.get("genres") or []
            lines = [
                f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                f"⚙️ <b>{F.fb('MY PREFERENCES')}</b>",
                F.DIV, "",
                f"🌐 {F.sc('languages')} · <code>{', '.join(langs) or 'all'}</code>",
                f"🎭 {F.sc('genres')} · <code>{', '.join(genres) or 'all'}</code>",
                "",
                f"📌 {F.sc('used for recommendations')}",
            ]
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    f"🗑️ {F.sc('clear prefs')}",
                    callback_data=f"{PFX}:prefs_clear",
                )],
                [
                    InlineKeyboardButton(
                        f"{F.EMO['back']} {F.sc('back')}",
                        callback_data=f"{PFX}:refresh",
                    ),
                    InlineKeyboardButton(
                        f"{F.EMO['cross']} {F.sc('close')}",
                        callback_data=f"{PFX}:close",
                    ),
                ],
            ])
            await _safe_edit(q, "\n".join(lines), kb)
            return await q.answer()

        if action == "prefs_clear":
            await S.save_prefs(q.from_user.id, languages=[], genres=[])
            await q.answer("🗑️ Cleared")

        # ── BROADCAST (admin) ──
        if action == "bc":
            if not _is_admin(q.from_user.id):
                return await q.answer("⛔", show_alert=True)
            try:
                tmdb_id = int(arg)
            except ValueError:
                return await q.answer("❌")
            # Hand off to broadcast module
            await q.answer("Use /broadcast → source = this movie", show_alert=True)
            return

        # ── GET FILE ──
        if action == "getfile":
            await q.answer("📥 Search in the group", show_alert=True)
            return

        return await q.answer("❓ Unknown")

    except Exception as e:
        logger.exception(f"[OTT] router: {e}")
        try:
            await q.answer(f"❌ {type(e).__name__}", show_alert=True)
        except Exception:
            pass


# ============================================================
# HELPERS
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
            logger.debug(f"[OTT] edit: {e}")


# ============================================================
# SNAPSHOT
# ============================================================

def snapshot() -> Dict[str, Any]:
    return {"module": "ott"}


__all__ = ["cmd_ott", "snapshot"]
