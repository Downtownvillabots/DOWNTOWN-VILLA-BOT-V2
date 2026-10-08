# ============================================================
# 🏨 DOWNTOWN VILLA — OTT SETTINGS UI
# ============================================================

from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional, Tuple

from pyrogram.enums import ParseMode
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from plugins.broadcast.config import (
    fb, sc, _esc, _fmt_int, DIV, DIV2,
)
from plugins.ott import settings_db as SD
from plugins.ott import database as DB

logger = logging.getLogger(__name__)


def cb(*parts) -> str:
    return "ott:" + ":".join(str(p) for p in parts)


def _btn(lbl, cd): return InlineKeyboardButton(lbl, callback_data=cd)


def _back_close(back_cb: str) -> List[List[InlineKeyboardButton]]:
    return [[
        _btn("⬅️ Back", back_cb),
        _btn("❌ Close", cb("close")),
    ]]


# ═══════════════════════════════════════════════════════════
# CAPTION SETTINGS — MAIN
# ═══════════════════════════════════════════════════════════

async def view_caption_settings() -> Tuple[str, InlineKeyboardMarkup]:
    gc = await SD.get_global_caption()
    cfg = await DB.get_cfg()

    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📝 <b>{fb('OTT CAPTION SETTINGS')}</b>",
        DIV, "",
        f"📌 {sc('choose where to configure the caption')}",
        "",
        DIV2,
        f"🌐 {sc('current global caption')}:",
        f"<code>{_esc(gc[:200])}</code>",
        "", DIV2,
        f"📌 {sc('per-target captions override the global')}",
    ])

    kb = InlineKeyboardMarkup([
        [_btn("🌐 Global Default", cb("cap_global"))],
        [_btn("📢 Channels", cb("cap_ch_list")),
         _btn("👥 Groups", cb("cap_gr_list"))],
        [_btn("👤 Users", cb("cap_us")),
         _btn("💎 Premium", cb("cap_pm"))],
        *_back_close("ott:set"),
    ])
    return text, kb


# ═══════════════════════════════════════════════════════════
# CAPTION — GLOBAL
# ═══════════════════════════════════════════════════════════

async def view_caption_global() -> Tuple[str, InlineKeyboardMarkup]:
    gc = await SD.get_global_caption()

    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📝 <b>{fb('GLOBAL CAPTION')}</b>",
        DIV, "",
        f"<b>{sc('current')}:</b>",
        f"<code>{_esc(gc)}</code>",
        "", DIV2,
        f"<b>{sc('placeholders')}:</b>",
        "<code>{title} {year} {rating} {lang}</code>",
        "<code>{genres} {platform} {release_date}</code>",
        "<code>{overview} {imdb_url}</code>",
    ])

    kb = InlineKeyboardMarkup([
        [_btn("✏️ Edit Caption", cb("cap_global_edit"))],
        [_btn("📚 Load Template", cb("cap_global_tpl"))],
        [_btn("♻️ Reset to Default", cb("cap_global_rst"))],
        [_btn("👁 Preview", cb("cap_global_prev"))],
        *_back_close("ott:cap_settings"),
    ])
    return text, kb


async def view_caption_global_templates() -> Tuple[str, InlineKeyboardMarkup]:
    rows: List[List[InlineKeyboardButton]] = []
    for name in SD.CAPTION_TEMPLATES:
        rows.append([_btn(f"📝 {name.upper()}",
                          cb(f"cap_global_tpl_use:{name}"))])
    rows.append([_btn("⬅️ Back", cb("cap_global"))])
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📚 <b>{fb('CAPTION TEMPLATES')}</b>",
        DIV, "",
        f"📌 {sc('pick a template to load as global caption')}",
    ])
    return text, InlineKeyboardMarkup(rows)


async def view_caption_global_preview() -> Tuple[str, InlineKeyboardMarkup]:
    gc = await SD.get_global_caption()
    sample = SD.fill_caption(gc, _sample_movie())
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"👁 <b>{fb('CAPTION PREVIEW')}</b>",
        DIV, "",
        f"<i>{sc('shown with sample movie data')}</i>",
        "", DIV2, "",
        sample,
    ])
    kb = InlineKeyboardMarkup([
        [_btn("✏️ Edit", cb("cap_global_edit"))],
        *_back_close("ott:cap_global"),
    ])
    return text, kb


