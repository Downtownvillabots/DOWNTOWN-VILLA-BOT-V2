# ============================================================
# 🏨 DOWNTOWN VILLA — BROADCAST WATCHER (BATCH EDITION)
# ============================================================
# Upload N files → ONE reply in channel with per-file toggles
# Select files → "Broadcast selected (N)" → confirmation in PM
# ============================================================

from __future__ import annotations
import asyncio
import logging
from typing import Any, Dict, List, Optional

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from plugins.broadcast.config import (
    BROADCAST_CHANNEL_ID, ADMINS, DEBOUNCE_SECONDS,
    DIV, DIV2, fb, sc, _is_admin, _fmt_int,
)
from plugins.broadcast import database as DB
from plugins.broadcast import keyboards as KB
from plugins.broadcast import state as ST
from plugins.broadcast import templates as TPL

logger = logging.getLogger(__name__)

_MANUAL_TARGETS: Dict[int, int] = {}
_CONF: Dict[str, Dict[str, Any]] = {}  # sid → confirmation state


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


def _pick_admin(uid: Optional[int]) -> int:
    if uid and _is_admin(uid):
        return int(uid)
    return int(ADMINS[0]) if ADMINS else 0


# ═════════════════════════════════════════════════════════════
# WATCHER — fires on every upload
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

            batch = ST.get_batch(key)
            if not batch:
                sid = ST.register_source(message)
                batch = ST.new_batch(key, sid)
                batch["admin_id"] = _pick_admin(
                    message.from_user.id if message.from_user else None
                )
                batch["reply_msg_id"] = None

            batch["files"].append({
                "msg_id": int(message.id),
                "chat_id": int(message.chat.id),
                "name": name,
                "selected": False,
                "original_caption": message.caption or "",
            })

            ST.set_debounce(key, int(message.id))
            asyncio.create_task(
                _debounced_show(message, key, int(message.id))
            )
        except Exception as e:
            logger.exception(f"[BC-WATCH] {e}")


async def _debounced_show(message: Message, key: int, msg_id: int):
    await asyncio.sleep(DEBOUNCE_SECONDS)
    if ST.get_debounce(key) != msg_id:
        return

    batch = ST.get_batch(key)
    if not batch:
        return

    # Cancel any previous panel
    if batch.get("reply_msg_id"):
        try:
            await message._client.delete_messages(
                chat_id=batch["chat_id"],
                message_ids=batch["reply_msg_id"],
            )
        except Exception:
            pass

    text, kb = _build_batch_view(batch)
    try:
        sent = await message.reply_text(
            text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
            quote=True,
        )
        batch["reply_msg_id"] = sent.id
    except Exception as e:
        logger.warning(f"[BC-WATCH] {e}")


def _build_batch_view(batch: Dict[str, Any]):
    files = batch["files"]
    n = len(files)
    selected = sum(1 for f in files if f["selected"])

    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📦 <b>{fb('BATCH READY')}</b>",
        DIV, "",
        f"📊 {sc('files')} · <b>{n}</b>",
        f"✅ {sc('selected')} · <b>{selected}</b>",
        "", DIV2, "",
    ]
    for i, f in enumerate(files, 1):
        mark = "✅" if f["selected"] else "☐"
        name = (f.get("name") or "file")[:50]
        lines.append(f"{mark} <b>{i}.</b> <code>{name}</code>")

    lines += [
        "", DIV2, "",
        f"📌 {sc('tap a number to toggle')}",
        f"📌 {sc('tap broadcast when ready')}",
    ]

    return "\n".join(lines), KB.kb_batch(batch, sc)


