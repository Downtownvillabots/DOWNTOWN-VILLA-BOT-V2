# plugins/groups/series/handler.py
# ============================================================
# 🏨 DOWNTOWN VILLA — SERIES GROUP HANDLER (v1 UX · v2 POWER)
# ============================================================
# Flow:
#   group text → search → suggestions → language → season
#             → [episode] → quality → PM delivery
#
# Quality screen behaviour:
#   • User already started bot → quality deep-link buttons
#   • User never started bot    → single "START BOT" button
#
# Callback prefix: sg:
# Handler group: -9999
# ============================================================

from __future__ import annotations

import asyncio
import base64
import logging
import os
import re
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Set, Tuple

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.errors import (
    FloodWait, MessageNotModified, UserIsBlocked, ChatAdminRequired,
)
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
    InputMediaPhoto,
)

from core import config as CFG
from plugins.groups import state as S
from plugins.groups.shared import search as SEARCH
from plugins.groups.shared import suggestions as SUGG
from plugins.groups.shared import deep_link as DL
from plugins.groups.series import flow as SFLOW
from plugins.groups.series import tmdb as STMDB
from utils import fonts as F
from utils import format as FM

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# SECTION 1 — CONFIG
# ═══════════════════════════════════════════════════════════════════════════
IST = timezone(timedelta(hours=5, minutes=30))
DIV = F.DIV
DIV_S = F.DIV_S

COOLDOWN = 3.0
MIN_QUERY_LEN = 2
MAX_QUERY_LEN = 100
SESSION_TTL = 900
WIZARD_TTL = 900.0
DELIVER_BATCH_DELAY = 0.6

try:
    _sg_env = int(os.getenv("SERIES_GROUP_ID", "0") or 0)
except (TypeError, ValueError):
    _sg_env = 0
if not _sg_env:
    try:
        _sg_env = int(getattr(CFG, "SERIES_GROUP_ID", 0) or 0)
    except Exception:
        _sg_env = 0
SERIES_GROUP_ID: Optional[int] = _sg_env or None

SERIES_GROUP_ENABLED = os.getenv("SERIES_GROUP_ENABLED", "true").lower() in (
    "1", "true", "yes", "on",
)

REQST_CHANNEL = getattr(CFG, "REQST_CHANNEL", None) or None
UPDATE_CHNL_LNK = getattr(CFG, "UPDATE_CHNL_LNK", None) or "https://t.me/"
ADMINS = list(getattr(CFG, "ADMINS", []) or [])


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 2 — SMALL HELPERS
# ═══════════════════════════════════════════════════════════════════════════
def fb(s: Any) -> str:
    return F.fb(str(s))


def sc(s: Any) -> str:
    return F.sc(str(s))


def esc(t: Any) -> str:
    if t is None:
        return ""
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def b64e(s: str) -> str:
    try:
        return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")
    except Exception:
        return ""


def b64d(s: str) -> str:
    try:
        pad = "=" * (4 - len(s) % 4)
        return base64.urlsafe_b64decode((s + pad).encode()).decode()
    except Exception:
        return ""


def is_admin(uid: Any) -> bool:
    try:
        return int(uid) in [int(a) for a in ADMINS]
    except Exception:
        return False


def fmt_size(b: Any) -> str:
    try:
        return FM.size(int(b or 0))
    except Exception:
        return "0 B"


def now_ist() -> str:
    return datetime.now(IST).strftime("%d %b %Y · %H:%M IST")


def poster_url(path: Any, size: str = "w500") -> Optional[str]:
    if not path:
        return None
    s = str(path)
    if s.startswith("http://") or s.startswith("https://"):
        return s
    try:
        return STMDB.poster_url(s, size)
    except Exception:
        return f"https://image.tmdb.org/t/p/{size}{s}"


def summarize_hits(hits: List[Dict[str, Any]]) -> Dict[str, Any]:
    langs: Set[str] = set()
    seasons: Dict[int, Set[int]] = defaultdict(set)
    for h in hits:
        for l in (h.get("audio_languages") or []):
            n = str(l).strip().title()
            if n:
                langs.add(n)
        sn = h.get("season")
        ep = h.get("episode")
        if sn is None:
            continue
        try:
            sn_i = int(sn)
        except (TypeError, ValueError):
            continue
        try:
            ep_i = int(ep) if ep is not None else 0
        except (TypeError, ValueError):
            ep_i = 0
        seasons[sn_i].add(ep_i)
    return {
        "languages": sorted(langs),
        "seasons": {k: sorted(v) for k, v in seasons.items()},
    }


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 3 — SESSION + COOLDOWN
# ═══════════════════════════════════════════════════════════════════════════
_SESSIONS: Dict[int, Dict[str, Any]] = {}
_last_seen: Dict[int, float] = {}


def sess_new(uid: int, chat_id: int, **data) -> None:
    _SESSIONS[int(uid)] = {
        "data": {"chat_id": int(chat_id), **data},
        "expires": time.time() + SESSION_TTL,
    }


def sess_get(uid: int) -> Optional[Dict[str, Any]]:
    s = _SESSIONS.get(int(uid))
    if not s:
        return None
    if time.time() > s["expires"]:
        _SESSIONS.pop(int(uid), None)
        return None
    return s


def sess_set(uid: int, **data) -> None:
    s = _SESSIONS.get(int(uid))
    if not s:
        return
    s["data"].update(data)
    s["expires"] = time.time() + SESSION_TTL


def sess_drop(uid: int) -> None:
    _SESSIONS.pop(int(uid), None)


def cleanup_sessions() -> None:
    now = time.time()
    for u in list(_SESSIONS.keys()):
        if _SESSIONS[u]["expires"] < now:
            _SESSIONS.pop(u, None)


def cooldown_ok(uid: int) -> bool:
    now = time.time()
    if now - _last_seen.get(int(uid), 0) < COOLDOWN:
        return False
    _last_seen[int(uid)] = now
    return True


def cleanup_cooldown() -> None:
    now = time.time()
    if len(_last_seen) < 5000:
        return
    for k in list(_last_seen.keys()):
        if now - _last_seen[k] > 300:
            _last_seen.pop(k, None)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 3b — USER STARTED CHECK (v1-style delivery gate)
# ═══════════════════════════════════════════════════════════════════════════
async def user_started_bot(uid: int) -> bool:
    """
    True if the user has ever started the bot (a `users` doc exists).
    Fails open — if we can't verify, we treat them as started so
    they still get the direct deep-link quality buttons.
    """
    try:
        from database import db_registry
        db = db_registry.get_user_db()
        if db is None:
            return True
        doc = await db["users"].find_one(
            {"user_id": int(uid)}, {"_id": 1},
        )
        return doc is not None
    except Exception as e:
        logger.debug(f"[SERIES-H] user_started check: {e}")
        return True


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 4 — FLOW LAYOUT READERS
# ═══════════════════════════════════════════════════════════════════════════
async def get_per_row(chat_id: int, key: str, default: int = 2) -> int:
    try:
        n = await SFLOW.get_per_row(chat_id, key)
        if n:
            return int(n)
    except Exception:
        pass
    return default


async def get_max_items(chat_id: int, key: str, default: int = 12) -> int:
    try:
        n = await SFLOW.get_max_items(chat_id, key, default)
        if n:
            return int(n)
    except Exception:
        pass
    return default


async def step_enabled(chat_id: int, key: str) -> bool:
    try:
        return bool(await SFLOW.is_step_enabled(chat_id, key))
    except Exception:
        return True


async def step_auto_skip(chat_id: int, key: str) -> bool:
    return False


async def wizard_steps(chat_id: int) -> List[str]:
    return ["language", "season", "episode", "quality", "file_delivery"]


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 5 — VIEWS
# ═══════════════════════════════════════════════════════════════════════════
def view_suggestions(raw: str, items: List[Dict[str, Any]]) -> str:
    lines = [
        f"{F.EMO['brand']} <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🎬 <b>{fb('SERIES SUGGESTIONS')}</b>",
        DIV, "",
        f"🔍 {sc('you searched')} · <code>{esc(raw)}</code>",
        "", f"📌 {sc('pick the series you meant')}",
        "", DIV_S, "",
    ]
    for i, it in enumerate(items, 1):
        title = (it.get("title") or "?").strip().upper()
        rating = it.get("rating") or 0
        line = f"<b>{i}.</b> <b>{esc(title)}</b>"
        try:
            if rating:
                line += f" · ⭐ {float(rating):.1f}"
        except (TypeError, ValueError):
            pass
        lines.append(line)
    lines += [
        "", DIV_S,
        f"💡 {sc('not what you wanted?')} · ᴛᴀᴘ ʀᴇǫᴜᴇꜱᴛ ʙᴜᴛᴛᴏɴ",
    ]
    return "\n".join(lines)


def view_languages(title: str, year: Any) -> str:
    yr = f" ({year})" if year else ""
    return "\n".join([
        f"{F.EMO['brand']} <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🎬 <b>{esc(title)}</b>{yr}",
        DIV, "", f"🌍 {sc('pick language')}",
        "", f"🟢 {sc('has files')} · ⚪ {sc('tmdb only')}",
    ])


def view_seasons(title: str, year: Any) -> str:
    yr = f" ({year})" if year else ""
    return "\n".join([
        f"{F.EMO['brand']} <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🎬 <b>{esc(title)}</b>{yr}",
        DIV, "", f"📺 {sc('pick season')}",
        "", "🟢 ꜰᴜʟʟ · 🟡 ᴘᴀʀᴛɪᴀʟ · ⚪ ɴᴏ ꜰɪʟᴇꜱ",
    ])


def view_episodes(title: str, season: int, count: int) -> str:
    return "\n".join([
        f"{F.EMO['brand']} <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🎬 <b>{esc(title)}</b>",
        f"📺 <b>Season {int(season):02d}</b>",
        DIV, "", f"🎞️ {sc('pick episode')}",
        "", f"📁 <code>{count}</code> ꜰɪʟᴇꜱ ᴛᴏ ꜱᴇɴᴅ",
    ])


def view_qualities(title: str, season: int, count: int) -> str:
    return "\n".join([
        f"{F.EMO['brand']} <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🎬 <b>{esc(title)}</b>",
        f"📺 <b>Season {int(season):02d}</b>",
        DIV, "", f"🎯 <b>{sc('pick quality')}</b>",
        "", f"📁 <code>{count}</code> ꜰɪʟᴇꜱ ᴛᴏ ꜱᴇɴᴅ",
        f"📩 <i>ᴛᴀᴘ ᴀ ǫᴜᴀʟɪᴛʏ ᴛᴏ ɢᴇᴛ ꜰɪʟᴇꜱ ɪɴ ʙᴏᴛ ᴘᴍ</i>",
    ])