# ═══════════════════════════════════════════════════════════
# CAPTION — CHANNEL LIST → CHANNEL EDITOR
# ═══════════════════════════════════════════════════════════

async def view_caption_ch_list() -> Tuple[str, InlineKeyboardMarkup]:
    try:
        from plugins.broadcast import database as BDB
        chans = await BDB.get_saved_channels()
    except Exception:
        chans = []

    rows: List[List[InlineKeyboardButton]] = []
    if not chans:
        rows.append([_btn("⚠️ no channels saved",
                          cb("noop"))])
    for c in chans[:15]:
        cid = c.get("chat_id")
        title = str(c.get("title") or cid)[:32]
        ov = await SD.get_channel_override(cid)
        mark = "📝" if ov.get("caption") else "🌐"
        rows.append([_btn(f"{mark} {title}",
                          cb(f"cap_ch:{cid}"))])
    rows.extend(_back_close("ott:cap_settings"))

    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📢 <b>{fb('CHANNEL CAPTIONS')}</b>",
        DIV, "",
        f"📌 {sc('📝 = custom · 🌐 = using global')}",
        f"📌 {sc('tap a channel to configure')}",
    ])
    return text, InlineKeyboardMarkup(rows)


async def view_caption_channel(cid: int) -> Tuple[str, InlineKeyboardMarkup]:
    ov = await SD.get_channel_override(cid)
    try:
        from plugins.broadcast import database as BDB
        ch = await BDB.get_channel(cid)
    except Exception:
        ch = None
    title = (ch or {}).get("title") or str(cid)

    cur = ov.get("caption")
    if cur is None:
        disp = f"🌐 {sc('using global default')}"
    else:
        disp = f"<code>{_esc(cur[:250])}</code>"

    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📝 <b>{fb('CHANNEL CAPTION')}</b>",
        DIV, "",
        f"📢 {sc('channel')} · <b>{_esc(title)}</b>",
        f"🆔 <code>{cid}</code>",
        "", DIV2,
        f"<b>{sc('current')}:</b>",
        disp,
    ])

    kb = InlineKeyboardMarkup([
        [_btn("✏️ Set Custom Caption",
              cb(f"cap_ch_edit:{cid}"))],
        [_btn("📚 Load Template",
              cb(f"cap_ch_tpl:{cid}"))],
        [_btn("♻️ Reset to Global",
              cb(f"cap_ch_rst:{cid}"))],
        *_back_close("ott:cap_ch_list"),
    ])
    return text, kb


async def view_caption_channel_templates(cid: int
                                          ) -> Tuple[str, InlineKeyboardMarkup]:
    rows: List[List[InlineKeyboardButton]] = []
    for name in SD.CAPTION_TEMPLATES:
        rows.append([_btn(f"📝 {name.upper()}",
                          cb(f"cap_ch_tpl_use:{cid}:{name}"))])
    rows.append([_btn("⬅️ Back", cb(f"cap_ch:{cid}"))])

    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📚 <b>{fb('LOAD TEMPLATE')}</b>",
        DIV, "",
        f"📌 {sc('pick a template for this channel')}",
    ])
    return text, InlineKeyboardMarkup(rows)


# ═══════════════════════════════════════════════════════════
# CAPTION — GROUP LIST → GROUP EDITOR
# ═══════════════════════════════════════════════════════════

async def view_caption_gr_list() -> Tuple[str, InlineKeyboardMarkup]:
    try:
        from plugins.broadcast import database as BDB
        groups = await BDB.get_all_groups_full()
    except Exception:
        groups = []

    rows: List[List[InlineKeyboardButton]] = []
    if not groups:
        rows.append([_btn("⚠️ no groups registered", cb("noop"))])
    for g in groups[:15]:
        gid = g.get("chat_id")
        title = str(g.get("title") or gid)[:32]
        ov = await SD.get_group_override(gid)
        mark = "📝" if ov.get("caption") else "🌐"
        rows.append([_btn(f"{mark} {title}",
                          cb(f"cap_gr:{gid}"))])
    rows.extend(_back_close("ott:cap_settings"))

    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"👥 <b>{fb('GROUP CAPTIONS')}</b>",
        DIV, "",
        f"📌 {sc('📝 = custom · 🌐 = using global')}",
    ])
    return text, InlineKeyboardMarkup(rows)