# ═════════════════════════════════════════════════════════════
# BATCH CALLBACKS — toggles in channel
# ═════════════════════════════════════════════════════════════
@Client.on_callback_query(
    filters.regex(r"^bcbatch:tog:([a-f0-9]+):(\d+)$"), group=-500
)
async def cb_batch_tog(client, q):
    sid = q.matches[0].group(1)
    idx = int(q.matches[0].group(2))
    batch = ST.find_batch_by_sid(sid)
    if not batch:
        return await q.answer("⏱️ Expired", show_alert=True)
    if idx < 0 or idx >= len(batch["files"]):
        return await q.answer("❌ Invalid", show_alert=True)
    batch["files"][idx]["selected"] = not batch["files"][idx]["selected"]
    text, kb = _build_batch_view(batch)
    try:
        await q.message.edit_text(
            text, reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception:
        pass
    await q.answer()


@Client.on_callback_query(
    filters.regex(r"^bcbatch:all:([a-f0-9]+)$"), group=-500
)
async def cb_batch_all(client, q):
    sid = q.matches[0].group(1)
    batch = ST.find_batch_by_sid(sid)
    if not batch:
        return await q.answer("⏱️ Expired", show_alert=True)
    for f in batch["files"]:
        f["selected"] = True
    text, kb = _build_batch_view(batch)
    try:
        await q.message.edit_text(
            text, reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception:
        pass
    await q.answer("✅ All selected")


@Client.on_callback_query(
    filters.regex(r"^bcbatch:none:([a-f0-9]+)$"), group=-500
)
async def cb_batch_none(client, q):
    sid = q.matches[0].group(1)
    batch = ST.find_batch_by_sid(sid)
    if not batch:
        return await q.answer("⏱️ Expired", show_alert=True)
    for f in batch["files"]:
        f["selected"] = False
    text, kb = _build_batch_view(batch)
    try:
        await q.message.edit_text(
            text, reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception:
        pass
    await q.answer("☐ Cleared")


@Client.on_callback_query(
    filters.regex(r"^bcbatch:bcast:([a-f0-9]+)$"), group=-500
)
async def cb_batch_bcast(client, q):
    sid = q.matches[0].group(1)
    batch = ST.find_batch_by_sid(sid)
    if not batch:
        return await q.answer("⏱️ Expired", show_alert=True)

    selected = [f for f in batch["files"] if f["selected"]]
    if not selected:
        return await q.answer("⚠️ Select at least 1", show_alert=True)

    admin_id = batch.get("admin_id")
    if not admin_id:
        return await q.answer("⚠️ No admin", show_alert=True)

    # Save confirmation state
    _CONF[sid] = {
        "batch_sid": sid,
        "admin_id": admin_id,
        "files": selected,
        "destination": None,
        "channel_id": None,
        "caption_mode": None,
        "timer_days": 0,
        "created": asyncio.get_event_loop().time(),
    }

    # Send confirmation panel to admin PM
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🚀 <b>{fb('CONFIRM BROADCAST')}</b>",
        DIV, "",
        f"📦 {sc('files')} · <b>{len(selected)}</b>",
        "", DIV2, "",
        f"📌 {sc('pick destination type')}",
    ])
    try:
        await client.send_message(
            chat_id=admin_id,
            text=text,
            reply_markup=KB.kb_conf_destination(sid),
            parse_mode=ParseMode.HTML,
        )
        await q.answer("📩 Check your PM")
    except Exception as e:
        logger.exception(f"[BC-BATCH] {e}")
        await q.answer("❌ Cannot open PM", show_alert=True)


@Client.on_callback_query(
    filters.regex(r"^bcbatch:no:([a-f0-9]+)$"), group=-500
)
async def cb_batch_no(client, q):
    sid = q.matches[0].group(1)
    batch = ST.find_batch_by_sid(sid)
    if batch:
        ST.clear_batch(batch["chat_id"])
    _CONF.pop(sid, None)
    try:
        await q.message.delete()
    except Exception:
        pass
    await q.answer("❌ Cancelled")


# ═════════════════════════════════════════════════════════════
# CONFIRMATION FLOW — PM panel
# ═════════════════════════════════════════════════════════════
def _conf_header(sid: str, extra: Optional[str] = None) -> str:
    conf = _CONF.get(sid) or {}
    files = conf.get("files") or []
    dest = conf.get("destination") or "—"
    cap_mode = conf.get("caption_mode") or "—"
    timer = conf.get("timer_days", 0)
    timer_label = "♾️ never" if not timer else f"⏱️ {timer}d"

    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🚀 <b>{fb('CONFIRM BROADCAST')}</b>",
        DIV, "",
        f"📦 {sc('files')} · <b>{len(files)}</b>",
        f"🎯 {sc('destination')} · <b>{dest}</b>",
        f"📝 {sc('caption')} · <b>{cap_mode}</b>",
        f"⏱️ {sc('timer')} · <b>{timer_label}</b>",
    ]
    if extra:
        lines += ["", DIV2, "", extra]
    return "\n".join(lines)


