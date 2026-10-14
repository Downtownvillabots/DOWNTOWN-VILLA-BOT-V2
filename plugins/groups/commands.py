# ============================================================
# 🏨 DOWNTOWN VILLA — GROUPS COMMANDS
# ============================================================
#
# Slash commands available in groups and PM.
#
# In a group:
#   /settings              → open settings panel (offer PM or here)
#   /reload                → re-register group + reload cache
#   /add_button Name | URL → add result button
#   /list_buttons          → list result buttons
#   /remove_button N       → remove button by number
#   /clear_buttons         → clear all result buttons
#   /set_delete_time SECS  → set bot message auto-delete timer
#   /ban                   → ban user (reply or /ban USER_ID)
#   /unban                 → unban user
#   /banlist               → list banned users
#   /filter WORD           → add banned word
#   /unfilter WORD         → remove banned word
#   /filters               → list banned words
#
# In PM (bot admin only):
#   /settings              → list connected groups
#   /maintenance on|off    → toggle maintenance mode
#
# ============================================================

from __future__ import annotations

import io
import json
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from pyrogram import Client, filters
from pyrogram.enums import ChatType, ParseMode
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from core import config
from plugins.groups import state as S
from plugins.groups import router as R
from utils import fonts as F

logger = logging.getLogger(__name__)


# ============================================================
# SECTION 1 — AUTH HELPERS
# ============================================================

def _is_bot_admin(uid: int) -> bool:
    try:
        return int(uid) in [int(a) for a in config.ADMINS]
    except Exception:
        return False


async def _is_group_admin(
    client: Client, chat_id: int, user_id: int,
) -> bool:
    if _is_bot_admin(user_id):
        return True
    try:
        m = await client.get_chat_member(chat_id, user_id)
        st = getattr(m, "status", None)
        st = st.name.lower() if hasattr(st, "name") else str(st).lower()
        return st in ("administrator", "creator", "owner")
    except Exception:
        return False


def _is_group(chat_type) -> bool:
    return chat_type in (ChatType.GROUP, ChatType.SUPERGROUP)


# ============================================================
# SECTION 2 — /settings
# ============================================================

@Client.on_message(
    filters.command("settings"),
    group=-8500,
)
async def cmd_settings(client: Client, message: Message):
    if not message.from_user:
        return

    # ── In a group ──
    if _is_group(message.chat.type):
        if not await _is_group_admin(
            client, message.chat.id, message.from_user.id,
        ):
            return await message.reply_text(
                f"{F.EMO['cross']} {F.sc('admins only')}",
                parse_mode=ParseMode.HTML,
            )

        await S.register_group(
            message.chat.id,
            title=message.chat.title or "",
            username=message.chat.username or "",
        )

        # Offer PM or here
        try:
            me = await client.identity()
            bot_username = me.username or ""
        except Exception:
            try:
                me = await client.get_me()
                bot_username = me.username or ""
            except Exception:
                bot_username = ""

        rows: List[List[InlineKeyboardButton]] = []
        if bot_username:
            rows.append([InlineKeyboardButton(
                f"💬 {F.sc('open in pm')}",
                url=f"https://t.me/{bot_username}?start=gs:{message.chat.id}",
            )])
        rows.append([InlineKeyboardButton(
            f"👥 {F.sc('open here')}",
            callback_data=f"ga:open:{message.chat.id}",
        )])

        return await message.reply_text(
            "\n".join([
                f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                f"{F.EMO['gear']} <b>{F.fb('GROUP SETTINGS')}</b>",
                F.DIV, "",
                f"📌 {F.sc('where to open the settings panel')}",
            ]),
            reply_markup=InlineKeyboardMarkup(rows),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )

    # ── In PM ──
    if not _is_bot_admin(message.from_user.id):
        return await message.reply_text(
            f"{F.EMO['cross']} {F.sc('bot admins only')}",
            parse_mode=ParseMode.HTML,
        )

    await _show_group_list(client, message)


async def _build_group_list() -> Tuple[str, InlineKeyboardMarkup]:
    """Build the connected-groups list text + keyboard."""
    groups = await S.list_groups(limit=20)
    total = await S.count_groups()

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"👥 <b>{F.fb('CONNECTED GROUPS')}</b>",
        F.DIV, "",
        f"📊 {F.sc('total')} · <b>{total}</b>",
        "",
    ]

    rows: List[List[InlineKeyboardButton]] = []
    if not groups:
        lines.append(f"⚪ {F.sc('no groups registered yet')}")
        lines.append("")
        lines.append(f"📌 {F.sc('add bot to a group + /settings there')}")
    else:
        for i, g in enumerate(groups, 1):
            cid = g.get("chat_id")
            title = str(g.get("title") or cid)[:40]
            lines.append(f"<b>{i:02d}.</b> {F.sc(title)}")
            lines.append(f"   <code>{cid}</code>")

            rows.append([InlineKeyboardButton(
                f"👥 {title[:36]}",
                callback_data=f"ga:open:{cid}",
            )])

    rows.append([InlineKeyboardButton(
        f"{F.EMO['refresh']} {F.sc('refresh')}",
        callback_data="ga:list",
    )])
    rows.append([InlineKeyboardButton(
        f"{F.EMO['cross']} {F.sc('close')}",
        callback_data="ga:close",
    )])

    return "\n".join(lines)[:4000], InlineKeyboardMarkup(rows)


async def _show_group_list(client: Client, message: Message) -> None:
    """Reply with the connected-groups list."""
    text, kb = await _build_group_list()
    await message.reply_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )

# ============================================================
# SECTION 3 — /reload
# ============================================================

