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

import logging
import time
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

    await _show_group_list(message)


async def _show_group_list(message: Message):
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

    await message.reply_text(
        "\n".join(lines)[:4000],
        reply_markup=InlineKeyboardMarkup(rows),
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
# SECTION 9 — /admin → 👥 Groups LIST (PM only)
# ============================================================

@Client.on_callback_query(
    filters.regex(r"^ga:list$"),
    group=-8499,
)
async def cb_list_groups(client: Client, q: CallbackQuery):
    if not q.from_user or not _is_bot_admin(q.from_user.id):
        return await q.answer("⛔ bot admins only", show_alert=True)

    try:
        await q.message.delete()
    except Exception:
        pass

    await _show_group_list(q.message)
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
    "start_group_settings",
]
