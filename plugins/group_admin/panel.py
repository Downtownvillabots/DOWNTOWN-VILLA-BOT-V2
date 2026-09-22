# ============================================================
# 🏨 DOWNTOWN VILLA — GROUP ADMIN PANEL RENDERER
# ============================================================
#
# Renders every section of the group admin panel.
# Full customization — every field editable from Telegram.
# ============================================================

from __future__ import annotations
import logging
from typing import Any, Dict, List, Optional, Tuple

from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from plugins.group_admin import state as S
from utils import fonts as F
from utils import format as FM

logger = logging.getLogger(__name__)


# ── HELPERS ──
def _on(v) -> str:
    return "🟢 " + F.sc("on") if v else "🔴 " + F.sc("off")


def _div() -> str:
    return F.DIV


# ============================================================
# MAIN PANEL
# ============================================================

async def render_main(chat_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await S.get_config(chat_id)

    flow = cfg.get("flow") or {}
    ad = cfg.get("auto_delete") or {}
    fsub = cfg.get("fsub") or {}
    verify = cfg.get("verify") or {}

    content_mode = cfg.get("content_mode", "both")
    mode_icon = {
        "movies": "🎬", "series": "📺", "both": "🎬📺"
    }.get(content_mode, "🎬📺")

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"{F.EMO['gear']} <b>{F.fb('GROUP SETTINGS')}</b>",
        F.DIV, "",
        f"👥 <b>{F.sc(str(cfg.get('title') or chat_id)[:50])}</b>",
        f"🆔 <code>{chat_id}</code>",
        "",
        F.DIV_S, "",
        f"{mode_icon} {F.sc('content')} · "
        f"<b>{content_mode.upper()}</b>",
        f"🔎 {F.sc('search')} · {_on(cfg.get('search_enabled', True))}",
        f"💬 {F.sc('pm search')} · {_on(cfg.get('pm_search_enabled', True))}",
        f"👋 {F.sc('welcome')} · {_on(cfg.get('welcome_enabled', False))}",
        f"⏱️ {F.sc('auto-delete')} · "
        f"<b>{ad.get('bot_timer', 600)}s</b>",
        f"📢 {F.sc('force-sub')} · "
        f"<b>{len(fsub.get('channels') or [])}</b>",
        f"🔐 {F.sc('verify')} · {_on(verify.get('enabled', False))}",
        f"📝 {F.sc('caption')} · "
        f"{'custom' if cfg.get('caption_template') else 'global'}",
        f"🔘 {F.sc('buttons')} · "
        f"<b>{len(cfg.get('result_buttons') or [])}</b>",
    ]

    rows = [
        [InlineKeyboardButton(
            f"{F.EMO['search']} {F.sc('search settings')}",
            callback_data="ga:s:search",
        )],
        [InlineKeyboardButton(
            f"🎬 {F.sc('content mode')} · {content_mode.upper()}",
            callback_data="ga:s:content",
        )],
        [InlineKeyboardButton(
            f"🎯 {F.sc('flow editor')}",
            callback_data="ga:s:flow",
        )],
        [InlineKeyboardButton(
            f"📝 {F.sc('caption')}",
            callback_data="ga:s:caption",
        ), InlineKeyboardButton(
            f"🔘 {F.sc('buttons')}",
            callback_data="ga:s:buttons",
        )],
        [InlineKeyboardButton(
            f"👋 {F.sc('welcome')}",
            callback_data="ga:s:welcome",
        ), InlineKeyboardButton(
            f"⏱️ {F.sc('auto-delete')}",
            callback_data="ga:s:autodel",
        )],
        [InlineKeyboardButton(
            f"🚫 {F.sc('filters')}",
            callback_data="ga:s:filters",
        ), InlineKeyboardButton(
            f"📢 {F.sc('force-sub')}",
            callback_data="ga:s:fsub",
        )],
        [InlineKeyboardButton(
            f"🔐 {F.sc('verification')}",
            callback_data="ga:s:verify",
        ), InlineKeyboardButton(
            f"🛡️ {F.sc('security')}",
            callback_data="ga:s:security",
        )],
        [InlineKeyboardButton(
            f"📝 {F.sc('requests')}",
            callback_data="ga:s:requests",
        ), InlineKeyboardButton(
            f"🎬 {F.sc('metadata')}",
            callback_data="ga:s:metadata",
        )],
        [InlineKeyboardButton(
            f"📊 {F.sc('stats')}",
            callback_data="ga:s:stats",
        ), InlineKeyboardButton(
            f"📋 {F.sc('view all')}",
            callback_data="ga:s:view",
        )],
        [InlineKeyboardButton(
            f"♻️ {F.sc('reset all')}",
            callback_data="ga:s:reset",
        ), InlineKeyboardButton(
            f"{F.EMO['refresh']} {F.sc('refresh')}",
            callback_data="ga:s:refresh",
        )],
        [InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('close')}",
            callback_data="ga:close",
        )],
    ]
    return "\n".join(lines), InlineKeyboardMarkup(rows)


