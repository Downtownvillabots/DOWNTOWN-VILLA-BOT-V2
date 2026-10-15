# ============================================================
# 🏨 DOWNTOWN VILLA — PREMIUM WATCH (MAIN COMMAND)
# ============================================================
#
# ONE COMMAND: /premium
#
# Handles:
#   • Premium menu (my sessions, badges, help)
#   • Opening a session from a group deep link (prem_{token})
#   • Session panel (poster + buttons)
#   • Episode delivery + mark watched
#   • Watch next
#   • Seasons view
#   • Episode grid
#   • Rating
#   • Mark complete
#   • Watch order
#   • Admin panel (/premium_admin inside /premium if admin)
#
# ============================================================

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any, Dict, List, Optional

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.errors import FloodWait, UserIsBlocked
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from core import config
from utils import fonts as F
from utils import format as FM
from utils import progress as P

logger = logging.getLogger(__name__)


# ============================================================
# AUTH + HELPERS
# ============================================================

def _is_admin(uid) -> bool:
    try:
        return int(uid) in [int(a) for a in config.ADMINS]
    except Exception:
        return False


async def _safe_edit(q: CallbackQuery, text: str, kb) -> None:
    """
    Edit either a text or a photo message safely.
    Photo messages require edit_caption; text uses edit_text.
    """
    msg = q.message
    is_media = bool(
        getattr(msg, "photo", None)
        or getattr(msg, "video", None)
        or getattr(msg, "document", None)
        or getattr(msg, "animation", None)
    )

    try:
        if is_media:
            await msg.edit_caption(
                caption=text,
                reply_markup=kb,
                parse_mode=ParseMode.HTML,
            )
        else:
            await msg.edit_text(
                text,
                reply_markup=kb,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
    except Exception as e:
        err = str(e).lower()
        if "not modified" not in err:
            logger.debug(f"[PREM] safe_edit: {e}")


# ============================================================
# COMMAND
# ============================================================

@Client.on_message(
    filters.command(["premium", "watch"]) & filters.private,
    group=-8400,
)
async def cmd_premium(client: Client, message: Message):
    if not message.from_user:
        return

    uid = message.from_user.id

    from plugins.premium import state as S
    if not await S.is_premium_or_grace(uid):
        return await message.reply_text(
            "\n".join([
                f"{F.EMO['crown']} <b>{F.fb('PREMIUM WATCH')}</b>",
                F.DIV, "",
                f"{F.EMO['lock']} {F.sc('premium only')}",
                "",
                f"📌 {F.sc('contact admin to subscribe')}",
            ]),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"{F.EMO['users']} {F.sc('contact admin')}",
                    url=config.OWNER_LNK or "https://t.me/",
                ),
            ]]),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )

    await _show_main_menu(client, message.chat.id, uid)


