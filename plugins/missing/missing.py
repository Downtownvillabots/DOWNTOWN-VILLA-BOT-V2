# ============================================================
# 🏨 DOWNTOWN VILLA — MISSING FILES FINDER (V1 + V2 MERGED)
# ============================================================
from __future__ import annotations
import asyncio, logging, os, re, secrets, time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.errors import MessageNotModified, FloodWait
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

try:
    from core.config import ADMINS as _ADMINS
    ADMINS = list(_ADMINS or [])
except Exception:
    ADMINS = []

from plugins.missing import fonts as F
from plugins.missing import scan as SC
from plugins.missing import state as S
from plugins.missing import templates as T

logger = logging.getLogger(__name__)

# ── CONFIG ──
PFX = "miss"
SESSION_TTL = 900
IST = timezone(timedelta(hours=5, minutes=30))
MOVIES_PER_PART = 25


# ── HELPERS ──
def _is_admin(uid) -> bool:
    try:
        return int(uid) in [int(a) for a in ADMINS if str(a).lstrip("-").isdigit()]
    except Exception:
        return False


def _esc(t) -> str:
    if t is None: return ""
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _fmt_int(n) -> str:
    try: return f"{int(n):,}"
    except (TypeError, ValueError): return "0"


# ── SESSIONS ──
_SESSIONS: Dict[int, Dict[str, Any]] = {}


def _new_session(uid: int, action: str, **data) -> str:
    tok = secrets.token_urlsafe(8)[:10]
    _SESSIONS[int(uid)] = {"token": tok, "action": action, "data": data,
                           "expires": time.time() + SESSION_TTL}
    return tok


def _get_session(uid: int) -> Optional[Dict[str, Any]]:
    s = _SESSIONS.get(int(uid))
    if not s: return None
    if time.time() > s["expires"]:
        _SESSIONS.pop(int(uid), None)
        return None
    return s


def _clear_session(uid: int) -> None:
    _SESSIONS.pop(int(uid), None)


def _cleanup_sessions() -> None:
    now = time.time()
    for uid in list(_SESSIONS.keys()):
        if _SESSIONS[uid]["expires"] < now:
            _SESSIONS.pop(uid, None)


# ── SAFE EDIT ──
async def _safe_edit(target, text: str, kb=None) -> bool:
    try:
        msg = getattr(target, "message", target)
        await msg.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                            disable_web_page_preview=True)
        return True
    except MessageNotModified:
        return True
    except Exception as e:
        logger.debug(f"[MISS] edit: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════════
# VIEW BUILDERS
# ═══════════════════════════════════════════════════════════════════════════
async def _view_start() -> str:
    cfg = await S.get_cfg()
    ind = cfg.get("default_industry", "hollywood")
    return "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"🔍 <b>{F.fb('MISSING FILES FINDER')}</b>",
        F.DIV, "",
        f"📌 {F.sc('compare tmdb with your local db')}",
        f"📌 {F.sc('find every missing title')}",
        f"📌 {F.sc('no filters · no cache')}",
        "",
        F.DIV_S, "",
        f"⚙️ {F.sc('default industry')} · <b>{F.sc(ind)}</b>",
        f"📊 {F.sc('per part')} · <b>{cfg.get('movies_per_part', 25)}</b>",
    ])


def _view_industry(kind: str) -> str:
    lbl = "MOVIES" if kind == "movie" else "SERIES"
    return "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"🔍 <b>{F.fb('MISSING ' + lbl)}</b>",
        F.DIV, "",
        f"🌍 {F.sc('pick an industry')}",
        f"📌 {F.sc('all = every language')}",
    ])


def _view_year_input(kind: str, ind_label: str) -> str:
    lbl = "MOVIES" if kind == "movie" else "SERIES"
    return "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"📅 <b>{F.fb('ENTER YEAR')}</b>",
        F.DIV, "",
        f"🎬 {F.sc('type')} · <code>{lbl}</code>",
        f"🌍 {F.sc('industry')} · <b>{_esc(ind_label)}</b>",
        "", F.DIV_S, "",
        f"📝 {F.sc('send the year as next message')}",
        f"📌 {F.sc('range')} · <code>1950 – 2027</code>",
    ])


def _view_months(kind: str, ind_label: str, year: int) -> str:
    return "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"📅 <b>{F.fb('YEAR')}</b> · <code>{year}</code>",
        F.DIV, "",
        f"🎬 {F.sc('type')} · <code>{kind.upper()}</code>",
        f"🌍 {F.sc('industry')} · <b>{_esc(ind_label)}</b>",
        "", F.DIV_S, "",
        f"📌 {F.sc('pick a month to scan')}",
    ])


