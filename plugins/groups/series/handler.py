# ============================================================
# 🏨 DOWNTOWN VILLA — SERIES GROUP HANDLER
# ============================================================
#
# Entry point for text messages in the SERIES group only
# (chat_id == SERIES_GROUP_ID).
#
# Flow:
#   1. Gate: series group only · enabled · content_mode · cooldown
#   2. quick_search → if hits → wizard
#   3. Wizard: language → season → episode → quality
#   4. Quality pick → deliver token → deep-link to PM
#
# If no hits:
#   5. Spell check + retry
#   6. TMDB suggestions → user picks → re-search → wizard OR request
#   7. Request prompt
#
# All steps gated by plugins.groups.series.flow reader.
#
# Handler group: -9999 (runs BEFORE movie handler at -510)
# This ensures SERIES_GROUP_ID is claimed first.
#
# Wizard callbacks use prefix: sgw:
#
# ============================================================

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from core import config
from plugins.groups import state as S
from plugins.groups.shared import search as SEARCH
from plugins.groups.shared import suggestions as SUGG
from plugins.groups.shared import deep_link as DL
from plugins.groups.shared import request_flow as RF
from plugins.groups.shared import delivery as DELIVERY
from plugins.groups.movie import flow as MFLOW  # reuse step helpers
from plugins.groups.series import flow as SFLOW
from plugins.groups.series import tmdb as STMDB
from utils import fonts as F
from utils import format as FM

logger = logging.getLogger(__name__)


# ============================================================
# SECTION 1 — CONSTANTS
# ============================================================

COOLDOWN = 3.0
MIN_QUERY_LEN = 2
MAX_QUERY_LEN = 100
WIZARD_TTL = 900.0   # 15 min


# ============================================================
# SECTION 2 — COOLDOWN
# ============================================================

_last_seen: Dict[int, float] = {}


def _cooldown_ok(uid: int) -> bool:
    now = time.time()
    if now - _last_seen.get(uid, 0) < COOLDOWN:
        return False
    _last_seen[uid] = now
    return True


def _cleanup_cooldown() -> None:
    now = time.time()
    if len(_last_seen) < 5000:
        return
    for k in list(_last_seen.keys()):
        if now - _last_seen[k] > 300:
            _last_seen.pop(k, None)


# ============================================================
# SECTION 3 — WIZARD SESSIONS
# ============================================================

_wizard: Dict[int, Dict[str, Any]] = {}


def _wiz_new(uid: int, chat_id: int, **data) -> None:
    _wizard[int(uid)] = {
        "created": time.time(),
        "expires": time.time() + WIZARD_TTL,
        "chat_id": int(chat_id),
        **data,
    }


def _wiz_get(uid: int) -> Optional[Dict[str, Any]]:
    s = _wizard.get(int(uid))
    if not s:
        return None
    if time.time() > s.get("expires", 0):
        _wizard.pop(int(uid), None)
        return None
    return s


def _wiz_set(uid: int, **data) -> None:
    s = _wizard.get(int(uid))
    if not s:
        return
    s.update(data)
    s["expires"] = time.time() + WIZARD_TTL


def _wiz_drop(uid: int) -> None:
    _wizard.pop(int(uid), None)


def _wiz_cleanup() -> None:
    now = time.time()
    for k in list(_wizard.keys()):
        if now > _wizard[k].get("expires", 0):
            _wizard.pop(k, None)


# ============================================================
# SECTION 4 — ENTRY HANDLER
# ============================================================

