# ============================================================
# 🏨 DOWNTOWN VILLA — REQUESTS STATE
# ============================================================
#
# Collections (SYSTEM DB):
#   search_requests     — user requests + tokens
#
# SCHEMA:
#   {
#     "_id": ObjectId,
#     "token_id": "abc123",
#     "kind": "movie" | "series",
#     "user_id": 123,
#     "username": "john",
#     "full_name": "John Doe",
#     "movie_name": "Braking bad",
#     "imdb_id": "tt0903747",
#     "tmdb_id": 1396,
#     "year": "2008",
#     "user_query": "braking bad",
#     "status": "pending" | "updated" | "not_released"
#             | "not_found" | "cancelled" | "fulfilled",
#     "created_at": ISODate,
#     "updated_at": ISODate,
#     "expires_at": ISODate,
#   }
#
# ============================================================

from __future__ import annotations
import logging, time, uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

REQUEST_TTL_DAYS = 30


def _coll():
    try:
        from database import db_registry
        db = db_registry.get_system_db()
        return db["search_requests"] if db is not None else None
    except Exception:
        return None


async def ensure_indexes() -> bool:
    c = _coll()
    if c is None:
        return False
    try:
        await c.create_index("token_id", unique=True)
        await c.create_index("expires_at", expireAfterSeconds=0)
        await c.create_index([
            ("user_id", 1), ("movie_name", 1), ("status", 1),
        ])
        return True
    except Exception as e:
        logger.warning(f"[REQ] index: {e}")
        return False


async def create_request(
    user_id: int,
    username: str = "",
    full_name: str = "",
    movie_name: str = "",
    kind: str = "movie",
    imdb_id: Optional[str] = None,
    tmdb_id: Optional[int] = None,
    year: Optional[str] = None,
    user_query: str = "",
) -> Optional[str]:
    c = _coll()
    if c is None:
        return None
    try:
        token = uuid.uuid4().hex[:12]
        now = datetime.now(timezone.utc)
        await c.insert_one({
            "token_id": token,
            "kind": kind,
            "user_id": int(user_id),
            "username": username or "",
            "full_name": full_name or "",
            "movie_name": movie_name or "?",
            "imdb_id": imdb_id,
            "tmdb_id": tmdb_id,
            "year": year,
            "user_query": user_query or movie_name,
            "status": "pending",
            "created_at": now,
            "updated_at": now,
            "expires_at": now + timedelta(days=REQUEST_TTL_DAYS),
        })
        logger.info(f"[REQ] created token={token} user={user_id}")
        return token
    except Exception as e:
        logger.warning(f"[REQ] create: {e}")
        return None


async def get_request(token: str) -> Optional[Dict[str, Any]]:
    c = _coll()
    if c is None:
        return None
    try:
        return await c.find_one({"token_id": token})
    except Exception:
        return None


async def update_status(token: str, status: str) -> bool:
    c = _coll()
    if c is None:
        return False
    try:
        r = await c.update_one(
            {"token_id": token},
            {"$set": {
                "status": status,
                "updated_at": datetime.now(timezone.utc),
            }},
        )
        return r.matched_count > 0
    except Exception:
        return False


async def delete_request(token: str) -> bool:
    c = _coll()
    if c is None:
        return False
    try:
        r = await c.delete_one({"token_id": token})
        return r.deleted_count > 0
    except Exception:
        return False


async def count_pending() -> int:
    c = _coll()
    if c is None:
        return 0
    try:
        return await c.count_documents({"status": "pending"})
    except Exception:
        return 0


async def list_recent(limit: int = 20) -> List[Dict[str, Any]]:
    c = _coll()
    if c is None:
        return []
    try:
        cur = c.find({}).sort("created_at", -1).limit(int(limit))
        return await cur.to_list(length=int(limit))
    except Exception:
        return []


async def cleanup_expired() -> int:
    c = _coll()
    if c is None:
        return 0
    try:
        r = await c.delete_many({
            "expires_at": {"$lt": datetime.now(timezone.utc)}
        })
        return r.deleted_count
    except Exception:
        return 0


__all__ = [
    "create_request", "get_request", "update_status", "delete_request",
    "count_pending", "list_recent", "cleanup_expired",
    "ensure_indexes", "REQUEST_TTL_DAYS",
]
