# ============================================================
# 🏨 DOWNTOWN VILLA — OTT STATE
# ============================================================
#
# Collections (SYSTEM DB):
#   ott_weeks         — one doc per week (days + movies)
#   ott_movies        — cached metadata per movie
#   ott_subs          — user subscriptions
#   ott_prefs         — user preferences (languages, genres, watchlist)
#   ott_settings      — singleton config
#   ott_sent_log      — sent notifications
#   ott_pending_msgs  — messages to auto-delete
#
# ============================================================

from __future__ import annotations

import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

# ── TTLs ──
SUB_TTL_DAYS = 60
MOVIE_CACHE_DAYS = 30
SENT_LOG_DAYS = 7
WEEK_TTL_DAYS = 30


def _db():
    try:
        from database import db_registry
        return db_registry.get_system_db()
    except Exception:
        return None


def _c(name: str):
    db = _db()
    return db[name] if db is not None else None


def weeks_coll():    return _c("ott_weeks")
def movies_coll():   return _c("ott_movies")
def subs_coll():     return _c("ott_subs")
def prefs_coll():    return _c("ott_prefs")
def settings_coll(): return _c("ott_settings")
def sent_coll():     return _c("ott_sent_log")
def pending_coll():  return _c("ott_pending_msgs")


# ============================================================
# SETTINGS
# ============================================================

DEFAULT_CFG = {
    "region": "IN",
    "release_time": "12:00",
    "file_ttl_hours": 5,
    "notify_ttl_hours": 12,
    "share_button": True,
    "notify_button": True,
    "weekly_enabled": True,
    "hype_enabled": True,
    "trending_enabled": True,
    "spotlight_enabled": True,
}


async def get_cfg() -> Dict[str, Any]:
    c = settings_coll()
    if c is None:
        return dict(DEFAULT_CFG)
    try:
        d = await c.find_one({"_id": "config"}) or {}
        out = dict(DEFAULT_CFG)
        out.update({k: v for k, v in d.items() if k != "_id"})
        return out
    except Exception:
        return dict(DEFAULT_CFG)


async def save_cfg(**fields) -> bool:
    c = settings_coll()
    if c is None:
        return False
    try:
        fields["updated_at"] = time.time()
        await c.update_one(
            {"_id": "config"},
            {"$set": fields},
            upsert=True,
        )
        return True
    except Exception:
        return False


# ============================================================
# WEEKS
# ============================================================

def week_key() -> str:
    now = datetime.now(IST)
    iso = now.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def week_range() -> tuple:
    now = datetime.now(IST)
    monday = now - timedelta(days=now.weekday())
    monday = monday.replace(hour=0, minute=0, second=0, microsecond=0)
    return monday, monday + timedelta(days=7)


def day_date(day_idx: int) -> datetime:
    monday, _ = week_range()
    return monday + timedelta(days=day_idx)


async def save_week(
    wk: str,
    days: List[List[Dict[str, Any]]],
    posted: bool = False,
) -> bool:
    c = weeks_coll()
    if c is None:
        return False
    try:
        await c.update_one(
            {"_id": wk},
            {"$set": {
                "week_key": wk,
                "days": days,
                "posted": posted,
                "updated_at": time.time(),
                "expires_at": datetime.now(timezone.utc)
                    + timedelta(days=WEEK_TTL_DAYS),
            }},
            upsert=True,
        )
        return True
    except Exception:
        return False


async def get_week(wk: str) -> Optional[Dict[str, Any]]:
    c = weeks_coll()
    if c is None:
        return None
    try:
        return await c.find_one({"_id": wk})
    except Exception:
        return None


# ============================================================
# MOVIE CACHE
# ============================================================

async def save_movie(movie: Dict[str, Any]) -> None:
    c = movies_coll()
    if c is None:
        return
    try:
        tmdb_id = movie.get("tmdb_id")
        if not tmdb_id:
            return
        await c.update_one(
            {"tmdb_id": int(tmdb_id)},
            {"$set": {
                **movie,
                "cached_at": datetime.now(timezone.utc),
            }},
            upsert=True,
        )
    except Exception:
        pass


async def get_movie(tmdb_id: int) -> Optional[Dict[str, Any]]:
    c = movies_coll()
    if c is None:
        return None
    try:
        return await c.find_one({"tmdb_id": int(tmdb_id)})
    except Exception:
        return None


