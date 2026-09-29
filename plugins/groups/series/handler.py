# ============================================================
# 🏨 DOWNTOWN VILLA — SERIES GROUP HANDLER (FINAL)
# ============================================================
# Quality pick → URL button → user taps → /start deliver_XXX → files
# Works for both new and existing users (V1 style)
# ============================================================

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

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
from plugins.groups.series import flow as SFLOW
from plugins.groups.series import tmdb as STMDB
from utils import fonts as F
from utils import format as FM

logger = logging.getLogger(__name__)

COOLDOWN = 3.0
MIN_QUERY_LEN = 2
MAX_QUERY_LEN = 100
WIZARD_TTL = 900.0

_last_seen: Dict[int, float] = {}
_wizard: Dict[int, Dict[str, Any]] = {}


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
    s = _wizard.get(uid)
    if not s:
        return
    s.update(data)
    s["expires"] = time.time() + WIZARD_TTL


def _wiz_drop(uid: int) -> None:
    _wizard.pop(int(uid), None)


# ============================================================
# ENTRY
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

        series_gid = getattr(config, "SERIES_GROUP_ID", None)
        if not series_gid:
            return
        if int(message.chat.id) != int(series_gid):
            return

        txt = (message.text or "").strip()
        if len(txt) < MIN_QUERY_LEN or len(txt) > MAX_QUERY_LEN:
            return
        low = txt.lower()
        if "http://" in low or "https://" in low or "t.me/" in low:
            return
        if txt.startswith("/"):
            return

        chat_id = message.chat.id
        cfg = await S.get_config(chat_id)

        if not cfg.get("enabled", True):
            return
        if not cfg.get("search_enabled", True):
            return

        uid = message.from_user.id
        if not _cooldown_ok(uid):
            return
        _cleanup_cooldown()

        try:
            message.stop_propagation()
        except Exception:
            pass

        try:
            status = await message.reply_text("🔎 ꜱᴇᴀʀᴄʜɪɴɢ…")
        except Exception:
            return

        try:
            await S.bump_stat(chat_id, "searches_today")
        except Exception:
            pass

        await _run_pipeline(client, message, status, txt, cfg, uid, chat_id)

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


# ============================================================
# PIPELINE
# ============================================================

async def _run_pipeline(client, message, status, query, cfg, uid, chat_id):
    hits, complete = await SEARCH.quick_search(query, is_series=True)

    if hits:
        if await _is_user_premium(uid):
            if await _try_premium_redirect(
                client, message, status, query, hits, uid, chat_id,
            ):
                return
        await _start_wizard(client, status, query, hits, cfg, uid, chat_id)
        return

    if not complete:
        await _edit_status(status, f"{F.EMO['warn']} DBs unreachable")
        return

    if await SFLOW.is_step_enabled(chat_id, "spell_check"):
        corrected = None
        try:
            corrected = await SUGG.ai_spell_check_for_group(
                chat_id, query, is_series=True,
            )
        except Exception:
            pass

        if corrected and corrected.strip().lower() != query.strip().lower():
            ch, _ = await SEARCH.quick_search(corrected, is_series=True)
            if ch:
                await status.edit_text(
                    f"🔤 corrected → <code>{F.sc(corrected[:40])}</code>",
                    parse_mode=ParseMode.HTML,
                )
                await _start_wizard(
                    client, status, corrected, ch, cfg, uid, chat_id,
                )
                return

    if await SFLOW.is_step_enabled(chat_id, "suggestions"):
        try:
            items = await SUGG.get_suggestions_for_group(
                chat_id, query, kind="series",
            )
        except Exception:
            items = []
        if items:
            await _show_suggestions(
                client, status, query, items, uid, chat_id,
            )
            return

    await _show_request_prompt(client, status, query)


# ============================================================
# WIZARD
# ============================================================

async def _start_wizard(client, target, query, hits, cfg, uid, chat_id):
    _wiz_new(uid=uid, chat_id=chat_id, query=query, hits=hits)
    wizard_steps = await SFLOW.get_wizard_steps(chat_id)
    if not wizard_steps:
        return await _render_delivery(client, target, uid)
    return await _goto_step(client, target, uid, wizard_steps[0])


