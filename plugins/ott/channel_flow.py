# ============================================================
# 🏨 DOWNTOWN VILLA — OTT CHANNEL FLOW (setup + broadcast)
# ============================================================
# Everything after "Setup Broadcast" happens in the ADMIN channel.
# Setup message transforms into live post (same message id).
# ============================================================

from __future__ import annotations
import logging
import time
from typing import Any, Dict, List, Optional

from pyrogram import Client
from pyrogram.enums import ParseMode
from pyrogram.errors import MessageNotModified
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
)

from plugins.broadcast.config import (
    fb, sc, _fmt_int, DIV, DIV2,
)
from plugins.ott import database as DB
from plugins.ott import views as V
from plugins.ott import keyboards as KB
from plugins.ott.tmdb import poster_url

logger = logging.getLogger(__name__)

# message_id (in admin channel) → setup dict
_SETUPS: Dict[int, Dict[str, Any]] = {}
SETUP_TTL = 6 * 3600


def _cleanup():
    now = time.time()
    for k in list(_SETUPS.keys()):
        if now - _SETUPS[k].get("created", 0) > SETUP_TTL:
            _SETUPS.pop(k, None)


def find(msg_id: int) -> Optional[Dict[str, Any]]:
    _cleanup()
    return _SETUPS.get(int(msg_id))


def drop(msg_id: int) -> None:
    _SETUPS.pop(int(msg_id), None)


# ═══════════════════════════════════════════════════════════
# EDIT HELPERS
# ═══════════════════════════════════════════════════════════

