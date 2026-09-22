# ============================================================
# 🏨 DOWNTOWN VILLA — /missing COMMAND
# ============================================================
#
# Full panel + customizable flow:
#   Type → Industry → Year → Month → Week → Scan
#
# Admin settings:
#   • Edit templates (header / item / footer)
#   • Edit buttons
#   • Set defaults (industry, pages, per_part)
#   • Save / load presets
#   • View history
# ============================================================

from __future__ import annotations
import asyncio, logging, time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from core import config
from plugins.missing import state as S
from plugins.missing import scan as SC
from plugins.missing import templates as T
from utils import fonts as F
from utils import format as FM

logger = logging.getLogger(__name__)

PFX = "ms"
MOVIES_PER_PART = 25


def _is_admin(uid) -> bool:
    try:
        return int(uid) in [int(a) for a in config.ADMINS]
    except Exception:
        return False


# ── SESSION ──
_sessions: Dict[int, Dict[str, Any]] = {}
TTL = 900.0


def _ss_get(uid: int) -> Optional[Dict[str, Any]]:
    s = _sessions.get(int(uid))
    if not s: return None
    if time.time() > s["exp"]:
        _sessions.pop(int(uid), None)
        return None
    return s


def _ss_new(uid: int, **data):
    _sessions[int(uid)] = {"exp": time.time() + TTL, **data}


def _ss_set(uid: int, **data):
    s = _sessions.get(int(uid))
    if s:
        s.update(data)
        s["exp"] = time.time() + TTL


def _ss_drop(uid: int):
    _sessions.pop(int(uid), None)


# ── MAIN ──
async def _build_main() -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await S.get_cfg()
    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"🔍 <b>{F.fb('MISSING FINDER')}</b>",
        F.DIV, "",
        f"📌 {F.sc('compare tmdb vs local db')}",
        f"📌 {F.sc('find every missing movie')}",
        f"📌 {F.sc('copy-friendly output')}",
        "",
        F.DIV_S,
        f"⚙️ {F.sc('default industry')} · "
        f"<b>{cfg.get('default_industry', 'hollywood')}</b>",
        f"📊 {F.sc('results per part')} · "
        f"<b>{cfg.get('movies_per_part', 25)}</b>",
    ]

    rows = [
        [InlineKeyboardButton(
            f"🎬 {F.sc('missing movies')}",
            callback_data=f"{PFX}:type:movie",
        )],
        [InlineKeyboardButton(
            f"📺 {F.sc('missing series')}",
            callback_data=f"{PFX}:type:series",
        )],
        [
            InlineKeyboardButton(
                f"📚 {F.sc('presets')}",
                callback_data=f"{PFX}:presets",
            ),
            InlineKeyboardButton(
                f"🧾 {F.sc('history')}",
                callback_data=f"{PFX}:history",
            ),
        ],
    ]

    if _is_admin(0):  # will be replaced with real check
        pass

    # Settings button — safe to always show since _build_main
    # is only invoked from cmd_missing (admin-gated).
    rows.append([
        InlineKeyboardButton(
            f"⚙️ {F.sc('settings')}",
            callback_data=f"{PFX}:settings",
        ),
    ])
    rows.append([InlineKeyboardButton(
        f"{F.EMO['cross']} {F.sc('close')}",
        callback_data=f"{PFX}:close",
    )])

    return "\n".join(lines), InlineKeyboardMarkup(rows)