@Client.on_message(
    filters.group
    & filters.text
    & ~filters.regex(r"^/")
    & ~filters.regex(r"^sr:")
    & ~filters.regex(r"^sgw:"),
    group=-9999,
)
async def series_group_entry(client: Client, message: Message):
    status: Optional[Message] = None
    try:
        if not message.from_user:
            return

        # ── GATE 1: must be SERIES_GROUP_ID ──
        series_gid = getattr(config, "SERIES_GROUP_ID", None)
        if not series_gid:
            return
        if int(message.chat.id) != int(series_gid):
            return

        # ── GATE 2: query validation ──
        txt = (message.text or "").strip()
        if len(txt) < MIN_QUERY_LEN or len(txt) > MAX_QUERY_LEN:
            return
        low = txt.lower()
        if "http://" in low or "https://" in low or "t.me/" in low:
            return
        if txt.startswith("/"):
            return

        # ── GATE 3: group enabled + content_mode ──
        chat_id = message.chat.id
        cfg = await S.get_config(chat_id)

        if not cfg.get("enabled", True):
            return
        if not cfg.get("search_enabled", True):
            return

        content_mode = str(cfg.get("content_mode", "both")).lower()
        if content_mode == "movie":
            # This group is movies-only, but it's also SERIES_GROUP_ID
            # → still allow series here (SERIES_GROUP_ID wins)
            pass

        # ── GATE 4: cooldown ──
        uid = message.from_user.id
        if not _cooldown_ok(uid):
            return
        _cleanup_cooldown()

        try:
            message.stop_propagation()
        except Exception:
            pass

        # ── Show status ──
        try:
            status = await message.reply_text("🔎 ꜱᴇᴀʀᴄʜɪɴɢ…")
        except Exception:
            return

        try:
            await S.bump_stat(chat_id, "searches_today")
        except Exception:
            pass

        # ── Run pipeline ──
        await _run_series_pipeline(
            client=client,
            message=message,
            status=status,
            query=txt,
            cfg=cfg,
        )

    except Exception as e:
        logger.exception(f"[SERIES-H] entry: {e}")
        if status is not None:
            try:
                await status.edit_text(
                    "\n".join([
                        f"{F.EMO['cross']} <b>{F.fb('ERROR')}</b>",
                        F.DIV, "",
                        f"📌 {F.sc('please try again')}",
                    ]),
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass


# ============================================================
# SECTION 5 — PIPELINE
# ============================================================

async def _run_series_pipeline(
    client: Client,
    message: Message,
    status: Message,
    query: str,
    cfg: Dict[str, Any],
) -> None:
    uid = message.from_user.id
    chat_id = message.chat.id

       # ── 1. DB search (series-aware) ──
    hits, complete = await SEARCH.quick_search(query, is_series=True)

    if hits:
        # ── Premium fast-path: if user is premium, redirect to PM ──
        if await _is_user_premium(uid):
            ok = await _try_premium_redirect(
                client, message, status, query, hits, uid, chat_id,
            )
            if ok:
                return

        await _start_wizard(client, status, query, hits, cfg, uid, chat_id)
        return
    if not complete:
        await _edit_status(
            status,
            "\n".join([
                f"{F.EMO['warn']} <b>{F.fb('DBs UNREACHABLE')}</b>",
                F.DIV, "",
                f"📌 {F.sc('try again in a moment')}",
            ]),
        )
        return

    # ── 2. Spell check ──
    if await SFLOW.is_step_enabled(chat_id, "spell_check"):
        corrected: Optional[str] = None
        try:
            corrected = await SUGG.ai_spell_check(query, is_series=True)
        except Exception as e:
            logger.debug(f"[SERIES-H] spell: {e}")

        if corrected and corrected.strip().lower() != query.strip().lower():
            corrected_hits, _ = await SEARCH.quick_search(
                corrected, is_series=True,
            )
            if corrected_hits:
                await status.edit_text(
                    "\n".join([
                        f"🔤 <b>{F.fb('CORRECTED')}</b>",
                        f"📌 <code>{F.sc(query[:40])}</code> → "
                        f"<code>{F.sc(corrected[:40])}</code>",
                    ]),
                    parse_mode=ParseMode.HTML,
                )
                await _start_wizard(
                    client, status, corrected,
                    corrected_hits, cfg, uid, chat_id,
                )
                return

    # ── 3. Suggestions ──
    if await SFLOW.is_step_enabled(chat_id, "suggestions"):
        try:
            items = await SUGG.suggestions(
                query, kind="series", limit=int(cfg.get("suggestion_count", 6)),
            )
        except Exception as e:
            logger.debug(f"[SERIES-H] suggestions: {e}")
            items = []

        if items:
            await _show_suggestions(
                client, status, query, items, uid, chat_id,
            )
            return

    # ── 4. Request prompt ──
    await _show_request_prompt(client, status, query)


# ============================================================
# SECTION 6 — WIZARD START
# ============================================================

async def _start_wizard(
    client: Client,
    target: Message,
    query: str,
    hits: List[Dict[str, Any]],
    cfg: Dict[str, Any],
    uid: int,
    chat_id: int,
) -> None:
    """
    Begin the wizard with hits already in hand.
    First step depends on which are enabled.
    """
    # Store in wizard session
    _wiz_new(
        uid=uid,
        chat_id=chat_id,
        query=query,
        hits=hits,
    )

    # Which steps are enabled?
    step_order = await SFLOW.get_enabled_steps(chat_id)

    # Skip to first actual step
    for step in step_order:
        if step in ("base_search", "spell_check", "suggestions"):
            continue
        if step == "language":
            return await _render_language(client, target, uid)
        if step == "season":
            return await _render_season(client, target, uid)
        if step == "episode":
            return await _render_episode(client, target, uid)
        if step == "quality":
            return await _render_quality(client, target, uid)
        if step == "file_delivery":
            return await _render_delivery(client, target, uid)

    # Nothing to do → deliver
    await _render_delivery(client, target, uid)


# ============================================================
# SECTION 7 — LANGUAGE STEP
# ============================================================

async def _render_language(
    client: Client,
    target: Message,
    uid: int,
) -> None:
    s = _wiz_get(uid)
    if not s:
        return
    hits = s.get("hits") or []
    query = s.get("query") or "?"
    chat_id = s["chat_id"]

    # Local languages from hits
    local: List[str] = []
    for h in hits:
        for l in (h.get("audio_languages") or []):
            n = str(l).strip().title()
            if n and n not in local:
                local.append(n)

    # TMDB languages
    tmdb_langs: List[str] = []
    try:
        tmdb_langs = await STMDB.get_series_languages(query)
    except Exception as e:
        logger.debug(f"[SERIES-H] tmdb langs: {e}")

    # Merge
    ordered: List[str] = []
    for l in local:
        if l not in ordered:
            ordered.append(l)
    for l in tmdb_langs:
        if l not in ordered:
            ordered.append(l)
    if not ordered:
        ordered = ["English", "Hindi", "Tamil", "Telugu", "Malayalam"]

    _wiz_set(uid,
             ordered_langs=ordered,
             local_langs=local,
             step="language")

    # Auto-skip
    auto_skip = await SFLOW.is_auto_skip(chat_id, "language")
    if len(ordered) == 1 and auto_skip:
        _wiz_set(uid, selected_language=ordered[0])
        return await _render_season(client, target, uid)

    # Render
    per_row = await SFLOW.get_per_row(chat_id, "language")
    text = "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"🌍 <b>{F.fb('PICK LANGUAGE')}</b>",
        F.DIV, "",
        f"🎬 <b>{F.sc(str(query)[:50])}</b>",
        "",
        f"🟢 ʜᴀꜱ ꜰɪʟᴇꜱ   ⚪ ᴛᴍᴅʙ ᴏɴʟʏ",
        "",
        f"ᴛᴀᴘ ᴀ ʟᴀɴɢᴜᴀɢᴇ:",
    ])

    rows: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []
    for i, l in enumerate(ordered[:12]):
        icon = "🟢" if l in local else "⚪"
        row.append(InlineKeyboardButton(
            f"{icon} {l}",
            callback_data=f"sgw:lang:{i}",
        ))
        if len(row) >= per_row:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    rows.append([InlineKeyboardButton(
        f"{F.EMO['cross']} {F.sc('cancel')}",
        callback_data="sgw:close",
    )])

    await _edit_or_send(target, text, InlineKeyboardMarkup(rows))


