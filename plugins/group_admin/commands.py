# ============================================================
# 🏨 DOWNTOWN VILLA — GROUP ADMIN COMMANDS
# ============================================================
#
# Commands available in group / PM:
#   /settings         — open panel
#   /reload           — reload config
#   /add_button       — add result button
#   /list_buttons     — list
#   /remove_button    — remove
#   /clear_buttons    — clear all
#   /set_delete_time  — set auto-delete timer
#   /ban              — ban user
#   /unban            — unban
#   /banlist          — list banned
#   /filter           — add banned word
#   /unfilter         — remove banned word
#   /filters          — list
#   /maintenance      — toggle maintenance
# ============================================================

from __future__ import annotations
import logging
from typing import Any, Dict, List

from pyrogram import Client, filters
from pyrogram.enums import ChatType, ParseMode
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from core import config
from plugins.group_admin import state as S
from utils import fonts as F

logger = logging.getLogger(__name__)


def _is_admin(uid) -> bool:
    try:
        return int(uid) in [int(a) for a in config.ADMINS]
    except Exception:
        return False


async def _is_group_admin(client, chat_id, user_id) -> bool:
    if _is_admin(user_id):
        return True
    try:
        m = await client.get_chat_member(chat_id, user_id)
        st = getattr(m, "status", None)
        st = st.name.lower() if hasattr(st, "name") else str(st).lower()
        return st in ("administrator", "creator", "owner")
    except Exception:
        return False


# ============================================================
# /settings
# ============================================================

@Client.on_message(
    filters.command("settings"),
    group=-8500,
)
async def cmd_settings(client: Client, message: Message):
    if not message.from_user:
        return

    if message.chat.type in (ChatType.GROUP, ChatType.SUPERGROUP):
        if not await _is_group_admin(
            client, message.chat.id, message.from_user.id
        ):
            return await message.reply_text("❌ ᴀᴅᴍɪɴꜱ ᴏɴʟʏ.")

        await S.register_group(
            message.chat.id,
            title=message.chat.title or "",
            username=message.chat.username or "",
        )

        # Offer PM or here
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                f"{F.EMO['lock']} {F.sc('open in pm')}",
                url=f"https://t.me/{(await client.identity()).username}"
                    f"?start=gs:{message.chat.id}",
            )],
            [InlineKeyboardButton(
                f"👥 {F.sc('open here')}",
                callback_data=f"ga:open:{message.chat.id}",
            )],
        ])
        return await message.reply_text(
            "\n".join([
                f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                F.DIV, "",
                f"📌 {F.sc('where to open the settings panel')}",
            ]),
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
        )

    # In PM → list groups (owner only)
    if not _is_admin(message.from_user.id):
        return await message.reply_text("❌ ᴏᴡɴᴇʀ ᴏɴʟʏ.")

    await _show_group_list(message)


