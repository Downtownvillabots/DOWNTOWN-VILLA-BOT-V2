# ============================================================
# 🏨 DOWNTOWN VILLA — OTT DATABASE
# ============================================================

from __future__ import annotations
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from plugins.ott.config import DEFAULT_SETTINGS

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

SUB_TTL_DAYS = 60
MOVIE_CACHE_DAYS = 30
SENT_LOG_DAYS = 7
WEEK_TTL_DAYS = 30
BROADCAST_LOG_DAYS = 90


def _db():
    try:
        from database import db_registry
        return db_registry.get_system_db()
    except Exception:
        return None


def _c(name: str):
    db = _db()
    return db[name] if db is not None else None


def weeks_coll():       return _c("ott_weeks")
def movies_coll():      return _c("ott_movies")
def subs_coll():        return _c("ott_subs")
def prefs_coll():       return _c("ott_prefs")
def settings_coll():    return _c("ott_settings")
def sent_coll():        return _c("ott_sent_log")
def pending_coll():     return _c("ott_pending_msgs")
def broadcasts_coll():  return _c("ott_broadcasts")


# ═══════════════════════════════════════════════════════════
# SETTINGS
# ═══════════════════════════════════════════════════════════

async def get_cfg() -> Dict[str, Any]:
    c = settings_coll()
    if c is None:
        return dict(DEFAULT_SETTINGS)
    try:
        d = await c.find_one({"_id": "config"}) or {}
        out = dict(DEFAULT_SETTINGS)
        out.update({k: v for k, v in d.items() if k != "_id"})
        return out
    except Exception:
        return dict(DEFAULT_SETTINGS)


async def save_cfg(**fields) -> bool:
    c = settings_coll()
    if c is None:
        return False
    try:
        fields["updated_at"] = time.time()
        await c.update_one({"_id": "config"}, {"$set": fields}, upsert=True)
        return True
    except Exception:
        return False


# ═══════════════════════════════════════════════════════════
# WEEKS
# ═══════════════════════════════════════════════════════════

