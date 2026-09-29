# ============================================================
# 🎛️ AI LIBRARIAN v5 — MAIN HANDLERS
# ============================================================
from __future__ import annotations
import asyncio, logging, re, time
from datetime import datetime
from typing import Any, Dict, List, Optional

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from plugins.ai_librarian.fonts import (
    fb, sc, DIV, DIV2, IST,
    _fmt_int, _esc, _is_admin, _now_ist,
)
from plugins.ai_librarian.db import (
    _list_completed, _count_completed,
    _get_setting, _set_setting,
    _mark_completed, _unmark_completed,
    _completed_coll,
)
from plugins.ai_librarian.scan import (
    _engine_search, SeriesCatalog,
)
from plugins.ai_librarian.tmdb import (
    _tmdb_search_series, _tmdb_series_details, _tmdb_seasons,
)
from plugins.ai_librarian.sessions import (
    _new_session, _get_session, _clear_session,
    _kill_live_task, _cleanup_sessions,
    _LIVE_TASKS,
)
from plugins.ai_librarian.views import (
    kb_main, kb_back, kb_add_cancel, kb_suggestions,
    _view_main, _view_add_prompt, _view_searching,
    _safe_edit,
)
from plugins.ai_librarian.live import (
    _render_live,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# COMMAND
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_message(
    filters.command(["ai", "librarian", "ailib"]) & filters.private,
    group=-430,
)
async def cmd_ai(client, message):
    if not message.from_user or not _is_admin(message.from_user.id):
        return await message.reply_text("⛔ ᴀᴅᴍɪɴꜱ ᴏɴʟʏ.")
    try:
        _clear_session(message.from_user.id)
        text, kb = await _view_main()
        await message.reply_text(text, reply_markup=kb,
                                  parse_mode=ParseMode.HTML,
                                  disable_web_page_preview=True)
    except Exception as e:
        logger.exception(f"[AI] /ai: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# MAIN CALLBACKS
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^ai:main$"), group=-430)
async def cb_main(client, q):
    try:
        _clear_session(q.from_user.id)
        text, kb = await _view_main()
        await _safe_edit(q, text, kb)
        await q.answer()
    except Exception as e:
        logger.exception(f"[AI] cb_main: {e}")


@Client.on_callback_query(filters.regex(r"^ai:close$"), group=-430)
async def cb_close(client, q):
    try:
        _clear_session(q.from_user.id)
        try: await q.message.delete()
        except Exception: pass
        await q.answer("ᴄʟᴏꜱᴇᴅ")
    except Exception:
        try: await q.answer("ᴄʟᴏꜱᴇᴅ")
        except Exception: pass


@Client.on_callback_query(filters.regex(r"^ai:toggle_auto$"), group=-430)
async def cb_toggle(client, q):
    try:
        cur = await _get_setting("auto_mode", True)
        await _set_setting("auto_mode", not cur)
        await q.answer("🟢 ᴀᴜᴛᴏ ᴏɴ" if not cur else "🔴 ᴀᴜᴛᴏ ᴏꜰꜰ")
        text, kb = await _view_main()
        await _safe_edit(q, text, kb)
    except Exception as e:
        logger.exception(f"[AI] toggle: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# ADD SERIES → TMDB SUGGEST → START LIVE
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^ai:add$"), group=-430)
async def cb_add(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    try:
        _clear_session(q.from_user.id)
        _new_session(q.from_user.id, "await_add_name",
                     chat_id=q.message.chat.id,
                     msg_id=q.message.id)
        await _safe_edit(q, _view_add_prompt(), kb_add_cancel())
        await q.answer()
    except Exception as e:
        logger.exception(f"[AI] add: {e}")


@Client.on_message(
    filters.private & filters.text & ~filters.regex(r"^/"),
    group=-429,
)
async def ai_add_input(client, message):
    """Catches the series name admin typed."""
    if not message.from_user: return
    if not _is_admin(message.from_user.id): return

    s = _get_session(message.from_user.id)
    if not s or s.get("action") != "await_add_name":
        return

    try: message.stop_propagation()
    except Exception: pass

    query = (message.text or "").strip()
    if len(query) < 2:
        return await message.reply_text("❌ ᴛᴏᴏ ꜱʜᴏʀᴛ.")

    uid = message.from_user.id
    chat_id = message.chat.id

    _new_session(uid, "await_pick",
                 query=query,
                 chat_id=chat_id,
                 msg_id=s.get("msg_id"))

    loading = await message.reply_text(_view_searching(query),
                                        parse_mode=ParseMode.HTML)

    # 1. TMDB suggest first
    suggestions = await _tmdb_search_series(query)

    if suggestions:
        _new_session(uid, "await_pick",
                     query=query,
                     suggestions=suggestions,
                     chat_id=chat_id,
                     msg_id=loading.id)
        lines = [
            f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
            f"🔎 <b>{fb('TMDB SUGGESTIONS')}</b>",
            DIV, "",
            f"📝 <code>{_esc(query)}</code>", "",
            f"📌 {sc('tap a title to start live scan')}",
            "", DIV2, "",
        ]
        for i, it in enumerate(suggestions, 1):
            t = it.get("title") or "?"
            yr = it.get("year") or ""
            r = it.get("rating", 0)
            lines.append(
                f"<b>{i}.</b> <b>{_esc(t)}</b>"
                + (f" <code>({yr})</code>" if yr else "")
                + (f" · ⭐ {r:.1f}" if r else "")
            )
        try:
            await client.edit_message_text(
                chat_id=chat_id, message_id=loading.id,
                text="\n".join(lines),
                reply_markup=kb_suggestions(suggestions),
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except Exception as e:
            logger.warning(f"[AI] suggest render: {e}")
        return

    # 2. No TMDB → scan DB directly
    await _start_live_scan(client, uid, chat_id, loading.id,
                            title=query, year="",
                            tmdb_seasons=[], matched_title=None)


@Client.on_callback_query(filters.regex(r"^ai:pick:(\d+)$"), group=-430)
async def cb_pick(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    try:
        idx = int(q.matches[0].group(1))
        s = _get_session(q.from_user.id)
        if not s or s.get("action") != "await_pick":
            return await q.answer("⏱️ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ", show_alert=True)

        items = s.get("suggestions") or []
        if idx < 0 or idx >= len(items):
            return await q.answer("⚠️ ɪɴᴠᴀʟɪᴅ", show_alert=True)

        chosen = items[idx]
        title = chosen.get("title") or ""
        year = chosen.get("year") or ""
        tmdb_id = chosen.get("tmdb_id")

        await q.answer("🔍 ꜱᴛᴀʀᴛɪɴɢ ʟɪᴠᴇ ꜱᴄᴀɴ...")

        tmdb_seasons = []
        if tmdb_id:
            details = await _tmdb_series_details(tmdb_id)
            if details:
                tmdb_seasons = _tmdb_seasons(details)

        await _start_live_scan(client, q.from_user.id,
                                q.message.chat.id, q.message.id,
                                title=title, year=year,
                                tmdb_seasons=tmdb_seasons,
                                matched_title=title)
    except Exception as e:
        logger.exception(f"[AI] pick: {e}")
        try: await q.answer("⚠️ ᴇʀʀᴏʀ", show_alert=True)
        except Exception: pass


@Client.on_callback_query(filters.regex(r"^ai:search_db_only$"), group=-430)
async def cb_search_db_only(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    try:
        s = _get_session(q.from_user.id)
        if not s or s.get("action") != "await_pick":
            return await q.answer("⏱️ ꜱᴇꜱꜱɪᴏɴ ᴇxᴘɪʀᴇᴅ", show_alert=True)
        query = s.get("query") or ""

        await q.answer("🔍 ꜱᴄᴀɴɴɪɴɢ ᴅʙ...")
        await _start_live_scan(client, q.from_user.id,
                                q.message.chat.id, q.message.id,
                                title=query, year="",
                                tmdb_seasons=[],
                                matched_title=query)
    except Exception as e:
        logger.exception(f"[AI] search_db_only: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# START LIVE SCAN
# ═══════════════════════════════════════════════════════════════════════════
async def _start_live_scan(client, uid, chat_id, msg_id,
                            title, year, tmdb_seasons, matched_title=None):
    search_term = matched_title or title
    logger.info(f"[AI-LIVE] starting for {title!r} (search={search_term!r})")

    try:
        files = await _engine_search(search_term)
    except Exception as e:
        logger.warning(f"[AI-LIVE] initial search: {e}")
        files = []

    cat = SeriesCatalog()
    for f in files:
        cat.add_file(f)

    db_title = title
    if files:
        first = files[0]
        db_title = first.get("series_title") or first.get("title") or title

    _new_session(uid, "live_scan",
                 search_term=search_term,
                 title=db_title,
                 year=year,
                 tmdb_seasons=tmdb_seasons or [],
                 catalog_data=cat.data,
                 chat_id=chat_id,
                 msg_id=msg_id,
                 started_at=time.time())

    total_expected = sum(s.get("episodes", 0) for s in (tmdb_seasons or []))
    await _render_live(client, chat_id, msg_id, uid,
                        elapsed=0, total_expected=total_expected)

    _kill_live_task(uid)
    from plugins.ai_librarian.live import _live_refresher
    task = asyncio.create_task(
        _live_refresher(client, uid, chat_id, msg_id)
    )
    _LIVE_TASKS[uid] = task


# ═══════════════════════════════════════════════════════════════════════════
# LIVE CONTROLS
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^ai:live_refresh$"), group=-430)
async def cb_live_refresh(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    try:
        uid = q.from_user.id
        sess = _get_session(uid)
        if not sess or sess.get("action") != "live_scan":
            return await q.answer("⏱️ ɴᴏ ʟɪᴠᴇ ꜱᴇꜱꜱɪᴏɴ", show_alert=True)

        await q.answer("🔄 ʀᴇꜰʀᴇꜱʜɪɴɢ...")

        search_term = sess.get("search_term") or ""
        files = await _engine_search(search_term)

        cat = SeriesCatalog()
        for f in files:
            cat.add_file(f)
        sess["catalog_data"] = cat.data

        tmdb_seasons = sess.get("tmdb_seasons") or []
        total_expected = sum(s.get("episodes", 0) for s in tmdb_seasons)
        elapsed = time.time() - sess.get("started_at", time.time())

        await _render_live(client, q.message.chat.id, q.message.id, uid,
                            elapsed=elapsed,
                            total_expected=total_expected)
    except Exception as e:
        logger.exception(f"[AI] live_refresh: {e}")
        try: await q.answer("⚠️ ᴇʀʀᴏʀ", show_alert=True)
        except Exception: pass


@Client.on_callback_query(filters.regex(r"^ai:live_cancel$"), group=-430)
async def cb_live_cancel(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    try:
        uid = q.from_user.id
        sess = _get_session(uid)
        if not sess or sess.get("action") != "live_scan":
            _clear_session(uid)
            await q.answer("✅ ᴄᴀɴᴄᴇʟʟᴇᴅ")
            text, kb = await _view_main()
            await _safe_edit(q, text, kb)
            return

        title = sess.get("title") or "?"
        _clear_session(uid)

        await q.answer("❌ ʟɪᴠᴇ ᴄᴀɴᴄᴇʟʟᴇᴅ")
        text = "\n".join([
            f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
            f"❌ <b>{fb('LIVE CANCELLED')}</b>",
            DIV, "",
            f"🎬 <b>{_esc(title)}</b>",
            "",
            f"📌 {sc('no changes were saved')}",
            f"📌 {sc('tap add series to restart')}",
        ])
        await _safe_edit(q, text, kb_back("ai:main"))
    except Exception as e:
        logger.exception(f"[AI] live_cancel: {e}")


@Client.on_callback_query(filters.regex(r"^ai:live_complete$"), group=-430)
async def cb_live_complete(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    try:
        uid = q.from_user.id
        sess = _get_session(uid)
        if not sess or sess.get("action") != "live_scan":
            return await q.answer("⏱️ ɴᴏ ʟɪᴠᴇ ꜱᴇꜱꜱɪᴏɴ", show_alert=True)

        title = sess.get("title") or "?"
        catalog_data = sess.get("catalog_data") or {}

        slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
        if not slug:
            return await q.answer("⚠️ ɪɴᴠᴀʟɪᴅ ᴛɪᴛʟᴇ", show_alert=True)

        total_files = 0
        for series in catalog_data.values():
            total_files += series.get("file_count", 0)

        ok = await _mark_completed(title, slug, total_files)
        if not ok:
            return await q.answer("❌ ꜱᴀᴠᴇ ꜰᴀɪʟᴇᴅ", show_alert=True)

        _clear_session(uid)

        await q.answer("✅ ᴍᴀʀᴋᴇᴅ ᴄᴏᴍᴘʟᴇᴛᴇ")
        text = "\n".join([
            f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
            f"✅ <b>{fb('MARKED COMPLETE')}</b>",
            DIV, "",
            f"🎬 <b>{_esc(title)}</b>",
            f"📁 <code>{_fmt_int(total_files)}</code> ꜰɪʟᴇꜱ",
            f"📅 <code>{_now_ist()}</code>",
            "", DIV2,
            f"📌 {sc('will be skipped in future scans')}",
        ])
        await _safe_edit(q, text, kb_back("ai:main"))
    except Exception as e:
        logger.exception(f"[AI] live_complete: {e}")
        try: await q.answer("⚠️ ᴇʀʀᴏʀ", show_alert=True)
        except Exception: pass


# ═══════════════════════════════════════════════════════════════════════════
# VIEW / LIST SERIES
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^ai:all$"), group=-430)
async def cb_all(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    try:
        _clear_session(q.from_user.id)
        await q.answer("🔍 ʟᴏᴀᴅɪɴɢ...")

        comp = await _list_completed(200)
        if not comp:
            await _safe_edit(q,
                f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>\n\n⚪ ɴᴏ ꜱᴇʀɪᴇꜱ ʏᴇᴛ.",
                kb_back("ai:main"))
            return

        lines = [
            f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
            f"📚 <b>{fb('ALL SERIES')}</b>",
            DIV, "",
            f"📊 <code>{len(comp)}</code> ᴛᴏᴛᴀʟ",
            "", DIV2, "",
        ]
        for it in comp[:25]:
            lines.append(
                f"✅ <b>{_esc(it.get('title'))}</b> · "
                f"<code>{it.get('total_files', 0)}</code>"
            )
        await _safe_edit(q, "\n".join(lines), kb_back("ai:main"))
    except Exception as e:
        logger.exception(f"[AI] all: {e}")


@Client.on_callback_query(filters.regex(r"^ai:completed$"), group=-430)
async def cb_completed(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    try:
        await _render_completed(q)
        await q.answer()
    except Exception as e:
        logger.exception(f"[AI] completed: {e}")


async def _render_completed(q):
    items = await _list_completed(50)
    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"✅ <b>{fb('COMPLETED')}</b>",
        DIV, "",
    ]
    if not items:
        lines.append("⚪ ɴᴏɴᴇ ʏᴇᴛ.")
    else:
        for it in items[:30]:
            ts = it.get("completed_at", 0)
            try:
                d = datetime.fromtimestamp(ts, IST).strftime("%d %b %Y")
            except Exception:
                d = "?"
            lines.append(
                f"✅ <b>{_esc(it.get('title'))}</b> · <code>{d}</code>"
            )

    rows = [
        [InlineKeyboardButton(
            f"🔄 UNMARK · {(it.get('title') or '?')[:25]}",
            callback_data=f"ai:unmark:{it.get('title_slug')}",
        )]
        for it in items[:10]
    ]
    rows.append([
        InlineKeyboardButton("◀️ BACK", callback_data="ai:main"),
        InlineKeyboardButton("❌ CLOSE", callback_data="ai:close"),
    ])
    await _safe_edit(q, "\n".join(lines), InlineKeyboardMarkup(rows))


@Client.on_callback_query(filters.regex(r"^ai:unmark:([a-z0-9_]+)$"), group=-430)
async def cb_unmark(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    try:
        slug = q.matches[0].group(1)
        ok = await _unmark_completed(slug)
        await q.answer("✅ ᴜɴᴍᴀʀᴋᴇᴅ" if ok else "❌ ɴᴏᴛ ꜰᴏᴜɴᴅ")
        await _render_completed(q)
    except Exception as e:
        logger.exception(f"[AI] unmark: {e}")


@Client.on_callback_query(filters.regex(r"^ai:last_report$"), group=-430)
async def cb_last(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    try:
        comp = await _count_completed()
        total = await _get_setting("total_series", 0)
        await _safe_edit(q, "\n".join([
            f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
            f"📊 <b>{fb('STATUS')}</b>",
            DIV, "",
            f"📚 <code>{_fmt_int(total)}</code> · "
            f"✅ <code>{_fmt_int(comp)}</code>",
            "",
            f"🕒 <code>{_now_ist()}</code>",
        ]), kb_back("ai:main"))
        await q.answer()
    except Exception as e:
        logger.exception(f"[AI] last: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# VIEW SINGLE SERIES
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^ai:view:([a-z0-9_]+)$"), group=-430)
async def cb_view(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    try:
        slug = q.matches[0].group(1)
        c = _completed_coll()
        if c is None:
            return await q.answer("⚠️ ᴅʙ ᴇʀʀᴏʀ", show_alert=True)
        doc = await c.find_one({"title_slug": slug})
        if not doc:
            return await q.answer("⚠️ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)

        title = doc.get("title") or slug
        total_files = doc.get("total_files", 0)
        ts = doc.get("completed_at", 0)
        try:
            completed_str = datetime.fromtimestamp(ts, IST).strftime(
                "%d %b %Y · %H:%M IST")
        except Exception:
            completed_str = "?"

        await _safe_edit(q, "\n".join([
            f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
            f"✅ <b>{_esc(title)}</b>",
            DIV, "",
            f"📁 {sc('total files')} · <code>{_fmt_int(total_files)}</code>",
            f"📅 {sc('completed')} · <code>{completed_str}</code>",
            "", DIV2,
            f"💡 {sc('start a live scan to see current status')}",
        ]), kb_back("ai:main"))
        await q.answer()
    except Exception as e:
        logger.exception(f"[AI] view: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# BACKGROUND CLEANUP
# ═══════════════════════════════════════════════════════════════════════════
async def _cleanup_loop():
    while True:
        try:
            await asyncio.sleep(300)
            _cleanup_sessions()
        except asyncio.CancelledError:
            break
        except Exception: pass


_BOOTED = False


@Client.on_message(filters.private, group=-428)
async def _boot(client, message):
    global _BOOTED
    if _BOOTED:
        return
    _BOOTED = True
    try:
        loop = asyncio.get_running_loop()
        loop.create_task(_cleanup_loop())
        logger.info("[AI] cleanup loop started")
    except Exception as e:
        logger.warning(f"[AI] boot: {e}")


__all__ = ["cmd_ai"]

logger.info("🎛️ AI LIBRARIAN v5 LOADED — LIVE SCAN + SAME DB ENGINE")