async def view_caption_group(gid: int) -> Tuple[str, InlineKeyboardMarkup]:
    ov = await SD.get_group_override(gid)
    try:
        from plugins.broadcast import database as BDB
        groups = await BDB.get_all_groups_full()
        title = next(
            (g["title"] for g in groups if g["chat_id"] == gid),
            str(gid),
        )
    except Exception:
        title = str(gid)

    cur = ov.get("caption")
    disp = (f"🌐 {sc('using global default')}"
            if cur is None else f"<code>{_esc(cur[:250])}</code>")

    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📝 <b>{fb('GROUP CAPTION')}</b>",
        DIV, "",
        f"👥 {sc('group')} · <b>{_esc(title)}</b>",
        f"🆔 <code>{gid}</code>",
        "", DIV2,
        f"<b>{sc('current')}:</b>",
        disp,
    ])

    kb = InlineKeyboardMarkup([
        [_btn("✏️ Set Custom", cb(f"cap_gr_edit:{gid}"))],
        [_btn("♻️ Reset to Global", cb(f"cap_gr_rst:{gid}"))],
        *_back_close("ott:cap_gr_list"),
    ])
    return text, kb


# ═══════════════════════════════════════════════════════════
# CAPTION — USERS / PREMIUM
# ═══════════════════════════════════════════════════════════

async def view_caption_users(kind: str = "user"
                              ) -> Tuple[str, InlineKeyboardMarkup]:
    if kind == "premium":
        cur = await SD.get_premium_caption()
        title = "💎 PREMIUM CAPTION"
        back = "ott:cap_settings"
        edit_cb = "cap_pm_edit"
        rst_cb = "cap_pm_rst"
    else:
        cur = await SD.get_user_caption()
        title = "👤 USERS CAPTION"
        back = "ott:cap_settings"
        edit_cb = "cap_us_edit"
        rst_cb = "cap_us_rst"

    disp = (f"🌐 {sc('using global default')}"
            if cur is None else f"<code>{_esc(cur[:300])}</code>")

    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📝 <b>{fb(title)}</b>",
        DIV, "",
        f"<b>{sc('current')}:</b>",
        disp,
        "", DIV2,
        f"📌 {sc('used when DMing this audience')}",
    ])

    kb = InlineKeyboardMarkup([
        [_btn("✏️ Set Custom", cb(edit_cb))],
        [_btn("♻️ Reset to Global", cb(rst_cb))],
        *_back_close(back),
    ])
    return text, kb


# ═══════════════════════════════════════════════════════════
# BUTTONS SETTINGS — MAIN
# ═══════════════════════════════════════════════════════════

def _buttons_summary(btn: Dict[str, Any]) -> str:
    lines = []
    lines.append(
        f"1. 🔔 Get Notified · "
        f"{'🟢 ON' if btn.get('get_notified', True) else '🔴 OFF'}"
    )
    lines.append(
        f"2. 📥 Get Files · "
        f"{'🟢 ON' if btn.get('get_files', True) else '🔴 OFF'}"
    )
    lines.append(
        f"3. 🎁 Watchlist · "
        f"{'🟢 ON' if btn.get('watchlist', True) else '🔴 OFF'}"
    )
    custom = btn.get("custom") or []
    if not custom:
        lines.append("4. (no custom buttons)")
    else:
        for i, c in enumerate(custom, 1):
            lines.append(f"{i+3}. ✨ {_esc(c.get('name') or '?')}")
    return "\n".join(lines)


async def view_buttons_settings() -> Tuple[str, InlineKeyboardMarkup]:
    gb = await SD.get_global_buttons()

    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🔘 <b>{fb('OTT BUTTON SETTINGS')}</b>",
        DIV, "",
        f"📌 {sc('global default buttons')}:",
        "",
        _buttons_summary(gb),
        "", DIV2,
        f"📌 {sc('choose where to configure')}",
    ])

    kb = InlineKeyboardMarkup([
        [_btn("🌐 Global Default", cb("btn_global"))],
        [_btn("📢 Channels", cb("btn_ch_list")),
         _btn("👥 Groups", cb("btn_gr_list"))],
        [_btn("👤 Users", cb("btn_us")),
         _btn("💎 Premium", cb("btn_pm"))],
        *_back_close("ott:set"),
    ])
    return text, kb