# ============================================================
# SUBSCRIPTIONS
# ============================================================

async def sub_add(
    user_id: int,
    tmdb_id: int,
    title: str,
    year: str = "",
    release_date: str = "",
) -> bool:
    c = subs_coll()
    if c is None:
        return False
    try:
        expires = datetime.now(timezone.utc) + timedelta(days=SUB_TTL_DAYS)
        await c.update_one(
            {"user_id": int(user_id), "tmdb_id": int(tmdb_id)},
            {"$set": {
                "user_id": int(user_id),
                "tmdb_id": int(tmdb_id),
                "title": title,
                "year": year,
                "release_date": release_date,
                "notified": False,
                "created_at": time.time(),
                "expires_at": expires,
            }},
            upsert=True,
        )
        return True
    except Exception:
        return False


async def sub_remove(user_id: int, tmdb_id: int) -> bool:
    c = subs_coll()
    if c is None:
        return False
    try:
        r = await c.delete_one({
            "user_id": int(user_id), "tmdb_id": int(tmdb_id),
        })
        return r.deleted_count > 0
    except Exception:
        return False


async def sub_exists(user_id: int, tmdb_id: int) -> bool:
    c = subs_coll()
    if c is None:
        return False
    try:
        d = await c.find_one({
            "user_id": int(user_id), "tmdb_id": int(tmdb_id),
        })
        return d is not None
    except Exception:
        return False


async def subs_for_user(user_id: int, limit: int = 30) -> List[Dict[str, Any]]:
    c = subs_coll()
    if c is None:
        return []
    try:
        cursor = c.find({"user_id": int(user_id)}).sort(
            "created_at", -1
        ).limit(limit)
        return await cursor.to_list(length=limit)
    except Exception:
        return []


async def count_subs_for_movie(tmdb_id: int) -> int:
    c = subs_coll()
    if c is None:
        return 0
    try:
        return await c.count_documents({"tmdb_id": int(tmdb_id)})
    except Exception:
        return 0


async def pending_movies_to_notify(limit: int = 50) -> List[Dict[str, Any]]:
    c = subs_coll()
    if c is None:
        return []
    try:
        pipeline = [
            {"$match": {"notified": False}},
            {"$group": {
                "_id": "$tmdb_id",
                "title": {"$first": "$title"},
                "year": {"$first": "$year"},
                "release_date": {"$first": "$release_date"},
                "count": {"$sum": 1},
            }},
            {"$limit": int(limit)},
        ]
        return await c.aggregate(pipeline).to_list(length=int(limit))
    except Exception:
        return []


async def subs_for_movie(tmdb_id: int, limit: int = 10000) -> List[Dict[str, Any]]:
    c = subs_coll()
    if c is None:
        return []
    try:
        cursor = c.find({"tmdb_id": int(tmdb_id), "notified": False}).limit(limit)
        return await cursor.to_list(length=limit)
    except Exception:
        return []


async def mark_subs_notified(tmdb_id: int) -> None:
    c = subs_coll()
    if c is None:
        return
    try:
        await c.update_many(
            {"tmdb_id": int(tmdb_id)},
            {"$set": {"notified": True, "notified_at": time.time()}},
        )
    except Exception:
        pass


# ============================================================
# USER PREFERENCES + WATCHLIST
# ============================================================

DEFAULT_PREFS = {
    "languages": [],
    "genres": [],
    "region": "",
    "notify_all": False,
}


async def get_prefs(user_id: int) -> Dict[str, Any]:
    c = prefs_coll()
    if c is None:
        return dict(DEFAULT_PREFS)
    try:
        d = await c.find_one({"user_id": int(user_id)}) or {}
        out = dict(DEFAULT_PREFS)
        out.update({k: v for k, v in d.items()
                    if k not in ("_id", "user_id")})
        return out
    except Exception:
        return dict(DEFAULT_PREFS)


async def save_prefs(user_id: int, **fields) -> bool:
    c = prefs_coll()
    if c is None:
        return False
    try:
        fields["updated_at"] = time.time()
        await c.update_one(
            {"user_id": int(user_id)},
            {"$set": fields},
            upsert=True,
        )
        return True
    except Exception:
        return False


