# ============================================================
# 🏨 DOWNTOWN VILLA — GROUPS SHARED CALLBACKS
# ============================================================
#
# Handles every `sr:*` callback fired from a group file list.
#
# These callbacks only fire when the user's bot username was
# unavailable at delivery time (rare) — the preferred path is
# a direct deep-link button that goes straight to start_router.
#
# Callback map:
#   sr:file:{sid}:{idx}         → deliver that file to user PM
#   sr:more:{sid}:{page}        → show page N of the file list
#   sr:sug:{sid}:{idx}          → user picked a suggestion
#   sr:cancel                   → delete the message
#
# Handler group: -8097 (runs AFTER commands, BEFORE pm_search)
#
# ============================================================

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
)

from plugins.groups import state as S
from plugins.groups.shared import search as SEARCH
from plugins.groups.shared import suggestions as SUGG
from plugins.groups.shared import delivery as DELIVERY
from plugins.groups.shared import deep_link as DL
from utils import fonts as F
from utils import format as FM

logger = logging.getLogger(__name__)


# ============================================================
# SECTION 0 — SHARED HELPERS
# ============================================================

async def _bot_username(client: Client) -> str:
    """
    Resolve the bot username safely.
    Tries `identity()` first (custom client method), then falls
    back to the standard Pyrogram `get_me()`. Never raises.
    """
    # ✅ FIX: single helper for every bot-username lookup
    try:
        me = await client.identity()
        u = getattr(me, "username", "") or ""
        if u:
            return u
    except Exception:
        pass
    try:
        me = await client.get_me()
        return getattr(me, "username", "") or ""
    except Exception:
        return ""


def _read_search_cfg(cfg: Dict[str, Any]) -> Dict[str, int]:
    """
    Return per-page / per-row from the nested `search` section.
    ✅ FIX: keys live at cfg["search"], not top level.
    """
    s = cfg.get("search") or {}
    try:
        per_page = int(s.get("search_per_page", 10) or 10)
    except (TypeError, ValueError):
        per_page = 10
    try:
        per_row = int(s.get("search_per_row", 1) or 1)
    except (TypeError, ValueError):
        per_row = 1
    return {"per_page": per_page, "per_row": per_row}


def _read_sort_mode(cfg: Dict[str, Any]) -> str:
    """
    Return sort mode from the delivery step config.
    ✅ FIX: sort_order lives at cfg["flow"]["file_delivery"]["sort_order"],
    not top level.
    """
    flow = cfg.get("flow") or {}
    fd = flow.get("file_delivery") or {}
    mode = str(fd.get("sort_order", "small_to_big") or "small_to_big")
    if mode not in ("small_to_big", "big_to_small"):
        mode = "small_to_big"
    return mode


# ============================================================
# SECTION 1 — SESSION LOOKUP
# ============================================================

async def _get_session(sid: str):
    """Read media_search session by id."""
    try:
        from media_search import sessions as _sess_mod
        return await _sess_mod.sessions.get(sid)
    except Exception as e:
        logger.debug(f"[SR-CB] session: {e}")
        return None


# ============================================================
# SECTION 2 — SR:FILE (deliver one file to user PM)
# ============================================================