async def _edit_msg(client: Client, chat_id: int, msg_id: int,
                    text: str, kb: InlineKeyboardMarkup,
                    has_media: bool = True) -> None:
    try:
        if has_media:
            await client.edit_message_caption(
                chat_id=chat_id, message_id=msg_id,
                caption=text, reply_markup=kb,
                parse_mode=ParseMode.HTML,
            )
        else:
            await client.edit_message_text(
                chat_id=chat_id, message_id=msg_id,
                text=text, reply_markup=kb,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
    except MessageNotModified:
        pass
    except Exception as e:
        logger.debug(f"[OTT-CF] edit: {e}")


# ═══════════════════════════════════════════════════════════
# OPEN SETUP (post in admin channel)
# ═══════════════════════════════════════════════════════════

async def open_setup(client: Client, q: CallbackQuery, tmdb_id: int) -> None:
    from plugins.ott.engine import get_ott_channel
    ch = await get_ott_channel()
    if not ch:
        return await q.answer(
            "⚠️ Set OTT channel first (Settings → 📢 OTT Channel)",
            show_alert=True)

    raw = await DB.get_movie(tmdb_id)
    if not raw:
        return await q.answer("⚠️ Movie not found", show_alert=True)

    from plugins.ott.tmdb import enrich_movie
    movie = await enrich_movie(raw)

    cfg = await DB.get_cfg()
    default_hours = int(cfg.get("broadcast_ttl_hours", 24))

    text, kb = await V.view_setup(movie, True, True, default_hours)
    poster = poster_url(movie.get("poster_path"), "w500")

    sent = None
    try:
        if poster:
            try:
                sent = await client.send_photo(
                    chat_id=ch, photo=poster, caption=text,
                    reply_markup=kb, parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass
        if sent is None:
            sent = await client.send_message(
                chat_id=ch, text=text, reply_markup=kb,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
    except Exception as e:
        logger.exception(f"[OTT-CF] open setup: {e}")
        return await q.answer(f"❌ {type(e).__name__}", show_alert=True)

    _SETUPS[sent.id] = {
        "message_id": sent.id,
        "chat_id": ch,
        "tmdb_id": tmdb_id,
        "notify": True,
        "show_file": True,
        "auto_delete_hours": default_hours,
        "admin_id": q.from_user.id,
        "has_media": bool(poster),
        "created": time.time(),
    }
    await q.answer("📢 Setup posted in channel")


# ═══════════════════════════════════════════════════════════
# TOGGLES (in-place)
# ═══════════════════════════════════════════════════════════

async def _refresh_setup(client: Client, s: Dict[str, Any]) -> None:
    from plugins.ott.tmdb import enrich_movie
    raw = await DB.get_movie(s["tmdb_id"]) or {}
    movie = await enrich_movie(raw)
    text, kb = await V.view_setup(
        movie, s["notify"], s["show_file"], s["auto_delete_hours"])
    await _edit_msg(client, s["chat_id"], s["message_id"], text, kb,
                    has_media=s.get("has_media", True))


async def toggle_notify(client: Client, q: CallbackQuery, tmdb_id: int):
    s = find(q.message.id)
    if not s:
        return await q.answer("⏱️ Expired", show_alert=True)
    s["notify"] = not s["notify"]
    await _refresh_setup(client, s)
    return await q.answer("🟢 on" if s["notify"] else "🔴 off")


async def toggle_file(client: Client, q: CallbackQuery, tmdb_id: int):
    s = find(q.message.id)
    if not s:
        return await q.answer("⏱️ Expired", show_alert=True)
    s["show_file"] = not s["show_file"]
    await _refresh_setup(client, s)
    return await q.answer("🟢 on" if s["show_file"] else "🔴 off")


async def show_timer(client: Client, q: CallbackQuery, tmdb_id: int):
    s = find(q.message.id)
    if not s:
        return await q.answer("⏱️ Expired", show_alert=True)
    kb = KB.kb_timer(tmdb_id, s["auto_delete_hours"])
    try:
        if s.get("has_media"):
            await q.message.edit_reply_markup(reply_markup=kb)
        else:
            await q.message.edit_reply_markup(reply_markup=kb)
    except Exception:
        pass
    return await q.answer()


async def set_timer(client: Client, q: CallbackQuery, tmdb_id: int,
                     hours: int):
    s = find(q.message.id)
    if not s:
        return await q.answer("⏱️ Expired", show_alert=True)
    s["auto_delete_hours"] = int(hours)
    await _refresh_setup(client, s)
    return await q.answer(f"✅ {hours}h" if hours else "♾️")


async def cancel_setup(client: Client, q: CallbackQuery, tmdb_id: int):
    s = find(q.message.id)
    if not s:
        return await q.answer("⏱️ Expired", show_alert=True)
    drop(q.message.id)
    try:
        await q.message.delete()
    except Exception:
        pass
    return await q.answer("❌ Setup cancelled")


# ═══════════════════════════════════════════════════════════
# BROADCAST TARGET PICKER
# ═══════════════════════════════════════════════════════════

async def _count_targets() -> Dict[str, int]:
    counts = {"channels": 0, "groups": 0, "all": 0, "premium": 0}
    try:
        from plugins.broadcast import database as BDB
        counts["channels"] = len(await BDB.get_saved_channels())
        counts["groups"] = len(await BDB.get_all_groups())
        counts["all"] = len(await BDB.get_all_users())
    except Exception:
        pass
    try:
        from plugins.premium import state as PS
        users = await PS.list_users(limit=50000)
        counts["premium"] = len(users)
    except Exception:
        pass
    return counts


async def open_bc_picker(client: Client, q: CallbackQuery, tmdb_id: int):
    s = find(q.message.id)
    if not s:
        return await q.answer("⏱️ Expired", show_alert=True)

    counts = await _count_targets()
    kb = KB.kb_bc_targets(tmdb_id, counts)

    from plugins.ott.tmdb import enrich_movie
    movie = await enrich_movie(await DB.get_movie(tmdb_id) or {})
    title = (movie.get("title") or "?")[:50]

    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📢 <b>{fb('BROADCAST TO')}</b>",
        DIV, "",
        f"🎬 <b>{sc(title)}</b>",
        "", DIV2,
        f"📡 {sc('channels')} · <b>{counts['channels']}</b>",
        f"👥 {sc('groups')} · <b>{counts['groups']}</b>",
        f"👤 {sc('all users')} · <b>{counts['all']}</b>",
        f"💎 {sc('premium')} · <b>{counts['premium']}</b>",
        "", DIV2,
        f"📌 {sc('pick where to send the live post')}",
    ])
    await _edit_msg(client, s["chat_id"], s["message_id"], text, kb,
                    has_media=s.get("has_media", True))
    return await q.answer()


async def show_channel_list(client: Client, q: CallbackQuery, tmdb_id: int):
    s = find(q.message.id)
    if not s:
        return await q.answer("⏱️ Expired", show_alert=True)
    try:
        from plugins.broadcast import database as BDB
        chans = await BDB.get_saved_channels()
    except Exception:
        chans = []

    if not chans:
        return await q.answer("⚠️ No channels saved", show_alert=True)

    kb = KB.kb_bc_channels(tmdb_id, chans)
    from plugins.ott.tmdb import enrich_movie
    movie = await enrich_movie(await DB.get_movie(tmdb_id) or {})
    title = (movie.get("title") or "?")[:50]

    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📡 <b>{fb('PICK A CHANNEL')}</b>",
        DIV, "",
        f"🎬 <b>{sc(title)}</b>",
        "", DIV2,
        f"📌 {sc('tap a channel, or ALL CHANNELS')}",
    ])
    await _edit_msg(client, s["chat_id"], s["message_id"], text, kb,
                    has_media=s.get("has_media", True))
    return await q.answer()