@Client.on_callback_query(
    filters.regex(r"^bcconf:([a-f0-9]+):dest:(\w+)$"), group=-500
)
async def cb_conf_dest(client, q):
    sid = q.matches[0].group(1)
    dest = q.matches[0].group(2)
    conf = _CONF.get(sid)
    if not conf:
        return await q.answer("⏱️ Expired", show_alert=True)
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)

    conf["destination"] = dest

    if dest == "channels":
        channels = await DB.get_saved_channels()
        enabled = [c for c in channels if c.get("enabled", True)]
        if not enabled:
            return await q.answer("⚠️ No channels", show_alert=True)
        text = _conf_header(sid, f"📌 {sc('pick a channel')}")
        await _safe_edit_pm(q, text, KB.kb_conf_channels(sid, enabled))
        return await q.answer()

    if dest == "groups":
        total = await DB.count_groups()
        if total == 0:
            return await q.answer("⚠️ No groups", show_alert=True)
        conf["channel_id"] = None
        text = _conf_header(sid, f"📊 {sc('groups')} · <b>{total}</b>")
        return await _show_caption_picker(client, q, sid, text)

    if dest == "users":
        total = await DB.count_users()
        if total == 0:
            return await q.answer("⚠️ No users", show_alert=True)
        conf["channel_id"] = None
        text = _conf_header(sid, f"📊 {sc('users')} · <b>{total}</b>")
        return await _show_caption_picker(client, q, sid, text)

    if dest == "manual":
        conf["manual_await"] = True
        text = _conf_header(sid, "\n".join([
            f"🎯 {sc('send the chat id or @username in PM')}",
            f"📌 {sc('bot must be able to post there')}",
        ]))
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                "❌ CANCEL",
                callback_data=f"bcconf:{sid}:cancel",
            )
        ]])
        await _safe_edit_pm(q, text, kb)
        return await q.answer()


@Client.on_callback_query(
    filters.regex(r"^bcconf:([a-f0-9]+):ch:(-?\d+)$"), group=-500
)
async def cb_conf_ch(client, q):
    sid = q.matches[0].group(1)
    cid = int(q.matches[0].group(2))
    conf = _CONF.get(sid)
    if not conf:
        return await q.answer("⏱️ Expired", show_alert=True)
    conf["channel_id"] = cid
    text = _conf_header(sid, f"📢 {sc('channel')} · <code>{cid}</code>")
    await _show_caption_picker(client, q, sid, text)
    await q.answer()


@Client.on_callback_query(
    filters.regex(r"^bcconf:([a-f0-9]+):chall$"), group=-500
)
async def cb_conf_chall(client, q):
    sid = q.matches[0].group(1)
    conf = _CONF.get(sid)
    if not conf:
        return await q.answer("⏱️ Expired", show_alert=True)
    conf["channel_id"] = "all"
    text = _conf_header(
        sid, f"📢 {sc('all channels')} · <b>ALL</b>"
    )
    await _show_caption_picker(client, q, sid, text)
    await q.answer()


async def _show_caption_picker(client, q, sid, text):
    conf = _CONF.get(sid) or {}
    has_channel = bool(conf.get("channel_id"))
    await _safe_edit_pm(
        q, text, KB.kb_conf_caption(sid, has_channel)
    )
    try:
        await q.answer()
    except Exception:
        pass