# ============================================================
# SEARCH SETTINGS
# ============================================================

async def render_search(chat_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await S.get_config(chat_id)
    search_on = cfg.get("search_enabled", True)
    pm_on = cfg.get("pm_search_enabled", True)

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"{F.EMO['search']} <b>{F.fb('SEARCH SETTINGS')}</b>",
        F.DIV, "",
        f"🔎 {F.sc('group search')} · {_on(search_on)}",
        f"💬 {F.sc('pm search')} · {_on(pm_on)}",
        "",
        F.DIV_S,
        f"📌 {F.sc('pm search = respond to PM text with search')}",
    ]

    rows = [
        [InlineKeyboardButton(
            f"🔎 {F.sc('group search')} · {'🟢' if search_on else '🔴'}",
            callback_data="ga:tog:search_enabled",
        )],
        [InlineKeyboardButton(
            f"💬 {F.sc('pm search')} · {'🟢' if pm_on else '🔴'}",
            callback_data="ga:tog:pm_search_enabled",
        )],
        [InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data="ga:back",
        ), InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('close')}",
            callback_data="ga:close",
        )],
    ]
    return "\n".join(lines), InlineKeyboardMarkup(rows)


# ============================================================
# CONTENT MODE
# ============================================================

async def render_content(chat_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await S.get_config(chat_id)
    mode = cfg.get("content_mode", "both")

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"🎬 <b>{F.fb('CONTENT MODE')}</b>",
        F.DIV, "",
        f"📌 {F.sc('what users can search in this group')}",
        "",
        f"🎬 {F.sc('movies only')}",
        f"📺 {F.sc('series only')}",
        f"🎬📺 {F.sc('both')}",
        "",
        f"🎯 {F.sc('current')} · <b>{mode.upper()}</b>",
    ]

    def _mark(v): return "✅ " if mode == v else ""

    rows = [
        [InlineKeyboardButton(
            f"{_mark('movies')}🎬 {F.sc('movies only')}",
            callback_data="ga:set:content:movies",
        )],
        [InlineKeyboardButton(
            f"{_mark('series')}📺 {F.sc('series only')}",
            callback_data="ga:set:content:series",
        )],
        [InlineKeyboardButton(
            f"{_mark('both')}🎬📺 {F.sc('both')}",
            callback_data="ga:set:content:both",
        )],
        [InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data="ga:back",
        ), InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('close')}",
            callback_data="ga:close",
        )],
    ]
    return "\n".join(lines), InlineKeyboardMarkup(rows)


# ============================================================
# FLOW EDITOR (per-group)
# ============================================================

