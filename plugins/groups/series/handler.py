# plugins/groups/series/handler.py
# ============================================================
# 🏨 DOWNTOWN VILLA — SERIES GROUP HANDLER (v1 UX · v2 backend)
# ============================================================
# Search → Suggestions → Language → Season → Quality → PM
# No episode picker. No spell-check step.
# Admin panel (state.py, panel.py, flow) still applies layout.
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
from typing import Any, Dict, List, Optional, Set

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.errors import FloodWait, MessageNotModified, UserIsBlocked
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

try:
    from database import db_manager as DB_MANAGER
except Exception:
    DB_MANAGER = None

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════════════════
IST = timezone(timedelta(hours=5, minutes=30))

def _resolve_group_id() -> Optional[int]:
    gid = getattr(CFG, "SERIES_GROUP_ID", None)
    if gid:
        try:
            return int(gid)
        except (TypeError, ValueError):
            pass
    try:
        env = int(os.getenv("SERIES_GROUP_ID", "0") or 0)
        return env or None
    except (TypeError, ValueError):
        return None

SERIES_GROUP_ID = _resolve_group_id()
SERIES_GROUP_ENABLED = os.getenv("SERIES_GROUP_ENABLED", "true").lower() in \
                       ("1", "true", "yes", "on")

REQST_CHANNEL = getattr(CFG, "REQST_CHANNEL", None) or None
UPDATE_CHNL_LNK = getattr(CFG, "UPDATE_CHNL_LNK", None) or "https://t.me/"
ADMINS = list(getattr(CFG, "ADMINS", []) or [])

SESSION_TTL = 900
MIN_QUERY_LEN = 2
MAX_QUERY_LEN = 100

DIV = F.DIV
DIV_S = F.DIV_S

# ═══════════════════════════════════════════════════════════════════════════
# SESSION STORE
# ═══════════════════════════════════════════════════════════════════════════
_SESSIONS: Dict[int, Dict[str, Any]] = {}


def _new_session(uid: int, **data) -> None:
    _SESSIONS[int(uid)] = {
        "data": data,
        "expires": time.time() + SESSION_TTL,
    }


def _get_session(uid: int) -> Optional[Dict[str, Any]]:
    s = _SESSIONS.get(int(uid))
    if not s:
        return None
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


# ═══════════════════════════════════════════════════════════════════════════
# SMALL HELPERS
# ═══════════════════════════════════════════════════════════════════════════
def fb(s: Any) -> str: return F.fb(str(s))
def sc(s: Any) -> str: return F.sc(str(s))


def _esc(t: Any) -> str:
    if t is None: return ""
    return str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _b64e(s: str) -> str:
    try: return base64.urlsafe_b64encode(s.encode()).decode().rstrip("=")
    except Exception: return ""


def _b64d(s: str) -> str:
    try:
        pad = "=" * (4 - len(s) % 4)
        return base64.urlsafe_b64decode((s + pad).encode()).decode()
    except Exception: return ""


def _is_admin(uid: Any) -> bool:
    try:
        return int(uid) in [int(a) for a in ADMINS]
    except Exception:
        return False


def _poster_url(path: Any, size: str = "w500") -> Optional[str]:
    if not path: return None
    s = str(path)
    if s.startswith("http://") or s.startswith("https://"):
        return s
    try:
        return STMDB.poster_url(s, size)
    except Exception:
        return f"https://image.tmdb.org/t/p/{size}{s}"


def _summarize_hits(hits: List[Dict[str, Any]]) -> Dict[str, Any]:
    langs: Set[str] = set()
    seasons: Dict[int, Set[int]] = defaultdict(set)
    for h in hits:
        for l in (h.get("audio_languages") or []):
            n = str(l).strip().title()
            if n: langs.add(n)
        sn = h.get("season"); ep = h.get("episode")
        if sn is None: continue
        try: sn_i = int(sn)
        except (TypeError, ValueError): continue
        try: ep_i = int(ep) if ep is not None else 0
        except (TypeError, ValueError): ep_i = 0
        seasons[sn_i].add(ep_i)
    return {
        "languages": sorted(langs),
        "seasons": {k: sorted(v) for k, v in seasons.items()},
    }


