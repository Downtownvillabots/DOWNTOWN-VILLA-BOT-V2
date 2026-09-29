# ============================================================
# 🏨 DOWNTOWN VILLA — FLOW CONTROL CENTER
# ============================================================
#
# /admin → [🎯 Flow Editor] opens this.
#
# Hierarchy:
#   Home
#   ├─ 📢 Channels → list → target menu → flow editor
#   ├─ 👥 Groups   → list → target menu → flow editor
#   ├─ 💬 PM       → PM search flow (chat_id = 0)
#   └─ 🌐 Global   → all flows for defaults (chat_id = 0)
#
# Every editor reuses core.flow_engine data functions but
# carries the target chat_id in every callback, so admins
# can edit any group/channel from their own PM.
#
# Callback prefix: adm:flw_
# Handler group: -9525 (runs before other admin sub-routers)
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
from core.flow_engine import (
    get_flow_for, set_flow_for, delete_flow_for,
    toggle_step, move_step, reset_step_to_default, set_step_field,
    get_step, list_flows, build_default,
)
from utils import fonts as F

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
# SECTION 2 — LABELS
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


def _flow_label(name: str) -> Tuple[str, str]:
    return _FLOW_META.get(name, ("🎯", name))


def _cat_label(cat: str) -> Tuple[str, str]:
    return _CATEGORY_META.get(cat, ("🎯", cat))


def _flows_for_category(cat: str) -> List[str]:
    if cat == "group":
        return ["series_search", "movie_search", "pm_search"]
    if cat == "channel":
        return ["movie_search", "series_search"]
    if cat == "pm":
        return ["pm_search"]
    if cat == "global":
        return ["series_search", "movie_search", "pm_search", "broadcast"]
    return list_flows()


# ============================================================
# SECTION 3 — DATA SOURCES
# ============================================================

async def _list_groups() -> List[Dict[str, Any]]:
    """Connected groups (from group_admin state)."""
    try:
        from plugins.group_admin import state as S
        docs = await S.list_groups(limit=50)
        out: List[Dict[str, Any]] = []
        for d in docs:
            cid = d.get("chat_id")
            if not cid:
                continue
            out.append({
                "chat_id": int(cid),
                "title": str(d.get("title") or cid)[:60],
            })
        return out
    except Exception as e:
        logger.debug(f"[FLW-ADMIN] list groups: {e}")
        return []


async def _list_channels() -> List[Dict[str, Any]]:
    """Registered indexing channels."""
    try:
        from plugins.indexing import backward as BW
        docs = await BW.list_registered_channels()
        out: List[Dict[str, Any]] = []
        for d in docs:
            cid = d.get("chat_id")
            if not cid:
                continue
            out.append({
                "chat_id": int(cid),
                "title": str(d.get("title") or cid)[:60],
                "enabled": bool(d.get("enabled", True)),
            })
        return out
    except Exception as e:
        logger.debug(f"[FLW-ADMIN] list channels: {e}")
        return []


async def _target_label(cat: str, cid: int) -> str:
    """Human label for a target (group title / channel title)."""
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
    return f"{cat}-{cid}"


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


def _back_close(
    back_cb: str = "adm:flw_home",
    back_label: str = "back",
) -> List[List[InlineKeyboardButton]]:
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


# ============================================================
# SECTION 5 — HOME
# ============================================================

async def build() -> Tuple[str, InlineKeyboardMarkup]:
    """Entry point — called by admin.py's _build_page_builder('flow')."""
    return await render_home()


async def render_home() -> Tuple[str, InlineKeyboardMarkup]:
    groups = await _list_groups()
    channels = await _list_channels()

    lines = [
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
        F.DIV,
        f"🕒 <code>{__import__('utils.format', fromlist=['datetime_']).datetime_()}</code>",
    ]

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"📢 {F.sc('channels')} ({len(channels)})",
            callback_data="adm:flw_cat:channel",
        )],
        [InlineKeyboardButton(
            f"👥 {F.sc('groups')} ({len(groups)})",
            callback_data="adm:flw_cat:group",
        )],
        [InlineKeyboardButton(
            f"💬 {F.sc('pm search')}",
            callback_data="adm:flw_cat:pm",
        )],
        [InlineKeyboardButton(
            f"🌐 {F.sc('global defaults')}",
            callback_data="adm:flw_cat:global",
        )],
        _back_close("adm:home", "admin menu")[0],
    ])

    return "\n".join(lines), kb