async def render_flow(chat_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await S.get_config(chat_id)
    flow = cfg.get("flow") or {}

    step_order = [
        ("search",        "🔎", "Search"),
        ("spell_check",   "🔤", "Spell Check"),
        ("suggestions",   "💡", "Suggestions"),
        ("language",      "🌍", "Language"),
        ("season",        "📺", "Season"),
        ("episode",       "🎞️", "Episode"),
        ("quality",       "🎯", "Quality"),
        ("file_delivery", "📤", "Delivery"),
    ]

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"🎯 <b>{F.fb('FLOW EDITOR')}</b>",
        F.DIV, "",
        f"📌 {F.sc('customize the search flow for this group')}",
        "",
    ]

    rows = []
    for key, icon, name in step_order:
        s = flow.get(key, {})
        enabled = s.get("enabled", True)
        per_row = s.get("per_row", "—")
        icon_str = "🟢" if enabled else "🔴"
        lines.append(
            f"{icon_str} {icon} <b>{F.sc(name)}</b> · "
            f"<code>{per_row}/row</code>"
        )
        rows.append([InlineKeyboardButton(
            f"{icon_str} {icon} {name}",
            callback_data=f"ga:flow:{key}",
        )])

    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data="ga:back",
        ),
        InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('close')}",
            callback_data="ga:close",
        ),
    ])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def render_flow_step(chat_id: int, key: str) -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await S.get_config(chat_id)
    flow = cfg.get("flow") or {}
    s = flow.get(key, {})

    if not s:
        return await render_flow(chat_id)

    enabled = s.get("enabled", True)
    per_row = s.get("per_row", 2)
    auto_skip = s.get("auto_skip", True)

    labels = {
        "search": "Search", "spell_check": "Spell Check",
        "suggestions": "Suggestions", "language": "Language",
        "season": "Season", "episode": "Episode",
        "quality": "Quality", "file_delivery": "Delivery",
    }
    name = labels.get(key, key)

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"🎯 <b>{F.fb(f'{name.upper()} STEP')}</b>",
        F.DIV, "",
        f"⚙️ {F.sc('enabled')} · {_on(enabled)}",
        f"📊 {F.sc('layout')} · <b>{per_row}/row</b>",
        f"🔄 {F.sc('auto-skip')} · {_on(auto_skip)}",
    ]

    rows = [
        [InlineKeyboardButton(
            f"{'🔴 ' + F.sc('disable') if enabled else '🟢 ' + F.sc('enable')}",
            callback_data=f"ga:flow_tog:{key}",
        )],
    ]

    # Layout
    layout_row = []
    for n in (1, 2, 3, 4):
        mark = "✅ " if per_row == n else ""
        layout_row.append(InlineKeyboardButton(
            f"{mark}{n}/row",
            callback_data=f"ga:flow_row:{key}:{n}",
        ))
    rows.append(layout_row)

    # Auto-skip
    if key in ("language", "season"):
        rows.append([InlineKeyboardButton(
            f"🔄 {F.sc('auto-skip if one')} · {'🟢' if auto_skip else '🔴'}",
            callback_data=f"ga:flow_skip:{key}",
        )])

    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data="ga:s:flow",
        ),
        InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('close')}",
            callback_data="ga:close",
        ),
    ])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


# ============================================================
# CAPTION
# ============================================================

async def render_caption(chat_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await S.get_config(chat_id)
    tpl = cfg.get("caption_template")

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"📝 <b>{F.fb('CAPTION TEMPLATE')}</b>",
        F.DIV, "",
        f"📌 {F.sc('per-group caption for delivered files')}",
        "",
        f"🎯 {F.sc('status')} · "
        f"{'🟢 custom' if tpl else '⚪ global'}",
    ]
    if tpl:
        lines += ["", f"<code>{F.sc(str(tpl)[:400])}</code>"]

    lines += [
        "",
        F.DIV_S,
        f"📌 {F.sc('variables')}:",
        f"<code>{{title}}</code> <code>{{year}}</code>",
        f"<code>{{quality}}</code> <code>{{codec}}</code>",
        f"<code>{{audio}}</code> <code>{{subtitle}}</code>",
        f"<code>{{size}}</code> <code>{{season}}</code>",
        f"<code>{{episode}}</code> <code>{{bot_username}}</code>",
    ]

    rows = [
        [InlineKeyboardButton(
            f"✏️ {F.sc('edit caption')}",
            callback_data="ga:cap:edit",
        )],
    ]
    if tpl:
        rows.append([InlineKeyboardButton(
            f"♻️ {F.sc('reset to global')}",
            callback_data="ga:cap:reset",
        )])
    rows.append([InlineKeyboardButton(
        f"👁️ {F.sc('preview')}",
        callback_data="ga:cap:preview",
    )])
    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data="ga:back",
        ),
        InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('close')}",
            callback_data="ga:close",
        ),
    ])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


# ============================================================
# BUTTONS
# ============================================================

