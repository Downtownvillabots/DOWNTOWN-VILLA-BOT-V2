# ============================================================
# 🏨 DOWNTOWN VILLA — BROADCAST KEYBOARDS
# ============================================================

from __future__ import annotations
from typing import Any, Dict, List

from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from plugins.broadcast.config import (
    sc, AUTODELETE_PRESETS, AUTODELETE_SECONDS,
    _fmt_duration,
)


def cb(*parts) -> str:
    return "bc:" + ":".join(str(p) for p in parts)


def kb_main(user_count, group_count, chan_count,
            btn_count, autodelete_count=0):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"📢 CHANNELS ({chan_count})",
            callback_data="bc:channels")],
        [InlineKeyboardButton(
            f"👥 GROUPS ({group_count})",
            callback_data="bc:groups")],
        [InlineKeyboardButton(
            f"👤 USERS ({user_count})",
            callback_data="bc:users_menu")],
        [InlineKeyboardButton(
            "📝 DEFAULT CAPTION", callback_data="bc:caption"),
         InlineKeyboardButton(
            f"🔘 DEFAULT BUTTONS ({btn_count})",
            callback_data="bc:buttons")],
        [InlineKeyboardButton(
            "📚 TEMPLATES", callback_data="bc:caption_lib"),
         InlineKeyboardButton(
            "🎯 MANUAL", callback_data="bc:manual")],
        [InlineKeyboardButton(
            f"⏱️ AUTO-DELETE ({autodelete_count})",
            callback_data="bc:autodelete")],
        [InlineKeyboardButton(
            "📈 STATS", callback_data="bc:stats"),
         InlineKeyboardButton(
            "📊 HISTORY", callback_data="bc:history")],
        [InlineKeyboardButton(
            "💾 EXPORT", callback_data="bc:export"),
         InlineKeyboardButton(
            "📥 IMPORT", callback_data="bc:import")],
        [InlineKeyboardButton(
            "🔄 REFRESH", callback_data="bc:main"),
         InlineKeyboardButton(
            "❌ CLOSE", callback_data="bc:close")],
    ])


def kb_channels(channels: List[Dict[str, Any]]):
    rows = []
    for c in channels:
        title = (c.get("title") or "?")[:38]
        cid = c.get("chat_id")
        markers = ""
        if c.get("caption") is not None:
            markers += "📝"
        if c.get("buttons") is not None:
            markers += "🔘"
        if c.get("primary"):
            markers = "⭐" + markers
        if not markers:
            markers = "⚪"
        rows.append([InlineKeyboardButton(
            f"{markers} 📢 {title}",
            callback_data=f"bc:ch_view:{cid}")])
    rows.append([
        InlineKeyboardButton("➕ ADD CHANNEL",
                             callback_data="bc:ch_add"),
        InlineKeyboardButton("🔄 REFRESH",
                             callback_data="bc:channels"),
    ])
    rows.append([
        InlineKeyboardButton("◀️ BACK", callback_data="bc:main"),
        InlineKeyboardButton("❌ CLOSE", callback_data="bc:close"),
    ])
    return InlineKeyboardMarkup(rows)


def kb_channel_view(chat_id):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "📝 EDIT CAPTION",
            callback_data=f"bc:ch_cap:{chat_id}"),
         InlineKeyboardButton(
            "🔘 EDIT BUTTONS",
            callback_data=f"bc:ch_btn:{chat_id}")],
        [InlineKeyboardButton(
            "⭐ TOGGLE PRIMARY",
            callback_data=f"bc:ch_primary:{chat_id}")],
        [InlineKeyboardButton(
            "♻️ RESET TO DEFAULTS",
            callback_data=f"bc:ch_reset:{chat_id}")],
        [InlineKeyboardButton(
            "🗑️ REMOVE CHANNEL",
            callback_data=f"bc:ch_rm:{chat_id}")],
        [InlineKeyboardButton(
            "◀️ BACK", callback_data="bc:channels"),
         InlineKeyboardButton(
            "❌ CLOSE", callback_data="bc:close")],
    ])


def kb_caption():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ EDIT CAPTION",
                              callback_data="bc:caption_edit")],
        [InlineKeyboardButton("📚 LOAD TEMPLATE",
                              callback_data="bc:caption_lib")],
        [InlineKeyboardButton("♻️ RESET DEFAULT",
                              callback_data="bc:caption_reset")],
        [InlineKeyboardButton("👁️ PREVIEW",
                              callback_data="bc:caption_preview")],
        [InlineKeyboardButton("◀️ BACK", callback_data="bc:main"),
         InlineKeyboardButton("❌ CLOSE", callback_data="bc:close")],
    ])