def _view_weeks(kind: str, ind_label: str, year: int, month: int) -> str:
    return "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"📅 <b>{SC.MONTHS_FULL[month-1].upper()} {year}</b>",
        F.DIV, "",
        f"🎬 {F.sc('type')} · <code>{kind.upper()}</code>",
        f"🌍 {F.sc('industry')} · <b>{_esc(ind_label)}</b>",
        "", F.DIV_S, "",
        f"📌 {F.sc('pick a week or full month')}",
    ])


async def _view_history() -> str:
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
                f"• <b>{_esc(str(r.get('label','?'))[:24])}</b> · "
                f"<code>{_esc(str(r.get('period','?')))}</code>")
            lines.append(
                f"   ✅ {_fmt_int(r.get('in_db',0))} · "
                f"❌ {_fmt_int(r.get('missing',0))} · "
                f"📥 {_fmt_int(r.get('fetched',0))}")
            lines.append("")
    return "\n".join(lines)[:4000]


async def _view_settings() -> str:
    cfg = await S.get_cfg()
    def dot(v): return "🟢" if v else "🔴"
    return "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"⚙️ <b>{F.fb('MISSING SETTINGS')}</b>",
        F.DIV, "",
        f"🎬 {F.sc('default industry')} · "
        f"<b>{_esc(cfg.get('default_industry','hollywood'))}</b>",
        f"📊 {F.sc('results per part')} · "
        f"<b>{cfg.get('movies_per_part', 25)}</b>",
        f"⭐ {F.sc('show rating')} · {dot(cfg.get('show_rating'))}",
        f"🎯 {F.sc('show popularity')} · {dot(cfg.get('show_popularity'))}",
        f"🌐 {F.sc('show lang code')} · {dot(cfg.get('show_lang_code'))}",
        f"📅 {F.sc('include year')} · {dot(cfg.get('include_year', True))}",
    ])


async def _view_buttons() -> str:
    btns = await S.get_buttons()
    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"🔘 <b>{F.fb('BUTTONS')}</b>",
        F.DIV, "",
        f"📊 <b>{len(btns)}</b> / 8",
        "",
    ]
    for i, b in enumerate(btns, 1):
        lines.append(f"<b>{i:02d}.</b> {_esc(str(b.get('name','?'))[:30])}")
        lines.append(f"   <code>{_esc(str(b.get('url','?'))[:50])}</code>")
    return "\n".join(lines)[:4000]


# ═══════════════════════════════════════════════════════════════════════════
# KEYBOARDS
# ═══════════════════════════════════════════════════════════════════════════
def kb_type():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🎬 MOVIES", callback_data=f"{PFX}:type:movie"),
         InlineKeyboardButton("📺 SERIES", callback_data=f"{PFX}:type:series")],
        [InlineKeyboardButton("🧾 HISTORY",  callback_data=f"{PFX}:history"),
         InlineKeyboardButton("⚙️ SETTINGS", callback_data=f"{PFX}:settings")],
        [InlineKeyboardButton("❌ CLOSE", callback_data=f"{PFX}:close")],
    ])


def kb_industry(kind: str):
    rows, row = [], []
    for code, label, _ in SC.INDUSTRIES:
        row.append(InlineKeyboardButton(
            label, callback_data=f"{PFX}:ind:{kind}:{code}"))
        if len(row) == 2:
            rows.append(row); row = []
    if row: rows.append(row)
    rows.append([
        InlineKeyboardButton("◀️ BACK",  callback_data=f"{PFX}:back_type"),
        InlineKeyboardButton("❌ CLOSE", callback_data=f"{PFX}:close"),
    ])
    return InlineKeyboardMarkup(rows)


def kb_months(kind: str, code: str, year: int):
    rows, row = [], []
    for i, m in enumerate(SC.MONTHS, 1):
        row.append(InlineKeyboardButton(
            f"📅 {m}", callback_data=f"{PFX}:mo:{kind}:{code}:{year}:{i}"))
        if len(row) == 3:
            rows.append(row); row = []
    if row: rows.append(row)
    rows.append([
        InlineKeyboardButton("◀️ BACK",
                             callback_data=f"{PFX}:back_ind:{kind}"),
        InlineKeyboardButton("❌ CLOSE", callback_data=f"{PFX}:close"),
    ])
    return InlineKeyboardMarkup(rows)


def kb_weeks(kind: str, code: str, year: int, month: int):
    weeks = SC.weeks_of_month(year, month)
    rows = []
    for wk, s, e in weeks:
        rows.append([InlineKeyboardButton(
            f"📆 W{wk} · {s:02d}-{e:02d} {SC.MONTHS[month-1]}",
            callback_data=f"{PFX}:wk:{kind}:{code}:{year}:{month}:{wk}")])
    rows.append([InlineKeyboardButton(
        f"📅 FULL MONTH ({SC.MONTHS_FULL[month-1]})",
        callback_data=f"{PFX}:wk:{kind}:{code}:{year}:{month}:0")])
    rows.append([
        InlineKeyboardButton("◀️ BACK",
                             callback_data=f"{PFX}:back_months:{kind}:{code}:{year}"),
        InlineKeyboardButton("❌ CLOSE", callback_data=f"{PFX}:close"),
    ])
    return InlineKeyboardMarkup(rows)