async def _show_main_menu(client: Client, chat_id: int, uid: int) -> None:
    from plugins.premium import state as S
    from plugins.premium import achievements as A

    sessions = await S.list_user_sessions(uid)
    badges = await A.compute_for_user(uid)
    is_prem = await S.is_premium(uid)

    user = await S.get_user(uid)
    days_left = 0
    if user:
        days_left = int((user.get("expires_at", 0) - time.time()) / 86400)

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"{F.EMO['crown']} <b>{F.fb('PREMIUM WATCH')}</b>",
        F.DIV, "",
        f"{'🟢 ' + F.sc('premium active') if is_prem else '🟡 ' + F.sc('grace period')}",
    ]
    if days_left > 0:
        lines.append(f"{F.EMO['cal']} {F.sc('expires in')} · "
                     f"<b>{days_left} {F.sc('days')}</b>")

    if badges:
        lines += ["", A.render_badges(badges, limit=4)]

    lines += [
        "",
        F.DIV_S,
        f"{F.EMO['tv']} {F.sc('your series')} · "
        f"<b>{len(sessions)}</b>",
        "",
    ]

    for s in sessions[:5]:
        p = S.compute_progress(s)
        bar = P.bar(p["pct"], "indexing", width=8, show_percent=False)
        title = str(s.get("series_title", "?"))[:30]
        lines.append(f"{bar} <b>{F.sc(title)}</b>")
        lines.append(f"   <code>{p['total_watched']}/{p['total_eps']}</code>")

    if len(sessions) > 5:
        lines.append(f"<i>… +{len(sessions) - 5} more</i>")

    lines += [
        "",
        f"📌 {F.sc('search in the group to open a new series')}",
    ]

    rows: List[List[InlineKeyboardButton]] = []

    for s in sessions[:5]:
        rows.append([InlineKeyboardButton(
            f"{F.EMO['tv']} {str(s.get('series_title', '?'))[:32]}",
            callback_data=f"pw:open:{s['series_slug']}",
        )])

    if sessions:
        rows.append([InlineKeyboardButton(
            f"{F.EMO['chart']} {F.sc('full list')}",
            callback_data="pw:my_sessions",
        )])

    if _is_admin(uid):
        rows.append([InlineKeyboardButton(
            f"{F.EMO['gear']} {F.sc('admin panel')}",
            callback_data="pw:admin",
        )])

    rows.append([InlineKeyboardButton(
        f"{F.EMO['cross']} {F.sc('close')}",
        callback_data="pw:menu_close",
    )])

    try:
        await client.send_message(
            chat_id=chat_id,
            text="\n".join(lines)[:4000],
            reply_markup=InlineKeyboardMarkup(rows),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.debug(f"[PREM] menu: {e}")


# ============================================================
# OPEN FROM TOKEN (from series group deep link)
# ============================================================

async def open_from_token(
    client: Client,
    message: Message,
    token_data: Dict[str, Any],
) -> None:
    """Open a premium watch session from a group deep link."""
    try:
        uid = message.from_user.id
        title = token_data.get("title") or "?"
        tmdb_id = token_data.get("tmdb_id")
        slug = token_data.get("slug") or ""

        if not slug:
            from plugins.premium import state as S
            slug = S.make_slug(title)

        hits = token_data.get("hits") or []

        # Get TMDB details
        tmdb_seasons: List[Dict[str, Any]] = []
        poster: Optional[str] = None
        language = ""

        if tmdb_id:
            try:
                from plugins.groups.series import tmdb as T
                details = await T.get_series_details(title)
                if details:
                    tmdb_seasons = T.get_series_seasons(title)
                    langs = T.get_series_languages(title)
                    language = langs[0] if langs else "English"
                    poster = details.get("poster_path")
            except Exception as e:
                logger.debug(f"[PREM] tmdb: {e}")

        # Create session in DB
        from plugins.premium import state as S
        await S.create_session(
            user_id=uid,
            title=title,
            tmdb_id=tmdb_id,
            poster=poster,
            language=language,
            tmdb_seasons=tmdb_seasons,
            hits=hits,
        )

        session = await S.get_session(uid, slug)
        if not session:
            return await message.reply_text(
                f"❌ {F.sc('could not create session')}",
                parse_mode=ParseMode.HTML,
            )

        # Send poster
        from plugins.premium import poster as PO
        msg_id = await PO.send_poster(client, uid, session, slug)
        if msg_id:
            await S.update_poster_msg(uid, slug, msg_id)

    except Exception as e:
        logger.exception(f"[PREM] open_from_token: {e}")


# ============================================================
# SESSION OPEN CALLBACK
# ============================================================

async def _open_session(
    client: Client,
    q: CallbackQuery,
    slug: str,
) -> None:
    uid = q.from_user.id
    from plugins.premium import state as S
    session = await S.get_session(uid, slug)
    if not session:
        return await q.answer("⚠️ Session not found", show_alert=True)

    from plugins.premium import poster as PO
    msg_id = await PO.send_poster(client, uid, session, slug)
    if msg_id:
        await S.update_poster_msg(uid, slug, msg_id)

    try:
        await q.message.delete()
    except Exception:
        pass
    await q.answer()


# ============================================================
# SEASONS VIEW
# ============================================================

async def _show_seasons(
    client: Client,
    q: CallbackQuery,
    slug: str,
) -> None:
    uid = q.from_user.id
    from plugins.premium import state as S
    session = await S.get_session(uid, slug)
    if not session:
        return await q.answer("⚠️ Not found", show_alert=True)

    title = session.get("series_title") or "?"
    seasons_raw = session.get("seasons") or {}
    ordered = sorted(int(k) for k in seasons_raw.keys() if k.isdigit())
    p = S.compute_progress(session)

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"{F.EMO['tv']} <b>{F.fb('SEASONS')}</b>",
        F.DIV, "",
        f"🎬 <b>{F.sc(str(title)[:50])}</b>",
        f"📊 <code>{p['total_watched']}/{p['total_eps']}</code> "
        f"({p['pct']}%)",
        "",
    ]

    rows: List[List[InlineKeyboardButton]] = []

    for sn in ordered:
        s = seasons_raw.get(str(sn)) or {}
        watched = len(s.get("watched") or [])
        total = int(s.get("total_eps", 0) or 0)

        if total > 0 and watched >= total:
            icon = "🟢"
        elif watched > 0:
            icon = "🟡"
        else:
            icon = "⚪"

        bar = (
            P.bar(watched / total * 100, "indexing", width=8,
                  show_percent=False)
            if total else "⬛" * 8
        )
        lines.append(f"{icon} S{sn:02d} {bar} "
                     f"<code>{watched}/{total}</code>")

        rows.append([InlineKeyboardButton(
            f"{icon} S{sn:02d} · {watched}/{total}",
            callback_data=f"pw:season:{slug}:{sn}",
        )])

    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data=f"pw:open:{slug}",
        ),
        InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('close')}",
            callback_data="pw:close_session",
        ),
    ])

    await _safe_edit(
        q,
        "\n".join(lines)[:4000],
        InlineKeyboardMarkup(rows),
    )
    await q.answer()


