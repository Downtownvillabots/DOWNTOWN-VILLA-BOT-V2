# ============================================================
# 🏨 DOWNTOWN VILLA — BROADCAST WATCHER
# ============================================================
# Upload to BROADCAST_CHANNEL_ID → destination picker
# Multi-file debounce → "USE ALL (N)" option
# ============================================================

from __future__ import annotations
import asyncio
import logging
from typing import Any, Dict, List

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from plugins.broadcast.config import (
    BROADCAST_CHANNEL_ID, DIV, DIV2, fb, sc, _is_admin,
    _fmt_int, DEBOUNCE_SECONDS,
)
from plugins.broadcast import database as DB
from plugins.broadcast import keyboards as KB
from plugins.broadcast import state as ST
from plugins.broadcast import views as V

logger = logging.getLogger(__name__)

_MANUAL_TARGETS: Dict[int, int] = {}


def _extract_name(message: Message) -> str:
    try:
        for attr in ("document", "video", "audio", "photo", "animation"):
            m = getattr(message, attr, None)
            if m:
                return (
                    getattr(m, "file_name", None)
                    or (message.caption or "")[:60]
                    or f"{attr} file"
                )
    except Exception:
        pass
    return "file"


# ═════════════════════════════════════════════════════════════
# DEBOUNCE — one panel for N rapid uploads
# ═════════════════════════════════════════════════════════════
async def _debounced_show(message: Message, key: int, msg_id: int):
    await asyncio.sleep(DEBOUNCE_SECONDS)
    if ST.get_debounce(key) != msg_id:
        return

    docs = await ST.list_sources(limit=10)
    if not docs:
        return

    if len(docs) == 1:
        d = docs[0]
        sid = ST.register_source(message)
        _MANUAL_TARGETS.pop(
            message.from_user.id if message.from_user else 0, None
        )
        manual = _MANUAL_TARGETS.pop(
            message.from_user.id if message.from_user else 0, 0
        )
        text = "\n".join([
            f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
            f"📢 <b>{fb('BROADCAST READY')}</b>",
            DIV, "",
            f"📦 <code>{_extract_name(message)[:50]}</code>",
            "", f"📌 {sc('choose destination')}",
            f"📢 {sc('channels')} — {sc('per-channel caption/buttons')}",
            f"👥 {sc('groups')} — {sc('global default')}",
            f"👤 {sc('users')} — {sc('with auto-delete timer')}",
        ])
        try:
            await message.reply_text(
                text,
                reply_markup=KB.kb_destination(sid, manual),
                parse_mode=ParseMode.HTML,
                reply_to_message_id=message.id,
                quote=True,
            )
        except Exception as e:
            logger.warning(f"[BC-WATCH] {e}")
        return

    # Multiple files → source picker with USE ALL
    sid = ST.register_source(message)
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📦 <b>{fb('MULTIPLE FILES READY')}</b>",
        DIV, "",
        f"📊 {sc('count')} · <b>{len(docs)}</b>",
        f"📌 {sc('send order')} · <i>{sc('oldest first')}</i>",
        "", DIV2, "",
        f"📌 {sc('choose one target — all files sent in order')}",
    ])
    try:
        await message.reply_text(
            text,
            reply_markup=KB.kb_destination_batch(sid, len(docs)),
            parse_mode=ParseMode.HTML,
            reply_to_message_id=message.id,
            quote=True,
        )
    except Exception as e:
        logger.warning(f"[BC-WATCH] {e}")


# ═════════════════════════════════════════════════════════════
# CHANNEL WATCHER
# ═════════════════════════════════════════════════════════════
if BROADCAST_CHANNEL_ID:

    @Client.on_message(
        filters.chat(BROADCAST_CHANNEL_ID) & ~filters.service,
        group=-499,
    )
    async def bc_watcher(client: Client, message: Message):
        try:
            key = int(message.chat.id)
            name = _extract_name(message)

            await ST.save_source(
                int(message.id), int(message.chat.id), name
            )
            ST.set_debounce(key, int(message.id))

            asyncio.create_task(
                _debounced_show(message, key, int(message.id))
            )
        except Exception as e:
            logger.exception(f"[BC-WATCH] {e}")