# ═══════════════════════════════════════════════════════════
# BUTTONS — GLOBAL EDITOR
# ═══════════════════════════════════════════════════════════

def _buttons_editor_kb(btn: Dict[str, Any],
                        prefix: str,
                        add_cb: str,
                        rm_prefix: str,
                        rst_cb: str,
                        back_cb: str) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    rows.append([_btn(
        f"🔔 Get Notified · "
        f"{'🟢 ON' if btn.get('get_notified', True) else '🔴 OFF'}",
        cb(f"{prefix}:get_notified"),
    )])
    rows.append([_btn(
        f"📥 Get Files · "
        f"{'🟢 ON' if btn.get('get_files', True) else '🔴 OFF'}",
        cb(f"{prefix}:get_files"),
    )])
    rows.append([_btn(
        f"🎁 Watchlist · "
        f"{'🟢 ON' if btn.get('watchlist', True) else '🔴 OFF'}",
        cb(f"{prefix}:watchlist"),
    )])

    custom = btn.get("custom") or []
    for i, c in enumerate(custom[:6]):
        name = str(c.get("name") or "?")[:28]
        rows.append([_btn(f"🗑️ {name}",
                          cb(f"{rm_prefix}:{i}"))])
    if len(custom) < 6:
        rows.append([_btn("➕ Add Custom Button", cb(add_cb))])
    rows.append([_btn("♻️ Reset Default", cb(rst_cb))])
    rows.extend(_back_close(back_cb))
    return InlineKeyboardMarkup(rows)


async def view_buttons_global() -> Tuple[str, InlineKeyboardMarkup]:
    gb = await SD.get_global_buttons()

    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🔘 <b>{fb('GLOBAL BUTTONS')}</b>",
        DIV, "",
        f"<b>{sc('current')}:</b>",
        _buttons_summary(gb),
        "", DIV2,
        f"📌 {sc('tap a toggle to flip ON/OFF')}",
        f"📌 {sc('tap a custom to remove it')}",
    ])

    kb = _buttons_editor_kb(
        gb,
        prefix="btn_global_tog",
        add_cb="btn_global_add",
        rm_prefix="btn_global_rm",
        rst_cb="btn_global_rst",
        back_cb="ott:btn_settings",
    )
    return text, kb


# ═══════════════════════════════════════════════════════════
# BUTTONS — CHANNEL
# ═══════════════════════════════════════════════════════════

async def view_buttons_ch_list() -> Tuple[str, InlineKeyboardMarkup]:
    try:
        from plugins.broadcast import database as BDB
        chans = await BDB.get_saved_channels()
    except Exception:
        chans = []

    rows: List[List[InlineKeyboardButton]] = []
    if not chans:
        rows.append([_btn("⚠️ no channels saved", cb("noop"))])
    for c in chans[:15]:
        cid = c.get("chat_id")
        title = str(c.get("title") or cid)[:32]
        ov = await SD.get_channel_override(cid)
        mark = "🔘" if ov.get("buttons") is not None else "🌐"
        rows.append([_btn(f"{mark} {title}",
                          cb(f"btn_ch:{cid}"))])
    rows.extend(_back_close("ott:btn_settings"))

    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📢 <b>{fb('CHANNEL BUTTONS')}</b>",
        DIV, "",
        f"📌 {sc('🔘 = custom · 🌐 = using global')}",
    ])
    return text, InlineKeyboardMarkup(rows)