# ============================================================
# EPISODE GRID
# ============================================================

async def _show_episodes(
    client: Client,
    q: CallbackQuery,
    slug: str,
    season: int,
) -> None:
    uid = q.from_user.id
    from plugins.premium import state as S
    session = await S.get_session(uid, slug)
    if not session:
        return await q.answer("⚠️ Not found", show_alert=True)

    title = session.get("series_title") or "?"
    s = (session.get("seasons") or {}).get(str(season)) or {}
    total = int(s.get("total_eps", 0) or 0)
    watched = set(s.get("watched") or [])

    if total == 0:
        return await q.answer("⚠️ No episodes", show_alert=True)

    pct = len(watched) / total * 100 if total else 0
    bar = P.bar(pct, "indexing", width=12)

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"{F.EMO['clapper']} <b>{F.fb(f'SEASON {season:02d}')}</b>",
        F.DIV, "",
        f"🎬 <b>{F.sc(str(title)[:50])}</b>",
        f"<code>{bar}</code>",
        f"📊 <code>{len(watched)}/{total}</code>",
        "",
    ]

    rows: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []

    for ep in range(1, total + 1):
        mark = "🟢" if ep in watched else "▶️"
        row.append(InlineKeyboardButton(
            f"{mark} E{ep:02d}",
            callback_data=f"pw:play:{slug}:{season}:{ep}",
        ))
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    rows.append([InlineKeyboardButton(
        f"{F.EMO['send']} {F.sc('send all')}",
        callback_data=f"pw:sendall:{slug}:{season}",
    )])
    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data=f"pw:seasons:{slug}",
        ),
        InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('close')}",
            callback_data="pw:close_session",
        ),
    ])

    await _safe_edit(
        q,
        "\n".join(lines)[:4000],
        InlineKeyboardMarkup(rows),
    )
    await q.answer()


# ============================================================
# EPISODE DELIVERY
# ============================================================