def view_start_bot_first(
    title: str, season: int, quality: str, count: int,
) -> str:
    return "\n".join([
        f"{F.EMO['brand']} <b>{fb('DOWNTOWN VILLA')}</b>",
        f"{F.EMO['rocket']} <b>{fb('START THE BOT FIRST')}</b>",
        DIV, "",
        f"🎬 <b>{esc(title)}</b>",
        f"📺 <b>Season {int(season):02d}</b>",
        f"🎯 <code>{esc(quality)}</code>",
        "", f"📁 <code>{count}</code> ᴇᴘɪꜱᴏᴅᴇꜱ ʀᴇᴀᴅʏ",
        "",
        f"📌 {sc('tap the button below')}",
        f"📌 {sc('then press START in telegram')}",
        f"📌 {sc('files will arrive in your pm')}",
    ])


def view_redirecting(title: str, season: int, quality: str, count: int) -> str:
    return "\n".join([
        f"{F.EMO['brand']} <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🚀 <b>{fb('REDIRECTING TO PM')}</b>",
        DIV, "",
        f"🎬 <b>{esc(title)}</b>",
        f"📺 <b>Season {int(season):02d}</b>",
        f"🎯 <code>{esc(quality)}</code>",
        "", f"📁 <code>{count}</code> ᴇᴘɪꜱᴏᴅᴇꜱ",
        "", f"📌 {sc('bot will open in pm')}",
        f"📌 {sc('files will be delivered there')}",
    ])

