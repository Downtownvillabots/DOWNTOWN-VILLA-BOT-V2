# ============================================================
# 🏨 DOWNTOWN VILLA — BROADCAST ENGINE
# ============================================================

from __future__ import annotations
import asyncio
import logging
import time
from typing import Any, Dict, List, Optional

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.errors import (
    FloodWait, RPCError, UserIsBlocked, InputUserDeactivated,
    ChatWriteForbidden, ChatAdminRequired, ChannelPrivate,
    UserNotParticipant, PeerIdInvalid, MessageIdInvalid, ChatForbidden,
    UserDeactivated, UserDeactivatedBan, MessageNotModified, MediaEmpty,
)
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from plugins.broadcast.config import (
    BROADCAST_BATCH_SIZE, BROADCAST_CONCURRENCY, DEFAULT_DELAY,
    PROGRESS_EDIT_INTERVAL, DIV, DIV2,
    fb, sc, _esc, _fmt_int, _fmt_duration, _progress_colored,
)
from plugins.broadcast import database as DB
from plugins.broadcast import state as ST
from plugins.broadcast import templates as TPL

logger = logging.getLogger(__name__)


def _kind_label(kind):
    return {
        "channel": "ᴄʜᴀɴɴᴇʟ", "channels_all": "ᴀʟʟ ᴄʜᴀɴɴᴇʟꜱ",
        "groups": "ɢʀᴏᴜᴘꜱ", "users": "ᴜꜱᴇʀꜱ",
    }.get(kind, kind)


# ═════════════════════════════════════════════════════════════
# RUN BROADCAST
# ═════════════════════════════════════════════════════════════
async def run_broadcast(
    client: Client, q: CallbackQuery, sid: str, kind: str,
    targets: Optional[List[int]] = None,
    autodelete_seconds: int = 0,
):
    src = ST.get_source(sid)
    if not src:
        return await q.answer("⏱️ ᴇxᴘɪʀᴇᴅ", show_alert=True)

    # Handle batches (USE ALL)
    use_all = src.get("use_all") and src.get("batch")
    batch: List = src.get("batch") or []

    # Build target list
    if kind == "channel":
        if not targets:
            return await q.answer("⚠️ ɴᴏ ᴛᴀʀɢᴇᴛ", show_alert=True)
        target_list = list(targets)
    elif kind == "channels_all":
        channels = await DB.get_saved_channels()
        enabled = [c for c in channels if c.get("enabled", True)]
        if not enabled:
            return await q.answer("⚠️ ɴᴏ ᴄʜᴀɴɴᴇʟꜱ", show_alert=True)
        # channels_all does per-channel caption/buttons
        asyncio.create_task(
            _run_channels_all(client, q, src, enabled,
                             use_all, batch, autodelete_seconds)
        )
        return
    elif kind == "groups":
        target_list = await DB.get_all_groups()
    elif kind == "users":
        target_list = await DB.get_all_users()
    else:
        return await q.answer("⚠️ ʙᴀᴅ ᴋɪɴᴅ", show_alert=True)

    total = len(target_list)
    if total == 0:
        return await q.answer("⚠️ ɴᴏ ᴛᴀʀɢᴇᴛꜱ", show_alert=True)

    # Per-channel caption/buttons for single channel
    if kind == "channel" and len(target_list) == 1:
        ch = await DB.get_channel(target_list[0])
        cap_tpl = await TPL.effective_caption(ch)
        btns = await TPL.effective_buttons(ch)
    else:
        cap_tpl = await DB.get_global_caption()
        btns = await DB.get_global_buttons()

    # Get source message(s)
    if use_all and batch:
        src_msgs = []
        for msg_id, name in batch:
            try:
                m = await client.get_messages(src["chat_id"], msg_id)
                if m and not m.empty:
                    src_msgs.append((m, name))
            except Exception as e:
                logger.warning(f"[BC-RUN] fetch {msg_id}: {e}")
        if not src_msgs:
            return await q.answer("⚠️ ɴᴏ ꜱᴏᴜʀᴄᴇ", show_alert=True)
    else:
        try:
            m = await client.get_messages(src["chat_id"], src["message_id"])
        except Exception as e:
            return await q.answer(f"⚠️ {e}"[:180], show_alert=True)
        if not m or m.empty:
            return await q.answer("⚠️ ꜱᴏᴜʀᴄᴇ ᴅᴇʟᴇᴛᴇᴅ", show_alert=True)
        src_msgs = [(m, "file")]

    # Kick off
    progress_chat = q.message.chat.id
    try:
        progress_msg = await q.message.edit_text(
            f"🏨 <b>{fb('BROADCAST STARTED')}</b>\n{DIV}\n\n"
            f"📤 {sc('sending to')} <b>{_fmt_int(total)}</b> "
            f"{_kind_label(kind)}...",
            parse_mode=ParseMode.HTML,
        )
    except MessageNotModified:
        progress_msg = q.message
    except Exception:
        progress_msg = q.message

    if use_all and batch:
        asyncio.create_task(_run_batch(
            client, progress_chat, progress_msg.id,
            src, src_msgs, target_list, kind,
            cap_tpl, btns, autodelete_seconds,
        ))
    else:
        src_msg = src_msgs[0][0]
        caption = TPL.build_caption(src_msg, cap_tpl)
        kb = TPL.build_buttons_kb(btns)
        jid = ST.new_job(
            admin_id=q.from_user.id, kind=kind, total=total,
            source_msg_id=src["message_id"],
            source_chat_id=src["chat_id"],
            progress_chat_id=progress_chat,
            progress_msg_id=progress_msg.id,
            autodelete_seconds=autodelete_seconds,
        )
        job = ST.get_job(jid)
        job["targets"] = target_list
        asyncio.create_task(
            _worker(client, jid, src_msg, caption, kb)
        )


