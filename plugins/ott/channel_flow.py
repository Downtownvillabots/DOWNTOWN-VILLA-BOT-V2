# ============================================================
# 🏨 DOWNTOWN VILLA — OTT CHANNEL FLOW (v3 — event-driven)
# ============================================================
# The event doc is the source of truth.
# The channel message is the source of truth UI.
# PM is only used to trigger the transition.
# ============================================================

from __future__ import annotations
import asyncio
import logging
from typing import Any, Dict, List, Optional, Tuple

from pyrogram import Client
from pyrogram.enums import ParseMode
from pyrogram.errors import MessageNotModified
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from plugins.broadcast.config import (
    fb, sc, _fmt_int, DIV, DIV2,
    BROADCAST_BATCH_SIZE, BROADCAST_CONCURRENCY, DEFAULT_DELAY,
)
from plugins.ott import database as DB
from plugins.ott import events as EVENTS
from plugins.ott import views as V
from plugins.ott import keyboards as KB
from plugins.ott import stats_sync as SYNC
from plugins.ott.tmdb import poster_url, enrich_movie

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════
# FIND EVENT BY MESSAGE ID
# ═══════════════════════════════════════════════════════════

async def find_by_msg(msg_id: int) -> Optional[Dict[str, Any]]:
    """Look up an event by its admin channel message id."""
    c = DB.events_coll()
    if c is None:
        return None
    try:
        return await c.find_one({"admin_msg_id": int(msg_id)})
    except Exception:
        return None


# ═══════════════════════════════════════════════════════════
# OPEN SETUP — critical PM → CHANNEL transition
# ═══════════════════════════════════════════════════════════

async def open_setup(client: Client, q: CallbackQuery, tmdb_id: int) -> None:
    """
    1. Post setup message to admin channel.
    2. Create event doc.
    3. Only on success → delete PM message.
    4. On failure → keep PM, show error.
    """
    from plugins.ott.engine import get_ott_channel
    ch = await get_ott_channel()
    if not ch:
        return await q.answer(
            "⚠️ Set OTT channel first (Settings → 📢 OTT Channel)",
            show_alert=True)

    raw = await DB.get_movie(tmdb_id)
    if not raw:
        return await q.answer("⚠️ Movie not found", show_alert=True)

    movie = await enrich_movie(raw)
    cfg = await DB.get_cfg()
    default_hours = int(cfg.get("broadcast_ttl_hours", 24))

    text, kb = await V.view_setup(movie, True, True, default_hours)
    poster = poster_url(movie.get("poster_path"), "w500")

    # ── Post to admin channel ──
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
        return await q.answer(
            f"❌ Could not create broadcast setup.\n{type(e).__name__}",
            show_alert=True)

    if not sent:
        return await q.answer("❌ Setup post failed. Try again.",
                              show_alert=True)

    # ── Create event doc ──
    eid = await EVENTS.create_event(
        tmdb_id=tmdb_id,
        title=movie.get("title") or "?",
        language=(movie.get("original_language") or "").upper(),
        admin_id=q.from_user.id,
        admin_channel_id=ch,
        admin_msg_id=sent.id,
    )
    if not eid:
        # Channel msg created but event failed — try to delete it
        try:
            await client.delete_messages(ch, sent.id)
        except Exception:
            pass
        return await q.answer("❌ Event create failed.", show_alert=True)

    # Sync counters immediately (in case there are already subs)
    try:
        await EVENTS.recount(eid)
    except Exception:
        pass

    # ── Answer + DELETE PM message ──
    await q.answer("📢 Setup posted in channel")
    try:
        await q.message.delete()
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════
# TOGGLES (in-place)
# ═══════════════════════════════════════════════════════════

async def toggle_notify(client: Client, q: CallbackQuery, tmdb_id: int):
    ev = await find_by_msg(q.message.id)
    if not ev:
        return await q.answer("⏱️ Expired", show_alert=True)
    new = not bool(ev.get("notify_enabled", True))
    await EVENTS.update_event(ev["_id"], notify_enabled=new)
    await SYNC.sync_admin_post(client, ev["_id"], force=True)
    return await q.answer("🟢 on" if new else "🔴 off")


