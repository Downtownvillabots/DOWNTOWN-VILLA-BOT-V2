# ============================================================
# 🏨 DOWNTOWN VILLA — START ROUTER (FUTURISTIC)
# ============================================================
#
# Single source of truth for /start deep-links.
#
# Replaces the OLD messy multi-handler approach where:
#   • group_search.py::pm_start_handler   (priority -999)
#   • series_group.py::pm_start_handler   (priority -9998)
#   • premium_watch.py::...               (conflicts)
#
# All raced against each other.
#
# NEW DESIGN:
#   ONE handler. ONE route table. Deterministic.
#
# Supported payloads:
#   file_{sid}_{idx}      → group search → deliver file
#   deliver_{token}       → series group → batch deliver
#   prem_{slug}           → premium watch → resume session
#   prem_start            → premium watch → open panel
#   wo_{slug}             → watch order → open
#   ref_{user_id}         → referral → register + welcome
#   (empty)               → welcome message
#
# Features (new in v2):
#   • Route table (register/unregister at runtime)
#   • Auto register user on first /start
#   • Maintenance mode gate
#   • Ban check gate
#   • Referral capture
#   • Welcome message with configurable buttons
#   • New-user auto-start flow (from group → tap → file)
#   • Deep-link builder for every route
#   • Safe fallback for unknown payloads
#   • Rocket-timed routing
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

# handler signature:
#   async def handler(client, message, payload, extra) -> bool
#       return True if handled (stop further processing)
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
    Returns ("", "") for empty payload.
    """
    if not text:
        return "", ""
    parts = text.strip().split(maxsplit=1)
    if len(parts) < 2:
        return "", ""
    payload = parts[1].strip()
    if "_" in payload:
        head, tail = payload.split("_", 1)
        return head, tail
    return payload, ""


# ============================================================
# SECTION 3 — DEEP-LINK BUILDER
# ============================================================

def build_link(bot_username: str, payload: str) -> str:
    """Build https://t.me/<bot>?start=<payload>."""
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
    """Return True if we should block (maintenance mode active)."""
    if not config.MAINTENANCE_MODE:
        return False
    if message.from_user and message.from_user.id in config.ADMINS:
        return False

    text = "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"{F.EMO['gear']} {F.sc('maintenance mode')}",
        F.DIV,
        "",
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
    """Return True if user is banned."""
    from pyrogram.types import CallbackQuery  # noqa
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
            F.DIV,
            "",
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
    """Create/update user document on every /start."""
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
        F.DIV,
        "",
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
# SECTION 7 — ROUTE HANDLERS (default set)
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
    This is the NEW USER AUTO-START flow.
    """
    try:
        # extra looks like "abc123_3"
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
                    F.DIV,
                    "",
                    f"{F.EMO['search']} {F.sc('please search again in the group')}",
                ]),
                parse_mode=ParseMode.HTML,
            )
            return True

        if idx < 0 or idx >= len(session.candidates):
            await message.reply_text("❌ Invalid file.")
            return True

        data = session.candidates[idx]
        hit = FileHit(
            file_id=data.get("file_id", ""),
            file_unique_id=data.get("file_unique_id"),
            file_name=data.get("file_name"),
            file_size=data.get("file_size"),
            title=data.get("title", ""),
            normalized_title="",
            year=data.get("year"),
            type=data.get("type", "movie"),
            quality=data.get("quality"),
            codec=data.get("codec"),
            audio_languages=list(data.get("audio_languages") or []),
            subtitle_languages=list(data.get("subtitle_languages") or []),
            has_subtitle=bool(data.get("has_subtitle")),
            series_title=data.get("series_title"),
            season=data.get("season"),
            episode=data.get("episode"),
        )

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
    """deliver_{token} — series group batch delivery."""
    try:
        from plugins.series_group import series_group as _sg
        token = extra
        # Delegate to series_group if it exposes the handler
        fn = getattr(_sg, "handle_deliver_payload", None)
        if fn is not None:
            return await fn(client, message, token)
    except Exception as e:
        logger.debug(f"[START] deliver route: {e}")
    await message.reply_text(
        "\n".join([
            f"{F.EMO['warn']} <b>{F.fb('LINK EXPIRED')}</b>",
            F.DIV,
            "",
            f"{F.EMO['search']} {F.sc('please search again in the group')}",
        ]),
        parse_mode=ParseMode.HTML,
    )
    return True


async def _handle_premium(client, message, payload, extra):
    """prem_{slug} — open premium watch session."""
    try:
        from plugins.premium.premium_watch import open_session
        slug = extra
        return await open_session(client, message, slug)
    except Exception as e:
        logger.debug(f"[START] premium route: {e}")
        return False


async def _handle_watch_order(client, message, payload, extra):
    """wo_{slug} — open watch order."""
    try:
        from plugins.premium import premium_watch as _pw
        fn = getattr(_pw, "open_watch_order", None)
        if fn is not None:
            return await fn(client, message, extra)
    except Exception as e:
        logger.debug(f"[START] wo route: {e}")
    return False


# Register default routes
register_route("file",    _handle_file)
register_route("deliver", _handle_deliver)
register_route("prem",    _handle_premium)
register_route("wo",      _handle_watch_order)
register_route("ref",     _handle_referral)


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
    """
    THE single /start handler.
    Must run BEFORE every other /start handler (priority -9000).
    """
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
        F.DIV,
        "",
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
        F.DIV,
        "",
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
