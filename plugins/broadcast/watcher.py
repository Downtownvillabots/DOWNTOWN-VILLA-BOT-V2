# ============================================================
# 🏨 DOWNTOWN VILLA — BROADCAST WATCHER (IN-CHANNEL CONFIRM)
# ============================================================
# Upload N files → ONE message with per-file toggles
# Tap "Broadcast selected" → destination picker in SAME message
# All confirmation steps edit that same message.
# ============================================================

from __future__ import annotations
import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from plugins.broadcast.config import (
    BROADCAST_CHANNEL_ID, ADMINS, DEBOUNCE_SECONDS,
    BROADCAST_BATCH_SIZE, BROADCAST_CONCURRENCY, DEFAULT_DELAY,
    DIV, DIV2, fb, sc, _esc, _is_admin, _fmt_int, _progress_colored,
)
from plugins.broadcast import database as DB
from plugins.broadcast import keyboards as KB
from plugins.broadcast import state as ST
from plugins.broadcast import templates as TPL

logger = logging.getLogger(__name__)

_CONF: Dict[str, Dict[str, Any]] = {}
_CONF_TTL = 3600


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


def _get_conf(sid: str) -> Optional[Dict[str, Any]]:
    c = _CONF.get(sid)
    if not c:
        return None
    if time.time() - c.get("created", 0) > _CONF_TTL:
        _CONF.pop(sid, None)
        return None
    return c


# ═════════════════════════════════════════════════════════════
# WATCHER
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
                batch["admin_id"] = (
                    int(message.from_user.id)
                    if message.from_user and _is_admin(message.from_user.id)
                    else (int(ADMINS[0]) if ADMINS else 0)
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

    text, kb = _build_batch_view(batch, stage="toggles")
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


# ═════════════════════════════════════════════════════════════
# VIEW BUILDER (multi-stage)
# ═════════════════════════════════════════════════════════════
def _build_batch_view(
    batch: Dict[str, Any],
    stage: str = "toggles",
    conf: Optional[Dict[str, Any]] = None,
    extra: Optional[str] = None,
) -> Any:
    files = batch["files"]
    sid = batch["sid"]
    selected = [f for f in files if f["selected"]]

    if stage == "toggles":
        lines = [
            f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
            f"📦 <b>{fb('BATCH READY')}</b>",
            DIV, "",
            f"📊 {sc('files')} · <b>{len(files)}</b>",
            f"✅ {sc('selected')} · <b>{len(selected)}</b>",
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

    # ─── confirmation stages ───
    conf = conf or {}
    dest = conf.get("destination") or "—"
    cap_mode = conf.get("caption_mode") or "—"
    timer = conf.get("timer_days", 0)
    timer_label = "♾️ never" if not timer else f"⏱️ {timer}d"
    ch_id = conf.get("channel_id")
    ch_label = "—"
    if ch_id == "all":
        ch_label = "ALL"
    elif isinstance(ch_id, int):
        ch_label = str(ch_id)

    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🚀 <b>{fb('CONFIRM BROADCAST')}</b>",
        DIV, "",
        f"📦 {sc('files')} · <b>{len(selected)}</b>",
        f"🎯 {sc('destination')} · <b>{dest}</b>",
        f"📢 {sc('target')} · <code>{ch_label}</code>",
        f"📝 {sc('caption')} · <b>{cap_mode}</b>",
        f"⏱️ {sc('timer')} · <b>{timer_label}</b>",
    ]
    if extra:
        lines += ["", DIV2, "", extra]

    if stage == "dest":
        kb = KB.kb_conf_destination(sid)

    elif stage == "channels":
        ch_list = conf.get("_channels") or []
        kb = KB.kb_conf_channels(sid, ch_list)

    elif stage == "groups":
        total = conf.get("_groups_count", 0)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                f"✅ SEND TO {total} GROUPS",
                callback_data=f"bcconf:{sid}:groups_go",
            )],
            [InlineKeyboardButton(
                "◀️ BACK", callback_data=f"bcconf:{sid}:back"
            )],
            [InlineKeyboardButton(
                "❌ CANCEL", callback_data=f"bcconf:{sid}:cancel"
            )],
        ])

    elif stage == "users":
        total = conf.get("_users_count", 0)
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                f"✅ SEND TO {total} USERS",
                callback_data=f"bcconf:{sid}:users_go",
            )],
            [InlineKeyboardButton(
                "◀️ BACK", callback_data=f"bcconf:{sid}:back"
            )],
            [InlineKeyboardButton(
                "❌ CANCEL", callback_data=f"bcconf:{sid}:cancel"
            )],
        ])

    elif stage == "manual":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                "◀️ BACK", callback_data=f"bcconf:{sid}:back"
            )],
            [InlineKeyboardButton(
                "❌ CANCEL", callback_data=f"bcconf:{sid}:cancel"
            )],
        ])

    elif stage == "caption":
        has_ch = bool(ch_id)
        kb = KB.kb_conf_caption(sid, has_ch)

    elif stage == "timer":
        kb = KB.kb_conf_timer(sid)

    elif stage == "final":
        kb = KB.kb_conf_confirm(sid)

    elif stage == "preview":
        kb = KB.kb_conf_preview(sid)
        
    else:
        kb = KB.kb_conf_destination(sid)

    return "\n".join(lines), kb