async def _show_group_list(message: Message):
    groups = await S.list_groups(limit=10)
    total = len(groups)

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"👥 <b>{F.fb('GROUP MANAGER')}</b>",
        F.DIV, "",
        f"📊 {F.sc('groups')} · <b>{total}</b>",
        "",
        f"📌 {F.sc('tap a group to configure')}",
    ]

    rows = []
    for g in groups:
        gid = g.get("chat_id")
        title = str(g.get("title", gid))[:36]
        rows.append([InlineKeyboardButton(
            f"👥 {title}",
            callback_data=f"ga:open:{gid}",
        )])

    rows.append([InlineKeyboardButton(
        f"{F.EMO['refresh']} {F.sc('refresh')}",
        callback_data="ga:list",
    )])
    rows.append([InlineKeyboardButton(
        f"{F.EMO['cross']} {F.sc('close')}",
        callback_data="ga:close",
    )])

    await message.reply_text(
        "\n".join(lines),
        reply_markup=InlineKeyboardMarkup(rows),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


# ============================================================
# /reload
# ============================================================

@Client.on_message(
    filters.command("reload"),
    group=-8500,
)
async def cmd_reload(client: Client, message: Message):
    if not message.from_user:
        return
    if message.chat.type not in (ChatType.GROUP, ChatType.SUPERGROUP):
        return
    if not await _is_group_admin(client, message.chat.id, message.from_user.id):
        return await message.reply_text("❌ ᴀᴅᴍɪɴꜱ ᴏɴʟʏ.")

    await S.register_group(
        message.chat.id,
        title=message.chat.title or "",
        username=message.chat.username or "",
    )
    await message.reply_text(
        f"{F.EMO['check']} <b>Group reloaded</b>\n"
        f"📌 Use /settings to configure.",
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# /add_button
# ============================================================

@Client.on_message(
    filters.command("add_button") & filters.group,
    group=-8500,
)
async def cmd_add_button(client: Client, message: Message):
    if not message.from_user:
        return
    if not await _is_group_admin(client, message.chat.id, message.from_user.id):
        return await message.reply_text("❌ ᴀᴅᴍɪɴꜱ ᴏɴʟʏ.")

    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2 or "|" not in args[1]:
        return await message.reply_text(
            f"ᴜꜱᴀɢᴇ: <code>/add_button NAME | URL</code>",
            parse_mode=ParseMode.HTML,
        )

    name, url = [p.strip() for p in args[1].split("|", 1)]
    if not name or not url:
        return await message.reply_text("❌ ᴇᴍᴘᴛʏ.")

    cfg = await S.get_config(message.chat.id)
    btns = list(cfg.get("result_buttons") or [])
    if len(btns) >= 8:
        return await message.reply_text("⚠️ ᴍᴀx 8 ʙᴜᴛᴛᴏɴꜱ.")

    btns.append({
        "name": name[:60],
        "url": url,
        "enabled": True,
        "position": len(btns) + 1,
    })
    await S.save_field(message.chat.id, "result_buttons", btns)
    await message.reply_text(
        f"{F.EMO['check']} <b>Button added</b>\n"
        f"📛 {F.sc(name)}\n"
        f"🔗 <code>{url[:60]}</code>",
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# /list_buttons
# ============================================================

@Client.on_message(
    filters.command("list_buttons") & filters.group,
    group=-8500,
)
async def cmd_list_buttons(client: Client, message: Message):
    cfg = await S.get_config(message.chat.id)
    btns = cfg.get("result_buttons") or []

    if not btns:
        return await message.reply_text("⚪ ɴᴏ ʙᴜᴛᴛᴏɴꜱ ʏᴇᴛ.")

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('RESULT BUTTONS')}</b>",
        F.DIV, "",
    ]
    for i, b in enumerate(btns, 1):
        icon = "🟢" if b.get("enabled", True) else "🔴"
        lines.append(
            f"<b>{i:02d}.</b> {icon} {F.sc(str(b.get('name','?'))[:40])}"
        )
        lines.append(f"   <code>{str(b.get('url','?'))[:50]}</code>")

    await message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


# ============================================================
# /remove_button
# ============================================================

@Client.on_message(
    filters.command("remove_button") & filters.group,
    group=-8500,
)
async def cmd_remove_button(client: Client, message: Message):
    if not message.from_user:
        return
    if not await _is_group_admin(client, message.chat.id, message.from_user.id):
        return await message.reply_text("❌ ᴀᴅᴍɪɴꜱ ᴏɴʟʏ.")

    args = (message.text or "").split()
    if len(args) < 2:
        return await message.reply_text(
            "ᴜꜱᴀɢᴇ: <code>/remove_button NUMBER</code>",
            parse_mode=ParseMode.HTML,
        )
    try:
        idx = int(args[1]) - 1
    except ValueError:
        return await message.reply_text("❌ ɪɴᴠᴀʟɪᴅ.")

    cfg = await S.get_config(message.chat.id)
    btns = list(cfg.get("result_buttons") or [])
    if idx < 0 or idx >= len(btns):
        return await message.reply_text("❌ ᴏᴜᴛ ᴏꜰ ʀᴀɴɢᴇ.")

    removed = btns.pop(idx)
    for i, b in enumerate(btns, 1):
        b["position"] = i
    await S.save_field(message.chat.id, "result_buttons", btns)
    await message.reply_text(
        f"🗑️ ʀᴇᴍᴏᴠᴇᴅ: <b>{F.sc(str(removed.get('name','?')))}</b>",
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# /clear_buttons
# ============================================================

@Client.on_message(
    filters.command("clear_buttons") & filters.group,
    group=-8500,
)
async def cmd_clear_buttons(client: Client, message: Message):
    if not message.from_user:
        return
    if not await _is_group_admin(client, message.chat.id, message.from_user.id):
        return await message.reply_text("❌ ᴀᴅᴍɪɴꜱ ᴏɴʟʏ.")

    await S.save_field(message.chat.id, "result_buttons", [])
    await message.reply_text("🗑️ ᴀʟʟ ʙᴜᴛᴛᴏɴꜱ ᴄʟᴇᴀʀᴇᴅ.")


# ============================================================
# /set_delete_time
# ============================================================

@Client.on_message(
    filters.command("set_delete_time") & filters.group,
    group=-8500,
)
async def cmd_set_delete_time(client: Client, message: Message):
    if not message.from_user:
        return
    if not await _is_group_admin(client, message.chat.id, message.from_user.id):
        return await message.reply_text("❌ ᴀᴅᴍɪɴꜱ ᴏɴʟʏ.")

    args = (message.text or "").split()
    if len(args) < 2:
        return await message.reply_text(
            "ᴜꜱᴀɢᴇ: <code>/set_delete_time 600</code> (seconds)\n"
            "ᴇxᴀᴍᴘʟᴇꜱ:\n"
            "• 60 = 1 min\n• 600 = 10 min\n• 1800 = 30 min",
            parse_mode=ParseMode.HTML,
        )
    try:
        secs = int(args[1])
    except ValueError:
        return await message.reply_text("❌ ɪɴᴠᴀʟɪᴅ.")

    if secs < 30:
        return await message.reply_text("⚠️ ᴍɪɴ 30 ꜱᴇᴄᴏɴᴅꜱ.")

    await S.save_field(message.chat.id, "auto_delete.bot_timer", secs)
    await message.reply_text(
        f"✅ ᴀᴜᴛᴏ-ᴅᴇʟᴇᴛᴇ ꜱᴇᴛ ᴛᴏ <b>{secs}s</b>.",
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# BAN / UNBAN / BANLIST
# ============================================================

def _bans_coll():
    try:
        from database import db_registry
        db = db_registry.get_user_db()
        return db["group_bans"] if db is not None else None
    except Exception:
        return None


@Client.on_message(
    filters.command(["ban", "dban"]) & filters.group,
    group=-8500,
)
async def cmd_ban(client: Client, message: Message):
    if not message.from_user:
        return
    if not await _is_group_admin(client, message.chat.id, message.from_user.id):
        return await message.reply_text("❌ ᴀᴅᴍɪɴꜱ ᴏɴʟʏ.")

    # Get target
    target = None
    if message.reply_to_message and message.reply_to_message.from_user:
        target = message.reply_to_message.from_user.id
    else:
        args = (message.text or "").split()
        if len(args) >= 2:
            try:
                target = int(args[1])
            except ValueError:
                pass

    if not target:
        return await message.reply_text(
            "ᴜꜱᴀɢᴇ:\n• Reply to a message + /ban\n"
            "• /ban USER_ID",
            parse_mode=ParseMode.HTML,
        )

    coll = _bans_coll()
    if coll is not None:
        try:
            await coll.update_one(
                {"chat_id": message.chat.id, "user_id": int(target)},
                {"$set": {
                    "chat_id": message.chat.id,
                    "user_id": int(target),
                    "banned_by": message.from_user.id,
                    "banned_at": __import__("time").time(),
                }},
                upsert=True,
            )
        except Exception:
            pass

    # Actually kick from group (optional)
    try:
        await client.ban_chat_member(message.chat.id, int(target))
    except Exception as e:
        logger.debug(f"[GADMIN] ban: {e}")

    await message.reply_text(
        f"🚫 ʙᴀɴɴᴇᴅ <code>{target}</code>",
        parse_mode=ParseMode.HTML,
    )


@Client.on_message(
    filters.command(["unban"]) & filters.group,
    group=-8500,
)
async def cmd_unban(client: Client, message: Message):
    if not message.from_user:
        return
    if not await _is_group_admin(client, message.chat.id, message.from_user.id):
        return await message.reply_text("❌ ᴀᴅᴍɪɴꜱ ᴏɴʟʏ.")

    target = None
    if message.reply_to_message and message.reply_to_message.from_user:
        target = message.reply_to_message.from_user.id
    else:
        args = (message.text or "").split()
        if len(args) >= 2:
            try:
                target = int(args[1])
            except ValueError:
                pass

    if not target:
        return await message.reply_text("ᴜꜱᴀɢᴇ: /unban USER_ID")

    coll = _bans_coll()
    if coll is not None:
        try:
            await coll.delete_one({
                "chat_id": message.chat.id, "user_id": int(target)
            })
        except Exception:
            pass

    try:
        await client.unban_chat_member(message.chat.id, int(target))
    except Exception as e:
        logger.debug(f"[GADMIN] unban: {e}")

    await message.reply_text(
        f"✅ ᴜɴʙᴀɴɴᴇᴅ <code>{target}</code>",
        parse_mode=ParseMode.HTML,
    )


@Client.on_message(
    filters.command("banlist") & filters.group,
    group=-8500,
)
async def cmd_banlist(client: Client, message: Message):
    coll = _bans_coll()
    if coll is None:
        return await message.reply_text("❌ ᴅʙ ᴇʀʀᴏʀ.")

    try:
        cur = coll.find({"chat_id": message.chat.id}).limit(50)
        docs = await cur.to_list(length=50)
    except Exception:
        return await message.reply_text("❌ ꜰᴀɪʟᴇᴅ.")

    if not docs:
        return await message.reply_text("⚪ ɴᴏ ʙᴀɴɴᴇᴅ ᴜꜱᴇʀꜱ.")

    lines = [
        f"{F.EMO['warn']} <b>{F.fb('BANNED USERS')}</b>",
        F.DIV, "",
    ]
    for i, d in enumerate(docs, 1):
        lines.append(f"<b>{i:02d}.</b> <code>{d.get('user_id')}</code>")

    await message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# FILTERS
# ============================================================

@Client.on_message(
    filters.command(["filter", "addfilter"]) & filters.group,
    group=-8500,
)
async def cmd_filter(client: Client, message: Message):
    if not message.from_user:
        return
    if not await _is_group_admin(client, message.chat.id, message.from_user.id):
        return await message.reply_text("❌ ᴀᴅᴍɪɴꜱ ᴏɴʟʏ.")

    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        return await message.reply_text("ᴜꜱᴀɢᴇ: /filter WORD")

    word = args[1].strip().lower()
    if not word:
        return await message.reply_text("❌ ᴇᴍᴘᴛʏ.")

    cfg = await S.get_config(message.chat.id)
    words = list((cfg.get("filters") or {}).get("banned_words") or [])
    if word in words:
        return await message.reply_text("⚠️ ᴀʟʀᴇᴀᴅʏ ᴀᴅᴅᴇᴅ.")

    words.append(word)
    await S.save_field(message.chat.id, "filters.banned_words", words)
    await message.reply_text(
        f"✅ ᴀᴅᴅᴇᴅ: <code>{word}</code>",
        parse_mode=ParseMode.HTML,
    )


@Client.on_message(
    filters.command(["unfilter", "removefilter"]) & filters.group,
    group=-8500,
)
async def cmd_unfilter(client: Client, message: Message):
    if not message.from_user:
        return
    if not await _is_group_admin(client, message.chat.id, message.from_user.id):
        return await message.reply_text("❌ ᴀᴅᴍɪɴꜱ ᴏɴʟʏ.")

    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        return await message.reply_text("ᴜꜱᴀɢᴇ: /unfilter WORD")

    word = args[1].strip().lower()
    cfg = await S.get_config(message.chat.id)
    words = list((cfg.get("filters") or {}).get("banned_words") or [])
    if word not in words:
        return await message.reply_text("⚠️ ɴᴏᴛ ꜰᴏᴜɴᴅ.")
    words.remove(word)
    await S.save_field(message.chat.id, "filters.banned_words", words)
    await message.reply_text(f"🗑️ ʀᴇᴍᴏᴠᴇᴅ: <code>{word}</code>",
                             parse_mode=ParseMode.HTML)


@Client.on_message(
    filters.command("filters") & filters.group,
    group=-8500,
)
async def cmd_filters(client: Client, message: Message):
    cfg = await S.get_config(message.chat.id)
    words = (cfg.get("filters") or {}).get("banned_words") or []

    if not words:
        return await message.reply_text("⚪ ɴᴏ ʙᴀɴɴᴇᴅ ᴡᴏʀᴅꜱ.")

    lines = [
        f"{F.EMO['warn']} <b>{F.fb('BANNED WORDS')}</b>",
        F.DIV, "",
    ]
    for i, w in enumerate(words, 1):
        lines.append(f"<b>{i:02d}.</b> <code>{w}</code>")

    await message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# MAINTENANCE
# ============================================================

@Client.on_message(
    filters.command("maintenance") & filters.private,
    group=-8500,
)
async def cmd_maintenance(client: Client, message: Message):
    if not message.from_user or not _is_admin(message.from_user.id):
        return await message.reply_text("❌ ᴀᴅᴍɪɴ ᴏɴʟʏ.")

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or parts[1].strip().lower() not in (
        "on", "off", "true", "false"
    ):
        return await message.reply_text(
            "ᴜꜱᴀɢᴇ: <code>/maintenance on</code> or <code>off</code>",
            parse_mode=ParseMode.HTML,
        )

    enable = parts[1].strip().lower() in ("on", "true")
    try:
        from database import db_registry
        db = db_registry.get_system_db()
        await db["bot_settings"].update_one(
            {"_id": "maintenance"},
            {"$set": {"enabled": enable}},
            upsert=True,
        )
        config.MAINTENANCE_MODE = enable
        await message.reply_text(
            f"{F.EMO['check']} ᴍᴀɪɴᴛᴇɴᴀɴᴄᴇ · "
            f"<b>{'ᴏɴ' if enable else 'ᴏꜰꜰ'}</b>",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        await message.reply_text(f"❌ {e}")


__all__ = [
    "cmd_settings", "cmd_reload", "cmd_add_button", "cmd_list_buttons",
    "cmd_remove_button", "cmd_clear_buttons", "cmd_set_delete_time",
    "cmd_ban", "cmd_unban", "cmd_banlist",
    "cmd_filter", "cmd_unfilter", "cmd_filters", "cmd_maintenance",
]