@Client.on_message(
    filters.command("reload"),
    group=-8500,
)
async def cmd_reload(client: Client, message: Message):
    if not message.from_user:
        return
    if not _is_group(message.chat.type):
        return

    if not await _is_group_admin(
        client, message.chat.id, message.from_user.id,
    ):
        return await message.reply_text(
            f"{F.EMO['cross']} {F.sc('admins only')}",
            parse_mode=ParseMode.HTML,
        )

    await S.register_group(
        message.chat.id,
        title=message.chat.title or "",
        username=message.chat.username or "",
    )

    await message.reply_text(
        "\n".join([
            f"{F.EMO['check']} <b>{F.fb('GROUP RELOADED')}</b>",
            F.DIV, "",
            f"📌 {F.sc('use /settings to configure')}",
        ]),
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# SECTION 4 — BUTTON COMMANDS
# ============================================================

@Client.on_message(
    filters.command("add_button") & filters.group,
    group=-8500,
)
async def cmd_add_button(client: Client, message: Message):
    if not message.from_user:
        return
    if not await _is_group_admin(
        client, message.chat.id, message.from_user.id,
    ):
        return await message.reply_text(
            f"{F.EMO['cross']} {F.sc('admins only')}",
            parse_mode=ParseMode.HTML,
        )

    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2 or "|" not in args[1]:
        return await message.reply_text(
            f"ᴜꜱᴀɢᴇ: <code>/add_button NAME | URL</code>",
            parse_mode=ParseMode.HTML,
        )

    name, url = [p.strip() for p in args[1].split("|", 1)]
    if not name or not url:
        return await message.reply_text("❌ empty")

    # Normalize URL
    if url.startswith("@"):
        url = f"https://t.me/{url[1:]}"
    elif not (url.startswith("http://")
              or url.startswith("https://")
              or url.startswith("tg://")):
        if "." in url and " " not in url:
            url = f"https://{url}"
        else:
            return await message.reply_text("❌ invalid URL")

    cfg = await S.get_config(message.chat.id)
    btns = list(cfg.get("result_buttons") or [])
    if len(btns) >= 8:
        return await message.reply_text("⚠️ max 8 buttons")

    btns.append({
        "name": name[:60],
        "url": url,
        "enabled": True,
        "position": len(btns) + 1,
    })
    await S.save_field(message.chat.id, "result_buttons", btns)

    await message.reply_text(
        "\n".join([
            f"{F.EMO['check']} <b>{F.fb('BUTTON ADDED')}</b>",
            F.DIV, "",
            f"📛 {F.sc(name)}",
            f"🔗 <code>{url[:60]}</code>",
            "",
            f"📊 {F.sc('total')} · <b>{len(btns)}</b>",
        ]),
        parse_mode=ParseMode.HTML,
    )


@Client.on_message(
    filters.command("list_buttons") & filters.group,
    group=-8500,
)
async def cmd_list_buttons(client: Client, message: Message):
    cfg = await S.get_config(message.chat.id)
    btns = cfg.get("result_buttons") or []

    if not btns:
        return await message.reply_text("⚪ no buttons yet")

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('RESULT BUTTONS')}</b>",
        F.DIV, "",
    ]
    for i, b in enumerate(btns, 1):
        icon = "🟢" if b.get("enabled", True) else "🔴"
        lines.append(
            f"<b>{i:02d}.</b> {icon} {F.sc(str(b.get('name', '?'))[:40])}"
        )
        lines.append(f"   <code>{str(b.get('url', '?'))[:50]}</code>")

    await message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


@Client.on_message(
    filters.command("remove_button") & filters.group,
    group=-8500,
)
async def cmd_remove_button(client: Client, message: Message):
    if not message.from_user:
        return
    if not await _is_group_admin(
        client, message.chat.id, message.from_user.id,
    ):
        return await message.reply_text(
            f"{F.EMO['cross']} {F.sc('admins only')}",
            parse_mode=ParseMode.HTML,
        )

    args = (message.text or "").split()
    if len(args) < 2:
        return await message.reply_text(
            "ᴜꜱᴀɢᴇ: <code>/remove_button NUMBER</code>",
            parse_mode=ParseMode.HTML,
        )

    try:
        idx = int(args[1]) - 1
    except ValueError:
        return await message.reply_text("❌ invalid number")

    cfg = await S.get_config(message.chat.id)
    btns = list(cfg.get("result_buttons") or [])
    if idx < 0 or idx >= len(btns):
        return await message.reply_text("❌ out of range")

    removed = btns.pop(idx)
    for i, b in enumerate(btns, 1):
        b["position"] = i
    await S.save_field(message.chat.id, "result_buttons", btns)

    await message.reply_text(
        f"🗑️ ʀᴇᴍᴏᴠᴇᴅ: <b>{F.sc(str(removed.get('name', '?')))}</b>",
        parse_mode=ParseMode.HTML,
    )