async def render_buttons(chat_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await S.get_config(chat_id)
    btns = cfg.get("result_buttons") or []
    per_row = int(cfg.get("buttons_per_row", 2))

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"🔘 <b>{F.fb('RESULT BUTTONS')}</b>",
        F.DIV, "",
        f"📊 {F.sc('total')} · <b>{len(btns)}</b>",
        f"📐 {F.sc('per row')} · <b>{per_row}</b>",
        "",
    ]

    for i, b in enumerate(btns, 1):
        icon = "🟢" if b.get("enabled", True) else "🔴"
        lines.append(
            f"<b>{i:02d}.</b> {icon} "
            f"{F.sc(str(b.get('name', '?'))[:36])}"
        )
        lines.append(f"    <code>{str(b.get('url', '?'))[:50]}</code>")

    rows = []
    for i, b in enumerate(btns[:8], 1):
        icon = "🟢" if b.get("enabled", True) else "🔴"
        rows.append([InlineKeyboardButton(
            f"{icon} {i}. {str(b.get('name', '?'))[:26]}",
            callback_data=f"ga:btn:view:{i-1}",
        )])

    rows.append([InlineKeyboardButton(
        f"➕ {F.sc('add button')}",
        callback_data="ga:btn:add",
    )])

    per_row_row = []
    for n in (1, 2, 3):
        mark = "✅ " if per_row == n else ""
        per_row_row.append(InlineKeyboardButton(
            f"{mark}{n}/row",
            callback_data=f"ga:btn_row:{n}",
        ))
    rows.append(per_row_row)

    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data="ga:back",
        ),
        InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('close')}",
            callback_data="ga:close",
        ),
    ])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


async def render_button_view(chat_id: int, idx: int) -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await S.get_config(chat_id)
    btns = cfg.get("result_buttons") or []
    if idx < 0 or idx >= len(btns):
        return await render_buttons(chat_id)
    b = btns[idx]
    enabled = b.get("enabled", True)

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"🔘 <b>{F.fb('BUTTON DETAIL')}</b>",
        F.DIV, "",
        f"📛 {F.sc('name')} · <b>{F.sc(str(b.get('name','?'))[:60])}</b>",
        f"🔗 {F.sc('url')} · <code>{str(b.get('url','?'))[:60]}</code>",
        f"⚙️ {F.sc('status')} · {_on(enabled)}",
    ]

    rows = [
        [InlineKeyboardButton(
            f"{'🔴 ' + F.sc('disable') if enabled else '🟢 ' + F.sc('enable')}",
            callback_data=f"ga:btn:tog:{idx}",
        )],
        [
            InlineKeyboardButton(
                f"✏️ {F.sc('edit name')}",
                callback_data=f"ga:btn_edit_name:{idx}",
            ),
            InlineKeyboardButton(
                f"🔗 {F.sc('edit url')}",
                callback_data=f"ga:btn_edit_url:{idx}",
            ),
        ],
        [InlineKeyboardButton(
            f"🗑️ {F.sc('delete')}",
            callback_data=f"ga:btn_del:{idx}",
        )],
        [
            InlineKeyboardButton(
                f"{F.EMO['back']} {F.sc('back')}",
                callback_data="ga:s:buttons",
            ),
            InlineKeyboardButton(
                f"{F.EMO['cross']} {F.sc('close')}",
                callback_data="ga:close",
            ),
        ],
    ]
    return "\n".join(lines), InlineKeyboardMarkup(rows)


# ============================================================
# WELCOME
# ============================================================

async def render_welcome(chat_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await S.get_config(chat_id)
    w_on = cfg.get("welcome_enabled", False)
    w_text = cfg.get("welcome_text")
    ad_on = cfg.get("welcome_auto_delete", True)
    ad_secs = cfg.get("welcome_delete_after", 600)

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"👋 <b>{F.fb('WELCOME MESSAGE')}</b>",
        F.DIV, "",
        f"📢 {F.sc('enabled')} · {_on(w_on)}",
        f"⏱️ {F.sc('auto-delete')} · {_on(ad_on)}",
        f"⏳ {F.sc('delete after')} · <b>{ad_secs}s</b>",
        "",
    ]
    if w_text:
        lines += [f"📝 {F.sc('current message')}:",
                  f"<code>{F.sc(str(w_text)[:300])}</code>"]

    rows = [
        [InlineKeyboardButton(
            f"{'🔴 ' + F.sc('disable') if w_on else '🟢 ' + F.sc('enable')}",
            callback_data="ga:w_tog",
        )],
        [InlineKeyboardButton(
            f"✏️ {F.sc('edit text')}",
            callback_data="ga:w_edit",
        )],
        [InlineKeyboardButton(
            f"⏱️ {F.sc('auto-delete')} · {'🟢' if ad_on else '🔴'}",
            callback_data="ga:w_adtog",
        )],
        [
            InlineKeyboardButton(
                f"{F.EMO['back']} {F.sc('back')}",
                callback_data="ga:back",
            ),
            InlineKeyboardButton(
                f"{F.EMO['cross']} {F.sc('close')}",
                callback_data="ga:close",
            ),
        ],
    ]
    return "\n".join(lines), InlineKeyboardMarkup(rows)