@Client.on_message(
    filters.command(["missing", "gapscan", "lackfiles"]) & filters.private,
    group=-8400,
)
async def cmd_missing(client: Client, message: Message):
    if not message.from_user or not _is_admin(message.from_user.id):
        return await message.reply_text(
            f"{F.EMO['cross']} <b>{F.fb('ADMIN ONLY')}</b>",
            parse_mode=ParseMode.HTML,
        )

    if not config.TMDB_API_KEY:
        return await message.reply_text(
            f"{F.EMO['warn']} <b>TMDB_API_KEY missing</b>",
            parse_mode=ParseMode.HTML,
        )

    try:
        from plugins.missing import state as S
        pass
    except Exception:
        pass

    text, kb = await _build_main()
    _ss_drop(message.from_user.id)
    await message.reply_text(
        text, reply_markup=kb,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


# ── TYPE → INDUSTRY ──
async def _show_industries(kind: str) -> Tuple[str, InlineKeyboardMarkup]:
    label = "MOVIES" if kind == "movie" else "SERIES"
    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"🔍 <b>{F.fb(f'MISSING {label}')}</b>",
        F.DIV, "",
        f"🌍 {F.sc('pick an industry')}",
    ]

    rows = []
    row = []
    for code, lbl, _ in SC.INDUSTRIES:
        row.append(InlineKeyboardButton(
            lbl, callback_data=f"{PFX}:ind:{kind}:{code}",
        ))
        if len(row) == 2:
            rows.append(row); row = []
    if row: rows.append(row)

    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data=f"{PFX}:home",
        ),
        InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('close')}",
            callback_data=f"{PFX}:close",
        ),
    ])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


# ── YEAR INPUT ──
async def _show_year_prompt(kind: str, code: str, label: str) -> Tuple[str, InlineKeyboardMarkup]:
    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"📅 <b>{F.fb('ENTER YEAR')}</b>",
        F.DIV, "",
        f"🎬 {F.sc('type')} · <code>{kind.upper()}</code>",
        f"🌍 {F.sc('industry')} · <b>{F.sc(label)}</b>",
        "",
        f"📝 {F.sc('send the year as text')}",
        f"📌 {F.sc('example')} · <code>2024</code>",
    ]
    rows = [[
        InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('cancel')}",
            callback_data=f"{PFX}:home",
        ),
    ]]
    return "\n".join(lines), InlineKeyboardMarkup(rows)


# ── MONTHS ──
async def _show_months(kind: str, code: str, label: str, year: int) -> Tuple[str, InlineKeyboardMarkup]:
    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"📅 <b>{F.fb('PICK MONTH')}</b>",
        F.DIV, "",
        f"🎬 {F.sc('type')} · <code>{kind.upper()}</code>",
        f"🌍 {F.sc('industry')} · <b>{F.sc(label)}</b>",
        f"📅 {F.sc('year')} · <code>{year}</code>",
    ]
    rows = []
    row = []
    for i, m in enumerate(SC.MONTHS, 1):
        row.append(InlineKeyboardButton(
            f"📅 {m}", callback_data=f"{PFX}:mo:{kind}:{code}:{year}:{i}",
        ))
        if len(row) == 3:
            rows.append(row); row = []
    if row: rows.append(row)
    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data=f"{PFX}:ind:{kind}:{code}",
        ),
        InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('close')}",
            callback_data=f"{PFX}:close",
        ),
    ])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


# ── WEEKS ──
async def _show_weeks(kind: str, code: str, label: str, year: int, month: int) -> Tuple[str, InlineKeyboardMarkup]:
    weeks = SC.weeks_of_month(year, month)
    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"📅 <b>{F.fb(f'{SC.MONTHS_FULL[month-1]} {year}')}</b>",
        F.DIV, "",
        f"📌 {F.sc('pick a week or full month')}",
    ]
    rows = []
    for wk, st, en in weeks:
        rows.append([InlineKeyboardButton(
            f"📆 W{wk} · {st:02d}-{en:02d} {SC.MONTHS[month-1]}",
            callback_data=f"{PFX}:wk:{kind}:{code}:{year}:{month}:{wk}",
        )])
    rows.append([InlineKeyboardButton(
        f"📅 {F.sc('FULL MONTH')}",
        callback_data=f"{PFX}:wk:{kind}:{code}:{year}:{month}:0",
    )])
    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data=f"{PFX}:mo:{kind}:{code}:{year}:{month}",
        ),
        InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('close')}",
            callback_data=f"{PFX}:close",
        ),
    ])
    return "\n".join(lines), InlineKeyboardMarkup(rows)