async def view_buttons_channel(cid: int
                                ) -> Tuple[str, InlineKeyboardMarkup]:
    ov = await SD.get_channel_override(cid)
    custom = ov.get("buttons")
    using_global = custom is None
    btn = custom if custom is not None else await SD.get_global_buttons()

    try:
        from plugins.broadcast import database as BDB
        ch = await BDB.get_channel(cid)
    except Exception:
        ch = None
    title = (ch or {}).get("title") or str(cid)

    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🔘 <b>{fb('CHANNEL BUTTONS')}</b>",
        DIV, "",
        f"📢 {sc('channel')} · <b>{_esc(title)}</b>",
        f"🆔 <code>{cid}</code>",
        "",
        f"📌 {sc('source')} · "
        f"{'🌐 global default' if using_global else '🔘 custom'}",
        "", DIV2,
        f"<b>{sc('current')}:</b>",
        _buttons_summary(btn),
    ])

    if using_global:
        kb = InlineKeyboardMarkup([
            [_btn("✏️ Set Custom Buttons",
                  cb(f"btn_ch_custom:{cid}"))],
            *_back_close("ott:btn_ch_list"),
        ])
    else:
        kb = _buttons_editor_kb(
            btn,
            prefix=f"btn_ch_tog:{cid}",
            add_cb=f"btn_ch_add:{cid}",
            rm_prefix=f"btn_ch_rm:{cid}",
            rst_cb=f"btn_ch_rst:{cid}",
            back_cb="ott:btn_ch_list",
        )
    return text, kb


# ═══════════════════════════════════════════════════════════
# BUTTONS — GROUP
# ═══════════════════════════════════════════════════════════

async def view_buttons_gr_list() -> Tuple[str, InlineKeyboardMarkup]:
    try:
        from plugins.broadcast import database as BDB
        groups = await BDB.get_all_groups_full()
    except Exception:
        groups = []

    rows: List[List[InlineKeyboardButton]] = []
    if not groups:
        rows.append([_btn("⚠️ no groups registered", cb("noop"))])
    for g in groups[:15]:
        gid = g.get("chat_id")
        title = str(g.get("title") or gid)[:32]
        ov = await SD.get_group_override(gid)
        mark = "🔘" if ov.get("buttons") is not None else "🌐"
        rows.append([_btn(f"{mark} {title}",
                          cb(f"btn_gr:{gid}"))])
    rows.extend(_back_close("ott:btn_settings"))

    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"👥 <b>{fb('GROUP BUTTONS')}</b>",
        DIV, "",
        f"📌 {sc('🔘 = custom · 🌐 = using global')}",
    ])
    return text, InlineKeyboardMarkup(rows)


async def view_buttons_group(gid: int
                              ) -> Tuple[str, InlineKeyboardMarkup]:
    ov = await SD.get_group_override(gid)
    custom = ov.get("buttons")
    using_global = custom is None
    btn = custom if custom is not None else await SD.get_global_buttons()

    try:
        from plugins.broadcast import database as BDB
        groups = await BDB.get_all_groups_full()
        title = next(
            (g["title"] for g in groups if g["chat_id"] == gid),
            str(gid),
        )
    except Exception:
        title = str(gid)

    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🔘 <b>{fb('GROUP BUTTONS')}</b>",
        DIV, "",
        f"👥 {sc('group')} · <b>{_esc(title)}</b>",
        f"🆔 <code>{gid}</code>",
        "",
        f"📌 {sc('source')} · "
        f"{'🌐 global default' if using_global else '🔘 custom'}",
        "", DIV2,
        f"<b>{sc('current')}:</b>",
        _buttons_summary(btn),
    ])

    if using_global:
        kb = InlineKeyboardMarkup([
            [_btn("✏️ Set Custom", cb(f"btn_gr_custom:{gid}"))],
            *_back_close("ott:btn_gr_list"),
        ])
    else:
        kb = _buttons_editor_kb(
            btn,
            prefix=f"btn_gr_tog:{gid}",
            add_cb=f"btn_gr_add:{gid}",
            rm_prefix=f"btn_gr_rm:{gid}",
            rst_cb=f"btn_gr_rst:{gid}",
            back_cb="ott:btn_gr_list",
        )
    return text, kb


# ═══════════════════════════════════════════════════════════
# BUTTONS — USERS / PREMIUM
# ═══════════════════════════════════════════════════════════