@Client.on_message(
    filters.command("clear_buttons") & filters.group,
    group=-8500,
)
async def cmd_clear_buttons(client: Client, message: Message):
    if not message.from_user:
        return
    if not await _is_group_admin(
        client, message.chat.id, message.from_user.id,
    ):
        return await message.reply_text(
            f"{F.EMO['cross']} {F.sc('admins only')}",
            parse_mode=ParseMode.HTML,
        )

    await S.save_field(message.chat.id, "result_buttons", [])
    await message.reply_text(
        f"🗑️ {F.sc('all buttons cleared')}",
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# SECTION 5 — /set_delete_time
# ============================================================

@Client.on_message(
    filters.command("set_delete_time") & filters.group,
    group=-8500,
)
async def cmd_set_delete_time(client: Client, message: Message):
    if not message.from_user:
        return
    if not await _is_group_admin(
        client, message.chat.id, message.from_user.id,
    ):
        return await message.reply_text(
            f"{F.EMO['cross']} {F.sc('admins only')}",
            parse_mode=ParseMode.HTML,
        )

    args = (message.text or "").split()
    if len(args) < 2:
        return await message.reply_text(
            "\n".join([
                "ᴜꜱᴀɢᴇ: <code>/set_delete_time 600</code>",
                "",
                "ᴇxᴀᴍᴘʟᴇꜱ:",
                "• <code>60</code> = 1 min",
                "• <code>600</code> = 10 min",
                "• <code>1800</code> = 30 min",
                "• <code>0</code> = disable auto-delete",
            ]),
            parse_mode=ParseMode.HTML,
        )

    try:
        secs = int(args[1])
    except ValueError:
        return await message.reply_text("❌ invalid number")

    if secs < 0:
        return await message.reply_text("❌ must be ≥ 0")

    if secs == 0:
        await S.save_field(
            message.chat.id, "auto_delete.bot_messages", False,
        )
        await message.reply_text(
            f"🔴 {F.sc('auto-delete disabled')}",
            parse_mode=ParseMode.HTML,
        )
        return

    if secs < 30:
        return await message.reply_text("⚠️ minimum 30 seconds")

    await S.save_field(
        message.chat.id, "auto_delete.bot_messages", True,
    )
    await S.save_field(
        message.chat.id, "auto_delete.bot_timer", secs,
    )
    await message.reply_text(
        f"✅ ᴀᴜᴛᴏ-ᴅᴇʟᴇᴛᴇ · <b>{secs}s</b>",
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# SECTION 6 — BAN / UNBAN / BANLIST
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
    if not await _is_group_admin(
        client, message.chat.id, message.from_user.id,
    ):
        return await message.reply_text(
            f"{F.EMO['cross']} {F.sc('admins only')}",
            parse_mode=ParseMode.HTML,
        )

    target: Optional[int] = None

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
            "\n".join([
                "ᴜꜱᴀɢᴇ:",
                "• Reply to a message + <code>/ban</code>",
                "• <code>/ban USER_ID</code>",
            ]),
            parse_mode=ParseMode.HTML,
        )

    # Save to DB
    coll = _bans_coll()
    if coll is not None:
        try:
            await coll.update_one(
                {"chat_id": message.chat.id, "user_id": int(target)},
                {"$set": {
                    "chat_id": message.chat.id,
                    "user_id": int(target),
                    "banned_by": message.from_user.id,
                    "banned_at": time.time(),
                }},
                upsert=True,
            )
        except Exception as e:
            logger.debug(f"[GROUPS] ban save: {e}")

    # Kick from group (best-effort)
    try:
        await client.ban_chat_member(message.chat.id, int(target))
    except Exception as e:
        logger.debug(f"[GROUPS] ban: {e}")

    await message.reply_text(
        f"🚫 {F.sc('banned')} <code>{target}</code>",
        parse_mode=ParseMode.HTML,
    )


@Client.on_message(
    filters.command("unban") & filters.group,
    group=-8500,
)
async def cmd_unban(client: Client, message: Message):
    if not message.from_user:
        return
    if not await _is_group_admin(
        client, message.chat.id, message.from_user.id,
    ):
        return await message.reply_text(
            f"{F.EMO['cross']} {F.sc('admins only')}",
            parse_mode=ParseMode.HTML,
        )

    target: Optional[int] = None

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
            "ᴜꜱᴀɢᴇ: <code>/unban USER_ID</code>",
            parse_mode=ParseMode.HTML,
        )

    coll = _bans_coll()
    if coll is not None:
        try:
            await coll.delete_one({
                "chat_id": message.chat.id,
                "user_id": int(target),
            })
        except Exception:
            pass

    try:
        await client.unban_chat_member(message.chat.id, int(target))
    except Exception as e:
        logger.debug(f"[GROUPS] unban: {e}")

    await message.reply_text(
        f"✅ {F.sc('unbanned')} <code>{target}</code>",
        parse_mode=ParseMode.HTML,
    )


@Client.on_message(
    filters.command("banlist") & filters.group,
    group=-8500,
)
async def cmd_banlist(client: Client, message: Message):
    coll = _bans_coll()
    if coll is None:
        return await message.reply_text("❌ database error")

    try:
        cur = coll.find({"chat_id": message.chat.id}).limit(50)
        docs = await cur.to_list(length=50)
    except Exception:
        return await message.reply_text("❌ query failed")

    if not docs:
        return await message.reply_text("⚪ no banned users")

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
# SECTION 7 — FILTERS
# ============================================================

@Client.on_message(
    filters.command(["filter", "addfilter"]) & filters.group,
    group=-8500,
)
async def cmd_filter(client: Client, message: Message):
    if not message.from_user:
        return
    if not await _is_group_admin(
        client, message.chat.id, message.from_user.id,
    ):
        return await message.reply_text(
            f"{F.EMO['cross']} {F.sc('admins only')}",
            parse_mode=ParseMode.HTML,
        )

    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        return await message.reply_text(
            "ᴜꜱᴀɢᴇ: <code>/filter WORD</code>",
            parse_mode=ParseMode.HTML,
        )

    word = args[1].strip().lower()
    if not word:
        return await message.reply_text("❌ empty")

    cfg = await S.get_config(message.chat.id)
    words = list((cfg.get("filters") or {}).get("banned_words") or [])
    if word in words:
        return await message.reply_text("⚠️ already added")

    words.append(word)
    await S.save_field(
        message.chat.id, "filters.banned_words", words,
    )
    await message.reply_text(
        f"✅ {F.sc('added')} · <code>{word}</code>",
        parse_mode=ParseMode.HTML,
    )


@Client.on_message(
    filters.command(["unfilter", "removefilter"]) & filters.group,
    group=-8500,
)
async def cmd_unfilter(client: Client, message: Message):
    if not message.from_user:
        return
    if not await _is_group_admin(
        client, message.chat.id, message.from_user.id,
    ):
        return await message.reply_text(
            f"{F.EMO['cross']} {F.sc('admins only')}",
            parse_mode=ParseMode.HTML,
        )

    args = (message.text or "").split(maxsplit=1)
    if len(args) < 2:
        return await message.reply_text(
            "ᴜꜱᴀɢᴇ: <code>/unfilter WORD</code>",
            parse_mode=ParseMode.HTML,
        )

    word = args[1].strip().lower()
    cfg = await S.get_config(message.chat.id)
    words = list((cfg.get("filters") or {}).get("banned_words") or [])
    if word not in words:
        return await message.reply_text("⚠️ not found")

    words.remove(word)
    await S.save_field(
        message.chat.id, "filters.banned_words", words,
    )
    await message.reply_text(
        f"🗑️ {F.sc('removed')} · <code>{word}</code>",
        parse_mode=ParseMode.HTML,
    )