def kb_after_results(kind: str, code: str, year: int, month: int):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "🔄 RESCAN",
            callback_data=f"{PFX}:mo:{kind}:{code}:{year}:{month}")],
        [InlineKeyboardButton(
            "📅 NEW WEEK",
            callback_data=f"{PFX}:back_months:{kind}:{code}:{year}")],
        [InlineKeyboardButton("❌ CLOSE", callback_data=f"{PFX}:close")],
    ])


def kb_back(target: str = f"{PFX}:back_type"):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("◀️ BACK", callback_data=target)],
        [InlineKeyboardButton("❌ CLOSE", callback_data=f"{PFX}:close")],
    ])


async def _kb_settings():
    cfg = await S.get_cfg()
    def dot(v): return "🟢" if v else "🔴"
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("📝 EDIT TEMPLATE",
                              callback_data=f"{PFX}:tpl_edit")],
        [InlineKeyboardButton("🔘 EDIT BUTTONS",
                              callback_data=f"{PFX}:btn_edit")],
        [InlineKeyboardButton(
            f"⭐ RATING · {dot(cfg.get('show_rating'))}",
            callback_data=f"{PFX}:tog:rating"),
         InlineKeyboardButton(
            f"🎯 POP · {dot(cfg.get('show_popularity'))}",
            callback_data=f"{PFX}:tog:pop")],
        [InlineKeyboardButton(
            f"🌐 LANG · {dot(cfg.get('show_lang_code'))}",
            callback_data=f"{PFX}:tog:lang"),
         InlineKeyboardButton(
            f"📅 YEAR · {dot(cfg.get('include_year', True))}",
            callback_data=f"{PFX}:tog:year")],
        [InlineKeyboardButton("◀️ BACK", callback_data=f"{PFX}:home")],
    ])


def _kb_history():
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🗑️ CLEAR HISTORY",
                              callback_data=f"{PFX}:hist_clear")],
        [InlineKeyboardButton("🔄 REFRESH", callback_data=f"{PFX}:history"),
         InlineKeyboardButton("◀️ BACK",   callback_data=f"{PFX}:home")],
    ])


async def _kb_buttons():
    btns = await S.get_buttons()
    rows = []
    for i, b in enumerate(btns[:8], 1):
        rows.append([InlineKeyboardButton(
            f"🗑️ {i}. {str(b.get('name','?'))[:25]}",
            callback_data=f"{PFX}:btn_rm:{i-1}")])
    rows.append([InlineKeyboardButton("➕ ADD BUTTON",
                                      callback_data=f"{PFX}:btn_add")])
    if btns:
        rows.append([InlineKeyboardButton("🗑️ CLEAR ALL",
                                          callback_data=f"{PFX}:btn_clear")])
    rows.append([InlineKeyboardButton("◀️ BACK",
                                      callback_data=f"{PFX}:settings")])
    return InlineKeyboardMarkup(rows)