@Client.on_callback_query(
    filters.regex(r"^bcconf:([a-f0-9]+):cap:(\w+)$"), group=-500
)
async def cb_conf_cap(client, q):
    sid = q.matches[0].group(1)
    mode = q.matches[0].group(2)
    conf = _CONF.get(sid)
    if not conf:
        return await q.answer("⏱️ Expired", show_alert=True)
    conf["caption_mode"] = mode
    text = _conf_header(sid, f"📝 {sc('caption mode selected')}")
    await _safe_edit_pm(q, text, KB.kb_conf_timer(sid))
    await q.answer()


@Client.on_callback_query(
    filters.regex(r"^bcconf:([a-f0-9]+):timer:(\d+)$"), group=-500
)
async def cb_conf_timer(client, q):
    sid = q.matches[0].group(1)
    days = int(q.matches[0].group(2))
    conf = _CONF.get(sid)
    if not conf:
        return await q.answer("⏱️ Expired", show_alert=True)
    conf["timer_days"] = days
    text = _conf_header(sid, f"✅ {sc('ready to send')}")
    await _safe_edit_pm(q, text, KB.kb_conf_confirm(sid))
    await q.answer()


@Client.on_callback_query(
    filters.regex(r"^bcconf:([a-f0-9]+):chcap$"), group=-500
)
async def cb_conf_chcap(client, q):
    sid = q.matches[0].group(1)
    conf = _CONF.get(sid)
    if not conf:
        return await q.answer("⏱️ Expired", show_alert=True)
    text = _conf_header(sid, f"📝 {sc('choose caption mode')}")
    has_channel = bool(conf.get("channel_id"))
    await _safe_edit_pm(q, text, KB.kb_conf_caption(sid, has_channel))
    await q.answer()


@Client.on_callback_query(
    filters.regex(r"^bcconf:([a-f0-9]+):chtimer$"), group=-500
)
async def cb_conf_chtimer(client, q):
    sid = q.matches[0].group(1)
    conf = _CONF.get(sid)
    if not conf:
        return await q.answer("⏱️ Expired", show_alert=True)
    text = _conf_header(sid, f"⏱️ {sc('choose timer')}")
    await _safe_edit_pm(q, text, KB.kb_conf_timer(sid))
    await q.answer()


@Client.on_callback_query(
    filters.regex(r"^bcconf:([a-f0-9]+):back$"), group=-500
)
async def cb_conf_back(client, q):
    sid = q.matches[0].group(1)
    conf = _CONF.get(sid)
    if not conf:
        return await q.answer("⏱️ Expired", show_alert=True)
    conf["destination"] = None
    conf["channel_id"] = None
    text = _conf_header(sid, f"📌 {sc('pick destination type')}")
    await _safe_edit_pm(q, text, KB.kb_conf_destination(sid))
    await q.answer()


@Client.on_callback_query(
    filters.regex(r"^bcconf:([a-f0-9]+):cancel$"), group=-500
)
async def cb_conf_cancel(client, q):
    sid = q.matches[0].group(1)
    _CONF.pop(sid, None)
    try:
        await q.message.delete()
    except Exception:
        pass
    await q.answer("❌ Cancelled")


@Client.on_callback_query(
    filters.regex(r"^bcconf:([a-f0-9]+):send$"), group=-500
)
async def cb_conf_send(client, q):
    sid = q.matches[0].group(1)
    conf = _CONF.get(sid)
    if not conf:
        return await q.answer("⏱️ Expired", show_alert=True)
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)

    # Validate
    if not conf.get("destination"):
        return await q.answer("⚠️ Pick destination", show_alert=True)
    if not conf.get("caption_mode"):
        return await q.answer("⚠️ Pick caption mode", show_alert=True)

    await q.answer("🚀 Starting…")
    asyncio.create_task(
        _execute_batch(client, q, sid, conf)
    )


