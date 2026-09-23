# ============================================================
# 🏨 DOWNTOWN VILLA — START ROUTER (FUTURISTIC)
# ============================================================
#
# Single source of truth for /start deep-links.
#
# Supported payloads:
#   file_{sid}_{idx}      → group search → deliver file
#   deliver_{token}       → series group → batch deliver
#   prem_{token}          → premium watch → resume session
#   prem_start            → premium watch → open panel
#   wo_{slug}             → watch order → open
#   ref_{user_id}         → referral → register + welcome
#   gs:{chat_id}          → group settings panel
#   (empty)               → welcome message
#
# ============================================================

from __future__ import annotations

import logging
from typing import Awaitable, Callable, Dict, List, Optional, Tuple

from pyrogram import Client, filters
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
    """Register a payload prefix → handler."""
    _routes[prefix] = handler
    logger.info(f"[START] Route registered: {prefix}_*")


def unregister_route(prefix: str) -> None:
    _routes.pop(prefix, None)


def list_routes() -> List[str]:
    return sorted(_routes.keys())


# ============================================================
# SECTION 2 — PAYLOAD PARSER
# ============================================================

def parse_payload(text: str) -> Tuple[str, str]:
    """
    Split "/start file_abc_3" into ("file", "abc_3").
    Handles both "_" and ":" separators.
    Returns ("", "") for empty payload.
    """
    if not text:
        return "", ""
    parts = text.strip().split(maxsplit=1)
    if len(parts) < 2:
        return "", ""
    payload = parts[1].strip()
    if not payload:
        return "", ""
    # colon separator (gs:12345, etc.)
    if ":" in payload and "_" not in payload.split(":", 1)[0]:
        head, tail = payload.split(":", 1)
        return head, tail
    # underscore separator
    if "_" in payload:
        head, tail = payload.split("_", 1)
        return head, tail
    return payload, ""


# ============================================================
# SECTION 3 — DEEP-LINK BUILDER
# ============================================================

def build_link(bot_username: str, payload: str) -> str:
    if not bot_username:
        return "https://t.me/"
    return f"https://t.me/{bot_username}?start={payload}"


def link_file(bot_username: str, session_id: str, index: int) -> str:
    return build_link(bot_username, f"file_{session_id}_{index}")


def link_deliver(bot_username: str, token: str) -> str:
    return build_link(bot_username, f"deliver_{token}")


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
    if message.from_user and message.from_user.id in config.ADMINS:
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
        logger.debug(f"[START] ban check error: {e}")
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
        logger.debug(f"[START] register error: {e}")


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
                url=config.UPDATE_CHNL_LNK,
            ),
            InlineKeyboardButton(
                f"{F.EMO['users']} {F.sc('support')}",
                url=config.SUPPORT_CHAT,
            ),
        ],
    ])


# ============================================================
# SECTION 7 — ROUTE HANDLERS
# ============================================================

async def _handle_referral(client, message, payload, extra):
    """ref_{user_id} — capture referral + show welcome."""
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
        logger.debug(f"[START] referral error: {e}")
    await _send_welcome(message)
    return True


async def _handle_file(client, message, payload, extra):
    """
    file_{sid}_{idx} — deliver file from a search session.
    """
    try:
        parts = extra.rsplit("_", 1)
        if len(parts) != 2:
            return False
        sid, idx_str = parts
        idx = int(idx_str)
    except Exception:
        return False

    try:
        from media_search import sessions as _sess_mod
        from media_search import delivery as _del_mod
        from media_search.models import FileHit

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

        if idx < 0 or idx >= len(session.candidates):
            await message.reply_text("❌ Invalid file.")
            return True

        data = session.candidates[idx]
        hit = FileHit.from_dict(data)

        ok, err = await _del_mod.delivery.send_file(
            client, message.from_user.id, hit
        )
        if not ok and err:
            try:
                await message.reply_text(err)
            except Exception:
                pass
        return True
    except Exception as e:
        logger.exception(f"[START] file route: {e}")
        return False