# ═══════════════════════════════════════════════════════════════════════════
# PUBLIC ENTRY (called from admin.py and from /missing)
# ═══════════════════════════════════════════════════════════════════════════
async def open_panel_for_admin(client: Client, message: Message) -> bool:
    """Called by admin.py when user taps 🔎 MISSING button."""
    try:
        if not message.from_user or not _is_admin(message.from_user.id):
            return False
        if not os.getenv("TMDB_API_KEY", "").strip():
            try:
                await message.reply_text(
                    "⚠️ <b>TMDB_API_KEY ɴᴏᴛ ꜱᴇᴛ</b>",
                    parse_mode=ParseMode.HTML)
            except Exception: pass
            return False
        _clear_session(message.from_user.id)
        await message.reply_text(
            await _view_start(), reply_markup=kb_type(),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True)
        return True
    except Exception as e:
        logger.exception(f"[MISS] admin open: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════════
# /missing COMMAND
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_message(
    filters.command(["missing", "gapscan", "lackfiles"]) & filters.private,
    group=-460,
)
async def cmd_missing(client: Client, message: Message):
    try:
        if not message.from_user or not _is_admin(message.from_user.id):
            return await message.reply_text("⛔ ᴀᴅᴍɪɴꜱ ᴏɴʟʏ.")
        if not os.getenv("TMDB_API_KEY", "").strip():
            return await message.reply_text(
                "⚠️ <b>TMDB_API_KEY ɴᴏᴛ ꜱᴇᴛ</b>",
                parse_mode=ParseMode.HTML)
        _clear_session(message.from_user.id)
        await message.reply_text(
            await _view_start(), reply_markup=kb_type(),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True)
    except Exception as e:
        logger.exception(f"[MISS] cmd: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# CALLBACKS
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(rf"^{PFX}:close$"), group=-460)
async def cb_close(client, q):
    try:
        _clear_session(q.from_user.id)
        try: await q.message.delete()
        except Exception: pass
        await q.answer("ᴄʟᴏꜱᴇᴅ")
    except Exception:
        try: await q.answer("ᴄʟᴏꜱᴇᴅ")
        except Exception: pass


@Client.on_callback_query(filters.regex(rf"^{PFX}:home$"), group=-460)
async def cb_home(client, q):
    try:
        _clear_session(q.from_user.id)
        await _safe_edit(q, await _view_start(), kb_type())
        await q.answer()
    except Exception as e:
        logger.exception(f"[MISS] home: {e}")


@Client.on_callback_query(filters.regex(rf"^{PFX}:back_type$"), group=-460)
async def cb_back_type(client, q):
    try:
        _clear_session(q.from_user.id)
        await _safe_edit(q, await _view_start(), kb_type())
        await q.answer()
    except Exception as e:
        logger.exception(f"[MISS] back_type: {e}")


@Client.on_callback_query(
    filters.regex(rf"^{PFX}:type:(movie|series)$"), group=-460)
async def cb_type(client, q):
    try:
        kind = q.matches[0].group(1)
        _new_session(q.from_user.id, "kind", kind=kind)
        await _safe_edit(q, _view_industry(kind), kb_industry(kind))
        await q.answer()
    except Exception as e:
        logger.exception(f"[MISS] type: {e}")


@Client.on_callback_query(
    filters.regex(rf"^{PFX}:back_ind:(movie|series)$"), group=-460)
async def cb_back_ind(client, q):
    try:
        kind = q.matches[0].group(1)
        _new_session(q.from_user.id, "kind", kind=kind)
        await _safe_edit(q, _view_industry(kind), kb_industry(kind))
        await q.answer()
    except Exception as e:
        logger.exception(f"[MISS] back_ind: {e}")


@Client.on_callback_query(
    filters.regex(rf"^{PFX}:ind:(movie|series):(\w+)$"), group=-460)
async def cb_industry(client, q):
    try:
        kind = q.matches[0].group(1)
        code = q.matches[0].group(2)
        if code not in SC.INDUSTRY_MAP:
            return await q.answer("⚠️ ᴜɴᴋɴᴏᴡɴ ɪɴᴅᴜꜱᴛʀʏ", show_alert=True)
        label, lang = SC.INDUSTRY_MAP[code]
        _new_session(q.from_user.id, "year_input",
                     kind=kind, ind=code, ind_label=label, ind_lang=lang)
        await _safe_edit(q, _view_year_input(kind, label),
                         kb_back(f"{PFX}:back_ind:{kind}"))
        await q.answer()
    except Exception as e:
        logger.exception(f"[MISS] industry: {e}")


@Client.on_callback_query(
    filters.regex(rf"^{PFX}:back_months:(movie|series):(\w+):(\d{{4}})$"),
    group=-460)
async def cb_back_months(client, q):
    try:
        kind = q.matches[0].group(1)
        code = q.matches[0].group(2)
        year = int(q.matches[0].group(3))
        label, _ = SC.INDUSTRY_MAP.get(code, ("?", "en"))
        _new_session(q.from_user.id, "month_pick",
                     kind=kind, ind=code, ind_label=label, year=year)
        await _safe_edit(q, _view_months(kind, label, year),
                         kb_months(kind, code, year))
        await q.answer()
    except Exception as e:
        logger.exception(f"[MISS] back_months: {e}")


@Client.on_callback_query(
    filters.regex(rf"^{PFX}:mo:(movie|series):(\w+):(\d{{4}}):(\d{{1,2}})$"),
    group=-460)
async def cb_month(client, q):
    try:
        kind = q.matches[0].group(1)
        code = q.matches[0].group(2)
        year = int(q.matches[0].group(3))
        month = int(q.matches[0].group(4))
        if not (1 <= month <= 12):
            return await q.answer("⚠️ ɪɴᴠᴀʟɪᴅ ᴍᴏɴᴛʜ", show_alert=True)
        label, _ = SC.INDUSTRY_MAP.get(code, ("?", "en"))
        _new_session(q.from_user.id, "week_pick",
                     kind=kind, ind=code, ind_label=label,
                     year=year, month=month)
        await _safe_edit(q, _view_weeks(kind, label, year, month),
                         kb_weeks(kind, code, year, month))
        await q.answer()
    except Exception as e:
        logger.exception(f"[MISS] month: {e}")


@Client.on_callback_query(
    filters.regex(rf"^{PFX}:wk:(movie|series):(\w+):(\d{{4}}):(\d{{1,2}}):(\d{{1,2}})$"),
    group=-460)
async def cb_week(client, q):
    try:
        kind = q.matches[0].group(1)
        code = q.matches[0].group(2)
        year = int(q.matches[0].group(3))
        month = int(q.matches[0].group(4))
        wk = int(q.matches[0].group(5))
        label, lang = SC.INDUSTRY_MAP.get(code, ("?", "en"))
        week_tuple = None
        if wk > 0:
            for w in SC.weeks_of_month(year, month):
                if w[0] == wk:
                    week_tuple = w; break
            if week_tuple is None:
                return await q.answer("⚠️ ɪɴᴠᴀʟɪᴅ ᴡᴇᴇᴋ", show_alert=True)
        _clear_session(q.from_user.id)
        await q.answer("🔍 ꜱᴄᴀɴɴɪɴɢ...")
        await _run_scan(client, q, kind, code, label, lang,
                        year, month, week_tuple)
    except Exception as e:
        logger.exception(f"[MISS] week: {e}")
        try: await q.answer("⚠️ ᴇʀʀᴏʀ", show_alert=True)
        except Exception: pass


# ── HISTORY ──
@Client.on_callback_query(filters.regex(rf"^{PFX}:history$"), group=-460)
async def cb_history(client, q):
    try:
        await _safe_edit(q, await _view_history(), _kb_history())
        await q.answer()
    except Exception as e:
        logger.exception(f"[MISS] history: {e}")


@Client.on_callback_query(filters.regex(rf"^{PFX}:hist_clear$"), group=-460)
async def cb_hist_clear(client, q):
    try:
        n = await S.clear_history()
        await q.answer(f"🗑️ Cleared {n}")
        await _safe_edit(q, await _view_history(), _kb_history())
    except Exception as e:
        logger.exception(f"[MISS] hist_clear: {e}")


# ── SETTINGS ──
@Client.on_callback_query(filters.regex(rf"^{PFX}:settings$"), group=-460)
async def cb_settings(client, q):
    try:
        await _safe_edit(q, await _view_settings(), await _kb_settings())
        await q.answer()
    except Exception as e:
        logger.exception(f"[MISS] settings: {e}")


@Client.on_callback_query(filters.regex(rf"^{PFX}:tog:(\w+)$"), group=-460)
async def cb_toggle(client, q):
    try:
        key = q.matches[0].group(1)
        m = {"rating": "show_rating", "pop": "show_popularity",
             "lang": "show_lang_code", "year": "include_year"}
        if key not in m:
            return await q.answer("❓")
        cfg = await S.get_cfg()
        field = m[key]
        await S.save_cfg(**{field: not cfg.get(field, True)})
        await q.answer("✓")
        await _safe_edit(q, await _view_settings(), await _kb_settings())
    except Exception as e:
        logger.exception(f"[MISS] toggle: {e}")


# ── TEMPLATE EDITOR ──
@Client.on_callback_query(filters.regex(rf"^{PFX}:tpl_edit$"), group=-460)
async def cb_tpl_edit(client, q):
    try:
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📋 HEADER",
                                  callback_data=f"{PFX}:tpl:header")],
            [InlineKeyboardButton("🔤 ITEM LINE",
                                  callback_data=f"{PFX}:tpl:item")],
            [InlineKeyboardButton("📄 FOOTER",
                                  callback_data=f"{PFX}:tpl:footer")],
            [InlineKeyboardButton("♻️ RESET ALL",
                                  callback_data=f"{PFX}:tpl_reset")],
            [InlineKeyboardButton("◀️ BACK",
                                  callback_data=f"{PFX}:settings")],
        ])
        txt = "\n".join([
            f"{F.EMO['brand']} <b>{F.fb('EDIT TEMPLATE')}</b>",
            F.DIV, "",
            f"📌 {F.sc('choose what to edit')}",
        ])
        await _safe_edit(q, txt, kb)
        await q.answer()
    except Exception as e:
        logger.exception(f"[MISS] tpl_edit: {e}")