# ═════════════════════════════════════════════════════════════
# WORKER (single source)
# ═════════════════════════════════════════════════════════════
async def _worker(client, jid, src_msg, caption, kb):
    job = ST.get_job(jid)
    if not job:
        return
    targets = job["targets"]
    total = job["total"]
    ad = job.get("autodelete_seconds", 0)
    start = time.time()
    sem = asyncio.Semaphore(BROADCAST_CONCURRENCY)
    lock = asyncio.Lock()

    async def _one(tid):
        if job["cancel_flag"]:
            return "cancelled"
        async with sem:
            if job["cancel_flag"]:
                return "cancelled"
            try:
                sent = None
                try:
                    sent = await client.copy_message(
                        chat_id=tid,
                        from_chat_id=src_msg.chat.id,
                        message_id=src_msg.id,
                        caption=caption, reply_markup=kb,
                    )
                except (MediaEmpty, MessageNotModified):
                    sent = await client.copy_message(
                        chat_id=tid,
                        from_chat_id=src_msg.chat.id,
                        message_id=src_msg.id,
                    )
                if ad > 0 and sent:
                    try:
                        await DB.schedule_autodelete(
                            tid, sent.id, ad, jid
                        )
                    except Exception:
                        pass
                await asyncio.sleep(DEFAULT_DELAY)
                return "sent"
            except FloodWait as e:
                await asyncio.sleep(max(1, int(e.value)) + 2)
                try:
                    sent = await client.copy_message(
                        chat_id=tid,
                        from_chat_id=src_msg.chat.id,
                        message_id=src_msg.id,
                        caption=caption, reply_markup=kb,
                    )
                    if ad > 0 and sent:
                        try:
                            await DB.schedule_autodelete(
                                tid, sent.id, ad, jid
                            )
                        except Exception:
                            pass
                    return "sent"
                except Exception:
                    return "failed"
            except UserIsBlocked:
                return "blocked"
            except (InputUserDeactivated, UserDeactivated,
                    UserDeactivatedBan):
                return "deleted"
            except (ChatWriteForbidden, ChatForbidden,
                    ChatAdminRequired, ChannelPrivate,
                    PeerIdInvalid, UserNotParticipant,
                    MessageIdInvalid, RPCError):
                return "failed"
            except Exception as e:
                logger.debug(f"[BC] {tid}: {type(e).__name__}: {e}")
                return "failed"

    async def _wrap(tid):
        r = await _one(tid)
        async with lock:
            job["current_index"] += 1
            if r == "sent":
                job["sent"] += 1
            elif r == "blocked":
                job["blocked"] += 1
                if job["kind"] == "users":
                    asyncio.create_task(DB.delete_user(tid))
            elif r == "deleted":
                job["deleted"] += 1
                if job["kind"] == "users":
                    asyncio.create_task(DB.delete_user(tid))
            elif r == "failed":
                job["failed"] += 1

    try:
        for i in range(0, total, BROADCAST_BATCH_SIZE):
            if job["cancel_flag"]:
                break
            batch = targets[i:i + BROADCAST_BATCH_SIZE]
            await asyncio.gather(*[_wrap(t) for t in batch])
            await _update_progress(client, job)
        cancelled = job["cancel_flag"]
        ST.finish_job(jid, "cancelled" if cancelled else "completed")
        await _render_done(client, job, cancelled)
        await DB.log_broadcast({
            "job_id": jid, "kind": job["kind"],
            "admin_id": job["admin_id"], "total": total,
            "sent": job["sent"], "failed": job["failed"],
            "blocked": job["blocked"], "deleted": job["deleted"],
            "elapsed": time.time() - start,
            "status": job["status"],
            "autodelete_seconds": ad,
        })
    except Exception as e:
        logger.exception(f"[BC-RUN] crashed: {e}")
        ST.finish_job(jid, "failed")