async def _handle_deliver(client, message, payload, extra):
    """
    deliver_{token} — series group batch delivery.
    Loads token, verifies user, delivers every episode in token.
    """
    try:
        from plugins.series_group import deep_link as DL
        from media_search import delivery as _del_mod
        from media_search.models import FileHit

        token = str(extra or "").strip()
        if not token:
            return False

        data = await DL.get_token(token)
        if not data:
            await message.reply_text(
                "\n".join([
                    f"{F.EMO['warn']} <b>{F.fb('LINK EXPIRED')}</b>",
                    F.DIV, "",
                    f"{F.EMO['search']} {F.sc('please search again in the group')}",
                ]),
                parse_mode=ParseMode.HTML,
            )
            return True

        # Verify this token belongs to the user
        uid = message.from_user.id
        if int(data.get("user_id", 0)) != int(uid):
            await message.reply_text(
                f"{F.EMO['cross']} {F.sc('this link is not for you')}",
                parse_mode=ParseMode.HTML,
            )
            return True

        # Only handle "deliver" kind here
        if data.get("kind") != "deliver":
            return False

        title = str(data.get("title") or "?")
        season = data.get("season")
        quality = data.get("quality") or "?"
        language = data.get("language") or "—"
        episodes = list(data.get("episodes") or [])
        hits = list(data.get("hits") or [])

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

        # Progress card
        header = "\n".join([
            f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
            f"{F.EMO['rocket']} <b>{F.fb('DELIVERING')}</b>",
            F.DIV, "",
            f"🎬 <b>{F.sc(title[:50])}</b>",
            f"📺 <b>Season {int(season) if season else '?'}</b>",
            f"🎯 <code>{quality}</code> · 🔉 <code>{language}</code>",
            "",
            f"📁 <b>{len(hits)}</b> {F.sc('episodes queued')}",
            "",
            f"⏳ {F.sc('this may take a moment…')}",
        ])
        try:
            await message.reply_text(header, parse_mode=ParseMode.HTML)
        except Exception:
            pass

        # Deliver each hit
        sent = 0
        failed = 0
        for h in hits:
            try:
                hit = FileHit.from_dict(h) if isinstance(h, dict) else h
                ok, err = await _del_mod.delivery.send_file(client, uid, hit)
                if ok:
                    sent += 1
                else:
                    failed += 1
                    logger.debug(f"[START] deliver fail: {err}")
                # Small delay to avoid flood
                import asyncio
                await asyncio.sleep(0.7)
            except Exception as e:
                failed += 1
                logger.debug(f"[START] deliver hit: {e}")

        # Summary
        try:
            summary = "\n".join([
                f"{F.EMO['check']} <b>{F.fb('DELIVERY COMPLETE')}</b>",
                F.DIV, "",
                f"✅ {F.sc('sent')} · <b>{sent}</b>",
                f"❌ {F.sc('failed')} · <b>{failed}</b>",
                "",
                f"{F.EMO['spark']} <i>{F.sc('enjoy!')}</i>",
            ])
            await message.reply_text(summary, parse_mode=ParseMode.HTML)
        except Exception:
            pass

        # Mark token used
        try:
            await DL.mark_used(token)
        except Exception:
            pass

        return True

    except Exception as e:
        logger.exception(f"[START] deliver route: {e}")
        return False


async def _handle_premium(client, message, payload, extra):
    """
    prem_{token} — open premium watch session.
    prem_start   — open premium menu.
    """
    try:
        slug = str(extra or "").strip()

        # Special: prem_start → open menu
        if slug in ("start", ""):
            try:
                from plugins.premium import premium_watch as PW
                await PW.cmd_premium(client, message)
                return True
            except Exception as e:
                logger.debug(f"[START] prem_start: {e}")
                return False

        # Otherwise: treat as token
        from plugins.premium import deep_link as PDL
        handled = await PDL.handle_prem_token(client, message, slug)
        return bool(handled)
    except Exception as e:
        logger.debug(f"[START] premium route: {e}")
        return False


async def _handle_watch_order(client, message, payload, extra):
    """
    wo_{slug} — watch order placeholder.
    Watch order is a future feature; show a friendly message.
    """
    try:
        text = "\n".join([
            f"{F.EMO['book']} <b>{F.fb('WATCH ORDER')}</b>",
            F.DIV, "",
            f"📌 {F.sc('watch order for franchises')}",
            f"{F.EMO['clock']} {F.sc('coming soon')}",
            "",
            f"{F.EMO['spark']} <i>{F.sc('stay tuned!')}</i>",
        ])
        await message.reply_text(text, parse_mode=ParseMode.HTML)
        return True
    except Exception:
        return False


async def _handle_group_settings(client, message, payload, extra):
    """
    gs:{chat_id} — open group settings panel (from /settings in a group).
    """
    try:
        from plugins.group_admin import panel as P
        from plugins.group_admin import state as S

        chat_id = int(extra)
        uid = message.from_user.id

        # Verify user is admin in that group
        try:
            m = await client.get_chat_member(chat_id, uid)
            st = getattr(m, "status", None)
            st_str = (
                st.name.lower() if hasattr(st, "name") else str(st).lower()
            )
            if st_str not in ("administrator", "creator", "owner"):
                if uid not in [int(a) for a in config.ADMINS]:
                    await message.reply_text(
                        f"{F.EMO['cross']} {F.sc('you are not admin of that group')}",
                        parse_mode=ParseMode.HTML,
                    )
                    return True
        except Exception as e:
            logger.debug(f"[START] gs member check: {e}")
            return False

        await S.register_group(chat_id)
        text, kb = await P.render_main(chat_id)
        await message.reply_text(
            text, reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        return True
    except Exception as e:
        logger.debug(f"[START] gs route: {e}")
        return False

async def _handle_deferred_request(client, message, payload, extra):
    """
    req_{token} — user tapped "send request" from a group.
    Posts the deferred request to admin channel.
    """
    try:
        from plugins.search import deferred as DF
        token = str(extra or "").strip()
        if not token:
            return False
        handled = await DF.handle_req_token(client, message, token)
        return bool(handled)
    except Exception as e:
        logger.debug(f"[START] req route: {e}")
        return False

# Register default routes
register_route("req",     _handle_deferred_request)
register_route("file",    _handle_file)
register_route("deliver", _handle_deliver)
register_route("prem",    _handle_premium)
register_route("wo",      _handle_watch_order)
register_route("ref",     _handle_referral)
register_route("gs",      _handle_group_settings)


# ============================================================
# SECTION 8 — MAIN HANDLER
# ============================================================

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

            # 3. Parse payload
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
            logger.exception(f"[START] router crashed: {e}")
            try:
                await message.reply_text(
                    f"{F.EMO['cross']} <b>{F.fb('ERROR')}</b>\n"
                    f"<i>{F.sc('please try again')}</i>",
                    parse_mode=ParseMode.HTML,
                )
            except Exception:
                pass


# ============================================================
# SECTION 9 — CALLBACK HANDLERS
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
            text, reply_markup=kb, parse_mode=ParseMode.HTML
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
            url=config.OWNER_LNK,
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
    "link_premium",
    "link_referral",
    "snapshot",
]