@Client.on_callback_query(
    filters.regex(rf"^{PFX}:tpl:(header|item|footer)$"), group=-460)
async def cb_tpl_field(client, q):
    try:
        field = q.matches[0].group(1)
        _new_session(q.from_user.id, f"tpl_{field}", field=field)
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ CANCEL",
                                 callback_data=f"{PFX}:settings")]])
        txt = "\n".join([
            f"{F.EMO['brand']} <b>{F.fb(f'EDIT {field.upper()}')}</b>",
            F.DIV, "",
            f"📌 {F.sc('send the new template as text')}",
            "",
            f"<b>{F.sc('placeholders')}:</b>",
            f"<code>{{TYPE}} {{PERIOD}} {{INDUSTRY}}</code>",
            f"<code>{{FETCHED}} {{IN_DB}} {{MISSING}} {{TIME}}</code>",
            f"<b>{F.sc('item only')}:</b>",
            f"<code>{{N}} {{NAME}} {{STARS}} {{POP}} {{LANG}}</code>",
        ])
        await _safe_edit(q, txt, kb)
        await q.answer()
    except Exception as e:
        logger.exception(f"[MISS] tpl_field: {e}")


@Client.on_callback_query(filters.regex(rf"^{PFX}:tpl_reset$"), group=-460)
async def cb_tpl_reset(client, q):
    try:
        await T.set_template("template", T.TEMPLATES["default"])
        await q.answer("♻️ Reset")
        await _safe_edit(q, await _view_settings(), await _kb_settings())
    except Exception as e:
        logger.exception(f"[MISS] tpl_reset: {e}")