async def _deliver_episode(
    client: Client,
    uid: int,
    session: Dict[str, Any],
    season: int,
    episode: int,
) -> bool:
    """Deliver one episode with MARK WATCHED + NEXT buttons."""
    try:
        title = session.get("series_title") or "?"
        slug = session.get("series_slug") or ""
        hits = session.get("hits") or []

        # Find the file
        chosen = None
        for h in hits:
            if h.get("season") == season and h.get("episode") == episode:
                chosen = h
                break

        if not chosen:
            try:
                await client.send_message(
                    chat_id=uid,
                    text="\n".join([
                        f"{F.EMO['cross']} <b>{F.fb('FILE NOT FOUND')}</b>",
                        F.DIV, "",
                        f"📌 S{season:02d}E{episode:02d}",
                    ]),
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass
            return False

        file_id = chosen.get("file_id")
        quality = chosen.get("quality") or "?"
        size = FM.size(chosen.get("file_size", 0))
        langs = "+".join(chosen.get("languages") or []) or "?"

        caption = "\n".join([
            f"{F.EMO['film']} <b>{F.sc(str(title)[:50])}</b>",
            f"{F.EMO['clapper']} <b>S{season:02d}E{episode:02d}</b>",
            f"{F.EMO['spark']} <code>{quality}</code> · "
            f"<code>{langs}</code>",
            f"{F.EMO['size']} <code>{size}</code>",
            "",
            f"{F.EMO['crown']} <i>Premium · No Auto-Delete</i>",
        ])

        sent = None
        try:
            sent = await client.send_cached_media(
                chat_id=uid,
                file_id=file_id,
                caption=caption,
                parse_mode=ParseMode.HTML,
            )
        except FloodWait as e:
            await asyncio.sleep(e.value + 2)
            try:
                sent = await client.send_cached_media(
                    chat_id=uid,
                    file_id=file_id,
                    caption=caption,
                    parse_mode=ParseMode.HTML,
                )
            except UserIsBlocked:
                from services.users import mark_user_blocked
                await mark_user_blocked(uid)
                return False
        except UserIsBlocked:
            from services.users import mark_user_blocked
            await mark_user_blocked(uid)
            return False

        if not sent:
            return False

        # Attach buttons
        try:
            await client.edit_message_reply_markup(
                chat_id=uid,
                message_id=sent.id,
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        f"{F.EMO['check']} {F.sc('mark watched')}",
                        callback_data=(
                            f"pw:watched:{slug}:{season}:"
                            f"{episode}:{sent.id}"
                        ),
                    )],
                    [InlineKeyboardButton(
                        f"{F.EMO['next']} {F.sc('watch next')}",
                        callback_data=f"pw:next:{slug}:{season}:{episode}",
                    )],
                ]),
            )
        except Exception as e:
            logger.debug(f"[PREM] attach: {e}")

        # Update session
        from plugins.premium import state as S
        await S.update_current_file_msg(uid, slug, sent.id)
        await S.mark_sent(uid, slug, season, episode)

        return True
    except Exception as e:
        logger.exception(f"[PREM] deliver: {e}")
        return False


# ============================================================
# CALLBACK ROUTER
# ============================================================

