# ============================================================
# 🏨 DOWNTOWN VILLA — PM SEARCH MAIN FLOW
# ============================================================
#
# Uses plugins.groups.shared for:
#   • DB search (SEARCH.quick_search)
#   • Spell check + suggestions (SUGG)
#
# Everything else (panel, deliver, fsub, request) unchanged.
#
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
from plugins.pm_search import enrich as IE
from plugins.pm_search import panel as PN
from plugins.pm_search import deliver as DL
from plugins.pm_search import fsub as FS
from plugins.pm_search import request as RQ

# ── v2 imports (groups.shared) ──
from plugins.groups.shared import search as SEARCH
from plugins.groups.shared import suggestions as SUGG

logger = logging.getLogger(__name__)

PFX = "pms"
COOLDOWN = 2.0
_last_seen: Dict[int, float] = {}


# ============================================================
# SESSIONS
# ============================================================

_sessions: Dict[str, Dict[str, Any]] = {}
SESSION_TTL = 1800.0


def _new_session(user_id: int, query: str,
                 hits: Optional[List] = None,
                 extra: Optional[Dict] = None) -> str:
    sid = f"{int(time.time())}_{user_id % 100000}"
    _sessions[sid] = {
        "user_id": int(user_id),
        "query": query,
        "hits": list(hits or []),
        "extra": dict(extra or {}),
        "expires": time.time() + SESSION_TTL,
    }
    return sid


def _get_session(sid: str) -> Optional[Dict[str, Any]]:
    s = _sessions.get(sid)
    if not s:
        return None
    if time.time() > s["expires"]:
        _sessions.pop(sid, None)
        return None
    return s


def _drop_session(sid: str) -> None:
    _sessions.pop(sid, None)


# ============================================================
# PM TEXT HANDLER
# ============================================================

@Client.on_message(
    filters.private
    & filters.text
    & ~filters.regex(r"^/")
    & ~filters.regex(r"^sr:")
    & ~filters.regex(r"^pms:")
    & ~filters.regex(r"^pmsa:")
    & ~filters.regex(r"^idx:")
    & ~filters.regex(r"^dtvb:")
    & ~filters.regex(r"^adm:")
    & ~filters.regex(r"^ga:")
    & ~filters.regex(r"^glist:")
    & ~filters.regex(r"^sgw:"),
    group=-500,
)
async def pm_text_handler(client: Client, message: Message):
    try:
        if not message.from_user:
            return

        cfg = await CFG.get_cfg()
        if not cfg.get("enabled", True):
            return

        txt = (message.text or "").strip()
        if not txt or len(txt) < 2 or len(txt) > 120:
            return
        if "http://" in txt.lower() or "https://" in txt.lower():
            return

        uid = message.from_user.id
        now = time.time()
        if now - _last_seen.get(uid, 0) < COOLDOWN:
            return
        _last_seen[uid] = now

        try:
            from plugins.admin import stats as S
            S.track_search(uid, txt)
        except Exception:
            pass

        await _do_search(client, message, txt, cfg)

        try:
            message.stop_propagation()
        except Exception:
            pass

    except Exception as e:
        logger.exception(f"[PM-SEARCH] text: {e}")


# ============================================================
# SEARCH CORE (DB → spell check → suggestions → request)
# ============================================================

