# ============================================================
# 🎛️ AI LIBRARIAN — KEYBOARDS + VIEW BUILDERS + PROGRESS BAR
# ============================================================
from __future__ import annotations
import asyncio, logging
from typing import Any, Dict, List

from pyrogram.enums import ParseMode
from pyrogram.errors import MessageNotModified, FloodWait
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from plugins.ai_librarian.fonts import (
    fb, sc, DIV, DIV2, QUALITY_RANK,
    _fmt_int, _esc, _now_ist,
    LIVE_DURATION_SEC,
)
from plugins.ai_librarian.db import (
    _get_setting, _count_completed,
)

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# KEYBOARDS
# ═══════════════════════════════════════════════════════════════════════════
def kb_main(auto_on, completed, total):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🟢 AUTO MODE ON" if auto_on else "🔴 AUTO MODE OFF",
                              callback_data="ai:toggle_auto")],
        [InlineKeyboardButton("➕ ADD SERIES (LIVE)", callback_data="ai:add")],
        [InlineKeyboardButton(f"📚 ALL SERIES ({total})", callback_data="ai:all"),
         InlineKeyboardButton(f"✅ COMPLETED ({completed})",
                              callback_data="ai:completed")],
        [InlineKeyboardButton("📊 STATUS", callback_data="ai:last_report"),
         InlineKeyboardButton("🔄 REFRESH", callback_data="ai:main")],
        [InlineKeyboardButton("❌ CLOSE", callback_data="ai:close")],
    ])


def kb_live_controls(uid):
    return InlineKeyboardMarkup([
        [InlineKeyboardButton("🔄 REFRESH NOW", callback_data="ai:live_refresh"),
         InlineKeyboardButton("✅ MARK COMPLETE", callback_data="ai:live_complete")],
        [InlineKeyboardButton("❌ CANCEL LIVE", callback_data="ai:live_cancel")],
    ])


def kb_back(target="ai:main"):
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("◀️ BACK", callback_data=target),
        InlineKeyboardButton("❌ CLOSE", callback_data="ai:close")]])


def kb_series_list(lst):
    rows = []
    for s in lst[:25]:
        title = (s.get("title") or "?")[:32]
        count = s.get("file_count", 0)
        rows.append([InlineKeyboardButton(
            f"🎬 {title} · {count}",
            callback_data=f"ai:view:{s['title_slug']}")])
    rows.append([InlineKeyboardButton("◀️ BACK", callback_data="ai:main"),
                 InlineKeyboardButton("❌ CLOSE", callback_data="ai:close")])
    return InlineKeyboardMarkup(rows)


def kb_add_cancel():
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("❌ CANCEL", callback_data="ai:main")]])


def kb_suggestions(items):
    """TMDB suggestions — name in caps + rating."""
    rows = []
    for i, it in enumerate(items):
        title = (it.get("title") or "?").strip().upper()
        rating = it.get("rating", 0)
        if len(title) > 42:
            title = title[:41] + "…"
        label = title
        if rating:
            label += f" ⭐{rating:.1f}"
        rows.append([InlineKeyboardButton(
            label, callback_data=f"ai:pick:{i}")])
    rows.append([InlineKeyboardButton("✍️ SEARCH DB ONLY",
                                       callback_data="ai:search_db_only")])
    rows.append([InlineKeyboardButton("❌ CANCEL", callback_data="ai:main")])
    return InlineKeyboardMarkup(rows)


# ═══════════════════════════════════════════════════════════════════════════
# VIEW BUILDERS
# ═══════════════════════════════════════════════════════════════════════════
async def _view_main():
    auto_on = await _get_setting("auto_mode", True)
    comp = await _count_completed()
    total = await _get_setting("total_series", 0)
    return "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🎛️ <b>{fb('AI LIBRARIAN')}</b>",
        DIV, "",
        f"⚙️ {sc('auto mode')} · {'🟢 ᴏɴ' if auto_on else '🔴 ᴏꜰꜰ'}",
        f"✅ {sc('completed')} · <code>{_fmt_int(comp)}</code>",
        f"📚 {sc('total series')} · <code>{_fmt_int(total)}</code>",
        "", DIV2, "",
        f"➕ {sc('add series')} · ʟɪᴠᴇ 1-ʜᴏᴜʀ ꜱᴄᴀɴ",
        f"🔄 {sc('auto refresh')} · ᴇᴠᴇʀʏ 30 ꜱᴇᴄᴏɴᴅꜱ",
        f"🟢 {sc('green tick')} ᴡʜᴇɴ ꜰɪʟᴇ ꜰᴏᴜɴᴅ",
        "", DIV2,
        f"🕒 <code>{_now_ist()}</code>",
    ]), kb_main(auto_on, comp, total)


def _view_add_prompt():
    return "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"➕ <b>{fb('ADD SERIES')}</b>",
        DIV, "",
        f"📝 {sc('send the series name')}",
        "",
        f"📌 {sc('examples')}:",
        f"<code>breaking bad</code>",
        f"<code>game of thrones</code>",
        f"<code>money heist</code>",
        "", DIV2,
        f"💡 {sc('bot will search tmdb + your db')}",
        f"💡 {sc('then start live 1-hour scan')}",
    ])


def _view_searching(query):
    return "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🔍 <b>{fb('SEARCHING')}</b>",
        DIV, "",
        f"📝 <code>{_esc(query)}</code>",
        "",
        f"📌 {sc('checking tmdb + your db')}...",
    ])