async def view_buttons_users(kind: str = "user"
                              ) -> Tuple[str, InlineKeyboardMarkup]:
    if kind == "premium":
        btn = await SD.get_premium_buttons()
        title = "💎 PREMIUM BUTTONS"
        using_global = btn is None
        if using_global:
            btn = await SD.get_global_buttons()
        edit_cb = "btn_pm_custom"
        tog_prefix = "btn_pm_tog"
        add_cb = "btn_pm_add"
        rm_prefix = "btn_pm_rm"
        rst_cb = "btn_pm_rst"
        back = "ott:btn_settings"
    else:
        btn = await SD.get_user_buttons()
        title = "👤 USERS BUTTONS"
        using_global = btn is None
        if using_global:
            btn = await SD.get_global_buttons()
        edit_cb = "btn_us_custom"
        tog_prefix = "btn_us_tog"
        add_cb = "btn_us_add"
        rm_prefix = "btn_us_rm"
        rst_cb = "btn_us_rst"
        back = "ott:btn_settings"

    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🔘 <b>{fb(title)}</b>",
        DIV, "",
        f"📌 {sc('source')} · "
        f"{'🌐 global default' if using_global else '🔘 custom'}",
        "", DIV2,
        f"<b>{sc('current')}:</b>",
        _buttons_summary(btn),
    ])

    if using_global:
        kb = InlineKeyboardMarkup([
            [_btn("✏️ Set Custom", cb(edit_cb))],
            *_back_close(back),
        ])
    else:
        kb = _buttons_editor_kb(
            btn,
            prefix=tog_prefix,
            add_cb=add_cb,
            rm_prefix=rm_prefix,
            rst_cb=rst_cb,
            back_cb=back,
        )
    return text, kb


# ═══════════════════════════════════════════════════════════
# PROMPT SCREENS (text input)
# ═══════════════════════════════════════════════════════════

def prompt_caption_edit(where: str, back_cb: str
                        ) -> Tuple[str, InlineKeyboardMarkup]:
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"✏️ <b>{fb('EDIT CAPTION')}</b>",
        DIV, "",
        f"📝 {sc('send the new caption as the next message')}",
        f"📌 {sc('placeholders')}:",
        "<code>{title} {year} {rating} {lang}</code>",
        "<code>{genres} {platform} {release_date}</code>",
        "<code>{overview} {imdb_url}</code>",
        "", DIV2,
        f"📌 {sc('send')} <code>-</code> {sc('to cancel')}",
        f"📍 {sc('target')} · <b>{_esc(where)}</b>",
    ])
    kb = InlineKeyboardMarkup(_back_close(back_cb))
    return text, kb


def prompt_add_custom_button(where: str, back_cb: str
                              ) -> Tuple[str, InlineKeyboardMarkup]:
    text = "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"➕ <b>{fb('ADD CUSTOM BUTTON')}</b>",
        DIV, "",
        f"📝 {sc('send as')} <code>Name | URL</code>",
        f"📌 {sc('example')}:",
        "<code>Join Backups | https://t.me/backups</code>",
        "", DIV2,
        f"📍 {sc('target')} · <b>{_esc(where)}</b>",
    ])
    kb = InlineKeyboardMarkup(_back_close(back_cb))
    return text, kb


# ═══════════════════════════════════════════════════════════
# SAMPLE MOVIE FOR PREVIEW
# ═══════════════════════════════════════════════════════════

def _sample_movie() -> Dict[str, Any]:
    return {
        "title": "KALIFA",
        "release_date": "2026-10-15",
        "vote_average": 7.8,
        "original_language": "ml",
        "genres": "Action, Drama",
        "provider": "Amazon Prime Video",
        "region_release": {"date": "2026-10-15"},
        "overview": (
            "A fearless warrior rises against an empire. "
            "A story of courage, sacrifice, and destiny."
        ),
        "imdb_id": "tt1234567",
    }


__all__ = [
    # caption
    "view_caption_settings",
    "view_caption_global", "view_caption_global_templates",
    "view_caption_global_preview",
    "view_caption_ch_list", "view_caption_channel",
    "view_caption_channel_templates",
    "view_caption_gr_list", "view_caption_group",
    "view_caption_users",
    # buttons
    "view_buttons_settings",
    "view_buttons_global",
    "view_buttons_ch_list", "view_buttons_channel",
    "view_buttons_gr_list", "view_buttons_group",
    "view_buttons_users",
    # prompts
    "prompt_caption_edit", "prompt_add_custom_button",
]