# ═══════════════════════════════════════════════════════════════════════════
# READ FLOW LAYOUT FROM ADMIN PANEL
# ═══════════════════════════════════════════════════════════════════════════
async def _per_row(chat_id: int, key: str, default: int = 2) -> int:
    try:
        n = await SFLOW.get_per_row(chat_id, key)
        if n: return int(n)
    except Exception:
        pass
    return default


async def _max_items(chat_id: int, key: str, default: int = 12) -> int:
    try:
        n = await SFLOW.get_max_items(chat_id, key, default)
        if n: return int(n)
    except Exception:
        pass
    return default


# ═══════════════════════════════════════════════════════════════════════════
# VIEWS
# ═══════════════════════════════════════════════════════════════════════════
def _view_suggestions(raw: str, items: List[Dict[str, Any]]) -> str:
    lines = [
        f"{F.EMO['brand']} <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🎬 <b>{fb('SERIES SUGGESTIONS')}</b>",
        DIV, "",
        f"🔍 {sc('you searched')} · <code>{_esc(raw)}</code>",
        "", f"📌 {sc('pick the series you meant')}",
        "", DIV_S, "",
    ]
    for i, it in enumerate(items, 1):
        title = (it.get("title") or "?").strip().upper()
        rating = it.get("rating") or 0
        line = f"<b>{i}.</b> <b>{_esc(title)}</b>"
        try:
            if rating: line += f" · ⭐ {float(rating):.1f}"
        except (TypeError, ValueError):
            pass
        lines.append(line)
    lines += [
        "", DIV_S,
        f"💡 {sc('not what you wanted?')} · ᴛᴀᴘ ʀᴇǫᴜᴇꜱᴛ ʙᴜᴛᴛᴏɴ",
    ]
    return "\n".join(lines)


def _view_languages(title: str, year: Any) -> str:
    yr = f" ({year})" if year else ""
    return "\n".join([
        f"{F.EMO['brand']} <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🎬 <b>{_esc(title)}</b>{yr}",
        DIV, "",
        f"🌍 {sc('pick language')}",
        "",
        f"🟢 {sc('has files')} · ⚪ {sc('tmdb only')}",
    ])


def _view_seasons(title: str, year: Any) -> str:
    yr = f" ({year})" if year else ""
    return "\n".join([
        f"{F.EMO['brand']} <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🎬 <b>{_esc(title)}</b>{yr}",
        DIV, "",
        f"📺 {sc('pick season')}",
        "",
        f"🟢 ꜰᴜʟʟ · 🟡 ᴘᴀʀᴛɪᴀʟ · ⚪ ɴᴏ ꜰɪʟᴇꜱ",
    ])


def _view_qualities(title: str, season: int, count: int) -> str:
    return "\n".join([
        f"{F.EMO['brand']} <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🎬 <b>{_esc(title)}</b>",
        f"📺 <b>Season {int(season):02d}</b>",
        DIV, "",
        f"🎯 {sc('pick quality')}",
        "",
        f"📁 <code>{count}</code> ꜰɪʟᴇꜱ ᴛᴏ ꜱᴇɴᴅ",
        f"📩 {sc('files will go to your pm')}",
    ])


def _view_redirecting(title: str, season: int, quality: str, count: int) -> str:
    return "\n".join([
        f"{F.EMO['brand']} <b>{fb('DOWNTOWN VILLA')}</b>",
        f"🚀 <b>{fb('REDIRECTING TO PM')}</b>",
        DIV, "",
        f"🎬 <b>{_esc(title)}</b>",
        f"📺 <b>Season {int(season):02d}</b>",
        f"🎯 <code>{_esc(quality)}</code>",
        "",
        f"📁 <code>{count}</code> ᴇᴘɪꜱᴏᴅᴇꜱ",
        "",
        f"📌 {sc('bot will open in pm')}",
        f"📌 {sc('files will be delivered there')}",
    ])


