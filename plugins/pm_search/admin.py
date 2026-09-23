# ============================================================
# 🏨 DOWNTOWN VILLA — PM SEARCH ADMIN PANEL (/pmsearch)
# ============================================================

from __future__ import annotations
import logging, time
from typing import Any, Dict, List, Optional

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from core import config
from utils import fonts as F
from utils import format as FM
from plugins.pm_search import state as CFG

logger = logging.getLogger(__name__)

PFX = "pmsa"
DIV = F.DIV

_pending: Dict[int, Dict[str, Any]] = {}
PENDING_TTL = 600.0


def _is_admin(uid) -> bool:
    try:
        return int(uid) in [int(a) for a in config.ADMINS]
    except Exception:
        return False


def _set_pending(uid: int, **data) -> None:
    _pending[int(uid)] = {"expires": time.time() + PENDING_TTL, **data}


def _get_pending(uid: int) -> Optional[Dict[str, Any]]:
    s = _pending.get(int(uid))
    if not s:
        return None
    if time.time() > s.get("expires", 0):
        _pending.pop(int(uid), None)
        return None
    return s


def _drop_pending(uid: int) -> None:
    _pending.pop(int(uid), None)


# ============================================================
# MAIN PANEL
# ============================================================

async def _render_main() -> tuple:
    cfg = await CFG.get_cfg()
    fsub_ch = len(cfg.get("fsub_channels") or [])
    del_btn = len([b for b in (cfg.get("delivered_buttons") or [])
                   if b.get("enabled", True)])

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"⚙️ <b>{F.fb('PM SEARCH SETTINGS')}</b>",
        DIV, "",
        f"{'🟢' if cfg.get('enabled') else '🔴'} {F.sc('enabled')}",
        f"📁 {F.sc('per row')} · <b>{cfg.get('per_row', 2)}</b>",
        f"🔢 {F.sc('max buttons')} · <b>{cfg.get('max_buttons', 15)}</b>",
        f"📊 {F.sc('sort')} · <code>{cfg.get('sort_order')}</code>",
        "",
        f"🖼️ {F.sc('poster')} · "
        f"{'🟢' if cfg.get('show_poster') else '🔴'}",
        f"⭐ {F.sc('rating')} · "
        f"{'🟢' if cfg.get('show_rating') else '🔴'}",
        f"📅 {F.sc('year')} · "
        f"{'🟢' if cfg.get('show_year') else '🔴'}",
        f"📖 {F.sc('overview')} · "
        f"{'🟢' if cfg.get('show_overview') else '🔴'}",
        "",
        f"🔍 {F.sc('suggestions')} · "
        f"{'🟢' if cfg.get('suggestion_enabled') else '🔴'} "
        f"(<b>{cfg.get('suggestion_count', 6)}</b>)",
        f"📩 {F.sc('request')} · "
        f"{'🟢' if cfg.get('request_enabled') else '🔴'}",
        "",
        f"🗑️ {F.sc('auto delete')} · "
        f"{'🟢' if cfg.get('auto_delete_enabled') else '🔴'} "
        f"<b>{cfg.get('auto_delete_minutes', 10)}m</b>",
        f"📤 {F.sc('share button')} · "
        f"{'🟢' if cfg.get('share_button') else '🔴'}",
        f"🔘 {F.sc('buttons')} · <b>{del_btn}</b> "
        f"· <b>{cfg.get('delivered_buttons_per_row', 2)}/row</b>",
        "",
        f"🔒 {F.sc('force-sub')} · "
        f"{'🟢 ON' if cfg.get('fsub_enabled') else '🔴 OFF'}",
        f"📢 {F.sc('fsub channels')} · <b>{fsub_ch}</b>",
        "",
        DIV,
        f"🕒 <code>{FM.datetime_()}</code>",
    ]

    rows: List[List[InlineKeyboardButton]] = [
        [InlineKeyboardButton(
            f"{'🟢' if cfg.get('enabled') else '🔴'} {F.sc('enable/disable')}",
            callback_data=f"{PFX}:tog:enabled",
        )],
        [
            InlineKeyboardButton(
                f"📁 {F.sc('per row')}",
                callback_data=f"{PFX}:noop",
            ),
            InlineKeyboardButton(
                f"{'✅' if cfg.get('per_row') == 1 else ''}1",
                callback_data=f"{PFX}:row:1",
            ),
            InlineKeyboardButton(
                f"{'✅' if cfg.get('per_row') == 2 else ''}2",
                callback_data=f"{PFX}:row:2",
            ),
            InlineKeyboardButton(
                f"{'✅' if cfg.get('per_row') == 3 else ''}3",
                callback_data=f"{PFX}:row:3",
            ),
        ],
        [
            InlineKeyboardButton(
                f"📊 {F.sc('sort')} · "
                f"{'small→big' if cfg.get('sort_order') == 'small_to_big' else 'big→small'}",
                callback_data=f"{PFX}:sort",
            ),
            InlineKeyboardButton(
                f"🔢 {F.sc('max')} · {cfg.get('max_buttons', 15)}",
                callback_data=f"{PFX}:max",
            ),
        ],
        [
            InlineKeyboardButton(
                f"{'🟢' if cfg.get('show_poster') else '🔴'} 🖼️",
                callback_data=f"{PFX}:tog:show_poster",
            ),
            InlineKeyboardButton(
                f"{'🟢' if cfg.get('show_rating') else '🔴'} ⭐",
                callback_data=f"{PFX}:tog:show_rating",
            ),
            InlineKeyboardButton(
                f"{'🟢' if cfg.get('show_year') else '🔴'} 📅",
                callback_data=f"{PFX}:tog:show_year",
            ),
            InlineKeyboardButton(
                f"{'🟢' if cfg.get('show_overview') else '🔴'} 📖",
                callback_data=f"{PFX}:tog:show_overview",
            ),
        ],
        [
            InlineKeyboardButton(
                f"{'🟢' if cfg.get('show_quality') else '🔴'} Q",
                callback_data=f"{PFX}:tog:show_quality",
            ),
            InlineKeyboardButton(
                f"{'🟢' if cfg.get('show_size') else '🔴'} S",
                callback_data=f"{PFX}:tog:show_size",
            ),
            InlineKeyboardButton(
                f"{'🟢' if cfg.get('show_languages') else '🔴'} L",
                callback_data=f"{PFX}:tog:show_languages",
            ),
        ],
        [
            InlineKeyboardButton(
                f"{'🟢' if cfg.get('suggestion_enabled') else '🔴'} "
                f"{F.sc('suggestions')} ({cfg.get('suggestion_count', 6)})",
                callback_data=f"{PFX}:sug",
            ),
            InlineKeyboardButton(
                f"{'🟢' if cfg.get('request_enabled') else '🔴'} "
                f"{F.sc('request')}",
                callback_data=f"{PFX}:tog:request_enabled",
            ),
        ],
        [
            InlineKeyboardButton(
                f"{'🟢' if cfg.get('auto_delete_enabled') else '🔴'} "
                f"🗑️ {F.sc('auto delete')} · "
                f"{cfg.get('auto_delete_minutes', 10)}m",
                callback_data=f"{PFX}:ad_tog",
            ),
            InlineKeyboardButton(
                f"⏱️ {F.sc('minutes')}",
                callback_data=f"{PFX}:ad_min",
            ),
        ],
        [
            InlineKeyboardButton(
                f"✏️ {F.sc('edit delete warning')}",
                callback_data=f"{PFX}:ad_msg",
            ),
        ],
        [
            InlineKeyboardButton(
                f"{'🟢' if cfg.get('share_button') else '🔴'} "
                f"📤 {F.sc('share button')}",
                callback_data=f"{PFX}:tog:share_button",
            ),
        ],
        [
            InlineKeyboardButton(
                f"📝 {F.sc('caption')}",
                callback_data=f"{PFX}:cap:edit",
            ),
            InlineKeyboardButton(
                f"👁️ {F.sc('preview')}",
                callback_data=f"{PFX}:cap:preview",
            ),
        ],
        [
            InlineKeyboardButton(
                f"🔘 {F.sc('buttons')} ({del_btn})",
                callback_data=f"{PFX}:btn:list",
            ),
            InlineKeyboardButton(
                f"➕ {F.sc('add')}",
                callback_data=f"{PFX}:btn:add",
            ),
        ],
        [
            InlineKeyboardButton(
                f"📐 {F.sc('btn/row')} · "
                f"{cfg.get('delivered_buttons_per_row', 2)}",
                callback_data=f"{PFX}:btnrow",
            ),
        ],
        [
            InlineKeyboardButton(
                f"{'🟢' if cfg.get('fsub_enabled') else '🔴'} 🔒 "
                f"{F.sc('force-sub')}",
                callback_data=f"{PFX}:tog:fsub_enabled",
            ),
        ],
        [
            InlineKeyboardButton(
                f"📢 {F.sc('fsub channels')} ({fsub_ch})",
                callback_data=f"{PFX}:fsub:list",
            ),
            InlineKeyboardButton(
                f"➕ {F.sc('add')}",
                callback_data=f"{PFX}:fsub:add",
            ),
        ],
        [
            InlineKeyboardButton(
                f"✏️ {F.sc('fsub message')}",
                callback_data=f"{PFX}:fsub:msg",
            ),
        ],
        [
            InlineKeyboardButton(
                f"{F.EMO['refresh']} {F.sc('refresh')}",
                callback_data=f"{PFX}:home",
            ),
            InlineKeyboardButton(
                f"♻️ {F.sc('reset')}",
                callback_data=f"{PFX}:reset",
            ),
        ],
        [
            InlineKeyboardButton(
                f"{F.EMO['close']} {F.sc('close')}",
                callback_data=f"{PFX}:close",
            ),
        ],
    ]

    return "\n".join(lines)[:4000], InlineKeyboardMarkup(rows)