@Client.on_callback_query(
    filters.regex(r"^pw:"),
    group=-8400,
)
async def premium_router(client: Client, q: CallbackQuery):
    if not q.from_user:
        return await q.answer()

    uid = q.from_user.id
    parts = str(q.data).split(":")
    action = parts[1] if len(parts) > 1 else ""

    try:
        # ─── MENU CLOSE ───
        if action == "menu_close":
            try:
                await q.message.delete()
            except Exception:
                pass
            return await q.answer("Closed")

        # ─── SESSION CLOSE ───
        if action == "close_session":
            try:
                await q.message.delete()
            except Exception:
                pass
            return await q.answer("Closed")

        # ─── MENU ───
        if action == "menu":
            try:
                await q.message.delete()
            except Exception:
                pass
            await _show_main_menu(client, q.from_user.id, uid)
            return await q.answer()

        # ─── OPEN SESSION ───
        if action == "open":
            return await _open_session(client, q, parts[2])

        # ─── SEASONS LIST ───
        if action == "seasons":
            return await _show_seasons(client, q, parts[2])

        # ─── SEASON EPISODES ───
        if action == "season":
            return await _show_episodes(
                client, q, parts[2], int(parts[3])
            )

        # ─── PLAY EPISODE ───
        if action == "play":
            slug = parts[2]
            season = int(parts[3])
            episode = int(parts[4])

            from plugins.premium import state as S
            session = await S.get_session(uid, slug)
            if not session:
                return await q.answer("⚠️ Not found", show_alert=True)

            await q.answer("📤 Sending…")
            await _deliver_episode(
                client, uid, session, season, episode
            )
            return

        # ─── WATCHED MARK ───
        if action == "watched":
            slug = parts[2]
            season = int(parts[3])
            episode = int(parts[4])
            file_msg_id = int(parts[5])

            from plugins.premium import state as S
            session = await S.get_session(uid, slug)
            if not session:
                return await q.answer("⚠️ Not found", show_alert=True)

            await S.mark_watched(uid, slug, season, episode)
            await S.set_current_position(uid, slug, season, episode)

            # Update file button
            try:
                await client.edit_message_reply_markup(
                    chat_id=uid,
                    message_id=file_msg_id,
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton(
                            f"{F.EMO['check']} {F.sc('watched')}",
                            callback_data=(
                                f"pw:already:{slug}:{season}:{episode}"
                            ),
                        ),
                    ]]),
                )
            except Exception:
                pass

            # Auto-delete after grace
            asyncio.create_task(
                _auto_delete(client, uid, file_msg_id, 30)
            )

            # Refresh poster
            fresh = await S.get_session(uid, slug)
            if fresh:
                from plugins.premium import poster as PO
                await PO.render_update(client, fresh)

            # Season complete?
            if fresh and S.is_season_complete(fresh, season):
                await _notify_season_complete(client, uid, fresh, season)

            if fresh and S.is_series_complete(fresh):
                await _notify_series_complete(client, uid, fresh)

            return await q.answer("✅ Watched")

        # ─── ALREADY WATCHED ───
        if action == "already":
            return await q.answer("✅ Already watched")

        # ─── WATCH NEXT ───
        if action == "next":
            slug = parts[2]
            season = int(parts[3])
            episode = int(parts[4])

            from plugins.premium import state as S
            session = await S.get_session(uid, slug)
            if not session:
                return await q.answer("⚠️ Not found", show_alert=True)

            await S.mark_watched(uid, slug, season, episode)

            next_ep = S.find_next_episode(
                await S.get_session(uid, slug)
            )
            if not next_ep:
                fresh = await S.get_session(uid, slug)
                if fresh:
                    from plugins.premium import poster as PO
                    await PO.render_update(client, fresh)
                    await _notify_series_complete(client, uid, fresh)
                return await q.answer("🏆 All done!")

            sn, ep = next_ep
            await q.answer(f"▶️ S{sn:02d}E{ep:02d}")
            await _deliver_episode(client, uid, session, sn, ep)

            fresh = await S.get_session(uid, slug)
            if fresh:
                from plugins.premium import poster as PO
                await PO.render_update(client, fresh)
            return

        # ─── SEND ALL ───
        if action == "sendall":
            slug = parts[2]
            season = int(parts[3])

            from plugins.premium import state as S
            session = await S.get_session(uid, slug)
            if not session:
                return await q.answer("⚠️ Not found", show_alert=True)

            s = (session.get("seasons") or {}).get(str(season)) or {}
            total = int(s.get("total_eps", 0) or 0)
            watched = set(s.get("watched") or [])
            to_send = [e for e in range(1, total + 1) if e not in watched]

            if not to_send:
                return await q.answer("✅ All watched", show_alert=True)

            await q.answer(f"📤 Sending {len(to_send)}…")

            for ep in to_send:
                await _deliver_episode(client, uid, session, season, ep)
                await asyncio.sleep(0.8)

            return

        # ─── RATING ───
        if action == "rate_menu":
            slug = parts[2]
            return await _show_rating_menu(client, q, slug)

        if action == "rate":
            slug = parts[2]
            stars = int(parts[3])
            from plugins.premium import state as S
            await S.save_rating(uid, slug, stars)
            await S.mark_rated(uid, slug)
            await q.answer(f"⭐ {stars}/5")
            return await _open_session(client, q, slug)

        # ─── MARK COMPLETE ───
        if action == "complete":
            slug = parts[2]
            from plugins.premium import state as S
            await S.mark_completed(uid, slug)
            await q.answer("🏆 Complete")
            try:
                await q.message.delete()
            except Exception:
                pass
            return

        # ─── MISSING ───
        if action == "missing":
            slug = parts[2]
            return await _show_missing(client, q, slug)

        # ─── WATCH ORDER ───
        if action == "wo":
            slug = parts[2]
            return await _show_watch_order(client, q, slug)

        # ─── MY SESSIONS ───
        if action == "my_sessions":
            try:
                await q.message.delete()
            except Exception:
                pass
            await _show_main_menu(client, q.from_user.id, uid)
            return await q.answer()

        # ─── ADMIN ───
        if action == "admin":
            if not _is_admin(uid):
                return await q.answer("⛔", show_alert=True)
            return await _show_admin(client, q)

        await q.answer("❓ Unknown")

    except Exception as e:
        logger.exception(f"[PREM] router: {e}")
        try:
            await q.answer(f"❌ {type(e).__name__}", show_alert=True)
        except Exception:
            pass