# ============================================================
# SECTION 6 — CATEGORY VIEW
# ============================================================

async def render_category(cat: str) -> Tuple[str, InlineKeyboardMarkup]:
    emoji, label = _cat_label(cat)

    if cat == "pm":
        # Direct entry — PM search is one flow
        return await render_target(cat, 0)

    if cat == "global":
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

    lines = [
        _header(emoji, label.upper()),
        f"📊 {F.sc('total')} · <b>{len(items)}</b>",
        "",
    ]

    rows: List[List[InlineKeyboardButton]] = []

    if not items:
        lines.append(f"⚪ {F.sc(empty_msg)}")
        if hint:
            lines.append(f"📌 {F.sc(hint)}")
    else:
        for i, it in enumerate(items[:30], 1):
            cid = it["chat_id"]
            title = it["title"]
            marker = "🟢" if it.get("enabled", True) else "🔴"
            lines.append(f"{marker} <b>{i:02d}.</b> {F.sc(title[:45])}")
            lines.append(f"   <code>{cid}</code>")

            rows.append([InlineKeyboardButton(
                f"{marker} {title[:36]}",
                callback_data=f"adm:flw_target:{cat}:{cid}",
            )])

    rows.append(_back_close("adm:flw_home", "back")[0])

    return "\n".join(lines)[:4000], InlineKeyboardMarkup(rows)


# ============================================================
# SECTION 7 — TARGET VIEW
# ============================================================

async def render_target(cat: str, cid: int) -> Tuple[str, InlineKeyboardMarkup]:
    emoji, cat_label = _cat_label(cat)
    target = await _target_label(cat, cid)

    lines = [
        _header(emoji, f"{cat_label.upper()} · {target[:40]}"),
        f"🆔 {F.sc('chat id')} · <code>{cid}</code>",
        "",
        f"📌 {F.sc('pick a flow to customize')}",
        "",
    ]

    rows: List[List[InlineKeyboardButton]] = []
    flow_names = _flows_for_category(cat)

    for name in flow_names:
        icon, label = _flow_label(name)
        # Check if a custom config exists
        try:
            flow = await get_flow_for(cid, name)
            enabled = sum(
                1 for s in flow.all_steps_sorted()
                if s.get("enabled", True)
            )
            total = len(flow.steps)
        except Exception:
            enabled = total = 0

        lines.append(
            f"{icon} <b>{F.sc(label)}</b> · "
            f"<code>{enabled}/{total}</code> steps"
        )

        rows.append([InlineKeyboardButton(
            f"{icon} {label} · {enabled}/{total}",
            callback_data=f"adm:flw_edit:{cat}:{cid}:{name}",
        )])

    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data=f"adm:flw_cat:{cat}",
        ),
        InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('close')}",
            callback_data="adm:close",
        ),
    ])

    return "\n".join(lines)[:4000], InlineKeyboardMarkup(rows)


# ============================================================
# SECTION 8 — FLOW EDITOR (STEP LIST)
# ============================================================

async def render_editor(
    cat: str, cid: int, flow_name: str,
) -> Tuple[str, InlineKeyboardMarkup]:
    emoji, cat_label = _cat_label(cat)
    flow_icon, flow_label = _flow_label(flow_name)
    target = await _target_label(cat, cid)

    try:
        flow = await get_flow_for(cid, flow_name)
    except Exception as e:
        logger.exception(f"[FLW-ADMIN] load flow: {e}")
        return await render_target(cat, cid)

    steps = flow.all_steps_sorted()
    enabled_count = sum(1 for s in steps if s.get("enabled", True))

    lines = [
        _header(flow_icon, f"{flow_label.upper()} · {target[:30]}"),
        f"🆔 <code>{cid}</code>",
        f"📊 {F.sc('enabled')} · <b>{enabled_count}</b> / {len(steps)}",
        "",
    ]

    rows: List[List[InlineKeyboardButton]] = []

    for i, step_cfg in enumerate(steps):
        step = get_step(step_cfg["type"])
        if step is None:
            continue

        enabled = step_cfg.get("enabled", True)
        icon = "🟢" if enabled else "🔴"
        per_row = step_cfg.get("per_row", 2)

        lines.append(
            f"{icon} <b>{i + 1:02d}.</b> {step.icon} "
            f"{F.sc(step.display_name or step_cfg['type'])} "
            f"· <code>{per_row}/row</code>"
        )

        rows.append([InlineKeyboardButton(
            f"{icon} {i + 1:02d}. {step.icon} "
            f"{(step.display_name or step_cfg['type'])[:24]}",
            callback_data=f"adm:flw_step:{cat}:{cid}:{flow_name}:{i}",
        )])

    lines += [
        "",
        F.DIV_S,
        f"📌 {F.sc('tap a step to configure')}",
    ]

    rows.append([
        InlineKeyboardButton(
            f"👁️ {F.sc('preview')}",
            callback_data=f"adm:flw_prev:{cat}:{cid}:{flow_name}",
        ),
        InlineKeyboardButton(
            f"♻️ {F.sc('reset all')}",
            callback_data=f"adm:flw_rst_all:{cat}:{cid}:{flow_name}",
        ),
    ])
    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data=f"adm:flw_target:{cat}:{cid}",
        ),
        InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('close')}",
            callback_data="adm:close",
        ),
    ])

    return "\n".join(lines)[:4000], InlineKeyboardMarkup(rows)


