# ============================================================
# 🏨 DOWNTOWN VILLA — FLOW CONTROL CENTER (v2 — FULL)
# ============================================================
#
# Entry point: /admin → 🎯 Flow Editor
#
# Hierarchy:
#   Home → Category → Target → Flow → Step → Advanced
#
# Callback prefix: adm:flw_
#
# Editor covers:
#   • Flow reorder (⬆️⬇️ per step)
#   • Per-step enable/disable
#   • Per-row layout (1-4)
#   • Auto-skip if one
#   • Max items per step
#   • Spell check accuracy (threshold, corrections)
#   • IMDb/TMDB suggestion accuracy (min score, providers)
#   • Poster on/off
#   • Rating on/off
#   • Year on/off
#   • Genre on/off
#   • File name display (quality/size/name toggles)
#   • File list sort order
#   • Button name max length
#   • Caption editor (per-group)
#   • Caption preview
#   • Search cache TTL
#   • Flood control
#   • Reset to defaults
#
# ============================================================

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from core import config
from plugins.groups import state as GS
from utils import fonts as F
from utils import format as FM

logger = logging.getLogger(__name__)


# ============================================================
# SECTION 1 — AUTH
# ============================================================

def _is_admin(uid) -> bool:
    try:
        return int(uid) in [int(a) for a in config.ADMINS]
    except Exception:
        return False


# ============================================================
# SECTION 2 — CONSTANTS
# ============================================================

_FLOW_META = {
    "series_search": ("📺", "Series Search"),
    "movie_search":  ("🎬", "Movie Search"),
    "pm_search":     ("💬", "PM Search"),
    "broadcast":     ("📢", "Broadcast"),
}

_CATEGORY_META = {
    "channel": ("📢", "Channels"),
    "group":   ("👥", "Groups"),
    "pm":      ("💬", "PM"),
    "global":  ("🌐", "Global Defaults"),
}

_STEP_META = {
    "base_search":   ("🔎", "Search"),
    "spell_check":   ("🔤", "Spell Check"),
    "suggestions":   ("💡", "Suggestions"),
    "language":      ("🌍", "Language"),
    "season":        ("📺", "Season"),
    "episode":       ("🎞️", "Episode"),
    "quality":       ("🎯", "Quality"),
    "file_delivery": ("📤", "Delivery"),
}

_MANDATORY = {"base_search", "file_delivery"}


def _flow_icon(name: str) -> Tuple[str, str]:
    return _FLOW_META.get(name, ("🎯", name))


def _cat_icon(cat: str) -> Tuple[str, str]:
    return _CATEGORY_META.get(cat, ("🎯", cat))


def _step_icon(key: str) -> Tuple[str, str]:
    return _STEP_META.get(key, ("⚙️", key))


# ============================================================
# SECTION 3 — DATA SOURCES
# ============================================================

async def _list_groups() -> List[Dict[str, Any]]:
    try:
        docs = await GS.list_groups(limit=50)
        out = []
        for d in docs:
            cid = d.get("chat_id")
            if not cid:
                continue
            title = str(d.get("title") or "").strip()
            username = str(d.get("username") or "").strip().lstrip("@")
            if (not title or title.lstrip("-").isdigit()
                    or title.casefold() in {"group", "channel"}):
                title = f"@{username}" if username else "Group"
            out.append({
                "chat_id": int(cid),
                "title": title[:60],
            })
        return out
    except Exception:
        return []


async def _list_channels() -> List[Dict[str, Any]]:
    try:
        from plugins.indexing import backward as BW
        docs = await BW.list_registered_channels()
        out = []
        for d in docs:
            cid = d.get("chat_id")
            if not cid:
                continue
            title = str(d.get("title") or "").strip()
            username = str(d.get("username") or "").strip().lstrip("@")
            if (not title or title.lstrip("-").isdigit()
                    or title.casefold() in {"group", "channel"}):
                title = f"@{username}" if username else "Channel"
            out.append({
                "chat_id": int(cid),
                "title": title[:60],
                "enabled": bool(d.get("enabled", True)),
            })
        return out
    except Exception:
        return []


async def _target_label(cat: str, cid: int) -> str:
    if cid == 0:
        return "Global Defaults"
    if cat == "group":
        for g in await _list_groups():
            if g["chat_id"] == cid:
                return g["title"]
    if cat == "channel":
        for ch in await _list_channels():
            if ch["chat_id"] == cid:
                return ch["title"]
    return {
        "group": "Group",
        "channel": "Channel",
        "pm": "PM Search",
        "global": "Global Defaults",
    }.get(cat, "Target")


def _flows_for_category(cat: str) -> List[str]:
    if cat == "group":
        return ["series_search", "movie_search", "pm_search"]
    if cat == "channel":
        return ["movie_search", "series_search"]
    if cat == "pm":
        return ["pm_search"]
    if cat == "global":
        return ["series_search", "movie_search", "pm_search", "broadcast"]
    return []


# ============================================================
# SECTION 4 — HEADER / FOOTER
# ============================================================

def _header(emoji: str, title: str) -> str:
    return "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"{emoji} <b>{F.fb(title)}</b>",
        F.DIV,
        "",
    ])


def _back_close(back_cb: str = "adm:flw_home", back_label: str = "back"):
    return [[
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc(back_label)}",
            callback_data=back_cb,
        ),
        InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('close')}",
            callback_data="adm:close",
        ),
    ]]


def _on(v) -> str:
    return "🟢 on" if v else "🔴 off"


# ============================================================
# SECTION 5 — HOME
# ============================================================

async def build() -> Tuple[str, InlineKeyboardMarkup]:
    return await render_home()