# ============================================================
# RATING MENU
# ============================================================

async def _show_rating_menu(client, q, slug: str) -> None:
    uid = q.from_user.id
    from plugins.premium import state as S
    session = await S.get_session(uid, slug)
    if not session:
        return await q.answer("⚠️ Not found", show_alert=True)

    title = session.get("series_title") or "?"
    current = await S.get_rating(uid, slug)

    text = "\n".join([
        f"{F.EMO['star']} <b>{F.fb('RATE THIS SERIES')}</b>",
        F.DIV, "",
        f"🎬 <b>{F.sc(str(title)[:50])}</b>",
        "",
        f"📌 {F.sc('how would you rate it')}",
        f"📌 <code>1 = Poor · 5 = Excellent</code>",
    ])

    rows = [
        [
            InlineKeyboardButton("⭐ 1",
                callback_data=f"pw:rate:{slug}:1"),
            InlineKeyboardButton("⭐⭐ 2",
                callback_data=f"pw:rate:{slug}:2"),
            InlineKeyboardButton("⭐⭐⭐ 3",
                callback_data=f"pw:rate:{slug}:3"),
        ],
        [
            InlineKeyboardButton("⭐⭐⭐⭐ 4",
                callback_data=f"pw:rate:{slug}:4"),
            InlineKeyboardButton("⭐⭐⭐⭐⭐ 5",
                callback_data=f"pw:rate:{slug}:5"),
        ],
        [InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('skip')}",
            callback_data=f"pw:open:{slug}",
        )],
    ]

    await _safe_edit(q, text, InlineKeyboardMarkup(rows))
    await q.answer()


# ============================================================
# MISSING EPISODES
# ============================================================

async def _show_missing(client, q, slug: str) -> None:
    uid = q.from_user.id
    from plugins.premium import state as S
    session = await S.get_session(uid, slug)
    if not session:
        return await q.answer("⚠️ Not found", show_alert=True)

    title = session.get("series_title") or "?"
    seasons_raw = session.get("seasons") or {}
    ordered = sorted(int(k) for k in seasons_raw.keys() if k.isdigit())

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"{F.EMO['chart']} <b>{F.fb('MISSING EPISODES')}</b>",
        F.DIV, "",
        f"🎬 <b>{F.sc(str(title)[:50])}</b>",
        "",
    ]

    total_missing = 0
    rows = []
    for sn in ordered:
        s = seasons_raw.get(str(sn)) or {}
        total = int(s.get("total_eps", 0) or 0)
        watched = set(s.get("watched") or [])
        missing = [e for e in range(1, total + 1) if e not in watched]

        if not missing:
            continue

        total_missing += len(missing)
        short = ", ".join(f"E{e:02d}" for e in missing[:8])
        if len(missing) > 8:
            short += f" +{len(missing) - 8}"
        lines.append(f"📺 <b>S{sn:02d}</b> — <code>{short}</code>")

        rows.append([InlineKeyboardButton(
            f"📤 Send missing S{sn:02d} ({len(missing)})",
            callback_data=f"pw:sendmissing:{slug}:{sn}",
        )])

    if total_missing == 0:
        lines.append(f"🎉 {F.sc('all caught up!')}")

    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data=f"pw:open:{slug}",
        ),
        InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('close')}",
            callback_data="pw:close_session",
        ),
    ])

    await _safe_edit(
        q,
        "\n".join(lines)[:4000],
        InlineKeyboardMarkup(rows),
    )
    await q.answer()


# ============================================================
# WATCH ORDER (simplified — franchises)
# ============================================================

