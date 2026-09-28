# ============================================================
# 🏨 DOWNTOWN VILLA — BROADCAST PANEL
# ============================================================
# /broadcast command · main panel callbacks · settings
# /admin → Broadcast entry point
# ============================================================

from __future__ import annotations
import json
import logging
from datetime import datetime
from io import BytesIO
from typing import Any, Dict, List

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from plugins.broadcast.config import (
    ADMINS, CAPTION_TEMPLATES, DEFAULT_BROADCAST_CAPTION,
    DIV, DIV2, fb, sc, _is_admin, _esc,
)
from plugins.broadcast import database as DB
from plugins.broadcast import keyboards as KB
from plugins.broadcast import state as ST
from plugins.broadcast import views as V

logger = logging.getLogger(__name__)


# ═════════════════════════════════════════════════════════════
# /broadcast COMMAND
# ═════════════════════════════════════════════════════════════
@Client.on_message(
    filters.command(["broadcast", "bc"]) & filters.private,
    group=-500,
)
async def cmd_broadcast(client: Client, message: Message):
    try:
        if not message.from_user or not _is_admin(message.from_user.id):
            return await message.reply_text("⛔ ᴀᴅᴍɪɴꜱ ᴏɴʟʏ.")
        panel = await message.reply_text("🔄 ʟᴏᴀᴅɪɴɢ ᴘᴀɴᴇʟ...")
        text, kb = await V.view_main()
        await V.safe_edit(panel, text, kb)
    except Exception as e:
        logger.exception(f"[BC] /broadcast crashed: {e}")


