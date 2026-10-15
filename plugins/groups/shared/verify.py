# ============================================================
# 🏨 DOWNTOWN VILLA — VERIFY (shortener gate)
# ============================================================

from __future__ import annotations

import logging
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional, Tuple
from urllib.parse import quote

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import (
    InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from utils import fonts as F

logger = logging.getLogger(__name__)
DIV = F.DIV

TOKENS_COLL = "verify_tokens"
GRANTS_COLL = "verify_grants"
DEFAULT_TOKEN_TTL = 1800
DEFAULT_GRANT_TTL = 1200
RETURN_USER_WINDOW = 24 * 3600


def _db():
    try:
        from database import db_registry
        return db_registry.get_system_db()
    except Exception:
        return None


def _tokens():
    db = _db()
    return db[TOKENS_COLL] if db is not None else None


def _grants():
    db = _db()
    return db[GRANTS_COLL] if db is not None else None


def _new_token() -> str:
    return secrets.token_urlsafe(10)[:14]


# ============================================================
# TOKEN STORE
# ============================================================

async def create_verify_token(
    user_id: int, chat_id: int, ttl: int = DEFAULT_TOKEN_TTL,
) -> Optional[str]:
    c = _tokens()
    if c is None:
        return None
    try:
        token = _new_token()
        now = datetime.now(timezone.utc)
        await c.insert_one({
            "token": token,
            "user_id": int(user_id),
            "chat_id": int(chat_id),
            "used": False,
            "verified": False,
            "created_at": now,
            "expires_at": now + timedelta(seconds=int(ttl)),
        })
        return token
    except Exception as e:
        logger.warning(f"[VERIFY] create: {e}")
        return None


async def get_token(token: str) -> Optional[Dict[str, Any]]:
    c = _tokens()
    if c is None or not token:
        return None
    try:
        doc = await c.find_one({"token": str(token)})
        if not doc:
            return None
        exp = doc.get("expires_at")
        if isinstance(exp, datetime):
            now = datetime.now(timezone.utc)
            if exp.tzinfo is None:
                now = datetime.utcnow()
            if exp < now:
                return None
        doc.pop("_id", None)
        return doc
    except Exception:
        return None


async def mark_verified(token: str) -> bool:
    doc = await get_token(token)
    if not doc:
        return False
    user_id = int(doc.get("user_id", 0))
    chat_id = int(doc.get("chat_id", 0))
    if not user_id or not chat_id:
        return False

    now = datetime.now(timezone.utc)

    try:
        c = _tokens()
        if c is not None:
            await c.update_one(
                {"token": str(token)},
                {"$set": {"verified": True, "verified_at": now}},
            )
    except Exception:
        pass

    try:
        g = _grants()
        if g is not None:
            ttl = DEFAULT_GRANT_TTL
            try:
                from plugins.groups import state as GS
                cfg = await GS.get_config(chat_id)
                v = cfg.get("verify") or {}
                ttl = int(v.get("verify_time", DEFAULT_GRANT_TTL) or DEFAULT_GRANT_TTL)
            except Exception:
                pass
            ttl = max(60, min(86400, ttl))

            existing = await g.find_one({"user_id": user_id, "chat_id": chat_id})
            first_at = (existing or {}).get("first_verified_at")
            if not isinstance(first_at, datetime):
                first_at = now

            await g.update_one(
                {"user_id": user_id, "chat_id": chat_id},
                {"$set": {
                    "user_id": user_id,
                    "chat_id": chat_id,
                    "verified_at": now,
                    "first_verified_at": first_at,
                    "until": now + timedelta(seconds=ttl),
                    "auto_renewed": False,
                }},
                upsert=True,
            )
    except Exception as e:
        logger.debug(f"[VERIFY] grant: {e}")

    return True


# ============================================================
# GRANT LOOKUP
# ============================================================

async def get_grant(user_id: int, chat_id: int) -> Optional[Dict[str, Any]]:
    g = _grants()
    if g is None:
        return None
    try:
        doc = await g.find_one({"user_id": int(user_id), "chat_id": int(chat_id)})
        if not doc:
            return None
        until = doc.get("until")
        if isinstance(until, datetime):
            now = datetime.now(timezone.utc)
            if until.tzinfo is None:
                now = datetime.utcnow()
            if until < now:
                try:
                    await g.delete_one({"user_id": int(user_id), "chat_id": int(chat_id)})
                except Exception:
                    pass
                return None
        return doc
    except Exception:
        return None


async def is_verified(user_id: int, chat_id: int) -> bool:
    doc = await get_grant(user_id, chat_id)
    return doc is not None


async def try_auto_renew(user_id: int, chat_id: int) -> bool:
    g = _grants()
    if g is None:
        return False
    try:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=RETURN_USER_WINDOW)
        doc = await g.find_one({"user_id": int(user_id), "chat_id": int(chat_id)})
        if not doc:
            return False
        last = doc.get("verified_at") or doc.get("first_verified_at")
        if not isinstance(last, datetime):
            return False
        last_aware = last if last.tzinfo else last.replace(tzinfo=timezone.utc)
        if last_aware < cutoff:
            return False

        ttl = DEFAULT_GRANT_TTL
        try:
            from plugins.groups import state as GS
            cfg = await GS.get_config(chat_id)
            v = cfg.get("verify") or {}
            ttl = int(v.get("verify_time", DEFAULT_GRANT_TTL) or DEFAULT_GRANT_TTL)
        except Exception:
            pass
        ttl = max(60, min(86400, ttl))

        await g.update_one(
            {"user_id": int(user_id), "chat_id": int(chat_id)},
            {"$set": {
                "user_id": int(user_id),
                "chat_id": int(chat_id),
                "verified_at": now,
                "until": now + timedelta(seconds=ttl),
                "auto_renewed": True,
            }},
            upsert=True,
        )
        logger.info(f"[VERIFY] auto-renew uid={user_id} chat={chat_id} for {ttl}s")
        return True
    except Exception as e:
        logger.debug(f"[VERIFY] auto-renew: {e}")
        return False