@Client.on_callback_query(
    filters.regex(r"^sr:file:"),
    group=-8097,
)
async def sr_file(client: Client, q: CallbackQuery):
    """
    User tapped a file button in a group (fallback path when
    bot username was unavailable for deep-link).
    """
    try:
        parts = str(q.data).split(":")
        if len(parts) < 4:
            return await q.answer("❌ invalid", show_alert=True)

        sid = parts[2]
        try:
            idx = int(parts[3])
        except (ValueError, IndexError):
            return await q.answer("❌ invalid index", show_alert=True)

        # Verify session
        session = await _get_session(sid)
        if not session:
            return await q.answer(
                "⏱️ Session expired — search again",
                show_alert=True,
            )

        candidates = session.candidates or []
        if idx < 0 or idx >= len(candidates):
            return await q.answer("❌ invalid file", show_alert=True)

        hit = candidates[idx]

        chat_id = q.message.chat.id if q.message.chat else 0

        # ── Verify gate ──
        try:
            cfg = await S.get_config(chat_id)
            v_cfg = cfg.get("verify") or {}
            if v_cfg.get("enabled") and v_cfg.get("shortener_url"):
                from plugins.groups.shared import verify as V
                uid = q.from_user.id

                needs_verify = not await V.is_verified(uid, chat_id)

                # ✅ Return-user shortcut: auto-renew if recent
                if needs_verify:
                    renewed = await V.try_auto_renew(uid, chat_id)
                    if renewed:
                        logger.debug(
                            f"[SR-CB] verify auto-renewed for {uid}"
                        )
                        needs_verify = False

                if needs_verify:
                    # Full verify flow (first-time or >24h since last)
                    bot_username = await _bot_username(client)
                    if not bot_username:
                        return await q.answer(
                            "⚠️ Bot username missing",
                            show_alert=True,
                        )
                    target = (
                        f"https://t.me/{bot_username}?start=v_{{url}}"
                    )
                    text, kb = await V.build_verify_card(
                        client, cfg, chat_id, uid, target,
                    )
                    if not text or not kb:
                        return await q.answer(
                            "⚠️ Verify setup error",
                            show_alert=True,
                        )
                    await q.answer("🔐 Verify required")
                    try:
                        await q.message.reply_text(
                            text,
                            reply_markup=kb,
                            parse_mode=ParseMode.HTML,
                            disable_web_page_preview=True,
                        )
                    except Exception as e:
                        logger.debug(f"[SR-CB] verify card: {e}")
                    return
        except Exception as e:
            logger.debug(f"[SR-CB] verify gate: {e}")
        # Notify user
        await q.answer("📤 Sending to your PM…")

        # Deliver
        from media_search import delivery as DEL
        from media_search.models import FileHit

        try:
            file_hit = FileHit.from_dict(hit) if isinstance(hit, dict) else hit
            # Attach the group chat_id so delivery can load the
            # per-group button config. FileHit allows setattr.
            try:
                setattr(
                    file_hit, "source_chat_id",
                    q.message.chat.id if q.message.chat else 0,
                )
            except Exception:
                pass
            ok, err = await DEL.delivery.send_file(
                client, q.from_user.id, file_hit,
            )
            if ok:
                # Track delivery against this group
                try:
                    gid = q.message.chat.id if q.message.chat else 0
                    if gid:
                        await S.bump_stat(gid, "files_sent")
                except Exception:
                    pass
            else:
                # Group context → prompt user to /start bot
                await _prompt_start(client, q)
        except Exception as e:
            logger.exception(f"[SR-CB] file deliver: {e}")
            try:
                await q.answer("❌ Could not send", show_alert=True)
            except Exception:
                pass

    except Exception as e:
        logger.exception(f"[SR-CB] sr_file: {e}")
        try:
            await q.answer("❌ Error", show_alert=True)
        except Exception:
            pass


async def _prompt_start(client: Client, q: CallbackQuery) -> None:
    """
    If delivery fails (user never started bot), send a
    "start the bot" prompt.
    """
    # ✅ FIX: use safe helper
    bot_username = await _bot_username(client)

    if not bot_username:
        return await q.answer(
            "📌 Start the bot in PM to receive files",
            show_alert=True,
        )

    try:
        await q.message.reply_text(
            "\n".join([
                f"{F.EMO['rocket']} <b>{F.fb('START THE BOT')}</b>",
                F.DIV, "",
                f"📌 {F.sc('tap the button below')}",
                f"📌 {F.sc('files will arrive in pm')}",
            ]),
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"{F.EMO['rocket']} {F.sc('start bot')}",
                    url=f"https://t.me/{bot_username}?start=start",
                ),
            ]]),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception:
        pass


# ============================================================
# SECTION 3 — SR:MORE (page navigation)
# ============================================================

