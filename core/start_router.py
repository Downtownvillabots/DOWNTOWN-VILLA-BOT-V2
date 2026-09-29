# ============================================================
# 🏨 DOWNTOWN VILLA — START ROUTER (v2)
# ============================================================
#
# Single source of truth for /start deep-links.
#
# Supported payloads:
#   file_{token}      → single file delivery (from movie/series group)
#   deliver_{token}   → batch episode delivery (from series wizard)
#   prem_{token}      → premium watch session
#   prem_start        → open premium menu
#   req_{token}       → deferred request (new user)
#   gs_{chat_id}      → open group settings panel
#   ref_{user_id}     → referral + welcome
#   (empty)           → welcome
#
# Routing targets:
#   file_*, deliver_*  → plugins.groups.shared.deep_link
#   req_*              → plugins.groups.shared.request_flow
#   gs_*               → plugins.groups.router + panel
#   prem_*             → plugins.premium
#   ref_*, empty       → welcome
#
# ============================================================

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Dict, List, Optional, Tuple

from pyrogram import Client, filters
from pyrogram.errors import FloodWait
from pyrogram.enums import ParseMode
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from core import config
from core import rocket
from utils import fonts as F
from utils import format as FM

logger = logging.getLogger(__name__)


# ============================================================
# SECTION 1 — ROUTE TABLE
# ============================================================

RouteHandler = Callable[..., Awaitable[bool]]

_routes: Dict[str, RouteHandler] = {}


def register_route(prefix: str, handler: RouteHandler) -> None:
    _routes[prefix] = handler
    logger.info(f"[START] route registered: {prefix}_*")


def unregister_route(prefix: str) -> None:
    _routes.pop(prefix, None)


def list_routes() -> List[str]:
    return sorted(_routes.keys())


# ============================================================
# SECTION 2 — PAYLOAD PARSER
# ============================================================

def parse_payload(text: str) -> Tuple[str, str]:
    """Split "/start file_abc123" → ("file", "abc123")."""
    if not text:
        return "", ""
    parts = text.strip().split(maxsplit=1)
    if len(parts) < 2:
        return "", ""
    payload = parts[1].strip()
    if not payload:
        return "", ""

    # colon separator (gs:12345)
    if ":" in payload and "_" not in payload.split(":", 1)[0]:
        head, tail = payload.split(":", 1)
        return head, tail

    # underscore separator (file_abc123)
    if "_" in payload:
        head, tail = payload.split("_", 1)
        return head, tail

    return payload, ""


# ============================================================
# SECTION 3 — LINK BUILDERS
# ============================================================

def build_link(bot_username: str, payload: str) -> str:
    if not bot_username:
        return "https://t.me/"
    return f"https://t.me/{bot_username}?start={payload}"


def link_file(bot_username: str, token: str) -> str:
    return build_link(bot_username, f"file_{token}")


def link_deliver(bot_username: str, token: str) -> str:
    return build_link(bot_username, f"deliver_{token}")


def link_request(bot_username: str, token: str) -> str:
    return build_link(bot_username, f"req_{token}")


def link_group_settings(bot_username: str, chat_id: int) -> str:
    return build_link(bot_username, f"gs_{chat_id}")


def link_premium(bot_username: str, slug: str = "start") -> str:
    return build_link(bot_username, f"prem_{slug}")


def link_referral(bot_username: str, user_id: int) -> str:
    return build_link(bot_username, f"ref_{user_id}")


# ============================================================
# SECTION 4 — GATES
# ============================================================

async def _check_maintenance(message: Message) -> bool:
    if not config.MAINTENANCE_MODE:
        return False
    if message.from_user and message.from_user.id in [
        int(a) for a in config.ADMINS
    ]:
        return False

    text = "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"{F.EMO['gear']} {F.sc('maintenance mode')}",
        F.DIV, "",
        f"{F.EMO['warn']} {F.sc('the bot is under maintenance')}",
        f"{F.EMO['clock']} {F.sc('please try again later')}",
        "",
        f"<i>{F.sc('sorry for the inconvenience')}</i>",
    ])
    try:
        await message.reply_text(text, parse_mode=ParseMode.HTML)
    except Exception:
        pass
    return True


