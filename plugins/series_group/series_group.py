# ============================================================
# 🏨 DOWNTOWN VILLA — SERIES GROUP (MAIN FLOW)
# ============================================================
#
# FULL 6-STEP FLOW:
#   1. Search (auto — user types)
#   2. Suggestions (if no exact match)
#   3. Language picker
#   4. Season picker    (🟢 full / 🟡 partial / ⚪ empty)
#   5. Episode picker   (E01, E02, E03...)
#   6. Quality picker
#   → tap quality → token → deep link → PM delivery
#
# PREMIUM USERS:
#   If user is premium AND DB has hits → direct deep link
#   https://t.me/bot?start=prem_{slug}
#   → opens premium watch panel in PM
#
# ============================================================

from __future__ import annotations

import logging
import re
import time
from typing import Any, Dict, List, Optional

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from core import config
from utils import fonts as F
from utils import format as FM
from utils import progress as P

logger = logging.getLogger(__name__)


# ============================================================
# CONSTANTS
# ============================================================

PFX = "sg"
COOLDOWN = 3.0
_last_seen: Dict[int, float] = {}


# ============================================================
# IN-MEMORY SESSION STORE
# ============================================================

_sessions: Dict[str, Dict[str, Any]] = {}
SESSION_TTL = 1800.0


def _new_session(**data) -> str:
    token = f"{int(time.time()*1000)}"
    import hashlib
    token = hashlib.md5(token.encode()).hexdigest()[:12]
    _sessions[token] = {
        "created": time.time(),
        "expires": time.time() + SESSION_TTL,
        **data,
    }
    return token


def _get_session(token: str) -> Optional[Dict[str, Any]]:
    s = _sessions.get(token)
    if not s:
        return None
    if time.time() > s["expires"]:
        _sessions.pop(token, None)
        return None
    return s


def _update_session(token: str, **data) -> None:
    s = _sessions.get(token)
    if not s:
        return
    s.update(data)
    s["expires"] = time.time() + SESSION_TTL


def _drop_session(token: str) -> None:
    _sessions.pop(token, None)


# ============================================================
# PREMIUM CHECK
# ============================================================

async def _is_premium(uid: int) -> bool:
    try:
        from plugins.premium import premium_watch as PW
        fn = getattr(PW, "is_premium", None)
        if fn:
            return bool(await fn(uid))
    except Exception:
        pass

    try:
        from database import db_registry
        db = db_registry.get_user_db()
        if db is None:
            return False
        doc = await db["premium_users"].find_one({
            "user_id": int(uid), "status": "active"
        })
        if doc and doc.get("expires_at", 0) > time.time():
            return True
    except Exception:
        pass
    return False


# ============================================================
# SEARCH ENGINE
# ============================================================