# ═════════════════════════════════════════════════════════════
# WORKER (batch of multiple sources)
# ═════════════════════════════════════════════════════════════
async def _run_batch(
    client, chat_id, msg_id,
    src, src_msgs, target_list, kind,
    cap_tpl, btns, autodelete_seconds,
):
    total_src = len(src_msgs)
    total_tg = len(target_list)
    grand_total = total_src * total_tg
    grand_sent = 0
    grand_failed = 0
    grand_blocked = 0

    for idx, (src_msg, name) in enumerate(src_msgs, 1):
        # progress header
        try:
            await client.edit_message_text(
                chat_id=chat_id, message_id=msg_id,
                text="\n".join([
                    f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                    f"🚀 <b>{fb('MULTI-FILE BROADCAST')}</b>",
                    DIV, "",
                    f"📦 {sc('file')} · <b>{idx}/{total_src}</b>",
                    f"📛 <code>{name[:40]}</code>",
                    "", DIV2,
                    f"🎯 {sc('targets')} · <b>{total_tg}</b>",
                    f"📊 {sc('progress')} · "
                    f"<b>{grand_sent + grand_failed}/{grand_total}</b>",
                ]),
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        "⏹ STOP", callback_data="bcstop:batch"
                    )
                ]]),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass

        caption = TPL.build_caption(src_msg, cap_tpl)
        kb = TPL.build_buttons_kb(btns)

        jid = ST.new_job(
            admin_id=0, kind=kind, total=total_tg,
            source_msg_id=src_msg.id,
            source_chat_id=src_msg.chat.id,
            progress_chat_id=chat_id,
            progress_msg_id=msg_id,
            autodelete_seconds=autodelete_seconds,
        )
        job = ST.get_job(jid)
        job["targets"] = target_list
        job["batch_aggregate"] = True

        # silent worker — reuse _worker but with aggregate tracking
        # to keep it simple: await a manual loop
        sem = asyncio.Semaphore(BROADCAST_CONCURRENCY)
        lock = asyncio.Lock()

        async def _one(tid):
            async with sem:
                if job["cancel_flag"]:
                    return "cancelled"
                try:
                    sent = None
                    try:
                        sent = await client.copy_message(
                            chat_id=tid,
                            from_chat_id=src_msg.chat.id,
                            message_id=src_msg.id,
                            caption=caption, reply_markup=kb,
                        )
                    except (MediaEmpty, MessageNotModified):
                        sent = await client.copy_message(
                            chat_id=tid,
                            from_chat_id=src_msg.chat.id,
                            message_id=src_msg.id,
                        )
                    if autodelete_seconds > 0 and sent:
                        try:
                            await DB.schedule_autodelete(
                                tid, sent.id,
                                autodelete_seconds, jid,
                            )
                        except Exception:
                            pass
                    await asyncio.sleep(DEFAULT_DELAY)
                    return "sent"
                except FloodWait as e:
                    await asyncio.sleep(max(1, int(e.value)) + 2)
                    try:
                        sent = await client.copy_message(
                            chat_id=tid,
                            from_chat_id=src_msg.chat.id,
                            message_id=src_msg.id,
                            caption=caption, reply_markup=kb,
                        )
                        return "sent"
                    except Exception:
                        return "failed"
                except UserIsBlocked:
                    return "blocked"
                except (InputUserDeactivated, UserDeactivated,
                        UserDeactivatedBan):
                    return "deleted"
                except Exception:
                    return "failed"

        async def _wrap(tid):
            r = await _one(tid)
            async with lock:
                if r == "sent":
                    grand_sent_nc[0] += 1
                elif r == "failed":
                    grand_failed_nc[0] += 1
                elif r == "blocked":
                    grand_blocked_nc[0] += 1

        grand_sent_nc = [0]
        grand_failed_nc = [0]
        grand_blocked_nc = [0]

        try:
            for i in range(0, total_tg, BROADCAST_BATCH_SIZE):
                if job["cancel_flag"]:
                    break
                batch = target_list[i:i + BROADCAST_BATCH_SIZE]
                await asyncio.gather(*[_wrap(t) for t in batch])
        except Exception as e:
            logger.exception(f"[BC-BATCH] {name}: {e}")

        grand_sent += grand_sent_nc[0]
        grand_failed += grand_failed_nc[0]
        grand_blocked += grand_blocked_nc[0]

        await asyncio.sleep(0.5)

    # Final report
    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"✅ <b>{fb('BATCH COMPLETE')}</b>",
        DIV, "",
        f"📦 {sc('files')} · <b>{total_src}</b>",
        f"🎯 {sc('targets')} · <b>{total_tg}</b>",
        "", DIV2, "",
        f"✅ {sc('sent')} · <b>{_fmt_int(grand_sent)}</b>",
        f"❌ {sc('failed')} · <b>{_fmt_int(grand_failed)}</b>",
        f"🚫 {sc('blocked')} · <b>{_fmt_int(grand_blocked)}</b>",
    ]
    try:
        await client.edit_message_text(
            chat_id=chat_id, message_id=msg_id,
            text="\n".join(lines),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "❌ CLOSE", callback_data="bcend:batch"
                )
            ]]),
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass

    await DB.log_broadcast({
        "kind": f"{kind}_batch",
        "total": grand_total,
        "sent": grand_sent, "failed": grand_failed,
        "blocked": grand_blocked, "deleted": 0,
        "autodelete_seconds": autodelete_seconds,
    })