# ═════════════════════════════════════════════════════════════
# DESTINATION PICKER CALLBACKS
# ═════════════════════════════════════════════════════════════
@Client.on_callback_query(
    filters.regex(r"^bcsend:ch:([a-f0-9]+)$"), group=-500
)
async def cb_send_ch(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    sid = q.matches[0].group(1)
    if not ST.get_source(sid):
        return await q.answer("⏱️ ᴇxᴘɪʀᴇᴅ", show_alert=True)

    channels = await DB.get_saved_channels()
    enabled = [c for c in channels if c.get("enabled", True)]
    if not enabled:
        return await q.answer("⚠️ ɴᴏ ᴄʜᴀɴɴᴇʟꜱ", show_alert=True)

    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📢 <b>{fb('SELECT CHANNEL')}</b>",
        DIV, "",
        f"📝 = custom caption · 🔘 = custom buttons",
        "", f"📌 {sc('each channel uses its own settings')}",
    ])
    await V.safe_edit(q, text, KB.kb_channel_picker(sid, enabled))
    await q.answer()


@Client.on_callback_query(
    filters.regex(r"^bcsend:goto_ch:([a-f0-9]+):(-?\d+)$"),
    group=-500,
)
async def cb_goto_ch(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    sid = q.matches[0].group(1)
    cid = int(q.matches[0].group(2))
    if not ST.get_source(sid):
        return await q.answer("⏱️ ᴇxᴘɪʀᴇᴅ", show_alert=True)
    await q.answer("🚀 ꜱᴛᴀʀᴛɪɴɢ...")
    from plugins.broadcast.engine import run_broadcast
    asyncio.create_task(
        run_broadcast(client, q, sid, "channel", targets=[cid])
    )


@Client.on_callback_query(
    filters.regex(r"^bcsend:goto_chall:([a-f0-9]+)$"), group=-500
)
async def cb_goto_chall(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    sid = q.matches[0].group(1)
    if not ST.get_source(sid):
        return await q.answer("⏱️ ᴇxᴘɪʀᴇᴅ", show_alert=True)
    await q.answer("🚀 ꜱᴛᴀʀᴛɪɴɢ ᴀʟʟ ᴄʜᴀɴɴᴇʟꜱ...")
    from plugins.broadcast.engine import run_broadcast
    asyncio.create_task(
        run_broadcast(client, q, sid, "channels_all")
    )


@Client.on_callback_query(
    filters.regex(r"^bcsend:gr:([a-f0-9]+)$"), group=-500
)
async def cb_send_gr(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    sid = q.matches[0].group(1)
    if not ST.get_source(sid):
        return await q.answer("⏱️ ᴇxᴘɪʀᴇᴅ", show_alert=True)
    total = await DB.count_groups()
    if total == 0:
        return await q.answer("⚠️ ɴᴏ ɢʀᴏᴜᴘꜱ", show_alert=True)

    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"👥 <b>{fb('CONFIRM GROUP BROADCAST')}</b>",
        DIV, "",
        f"📊 {sc('total groups')} · <code>{_fmt_int(total)}</code>",
        "", f"📌 {sc('uses global default caption & buttons')}",
    ])
    await V.safe_edit(q, text, KB.kb_confirm_groups(sid, total))
    await q.answer()


@Client.on_callback_query(
    filters.regex(r"^bcsend:goto_gr:([a-f0-9]+)$"), group=-500
)
async def cb_goto_gr(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    sid = q.matches[0].group(1)
    if not ST.get_source(sid):
        return await q.answer("⏱️ ᴇxᴘɪʀᴇᴅ", show_alert=True)
    await q.answer("🚀 ꜱᴛᴀʀᴛɪɴɢ...")
    from plugins.broadcast.engine import run_broadcast
    asyncio.create_task(run_broadcast(client, q, sid, "groups"))


@Client.on_callback_query(
    filters.regex(r"^bcsend:us:([a-f0-9]+)$"), group=-500
)
async def cb_send_us(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    sid = q.matches[0].group(1)
    if not ST.get_source(sid):
        return await q.answer("⏱️ ᴇxᴘɪʀᴇᴅ", show_alert=True)
    total = await DB.count_users()
    if total == 0:
        return await q.answer("⚠️ ɴᴏ ᴜꜱᴇʀꜱ", show_alert=True)

    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"⏱️ <b>{fb('AUTO-DELETE TIMER')}</b>",
        DIV, "",
        f"📊 {sc('target users')} · <code>{_fmt_int(total)}</code>",
        "", DIV2, "",
        f"📌 {sc('choose how long messages stay')}",
        f"📌 {sc('after timer expires, messages auto-delete')}",
    ])
    await V.safe_edit(q, text, KB.kb_user_timer(sid))
    await q.answer()


@Client.on_callback_query(
    filters.regex(r"^bcsend:us_t:([a-f0-9]+):(\d+)$"), group=-500
)
async def cb_us_timer(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    sid = q.matches[0].group(1)
    days = int(q.matches[0].group(2))
    if not ST.get_source(sid):
        return await q.answer("⏱️ ᴇxᴘɪʀᴇᴅ", show_alert=True)

    total = await DB.count_users()
    from plugins.broadcast.config import (
        AUTODELETE_SECONDS, AUTODELETE_LABELS,
    )
    seconds = AUTODELETE_SECONDS.get(days, 0)
    label = AUTODELETE_LABELS.get(days, f"{days} days")
    ad_text = "♾️ Never" if seconds == 0 else f"⏱️ {label}"

    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"✅ <b>{fb('CONFIRM USER BROADCAST')}</b>",
        DIV, "",
        f"📊 {sc('target users')} · <code>{_fmt_int(total)}</code>",
        f"⏱️ {sc('auto-delete')} · <b>{ad_text}</b>",
        "", DIV2, "",
        f"📌 {sc('uses global default caption & buttons')}",
        f"⚠️ {sc('blocked/deleted users auto-removed')}",
    ])
    await V.safe_edit(q, text, KB.kb_user_timer_confirm(sid, days, total))
    await q.answer()