# ── Watchlist ──
async def watchlist_add(user_id: int, tmdb_id: int, title: str) -> bool:
    c = prefs_coll()
    if c is None:
        return False
    try:
        await c.update_one(
            {"user_id": int(user_id)},
            {"$addToSet": {
                "watchlist": {
                    "tmdb_id": int(tmdb_id),
                    "title": title,
                    "added_at": time.time(),
                }
            }},
            upsert=True,
        )
        return True
    except Exception:
        return False


async def watchlist_remove(user_id: int, tmdb_id: int) -> bool:
    c = prefs_coll()
    if c is None:
        return False
    try:
        await c.update_one(
            {"user_id": int(user_id)},
            {"$pull": {"watchlist": {"tmdb_id": int(tmdb_id)}}},
        )
        return True
    except Exception:
        return False


async def watchlist_get(user_id: int) -> List[Dict[str, Any]]:
    c = prefs_coll()
    if c is None:
        return []
    try:
        d = await c.find_one({"user_id": int(user_id)}) or {}
        return list(d.get("watchlist") or [])
    except Exception:
        return []


# ============================================================
# SENT LOG
# ============================================================

async def sent_log(user_id: int, tmdb_id: int, mode: str = "notify") -> None:
    c = sent_coll()
    if c is None:
        return
    try:
        await c.insert_one({
            "user_id": int(user_id),
            "tmdb_id": int(tmdb_id),
            "mode": mode,
            "sent_at": datetime.now(timezone.utc),
        })
    except Exception:
        pass


# ============================================================
# PENDING AUTO-DELETE
# ============================================================

async def pending_add(
    chat_id: int,
    message_id: int,
    ttl_seconds: int,
) -> None:
    c = pending_coll()
    if c is None:
        return
    try:
        await c.insert_one({
            "chat_id": int(chat_id),
            "message_id": int(message_id),
            "delete_at": datetime.now(timezone.utc)
                + timedelta(seconds=ttl_seconds),
            "created_at": time.time(),
        })
    except Exception:
        pass


async def pending_due(limit: int = 200) -> List[Dict[str, Any]]:
    c = pending_coll()
    if c is None:
        return []
    try:
        cursor = c.find({
            "delete_at": {"$lte": datetime.now(timezone.utc)}
        }).limit(limit)
        return await cursor.to_list(length=limit)
    except Exception:
        return []


async def pending_remove(doc_id) -> None:
    c = pending_coll()
    if c is None:
        return
    try:
        await c.delete_one({"_id": doc_id})
    except Exception:
        pass


# ============================================================
# INDEXES
# ============================================================

async def ensure_indexes() -> bool:
    try:
        subs = subs_coll()
        if subs is not None:
            await subs.create_index("expires_at", expireAfterSeconds=0)
            await subs.create_index([("tmdb_id", 1), ("notified", 1)])

        pend = pending_coll()
        if pend is not None:
            await pend.create_index("delete_at", expireAfterSeconds=0)

        weeks = weeks_coll()
        if weeks is not None:
            await weeks.create_index("expires_at", expireAfterSeconds=0)

        movies = movies_coll()
        if movies is not None:
            await movies.create_index(
                "cached_at",
                expireAfterSeconds=MOVIE_CACHE_DAYS * 86400,
            )

        sent = sent_coll()
        if sent is not None:
            await sent.create_index(
                "sent_at",
                expireAfterSeconds=SENT_LOG_DAYS * 86400,
            )

        prefs = prefs_coll()
        if prefs is not None:
            await prefs.create_index("user_id", unique=True)

        return True
    except Exception as e:
        logger.warning(f"[OTT] index: {e}")
        return False


__all__ = [
    "IST",
    "get_cfg", "save_cfg", "DEFAULT_CFG",
    "week_key", "week_range", "day_date",
    "save_week", "get_week",
    "save_movie", "get_movie",
    "sub_add", "sub_remove", "sub_exists",
    "subs_for_user", "count_subs_for_movie",
    "pending_movies_to_notify", "subs_for_movie", "mark_subs_notified",
    "get_prefs", "save_prefs", "DEFAULT_PREFS",
    "watchlist_add", "watchlist_remove", "watchlist_get",
    "sent_log",
    "pending_add", "pending_due", "pending_remove",
    "ensure_indexes",
]