async def confirm_bc(client: Client, q: CallbackQuery, tmdb_id: int,
                     kind: str, target_id: int):
    s = find(q.message.id)
    if not s:
        return await q.answer("⏱️ Expired", show_alert=True)

    label = {
        "ch": f"channel {target_id}",
        "chall": "ALL channels",
        "gr": "ALL groups",
        "us": "ALL users",
        "pm": "premium users",
    }.get(kind, kind)

    kb = KB.kb_bc_confirm(tmdb_id, kind, target_id, label)
    from plugins.ott.tmdb import enrich_movie
    movie = await enrich_movie(await DB.get_movie(tmdb_id) or {})
    title = (movie.get("title") or "?")[:50]

    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"⚠️ <b>{fb('CONFIRM BROADCAST')}</b>",
        DIV, "",
        f"🎬 <b>{sc(title)}</b>",
        f"🎯 {sc('target')} · <b>{label}</b>",
        "", DIV2,
        f"📌 {sc('a live post with Get Notified button will be sent')}",
        "", f"❓ {sc('proceed?')}",
    ])
    await _edit_msg(client, s["chat_id"], s["message_id"], text, kb,
                    has_media=s.get("has_media", True))
    return await q.answer()


async def do_broadcast(client: Client, q: CallbackQuery, tmdb_id: int,
                        kind: str, target_id: int):
    s = find(q.message.id)
    if not s:
        return await q.answer("⏱️ Expired", show_alert=True)

    from plugins.ott.engine import send_to_targets
    await q.answer("📤 Broadcasting…")

    delivered, failed, total = await send_to_targets(
        client=client,
        tmdb_id=tmdb_id,
        notify=s["notify"],
        show_file=s["show_file"],
        kind=kind,
        target_id=target_id,
        admin_id=q.from_user.id,
    )

    # Show result
    from plugins.ott.tmdb import enrich_movie
    movie = await enrich_movie(await DB.get_movie(tmdb_id) or {})
    title = (movie.get("title") or "?")[:50]

    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"✅ <b>{fb('BROADCAST DONE')}</b>",
        DIV, "",
        f"🎬 <b>{sc(title)}</b>",
        f"🎯 <code>{kind}</code>",
        "", DIV2,
        f"📬 {sc('delivered')} · <b>{_fmt_int(delivered)}</b>",
        f"❌ {sc('failed')} · <b>{_fmt_int(failed)}</b>",
        f"📊 {sc('total')} · <b>{_fmt_int(total)}</b>",
        "", DIV2,
        f"📌 {sc('back to setup to POST NOW in admin channel')}",
    ])
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "⬅️ Back to setup",
            callback_data=f"ott:csetup:{tmdb_id}")],
    ])
    await _edit_msg(client, s["chat_id"], s["message_id"], text, kb,
                    has_media=s.get("has_media", True))