async def _do_search(
    client: Client,
    message: Message,
    query: str,
    cfg: Dict[str, Any],
):
    uid = message.from_user.id
    chat_id = message.chat.id

    # ── 1. DB query ──
    hits: List[Any] = []
    complete = True
    try:
        hits, complete = await SEARCH.quick_search(query)
    except Exception as e:
        logger.exception(f"[PM-SEARCH] quick_search: {e}")

    if hits:
        sid = _new_session(uid, query, hits)
        meta = None
        if cfg.get("show_poster", True) or cfg.get("show_rating", True):
            try:
                meta = await IE.enrich(query)
            except Exception:
                meta = None
        await PN.send_panel(client, uid, chat_id, query, hits, sid, cfg, meta)
        return

    if not complete:
        try:
            await client.send_message(
                chat_id=chat_id,
                text=(
                    f"{F.EMO['warn']} <b>{F.fb('ONE OR MORE DBs OFFLINE')}</b>\n"
                    f"{F.EMO['info']} {F.sc('try again in a moment')}"
                ),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        return

    # ── 2. Spell check → retry DB ──
    corrected: Optional[str] = None
    try:
        corrected = await SUGG.ai_spell_check(query)
    except Exception as e:
        logger.debug(f"[PM-SEARCH] spell_check: {e}")

    if corrected and corrected.strip().lower() != query.strip().lower():
        try:
            hits2, _ = await SEARCH.quick_search(corrected)
        except Exception:
            hits2 = []

        if hits2:
            sid = _new_session(uid, corrected, hits2)
            meta = None
            try:
                meta = await IE.enrich(corrected)
            except Exception:
                meta = None
            if meta:
                meta["_corrected_from"] = query
            else:
                meta = {"_corrected_from": query}
            await PN.send_panel(
                client, uid, chat_id, corrected, hits2, sid, cfg, meta,
            )
            return

    # ── 3. Suggestions ──
    if not cfg.get("suggestion_enabled", True):
        await _send_request_flow(client, message, query, None, cfg)
        return

    items: List[Dict[str, Any]] = []
    try:
        raw = await SUGG.suggestions(
            query,
            limit=int(cfg.get("suggestion_count", 6)),
        )
        # Normalize to dict shape the panel expects
        items = [SUGG.to_dict(x) for x in raw if x]
    except Exception as e:
        logger.debug(f"[PM-SEARCH] suggestions: {e}")

    if items:
        sid = _new_session(uid, query, [], extra={"suggestions": items})
        await PN.send_suggestions(client, chat_id, query, items, sid)
        return

    # ── 4. No suggestions → request ──
    await _send_request_flow(client, message, query, None, cfg)


# ============================================================
# REQUEST FLOW
# ============================================================

async def _send_request_flow(
    client: Client,
    message: Message,
    query: str,
    meta: Optional[Dict[str, Any]],
    cfg: Dict[str, Any],
    user=None,
):
    if user is not None:
        uid = user.id
        u = user
    else:
        uid = message.from_user.id if message.from_user else 0
        u = message.from_user

    if not cfg.get("request_enabled", True):
        try:
            await client.send_message(
                chat_id=message.chat.id,
                text=(
                    f"{F.EMO['cross']} <b>{F.fb('NO RESULTS')}</b>\n\n"
                    f"📌 <code>{query[:60]}</code>"
                ),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        return

    title = meta.get("title") if meta else query
    year = meta.get("year") if meta else None
    tmdb_id = meta.get("tmdb_id") if meta else None
    kind = (meta.get("kind") if meta else "movie") or "movie"

    token = await RQ.send_request(
        client=client,
        user_id=uid,
        username=u.username or "",
        full_name=u.first_name or "",
        title=str(title or query)[:120],
        year=year,
        kind=kind,
        tmdb_id=tmdb_id,
        user_query=query,
    )
    if token:
        await RQ.notify_sent(client, uid, str(title or query), year)
    else:
        try:
            await client.send_message(
                chat_id=message.chat.id,
                text=(
                    f"{F.EMO['cross']} <b>{F.fb('NO RESULTS')}</b>\n\n"
                    f"📌 <code>{query[:60]}</code>"
                ),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass


# ============================================================
# CALLBACK ROUTER
# ============================================================

@Client.on_callback_query(
    filters.regex(rf"^{PFX}:"),
    group=-8085,
)
async def pms_router(client: Client, q: CallbackQuery):
    if not q.from_user:
        return await q.answer()

    parts = str(q.data).split(":")
    action = parts[1] if len(parts) > 1 else ""
    sid = parts[2] if len(parts) > 2 else ""
    idx_str = parts[3] if len(parts) > 3 else "0"
    uid = q.from_user.id

    try:
        if action == "noop":
            return await q.answer()

        if action == "close":
            _drop_session(sid)
            try:
                await q.message.delete()
            except Exception:
                pass
            return await q.answer("Closed")

        if action == "get":
            try:
                idx = int(idx_str)
            except ValueError:
                return await q.answer("❌")

            s = _get_session(sid)
            if not s:
                return await q.answer("⏱️ Session expired", show_alert=True)
            if int(s["user_id"]) != uid:
                return await q.answer("❌ Not yours", show_alert=True)

            cfg = await CFG.get_cfg()

            subscribed, missing = await FS.check_fsub(client, uid, cfg)
            if not subscribed:
                await q.answer("🔒 Join required")
                text, kb = FS.build_fsub_panel(cfg, sid, idx, missing)
                try:
                    await q.message.edit_text(
                        text, reply_markup=kb,
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=True,
                    )
                except Exception:
                    pass
                return

            hits = s.get("hits") or []
            if idx < 0 or idx >= len(hits):
                return await q.answer("❌ Invalid", show_alert=True)

            await q.answer("📤 Sending…")
            ok = await DL.send_file(client, uid, hits[idx], cfg)
            if not ok:
                await q.answer("❌ Could not send", show_alert=True)
            return

        if action == "try":
            try:
                idx = int(idx_str)
            except ValueError:
                return await q.answer("❌")

            s = _get_session(sid)
            if not s:
                return await q.answer("⏱️ Session expired", show_alert=True)
            if int(s["user_id"]) != uid:
                return await q.answer("❌ Not yours", show_alert=True)

            cfg = await CFG.get_cfg()
            subscribed, missing = await FS.check_fsub(client, uid, cfg)

            if not subscribed:
                await q.answer("🔒 Still not joined")
                text, kb = FS.build_fsub_panel(cfg, sid, idx, missing)
                try:
                    await q.message.edit_text(
                        text, reply_markup=kb,
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=True,
                    )
                except Exception:
                    pass
                return

            hits = s.get("hits") or []
            if idx < 0 or idx >= len(hits):
                return await q.answer("❌ Invalid", show_alert=True)

            await q.answer("✅ Verified — sending…")
            ok = await DL.send_file(client, uid, hits[idx], cfg)
            if ok:
                try:
                    await q.message.delete()
                except Exception:
                    pass
            return

        if action == "sug":
            try:
                idx = int(idx_str)
            except ValueError:
                return await q.answer("❌")

            s = _get_session(sid)
            if not s:
                return await q.answer("⏱️ Session expired", show_alert=True)
            if int(s["user_id"]) != uid:
                return await q.answer("❌ Not yours", show_alert=True)

            items = (s.get("extra") or {}).get("suggestions") or []
            if idx < 0 or idx >= len(items):
                return await q.answer("❌ Invalid", show_alert=True)

            chosen = items[idx]
            title = chosen.get("title") or ""
            year_str = chosen.get("year") or ""
            tmdb_id = chosen.get("tmdb_id")

            await q.answer(f"🔎 {title}…")

            try:
                await q.message.delete()
            except Exception:
                pass

            _drop_session(sid)

            cfg = await CFG.get_cfg()
            query_text = title
            if year_str:
                query_text = f"{title} {year_str}"

            hits: List[Any] = []
            try:
                y = int(year_str) if str(year_str).isdigit() else None
                hits, _ = await SEARCH.quick_search(title, year=y)
            except Exception:
                hits = []

            if hits:
                new_sid = _new_session(uid, query_text, hits)
                meta = {
                    "title": title,
                    "year": year_str,
                    "rating": chosen.get("rating", 0),
                    "poster": chosen.get("poster"),
                    "overview": "",
                    "tmdb_id": tmdb_id,
                    "kind": chosen.get("kind", "movie"),
                }
                await PN.send_panel(
                    client, uid, q.message.chat.id,
                    query_text, hits, new_sid, cfg, meta,
                )
            else:
                meta = {
                    "title": title, "year": year_str,
                    "tmdb_id": tmdb_id,
                    "kind": chosen.get("kind", "movie"),
                }
                await _send_request_flow(
                    client, q.message, title, meta, cfg,
                    user=q.from_user,
                )
            return

        return await q.answer("❓")

    except Exception as e:
        logger.exception(f"[PM-SEARCH] router: {e}")
        try:
            await q.answer(f"❌ {type(e).__name__}", show_alert=True)
        except Exception:
            pass


# ============================================================
# EXPORT FOR REQUEST.PY
# ============================================================

async def show_results_for_request(
    client: Client,
    user_id: int,
    chat_id: int,
    query: str,
    year: Optional[str] = None,
) -> bool:
    """
    Fresh DB search + send PM panel.
    Used by plugins.requests.request when admin taps ✅ UPDATED.
    """
    try:
        cfg = await CFG.get_cfg()

        q_text = query
        y = None
        if year and str(year).isdigit():
            y = int(year)
            q_text = f"{query} {year}"

        hits, _ = await SEARCH.quick_search(query, year=y)
        if not hits:
            return False

        sid = _new_session(user_id, q_text, hits)
        meta = None
        if cfg.get("show_poster", True):
            try:
                meta = await IE.enrich(query, year=y)
            except Exception:
                meta = None

        await PN.send_panel(
            client, user_id, chat_id, q_text, hits, sid, cfg, meta,
        )
        return True
    except Exception as e:
        logger.exception(f"[PM-SEARCH] show_for_request: {e}")
        return False


__all__ = ["pm_text_handler", "show_results_for_request"]