# ═══════════════════════════════════════════════════════════════════════════
# SECTION 5b — NO-FILES CARD (suggestion clicked but not in DB)
# ═══════════════════════════════════════════════════════════════════════════
def view_no_files_card(title: str, year: Any = None) -> str:
    yr = f" ({year})" if year else ""
    return "\n".join([
        f"{F.EMO['brand']} <b>{fb('DOWNTOWN VILLA')}</b>",
        f"❌ <b>{fb('NOT IN DATABASE YET')}</b>",
        DIV, "",
        f"🎬 <b>{esc(title)}</b>{yr}",
        "",
        f"📌 {sc('this title is not in our database yet')}",
        f"📌 {sc('your request has been sent to admin')}",
        f"📌 {sc('we will notify you once it is uploaded')}",
        "",
        DIV_S,
        f"📩 {sc('you will be notified once it is uploaded')}",
    ])


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 6 — KEYBOARDS
# ═══════════════════════════════════════════════════════════════════════════
def kb_suggestions(items: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    for i, it in enumerate(items):
        title = (it.get("title") or "?").strip().upper()
        if len(title) > 42:
            title = title[:41] + "…"
        rating = it.get("rating") or 0
        label = title
        try:
            if rating:
                label += f" ⭐{float(rating):.1f}"
        except (TypeError, ValueError):
            pass
        rows.append([
            InlineKeyboardButton(label, callback_data=f"sg:pick:{i}")
        ])
    rows.append([
        InlineKeyboardButton("📩 REQUEST TO ADMIN", callback_data="sg:request")
    ])
    rows.append([
        InlineKeyboardButton("❌ CLOSE", callback_data="sg:close")
    ])
    return InlineKeyboardMarkup(rows)


def kb_languages(
    langs: List[str], local_langs: List[str],
    per_row: int = 2, max_items: int = 12,
) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []
    for i, lang in enumerate(langs[:max_items]):
        mark = "🟢" if lang in local_langs else "⚪"
        row.append(InlineKeyboardButton(
            f"{mark} {lang}", callback_data=f"sg:lang:{i}"))
        if len(row) >= per_row:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([
        InlineKeyboardButton("◀️ BACK", callback_data="sg:back_sugg"),
        InlineKeyboardButton("❌ CLOSE", callback_data="sg:close"),
    ])
    return InlineKeyboardMarkup(rows)


def kb_seasons(
    seasons: List[Dict[str, Any]], local: Dict[int, List[int]],
    per_row: int = 1, max_items: int = 15,
) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []
    for i, s in enumerate(seasons[:max_items]):
        sn = int(s.get("season") or 0)
        eps = int(s.get("episodes") or 0)
        local_eps = local.get(sn, [])
        if local_eps:
            cnt = len([e for e in local_eps if e > 0])
            mark = "🟢" if cnt >= eps else "🟡"
        else:
            cnt = 0
            mark = "⚪"
        label = f"{mark} S{sn:02d} · {eps} ᴇᴘ"
        if cnt:
            label += f" · {cnt} ʟᴏᴄᴀʟ"
        row.append(InlineKeyboardButton(
            label, callback_data=f"sg:seas:{i}"))
        if len(row) >= per_row:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    if not rows:
        rows.append([
            InlineKeyboardButton("⚠️ no seasons", callback_data="sg:close")
        ])
    rows.append([
        InlineKeyboardButton("◀️ BACK", callback_data="sg:back_lang"),
        InlineKeyboardButton("❌ CLOSE", callback_data="sg:close"),
    ])
    return InlineKeyboardMarkup(rows)


def kb_episodes(
    eps: List[int], season: int, local_eps: List[int],
    per_row: int = 4, max_items: int = 30,
) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []
    seen: Set[int] = set()
    for ep in eps[:max_items]:
        try:
            e = int(ep)
        except (TypeError, ValueError):
            continue
        if e in seen:
            continue
        seen.add(e)
        mark = "🟢" if e in local_eps else "⚪"
        row.append(InlineKeyboardButton(
            f"{mark} E{e:02d}", callback_data=f"sg:ep:{e}"))
        if len(row) >= per_row:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([
        InlineKeyboardButton("◀️ BACK", callback_data="sg:back_seas"),
        InlineKeyboardButton("❌ CLOSE", callback_data="sg:close"),
    ])
    return InlineKeyboardMarkup(rows)


def kb_qualities(
    qual_items: List[Tuple[str, str]],
    per_row: int = 2, max_items: int = 12,
) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []
    for q_label, q_url in qual_items[:max_items]:
        row.append(InlineKeyboardButton(f"🎯 {q_label}", url=q_url))
        if len(row) >= per_row:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([
        InlineKeyboardButton("◀️ BACK", callback_data="sg:back_ep"),
        InlineKeyboardButton("❌ CLOSE", callback_data="sg:close"),
    ])
    return InlineKeyboardMarkup(rows)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 7 — RENDER
# ═══════════════════════════════════════════════════════════════════════════
async def render(
    client: Client, chat_id: int, msg_id: int,
    text: str, kb: Optional[InlineKeyboardMarkup],
    poster: Optional[str] = None,
) -> bool:
    if poster:
        try:
            await client.edit_message_media(
                chat_id=chat_id, message_id=msg_id,
                media=InputMediaPhoto(
                    media=poster, caption=text,
                    parse_mode=ParseMode.HTML,
                ),
                reply_markup=kb,
            )
            return True
        except MessageNotModified:
            return True
        except Exception as e:
            logger.debug(f"[SERIES-H] edit_media: {e}")
        try:
            await client.delete_messages(chat_id, msg_id)
        except Exception:
            pass
        try:
            await client.send_photo(
                chat_id=chat_id, photo=poster, caption=text,
                reply_markup=kb, parse_mode=ParseMode.HTML,
            )
            return True
        except Exception as e:
            logger.warning(f"[SERIES-H] send_photo: {e}")

    try:
        await client.edit_message_text(
            chat_id=chat_id, message_id=msg_id, text=text,
            reply_markup=kb, parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        return True
    except MessageNotModified:
        return True
    except Exception as e:
        logger.debug(f"[SERIES-H] edit_text: {e}")
        try:
            await client.send_message(
                chat_id=chat_id, text=text, reply_markup=kb,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
            return True
        except Exception:
            return False


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 8 — SAFE CAPTION + CUSTOM BUTTONS
# ═══════════════════════════════════════════════════════════════════════════
class _SafeDict(dict):
    def __missing__(self, key):
        return ""


def safe_caption(template: str, ctx: Dict[str, Any], fallback: str) -> str:
    if not template:
        return fallback
    try:
        return template.format_map(_SafeDict(ctx))
    except Exception:
        return fallback


def build_extra_kb(buttons: List[Dict[str, Any]]) -> Optional[InlineKeyboardMarkup]:
    if not buttons:
        return None
    rows: List[List[InlineKeyboardButton]] = []
    for b in buttons:
        if not isinstance(b, dict):
            continue
        if not b.get("enabled", True):
            continue
        name = str(b.get("name") or "")[:60]
        url = str(b.get("url") or "").strip()
        if not name or not url:
            continue
        if url.startswith("@"):
            url = f"https://t.me/{url[1:]}"
        elif not (url.startswith("http://")
                  or url.startswith("https://")
                  or url.startswith("tg://")):
            if "." in url and " " not in url:
                url = f"https://{url}"
            else:
                continue
        rows.append([InlineKeyboardButton(name, url=url)])
    return InlineKeyboardMarkup(rows) if rows else None


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 9 — DB SEARCH
# ═══════════════════════════════════════════════════════════════════════════
def _norm(s: str) -> str:
    if not s:
        return ""
    s = s.strip().lower()
    s = re.sub(r"[.\-_/,;:]+", " ", s)
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[^\w\s]", "", s)
    return s.strip()


async def smart_db_search(title: str) -> Optional[Dict[str, Any]]:
    try:
        hits, _ = await SEARCH.quick_search(title, is_series=True)
    except Exception as e:
        logger.debug(f"[SERIES-H] quick_search: {e}")
        hits = []

    if hits:
        matched = (
            hits[0].get("series_title")
            or hits[0].get("title")
            or title
        )
        return {"matched_title": matched, "hits": hits}

    norm = _norm(title)
    words = norm.split()
    for i in range(len(words) - 1, max(0, len(words) - 4), -1):
        partial = " ".join(words[:i])
        if len(partial) < 3:
            continue
        try:
            hits, _ = await SEARCH.quick_search(partial, is_series=True)
        except Exception:
            hits = []
        if hits:
            matched = (
                hits[0].get("series_title")
                or hits[0].get("title")
                or partial
            )
            return {"matched_title": matched, "hits": hits}
    return None


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 10 — TMDB ENRICHMENT
# ═══════════════════════════════════════════════════════════════════════════
async def enrich_with_tmdb(
    matched_title: str,
    hits: List[Dict[str, Any]],
    tmdb_id_override: Optional[int] = None,
    poster_override: Optional[str] = None,
    year_override: Optional[str] = None,
) -> Dict[str, Any]:
    tmdb_id: Optional[int] = tmdb_id_override
    poster: Optional[str] = poster_override
    year: str = str(year_override) if year_override else ""
    tmdb_langs: List[str] = ["English"]
    tmdb_seasons: List[Dict[str, Any]] = []

    if tmdb_id is None or poster is None or not year:
        try:
            from providers import tmdb_provider as TP
            results = await TP.search_tv(matched_title) or []
            if results:
                top = results[0]
                if tmdb_id is None:
                    try:
                        tmdb_id = int(top.get("tmdb_id")) if top.get("tmdb_id") else None
                    except (TypeError, ValueError):
                        tmdb_id = None
                if poster is None:
                    poster = top.get("poster")
                if not year:
                    year = str(top.get("year") or "")
        except Exception as e:
            logger.debug(f"[SERIES-H] tmdb search: {e}")

    try:
        langs = await STMDB.get_series_languages(matched_title)
        if langs:
            tmdb_langs = list(langs)
    except Exception as e:
        logger.debug(f"[SERIES-H] tmdb langs: {e}")

    try:
        seasons = await STMDB.get_series_seasons(matched_title)
        if seasons:
            tmdb_seasons = list(seasons)
    except Exception as e:
        logger.debug(f"[SERIES-H] tmdb seasons: {e}")

    if not year and hits:
        for h in hits:
            y = h.get("year")
            if y:
                year = str(y)
                break

    summary = summarize_hits(hits)
    display_title = matched_title

    return {
        "tmdb_id": tmdb_id,
        "title": display_title,
        "year": year,
        "poster": poster,
        "tmdb_langs": tmdb_langs,
        "tmdb_seasons": tmdb_seasons,
        "local_langs": summary["languages"],
        "local_seasons": summary["seasons"],
    }


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 11 — REQUEST CHANNEL
# ═══════════════════════════════════════════════════════════════════════════
def _get_system_db():
    try:
        from database import db_registry
        return db_registry.get_system_db()
    except Exception:
        return None


def _req_coll():
    d = _get_system_db()
    return d["search_requests"] if d is not None else None


async def add_request(
    user_id: int, title: str,
    year: Optional[Any] = None,
    tmdb_id: Optional[int] = None,
    source: str = "series_search",
) -> Optional[str]:
    c = _req_coll()
    if c is None:
        return None
    try:
        token = uuid.uuid4().hex[:12]
        await c.insert_one({
            "token_id": token,
            "user_id": int(user_id),
            "movie_name": title,
            "query": title,
            "year": year,
            "tmdb_id": tmdb_id,
            "kind": "series",
            "source": source,
            "status": "not_found",
            "created_at": time.time(),
        })
        return token
    except Exception as e:
        logger.warning(f"[SERIES-H] req save: {e}")
        return None


async def get_request(token: str) -> Optional[Dict[str, Any]]:
    c = _req_coll()
    if c is None:
        return None
    try:
        return await c.find_one({"token_id": token})
    except Exception:
        return None


async def post_to_request_channel(
    client: Client, user_id: int, title: str,
    year: Optional[Any] = None,
    tmdb_id: Optional[int] = None,
    source: str = "series_search",
) -> Optional[str]:
    if not REQST_CHANNEL:
        logger.warning("[SERIES-H] REQST_CHANNEL not set")
        return None

    token = await add_request(user_id, title, year, tmdb_id, source)
    if not token:
        return None

    try:
        user_obj = await client.get_users(user_id)
        user_mention = getattr(user_obj, "mention", f"user {user_id}")
    except Exception:
        user_mention = f"user {user_id}"

    title_disp = title + (f" ({year})" if year else "")
    lines = [
        f"{F.EMO['brand']} <b>{fb('DOWNTOWN VILLA')}</b>",
        f"📺 <b>{fb('NEW SERIES REQUEST')}</b>",
        DIV, "",
        f"🎬 {sc('series')} · <b>{esc(title_disp)}</b>",
    ]
    if tmdb_id:
        lines.append(f"🎯 {sc('tmdb')} · <code>{tmdb_id}</code>")
    lines += [
        "", f"👤 {sc('user')} · {user_mention}",
        f"🆔 {sc('id')} · <code>{user_id}</code>",
        "", f"🔑 {sc('token')} · <code>{token}</code>",
        DIV, "",
        f"<i>{sc('admin · choose an action below')}</i>",
    ]

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            "📺 SERIES UPDATED",
            callback_data=f"gsreq:{token}:updated")],
        [InlineKeyboardButton(
            "📅 NOT RELEASED",
            callback_data=f"gsreq:{token}:notreleased"),
         InlineKeyboardButton(
            "🔎 NOT FOUND",
            callback_data=f"gsreq:{token}:notfound")],
        [InlineKeyboardButton(
            "❌ CANCEL",
            callback_data=f"gsreq:{token}:cancel")],
    ])

    try:
        await client.send_message(
            chat_id=REQST_CHANNEL, text="\n".join(lines),
            reply_markup=kb, parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        logger.info(f"[SERIES-H] request posted token={token}")
        return token
    except Exception as e:
        logger.warning(f"[SERIES-H] request post fail: {e}")
        return None


async def update_request(token: str, status: str) -> bool:
    c = _req_coll()
    if c is None:
        return False
    try:
        r = await c.update_one(
            {"token_id": token},
            {"$set": {"status": status, "updated_at": time.time()}},
        )
        return r.modified_count > 0
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 12 — FORCE-SUB GATE
# ═══════════════════════════════════════════════════════════════════════════
async def check_fsub(
    client: Client, user_id: int, chat_id: int,
) -> Tuple[bool, List[int]]:
    try:
        cfg = await S.get_config(chat_id)
    except Exception:
        return True, []

    fsub = cfg.get("fsub") or {}
    if not fsub.get("enabled"):
        return True, []
    channels = fsub.get("channels") or []
    if not channels:
        return True, []

    missing: List[int] = []
    for ch in channels:
        try:
            m = await client.get_chat_member(int(ch), user_id)
        except Exception:
            missing.append(int(ch))
            continue
        st = getattr(m, "status", None)
        st = st.name.lower() if hasattr(st, "name") else str(st).lower()
        if st in ("left", "kicked", "banned"):
            missing.append(int(ch))

    return (len(missing) == 0), missing


async def kb_fsub(
    client: Client, missing: List[int],
) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    for ch in missing[:5]:
        url = "https://t.me/"
        name = str(ch)
        try:
            chat = await client.get_chat(int(ch))
            name = chat.title or name
            if getattr(chat, "username", None):
                url = f"https://t.me/{chat.username}"
            elif getattr(chat, "invite_link", None):
                url = chat.invite_link
            else:
                try:
                    inv = await client.export_chat_invite_link(int(ch))
                    if inv:
                        url = inv
                except Exception:
                    pass
        except Exception:
            pass
        rows.append([InlineKeyboardButton(
            f"📢 JOIN · {name[:30]}", url=url)])
    rows.append([InlineKeyboardButton(
        "🔄 CHECK AGAIN", callback_data="sg:fsub_check")])
    return InlineKeyboardMarkup(rows)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 13 — NO-RESULTS VIEW
# ═══════════════════════════════════════════════════════════════════════════
async def handle_no_results(
    client: Client, message: Message, status: Message, raw: str,
) -> None:
    try:
        await client.edit_message_text(
            chat_id=message.chat.id, message_id=status.id,
            text="\n".join([
                f"{F.EMO['brand']} <b>{fb('DOWNTOWN VILLA')}</b>",
                f"🔎 <b>{fb('NOT FOUND')}</b>",
                DIV, "",
                f"🎬 <code>{esc(raw)}</code>",
                "",
                f"📌 {sc('no match in db')}",
                f"📌 {sc('no match on tmdb')}",
                "", DIV_S, "",
                f"📩 {sc('sending request to admin')}…",
            ]),
            parse_mode=ParseMode.HTML,
        )

        token = await post_to_request_channel(
            client, message.from_user.id, raw,
            source="series_no_match",
        )

        if token:
            await client.edit_message_text(
                chat_id=message.chat.id, message_id=status.id,
                text="\n".join([
                    f"{F.EMO['brand']} <b>{fb('DOWNTOWN VILLA')}</b>",
                    f"✅ <b>{fb('REQUEST SENT')}</b>",
                    DIV, "",
                    f"🎬 <b>{esc(raw)}</b>",
                    "",
                    f"📌 {sc('admin will review soon')}",
                    f"📌 {sc('you will be notified in pm')}",
                ]),
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ CLOSE",
                                          callback_data="sg:close"),
                ]]),
                parse_mode=ParseMode.HTML,
            )
        else:
            await client.edit_message_text(
                chat_id=message.chat.id, message_id=status.id,
                text="\n".join([
                    f"{F.EMO['brand']} <b>{fb('DOWNTOWN VILLA')}</b>",
                    f"❌ <b>{fb('NOT FOUND')}</b>",
                    DIV, "",
                    f"🎬 <code>{esc(raw)}</code>",
                    "",
                    f"📌 {sc('try a different name')}",
                ]),
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ CLOSE",
                                          callback_data="sg:close"),
                ]]),
                parse_mode=ParseMode.HTML,
            )
    except Exception as e:
        logger.exception(f"[SERIES-H] no_results: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 14 — PREMIUM HOOK
# ═══════════════════════════════════════════════════════════════════════════
async def is_premium(uid: int) -> bool:
    try:
        from plugins.premium import state as PS
        return bool(await PS.is_premium(uid))
    except Exception:
        try:
            from plugins.premium_watch import is_premium as _ip
            return bool(await _ip(uid))
        except Exception:
            return False


async def try_premium_redirect(
    client: Client, message: Message, status: Message,
    query: str, hits: List[Dict[str, Any]],
    uid: int, chat_id: int,
) -> bool:
    try:
        slug = re.sub(r"[^a-z0-9]+", "_", query.lower()).strip("_")[:100]
        token = await DL.create_premium_token(
            user_id=uid, chat_id=chat_id,
            title=str(query)[:200], slug=slug,
            tmdb_id=None, hits=hits,
        )
        if not token:
            return False

        try:
            me = await client.identity()
            bot_username = me.username or ""
        except Exception:
            try:
                me = await client.get_me()
                bot_username = me.username or ""
            except Exception:
                bot_username = ""
        if not bot_username:
            return False

        deep_link = f"https://t.me/{bot_username}?start=prem_{token}"

        text = "\n".join([
            f"{F.EMO['brand']} <b>{fb('DOWNTOWN VILLA')}</b>",
            f"{F.EMO['crown']} <b>{fb('PREMIUM MODE')}</b>",
            DIV, "",
            f"🎬 <b>{sc(query[:50])}</b>",
            "",
            f"📌 ᴛᴀᴘ ᴛᴏ ᴏᴘᴇɴ ɪɴ ᴘᴍ",
        ])
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                f"{F.EMO['rocket']} {sc('open premium watch')}",
                url=deep_link,
            ),
        ]])

        try:
            await status.edit_text(
                text, reply_markup=kb,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except Exception:
            pass
        return True
    except Exception as e:
        logger.exception(f"[SERIES-H] premium: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 15 — WIZARD DISPATCHER
# ═══════════════════════════════════════════════════════════════════════════
async def goto_step(
    client: Client, target: Message, uid: int, step: str,
) -> None:
    s = sess_get(uid)
    if not s:
        return
    chat_id = s["data"].get("chat_id")

    if step in ("close", "done", ""):
        return

    if not await step_enabled(chat_id, step):
        return await advance(client, target, uid, step)

    if step == "language":
        return await render_language(client, target, uid)
    if step == "season":
        return await render_season(client, target, uid)
    if step == "episode":
        return await render_episode(client, target, uid)
    if step == "quality":
        return await render_quality(client, target, uid)
    if step == "file_delivery":
        return await deliver_to_pm(client, target, uid)

    return await advance(client, target, uid, step)


async def advance(
    client: Client, target: Message, uid: int, current: str,
) -> None:
    s = sess_get(uid)
    if not s:
        return
    chat_id = s["data"].get("chat_id")

    order = await wizard_steps(chat_id)
    try:
        idx = order.index(current)
    except ValueError:
        idx = -1

    for nxt in order[idx + 1:]:
        if await step_enabled(chat_id, nxt):
            return await goto_step(client, target, uid, nxt)

    return await deliver_to_pm(client, target, uid)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 16 — GROUP ENTRY HANDLER
# ═══════════════════════════════════════════════════════════════════════════
if SERIES_GROUP_ID and SERIES_GROUP_ENABLED:

    @Client.on_message(
        filters.chat(SERIES_GROUP_ID)
        & filters.text
        & ~filters.regex(r"^/")
        & ~filters.regex(r"^sg:"),
        group=-9999,
    )
    async def series_group_search(client: Client, message: Message):
        status: Optional[Message] = None
        try:
            txt = (message.text or "").strip()
            if len(txt) < MIN_QUERY_LEN or len(txt) > MAX_QUERY_LEN:
                return
            if not message.from_user:
                return
            low = txt.lower()
            if "http://" in low or "https://" in low or "t.me/" in low:
                return

            chat_id = message.chat.id
            uid = message.from_user.id

            try:
                cfg = await S.get_config(chat_id)
            except Exception:
                cfg = {}

            if not cfg.get("enabled", True):
                return
            if not cfg.get("search_enabled", True):
                return
            mode = str(cfg.get("content_mode", "both")).lower()
            if mode == "movie":
                return

            if not cooldown_ok(uid):
                return
            cleanup_cooldown()

            try:
                message.stop_propagation()
            except Exception:
                pass

            logger.info(f"[SERIES-H] search {txt!r} from {uid}")

            try:
                status = await message.reply_text("🔎 ꜱᴇᴀʀᴄʜɪɴɢ…")
            except Exception:
                return

            try:
                await S.bump_stat(chat_id, "searches_today")
            except Exception:
                pass

            db_match = await smart_db_search(txt)

            if db_match and await is_premium(uid):
                if await try_premium_redirect(
                    client, message, status, txt,
                    db_match["hits"], uid, chat_id,
                ):
                    return

            if db_match:
                matched_title = db_match["matched_title"]
                hits = db_match["hits"]
                logger.info(
                    f"[SERIES-H] DB match {matched_title!r} "
                    f"({len(hits)} hits)"
                )
                chosen = await enrich_with_tmdb(matched_title, hits)

                sess_new(
                    uid, chat_id,
                    suggestions=[], raw_query=txt,
                    chosen=chosen, hits=hits,
                )

                steps = await wizard_steps(chat_id)
                first = steps[0] if steps else "language"
                return await goto_step(
                    client, status, uid, first,
                )

            if await step_enabled(chat_id, "spell_check"):
                corrected: Optional[str] = None
                try:
                    corrected = await SUGG.ai_spell_check_for_group(
                        chat_id, txt, is_series=True,
                    )
                except Exception as e:
                    logger.debug(f"[SERIES-H] spell: {e}")

                if corrected and corrected.strip().lower() != txt.strip().lower():
                    try:
                        retry_match = await smart_db_search(corrected)
                    except Exception:
                        retry_match = None

                    if retry_match:
                        await status.edit_text(
                            f"🔤 corrected → <code>{sc(corrected[:40])}</code>",
                            parse_mode=ParseMode.HTML,
                        )
                        matched_title = retry_match["matched_title"]
                        hits = retry_match["hits"]
                        chosen = await enrich_with_tmdb(matched_title, hits)

                        sess_new(
                            uid, chat_id,
                            suggestions=[], raw_query=corrected,
                            chosen=chosen, hits=hits,
                        )
                        steps = await wizard_steps(chat_id)
                        first = steps[0] if steps else "language"
                        return await goto_step(client, status, uid, first)

            items: List[Dict[str, Any]] = []
            try:
                items = await SUGG.get_suggestions_for_group(
                    chat_id, txt, kind="series", limit=8,
                ) or []
            except Exception as e:
                logger.debug(f"[SERIES-H] sugg: {e}")

            stored: List[Dict[str, Any]] = []
            for it in items:
                try:
                    d = SUGG.to_dict(it) if not isinstance(it, dict) else it
                except Exception:
                    d = it if isinstance(it, dict) else {}
                if d.get("title"):
                    stored.append(d)

            if not stored:
                return await handle_no_results(
                    client, message, status, txt,
                )

            sess_new(
                uid, chat_id,
                suggestions=stored, raw_query=txt,
            )
            await render(
                client, chat_id, status.id,
                view_suggestions(txt, stored),
                kb_suggestions(stored),
                None,
            )

        except Exception as e:
            logger.exception(f"[SERIES-H] entry: {e}")
            if status is not None:
                try:
                    await status.edit_text(
                        f"{F.EMO['cross']} error — try again",
                        parse_mode=ParseMode.HTML,
                    )
                except Exception:
                    pass


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 16b — PM DELIVERY HANDLER (self-contained)
# ═══════════════════════════════════════════════════════════════════════════
# Runs FIRST (group -100000) so no other /start handler can steal
# the deliver_ payload. Reads the token from deep_link store and
# sends every episode file to the user's PM.
#
# Depends on nothing external — no start_router.py needed.
# ═══════════════════════════════════════════════════════════════════════════

@Client.on_message(
    filters.private & filters.command("start"),
    group=-100000,
)
async def series_delivery_start(client: Client, message: Message):
    if not message.from_user:
        return

    cmd = getattr(message, "command", None) or []
    if len(cmd) < 2:
        return

    payload = str(cmd[1] or "").strip()
    if not payload.startswith("deliver_"):
        return

    token = payload[8:].strip()
    if not token:
        return

    # Claim the message — nothing else will see it
    try:
        message.stop_propagation()
    except Exception:
        pass

    uid = int(message.from_user.id)
    logger.info(f"[SERIES-H] ▶️ deliver start uid={uid} token={token[:10]}…")

    # ── Load token ──
    try:
        doc = await DL.get_token(token)
    except Exception as e:
        logger.exception(f"[SERIES-H] get_token crash: {e}")
        doc = None

    if not doc:
        logger.warning(f"[SERIES-H] ❌ token NOT FOUND: {token}")
        try:
            await message.reply_text(
                "\n".join([
                    f"{F.EMO['warn']} <b>{fb('LINK EXPIRED')}</b>",
                    DIV, "",
                    f"📌 {sc('please search again in the group')}",
                ]),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        return

    kind = doc.get("kind")
    owner = int(doc.get("user_id", 0))
    logger.info(
        f"[SERIES-H] token kind={kind} owner={owner} uid={uid}"
    )

    if kind != "deliver":
        logger.warning(f"[SERIES-H] wrong token kind: {kind}")
        try:
            await message.reply_text("❌ Invalid token")
        except Exception:
            pass
        return

    if owner != uid:
        try:
            await message.reply_text(
                f"{F.EMO['cross']} {sc('this link is not for you')}",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        return

    # ── Extract payload ──
    title = str(doc.get("title") or "?")
    try:
        season = int(doc.get("season") or 0)
    except (TypeError, ValueError):
        season = 0
    quality = str(doc.get("quality") or "?")
    language = str(doc.get("language") or "")
    hits = list(doc.get("hits") or [])
    chat_id = int(doc.get("chat_id") or 0)

    logger.info(
        f"[SERIES-H] deliver: title={title!r} S{season:02d} "
        f"q={quality} files={len(hits)} chat={chat_id}"
    )

    if not hits:
        try:
            await message.reply_text(
                "\n".join([
                    f"{F.EMO['cross']} <b>{fb('NO FILES')}</b>",
                    DIV, "",
                    f"📌 {sc('please search again in the group')}",
                ]),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        return

    # ── Load group config ──
    caption_tpl = ""
    custom_buttons: List[Dict[str, Any]] = []
    auto_delete_min = 0

    if chat_id:
        try:
            cfg = await S.get_config(chat_id)
            caption_tpl = cfg.get("caption_template") or ""
            custom_buttons = cfg.get("result_buttons") or []
            ad = cfg.get("auto_delete") or {}
            if ad.get("bot_messages", True):
                auto_delete_min = int(ad.get("bot_timer", 0) or 0) // 60
            logger.info(
                f"[SERIES-H] cfg: caption={'Y' if caption_tpl else 'N'} "
                f"buttons={len(custom_buttons)} autodel={auto_delete_min}m"
            )
        except Exception as e:
            logger.warning(f"[SERIES-H] cfg load: {e}")

    custom_kb = build_extra_kb(custom_buttons)

    # ── Intro card ──
    try:
        intro_lines = [
            f"{F.EMO['brand']} <b>{fb('DOWNTOWN VILLA')}</b>",
            f"{F.EMO['rocket']} <b>{fb('DELIVERING')}</b>",
            DIV, "",
            f"🎬 <b>{esc(title[:60])}</b>",
            f"📺 <b>Season {season:02d}</b>",
            f"🎯 <code>{esc(quality)}</code>",
        ]
        if language:
            intro_lines.append(f"🔊 <code>{esc(language)}</code>")
        intro_lines += [
            "",
            f"📁 <code>{len(hits)}</code> episodes",
            "",
            f"⏳ {sc('please wait…')}",
        ]
        await message.reply_text(
            "\n".join(intro_lines),
            parse_mode=ParseMode.HTML,
        )
        logger.info(f"[SERIES-H] ✅ intro sent")
    except Exception as e:
        logger.warning(f"[SERIES-H] intro fail: {e}")

    # ── Deliver files ──
    sent_ids: List[int] = []
    sent = 0
    failed = 0

    for i, h in enumerate(hits):
        try:
            if not isinstance(h, dict):
                failed += 1
                continue

            ep = h.get("episode") or 0
            size_str = fmt_size(h.get("file_size") or 0)
            file_id = str(h.get("file_id") or "")

            logger.info(
                f"[SERIES-H] [{i+1}/{len(hits)}] ep={ep} "
                f"fid={'Y' if file_id else 'N'}"
            )

            if not file_id:
                failed += 1
                logger.warning(f"[SERIES-H] no file_id for ep={ep}")
                continue

            # Caption
            ctx = {
                "title": title, "series": title,
                "season": season, "episode": ep,
                "quality": quality, "language": language,
                "lang": language, "size": size_str,
                "file_size": size_str,
                "file_name": h.get("file_name") or "",
                "year": "—", "rating": "—", "bot_username": "",
            }
            fallback = (
                f"🎬 <b>{esc(title[:60])}</b>\n"
                f"📺 S{season:02d}E{int(ep):02d} · "
                f"<code>{esc(quality)}</code>"
            )
            caption = safe_caption(caption_tpl, ctx, fallback)

            sent_msg = None
            try:
                sent_msg = await client.send_cached_media(
                    chat_id=uid,
                    file_id=file_id,
                    caption=caption,
                    reply_markup=custom_kb,
                    parse_mode=ParseMode.HTML,
                )
            except FloodWait as e:
                w = int(getattr(e, "value", 30) or 30)
                logger.warning(f"[SERIES-H] flood {w}s")
                await asyncio.sleep(w + 2)
                try:
                    sent_msg = await client.send_cached_media(
                        chat_id=uid, file_id=file_id,
                        caption=caption, reply_markup=custom_kb,
                        parse_mode=ParseMode.HTML,
                    )
                except Exception as e2:
                    logger.warning(f"[SERIES-H] retry: {e2}")
            except UserIsBlocked:
                logger.warning(f"[SERIES-H] user blocked — stopping")
                break
            except Exception as e:
                logger.warning(
                    f"[SERIES-H] send fail: {type(e).__name__}: {e}"
                )

            if sent_msg and getattr(sent_msg, "id", None):
                sent_ids.append(sent_msg.id)
                sent += 1
                logger.info(f"[SERIES-H] ✅ ep={ep}")
            else:
                failed += 1
                logger.warning(f"[SERIES-H] ❌ ep={ep}")

            await asyncio.sleep(DELIVER_BATCH_DELAY)

        except Exception as e:
            failed += 1
            logger.exception(f"[SERIES-H] ep crash: {e}")

    logger.info(
        f"[SERIES-H] ═══ delivery done: sent={sent} failed={failed} ═══"
    )

    # ── Auto-delete schedule ──
    if auto_delete_min > 0 and sent_ids:
        try:
            warn = await message.reply_text(
                "\n".join([
                    f"⚠️ <b>{fb('AUTO-DELETE')}</b>",
                    f"📌 {sc('this will be deleted in')} "
                    f"<b>{auto_delete_min} {sc('minutes')}</b>",
                    f"📌 {sc('save or forward now')}",
                ]),
                parse_mode=ParseMode.HTML,
            )
            if warn and warn.id:
                sent_ids.append(warn.id)
        except Exception:
            pass

        asyncio.create_task(
            _pm_auto_delete(client, uid, sent_ids, auto_delete_min * 60)
        )

    # ── Summary ──
    try:
        await message.reply_text(
            "\n".join([
                f"{F.EMO['check']} <b>{fb('DELIVERY COMPLETE')}</b>",
                DIV, "",
                f"🎬 <b>{esc(title[:50])}</b>",
                f"📺 Season {season:02d} · {esc(quality)}",
                "",
                f"✅ {sc('sent')} · <code>{sent}</code>",
                f"❌ {sc('failed')} · <code>{failed}</code>",
                "",
                f"🕒 <code>{now_ist()}</code>",
            ]),
            parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass

    # Mark used
    try:
        await DL.mark_used(token)
    except Exception:
        pass


async def _pm_auto_delete(client, chat_id: int, msg_ids: List[int], seconds: int):
    try:
        await asyncio.sleep(seconds)
        for mid in msg_ids:
            try:
                await client.delete_messages(chat_id, mid)
            except Exception:
                pass
        logger.info(f"[SERIES-H] autodel: deleted {len(msg_ids)} msgs")
    except asyncio.CancelledError:
        return
    except Exception as e:
        logger.debug(f"[SERIES-H] autodel: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 17 — WIZARD RENDERERS
# ═══════════════════════════════════════════════════════════════════════════
async def render_language(
    client: Client, target: Message, uid: int,
) -> None:
    s = sess_get(uid)
    if not s:
        return
    c = s["data"].get("chosen") or {}
    hits = s["data"].get("hits") or []
    chat_id = s["data"].get("chat_id") or target.chat.id

    local: List[str] = []
    for h in hits:
        for l in (h.get("audio_languages") or []):
            n = str(l).strip().title()
            if n and n not in local:
                local.append(n)

    tmdb_langs = c.get("tmdb_langs") or ["English"]

    ordered: List[str] = []
    for l in tmdb_langs:
        if l in local and l not in ordered:
            ordered.append(l)
    for l in tmdb_langs:
        if l not in ordered:
            ordered.append(l)
    for l in local:
        if l not in ordered:
            ordered.append(l)
    if not ordered:
        ordered = ["English", "Hindi", "Tamil", "Telugu", "Malayalam"]

    c["ordered_langs"] = ordered
    c["local_langs"] = local
    sess_set(uid, chosen=c)

    if len(ordered) == 1 and await step_auto_skip(chat_id, "language"):
        sess_set(uid, selected_language=ordered[0])
        return await advance(client, target, uid, "language")

    per_row = await get_per_row(chat_id, "language", 2)
    max_items = await get_max_items(chat_id, "language", 12)

    text = view_languages(c.get("title"), c.get("year"))
    kb = kb_languages(ordered, local, per_row, max_items)
    poster = poster_url(c.get("poster"), "w500")

    await render(client, chat_id, target.id, text, kb, poster)


async def render_season(
    client: Client, target: Message, uid: int,
) -> None:
    s = sess_get(uid)
    if not s:
        return
    c = s["data"].get("chosen") or {}
    hits = s["data"].get("hits") or []
    chat_id = s["data"].get("chat_id") or target.chat.id

    lang = c.get("selected_language")
    filtered = SEARCH.filter_by_language(hits, lang) if lang else list(hits)

    local_seasons: Dict[int, List[int]] = defaultdict(list)
    for h in filtered:
        sn = h.get("season")
        if sn is None:
            continue
        try:
            sn_i = int(sn)
        except (TypeError, ValueError):
            continue
        ep = h.get("episode")
        try:
            ep_i = int(ep) if ep is not None else 0
        except (TypeError, ValueError):
            ep_i = 0
        local_seasons[sn_i].append(ep_i)

    local_map = {k: sorted(set(v)) for k, v in local_seasons.items()}
    tmdb_seasons = c.get("tmdb_seasons") or []

    merged: List[Dict[str, Any]] = []
    seen_sns: Set[int] = set()
    for t in tmdb_seasons:
        try:
            sn = int(t.get("season") or 0)
        except (TypeError, ValueError):
            continue
        if sn <= 0 or sn in seen_sns:
            continue
        seen_sns.add(sn)
        merged.append({
            "season": sn,
            "episodes": int(t.get("episodes") or 0),
        })
    for sn in sorted(local_map.keys()):
        if sn in seen_sns:
            continue
        eps = local_map[sn]
        merged.append({
            "season": sn,
            "episodes": len([e for e in eps if e > 0]),
        })
    merged.sort(key=lambda x: x["season"])

    if not merged:
        return await advance(client, target, uid, "season")

    c["filtered_hits"] = filtered
    c["local_seasons"] = local_map
    c["merged_seasons"] = merged
    sess_set(uid, chosen=c)

    if len(merged) == 1 and await step_auto_skip(chat_id, "season"):
        sess_set(uid, selected_season=merged[0]["season"])
        return await advance(client, target, uid, "season")

    per_row = await get_per_row(chat_id, "season", 1)
    max_items = await get_max_items(chat_id, "season", 15)

    text = view_seasons(c.get("title"), c.get("year"))
    kb = kb_seasons(merged, local_map, per_row, max_items)

    await render(client, chat_id, target.id, text, kb, None)


async def render_episode(
    client: Client, target: Message, uid: int,
) -> None:
    s = sess_get(uid)
    if not s:
        return
    c = s["data"].get("chosen") or {}
    chat_id = s["data"].get("chat_id") or target.chat.id

    season = c.get("selected_season")
    if season is None:
        return await advance(client, target, uid, "episode")

    try:
        season_i = int(season)
    except (TypeError, ValueError):
        return await advance(client, target, uid, "episode")

    filtered = c.get("filtered_hits") or s["data"].get("hits") or []
    season_hits = SEARCH.filter_by_season(filtered, season_i)

    c["files_by_season"] = season_hits or filtered
    sess_set(uid, chosen=c)

    local_eps = SEARCH.unique_episodes(season_hits, season=season_i) or []

    tmdb_eps: List[int] = []
    try:
        title = c.get("title") or ""
        if title:
            tmdb_eps = await STMDB.get_season_episodes(title, season_i) or []
    except Exception as e:
        logger.debug(f"[SERIES-H] tmdb eps: {e}")

    all_eps = sorted(set(int(e) for e in tmdb_eps) | set(int(e) for e in local_eps))
    if not all_eps:
        return await advance(client, target, uid, "episode")

    c["season_episodes"] = all_eps
    c["local_eps"] = local_eps
    sess_set(uid, chosen=c)

    if len(all_eps) == 1 and await step_auto_skip(chat_id, "episode"):
        sess_set(uid, selected_episode=all_eps[0])
        return await advance(client, target, uid, "episode")

    per_row = await get_per_row(chat_id, "episode", 4)
    max_items = await get_max_items(chat_id, "episode", 30)

    text = view_episodes(c.get("title"), season_i, len(season_hits or filtered))
    kb = kb_episodes(all_eps, season_i, local_eps, per_row, max_items)

    await render(client, chat_id, target.id, text, kb, None)


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 17b — QUALITY (v1 UX with user-started gate)
# ═══════════════════════════════════════════════════════════════════════════
async def render_quality(
    client: Client, target: Message, uid: int,
) -> None:
    s = sess_get(uid)
    if not s:
        return
    c = s["data"].get("chosen") or {}
    chat_id = s["data"].get("chat_id") or target.chat.id

    title = c.get("title") or "?"
    season = c.get("selected_season")
    episode = c.get("selected_episode")
    language = c.get("selected_language") or ""

    # ── Resolve file list ──
    files = c.get("files_by_season")
    if not files:
        filtered = c.get("filtered_hits") or s["data"].get("hits") or []
        if season is not None:
            try:
                files = SEARCH.filter_by_season(filtered, int(season))
            except Exception:
                files = filtered
        else:
            files = filtered
        if not files:
            files = s["data"].get("hits") or []
        c["files_by_season"] = files
        sess_set(uid, chosen=c)

    # Narrow by episode if selected
    if episode is not None:
        try:
            ep_i = int(episode)
            ep_files = SEARCH.filter_by_episode(files, ep_i)
            if ep_files:
                files = ep_files
        except (TypeError, ValueError):
            pass

    # ── Extract qualities ──
    quals = SEARCH.unique_qualities(files) if files else []

    if not quals and files:
        raw_quals = set()
        for f in files:
            q = f.get("quality")
            if q and str(q).strip().upper() not in ("", "NONE", "UNKNOWN"):
                raw_quals.add(str(q).strip())
        if raw_quals:
            quals = sorted(list(raw_quals))
        else:
            quals = ["Original"]

    if not quals:
        quals = ["Original"]

    c["available_qualities"] = quals
    c["files_for_quality"] = files
    sess_set(uid, chosen=c)

    if len(quals) == 1 and await step_auto_skip(chat_id, "quality"):
        sess_set(uid, selected_quality=quals[0])
        return await advance(client, target, uid, "quality")

    # ── Force-sub gate ──
    ok, missing = await check_fsub(client, uid, chat_id)
    if not ok:
        kb = await kb_fsub(client, missing)
        return await render(
            client, chat_id, target.id,
            "\n".join([
                f"{F.EMO['brand']} <b>{fb('DOWNTOWN VILLA')}</b>",
                f"⚠️ <b>{fb('JOIN CHANNELS FIRST')}</b>",
                DIV, "",
                f"📌 {sc('please join the channels below')}",
                f"📌 {sc('then try again')}",
            ]),
            kb, None,
        )

    # ── Bot username for deep links ──
    bot_username = ""
    try:
        me = await client.identity()
        bot_username = me.username or ""
    except Exception:
        try:
            me = await client.get_me()
            bot_username = me.username or ""
        except Exception:
            bot_username = ""

    if not bot_username:
        bot_username = str(getattr(CFG, "BOT_USERNAME", "") or "").lstrip("@")

    if not bot_username:
        sess_drop(uid)
        return await render(
            client, chat_id, target.id,
            "\n".join([
                f"{F.EMO['brand']} <b>{fb('DOWNTOWN VILLA')}</b>",
                f"⚠️ <b>{fb('BOT CONFIGURATION ERROR')}</b>",
                DIV, "",
                f"📌 {sc('bot username is missing — please contact admin')}",
            ]),
            None, None,
        )

    season_i = int(season) if season is not None else 0

    # ── Check if user has started the bot ──
    started = await user_started_bot(uid)
    logger.info(f"[SERIES-H] quality: uid={uid} started={started}")

    # ═══════════════════════════════════════════════════════════════════════
    # CASE A — USER ALREADY STARTED BOT
    #           Show each quality as a direct deep-link button → PM
    # ═══════════════════════════════════════════════════════════════════════
    if started:
        qual_items: List[Tuple[str, str]] = []
        for q in quals:
            q_up = str(q).upper()
            if q_up == "ORIGINAL":
                matching = list(files)
            else:
                matching = [
                    f for f in files
                    if str(f.get("quality") or "").upper() == q_up
                ]
                if not matching:
                    matching = [
                        f for f in files
                        if not f.get("quality")
                        or str(f.get("quality")).upper() == "UNKNOWN"
                    ]
                if not matching:
                    matching = list(files)

            matching = _dedupe_episodes(matching)

            token = await DL.create_deliver_token(
                user_id=uid, chat_id=chat_id,
                title=title, season=season_i,
                quality=str(q), language=str(language),
                hits=matching,
            )
            if token:
                deep_link = f"https://t.me/{bot_username}?start=deliver_{token}"
                qual_items.append((str(q), deep_link))

        if not qual_items:
            return await render(
                client, chat_id, target.id,
                "\n".join([
                    f"{F.EMO['brand']} <b>{fb('DOWNTOWN VILLA')}</b>",
                    f"❌ <b>{fb('NO FILES AVAILABLE')}</b>",
                    DIV, "",
                    f"📌 {sc('unable to package files for delivery')}",
                ]),
                InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        "❌ CLOSE", callback_data="sg:close",
                    ),
                ]]),
                None,
            )

        per_row = await get_per_row(chat_id, "quality", 2)
        max_items = await get_max_items(chat_id, "quality", 12)

        text = view_qualities(title, season_i, len(files))
        kb = kb_qualities(qual_items, per_row, max_items)

        await render(client, chat_id, target.id, text, kb, None)
        logger.info(
            f"[SERIES-H] quality screen (existing user) "
            f"uid={uid} quals={[q for q, _ in qual_items]}"
        )
        return

    # ═══════════════════════════════════════════════════════════════════════
    # CASE B — USER NEVER STARTED BOT
    #           Show "START BOT FIRST" card with single button
    # ═══════════════════════════════════════════════════════════════════════
    default_quality = quals[0]  # highest-ranked
    q_up = str(default_quality).upper()

    if q_up == "ORIGINAL":
        matching = list(files)
    else:
        matching = [
            f for f in files
            if str(f.get("quality") or "").upper() == q_up
        ]
        if not matching:
            matching = [
                f for f in files
                if not f.get("quality")
                or str(f.get("quality")).upper() == "UNKNOWN"
            ]
        if not matching:
            matching = list(files)

    matching = _dedupe_episodes(matching)

    token = await DL.create_deliver_token(
        user_id=uid, chat_id=chat_id,
        title=title, season=season_i,
        quality=str(default_quality),
        language=str(language),
        hits=matching,
    )

    if not token:
        return await render(
            client, chat_id, target.id,
            "\n".join([
                f"{F.EMO['brand']} <b>{fb('DOWNTOWN VILLA')}</b>",
                f"❌ <b>{fb('ERROR')}</b>",
                DIV, "",
                f"📌 {sc('please try again')}",
            ]),
            InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ CLOSE", callback_data="sg:close"),
            ]]),
            None,
        )

    deep_link = f"https://t.me/{bot_username}?start=deliver_{token}"

    text = view_start_bot_first(
        title, season_i, str(default_quality), len(matching),
    )
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"{F.EMO['rocket']} {sc('START BOT & GET FILES')}",
            url=deep_link,
        )],
        [InlineKeyboardButton(
            "❌ CLOSE", callback_data="sg:close",
        )],
    ])

    await render(client, chat_id, target.id, text, kb, None)
    logger.info(
        f"[SERIES-H] start-bot card uid={uid} "
        f"default_q={default_quality} files={len(matching)}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 18 — DELIVERY (fallback — only triggered if quality step disabled)
# ═══════════════════════════════════════════════════════════════════════════
async def deliver_to_pm(
    client: Client, target: Message, uid: int,
) -> None:
    s = sess_get(uid)
    if not s:
        return
    c = s["data"].get("chosen") or {}
    chat_id = s["data"].get("chat_id") or target.chat.id

    title = c.get("title") or "?"
    season = c.get("selected_season") or 0
    quality = c.get("selected_quality") or "UNKNOWN"
    language = c.get("selected_language") or ""

    try:
        season_i = int(season)
    except (TypeError, ValueError):
        season_i = 0

    files = c.get("files_for_quality") or c.get("files_by_season") or []

    final: List[Dict[str, Any]] = []
    q_up = str(quality).upper()
    for f in files:
        f_q = str(f.get("quality") or "").upper()
        if f_q == q_up:
            final.append(f)
    if not final:
        final = [
            f for f in files
            if not f.get("quality")
            or str(f.get("quality")).upper() == "UNKNOWN"
        ]
    if not final:
        final = list(files)

    final = _dedupe_episodes(final)
    final.sort(key=lambda x: (int(x.get("episode") or 0)))

    if not final:
        return await render(
            client, chat_id, target.id,
            "\n".join([
                f"{F.EMO['brand']} <b>{fb('DOWNTOWN VILLA')}</b>",
                f"❌ <b>{fb('NO FILES')}</b>",
                DIV, "",
                f"📌 {sc('please try a different quality')}",
            ]),
            InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ CLOSE", callback_data="sg:close"),
            ]]),
            None,
        )

    ok, missing = await check_fsub(client, uid, chat_id)
    if not ok:
        kb = await kb_fsub(client, missing)
        return await render(
            client, chat_id, target.id,
            "\n".join([
                f"{F.EMO['brand']} <b>{fb('DOWNTOWN VILLA')}</b>",
                f"⚠️ <b>{fb('JOIN CHANNELS FIRST')}</b>",
                DIV, "",
                f"📌 {sc('please join the channels below')}",
                f"📌 {sc('then try again')}",
            ]),
            kb, None,
        )

    token = await DL.create_deliver_token(
        user_id=uid, chat_id=chat_id,
        title=title, season=season_i,
        quality=str(quality), language=str(language),
        hits=final,
    )
    if not token:
        return await render(
            client, chat_id, target.id,
            "\n".join([
                f"{F.EMO['brand']} <b>{fb('DOWNTOWN VILLA')}</b>",
                f"❌ <b>{fb('ERROR')}</b>",
                DIV, "",
                f"📌 {sc('please try again')}",
            ]),
            InlineKeyboardMarkup([[
                InlineKeyboardButton("❌ CLOSE", callback_data="sg:close"),
            ]]),
            None,
        )

    bot_username = ""
    try:
        me = await client.identity()
        bot_username = me.username or ""
    except Exception:
        try:
            me = await client.get_me()
            bot_username = me.username or ""
        except Exception:
            bot_username = ""

    if not bot_username:
        bot_username = str(getattr(CFG, "BOT_USERNAME", "") or "").lstrip("@")

    if not bot_username:
        sess_drop(uid)
        return await render(
            client, chat_id, target.id,
            "\n".join([
                f"{F.EMO['brand']} <b>{fb('DOWNTOWN VILLA')}</b>",
                f"⚠️ <b>{fb('BOT USERNAME MISSING')}</b>",
                DIV, "",
                f"📌 {sc('contact admin — bot misconfigured')}",
            ]),
            None, None,
        )

    deep_link = f"https://t.me/{bot_username}?start=deliver_{token}"

    await render(
        client, chat_id, target.id,
        view_redirecting(title, season_i, quality, len(final)),
        InlineKeyboardMarkup([[
            InlineKeyboardButton("🚀 OPEN BOT PM", url=deep_link),
        ]]),
        None,
    )

    logger.info(
        f"[SERIES-H] redirect uid={uid} S{season_i:02d} "
        f"q={quality} files={len(final)} token={token}"
    )

    sess_drop(uid)


