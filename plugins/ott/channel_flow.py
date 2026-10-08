# ============================================================
# 🏨 DOWNTOWN VILLA — OTT CHANNEL BROADCAST FLOW
# ============================================================

from __future__ import annotations
import logging
import time
from typing import Any, Dict, Optional

from pyrogram import Client
from pyrogram.enums import ParseMode
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
)

from plugins.broadcast.config import (
    fb, sc, _fmt_int, _fmt_duration, DIV, DIV2,
)
from plugins.ott import database as DB
from plugins.ott.tmdb import poster_url

logger = logging.getLogger(__name__)

# message_id → setup dict
_SETUPS: Dict[int, Dict[str, Any]] = {}
SETUP_TTL = 3600


def _cleanup():
    now = time.time()
    for k in list(_SETUPS.keys()):
        if now - _SETUPS[k].get("created", 0) > SETUP_TTL:
            _SETUPS.pop(k, None)


def get_setup(msg_id: int) -> Optional[Dict[str, Any]]:
    _cleanup()
    return _SETUPS.get(int(msg_id))


def drop_setup(msg_id: int) -> None:
    _SETUPS.pop(int(msg_id), None)


# ═══════════════════════════════════════════════════════════
# SETUP TEXT + KB
# ═══════════════════════════════════════════════════════════

def _setup_text(movie: Dict[str, Any], notify: bool, show_file: bool,
                hours: int, channel: int) -> str:
    title = (movie.get("title") or "?")[:60]
    year = (movie.get("release_date") or "")[:4]
    provider = movie.get("provider") or "—"
    rel = movie.get("release_date") or "—"

    notify_lbl = "🟢 on" if notify else "🔴 off"
    file_lbl = "🟢 on" if show_file else "🔴 off"
    timer_lbl = "♾️ never" if hours <= 0 else f"⏱️ {hours}h"

    return "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"⚙️ <b>{fb('BROADCAST SETUP')}</b>",
        DIV, "",
        f"🎬 <b>{sc(title)}</b> ({year})",
        f"📺 <code>{sc(provider)}</code> · 📅 <code>{rel}</code>",
        "", DIV2,
        f"🔔 {sc('notify button')} · <b>{notify_lbl}</b>",
        f"📥 {sc('get file button')} · <b>{file_lbl}</b>",
        f"🗑️ {sc('auto-delete')} · <b>{timer_lbl}</b>",
        f"📢 {sc('post will go to this channel')}",
        "", DIV2,
        f"📌 {sc('tap buttons below to configure')}",
        f"📌 {sc('then press POST NOW')}",
    ])


def _setup_kb(movie: Dict[str, Any], notify: bool, show_file: bool,
              hours: int) -> InlineKeyboardMarkup:
    tid = movie.get("tmdb_id")
    notify_lbl = "🟢" if notify else "🔴"
    file_lbl = "🟢" if show_file else "🔴"
    timer_lbl = "♾️" if hours <= 0 else f"⏱️ {hours}h"

    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"🔔 Notify button · {notify_lbl}",
            callback_data=f"ott:csetup_n:{tid}")],
        [InlineKeyboardButton(
            f"📥 Get File button · {file_lbl}",
            callback_data=f"ott:csetup_f:{tid}")],
        [InlineKeyboardButton(
            f"🗑️ Auto-delete · {timer_lbl}",
            callback_data=f"ott:csetup_t:{tid}")],
        [InlineKeyboardButton(
            f"🚀 {sc('POST NOW')}",
            callback_data=f"ott:csetup_go:{tid}")],
        [InlineKeyboardButton(
            f"❌ {sc('Cancel setup')}",
            callback_data=f"ott:csetup_x:{tid}")],
    ])


def _timer_kb(movie: Dict[str, Any], current: int) -> InlineKeyboardMarkup:
    from plugins.ott.config import BC_DELETE_HOURS
    tid = movie.get("tmdb_id")
    rows, row = [], []
    for h in BC_DELETE_HOURS:
        label = "♾️" if h == 0 else f"{h}h"
        mark = "✅ " if h == current else ""
        row.append(InlineKeyboardButton(
            f"{mark}{label}",
            callback_data=f"ott:csetup_td:{tid}:{h}"))
        if len(row) == 4:
            rows.append(row); row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(
        f"⬅️ {sc('Back')}",
        callback_data=f"ott:csetup:{tid}")])
    return InlineKeyboardMarkup(rows)


# ═══════════════════════════════════════════════════════════
# OPEN SETUP (posts to the OTT channel)
# ═══════════════════════════════════════════════════════════