# ============================================================
# SHORTENER URL
# ============================================================

def build_shortener_url(template: str, target: str) -> Optional[str]:
    if not template:
        return None
    if not target:
        return template
    encoded = quote(target, safe="")
    if "{url}" in template:
        return template.replace("{url}", encoded)
    if template.endswith("="):
        return template + encoded
    if template.endswith("?"):
        return template + "url=" + encoded
    return template


# ============================================================
# VERIFY CARD
# ============================================================

async def build_verify_card(
    client: Client, cfg: Dict[str, Any],
    chat_id: int, user_id: int, shortener_target: str,
) -> Tuple[Optional[str], Optional[InlineKeyboardMarkup]]:
    verify = cfg.get("verify") or {}
    template = str(verify.get("shortener_url") or "").strip()
    if not template:
        return None, None

    token = await create_verify_token(user_id, chat_id)
    if not token:
        return None, None

    short_url = build_shortener_url(template, shortener_target)
    if not short_url:
        return None, None

    vtime = int(verify.get("verify_time", 1200) or 1200)
    if vtime < 60:
        vtime = 60
    if vtime < 60:
        t_str = f"{vtime}s"
    elif vtime < 3600:
        t_str = f"{vtime // 60} min"
    else:
        t_str = f"{vtime // 3600}h"

    text = "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"🔐 <b>{F.fb('VERIFICATION REQUIRED')}</b>",
        DIV, "",
        f"📌 {F.sc('tap the button below to verify')}",
        f"📌 {F.sc('then come back and tap')} <b>{F.sc('i verified')}</b>",
        "",
        f"⏱️ {F.sc('verification valid for')} <b>{t_str}</b>",
        "",
        DIV,
        f"⚠️ {F.sc('do not close the shortener early')}",
    ])

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(f"🔗 {F.sc('verify now')}", url=short_url)],
        [InlineKeyboardButton(
            f"✅ {F.sc('i verified')}",
            callback_data=f"sr:vchk:{token}",
        )],
        [InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('close')}",
            callback_data="sr:cancel",
        )],
    ])
    return text, kb