def _dedupe_episodes(files: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_ep: Dict[Tuple[int, int], Dict[str, Any]] = {}
    no_ep: List[Dict[str, Any]] = []
    for f in files:
        ep = f.get("episode")
        sn = f.get("season")
        if ep is None:
            no_ep.append(f)
            continue
        try:
            ep_i = int(ep)
        except (TypeError, ValueError):
            no_ep.append(f)
            continue
        try:
            sn_i = int(sn) if sn is not None else 0
        except (TypeError, ValueError):
            sn_i = 0
        key = (sn_i, ep_i)
        cur = by_ep.get(key)
        try:
            size = int(f.get("file_size") or 0)
        except (TypeError, ValueError):
            size = 0
        if cur is None:
            by_ep[key] = f
        else:
            try:
                cur_size = int(cur.get("file_size") or 0)
            except (TypeError, ValueError):
                cur_size = 0
            if size and (cur_size == 0 or size < cur_size):
                by_ep[key] = f
    out = list(by_ep.values())
    out.extend(no_ep)
    return out


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 19 — CALLBACKS: SUGGESTIONS
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^sg:pick:(\d+)$"), group=-9999)
async def cb_pick(client: Client, q: CallbackQuery):
    try:
        idx = int(q.matches[0].group(1))
        uid = q.from_user.id
        s = sess_get(uid)
        if not s:
            return await q.answer("⏱️ session expired", show_alert=True)

        items = s["data"].get("suggestions") or []
        if idx >= len(items):
            return await q.answer("⚠️ invalid", show_alert=True)

        chosen = items[idx]
        tmdb_id = chosen.get("tmdb_id")
        title = chosen.get("title") or ""
        year = chosen.get("year") or ""
        poster = chosen.get("poster")

        await q.answer("🔍 loading…")

        # ── Step 1: search DB with the suggestion title ──
        db_match = await smart_db_search(title)

        # ── Step 2: no DB hit → post request + show Start Bot card ──
        if not db_match:
            logger.info(
                f"[SERIES-H] suggestion click → no DB match: {title!r}"
            )

            token = await post_to_request_channel(
                client, uid, title,
                year=year or None, tmdb_id=tmdb_id,
                source="suggestion_not_in_db",
            )

            # Get bot username for the Start button
            bot_username = ""
            try:
                me = await client.identity()
                bot_username = me.username or ""
            except Exception:
                try:
                    me = await client.get_me()
                    bot_username = me.username or ""
                except Exception:
                    bot_username = ""
            if not bot_username:
                bot_username = str(
                    getattr(CFG, "BOT_USERNAME", "") or ""
                ).lstrip("@")

            already = await user_started_bot(uid)
            rows: List[List[InlineKeyboardButton]] = []
            if bot_username and not already:
                start_link = f"https://t.me/{bot_username}?start=start"
                rows.append([InlineKeyboardButton(
                    f"{F.EMO['rocket']} {sc('START BOT FOR UPDATES')}",
                    url=start_link,
                )])
            rows.append([InlineKeyboardButton(
                "❌ CLOSE", callback_data="sg:close",
            )])

            await render(
                client, q.message.chat.id, q.message.id,
                view_no_files_card(title, year),
                InlineKeyboardMarkup(rows),
                None,
            )

            logger.info(
                f"[SERIES-H] request posted · uid={uid} "
                f"title={title!r} req_token={token or 'FAILED'}"
            )
            return

        # ── Step 3: DB hit → start the wizard ──
        matched_title = db_match["matched_title"]
        hits = db_match["hits"]
        logger.info(
            f"[SERIES-H] suggestion click → DB match {matched_title!r} "
            f"({len(hits)} hits)"
        )

        chosen_data = await enrich_with_tmdb(
            matched_title, hits,
            tmdb_id_override=tmdb_id if tmdb_id else None,
            poster_override=poster,
            year_override=year or None,
        )

        sess_set(
            uid,
            chosen=chosen_data,
            hits=hits,
            raw_query=title,
        )

        chat_id = s["data"].get("chat_id") or q.message.chat.id
        steps = await wizard_steps(chat_id)
        first = steps[0] if steps else "language"
        await goto_step(client, q.message, uid, first)
        await q.answer()
    except Exception as e:
        logger.exception(f"[SERIES-H] cb_pick: {e}")
        try:
            await q.answer("⚠️ error", show_alert=True)
        except Exception:
            pass


@Client.on_callback_query(filters.regex(r"^sg:request$"), group=-9999)
async def cb_request(client: Client, q: CallbackQuery):
    try:
        s = sess_get(q.from_user.id)
        if not s:
            return await q.answer("⏱️ expired", show_alert=True)
        raw = s["data"].get("raw_query") or ""
        await q.answer("📩 sending…")
        token = await post_to_request_channel(
            client, q.from_user.id, raw,
            source="series_manual_request",
        )
        if token:
            await render(
                client, q.message.chat.id, q.message.id,
                "\n".join([
                    f"{F.EMO['brand']} <b>{fb('DOWNTOWN VILLA')}</b>",
                    f"✅ <b>{fb('REQUEST SENT')}</b>",
                    DIV, "",
                    f"🎬 <b>{esc(raw)}</b>",
                    "",
                    f"📌 {sc('admin will review soon')}",
                ]),
                InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ CLOSE",
                                          callback_data="sg:close"),
                ]]),
                None,
            )
    except Exception as e:
        logger.exception(f"[SERIES-H] cb_request: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 20 — CALLBACKS: LANGUAGE
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^sg:lang:(\d+)$"), group=-9999)
async def cb_lang(client: Client, q: CallbackQuery):
    try:
        idx = int(q.matches[0].group(1))
        uid = q.from_user.id
        s = sess_get(uid)
        if not s:
            return await q.answer("⏱️ expired", show_alert=True)

        c = s["data"].get("chosen") or {}
        ordered = c.get("ordered_langs") or []
        if idx >= len(ordered):
            return await q.answer("⚠️ invalid", show_alert=True)

        lang = ordered[idx]
        c["selected_language"] = lang
        sess_set(uid, chosen=c)

        await q.answer(f"🌍 {lang}")
        await advance(client, q.message, uid, "language")
    except Exception as e:
        logger.exception(f"[SERIES-H] cb_lang: {e}")
        try:
            await q.answer("⚠️ error", show_alert=True)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 21 — CALLBACKS: SEASON
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^sg:seas:(\d+)$"), group=-9999)
async def cb_seas(client: Client, q: CallbackQuery):
    try:
        idx = int(q.matches[0].group(1))
        uid = q.from_user.id
        s = sess_get(uid)
        if not s:
            return await q.answer("⏱️ expired", show_alert=True)

        c = s["data"].get("chosen") or {}
        merged = c.get("merged_seasons") or []
        if idx >= len(merged):
            return await q.answer("⚠️ invalid", show_alert=True)

        season = int(merged[idx]["season"])
        c["selected_season"] = season

        filtered = c.get("filtered_hits") or s["data"].get("hits") or []
        try:
            c["files_by_season"] = SEARCH.filter_by_season(filtered, season)
        except Exception:
            c["files_by_season"] = filtered

        sess_set(uid, chosen=c)

        await q.answer(f"📺 Season {season:02d}")
        await advance(client, q.message, uid, "season")
    except Exception as e:
        logger.exception(f"[SERIES-H] cb_seas: {e}")
        try:
            await q.answer("⚠️ error", show_alert=True)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 22 — CALLBACKS: EPISODE
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^sg:ep:(\d+)$"), group=-9999)
async def cb_ep(client: Client, q: CallbackQuery):
    try:
        ep = int(q.matches[0].group(1))
        uid = q.from_user.id
        s = sess_get(uid)
        if not s:
            return await q.answer("⏱️ expired", show_alert=True)

        c = s["data"].get("chosen") or {}
        c["selected_episode"] = ep
        sess_set(uid, chosen=c)

        await q.answer(f"🎞️ E{ep:02d}")
        await advance(client, q.message, uid, "episode")
    except Exception as e:
        logger.exception(f"[SERIES-H] cb_ep: {e}")
        try:
            await q.answer("⚠️ error", show_alert=True)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 23 — CALLBACKS: QUALITY
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^sg:qual:(\d+)$"), group=-9999)
async def cb_qual(client: Client, q: CallbackQuery):
    try:
        idx = int(q.matches[0].group(1))
        uid = q.from_user.id
        s = sess_get(uid)
        if not s:
            return await q.answer("⏱️ expired", show_alert=True)

        c = s["data"].get("chosen") or {}
        quals = c.get("available_qualities") or []
        if idx >= len(quals):
            return await q.answer("⚠️ invalid", show_alert=True)

        quality = quals[idx]
        c["selected_quality"] = quality
        sess_set(uid, chosen=c)

        await q.answer("🚀")
        await advance(client, q.message, uid, "quality")
    except Exception as e:
        logger.exception(f"[SERIES-H] cb_qual: {e}")
        try:
            await q.answer("⚠️ error", show_alert=True)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 24 — CALLBACKS: FSUB / BACK / CLOSE
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^sg:fsub_check$"), group=-9999)
async def cb_fsub_check(client: Client, q: CallbackQuery):
    try:
        chat_id = q.message.chat.id
        ok, missing = await check_fsub(client, q.from_user.id, chat_id)
        if ok:
            await q.answer("✅ verified! try again", show_alert=True)
            try:
                await q.message.delete()
            except Exception:
                pass
        else:
            await q.answer("❌ still missing channels", show_alert=True)
    except Exception as e:
        logger.debug(f"[SERIES-H] fsub_check: {e}")


@Client.on_callback_query(filters.regex(r"^sg:back_sugg$"), group=-9999)
async def cb_back_sugg(client: Client, q: CallbackQuery):
    s = sess_get(q.from_user.id)
    if not s:
        return await q.answer("⏱️ expired", show_alert=True)
    items = s["data"].get("suggestions") or []
    raw = s["data"].get("raw_query") or ""
    if not items:
        return await q.answer("⚠️ no suggestions", show_alert=True)
    await render(
        client, q.message.chat.id, q.message.id,
        view_suggestions(raw, items),
        kb_suggestions(items),
        None,
    )
    await q.answer()


@Client.on_callback_query(filters.regex(r"^sg:back_lang$"), group=-9999)
async def cb_back_lang(client: Client, q: CallbackQuery):
    await render_language(client, q.message, q.from_user.id)
    await q.answer()


@Client.on_callback_query(filters.regex(r"^sg:back_seas$"), group=-9999)
async def cb_back_seas(client: Client, q: CallbackQuery):
    await render_season(client, q.message, q.from_user.id)
    await q.answer()


@Client.on_callback_query(filters.regex(r"^sg:back_ep$"), group=-9999)
async def cb_back_ep(client: Client, q: CallbackQuery):
    await render_episode(client, q.message, q.from_user.id)
    await q.answer()


@Client.on_callback_query(filters.regex(r"^sg:close$"), group=-9999)
async def cb_close(client: Client, q: CallbackQuery):
    sess_drop(q.from_user.id)
    try:
        await q.message.delete()
    except Exception:
        pass
    await q.answer("closed")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 25 — REQUEST CHANNEL ADMIN CALLBACKS
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_callback_query(filters.regex(r"^gsreq:"), group=-9999)
async def cb_gsreq(client: Client, q: CallbackQuery):
    try:
        _, token, action = q.data.split(":", 2)
    except Exception:
        return await q.answer("❌ invalid", show_alert=True)

    if not is_admin(q.from_user.id):
        try:
            m = await client.get_chat_member(
                q.message.chat.id, q.from_user.id,
            )
            st = getattr(m, "status", None)
            st = st.name.lower() if hasattr(st, "name") else str(st).lower()
            if st not in ("administrator", "creator", "owner"):
                return await q.answer("⛔ admins only", show_alert=True)
        except Exception:
            return await q.answer("⛔ admins only", show_alert=True)

    req = await get_request(token)
    if not req:
        return await q.answer("⚠️ not found", show_alert=True)

    user_id = req.get("user_id")
    title = req.get("movie_name") or ""
    year = req.get("year")

    messages = {
        "updated": (
            f"🎬 <b>{sc('good news!')}</b>\n\n"
            f"ʏᴏᴜʀ ʀᴇǫᴜᴇꜱᴛ <b>{esc(title)}</b> ʜᴀꜱ ʙᴇᴇɴ ᴜᴘʟᴏᴀᴅᴇᴅ ✅\n\n"
            f"ᴛᴀᴘ ᴛʜᴇ ʙᴜᴛᴛᴏɴ ʙᴇʟᴏᴡ ᴛᴏ ɢᴇᴛ ɪᴛ."
        ),
        "notreleased": (
            f"📅 <b>{sc('not released yet')}</b>\n\n"
            f"<b>{esc(title)}</b> ʜᴀꜱ ɴᴏᴛ ʙᴇᴇɴ ʀᴇʟᴇᴀꜱᴇᴅ ʏᴇᴛ."
        ),
        "notfound": (
            f"🔎 <b>{sc('not found')}</b>\n\n"
            f"ᴡᴇ ᴄᴏᴜʟᴅɴ'ᴛ ꜰɪɴᴅ <b>{esc(title)}</b>."
        ),
        "cancel": (
            f"❌ <b>{sc('cancelled')}</b>\n\n"
            f"ʏᴏᴜʀ ʀᴇǫᴜᴇꜱᴛ <b>{esc(title)}</b> ʜᴀꜱ ʙᴇᴇɴ ᴄᴀɴᴄᴇʟʟᴇᴅ."
        ),
    }
    icons = {
        "updated": "📺 SERIES UPDATED ✅",
        "notreleased": "📅 NOT RELEASED",
        "notfound": "🔎 NOT FOUND",
        "cancel": "❌ CANCELLED",
    }

    if user_id:
        try:
            kb_rows: List[List[InlineKeyboardButton]] = []
            if action == "updated" and title:
                b64t = b64e(title)
                b64y = b64e(str(year) if year else "")
                kb_rows.append([InlineKeyboardButton(
                    f"🔍 SEARCH · {title[:40]}",
                    callback_data=f"greqsearch:{b64t}:{b64y}",
                )])
            kb_rows.append([InlineKeyboardButton(
                "📢 UPDATES", url=UPDATE_CHNL_LNK)])
            await client.send_message(
                chat_id=user_id,
                text=messages.get(action, "✅ status updated"),
                reply_markup=InlineKeyboardMarkup(kb_rows),
                parse_mode=ParseMode.HTML,
            )
            logger.info(f"[SERIES-H] notified {user_id} · {action}")
        except UserIsBlocked:
            logger.info("[SERIES-H] user blocked")
        except Exception as e:
            logger.warning(f"[SERIES-H] DM fail: {e}")

    await update_request(token, action)

    try:
        original = q.message.text or q.message.caption or ""
        await q.message.edit_text(
            f"<b><strike>{original}</strike></b>\n\n"
            f"<b>{icons.get(action, '✅ DONE')}</b>",
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        logger.debug(f"[SERIES-H] edit req msg: {e}")

    await q.answer(f"✅ {action}")


@Client.on_callback_query(filters.regex(r"^greqsearch:"), group=-9999)
async def cb_greq_search(client: Client, q: CallbackQuery):
    try:
        parts = q.data.split(":", 2)
        if len(parts) < 3:
            return await q.answer("❌ invalid", show_alert=True)
        _, b64t, b64y = parts
        title = b64d(b64t)
        year = b64d(b64y) or ""
        if not title:
            return await q.answer("❌ error", show_alert=True)

        uid = q.from_user.id
        logger.info(f"[SERIES-H] req search {title!r} for {uid}")

        await q.answer("🔍 searching…")

        db_match = await smart_db_search(title)

        if not db_match:
            await q.message.edit_text(
                "\n".join([
                    f"{F.EMO['brand']} <b>{fb('DOWNTOWN VILLA')}</b>",
                    f"⏳ <b>{fb('STILL NOT AVAILABLE')}</b>",
                    DIV, "",
                    f"🎬 <b>{esc(title)}</b>"
                    + (f" ({year})" if year else ""),
                    "",
                    f"📌 {sc('the files are being processed')}",
                    f"📌 {sc('try again in a few minutes')}",
                ]),
                reply_markup=InlineKeyboardMarkup([[
                    InlineKeyboardButton("❌ CLOSE",
                                          callback_data="sg:close"),
                ]]),
                parse_mode=ParseMode.HTML,
            )
            return

        matched_title = db_match["matched_title"]
        hits = db_match["hits"]
        chosen = await enrich_with_tmdb(
            matched_title, hits,
            year_override=year or None,
        )

        sess_new(
            uid, q.message.chat.id,
            suggestions=[], raw_query=title,
            chosen=chosen, hits=hits,
        )

        chat_id = q.message.chat.id
        steps = await wizard_steps(chat_id)
        first = steps[0] if steps else "language"
        await goto_step(client, q.message, uid, first)
    except Exception as e:
        logger.exception(f"[SERIES-H] greqsearch: {e}")
        try:
            await q.answer("⚠️ error", show_alert=True)
        except Exception:
            pass


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 26 — PM /start HANDLER
# ═══════════════════════════════════════════════════════════════════════════
@Client.on_message(
    filters.command("start") & filters.private,
    group=-9998,
)
async def pm_start_fallback(client: Client, message: Message):
    try:
        if not message.from_user:
            return
        cmd = getattr(message, "command", None) or []
        if len(cmd) < 2:
            return
        payload = str(cmd[1] or "")
        if payload.startswith(("deliver_", "prem_", "file_",
                                "req_", "gs_", "ref_", "wo_")):
            return
        try:
            message.stop_propagation()
        except Exception:
            pass
        await message.reply_text(
            "\n".join([
                f"{F.EMO['brand']} <b>{fb('DOWNTOWN VILLA')}</b>",
                DIV, "",
                f"📌 {sc('search for series in the series group')}",
                f"📌 {sc('files will arrive here in pm')}",
            ]),
            parse_mode=ParseMode.HTML,
        )
    except Exception as e:
        logger.debug(f"[SERIES-H] pm start: {e}")


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 27 — CLEANUP LOOP
# ═══════════════════════════════════════════════════════════════════════════
async def _cleanup_loop():
    while True:
        try:
            await asyncio.sleep(300)
            cleanup_sessions()
            cleanup_cooldown()
        except asyncio.CancelledError:
            return
        except Exception:
            pass


try:
    asyncio.get_event_loop().create_task(_cleanup_loop())
except Exception:
    pass


# ═══════════════════════════════════════════════════════════════════════════
# SECTION 28 — SNAPSHOT
# ═══════════════════════════════════════════════════════════════════════════
def snapshot() -> Dict[str, Any]:
    return {
        "module": "groups.series.handler (v1 UX · v2 power)",
        "sessions": len(_SESSIONS),
        "cooldowns": len(_last_seen),
        "group_id": SERIES_GROUP_ID,
        "enabled": SERIES_GROUP_ENABLED,
        "reqst_channel": bool(REQST_CHANNEL),
    }


__all__ = [
    "series_group_search",
    "render_language", "render_season",
    "render_episode", "render_quality",
    "deliver_to_pm",
    "goto_step", "advance",
    "cb_pick", "cb_request",
    "cb_lang", "cb_seas", "cb_ep", "cb_qual",
    "cb_fsub_check",
    "cb_back_sugg", "cb_back_lang",
    "cb_back_seas", "cb_back_ep",
    "cb_close",
    "cb_gsreq", "cb_greq_search",
    "pm_start_fallback",
    "smart_db_search", "enrich_with_tmdb",
    "post_to_request_channel", "get_request", "update_request",
    "check_fsub", "kb_fsub",
    "user_started_bot",
    "snapshot",
]