# ============================================================
# SECTION 8 — SEASON STEP
# ============================================================

async def _render_season(
    client: Client,
    target: Message,
    uid: int,
) -> None:
    s = _wiz_get(uid)
    if not s:
        return
    hits = s.get("hits") or []
    query = s.get("query") or "?"
    lang = s.get("selected_language")
    chat_id = s["chat_id"]

    # Filter hits by language
    filtered = SEARCH.filter_by_language(hits, lang) if lang else hits

    # Local seasons map
    local_seasons: Dict[int, List[int]] = {}
    for h in filtered:
        sn = h.get("season")
        ep = h.get("episode")
        if sn is None:
            continue
        try:
            sn_int = int(sn)
        except (TypeError, ValueError):
            continue
        local_seasons.setdefault(sn_int, [])
        if ep is not None:
            try:
                local_seasons[sn_int].append(int(ep))
            except (TypeError, ValueError):
                pass

    # TMDB seasons
    tmdb_seasons: List[Dict[str, Any]] = []
    try:
        tmdb_seasons = await STMDB.get_series_seasons(query)
    except Exception as e:
        logger.debug(f"[SERIES-H] tmdb seasons: {e}")

    # If neither source has seasons → not a series
    if not tmdb_seasons and not local_seasons:
        # No season info — skip to quality
        return await _render_quality(client, target, uid)

    _wiz_set(uid,
             filtered_hits=filtered,
             tmdb_seasons=tmdb_seasons,
             local_seasons=local_seasons,
             step="season")

    total_seasons = max(len(tmdb_seasons), len(local_seasons))

    # Auto-skip
    auto_skip = await SFLOW.is_auto_skip(chat_id, "season")
    if total_seasons == 1 and auto_skip:
        if tmdb_seasons:
            sn = tmdb_seasons[0].get("season")
        else:
            sn = next(iter(sorted(local_seasons)))
        _wiz_set(uid, selected_season=int(sn))
        return await _render_episode(client, target, uid)

    # Icons per season
    def icon_for(sn: int, tmdb_eps: int) -> str:
        eps = local_seasons.get(sn, [])
        count = len([e for e in eps if e > 0])
        if count == 0:
            return "⚪"
        if tmdb_eps and count >= tmdb_eps:
            return "🟢"
        return "🟡"

    text = "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"📺 <b>{F.fb('PICK SEASON')}</b>",
        F.DIV, "",
        f"🎬 <b>{F.sc(str(query)[:50])}</b>",
        f"🔊 <code>{F.sc(lang or '—')}</code>",
        "",
        f"🟢 ꜰᴜʟʟ · 🟡 ᴘᴀʀᴛɪᴀʟ · ⚪ ᴍɪꜱꜱɪɴɢ",
    ])

    per_row = await SFLOW.get_per_row(chat_id, "season")
    rows: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []

    tmdb_season_nums = {int(t.get("season") or 0) for t in tmdb_seasons}

    for t in tmdb_seasons:
        sn = int(t.get("season") or 0)
        eps = int(t.get("episodes") or 0)
        icon = icon_for(sn, eps)
        label = f"{icon} S{sn:02d}"
        if eps:
            label += f" · {eps}ᴱ"
        row.append(InlineKeyboardButton(
            label,
            callback_data=f"sgw:seas:{sn}",
        ))
        if len(row) >= per_row:
            rows.append(row)
            row = []

    # Local-only seasons
    for sn in sorted(local_seasons.keys()):
        if sn in tmdb_season_nums:
            continue
        count = len([e for e in local_seasons[sn] if e > 0])
        row.append(InlineKeyboardButton(
            f"🟢 S{sn:02d} · {count}ᴱ",
            callback_data=f"sgw:seas:{sn}",
        ))
        if len(row) >= per_row:
            rows.append(row)
            row = []

    if row:
        rows.append(row)

    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data="sgw:back:language",
        ),
        InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('cancel')}",
            callback_data="sgw:close",
        ),
    ])

    await _edit_or_send(target, text, InlineKeyboardMarkup(rows))