# ═════════════════════════════════════════════════════════════
# CHANNELS ALL (per-channel caption)
# ═════════════════════════════════════════════════════════════
async def _run_channels_all(
    client, q, src, channels,
    use_all, batch, autodelete_seconds,
):
    chat_id = q.message.chat.id
    msg_id = q.message.id

    # Get source messages
    if use_all and batch:
        src_list = []
        for m_id, name in batch:
            try:
                m = await client.get_messages(src["chat_id"], m_id)
                if m and not m.empty:
                    src_list.append((m, name))
            except Exception:
                pass
    else:
        try:
            m = await client.get_messages(
                src["chat_id"], src["message_id"]
            )
            if m and not m.empty:
                src_list = [(m, "file")]
            else:
                src_list = []
        except Exception:
            src_list = []

    if not src_list:
        return

    grand_sent = 0
    grand_failed = 0

    for idx, (src_msg, name) in enumerate(src_list, 1):
        for ch in channels:
            cid = ch.get("chat_id")
            cap_tpl = (
                ch.get("caption")
                if ch.get("caption") is not None
                else await DB.get_global_caption()
            )
            btns = (
                ch.get("buttons")
                if ch.get("buttons") is not None
                else await DB.get_global_buttons()
            )
            caption = TPL.build_caption(src_msg, cap_tpl)
            kb = TPL.build_buttons_kb(btns)
            try:
                sent = await client.copy_message(
                    chat_id=int(cid),
                    from_chat_id=src_msg.chat.id,
                    message_id=src_msg.id,
                    caption=caption, reply_markup=kb,
                )
                grand_sent += 1
                if autodelete_seconds > 0 and sent:
                    try:
                        await DB.schedule_autodelete(
                            int(cid), sent.id,
                            autodelete_seconds, "",
                        )
                    except Exception:
                        pass
            except FloodWait as e:
                await asyncio.sleep(int(e.value) + 2)
                try:
                    sent = await client.copy_message(
                        chat_id=int(cid),
                        from_chat_id=src_msg.chat.id,
                        message_id=src_msg.id,
                        caption=caption, reply_markup=kb,
                    )
                    grand_sent += 1
                except Exception:
                    grand_failed += 1
            except Exception:
                grand_failed += 1

            await asyncio.sleep(0.4)

        # progress
        try:
            await client.edit_message_text(
                chat_id=chat_id, message_id=msg_id,
                text="\n".join([
                    f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                    f"🚀 <b>{fb('ALL CHANNELS')}</b>",
                    DIV, "",
                    f"📦 {sc('file')} · <b>{idx}/{len(src_list)}</b>",
                    f"📛 <code>{name[:35]}</code>",
                    "", DIV2, "",
                    f"✅ {sc('sent')} · <b>{grand_sent}</b>",
                    f"❌ {sc('failed')} · <b>{grand_failed}</b>",
                ]),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass

    # Final
    try:
        await client.edit_message_text(
            chat_id=chat_id, message_id=msg_id,
            text="\n".join([
                f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
                f"✅ <b>{fb('ALL CHANNELS COMPLETE')}</b>",
                DIV, "",
                f"📦 {sc('files')} · <b>{len(src_list)}</b>",
                f"📢 {sc('channels')} · <b>{len(channels)}</b>",
                "", DIV2, "",
                f"✅ {sc('sent')} · <b>{grand_sent}</b>",
                f"❌ {sc('failed')} · <b>{grand_failed}</b>",
            ]),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    "❌ CLOSE", callback_data="bcend:batch"
                )
            ]]),
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass

    await DB.log_broadcast({
        "kind": "channels_all",
        "total": len(src_list) * len(channels),
        "sent": grand_sent, "failed": grand_failed,
        "blocked": 0, "deleted": 0,
        "autodelete_seconds": autodelete_seconds,
    })