async def render_home() -> Tuple[str, InlineKeyboardMarkup]:
    groups = await _list_groups()
    channels = await _list_channels()

    text = "\n".join([
        _header("🎯", "FLOW CONTROL CENTER"),
        f"📌 {F.sc('pick a category to customize')}",
        "",
        f"{F.EMO['info']} {F.sc('edit search flow per target')}",
        f"{F.EMO['info']} {F.sc('applies instantly — no restart')}",
        "",
        F.DIV_S,
        f"📢 {F.sc('channels')} · <b>{len(channels)}</b>",
        f"👥 {F.sc('groups')} · <b>{len(groups)}</b>",
        f"💬 {F.sc('pm search')} · <b>1</b>",
        f"🌐 {F.sc('global defaults')} · <b>4 flows</b>",
        "",
        f"🕒 <code>{FM.datetime_()}</code>",
    ])

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"📢 {F.sc('channels')} ({len(channels)})",
            callback_data="adm:flw_cat:channel")],
        [InlineKeyboardButton(
            f"👥 {F.sc('groups')} ({len(groups)})",
            callback_data="adm:flw_cat:group")],
        [InlineKeyboardButton(
            f"💬 {F.sc('pm search')}",
            callback_data="adm:flw_cat:pm")],
        [InlineKeyboardButton(
            f"🌐 {F.sc('global defaults')}",
            callback_data="adm:flw_cat:global")],
        _back_close("adm:home", "admin")[0],
    ])

    return "\n".join(text), kb


# ============================================================
# SECTION 6 — CATEGORY
# ============================================================

async def render_category(cat: str) -> Tuple[str, InlineKeyboardMarkup]:
    emoji, label = _cat_icon(cat)

    if cat in ("pm", "global"):
        return await render_target(cat, 0)

    if cat == "group":
        items = await _list_groups()
        empty_msg = "no groups registered yet"
        hint = "add bot to a group → /settings"
    elif cat == "channel":
        items = await _list_channels()
        empty_msg = "no channels registered yet"
        hint = "add bot as admin to a channel"
    else:
        items = []
        empty_msg = "unknown category"
        hint = ""

    text_lines = [
        _header(emoji, label.upper()),
        f"📊 {F.sc('total')} · <b>{len(items)}</b>",
        "",
    ]

    rows: List[List[InlineKeyboardButton]] = []

    if not items:
        text_lines.append(f"⚪ {F.sc(empty_msg)}")
        if hint:
            text_lines.append(f"📌 {F.sc(hint)}")
    else:
        for i, it in enumerate(items[:30], 1):
            cid = it["chat_id"]
            title = it["title"]
            marker = "🟢" if it.get("enabled", True) else "🔴"
            text_lines.append(f"{marker} <b>{i:02d}.</b> {F.sc(title[:45])}")
            rows.append([InlineKeyboardButton(
                f"{marker} {title[:36]}",
                callback_data=f"adm:flw_target:{cat}:{cid}",
            )])

    rows.append(_back_close("adm:flw_home", "back")[0])
    return "\n".join(text_lines)[:4000], InlineKeyboardMarkup(rows)


# ============================================================
# SECTION 7 — TARGET
# ============================================================

async def render_target(cat: str, cid: int) -> Tuple[str, InlineKeyboardMarkup]:
    emoji, cat_label = _cat_icon(cat)
    target = await _target_label(cat, cid)

    text_lines = [
        _header(emoji, f"{cat_label.upper()} · {target[:40]}"),
        "",
        f"📌 {F.sc('pick a flow to customize')}",
        "",
    ]

    rows: List[List[InlineKeyboardButton]] = []
    flow_names = _flows_for_category(cat)

    for name in flow_names:
        icon, label = _flow_icon(name)
        try:
            from core.flow_engine import get_flow_for
            flow = await get_flow_for(cid, name)
            steps = flow.all_steps_sorted() if hasattr(flow, "all_steps_sorted") else []
            enabled = sum(1 for s in steps if s.get("enabled", True))
            total = len(steps)
        except Exception:
            enabled = total = 0

        text_lines.append(
            f"{icon} <b>{F.sc(label)}</b> · "
            f"<code>{enabled}/{total}</code> steps"
        )

        rows.append([InlineKeyboardButton(
            f"{icon} {label} · {enabled}/{total}",
            callback_data=f"adm:flw_edit:{cat}:{cid}:{name}",
        )])

    rows.append(_back_close(f"adm:flw_cat:{cat}", "back")[0])
    return "\n".join(text_lines)[:4000], InlineKeyboardMarkup(rows)


# ============================================================
# SECTION 8 — FLOW EDITOR (steps list with reorder)
# ============================================================