# ============================================================
# /start v_{token}
# ============================================================

@Client.on_message(
    filters.private & filters.command("start"),
    group=6,
)
async def verify_start_handler(client: Client, message: Message):
    if not message.from_user:
        return
    cmd = getattr(message, "command", None) or []
    if len(cmd) < 2:
        return
    payload = str(cmd[1] or "").strip()
    if not payload.startswith("v_"):
        return

    token = payload[2:].strip()
    if not token:
        return

    try:
        message.stop_propagation()
    except Exception:
        pass

    uid = int(message.from_user.id)
    doc = await get_token(token)

    if not doc:
        try:
            await message.reply_text(
                "\n".join([
                    f"{F.EMO['warn']} <b>{F.fb('LINK EXPIRED')}</b>",
                    DIV, "",
                    f"📌 {F.sc('please search again in the group')}",
                ]),
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        return

    owner = int(doc.get("user_id", 0))
    if owner != uid:
        try:
            await message.reply_text(
                f"{F.EMO['cross']} {F.sc('this link is not for you')}",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        return

    ok = await mark_verified(token)
    if not ok:
        try:
            await message.reply_text(
                f"{F.EMO['cross']} {F.sc('something went wrong')}",
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
        return

    try:
        await message.reply_text(
            "\n".join([
                f"{F.EMO['check']} <b>{F.fb('VERIFIED!')}</b>",
                DIV, "",
                f"📌 {F.sc('return to the group')}",
                f"📌 {F.sc('tap the file button again')}",
            ]),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception:
        pass


# ============================================================
# CLEANUP + INDEXES
# ============================================================

async def purge_expired() -> int:
    total = 0
    now = datetime.now(timezone.utc)
    for coll, field in ((_tokens(), "expires_at"), (_grants(), "until")):
        if coll is None:
            continue
        try:
            r = await coll.delete_many({field: {"$lt": now}})
            total += int(r.deleted_count or 0)
        except Exception:
            continue
    return total


_indexes_ready = False


async def ensure_indexes() -> bool:
    global _indexes_ready
    if _indexes_ready:
        return True
    t = _tokens()
    g = _grants()
    if t is None or g is None:
        return False
    try:
        await t.create_index("token", unique=True, name="vtoken_uq")
        await t.create_index("expires_at", expireAfterSeconds=0, name="vttl")
        await g.create_index(
            [("user_id", 1), ("chat_id", 1)],
            unique=True, name="vgrant_uq",
        )
        await g.create_index("until", expireAfterSeconds=0, name="vgrant_ttl")
        _indexes_ready = True
        logger.info("[VERIFY] indexes ready")
        return True
    except Exception as e:
        logger.warning(f"[VERIFY] index: {e}")
        return False


def snapshot() -> Dict[str, Any]:
    return {
        "tokens_collection": TOKENS_COLL,
        "grants_collection": GRANTS_COLL,
        "token_ttl": DEFAULT_TOKEN_TTL,
        "grant_ttl": DEFAULT_GRANT_TTL,
        "indexes_ready": _indexes_ready,
    }


__all__ = [
    "is_verified",
    "get_grant",
    "create_verify_token",
    "get_token",
    "mark_verified",
    "build_shortener_url",
    "build_verify_card",
    "purge_expired",
    "ensure_indexes",
    "snapshot",
    "try_auto_renew",
    "DEFAULT_TOKEN_TTL",
    "DEFAULT_GRANT_TTL",
    "RETURN_USER_WINDOW",
]