async def _goto_step(client, target, uid, step_key):
    s = _wiz_get(uid)
    if not s:
        return
    chat_id = s["chat_id"]

    if step_key in ("close", "done", ""):
        return

    if await SFLOW.is_step_enabled(chat_id, step_key):
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

    order = await SFLOW.get_step_order(chat_id)
    try:
        idx = order.index(step_key)
    except ValueError:
        idx = -1

    for next_step in order[idx + 1:]:
        if next_step in ("base_search", "spell_check", "suggestions"):
            continue
        return await _goto_step(client, target, uid, next_step)

    return await _render_delivery(client, target, uid)


# ============================================================
# LANGUAGE
# ============================================================

async def _render_language(client, target, uid):
    s = _wiz_get(uid)
    if not s:
        return
    hits = s.get("hits") or []
    query = s.get("query") or "?"
    chat_id = s["chat_id"]

    local = []
    for h in hits:
        for l in (h.get("audio_languages") or []):
            n = str(l).strip().title()
            if n and n not in local:
                local.append(n)

    tmdb_langs = []
    try:
        tmdb_langs = await STMDB.get_series_languages(query)
    except Exception:
        pass

    ordered = []
    for l in local:
        if l not in ordered:
            ordered.append(l)
    for l in tmdb_langs:
        if l not in ordered:
            ordered.append(l)
    if not ordered:
        ordered = ["English", "Hindi", "Tamil", "Telugu", "Malayalam"]

    _wiz_set(uid, ordered_langs=ordered, local_langs=local, step="language")

    auto_skip = await SFLOW.is_auto_skip(chat_id, "language")
    if len(ordered) == 1 and auto_skip:
        _wiz_set(uid, selected_language=ordered[0])
        return await _goto_step(client, target, uid, "season")

    per_row = await SFLOW.get_per_row(chat_id, "language")
    max_items = await SFLOW.get_max_items(chat_id, "language", 12)

    text = "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"🌍 <b>{F.fb('PICK LANGUAGE')}</b>",
        F.DIV, "",
        f"🎬 <b>{F.sc(str(query)[:50])}</b>",
        "",
        f"🟢 ʜᴀꜱ ꜰɪʟᴇꜱ   ⚪ ᴛᴍᴅʙ ᴏɴʟʏ",
    ])

    rows = []
    row = []
    for i, l in enumerate(ordered[:max_items]):
        icon = "🟢" if l in local else "⚪"
        row.append(InlineKeyboardButton(
            f"{icon} {l}", callback_data=f"sgw:lang:{i}"))
        if len(row) >= per_row:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(
        f"{F.EMO['cross']} {F.sc('cancel')}",
        callback_data="sgw:close")])

    await _edit_or_send(target, text, InlineKeyboardMarkup(rows))


# ============================================================
# SEASON
# ============================================================

async def _render_season(client, target, uid):
    s = _wiz_get(uid)
    if not s:
        return
    hits = s.get("hits") or []
    query = s.get("query") or "?"
    lang = s.get("selected_language")
    chat_id = s["chat_id"]

    filtered = SEARCH.filter_by_language(hits, lang) if lang else hits

    local_seasons = {}
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

    tmdb_seasons = []
    try:
        tmdb_seasons = await STMDB.get_series_seasons(query)
    except Exception:
        pass

    if not tmdb_seasons and not local_seasons:
        return await _goto_step(client, target, uid, "quality")

    _wiz_set(uid,
             filtered_hits=filtered,
             tmdb_seasons=tmdb_seasons,
             local_seasons=local_seasons,
             step="season")

    total_seasons = max(len(tmdb_seasons), len(local_seasons))

    auto_skip = await SFLOW.is_auto_skip(chat_id, "season")
    if total_seasons == 1 and auto_skip:
        if tmdb_seasons:
            sn = tmdb_seasons[0].get("season")
        else:
            sn = next(iter(sorted(local_seasons)))
        _wiz_set(uid, selected_season=int(sn))
        return await _goto_step(client, target, uid, "episode")

    def icon_for(sn, tmdb_eps):
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
    max_items = await SFLOW.get_max_items(chat_id, "season", 12)

    rows = []
    row = []
    tmdb_season_nums = {int(t.get("season") or 0) for t in tmdb_seasons}

    for t in tmdb_seasons[:max_items]:
        sn = int(t.get("season") or 0)
        eps = int(t.get("episodes") or 0)
        icon = icon_for(sn, eps)
        label = f"{icon} S{sn:02d}"
        if eps:
            label += f" · {eps}ᴱ"
        row.append(InlineKeyboardButton(
            label, callback_data=f"sgw:seas:{sn}"))
        if len(row) >= per_row:
            rows.append(row)
            row = []

    for sn in sorted(local_seasons.keys()):
        if sn in tmdb_season_nums:
            continue
        count = len([e for e in local_seasons[sn] if e > 0])
        row.append(InlineKeyboardButton(
            f"🟢 S{sn:02d} · {count}ᴱ",
            callback_data=f"sgw:seas:{sn}"))
        if len(row) >= per_row:
            rows.append(row)
            row = []

    if row:
        rows.append(row)

    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data="sgw:back:language"),
        InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('cancel')}",
            callback_data="sgw:close"),
    ])

    await _edit_or_send(target, text, InlineKeyboardMarkup(rows))