# ============================================================
# AUTO-DELETE
# ============================================================

async def render_autodel(chat_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await S.get_config(chat_id)
    ad = cfg.get("auto_delete") or {}

    bot_on = ad.get("bot_messages", True)
    bot_timer = ad.get("bot_timer", 600)
    user_on = ad.get("user_messages", True)
    keep_n = ad.get("keep_last_n", 10)
    cmd_on = ad.get("command_messages", True)

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"⏱️ <b>{F.fb('AUTO-DELETE')}</b>",
        F.DIV, "",
        f"🤖 {F.sc('bot messages')} · {_on(bot_on)}",
        f"⏳ {F.sc('bot timer')} · <b>{bot_timer}s</b>",
        f"👤 {F.sc('user messages')} · {_on(user_on)}",
        f"🔢 {F.sc('keep last')} · <b>{keep_n}</b>",
        f"⌨️ {F.sc('command messages')} · {_on(cmd_on)}",
        "",
        F.DIV_S,
        f"📌 {F.sc('bot = delete our sent files/messages')}",
        f"📌 {F.sc('user = clean up user messages')}",
    ]

    rows = [
        [InlineKeyboardButton(
            f"🤖 {F.sc('bot messages')} · {'🟢' if bot_on else '🔴'}",
            callback_data="ga:ad_tog:bot_messages",
        )],
    ]

    # Bot timer picker
    timer_row = []
    for secs, label in [(60, "1m"), (300, "5m"), (600, "10m"),
                        (1800, "30m"), (3600, "1h"), (0, "OFF")]:
        mark = "✅ " if bot_timer == secs else ""
        timer_row.append(InlineKeyboardButton(
            f"{mark}{label}",
            callback_data=f"ga:ad_timer:{secs}",
        ))
    rows.append(timer_row)

    rows.append([InlineKeyboardButton(
        f"👤 {F.sc('user messages')} · {'🟢' if user_on else '🔴'}",
        callback_data="ga:ad_tog:user_messages",
    )])

    # Keep-last picker
    keep_row = []
    for n in (5, 10, 20, 50):
        mark = "✅ " if keep_n == n else ""
        keep_row.append(InlineKeyboardButton(
            f"{mark}{n}",
            callback_data=f"ga:ad_keep:{n}",
        ))
    rows.append(keep_row)

    rows.append([InlineKeyboardButton(
        f"⌨️ {F.sc('command messages')} · {'🟢' if cmd_on else '🔴'}",
        callback_data="ga:ad_tog:command_messages",
    )])

    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data="ga:back",
        ),
        InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('close')}",
            callback_data="ga:close",
        ),
    ])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


# ============================================================
# FILTERS
# ============================================================

async def render_filters(chat_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await S.get_config(chat_id)
    filt = cfg.get("filters") or {}

    bl_on = filt.get("banned_links", True)
    bf_on = filt.get("block_forward", False)
    bm_on = filt.get("block_media", False)
    words = filt.get("banned_words") or []

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"🚫 <b>{F.fb('MANUAL FILTERS')}</b>",
        F.DIV, "",
        f"🔗 {F.sc('block links')} · {_on(bl_on)}",
        f"➡️ {F.sc('block forwards')} · {_on(bf_on)}",
        f"📎 {F.sc('block media')} · {_on(bm_on)}",
        f"🔤 {F.sc('banned words')} · <b>{len(words)}</b>",
        "",
        F.DIV_S,
        f"📌 {F.sc('blocked users are not affected')}",
    ]

    rows = [
        [InlineKeyboardButton(
            f"🔗 {F.sc('links')} · {'🟢' if bl_on else '🔴'}",
            callback_data="ga:flt_tog:banned_links",
        ), InlineKeyboardButton(
            f"➡️ {F.sc('forwards')} · {'🟢' if bf_on else '🔴'}",
            callback_data="ga:flt_tog:block_forward",
        )],
        [InlineKeyboardButton(
            f"📎 {F.sc('media')} · {'🟢' if bm_on else '🔴'}",
            callback_data="ga:flt_tog:block_media",
        )],
        [InlineKeyboardButton(
            f"🔤 {F.sc('banned words')} ({len(words)})",
            callback_data="ga:flt_words",
        )],
        [InlineKeyboardButton(
            f"➕ {F.sc('add word')}",
            callback_data="ga:flt_add",
        ), InlineKeyboardButton(
            f"🗑️ {F.sc('clear words')}",
            callback_data="ga:flt_clear",
        )],
        [
            InlineKeyboardButton(
                f"{F.EMO['back']} {F.sc('back')}",
                callback_data="ga:back",
            ),
            InlineKeyboardButton(
                f"{F.EMO['cross']} {F.sc('close')}",
                callback_data="ga:close",
            ),
        ],
    ]
    return "\n".join(lines), InlineKeyboardMarkup(rows)