@Client.on_callback_query(
    filters.regex(r"^bcsend:us_go:([a-f0-9]+):(\d+)$"), group=-500
)
async def cb_us_go(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    sid = q.matches[0].group(1)
    days = int(q.matches[0].group(2))
    if not ST.get_source(sid):
        return await q.answer("⏱️ ᴇxᴘɪʀᴇᴅ", show_alert=True)
    from plugins.broadcast.config import AUTODELETE_SECONDS
    seconds = AUTODELETE_SECONDS.get(days, 0)
    await q.answer("🚀 ꜱᴛᴀʀᴛɪɴɢ...")
    from plugins.broadcast.engine import run_broadcast
    asyncio.create_task(
        run_broadcast(client, q, sid, "users",
                      autodelete_seconds=seconds)
    )


@Client.on_callback_query(
    filters.regex(r"^bcsend:manual:([a-f0-9]+):(-?\d+)$"),
    group=-500,
)
async def cb_manual_send(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    sid = q.matches[0].group(1)
    target = int(q.matches[0].group(2))
    if not ST.get_source(sid):
        return await q.answer("⏱️ ᴇxᴘɪʀᴇᴅ", show_alert=True)
    await q.answer("🚀 ꜱᴛᴀʀᴛɪɴɢ...")
    from plugins.broadcast.engine import run_broadcast
    asyncio.create_task(
        run_broadcast(client, q, sid, "channel", targets=[target])
    )


@Client.on_callback_query(
    filters.regex(r"^bcsend:all:([a-f0-9]+)$"), group=-500
)
async def cb_send_all(client, q):
    """USE ALL — send all files. Pick destination next."""
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    sid = q.matches[0].group(1)
    if not ST.get_source(sid):
        return await q.answer("⏱️ ᴇxᴘɪʀᴇᴅ", show_alert=True)

    docs = await ST.list_sources(limit=10)
    if not docs:
        return await q.answer("⚠️ ɴᴏ ꜰɪʟᴇꜱ", show_alert=True)

    ST.get_source(sid)["use_all"] = True
    ST.get_source(sid)["batch"] = [
        (int(d["message_id"]), d.get("name") or "file")
        for d in docs
    ]

    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🎯 <b>{fb('USE ALL FILES')}</b>",
        DIV, "",
        f"📊 {sc('files')} · <b>{len(docs)}</b>",
        "", f"📌 {sc('pick destination')}",
    ])
    await V.safe_edit(q, text, KB.kb_destination(sid, 0))
    await q.answer(f"✅ {len(docs)} ꜰɪʟᴇꜱ")