# ============================================================
# SECTION 9 — STEP DETAIL
# ============================================================

async def render_step(
    cat: str, cid: int, flow_name: str, idx: int,
) -> Tuple[str, InlineKeyboardMarkup]:
    flow_icon, flow_label = _flow_label(flow_name)

    try:
        flow = await get_flow_for(cid, flow_name)
    except Exception:
        return await render_editor(cat, cid, flow_name)

    steps = flow.all_steps_sorted()
    if idx < 0 or idx >= len(steps):
        return await render_editor(cat, cid, flow_name)

    step_cfg = steps[idx]
    step = get_step(step_cfg["type"])
    if step is None:
        return await render_editor(cat, cid, flow_name)

    enabled = step_cfg.get("enabled", True)
    per_row = int(step_cfg.get("per_row", 2))
    auto_skip = bool(step_cfg.get("auto_skip_if_one", True))
    mandatory = bool(getattr(step, "mandatory", False))

    lines = [
        _header(step.icon or "⚙️", (step.display_name or step_cfg["type"]).upper()),
        f"📌 {F.sc(step.help_text or '')}",
        "",
        f"🏷️ {F.sc('type')} · <code>{step_cfg['type']}</code>",
        f"📊 {F.sc('position')} · <b>{idx + 1}</b> / {len(steps)}",
        f"⚙️ {F.sc('status')} · "
        f"{'🟢 enabled' if enabled else '🔴 disabled'}",
        f"📐 {F.sc('layout')} · <b>{per_row}</b> {F.sc('per row')}",
        f"🔄 {F.sc('auto-skip')} · "
        f"{'🟢 on' if auto_skip else '🔴 off'}",
    ]
    if mandatory:
        lines.append(f"🔒 {F.sc('mandatory')} — cannot be disabled")

    rows: List[List[InlineKeyboardButton]] = []

    # Toggle (skip if mandatory)
    if not mandatory:
        rows.append([InlineKeyboardButton(
            f"{'🔴 ' + F.sc('disable') if enabled else '🟢 ' + F.sc('enable')}",
            callback_data=f"adm:flw_tog:{cat}:{cid}:{flow_name}:{idx}",
        )])

    # Layout picker
    layout_row = []
    for n in (1, 2, 3):
        mark = "✅ " if n == per_row else ""
        layout_row.append(InlineKeyboardButton(
            f"{mark}{n}/row",
            callback_data=f"adm:flw_row:{cat}:{cid}:{flow_name}:{idx}:{n}",
        ))
    rows.append(layout_row)

    # Auto-skip toggle
    rows.append([InlineKeyboardButton(
        f"{'🟢' if auto_skip else '🔴'} {F.sc('auto-skip if one')}",
        callback_data=f"adm:flw_skip:{cat}:{cid}:{flow_name}:{idx}",
    )])

    # Move
    rows.append([
        InlineKeyboardButton(
            f"⬆️ {F.sc('up')}",
            callback_data=f"adm:flw_up:{cat}:{cid}:{flow_name}:{idx}",
        ),
        InlineKeyboardButton(
            f"⬇️ {F.sc('down')}",
            callback_data=f"adm:flw_down:{cat}:{cid}:{flow_name}:{idx}",
        ),
    ])

    # Reset
    rows.append([InlineKeyboardButton(
        f"♻️ {F.sc('reset step')}",
        callback_data=f"adm:flw_rst_step:{cat}:{cid}:{flow_name}:{idx}",
    )])

    # Nav
    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data=f"adm:flw_edit:{cat}:{cid}:{flow_name}",
        ),
        InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('close')}",
            callback_data="adm:close",
        ),
    ])

    return "\n".join(lines)[:4000], InlineKeyboardMarkup(rows)