# ── RUN SCAN ──
async def _run_scan(
    client: Client, q: CallbackQuery,
    kind: str, code: str, label: str, year: int, month: int, week_num: int,
):
    lang = SC.INDUSTRY_MAP.get(code, ("?", "en"))[1]
    weeks = SC.weeks_of_month(year, month)
    week = None
    if week_num > 0:
        for w in weeks:
            if w[0] == week_num:
                week = w; break

    gte, lte = SC.date_range(year, month, week)
    period = (
        f"FULL {SC.MONTHS_FULL[month-1].upper()} {year}"
        if week is None
        else f"W{week[0]} · {week[1]:02d}-{week[2]:02d} {SC.MONTHS_FULL[month-1]} {year}"
    )
    period_short = (
        f"{SC.MONTHS[month-1]} {year}"
        if week is None
        else f"{SC.MONTHS[month-1]} {year} · W{week[0]}"
    )

    try:
        await q.message.edit_text(
            "\n".join([
                f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                f"🔍 <b>{F.fb('SCANNING')}</b>",
                F.DIV, "",
                f"📅 <code>{period_short}</code>",
                f"🌍 <b>{F.sc(label)}</b>",
                "",
                f"⏳ {F.sc('fetching from tmdb')}…",
            ]),
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass
    await q.answer()

    # Fetch
    if kind == "movie":
        items, raw = await SC.fetch_movies_range(gte, lte, lang)
    else:
        items, raw = await SC.fetch_series_range(gte, lte, lang)

    items = SC.dedupe_by_tmdb(items)
    fetched = len(items)

    # Scan
    missing, in_db = await SC.find_missing(items)
    missing.sort(key=lambda x: x.get("popularity", 0), reverse=True)

    # Log scan
    await S.log_scan({
        "kind": kind, "industry": code, "label": label,
        "year": year, "month": month, "week": week_num,
        "period": period_short,
        "fetched": fetched, "in_db": in_db, "missing": len(missing),
        "owner": q.from_user.id,
    })

    # Send results
    await _send_results(
        client, q.message.chat.id,
        kind=kind, label=label, period=period_short,
        fetched=fetched, in_db=in_db, missing_count=len(missing),
        missing=missing,
        code=code, year=year, month=month,
    )


async def _send_results(
    client, chat_id: int,
    kind: str, label: str, period: str,
    fetched: int, in_db: int, missing_count: int,
    missing: List[Dict], code: str, year: int, month: int,
):
    t = await T.get_template("template") or T.TEMPLATES["default"]
    ctx = {
        "TYPE": "MOVIES" if kind == "movie" else "SERIES",
        "PERIOD": period,
        "INDUSTRY": label,
        "FETCHED": FM.num(fetched),
        "IN_DB": FM.num(in_db),
        "MISSING": FM.num(missing_count),
        "TIME": FM.datetime_(),
    }

    header = T.render_header(t, ctx)
    footer = T.render_footer(t, ctx)

    # No missing
    if missing_count == 0:
        try:
            await client.send_message(
                chat_id=chat_id,
                text=header + "\n🎉 <b>Your DB is complete for this range!</b>",
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except Exception:
            pass
        return

    # Send header
    try:
        await client.send_message(
            chat_id=chat_id,
            text=header,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception:
        pass

    # Chunks
    total_parts = (len(missing) + MOVIES_PER_PART - 1) // MOVIES_PER_PART

    for p in range(total_parts):
        chunk = missing[p * MOVIES_PER_PART:(p + 1) * MOVIES_PER_PART]
        lines = [
            f"🏨 <b>{F.fb('DOWNTOWN VILLA')}</b>",
            f"🔍 <b>{F.fb('MISSING ' + ('MOVIES' if kind == 'movie' else 'SERIES'))}</b>",
            f"📅 <code>{period}</code> · 🌍 <b>{F.sc(label)}</b>",
            f"📄 {F.sc('part')} · <code>{p+1}/{total_parts}</code>",
            F.DIV, "",
        ]

        base = p * MOVIES_PER_PART + 1
        for i, m in enumerate(chunk):
            n = base + i
            title = m.get("title") or "?"
            year_v = m.get("year") or ""
            rating = m.get("rating", 0)
            pop = m.get("popularity", 0)
            lang_c = (m.get("lang") or "").upper()

            name = f"{title} {year_v}" if year_v else title
            stars = f"⭐{rating}" if rating else ""
            pop_str = f"🎯{pop}" if pop else ""

            item_ctx = {
                "N": n,
                "NAME": name,
                "STARS": stars,
                "POP": pop_str,
                "LANG": lang_c,
            }
            lines.append(T.render_item(t, item_ctx))

        if p == total_parts - 1:
            lines.append(footer)

        kb = T.build_button_kb(await T.get_buttons())
        if p < total_parts - 1 and kb is None:
            kb = None

        try:
            await client.send_message(
                chat_id=chat_id,
                text="\n".join(lines)[:4000],
                reply_markup=kb,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
            await asyncio.sleep(0.4)
        except Exception as e:
            logger.debug(f"[MISS] part {p}: {e}")


# ── HISTORY ──
async def _show_history() -> Tuple[str, InlineKeyboardMarkup]:
    runs = await S.recent_scans(15)
    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"🧾 <b>{F.fb('MISSING HISTORY')}</b>",
        F.DIV, "",
    ]
    if not runs:
        lines.append(f"⚪ {F.sc('no scans yet')}")
    else:
        for r in runs:
            lines.append(
                f"• <b>{F.sc(str(r.get('label','?'))[:24])}</b> · "
                f"<code>{r.get('period','?')}</code>"
            )
            lines.append(
                f"   ✅ {FM.num(r.get('in_db',0))} · "
                f"❌ {FM.num(r.get('missing',0))} · "
                f"📥 {FM.num(r.get('fetched',0))}"
            )
            lines.append("")
    rows = [
        [InlineKeyboardButton(
            f"🗑️ {F.sc('clear history')}",
            callback_data=f"{PFX}:hist_clear",
        )],
        [
            InlineKeyboardButton(
                f"{F.EMO['refresh']} {F.sc('refresh')}",
                callback_data=f"{PFX}:history",
            ),
            InlineKeyboardButton(
                f"{F.EMO['back']} {F.sc('back')}",
                callback_data=f"{PFX}:home",
            ),
        ],
    ]
    return "\n".join(lines)[:4000], InlineKeyboardMarkup(rows)


# ── SETTINGS ──
async def _show_settings() -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await S.get_cfg()
    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"⚙️ <b>{F.fb('MISSING SETTINGS')}</b>",
        F.DIV, "",
        f"🎬 {F.sc('default industry')} · "
        f"<b>{cfg.get('default_industry','hollywood')}</b>",
        f"📊 {F.sc('results per part')} · "
        f"<b>{cfg.get('movies_per_part',25)}</b>",
        f"⭐ {F.sc('show rating')} · "
        f"{'🟢' if cfg.get('show_rating') else '🔴'}",
        f"🎯 {F.sc('show popularity')} · "
        f"{'🟢' if cfg.get('show_popularity') else '🔴'}",
        f"🌐 {F.sc('show lang code')} · "
        f"{'🟢' if cfg.get('show_lang_code') else '🔴'}",
        f"📋 {F.sc('copy friendly')} · "
        f"{'🟢' if cfg.get('copy_friendly') else '🔴'}",
        f"📅 {F.sc('include year')} · "
        f"{'🟢' if cfg.get('include_year') else '🔴'}",
    ]
    rows = [
        [InlineKeyboardButton(
            f"📝 {F.sc('edit template')}",
            callback_data=f"{PFX}:tpl_edit",
        )],
        [InlineKeyboardButton(
            f"🔘 {F.sc('edit buttons')}",
            callback_data=f"{PFX}:btn_edit",
        )],
        [
            InlineKeyboardButton(
                f"📊 {F.sc('set per part')}",
                callback_data=f"{PFX}:set_per_part",
            ),
        ],
        [
            InlineKeyboardButton(
                f"⭐ {F.sc('rating')} · {'🟢' if cfg.get('show_rating') else '🔴'}",
                callback_data=f"{PFX}:tog_rating",
            ),
            InlineKeyboardButton(
                f"🎯 {F.sc('pop')} · {'🟢' if cfg.get('show_popularity') else '🔴'}",
                callback_data=f"{PFX}:tog_pop",
            ),
        ],
        [
            InlineKeyboardButton(
                f"🌐 {F.sc('lang')} · {'🟢' if cfg.get('show_lang_code') else '🔴'}",
                callback_data=f"{PFX}:tog_lang",
            ),
            InlineKeyboardButton(
                f"📋 {F.sc('copy')} · {'🟢' if cfg.get('copy_friendly') else '🔴'}",
                callback_data=f"{PFX}:tog_copy",
            ),
        ],
        [InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data=f"{PFX}:home",
        )],
    ]
    return "\n".join(lines), InlineKeyboardMarkup(rows)


# ── CALLBACK ROUTER ──
@Client.on_callback_query(filters.regex(rf"^{PFX}:"), group=-8400)
async def missing_router(client: Client, q: CallbackQuery):
    if not q.from_user or not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)

    parts = str(q.data).split(":")
    action = parts[1] if len(parts) > 1 else ""

    try:
        if action == "close":
            try: await q.message.delete()
            except Exception: pass
            return await q.answer("Closed")

        if action == "home":
            text, kb = await _build_main()
            await _safe_edit(q, text, kb)
            return await q.answer()

        if action == "type":
            kind = parts[2]
            text, kb = await _show_industries(kind)
            await _safe_edit(q, text, kb)
            return await q.answer()

        if action == "ind":
            kind = parts[2]; code = parts[3]
            label, _ = SC.INDUSTRY_MAP.get(code, ("?", "en"))
            _ss_new(q.from_user.id, kind=kind, code=code, label=label)
            text, kb = await _show_year_prompt(kind, code, label)
            await _safe_edit(q, text, kb)
            return await q.answer()

        if action == "mo":
            kind = parts[2]; code = parts[3]
            year = int(parts[4]); month = int(parts[5])
            label, _ = SC.INDUSTRY_MAP.get(code, ("?", "en"))
            text, kb = await _show_weeks(kind, code, label, year, month)
            await _safe_edit(q, text, kb)
            return await q.answer()

        if action == "wk":
            kind = parts[2]; code = parts[3]
            year = int(parts[4]); month = int(parts[5])
            wk = int(parts[6])
            label, _ = SC.INDUSTRY_MAP.get(code, ("?", "en"))
            await _run_scan(client, q, kind, code, label, year, month, wk)
            return

        if action == "history":
            text, kb = await _show_history()
            await _safe_edit(q, text, kb)
            return await q.answer()

        if action == "hist_clear":
            n = await S.clear_history()
            await q.answer(f"🗑️ Cleared {n}")
            text, kb = await _show_history()
            await _safe_edit(q, text, kb)
            return

        if action == "settings":
            text, kb = await _show_settings()
            await _safe_edit(q, text, kb)
            return await q.answer()

        if action == "tog_rating":
            cfg = await S.get_cfg()
            await S.save_cfg(show_rating=not cfg.get("show_rating", True))
            await q.answer("Toggled")
            text, kb = await _show_settings()
            await _safe_edit(q, text, kb)
            return

        if action == "tog_pop":
            cfg = await S.get_cfg()
            await S.save_cfg(show_popularity=not cfg.get("show_popularity", True))
            await q.answer("Toggled")
            text, kb = await _show_settings()
            await _safe_edit(q, text, kb)
            return

        if action == "tog_lang":
            cfg = await S.get_cfg()
            await S.save_cfg(show_lang_code=not cfg.get("show_lang_code", True))
            await q.answer("Toggled")
            text, kb = await _show_settings()
            await _safe_edit(q, text, kb)
            return

        if action == "tog_copy":
            cfg = await S.get_cfg()
            await S.save_cfg(copy_friendly=not cfg.get("copy_friendly", True))
            await q.answer("Toggled")
            text, kb = await _show_settings()
            await _safe_edit(q, text, kb)
            return

        if action == "tpl_edit":
            _ss_new(q.from_user.id, step="tpl_edit")
            text = "\n".join([
                f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                f"📝 <b>{F.fb('EDIT TEMPLATE')}</b>",
                F.DIV, "",
                f"📌 {F.sc('choose what to edit')}",
            ])
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    f"📋 {F.sc('header')}",
                    callback_data=f"{PFX}:tpl_header",
                )],
                [InlineKeyboardButton(
                    f"🔤 {F.sc('item line')}",
                    callback_data=f"{PFX}:tpl_item",
                )],
                [InlineKeyboardButton(
                    f"📄 {F.sc('footer')}",
                    callback_data=f"{PFX}:tpl_footer",
                )],
                [InlineKeyboardButton(
                    f"♻️ {F.sc('reset all')}",
                    callback_data=f"{PFX}:tpl_reset",
                )],
                [InlineKeyboardButton(
                    f"{F.EMO['back']} {F.sc('back')}",
                    callback_data=f"{PFX}:settings",
                )],
            ])
            await _safe_edit(q, text, kb)
            return await q.answer()

        if action in ("tpl_header", "tpl_item", "tpl_footer"):
            _ss_new(q.from_user.id, step=action)
            field = action.split("_")[1]
            text = "\n".join([
                f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                f"📝 <b>{F.fb(f'EDIT {field.upper()}')}</b>",
                F.DIV, "",
                f"📌 {F.sc('send the new template as text')}",
                "",
                f"📌 {F.sc('placeholders')}:",
                f"<code>{{TYPE}} {{PERIOD}} {{INDUSTRY}}</code>",
                f"<code>{{FETCHED}} {{IN_DB}} {{MISSING}} {{TIME}}</code>",
                f"📌 {F.sc('item only')}: "
                f"<code>{{N}} {{NAME}} {{STARS}} {{POP}} {{LANG}}</code>",
            ])
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"{F.EMO['cross']} {F.sc('cancel')}",
                    callback_data=f"{PFX}:settings",
                ),
            ]])
            await _safe_edit(q, text, kb)
            return await q.answer()

        if action == "tpl_reset":
            await T.set_template("template", T.TEMPLATES["default"])
            await q.answer("♻️ Reset")
            text, kb = await _show_settings()
            await _safe_edit(q, text, kb)
            return

        if action == "btn_edit":
            btns = await T.get_buttons()
            lines = [
                f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                f"🔘 <b>{F.fb('BUTTONS')}</b>",
                F.DIV, "",
                f"📊 <b>{len(btns)}</b> buttons",
                "",
            ]
            for i, b in enumerate(btns, 1):
                lines.append(
                    f"<b>{i:02d}.</b> {F.sc(str(b.get('name','?'))[:30])}"
                )
                lines.append(f"   <code>{str(b.get('url','?'))[:50]}</code>")

            rows = []
            for i, b in enumerate(btns[:8], 1):
                rows.append([InlineKeyboardButton(
                    f"🗑️ {i}. {str(b.get('name','?'))[:25]}",
                    callback_data=f"{PFX}:btn_rm:{i-1}",
                )])
            rows.append([InlineKeyboardButton(
                f"➕ {F.sc('add button')}",
                callback_data=f"{PFX}:btn_add",
            )])
            if btns:
                rows.append([InlineKeyboardButton(
                    f"🗑️ {F.sc('clear all')}",
                    callback_data=f"{PFX}:btn_clear",
                )])
            rows.append([InlineKeyboardButton(
                f"{F.EMO['back']} {F.sc('back')}",
                callback_data=f"{PFX}:settings",
            )])
            await _safe_edit(q, "\n".join(lines)[:4000],
                           InlineKeyboardMarkup(rows))
            return await q.answer()

        if action == "btn_add":
            _ss_new(q.from_user.id, step="btn_add")
            text = "\n".join([
                f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                f"➕ <b>{F.fb('ADD BUTTON')}</b>",
                F.DIV, "",
                f"📌 {F.sc('send')} <code>Name | URL</code>",
            ])
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"{F.EMO['cross']} {F.sc('cancel')}",
                    callback_data=f"{PFX}:settings",
                ),
            ]])
            await _safe_edit(q, text, kb)
            return await q.answer()

        if action == "btn_rm":
            idx = int(parts[2])
            btns = await T.get_buttons()
            if 0 <= idx < len(btns):
                btns.pop(idx)
                await T.set_buttons(btns)
            await q.answer("🗑️")
            # refresh
            q2 = q
            return await missing_router(client, q2) if False else await q.answer()

        if action == "btn_clear":
            await T.set_buttons([])
            await q.answer("🗑️ Cleared")
            text, kb = await _show_settings()
            await _safe_edit(q, text, kb)
            return

        return await q.answer("❓")

    except Exception as e:
        logger.exception(f"[MISS] router: {e}")
        try: await q.answer(f"❌ {type(e).__name__}", show_alert=True)
        except Exception: pass