@Client.on_message(
    filters.command("filters") & filters.group,
    group=-8500,
)
async def cmd_filters(client: Client, message: Message):
    cfg = await S.get_config(message.chat.id)
    words = (cfg.get("filters") or {}).get("banned_words") or []

    if not words:
        return await message.reply_text("⚪ no banned words")

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
# SECTION 8 — MAINTENANCE (bot admin, PM)
# ============================================================

@Client.on_message(
    filters.command("maintenance") & filters.private,
    group=-8500,
)
async def cmd_maintenance(client: Client, message: Message):
    if not message.from_user or not _is_bot_admin(message.from_user.id):
        return await message.reply_text(
            f"{F.EMO['cross']} {F.sc('bot admins only')}",
            parse_mode=ParseMode.HTML,
        )

    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2 or parts[1].strip().lower() not in (
        "on", "off", "true", "false",
    ):
        return await message.reply_text(
            "ᴜꜱᴀɢᴇ: <code>/maintenance on</code> "
            "ᴏʀ <code>/maintenance off</code>",
            parse_mode=ParseMode.HTML,
        )

    enable = parts[1].strip().lower() in ("on", "true")

    try:
        from database import db_registry
        db = db_registry.get_system_db()
        if db is None:
            return await message.reply_text("❌ db error")
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
        logger.exception(f"[GROUPS] maint: {e}")
        await message.reply_text(f"❌ {e}")

# ============================================================
# SECTION 8b — GROUP DEFAULT TEMPLATE (bot admins only)
# ============================================================
#
# /savegroupdefault   (in a group, bot admin)  → save this group's
#                       config as the global template for new groups
# /showgroupdefault   (in PM, bot admin)       → view template summary
# /resetgroupdefault  (in PM, bot admin)       → reset to code defaults

@Client.on_message(
    filters.command("savegroupdefault") & filters.group,
    group=-8500,
)
async def cmd_save_group_default(client: Client, message: Message):
    if not message.from_user or not _is_bot_admin(message.from_user.id):
        return await message.reply_text(
            f"{F.EMO['cross']} {F.sc('bot admins only')}",
            parse_mode=ParseMode.HTML,
        )

    chat_id = message.chat.id
    try:
        cfg = await S.get_config(chat_id, use_cache=False)
        ok = await S.save_default_template(cfg)
    except Exception as e:
        logger.exception(f"[GROUPS] save default: {e}")
        return await message.reply_text(f"❌ {e}")

    if not ok:
        return await message.reply_text(
            f"{F.EMO['cross']} {F.sc('save failed')}",
            parse_mode=ParseMode.HTML,
        )

    await message.reply_text(
        "\n".join([
            f"{F.EMO['check']} <b>{F.fb('DEFAULT TEMPLATE SAVED')}</b>",
            F.DIV, "",
            f"👥 {F.sc('source group')} · "
            f"<code>{message.chat.id}</code>",
            "",
            f"📌 {F.sc('every new group will inherit this config')}",
            f"📌 {F.sc('existing groups are unchanged')}",
            f"📌 {F.sc('reset a group to apply the new defaults')}",
        ]),
        parse_mode=ParseMode.HTML,
    )


