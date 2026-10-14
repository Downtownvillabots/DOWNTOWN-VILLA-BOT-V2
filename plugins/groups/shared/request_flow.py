# ============================================================
# 🏨 DOWNTOWN VILLA — GROUPS SHARED REQUEST FLOW
# ============================================================

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from pyrogram import Client
from pyrogram.enums import ParseMode
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from core import config
from utils import fonts as F

logger = logging.getLogger(__name__)
DIV = F.DIV


async def _resolve_request_channel(chat_id: int = 0) -> Optional[int]:
    if chat_id:
        try:
            from plugins.groups import state as GS
            cfg = await GS.get_config(int(chat_id))
            r_cfg = cfg.get("requests") or {}
            ch = r_cfg.get("channel")
            if ch:
                try:
                    return int(ch)
                except (TypeError, ValueError):
                    pass
        except Exception as e:
            logger.debug(f"[REQ-FLOW] group channel resolve: {e}")

    try:
        ch = getattr(config, "REQST_CHANNEL", None)
        if ch:
            return int(ch)
    except (TypeError, ValueError):
        pass
    return None


async def is_registered(user_id: int) -> bool:
    try:
        from database import db_registry
        db = db_registry.get_user_db()
        if db is None:
            return False
        doc = await db["users"].find_one({"user_id": int(user_id)}, {"_id": 1})
        return doc is not None
    except Exception as e:
        logger.debug(f"[REQ-FLOW] is_registered: {e}")
        return True


async def post_request(
    client: Client, user_id: int,
    username: str = "", full_name: str = "",
    title: str = "", year: Optional[int] = None,
    kind: str = "movie", tmdb_id: Optional[int] = None,
    chat_id: int = 0,
) -> Optional[str]:
    if not title:
        return None

    try:
        from plugins.requests import poster as REQ_POSTER
        token = await REQ_POSTER.post_request(
            client=client,
            user_id=int(user_id),
            username=username or "",
            full_name=full_name or "",
            movie_name=str(title)[:200],
            kind=str(kind or "movie"),
            tmdb_id=tmdb_id,
            year=str(year) if year else None,
            user_query=str(title)[:200],
        )
        if token:
            return token
    except ImportError:
        pass
    except Exception as e:
        logger.debug(f"[REQ-FLOW] requests.poster failed: {e}")

    try:
        return await _post_inline(
            client=client, user_id=int(user_id),
            username=username or "", full_name=full_name or "",
            title=str(title)[:200], year=year,
            kind=str(kind or "movie"), tmdb_id=tmdb_id,
            chat_id=chat_id,
        )
    except Exception as e:
        logger.exception(f"[REQ-FLOW] inline post failed: {e}")
        return None