# ============================================================
# EPISODE
# ============================================================

async def _render_episode(client, target, uid):
    s = _wiz_get(uid)
    if not s:
        return
    query = s.get("query") or "?"
    season = s.get("selected_season")
    if season is None:
        return await _goto_step(client, target, uid, "quality")

    chat_id = s["chat_id"]
    filtered = s.get("filtered_hits") or s.get("hits") or []
    local_eps = SEARCH.unique_episodes(filtered, season=season) or []

    tmdb_eps = []
    try:
        tmdb_eps = await STMDB.get_season_episodes(query, season)
    except Exception:
        pass

    all_eps = sorted(set(tmdb_eps) | set(local_eps))
    if not all_eps:
        return await _goto_step(client, target, uid, "quality")

    _wiz_set(uid, season_episodes=all_eps, local_eps=local_eps, step="episode")

    auto_skip = await SFLOW.is_auto_skip(chat_id, "episode")
    if len(all_eps) == 1 and auto_skip:
        _wiz_set(uid, selected_episode=all_eps[0])
        return await _goto_step(client, target, uid, "quality")

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
    max_items = await SFLOW.get_max_items(chat_id, "episode", 30)

    rows = []
    row = []
    for ep in all_eps[:max_items]:
        icon = "🟢" if ep in local_eps else "⚪"
        row.append(InlineKeyboardButton(
            f"{icon} E{ep:02d}", callback_data=f"sgw:ep:{ep}"))
        if len(row) >= per_row:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data="sgw:back:season"),
        InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('cancel')}",
            callback_data="sgw:close"),
    ])

    await _edit_or_send(target, text, InlineKeyboardMarkup(rows))


# ============================================================
# QUALITY
# ============================================================

async def _render_quality(client, target, uid):
    s = _wiz_get(uid)
    if not s:
        return
    query = s.get("query") or "?"
    season = s.get("selected_season")
    episode = s.get("selected_episode")
    chat_id = s["chat_id"]
    filtered = s.get("filtered_hits") or s.get("hits") or []

    f = filtered
    if season is not None:
        f = SEARCH.filter_by_season(f, season)
    if episode is not None:
        f2 = SEARCH.filter_by_episode(f, episode)
        if f2:
            f = f2

    qualities = SEARCH.unique_qualities(f)

    if not qualities:
        _wiz_set(uid, step="quality", final_hits=f)
        return await _goto_step(client, target, uid, "file_delivery")

    _wiz_set(uid, available_qualities=qualities, final_hits=f, step="quality")

    auto_skip = await SFLOW.is_auto_skip(chat_id, "quality")
    if len(qualities) == 1 and auto_skip:
        _wiz_set(uid, selected_quality=qualities[0])
        return await _goto_step(client, target, uid, "file_delivery")

    text = "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"🎯 <b>{F.fb('PICK QUALITY')}</b>",
        F.DIV, "",
        f"🎬 <b>{F.sc(str(query)[:50])}</b>",
        *([f"📺 S{int(season):02d}E{int(episode):02d}"]
          if season is not None and episode is not None else []),
    ])

    per_row = await SFLOW.get_per_row(chat_id, "quality")
    max_items = await SFLOW.get_max_items(chat_id, "quality", 8)

    rows = []
    row = []
    for q in qualities[:max_items]:
        row.append(InlineKeyboardButton(
            f"🎯 {q}", callback_data=f"sgw:qual:{q}"))
        if len(row) >= per_row:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data="sgw:back:episode"),
        InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('cancel')}",
            callback_data="sgw:close"),
    ])

    await _edit_or_send(target, text, InlineKeyboardMarkup(rows))