def _view_live_header(title, year, elapsed, total_expected, stats):
    minutes = int(elapsed // 60)
    seconds = int(elapsed % 60)
    remaining = max(0, LIVE_DURATION_SEC - int(elapsed))
    rem_min = remaining // 60

    found = stats["total_found"]
    seasons_found = len(stats["seasons"])

    if total_expected > 0:
        pct = min(100.0, found / total_expected * 100)
    else:
        pct = 0

    bar = _progress_bar(pct)

    lines = [
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🔴 <b>{fb('LIVE SCAN')}</b> · ⏱️ <code>{minutes:02d}:{seconds:02d}</code>",
        DIV, "",
        f"🎬 <b>{_esc(title)}</b>"
        + (f" <code>({year})</code>" if year else ""),
        "",
        f"<code>{bar}</code>",
        "",
        f"📁 {sc('found')} · <code>{found}</code>"
        + (f" / <code>{total_expected}</code>" if total_expected else ""),
        f"📺 {sc('seasons')} · <code>{seasons_found}</code>",
        f"⏳ {sc('ends in')} · <code>{rem_min} ᴍɪɴ</code>",
        "", DIV2, "",
    ]
    return "\n".join(lines)


def _view_live_grid(stats, tmdb_seasons):
    seasons_data = stats["seasons"]
    expected = stats["expected"]

    all_seasons = set(seasons_data.keys()) | set(expected.keys())
    if not all_seasons:
        return "⚪ ɴᴏ ᴇᴘɪꜱᴏᴅᴇꜱ ꜰᴏᴜɴᴅ ʏᴇᴛ..."

    lines = []
    for sn in sorted(all_seasons):
        eps_found = seasons_data.get(sn, {})
        eps_expected = expected.get(sn)

        if eps_expected:
            header = (f"📺 <b>Season {sn:02d}</b> · "
                      f"<code>{len(eps_found)}/{len(eps_expected)}</code>")
        else:
            header = (f"📺 <b>Season {sn:02d}</b> · "
                      f"<code>{len(eps_found)} ᴇᴘɪꜱᴏᴅᴇꜱ</code>")
        lines.append(header)

        if eps_expected:
            episode_set = sorted(eps_expected)
        else:
            episode_set = sorted(eps_found.keys())

        if not episode_set:
            lines.append("   ⚪ ɴᴏ ᴇᴘɪꜱᴏᴅᴇꜱ ʏᴇᴛ")
            lines.append("")
            continue

        for ep in episode_set:
            quals = sorted(eps_found.get(ep, set()),
                           key=lambda x: QUALITY_RANK.get(x, 0), reverse=True)
            if quals:
                icon = "🟢"
                q_str = " ".join(f"<code>{q}</code>" for q in quals[:4])
                if len(quals) > 4:
                    q_str += f" +{len(quals)-4}"
            else:
                icon = "🔴"
                q_str = "<i>—</i>"
            lines.append(f"   {icon} <b>E{ep:02d}</b> · {q_str}")

        lines.append("")

    lines.append(DIV2)
    lines.append(f"🟢 = {sc('available')}   🔴 = {sc('missing')}")
    return "\n".join(lines)


def _view_live(title, year, elapsed, total_expected, stats, tmdb_seasons):
    header = _view_live_header(title, year, elapsed,
                               total_expected, stats)
    grid = _view_live_grid(stats, tmdb_seasons)
    return header + grid


def _view_timeout(title):
    return "\n".join([
        f"🏨 <b>{fb('DOWNTOWN VILLA')}</b>",
        f"⏱️ <b>{fb('SESSION ENDED')}</b>",
        DIV, "",
        f"🎬 <b>{_esc(title)}</b>",
        "",
        f"📌 {sc('1-hour live window closed')}",
        f"📌 {sc('tap add series again to restart')}",
    ])


def _progress_bar(p, w=16):
    p = max(0.0, min(100.0, float(p)))
    filled = int(w * p / 100); empty = w - filled
    block = "🟩" if p >= 75 else ("🟨" if p >= 50 else ("🟧" if p >= 25 else "🟥"))
    return block * filled + "⬛" * empty + f"  {p:.0f}%"


# ═══════════════════════════════════════════════════════════════════════════
# SAFE EDIT
# ═══════════════════════════════════════════════════════════════════════════
async def _safe_edit(q_or_msg, text, kb=None):
    try:
        m = getattr(q_or_msg, "message", q_or_msg)
        await m.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                           disable_web_page_preview=True)
        return True
    except MessageNotModified:
        return True
    except FloodWait as e:
        await asyncio.sleep(e.value + 1)
        try:
            m = getattr(q_or_msg, "message", q_or_msg)
            await m.edit_text(text, reply_markup=kb, parse_mode=ParseMode.HTML,
                               disable_web_page_preview=True)
            return True
        except Exception: return False
    except Exception as e:
        logger.debug(f"[AI] edit: {e}")
        return False


async def _edit_by_ids(client, chat_id, msg_id, text, kb=None):
    try:
        await client.edit_message_text(
            chat_id=chat_id, message_id=msg_id,
            text=text, reply_markup=kb, parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        return True
    except MessageNotModified: return True
    except FloodWait as e:
        await asyncio.sleep(e.value + 1)
        try:
            await client.edit_message_text(
                chat_id=chat_id, message_id=msg_id,
                text=text, reply_markup=kb, parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
            return True
        except Exception: return False
    except Exception as e:
        logger.debug(f"[AI] edit_by_ids: {e}")
        return False


__all__ = [
    "kb_main", "kb_live_controls", "kb_back", "kb_series_list",
    "kb_add_cancel", "kb_suggestions",
    "_view_main", "_view_add_prompt", "_view_searching",
    "_view_live_header", "_view_live_grid", "_view_live", "_view_timeout",
    "_progress_bar",
    "_safe_edit", "_edit_by_ids",
]