# ═════════════════════════════════════════════════════════════
# MAIN PANEL CALLBACKS
# ═════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^bc:main$"), group=-500)
async def cb_main(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    text, kb = await V.view_main()
    await V.safe_edit(q, text, kb)
    await q.answer()


@Client.on_callback_query(filters.regex(r"^bc:close$"), group=-500)
async def cb_close(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    ST.clear_session(q.from_user.id)
    try:
        await q.message.delete()
    except Exception:
        pass
    await q.answer("ᴄʟᴏꜱᴇᴅ")


@Client.on_callback_query(
    filters.regex(r"^bc:cancel_session$"), group=-500
)
async def cb_cancel_session(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    ST.clear_session(q.from_user.id)
    text, kb = await V.view_main()
    await V.safe_edit(q, text, kb)
    await q.answer("❌ ᴄᴀɴᴄᴇʟʟᴇᴅ")


# ═════════════════════════════════════════════════════════════
# CAPTION + BUTTONS (global)
# ═════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^bc:caption$"), group=-500)
async def cb_caption(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    text, kb = await V.view_caption()
    await V.safe_edit(q, text, kb)
    await q.answer()


@Client.on_callback_query(
    filters.regex(r"^bc:caption_edit$"), group=-500
)
async def cb_caption_edit(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    ST.new_session(q.from_user.id, "edit_caption")
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"✏️ <b>{fb('EDIT DEFAULT CAPTION')}</b>",
        DIV, "",
        f"📝 {sc('send the new caption as next message')}",
    ])
    await V.safe_edit(q, text, KB.kb_cancel_session())
    await q.answer()


@Client.on_callback_query(
    filters.regex(r"^bc:caption_reset$"), group=-500
)
async def cb_caption_reset(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    await DB.set_global_caption(DEFAULT_BROADCAST_CAPTION)
    await q.answer("✅ ʀᴇꜱᴇᴛ")
    text, kb = await V.view_caption()
    await V.safe_edit(q, text, kb)


@Client.on_callback_query(
    filters.regex(r"^bc:caption_preview$"), group=-500
)
async def cb_caption_preview(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    cap = await DB.get_global_caption()
    try:
        sample = cap.format(
            file_name="Interstellar.2014.1080p.mkv",
            file_size="2.4 GB",
            rating="8.7",
            year="2014",
            file_caption="Interstellar (2014)",
        )
    except Exception:
        sample = cap
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"👁️ <b>{fb('CAPTION PREVIEW')}</b>",
        DIV, "", sample,
    ])
    await V.safe_edit(q, text, KB.kb_back("bc:caption"))
    await q.answer()


@Client.on_callback_query(filters.regex(r"^bc:buttons$"), group=-500)
async def cb_buttons(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    text, kb = await V.view_buttons()
    await V.safe_edit(q, text, kb)
    await q.answer()


@Client.on_callback_query(
    filters.regex(r"^bc:btn_view:(\d+)$"), group=-500
)
async def cb_btn_view(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    idx = int(q.matches[0].group(1))
    r = await V.view_button_detail(idx)
    if r is None:
        return await q.answer("⚠️ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)
    await V.safe_edit(q, r[0], r[1])
    await q.answer()


@Client.on_callback_query(
    filters.regex(r"^bc:btn_add$"), group=-500
)
async def cb_btn_add(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    ST.new_session(q.from_user.id, "add_button")
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"➕ <b>{fb('ADD DEFAULT BUTTON')}</b>",
        DIV, "",
        f"📝 {sc('send')} <code>Name | URL</code>",
    ])
    await V.safe_edit(q, text, KB.kb_cancel_session())
    await q.answer()


@Client.on_callback_query(
    filters.regex(r"^bc:btn_rm:(\d+)$"), group=-500
)
async def cb_btn_rm(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    idx = int(q.matches[0].group(1))
    btns = await DB.get_global_buttons()
    if idx < 0 or idx >= len(btns):
        return await q.answer("⚠️ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)
    btns.pop(idx)
    await DB.set_global_buttons(btns)
    await q.answer("✅ ʀᴇᴍᴏᴠᴇᴅ")
    text, kb = await V.view_buttons()
    await V.safe_edit(q, text, kb)


@Client.on_callback_query(
    filters.regex(r"^bc:btn_edit_name:(\d+)$"), group=-500
)
async def cb_btn_edit_name(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    idx = int(q.matches[0].group(1))
    ST.new_session(q.from_user.id, "edit_button_name", idx=idx)
    text = "✏️ ꜱᴇɴᴅ ᴛʜᴇ ɴᴇᴡ ɴᴀᴍᴇ."
    await V.safe_edit(q, text, KB.kb_cancel_session())
    await q.answer()


@Client.on_callback_query(
    filters.regex(r"^bc:btn_edit_url:(\d+)$"), group=-500
)
async def cb_btn_edit_url(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    idx = int(q.matches[0].group(1))
    ST.new_session(q.from_user.id, "edit_button_url", idx=idx)
    text = "✏️ ꜱᴇɴᴅ ᴛʜᴇ ɴᴇᴡ ᴜʀʟ."
    await V.safe_edit(q, text, KB.kb_cancel_session())
    await q.answer()


# ═════════════════════════════════════════════════════════════
# CAPTION TEMPLATES
# ═════════════════════════════════════════════════════════════
@Client.on_callback_query(
    filters.regex(r"^bc:caption_lib$"), group=-500
)
async def cb_caption_lib(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    rows = [
        [InlineKeyboardButton(
            f"📝 {n.upper()}",
            callback_data=f"bc:caption_use:{n}")]
        for n in CAPTION_TEMPLATES
    ]
    rows.append([InlineKeyboardButton(
        "◀️ BACK", callback_data="bc:caption"
    )])
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📚 <b>{fb('CAPTION TEMPLATES')}</b>",
        DIV, "",
        f"📌 {sc('pick a template to load into the global editor')}",
    ])
    await V.safe_edit(q, text, InlineKeyboardMarkup(rows))
    await q.answer()


@Client.on_callback_query(
    filters.regex(r"^bc:caption_use:(\w+)$"), group=-500
)
async def cb_caption_use(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    name = q.matches[0].group(1)
    tpl = CAPTION_TEMPLATES.get(name)
    if not tpl:
        return await q.answer("⚠️ ɴᴏᴛ ꜰᴏᴜɴᴅ", show_alert=True)
    await DB.set_global_caption(tpl)
    await q.answer(f"✅ ʟᴏᴀᴅᴇᴅ {name}")
    text, kb = await V.view_caption()
    await V.safe_edit(q, text, kb)


# ═════════════════════════════════════════════════════════════
# USERS / GROUPS / MANUAL
# ═════════════════════════════════════════════════════════════
@Client.on_callback_query(
    filters.regex(r"^bc:users_menu$"), group=-500
)
async def cb_users_menu(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    text, kb = await V.view_users_menu()
    await V.safe_edit(q, text, kb)
    await q.answer()


@Client.on_callback_query(
    filters.regex(r"^bc:groups$"), group=-500
)
async def cb_groups(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    text, kb = await V.view_groups()
    await V.safe_edit(q, text, kb)
    await q.answer()


@Client.on_callback_query(
    filters.regex(r"^bc:gr_view:(-?\d+)$"), group=-500
)
async def cb_gr_view(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    gid = int(q.matches[0].group(1))
    r = await V.view_group_detail(gid)
    if r is None:
        return await q.answer("⚠️ Not found", show_alert=True)
    await V.safe_edit(q, r[0], r[1])
    await q.answer()

@Client.on_callback_query(
    filters.regex(r"^bc:gr_add$"), group=-500
)
async def cb_gr_add(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    ST.new_session(q.from_user.id, "add_group")
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"➕ <b>{fb('ADD GROUP')}</b>",
        DIV, "",
        f"📝 {sc('send the group id or @username')}",
        "", DIV2, "",
        f"📌 {sc('examples')}:",
        f"• <code>-1001234567890</code>",
        f"• <code>@mygroup</code>",
        "", f"⚠️ {sc('bot must be in the group')}",
    ])
    await V.safe_edit(q, text, KB.kb_cancel_session())
    await q.answer()



@Client.on_callback_query(
    filters.regex(r"^bc:gr_cap:(-?\d+)$"), group=-500
)
async def cb_gr_cap(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    gid = int(q.matches[0].group(1))
    ST.new_session(q.from_user.id, "gr_edit_caption", chat_id=gid)
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"✏️ <b>{fb('SET GROUP CAPTION')}</b>",
        DIV, "",
        f"📝 {sc('send the new caption as next message')}",
        f"📌 {sc('send')} <code>-</code> {sc('to clear')}",
    ])
    await V.safe_edit(q, text, KB.kb_cancel_session())
    await q.answer()


@Client.on_callback_query(
    filters.regex(r"^bc:gr_btn:(-?\d+)$"), group=-500
)
async def cb_gr_btn(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    gid = int(q.matches[0].group(1))
    ST.new_session(q.from_user.id, "gr_add_button", chat_id=gid)
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🔘 <b>{fb('ADD GROUP BUTTON')}</b>",
        DIV, "",
        f"📝 {sc('send as:')}",
        f"<code>Name | URL</code>",
    ])
    await V.safe_edit(q, text, KB.kb_cancel_session())
    await q.answer()


@Client.on_callback_query(
    filters.regex(r"^bc:gr_timer:(-?\d+)$"), group=-500
)
async def cb_gr_timer(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    gid = int(q.matches[0].group(1))
    await q.answer(
        f"⏱️ Timer set at broadcast — pick when you send",
        show_alert=True,
    )


@Client.on_callback_query(
    filters.regex(r"^bc:gr_send:(-?\d+)$"), group=-500
)
async def cb_gr_send(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    await q.answer(
        "📌 Upload a file to the broadcast channel first",
        show_alert=True,
    )


@Client.on_callback_query(
    filters.regex(r"^bc:do_users$"), group=-500
)
async def cb_do_users(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    await q.answer(
        "📌 ᴜᴘʟᴏᴀᴅ ᴀ ꜰɪʟᴇ ᴛᴏ ᴛʜᴇ ʙʀᴏᴀᴅᴄᴀꜱᴛ ᴄʜᴀɴɴᴇʟ ꜰɪʀꜱᴛ",
        show_alert=True,
    )


@Client.on_callback_query(
    filters.regex(r"^bc:do_groups$"), group=-500
)
async def cb_do_groups(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    await q.answer(
        "📌 ᴜᴘʟᴏᴀᴅ ᴀ ꜰɪʟᴇ ᴛᴏ ᴛʜᴇ ʙʀᴏᴀᴅᴄᴀꜱᴛ ᴄʜᴀɴɴᴇʟ ꜰɪʀꜱᴛ",
        show_alert=True,
    )


@Client.on_callback_query(
    filters.regex(r"^bc:manual$"), group=-500
)
async def cb_manual(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    ST.new_session(q.from_user.id, "manual_target")
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🎯 <b>{fb('MANUAL TARGET')}</b>",
        DIV, "",
        f"📝 {sc('send a chat id or @username as next message')}",
    ])
    await V.safe_edit(q, text, KB.kb_cancel_session())
    await q.answer()


# ═════════════════════════════════════════════════════════════
# STATS / HISTORY / AUTODELETE / EXPORT / IMPORT
# ═════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^bc:stats$"), group=-500)
async def cb_stats(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    text, kb = await V.view_stats()
    await V.safe_edit(q, text, kb)
    await q.answer()


@Client.on_callback_query(
    filters.regex(r"^bc:history$"), group=-500
)
async def cb_history(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    text, kb = await V.view_history()
    await V.safe_edit(q, text, kb)
    await q.answer()


@Client.on_callback_query(
    filters.regex(r"^bc:autodelete$"), group=-500
)
async def cb_autodelete(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    text, kb = await V.view_autodelete()
    await V.safe_edit(q, text, kb)
    await q.answer()


@Client.on_callback_query(
    filters.regex(r"^bc:export$"), group=-500
)
async def cb_export(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    btns = await DB.get_global_buttons()
    cap = await DB.get_global_caption()
    data = {
        "buttons": btns,
        "caption": cap,
        "exported_at": datetime.now().isoformat(),
    }
    text = json.dumps(data, indent=2, ensure_ascii=False)
    bio = BytesIO(text.encode("utf-8"))
    bio.name = "broadcast_config.json"
    try:
        await client.send_document(
            chat_id=q.from_user.id,
            document=bio,
            caption=(
                f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>\n"
                f"💾 <b>{fb('BROADCAST CONFIG EXPORT')}</b>"
            ),
            parse_mode=ParseMode.HTML,
        )
        await q.answer("✅ ᴇxᴘᴏʀᴛᴇᴅ")
    except Exception as e:
        await q.answer(f"❌ {e}"[:180], show_alert=True)


@Client.on_callback_query(
    filters.regex(r"^bc:import$"), group=-500
)
async def cb_import(client, q):
    if not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)
    ST.new_session(q.from_user.id, "import_config")
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📥 <b>{fb('IMPORT CONFIG')}</b>",
        DIV, "",
        f"📝 {sc('send the JSON config as next message')}",
    ])
    await V.safe_edit(q, text, KB.kb_cancel_session())
    await q.answer()


# ═════════════════════════════════════════════════════════════
# ADMIN PANEL ENTRY (/admin → 📢 Broadcast)
# ═════════════════════════════════════════════════════════════
async def open_panel_for_admin(client: Client, q: CallbackQuery) -> None:
    """Called from /admin → [📢 Broadcast]."""
    if not q.from_user or not _is_admin(q.from_user.id):
        return await q.answer("⛔ ᴀᴅᴍɪɴꜱ ᴏɴʟʏ", show_alert=True)
    try:
        text, kb = await V.view_main()
        await client.send_message(
            chat_id=q.from_user.id,
            text=text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        await q.answer("📢 ᴏᴘᴇɴɪɴɢ ɪɴ ᴘᴍ…")
    except Exception as e:
        logger.exception(f"[BC-ADMIN] {e}")
        try:
            await q.answer(f"❌ {type(e).__name__}", show_alert=True)
        except Exception:
            pass


__all__ = ["open_panel_for_admin"]