# ============================================================
# SECTION 9 — EPISODE STEP
# ============================================================

async def _render_episode(
    client: Client,
    target: Message,
    uid: int,
) -> None:
    s = _wiz_get(uid)
    if not s:
        return
    query = s.get("query") or "?"
    season = s.get("selected_season")
    if season is None:
        return await _render_quality(client, target, uid)

    chat_id = s["chat_id"]
    filtered = s.get("filtered_hits") or s.get("hits") or []

    # Local episodes for this season
    local_eps = SEARCH.unique_episodes(filtered, season=season)
    if not local_eps:
        local_eps = []

    # TMDB episodes
    tmdb_eps: List[int] = []
    try:
        tmdb_eps = await STMDB.get_season_episodes(query, season)
    except Exception as e:
        logger.debug(f"[SERIES-H] tmdb eps: {e}")

    all_eps = sorted(set(tmdb_eps) | set(local_eps))
    if not all_eps:
        # No episode info → skip to quality
        return await _render_quality(client, target, uid)

    _wiz_set(uid,
             season_episodes=all_eps,
             local_eps=local_eps,
             step="episode")

    # Auto-skip
    auto_skip = await SFLOW.is_auto_skip(chat_id, "episode")
    if len(all_eps) == 1 and auto_skip:
        _wiz_set(uid, selected_episode=all_eps[0])
        return await _render_quality(client, target, uid)

    text = "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"🎞️ <b>{F.fb('PICK EPISODE')}</b>",
        F.DIV, "",
        f"🎬 <b>{F.sc(str(query)[:50])}</b>",
        f"📺 S{int(season):02d} · {len(all_eps)} ᴇᴘɪꜱᴏᴅᴇꜱ",
        "",
        f"🟢 ᴀᴠᴀɪʟᴀʙʟᴇ · ⚪ ᴍɪꜱꜱɪɴɢ",
    ])

    per_row = await SFLOW.get_per_row(chat_id, "episode")
    rows: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []

    for ep in all_eps:
        icon = "🟢" if ep in local_eps else "⚪"
        row.append(InlineKeyboardButton(
            f"{icon} E{ep:02d}",
            callback_data=f"sgw:ep:{ep}",
        ))
        if len(row) >= per_row:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data="sgw:back:season",
        ),
        InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('cancel')}",
            callback_data="sgw:close",
        ),
    ])

    await _edit_or_send(target, text, InlineKeyboardMarkup(rows))