# ═════════════════════════════════════════════════════════════
# EXECUTE
# ═════════════════════════════════════════════════════════════
async def _execute_batch(client, q, sid, conf):
    from plugins.broadcast.config import AUTODELETE_SECONDS
    from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

    files = conf["files"]
    dest = conf["destination"]
    cap_mode = conf["caption_mode"]
    ch_id = conf.get("channel_id")
    timer_days = conf.get("timer_days", 0)
    timer_secs = AUTODELETE_SECONDS.get(timer_days, 0)

    # ─── Resolve targets ───
    if dest == "channels":
        if ch_id == "all":
            channels = await DB.get_saved_channels()
            targets = [
                c["chat_id"] for c in channels
                if c.get("enabled", True)
            ]
            kind = "channels_all"
        else:
            targets = [int(ch_id)]
            kind = "channel"
    elif dest == "groups":
        targets = await DB.get_all_groups()
        kind = "groups"
    elif dest == "users":
        targets = await DB.get_all_users()
        kind = "users"
    elif dest == "manual":
        targets = [int(conf.get("manual_target") or 0)]
        kind = "channel"
    else:
        return

    targets = [t for t in targets if t]
    if not targets:
        try:
            await q.message.edit_text("⚠️ No valid targets")
        except Exception:
            pass
        return

    # ─── Global caption template (for wrap modes) ───
    global_cap = await DB.get_global_caption()
    global_btns = await DB.get_global_buttons()

    total_files = len(files)
    total_targets = len(targets)
    grand_total = total_files * total_targets
    grand_sent = 0
    grand_failed = 0

    progress_msg = q.message

    for idx, f in enumerate(files, 1):
        try:
            src_msg = await client.get_messages(
                int(f["chat_id"]), int(f["msg_id"])
            )
        except Exception:
            continue
        if not src_msg or src_msg.empty:
            continue

        # ─── Build caption per mode ───
        if cap_mode == "own":
            own_clean = TPL.clean_caption(f.get("original_caption") or "")
            caption = own_clean if own_clean else ""
            kb = None  # No buttons in own mode
        elif cap_mode == "global":
            caption = TPL.build_caption(src_msg, global_cap)
            kb = TPL.build_buttons_kb(global_btns)
        elif cap_mode == "channel":
            ch = await DB.get_channel(int(ch_id)) if ch_id not in ("all", None) else None
            if ch:
                cap_tpl = (
                    ch.get("caption")
                    if ch.get("caption") is not None
                    else global_cap
                )
                btns = (
                    ch.get("buttons")
                    if ch.get("buttons") is not None
                    else global_btns
                )
            else:
                cap_tpl = global_cap
                btns = global_btns
            caption = TPL.build_caption(src_msg, cap_tpl)
            kb = TPL.build_buttons_kb(btns)
        else:
            caption = TPL.build_caption(src_msg, global_cap)
            kb = TPL.build_buttons_kb(global_btns)

        # ─── Live progress header ───
        try:
            await client.edit_message_text(
                chat_id=progress_msg.chat.id,
                message_id=progress_msg.id,
                text="\n".join([
                    f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                    f"🚀 <b>{fb('BROADCASTING')}</b>",
                    DIV, "",
                    f"📦 {sc('file')} · <b>{idx}/{total_files}</b>",
                    f"📛 <code>{(f.get('name') or 'file')[:40]}</code>",
                    "", DIV2,
                    f"🎯 {sc('targets')} · <b>{total_targets}</b>",
                    f"✅ {sc('sent')} · <b>{grand_sent}</b>",
                    f"❌ {sc('failed')} · <b>{grand_failed}</b>",
                ]),
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        "⏹ STOP",
                        callback_data=f"bcconf:{sid}:cancel",
                    )
                ]]),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass

        # ─── Send to all targets ───
        from plugins.broadcast.config import BROADCAST_BATCH_SIZE
        sem = asyncio.Semaphore(5)
        lock = asyncio.Lock()

        async def _send_one(tid):
            async with sem:
                try:
                    sent = None
                    try:
                        sent = await client.copy_message(
                            chat_id=tid,
                            from_chat_id=src_msg.chat.id,
                            message_id=src_msg.id,
                            caption=caption,
                            reply_markup=kb,
                        )
                    except Exception:
                        sent = await client.copy_message(
                            chat_id=tid,
                            from_chat_id=src_msg.chat.id,
                            message_id=src_msg.id,
                        )
                    if timer_secs > 0 and sent:
                        try:
                            await DB.schedule_autodelete(
                                tid, sent.id, timer_secs, sid
                            )
                        except Exception:
                            pass
                    return "sent"
                except Exception as e:
                    logger.debug(f"[BC-CONF] {tid}: {type(e).__name__}")
                    return "failed"

        results = await asyncio.gather(
            *[_send_one(t) for t in targets],
            return_exceptions=True,
        )
        for r in results:
            if r == "sent":
                grand_sent += 1
            else:
                grand_failed += 1

    # ─── Final report ───
    try:
        await client.edit_message_text(
            chat_id=progress_msg.chat.id,
            message_id=progress_msg.id,
            text="\n".join([
                f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                f"✅ <b>{fb('BROADCAST COMPLETE')}</b>",
                DIV, "",
                f"📦 {sc('files')} · <b>{total_files}</b>",
                f"🎯 {sc('targets')} · <b>{total_targets}</b>",
                "", DIV2, "",
                f"✅ {sc('sent')} · <b>{grand_sent}</b>",
                f"❌ {sc('failed')} · <b>{grand_failed}</b>",
            ]),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "❌ CLOSE",
                    callback_data=f"bcconf:{sid}:cancel",
                )
            ]]),
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass

    # Cleanup
    batch = ST.find_batch_by_sid(conf.get("batch_sid", ""))
    if batch:
        ST.clear_batch(batch["chat_id"])
    _CONF.pop(sid, None)

    await DB.log_broadcast({
        "kind": f"batch_{dest}",
        "total": grand_total,
        "sent": grand_sent,
        "failed": grand_failed,
        "blocked": 0,
        "deleted": 0,
        "autodelete_seconds": timer_secs,
    })


