# ============================================================
# 🏨 DOWNTOWN VILLA — BROADCAST TEXT INPUT
# ============================================================

from __future__ import annotations
import json
import logging

from pyrogram import Client, filters
from pyrogram.enums import ParseMode

from plugins.broadcast.config import (
    DIV, fb, sc, _is_admin, _esc,
)
from plugins.broadcast import database as DB
from plugins.broadcast import state as ST
from plugins.broadcast import views as V

logger = logging.getLogger(__name__)


@Client.on_message(
    filters.private & filters.text & ~filters.regex(r"^/"),
    group=-450,
)
async def bc_input(client: Client, message):
    if not message.from_user:
        return
    if not _is_admin(message.from_user.id):
        return
    session = ST.get_session(message.from_user.id)
    if not session:
        return

    action = session["action"]
    text = (message.text or "").strip()

    try:
        message.stop_propagation()
    except Exception:
        pass

    # ─── ADD CHANNEL ───
    if action == "add_channel":
        target_id = target_title = target_username = None
        if text.startswith("@"):
            try:
                chat = await client.get_chat(text)
                target_id = chat.id
                target_title = chat.title or text
                target_username = chat.username
            except Exception as e:
                return await message.reply_text(
                    f"❌ ᴄᴀɴɴᴏᴛ ʀᴇꜱᴏʟᴠᴇ <code>{_esc(text)}</code>\n"
                    f"<code>{_esc(e)}</code>",
                    parse_mode=ParseMode.HTML,
                )
        else:
            try:
                target_id = int(text)
                try:
                    chat = await client.get_chat(target_id)
                    target_title = chat.title or str(target_id)
                    target_username = chat.username
                except Exception:
                    target_title = str(target_id)
            except ValueError:
                return await message.reply_text(
                    "❌ ꜱᴇɴᴅ ᴀ ᴄʜᴀɴɴᴇʟ ɪᴅ ᴏʀ @ᴜꜱᴇʀɴᴀᴍᴇ."
                )
        # admin check
        try:
            me = await client.get_me()
            m = await client.get_chat_member(target_id, me.id)
            st = getattr(m, "status", None)
            st = st.name.lower() if hasattr(st, "name") else str(st).lower()
            if st not in ("administrator", "creator", "owner"):
                return await message.reply_text(
                    f"⚠️ ʙᴏᴛ ɪꜱ ɴᴏᴛ ᴀᴅᴍɪɴ ɪɴ "
                    f"<b>{_esc(target_title)}</b>.",
                    parse_mode=ParseMode.HTML,
                )
        except Exception as e:
            return await message.reply_text(
                f"❌ ᴀᴅᴍɪɴ ᴄʜᴇᴄᴋ ꜰᴀɪʟᴇᴅ:\n<code>{_esc(e)}</code>",
                parse_mode=ParseMode.HTML,
            )
        ok = await DB.save_channel(
            target_id, target_title, target_username
        )
        ST.clear_session(message.from_user.id)
        if ok:
            await message.reply_text(
                f"✅ <b>ᴄʜᴀɴɴᴇʟ ᴀᴅᴅᴇᴅ</b>\n\n"
                f"📛 <b>{_esc(target_title)}</b>\n"
                f"🆔 <code>{target_id}</code>",
                parse_mode=ParseMode.HTML,
            )
        else:
            await message.reply_text("❌ ꜰᴀɪʟᴇᴅ.")
        return

    # ─── EDIT GLOBAL CAPTION ───
    if action == "edit_caption":
        if len(text) < 3:
            return await message.reply_text("❌ ᴛᴏᴏ ꜱʜᴏʀᴛ.")
        ok = await DB.set_global_caption(text)
        ST.clear_session(message.from_user.id)
        await message.reply_text(
            "✅ ᴄᴀᴘᴛɪᴏɴ ᴜᴘᴅᴀᴛᴇᴅ." if ok else "❌ ꜰᴀɪʟᴇᴅ."
        )
        return

    # ─── ADD GLOBAL BUTTON ───
    if action == "add_button":
        if "|" not in text:
            return await message.reply_text(
                "❌ ꜰᴏʀᴍᴀᴛ: <code>Name | URL</code>",
                parse_mode=ParseMode.HTML,
            )
        name, url = [p.strip() for p in text.split("|", 1)]
        if not name or not url:
            return await message.reply_text("❌ ᴇᴍᴘᴛʏ.")
        if url.startswith("@"):
            url = f"https://t.me/{url[1:]}"
        elif not (url.startswith("http://")
                  or url.startswith("https://")
                  or url.startswith("tg://")):
            if "." in url and " " not in url:
                url = f"https://{url}"
            else:
                return await message.reply_text("❌ ɪɴᴠᴀʟɪᴅ ᴜʀʟ.")
        btns = await DB.get_global_buttons()
        if len(btns) >= 8:
            ST.clear_session(message.from_user.id)
            return await message.reply_text("⚠️ ᴍᴀx 8 ʙᴜᴛᴛᴏɴꜱ.")
        btns.append({"name": name[:60], "url": url})
        await DB.set_global_buttons(btns)
        ST.clear_session(message.from_user.id)
        await message.reply_text(
            f"✅ ʙᴜᴛᴛᴏɴ ᴀᴅᴅᴇᴅ: <b>{_esc(name)}</b>",
            parse_mode=ParseMode.HTML,
        )
        return

    # ─── EDIT BUTTON NAME ───
    if action == "edit_button_name":
        idx = session["data"].get("idx")
        btns = await DB.get_global_buttons()
        if idx is None or idx < 0 or idx >= len(btns):
            ST.clear_session(message.from_user.id)
            return await message.reply_text("❌ ɪɴᴠᴀʟɪᴅ ɪɴᴅᴇx.")
        btns[idx]["name"] = text[:60]
        await DB.set_global_buttons(btns)
        ST.clear_session(message.from_user.id)
        await message.reply_text("✅ ɴᴀᴍᴇ ᴜᴘᴅᴀᴛᴇᴅ.")
        return

    # ─── EDIT BUTTON URL ───
    if action == "edit_button_url":
        idx = session["data"].get("idx")
        btns = await DB.get_global_buttons()
        if idx is None or idx < 0 or idx >= len(btns):
            ST.clear_session(message.from_user.id)
            return await message.reply_text("❌ ɪɴᴠᴀʟɪᴅ ɪɴᴅᴇx.")
        url = text.strip()
        if url.startswith("@"):
            url = f"https://t.me/{url[1:]}"
        elif not (url.startswith("http://")
                  or url.startswith("https://")
                  or url.startswith("tg://")):
            if "." in url and " " not in url:
                url = f"https://{url}"
            else:
                return await message.reply_text("❌ ɪɴᴠᴀʟɪᴅ ᴜʀʟ.")
        btns[idx]["url"] = url
        await DB.set_global_buttons(btns)
        ST.clear_session(message.from_user.id)
        await message.reply_text("✅ ᴜʀʟ ᴜᴘᴅᴀᴛᴇᴅ.")
        return

    # ─── CHANNEL CAPTION ───
    if action == "ch_edit_caption":
        cid = session["data"].get("chat_id")
        if cid is None:
            ST.clear_session(message.from_user.id)
            return await message.reply_text("❌ ɪɴᴠᴀʟɪᴅ ꜱᴇꜱꜱɪᴏɴ.")
        new_cap = "" if text == "-" else text
        ok = await DB.update_channel(cid, caption=new_cap)
        ST.clear_session(message.from_user.id)
        if ok:
            await message.reply_text(
                f"✅ <b>ᴄʜᴀɴɴᴇʟ ᴄᴀᴘᴛɪᴏɴ ᴜᴘᴅᴀᴛᴇᴅ</b>\n\n"
                f"<code>{_esc(new_cap) if new_cap else '(empty)'}</code>",
                parse_mode=ParseMode.HTML,
            )
        else:
            await message.reply_text("❌ ꜰᴀɪʟᴇᴅ.")
        return


        # ─── GROUP CAPTION ───
    if action == "gr_edit_caption":
        gid = session["data"].get("chat_id")
        if gid is None:
            ST.clear_session(message.from_user.id)
            return await message.reply_text("❌ Invalid session.")
        from plugins.broadcast import views as V
        new_cap = "" if text == "-" else text
        await V._set_group_override(gid, caption=new_cap or None)
        ST.clear_session(message.from_user.id)
        await message.reply_text(
            f"✅ <b>Group caption saved</b>\n\n"
            f"<code>{_esc(new_cap) if new_cap else '(cleared)'}</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    # ─── GROUP BUTTON ───
    if action == "gr_add_button":
        gid = session["data"].get("chat_id")
        if gid is None:
            ST.clear_session(message.from_user.id)
            return await message.reply_text("❌ Invalid.")
        if "|" not in text:
            return await message.reply_text(
                "❌ Format: <code>Name | URL</code>",
                parse_mode=ParseMode.HTML,
            )
        name, url = [p.strip() for p in text.split("|", 1)]
        if url.startswith("@"):
            url = f"https://t.me/{url[1:]}"
        elif not (url.startswith("http://")
                  or url.startswith("https://")
                  or url.startswith("tg://")):
            if "." in url and " " not in url:
                url = f"https://{url}"
            else:
                return await message.reply_text("❌ Invalid URL.")
        from plugins.broadcast import views as V
        ov = await V._get_group_override(gid)
        btns = list(ov.get("buttons") or [])
        btns.append({"name": name[:60], "url": url})
        await V._set_group_override(gid, buttons=btns)
        ST.clear_session(message.from_user.id)
        await message.reply_text(
            f"✅ <b>Button added</b>\n<code>{_esc(name)}</code>",
            parse_mode=ParseMode.HTML,
        )
        return

    

    # ─── CHANNEL BUTTON ───
    if action == "ch_add_button":
        cid = session["data"].get("chat_id")
        if cid is None:
            ST.clear_session(message.from_user.id)
            return await message.reply_text("❌ ɪɴᴠᴀʟɪᴅ.")
        if "|" not in text:
            return await message.reply_text(
                "❌ ꜰᴏʀᴍᴀᴛ: <code>Name | URL</code>",
                parse_mode=ParseMode.HTML,
            )
        name, url = [p.strip() for p in text.split("|", 1)]
        if url.startswith("@"):
            url = f"https://t.me/{url[1:]}"
        elif not (url.startswith("http://")
                  or url.startswith("https://")
                  or url.startswith("tg://")):
            if "." in url and " " not in url:
                url = f"https://{url}"
            else:
                return await message.reply_text("❌ ɪɴᴠᴀʟɪᴅ ᴜʀʟ.")
        ch = await DB.get_channel(cid)
        existing = ch.get("buttons") if ch else None
        btns = list(existing) if existing is not None else []
        if len(btns) >= 8:
            ST.clear_session(message.from_user.id)
            return await message.reply_text("⚠️ ᴍᴀx 8 ʙᴜᴛᴛᴏɴꜱ.")
        btns.append({"name": name[:60], "url": url})
        ok = await DB.update_channel(cid, buttons=btns)
        ST.clear_session(message.from_user.id)
        await message.reply_text(
            f"✅ ʙᴜᴛᴛᴏɴ ᴀᴅᴅᴇᴅ." if ok else "❌ ꜰᴀɪʟᴇᴅ."
        )
        return

    # ─── MANUAL TARGET ───
    if action == "manual_target":
        target_id = None
        if text.startswith("@"):
            try:
                chat = await client.get_chat(text)
                target_id = chat.id
            except Exception as e:
                return await message.reply_text(f"❌ {e}")
        else:
            try:
                target_id = int(text)
            except ValueError:
                return await message.reply_text("❌ ɪɴᴠᴀʟɪᴅ.")
        ST.clear_session(message.from_user.id)
        from plugins.broadcast import watcher as W
        W._MANUAL_TARGETS[message.from_user.id] = target_id
        await message.reply_text(
            f"✅ ᴛᴀʀɢᴇᴛ ꜱᴀᴠᴇᴅ · <code>{target_id}</code>\n\n"
            f"📌 ᴜᴘʟᴏᴀᴅ ᴀ ꜰɪʟᴇ ᴛᴏ ᴛʜᴇ ʙʀᴏᴀᴅᴄᴀꜱᴛ ᴄʜᴀɴɴᴇʟ.",
            parse_mode=ParseMode.HTML,
        )
        return

    # ─── IMPORT CONFIG ───
    if action == "import_config":
        try:
            data = json.loads(text)
        except Exception as e:
            ST.clear_session(message.from_user.id)
            return await message.reply_text(f"❌ ɪɴᴠᴀʟɪᴅ ᴊꜱᴏɴ: {e}")
        btns = data.get("buttons") or []
        cap = data.get("caption") or None
        if isinstance(btns, list):
            clean = []
            for b in btns[:8]:
                if not isinstance(b, dict):
                    continue
                n = (b.get("name") or "").strip()
                u = (b.get("url") or "").strip()
                if n and u:
                    clean.append({"name": n[:60], "url": u})
            await DB.set_global_buttons(clean)
        if cap:
            await DB.set_global_caption(str(cap))
        ST.clear_session(message.from_user.id)
        await message.reply_text("✅ ᴄᴏɴꜰɪɢ ɪᴍᴘᴏʀᴛᴇᴅ.")
        return

    ST.clear_session(message.from_user.id)
    await message.reply_text("⚠️ ᴜɴᴋɴᴏᴡɴ ꜱᴇꜱꜱɪᴏɴ.")


__all__ = []