# ============================================================
# COMMAND
# ============================================================

@Client.on_message(
    filters.command(["pmsearch", "pmcfg"]) & filters.private,
    group=-8150,
)
async def cmd_pmsearch(client: Client, message: Message):
    if not message.from_user or not _is_admin(message.from_user.id):
        return await message.reply_text(
            f"{F.EMO['cross']} <b>{F.fb('ADMIN ONLY')}</b>",
            parse_mode=ParseMode.HTML,
        )
    text, kb = await _render_main()
    await message.reply_text(
        text, reply_markup=kb,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


# ============================================================
# ROUTER
# ============================================================

@Client.on_callback_query(
    filters.regex(rf"^{PFX}:"),
    group=-8150,
)
async def pmsa_router(client: Client, q: CallbackQuery):
    if not q.from_user or not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)

    parts = str(q.data).split(":")
    action = parts[1] if len(parts) > 1 else ""
    arg = parts[2] if len(parts) > 2 else ""
    uid = q.from_user.id

    try:
        if action == "home":
            _drop_pending(uid)
            text, kb = await _render_main()
            await _edit(q, text, kb)
            return await q.answer()

        if action == "close":
            try:
                await q.message.delete()
            except Exception:
                pass
            return await q.answer("Closed")

        if action == "noop":
            return await q.answer()

        if action == "tog":
            cfg = await CFG.get_cfg()
            cur = bool(cfg.get(arg, False))
            await CFG.set_cfg(**{arg: not cur})
            await q.answer("🟢" if not cur else "🔴")
            text, kb = await _render_main()
            await _edit(q, text, kb)
            return

        if action == "row":
            try:
                n = int(arg)
            except ValueError:
                n = 2
            await CFG.set_cfg(per_row=n)
            await q.answer(f"📁 {n}/row")
            text, kb = await _render_main()
            await _edit(q, text, kb)
            return

        if action == "sort":
            cfg = await CFG.get_cfg()
            cur = cfg.get("sort_order", "small_to_big")
            new = "big_to_small" if cur == "small_to_big" else "small_to_big"
            await CFG.set_cfg(sort_order=new)
            await q.answer(f"📊 {new}")
            text, kb = await _render_main()
            await _edit(q, text, kb)
            return

        if action == "max":
            cfg = await CFG.get_cfg()
            cur = int(cfg.get("max_buttons", 15))
            opts = [5, 10, 15, 20, 30]
            try:
                i = opts.index(cur)
                new = opts[(i + 1) % len(opts)]
            except ValueError:
                new = 15
            await CFG.set_cfg(max_buttons=new)
            await q.answer(f"🔢 max {new}")
            text, kb = await _render_main()
            await _edit(q, text, kb)
            return

        if action == "sug":
            cfg = await CFG.get_cfg()
            cur = int(cfg.get("suggestion_count", 6))
            opts = [3, 5, 6, 8, 10]
            try:
                i = opts.index(cur)
                new = opts[(i + 1) % len(opts)]
            except ValueError:
                new = 6
            await CFG.set_cfg(suggestion_count=new)
            await q.answer(f"🔢 {new}")
            text, kb = await _render_main()
            await _edit(q, text, kb)
            return

        if action == "ad_tog":
            cfg = await CFG.get_cfg()
            cur = bool(cfg.get("auto_delete_enabled", False))
            await CFG.set_cfg(auto_delete_enabled=not cur)
            await q.answer("🟢" if not cur else "🔴")
            text, kb = await _render_main()
            await _edit(q, text, kb)
            return

        if action == "ad_min":
            cfg = await CFG.get_cfg()
            cur = int(cfg.get("auto_delete_minutes", 10))
            opts = [5, 10, 15, 20, 30, 60]
            try:
                i = opts.index(cur)
                new = opts[(i + 1) % len(opts)]
            except ValueError:
                new = 10
            await CFG.set_cfg(auto_delete_minutes=new)
            await q.answer(f"⏱️ {new}m")
            text, kb = await _render_main()
            await _edit(q, text, kb)
            return

        if action == "ad_msg":
            _set_pending(uid, kind="ad_msg")
            lines = [
                f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                f"✏️ <b>{F.fb('EDIT DELETE WARNING')}</b>",
                DIV, "",
                f"📌 {F.sc('send the new warning message')}",
                f"📌 {F.sc('use')} <code>{{minutes}}</code> "
                f"{F.sc('for the number')}",
                f"📌 {F.sc('send')} <code>-</code> {F.sc('to reset')}",
            ]
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"{F.EMO['back']} {F.sc('cancel')}",
                    callback_data=f"{PFX}:home",
                ),
            ]])
            await _edit(q, "\n".join(lines), kb)
            return await q.answer()

        if action == "cap" and arg == "edit":
            _set_pending(uid, kind="caption")
            lines = [
                f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                f"📝 <b>{F.fb('EDIT CAPTION')}</b>",
                DIV, "",
                f"📌 {F.sc('placeholders')}:",
                f"<code>{{title}} {{year}} {{quality}} {{codec}}</code>",
                f"<code>{{audio}} {{subtitle}} {{size}}</code>",
                f"<code>{{season}} {{episode}}</code>",
                "",
                f"📌 {F.sc('send')} <code>-</code> {F.sc('to reset')}",
            ]
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"{F.EMO['back']} {F.sc('cancel')}",
                    callback_data=f"{PFX}:home",
                ),
            ]])
            await _edit(q, "\n".join(lines), kb)
            return await q.answer()

        if action == "cap" and arg == "preview":
            cfg = await CFG.get_cfg()
            tpl = cfg.get("caption_template") or ""
            sample = {
                "title": "Karnan", "year": "2021",
                "quality": "1080P", "codec": "HEVC",
                "audio": "Tamil", "subtitle": "English",
                "size": "1.4 GB", "season": "", "episode": "",
            }
            try:
                preview = tpl.format(**sample)
            except Exception as e:
                preview = f"(error: {e})\n\n{tpl}"
            lines = [
                f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                f"👁️ <b>{F.fb('CAPTION PREVIEW')}</b>",
                DIV, "",
                preview,
            ]
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"{F.EMO['back']} {F.sc('back')}",
                    callback_data=f"{PFX}:home",
                ),
            ]])
            await _edit(q, "\n".join(lines)[:4000], kb)
            return await q.answer()

        # ── DELIVERED BUTTONS ──
        if action == "btn" and arg == "list":
            cfg = await CFG.get_cfg()
            btns = cfg.get("delivered_buttons") or []
            lines = [
                f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                f"🔘 <b>{F.fb('DELIVERED BUTTONS')}</b>",
                DIV, "",
                f"📊 {F.sc('total')} · <b>{len(btns)}</b>",
                "",
            ]
            rows: List[List[InlineKeyboardButton]] = []
            if not btns:
                lines.append(f"⚪ {F.sc('no buttons')}")
            else:
                for i, b in enumerate(btns, 1):
                    if not isinstance(b, dict):
                        continue
                    name = str(b.get("name", "?"))[:36]
                    en = b.get("enabled", True)
                    lines.append(
                        f"<b>{i:02d}.</b> {'🟢' if en else '🔴'} {F.sc(name)}"
                    )
                    rows.append([InlineKeyboardButton(
                        f"{'🟢' if en else '🔴'} {name}",
                        callback_data=f"{PFX}:btn:view:{i - 1}",
                    )])
            rows.append([
                InlineKeyboardButton(
                    f"➕ {F.sc('add')}",
                    callback_data=f"{PFX}:btn:add",
                ),
                InlineKeyboardButton(
                    f"{F.EMO['back']} {F.sc('back')}",
                    callback_data=f"{PFX}:home",
                ),
            ])
            await _edit(q, "\n".join(lines)[:4000],
                        InlineKeyboardMarkup(rows))
            return await q.answer()

        if action == "btn" and arg == "add":
            _set_pending(uid, kind="btn_add")
            lines = [
                f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                f"➕ <b>{F.fb('ADD BUTTON')}</b>",
                DIV, "",
                f"📌 {F.sc('send')} <code>Name | URL</code>",
            ]
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"{F.EMO['back']} {F.sc('cancel')}",
                    callback_data=f"{PFX}:home",
                ),
            ]])
            await _edit(q, "\n".join(lines), kb)
            return await q.answer()

        if action == "btn" and arg == "view":
            try:
                idx = int(parts[3])
            except (ValueError, IndexError):
                return await q.answer("❌")
            cfg = await CFG.get_cfg()
            btns = cfg.get("delivered_buttons") or []
            if idx < 0 or idx >= len(btns):
                return await q.answer("❌")
            b = btns[idx]
            en = b.get("enabled", True)
            lines = [
                f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                f"🔘 <b>{F.fb('BUTTON DETAIL')}</b>",
                DIV, "",
                f"📛 <b>{F.sc(str(b.get('name', '?'))[:60])}</b>",
                f"🔗 <code>{str(b.get('url', '?'))[:60]}</code>",
            ]
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    f"{'🔴 disable' if en else '🟢 enable'}",
                    callback_data=f"{PFX}:btn:tog:{idx}",
                )],
                [InlineKeyboardButton(
                    f"🗑️ {F.sc('delete')}",
                    callback_data=f"{PFX}:btn:del:{idx}",
                )],
                [InlineKeyboardButton(
                    f"{F.EMO['back']} {F.sc('back')}",
                    callback_data=f"{PFX}:btn:list",
                )],
            ])
            await _edit(q, "\n".join(lines), kb)
            return await q.answer()

        if action == "btn" and arg == "tog":
            try:
                idx = int(parts[3])
            except (ValueError, IndexError):
                return await q.answer("❌")
            cfg = await CFG.get_cfg()
            btns = list(cfg.get("delivered_buttons") or [])
            if 0 <= idx < len(btns):
                btns[idx]["enabled"] = not btns[idx].get("enabled", True)
                await CFG.set_cfg(delivered_buttons=btns)
            await q.answer("✅")
            text, kb = await _render_main()
            await _edit(q, text, kb)
            return

        if action == "btn" and arg == "del":
            try:
                idx = int(parts[3])
            except (ValueError, IndexError):
                return await q.answer("❌")
            cfg = await CFG.get_cfg()
            btns = list(cfg.get("delivered_buttons") or [])
            if 0 <= idx < len(btns):
                btns.pop(idx)
                await CFG.set_cfg(delivered_buttons=btns)
            await q.answer("🗑️")
            text, kb = await _render_main()
            await _edit(q, text, kb)
            return

        if action == "btnrow":
            cfg = await CFG.get_cfg()
            cur = int(cfg.get("delivered_buttons_per_row", 2))
            opts = [1, 2, 3]
            try:
                i = opts.index(cur)
                new = opts[(i + 1) % len(opts)]
            except ValueError:
                new = 2
            await CFG.set_cfg(delivered_buttons_per_row=new)
            await q.answer(f"📐 {new}/row")
            text, kb = await _render_main()
            await _edit(q, text, kb)
            return

        # ── FSUB ──
        if action == "fsub" and arg == "list":
            cfg = await CFG.get_cfg()
            ch = cfg.get("fsub_channels") or []
            lines = [
                f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                f"📢 <b>{F.fb('FORCE-SUB CHANNELS')}</b>",
                DIV, "",
                f"📊 {F.sc('total')} · <b>{len(ch)}</b>",
                "",
            ]
            rows: List[List[InlineKeyboardButton]] = []
            for i, c in enumerate(ch, 1):
                lines.append(f"<b>{i:02d}.</b> <code>{c}</code>")
                rows.append([InlineKeyboardButton(
                    f"🗑️ {c}",
                    callback_data=f"{PFX}:fsub:del:{i - 1}",
                )])
            if not ch:
                lines.append(f"⚪ {F.sc('no channels')}")
            rows.append([
                InlineKeyboardButton(
                    f"➕ {F.sc('add')}",
                    callback_data=f"{PFX}:fsub:add",
                ),
                InlineKeyboardButton(
                    f"{F.EMO['back']} {F.sc('back')}",
                    callback_data=f"{PFX}:home",
                ),
            ])
            await _edit(q, "\n".join(lines)[:4000],
                        InlineKeyboardMarkup(rows))
            return await q.answer()

        if action == "fsub" and arg == "add":
            _set_pending(uid, kind="fsub_add")
            lines = [
                f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                f"➕ <b>{F.fb('ADD FSUB CHANNEL')}</b>",
                DIV, "",
                f"📌 {F.sc('send channel id or @username')}",
                f"📌 {F.sc('bot must be admin in that channel')}",
                f"📌 {F.sc('add multiple channels — user must join all')}",
            ]
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"{F.EMO['back']} {F.sc('cancel')}",
                    callback_data=f"{PFX}:home",
                ),
            ]])
            await _edit(q, "\n".join(lines), kb)
            return await q.answer()

        if action == "fsub" and arg == "del":
            try:
                idx = int(parts[3])
            except (ValueError, IndexError):
                return await q.answer("❌")
            cfg = await CFG.get_cfg()
            ch = list(cfg.get("fsub_channels") or [])
            if 0 <= idx < len(ch):
                ch.pop(idx)
                await CFG.set_cfg(fsub_channels=ch)
            await q.answer("🗑️")
            text, kb = await _render_main()
            await _edit(q, text, kb)
            return

        if action == "fsub" and arg == "msg":
            _set_pending(uid, kind="fsub_msg")
            lines = [
                f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                f"✏️ <b>{F.fb('EDIT FSUB MESSAGE')}</b>",
                DIV, "",
                f"📌 {F.sc('send the new message as text')}",
                f"📌 {F.sc('send')} <code>-</code> {F.sc('to reset')}",
            ]
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"{F.EMO['back']} {F.sc('cancel')}",
                    callback_data=f"{PFX}:home",
                ),
            ]])
            await _edit(q, "\n".join(lines), kb)
            return await q.answer()

        if action == "reset":
            text = "\n".join([
                f"{F.EMO['warn']} <b>{F.fb('RESET PM SEARCH?')}</b>",
                DIV, "",
                f"{F.EMO['warn']} {F.sc('restores all defaults')}",
            ])
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    f"♻️ {F.sc('yes, reset')}",
                    callback_data=f"{PFX}:reset_do",
                )],
                [InlineKeyboardButton(
                    f"{F.EMO['back']} {F.sc('cancel')}",
                    callback_data=f"{PFX}:home",
                )],
            ])
            await _edit(q, text, kb)
            return await q.answer()

        if action == "reset_do":
            await CFG.reset_cfg()
            await q.answer("♻️ Reset")
            text, kb = await _render_main()
            await _edit(q, text, kb)
            return

        return await q.answer("❓")

    except Exception as e:
        logger.exception(f"[PMSA] router: {e}")
        try:
            await q.answer(f"❌ {type(e).__name__}", show_alert=True)
        except Exception:
            pass