# ============================================================
# DELIVERY — create token + show URL button
# ============================================================

async def _render_delivery(client, target, uid):
    s = _wiz_get(uid)
    if not s:
        return

    query = s.get("query") or "?"
    season = s.get("selected_season")
    quality = s.get("selected_quality")
    language = s.get("selected_language") or ""
    chat_id = s["chat_id"]
    hits = s.get("final_hits") or s.get("filtered_hits") or s.get("hits") or []

    if season is not None:
        hs = SEARCH.filter_by_season(hits, season)
        if hs:
            hits = hs
    if quality:
        hq = SEARCH.filter_by_quality(hits, quality)
        if hq:
            hits = hq

    episode = s.get("selected_episode")
    if episode is not None:
        he = SEARCH.filter_by_episode(hits, episode)
        if he:
            hits = he
        hits = sorted(hits, key=lambda x: int(x.get("file_size") or 0))[:1]
    else:
        by_ep = {}
        for h in hits:
            ep = h.get("episode")
            if ep is None:
                continue
            try:
                ep_int = int(ep)
            except (TypeError, ValueError):
                continue
            existing = by_ep.get(ep_int)
            if existing is None:
                by_ep[ep_int] = h
            else:
                cur_sz = int(existing.get("file_size") or 0)
                new_sz = int(h.get("file_size") or 0)
                if new_sz and (cur_sz == 0 or new_sz < cur_sz):
                    by_ep[ep_int] = h

        def _ep_num(h):
            try:
                return int(h.get("episode") or 0)
            except (TypeError, ValueError):
                return 0
        hits = sorted(by_ep.values(), key=_ep_num)

    if not hits:
        _wiz_drop(uid)
        await _show_request_prompt(client, target, query)
        return None

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
        _wiz_drop(uid)
        await _edit_status(target, "❌ token error")
        return None

    bot_username = ""
    try:
        me = await client.identity()
        bot_username = me.username or ""
    except Exception:
        try:
            me = await client.get_me()
            bot_username = me.username or ""
        except Exception:
            pass

    if not bot_username:
        _wiz_drop(uid)
        await _edit_status(target, "❌ bot username missing")
        return None

    deep_link = f"https://t.me/{bot_username}?start=deliver_{token}"
    logger.info(f"[SERIES-H] token={token} link={deep_link}")

    text = "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"{F.EMO['rocket']} <b>{F.fb('READY TO DELIVER')}</b>",
        F.DIV, "",
        f"🎬 <b>{F.sc(str(query)[:50])}</b>",
        *([f"📺 <b>Season {int(season):02d}</b>"] if season else []),
        *([f"🎯 <code>{quality}</code>"] if quality else []),
        *([f"🔊 <code>{language}</code>"] if language else []),
        "",
        f"📁 <b>{len(hits)}</b> ꜰɪʟᴇꜱ",
        "",
        f"📌 ᴛᴀᴘ ᴛʜᴇ ʙᴜᴛᴛᴏɴ ʙᴇʟᴏᴡ",
        f"📌 ꜰɪʟᴇꜱ ᴀʀʀɪᴠᴇ ɪɴ ᴘᴍ",
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
    return None


# ============================================================
# CALLBACK ROUTER
# ============================================================

@Client.on_callback_query(filters.regex(r"^sgw:"), group=-9999)
async def series_wizard_router(client, q: CallbackQuery):
    if not q.from_user:
        return await q.answer()

    uid = q.from_user.id
    parts = str(q.data).split(":")
    action = parts[1] if len(parts) > 1 else ""

    try:
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

        if action == "lang":
            idx = int(parts[2])
            ordered = s.get("ordered_langs") or []
            if 0 <= idx < len(ordered):
                _wiz_set(uid, selected_language=ordered[idx])
                await q.answer(f"🌍 {ordered[idx]}")
            return await _goto_step(client, q.message, uid, "season")

        if action == "seas":
            sn = int(parts[2])
            _wiz_set(uid, selected_season=sn)
            await q.answer(f"📺 S{sn:02d}")
            return await _goto_step(client, q.message, uid, "episode")

        if action == "ep":
            ep = int(parts[2])
            _wiz_set(uid, selected_episode=ep)
            await q.answer(f"🎞️ E{ep:02d}")
            return await _goto_step(client, q.message, uid, "quality")

        if action == "qual":
            quality = parts[2] if len(parts) > 2 else ""
            _wiz_set(uid, selected_quality=quality)
            await q.answer(f"🎯 {quality}")
            await _render_delivery(client, q.message, uid)
            return

        if action == "back":
            target_step = parts[2] if len(parts) > 2 else "language"
            return await _goto_step(client, q.message, uid, target_step)

        return await q.answer("❓")

    except Exception as e:
        logger.exception(f"[SERIES-H] wizard: {e}")
        try:
            await q.answer("❌ error", show_alert=True)
        except Exception:
            pass