# ============================================================
# SECTION 10 — PREVIEW
# ============================================================

async def render_preview(
    cat: str, cid: int, flow_name: str,
) -> Tuple[str, InlineKeyboardMarkup]:
    flow_icon, flow_label = _flow_label(flow_name)
    target = await _target_label(cat, cid)

    try:
        flow = await get_flow_for(cid, flow_name)
    except Exception:
        return await render_editor(cat, cid, flow_name)

    steps = flow.sorted_steps()
    lines = [
        _header("👁️", "FLOW PREVIEW"),
        f"🎬 {F.sc('flow')} · <b>{flow_label}</b>",
        f"🎯 {F.sc('target')} · {F.sc(target[:40])}",
        f"📊 {F.sc('active steps')} · <b>{len(steps)}</b>",
        "",
        F.DIV_S,
        "",
        f"📌 {F.sc('this is the order users will see')}",
        "",
    ]

    for i, step_cfg in enumerate(steps, 1):
        step = get_step(step_cfg["type"])
        if step is None:
            continue
        per_row = step_cfg.get("per_row", 2)
        auto = step_cfg.get("auto_skip_if_one", True)
        lines.append(
            f"<b>{i:02d}.</b> {step.icon} "
            f"<b>{F.sc(step.display_name)}</b> "
            f"· <code>{per_row}/row</code>"
            + (" · ⏭️ auto-skip" if auto else "")
        )

    lines += [
        "",
        F.DIV,
        f"🆔 <code>{cid}</code>",
    ]

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"{F.EMO['back']} {F.sc('back')}",
                callback_data=f"adm:flw_edit:{cat}:{cid}:{flow_name}",
            ),
            InlineKeyboardButton(
                f"{F.EMO['cross']} {F.sc('close')}",
                callback_data="adm:close",
            ),
        ],
    ])
    return "\n".join(lines)[:4000], kb


# ============================================================
# SECTION 11 — SAFE EDIT
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
            logger.debug(f"[FLW-ADMIN] edit: {e}")


# ============================================================
# SECTION 12 — CALLBACK ROUTER
# ============================================================