# ── TEXT INPUT ──
@Client.on_message(
    filters.private & filters.text & ~filters.regex(r"^/"),
    group=-8395,
)
async def missing_text_input(client: Client, message: Message):
    if not message.from_user or not _is_admin(message.from_user.id):
        return
    s = _ss_get(message.from_user.id)
    if not s: return

    step = s.get("step")
    text = (message.text or "").strip()
    if not text: return

    # Year input (after industry)
    if "kind" in s and "code" in s and "label" in s and not s.get("step"):
        try:
            year = int(text)
            if year < 1950 or year > 2030:
                raise ValueError
        except ValueError:
            return await message.reply_text(
                f"{F.EMO['cross']} {F.sc('invalid year')}",
                parse_mode=ParseMode.HTML,
            )
        text_out, kb = await _show_months(
            s["kind"], s["code"], s["label"], year,
        )
        _ss_set(message.from_user.id, year=year)
        await message.reply_text(
            text_out, reply_markup=kb,
            parse_mode=ParseMode.HTML,
        )
        try: message.stop_propagation()
        except Exception: pass
        return

    # Template edits
    if step == "tpl_header":
        t = await T.get_template("template") or dict(T.TEMPLATES["default"])
        t["header"] = text
        await T.set_template("template", t)
        _ss_drop(message.from_user.id)
        await message.reply_text(
            f"{F.EMO['check']} <b>Header updated</b>",
            parse_mode=ParseMode.HTML,
        )
        try: message.stop_propagation()
        except Exception: pass
        return

    if step == "tpl_item":
        t = await T.get_template("template") or dict(T.TEMPLATES["default"])
        t["item_line"] = text
        await T.set_template("template", t)
        _ss_drop(message.from_user.id)
        await message.reply_text(
            f"{F.EMO['check']} <b>Item line updated</b>",
            parse_mode=ParseMode.HTML,
        )
        try: message.stop_propagation()
        except Exception: pass
        return

    if step == "tpl_footer":
        t = await T.get_template("template") or dict(T.TEMPLATES["default"])
        t["footer"] = text
        await T.set_template("template", t)
        _ss_drop(message.from_user.id)
        await message.reply_text(
            f"{F.EMO['check']} <b>Footer updated</b>",
            parse_mode=ParseMode.HTML,
        )
        try: message.stop_propagation()
        except Exception: pass
        return

    if step == "btn_add":
        if "|" not in text:
            return await message.reply_text(
                f"{F.EMO['cross']} <code>Name | URL</code>",
                parse_mode=ParseMode.HTML,
            )
        name, url = [p.strip() for p in text.split("|", 1)]
        btns = await T.get_buttons()
        if len(btns) >= 8:
            _ss_drop(message.from_user.id)
            return await message.reply_text("⚠️ Max 8 buttons")
        btns.append({"name": name[:60], "url": url})
        await T.set_buttons(btns)
        _ss_drop(message.from_user.id)
        await message.reply_text(
            f"{F.EMO['check']} <b>Added</b>",
            parse_mode=ParseMode.HTML,
        )
        try: message.stop_propagation()
        except Exception: pass
        return


# ── HELPERS ──
async def _safe_edit(q, text, kb):
    try:
        await q.message.edit_text(
            text, reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        if "not modified" not in str(e).lower():
            logger.debug(f"[MISS] edit: {e}")


def snapshot() -> Dict[str, Any]:
    return {"module": "missing"}


__all__ = ["cmd_missing", "snapshot"]