async def render_editor(
    cat: str, cid: int, flow_name: str,
) -> Tuple[str, InlineKeyboardMarkup]:
    flow_icon, flow_label = _flow_icon(flow_name)
    target = await _target_label(cat, cid)

    # Read flow + order
    try:
        steps, order = await _load_flow_view(cid, flow_name)
    except Exception as e:
        logger.exception(f"[FLW] load: {e}")
        return await render_target(cat, cid)

    enabled_count = sum(1 for s in steps if s.get("enabled", True))

    text_lines = [
        _header(flow_icon, f"{flow_label.upper()} · {target[:30]}"),
        f"📊 {F.sc('enabled')} · <b>{enabled_count}</b> / {len(steps)}",
        "",
        f"📌 {F.sc('tap a step to configure')}",
        f"📌 {F.sc('use ⬆️⬇️ to reorder')}",
        "",
    ]

    rows: List[List[InlineKeyboardButton]] = []

    for i, step_cfg in enumerate(steps):
        key = step_cfg.get("type") or step_cfg.get("key") or "?"
        enabled = step_cfg.get("enabled", True)
        per_row = step_cfg.get("per_row", 2)
        icon, label = _step_icon(key)
        marker = "🟢" if enabled else "🔴"

        text_lines.append(
            f"{marker} <b>{i + 1:02d}.</b> {icon} "
            f"{F.sc(label)} · <code>{per_row}/row</code>"
        )

        # One row per step with reorder buttons inline
        row = [
            InlineKeyboardButton(
                f"{marker} {i + 1:02d}. {icon} {label[:18]}",
                callback_data=f"adm:flw_step:{cat}:{cid}:{flow_name}:{i}",
            ),
        ]
        # Move up
        if i > 0:
            row.append(InlineKeyboardButton(
                "⬆️",
                callback_data=f"adm:flw_up:{cat}:{cid}:{flow_name}:{i}",
            ))
        else:
            row.append(InlineKeyboardButton("·", callback_data="adm:flw_noop"))
        # Move down
        if i < len(steps) - 1:
            row.append(InlineKeyboardButton(
                "⬇️",
                callback_data=f"adm:flw_down:{cat}:{cid}:{flow_name}:{i}",
            ))
        else:
            row.append(InlineKeyboardButton("·", callback_data="adm:flw_noop"))

        rows.append(row)

    rows.append([
        InlineKeyboardButton(
            f"👁️ {F.sc('preview')}",
            callback_data=f"adm:flw_prev:{cat}:{cid}:{flow_name}",
        ),
        InlineKeyboardButton(
            f"🎨 {F.sc('display')}",
            callback_data=f"adm:flw_disp:{cat}:{cid}",
        ),
    ])
    rows.append([
        InlineKeyboardButton(
            f"📝 {F.sc('caption')}",
            callback_data=f"adm:flw_cap:{cat}:{cid}",
        ),
        InlineKeyboardButton(
            f"♻️ {F.sc('reset all')}",
            callback_data=f"adm:flw_rst_all:{cat}:{cid}:{flow_name}",
        ),
    ])
    rows.append(_back_close(f"adm:flw_target:{cat}:{cid}", "back")[0])

    return "\n".join(text_lines)[:4000], InlineKeyboardMarkup(rows)


# ============================================================
# SECTION 9 — LOAD FLOW VIEW (steps + order from DB)
# ============================================================

async def _load_flow_view(
    cid: int, flow_name: str,
) -> Tuple[List[Dict[str, Any]], List[str]]:
    """
    Return (steps_ordered, order_list).
    Order comes from cfg["flow_order"] if set, else default.
    """
    cfg = await GS.get_config(cid)
    flow_cfg = cfg.get("flow") or {}
    flow_order_all = cfg.get("flow_order") or {}

    key = "series" if "series" in flow_name else "movie"
    custom_order = list(flow_order_all.get(key) or [])

    # Default order
    if "series" in flow_name:
        default = ["base_search", "spell_check", "suggestions",
                   "language", "season", "episode", "quality",
                   "file_delivery"]
    else:
        default = ["base_search", "spell_check", "suggestions",
                   "quality", "file_delivery"]

    # Use custom order if it's valid, else default
    order = [k for k in custom_order if k in default] or default
    # Append any missing steps from default
    for k in default:
        if k not in order:
            order.append(k)

    # Build steps list
    steps: List[Dict[str, Any]] = []
    for key in order:
        s = dict(flow_cfg.get(key) or {})
        s["type"] = key
        s.setdefault("enabled", True)
        s.setdefault("per_row", 2)
        s.setdefault("auto_skip", True)
        s.setdefault("max_items", 10)
        steps.append(s)

    return steps, order


# ============================================================
# SECTION 10 — STEP DETAIL
# ============================================================

async def render_step(
    cat: str, cid: int, flow_name: str, idx: int,
) -> Tuple[str, InlineKeyboardMarkup]:
    try:
        steps, _ = await _load_flow_view(cid, flow_name)
    except Exception:
        return await render_editor(cat, cid, flow_name)

    if idx < 0 or idx >= len(steps):
        return await render_editor(cat, cid, flow_name)

    step = steps[idx]
    key = step["type"]
    icon, label = _step_icon(key)
    mandatory = key in _MANDATORY

    enabled = step.get("enabled", True)
    per_row = int(step.get("per_row", 2))
    auto_skip = bool(step.get("auto_skip", True))
    max_items = int(step.get("max_items", 10))

    text_lines = [
        _header(icon, label.upper()),
        f"🏷️ {F.sc('type')} · <code>{key}</code>",
        f"📊 {F.sc('position')} · <b>{idx + 1}</b> / {len(steps)}",
        f"⚙️ {F.sc('status')} · {'🟢 enabled' if enabled else '🔴 disabled'}",
        f"📐 {F.sc('layout')} · <b>{per_row}</b> per row",
        f"🔄 {F.sc('auto-skip')} · {_on(auto_skip)}",
        f"🔢 {F.sc('max items')} · <b>{max_items}</b>",
    ]
    if mandatory:
        text_lines.append(f"🔒 {F.sc('mandatory')} — cannot disable")

    rows: List[List[InlineKeyboardButton]] = []

    # Toggle
    if not mandatory:
        rows.append([InlineKeyboardButton(
            f"{'🔴 ' + F.sc('disable') if enabled else '🟢 ' + F.sc('enable')}",
            callback_data=f"adm:flw_tog:{cat}:{cid}:{flow_name}:{idx}",
        )])

    # Per-row picker
    layout_row = []
    for n in (1, 2, 3, 4):
        mark = "✅ " if n == per_row else ""
        layout_row.append(InlineKeyboardButton(
            f"{mark}{n}/row",
            callback_data=f"adm:flw_row:{cat}:{cid}:{flow_name}:{idx}:{n}",
        ))
    rows.append(layout_row)

    # Auto-skip
    if key in ("language", "season", "episode", "quality"):
        rows.append([InlineKeyboardButton(
            f"🔄 {F.sc('auto-skip if one')} · {_on(auto_skip)}",
            callback_data=f"adm:flw_skip:{cat}:{cid}:{flow_name}:{idx}",
        )])

    # Max items (1-30 in steps)
    max_row = []
    for n in (3, 5, 8, 10, 15, 20):
        mark = "✅ " if n == max_items else ""
        max_row.append(InlineKeyboardButton(
            f"{mark}{n}",
            callback_data=f"adm:flw_max:{cat}:{cid}:{flow_name}:{idx}:{n}",
        ))
    rows.append([InlineKeyboardButton(
        f"🔢 {F.sc('max items')}",
        callback_data="adm:flw_noop",
    )])
    rows.append(max_row)

    # Advanced settings (step-specific)
    rows.append([InlineKeyboardButton(
        f"⚙️ {F.sc('advanced settings')}",
        callback_data=f"adm:flw_adv:{cat}:{cid}:{flow_name}:{idx}",
    )])

    # Reorder buttons
    up_btn = InlineKeyboardButton(
        "⬆️ up",
        callback_data=f"adm:flw_up:{cat}:{cid}:{flow_name}:{idx}",
    ) if idx > 0 else InlineKeyboardButton("⬆️", callback_data="adm:flw_noop")
    down_btn = InlineKeyboardButton(
        "⬇️ down",
        callback_data=f"adm:flw_down:{cat}:{cid}:{flow_name}:{idx}",
    ) if idx < len(steps) - 1 else InlineKeyboardButton("⬇️", callback_data="adm:flw_noop")
    rows.append([up_btn, down_btn])

    # Reset
    rows.append([InlineKeyboardButton(
        f"♻️ {F.sc('reset step')}",
        callback_data=f"adm:flw_rst_step:{cat}:{cid}:{flow_name}:{idx}",
    )])

    rows.append(_back_close(f"adm:flw_edit:{cat}:{cid}:{flow_name}", "back")[0])
    return "\n".join(text_lines)[:4000], InlineKeyboardMarkup(rows)


