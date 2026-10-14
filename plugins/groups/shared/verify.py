# ============================================================
# 🏨 DOWNTOWN VILLA — GROUPS SHARED VERIFY
# ============================================================
#
# Shortener-based verification gate for file delivery.
#
# Two collections (SYSTEM DB):
#   verify_tokens  — one-shot tokens for the PM redirect
#   verify_grants  — active user+chat grants (after verify)
#
# Flow:
#   1. User taps file → no grant → create token + send card
#   2. User opens shortener → PM → /start v_{token}
#   3. Bot marks grant + tells user to return
#   4. User taps "I VERIFIED" → grant valid → deliver
#
# Public API:
#   is_verified(user_id, chat_id) → bool
#   create_verify_token(user_id, chat_id, ttl) → token | None
#   mark_verified(token) → bool
#   get_grant(user_id, chat_id) → dict | None
#   build_shortener_url(template, target) → str | None
#   build_verify_card(cfg, token) → (text, kb) | (None, None)
#   purge_expired() → int
#   ensure_indexes() → bool
#
# Self-contained /start handler (group -100001)
# ============================================================

from __future__ import annotations

import logging
import secrets
import time
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
DEFAULT_TOKEN_TTL = 1800   # 30 min — time to click the shortener
DEFAULT_GRANT_TTL = 1200   # 20 min — how long a verify lasts


# ============================================================
# SECTION 1 — DB HELPERS
# ============================================================

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


# ============================================================
# SECTION 2 — TOKEN STORE
# ============================================================

def _new_token() -> str:
    return secrets.token_urlsafe(10)[:14]