# ============================================================
# FORCE-SUB
# ============================================================

async def render_fsub(chat_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await S.get_config(chat_id)
    f = cfg.get("fsub") or {}
    enabled = f.get("enabled", False)
    chans = f.get("channels") or []

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"📢 <b>{F.fb('FORCE SUBSCRIPTION')}</b>",
        F.DIV, "",
        f"⚙️ {F.sc('enabled')} · {_on(enabled)}",
        f"📊 {F.sc('channels')} · <b>{len(chans)}</b>",
        "",
    ]
    for c in chans[:5]:
        lines.append(f"• <code>{c}</code>")

    rows = [
        [InlineKeyboardButton(
            f"{'🔴 ' + F.sc('disable') if enabled else '🟢 ' + F.sc('enable')}",
            callback_data="ga:fs_tog",
        )],
        [InlineKeyboardButton(
            f"➕ {F.sc('add channel')}",
            callback_data="ga:fs_add",
        )],
    ]
    if chans:
        rows.append([InlineKeyboardButton(
            f"🗑️ {F.sc('remove one')}",
            callback_data="ga:fs_rm_menu",
        )])
    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data="ga:back",
        ),
        InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('close')}",
            callback_data="ga:close",
        ),
    ])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


# ============================================================
# VERIFY
# ============================================================

async def render_verify(chat_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await S.get_config(chat_id)
    v = cfg.get("verify") or {}
    enabled = v.get("enabled", False)
    shortener = v.get("shortener_url")
    vtime = v.get("verify_time", 1200)

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"🔐 <b>{F.fb('VERIFICATION')}</b>",
        F.DIV, "",
        f"⚙️ {F.sc('enabled')} · {_on(enabled)}",
        f"🔗 {F.sc('shortener')} · "
        f"<code>{shortener or 'not set'}</code>",
        f"⏱️ {F.sc('verify time')} · <b>{vtime}s</b>",
    ]

    rows = [
        [InlineKeyboardButton(
            f"{'🔴 ' + F.sc('disable') if enabled else '🟢 ' + F.sc('enable')}",
            callback_data="ga:v_tog",
        )],
        [InlineKeyboardButton(
            f"🔗 {F.sc('set shortener')}",
            callback_data="ga:v_url",
        )],
        [InlineKeyboardButton(
            f"⏱️ {F.sc('verify time')}",
            callback_data="ga:v_time",
        )],
        [
            InlineKeyboardButton(
                f"{F.EMO['back']} {F.sc('back')}",
                callback_data="ga:back",
            ),
            InlineKeyboardButton(
                f"{F.EMO['cross']} {F.sc('close')}",
                callback_data="ga:close",
            ),
        ],
    ]
    return "\n".join(lines), InlineKeyboardMarkup(rows)


# ============================================================
# SECURITY
# ============================================================