# ═════════════════════════════════════════════════════════════
# PROGRESS + DONE
# ═════════════════════════════════════════════════════════════
async def _update_progress(client, job):
    if job["cancel_flag"]:
        return
    now = time.time()
    if (now - job["last_edit"] < PROGRESS_EDIT_INTERVAL
            and job["current_index"] < job["total"]):
        return
    job["last_edit"] = now

    elapsed = max(0.001, now - job["started_at"])
    done = job["current_index"]
    total = job["total"]
    speed = done / elapsed if elapsed else 0
    remaining = max(0, total - done)
    eta = remaining / speed if speed > 0 else 0
    bar = _progress_colored(done, total, width=14)

    ad = job.get("autodelete_seconds", 0)
    ad_line = ""
    if ad > 0:
        ad_line = f"⏱️ {sc('auto-delete')} · {_fmt_duration(ad)}"

    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📢 <b>{fb('BROADCAST IN PROGRESS')}</b>",
        DIV, "",
        f"📤 {sc('sending to')} <b>{_kind_label(job['kind'])}</b>",
    ]
    if ad_line:
        lines.append(ad_line)
    lines += [
        "", bar, "",
        f"✅ {sc('sent')} · <code>{_fmt_int(job['sent'])}</code>",
        f"❌ {sc('failed')} · <code>{_fmt_int(job['failed'])}</code>",
        f"🚫 {sc('blocked')} · <code>{_fmt_int(job['blocked'])}</code>",
        f"👻 {sc('deleted')} · <code>{_fmt_int(job['deleted'])}</code>",
        "", DIV2, "",
        f"📊 {sc('progress')} · <code>{done}/{total}</code>",
        f"⚡ {sc('speed')} · <code>{speed:.1f}/s</code>",
        f"⏱️ {sc('eta')} · <code>{_fmt_duration(eta)}</code>",
    ]
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "⏹️ CANCEL", callback_data=f"bcstop:{job['id']}"
        )
    ]])
    try:
        await client.edit_message_text(
            chat_id=job["progress_chat_id"],
            message_id=job["progress_msg_id"],
            text="\n".join(lines),
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except MessageNotModified:
        pass
    except Exception as e:
        logger.debug(f"[BC] progress edit: {e}")


async def _render_done(client, job, cancelled):
    elapsed = time.time() - job["started_at"]
    title = "🛑 ᴄᴀɴᴄᴇʟʟᴇᴅ" if cancelled else "✅ ᴄᴏᴍᴘʟᴇᴛᴇ"
    ad = job.get("autodelete_seconds", 0)
    ad_line = ""
    if ad > 0:
        ad_line = f"⏱️ {sc('auto-delete')} · {_fmt_duration(ad)}"

    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📢 <b>{fb('BROADCAST ' + ('CANCELLED' if cancelled else 'COMPLETE'))}</b>",
        DIV, "",
        f"📤 {sc('target')} · <b>{_kind_label(job['kind'])}</b>",
    ]
    if ad_line:
        lines.append(ad_line)
    lines += [
        "",
        f"✅ {sc('sent')} · <code>{_fmt_int(job['sent'])}</code>",
        f"❌ {sc('failed')} · <code>{_fmt_int(job['failed'])}</code>",
        f"🚫 {sc('blocked')} · <code>{_fmt_int(job['blocked'])}</code>",
        f"👻 {sc('deleted')} · <code>{_fmt_int(job['deleted'])}</code>",
        "", DIV2,
        f"🕒 {sc('total time')} · <code>{_fmt_duration(elapsed)}</code>",
        "", f"<b>{title}</b>",
    ]
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            "❌ CLOSE", callback_data=f"bcend:{job['id']}"
        )
    ]])
    try:
        await client.edit_message_text(
            chat_id=job["progress_chat_id"],
            message_id=job["progress_msg_id"],
            text="\n".join(lines),
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except MessageNotModified:
        pass
    except Exception as e:
        logger.warning(f"[BC] done edit: {e}")


# ═════════════════════════════════════════════════════════════
# STOP / CLOSE
# ═════════════════════════════════════════════════════════════
@Client.on_callback_query(
    filters.regex(r"^bcstop:([a-f0-9]+)$"), group=-500
)
async def cb_stop(client, q):
    if not _is_admin_check(q):
        return await q.answer("⛔", show_alert=True)
    jid = q.matches[0].group(1)
    job = ST.get_job(jid)
    if not job:
        return await q.answer("⚠️ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)
    job["cancel_flag"] = True
    await q.answer("⏹️ ᴄᴀɴᴄᴇʟʟɪɴɢ...")


@Client.on_callback_query(
    filters.regex(r"^bcend:([a-f0-9]+|batch)$"), group=-500
)
async def cb_end(client, q):
    if not _is_admin_check(q):
        return await q.answer("⛔", show_alert=True)
    try:
        await q.message.delete()
    except Exception:
        pass
    await q.answer("✅")


def _is_admin_check(q):
    try:
        from plugins.broadcast.config import _is_admin
        return q.from_user and _is_admin(q.from_user.id)
    except Exception:
        return False