# ============================================================
# SECTION 11 — STEP ADVANCED (per-step-type settings)
# ============================================================

async def render_step_advanced(
    cat: str, cid: int, flow_name: str, idx: int,
) -> Tuple[str, InlineKeyboardMarkup]:
    try:
        steps, _ = await _load_flow_view(cid, flow_name)
    except Exception:
        return await render_editor(cat, cid, flow_name)

    if idx < 0 or idx >= len(steps):
        return await render_editor(cat, cid, flow_name)

    step = steps[idx]
    key = step["type"]
    icon, label = _step_icon(key)

    rows: List[List[InlineKeyboardButton]] = []
    text_lines = [
        _header("⚙️", f"{label.upper()} · ADVANCED"),
        f"🏷️ {F.sc('type')} · <code>{key}</code>",
        "",
    ]

    if key == "spell_check":
        threshold = int(step.get("threshold", 82))
        max_corr = int(step.get("max_corrections", 1))
        text_lines += [
            f"🎯 {F.sc('match threshold')} · <b>{threshold}</b>",
            f"🔁 {F.sc('max corrections')} · <b>{max_corr}</b>",
            "",
            f"📌 {F.sc('higher threshold = stricter spelling')}",
        ]
        rows.append([InlineKeyboardButton(
            f"🎯 {F.sc('threshold')}",
            callback_data="adm:flw_noop",
        )])
        trow = []
        for n in (60, 70, 75, 80, 82, 85, 90, 95):
            mark = "✅ " if n == threshold else ""
            trow.append(InlineKeyboardButton(
                f"{mark}{n}",
                callback_data=f"adm:flw_set:{cat}:{cid}:{flow_name}:{idx}:threshold:{n}",
            ))
            if len(trow) == 4:
                rows.append(trow)
                trow = []
        if trow:
            rows.append(trow)

        rows.append([InlineKeyboardButton(
            f"🔁 {F.sc('max corrections')}",
            callback_data="adm:flw_noop",
        )])
        rows.append([
            InlineKeyboardButton(
                f"{'✅ ' if max_corr == 1 else ''}1",
                callback_data=f"adm:flw_set:{cat}:{cid}:{flow_name}:{idx}:max_corrections:1",
            ),
            InlineKeyboardButton(
                f"{'✅ ' if max_corr == 2 else ''}2",
                callback_data=f"adm:flw_set:{cat}:{cid}:{flow_name}:{idx}:max_corrections:2",
            ),
            InlineKeyboardButton(
                f"{'✅ ' if max_corr == 3 else ''}3",
                callback_data=f"adm:flw_set:{cat}:{cid}:{flow_name}:{idx}:max_corrections:3",
            ),
        ])

    elif key == "suggestions":
        min_score = int(step.get("min_score", 45))
        provider = str(step.get("provider", "both"))
        show_rating = bool(step.get("show_rating", True))
        show_year = bool(step.get("show_year", True))
        show_icon = bool(step.get("show_icon", True))

        text_lines += [
            f"🎯 {F.sc('min match score')} · <b>{min_score}</b>",
            f"📡 {F.sc('provider')} · <b>{provider}</b>",
            f"⭐ {F.sc('show rating')} · {_on(show_rating)}",
            f"📅 {F.sc('show year')} · {_on(show_year)}",
            f"🎬 {F.sc('show icon')} · {_on(show_icon)}",
        ]

        rows.append([InlineKeyboardButton(
            f"🎯 {F.sc('min score')}",
            callback_data="adm:flw_noop",
        )])
        srow = []
        for n in (30, 40, 45, 50, 60, 70, 80):
            mark = "✅ " if n == min_score else ""
            srow.append(InlineKeyboardButton(
                f"{mark}{n}",
                callback_data=f"adm:flw_set:{cat}:{cid}:{flow_name}:{idx}:min_score:{n}",
            ))
            if len(srow) == 4:
                rows.append(srow)
                srow = []
        if srow:
            rows.append(srow)

        rows.append([InlineKeyboardButton(
            f"📡 {F.sc('provider')}",
            callback_data="adm:flw_noop",
        )])
        rows.append([
            InlineKeyboardButton(
                f"{'✅ ' if provider == 'tmdb' else ''}TMDB",
                callback_data=f"adm:flw_set:{cat}:{cid}:{flow_name}:{idx}:provider:tmdb",
            ),
            InlineKeyboardButton(
                f"{'✅ ' if provider == 'imdb' else ''}IMDb",
                callback_data=f"adm:flw_set:{cat}:{cid}:{flow_name}:{idx}:provider:imdb",
            ),
            InlineKeyboardButton(
                f"{'✅ ' if provider == 'both' else ''}Both",
                callback_data=f"adm:flw_set:{cat}:{cid}:{flow_name}:{idx}:provider:both",
            ),
        ])
        rows.append([
            InlineKeyboardButton(
                f"⭐ {_on(show_rating)}",
                callback_data=f"adm:flw_tog_f:{cat}:{cid}:{flow_name}:{idx}:show_rating",
            ),
            InlineKeyboardButton(
                f"📅 {_on(show_year)}",
                callback_data=f"adm:flw_tog_f:{cat}:{cid}:{flow_name}:{idx}:show_year",
            ),
            InlineKeyboardButton(
                f"🎬 {_on(show_icon)}",
                callback_data=f"adm:flw_tog_f:{cat}:{cid}:{flow_name}:{idx}:show_icon",
            ),
        ])

    elif key == "file_delivery":
        sort_order = str(step.get("sort_order", "small_to_big"))
        size_fmt = str(step.get("size_format", "short"))
        show_quality = bool(step.get("show_quality", True))
        show_name = bool(step.get("show_name", True))
        name_len = int(step.get("name_max_len", 34))

        text_lines += [
            f"📊 {F.sc('sort')} · <b>{sort_order}</b>",
            f"💾 {F.sc('size format')} · <b>{size_fmt}</b>",
            f"🎯 {F.sc('show quality')} · {_on(show_quality)}",
            f"📛 {F.sc('show name')} · {_on(show_name)}",
            f"📏 {F.sc('name max len')} · <b>{name_len}</b>",
        ]

        rows.append([InlineKeyboardButton(
            f"📊 {F.sc('sort order')}",
            callback_data="adm:flw_noop",
        )])
        rows.append([
            InlineKeyboardButton(
                f"{'✅ ' if sort_order == 'small_to_big' else ''}📈 small→big",
                callback_data=f"adm:flw_set:{cat}:{cid}:{flow_name}:{idx}:sort_order:small_to_big",
            ),
            InlineKeyboardButton(
                f"{'✅ ' if sort_order == 'big_to_small' else ''}📉 big→small",
                callback_data=f"adm:flw_set:{cat}:{cid}:{flow_name}:{idx}:sort_order:big_to_small",
            ),
        ])

        rows.append([
            InlineKeyboardButton(
                f"🎯 {_on(show_quality)}",
                callback_data=f"adm:flw_tog_f:{cat}:{cid}:{flow_name}:{idx}:show_quality",
            ),
            InlineKeyboardButton(
                f"📛 {_on(show_name)}",
                callback_data=f"adm:flw_tog_f:{cat}:{cid}:{flow_name}:{idx}:show_name",
            ),
        ])

        rows.append([InlineKeyboardButton(
            f"📏 {F.sc('name max length')}",
            callback_data="adm:flw_noop",
        )])
        lrow = []
        for n in (20, 25, 30, 34, 40, 50):
            mark = "✅ " if n == name_len else ""
            lrow.append(InlineKeyboardButton(
                f"{mark}{n}",
                callback_data=f"adm:flw_set:{cat}:{cid}:{flow_name}:{idx}:name_max_len:{n}",
            ))
            if len(lrow) == 3:
                rows.append(lrow)
                lrow = []
        if lrow:
            rows.append(lrow)

    else:
        # Generic — no specific settings
        text_lines.append(f"⚪ {F.sc('no extra settings for this step')}")

    rows.append(_back_close(
        f"adm:flw_step:{cat}:{cid}:{flow_name}:{idx}", "back"
    )[0])
    return "\n".join(text_lines)[:4000], InlineKeyboardMarkup(rows)