# ============================================================
# SECTION 10 — QUALITY STEP
# ============================================================

async def _render_quality(
    client: Client,
    target: Message,
    uid: int,
) -> None:
    s = _wiz_get(uid)
    if not s:
        return
    query = s.get("query") or "?"
    season = s.get("selected_season")
    episode = s.get("selected_episode")
    chat_id = s["chat_id"]
    filtered = s.get("filtered_hits") or s.get("hits") or []

    # Filter hits to season+episode
    f = filtered
    if season is not None:
        f = SEARCH.filter_by_season(f, season)
    if episode is not None:
        f2 = SEARCH.filter_by_episode(f, episode)
        if f2:
            f = f2

    qualities = SEARCH.unique_qualities(f)

    if not qualities:
        # No quality info → straight to delivery
        _wiz_set(uid, step="quality", final_hits=f)
        return await _render_delivery(client, target, uid)

    _wiz_set(uid,
             available_qualities=qualities,
             final_hits=f,
             step="quality")

    auto_skip = await SFLOW.is_auto_skip(chat_id, "quality")
    if len(qualities) == 1 and auto_skip:
        _wiz_set(uid, selected_quality=qualities[0])
        return await _render_delivery(client, target, uid)

    text = "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"🎯 <b>{F.fb('PICK QUALITY')}</b>",
        F.DIV, "",
        f"🎬 <b>{F.sc(str(query)[:50])}</b>",
        *(
            [f"📺 S{int(season):02d}E{int(episode):02d}"]
            if season is not None and episode is not None
            else []
        ),
    ])

    per_row = await SFLOW.get_per_row(chat_id, "quality")
    rows: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []

    for q in qualities[:8]:
        row.append(InlineKeyboardButton(
            f"🎯 {q}",
            callback_data=f"sgw:qual:{q}",
        ))
        if len(row) >= per_row:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data="sgw:back:episode",
        ),
        InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('cancel')}",
            callback_data="sgw:close",
        ),
    ])

    await _edit_or_send(target, text, InlineKeyboardMarkup(rows))


# ============================================================
# SECTION 11 — DELIVERY (build deliver token + deep link)
# ============================================================

async def _render_delivery(
    client: Client,
    target: Message,
    uid: int,
) -> None:
    s = _wiz_get(uid)
    if not s:
        return

    query = s.get("query") or "?"
    season = s.get("selected_season")
    quality = s.get("selected_quality")
    language = s.get("selected_language") or ""
    chat_id = s["chat_id"]
    hits = s.get("final_hits") or s.get("filtered_hits") or s.get("hits") or []

    # If a quality was selected, filter to it
    if quality:
        hits_q = SEARCH.filter_by_quality(hits, quality)
        if hits_q:
            hits = hits_q

    # If a season was selected, filter to it
    if season is not None:
        hits_s = SEARCH.filter_by_season(hits, season)
        if hits_s:
            hits = hits_s

    # Sort small → big
    hits = SEARCH.sort_hits(hits, mode="small_to_big")

    if not hits:
        return await _show_request_prompt(client, target, query)

    # Create deliver token
    token = await DL.create_deliver_token(
        user_id=uid,
        chat_id=chat_id,
        title=query,
        season=int(season or 0),
        quality=str(quality or "UNKNOWN"),
        language=str(language),
        hits=hits,
    )
    if not token:
        return await _edit_status(
            target, "❌ token error",
        )

    # Build deep-link
    bot_username = ""
    try:
        me = await client.identity()
        bot_username = me.username or ""
    except Exception:
        pass

    if not bot_username:
        return await _edit_status(target, "❌ bot username missing")

    deep_link = f"https://t.me/{bot_username}?start=deliver_{token}"

    text = "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"{F.EMO['rocket']} <b>{F.fb('READY TO DELIVER')}</b>",
        F.DIV, "",
        f"🎬 <b>{F.sc(str(query)[:50])}</b>",
        *(
            [f"📺 <b>Season {int(season):02d}</b>"]
            if season else []
        ),
        *(
            [f"🎯 <code>{quality}</code>"]
            if quality else []
        ),
        *(
            [f"🔊 <code>{language}</code>"]
            if language else []
        ),
        "",
        f"📁 <b>{len(hits)}</b> ꜰɪʟᴇꜱ",
        "",
        f"📌 ᴛᴀᴘ ᴛʜᴇ ʙᴜᴛᴛᴏɴ ᴛᴏ ʀᴇᴄᴇɪᴠᴇ ɪɴ ᴘᴍ",
    ])

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"{F.EMO['rocket']} {F.sc('open bot pm')}",
            url=deep_link,
        )],
        [InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('cancel')}",
            callback_data="sgw:close",
        )],
    ])

    _wiz_drop(uid)
    await _edit_or_send(target, text, kb)