async def toggle_file(client: Client, q: CallbackQuery, tmdb_id: int):
    ev = await find_by_msg(q.message.id)
    if not ev:
        return await q.answer("⏱️ Expired", show_alert=True)
    new = not bool(ev.get("get_files_enabled", True))
    await EVENTS.update_event(ev["_id"], get_files_enabled=new)
    await SYNC.sync_admin_post(client, ev["_id"], force=True)
    return await q.answer("🟢 on" if new else "🔴 off")


# ═══════════════════════════════════════════════════════════
# TIMER PICKER
# ═══════════════════════════════════════════════════════════

async def show_timer(client: Client, q: CallbackQuery, tmdb_id: int):
    ev = await find_by_msg(q.message.id)
    if not ev:
        return await q.answer("⏱️ Expired", show_alert=True)
    kb = KB.kb_timer(tmdb_id, int(ev.get("auto_delete_hours", 24)))
    try:
        await q.message.edit_reply_markup(reply_markup=kb)
    except Exception:
        pass
    return await q.answer()


async def set_timer(client: Client, q: CallbackQuery, tmdb_id: int,
                     hours: int):
    ev = await find_by_msg(q.message.id)
    if not ev:
        return await q.answer("⏱️ Expired", show_alert=True)
    await EVENTS.update_event(ev["_id"], auto_delete_hours=int(hours))
    await SYNC.sync_admin_post(client, ev["_id"], force=True)
    return await q.answer(f"✅ {hours}h" if hours else "♾️")


async def cancel_setup(client: Client, q: CallbackQuery, tmdb_id: int):
    ev = await find_by_msg(q.message.id)
    if not ev:
        return await q.answer("⏱️ Expired", show_alert=True)
    # Drop pending subs
    try:
        await DB.cancel_all_subs(tmdb_id)
    except Exception:
        pass
    await EVENTS.mark_ended(ev["_id"])
    SYNC.drop_lock(q.message.id)
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
        counts["premium"] = len(await PS.list_users(limit=50000))
    except Exception:
        pass
    return counts


async def open_bc_picker(client: Client, q: CallbackQuery, tmdb_id: int):
    ev = await find_by_msg(q.message.id)
    if not ev:
        return await q.answer("⏱️ Expired", show_alert=True)
    counts = await _count_targets()
    kb = KB.kb_bc_targets(tmdb_id, counts)

    movie = await DB.get_movie(tmdb_id) or {}
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
    await _edit_msg(client, ev, text, kb)
    return await q.answer()


async def show_channel_list(client: Client, q: CallbackQuery, tmdb_id: int):
    ev = await find_by_msg(q.message.id)
    if not ev:
        return await q.answer("⏱️ Expired", show_alert=True)
    try:
        from plugins.broadcast import database as BDB
        chans = await BDB.get_saved_channels()
    except Exception:
        chans = []

    if not chans:
        return await q.answer("⚠️ No channels saved", show_alert=True)

    kb = KB.kb_bc_channels(tmdb_id, chans)
    movie = await DB.get_movie(tmdb_id) or {}
    title = (movie.get("title") or "?")[:50]

    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📡 <b>{fb('PICK A CHANNEL')}</b>",
        DIV, "",
        f"🎬 <b>{sc(title)}</b>",
        "", DIV2,
        f"📌 {sc('tap a channel, or ALL CHANNELS')}",
    ])
    await _edit_msg(client, ev, text, kb)
    return await q.answer()


async def confirm_bc(client: Client, q: CallbackQuery, tmdb_id: int,
                     kind: str, target_id: int):
    ev = await find_by_msg(q.message.id)
    if not ev:
        return await q.answer("⏱️ Expired", show_alert=True)

    label = {
        "ch": f"channel {target_id}",
        "chall": "ALL channels",
        "gr": "ALL groups",
        "us": "ALL users",
        "pm": "premium users",
    }.get(kind, kind)

    kb = KB.kb_bc_confirm(tmdb_id, kind, target_id, label)
    movie = await DB.get_movie(tmdb_id) or {}
    title = (movie.get("title") or "?")[:50]

    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"⚠️ <b>{fb('CONFIRM BROADCAST')}</b>",
        DIV, "",
        f"🎬 <b>{sc(title)}</b>",
        f"🎯 {sc('target')} · <b>{label}</b>",
        "", DIV2,
        f"📌 {sc('live post with Get Notified will be sent')}",
        "", f"❓ {sc('proceed?')}",
    ])
    await _edit_msg(client, ev, text, kb)
    return await q.answer()