async def open_setup(client: Client, q: CallbackQuery, tmdb_id: int):
    """Post a setup message in the OTT channel."""
    from plugins.ott.engine import get_ott_channel
    ch = await get_ott_channel()
    if not ch:
        return await q.answer(
            "⚠️ Set OTT channel first (Settings → 📢 OTT Channel)",
            show_alert=True)

    movie = await DB.get_movie(tmdb_id)
    if not movie:
        return await q.answer("⚠️ Movie not found", show_alert=True)

    cfg = await DB.get_cfg()
    default_hours = int(cfg.get("broadcast_ttl_hours", 24))

    text = _setup_text(movie, True, True, default_hours, ch)
    kb = _setup_kb(movie, True, True, default_hours)

    try:
        sent = await client.send_message(
            chat_id=ch, text=text, reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.exception(f"[OTT-CF] open: {e}")
        return await q.answer(f"❌ {type(e).__name__}", show_alert=True)

    _SETUPS[sent.id] = {
        "message_id": sent.id,
        "chat_id": ch,
        "tmdb_id": tmdb_id,
        "notify": True,
        "show_file": True,
        "auto_delete_hours": default_hours,
        "admin_id": q.from_user.id,
        "created": time.time(),
    }

    await q.answer("📢 Setup posted in channel")


# ═══════════════════════════════════════════════════════════
# EDIT SETUP IN CHANNEL
# ═══════════════════════════════════════════════════════════

async def _edit_setup(client: Client, msg_id: int,
                       movie: Dict[str, Any], s: Dict[str, Any]):
    text = _setup_text(movie, s["notify"], s["show_file"],
                       s["auto_delete_hours"], s["chat_id"])
    kb = _setup_kb(movie, s["notify"], s["show_file"],
                   s["auto_delete_hours"])
    try:
        await client.edit_message_text(
            chat_id=s["chat_id"], message_id=msg_id,
            text=text, reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.debug(f"[OTT-CF] edit: {e}")


async def toggle_notify(client: Client, q: CallbackQuery, tmdb_id: int):
    s = _find_setup_by_msg(q.message.id)
    if not s:
        return await q.answer("⏱️ Expired", show_alert=True)
    s["notify"] = not s["notify"]
    movie = await DB.get_movie(tmdb_id) or {}
    await _edit_setup(client, s["message_id"], movie, s)
    return await q.answer("🟢 on" if s["notify"] else "🔴 off")


async def toggle_file(client: Client, q: CallbackQuery, tmdb_id: int):
    s = _find_setup_by_msg(q.message.id)
    if not s:
        return await q.answer("⏱️ Expired", show_alert=True)
    s["show_file"] = not s["show_file"]
    movie = await DB.get_movie(tmdb_id) or {}
    await _edit_setup(client, s["message_id"], movie, s)
    return await q.answer("🟢 on" if s["show_file"] else "🔴 off")


async def show_timer(client: Client, q: CallbackQuery, tmdb_id: int):
    s = _find_setup_by_msg(q.message.id)
    if not s:
        return await q.answer("⏱️ Expired", show_alert=True)
    movie = await DB.get_movie(tmdb_id) or {}
    try:
        await q.message.edit_reply_markup(
            reply_markup=_timer_kb(movie, s["auto_delete_hours"]))
    except Exception:
        pass
    return await q.answer()


async def set_timer(client: Client, q: CallbackQuery, tmdb_id: int,
                     hours: int):
    s = _find_setup_by_msg(q.message.id)
    if not s:
        return await q.answer("⏱️ Expired", show_alert=True)
    s["auto_delete_hours"] = int(hours)
    movie = await DB.get_movie(tmdb_id) or {}
    await _edit_setup(client, s["message_id"], movie, s)
    return await q.answer(f"✅ {hours}h" if hours else "♾️")


async def cancel_setup(client: Client, q: CallbackQuery):
    s = _find_setup_by_msg(q.message.id)
    if not s:
        return await q.answer("⏱️ Expired", show_alert=True)
    drop_setup(s["message_id"])
    try:
        await q.message.delete()
    except Exception:
        pass
    return await q.answer("❌ Cancelled")


def _find_setup_by_msg(msg_id: int) -> Optional[Dict[str, Any]]:
    _cleanup()
    return _SETUPS.get(int(msg_id))


# ═══════════════════════════════════════════════════════════
# POST NOW — replace setup msg with the final broadcast
# ═══════════════════════════════════════════════════════════

async def post_now(client: Client, q: CallbackQuery, tmdb_id: int):
    s = _find_setup_by_msg(q.message.id)
    if not s:
        return await q.answer("⏱️ Expired", show_alert=True)

    movie = await DB.get_movie(tmdb_id)
    if not movie:
        return await q.answer("⚠️ Movie not found", show_alert=True)

    from plugins.ott.engine import build_caption
    from plugins.ott.keyboards import kb_channel_post

    notify = s["notify"]
    show_file = s["show_file"]
    hours = s["auto_delete_hours"]
    ttl = hours * 3600 if hours > 0 else 0
    ch = s["chat_id"]

    # Delete the setup message
    try:
        await q.message.delete()
    except Exception:
        pass

    caption = build_caption(movie)
    kb = kb_channel_post(tmdb_id, notify=notify, show_file=show_file)
    poster = poster_url(movie.get("poster_path"), "w500")

    sent = None
    try:
        if poster:
            try:
                sent = await client.send_photo(
                    chat_id=ch, photo=poster, caption=caption,
                    reply_markup=kb, parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass
        if sent is None:
            sent = await client.send_message(
                chat_id=ch, text=caption, reply_markup=kb,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
    except Exception as e:
        logger.exception(f"[OTT-CF] post: {e}")
        return await q.answer(f"❌ {type(e).__name__}", show_alert=True)

    if ttl > 0 and sent:
        try:
            await DB.pending_add(ch, sent.id, ttl)
        except Exception:
            pass

    try:
        await DB.broadcast_log(
            tmdb_id=tmdb_id, target="ott_channel",
            delivered=1, failed=0, total=1,
            admin_id=q.from_user.id,
            channel_msg_id=sent.id if sent else 0,
        )
    except Exception:
        pass

    drop_setup(s["message_id"])
    return await q.answer("✅ Posted to channel")


__all__ = [
    "open_setup", "toggle_notify", "toggle_file",
    "show_timer", "set_timer", "cancel_setup", "post_now",
    "get_setup", "drop_setup",
]
