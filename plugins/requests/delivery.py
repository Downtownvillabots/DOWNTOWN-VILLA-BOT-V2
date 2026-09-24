# ============================================================
# 🏨 DOWNTOWN VILLA — REQUEST DELIVERY TOKENS
# ============================================================
# Small records that outlive the request token.
# Used by the "GET FILE" button after admin marks UPDATED.
# ============================================================

from __future__ import annotations
import logging, secrets, time
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_COLLECTION = "request_deliveries"
_TTL_DAYS = 30


def _db():
    """Best-effort: find the system DB handle."""
    try:
        from database import db_registry
    except Exception:
        return None

    for name in ("get_system_db", "system_db", "get_default_db"):
        attr = getattr(db_registry, name, None)
        if attr is None:
            continue
        try:
            return attr() if callable(attr) else attr
        except Exception:
            continue

    try:
        for e in db_registry.system_entries():
            return e.db
    except Exception:
        pass

    return None


async def create_delivery(
    user_id: int,
    movie_name: str,
    year: Optional[str] = None,
    kind: str = "movie",
) -> Optional[str]:
    db = _db()
    if db is None:
        logger.warning("[DELIVERY] no system DB")
        return None
    try:
        token = secrets.token_hex(6)
        await db[_COLLECTION].insert_one({
            "_id": token,
            "user_id": int(user_id),
            "movie_name": str(movie_name)[:200],
            "year": str(year) if year else None,
            "kind": str(kind or "movie"),
            "created_at": time.time(),
        })
        return token
    except Exception as e:
        logger.warning(f"[DELIVERY] create: {e}")
        return None


async def get_delivery(token: str) -> Optional[Dict[str, Any]]:
    db = _db()
    if db is None:
        return None
    try:
        return await db[_COLLECTION].find_one({"_id": str(token)})
    except Exception as e:
        logger.debug(f"[DELIVERY] get: {e}")
        return None


async def delete_delivery(token: str) -> bool:
    db = _db()
    if db is None:
        return False
    try:
        r = await db[_COLLECTION].delete_one({"_id": str(token)})
        return bool(r.deleted_count)
    except Exception as e:
        logger.debug(f"[DELIVERY] delete: {e}")
        return False


async def purge_expired() -> int:
    db = _db()
    if db is None:
        return 0
    try:
        cutoff = time.time() - (_TTL_DAYS * 86400)
        r = await db[_COLLECTION].delete_many({"created_at": {"$lt": cutoff}})
        return int(r.deleted_count or 0)
    except Exception:
        return 0


__all__ = [
    "create_delivery", "get_delivery",
    "delete_delivery", "purge_expired",
]