# ============================================================
# SECTION 12 — SUGGESTIONS (mirrors movie handler)
# ============================================================

async def _show_suggestions(
    client: Client,
    target: Message,
    query: str,
    items: List[Dict[str, Any]],
    uid: int,
    chat_id: int,
) -> None:
    stored = [SUGG.to_dict(x) for x in items if x]
    stored = [s for s in stored if s.get("title")]
    if not stored:
        return await _show_request_prompt(client, target, query)

    sid = await DELIVERY.create_session(
        user_id=uid,
        chat_id=chat_id,
        query=query,
        hits=[],
    )
    if not sid:
        return await _edit_status(target, "❌ session error")

    try:
        from media_search import sessions as _sess_mod
        await _sess_mod.sessions.update(sid, candidates=stored)
    except Exception:
        pass

    text = "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"{F.EMO['search']} <b>{F.fb('DID YOU MEAN?')}</b>",
        F.DIV, "",
        f"🔍 <code>{F.sc(query[:50])}</code>",
        "",
        f"📌 {F.sc('tap a title below')}",
    ])

    rows: List[List[InlineKeyboardButton]] = []
    for i, s in enumerate(stored[:8]):
        title = str(s.get("title") or "?")[:34]
        year = s.get("year")
        rating = s.get("rating") or 0
        label = f"📺 {title}"
        if year:
            label += f" ({year})"
        if rating:
            label += f" · ⭐{rating:.1f}"
        if len(label) > 60:
            label = label[:57] + "…"
        rows.append([InlineKeyboardButton(
            label,
            callback_data=f"sr:sug:{sid}:{i}",
        )])

    rows.append([InlineKeyboardButton(
        f"🔍 {F.sc('search on google')}",
        url=f"https://www.google.com/search?q={query}",
    )])
    rows.append([InlineKeyboardButton(
        f"{F.EMO['cross']} {F.sc('close')}",
        callback_data="sr:cancel",
    )])

    await _edit_or_send(target, text, InlineKeyboardMarkup(rows))


# ============================================================
# SECTION 13 — REQUEST PROMPT
# ============================================================

async def _show_request_prompt(
    client: Client,
    target: Message,
    query: str,
) -> None:
    try:
        uid = target.from_user.id if target.from_user else 0
        u = target.from_user
        username = u.username if u else ""
        full_name = u.first_name if u else ""

        token = await RF.create_deferred_request(
            user_id=uid,
            username=username or "",
            full_name=full_name or "",
            title=query,
            year=None,
            kind="series",
            tmdb_id=None,
        )
        if not token:
            return await _edit_status(
                target,
                "\n".join([
                    f"{F.EMO['cross']} <b>{F.fb('NO RESULTS')}</b>",
                    F.DIV, "",
                    f"🔍 <code>{F.sc(query[:50])}</code>",
                    f"📌 {F.sc('try a different spelling')}",
                ]),
            )

        bot_username = ""
        try:
            me = await client.identity()
            bot_username = me.username or ""
        except Exception:
            pass

        if not bot_username:
            return await _edit_status(
                target,
                f"{F.EMO['cross']} {F.sc('no results')}",
            )

        deep_link = f"https://t.me/{bot_username}?start=req_{token}"

        text = "\n".join([
            f"{F.EMO['warn']} <b>{F.fb('NOT IN OUR DATABASE')}</b>",
            F.DIV, "",
            f"📺 <b>{F.sc(query[:60])}</b>",
            "",
            f"📌 {F.sc('tap below to send a request')}",
        ])

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                f"{F.EMO['rocket']} {F.sc('send request')}",
                url=deep_link,
            )],
            [InlineKeyboardButton(
                f"{F.EMO['cross']} {F.sc('close')}",
                callback_data="sr:cancel",
            )],
        ])

        await _edit_or_send(target, text, kb)

    except Exception as e:
        logger.exception(f"[SERIES-H] request prompt: {e}")