# ═══════════════════════════════════════════════════════════
# POST NOW (transform setup → live)
# ═══════════════════════════════════════════════════════════

async def post_now(client: Client, q: CallbackQuery, tmdb_id: int):
    s = find(q.message.id)
    if not s:
        return await q.answer("⏱️ Expired", show_alert=True)

    from plugins.ott.tmdb import enrich_movie
    movie = await enrich_movie(await DB.get_movie(tmdb_id) or {})

    notify = s["notify"]
    show_file = s["show_file"]
    hours = s["auto_delete_hours"]
    ttl = hours * 3600 if hours > 0 else 0
    ch = s["chat_id"]

    # Log broadcast (stores admin post id for later stat refresh)
    bc_id = await DB.broadcast_log(
        tmdb_id=tmdb_id, target="admin_channel",
        delivered=0, failed=0, total=0,
        admin_id=q.from_user.id,
        channel_msg_id=q.message.id,
    )
    try:
        await DB.broadcasts_coll().update_one(
            {"_id": __import__("bson").ObjectId(bc_id)}
            if bc_id and len(bc_id) == 24 else {"tmdb_id": tmdb_id},
            {"$set": {
                "channel_msg_id": q.message.id,
                "channel_chat_id": ch,
            }},
        )
    except Exception:
        pass

    # Schedule auto-delete of the admin post
    if ttl > 0:
        try:
            await DB.pending_add(ch, q.message.id, ttl)
        except Exception:
            pass

    # Edit → live post
    text, kb = await V.view_live(
        movie, notify=notify, show_file=show_file,
        is_admin_view=True, ended=False)
    await _edit_msg(client, ch, q.message.id, text, kb,
                    has_media=s.get("has_media", True))

    # Drop setup (no longer editable as setup)
    drop(s["message_id"])
    return await q.answer("✅ Posted as live post")


# ═══════════════════════════════════════════════════════════
# REFRESH ADMIN POST (called after user sub / notify / etc.)
# ═══════════════════════════════════════════════════════════

async def refresh_admin_post(client: Client, tmdb_id: int) -> None:
    """Find the admin channel post for this movie and update its stats."""
    bc = await DB.broadcast_get_latest(tmdb_id)
    if not bc:
        return
    msg_id = bc.get("channel_msg_id")
    chat_id = bc.get("channel_chat_id")
    if not msg_id or not chat_id:
        return

    from plugins.ott.tmdb import enrich_movie
    movie = await enrich_movie(await DB.get_movie(tmdb_id) or {})
    ended = bool(bc.get("cancelled"))
    notify = True
    show_file = True

    text, kb = await V.view_live(
        movie, notify=notify, show_file=show_file,
        is_admin_view=True, ended=ended)

    try:
        try:
            await client.edit_message_caption(
                chat_id=int(chat_id), message_id=int(msg_id),
                caption=text, reply_markup=kb,
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            await client.edit_message_text(
                chat_id=int(chat_id), message_id=int(msg_id),
                text=text, reply_markup=kb,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
    except Exception as e:
        logger.debug(f"[OTT-CF] refresh admin post: {e}")


__all__ = [
    "open_setup", "toggle_notify", "toggle_file",
    "show_timer", "set_timer", "cancel_setup",
    "open_bc_picker", "show_channel_list",
    "confirm_bc", "do_broadcast", "post_now",
    "refresh_admin_post", "find", "drop",
]