@Client.on_message(
    filters.command("showgroupdefault") & filters.private,
    group=-8500,
)
async def cmd_show_group_default(client: Client, message: Message):
    if not message.from_user or not _is_bot_admin(message.from_user.id):
        return await message.reply_text(
            f"{F.EMO['cross']} {F.sc('bot admins only')}",
            parse_mode=ParseMode.HTML,
        )

    try:
        tpl = await S.get_default_template()
        is_custom = await S.has_custom_template()
    except Exception as e:
        return await message.reply_text(f"❌ {e}")

    source = "🟢 custom" if is_custom else "⚪ code defaults"

    ad = tpl.get("auto_delete") or {}
    flow = tpl.get("flow") or {}
    spell = flow.get("spell_check") or {}
    sugg = flow.get("suggestions") or {}
    fd = flow.get("file_delivery") or {}

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"🌐 <b>{F.fb('DEFAULT TEMPLATE')}</b>",
        F.DIV, "",
        f"📦 {F.sc('source')} · <b>{source}</b>",
        "",
        F.DIV_S, "",
        f"🎬 {F.sc('content mode')} · "
        f"<code>{tpl.get('content_mode', 'both')}</code>",
        f"⏱️ {F.sc('auto-delete')} · "
        f"<code>{ad.get('bot_timer', 600)}s</code>",
        f"🎯 {F.sc('spell threshold')} · "
        f"<code>{spell.get('threshold', 82)}</code>",
        f"💡 {F.sc('suggestion min score')} · "
        f"<code>{sugg.get('min_score', 45)}</code>",
        f"📡 {F.sc('provider')} · "
        f"<code>{sugg.get('provider', 'both')}</code>",
        f"📊 {F.sc('sort')} · "
        f"<code>{fd.get('sort_order', 'small_to_big')}</code>",
        "",
        F.DIV_S,
        f"📌 {F.sc('save template')} · "
        f"<code>/savegroupdefault</code> (in a group)",
        f"📌 {F.sc('reset template')} · "
        f"<code>/resetgroupdefault</code>",
    ]

    await message.reply_text(
        "\n".join(lines),
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


@Client.on_message(
    filters.command("resetgroupdefault") & filters.private,
    group=-8500,
)
async def cmd_reset_group_default(client: Client, message: Message):
    if not message.from_user or not _is_bot_admin(message.from_user.id):
        return await message.reply_text(
            f"{F.EMO['cross']} {F.sc('bot admins only')}",
            parse_mode=ParseMode.HTML,
        )

    try:
        ok = await S.reset_default_template()
    except Exception as e:
        return await message.reply_text(f"❌ {e}")

    if not ok:
        return await message.reply_text(
            f"{F.EMO['cross']} {F.sc('reset failed')}",
            parse_mode=ParseMode.HTML,
        )

    await message.reply_text(
        "\n".join([
            f"{F.EMO['check']} <b>{F.fb('TEMPLATE RESET')}</b>",
            F.DIV, "",
            f"📌 {F.sc('new groups will use code defaults')}",
            f"📌 {F.sc('existing groups are unchanged')}",
        ]),
        parse_mode=ParseMode.HTML,
    )

# ============================================================
# SECTION 8c — GROUP STATS (bot admins only)
# ============================================================

def _fmt_num(n: Any) -> str:
    """Pretty-print a number with thousand separators."""
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return "0"


def _read_stats(doc: Dict[str, Any]) -> Dict[str, int]:
    """Pull the 4 counters out of a group doc."""
    st = doc.get("stats") or {}
    def _i(k):
        try:
            return int(st.get(k, 0) or 0)
        except (TypeError, ValueError):
            return 0
    return {
        "searches_today": _i("searches_today"),
        "results_found":  _i("results_found"),
        "not_found":      _i("not_found"),
        "files_sent":     _i("files_sent"),
    }


@Client.on_message(
    filters.command(["groupstats", "gstats"]) & filters.private,
    group=-8500,
)
async def cmd_groupstats(client: Client, message: Message):
    """Show stats for all groups, or one specific group."""
    if not message.from_user or not _is_bot_admin(message.from_user.id):
        return await message.reply_text(
            f"{F.EMO['cross']} {F.sc('bot admins only')}",
            parse_mode=ParseMode.HTML,
        )

    # ── Parse optional chat_id argument ──
    args = (message.text or "").split()
    target_cid: Optional[int] = None
    if len(args) >= 2:
        try:
            target_cid = int(args[1])
        except (ValueError, TypeError):
            return await message.reply_text(
                "\n".join([
                    f"{F.EMO['cross']} <b>{F.fb('INVALID CHAT ID')}</b>",
                    F.DIV, "",
                    "ᴜꜱᴀɢᴇ:",
                    "• <code>/groupstats</code> — all groups",
                    "• <code>/groupstats -100123456789</code> — one group",
                ]),
                parse_mode=ParseMode.HTML,
            )

    # ── Fetch all groups ──
    try:
        docs = await S.list_groups(limit=100)
    except Exception as e:
        logger.exception(f"[GROUPS] stats list: {e}")
        return await message.reply_text(f"❌ {e}")

    if not docs:
        return await message.reply_text(
            "\n".join([
                f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                f"📊 <b>{F.fb('GROUP STATS')}</b>",
                F.DIV, "",
                f"⚪ {F.sc('no groups registered yet')}",
            ]),
            parse_mode=ParseMode.HTML,
        )

    # ── Specific group ──
    if target_cid is not None:
        target_doc = None
        for d in docs:
            try:
                if int(d.get("chat_id") or 0) == target_cid:
                    target_doc = d
                    break
            except (TypeError, ValueError):
                continue

        if not target_doc:
            return await message.reply_text(
                "\n".join([
                    f"{F.EMO['cross']} <b>{F.fb('GROUP NOT FOUND')}</b>",
                    F.DIV, "",
                    f"🆔 <code>{target_cid}</code>",
                    f"📌 {F.sc('not registered in the bot')}",
                ]),
                parse_mode=ParseMode.HTML,
            )

        title = str(target_doc.get("title") or target_cid)[:60]
        st = _read_stats(target_doc)

        # Success rate (found / total searches)
        searches = st["searches_today"]
        found = st["results_found"]
        if searches > 0:
            rate = (found / searches) * 100
            rate_str = f"{rate:.1f}%"
        else:
            rate_str = "—"

        lines = [
            f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
            f"📊 <b>{F.fb('GROUP STATS')}</b>",
            F.DIV, "",
            f"👥 <b>{F.sc(title)}</b>",
            f"🆔 <code>{target_cid}</code>",
            "",
            F.DIV_S, "",
            f"🔎 {F.sc('searches')} · <b>{_fmt_num(searches)}</b>",
            f"✅ {F.sc('results found')} · "
            f"<b>{_fmt_num(found)}</b>",
            f"❌ {F.sc('not found')} · "
            f"<b>{_fmt_num(st['not_found'])}</b>",
            f"📤 {F.sc('files sent')} · "
            f"<b>{_fmt_num(st['files_sent'])}</b>",
            "",
            F.DIV_S, "",
            f"📈 {F.sc('success rate')} · <b>{rate_str}</b>",
            "",
            F.DIV_S,
            f"♻️ {F.sc('reset')} · "
            f"<code>/resetgroupstats {target_cid}</code>",
        ]
        return await message.reply_text(
            "\n".join(lines),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )

    # ── All groups ──
    # Aggregate + collect per-group
    totals = {
        "searches_today": 0,
        "results_found": 0,
        "not_found": 0,
        "files_sent": 0,
    }
    entries: List[Dict[str, Any]] = []
    for d in docs:
        st = _read_stats(d)
        for k in totals:
            totals[k] += st[k]
        entries.append({
            "chat_id": int(d.get("chat_id") or 0),
            "title": str(d.get("title") or d.get("chat_id"))[:40],
            **st,
        })

    # Top 10 by searches
    entries.sort(key=lambda x: x["searches_today"], reverse=True)
    top = entries[:10]

    # Overall success rate
    if totals["searches_today"] > 0:
        overall_rate = (
            totals["results_found"] / totals["searches_today"]
        ) * 100
        overall_rate_str = f"{overall_rate:.1f}%"
    else:
        overall_rate_str = "—"

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"📊 <b>{F.fb('GROUP STATS')}</b>",
        F.DIV, "",
        f"📈 <b>{F.sc('TOTALS')}</b>",
        "",
        f"👥 {F.sc('groups')} · <b>{len(entries)}</b>",
        f"🔎 {F.sc('searches')} · "
        f"<b>{_fmt_num(totals['searches_today'])}</b>",
        f"✅ {F.sc('results found')} · "
        f"<b>{_fmt_num(totals['results_found'])}</b>",
        f"❌ {F.sc('not found')} · "
        f"<b>{_fmt_num(totals['not_found'])}</b>",
        f"📤 {F.sc('files sent')} · "
        f"<b>{_fmt_num(totals['files_sent'])}</b>",
        "",
        f"📈 {F.sc('success rate')} · <b>{overall_rate_str}</b>",
        "",
        F.DIV_S, "",
        f"🏆 <b>{F.sc('TOP GROUPS')}</b>",
        f"<i>{F.sc('by searches today')}</i>",
        "",
    ]

    for i, e in enumerate(top, 1):
        if e["searches_today"] == 0 and e["files_sent"] == 0:
            continue
        lines.append(
            f"<b>{i:02d}.</b> {F.sc(e['title'])} "
            f"· <code>{_fmt_num(e['searches_today'])}</code> 🔎 "
            f"· <code>{_fmt_num(e['files_sent'])}</code> 📤"
        )

    if all(
        e["searches_today"] == 0 and e["files_sent"] == 0
        for e in entries
    ):
        lines.append(f"⚪ {F.sc('no activity yet')}")

    lines += [
        "",
        F.DIV_S,
        f"📌 {F.sc('per-group')} · "
        f"<code>/groupstats -1001234567890</code>",
        f"📌 {F.sc('reset')} · "
        f"<code>/resetgroupstats -1001234567890</code>",
    ]

    await message.reply_text(
        "\n".join(lines)[:4000],
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


@Client.on_message(
    filters.command("resetgroupstats") & filters.private,
    group=-8500,
)
async def cmd_reset_groupstats(client: Client, message: Message):
    """Zero out one group's stats counters."""
    if not message.from_user or not _is_bot_admin(message.from_user.id):
        return await message.reply_text(
            f"{F.EMO['cross']} {F.sc('bot admins only')}",
            parse_mode=ParseMode.HTML,
        )

    args = (message.text or "").split()
    if len(args) < 2:
        return await message.reply_text(
            "\n".join([
                "ᴜꜱᴀɢᴇ: <code>/resetgroupstats -1001234567890</code>",
                "",
                f"📌 {F.sc('get the id from')} "
                f"<code>/groupstats</code>",
            ]),
            parse_mode=ParseMode.HTML,
        )

    try:
        cid = int(args[1])
    except (ValueError, TypeError):
        return await message.reply_text(
            f"{F.EMO['cross']} {F.sc('invalid chat id')}",
            parse_mode=ParseMode.HTML,
        )

    try:
        now = datetime.utcnow()
        await S.save_field(cid, "stats", {
            "searches_today": 0,
            "results_found": 0,
            "not_found": 0,
            "files_sent": 0,
            "updated_at": now,
        })
    except Exception as e:
        logger.exception(f"[GROUPS] reset stats: {e}")
        return await message.reply_text(f"❌ {e}")

    await message.reply_text(
        "\n".join([
            f"{F.EMO['check']} <b>{F.fb('STATS RESET')}</b>",
            F.DIV, "",
            f"🆔 <code>{cid}</code>",
            "",
            f"📌 {F.sc('all counters set to 0')}",
        ]),
        parse_mode=ParseMode.HTML,
    )

# ============================================================
# SECTION 8d — GROUP CONFIG BACKUP / RESTORE (bot admins)
# ============================================================
#
# /backupgroup <chat_id>     → JSON file to PM
# /restoregroup <chat_id>    → reply to JSON, apply
# /backupall                 → every group in one JSON
# /restoreall                → reply to JSON, restore all
#
# Only whitelisted keys (DEFAULT_CFG) are applied. Per-instance
# keys (chat_id, title, stats) are stripped before export.
# ============================================================

_STRIP_ON_EXPORT = frozenset({
    "chat_id", "_id", "title", "username",
    "created_at", "updated_at",
})


def _export_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """Return a clean copy of cfg for JSON export."""
    out: Dict[str, Any] = {}
    for k, v in (cfg or {}).items():
        if k in _STRIP_ON_EXPORT:
            continue
        if k == "stats":
            continue
        out[k] = v
    return out


def _sanitize_import(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """
    Keep only keys that exist in DEFAULT_CFG.
    Drops anything unknown — safe against malicious payloads.
    """
    if not isinstance(cfg, dict):
        return {}
    out: Dict[str, Any] = {}
    for k, v in cfg.items():
        if k in _STRIP_ON_EXPORT:
            continue
        if k == "stats":
            continue
        if k not in S.DEFAULT_CFG:
            continue
        out[k] = v
    return out


async def _send_json_file(
    client: Client,
    chat_id: int,
    data: Any,
    filename: str,
    caption: str,
) -> bool:
    """Send a JSON payload as a document."""
    try:
        raw = json.dumps(data, indent=2, ensure_ascii=False).encode("utf-8")
    except Exception as e:
        logger.warning(f"[GROUPS] json encode: {e}")
        return False

    try:
        buf = io.BytesIO(raw)
        buf.name = filename
        await client.send_document(
            chat_id=int(chat_id),
            document=buf,
            file_name=filename,
            caption=caption,
            parse_mode=ParseMode.HTML,
        )
        return True
    except Exception as e:
        logger.exception(f"[GROUPS] send json: {e}")
        return False


async def _download_json(message: Message) -> Optional[Any]:
    """Download a JSON document from a replied-to message."""
    target = message.reply_to_message
    if not target or not target.document:
        return None
    try:
        path = await target.download()
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return data
    except Exception as e:
        logger.warning(f"[GROUPS] download json: {e}")
        return None


# ── /backupgroup ──

@Client.on_message(
    filters.command(["backupgroup", "bg"]) & filters.private,
    group=-8500,
)
async def cmd_backup_group(client: Client, message: Message):
    if not message.from_user or not _is_bot_admin(message.from_user.id):
        return await message.reply_text(
            f"{F.EMO['cross']} {F.sc('bot admins only')}",
            parse_mode=ParseMode.HTML,
        )

    args = (message.text or "").split()
    if len(args) < 2:
        return await message.reply_text(
            "\n".join([
                "ᴜꜱᴀɢᴇ: <code>/backupgroup -1001234567890</code>",
                "",
                f"📌 {F.sc('get the id from')} <code>/groupstats</code>",
            ]),
            parse_mode=ParseMode.HTML,
        )

    try:
        cid = int(args[1])
    except (ValueError, TypeError):
        return await message.reply_text(
            f"{F.EMO['cross']} {F.sc('invalid chat id')}",
            parse_mode=ParseMode.HTML,
        )

    try:
        cfg = await S.get_config(cid, use_cache=False)
    except Exception as e:
        return await message.reply_text(f"❌ {e}")

    if not cfg.get("chat_id"):
        return await message.reply_text(
            "\n".join([
                f"{F.EMO['cross']} <b>{F.fb('GROUP NOT FOUND')}</b>",
                F.DIV, "",
                f"🆔 <code>{cid}</code>",
            ]),
            parse_mode=ParseMode.HTML,
        )

    export = {
        "version": 1,
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "chat_id": cid,
        "title": str(cfg.get("title") or "")[:100],
        "config": _export_config(cfg),
    }

    fname = f"group_backup_{cid}_{int(time.time())}.json"
    caption = "\n".join([
        f"{F.EMO['check']} <b>{F.fb('BACKUP READY')}</b>",
        F.DIV, "",
        f"👥 {F.sc('group')} · <code>{cid}</code>",
        f"📦 {F.sc('keys')} · <b>{len(export['config'])}</b>",
        "",
        f"📌 {F.sc('keep this file safe')}",
        f"📌 {F.sc('restore with')} "
        f"<code>/restoregroup {cid}</code>",
    ])

    ok = await _send_json_file(
        client, message.chat.id, export, fname, caption,
    )
    if not ok:
        return await message.reply_text(
            f"{F.EMO['cross']} {F.sc('send failed')}",
            parse_mode=ParseMode.HTML,
        )


# ── /restoregroup ──

@Client.on_message(
    filters.command(["restoregroup", "rg"])
    & filters.private
    & filters.reply,
    group=-8500,
)
async def cmd_restore_group(client: Client, message: Message):
    if not message.from_user or not _is_bot_admin(message.from_user.id):
        return

    args = (message.text or "").split()
    if len(args) < 2:
        return await message.reply_text(
            "\n".join([
                "ᴜꜱᴀɢᴇ:",
                f"1. {F.sc('reply to a backup json')}",
                "2. <code>/restoregroup -1001234567890</code>",
            ]),
            parse_mode=ParseMode.HTML,
        )

    try:
        cid = int(args[1])
    except (ValueError, TypeError):
        return await message.reply_text(
            f"{F.EMO['cross']} {F.sc('invalid chat id')}",
            parse_mode=ParseMode.HTML,
        )

    data = await _download_json(message)
    if data is None:
        return await message.reply_text(
            f"{F.EMO['cross']} {F.sc('could not read json')}",
            parse_mode=ParseMode.HTML,
        )

    # Accept two shapes:
    #   1. Wrapped:   {"chat_id": X, "config": {...}}
    #   2. Flat:      {...keys of config...}
    raw_cfg: Dict[str, Any] = {}
    if isinstance(data, dict):
        if isinstance(data.get("config"), dict):
            raw_cfg = data["config"]
        else:
            raw_cfg = data

    clean = _sanitize_import(raw_cfg)
    if not clean:
        return await message.reply_text(
            "\n".join([
                f"{F.EMO['cross']} <b>{F.fb('INVALID BACKUP')}</b>",
                F.DIV, "",
                f"📌 {F.sc('no valid keys found')}",
            ]),
            parse_mode=ParseMode.HTML,
        )

    # Preserve existing meta
    try:
        existing = await S.get_config(cid, use_cache=False)
    except Exception:
        existing = {}

    now = datetime.utcnow()
    doc: Dict[str, Any] = {
        "chat_id": int(cid),
        "title": existing.get("title"),
        "username": existing.get("username"),
        "created_at": existing.get("created_at", now),
        "updated_at": now,
        "stats": existing.get("stats") or {
            "searches_today": 0,
            "results_found": 0,
            "not_found": 0,
            "files_sent": 0,
            "updated_at": now,
        },
    }

    # Merge defaults over top of the sanitized import so any
    # missing key falls back to the code default.
    template = await S.get_default_template()
    merged = dict(template)
    for k, v in clean.items():
        merged[k] = v
    for k in S.DEFAULT_CFG.keys():
        if k not in merged and k in clean:
            merged[k] = clean[k]

    # Strip per-instance keys from merged
    for k in _STRIP_ON_EXPORT:
        merged.pop(k, None)
    merged.pop("stats", None)

    doc.update(merged)

    try:
        coll = S._coll()
        if coll is None:
            raise RuntimeError("no db")
        await coll.replace_one({"chat_id": int(cid)}, doc, upsert=True)
        S._cache_invalidate(int(cid))
    except Exception as e:
        logger.exception(f"[GROUPS] restore: {e}")
        return await message.reply_text(f"❌ {e}")

    await message.reply_text(
        "\n".join([
            f"{F.EMO['check']} <b>{F.fb('RESTORE COMPLETE')}</b>",
            F.DIV, "",
            f"👥 {F.sc('group')} · <code>{cid}</code>",
            f"📦 {F.sc('keys applied')} · <b>{len(clean)}</b>",
            "",
            f"📌 {F.sc('config is now live')}",
        ]),
        parse_mode=ParseMode.HTML,
    )


# ── /backupall ──

@Client.on_message(
    filters.command(["backupall", "ba"]) & filters.private,
    group=-8500,
)
async def cmd_backup_all(client: Client, message: Message):
    if not message.from_user or not _is_bot_admin(message.from_user.id):
        return await message.reply_text(
            f"{F.EMO['cross']} {F.sc('bot admins only')}",
            parse_mode=ParseMode.HTML,
        )

    try:
        docs = await S.list_groups(limit=500)
    except Exception as e:
        return await message.reply_text(f"❌ {e}")

    if not docs:
        return await message.reply_text(
            f"⚪ {F.sc('no groups registered yet')}",
            parse_mode=ParseMode.HTML,
        )

    bundle: Dict[str, Any] = {
        "version": 1,
        "exported_at": datetime.utcnow().isoformat() + "Z",
        "groups": {},
    }
    count = 0
    for d in docs:
        try:
            cid = int(d.get("chat_id") or 0)
        except (TypeError, ValueError):
            continue
        if not cid:
            continue
        try:
            cfg = await S.get_config(cid, use_cache=False)
        except Exception:
            continue
        bundle["groups"][str(cid)] = {
            "title": str(cfg.get("title") or "")[:100],
            "config": _export_config(cfg),
        }
        count += 1

    fname = f"all_groups_backup_{int(time.time())}.json"
    caption = "\n".join([
        f"{F.EMO['check']} <b>{F.fb('FULL BACKUP READY')}</b>",
        F.DIV, "",
        f"👥 {F.sc('groups')} · <b>{count}</b>",
        "",
        f"📌 {F.sc('restore with')} <code>/restoreall</code>",
    ])

    await _send_json_file(
        client, message.chat.id, bundle, fname, caption,
    )


# ── /restoreall ──

@Client.on_message(
    filters.command(["restoreall", "ra"])
    & filters.private
    & filters.reply,
    group=-8500,
)
async def cmd_restore_all(client: Client, message: Message):
    if not message.from_user or not _is_bot_admin(message.from_user.id):
        return

    data = await _download_json(message)
    if not isinstance(data, dict) or not isinstance(
        data.get("groups"), dict,
    ):
        return await message.reply_text(
            "\n".join([
                f"{F.EMO['cross']} <b>{F.fb('INVALID BUNDLE')}</b>",
                F.DIV, "",
                f"📌 {F.sc('reply to a /backupall file')}",
            ]),
            parse_mode=ParseMode.HTML,
        )

    groups = data["groups"]
    if not groups:
        return await message.reply_text(
            f"⚪ {F.sc('empty bundle')}",
            parse_mode=ParseMode.HTML,
        )

    # Confirm
    total = len(groups)
    confirm_kb = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            f"✅ {F.sc(f'yes, restore {total}')}",
            callback_data="ga:rstall_do",
        ),
        InlineKeyboardButton(
            f"❌ {F.sc('cancel')}",
            callback_data="ga:rstall_no",
        ),
    ]])

    # Stash the payload for the callback to pick up
    try:
        from plugins.groups import router as R
        R._sess_new(
            message.from_user.id,
            "rstall",
            message.chat.id,
            payload=groups,
        )
    except Exception as e:
        logger.debug(f"[GROUPS] stash rstall: {e}")

    await message.reply_text(
        "\n".join([
            f"{F.EMO['warn']} <b>{F.fb('RESTORE ALL GROUPS?')}</b>",
            F.DIV, "",
            f"👥 {F.sc('groups in bundle')} · <b>{total}</b>",
            "",
            f"⚠️ {F.sc('this will overwrite existing configs')}",
            f"📌 {F.sc('stats and titles are preserved')}",
        ]),
        reply_markup=confirm_kb,
        parse_mode=ParseMode.HTML,
    )