async def create_verify_token(
    user_id: int,
    chat_id: int,
    ttl: int = DEFAULT_TOKEN_TTL,
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
    """
    Mark a token verified AND create a grant for its user+chat.
    """
    doc = await get_token(token)
    if not doc:
        return False

    user_id = int(doc.get("user_id", 0))
    chat_id = int(doc.get("chat_id", 0))
    if not user_id or not chat_id:
        return False

    now = datetime.now(timezone.utc)

    # Mark token
    try:
        c = _tokens()
        if c is not None:
            await c.update_one(
                {"token": str(token)},
                {"$set": {
                    "verified": True,
                    "verified_at": now,
                }},
            )
    except Exception:
        pass

    # Create/refresh grant
    try:
        g = _grants()
        if g is not None:
            # Get verify_time from the group config if available
            ttl = DEFAULT_GRANT_TTL
            try:
                from plugins.groups import state as GS
                cfg = await GS.get_config(chat_id)
                v = cfg.get("verify") or {}
                ttl = int(v.get("verify_time", DEFAULT_GRANT_TTL) or
                          DEFAULT_GRANT_TTL)
            except Exception:
                pass
            ttl = max(60, min(86400, ttl))

            # Preserve first_verified_at across re-verifies
            existing = await g.find_one({
                "user_id": user_id, "chat_id": chat_id,
            })
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
# SECTION 3 — GRANT LOOKUP
# ============================================================

async def get_grant(
    user_id: int, chat_id: int,
) -> Optional[Dict[str, Any]]:
    g = _grants()
    if g is None:
        return None
    try:
        doc = await g.find_one({
            "user_id": int(user_id),
            "chat_id": int(chat_id),
        })
        if not doc:
            return None
        until = doc.get("until")
        if isinstance(until, datetime):
            now = datetime.now(timezone.utc)
            if until.tzinfo is None:
                now = datetime.utcnow()
            if until < now:
                try:
                    await g.delete_one({
                        "user_id": int(user_id),
                        "chat_id": int(chat_id),
                    })
                except Exception:
                    pass
                return None
        return doc
    except Exception:
        return None


async def is_verified(user_id: int, chat_id: int) -> bool:
    doc = await get_grant(user_id, chat_id)
    return doc is not None


# ── Return-user shortcut ──
# If the user has verified in the last N hours, auto-renew their
# grant without making them open the shortener again.
RETURN_USER_WINDOW = 24 * 3600   # 24 hours


async def try_auto_renew(
    user_id: int,
    chat_id: int,
) -> bool:
    """
    If the user has verified in the last RETURN_USER_WINDOW seconds,
    create a fresh grant immediately and return True.

    If no prior verification exists (or it's too old), return False
    — the caller should fall back to the full verify flow.
    """
    g = _grants()
    if g is None:
        return False

    try:
        now = datetime.now(timezone.utc)
        cutoff = now - timedelta(seconds=RETURN_USER_WINDOW)

        # Find a recent verify for this user+chat (even if `until`
        # has passed — we look at last_verified_at).
        doc = await g.find_one({
            "user_id": int(user_id),
            "chat_id": int(chat_id),
        })
        if not doc:
            return False

        # Read the most recent verification moment
        last = doc.get("verified_at") or doc.get("first_verified_at")
        if not isinstance(last, datetime):
            return False
        # Normalise tz
        if last.tzinfo is None:
            last_aware = last.replace(tzinfo=timezone.utc)
        else:
            last_aware = last
        if last_aware < cutoff:
            return False

        # Within window → refresh grant
        # Pull TTL from group config
        ttl = DEFAULT_GRANT_TTL
        try:
            from plugins.groups import state as GS
            cfg = await GS.get_config(chat_id)
            v = cfg.get("verify") or {}
            ttl = int(v.get("verify_time", DEFAULT_GRANT_TTL) or
                      DEFAULT_GRANT_TTL)
        except Exception:
            pass
        ttl = max(60, min(86400, ttl))

        await g.update_one(
            {"user_id": int(user_id), "chat_id": int(chat_id)},
            {"$set": {
                "user_id": int(user_id),
                "chat_id": int(chat_id),
                "verified_at": now,
                "first_verified_at": last_aware,
                "until": now + timedelta(seconds=ttl),
                "auto_renewed": True,
            }},
            upsert=True,
        )
        logger.info(
            f"[VERIFY] auto-renew uid={user_id} chat={chat_id} "
            f"for {ttl}s"
        )
        return True

    except Exception as e:
        logger.debug(f"[VERIFY] auto-renew: {e}")
        return False


# ============================================================
# SECTION 4 — SHORTENER URL BUILDER
# ============================================================

def build_shortener_url(
    template: str,
    target: str,
) -> Optional[str]:
    """
    Build the final shortener URL from a template.

    Supported shapes:
      • https://short.link/api?key=X&url={url}   → substitute {url}
      • https://short.link/api?key=X&url=        → append encoded url
      • https://short.link/                      → return as-is (no target)
    """
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
    # Fallback — no way to inject, hand back as-is
    return template


# ============================================================
# SECTION 5 — VERIFY CARD
# ============================================================

async def build_verify_card(
    client: Client,
    cfg: Dict[str, Any],
    chat_id: int,
    user_id: int,
    shortener_target: str,
) -> Tuple[Optional[str], Optional[InlineKeyboardMarkup]]:
    """
    Build the verify card text + keyboard.

    shortener_target — the PM link that the shortener will redirect to.
    Returns (text, keyboard) or (None, None) on error.
    """
    verify = cfg.get("verify") or {}
    template = str(verify.get("shortener_url") or "").strip()
    if not template:
        return None, None

    # Create token
    token = await create_verify_token(user_id, chat_id)
    if not token:
        return None, None

    # Build shortener link
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
        f"📌 {F.sc('then come back and tap')} "
        f"<b>{F.sc('i verified')}</b>",
        "",
        f"⏱️ {F.sc('verification valid for')} <b>{t_str}</b>",
        "",
        DIV,
        f"⚠️ {F.sc('do not close the shortener early')}",
    ])

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"🔗 {F.sc('verify now')}",
            url=short_url,
        )],
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
# SECTION 6 — /start v_{token} HANDLER (self-contained)
# ============================================================
#
# Runs at group -100001 — before series_delivery_start (-100000).
# Claims /start messages whose payload starts with "v_".

@Client.on_message(
    filters.private & filters.command("start"),
    group=-100001,
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
                f"📌 {F.sc('files will be delivered')}",
            ]),
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception:
        pass


# ============================================================
# SECTION 7 — CLEANUP
# ============================================================

async def purge_expired() -> int:
    """Delete expired tokens + grants. Returns total removed."""
    total = 0
    now = datetime.now(timezone.utc)
    for coll, field in (
        (_tokens(), "expires_at"),
        (_grants(), "until"),
    ):
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
        await t.create_index(
            "expires_at", expireAfterSeconds=0, name="vttl",
        )
        await g.create_index(
            [("user_id", 1), ("chat_id", 1)],
            unique=True, name="vgrant_uq",
        )
        await g.create_index(
            "until", expireAfterSeconds=0, name="vgrant_ttl",
        )
        _indexes_ready = True
        logger.info("[VERIFY] indexes ready")
        return True
    except Exception as e:
        logger.warning(f"[VERIFY] index: {e}")
        return False


# ============================================================
# SECTION 8 — SNAPSHOT
# ============================================================

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