# ============================================================
# PREMIUM
# ============================================================

async def _is_user_premium(uid):
    try:
        from plugins.premium import state as PS
        return await PS.is_premium(uid)
    except Exception:
        return False


async def _try_premium_redirect(client, message, status, query, hits, uid, chat_id):
    try:
        import re as _re
        title = hits[0].get("series_title") or hits[0].get("title") or query
        slug = _re.sub(r"[^a-z0-9]+", "_", str(title).lower()).strip("_")

        token = await DL.create_premium_token(
            user_id=uid, chat_id=chat_id,
            title=str(title)[:200], slug=slug[:100],
            tmdb_id=None, hits=hits,
        )
        if not token:
            return False

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
            "",
            f"📌 ᴛᴀᴘ ᴛᴏ ᴏᴘᴇɴ ɪɴ ᴘᴍ",
        ])
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton(
                f"{F.EMO['rocket']} {F.sc('open premium watch')}",
                url=deep_link),
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


# ============================================================
# SUGGESTIONS
# ============================================================

async def _show_suggestions(client, target, query, items, uid, chat_id):
    stored = [SUGG.to_dict(x) for x in items if x]
    stored = [s for s in stored if s.get("title")]
    if not stored:
        return await _show_request_prompt(client, target, query)

    sid = await DELIVERY.create_session(
        user_id=uid, chat_id=chat_id, query=query, hits=[],
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

    disp = await SFLOW.get_suggestion_display(chat_id)

    rows = []
    for i, s in enumerate(stored[:8]):
        title = str(s.get("title") or "?")[:34]
        year = s.get("year")
        rating = s.get("rating") or 0
        kind = str(s.get("kind") or "movie")

        label = ""
        if disp["show_icon"]:
            label += ("📺 " if kind == "series" else "🎬 ")
        label += title
        if disp["show_year"] and year:
            label += f" ({year})"
        if disp["show_rating"] and rating:
            label += f" · ⭐{rating:.1f}"
        if len(label) > 60:
            label = label[:57] + "…"

        rows.append([InlineKeyboardButton(
            label, callback_data=f"sr:sug:{sid}:{i}")])

    rows.append([InlineKeyboardButton(
        f"🔍 {F.sc('search on google')}",
        url=f"https://www.google.com/search?q={query}")])
    rows.append([InlineKeyboardButton(
        f"{F.EMO['cross']} {F.sc('close')}",
        callback_data="sr:cancel")])

    await _edit_or_send(target, text, InlineKeyboardMarkup(rows))


# ============================================================
# REQUEST
# ============================================================

async def _show_request_prompt(client, target, query):
    try:
        uid = target.from_user.id if target.from_user else 0
        u = target.from_user
        username = u.username if u else ""
        full_name = u.first_name if u else ""

        token = await RF.create_deferred_request(
            user_id=uid, username=username or "",
            full_name=full_name or "", title=query,
            year=None, kind="series", tmdb_id=None,
        )
        if not token:
            return await _edit_status(target, "❌ no results")

        bot_username = ""
        try:
            me = await client.identity()
            bot_username = me.username or ""
        except Exception:
            pass
        if not bot_username:
            return await _edit_status(target, "❌ no results")

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
                url=deep_link)],
            [InlineKeyboardButton(
                f"{F.EMO['cross']} {F.sc('close')}",
                callback_data="sr:cancel")],
        ])
        await _edit_or_send(target, text, kb)
    except Exception as e:
        logger.exception(f"[SERIES-H] request: {e}")


# ============================================================
# HELPERS
# ============================================================

async def _edit_or_send(target, text, kb):
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


async def _edit_status(target, text):
    try:
        await target.edit_text(
            text[:4000],
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception:
        pass


def snapshot():
    return {"module": "groups.series.handler", "wizard": len(_wizard)}


__all__ = ["series_group_entry", "series_wizard_router", "snapshot"]