# ============================================================
# SECTION 12 — DISPLAY SETTINGS (per-group, applies everywhere)
# ============================================================

async def render_display(
    cat: str, cid: int,
) -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await GS.get_config(cid)
    meta = cfg.get("metadata") or {}

    poster = bool(meta.get("poster", True))
    rating = bool(meta.get("rating", True))
    genre = bool(meta.get("genre", True))
    year = bool(meta.get("year", True))
    language = bool(meta.get("language", True))

    text_lines = [
        _header("🎨", "DISPLAY SETTINGS"),
        f"📌 {F.sc('what appears in search results')}",
        "",
        f"🖼️ {F.sc('poster')} · {_on(poster)}",
        f"⭐ {F.sc('rating')} · {_on(rating)}",
        f"📅 {F.sc('year')} · {_on(year)}",
        f"🎭 {F.sc('genre')} · {_on(genre)}",
        f"🌐 {F.sc('language')} · {_on(language)}",
    ]

    rows = [
        [InlineKeyboardButton(
            f"🖼️ {F.sc('poster')} · {_on(poster)}",
            callback_data=f"adm:flw_meta:{cat}:{cid}:poster",
        )],
        [InlineKeyboardButton(
            f"⭐ {F.sc('rating')} · {_on(rating)}",
            callback_data=f"adm:flw_meta:{cat}:{cid}:rating",
        )],
        [InlineKeyboardButton(
            f"📅 {F.sc('year')} · {_on(year)}",
            callback_data=f"adm:flw_meta:{cat}:{cid}:year",
        )],
        [InlineKeyboardButton(
            f"🎭 {F.sc('genre')} · {_on(genre)}",
            callback_data=f"adm:flw_meta:{cat}:{cid}:genre",
        )],
        [InlineKeyboardButton(
            f"🌐 {F.sc('language')} · {_on(language)}",
            callback_data=f"adm:flw_meta:{cat}:{cid}:language",
        )],
        _back_close(f"adm:flw_target:{cat}:{cid}", "back")[0],
    ]

    return "\n".join(text_lines), InlineKeyboardMarkup(rows)