def kb_buttons(buttons: List[Dict[str, Any]]):
    rows = []
    for i, b in enumerate(buttons, 1):
        name = (b.get("name") or "?")[:40]
        rows.append([InlineKeyboardButton(
            f"{i}. {name}",
            callback_data=f"bc:btn_view:{i-1}")])
    rows.append([InlineKeyboardButton(
        "➕ ADD BUTTON", callback_data="bc:btn_add")])
    rows.append([
        InlineKeyboardButton("◀️ BACK", callback_data="bc:main"),
        InlineKeyboardButton("❌ CLOSE", callback_data="bc:close"),
    ])
    return InlineKeyboardMarkup(rows)


def kb_button_view(idx):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("✏️ EDIT NAME",
                              callback_data=f"bc:btn_edit_name:{idx}")],
        [InlineKeyboardButton("🔗 EDIT URL",
                              callback_data=f"bc:btn_edit_url:{idx}")],
        [InlineKeyboardButton("🗑️ REMOVE",
                              callback_data=f"bc:btn_rm:{idx}")],
        [InlineKeyboardButton("◀️ BACK", callback_data="bc:buttons"),
         InlineKeyboardButton("❌ CLOSE", callback_data="bc:close")],
    ])


def kb_users_menu(count):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"🚀 BROADCAST TO ALL ({count})",
            callback_data="bc:do_users")],
        [InlineKeyboardButton("◀️ BACK", callback_data="bc:main"),
         InlineKeyboardButton("❌ CLOSE", callback_data="bc:close")],
    ])


def kb_groups_menu(count):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"🚀 BROADCAST TO ALL ({count})",
            callback_data="bc:do_groups")],
        [InlineKeyboardButton("◀️ BACK", callback_data="bc:main"),
         InlineKeyboardButton("❌ CLOSE", callback_data="bc:close")],
    ])


# ─── WATCHER: destination picker ───
def kb_destination(sid: str, manual_target: int = 0):
    rows = []
    if manual_target:
        rows.append([InlineKeyboardButton(
            "🎯 SEND TO MANUAL TARGET",
            callback_data=f"bcsend:manual:{sid}:{manual_target}")])
    rows += [
        [InlineKeyboardButton(
            "📢 CHANNELS",
            callback_data=f"bcsend:ch:{sid}")],
        [InlineKeyboardButton(
            "👥 GROUPS",
            callback_data=f"bcsend:gr:{sid}")],
        [InlineKeyboardButton(
            "👤 USERS",
            callback_data=f"bcsend:us:{sid}")],
        [InlineKeyboardButton(
            "❌ CANCEL",
            callback_data=f"bcsend:no:{sid}")],
    ]
    return InlineKeyboardMarkup(rows)


def kb_destination_batch(sid: str, count: int):
    """Multi-file picker with USE ALL option."""
    rows = [
        [InlineKeyboardButton(
            f"🎯 USE ALL ({count} FILES)",
            callback_data=f"bcsend:all:{sid}")],
        [InlineKeyboardButton(
            "📢 CHANNELS",
            callback_data=f"bcsend:ch:{sid}")],
        [InlineKeyboardButton(
            "👥 GROUPS",
            callback_data=f"bcsend:gr:{sid}")],
        [InlineKeyboardButton(
            "👤 USERS",
            callback_data=f"bcsend:us:{sid}")],
        [InlineKeyboardButton(
            "❌ CANCEL",
            callback_data=f"bcsend:no:{sid}")],
    ]
    return InlineKeyboardMarkup(rows)


def kb_channel_picker(sid: str, channels: List[Dict[str, Any]]):
    rows = []
    for c in channels:
        title = (c.get("title") or "?")[:34]
        cid = c.get("chat_id")
        markers = ""
        if c.get("caption") is not None:
            markers += "📝"
        if c.get("buttons") is not None:
            markers += "🔘"
        if c.get("primary"):
            markers = "⭐" + markers
        if not markers:
            markers = "⚪"
        rows.append([InlineKeyboardButton(
            f"{markers} {title}",
            callback_data=f"bcsend:goto_ch:{sid}:{cid}")])
    rows.append([
        InlineKeyboardButton("🎯 SEND TO ALL",
                             callback_data=f"bcsend:goto_chall:{sid}"),
    ])
    rows.append([InlineKeyboardButton(
        "❌ CANCEL", callback_data=f"bcsend:no:{sid}")])
    return InlineKeyboardMarkup(rows)


def kb_confirm_groups(sid: str, total: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"✅ YES, SEND TO {total} GROUPS",
            callback_data=f"bcsend:goto_gr:{sid}")],
        [InlineKeyboardButton(
            "❌ CANCEL", callback_data=f"bcsend:no:{sid}")],
    ])