# ============================================================
# SECTION 14 — CALLBACK ROUTER (sgw:*)
# ============================================================

@Client.on_callback_query(
    filters.regex(r"^sgw:"),
    group=-9999,
)
async def series_wizard_router(client: Client, q: CallbackQuery):
    if not q.from_user:
        return await q.answer()

    uid = q.from_user.id
    parts = str(q.data).split(":")
    action = parts[1] if len(parts) > 1 else ""

    try:
        # ── CLOSE ──
        if action == "close":
            _wiz_drop(uid)
            try:
                await q.message.delete()
            except Exception:
                pass
            return await q.answer("❌")

        s = _wiz_get(uid)
        if not s:
            return await q.answer("⏱️ Session expired", show_alert=True)

        # ── LANGUAGE PICK ──
        if action == "lang":
            try:
                idx = int(parts[2])
            except (ValueError, IndexError):
                return await q.answer("❌")
            ordered = s.get("ordered_langs") or []
            if idx < 0 or idx >= len(ordered):
                return await q.answer("❌")
            _wiz_set(uid, selected_language=ordered[idx])
            await q.answer(f"🌍 {ordered[idx]}")
            return await _render_season(client, q.message, uid)

        # ── SEASON PICK ──
        if action == "seas":
            try:
                sn = int(parts[2])
            except (ValueError, IndexError):
                return await q.answer("❌")
            _wiz_set(uid, selected_season=sn)
            await q.answer(f"📺 S{sn:02d}")
            return await _render_episode(client, q.message, uid)

        # ── EPISODE PICK ──
        if action == "ep":
            try:
                ep = int(parts[2])
            except (ValueError, IndexError):
                return await q.answer("❌")
            _wiz_set(uid, selected_episode=ep)
            await q.answer(f"🎞️ E{ep:02d}")
            return await _render_quality(client, q.message, uid)

        # ── QUALITY PICK ──
        if action == "qual":
            quality = parts[2] if len(parts) > 2 else ""
            if not quality:
                return await q.answer("❌")
            _wiz_set(uid, selected_quality=quality)
            await q.answer(f"🎯 {quality}")
            return await _render_delivery(client, q.message, uid)

        # ── BACK ──
        if action == "back":
            target_step = parts[2] if len(parts) > 2 else "language"
            if target_step == "language":
                return await _render_language(client, q.message, uid)
            if target_step == "season":
                return await _render_season(client, q.message, uid)
            if target_step == "episode":
                return await _render_episode(client, q.message, uid)
            if target_step == "quality":
                return await _render_quality(client, q.message, uid)
            return await q.answer()

        return await q.answer("❓")

    except Exception as e:
        logger.exception(f"[SERIES-H] wizard callback: {e}")
        try:
            await q.answer("❌ error", show_alert=True)
        except Exception:
            pass


# ============================================================
# SECTION 15 — HELPERS
# ============================================================