# ═════════════════════════════════════════════════════════════
# BATCH TOGGLES
# ═════════════════════════════════════════════════════════════
async def _refresh_toggles(q: CallbackQuery, batch: Dict[str, Any]):
    text, kb = _build_batch_view(batch, stage="toggles")
    try:
        await q.message.edit_text(
            text, reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception:
        pass


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
    await _refresh_toggles(q, batch)
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
    await _refresh_toggles(q, batch)
    await q.answer("✅ All")


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
    await _refresh_toggles(q, batch)
    await q.answer("☐ Cleared")


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
# START CONFIRM — same message, not PM
# ═════════════════════════════════════════════════════════════
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

    _CONF[sid] = {
        "batch_sid": sid,
        "files": selected,
        "destination": None,
        "channel_id": None,
        "caption_mode": None,
        "timer_days": 0,
        "manual_await": False,
        "created": time.time(),
    }

    text, kb = _build_batch_view(
        batch, stage="dest", conf=_CONF[sid],
        extra=f"📌 {sc('pick destination')}",
    )
    try:
        await q.message.edit_text(
            text, reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.debug(f"[BC-BCAST] edit: {e}")
    await q.answer()


# ═════════════════════════════════════════════════════════════
# CONFIRM — destination picker
# ═════════════════════════════════════════════════════════════
@Client.on_callback_query(
    filters.regex(r"^bcconf:([a-f0-9]+):dest:(\w+)$"), group=-500
)
async def cb_conf_dest(client, q):
    sid = q.matches[0].group(1)
    dest = q.matches[0].group(2)
    conf = _get_conf(sid)
    if not conf:
        return await q.answer("⏱️ Expired", show_alert=True)
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)

    batch = ST.find_batch_by_sid(sid)
    if not batch:
        return await q.answer("⏱️ Expired", show_alert=True)

    conf["destination"] = dest

    if dest == "channels":
        channels = await DB.get_saved_channels()
        enabled = [c for c in channels if c.get("enabled", True)]
        if not enabled:
            return await q.answer("⚠️ No channels", show_alert=True)
        conf["_channels"] = enabled
        text, kb = _build_batch_view(
            batch, stage="channels", conf=conf,
            extra=f"📌 {sc('pick a channel')}",
        )
        await _edit_or_answer(q, text, kb)
        return

    if dest == "groups":
        total = await DB.count_groups()
        if total == 0:
            return await q.answer("⚠️ No groups", show_alert=True)
        conf["_groups_count"] = total
        conf["channel_id"] = None
        text, kb = _build_batch_view(
            batch, stage="groups", conf=conf,
            extra=f"📊 {sc('groups')} · <b>{total}</b>",
        )
        await _edit_or_answer(q, text, kb)
        return

    if dest == "users":
        total = await DB.count_users()
        if total == 0:
            return await q.answer("⚠️ No users", show_alert=True)
        conf["_users_count"] = total
        conf["channel_id"] = None
        text, kb = _build_batch_view(
            batch, stage="users", conf=conf,
            extra=f"📊 {sc('users')} · <b>{total}</b>",
        )
        await _edit_or_answer(q, text, kb)
        return

    if dest == "manual":
        conf["manual_await"] = True
        conf["destination"] = "manual"
        text, kb = _build_batch_view(
            batch, stage="manual", conf=conf,
            extra="\n".join([
                f"🎯 {sc('send the target chat id here')}",
                f"📌 {sc('example')} · <code>-1001234567890</code>",
                f"📌 {sc('or')} · <code>@username</code>",
            ]),
        )
        await _edit_or_answer(q, text, kb)
        return


@Client.on_callback_query(
    filters.regex(r"^bcconf:([a-f0-9]+):ch:(-?\d+)$"), group=-500
)
async def cb_conf_ch(client, q):
    sid = q.matches[0].group(1)
    cid = int(q.matches[0].group(2))
    conf = _get_conf(sid)
    if not conf:
        return await q.answer("⏱️ Expired", show_alert=True)
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)

    batch = ST.find_batch_by_sid(sid)
    conf["channel_id"] = cid

    text, kb = _build_batch_view(
        batch, stage="caption", conf=conf,
        extra=f"📝 {sc('choose caption mode')}",
    )
    await _edit_or_answer(q, text, kb)