# ============================================================
# SECTION 9 — /admin → 👥 Groups LIST (PM only)
# ============================================================

@Client.on_callback_query(
    filters.regex(r"^ga:list$"),
    group=-8499,
)
async def cb_list_groups(client: Client, q: CallbackQuery):
    if not q.from_user or not _is_bot_admin(q.from_user.id):
        return await q.answer("⛔ bot admins only", show_alert=True)

    # Capture chat_id BEFORE deleting the message
    chat_id = q.message.chat.id if q.message.chat else 0
    try:
        await q.message.delete()
    except Exception:
        pass

    if not chat_id:
        return await q.answer("❌ chat unavailable", show_alert=True)

    text, kb = await _build_group_list()
    try:
        await client.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.debug(f"[GROUPS] list send: {e}")

    await q.answer()

# ============================================================
# SECTION 10 — DEEP-LINK ENTRY (gs:{chat_id})
# ============================================================

@Client.on_message(
    filters.command("start") & filters.private,
    group=-8510,
)
async def start_group_settings(client: Client, message: Message):
    """
    Handles /start gs:{chat_id} — opens group panel from PM.
    Called when user taps "Open in PM" from /settings in a group.
    """
    try:
        if not message.from_user:
            return

        args = (message.text or "").split(maxsplit=1)
        if len(args) < 2:
            return  # not our payload

        payload = args[1]
        if not payload.startswith("gs:"):
            return

        try:
            chat_id = int(payload[3:])
        except ValueError:
            return

        # Verify admin
        if not await _is_group_admin(
            client, chat_id, message.from_user.id,
        ):
            return await message.reply_text(
                f"{F.EMO['cross']} "
                f"<b>{F.fb('not admin of that group')}</b>",
                parse_mode=ParseMode.HTML,
            )

        await S.register_group(chat_id)
        text, kb = await P.render_main(chat_id)

        await message.reply_text(
            text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )

        try:
            message.stop_propagation()
        except Exception:
            pass

    except Exception as e:
        logger.exception(f"[GROUPS] start gs: {e}")


# local import at bottom to avoid circular
from plugins.groups import panel as P


__all__ = [
    "cmd_settings",
    "cmd_reload",
    "cmd_add_button",
    "cmd_list_buttons",
    "cmd_remove_button",
    "cmd_clear_buttons",
    "cmd_set_delete_time",
    "cmd_ban",
    "cmd_unban",
    "cmd_banlist",
    "cmd_filter",
    "cmd_unfilter",
    "cmd_filters",
    "cmd_maintenance",
    "cmd_save_group_default",
    "cmd_show_group_default",
    "cmd_reset_group_default",
    "cmd_groupstats",
    "cmd_reset_groupstats",
    "cmd_backup_group",
    "cmd_restore_group",
    "cmd_backup_all",
    "cmd_restore_all",
    "start_group_settings",
]