# ── BUTTON EDITOR ──
@Client.on_callback_query(filters.regex(rf"^{PFX}:btn_edit$"), group=-460)
async def cb_btn_edit(client, q):
    try:
        await _safe_edit(q, await _view_buttons(), await _kb_buttons())
        await q.answer()
    except Exception as e:
        logger.exception(f"[MISS] btn_edit: {e}")


@Client.on_callback_query(filters.regex(rf"^{PFX}:btn_rm:(\d+)$"), group=-460)
async def cb_btn_rm(client, q):
    try:
        idx = int(q.matches[0].group(1))
        btns = await S.get_buttons()
        if 0 <= idx < len(btns):
            btns.pop(idx)
            await S.set_buttons(btns)
        await q.answer("🗑️")
        await _safe_edit(q, await _view_buttons(), await _kb_buttons())
    except Exception as e:
        logger.exception(f"[MISS] btn_rm: {e}")


@Client.on_callback_query(filters.regex(rf"^{PFX}:btn_clear$"), group=-460)
async def cb_btn_clear(client, q):
    try:
        await S.set_buttons([])
        await q.answer("🗑️ Cleared")
        await _safe_edit(q, await _view_buttons(), await _kb_buttons())
    except Exception as e:
        logger.exception(f"[MISS] btn_clear: {e}")