def kb_user_timer(sid: str):
    rows = []
    row = []
    for d, _, label in AUTODELETE_PRESETS:
        icon = "⏱️" if d else "♾️"
        row.append(InlineKeyboardButton(
            f"{icon} {label}",
            callback_data=f"bcsend:us_t:{sid}:{d}"))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(
        "❌ CANCEL", callback_data=f"bcsend:no:{sid}")])
    return InlineKeyboardMarkup(rows)


def kb_user_timer_confirm(sid: str, days: int, total: int):
    seconds = AUTODELETE_SECONDS.get(days, 0)
    label = "♾️ Never" if seconds == 0 else f"⏱️ {days} day(s)"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"✅ CONFIRM · {label}",
            callback_data=f"bcsend:us_go:{sid}:{days}")],
        [InlineKeyboardButton(
            "⬅️ CHANGE TIMER",
            callback_data=f"bcsend:us:{sid}")],
        [InlineKeyboardButton(
            "❌ CANCEL", callback_data=f"bcsend:no:{sid}")],
    ])


def kb_confirm_batch(sid: str, count: int, kind_label: str):
    """Confirm sending N files to all targets."""
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"✅ SEND ALL {count} FILES",
            callback_data=f"bcsend:batch_go:{sid}")],
        [InlineKeyboardButton(
            "❌ CANCEL", callback_data=f"bcsend:no:{sid}")],
    ])


def kb_cancel_session():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ CANCEL",
                             callback_data="bc:cancel_session")
    ]])


def kb_back(target: str = "bc:main"):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("◀️ BACK", callback_data=target),
        InlineKeyboardButton("❌ CLOSE", callback_data="bc:close"),
    ]])


def kb_batch(batch: Dict[str, Any], sc_fn) -> InlineKeyboardMarkup:
    """Multi-file toggle panel (posted in broadcast channel)."""
    files = batch["files"]
    sid = batch["sid"]
    selected = sum(1 for f in files if f["selected"])

    rows: List[List[InlineKeyboardButton]] = []

    # Toggle row — up to 5 per row
    row: List[InlineKeyboardButton] = []
    for i, f in enumerate(files):
        mark = "✅" if f["selected"] else "☐"
        row.append(InlineKeyboardButton(
            f"{mark} {i + 1}",
            callback_data=f"bcbatch:tog:{sid}:{i}",
        ))
        if len(row) == 5:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    # All / None
    rows.append([
        InlineKeyboardButton("✅ ALL", callback_data=f"bcbatch:all:{sid}"),
        InlineKeyboardButton("☐ NONE", callback_data=f"bcbatch:none:{sid}"),
    ])

    # Broadcast button (only when something is selected)
    if selected > 0:
        rows.append([InlineKeyboardButton(
            f"🚀 BROADCAST SELECTED ({selected})",
            callback_data=f"bcbatch:bcast:{sid}",
        )])

    rows.append([InlineKeyboardButton(
        "❌ CANCEL", callback_data=f"bcbatch:no:{sid}",
    )])

    return InlineKeyboardMarkup(rows)


def kb_conf_destination(sid: str) -> InlineKeyboardMarkup:
    """PM confirmation — pick destination type."""
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                "📢 CHANNELS",
                callback_data=f"bcconf:{sid}:dest:channels",
            ),
            InlineKeyboardButton(
                "👥 GROUPS",
                callback_data=f"bcconf:{sid}:dest:groups",
            ),
        ],
        [
            InlineKeyboardButton(
                "👤 USERS",
                callback_data=f"bcconf:{sid}:dest:users",
            ),
            InlineKeyboardButton(
                "🎯 MANUAL",
                callback_data=f"bcconf:{sid}:dest:manual",
            ),
        ],
        [InlineKeyboardButton(
            "❌ CANCEL",
            callback_data=f"bcconf:{sid}:cancel",
        )],
    ])


def kb_conf_channels(
    sid: str, channels: List[Dict[str, Any]]
) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = [
        [InlineKeyboardButton(
            "🎯 SEND TO ALL CHANNELS",
            callback_data=f"bcconf:{sid}:chall",
        )],
    ]
    for c in channels:
        title = (c.get("title") or "?")[:34]
        cid = c.get("chat_id")
        marks = ""
        if c.get("caption") is not None:
            marks += "📝"
        if c.get("buttons") is not None:
            marks += "🔘"
        if not marks:
            marks = "⚪"
        rows.append([InlineKeyboardButton(
            f"{marks} {title}",
            callback_data=f"bcconf:{sid}:ch:{cid}",
        )])
    rows.append([InlineKeyboardButton(
        "◀️ BACK", callback_data=f"bcconf:{sid}:back",
    )])
    return InlineKeyboardMarkup(rows)