async def _engine_search(
    title: str,
    language: Optional[str] = None,
    season: Optional[int] = None,
    quality: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Search all shards and filter."""
    try:
        from media_search import engine as _eng
        from media_search.normalizer import parse_query
        engine = getattr(_eng, "engine", None)
        if engine is None:
            return []

        norm, year, is_series = parse_query(title)
        if not norm:
            return []

        result = await engine.search_series(norm, year=year)
        hits = list(result.hits or []) if result else []

        if not hits:
            result = await engine.search_any(norm, year=year)
            hits = list(result.hits or []) if result else []

        out = []
        for h in hits:
            h_season = getattr(h, "season", None)
            h_ep = getattr(h, "episode", None)
            h_qual = (getattr(h, "quality", "") or "").upper()
            h_langs = [str(x).title() for x in
                       (getattr(h, "audio_languages", None) or [])]

            if season is not None and h_season != season:
                continue
            if language:
                ll = language.lower()
                hl = [l.lower() for l in h_langs]
                if hl and not any(ll in l or l in ll for l in hl):
                    continue
            if quality and h_qual:
                if h_qual != quality.upper():
                    continue

            out.append({
                "file_id": getattr(h, "file_id", ""),
                "file_unique_id": getattr(h, "file_unique_id", None),
                "file_name": getattr(h, "file_name", "") or "",
                "file_size": getattr(h, "file_size", 0) or 0,
                "season": h_season,
                "episode": h_ep,
                "quality": h_qual or "UNKNOWN",
                "languages": h_langs,
                "title": getattr(h, "title", "") or "",
                "series_title": getattr(h, "series_title", None) or "",
            })
        return out

    except Exception as e:
        logger.exception(f"[SG] engine: {e}")
        return []


# ============================================================
# ENTRY
# ============================================================

GROUP_FILTER = (
    filters.group
    & filters.text
    & ~filters.regex(r"^/")
)


@Client.on_message(GROUP_FILTER, group=-9999)
async def series_group_search(client: Client, message: Message):
    """Entry — any group text triggers series search."""
    try:
        if not message.from_user:
            return

        txt = (message.text or "").strip()
        if len(txt) < 2 or len(txt) > 80:
            return
        if "http" in txt.lower():
            return

        uid = message.from_user.id
        now = time.time()
        if now - _last_seen.get(uid, 0) < COOLDOWN:
            return
        _last_seen[uid] = now

        try:
            message.stop_propagation()
        except Exception:
            pass

        try:
            status = await message.reply_text("🔎 ꜱᴇᴀʀᴄʜɪɴɢ…")
        except Exception:
            return

        # 1. DB search first
        hits = await _engine_search(txt)

        # 2. Premium + hit → premium redirect
        if hits and await _is_premium(uid):
            await _premium_redirect(client, message, status, txt, hits)
            return

        # 3. Regular flow — start with suggestions
        await _handle_search(client, message, status, txt, hits)

    except Exception as e:
        logger.exception(f"[SG] entry: {e}")


# ============================================================
# PREMIUM REDIRECT
# ============================================================

async def _premium_redirect(
    client: Client,
    message: Message,
    status: Message,
    query: str,
    hits: List[Dict[str, Any]],
) -> None:
    """Premium user → generate prem_{token} deep link."""
    try:
        title = hits[0].get("series_title") or hits[0].get("title") or query
        slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")

        from plugins.series_group import deep_link as DL
        token = await DL.create_premium_token(
            user_id=message.from_user.id,
            chat_id=message.chat.id,
            title=title,
            slug=slug,
            tmdb_id=None,
            hits=hits,
        )
        if not token:
            await _handle_search(client, message, status, query, hits)
            return

        bot_username = ""
        try:
            me = await client.identity()
            bot_username = me.username or ""
        except Exception:
            pass

        deep_link = f"https://t.me/{bot_username}?start=prem_{token}"

        try:
            await status.edit_text(
                "\n".join([
                    f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                    f"{F.EMO['crown']} <b>{F.fb('PREMIUM MODE')}</b>",
                    F.DIV, "",
                    f"🎬 <b>{F.sc(str(title)[:50])}</b>",
                    f"📦 {len(hits)} ꜰɪʟᴇꜱ ꜰᴏᴜɴᴅ",
                    "",
                    F.DIV_S,
                    f"{F.EMO['spark']} ᴘʀᴇᴍɪᴜᴍ ᴜꜱᴇʀꜱ ɢᴇᴛ ᴛʜᴇ ꜰᴜʟʟ ᴡᴀᴛᴄʜ ᴇxᴘᴇʀɪᴇɴᴄᴇ:",
                    f"✅ ᴡᴀᴛᴄʜᴇᴅ ʟɪꜱᴛ",
                    f"✅ ɴᴇxᴛ ᴇᴘɪꜱᴏᴅᴇ",
                    f"✅ ᴡᴀᴛᴄʜ ᴏʀᴅᴇʀ",
                    f"✅ ᴘʀᴏɢʀᴇꜱꜱ ᴛʀᴀᴄᴋɪɴɢ",
                    "",
                    f"📌 ᴛᴀᴘ ᴛʜᴇ ʙᴜᴛᴛᴏɴ ʙᴇʟᴏᴡ ᴛᴏ ᴏᴘᴇɴ ɪɴ ᴘᴍ",
                ]),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        f"{F.EMO['rocket']} {F.sc('open premium watch')}",
                        url=deep_link,
                    )],
                    [InlineKeyboardButton(
                        f"{F.EMO['cross']} {F.sc('cancel')}",
                        callback_data="sg:close",
                    )],
                ]),
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except Exception:
            pass

    except Exception as e:
        logger.exception(f"[SG] premium redirect: {e}")
        await _handle_search(client, message, status, query, hits)


# ============================================================
# REGULAR FLOW
# ============================================================

async def _handle_search(
    client: Client,
    message: Message,
    status: Message,
    query: str,
    hits: List[Dict[str, Any]],
) -> None:
    """Regular flow — suggestions then steps."""
    if not hits:
        # No DB hits → suggestions via shared engine
        await _handle_no_results(client, message, status, query)
        return

    # Has hits → go to suggestions step (still allow user to pick)
    try:
        from media_search.spell_check import get_suggestions, clean_query
        cleaned = clean_query(query)
        suggestions = await get_suggestions(cleaned) or []
    except Exception:
        suggestions = []

    # If no suggestions, use the DB title directly
    if not suggestions:
        title = hits[0].get("series_title") or hits[0].get("title") or query
        token = _new_session(
            user_id=message.from_user.id,
            chat_id=message.chat.id,
            title=title,
            hits=hits,
        )
        # Skip suggestions step → go to language
        await _show_language_picker(client, status, token)
        return

    # Show suggestions
    token = _new_session(
        user_id=message.from_user.id,
        chat_id=message.chat.id,
        query=query,
        suggestions=suggestions,
        db_hits=hits,
    )

    rows: List[List[InlineKeyboardButton]] = []
    for i, s in enumerate(suggestions[:8]):
        title = str(s.get("title", "?"))[:32]
        year = s.get("year")
        rating = s.get("rating")
        label = f"🎬 {title}"
        if year:
            label += f" ({year})"
        if rating:
            label += f" · ⭐{rating}"
        if len(label) > 55:
            label = label[:52] + "…"
        rows.append([InlineKeyboardButton(
            label,
            callback_data=f"{PFX}:sug:{token}:{i}",
        )])

    rows.append([InlineKeyboardButton(
        f"{F.EMO['cross']} {F.sc('cancel')}",
        callback_data=f"{PFX}:close:{token}",
    )])

    text = "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"{F.EMO['search']} <b>{F.fb('DID YOU MEAN?')}</b>",
        F.DIV, "",
        f"🔍 <code>{F.sc(query[:50])}</code>",
        f"📝 {len(suggestions)} ꜱᴜɢɢᴇꜱᴛɪᴏɴꜱ",
        "",
        f"ᴘɪᴄᴋ ᴛʜᴇ ꜱᴇʀɪᴇꜱ ʏᴏᴜ ᴍᴇᴀɴᴛ:",
    ])

    try:
        await status.edit_text(
            text,
            reply_markup=InlineKeyboardMarkup(rows),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.debug(f"[SG] suggestions edit: {e}")


async def _handle_no_results(
    client: Client,
    message: Message,
    status: Message,
    query: str,
) -> None:
    """No DB hits → try TMDB suggestions."""
    try:
        from plugins.series_group import tmdb as T
        suggestions = await T.search_series(query)
    except Exception:
        suggestions = []

    if not suggestions:
        try:
            await status.edit_text(
                "\n".join([
                    f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                    F.DIV, "",
                    f"❌ ɴᴏ ᴍᴀᴛᴄʜ ꜰᴏʀ <code>{F.sc(query[:50])}</code>",
                    f"📌 ᴘʟᴇᴀꜱᴇ ᴄʜᴇᴄᴋ ꜱᴘᴇʟʟɪɴɢ.",
                ]),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        return

    token = _new_session(
        user_id=message.from_user.id,
        chat_id=message.chat.id,
        query=query,
        tmdb_suggestions=suggestions,
        db_hits=[],
    )

    rows: List[List[InlineKeyboardButton]] = []
    for i, s in enumerate(suggestions[:8]):
        title = str(s.get("title", "?"))[:32]
        year = s.get("year")
        label = f"🎬 {title}"
        if year:
            label += f" ({year})"
        if len(label) > 55:
            label = label[:52] + "…"
        rows.append([InlineKeyboardButton(
            label,
            callback_data=f"{PFX}:tsug:{token}:{i}",
        )])

    rows.append([InlineKeyboardButton(
        f"{F.EMO['cross']} {F.sc('cancel')}",
        callback_data=f"{PFX}:close:{token}",
    )])

    try:
        await status.edit_text(
            "\n".join([
                f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
                f"{F.EMO['search']} <b>{F.fb('TMDB SUGGESTIONS')}</b>",
                F.DIV, "",
                f"🔍 <code>{F.sc(query[:50])}</code>",
                f"📝 ɴᴏ ᴅʙ ʜɪᴛ · {len(suggestions)} ᴛᴍᴅʙ ꜱᴜɢɢᴇꜱᴛɪᴏɴꜱ",
                "",
                f"ᴘɪᴄᴋ ᴛʜᴇ ꜱᴇʀɪᴇꜱ:",
            ]),
            reply_markup=InlineKeyboardMarkup(rows),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception:
        pass


# ============================================================
# STEP: LANGUAGE
# ============================================================

async def _show_language_picker(
    client: Client,
    target,
    token: str,
) -> None:
    s = _get_session(token)
    if not s:
        return

    hits = s.get("hits") or []
    title = s.get("title") or "?"

    # Languages from hits
    local: List[str] = []
    for h in hits:
        for l in (h.get("languages") or []):
            n = str(l).strip().title()
            if n and n not in local:
                local.append(n)

    # Get TMDB languages (best effort)
    tmdb_langs: List[str] = []
    tmdb_id = s.get("tmdb_id")
    if not tmdb_id:
        try:
            from plugins.series_group import tmdb as T
            res = await T.search_series(title)
            if res:
                tmdb_id = res[0].get("tmdb_id") or res[0].get("id")
                _update_session(token, tmdb_id=tmdb_id, tmdb_poster=res[0].get("poster"))
        except Exception:
            pass

    if tmdb_id:
        try:
            from plugins.series_group import tmdb as T
            details = await T.get_details(tmdb_id)
            if details:
                tmdb_langs = T.extract_languages(details)
                _update_session(token, tmdb_details=details)
        except Exception:
            pass

    # Merge
    ordered = []
    for l in local:
        if l not in ordered:
            ordered.append(l)
    for l in tmdb_langs:
        if l not in ordered:
            ordered.append(l)
    if not ordered:
        ordered = ["English", "Hindi", "Tamil", "Telugu", "Malayalam"]

    _update_session(token, ordered_langs=ordered, local_langs=local)

    # Auto-skip
    if len(ordered) == 1:
        _update_session(token, selected_language=ordered[0])
        await _show_season_picker(client, target, token)
        return

    # Keyboard
    rows: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []
    for i, l in enumerate(ordered[:10]):
        icon = "🟢" if l in local else "⚪"
        row.append(InlineKeyboardButton(
            f"{icon} {l}",
            callback_data=f"{PFX}:lang:{token}:{i}",
        ))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    rows.append([InlineKeyboardButton(
        f"{F.EMO['cross']} {F.sc('cancel')}",
        callback_data=f"{PFX}:close:{token}",
    )])

    text = "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"{F.EMO['sound']} <b>{F.fb('PICK LANGUAGE')}</b>",
        F.DIV, "",
        f"🎬 <b>{F.sc(str(title)[:50])}</b>",
        "",
        f"🟢 ʜᴀꜱ ꜰɪʟᴇꜱ   ⚪ ᴛᴍᴅʙ ᴏɴʟʏ",
        "",
        f"ᴛᴀᴘ ᴀ ʟᴀɴɢᴜᴀɢᴇ:",
    ])

    try:
        if hasattr(target, "edit_text"):
            await target.edit_text(
                text,
                reply_markup=InlineKeyboardMarkup(rows),
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
    except Exception as e:
        logger.debug(f"[SG] lang picker: {e}")


# ============================================================
# STEP: SEASON
# ============================================================

async def _show_season_picker(
    client: Client,
    target,
    token: str,
) -> None:
    s = _get_session(token)
    if not s:
        return

    title = s.get("title") or "?"
    lang = s.get("selected_language") or "—"
    hits = s.get("hits") or []
    tmdb_details = s.get("tmdb_details") or {}

    # Local seasons map
    local_seasons: Dict[int, List[int]] = {}
    for h in hits:
        sn = h.get("season")
        ep = h.get("episode")
        if sn is None:
            continue
        local_seasons.setdefault(int(sn), [])
        if ep is not None:
            local_seasons[int(sn)].append(int(ep))

    # TMDB seasons
    tmdb_seasons: List[Dict[str, Any]] = []
    try:
        from plugins.series_group import tmdb as T
        tmdb_seasons = T.extract_seasons(tmdb_details) if tmdb_details else []
    except Exception:
        pass

    if not tmdb_seasons and not local_seasons:
        await _safe_edit(target,
            f"❌ ɴᴏ ꜱᴇᴀꜱᴏɴꜱ ꜰᴏᴜɴᴅ ꜰᴏʀ <code>{F.sc(str(title)[:40])}</code>"
        )
        return

    _update_session(token,
                    tmdb_seasons=tmdb_seasons,
                    local_seasons=local_seasons)

    # Auto-skip single season
    total_seasons = max(len(tmdb_seasons), len(local_seasons))
    if total_seasons == 1:
        if tmdb_seasons:
            sn = tmdb_seasons[0]["season"]
        else:
            sn = list(local_seasons.keys())[0]
        _update_session(token, selected_season=sn)
        await _show_episode_picker(client, target, token)
        return

    def icon_for(sn: int, tmdb_eps: int) -> str:
        eps = local_seasons.get(sn, [])
        count = len([e for e in eps if e > 0])
        if count == 0:
            return "⚪"
        if tmdb_eps and count >= tmdb_eps:
            return "🟢"
        return "🟡"

    rows: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []

    for i, ts in enumerate(tmdb_seasons):
        sn = ts["season"]
        eps = int(ts.get("episodes", 0) or 0)
        icon = icon_for(sn, eps)
        label = f"{icon} S{sn:02d}"
        if eps:
            label += f" · {eps}ᴱ"
        row.append(InlineKeyboardButton(
            label,
            callback_data=f"{PFX}:seas:{token}:{i}",
        ))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    # Local-only seasons not in TMDB
    tmdb_season_nums = {ts["season"] for ts in tmdb_seasons}
    for sn in sorted(local_seasons.keys()):
        if sn in tmdb_season_nums:
            continue
        icon = "🟢"
        count = len([e for e in local_seasons[sn] if e > 0])
        rows.append([InlineKeyboardButton(
            f"{icon} S{sn:02d} · {count}ᴱ",
            callback_data=f"{PFX}:seas_local:{token}:{sn}",
        )])

    rows.append([InlineKeyboardButton(
        f"{F.EMO['cross']} {F.sc('cancel')}",
        callback_data=f"{PFX}:close:{token}",
    )])

    text = "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"{F.EMO['tv']} <b>{F.fb('PICK SEASON')}</b>",
        F.DIV, "",
        f"🎬 <b>{F.sc(str(title)[:50])}</b>",
        f"🔊 <code>{F.sc(lang)}</code>",
        "",
        f"🟢 ꜰᴜʟʟ · 🟡 ᴘᴀʀᴛɪᴀʟ · ⚪ ᴍɪꜱꜱɪɴɢ",
        "",
        f"ᴛᴀᴘ ᴀ ꜱᴇᴀꜱᴏɴ:",
    ])

    await _safe_edit(target, text, InlineKeyboardMarkup(rows))


# ============================================================
# STEP: EPISODE
# ============================================================

async def _show_episode_picker(
    client: Client,
    target,
    token: str,
) -> None:
    s = _get_session(token)
    if not s:
        return

    title = s.get("title") or "?"
    season = s.get("selected_season")
    if season is None:
        return

    hits = s.get("hits") or []
    local_eps: List[int] = []
    for h in hits:
        if h.get("season") == season:
            ep = h.get("episode")
            if ep is not None:
                ep = int(ep)
                if ep not in local_eps:
                    local_eps.append(ep)

    # Get TMDB episodes
    tmdb_id = s.get("tmdb_id")
    tmdb_eps: List[int] = []
    if tmdb_id:
        try:
            from plugins.series_group import tmdb as T
            tmdb_eps = await T.get_season_episodes(tmdb_id, season)
        except Exception:
            pass

    # Merge — all episodes
    all_eps = sorted(set(tmdb_eps) | set(local_eps))
    if not all_eps:
        await _safe_edit(target, "❌ ɴᴏ ᴇᴘɪꜱᴏᴅᴇꜱ ꜰᴏᴜɴᴅ")
        return

    _update_session(token, season_episodes=all_eps, local_eps=local_eps)

    # Auto-skip
    if len(all_eps) == 1:
        _update_session(token, selected_episode=all_eps[0])
        await _show_quality_picker(client, target, token)
        return

    # Grid of episodes (E01, E02, ...)
    rows: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []
    for ep in all_eps:
        has = ep in local_eps
        icon = "🟢" if has else "⚪"
        row.append(InlineKeyboardButton(
            f"{icon} E{ep:02d}",
            callback_data=f"{PFX}:ep:{token}:{ep}",
        ))
        if len(row) == 4:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    rows.append([InlineKeyboardButton(
        f"{F.EMO['cross']} {F.sc('cancel')}",
        callback_data=f"{PFX}:close:{token}",
    )])

    text = "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"{F.EMO['clapper']} <b>{F.fb('PICK EPISODE')}</b>",
        F.DIV, "",
        f"🎬 <b>{F.sc(str(title)[:50])}</b>",
        f"📺 S{season:02d} · {len(all_eps)} ᴇᴘɪꜱᴏᴅᴇꜱ",
        "",
        f"🟢 ᴀᴠᴀɪʟᴀʙʟᴇ · ⚪ ᴍɪꜱꜱɪɴɢ",
        "",
        f"ᴛᴀᴘ ᴀɴ ᴇᴘɪꜱᴏᴅᴇ:",
    ])

    await _safe_edit(target, text, InlineKeyboardMarkup(rows))


# ============================================================
# STEP: QUALITY
# ============================================================

async def _show_quality_picker(
    client: Client,
    target,
    token: str,
) -> None:
    s = _get_session(token)
    if not s:
        return

    title = s.get("title") or "?"
    season = s.get("selected_season")
    ep = s.get("selected_episode")
    hits = s.get("hits") or []

    # Qualities for this (season, episode)
    qualities: List[str] = []
    for h in hits:
        if h.get("season") == season and h.get("episode") == ep:
            q = (h.get("quality") or "").upper()
            if q and q not in qualities:
                qualities.append(q)

    qualities.sort(key=lambda q: _quality_rank(q), reverse=True)

    if not qualities:
        await _safe_edit(
            target,
            f"❌ ɴᴏ ꜰɪʟᴇꜱ ꜰᴏʀ S{season:02d}E{ep:02d}"
        )
        return

    _update_session(token, available_qualities=qualities)

    rows: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []
    for q in qualities[:8]:
        row.append(InlineKeyboardButton(
            f"🎯 {q}",
            callback_data=f"{PFX}:qual:{token}:{q}",
        ))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    rows.append([InlineKeyboardButton(
        f"{F.EMO['cross']} {F.sc('cancel')}",
        callback_data=f"{PFX}:close:{token}",
    )])

    text = "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"{F.EMO['spark']} <b>{F.fb('PICK QUALITY')}</b>",
        F.DIV, "",
        f"🎬 <b>{F.sc(str(title)[:50])}</b>",
        f"📺 S{season:02d}E{ep:02d}",
        "",
        f"ᴛᴀᴘ ᴀ ǫᴜᴀʟɪᴛʏ:",
    ])

    await _safe_edit(target, text, InlineKeyboardMarkup(rows))


def _quality_rank(q: str) -> int:
    return {
        "2160P": 90, "4K": 90, "UHD": 90,
        "1440P": 80, "1080P": 70, "FHD": 70,
        "720P": 60, "HD": 60, "576P": 50,
        "480P": 40, "360P": 30,
    }.get(q.upper(), 25)


# ============================================================
# CALLBACKS
# ============================================================

@Client.on_callback_query(
    filters.regex(rf"^{PFX}:"),
    group=-9999,
)
async def series_callbacks(client: Client, q: CallbackQuery):
    try:
        parts = str(q.data).split(":")
        action = parts[1] if len(parts) > 1 else ""

        # ── CLOSE ──
        if action == "close":
            token = parts[2] if len(parts) > 2 else None
            if token:
                _drop_session(token)
            try:
                await q.message.delete()
            except Exception:
                pass
            return await q.answer("❌")

        # ── SUGGESTION PICK (from shared engine) ──
        if action == "sug":
            token = parts[2]
            idx = int(parts[3])
            s = _get_session(token)
            if not s:
                return await q.answer("⏱️ Expired", show_alert=True)

            suggestions = s.get("suggestions") or []
            if idx < 0 or idx >= len(suggestions):
                return await q.answer("❌ Invalid")

            chosen = suggestions[idx]
            title = chosen.get("title") or "?"
            _update_session(token, title=title)

            # Re-run search with chosen title
            hits = await _engine_search(title)
            _update_session(token, hits=hits)

            if not hits:
                return await q.answer("❌ No files for this series", show_alert=True)

            await q.answer()
            return await _show_language_picker(client, q.message, token)

        # ── TMDB SUGGESTION PICK ──
        if action == "tsug":
            token = parts[2]
            idx = int(parts[3])
            s = _get_session(token)
            if not s:
                return await q.answer("⏱️ Expired", show_alert=True)

            items = s.get("tmdb_suggestions") or []
            if idx < 0 or idx >= len(items):
                return await q.answer("❌ Invalid")

            chosen = items[idx]
            title = chosen.get("title") or "?"
            tmdb_id = chosen.get("tmdb_id") or chosen.get("id")

            _update_session(token, title=title, tmdb_id=tmdb_id)

            # Try to find files by this title
            hits = await _engine_search(title)
            _update_session(token, hits=hits)

            if not hits:
                return await q.answer(
                    "📩 Request sent to admin", show_alert=True
                )

            await q.answer()
            return await _show_language_picker(client, q.message, token)

        # ── LANGUAGE PICK ──
        if action == "lang":
            token = parts[2]
            idx = int(parts[3])
            s = _get_session(token)
            if not s:
                return await q.answer("⏱️ Expired", show_alert=True)

            langs = s.get("ordered_langs") or []
            if idx < 0 or idx >= len(langs):
                return await q.answer("❌ Invalid")

            chosen = langs[idx]
            _update_session(token, selected_language=chosen)
            await q.answer(f"🔊 {chosen}")
            return await _show_season_picker(client, q.message, token)

        # ── SEASON PICK ──
        if action == "seas":
            token = parts[2]
            idx = int(parts[3])
            s = _get_session(token)
            if not s:
                return await q.answer("⏱️ Expired", show_alert=True)

            seasons = s.get("tmdb_seasons") or []
            if idx < 0 or idx >= len(seasons):
                return await q.answer("❌ Invalid")

            sn = seasons[idx]["season"]
            _update_session(token, selected_season=sn)
            await q.answer(f"📺 S{sn:02d}")
            return await _show_episode_picker(client, q.message, token)

        # ── SEASON PICK (local only) ──
        if action == "seas_local":
            token = parts[2]
            sn = int(parts[3])
            s = _get_session(token)
            if not s:
                return await q.answer("⏱️ Expired", show_alert=True)

            _update_session(token, selected_season=sn)
            await q.answer(f"📺 S{sn:02d}")
            return await _show_episode_picker(client, q.message, token)

        # ── EPISODE PICK ──
        if action == "ep":
            token = parts[2]
            ep = int(parts[3])
            s = _get_session(token)
            if not s:
                return await q.answer("⏱️ Expired", show_alert=True)

            _update_session(token, selected_episode=ep)
            await q.answer(f"🎞️ E{ep:02d}")
            return await _show_quality_picker(client, q.message, token)

        # ── QUALITY PICK → DELIVER TOKEN ──
        if action == "qual":
            token = parts[2]
            quality = parts[3]
            s = _get_session(token)
            if not s:
                return await q.answer("⏱️ Expired", show_alert=True)

            return await _on_quality_pick(client, q, token, quality)

        return await q.answer("❓ Unknown")

    except Exception as e:
        logger.exception(f"[SG] callback: {e}")
        try:
            await q.answer("❌ Error", show_alert=True)
        except Exception:
            pass


# ============================================================
# QUALITY PICK → BUILD DELIVER TOKEN + DEEP LINK
# ============================================================

async def _on_quality_pick(
    client: Client,
    q: CallbackQuery,
    token: str,
    quality: str,
) -> None:
    s = _get_session(token)
    if not s:
        return await q.answer("⏱️ Expired", show_alert=True)

    uid = q.from_user.id
    title = s.get("title") or "?"
    season = s.get("selected_season") or 0
    ep = s.get("selected_episode") or 0
    lang = s.get("selected_language") or ""
    hits = s.get("hits") or []

    # Filter hits to this (season, episode, quality)
    matching = [
        h for h in hits
        if h.get("season") == season
        and h.get("episode") == ep
        and (h.get("quality") or "").upper() == quality.upper()
    ]

    # Also try to grab the whole season at this quality
    season_eps_hits = [
        h for h in hits
        if h.get("season") == season
        and (h.get("quality") or "").upper() == quality.upper()
    ]

    if not matching and not season_eps_hits:
        return await q.answer("❌ No files", show_alert=True)

    # Build episodes list
    episodes_found = []
    hits_for_delivery = []
    for h in sorted(
        season_eps_hits,
        key=lambda x: x.get("episode") or 0,
    ):
        e = h.get("episode")
        if e is None:
            continue
        if e not in episodes_found:
            episodes_found.append(e)
            hits_for_delivery.append(h)

    # If user picked a specific episode, still deliver the full season
    # (this matches the premium experience)

    # Create deliver token
    from plugins.series_group import deep_link as DL
    dtoken = await DL.create_deliver_token(
        user_id=uid,
        chat_id=q.message.chat.id,
        title=title,
        tmdb_id=s.get("tmdb_id"),
        season=season,
        quality=quality,
        language=lang,
        episodes=episodes_found,
        hits=hits_for_delivery,
    )

    if not dtoken:
        return await q.answer("❌ Token error", show_alert=True)

    bot_username = ""
    try:
        me = await client.identity()
        bot_username = me.username or ""
    except Exception:
        pass

    deep_link = f"https://t.me/{bot_username}?start=deliver_{dtoken}"

    # Drop session (its job is done)
    _drop_session(token)

    # Show redirect message
    text = "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"{F.EMO['rocket']} <b>{F.fb('REDIRECTING TO PM')}</b>",
        F.DIV, "",
        f"🎬 <b>{F.sc(str(title)[:50])}</b>",
        f"📺 <b>Season {season:02d}</b>",
        f"🎯 <code>{quality}</code> · 🔉 <code>{lang}</code>",
        "",
        f"📁 <code>{len(episodes_found)}</code> ᴇᴘɪꜱᴏᴅᴇꜱ",
        "",
        f"📌 ᴛᴀᴘ ᴛʜᴇ ʙᴜᴛᴛᴏɴ ᴛᴏ ᴏᴘᴇɴ ʙᴏᴛ ᴘᴍ",
        f"📌 ꜰɪʟᴇꜱ ᴡɪʟʟ ʙᴇ ᴅᴇʟɪᴠᴇʀᴇᴅ ᴛʜᴇʀᴇ",
    ])

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"{F.EMO['rocket']} {F.sc('open bot pm')}",
            url=deep_link,
        )],
        [InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('cancel')}",
            callback_data=f"{PFX}:close",
        )],
    ])

    try:
        await q.message.edit_text(
            text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception:
        pass

    await q.answer("🚀 Open PM")


# ============================================================
# HELPERS
# ============================================================

async def _safe_edit(target, text: str, kb=None) -> None:
    try:
        if hasattr(target, "edit_text"):
            await target.edit_text(
                text,
                reply_markup=kb,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
    except Exception as e:
        if "not modified" not in str(e).lower():
            logger.debug(f"[SG] edit: {e}")


async def ensure_indexes() -> None:
    try:
        from plugins.series_group import deep_link as DL
        await DL.ensure_indexes()
    except Exception:
        pass


# ============================================================
# PUBLIC
# ============================================================

__all__ = [
    "series_group_search",
    "series_callbacks",
    "ensure_indexes",
]