@Client.on_callback_query(
    filters.regex(r"^bcsend:no:([a-f0-9]+)$"), group=-500
)
async def cb_send_no(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    try:
        await q.message.delete()
    except Exception:
        pass
    await q.answer("❌ ᴄᴀɴᴄᴇʟʟᴇᴅ")


# ═════════════════════════════════════════════════════════════
# ADMIN PANEL ENTRY
# ═════════════════════════════════════════════════════════════
async def bc_open_for_admin(client: Client, user_id: int) -> None:
    """Called from /admin → 📢 Broadcast."""
    if not BROADCAST_CHANNEL_ID:
        try:
            await client.send_message(
                chat_id=user_id,
                text=f"⚠️ <b>BROADCAST_CHANNEL_ID not set</b>",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        return

    docs = await ST.list_sources(limit=10)
    if not docs:
        try:
            await client.send_message(
                chat_id=user_id,
                text="\n".join([
                    f"⚠️ <b>{fb('NO FILES')}</b>",
                    DIV, "",
                    f"📌 {sc('upload a file to the broadcast channel')}",
                    f"📌 {sc('then try again')}",
                ]),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        return

    if len(docs) == 1:
        d = docs[0]
        text = "\n".join([
            f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
            f"📢 <b>{fb('BROADCAST READY')}</b>",
            DIV, "",
            f"📦 <code>{d.get('name', 'file')[:50]}</code>",
            "", f"📌 {sc('choose destination')}",
        ])
        # create a temporary sid for this source
        sid = ST.register_source(  # dummy
            type("M", (), {
                "id": int(d["message_id"]),
                "chat": type("C", (), {"id": int(d["chat_id"])})(),
                "media": None,
                "caption": None,
            })()
        ) if False else _make_sid_from_doc(d)

        kb = KB.kb_destination_batch(sid, 1) if False \
            else KB.kb_destination(sid, 0)
        try:
            await client.send_message(
                chat_id=user_id,
                text=text,
                reply_markup=kb,
                parse_mode=ParseMode.HTML,
            )
        except Exception as e:
            logger.exception(f"[BC-ADMIN] {e}")
        return

    sid = _make_sid_from_doc(docs[0])
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📦 <b>{fb('MULTIPLE FILES READY')}</b>",
        DIV, "",
        f"📊 {sc('count')} · <b>{len(docs)}</b>",
        f"📌 {sc('send order')} · <i>{sc('oldest first')}</i>",
        "", DIV2, "",
        f"📌 {sc('choose one target — all files sent')}",
    ])
    try:
        await client.send_message(
            chat_id=user_id,
            text=text,
            reply_markup=KB.kb_destination_batch(sid, len(docs)),
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        logger.exception(f"[BC-ADMIN] {e}")


def _make_sid_from_doc(doc: Dict[str, Any]) -> str:
    """Create a sid for a DB source (from /admin, no live message)."""
    import uuid
    sid = uuid.uuid4().hex[:10]
    ST._SOURCES[sid] = {
        "message_id": int(doc["message_id"]),
        "chat_id": int(doc["chat_id"]),
        "created": doc.get("created_at", 0),
        "expires": 9e18,
        "kind": "document",
    }
    return sid


__all__ = ["bc_open_for_admin"]
