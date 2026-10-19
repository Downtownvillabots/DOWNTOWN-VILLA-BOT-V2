"""Private, non-persistent one-time broadcasts from a replied-to message."""

from __future__ import annotations

import asyncio
import logging
import random
import secrets
import time
from typing import Any, Dict, List, Optional

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.errors import FloodWait
from pyrogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from plugins.broadcast import database as DB
from plugins.broadcast import templates as TPL
from plugins.broadcast.config import (
    BROADCAST_BATCH_SIZE,
    BROADCAST_CONCURRENCY,
    DEFAULT_DELAY,
    DIV,
    _esc,
    _is_admin,
)

logger = logging.getLogger(__name__)
_PREFIX = "otb"
_TTL = 900
_SESSIONS: Dict[str, Dict[str, Any]] = {}


def _button(text: str, data: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(text, callback_data=data)


def _key(rows: List[List[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(rows)


def _menu_markup(sid: str) -> InlineKeyboardMarkup:
    return _key([
        [_button("📢 CHANNELS", f"{_PREFIX}:{sid}:dest:channels")],
        [_button("👥 ALL GROUPS", f"{_PREFIX}:{sid}:dest:groups")],
        [_button("👤 ALL USERS", f"{_PREFIX}:{sid}:dest:users")],
        [_button("❌ CANCEL", f"{_PREFIX}:{sid}:cancel")],
    ])


def _channel_markup(
    sid: str, channels: List[Dict[str, Any]]
) -> InlineKeyboardMarkup:
    rows = [[_button("📢 SEND TO ALL CHANNELS", f"{_PREFIX}:{sid}:allch")]]
    for channel in channels:
        chat_id = channel.get("chat_id")
        if chat_id is None:
            continue
        title = str(channel.get("title") or chat_id)[:45]
        rows.append([
            _button(f"📣 {title}", f"{_PREFIX}:{sid}:ch:{int(chat_id)}")
        ])
    rows.append([_button("◀️ BACK", f"{_PREFIX}:{sid}:home")])
    rows.append([_button("❌ CANCEL", f"{_PREFIX}:{sid}:cancel")])
    return _key(rows)


def _caption_markup(sid: str, channel_caption_available: bool) -> InlineKeyboardMarkup:
    rows = [
        [_button("🎲 RANDOM CAPTION", f"{_PREFIX}:{sid}:cap:random")],
        [_button("📄 FILE'S OWN CAPTION", f"{_PREFIX}:{sid}:cap:own")],
        [_button("🌐 GLOBAL CAPTION", f"{_PREFIX}:{sid}:cap:global")],
    ]
    if channel_caption_available:
        rows.append([
            _button("📢 CHANNEL CAPTION", f"{_PREFIX}:{sid}:cap:channel")
        ])
    rows += [
        [_button("✏️ WRITE ONE-TIME CAPTION", f"{_PREFIX}:{sid}:cap:custom")],
        [_button("◀️ CHANGE DESTINATION", f"{_PREFIX}:{sid}:home")],
        [_button("❌ CANCEL", f"{_PREFIX}:{sid}:cancel")],
    ]
    return _key(rows)


def _preview_markup(sid: str, button_count: int) -> InlineKeyboardMarkup:
    return _key([
        [_button("🚀 SEND ONCE", f"{_PREFIX}:{sid}:send")],
        [_button(f"🔘 ADD ONE-TIME BUTTON ({button_count})",
                 f"{_PREFIX}:{sid}:button")],
        [_button("📝 CHANGE CAPTION", f"{_PREFIX}:{sid}:captions")],
        [_button("🎯 CHANGE DESTINATION", f"{_PREFIX}:{sid}:home")],
        [_button("❌ CANCEL", f"{_PREFIX}:{sid}:cancel")],
    ])


def _state(sid: str, user_id: int) -> Optional[Dict[str, Any]]:
    data = _SESSIONS.get(sid)
    if not data:
        return None
    if data["expires"] < time.time():
        _SESSIONS.pop(sid, None)
        return None
    if data["user_id"] != int(user_id):
        return None
    return data


def _set_prompt(data: Dict[str, Any], mode: str, message_id: int) -> None:
    data["input_mode"] = mode
    data["prompt_message_id"] = int(message_id)


async def _get_source(client: Client, data: Dict[str, Any]) -> Optional[Message]:
    try:
        source = await client.get_messages(
            int(data["source_chat_id"]), int(data["source_message_id"])
        )
    except Exception:
        return None
    if not source or source.empty:
        return None
    return source


def _targets_caption_choice(data: Dict[str, Any]) -> bool:
    return data.get("destination") == "channels"


def _supports_caption(message: Message) -> bool:
    return any(
        getattr(message, media_type, None)
        for media_type in (
            "animation", "audio", "document", "photo", "video", "voice",
        )
    )


async def _render_preview(client: Client, sid: str, data: Dict[str, Any]) -> str:
    source = await _get_source(client, data)
    if not source:
        return "⚠️ The replied-to message could not be found."

    mode = data.get("caption_mode")
    caption = ""
    if mode == "own":
        caption = TPL.clean_caption(source.caption or source.text or "")
        caption = _esc(caption) if caption else "<i>(no file caption)</i>"
    elif mode == "custom":
        caption = TPL.build_caption(source, data.get("custom_caption") or "")
    elif mode == "channel":
        caption = "<i>Each selected channel's saved caption will be used.</i>"
    elif mode == "random":
        caption = (
            "<i>A caption will be randomly selected for each recipient "
            "from the available file, global, channel, and custom captions.</i>"
        )
    else:
        caption = TPL.build_caption(source, await DB.get_global_caption())

    destination = data.get("destination_label") or "—"
    original = source.caption or source.text or "Message"
    return "\n".join([
        "🏨 <b>ONE-TIME BROADCAST</b>",
        DIV,
        "",
        f"📨 <b>Source:</b> <code>{_esc(original[:100])}</code>",
        f"🎯 <b>Destination:</b> {_esc(destination)}",
        f"📝 <b>Caption mode:</b> {_esc(mode or '—')}",
        f"🔘 <b>One-time buttons:</b> {len(data.get('buttons') or [])}",
        "",
        caption[:1800],
    ])[:3800]


async def _show_preview(
    client: Client, chat_id: int, message_id: int, sid: str,
    data: Dict[str, Any],
) -> None:
    text = await _render_preview(client, sid, data)
    await client.edit_message_text(
        chat_id=chat_id,
        message_id=message_id,
        text=text,
        reply_markup=_preview_markup(sid, len(data.get("buttons") or [])),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


@Client.on_message(
    filters.private & filters.command("onetimebroadcast"), group=-490
)
async def onetimebroadcast_command(client: Client, message: Message) -> None:
    if not message.from_user or not _is_admin(message.from_user.id):
        return await message.reply_text("⛔ Admins only.")
    source = message.reply_to_message
    if not source:
        return await message.reply_text(
            "Reply to the file, image, or message you want to broadcast, "
            "then send <code>/onetimebroadcast</code>.",
            parse_mode=ParseMode.HTML,
        )

    now = time.time()
    for old_sid, old_data in list(_SESSIONS.items()):
        if (
            old_data.get("user_id") == int(message.from_user.id)
            or old_data.get("expires", 0) < now
        ):
            _SESSIONS.pop(old_sid, None)
    sid = secrets.token_hex(5)
    _SESSIONS[sid] = {
        "user_id": int(message.from_user.id),
        "source_chat_id": int(source.chat.id),
        "source_message_id": int(source.id),
        "created": now,
        "expires": now + _TTL,
        "destination": None,
        "destination_label": None,
        "channel_id": None,
        "caption_mode": None,
        "custom_caption": None,
        "buttons": [],
        "input_mode": None,
    }
    await message.reply_text(
        "🏨 <b>ONE-TIME BROADCAST</b>\n"
        f"{DIV}\n\nChoose where to send the replied-to message.",
        reply_markup=_menu_markup(sid),
        parse_mode=ParseMode.HTML,
    )


@Client.on_callback_query(
    filters.regex(r"^otb:([a-f0-9]+):(.+)$"), group=-490
)
async def onetimebroadcast_callback(client: Client, q: CallbackQuery) -> None:
    if not q.from_user or not _is_admin(q.from_user.id):
        return await q.answer("⛔ Admins only.", show_alert=True)
    sid, action = q.matches[0].group(1), q.matches[0].group(2)
    data = _state(sid, q.from_user.id)
    if not data:
        return await q.answer("⏱️ This one-time session expired.", show_alert=True)
    if data.get("status") == "sending":
        return await q.answer("This broadcast is already running.")

    if action == "cancel":
        _SESSIONS.pop(sid, None)
        await q.message.edit_text("❌ One-time broadcast cancelled.")
        return await q.answer("Cancelled")

    if action == "home":
        data.update(
            destination=None, destination_label=None,
            channel_id=None, caption_mode=None,
        )
        await q.message.edit_text(
            "🏨 <b>ONE-TIME BROADCAST</b>\n"
            f"{DIV}\n\nChoose where to send the replied-to message.",
            reply_markup=_menu_markup(sid),
            parse_mode=ParseMode.HTML,
        )
        return await q.answer()

    if action == "dest:channels":
        channels = [
            c for c in await DB.get_saved_channels()
            if c.get("enabled", True) and c.get("chat_id") is not None
        ]
        if not channels:
            return await q.answer("No saved channels.", show_alert=True)
        await q.message.edit_text(
            "📢 <b>Choose a channel</b>",
            reply_markup=_channel_markup(sid, channels),
            parse_mode=ParseMode.HTML,
        )
        return await q.answer()

    if action in ("dest:groups", "dest:users"):
        target_type = action.split(":", 1)[1]
        targets = (
            await DB.get_all_groups()
            if target_type == "groups"
            else await DB.get_all_users()
        )
        if not targets:
            return await q.answer(f"No {target_type} available.", show_alert=True)
        data.update(
            destination=target_type,
            destination_label=f"All {target_type} ({len(targets)})",
            channel_id=None,
        )
        return await _open_caption_picker(q, sid, data)

    if action == "allch":
        channels = [
            c for c in await DB.get_saved_channels()
            if c.get("enabled", True) and c.get("chat_id") is not None
        ]
        if not channels:
            return await q.answer("No enabled channels.", show_alert=True)
        data.update(
            destination="channels",
            destination_label=f"All channels ({len(channels)})",
            channel_id="all",
        )
        return await _open_caption_picker(q, sid, data)

    if action.startswith("ch:"):
        try:
            chat_id = int(action.split(":", 1)[1])
        except ValueError:
            return await q.answer("Invalid channel.", show_alert=True)
        channel = await DB.get_channel(chat_id)
        if not channel or not channel.get("enabled", True):
            return await q.answer("Channel is unavailable.", show_alert=True)
        data.update(
            destination="channels",
            destination_label=channel.get("title") or str(chat_id),
            channel_id=chat_id,
        )
        return await _open_caption_picker(q, sid, data)

    if action == "captions":
        return await _open_caption_picker(q, sid, data)

    if action.startswith("cap:"):
        mode = action.split(":", 1)[1]
        if mode == "custom":
            data["input_mode"] = "caption"
            prompt = await q.message.edit_text(
                "✏️ Send your one-time caption now. "
                "You can use <code>{file_name}</code>, "
                "<code>{file_size}</code>, <code>{year}</code>, "
                "and <code>{file_caption}</code>. "
                "This caption is not saved.",
                reply_markup=_key([[
                    _button("❌ CANCEL", f"{_PREFIX}:{sid}:cancel")
                ]]),
                parse_mode=ParseMode.HTML,
            )
            _set_prompt(data, "caption", prompt.id)
            return await q.answer()
        if mode not in {"random", "own", "global", "channel"}:
            return await q.answer("Invalid caption mode.", show_alert=True)
        data["caption_mode"] = mode
        await _show_preview(
            client, q.message.chat.id, q.message.id, sid, data
        )
        return await q.answer()

    if action == "button":
        if len(data.get("buttons") or []) >= 8:
            return await q.answer("Maximum 8 one-time buttons.", show_alert=True)
        data["input_mode"] = "button"
        prompt = await q.message.edit_text(
            "🔘 Send a temporary button as <code>Name | URL</code>.\n"
            "Example: <code>Open channel | https://t.me/example</code>\n"
            "This button is only used for this broadcast.",
            reply_markup=_key([[
                _button("❌ CANCEL", f"{_PREFIX}:{sid}:cancel")
            ]]),
            parse_mode=ParseMode.HTML,
        )
        _set_prompt(data, "button", prompt.id)
        return await q.answer()

    if action == "send":
        if not data.get("destination") or not data.get("caption_mode"):
            return await q.answer("Choose a destination and caption first.", show_alert=True)
        data["input_mode"] = None
        data["status"] = "sending"
        await q.answer("Starting one-time broadcast…")
        asyncio.create_task(
            _execute_once(client, q.message.chat.id, q.message.id, sid, data)
        )
        return

    return await q.answer("Unknown action.", show_alert=True)


async def _open_caption_picker(
    q: CallbackQuery, sid: str, data: Dict[str, Any]
) -> None:
    channel_caption_available = _targets_caption_choice(data)
    await q.message.edit_text(
        "📝 <b>Choose a one-time caption</b>\n"
        f"{DIV}\n\n"
        f"🎯 Destination: {_esc(data.get('destination_label'))}\n"
        "Random selects a caption separately for each recipient. "
        "One-time changes are never saved.",
        reply_markup=_caption_markup(sid, channel_caption_available),
        parse_mode=ParseMode.HTML,
    )
    await q.answer()


def _normalize_button_url(url: str) -> Optional[str]:
    url = url.strip()
    if url.startswith("@"):
        return f"https://t.me/{url[1:]}"
    if url.startswith(("http://", "https://", "tg://")):
        return url
    if "." in url and " " not in url:
        return f"https://{url}"
    return None


@Client.on_message(
    filters.private & filters.text & ~filters.regex(r"^/"), group=-460
)
async def onetimebroadcast_text_input(client: Client, message: Message) -> None:
    if not message.from_user or not _is_admin(message.from_user.id):
        return
    text = (message.text or "").strip()
    pending = next(
        (
            (sid, data) for sid, data in _SESSIONS.items()
            if data.get("user_id") == int(message.from_user.id)
            and data.get("input_mode")
            and data.get("expires", 0) >= time.time()
        ),
        None,
    )
    if not pending:
        return
    sid, data = pending
    mode = data.get("input_mode")

    if mode == "caption":
        if not text:
            return await message.reply_text("Caption cannot be empty.")
        if len(text) > 1024:
            return await message.reply_text("Caption must be 1024 characters or fewer.")
        data["custom_caption"] = text
        data["caption_mode"] = "custom"
    elif mode == "button":
        if "|" not in text:
            return await message.reply_text(
                "Use the format <code>Name | URL</code>.",
                parse_mode=ParseMode.HTML,
            )
        name, raw_url = [part.strip() for part in text.split("|", 1)]
        url = _normalize_button_url(raw_url)
        if not name or not url:
            return await message.reply_text("Button name or URL is invalid.")
        data.setdefault("buttons", []).append(
            {"name": name[:60], "url": url}
        )
    else:
        return

    data["input_mode"] = None
    prompt_id = data.pop("prompt_message_id", None)
    if prompt_id:
        try:
            await _show_preview(
                client, message.chat.id, int(prompt_id), sid, data
            )
        except Exception:
            await message.reply_text(
                "Could not update the one-time broadcast preview. "
                "Run /onetimebroadcast again."
            )
            _SESSIONS.pop(sid, None)


def _caption_for_target(
    source: Message,
    data: Dict[str, Any],
    channel: Optional[Dict[str, Any]],
) -> str:
    mode = data["caption_mode"]
    global_template = data.get("global_caption") or ""
    own = TPL.clean_caption(source.caption or source.text or "")

    if mode == "own":
        return own
    if mode == "custom":
        return TPL.build_caption(source, data.get("custom_caption") or "")
    if mode == "channel":
        template = (
            channel.get("caption")
            if channel and channel.get("caption") is not None
            else global_template
        )
        return TPL.build_caption(source, template)
    if mode == "random":
        candidates = [TPL.build_caption(source, global_template)]
        if own:
            candidates.append(own)
        if channel and channel.get("caption") is not None:
            candidates.append(TPL.build_caption(source, channel["caption"]))
        if data.get("custom_caption"):
            candidates.append(
                TPL.build_caption(source, data["custom_caption"])
            )
        return random.choice(candidates)
    return TPL.build_caption(source, global_template)


async def _execute_once(
    client: Client, chat_id: int, message_id: int,
    sid: str, data: Dict[str, Any],
) -> None:
    source = await _get_source(client, data)
    if not source:
        await client.edit_message_text(
            chat_id, message_id, "⚠️ The replied-to message is unavailable."
        )
        _SESSIONS.pop(sid, None)
        return

    destination = data["destination"]
    if destination == "channels":
        channels = [
            c for c in await DB.get_saved_channels()
            if c.get("enabled", True) and c.get("chat_id") is not None
        ]
        if data.get("channel_id") != "all":
            channels = [
                ch for ch in channels
                if int(ch["chat_id"]) == int(data["channel_id"])
            ]
        targets = [int(ch["chat_id"]) for ch in channels]
        channel_by_id = {int(ch["chat_id"]): ch for ch in channels}
        kind = "one_time_channels"
    elif destination == "groups":
        targets = await DB.get_all_groups()
        channel_by_id = {}
        kind = "one_time_groups"
    else:
        targets = await DB.get_all_users()
        channel_by_id = {}
        kind = "one_time_users"

    targets = list(dict.fromkeys(int(target) for target in targets if target))
    if not targets:
        await client.edit_message_text(
            chat_id, message_id, "⚠️ There are no available targets."
        )
        _SESSIONS.pop(sid, None)
        return

    data["global_caption"] = await DB.get_global_caption()
    global_buttons = await DB.get_global_buttons()
    total = len(targets)
    sent_count = failed_count = 0
    await client.edit_message_text(
        chat_id,
        message_id,
        f"🚀 <b>ONE-TIME BROADCAST STARTED</b>\n{DIV}\n\n"
        f"📤 Sending to <b>{total}</b> targets…",
        parse_mode=ParseMode.HTML,
    )

    semaphore = asyncio.Semaphore(BROADCAST_CONCURRENCY)

    async def send_one(target: int) -> bool:
        async with semaphore:
            channel = channel_by_id.get(target)
            caption = _caption_for_target(source, data, channel)
            buttons = (
                list(channel.get("buttons") or [])
                if channel and channel.get("buttons") is not None
                else list(global_buttons)
            )
            buttons.extend(data.get("buttons") or [])
            markup = TPL.build_buttons_kb(buttons)

            async def deliver() -> None:
                if _supports_caption(source):
                    await client.copy_message(
                        chat_id=target,
                        from_chat_id=source.chat.id,
                        message_id=source.id,
                        caption=caption,
                        reply_markup=markup,
                    )
                elif source.media:
                    await client.copy_message(
                        chat_id=target,
                        from_chat_id=source.chat.id,
                        message_id=source.id,
                        reply_markup=markup,
                    )
                else:
                    await client.send_message(
                        chat_id=target,
                        text=caption,
                        reply_markup=markup,
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=True,
                    )

            try:
                await deliver()
            except FloodWait as e:
                await asyncio.sleep(max(1, int(e.value)) + 2)
                try:
                    await deliver()
                except Exception as retry_error:
                    logger.warning(
                        "[ONE-TIME-BROADCAST] target %s retry failed: %s: %s",
                        target, type(retry_error).__name__, retry_error,
                    )
                    return False
            except Exception as e:
                logger.warning(
                    "[ONE-TIME-BROADCAST] target %s failed: %s: %s",
                    target, type(e).__name__, e,
                )
                return False
            await asyncio.sleep(DEFAULT_DELAY)
            return True

    try:
        for offset in range(0, total, BROADCAST_BATCH_SIZE):
            results = await asyncio.gather(
                *(send_one(target) for target in targets[offset:offset + BROADCAST_BATCH_SIZE])
            )
            sent_count += sum(results)
            failed_count += len(results) - sum(results)
            await client.edit_message_text(
                chat_id,
                message_id,
                f"🚀 <b>ONE-TIME BROADCAST</b>\n{DIV}\n\n"
                f"📊 Progress: <b>{min(offset + len(results), total)}/{total}</b>\n"
                f"✅ Sent: <b>{sent_count}</b>\n"
                f"❌ Failed: <b>{failed_count}</b>",
                parse_mode=ParseMode.HTML,
            )
    except Exception:
        logger.exception("[ONE-TIME-BROADCAST] broadcast failed")
        _SESSIONS.pop(sid, None)
        await client.edit_message_text(
            chat_id,
            message_id,
            "⚠️ One-time broadcast stopped after an internal error.",
        )
        return

    await client.edit_message_text(
        chat_id,
        message_id,
        f"✅ <b>ONE-TIME BROADCAST COMPLETE</b>\n{DIV}\n\n"
        f"🎯 Targets: <b>{total}</b>\n"
        f"📨 Sent: <b>{sent_count}</b>\n"
        f"❌ Failed: <b>{failed_count}</b>",
        parse_mode=ParseMode.HTML,
    )
    await DB.log_broadcast({
        "kind": kind,
        "total": total,
        "sent": sent_count,
        "failed": failed_count,
        "blocked": 0,
        "deleted": 0,
        "autodelete_seconds": 0,
    })
    _SESSIONS.pop(sid, None)