# ═════════════════════════════════════════════════════════════
# MANUAL TARGET INPUT (PM)
# ═════════════════════════════════════════════════════════════
@Client.on_message(
    filters.private & filters.text & ~filters.regex(r"^/"),
    group=-449,
)
async def conf_manual_input(client, message):
    if not message.from_user or not _is_admin(message.from_user.id):
        return
    # find any conf waiting for manual target for this admin
    for sid, conf in list(_CONF.items()):
        if conf.get("admin_id") != message.from_user.id:
            continue
        if not conf.get("manual_await"):
            continue
        text = (message.text or "").strip()
        try:
            if text.startswith("@"):
                chat = await client.get_chat(text)
                tid = chat.id
            else:
                tid = int(text)
        except Exception as e:
            await message.reply_text(f"❌ {e}")
            return
        conf["manual_await"] = False
        conf["manual_target"] = tid
        conf["channel_id"] = tid
        conf["destination"] = "manual"
        try:
            message.stop_propagation()
        except Exception:
            pass
        await message.reply_text(
            f"✅ Target saved · <code>{tid}</code>",
            parse_mode=ParseMode.HTML,
        )
        return


# ═════════════════════════════════════════════════════════════
# HELPERS
# ═════════════════════════════════════════════════════════════
async def _safe_edit_pm(q: CallbackQuery, text: str, kb):
    try:
        await q.message.edit_text(
            text, reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        if "not modified" not in str(e).lower():
            logger.debug(f"[BC-CONF] edit: {e}")


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
                    f"📌 {sc('upload files to the broadcast channel')}",
                    f"📌 {sc('then try again')}",
                ]),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        return

    try:
        await client.send_message(
            chat_id=user_id,
            text="\n".join([
                f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                f"📢 <b>{fb('BROADCAST')}</b>",
                DIV, "",
                f"📌 {sc('upload files to the broadcast channel')}",
                f"📌 {sc('the batch panel will open there')}",
                "",
                f"📊 {sc('files in queue')} · <b>{len(docs)}</b>",
            ]),
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        logger.exception(f"[BC-ADMIN] {e}")


__all__ = ["bc_open_for_admin"]