@Client.on_callback_query(
    filters.regex(r"^bcconf:([a-f0-9]+):chall$"), group=-500
)
async def cb_conf_chall(client, q):
    sid = q.matches[0].group(1)
    conf = _get_conf(sid)
    if not conf:
        return await q.answer("⏱️ Expired", show_alert=True)
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)

    batch = ST.find_batch_by_sid(sid)
    conf["channel_id"] = "all"
    conf["destination"] = "channels"

    text, kb = _build_batch_view(
        batch, stage="caption", conf=conf,
        extra=f"📝 {sc('choose caption mode')}",
    )
    await _edit_or_answer(q, text, kb)


@Client.on_callback_query(
    filters.regex(r"^bcconf:([a-f0-9]+):groups_go$"), group=-500
)
async def cb_conf_groups_go(client, q):
    sid = q.matches[0].group(1)
    conf = _get_conf(sid)
    if not conf:
        return await q.answer("⏱️ Expired", show_alert=True)
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)

    batch = ST.find_batch_by_sid(sid)
    conf["channel_id"] = None

    text, kb = _build_batch_view(
        batch, stage="caption", conf=conf,
        extra=f"📝 {sc('choose caption mode')}",
    )
    await _edit_or_answer(q, text, kb)


@Client.on_callback_query(
    filters.regex(r"^bcconf:([a-f0-9]+):users_go$"), group=-500
)
async def cb_conf_users_go(client, q):
    sid = q.matches[0].group(1)
    conf = _get_conf(sid)
    if not conf:
        return await q.answer("⏱️ Expired", show_alert=True)
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)

    batch = ST.find_batch_by_sid(sid)
    conf["channel_id"] = None

    text, kb = _build_batch_view(
        batch, stage="caption", conf=conf,
        extra=f"📝 {sc('choose caption mode')}",
    )
    await _edit_or_answer(q, text, kb)


@Client.on_callback_query(
    filters.regex(r"^bcconf:([a-f0-9]+):cap:(\w+)$"), group=-500
)
async def cb_conf_cap(client, q):
    sid = q.matches[0].group(1)
    mode = q.matches[0].group(2)
    conf = _get_conf(sid)
    if not conf:
        return await q.answer("⏱️ Expired", show_alert=True)
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)

    batch = ST.find_batch_by_sid(sid)
    conf["caption_mode"] = mode

    text, kb = _build_batch_view(
        batch, stage="timer", conf=conf,
        extra=f"⏱️ {sc('pick a timer')}",
    )
    await _edit_or_answer(q, text, kb)


@Client.on_callback_query(
    filters.regex(r"^bcconf:([a-f0-9]+):timer:(\d+)$"), group=-500
)
async def cb_conf_timer(client, q):
    sid = q.matches[0].group(1)
    days = int(q.matches[0].group(2))
    conf = _get_conf(sid)
    if not conf:
        return await q.answer("⏱️ Expired", show_alert=True)
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)

    batch = ST.find_batch_by_sid(sid)
    conf["timer_days"] = days

    # Build caption preview
    preview_text = await _render_preview(client, batch, conf)
    text, kb = _build_batch_view(
        batch, stage="preview", conf=conf,
        extra=preview_text,
    )
    await _edit_or_answer(q, text, kb)


@Client.on_callback_query(
    filters.regex(r"^bcconf:([a-f0-9]+):back$"), group=-500
)
async def cb_conf_back(client, q):
    sid = q.matches[0].group(1)
    conf = _get_conf(sid)
    if not conf:
        return await q.answer("⏱️ Expired", show_alert=True)
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)

    batch = ST.find_batch_by_sid(sid)
    conf["destination"] = None
    conf["channel_id"] = None
    conf["caption_mode"] = None
    conf["timer_days"] = 0

    text, kb = _build_batch_view(
        batch, stage="dest", conf=conf,
        extra=f"📌 {sc('pick destination')}",
    )
    await _edit_or_answer(q, text, kb)