async def render_security(chat_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await S.get_config(chat_id)
    s = cfg.get("security") or {}

    url_on = s.get("url_blocking", True)
    tg_on = s.get("telegram_links", True)
    admin_bypass = s.get("admin_bypass", True)
    flood_on = s.get("search_flood_control", True)
    search_limit = s.get("search_limit", 5)

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"🛡️ <b>{F.fb('SECURITY')}</b>",
        F.DIV, "",
        f"🌐 {F.sc('url blocking')} · {_on(url_on)}",
        f"🔗 {F.sc('telegram links')} · {_on(tg_on)}",
        f"👑 {F.sc('admin bypass')} · {_on(admin_bypass)}",
        f"⚠️ {F.sc('flood control')} · {_on(flood_on)}",
        f"📊 {F.sc('search limit')} · <b>{search_limit}/min</b>",
    ]

    rows = [
        [
            InlineKeyboardButton(
                f"🌐 {F.sc('urls')} · {'🟢' if url_on else '🔴'}",
                callback_data="ga:sec:url_blocking",
            ),
            InlineKeyboardButton(
                f"🔗 {F.sc('tg links')} · {'🟢' if tg_on else '🔴'}",
                callback_data="ga:sec:telegram_links",
            ),
        ],
        [
            InlineKeyboardButton(
                f"👑 {F.sc('admin bypass')} · {'🟢' if admin_bypass else '🔴'}",
                callback_data="ga:sec:admin_bypass",
            ),
        ],
        [
            InlineKeyboardButton(
                f"⚠️ {F.sc('flood')} · {'🟢' if flood_on else '🔴'}",
                callback_data="ga:sec:search_flood_control",
            ),
        ],
        [
            InlineKeyboardButton(
                f"{F.EMO['back']} {F.sc('back')}",
                callback_data="ga:back",
            ),
            InlineKeyboardButton(
                f"{F.EMO['cross']} {F.sc('close')}",
                callback_data="ga:close",
            ),
        ],
    ]
    return "\n".join(lines), InlineKeyboardMarkup(rows)


# ============================================================
# REQUESTS
# ============================================================

async def render_requests(chat_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await S.get_config(chat_id)
    r = cfg.get("requests") or {}
    en = r.get("enabled", True)
    pm_upd = r.get("user_pm_update", True)
    dup_chk = r.get("duplicate_check", True)
    channel = r.get("channel")

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"📝 <b>{F.fb('REQUESTS')}</b>",
        F.DIV, "",
        f"⚙️ {F.sc('enabled')} · {_on(en)}",
        f"💬 {F.sc('pm update')} · {_on(pm_upd)}",
        f"🔁 {F.sc('dup check')} · {_on(dup_chk)}",
        f"📢 {F.sc('channel')} · <code>{channel or 'global'}</code>",
    ]

    rows = [
        [InlineKeyboardButton(
            f"⚙️ {F.sc('enabled')} · {'🟢' if en else '🔴'}",
            callback_data="ga:req_tog:enabled",
        )],
        [
            InlineKeyboardButton(
                f"💬 {F.sc('pm update')} · {'🟢' if pm_upd else '🔴'}",
                callback_data="ga:req_tog:user_pm_update",
            ),
            InlineKeyboardButton(
                f"🔁 {F.sc('dup check')} · {'🟢' if dup_chk else '🔴'}",
                callback_data="ga:req_tog:duplicate_check",
            ),
        ],
        [InlineKeyboardButton(
            f"📢 {F.sc('set channel')}",
            callback_data="ga:req_channel",
        )],
        [
            InlineKeyboardButton(
                f"{F.EMO['back']} {F.sc('back')}",
                callback_data="ga:back",
            ),
            InlineKeyboardButton(
                f"{F.EMO['cross']} {F.sc('close')}",
                callback_data="ga:close",
            ),
        ],
    ]
    return "\n".join(lines), InlineKeyboardMarkup(rows)


# ============================================================
# METADATA
# ============================================================

async def render_metadata(chat_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await S.get_config(chat_id)
    m = cfg.get("metadata") or {}

    fields = [
        ("poster", "🖼️", "Poster"),
        ("rating", "⭐", "Rating"),
        ("genre", "🎭", "Genre"),
        ("year", "📅", "Year"),
        ("language", "🌐", "Language"),
    ]

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"🎬 <b>{F.fb('METADATA DISPLAY')}</b>",
        F.DIV, "",
        f"📌 {F.sc('what to show with search results')}",
        "",
    ]

    for k, icon, label in fields:
        v = m.get(k, True)
        lines.append(f"{icon} {F.sc(label)} · {_on(v)}")

    rows = []
    for k, icon, label in fields:
        v = m.get(k, True)
        rows.append([InlineKeyboardButton(
            f"{icon} {label} · {'🟢' if v else '🔴'}",
            callback_data=f"ga:meta_tog:{k}",
        )])

    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data="ga:back",
        ),
        InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('close')}",
            callback_data="ga:close",
        ),
    ])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