# ============================================================
# TEXT INPUT
# ============================================================

@Client.on_message(
    filters.private & filters.text & ~filters.regex(r"^/"),
    group=-8140,
)
async def pmsa_text_input(client: Client, message: Message):
    if not message.from_user or not _is_admin(message.from_user.id):
        return

    p = _get_pending(message.from_user.id)
    if not p:
        return

    kind = p.get("kind")
    text = (message.text or "").strip()
    if not text:
        return

    try:
        if kind == "caption":
            if text == "-":
                await CFG.set_cfg(
                    caption_template=CFG.DEFAULT_CFG["caption_template"]
                )
            else:
                await CFG.set_cfg(caption_template=text)
            _drop_pending(message.from_user.id)
            await message.reply_text(
                f"{F.EMO['check']} <b>Caption updated</b>",
                parse_mode=ParseMode.HTML,
            )

        elif kind == "ad_msg":
            if text == "-":
                await CFG.set_cfg(
                    auto_delete_warning=CFG.DEFAULT_CFG["auto_delete_warning"]
                )
            else:
                await CFG.set_cfg(auto_delete_warning=text)
            _drop_pending(message.from_user.id)
            await message.reply_text(
                f"{F.EMO['check']} <b>Warning updated</b>",
                parse_mode=ParseMode.HTML,
            )

        elif kind == "btn_add":
            if "|" not in text:
                return await message.reply_text(
                    f"{F.EMO['cross']} <code>Name | URL</code>",
                    parse_mode=ParseMode.HTML,
                )
            name, url = [x.strip() for x in text.split("|", 1)]
            if not name or not url:
                return await message.reply_text("❌ empty")
            cfg = await CFG.get_cfg()
            btns = list(cfg.get("delivered_buttons") or [])
            if len(btns) >= 8:
                _drop_pending(message.from_user.id)
                return await message.reply_text("⚠️ max 8")
            btns.append({"name": name[:60], "url": url, "enabled": True})
            await CFG.set_cfg(delivered_buttons=btns)
            _drop_pending(message.from_user.id)
            await message.reply_text(
                f"{F.EMO['check']} <b>Button added</b>",
                parse_mode=ParseMode.HTML,
            )

        elif kind == "fsub_add":
            cid = None
            if text.startswith("@"):
                try:
                    ch = await client.get_chat(text)
                    cid = int(ch.id)
                except Exception as e:
                    return await message.reply_text(f"❌ {e}")
            else:
                try:
                    cid = int(text)
                except ValueError:
                    return await message.reply_text("❌ invalid")
            cfg = await CFG.get_cfg()
            ch = list(cfg.get("fsub_channels") or [])
            if cid in ch:
                return await message.reply_text("⚠️ already added")
            ch.append(cid)
            await CFG.set_cfg(fsub_channels=ch)
            _drop_pending(message.from_user.id)
            await message.reply_text(
                f"{F.EMO['check']} <b>Added</b> · <code>{cid}</code>",
                parse_mode=ParseMode.HTML,
            )

        elif kind == "fsub_msg":
            if text == "-":
                await CFG.set_cfg(fsub_message=CFG.DEFAULT_CFG["fsub_message"])
            else:
                await CFG.set_cfg(fsub_message=text)
            _drop_pending(message.from_user.id)
            await message.reply_text(
                f"{F.EMO['check']} <b>Message updated</b>",
                parse_mode=ParseMode.HTML,
            )

        try:
            message.stop_propagation()
        except Exception:
            pass

    except Exception as e:
        logger.exception(f"[PMSA] text: {e}")


async def _edit(q: CallbackQuery, text: str, kb) -> None:
    try:
        await q.message.edit_text(
            text, reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        if "not modified" not in str(e).lower():
            logger.debug(f"[PMSA] edit: {e}")


__all__ = ["cmd_pmsearch"]
