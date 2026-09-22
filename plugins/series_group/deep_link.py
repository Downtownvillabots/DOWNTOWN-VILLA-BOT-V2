# ============================================================
# 🏨 DOWNTOWN VILLA — SERIES DEEP LINK TOKENS
# ============================================================
#
# Tokens stored in DB → survive bot restarts → up to 1 hour TTL.
#
# Two token kinds:
#   deliver_{token}  → batch delivery of episodes to PM
#   prem_{slug}      → premium watch session open
#
# ============================================================

from __future__ import annotations

import logging
import secrets
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


COLLECTION = "series_tokens"
TTL_SECONDS = 3600       # 1 hour


def _coll():
    try:
        from database import db_registry
        db = db_registry.get_system_db()
        if db is None:
            return None
        return db[COLLECTION]
    except Exception:
        return None


# ============================================================
# CREATE
# ============================================================

async def create_deliver_token(
    user_id: int,
    chat_id: int,
    title: str,
    tmdb_id: Optional[int],
    season: int,
    quality: str,
    language: str,
    episodes: List[int],
    hits: List[Dict[str, Any]],
) -> Optional[str]:
    """Create a token for batch episode delivery."""
    c = _coll()
    if c is None:
        return None

    try:
        token = secrets.token_urlsafe(10)[:14]
        now = datetime.utcnow()

        await c.insert_one({
            "token": token,
            "kind": "deliver",
            "user_id": int(user_id),
            "chat_id": int(chat_id),
            "title": str(title)[:200],
            "tmdb_id": int(tmdb_id) if tmdb_id else None,
            "season": int(season),
            "quality": str(quality),
            "language": str(language),
            "episodes": [int(e) for e in episodes],
            "hits": list(hits[:100]),
            "created_at": now,
            "expires_at": now + timedelta(seconds=TTL_SECONDS),
            "used": False,
        })
        logger.info(f"[SG-LINK] deliver token created: {token}")
        return token
    except Exception as e:
        logger.exception(f"[SG-LINK] create deliver: {e}")
        return None


async def create_premium_token(
    user_id: int,
    chat_id: int,
    title: str,
    slug: str,
    tmdb_id: Optional[int],
    hits: List[Dict[str, Any]],
) -> Optional[str]:
    """Create a token for premium watch session open."""
    c = _coll()
    if c is None:
        return None

    try:
        token = secrets.token_urlsafe(10)[:14]
        now = datetime.utcnow()

        await c.insert_one({
            "token": token,
            "kind": "premium",
            "user_id": int(user_id),
            "chat_id": int(chat_id),
            "title": str(title)[:200],
            "slug": str(slug)[:100],
            "tmdb_id": int(tmdb_id) if tmdb_id else None,
            "hits": list(hits[:100]),
            "created_at": now,
            "expires_at": now + timedelta(seconds=TTL_SECONDS),
            "used": False,
        })
        logger.info(f"[SG-LINK] premium token created: {token}")
        return token
    except Exception as e:
        logger.exception(f"[SG-LINK] create premium: {e}")
        return None


# ============================================================
# READ
# ============================================================

async def get_token(token: str) -> Optional[Dict[str, Any]]:
    c = _coll()
    if c is None or not token:
        return None
    try:
        doc = await c.find_one({"token": token})
        if not doc:
            return None

        exp = doc.get("expires_at")
        if isinstance(exp, datetime) and exp < datetime.utcnow():
            await c.delete_one({"token": token})
            return None

        doc.pop("_id", None)
        return doc
    except Exception as e:
        logger.debug(f"[SG-LINK] get: {e}")
        return None


async def mark_used(token: str) -> None:
    c = _coll()
    if c is None:
        return
    try:
        await c.update_one(
            {"token": token},
            {"$set": {"used": True, "used_at": datetime.utcnow()}},
        )
    except Exception:
        pass


# ============================================================
# CLEANUP
# ============================================================

async def cleanup_expired() -> int:
    c = _coll()
    if c is None:
        return 0
    try:
        r = await c.delete_many({
            "expires_at": {"$lt": datetime.utcnow()}
        })
        return r.deleted_count
    except Exception:
        return 0


async def ensure_indexes() -> bool:
    c = _coll()
    if c is None:
        return False
    try:
        await c.create_index("token", unique=True)
        await c.create_index("expires_at", expireAfterSeconds=0)
        return True
    except Exception:
        return False


# ============================================================
# PUBLIC
# ============================================================

__all__ = [
    "create_deliver_token",
    "create_premium_token",
    "get_token",
    "mark_used",
    "cleanup_expired",
    "ensure_indexes",
    "TTL_SECONDS",
]