@Client.on_callback_query(
    filters.regex(r"^bcconf:([a-f0-9]+):chcap$"), group=-500
)
async def cb_conf_chcap(client, q):
    sid = q.matches[0].group(1)
    conf = _get_conf(sid)
    if not conf:
        return await q.answer("⏱️ Expired", show_alert=True)
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)

    batch = ST.find_batch_by_sid(sid)
    text, kb = _build_batch_view(
        batch, stage="caption", conf=conf,
        extra=f"📝 {sc('choose caption mode')}",
    )
    await _edit_or_answer(q, text, kb)


@Client.on_callback_query(
    filters.regex(r"^bcconf:([a-f0-9]+):chtimer$"), group=-500
)
async def cb_conf_chtimer(client, q):
    sid = q.matches[0].group(1)
    conf = _get_conf(sid)
    if not conf:
        return await q.answer("⏱️ Expired", show_alert=True)
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)

    batch = ST.find_batch_by_sid(sid)
    text, kb = _build_batch_view(
        batch, stage="timer", conf=conf,
        extra=f"⏱️ {sc('pick a timer')}",
    )
    await _edit_or_answer(q, text, kb)


@Client.on_callback_query(
    filters.regex(r"^bcconf:([a-f0-9]+):cancel$"), group=-500
)
async def cb_conf_cancel(client, q):
    sid = q.matches[0].group(1)
    _CONF.pop(sid, None)
    batch = ST.find_batch_by_sid(sid)
    if batch:
        ST.clear_batch(batch["chat_id"])
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
    conf = _get_conf(sid)
    if not conf:
        return await q.answer("⏱️ Expired", show_alert=True)
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)

    if not conf.get("destination"):
        return await q.answer("⚠️ Pick destination", show_alert=True)
    if not conf.get("caption_mode"):
        return await q.answer("⚠️ Pick caption mode", show_alert=True)

    await q.answer("🚀 Starting…")
    asyncio.create_task(_execute_batch(client, q, sid, conf))