async def do_broadcast(client: Client, q: CallbackQuery, tmdb_id: int,
                        kind: str, target_id: int):
    ev = await find_by_msg(q.message.id)
    if not ev:
        return await q.answer("⏱️ Expired", show_alert=True)

    eid = ev["_id"]
    await q.answer("📤 Broadcasting…")

    # Send via engine (verbose if available, otherwise basic)
    from plugins.ott import engine as EG
    delivered = failed = total = 0
    posts: List[Tuple[int, int, str]] = []

    try:
        if hasattr(EG, "send_to_targets_verbose"):
            delivered, failed, total, posts = await EG.send_to_targets_verbose(
                client=client,
                tmdb_id=tmdb_id,
                notify=ev.get("notify_enabled", True),
                show_file=ev.get("get_files_enabled", True),
                kind=kind,
                target_id=target_id,
                admin_id=q.from_user.id,
            )
        else:
            delivered, failed, total = await EG.send_to_targets(
                client=client,
                tmdb_id=tmdb_id,
                notify=ev.get("notify_enabled", True),
                show_file=ev.get("get_files_enabled", True),
                kind=kind,
                target_id=target_id,
                admin_id=q.from_user.id,
            )
    except Exception as e:
        logger.exception(f"[OTT-CF] do_broadcast: {e}")

    # Track target posts for live sync
    for cid, mid, k in posts:
        try:
            await EVENTS.add_target_post(eid, cid, mid, k)
        except Exception:
            pass

    # Show result
    movie = await DB.get_movie(tmdb_id) or {}
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
    ])
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "⬅️ Back to setup",
            callback_data=f"ott:csetup:{tmdb_id}")],
    ])
    await _edit_msg(client, ev, text, kb)


# ═══════════════════════════════════════════════════════════
# POST NOW — setup → live (same message)
# ═══════════════════════════════════════════════════════════

async def post_now(client: Client, q: CallbackQuery, tmdb_id: int):
    ev = await find_by_msg(q.message.id)
    if not ev:
        return await q.answer("⏱️ Expired", show_alert=True)

    # Transition state
    await EVENTS.update_event(ev["_id"], state="live")

    # Schedule auto-delete of the admin post
    hours = int(ev.get("auto_delete_hours", 24))
    if hours > 0:
        try:
            await DB.pending_add(ev["admin_channel_id"],
                                  ev["admin_msg_id"], hours * 3600)
        except Exception:
            pass

    # Force sync → rebuilds as live
    await SYNC.sync_admin_post(client, ev["_id"], force=True)
    return await q.answer("✅ Posted as live")


# ═══════════════════════════════════════════════════════════
# EDIT HELPER
# ═══════════════════════════════════════════════════════════

async def _edit_msg(client: Client, ev: Dict[str, Any],
                    text: str, kb: InlineKeyboardMarkup) -> None:
    chat_id = int(ev.get("admin_channel_id") or 0)
    msg_id = int(ev.get("admin_msg_id") or 0)
    if not chat_id or not msg_id:
        return
    try:
        await client.edit_message_caption(
            chat_id=chat_id, message_id=msg_id,
            caption=text, reply_markup=kb,
            parse_mode=ParseMode.HTML,
        )
    except MessageNotModified:
        pass
    except Exception:
        try:
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


__all__ = [
    "find_by_msg",
    "open_setup", "toggle_notify", "toggle_file",
    "show_timer", "set_timer", "cancel_setup",
    "open_bc_picker", "show_channel_list",
    "confirm_bc", "do_broadcast", "post_now",
]