@Client.on_callback_query(
    filters.regex(r"^adm:flw_"),
    group=-9525,
)
async def flow_admin_router(client: Client, q: CallbackQuery):
    if not q.from_user or not _is_admin(q.from_user.id):
        return await q.answer("⛔ Admin only", show_alert=True)

    data = str(q.data)
    parts = data.split(":")
    # Format: adm:flw_ACTION:...
    action = parts[1][4:] if len(parts) > 1 and parts[1].startswith("flw_") else ""

    try:
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

        # ── EDITOR (step list) ──
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

        # ── PREVIEW ──
        if action == "prev":
            cat = parts[2]
            cid = int(parts[3])
            flow_name = parts[4]
            text, kb = await render_preview(cat, cid, flow_name)
            await _safe_edit(q, text, kb)
            return await q.answer()

        # ── TOGGLE enable ──
        if action == "tog":
            cat = parts[2]
            cid = int(parts[3])
            flow_name = parts[4]
            idx = int(parts[5])

            flow = await get_flow_for(cid, flow_name)
            steps = flow.all_steps_sorted()
            if 0 <= idx < len(steps):
                new_state = toggle_step(flow, steps[idx]["type"])
                await set_flow_for(cid, flow)
                await q.answer(
                    f"{'🟢 enabled' if new_state else '🔴 disabled'}"
                )
            text, kb = await render_step(cat, cid, flow_name, idx)
            await _safe_edit(q, text, kb)
            return

        # ── SET per_row ──
        if action == "row":
            cat = parts[2]
            cid = int(parts[3])
            flow_name = parts[4]
            idx = int(parts[5])
            n = int(parts[6])

            flow = await get_flow_for(cid, flow_name)
            steps = flow.all_steps_sorted()
            if 0 <= idx < len(steps):
                set_step_field(flow, steps[idx]["type"], "per_row", n)
                await set_flow_for(cid, flow)
            await q.answer(f"📐 {n}/row")
            text, kb = await render_step(cat, cid, flow_name, idx)
            await _safe_edit(q, text, kb)
            return

        # ── TOGGLE auto-skip ──
        if action == "skip":
            cat = parts[2]
            cid = int(parts[3])
            flow_name = parts[4]
            idx = int(parts[5])

            flow = await get_flow_for(cid, flow_name)
            steps = flow.all_steps_sorted()
            if 0 <= idx < len(steps):
                cur = steps[idx].get("auto_skip_if_one", True)
                set_step_field(
                    flow, steps[idx]["type"],
                    "auto_skip_if_one", not cur,
                )
                await set_flow_for(cid, flow)
            await q.answer("🔄 toggled")
            text, kb = await render_step(cat, cid, flow_name, idx)
            await _safe_edit(q, text, kb)
            return

        # ── MOVE UP ──
        if action == "up":
            cat = parts[2]
            cid = int(parts[3])
            flow_name = parts[4]
            idx = int(parts[5])

            flow = await get_flow_for(cid, flow_name)
            steps = flow.all_steps_sorted()
            if 0 <= idx < len(steps):
                moved = move_step(flow, steps[idx]["type"], "up")
                if moved:
                    await set_flow_for(cid, flow)
                    idx -= 1
                    await q.answer("⬆️ moved")
                else:
                    await q.answer("⚠️ already at top")
            text, kb = await render_step(cat, cid, flow_name, idx)
            await _safe_edit(q, text, kb)
            return

        # ── MOVE DOWN ──
        if action == "down":
            cat = parts[2]
            cid = int(parts[3])
            flow_name = parts[4]
            idx = int(parts[5])

            flow = await get_flow_for(cid, flow_name)
            steps = flow.all_steps_sorted()
            if 0 <= idx < len(steps):
                moved = move_step(flow, steps[idx]["type"], "down")
                if moved:
                    await set_flow_for(cid, flow)
                    idx += 1
                    await q.answer("⬇️ moved")
                else:
                    await q.answer("⚠️ already at bottom")
            text, kb = await render_step(cat, cid, flow_name, idx)
            await _safe_edit(q, text, kb)
            return

        # ── RESET STEP ──
        if action == "rst_step":
            cat = parts[2]
            cid = int(parts[3])
            flow_name = parts[4]
            idx = int(parts[5])

            flow = await get_flow_for(cid, flow_name)
            steps = flow.all_steps_sorted()
            if 0 <= idx < len(steps):
                reset_step_to_default(flow, steps[idx]["type"])
                await set_flow_for(cid, flow)
            await q.answer("♻️ reset")
            text, kb = await render_step(cat, cid, flow_name, idx)
            await _safe_edit(q, text, kb)
            return

        # ── RESET ALL (confirm) ──
        if action == "rst_all":
            cat = parts[2]
            cid = int(parts[3])
            flow_name = parts[4]
            text = "\n".join([
                f"{F.EMO['warn']} <b>{F.fb('RESET FLOW?')}</b>",
                F.DIV, "",
                f"📌 {F.sc('all custom settings for this flow')}",
                f"📌 {F.sc('will revert to defaults')}",
                "",
                F.DIV_S,
            ])
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    f"♻️ {F.sc('yes, reset')}",
                    callback_data=f"adm:flw_rst_do:{cat}:{cid}:{flow_name}",
                )],
                [InlineKeyboardButton(
                    f"{F.EMO['back']} {F.sc('cancel')}",
                    callback_data=f"adm:flw_edit:{cat}:{cid}:{flow_name}",
                )],
            ])
            await _safe_edit(q, text, kb)
            return await q.answer()

        if action == "rst_do":
            cat = parts[2]
            cid = int(parts[3])
            flow_name = parts[4]
            await delete_flow_for(cid, flow_name)
            await q.answer("♻️ reset complete")
            text, kb = await render_editor(cat, cid, flow_name)
            await _safe_edit(q, text, kb)
            return

        return await q.answer("❓ unknown", show_alert=True)

    except Exception as e:
        logger.exception(f"[FLW-ADMIN] router: {e}")
        try:
            await q.answer(f"❌ {type(e).__name__}", show_alert=True)
        except Exception:
            pass


# ============================================================
# SECTION 13 — PUBLIC EXPORTS
# ============================================================

__all__ = [
    "build",
    "render_home",
    "render_category",
    "render_target",
    "render_editor",
    "render_step",
    "render_preview",
]