# ============================================================
# SECTION 13 — CAPTION EDITOR
# ============================================================

async def render_caption_editor(
    cat: str, cid: int,
) -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await GS.get_config(cid)
    tpl = cfg.get("caption_template")

    text_lines = [
        _header("📝", "CAPTION EDITOR"),
        f"📌 {F.sc('per-group caption for delivered files')}",
        "",
        f"🎯 {F.sc('status')} · "
        f"{'🟢 custom' if tpl else '⚪ global'}",
    ]
    if tpl:
        text_lines += ["", f"<code>{F.sc(str(tpl)[:400])}</code>"]

    text_lines += [
        "",
        F.DIV_S,
        f"📌 {F.sc('variables')}:",
        "<code>{title} {year} {quality} {codec}</code>",
        "<code>{audio} {subtitle} {size}</code>",
        "<code>{season} {episode} {bot_username}</code>",
    ]

    rows = [
        [InlineKeyboardButton(
            f"✏️ {F.sc('edit caption')}",
            callback_data=f"adm:flw_cap_edit:{cat}:{cid}",
        )],
    ]
    if tpl:
        rows.append([InlineKeyboardButton(
            f"👁️ {F.sc('preview')}",
            callback_data=f"adm:flw_cap_prev:{cat}:{cid}",
        )])
        rows.append([InlineKeyboardButton(
            f"♻️ {F.sc('reset to global')}",
            callback_data=f"adm:flw_cap_rst:{cat}:{cid}",
        )])
    rows.append(_back_close(f"adm:flw_target:{cat}:{cid}", "back")[0])
    return "\n".join(text_lines), InlineKeyboardMarkup(rows)


# ============================================================
# SECTION 14 — PREVIEW
# ============================================================

async def render_preview(
    cat: str, cid: int, flow_name: str,
) -> Tuple[str, InlineKeyboardMarkup]:
    flow_icon, flow_label = _flow_icon(flow_name)
    target = await _target_label(cat, cid)

    try:
        steps, _ = await _load_flow_view(cid, flow_name)
    except Exception:
        return await render_editor(cat, cid, flow_name)

    text_lines = [
        _header("👁️", "FLOW PREVIEW"),
        f"🎬 {F.sc('flow')} · <b>{flow_label}</b>",
        f"🎯 {F.sc('target')} · {F.sc(target[:40])}",
        "",
        f"📌 {F.sc('order users will experience')}",
        "",
    ]

    for i, step in enumerate(steps, 1):
        key = step["type"]
        icon, label = _step_icon(key)
        enabled = step.get("enabled", True)
        per_row = step.get("per_row", 2)
        auto = step.get("auto_skip", True)
        marker = "🟢" if enabled else "🔴"

        text_lines.append(
            f"{marker} <b>{i:02d}.</b> {icon} "
            f"<b>{F.sc(label)}</b> · <code>{per_row}/row</code>"
            + (" · ⏭️" if auto else "")
        )

    rows = [_back_close(f"adm:flw_edit:{cat}:{cid}:{flow_name}", "back")[0]]
    return "\n".join(text_lines)[:4000], InlineKeyboardMarkup(rows)


# ============================================================
# SECTION 15 — SAVE HELPERS
# ============================================================

async def _save_order(
    cid: int, flow_name: str, new_order: List[str],
) -> bool:
    """Save custom order list for a flow."""
    try:
        cfg = await GS.get_config(cid)
        flow_order = dict(cfg.get("flow_order") or {})
        key = "series" if "series" in flow_name else "movie"
        flow_order[key] = list(new_order)
        return await GS.save_field(cid, "flow_order", flow_order)
    except Exception as e:
        logger.warning(f"[FLW] save order: {e}")
        return False


async def _save_step_field(
    cid: int, step_key: str, field: str, value: Any,
) -> bool:
    """Save one field under cfg['flow'][step_key][field]."""
    try:
        return await GS.save_field(
            cid, f"flow.{step_key}.{field}", value,
        )
    except Exception as e:
        logger.warning(f"[FLW] save step field: {e}")
        return False


async def _toggle_step_field(
    cid: int, step_key: str, field: str,
) -> Optional[bool]:
    """Toggle a boolean field under cfg['flow'][step_key]."""
    try:
        cfg = await GS.get_config(cid)
        flow_cfg = cfg.get("flow") or {}
        step = flow_cfg.get(step_key) or {}
        cur = bool(step.get(field, False))
        await _save_step_field(cid, step_key, field, not cur)
        return not cur
    except Exception:
        return None


# ============================================================
# SECTION 16 — CALLBACK ROUTER
# ============================================================

