from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Tuple

from pymongo.errors import DuplicateKeyError

logger = logging.getLogger(__name__)


async def register_user(user: Any) -> Tuple[bool, bool]:
    """Upsert a user as active; return (is_new, was_reactivated)."""
    if user is None:
        return False, False

    from database import db_registry

    db = db_registry.get_user_db()
    if db is None:
        logger.warning("[USERS] cannot register user: user database unavailable")
        return False, False

    uid = int(user.id)
    now = datetime.utcnow()
    collection = db["users"]
    existing = await collection.find_one(
        {"$or": [{"user_id": uid}, {"id": uid}]},
        {"blocked_bot": 1, "is_active": 1, "status": 1},
    )
    was_reactivated = bool(
        existing
        and (
            existing.get("blocked_bot")
            or existing.get("is_active") is False
            or existing.get("status") == "inactive"
        )
    )
    values = {
        "user_id": uid,
        "username": user.username or "",
        "first_name": user.first_name or "",
        "last_name": user.last_name or "",
        "language_code": user.language_code or "",
        "last_seen": now,
        "blocked_bot": False,
        "is_active": True,
        "status": "active",
    }
    if was_reactivated:
        values["unblocked_at"] = now

    query = {"_id": existing["_id"]} if existing else {"user_id": uid}
    try:
        result = await collection.update_one(
            query,
            {
                "$set": values,
                "$setOnInsert": {
                    "created_at": now,
                    "is_premium": bool(getattr(user, "is_premium", False)),
                },
                "$unset": {"blocked_at": ""},
            },
            upsert=True,
        )
        return result.upserted_id is not None, was_reactivated
    except DuplicateKeyError:
        # A concurrent /start may have inserted the unique user_id first.
        await collection.update_one(
            {"$or": [{"user_id": uid}, {"id": uid}]},
            {"$set": values, "$unset": {"blocked_at": ""}},
        )
        return False, was_reactivated


async def mark_user_blocked(user_id: int) -> bool:
    """Mark a user inactive after Telegram confirms they blocked the bot."""
    uid = int(user_id)
    now = datetime.utcnow()
    try:
        from database import db_registry

        db = db_registry.get_user_db()
        if db is None:
            logger.error(
                "[USERS] cannot mark blocked user: user database unavailable"
            )
            return False

        collection = db["users"]
        existing = await collection.find_one(
            {"$or": [{"user_id": uid}, {"id": uid}]},
            {"blocked_bot": 1},
        )
        newly_blocked = not existing or not existing.get("blocked_bot", False)
        query = {"_id": existing["_id"]} if existing else {"user_id": uid}

        try:
            await collection.update_one(
                query,
                {
                    "$set": {
                        "user_id": uid,
                        "blocked_bot": True,
                        "is_active": False,
                        "status": "inactive",
                        "blocked_at": now,
                        "last_blocked_at": now,
                    },
                    "$setOnInsert": {"created_at": now},
                },
                upsert=True,
            )
        except DuplicateKeyError:
            await collection.update_one(
                {"$or": [{"user_id": uid}, {"id": uid}]},
                {
                    "$set": {
                        "blocked_bot": True,
                        "is_active": False,
                        "status": "inactive",
                        "blocked_at": now,
                        "last_blocked_at": now,
                    },
                },
            )

        if newly_blocked:
            try:
                from plugins.log_channel import log_user_blocked
                await log_user_blocked(uid)
            except Exception:
                logger.exception("[USERS] failed to log blocked user")
        return newly_blocked
    except Exception:
        logger.exception(f"[USERS] failed to mark user {uid} inactive")
        return False


__all__ = ["register_user", "mark_user_blocked"]