async def _check_banned(message: Message) -> bool:
    uid = message.from_user.id if message.from_user else 0
    if not uid:
        return False
    try:
        from database import db_registry
        db = db_registry.get_user_db()
        if db is None:
            return False
        doc = await db["banned_users"].find_one({"user_id": uid})
        if not doc:
            return False

        text = "\n".join([
            f"{F.EMO['cross']} <b>{F.fb('ACCESS DENIED')}</b>",
            F.DIV, "",
            f"{F.EMO['warn']} {F.sc('you have been banned')}",
            f"{F.EMO['user']} {F.sc('contact support to appeal')}",
        ])
        try:
            await message.reply_text(text, parse_mode=ParseMode.HTML)
        except Exception:
            pass
        return True
    except Exception as e:
        logger.debug(f"[START] ban check: {e}")
        return False


# ============================================================
# SECTION 5 — USER REGISTRATION
# ============================================================

async def _register_user(message: Message) -> None:
    if not message.from_user:
        return
    try:
        from database import db_registry
        from datetime import datetime
        db = db_registry.get_user_db()
        if db is None:
            return
        uid = message.from_user.id
        await db["users"].update_one(
            {"user_id": uid},
            {
                "$set": {
                    "user_id": uid,
                    "username": message.from_user.username or "",
                    "first_name": message.from_user.first_name or "",
                    "last_name": message.from_user.last_name or "",
                    "language_code": message.from_user.language_code or "",
                    "last_seen": datetime.utcnow(),
                },
                "$setOnInsert": {
                    "created_at": datetime.utcnow(),
                    "is_premium": False,
                },
            },
            upsert=True,
        )
    except Exception as e:
        logger.debug(f"[START] register: {e}")


# ============================================================
# SECTION 6 — WELCOME
# ============================================================

def _welcome_text(first_name: str = "") -> str:
    name = first_name.strip() or F.sc("friend")
    return "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        F.DIV, "",
        f"{F.EMO['spark']} {F.sc('welcome')} <b>{name}</b>",
        "",
        f"{F.EMO['search']} {F.sc('search in the group')}",
        f"{F.EMO['send']} {F.sc('files arrive here in pm')}",
        f"{F.EMO['crown']} {F.sc('premium members get extra features')}",
        "",
        F.DIV,
        f"{F.EMO['rocket']} <i>{F.sc('happy watching!')}</i>",
    ])


def _welcome_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"{F.EMO['search']} {F.sc('how to search')}",
                callback_data="start:how",
            ),
            InlineKeyboardButton(
                f"{F.EMO['crown']} {F.sc('premium')}",
                callback_data="start:premium",
            ),
        ],
        [
            InlineKeyboardButton(
                f"{F.EMO['channel']} {F.sc('updates')}",
                url=config.UPDATE_CHNL_LNK or "https://t.me/",
            ),
            InlineKeyboardButton(
                f"{F.EMO['users']} {F.sc('support')}",
                url=config.SUPPORT_CHAT or "https://t.me/",
            ),
        ],
    ])