async def _show_watch_order(client, q, slug: str) -> None:
    uid = q.from_user.id
    from plugins.premium import state as S
    session = await S.get_session(uid, slug)
    if not session:
        return await q.answer("⚠️ Not found", show_alert=True)

    title = session.get("series_title") or ""

    text = "\n".join([
        f"{F.EMO['book']} <b>{F.fb('WATCH ORDER')}</b>",
        F.DIV, "",
        f"🎬 <b>{F.sc(str(title)[:50])}</b>",
        "",
        f"📌 {F.sc('watch order for this series')}",
        f"📌 {F.sc('recommended order for franchise')}",
        "",
        F.DIV_S,
        f"<i>{F.sc('coming soon — franchises supported in v2')}</i>",
    ])

    await _safe_edit(
        q,
        text,
        InlineKeyboardMarkup([[
            InlineKeyboardButton(
                f"{F.EMO['back']} {F.sc('back')}",
                callback_data=f"pw:open:{slug}",
            ),
            InlineKeyboardButton(
                f"{F.EMO['cross']} {F.sc('close')}",
                callback_data="pw:close_session",
            ),
        ]]),
    )
    await q.answer()


# ============================================================
# ADMIN PANEL (basic)
# ============================================================

async def _show_admin(client, q) -> None:
    from plugins.premium import state as S
    stats = await S.count_users()
    sessions = await S.count_sessions()

    text = "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"{F.EMO['crown']} <b>{F.fb('PREMIUM ADMIN')}</b>",
        F.DIV, "",
        f"✅ {F.sc('active')} · <b>{stats['active']}</b>",
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

    await _safe_edit(
        q,
        text,
        InlineKeyboardMarkup([[
            InlineKeyboardButton(
                f"{F.EMO['back']} {F.sc('back')}",
                callback_data="pw:menu",
            ),
            InlineKeyboardButton(
                f"{F.EMO['cross']} {F.sc('close')}",
                callback_data="pw:menu_close",
            ),
        ]]),
    )
    await q.answer()


# ============================================================
# NOTIFICATIONS
# ============================================================

async def _notify_season_complete(client, uid, session, season) -> None:
    try:
        title = session.get("series_title") or "?"
        slug = session.get("series_slug") or ""

        text = "\n".join([
            f"{F.EMO['party']} <b>{F.fb(f'SEASON {season:02d} COMPLETE!')}</b>",
            F.DIV, "",
            f"🎬 <b>{F.sc(str(title)[:50])}</b>",
            "",
            f"🏆 {F.sc('great progress!')}",
        ])

        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                f"{F.EMO['play']} {F.sc('next season')}",
                callback_data=f"pw:seasons:{slug}",
            ),
        ]])

        await client.send_message(
            chat_id=uid,
            text=text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.debug(f"[PREM] season notify: {e}")


async def _notify_series_complete(client, uid, session) -> None:
    try:
        title = session.get("series_title") or "?"
        slug = session.get("series_slug") or ""
        from plugins.premium import state as S
        p = S.compute_progress(session)

        text = "\n".join([
            f"{F.EMO['trophy']} <b>{F.fb('CONGRATULATIONS!')}</b>",
            F.DIV, "",
            f"🎬 <b>{F.sc(str(title)[:50])}</b>",
            "",
            f"{F.EMO['party']} <b>{F.sc('SERIES COMPLETE')}</b>",
            f"📊 <code>{p['total_watched']}/{p['total_eps']}</code>",
        ])

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                f"{F.EMO['star']} {F.sc('rate series')}",
                callback_data=f"pw:rate_menu:{slug}",
            )],
            [InlineKeyboardButton(
                f"{F.EMO['trophy']} {F.sc('mark complete')}",
                callback_data=f"pw:complete:{slug}",
            )],
        ])

        await client.send_message(
            chat_id=uid,
            text=text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.debug(f"[PREM] series notify: {e}")


# ============================================================
# AUTO DELETE
# ============================================================

async def _auto_delete(client, chat_id, msg_id, seconds):
    try:
        await asyncio.sleep(seconds)
        await client.delete_messages(chat_id, msg_id)
    except Exception:
        pass


# ============================================================
# HELPERS
# ============================================================

def snapshot() -> Dict[str, Any]:
    return {"module": "premium_watch"}


# ============================================================
# PUBLIC
# ============================================================

__all__ = [
    "cmd_premium",
    "open_from_token",
    "snapshot",
]