# ═══════════════════════════════════════════════════════════════════════════
# KEYBOARDS
# ═══════════════════════════════════════════════════════════════════════════
def _kb_suggestions(items: List[Dict[str, Any]]) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    for i, it in enumerate(items):
        title = (it.get("title") or "?").strip().upper()
        rating = it.get("rating") or 0
        if len(title) > 42:
            title = title[:41] + "…"
        label = title
        try:
            if rating:
                label += f" ⭐{float(rating):.1f}"
        except (TypeError, ValueError):
            pass
        rows.append([InlineKeyboardButton(
            label, callback_data=f"sg:pick:{i}")])
    rows.append([InlineKeyboardButton(
        "📩 REQUEST TO ADMIN", callback_data="sg:request")])
    rows.append([InlineKeyboardButton(
        "❌ CLOSE", callback_data="sg:close")])
    return InlineKeyboardMarkup(rows)


def _kb_languages(
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
            rows.append(row); row = []
    if row: rows.append(row)
    rows.append([
        InlineKeyboardButton("◀️ BACK", callback_data="sg:back_sugg"),
        InlineKeyboardButton("❌ CLOSE", callback_data="sg:close"),
    ])
    return InlineKeyboardMarkup(rows)


def _kb_seasons(
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
            count = len([e for e in local_eps if e > 0])
            mark = "🟢" if count >= eps else "🟡"
        else:
            count = 0; mark = "⚪"
        label = f"{mark} S{sn:02d} · {eps} ᴇᴘ"
        if count: label += f" · {count} ʟᴏᴄᴀʟ"
        row.append(InlineKeyboardButton(
            label, callback_data=f"sg:seas:{i}"))
        if len(row) >= per_row:
            rows.append(row); row = []
    if row: rows.append(row)
    if not rows:
        rows.append([InlineKeyboardButton(
            "⚠️ no seasons", callback_data="sg:close")])
    rows.append([
        InlineKeyboardButton("◀️ BACK", callback_data="sg:back_lang"),
        InlineKeyboardButton("❌ CLOSE", callback_data="sg:close"),
    ])
    return InlineKeyboardMarkup(rows)


def _kb_qualities(
    qualities: List[str], per_row: int = 2, max_items: int = 12,
) -> InlineKeyboardMarkup:
    rows: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []
    for i, q in enumerate(qualities[:max_items]):
        row.append(InlineKeyboardButton(
            f"🎯 {q}", callback_data=f"sg:qual:{i}"))
        if len(row) >= per_row:
            rows.append(row); row = []
    if row: rows.append(row)
    rows.append([
        InlineKeyboardButton("◀️ BACK", callback_data="sg:back_seas"),
        InlineKeyboardButton("❌ CLOSE", callback_data="sg:close"),
    ])
    return InlineKeyboardMarkup(rows)


# ═══════════════════════════════════════════════════════════════════════════
# RENDER
# ═══════════════════════════════════════════════════════════════════════════
async def _render(
    client: Client, chat_id: int, msg_id: int,
    text: str, kb: Optional[InlineKeyboardMarkup],
    poster: Optional[str] = None,
) -> bool:
    if poster:
        try:
            await client.edit_message_media(
                chat_id=chat_id, message_id=msg_id,
                media=InputMediaPhoto(
                    media=poster, caption=text, parse_mode=ParseMode.HTML,
                ),
                reply_markup=kb,
            )
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
# SEARCH
# ═══════════════════════════════════════════════════════════════════════════
def _norm(s: str) -> str:
    if not s: return ""
    s = s.strip().lower()
    s = re.sub(r"[.\-_/,;:]+", " ", s)
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[^\w\s]", "", s)
    return s.strip()


async def _smart_db_search(title: str) -> Optional[Dict[str, Any]]:
    try:
        hits, _ = await SEARCH.quick_search(title, is_series=True)
    except Exception as e:
        logger.debug(f"[SERIES-H] search: {e}")
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


async def _prepare_chosen(
    matched_title: str, hits: List[Dict[str, Any]],
    tmdb_id_override: Optional[int] = None,
    poster_override: Optional[str] = None,
) -> Dict[str, Any]:
    # TMDB lookup
    tmdb_id: Optional[int] = None
    poster: Optional[str] = None
    year = ""
    tmdb_langs: List[str] = ["English"]
    tmdb_seasons: List[Dict[str, Any]] = []

    try:
        from providers import tmdb_provider as TP
        results = await TP.search_tv(matched_title) or []
        if results:
            ch = results[0]
            tmdb_id = ch.get("tmdb_id")
            poster = ch.get("poster")
            year = ch.get("year") or ""
    except Exception as e:
        logger.debug(f"[SERIES-H] tmdb search: {e}")

    try:
        langs = await STMDB.get_series_languages(matched_title)
        if langs:
            tmdb_langs = list(langs)
    except Exception:
        pass

    try:
        seasons = await STMDB.get_series_seasons(matched_title)
        if seasons:
            tmdb_seasons = list(seasons)
    except Exception:
        pass

    if tmdb_id_override is not None:
        tmdb_id = tmdb_id_override
    if poster_override:
        poster = poster_override

    # Fallback title / year
    display_title = matched_title
    if not year and hits:
        for h in hits:
            y = h.get("year")
            if y:
                year = str(y)
                break

    summary = _summarize_hits(hits)

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
# FORCE-SUB
# ═══════════════════════════════════════════════════════════════════════════
async def _check_fsub(
    client: Client, user_id: int, chat_id: int,
) -> Any:
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
            continue
        st = getattr(m, "status", None)
        st = st.name.lower() if hasattr(st, "name") else str(st).lower()
        if st in ("left", "kicked", "banned"):
            missing.append(int(ch))
    return (len(missing) == 0), missing


async def _kb_fsub(client: Client, missing: List[int]) -> InlineKeyboardMarkup:
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
                    if inv: url = inv
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
# REQUEST CHANNEL (v1 style — search_requests + gsreq callbacks)
# ═══════════════════════════════════════════════════════════════════════════
def _get_system_db():
    if DB_MANAGER is not None:
        try:
            for name in ("get_system_db", "get_media_db", "get_user_db"):
                fn = getattr(DB_MANAGER, name, None)
                if callable(fn):
                    d = fn()
                    if d is not None:
                        return d
            d = getattr(DB_MANAGER, "_db", None)
            if d is not None:
                return d
        except Exception:
            pass
    try:
        from database import db_registry
        return db_registry.get_system_db()
    except Exception:
        return None


def _req_coll():
    d = _get_system_db()
    return d["search_requests"] if d is not None else None


async def _add_request(
    user_id: int, title: str,
    year: Optional[Any] = None, tmdb_id: Optional[int] = None,
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
            "movie_name": title, "query": title,
            "year": year, "tmdb_id": tmdb_id, "kind": "series",
            "source": source, "status": "not_found",
            "created_at": time.time(),
        })
        return token
    except Exception as e:
        logger.warning(f"[SERIES-H] req save: {e}")
        return None


async def _get_request(token: str) -> Optional[Dict[str, Any]]:
    c = _req_coll()
    if c is None:
        return None
    try:
        return await c.find_one({"token_id": token})
    except Exception:
        return None


async def _post_to_request_channel(
    client: Client, user_id: int, title: str,
    year: Optional[Any] = None, tmdb_id: Optional[int] = None,
    source: str = "series_search",
) -> Optional[str]:
    if not REQST_CHANNEL:
        logger.warning("[SERIES-H] REQST_CHANNEL not set")
        return None

    token = await _add_request(user_id, title, year, tmdb_id, source)
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
        f"🎬 {sc('series')} · <b>{_esc(title_disp)}</b>",
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


# ═══════════════════════════════════════════════════════════════════════════
# LANGUAGE VIEW
# ═══════════════════════════════════════════════════════════════════════════
async def _render_languages(
    client: Client, chat_id: int, msg_id: int, uid: int,
) -> None:
    s = _get_session(uid)
    if not s:
        return
    c = s["data"].get("chosen") or {}
    if not c:
        return

    tmdb_langs = c.get("tmdb_langs") or ["English"]
   