@Client.on_callback_query(
    filters.regex(r"^sr:more:"),
    group=-8097,
)
async def sr_more(client: Client, q: CallbackQuery):
    """
    Show the next/previous page of the file list.

    Callback: sr:more:{sid}:{page}
    """
    try:
        parts = str(q.data).split(":")
        if len(parts) < 4:
            return await q.answer("❌ invalid", show_alert=True)

        sid = parts[2]
        try:
            page = int(parts[3])
        except (ValueError, IndexError):
            page = 1

        session = await _get_session(sid)
        if not session:
            return await q.answer(
                "⏱️ Session expired — search again",
                show_alert=True,
            )

        hits = list(session.candidates or [])
        if not hits:
            return await q.answer("❌ no files", show_alert=True)

        cfg = await S.get_config(q.message.chat.id)

        # ✅ FIX: safe bot username
        bot_username = await _bot_username(client)

        # ✅ FIX: read pagination from nested search section
        pag = _read_search_cfg(cfg)
        per_page = pag["per_page"]
        per_row = pag["per_row"]

        # ✅ FIX: read sort mode from flow.file_delivery
        sort_mode = _read_sort_mode(cfg)
        hits = SEARCH.sort_hits(hits, mode=sort_mode)

        # ✅ FIX: apply the same max_items cap as show_file_list
        try:
            flow = cfg.get("flow") or {}
            fd = flow.get("file_delivery") or {}
            max_items = int(fd.get("max_items", 15) or 15)
        except (TypeError, ValueError):
            max_items = 15
        max_items = max(1, min(30, max_items))
        if len(hits) > max_items:
            hits = hits[:max_items]

        kb, total_pages, page = DELIVERY.build_file_list_kb(
            sid=sid,
            hits=hits,
            page=page,
            per_page=per_page,
            per_row=per_row,
            bot_username=bot_username,
        )

        text = DELIVERY.build_file_list_text(
            query=session.query or "",
            total=len(hits),
            page=page,
            total_pages=total_pages,
        )

        try:
            await q.message.edit_text(
                text,
                reply_markup=kb,
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except Exception as e:
            if "not modified" not in str(e).lower():
                logger.debug(f"[SR-CB] more edit: {e}")

        await q.answer(f"📄 Page {page}/{total_pages}")

    except Exception as e:
        logger.exception(f"[SR-CB] sr_more: {e}")
        try:
            await q.answer("❌ Error", show_alert=True)
        except Exception:
            pass


# ============================================================
# SECTION 4 — SR:SUG (suggestion pick)
# ============================================================

@Client.on_callback_query(
    filters.regex(r"^sr:sug:"),
    group=-8097,
)
async def sr_sug(client: Client, q: CallbackQuery):
    """
    User picked a suggestion from the "did you mean?" list.

    Callback: sr:sug:{sid}:{idx}

    Flow:
      1. Read suggestion from session.candidates
      2. Re-search DB with the corrected title + year
      3. If hits → show file list
      4. If no hits → create request / prompt start
    """
    try:
        parts = str(q.data).split(":")
        if len(parts) < 4:
            return await q.answer("❌ invalid", show_alert=True)

        sid = parts[2]
        try:
            idx = int(parts[3])
        except (ValueError, IndexError):
            return await q.answer("❌ invalid index", show_alert=True)

        session = await _get_session(sid)
        if not session:
            return await q.answer(
                "⏱️ Session expired — search again",
                show_alert=True,
            )

        items = list(session.candidates or [])
        if idx < 0 or idx >= len(items):
            return await q.answer("❌ invalid", show_alert=True)

        chosen = items[idx]
        title = str(chosen.get("title") or "")
        year_str = str(chosen.get("year") or "")
        kind = str(chosen.get("kind") or "movie")

        if not title:
            return await q.answer("❌ empty", show_alert=True)

        await q.answer(f"🔎 Searching {title}…")

        # Parse year
        year: Optional[int] = None
        try:
            if year_str.isdigit():
                year = int(year_str)
        except Exception:
            year = None

        # Exact re-search
        hits = await SEARCH.search_by_title(
            title, year=year, kind=kind,
        )

        chat_id = q.message.chat.id if q.message.chat else 0

        # Track suggestion engagement
        try:
            await S.bump_stat(chat_id, "suggestions_clicked")
        except Exception:
            pass

        if hits:
            # Track that the suggestion actually produced files
            try:
                await S.bump_stat(
                    chat_id, "suggestions_led_to_files",
                )
                await S.bump_stat(chat_id, "results_found")
            except Exception:
                pass

            # Build new session and show file list
            uid = q.from_user.id

            # Cap using the delivery step's max_items
            cfg_tmp = await S.get_config(chat_id)
            try:
                flow = cfg_tmp.get("flow") or {}
                fd = flow.get("file_delivery") or {}
                max_items = int(fd.get("max_items", 15) or 15)
            except (TypeError, ValueError):
                max_items = 15
            max_items = max(1, min(30, max_items))
            hits = SEARCH.sort_hits(
                hits,
                mode=_read_sort_mode(cfg_tmp),
            )
            if len(hits) > max_items:
                hits = hits[:max_items]

            new_sid = await DELIVERY.create_session(
                user_id=uid,
                chat_id=chat_id,
                query=title,
                hits=hits,
            )
            if not new_sid:
                return await q.answer("❌ session error", show_alert=True)

            cfg = await S.get_config(chat_id)

            await DELIVERY.show_file_list(
                target=q.message,
                query=title,
                hits=hits,
                sid=new_sid,
                cfg=cfg,
                client=client,
                page=1,
            )
            return

        # ── Check requests.enabled before offering the flow ──
        chat_id = q.message.chat.id if q.message.chat else 0
        requests_enabled = True
        try:
            cfg_check = await S.get_config(chat_id)
            req_cfg = cfg_check.get("requests") or {}
            requests_enabled = bool(req_cfg.get("enabled", True))
        except Exception:
            requests_enabled = True

        if not requests_enabled:
            # Tell the user requests are disabled
            try:
                await q.message.edit_text(
                    "\n".join([
                        f"{F.EMO['cross']} <b>{F.fb('NO RESULTS')}</b>",
                        F.DIV, "",
                        f"🎬 <b>{F.sc(title[:60])}</b>",
                        "",
                        f"📌 {F.sc('requests are disabled in this group')}",
                        f"📌 {F.sc('please contact the admin directly')}",
                    ]),
                    reply_markup=InlineKeyboardMarkup([[
                        InlineKeyboardButton(
                            f"{F.EMO['cross']} {F.sc('close')}",
                            callback_data="sr:cancel",
                        ),
                    ]]),
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
            except Exception:
                pass
            return

        # ── No hits → request flow ──
        await _send_request_flow(
            client=client,
            q=q,
            title=title,
            year=year,
            kind=kind,
            tmdb_id=chosen.get("tmdb_id"),
        )

    except Exception as e:
        logger.exception(f"[SR-CB] sr_sug: {e}")
        try:
            await q.answer("❌ Error", show_alert=True)
        except Exception:
            pass


# ============================================================
# SECTION 4b — SR:REQ (user tapped "send request" from suggestions)
# ============================================================

@Client.on_callback_query(
    filters.regex(r"^sr:req:"),
    group=-8097,
)
async def sr_req(client: Client, q: CallbackQuery):
    """
    User tapped "📩 Send request" from the suggestion screen.
    Callback: sr:req:{sid}

    Reads the raw query from the session and triggers the
    request flow directly — no suggestion index needed.
    """
    try:
        parts = str(q.data).split(":")
        if len(parts) < 3:
            return await q.answer("❌ invalid", show_alert=True)
        sid = parts[2]

        session = await _get_session(sid)
        if not session:
            return await q.answer(
                "⏱️ Session expired — search again",
                show_alert=True,
            )

        # Use the original query text
        raw = str(session.query or "").strip()
        if not raw:
            return await q.answer("❌ empty query", show_alert=True)

        # Verify requests are still enabled for this group
        chat_id = q.message.chat.id if q.message.chat else 0
        try:
            cfg_check = await S.get_config(chat_id)
            req_cfg = cfg_check.get("requests") or {}
            if not bool(req_cfg.get("enabled", True)):
                return await q.answer(
                    "📌 Requests are disabled here",
                    show_alert=True,
                )
        except Exception:
            pass

        await q.answer("📩 Sending request…")

        # Track request
        try:
            gid = q.message.chat.id if q.message.chat else 0
            if gid:
                await S.bump_stat(gid, "requests_sent")
        except Exception:
            pass

        # Delegate to the shared request flow
        await _send_request_flow(
            client=client,
            q=q,
            title=raw,
            year=None,
            kind="movie",
            tmdb_id=None,
        )

    except Exception as e:
        logger.exception(f"[SR-CB] sr_req: {e}")
        try:
            await q.answer("❌ Error", show_alert=True)
        except Exception:
            pass


# ============================================================
# SECTION 5 — REQUEST FLOW (from suggestion with no DB hits)
# ============================================================

async def _send_request_flow(
    client: Client,
    q: CallbackQuery,
    title: str,
    year: Optional[int],
    kind: str,
    tmdb_id: Optional[int],
) -> None:
    """
    Post a request to admin channel.

    • Registered user → request sent directly, confirm in group
    • New user        → prompt start bot + deep link request
    """
    from plugins.groups.shared import request_flow as RF

    try:
        uid = q.from_user.id
        user = q.from_user
        username = user.username or ""
        full_name = user.first_name or ""

        # Check if user is registered (has started the bot)
        is_reg = await RF.is_registered(uid)

        if is_reg:
            # Direct post
            token = await RF.post_request(
                client=client,
                user_id=uid,
                username=username,
                full_name=full_name,
                title=title,
                year=year,
                kind=kind,
                tmdb_id=tmdb_id,
                chat_id=q.message.chat.id if q.message.chat else 0,
            )
            if token:
                try:
                    await q.message.edit_text(
                        "\n".join([
                            f"{F.EMO['check']} <b>{F.fb('REQUEST SENT')}</b>",
                            F.DIV, "",
                            f"🎬 <b>{F.sc(title[:60])}</b>",
                            "",
                            f"📌 {F.sc('admins have been notified')}",
                            f"📌 {F.sc('you will be messaged once uploaded')}",
                        ]),
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=True,
                    )
                except Exception:
                    pass
                await q.answer("✅ Request sent")
            else:
                await q.answer(
                    "⚠️ Could not send — try again",
                    show_alert=True,
                )
            return

        # New user → create deferred request + prompt start
        token = await RF.create_deferred_request(
            user_id=uid,
            username=username,
            full_name=full_name,
            title=title,
            year=str(year) if year else None,
            kind=kind,
            tmdb_id=tmdb_id,
            chat_id=q.message.chat.id if q.message.chat else 0,
        )

        if not token:
            return await q.answer(
                "⚠️ Could not prepare request",
                show_alert=True,
            )

        # ✅ FIX: safe bot username
        bot_username = await _bot_username(client)

        if not bot_username:
            return await q.answer(
                "📌 Start the bot in PM to send request",
                show_alert=True,
            )

        deep_link = f"https://t.me/{bot_username}?start=req_{token}"

        try:
            await q.message.edit_text(
                "\n".join([
                    f"{F.EMO['warn']} <b>{F.fb('NOT IN OUR DATABASE')}</b>",
                    F.DIV, "",
                    f"🎬 <b>{F.sc(title[:60])}</b>",
                    *(
                        [f"📅 <code>{year}</code>"] if year else []
                    ),
                    "",
                    f"📌 {F.sc('tap the button to send request')}",
                    f"📌 {F.sc('the admin will be notified')}",
                ]),
                reply_markup=InlineKeyboardMarkup([
                    [InlineKeyboardButton(
                        f"{F.EMO['rocket']} {F.sc('send request')}",
                        url=deep_link,
                    )],
                    [InlineKeyboardButton(
                        f"{F.EMO['cross']} {F.sc('cancel')}",
                        callback_data="sr:cancel",
                    )],
                ]),
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        except Exception:
            pass

        await q.answer("📤 Tap the button")

    except Exception as e:
        logger.exception(f"[SR-CB] request flow: {e}")
        try:
            await q.answer("❌ Error", show_alert=True)
        except Exception:
            pass


# ============================================================
# SECTION 6 — SR:CANCEL
# ============================================================

@Client.on_callback_query(
    filters.regex(r"^sr:cancel$"),
    group=-8097,
)
async def sr_cancel(client: Client, q: CallbackQuery):
    try:
        await q.message.delete()
    except Exception:
        pass
    await q.answer("❌ Cancelled")

@Client.on_callback_query(
    filters.regex(r"^sr:vchk:"),
    group=-8097,
)
async def sr_vchk(client: Client, q: CallbackQuery):
    """
    User tapped "✅ I VERIFIED" on a verify card.

    Callback: sr:vchk:{token}

    Looks up the token. If verified → delete the card and
    tell the user to retap the file button.
    """
    try:
        parts = str(q.data).split(":")
        if len(parts) < 3:
            return await q.answer("❌ invalid", show_alert=True)
        token = parts[2]

        from plugins.groups.shared import verify as V
        doc = await V.get_token(token)

        if not doc:
            return await q.answer(
                "⏱️ Link expired — search again",
                show_alert=True,
            )

        uid = q.from_user.id
        owner = int(doc.get("user_id", 0))
        if owner != uid:
            return await q.answer(
                "⛔ Not your link", show_alert=True,
            )

        if not doc.get("verified"):
            return await q.answer(
                "⚠️ Open the shortener first",
                show_alert=True,
            )

        # Verified! Delete the card and confirm
        try:
            await q.message.delete()
        except Exception:
            pass

        try:
            await q.message.reply_text(
                "\n".join([
                    f"{F.EMO['check']} <b>{F.fb('VERIFIED')}</b>",
                    F.DIV, "",
                    f"📌 {F.sc('now tap the file button again')}",
                ]),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass

        await q.answer("✅ Verified")
    except Exception as e:
        logger.exception(f"[SR-CB] vchk: {e}")
        try:
            await q.answer("❌ Error", show_alert=True)
        except Exception:
            pass


@Client.on_callback_query(
    filters.regex(r"^sr:cancel_noop$"),
    group=-8097,
)
async def sr_cancel_noop(client: Client, q: CallbackQuery):
    """Divider row — no action."""
    return await q.answer()


# ============================================================
# SECTION 7 — PUBLIC EXPORTS
# ============================================================

def snapshot() -> Dict[str, Any]:
    return {"module": "groups.shared.callbacks"}


__all__ = [
    "sr_file",
    "sr_more",
    "sr_sug",
    "sr_req",
    "sr_vchk",
    "sr_cancel",
    "sr_cancel_noop",
    "snapshot",
]
