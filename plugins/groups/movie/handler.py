# ============================================================
# 🏨 DOWNTOWN VILLA — MOVIE GROUP HANDLER
# ============================================================
#
# Entry point for text messages in MOVIE groups
# (any group that is NOT SERIES_GROUP_ID).
#
# Flow:
#   1. Gate: not series group · enabled · content_mode · cooldown
#   2. Show "🔎 searching…" status
#   3. quick_search(query) # Build deep-link
#        • If hits → file list (delivery.py) + deep-link buttons
#   4. Spell check + retry (if no hits)
#   5. Suggestions from TMDB (if still no hits)
#        • User taps a suggestion → sr:sug callback
#   6. Request prompt (if no suggestions)
#
# Handles ONLY movie / movie+series groups.
# Series group is handled by plugins.groups.series.handler.
#
# Handler group: -510 (runs AFTER series handler at -9999)
# This means SERIES_GROUP_ID is claimed first, and any other
# group falls through here.
#
# ============================================================

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional

from pyrogram import Client, filters
from pyrogram.enums import ChatType, ParseMode
from pyrogram.types import (
    InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from core import config
from plugins.groups import state as S
from plugins.groups.shared import search as SEARCH
from plugins.groups.shared import suggestions as SUGG
from plugins.groups.shared import delivery as DELIVERY
from plugins.groups.shared import request_flow as RF
from utils import fonts as F
from utils import format as FM

logger = logging.getLogger(__name__)


# ============================================================
# SECTION 1 — CONSTANTS
# ============================================================

COOLDOWN = 3.0
MIN_QUERY_LEN = 2
MAX_QUERY_LEN = 100
STATUS_TIMEOUT = 60  # seconds a status message stays before auto-cleanup


# ============================================================
# SECTION 2 — COOLDOWN (in-memory, per user)
# ============================================================

_last_seen: Dict[int, float] = {}


def _cooldown_ok(uid: int) -> bool:
    now = time.time()
    if now - _last_seen.get(uid, 0) < COOLDOWN:
        return False
    _last_seen[uid] = now
    return True


def _cleanup_cooldown() -> None:
    """Prevent unbounded growth."""
    now = time.time()
    if len(_last_seen) < 5000:
        return
    for k in list(_last_seen.keys()):
        if now - _last_seen[k] > 300:
            _last_seen.pop(k, None)


# ============================================================
# SECTION 3 — ENTRY HANDLER
# ============================================================

@Client.on_message(
    filters.group
    & filters.text
    & ~filters.regex(r"^/")
    & ~filters.regex(r"^sr:"),
    group=-510,
)
async def movie_group_entry(client: Client, message: Message):
    status: Optional[Message] = None
    try:
        if not message.from_user:
            return

        # ── GATE 1: series group ──
        series_gid = getattr(config, "SERIES_GROUP_ID", None)
        if series_gid and int(message.chat.id) == int(series_gid):
            return  # series handler owns this group

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
        if content_mode == "series":
            # This group is series-only; do not respond here
            return

        # ── GATE 4: cooldown (per-group) ──
        uid = message.from_user.id
        cd_secs = await SEARCH.get_cooldown_seconds(chat_id, default=COOLDOWN)

        # Skip entirely if disabled
        if cd_secs > 0:
            now = time.time()
            last = _last_seen.get(uid, 0)
            if now - last < cd_secs:
                return
            _last_seen[uid] = now

        _cleanup_cooldown()

        # ── Claim the message ──
        try:
            message.stop_propagation()
        except Exception:
            pass

        # ── Show status ──
        try:
            status = await message.reply_text("🔎 ꜱᴇᴀʀᴄʜɪɴɢ…")
        except Exception:
            return

        # ── Track stat ──
        try:
            await S.bump_stat(chat_id, "searches_today")
        except Exception:
            pass

        # ── Run search pipeline ──
        await _run_pipeline(
            client=client,
            message=message,
            status=status,
            query=txt,
            cfg=cfg,
        )

    except Exception as e:
        logger.exception(f"[MOVIE-H] entry: {e}")
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
# SECTION 4 — SEARCH PIPELINE
# ============================================================

async def _run_pipeline(
    client: Client,
    message: Message,
    status: Message,
    query: str,
    cfg: Dict[str, Any],
) -> None:
    """
    1. DB search
    2. Spell check + retry
    3. Suggestions
    4. Request prompt
    """
    uid = message.from_user.id
    chat_id = message.chat.id

    # ── 1. DB search ──
    hits, complete = await SEARCH.quick_search(query)

    if hits:
        await _deliver_files(
            client=client,
            status=status,
            query=query,
            hits=hits,
            cfg=cfg,
            uid=uid,
            chat_id=chat_id,
        )
        return

    if not complete:
        await _show_shards_offline(status)
        return

    # ── 2. Spell check ──
    corrected: Optional[str] = None
    try:
        corrected = await SUGG.ai_spell_check(query)
    except Exception as e:
        logger.debug(f"[MOVIE-H] spell: {e}")

    if corrected and corrected.strip().lower() != query.strip().lower():
        corrected_hits, _ = await SEARCH.quick_search(corrected)
        if corrected_hits:
            await _deliver_files(
                client=client,
                status=status,
                query=corrected,
                hits=corrected_hits,
                cfg=cfg,
                uid=uid,
                chat_id=chat_id,
                corrected_from=query,
            )
            return

    # ── 3. Suggestions ──
    try:
        items = await SUGG.suggestions(
            query,
            kind="any",
            limit=int(cfg.get("suggestion_count", 6)),
        )
    except Exception as e:
        logger.debug(f"[MOVIE-H] suggestions: {e}")
        items = []

    if items:
        await _show_suggestions(
            client=client,
            status=status,
            query=query,
            items=items,
            uid=uid,
            chat_id=chat_id,
        )
        return

    # ── 4. Request prompt ──
    await _show_request_prompt(
        client=client,
        status=status,
        query=query,
        chat_id=chat_id,
    )


# ============================================================
# SECTION 5 — DELIVER FILE LIST
# ============================================================

async def _deliver_files(
    client: Client,
    status: Message,
    query: str,
    hits: List[Dict[str, Any]],
    cfg: Dict[str, Any],
    uid: int,
    chat_id: int,
    corrected_from: Optional[str] = None,
) -> None:
    # Cap by the delivery step's max_items BEFORE creating the
    # session — so sr:more pagination uses the same list.
    try:
        flow = cfg.get("flow") or {}
        fd = flow.get("file_delivery") or {}
        max_items = int(fd.get("max_items", 15) or 15)
    except (TypeError, ValueError):
        max_items = 15
    max_items = max(1, min(30, max_items))
    if len(hits) > max_items:
        hits = hits[:max_items]

    # Create session for delivery + pagination
    sid = await DELIVERY.create_session(
        user_id=uid,
        chat_id=chat_id,
        query=query,
        hits=hits,
    )
    if not sid:
        return await _edit_status(
            status, "❌ session error"
        )

    # Track stat
    try:
        await S.bump_stat(chat_id, "results_found")
        await S.bump_stat(chat_id, "files_sent", len(hits))
    except Exception:
        pass

    # If corrected, prepend a small note
    if corrected_from:
        try:
            await status.edit_text(
                "\n".join([
                    f"🔤 <b>{F.fb('CORRECTED')}</b>",
                    f"📌 <code>{F.sc(corrected_from[:40])}</code> → "
                    f"<code>{F.sc(query[:40])}</code>",
                    "",
                    f"📌 {F.sc('loading results…')}",
                ]),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass

    # Show file list
    await DELIVERY.show_file_list(
        target=status,
        query=query,
        hits=hits,
        sid=sid,
        cfg=cfg,
        client=client,
        page=1,
    )


# ============================================================
# SECTION 6 — SHOW SUGGESTIONS
# ============================================================

async def _show_suggestions(
    client: Client,
    status: Message,
    query: str,
    items: List[Dict[str, Any]],
    uid: int,
    chat_id: int,
) -> None:
    """
    Store suggestions in a session so sr:sug callbacks can
    pick them up, then render the list.
    """
    # Normalize suggestions for storage
    stored = [SUGG.to_dict(x) for x in items if x]
    stored = [s for s in stored if s.get("title")]

    if not stored:
        return await _show_request_prompt(
            client, status, query, chat_id=chat_id,
        )

    # Read per-group display toggles (default: show everything)
    try:
        cfg_for_sugg = await S.get_config(chat_id)
        flow = cfg_for_sugg.get("flow") or {}
        sugg_cfg = flow.get("suggestions") or {}
    except Exception:
        sugg_cfg = {}
    show_rating = bool(sugg_cfg.get("show_rating", True))
    show_year = bool(sugg_cfg.get("show_year", True))
    show_icon = bool(sugg_cfg.get("show_icon", True))

    # Create a session to hold the suggestions
    sid = await DELIVERY.create_session(
        user_id=uid,
        chat_id=chat_id,
        query=query,
        hits=[],  # no hits — but session still needed
    )
    if not sid:
        return await _edit_status(status, "❌ session error")

    # Overwrite candidates with suggestions
    try:
        from media_search import sessions as _sess_mod
        await _sess_mod.sessions.update(sid, candidates=stored)
    except Exception as e:
        logger.debug(f"[MOVIE-H] store suggestions: {e}")

    # Build UI
    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"{F.EMO['search']} <b>{F.fb('DID YOU MEAN?')}</b>",
        F.DIV, "",
        f"🔍 {F.sc('you searched')} · <code>{F.sc(str(query)[:50])}</code>",
        f"📝 {F.sc('no exact match — pick the right one')}",
        "",
        F.DIV_S,
        f"📌 {F.sc('tap a title to see files')}",
        f"📌 {F.sc('or send a request to admin')}",
    ]

    # Check requests.enabled for this group
    requests_enabled = True
    try:
        cfg_check = await S.get_config(chat_id)
        req_cfg = cfg_check.get("requests") or {}
        requests_enabled = bool(req_cfg.get("enabled", True))
    except Exception:
        requests_enabled = True

    rows: List[List[InlineKeyboardButton]] = []

    # Top-of-list action: send request directly (if enabled)
    if requests_enabled:
        rows.append([InlineKeyboardButton(
            f"📩 {F.sc('send request to admin')}",
            callback_data=f"sr:req:{sid}",
        )])
        # Divider (no-op)
        rows.append([InlineKeyboardButton(
            "─────────",
            callback_data="sr:cancel_noop",
        )])

    # Then the suggestions — toggles apply
    for i, s in enumerate(stored[:8]):
        title = str(s.get("title") or "?")[:34]
        year = s.get("year")
        rating = s.get("rating") or 0
        kind = str(s.get("kind") or "movie")
        icon = "📺" if kind == "series" else "🎬"

        # Build label: icon + title
        if show_icon:
            label = f"{icon} {title}"
        else:
            label = title

        # Year
        if show_year and year:
            label += f" ({year})"

        # Rating — only if toggle on, and only if room
        try:
            r_float = float(rating)
        except (TypeError, ValueError):
            r_float = 0.0
        if show_rating and r_float > 0 and len(label) + 8 <= 60:
            label += f" · ⭐{r_float:.1f}"

        if len(label) > 60:
            label = label[:57] + "…"

        rows.append([InlineKeyboardButton(
            label,
            callback_data=f"sr:sug:{sid}:{i}",
        )])
    # Real "send request" button — uses sr:req callback
    rows.append([InlineKeyboardButton(
        f"📩 {F.sc('send request')}",
        callback_data=f"sr:req:{sid}",
    )])

    # Google search — proper URL encoding
    try:
        from urllib.parse import quote as _q
        g_url = (
            "https://www.google.com/search?q="
            + _q(str(query)[:200], safe="")
        )
    except Exception:
        g_url = "https://www.google.com/search?q=" + str(query)[:200]
    rows.append([InlineKeyboardButton(
        f"🔍 {F.sc('search on google')}",
        url=g_url,
    )])

    # IMDb direct search (bonus — helps when TMDB misses)
    try:
        from urllib.parse import quote as _q
        i_url = (
            "https://www.imdb.com/find?q="
            + _q(str(query)[:200], safe="")
        )
        rows.append([InlineKeyboardButton(
            "🎬 IMDb",
            url=i_url,
        )])
    except Exception:
        pass

    rows.append([InlineKeyboardButton(
        f"{F.EMO['cross']} {F.sc('close')}",
        callback_data="sr:cancel",
    )])
    # Edit status message
    try:
        await status.edit_text(
            "\n".join(lines)[:4000],
            reply_markup=InlineKeyboardMarkup(rows),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.debug(f"[MOVIE-H] suggestions edit: {e}")


# ============================================================
# SECTION 7 — REQUEST PROMPT (no suggestions at all)
# ============================================================

async def _show_request_prompt(
    client: Client,
    status: Message,
    query: str,
    chat_id: int = 0,
) -> None:
    """
    Nothing found in DB. Try the smart request flow:

      1. Respect `requests.enabled` per-group toggle
      2. Registered user → post directly (no deep-link needed)
      3. New user        → deferred token + deep-link prompt
    """
    try:
        uid = status.from_user.id if status.from_user else 0
        user = status.from_user
        username = user.username if user else ""
        full_name = user.first_name if user else ""

        # ── 1. Check requests.enabled for this group ──
        try:
            cfg = await S.get_config(chat_id) if chat_id else {}
            req_cfg = cfg.get("requests") or {}
            requests_enabled = bool(req_cfg.get("enabled", True))
        except Exception:
            requests_enabled = True

        if not requests_enabled:
            return await _edit_status(
                status,
                "\n".join([
                    f"{F.EMO['cross']} <b>{F.fb('NO RESULTS')}</b>",
                    F.DIV, "",
                    f"🔍 <code>{F.sc(str(query)[:50])}</code>",
                    "",
                    f"📌 {F.sc('requests are disabled in this group')}",
                    f"📌 {F.sc('try a different spelling')}",
                ]),
            )

        # ── 2. Registered user? Post directly ──
        is_reg = False
        try:
            is_reg = await RF.is_registered(uid)
        except Exception:
            is_reg = False

        if is_reg:
            token = await RF.post_request(
                client=client,
                user_id=uid,
                username=username or "",
                full_name=full_name or "",
                title=str(query)[:200],
                year=None,
                kind="movie",
                tmdb_id=None,
                chat_id=chat_id or (
                    status.chat.id if status.chat else 0
                ),
            )
            if token:
                return await _edit_status(
                    status,
                    "\n".join([
                        f"{F.EMO['check']} <b>{F.fb('REQUEST SENT')}</b>",
                        F.DIV, "",
                        f"🎬 <b>{F.sc(str(query)[:60])}</b>",
                        "",
                        f"📌 {F.sc('admins have been notified')}",
                        f"📌 {F.sc('you will be messaged once uploaded')}",
                    ]),
                )
            # direct post failed → fall through to deferred path

        # ── 3. Deferred path (new user or direct post failed) ──
        token = await RF.create_deferred_request(
            user_id=uid,
            username=username or "",
            full_name=full_name or "",
            title=str(query)[:200],
            year=None,
            kind="movie",
            tmdb_id=None,
            chat_id=chat_id or (
                status.chat.id if status.chat else 0
            ),
        )

        if not token:
            return await _edit_status(
                status,
                "\n".join([
                    f"{F.EMO['cross']} <b>{F.fb('NO RESULTS')}</b>",
                    F.DIV, "",
                    f"🔍 <code>{F.sc(str(query)[:50])}</code>",
                    f"📌 {F.sc('try a different spelling')}",
                ]),
            )

        # ── Build deep-link (with safe fallback) ──
        bot_username = ""
        try:
            me = await client.identity()
            bot_username = getattr(me, "username", "") or ""
        except Exception:
            pass
        if not bot_username:
            try:
                me = await client.get_me()
                bot_username = getattr(me, "username", "") or ""
            except Exception:
                pass

        if not bot_username:
            # Token was created — the request is already logged.
            # Show a positive confirmation so the user doesn't
            # re-search thinking it failed.
            return await _edit_status(
                status,
                "\n".join([
                    f"{F.EMO['check']} <b>{F.fb('REQUEST LOGGED')}</b>",
                    F.DIV, "",
                    f"🎬 <b>{F.sc(str(query)[:60])}</b>",
                    "",
                    f"📌 {F.sc('admins have been notified')}",
                    f"📌 {F.sc('you will be messaged once uploaded')}",
                ]),
            )

        deep_link = f"https://t.me/{bot_username}?start=req_{token}"

        lines = [
            f"{F.EMO['warn']} <b>{F.fb('NOT IN OUR DATABASE')}</b>",
            F.DIV, "",
            f"🎬 <b>{F.sc(str(query)[:60])}</b>",
            "",
            f"📌 {F.sc('tap the button below to send a request')}",
            f"📌 {F.sc('the admin will be notified')}",
        ]

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

        try:
            await status.edit_text(
                "\n".join(lines),
                reply_markup=kb,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
            # Track the "not found" stat
            try:
                if chat_id:
                    await S.bump_stat(chat_id, "not_found")
            except Exception:
                pass
        except Exception as e:
            logger.debug(f"[MOVIE-H] request prompt: {e}")

    except Exception as e:
        logger.exception(f"[MOVIE-H] request prompt: {e}")

# ============================================================
# SECTION 8 — SHARDS OFFLINE
# ============================================================

async def _show_shards_offline(status: Message) -> None:
    await _edit_status(
        status,
        "\n".join([
            f"{F.EMO['warn']} <b>{F.fb('DBs UNREACHABLE')}</b>",
            F.DIV, "",
            f"📌 {F.sc('one or more media shards are offline')}",
            f"📌 {F.sc('try again in a moment')}",
        ]),
    )


# ============================================================
# SECTION 9 — HELPERS
# ============================================================

async def _edit_status(status: Message, text: str) -> None:
    try:
        await status.edit_text(
            text,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        if "not modified" not in str(e).lower():
            logger.debug(f"[MOVIE-H] edit status: {e}")


# ============================================================
# SECTION 10 — PUBLIC EXPORTS
# ============================================================

def snapshot() -> Dict[str, Any]:
    return {
        "module": "groups.movie.handler",
        "cooldown_tracked": len(_last_seen),
    }


__all__ = [
    "movie_group_entry",
    "snapshot",
]