@Client.on_callback_query(filters.regex(rf"^{PFX}:btn_add$"), group=-460)
async def cb_btn_add(client, q):
    try:
        _new_session(q.from_user.id, "btn_add")
        txt = "\n".join([
            f"{F.EMO['brand']} <b>{F.fb('ADD BUTTON')}</b>",
            F.DIV, "",
            f"📌 {F.sc('send')} <code>Name | URL</code>",
        ])
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("❌ CANCEL",
                                 callback_data=f"{PFX}:settings")]])
        await _safe_edit(q, txt, kb)
        await q.answer()
    except Exception as e:
        logger.exception(f"[MISS] btn_add: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# TEXT INPUT
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_message(
    filters.private & filters.text & ~filters.regex(r"^/"),
    group=-459,
)
async def missing_text_input(client, message: Message):
    if not message.from_user: return
    s = _get_session(message.from_user.id)
    if not s or not _is_admin(message.from_user.id): return

    try: message.stop_propagation()
    except Exception: pass

    action = s.get("action")
    data = s.get("data") or {}
    text = (message.text or "").strip()
    if not text: return

    # ── Year ──
    if action == "year_input":
        try:
            year = int(text)
            if year < 1950 or year > 2027: raise ValueError
        except (TypeError, ValueError):
            return await message.reply_text(
                "❌ ɪɴᴠᴀʟɪᴅ ʏᴇᴀʀ.\n\n"
                "📌 ꜱᴇɴᴅ ᴀ ɴᴜᴍʙᴇʀ ʙᴇᴛᴡᴇᴇɴ "
                "<code>1950</code> ᴀɴᴅ <code>2027</code>.",
                parse_mode=ParseMode.HTML)
        kind = data.get("kind", "movie")
        code = data.get("ind", "hollywood")
        label = data.get("ind_label", "Hollywood")
        _new_session(message.from_user.id, "month_pick",
                     kind=kind, ind=code, ind_label=label, year=year)
        await message.reply_text(
            _view_months(kind, label, year),
            reply_markup=kb_months(kind, code, year),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True)
        return

    # ── Template edits ──
    if action in ("tpl_header", "tpl_item", "tpl_footer"):
        field = data.get("field") or action.split("_")[1]
        t = await T.get_template("template") or dict(T.TEMPLATES["default"])
        key = {"header": "header", "item": "item_line", "footer": "footer"}[field]
        t[key] = text
        await T.set_template("template", t)
        _clear_session(message.from_user.id)
        await message.reply_text(
            f"✅ <b>{field.upper()} updated</b>",
            parse_mode=ParseMode.HTML)
        return

    # ── Button add ──
    if action == "btn_add":
        if "|" not in text:
            return await message.reply_text(
                "❌ <code>Name | URL</code>",
                parse_mode=ParseMode.HTML)
        name, url = [p.strip() for p in text.split("|", 1)]
        btns = await S.get_buttons()
        if len(btns) >= 8:
            _clear_session(message.from_user.id)
            return await message.reply_text("⚠️ Max 8 buttons")
        btns.append({"name": name[:60], "url": url})
        await S.set_buttons(btns)
        _clear_session(message.from_user.id)
        await message.reply_text(
            "✅ <b>Added</b>",
            parse_mode=ParseMode.HTML)
        return


# ═══════════════════════════════════════════════════════════════════════════
# SCANNER
# ═══════════════════════════════════════════════════════════════════════════
async def _run_scan(client, q, kind, code, label, lang,
                    year, month, week):
    gte, lte = SC.date_range(year, month, week)
    if week is None:
        period = f"FULL {SC.MONTHS_FULL[month-1].upper()} {year}"
        period_short = f"{SC.MONTHS[month-1]} {year}"
    else:
        wk, s, e = week
        period = f"W{wk} · {s:02d}-{e:02d} {SC.MONTHS_FULL[month-1]} {year}"
        period_short = f"{SC.MONTHS[month-1]} {year} · W{wk}"

    # Progress
    try:
        progress = await q.message.edit_text(
            "\n".join([
                f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                f"🔍 <b>{F.fb('SCANNING')}</b>",
                F.DIV, "",
                f"📅 <code>{_esc(period_short)}</code>",
                f"🎬 <code>{kind.upper()}</code> · 🌍 <b>{_esc(label)}</b>",
                "", F.DIV_S, "",
                f"⏳ {F.sc('fetching from tmdb')}...",
            ]),
            parse_mode=ParseMode.HTML)
    except MessageNotModified:
        progress = q.message
    except Exception:
        progress = q.message

    chat_id = q.message.chat.id
    progress_id = progress.id

    # Fetch
    try:
        if kind == "movie":
            items, raw = await SC.fetch_movies_range(gte, lte, lang)
        else:
            items, raw = await SC.fetch_series_range(gte, lte, lang)
    except Exception as e:
        logger.exception(f"[MISS] fetch: {e}")
        items, raw = [], 0

    items = SC.dedupe_by_tmdb(items)
    fetched = len(items)

    # Empty
    if not items:
        try:
            await client.edit_message_text(
                chat_id=chat_id, message_id=progress_id,
                text="\n".join([
                    f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                    f"❌ <b>{F.fb('NO RESULTS')}</b>",
                    F.DIV, "",
                    f"📅 <code>{_esc(period_short)}</code>",
                    f"🎬 <code>{kind.upper()}</code> · 🌍 <b>{_esc(label)}</b>",
                    "",
                    f"📥 {F.sc('tmdb raw')} · <code>{_fmt_int(raw)}</code>",
                    "", F.DIV_S, "",
                    f"📌 {F.sc('nothing found on tmdb for this range')}",
                    "", f"💡 <b>{F.sc('try')}</b>:",
                    f"• ᴜꜱᴇ <b>FULL MONTH</b> ɪɴꜱᴛᴇᴀᴅ ᴏꜰ ᴀ ᴡᴇᴇᴋ",
                    f"• ᴛʀʏ ᴀ <b>ᴘᴀꜱᴛ ʏᴇᴀʀ</b>",
                    f"• ᴛʀʏ <b>🌍 ALL</b> ɪɴᴅᴜꜱᴛʀʏ",
                ]),
                reply_markup=kb_after_results(kind, code, year, month),
                parse_mode=ParseMode.HTML)
        except Exception: pass
        return

    missing, present = await SC.find_missing(items)
    in_db = len(present)
    missing_count = len(missing)
    missing.sort(key=lambda x: x.get("popularity", 0), reverse=True)

    # Log
    try:
        await S.log_scan({
            "kind": kind, "industry": code, "label": label,
            "year": year, "month": month,
            "week": week[0] if week else 0,
            "period": period_short,
            "fetched": fetched, "in_db": in_db, "missing": missing_count,
            "owner": q.from_user.id,
        })
    except Exception: pass

    # Delete progress
    try:
        await client.delete_messages(chat_id, progress_id)
    except Exception: pass

    # Send results
    await _send_results(
        client, chat_id, kind, label, period_short,
        fetched, in_db, missing_count, missing,
        kind_code=code, year=year, month=month)


# ═══════════════════════════════════════════════════════════════════════════
# SEND RESULTS
# ═══════════════════════════════════════════════════════════════════════════
async def _send_results(client, chat_id, kind, label, period,
                        fetched, in_db, missing_count, missing,
                        kind_code="hollywood", year=2000, month=1):
    cfg = await S.get_cfg()
    per_part = int(cfg.get("movies_per_part", MOVIES_PER_PART))
    show_rating = cfg.get("show_rating", True)
    show_pop   = cfg.get("show_popularity", True)
    show_lang  = cfg.get("show_lang_code", True)
    show_year  = cfg.get("include_year", True)

    type_label = "MOVIES" if kind == "movie" else "SERIES"

    tpl = await T.get_template("template") or dict(T.TEMPLATES["default"])
    ctx = {
        "TYPE": type_label,
        "PERIOD": period,
        "INDUSTRY": label,
        "FETCHED": _fmt_int(fetched),
        "IN_DB": _fmt_int(in_db),
        "MISSING": _fmt_int(missing_count),
        "TIME": datetime.now(IST).strftime("%Y-%m-%d %H:%M IST"),
    }

    header = T.render_header(tpl, ctx)
    footer = T.render_footer(tpl, ctx)

    # No missing
    if missing_count == 0:
        try:
            await client.send_message(
                chat_id=chat_id,
                text=header + f"\n🎉 <b>{F.sc('your db is complete!')}</b>",
                reply_markup=kb_after_results(kind, kind_code, year, month),
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True)
        except Exception as e:
            logger.debug(f"[MISS] header: {e}")
        return

    # Header
    try:
        await client.send_message(
            chat_id=chat_id, text=header,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True)
    except Exception as e:
        logger.debug(f"[MISS] header send: {e}")

    # Chunks
    total_parts = (len(missing) + per_part - 1) // per_part
    custom_kb = T.build_button_kb(await S.get_buttons())

    for p in range(total_parts):
        chunk = missing[p * per_part:(p + 1) * per_part]
        lines = [
            f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
            f"🔍 <b>{F.fb('MISSING ' + type_label)}</b>",
            f"📅 <code>{_esc(period)}</code> · 🌍 <b>{_esc(label)}</b>",
            f"📄 {F.sc('part')} · <code>{p+1}/{total_parts}</code>",
            F.DIV, "",
        ]
        base = p * per_part + 1
        for i, m in enumerate(chunk):
            n = base + i
            title = m.get("title") or "?"
            yr = m.get("year") or ""
            name = f"{title} {yr}".strip() if show_year else title

            item_ctx = {
                "N": n,
                "NAME": _esc(name),
                "STARS": f"⭐{m.get('rating')}" if (show_rating and m.get("rating")) else "",
                "POP": f"🎯{m.get('popularity')}" if (show_pop and m.get("popularity")) else "",
                "LANG": (m.get("lang") or "").upper() if show_lang else "",
            }
            lines.append(T.render_item(tpl, item_ctx).rstrip())

        if p == total_parts - 1:
            lines.append(footer)

        kb = custom_kb if p == total_parts - 1 else None
        if kb is None and p == total_parts - 1:
            kb = kb_after_results(kind, kind_code, year, month)

        body = "\n".join(lines)[:4000]

        try:
            await client.send_message(
                chat_id=chat_id, text=body, reply_markup=kb,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True)
            await asyncio.sleep(0.4)
        except FloodWait as e:
            await asyncio.sleep(e.value + 2)
            try:
                await client.send_message(
                    chat_id=chat_id, text=body, reply_markup=kb,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True)
            except Exception: pass
        except Exception as e:
            logger.warning(f"[MISS] part {p+1}: {e}")

    logger.info(f"[MISS] done: {missing_count} missing ({label} · {period})")


# ═══════════════════════════════════════════════════════════════════════════
# CLEANUP LOOP
# ═══════════════════════════════════════════════════════════════════════════
async def _cleanup_loop():
    while True:
        try:
            await asyncio.sleep(600)
            _cleanup_sessions()
        except asyncio.CancelledError:
            break
        except Exception:
            pass


try:
    asyncio.get_event_loop().create_task(_cleanup_loop())
except Exception:
    pass

# ═══════════════════════════════════════════════════════════════════════════
# EXPORTS
# ═══════════════════════════════════════════════════════════════════════════
__all__ = ["cmd_missing", "open_panel_for_admin"]


logger.info("")
logger.info("╔════════════════════════════════════════════════════════════════╗")
logger.info("║  🔍 MISSING FILES FINDER — V1 + V2 MERGED ✅                   ║")
logger.info("║                                                                ║")
logger.info("║  Commands: /missing · /gapscan · /lackfiles                    ║")
logger.info("║  Admin:    /admin → 🔎 MISSING                                 ║")
logger.info("║                                                                ║")
logger.info("║  Features: scan · history · settings · templates · buttons     ║")
logger.info("║  Storage:  MongoDB (settings · history · templates)            ║")
logger.info("╚════════════════════════════════════════════════════════════════╝")