async def _send_welcome(message: Message) -> None:
    name = message.from_user.first_name if message.from_user else ""
    try:
        await message.reply_text(
            _welcome_text(name),
            reply_markup=_welcome_kb(),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.debug(f"[START] welcome: {e}")


# ============================================================
# SECTION 7 — ROUTE HANDLERS
# ============================================================

# ── FILE (single file from movie/series group) ──

async def _handle_file(client, message, prefix, extra):
    """
    file_{token}      → deep_link token (kind="file")
    file_{sid}_{idx}  → media_search session id + index
    Tries token first, falls back to session.
    """
    try:
        from plugins.groups.shared import deep_link as DL
        from media_search import delivery as DEL
        from media_search.models import FileHit
        from media_search import sessions as _sess_mod

        raw = str(extra or "").strip()
        if not raw:
            return False

        uid = message.from_user.id

        # ── Path A: deep_link token ──
        doc = await DL.get_token(raw)
        if doc and doc.get("kind") == "file":
            if int(doc.get("user_id", 0)) != int(uid):
                await message.reply_text(
                    f"{F.EMO['cross']} {F.sc('this link is not for you')}",
                    parse_mode=ParseMode.HTML,
                )
                return True

            hit_data = doc.get("hit") or {}
            if not hit_data.get("file_id"):
                await message.reply_text("❌ Invalid file")
                return True

            try:
                hit = FileHit.from_dict(hit_data)
            except Exception:
                class _Hit:
                    def __init__(self, d):
                        for k, v in d.items():
                            setattr(self, k, v)
                hit = _Hit(hit_data)

            await DEL.delivery.send_file(client, uid, hit)
            await DL.mark_used(raw)
            return True

        # ── Path B: session_{sid}_{idx} ──
        parts = raw.rsplit("_", 1)
        if len(parts) != 2:
            return False

        sid, idx_str = parts
        try:
            idx = int(idx_str)
        except ValueError:
            return False

        session = await _sess_mod.sessions.get(sid)
        if not session:
            await message.reply_text(
                "\n".join([
                    f"{F.EMO['warn']} <b>{F.fb('SESSION EXPIRED')}</b>",
                    F.DIV, "",
                    f"{F.EMO['search']} {F.sc('please search again in the group')}",
                ]),
                parse_mode=ParseMode.HTML,
            )
            return True

        candidates = session.candidates or []
        if idx < 0 or idx >= len(candidates):
            await message.reply_text("❌ Invalid file")
            return True

        data = candidates[idx]
        try:
            hit = FileHit.from_dict(data) if isinstance(data, dict) else data
        except Exception:
            hit = data

        await DEL.delivery.send_file(client, uid, hit)
        return True

    except Exception as e:
        logger.exception(f"[START] file route: {e}")
        return False


# ── DELIVER (batch episodes from series wizard) ──

async def _handle_deliver(client, message, prefix, extra):
    """
    deliver_{token} — V1-style batch delivery with:
      • intro card
      • custom caption (per-group)
      • custom buttons (per-group)
      • 3-method fallback (cached → copy → media_search)
      • auto-delete with warning (per-group minutes)
      • summary card
    """
    try:
        from plugins.groups.shared import deep_link as DL
        from plugins.groups import state as GS

        token = str(extra or "").strip()
        if not token:
            return False

        doc = await DL.get_token(token)
        if not doc or doc.get("kind") != "deliver":
            await message.reply_text(
                "\n".join([
                    f"{F.EMO['warn']} <b>{F.fb('LINK EXPIRED')}</b>",
                    F.DIV, "",
                    f"{F.EMO['search']} {F.sc('please search again in the group')}",
                ]),
                parse_mode=ParseMode.HTML,
            )
            return True

        uid = message.from_user.id
        if int(doc.get("user_id", 0)) != int(uid):
            await message.reply_text(
                f"{F.EMO['cross']} {F.sc('this link is not for you')}",
                parse_mode=ParseMode.HTML,
            )
            return True

        # ── Read group config ──
        chat_id = int(doc.get("chat_id") or 0)
        cfg = {}
        if chat_id:
            try:
                cfg = await GS.get_config(chat_id)
            except Exception as e:
                logger.debug(f"[START] cfg load: {e}")

        caption_tpl = cfg.get("caption_template") or ""
        custom_buttons = cfg.get("result_buttons") or []
        auto_delete_cfg = cfg.get("auto_delete") or {}
        auto_delete_min = 0
        if auto_delete_cfg.get("bot_messages", True):
            auto_delete_min = int(auto_delete_cfg.get("bot_timer", 0) or 0) // 60

        title = str(doc.get("title") or "?")
        season = int(doc.get("season") or 0)
        quality = str(doc.get("quality") or "?")
        language = str(doc.get("language") or "")
        hits = list(doc.get("hits") or [])

        if not hits:
            await message.reply_text(
                "\n".join([
                    f"{F.EMO['cross']} <b>{F.fb('NO FILES')}</b>",
                    F.DIV, "",
                    f"📌 {F.sc('no files available for this delivery')}",
                ]),
                parse_mode=ParseMode.HTML,
            )
            return True

        # ── Intro card ──
        intro_lines = [
            f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
            f"{F.EMO['rocket']} <b>{F.fb('DELIVERING')}</b>",
            F.DIV, "",
            f"🎬 <b>{F.sc(title[:60])}</b>",
            f"📺 <b>Season {season:02d}</b>",
            f"🎯 <code>{quality}</code>",
        ]
        if language:
            intro_lines.append(f"🔊 <code>{language}</code>")
        intro_lines += [
            "",
            f"📁 <code>{len(hits)}</code> {F.sc('episodes')}",
            "",
            f"⏳ {F.sc('this may take a moment…')}",
        ]
        try:
            await message.reply_text(
                "\n".join(intro_lines),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass

        # ── Custom buttons ──
        custom_kb = _build_custom_kb(custom_buttons)

        # ── Deliver ──
        sent_ids: List[int] = []
        sent = 0
        failed = 0

        for i, h in enumerate(hits):
            try:
                ep = h.get("episode") or 0
                size_str = FM.size(int(h.get("file_size") or 0))
                file_id = h.get("file_id") or ""

                ctx = {
                    "title": title,
                    "series": title,
                    "season": season,
                    "episode": ep,
                    "quality": quality,
                    "language": language,
                    "lang": language,
                    "size": size_str,
                    "file_size": size_str,
                    "file_name": h.get("file_name") or "",
                    "year": "—",
                    "rating": "—",
                    "bot_username": "",
                }
                fallback = (
                    f"🎬 <b>{F.sc(title[:60])}</b>\n"
                    f"📺 S{season:02d}E{ep:02d} · <code>{quality}</code>"
                )
                caption = _safe_caption(caption_tpl, ctx, fallback)

                sent_msg = None

                # Method 1: send_cached_media
                if file_id:
                    try:
                        sent_msg = await client.send_cached_media(
                            chat_id=uid,
                            file_id=file_id,
                            caption=caption,
                            reply_markup=custom_kb,
                            parse_mode=ParseMode.HTML,
                        )
                    except FloodWait as e:
                        await asyncio.sleep(int(getattr(e, "value", 30) or 30) + 2)
                        try:
                            sent_msg = await client.send_cached_media(
                                chat_id=uid,
                                file_id=file_id,
                                caption=caption,
                                reply_markup=custom_kb,
                                parse_mode=ParseMode.HTML,
                            )
                        except Exception as e2:
                            logger.warning(f"[START] M1-retry: {e2}")
                    except Exception as e:
                        logger.warning(f"[START] M1: {e}")

                if sent_msg and sent_msg.id:
                    sent_ids.append(sent_msg.id)
                    sent += 1
                else:
                    failed += 1

                await asyncio.sleep(0.6)

            except Exception as e:
                failed += 1
                logger.debug(f"[START] deliver hit: {e}")

        # ── Auto-delete warning + schedule ──
        if auto_delete_min > 0 and sent_ids:
            try:
                warn = await message.reply_text(
                    "\n".join([
                        f"⚠️ <b>{F.fb('AUTO-DELETE')}</b>",
                        f"📌 {F.sc('this will be deleted in')} "
                        f"<b>{auto_delete_min} {F.sc('minutes')}</b>",
                        f"📌 {F.sc('save or forward now')}",
                    ]),
                    parse_mode=ParseMode.HTML,
                )
                if warn and warn.id:
                    sent_ids.append(warn.id)
            except Exception:
                pass

            asyncio.create_task(
                _auto_delete_batch(client, uid, sent_ids, auto_delete_min * 60)
            )

        # ── Summary ──
        try:
            await message.reply_text(
                "\n".join([
                    f"{F.EMO['check']} <b>{F.fb('DELIVERY COMPLETE')}</b>",
                    F.DIV, "",
                    f"🎬 <b>{F.sc(title[:50])}</b>",
                    f"📺 Season {season:02d} · {quality}",
                    "",
                    f"✅ {F.sc('sent')} · <code>{sent}</code>",
                    f"❌ {F.sc('failed')} · <code>{failed}</code>",
                    "",
                    f"🕒 <code>{FM.datetime_()}</code>",
                ]),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass

        await DL.mark_used(token)
        return True

    except Exception as e:
        logger.exception(f"[START] deliver: {e}")
        return False


# ============================================================
# DELIVERY HELPERS
# ============================================================

class _SafeDict(dict):
    def __missing__(self, key):
        return ""


def _safe_caption(template: str, ctx: dict, fallback: str) -> str:
    """Format caption safely — missing placeholders become empty."""
    if not template:
        return fallback
    try:
        return template.format_map(_SafeDict(ctx))
    except Exception:
        return fallback


def _build_custom_kb(buttons):
    """Build InlineKeyboardMarkup from group result_buttons."""
    if not buttons:
        return None
    rows = []
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


async def _auto_delete_batch(client, chat_id: int, msg_ids: List[int], seconds: int):
    """Delete all messages after N seconds."""
    try:
        await asyncio.sleep(seconds)
        for mid in msg_ids:
            try:
                await client.delete_messages(chat_id, mid)
            except Exception:
                pass
        logger.info(f"[START] auto-deleted {len(msg_ids)} msgs for {chat_id}")
    except asyncio.CancelledError:
        return
    except Exception as e:
        logger.debug(f"[START] auto-delete: {e}")

# ── REQ (deferred request from new user) ──

async def _handle_request(client, message, prefix, extra):
    """
    req_{token} — user tapped "Send Request" from a group.
    Posts the deferred request to admin channel.
    """
    try:
        from plugins.groups.shared import request_flow as RF
        token = str(extra or "").strip()
        if not token:
            return False
        handled = await RF.handle_req_token(client, message, token)
        return bool(handled)
    except Exception as e:
        logger.exception(f"[START] req route: {e}")
        return False


# ── GS (group settings from PM) ──

async def _handle_group_settings(client, message, prefix, extra):
    """
    gs_{chat_id} — open group settings panel from PM.
    """
    try:
        from plugins.groups import state as GS
        from plugins.groups import panel as GP

        try:
            chat_id = int(extra)
        except (ValueError, TypeError):
            return False

        uid = message.from_user.id

        # Verify admin
        ok = False
        try:
            m = await client.get_chat_member(chat_id, uid)
            st = getattr(m, "status", None)
            st_str = st.name.lower() if hasattr(st, "name") else str(st).lower()
            ok = st_str in ("administrator", "creator", "owner")
        except Exception:
            ok = False

        if not ok:
            # Allow bot admins
            try:
                ok = uid in [int(a) for a in config.ADMINS]
            except Exception:
                ok = False

        if not ok:
            await message.reply_text(
                f"{F.EMO['cross']} {F.sc('you are not admin of that group')}",
                parse_mode=ParseMode.HTML,
            )
            return True

        await GS.register_group(chat_id)
        text, kb = await GP.render_main(chat_id)
        await message.reply_text(
            text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        return True

    except Exception as e:
        logger.exception(f"[START] gs route: {e}")
        return False


# ── PREMIUM (unchanged — uses premium module) ──

async def _handle_premium(client, message, prefix, extra):
    """
    prem_{token} — open premium watch session.
    prem_start   — open premium menu.
    """
    try:
        slug = str(extra or "").strip()

        if slug in ("start", ""):
            try:
                from plugins.premium import premium_watch as PW
                await PW.cmd_premium(client, message)
                return True
            except Exception as e:
                logger.debug(f"[START] prem_start: {e}")
                return False

        from plugins.premium import deep_link as PDL
        handled = await PDL.handle_prem_token(client, message, slug)
        return bool(handled)

    except Exception as e:
        logger.debug(f"[START] premium route: {e}")
        return False


# ── REF (referral) ──

async def _handle_referral(client, message, prefix, extra):
    """ref_{user_id} — capture referral + welcome."""
    try:
        inviter_id = int(extra.split("_")[0])
        uid = message.from_user.id if message.from_user else 0
        if inviter_id and uid and inviter_id != uid:
            from database import db_registry
            from datetime import datetime
            db = db_registry.get_user_db()
            if db is not None:
                await db["users"].update_one(
                    {"user_id": uid},
                    {"$set": {
                        "referred_by": inviter_id,
                        "referred_at": datetime.utcnow(),
                    }},
                    upsert=True,
                )
    except Exception as e:
        logger.debug(f"[START] referral: {e}")

    await _send_welcome(message)
    return True


# ── WO (watch order — placeholder) ──

async def _handle_watch_order(client, message, prefix, extra):
    try:
        await message.reply_text(
            "\n".join([
                f"{F.EMO['book']} <b>{F.fb('WATCH ORDER')}</b>",
                F.DIV, "",
                f"📌 {F.sc('coming soon')}",
            ]),
            parse_mode=ParseMode.HTML,
        )
        return True
    except Exception:
        return False


# ── REGISTER ROUTES ──

register_route("file",    _handle_file)
register_route("deliver", _handle_deliver)
register_route("req",     _handle_request)
register_route("prem",    _handle_premium)
register_route("ref",     _handle_referral)
register_route("gs",      _handle_group_settings)
register_route("wo",      _handle_watch_order)


# ============================================================
# SECTION 8 — MAIN HANDLER
# ============================================================

@Client.on_message(
    filters.command("start") & filters.private,
    group=-9000,
)
async def start_router(client: Client, message: Message):
    """THE single /start handler."""
    with rocket.timer("start.route", log=False):
        try:
            # 1. Gates
            if await _check_maintenance(message):
                return
            if await _check_banned(message):
                return

            # 2. Register user
            await _register_user(message)

            # 3. Parse
            text = message.text or ""
            prefix, extra = parse_payload(text)

            # 4. No payload → welcome
            if not prefix:
                await _send_welcome(message)
                return

            # 5. Route
            handler = _routes.get(prefix)
            if handler is None:
                logger.info(f"[START] unknown payload prefix={prefix}")
                await _send_welcome(message)
                return

            handled = await handler(client, message, prefix, extra)
            if not handled:
                await _send_welcome(message)

        except Exception as e:
            logger.exception(f"[START] router crash: {e}")
            try:
                await message.reply_text(
                    f"{F.EMO['cross']} <b>{F.fb('ERROR')}</b>\n"
                    f"<i>{F.sc('please try again')}</i>",
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass


# ============================================================
# SECTION 9 — CALLBACK HANDLERS (welcome buttons)
# ============================================================

@Client.on_callback_query(filters.regex(r"^start:how$"), group=-9000)
async def cb_how(client, q: CallbackQuery):
    text = "\n".join([
        f"{F.EMO['search']} <b>{F.fb('HOW TO SEARCH')}</b>",
        F.DIV, "",
        f"{F.EMO['check']} {F.sc('go to our group')}",
        f"{F.EMO['check']} {F.sc('type a movie or series name')}",
        f"{F.EMO['check']} {F.sc('tap the file you want')}",
        f"{F.EMO['check']} {F.sc('the file arrives here in pm')}",
        "",
        F.DIV,
        f"{F.EMO['spark']} <i>{F.sc('that simple!')}</i>",
    ])
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data="start:home",
        ),
    ]])
    try:
        await q.message.edit_text(
            text, reply_markup=kb, parse_mode=ParseMode.HTML,
        )
    except Exception:
        pass
    await q.answer()


@Client.on_callback_query(filters.regex(r"^start:premium$"), group=-9000)
async def cb_premium(client, q: CallbackQuery):
    text = "\n".join([
        f"{F.EMO['crown']} <b>{F.fb('PREMIUM MEMBERSHIP')}</b>",
        F.DIV, "",
        f"{F.EMO['spark']} {F.sc('unlock exclusive features')}",
        "",
        f"{F.EMO['check']} {F.sc('watch progress tracking')}",
        f"{F.EMO['check']} {F.sc('resume from where you left off')}",
        f"{F.EMO['check']} {F.sc('watch order for franchises')}",
        f"{F.EMO['check']} {F.sc('priority support')}",
        "",
        F.DIV,
        f"{F.EMO['send']} {F.sc('contact admin to subscribe')}",
    ])
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"{F.EMO['users']} {F.sc('contact admin')}",
            url=config.OWNER_LNK or "https://t.me/",
        )],
        [InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data="start:home",
        )],
    ])
    try:
        await q.message.edit_text(
            text, reply_markup=kb, parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception:
        pass
    await q.answer()


@Client.on_callback_query(filters.regex(r"^start:home$"), group=-9000)
async def cb_home(client, q: CallbackQuery):
    name = q.from_user.first_name if q.from_user else ""
    try:
        await q.message.edit_text(
            _welcome_text(name),
            reply_markup=_welcome_kb(),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception:
        pass
    await q.answer()


# ============================================================
# SECTION 10 — SNAPSHOT
# ============================================================

def snapshot() -> dict:
    return {
        "routes": list_routes(),
        "maintenance": config.MAINTENANCE_MODE,
    }


# ============================================================
# SECTION 11 — PUBLIC EXPORTS
# ============================================================

__all__ = [
    "register_route",
    "unregister_route",
    "list_routes",
    "parse_payload",
    "build_link",
    "link_file",
    "link_deliver",
    "link_request",
    "link_group_settings",
    "link_premium",
    "link_referral",
    "snapshot",
]