def kb_conf_caption(sid: str, has_channel: bool) -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(
            "📄 USE FILE'S OWN CAPTION",
            callback_data=f"bcconf:{sid}:cap:own",
        )],
        [InlineKeyboardButton(
            "🌐 USE GLOBAL CAPTION",
            callback_data=f"bcconf:{sid}:cap:global",
        )],
    ]
    if has_channel:
        rows.append([InlineKeyboardButton(
            "📢 USE CHANNEL CAPTION",
            callback_data=f"bcconf:{sid}:cap:channel",
        )])
    rows.append([InlineKeyboardButton(
        "❌ CANCEL", callback_data=f"bcconf:{sid}:cancel",
    )])
    return InlineKeyboardMarkup(rows)


def kb_conf_timer(sid: str) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []
    for d, _, label in AUTODELETE_PRESETS:
        icon = "⏱️" if d else "♾️"
        row.append(InlineKeyboardButton(
            f"{icon} {label}",
            callback_data=f"bcconf:{sid}:timer:{d}",
        ))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(
        "❌ CANCEL", callback_data=f"bcconf:{sid}:cancel",
    )])
    return InlineKeyboardMarkup(rows)


def kb_conf_confirm(sid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🚀 SEND NOW", callback_data=f"bcconf:{sid}:send",
        )],
        [InlineKeyboardButton(
            "📝 CHANGE CAPTION MODE",
            callback_data=f"bcconf:{sid}:chcap",
        )],
        [InlineKeyboardButton(
            "⏱️ CHANGE TIMER",
            callback_data=f"bcconf:{sid}:chtimer",
        )],
        [InlineKeyboardButton(
            "❌ CANCEL", callback_data=f"bcconf:{sid}:cancel",
        )],
    ])


def kb_conf_preview(sid: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🚀 SEND NOW",
            callback_data=f"bcconf:{sid}:send",
        )],
        [InlineKeyboardButton(
            "📝 CHANGE CAPTION",
            callback_data=f"bcconf:{sid}:chcap",
        )],
        [InlineKeyboardButton(
            "⏱️ CHANGE TIMER",
            callback_data=f"bcconf:{sid}:chtimer",
        )],
        [InlineKeyboardButton(
            "◀️ BACK",
            callback_data=f"bcconf:{sid}:back",
        )],
        [InlineKeyboardButton(
            "❌ CANCEL",
            callback_data=f"bcconf:{sid}:cancel",
        )],
    ])

def kb_groups_list(groups: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = [
        [InlineKeyboardButton(
            f"🎯 SEND TO ALL ({len(groups)})",
            callback_data="bc:do_groups",
        )],
    ]
    for g in groups[:20]:
        gid = g.get("chat_id")
        title = str(g.get("title") or gid)[:32]
        rows.append([InlineKeyboardButton(
            f"👥 {title}",
            callback_data=f"bc:gr_view:{gid}",
        )])
    rows.append([
        InlineKeyboardButton("🔄 REFRESH", callback_data="bc:groups"),
        InlineKeyboardButton("◀️ BACK", callback_data="bc:main"),
    ])
    rows.append([InlineKeyboardButton("❌ CLOSE", callback_data="bc:close")])
    return InlineKeyboardMarkup(rows)


def kb_group_view(group: Dict[str, Any]) -> InlineKeyboardMarkup:
    gid = group.get("chat_id")
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "✏️ EDIT CAPTION",
            callback_data=f"bc:gr_cap:{gid}",
        )],
        [InlineKeyboardButton(
            "🔘 EDIT BUTTONS",
            callback_data=f"bc:gr_btn:{gid}",
        )],
        [InlineKeyboardButton(
            "⏱️ SET TIMER",
            callback_data=f"bc:gr_timer:{gid}",
        )],
        [InlineKeyboardButton(
            "🚀 SEND NOW",
            callback_data=f"bc:gr_send:{gid}",
        )],
        [InlineKeyboardButton(
            "◀️ BACK", callback_data="bc:groups",
        ),
         InlineKeyboardButton("❌ CLOSE", callback_data="bc:close")],
    ])


__all__ = [
    "cb", "kb_main", "kb_channels", "kb_channel_view",
    "kb_caption", "kb_buttons", "kb_button_view",
    "kb_users_menu", "kb_groups_menu",
    "kb_destination", "kb_destination_batch",
    "kb_channel_picker", "kb_confirm_groups",
    "kb_user_timer", "kb_user_timer_confirm",
    "kb_confirm_batch", "kb_cancel_session", "kb_back",
    "kb_batch", "kb_conf_destination", "kb_conf_channels",
    "kb_conf_caption", "kb_conf_timer", "kb_conf_confirm",
    "kb_conf_preview",
    "kb_groups_list", "kb_group_view",
]