def week_key() -> str:
    iso = datetime.now(IST).isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def week_range():
    now = datetime.now(IST)
    mon = (now - timedelta(days=now.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0)
    return mon, mon + timedelta(days=7)


def day_date(i: int) -> datetime:
    mon, _ = week_range()
    return mon + timedelta(days=i)


async def save_week(wk: str, days: List[List[Dict[str, Any]]],
                    posted: bool = False) -> bool:
    c = weeks_coll()
    if c is None:
        return False
    try:
        await c.update_one(
            {"_id": wk},
            {"$set": {
                "week_key": wk, "days": days, "posted": posted,
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


# ═══════════════════════════════════════════════════════════
# MOVIE CACHE
# ═══════════════════════════════════════════════════════════

async def save_movie(movie: Dict[str, Any]) -> None:
    c = movies_coll()
    if c is None:
        return
    try:
        tid = movie.get("tmdb_id")
        if not tid:
            return
        await c.update_one(
            {"tmdb_id": int(tid)},
            {"$set": {**movie, "cached_at": datetime.now(timezone.utc)}},
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


async def cache_count() -> int:
    c = movies_coll()
    if c is None:
        return 0
    try:
        return await c.count_documents({})
    except Exception:
        return 0


async def cache_clear() -> int:
    c = movies_coll()
    if c is None:
        return 0
    try:
        return (await c.delete_many({})).deleted_count
    except Exception:
        return 0


# ═══════════════════════════════════════════════════════════
# SUBSCRIPTIONS
# ═══════════════════════════════════════════════════════════

async def sub_add(user_id, tmdb_id, title, year="", release_date="") -> bool:
    c = subs_coll()
    if c is None:
        return False
    try:
        exp = datetime.now(timezone.utc) + timedelta(days=SUB_TTL_DAYS)
        await c.update_one(
            {"user_id": int(user_id), "tmdb_id": int(tmdb_id)},
            {"$set": {
                "user_id": int(user_id), "tmdb_id": int(tmdb_id),
                "title": title, "year": year, "release_date": release_date,
                "notified": False, "created_at": time.time(),
                "expires_at": exp,
            }},
            upsert=True,
        )
        return True
    except Exception:
        return False


async def sub_exists(user_id, tmdb_id) -> bool:
    c = subs_coll()
    if c is None:
        return False
    try:
        return (await c.find_one(
            {"user_id": int(user_id), "tmdb_id": int(tmdb_id)})) is not None
    except Exception:
        return False


async def sub_remove(user_id, tmdb_id) -> bool:
    c = subs_coll()
    if c is None:
        return False
    try:
        r = await c.delete_one(
            {"user_id": int(user_id), "tmdb_id": int(tmdb_id)})
        return r.deleted_count > 0
    except Exception:
        return False


async def subs_for_movie(tmdb_id, only_pending: bool = False,
                          limit: int = 10000) -> List[Dict[str, Any]]:
    c = subs_coll()
    if c is None:
        return []
    try:
        q: Dict[str, Any] = {"tmdb_id": int(tmdb_id)}
        if only_pending:
            q["notified"] = False
        return await c.find(q).limit(limit).to_list(length=limit)
    except Exception:
        return []


async def count_subs_for_movie(tmdb_id) -> int:
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
                "count": {"$sum": 1},
            }},
            {"$sort": {"count": -1}},
            {"$limit": int(limit)},
        ]
        return await c.aggregate(pipeline).to_list(length=int(limit))
    except Exception:
        return []


async def mark_subs_notified(tmdb_id) -> None:
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


async def cancel_all_subs(tmdb_id) -> int:
    c = subs_coll()
    if c is None:
        return 0
    try:
        r = await c.delete_many(
            {"tmdb_id": int(tmdb_id), "notified": False})
        return r.deleted_count
    except Exception:
        return 0


async def subs_overview(limit: int = 30) -> List[Dict[str, Any]]:
    c = subs_coll()
    if c is None:
        return []
    try:
        pipeline = [
            {"$group": {
                "_id": "$tmdb_id",
                "title": {"$first": "$title"},
                "count": {"$sum": 1},
                "notified": {"$sum": {
                    "$cond": [{"$eq": ["$notified", True]}, 1, 0]}},
            }},
            {"$sort": {"count": -1}},
            {"$limit": int(limit)},
        ]
        return await c.aggregate(pipeline).to_list(length=int(limit))
    except Exception:
        return []


async def pending_subs_total() -> int:
    c = subs_coll()
    if c is None:
        return 0
    try:
        return await c.count_documents({"notified": False})
    except Exception:
        return 0


# ═══════════════════════════════════════════════════════════
# SENT LOG
# ═══════════════════════════════════════════════════════════

async def sent_log(user_id, tmdb_id, mode: str = "notify") -> None:
    c = sent_coll()
    if c is None:
        return
    try:
        await c.insert_one({
            "user_id": int(user_id), "tmdb_id": int(tmdb_id),
            "mode": mode, "sent_at": datetime.now(timezone.utc),
        })
    except Exception:
        pass


async def sent_count_last(days: int = 7) -> int:
    c = sent_coll()
    if c is None:
        return 0
    try:
        since = datetime.now(timezone.utc) - timedelta(days=days)
        return await c.count_documents({"sent_at": {"$gte": since}})
    except Exception:
        return 0


async def sent_clear() -> int:
    c = sent_coll()
    if c is None:
        return 0
    try:
        return (await c.delete_many({})).deleted_count
    except Exception:
        return 0


# ═══════════════════════════════════════════════════════════
# PENDING AUTO-DELETE
# ═══════════════════════════════════════════════════════════

async def pending_add(chat_id, message_id, ttl_seconds: int) -> None:
    c = pending_coll()
    if c is None:
        return
    try:
        await c.insert_one({
            "chat_id": int(chat_id), "message_id": int(message_id),
            "delete_at": datetime.now(timezone.utc)
                + timedelta(seconds=int(ttl_seconds)),
            "created_at": time.time(),
        })
    except Exception:
        pass


async def pending_due(limit: int = 200) -> List[Dict[str, Any]]:
    c = pending_coll()
    if c is None:
        return []
    try:
        cur = c.find({"delete_at": {"$lte": datetime.now(timezone.utc)}}).limit(limit)
        return await cur.to_list(length=limit)
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


async def pending_count() -> int:
    c = pending_coll()
    if c is None:
        return 0
    try:
        return await c.count_documents({})
    except Exception:
        return 0


# ═══════════════════════════════════════════════════════════
# BROADCASTS
# ═══════════════════════════════════════════════════════════

async def broadcast_log(tmdb_id: int, target: str, delivered: int,
                        failed: int, total: int, admin_id: int,
                        channel_msg_id: int = 0) -> str:
    c = broadcasts_coll()
    if c is None:
        return ""
    try:
        r = await c.insert_one({
            "tmdb_id": int(tmdb_id), "target": target,
            "delivered": int(delivered), "failed": int(failed),
            "total": int(total), "admin_id": int(admin_id),
            "channel_msg_id": int(channel_msg_id),
            "cancelled": False,
            "sent_at": datetime.now(timezone.utc),
            "sent_ts": time.time(),
            "expires_at": datetime.now(timezone.utc)
                + timedelta(days=BROADCAST_LOG_DAYS),
        })
        return str(r.inserted_id)
    except Exception:
        return ""


async def broadcast_list(limit: int = 30) -> List[Dict[str, Any]]:
    c = broadcasts_coll()
    if c is None:
        return []
    try:
        return await c.find({}).sort("sent_ts", -1).limit(
            int(limit)).to_list(length=int(limit))
    except Exception:
        return []


async def broadcast_count_for_movie(tmdb_id) -> int:
    c = broadcasts_coll()
    if c is None:
        return 0
    try:
        return await c.count_documents({"tmdb_id": int(tmdb_id)})
    except Exception:
        return 0


async def broadcast_total_delivered(days: int = 30) -> int:
    c = broadcasts_coll()
    if c is None:
        return 0
    try:
        since = time.time() - days * 86400
        pipeline = [
            {"$match": {"sent_ts": {"$gte": since}}},
            {"$group": {"_id": None, "total": {"$sum": "$delivered"}}},
        ]
        r = await c.aggregate(pipeline).to_list(length=1)
        return r[0]["total"] if r else 0
    except Exception:
        return 0


async def broadcast_recent_count(days: int = 7) -> int:
    c = broadcasts_coll()
    if c is None:
        return 0
    try:
        return await c.count_documents(
            {"sent_ts": {"$gte": time.time() - days * 86400}})
    except Exception:
        return 0


async def broadcast_mark_cancelled(tmdb_id) -> int:
    c = broadcasts_coll()
    if c is None:
        return 0
    try:
        r = await c.update_many(
            {"tmdb_id": int(tmdb_id)},
            {"$set": {"cancelled": True, "cancelled_at": time.time()}},
        )
        return r.modified_count
    except Exception:
        return 0


async def broadcast_get_latest(tmdb_id) -> Optional[Dict[str, Any]]:
    c = broadcasts_coll()
    if c is None:
        return None
    try:
        return await c.find_one(
            {"tmdb_id": int(tmdb_id)}, sort=[("sent_ts", -1)])
    except Exception:
        return None
# ═══════════════════════════════════════════════════════════
# MOVIE STATS + END EVENT
# ═══════════════════════════════════════════════════════════

async def movie_stats(tmdb_id: int) -> Dict[str, Any]:
    """Live per-movie stats: subs, notified, broadcasts."""
    try:
        total = await subs_coll().count_documents({"tmdb_id": int(tmdb_id)})
        pending = await subs_coll().count_documents(
            {"tmdb_id": int(tmdb_id), "notified": False})
        sent = await sent_coll().count_documents(
            {"tmdb_id": int(tmdb_id), "mode": "now_available"})
    except Exception:
        total = pending = sent = 0

    bc = await broadcast_get_latest(tmdb_id)
    return {
        "total_subs": total,
        "pending": pending,
        "notified": total - pending,
        "files_sent": sent,
        "broadcast": bc,
        "ended": bool(bc and bc.get("cancelled")),
    }


async def end_movie(tmdb_id: int) -> Dict[str, int]:
    """
    Fully end a movie event:
      • delete every pending sub (tokens)
      • mark broadcasts cancelled
    Returns counts.
    """
    try:
        deleted = await cancel_all_subs(tmdb_id)
    except Exception:
        deleted = 0
    try:
        cancelled = await broadcast_mark_cancelled(tmdb_id)
    except Exception:
        cancelled = 0
    return {"deleted": deleted, "broadcasts_cancelled": cancelled}


async def is_movie_ended(tmdb_id: int) -> bool:
    bc = await broadcast_get_latest(tmdb_id)
    return bool(bc and bc.get("cancelled"))

# ═══════════════════════════════════════════════════════════
# INDEXES
# ═══════════════════════════════════════════════════════════

async def ensure_indexes() -> bool:
    try:
        if (s := subs_coll()) is not None:
            await s.create_index("expires_at", expireAfterSeconds=0)
            await s.create_index([("tmdb_id", 1), ("notified", 1)])
        if (p := pending_coll()) is not None:
            await p.create_index("delete_at", expireAfterSeconds=0)
        if (w := weeks_coll()) is not None:
            await w.create_index("expires_at", expireAfterSeconds=0)
        if (m := movies_coll()) is not None:
            await m.create_index(
                "cached_at", expireAfterSeconds=MOVIE_CACHE_DAYS * 86400)
        if (sl := sent_coll()) is not None:
            await sl.create_index(
                "sent_at", expireAfterSeconds=SENT_LOG_DAYS * 86400)
        if (b := broadcasts_coll()) is not None:
            await b.create_index("expires_at", expireAfterSeconds=0)
            await b.create_index("tmdb_id")
        return True
    except Exception as e:
        logger.warning(f"[OTT-DB] index: {e}")
        return False