# ============================================================
# STATS
# ============================================================

async def render_stats(chat_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await S.get_config(chat_id)
    s = cfg.get("stats") or {}

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"📊 <b>{F.fb('GROUP STATS')}</b>",
        F.DIV, "",
        f"🔎 {F.sc('searches today')} · "
        f"<b>{FM.num(s.get('searches_today', 0))}</b>",
        f"✅ {F.sc('results found')} · "
        f"<b>{FM.num(s.get('results_found', 0))}</b>",
        f"❌ {F.sc('not found')} · "
        f"<b>{FM.num(s.get('not_found', 0))}</b>",
        f"📤 {F.sc('files sent')} · "
        f"<b>{FM.num(s.get('files_sent', 0))}</b>",
    ]

    rows = [
        [InlineKeyboardButton(
            f"🔄 {F.sc('refresh')}",
            callback_data="ga:s:stats",
        )],
        [InlineKeyboardButton(
            f"🗑️ {F.sc('reset stats')}",
            callback_data="ga:stats_reset",
        )],
        [
            InlineKeyboardButton(
                f"{F.EMO['back']} {F.sc('back')}",
                callback_data="ga:back",
            ),
            InlineKeyboardButton(
                f"{F.EMO['cross']} {F.sc('close')}",
                callback_data="ga:close",
            ),
        ],
    ]
    return "\n".join(lines), InlineKeyboardMarkup(rows)


# ============================================================
# VIEW ALL
# ============================================================

async def render_view(chat_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await S.get_config(chat_id)

    ad = cfg.get("auto_delete") or {}
    fsub = cfg.get("fsub") or {}

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"📋 <b>{F.fb('ALL SETTINGS')}</b>",
        F.DIV, "",
        f"🎬 content · <b>{cfg.get('content_mode','both').upper()}</b>",
        f"🔎 search · {_on(cfg.get('search_enabled', True))}",
        f"💬 pm search · {_on(cfg.get('pm_search_enabled', True))}",
        f"👋 welcome · {_on(cfg.get('welcome_enabled', False))}",
        f"⏱️ auto-delete · <b>{ad.get('bot_timer', 600)}s</b>",
        f"🔢 keep last · <b>{ad.get('keep_last_n', 10)}</b>",
        f"📢 fsub · <b>{len(fsub.get('channels') or [])}</b>",
        f"📝 caption · "
        f"{'custom' if cfg.get('caption_template') else 'global'}",
        f"🔘 buttons · <b>{len(cfg.get('result_buttons') or [])}</b>",
        f"🚫 filters · <b>{len((cfg.get('filters') or {}).get('banned_words') or [])}</b>",
    ]

    rows = [
        [
            InlineKeyboardButton(
                f"{F.EMO['back']} {F.sc('back')}",
                callback_data="ga:back",
            ),
            InlineKeyboardButton(
                f"{F.EMO['cross']} {F.sc('close')}",
                callback_data="ga:close",
            ),
        ],
    ]
    return "\n".join(lines), InlineKeyboardMarkup(rows)


# ============================================================
# RESET
# ============================================================

async def render_reset(chat_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"♻️ <b>{F.fb('RESET ALL SETTINGS')}</b>",
        F.DIV, "",
        f"{F.EMO['warn']} {F.sc('this will restore all defaults')}",
        "",
        f"📌 {F.sc('title + username are kept')}",
        f"📌 {F.sc('everything else is reset')}",
    ]

    rows = [
        [InlineKeyboardButton(
            f"♻️ {F.sc('yes, reset all')}",
            callback_data="ga:reset_do",
        )],
        [InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('cancel')}",
            callback_data="ga:back",
        )],
    ]
    return "\n".join(lines), InlineKeyboardMarkup(rows)


__all__ = [
    "render_main", "render_search", "render_content",
    "render_flow", "render_flow_step",
    "render_caption", "render_buttons", "render_button_view",
    "render_welcome", "render_autodel", "render_filters",
    "render_fsub", "render_verify", "render_security",
    "render_requests", "render_metadata", "render_stats",
    "render_view", "render_reset",
]