@Client.on_callback_query(
    filters.regex(r"^adm:flw_"),
    group=-9525,
)
async def flow_admin_router(client: Client, q: CallbackQuery):
    if not q.from_user or not _is_admin(q.from_user.id):
        return await q.answer("⛔ admin only", show_alert=True)

    data = str(q.data)
    parts = data.split(":")
    action = parts[1][4:] if len(parts) > 1 and parts[1].startswith("flw_") else ""

    try:
        # ── NOOP ──
        if action == "noop":
            return await q.answer()

        # ── HOME ──
        if action == "home":
            text, kb = await render_home()
            await _safe_edit(q, text, kb)
            return await q.answer()

        # ── CATEGORY ──
        if action == "cat":
            cat = parts[2] if len(parts) > 2 else ""
            text, kb = await render_category(cat)
            await _safe_edit(q, text, kb)
            return await q.answer()

        # ── TARGET ──
        if action == "target":
            cat = parts[2]
            cid = int(parts[3])
            text, kb = await render_target(cat, cid)
            await _safe_edit(q, text, kb)
            return await q.answer()

        # ── EDITOR ──
        if action == "edit":
            cat = parts[2]
            cid = int(parts[3])
            flow_name = parts[4]
            text, kb = await render_editor(cat, cid, flow_name)
            await _safe_edit(q, text, kb)
            return await q.answer()

        # ── STEP DETAIL ──
        if action == "step":
            cat = parts[2]
            cid = int(parts[3])
            flow_name = parts[4]
            idx = int(parts[5])
            text, kb = await render_step(cat, cid, flow_name, idx)
            await _safe_edit(q, text, kb)
            return await q.answer()

        # ── STEP ADVANCED ──
        if action == "adv":
            cat = parts[2]
            cid = int(parts[3])
            flow_name = parts[4]
            idx = int(parts[5])
            text, kb = await render_step_advanced(cat, cid, flow_name, idx)
            await _safe_edit(q, text, kb)
            return await q.answer()

        # ── PREVIEW ──
        if action == "prev":
            cat = parts[2]
            cid = int(parts[3])
            flow_name = parts[4]
            text, kb = await render_preview(cat, cid, flow_name)
            await _safe_edit(q, text, kb)
            return await q.answer()

        # ── DISPLAY ──
        if action == "disp":
            cat = parts[2]
            cid = int(parts[3])
            text, kb = await render_display(cat, cid)
            await _safe_edit(q, text, kb)
            return await q.answer()

        if action == "meta":
            cat = parts[2]
            cid = int(parts[3])
            field = parts[4]
            cfg = await GS.get_config(cid)
            meta = dict(cfg.get("metadata") or {})
            cur = bool(meta.get(field, True))
            await GS.save_field(cid, f"metadata.{field}", not cur)
            await q.answer(f"{'🟢' if not cur else '🔴'}")
            text, kb = await render_display(cat, cid)
            await _safe_edit(q, text, kb)
            return

        # ── CAPTION ──
        if action == "cap":
            cat = parts[2]
            cid = int(parts[3])
            text, kb = await render_caption_editor(cat, cid)
            await _safe_edit(q, text, kb)
            return await q.answer()

        if action == "cap_edit":
            cat = parts[2]
            cid = int(parts[3])
            target = await _target_label(cat, cid)
            # Store session so text_input picks it up
            try:
                from plugins.groups import router as GR
                GR._sess_new(q.from_user.id, "cap_edit", cid)
            except Exception:
                pass
            text = "\n".join([
                _header("✏️", f"EDIT CAPTION · {target[:30]}"),
                f"📌 {F.sc('send the new caption')}",
                f"📌 {F.sc('or send')} <code>-</code> {F.sc('to reset')}",
                "",
                F.DIV_S,
                "<code>{title} {year} {quality}</code>",
                "<code>{codec} {audio} {subtitle}</code>",
                "<code>{size} {season} {episode}</code>",
                "<code>{bot_username}</code>",
            ])
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"{F.EMO['cross']} {F.sc(f'cancel · {target[:20]}')}",
                    callback_data=f"adm:flw_cap:{cat}:{cid}",
                ),
            ]])
            await _safe_edit(q, text, kb)
            return await q.answer()

        if action == "cap_rst":
            cat = parts[2]
            cid = int(parts[3])
            await GS.save_field(cid, "caption_template", None)
            await q.answer("♻️ reset")
            text, kb = await render_caption_editor(cat, cid)
            await _safe_edit(q, text, kb)
            return

        if action == "cap_prev":
            cat = parts[2]
            cid = int(parts[3])
            cfg = await GS.get_config(cid)
            tpl = cfg.get("caption_template") or ""
            sample = {
                "title": "Karnan", "year": "2021",
                "quality": "1080P", "codec": "HEVC",
                "audio": "Tamil", "subtitle": "English",
                "size": "1.4 GB", "season": "", "episode": "",
                "bot_username": "examplebot",
            }
            try:
                rendered = tpl.format(**sample)
            except Exception as e:
                rendered = f"(error: {e})\n\n{tpl}"
            text = "\n".join([
                _header("👁️", "CAPTION PREVIEW"),
                rendered,
            ])
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"{F.EMO['back']} {F.sc('back')}",
                    callback_data=f"adm:flw_cap:{cat}:{cid}",
                ),
            ]])
            await _safe_edit(q, text[:4000], kb)
            return await q.answer()

        # ── TOGGLE STEP ENABLED ──
        if action == "tog":
            cat = parts[2]
            cid = int(parts[3])
            flow_name = parts[4]
            idx = int(parts[5])
            steps, _ = await _load_flow_view(cid, flow_name)
            if 0 <= idx < len(steps):
                key = steps[idx]["type"]
                cur = steps[idx].get("enabled", True)
                await _save_step_field(cid, key, "enabled", not cur)
                await q.answer(f"{'🟢' if not cur else '🔴'}")
            text, kb = await render_step(cat, cid, flow_name, idx)
            await _safe_edit(q, text, kb)
            return

        # ── TOGGLE STEP FIELD (show_rating etc.) ──
        if action == "tog_f":
            cat = parts[2]
            cid = int(parts[3])
            flow_name = parts[4]
            idx = int(parts[5])
            field = parts[6]
            steps, _ = await _load_flow_view(cid, flow_name)
            if 0 <= idx < len(steps):
                key = steps[idx]["type"]
                new_val = await _toggle_step_field(cid, key, field)
                await q.answer(f"{'🟢' if new_val else '🔴'}")
            text, kb = await render_step_advanced(cat, cid, flow_name, idx)
            await _safe_edit(q, text, kb)
            return

        # ── SET STEP PER ROW ──
        if action == "row":
            cat = parts[2]
            cid = int(parts[3])
            flow_name = parts[4]
            idx = int(parts[5])
            n = int(parts[6])
            steps, _ = await _load_flow_view(cid, flow_name)
            if 0 <= idx < len(steps):
                key = steps[idx]["type"]
                await _save_step_field(cid, key, "per_row", n)
            await q.answer(f"📐 {n}/row")
            text, kb = await render_step(cat, cid, flow_name, idx)
            await _safe_edit(q, text, kb)
            return

        # ── SET STEP AUTO-SKIP ──
        if action == "skip":
            cat = parts[2]
            cid = int(parts[3])
            flow_name = parts[4]
            idx = int(parts[5])
            steps, _ = await _load_flow_view(cid, flow_name)
            if 0 <= idx < len(steps):
                key = steps[idx]["type"]
                await _toggle_step_field(cid, key, "auto_skip")
            await q.answer("🔄")
            text, kb = await render_step(cat, cid, flow_name, idx)
            await _safe_edit(q, text, kb)
            return

        # ── SET STEP MAX ITEMS ──
        if action == "max":
            cat = parts[2]
            cid = int(parts[3])
            flow_name = parts[4]
            idx = int(parts[5])
            n = int(parts[6])
            steps, _ = await _load_flow_view(cid, flow_name)
            if 0 <= idx < len(steps):
                key = steps[idx]["type"]
                await _save_step_field(cid, key, "max_items", n)
            await q.answer(f"🔢 {n}")
            text, kb = await render_step(cat, cid, flow_name, idx)
            await _safe_edit(q, text, kb)
            return

        # ── SET ADVANCED FIELD ──
        if action == "set":
            cat = parts[2]
            cid = int(parts[3])
            flow_name = parts[4]
            idx = int(parts[5])
            field = parts[6]
            value_raw = parts[7]
            # Cast value
            try:
                value: Any = int(value_raw)
            except ValueError:
                value = value_raw
            steps, _ = await _load_flow_view(cid, flow_name)
            if 0 <= idx < len(steps):
                key = steps[idx]["type"]
                await _save_step_field(cid, key, field, value)
            await q.answer(f"✅ {field}={value}")
            text, kb = await render_step_advanced(cat, cid, flow_name, idx)
            await _safe_edit(q, text, kb)
            return

        # ── MOVE UP ──
        if action == "up":
            cat = parts[2]
            cid = int(parts[3])
            flow_name = parts[4]
            idx = int(parts[5])
            steps, order = await _load_flow_view(cid, flow_name)
            if 0 <= idx < len(order) and idx > 0:
                order[idx - 1], order[idx] = order[idx], order[idx - 1]
                await _save_order(cid, flow_name, order)
                await q.answer("⬆️ moved")
                idx -= 1
            else:
                await q.answer("⚠️ top")
            text, kb = await render_editor(cat, cid, flow_name)
            await _safe_edit(q, text, kb)
            return

        # ── MOVE DOWN ──
        if action == "down":
            cat = parts[2]
            cid = int(parts[3])
            flow_name = parts[4]
            idx = int(parts[5])
            steps, order = await _load_flow_view(cid, flow_name)
            if 0 <= idx < len(order) - 1:
                order[idx], order[idx + 1] = order[idx + 1], order[idx]
                await _save_order(cid, flow_name, order)
                await q.answer("⬇️ moved")
                idx += 1
            else:
                await q.answer("⚠️ bottom")
            text, kb = await render_editor(cat, cid, flow_name)
            await _safe_edit(q, text, kb)
            return

        # ── RESET STEP ──
        if action == "rst_step":
            cat = parts[2]
            cid = int(parts[3])
            flow_name = parts[4]
            idx = int(parts[5])
            steps, _ = await _load_flow_view(cid, flow_name)
            if 0 <= idx < len(steps):
                key = steps[idx]["type"]
                await GS.save_field(cid, f"flow.{key}", None)
            await q.answer("♻️ reset")
            text, kb = await render_step(cat, cid, flow_name, idx)
            await _safe_edit(q, text, kb)
            return

        # ── RESET ALL ──
        if action == "rst_all":
            cat = parts[2]
            cid = int(parts[3])
            flow_name = parts[4]
            target = await _target_label(cat, cid)
            text = "\n".join([
                _header("⚠️", "RESET FLOW?"),
                f"🎯 {F.sc('target')} · <b>{F.sc(target[:40])}</b>",
                f"{F.EMO['warn']} {F.sc('all custom settings will be lost')}",
                "",
                F.DIV_S,
            ])
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    f"♻️ {F.sc('yes, reset')}",
                    callback_data=f"adm:flw_rst_do:{cat}:{cid}:{flow_name}",
                )],
                [InlineKeyboardButton(
                    f"{F.EMO['back']} {F.sc(f'cancel · {target[:20]}')}",
                    callback_data=f"adm:flw_edit:{cat}:{cid}:{flow_name}",
                )],
            ])
            await _safe_edit(q, text, kb)
            return await q.answer()

        if action == "rst_do":
            cat = parts[2]
            cid = int(parts[3])
            flow_name = parts[4]
            key = "series" if "series" in flow_name else "movie"
            cfg = await GS.get_config(cid)
            flow_order = dict(cfg.get("flow_order") or {})
            flow_order[key] = []
            await GS.save_field(cid, "flow_order", flow_order)
            await GS.save_field(cid, "flow", {})
            await q.answer("♻️ reset complete")
            text, kb = await render_editor(cat, cid, flow_name)
            await _safe_edit(q, text, kb)
            return

        return await q.answer("❓")

    except Exception as e:
        logger.exception(f"[FLW] router: {e}")
        try:
            await q.answer(f"❌ {type(e).__name__}", show_alert=True)
        except Exception:
            pass


# ============================================================
# SECTION 17 — SAFE EDIT
# ============================================================

async def _safe_edit(q: CallbackQuery, text: str, kb) -> None:
    try:
        await q.message.edit_text(
            text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        if "not modified" not in str(e).lower():
            logger.debug(f"[FLW] edit: {e}")


# ============================================================
# SECTION 18 — PUBLIC EXPORTS
# ============================================================

__all__ = [
    "build",
    "render_home",
    "render_category",
    "render_target",
    "render_editor",
    "render_step",
    "render_step_advanced",
    "render_display",
    "render_caption_editor",
    "render_preview",
]