async def _post_inline(
    client: Client, user_id: int, username: str, full_name: str,
    title: str, year: Optional[int], kind: str,
    tmdb_id: Optional[int], chat_id: int = 0,
) -> Optional[str]:
    token = await _store_request(
        user_id=user_id, username=username, full_name=full_name,
        title=title, year=year, kind=kind, tmdb_id=tmdb_id,
        chat_id=chat_id,
    )
    if not token:
        return None

    channel_id = await _resolve_request_channel(chat_id)
    if not channel_id:
        logger.debug("[REQ-FLOW] no request channel configured")
        return token

    is_series = str(kind).lower() == "series"
    kind_icon = "📺" if is_series else "🎬"
    kind_label = "SERIES" if is_series else "MOVIE"

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"{kind_icon} <b>{F.fb(f'NEW {kind_label} REQUEST')}</b>",
        DIV, "",
        f"{kind_icon} <b>{F.sc(title[:80])}</b>",
    ]
    if year:
        lines.append(f"📅 <code>{year}</code>")
    if tmdb_id:
        lines.append(f"🆔 ᴛᴍᴅʙ · <code>{tmdb_id}</code>")

    user_display = f"<a href='tg://user?id={user_id}'>{F.sc(full_name or 'user')}</a>"
    lines += [
        "", f"👤 ᴜꜱᴇʀ · {user_display}",
        f"🆔 ᴜꜱᴇʀ ɪᴅ · <code>{user_id}</code>",
    ]
    if username:
        lines.append(f"🔗 ᴜꜱᴇʀɴᴀᴍᴇ · @{F.sc(username.lstrip('@'))}")

    lines += [
        "", f"🔑 ᴛᴏᴋᴇɴ · <code>{token}</code>",
        DIV, "", f"<i>{F.sc('admin · choose an action')}</i>",
    ]

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"{kind_icon} {kind_label} UPDATED ✅",
            callback_data=f"req:updated:{token}",
        )],
        [
            InlineKeyboardButton("📅 NOT RELEASED",
                                 callback_data=f"req:notreleased:{token}"),
            InlineKeyboardButton("🔎 NOT FOUND",
                                 callback_data=f"req:notfound:{token}"),
        ],
        [InlineKeyboardButton("❌ CANCEL",
                              callback_data=f"req:cancel:{token}")],
    ])

    try:
        await client.send_message(
            chat_id=channel_id, text="\n".join(lines),
            reply_markup=kb, parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
        return token
    except Exception as e:
        logger.exception(f"[REQ-FLOW] post to channel: {e}")
        return token


async def _store_request(
    user_id: int, username: str, full_name: str, title: str,
    year: Optional[int], kind: str, tmdb_id: Optional[int],
    deferred: bool = False, chat_id: int = 0,
) -> Optional[str]:
    try:
        from plugins.requests import state as RS
        token = await RS.create_request(
            user_id=int(user_id), username=username or "",
            full_name=full_name or "", movie_name=str(title)[:200],
            kind=str(kind or "movie"), tmdb_id=tmdb_id,
            year=str(year) if year else None,
            user_query=str(title)[:200],
        )
        if token:
            return token
    except ImportError:
        pass
    except Exception as e:
        logger.debug(f"[REQ-FLOW] RS.create_request: {e}")

    return await _direct_store(
        user_id=user_id, username=username, full_name=full_name,
        title=title, year=year, kind=kind, tmdb_id=tmdb_id,
        deferred=deferred, chat_id=chat_id,
    )


async def _direct_store(
    user_id: int, username: str, full_name: str, title: str,
    year: Optional[int], kind: str, tmdb_id: Optional[int],
    deferred: bool = False, chat_id: int = 0,
) -> Optional[str]:
    try:
        import secrets
        from datetime import datetime, timedelta, timezone
        from database import db_registry

        db = db_registry.get_system_db()
        if db is None:
            return None

        token = secrets.token_urlsafe(8)[:12]
        now = datetime.now(timezone.utc)
        await db["search_requests"].insert_one({
            "token_id": token,
            "kind": str(kind or "movie"),
            "user_id": int(user_id),
            "username": str(username or ""),
            "full_name": str(full_name or ""),
            "movie_name": str(title)[:200],
            "tmdb_id": tmdb_id,
            "year": str(year) if year else None,
            "user_query": str(title)[:200],
            "status": "pending",
            "deferred": bool(deferred),
            "chat_id": int(chat_id) if chat_id else None,
            "created_at": now,
            "updated_at": now,
            "expires_at": now + timedelta(days=30),
        })
        return token
    except Exception as e:
        logger.exception(f"[REQ-FLOW] direct store: {e}")
        return None


async def create_deferred_request(
    user_id: int, username: str = "", full_name: str = "",
    title: str = "", year: Optional[str] = None,
    kind: str = "movie", tmdb_id: Optional[int] = None,
    chat_id: int = 0,
) -> Optional[str]:
    if not title:
        return None

    year_int: Optional[int] = None
    try:
        if year and str(year).isdigit():
            year_int = int(year)
    except Exception:
        year_int = None

    token = await _store_request(
        user_id=user_id, username=username, full_name=full_name,
        title=title, year=year_int, kind=kind, tmdb_id=tmdb_id,
        deferred=True, chat_id=chat_id,
    )
    return token


async def handle_req_token(client: Client, message, token: str) -> bool:
    try:
        if not token:
            await message.reply_text(
                "\n".join([
                    f"{F.EMO['warn']} <b>{F.fb('INVALID LINK')}</b>",
                    DIV, "",
                    f"📌 {F.sc('please search again in the group')}",
                ]),
                parse_mode=ParseMode.HTML,
            )
            return True

        req = await _load_request(token)
        if not req:
            await message.reply_text(
                "\n".join([
                    f"{F.EMO['warn']} <b>{F.fb('LINK EXPIRED')}</b>",
                    DIV, "",
                    f"📌 {F.sc('please search again in the group')}",
                ]),
                parse_mode=ParseMode.HTML,
            )
            return True

        uid = message.from_user.id if message.from_user else 0
        if int(req.get("user_id", 0)) != int(uid):
            await message.reply_text(
                f"{F.EMO['cross']} {F.sc('this link is not for you')}",
                parse_mode=ParseMode.HTML,
            )
            return True

        title = str(req.get("movie_name") or "?")
        year = req.get("year")
        kind = str(req.get("kind") or "movie")
        tmdb_id = req.get("tmdb_id")
        username = str(req.get("username") or "")
        full_name = str(req.get("full_name") or "")

        stored_chat_id = 0
        try:
            stored_chat_id = int(req.get("chat_id") or 0)
        except (TypeError, ValueError):
            stored_chat_id = 0

        channel_id = await _resolve_request_channel(stored_chat_id)
        if not channel_id:
            await message.reply_text(
                "\n".join([
                    f"{F.EMO['warn']} <b>{F.fb('REQUESTS DISABLED')}</b>",
                    DIV, "",
                    f"📌 {F.sc('admin has not configured requests')}",
                ]),
                parse_mode=ParseMode.HTML,
            )
            return True

        posted = False
        try:
            from plugins.requests import poster as REQ_POSTER
            posted_token = await REQ_POSTER.post_request(
                client=client, user_id=uid,
                username=username, full_name=full_name,
                movie_name=title, kind=kind, tmdb_id=tmdb_id,
                year=str(year) if year else None,
                user_query=title, existing_token=token,
            )
            posted = bool(posted_token)
        except ImportError:
            pass
        except Exception as e:
            logger.debug(f"[REQ-FLOW] poster reuse: {e}")

        if not posted:
            try:
                await _post_inline(
                    client=client, user_id=uid,
                    username=username, full_name=full_name,
                    title=title, year=_to_int(year),
                    kind=kind, tmdb_id=tmdb_id,
                    chat_id=stored_chat_id,
                )
                posted = True
            except Exception as e:
                logger.debug(f"[REQ-FLOW] inline reuse: {e}")

        if posted:
            await message.reply_text(
                "\n".join([
                    f"{F.EMO['check']} <b>{F.fb('REQUEST SENT')}</b>",
                    DIV, "",
                    f"🎬 <b>{F.sc(title[:60])}</b>",
                    *([f"📅 <code>{year}</code>"] if year else []),
                    "",
                    f"📌 {F.sc('admins have been notified')}",
                    f"📌 {F.sc('you will be messaged once uploaded')}",
                ]),
                parse_mode=ParseMode.HTML,
                disable_web_page_preview=True,
            )
        else:
            await message.reply_text(
                "\n".join([
                    f"{F.EMO['cross']} <b>{F.fb('COULD NOT SEND')}</b>",
                    DIV, "",
                    f"📌 {F.sc('please try again later')}",
                ]),
                parse_mode=ParseMode.HTML,
            )
        return True

    except Exception as e:
        logger.exception(f"[REQ-FLOW] handle_req_token: {e}")
        return False


async def _load_request(token: str) -> Optional[Dict[str, Any]]:
    try:
        from plugins.requests import state as RS
        doc = await RS.get_request(token)
        if doc:
            return doc
    except ImportError:
        pass
    except Exception as e:
        logger.debug(f"[REQ-FLOW] RS.get: {e}")

    try:
        from database import db_registry
        db = db_registry.get_system_db()
        if db is None:
            return None
        doc = await db["search_requests"].find_one({"token_id": token})
        if doc:
            doc.pop("_id", None)
            return doc
    except Exception as e:
        logger.debug(f"[REQ-FLOW] direct load: {e}")
    return None


def _to_int(v: Any) -> Optional[int]:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


__all__ = [
    "is_registered",
    "post_request",
    "create_deferred_request",
    "handle_req_token",
    "_resolve_request_channel",
]