async def _edit_or_answer(q: CallbackQuery, text: str, kb):
    try:
        await q.message.edit_text(
            text, reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        if "not modified" not in str(e).lower():
            logger.debug(f"[BC-CONF] edit: {e}")
    try:
        await q.answer()
    except Exception:
        pass


# ═════════════════════════════════════════════════════════════
# EXECUTE BATCH — sends and updates the SAME message in channel
# ═════════════════════════════════════════════════════════════
async def _execute_batch(client, q, sid, conf):
    from plugins.broadcast.config import (
        AUTODELETE_SECONDS, BROADCAST_BATCH_SIZE,
        BROADCAST_CONCURRENCY, DEFAULT_DELAY,
    )

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
        targets = []
        kind = "?"

    targets = [t for t in targets if t]
    if not targets:
        try:
            await q.message.edit_text(
                "⚠️ No valid targets",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        return

    # ─── Global caption template ───
    global_cap = await DB.get_global_caption()
    global_btns = await DB.get_global_buttons()

    total_files = len(files)
    total_targets = len(targets)
    grand_total = total_files * total_targets
    grand_sent = 0
    grand_failed = 0

    progress_msg = q.message

    # ─── Loop through files ───
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
            own_clean = TPL.clean_caption(
                f.get("original_caption") or ""
            )
            caption = own_clean if own_clean else ""
            kb = None
        elif cap_mode == "global":
            caption = TPL.build_caption(src_msg, global_cap)
            kb = TPL.build_buttons_kb(global_btns)
        elif cap_mode == "channel":
            ch = None
            if isinstance(ch_id, int):
                ch = await DB.get_channel(int(ch_id))
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
                    "",
                    _progress_colored(
                        grand_sent + grand_failed, grand_total
                    ),
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

        # ─── Send to targets (concurrent) ───
        sem = asyncio.Semaphore(BROADCAST_CONCURRENCY)
        lock = asyncio.Lock()

        async def _one(tid):
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
                    await asyncio.sleep(DEFAULT_DELAY)
                    return "sent"
                except Exception as e:
                    logger.debug(
                        f"[BC-EXEC] {tid}: {type(e).__name__}"
                    )
                    return "failed"

        try:
            batch_targets = []
            for i in range(0, total_targets, BROADCAST_BATCH_SIZE):
                sub = targets[i:i + BROADCAST_BATCH_SIZE]
                res = await asyncio.gather(
                    *[_one(t) for t in sub],
                    return_exceptions=True,
                )
                for r in res:
                    if r == "sent":
                        grand_sent += 1
                    else:
                        grand_failed += 1
        except Exception as e:
            logger.exception(f"[BC-EXEC] {e}")

    # ─── Final report (SAME message) ───
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

    # ─── Cleanup ───
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
# MANUAL TARGET INPUT (in channel)
# ═════════════════════════════════════════════════════════════
if BROADCAST_CHANNEL_ID:

    @Client.on_message(
        filters.chat(BROADCAST_CHANNEL_ID) & filters.text
        & ~filters.regex(r"^/"),
        group=-498,
    )
    async def conf_manual_input(client, message):
        if not message.from_user or not _is_admin(message.from_user.id):
            return
        # find any conf waiting for manual target
        target_sid = None
        for sid, conf in list(_CONF.items()):
            if not conf.get("manual_await"):
                continue
            target_sid = sid
            break
        if not target_sid:
            return

        conf = _CONF[target_sid]
        text = (message.text or "").strip()
        try:
            if text.startswith("@"):
                chat = await client.get_chat(text)
                tid = chat.id
            else:
                tid = int(text)
        except Exception as e:
            try:
                message.stop_propagation()
            except Exception:
                pass
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

        # Confirm and move to caption
        batch = ST.find_batch_by_sid(target_sid)
        if batch and batch.get("reply_msg_id"):
            try:
                text_view, kb = _build_batch_view(
                    batch, stage="caption", conf=conf,
                    extra=f"📝 {sc('choose caption mode')}",
                )
                await client.edit_message_text(
                    chat_id=batch["chat_id"],
                    message_id=batch["reply_msg_id"],
                    text=text_view,
                    reply_markup=kb,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
            except Exception:
                pass

        try:
            await message.delete()
        except Exception:
            pass


async def _render_preview(client, batch, conf) -> str:
    """Render preview of the caption using the first selected file."""
    files = conf["files"]
    if not files:
        return "(no files)"

    first = files[0]
    try:
        src_msg = await client.get_messages(
            int(first["chat_id"]), int(first["msg_id"])
        )
    except Exception:
        src_msg = None

    cap_mode = conf.get("caption_mode")
    caption_display = ""

    if cap_mode == "own":
        cleaned = TPL.clean_caption(first.get("original_caption") or "")
        if not cleaned:
            caption_display = "<i>(no caption on this file)</i>"
        else:
            caption_display = _esc(cleaned)

    elif cap_mode == "channel":
        ch_id = conf.get("channel_id")
        ch = None
        if isinstance(ch_id, int):
            ch = await DB.get_channel(int(ch_id))
        if ch and ch.get("caption"):
            cap_tpl = ch["caption"]
        else:
            cap_tpl = await DB.get_global_caption()
        if src_msg:
            caption_display = TPL.build_caption(src_msg, cap_tpl)
        else:
            caption_display = _esc(cap_tpl)

    else:  # global
        cap_tpl = await DB.get_global_caption()
        if src_msg:
            caption_display = TPL.build_caption(src_msg, cap_tpl)
        else:
            caption_display = _esc(cap_tpl)

    lines = [
        f"👁️ <b>{fb('PREVIEW')}</b>",
        "",
        f"📛 <code>{(first.get('name') or 'file')[:44]}</code>",
        "",
        f"<b>{sc('caption')}:</b>",
        "",
        caption_display,
    ]
    if len(files) > 1:
        lines += ["", f"📦 <i>+ {len(files) - 1} more file(s)</i>"]

    return "\n".join(lines)


# ═════════════════════════════════════════════════════════════
# ADMIN PANEL ENTRY (/admin → 📢 Broadcast)
# ═════════════════════════════════════════════════════════════
async def bc_open_for_admin(client: Client, user_id: int) -> None:
    """Called from /admin → 📢 Broadcast."""
    if not BROADCAST_CHANNEL_ID:
        try:
            await client.send_message(
                chat_id=user_id,
                text="⚠️ <b>BROADCAST_CHANNEL_ID not set</b>",
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
                f"📌 {sc('the batch panel opens there')}",
                "",
                f"📊 {sc('files in queue')} · <b>{len(docs)}</b>",
            ]),
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        logger.exception(f"[BC-ADMIN] {e}")


__all__ = ["bc_open_for_admin"]