async def _edit_or_send(
    target: Message,
    text: str,
    kb: InlineKeyboardMarkup,
) -> None:
    try:
        await target.edit_text(
            text[:4000],
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        if "not modified" not in str(e).lower():
            logger.debug(f"[SERIES-H] edit: {e}")


async def _edit_status(target: Message, text: str) -> None:
    try:
        await target.edit_text(
            text[:4000],
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        if "not modified" not in str(e).lower():
            logger.debug(f"[SERIES-H] status: {e}")


# ============================================================
# SECTION 15b — PREMIUM REDIRECT
# ============================================================

async def _is_user_premium(uid: int) -> bool:
    """True if user has active premium."""
    try:
        from plugins.premium import state as PS
        return await PS.is_premium(uid)
    except Exception:
        return False


async def _try_premium_redirect(
    client: Client,
    message: Message,
    status: Message,
    query: str,
    hits: List[Dict[str, Any]],
    uid: int,
    chat_id: int,
) -> bool:
    """
    Create premium token + send deep-link.
    Returns True on success, False → fall through to wizard.
    """
    try:
        import re as _re
        from plugins.groups.shared import deep_link as DL

        title = (
            hits[0].get("series_title")
            or hits[0].get("title")
            or query
        )
        slug = _re.sub(r"[^a-z0-9]+", "_", str(title).lower()).strip("_")

        token = await DL.create_premium_token(
            user_id=uid,
            chat_id=chat_id,
            title=str(title)[:200],
            slug=slug[:100],
            tmdb_id=None,
            hits=hits,
        )
        if not token:
            return False

        # Bot username
        bot_username = ""
        try:
            me = await client.identity()
            bot_username = me.username or ""
        except Exception:
            pass
        if not bot_username:
            return False

        deep_link = f"https://t.me/{bot_username}?start=prem_{token}"

        text = "\n".join([
            f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
            f"{F.EMO['crown']} <b>{F.fb('PREMIUM MODE')}</b>",
            F.DIV, "",
            f"🎬 <b>{F.sc(str(title)[:50])}</b>",
            f"📦 {len(hits)} ꜰɪʟᴇꜱ ꜰᴏᴜɴᴅ",
            "",
            F.DIV_S,
            f"{F.EMO['spark']} ᴘʀᴇᴍɪᴜᴍ ᴜꜱᴇʀꜱ ɢᴇᴛ:",
            f"✅ ᴡᴀᴛᴄʜᴇᴅ ʟɪꜱᴛ",
            f"✅ ɴᴇxᴛ ᴇᴘɪꜱᴏᴅᴇ",
            f"✅ ᴡᴀᴛᴄʜ ᴏʀᴅᴇʀ",
            f"✅ ᴘʀᴏɢʀᴇꜱꜱ ᴛʀᴀᴄᴋɪɴɢ",
            "",
            f"📌 ᴛᴀᴘ ᴛᴏ ᴏᴘᴇɴ ɪɴ ᴘᴍ",
        ])

        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton(
                f"{F.EMO['rocket']} {F.sc('open premium watch')}",
                url=deep_link,
            )],
            [InlineKeyboardButton(
                f"{F.EMO['cross']} {F.sc('cancel')}",
                callback_data="sr:cancel",
            )],
        ])

        try:
            await status.edit_text(
                text,
                reply_markup=kb,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except Exception:
            pass
        return True

    except Exception as e:
        logger.exception(f"[SERIES-H] premium redirect: {e}")
        return False
        
# ============================================================
# SECTION 15c — STEP-GATING TRANSITION
# ============================================================

async def _goto_step(
    client: Client,
    target: Message,
    uid: int,
    step_key: str,
) -> None:
    """
    Render `step_key` if enabled, else jump to next enabled step.
    Recursively walks forward until it finds an enabled step.
    """
    s = _wiz_get(uid)
    if not s:
        return
    chat_id = s["chat_id"]

    # Hard-stop guard
    if step_key in ("close", "done", ""):
        return

    # If this step is enabled → render it
    enabled = await SFLOW.is_step_enabled(chat_id, step_key)
    if enabled:
        if step_key == "language":
            return await _render_language(client, target, uid)
        if step_key == "season":
            return await _render_season(client, target, uid)
        if step_key == "episode":
            return await _render_episode(client, target, uid)
        if step_key == "quality":
            return await _render_quality(client, target, uid)
        if step_key == "file_delivery":
            return await _render_delivery(client, target, uid)

    # Disabled → find next in order
    order = await SFLOW.get_step_order(chat_id)
    try:
        idx = order.index(step_key)
    except ValueError:
        idx = -1

    for next_step in order[idx + 1:]:
        if next_step in ("base_search", "spell_check", "suggestions"):
            continue
        return await _goto_step(client, target, uid, next_step)

    # No more steps → deliver
    return await _render_delivery(client, target, uid)

# ============================================================
# SECTION 16 — PUBLIC EXPORTS
# ============================================================

def snapshot() -> Dict[str, Any]:
    return {
        "module": "groups.series.handler",
        "wizard_sessions": len(_wizard),
        "cooldown_tracked": len(_last_seen),
    }


__all__ = [
    "series_group_entry",
    "series_wizard_router",
    "snapshot",
]
