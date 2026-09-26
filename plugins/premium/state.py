# ============================================================
# 🏨 DOWNTOWN VILLA — PREMIUM STATE LAYER
# ============================================================
#
# User CRUD + watch session persistence.
#
# Collections (USER DB):
#   premium_users     — one doc per premium member
#   watch_sessions    — one doc per (user, series)
#   watch_ratings     — one doc per rating
#   premium_settings  — singleton
#
# ============================================================

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ============================================================
# CONFIG
# ============================================================

GRACE_PERIOD_DAYS = 30
INACTIVITY_DAYS = 180
DEFAULT_PLAN_MONTHS = 1

PLAN_OPTIONS = [
    ("1 MONTH",   1),
    ("3 MONTHS",  3),
    ("5 MONTHS",  5),
    ("6 MONTHS",  6),
    ("12 MONTHS", 12),
]


def _user_db():
    try:
        from database import db_registry
        return db_registry.get_user_db()
    except Exception:
        return None


def _users_coll():
    db = _user_db()
    return db["premium_users"] if db is not None else None


def _sessions_coll():
    db = _user_db()
    return db["watch_sessions"] if db is not None else None


def _ratings_coll():
    db = _user_db()
    return db["watch_ratings"] if db is not None else None


def _settings_coll():
    db = _user_db()
    return db["premium_settings"] if db is not None else None


# ============================================================
# USER CRUD
# ============================================================

async def add_premium_user(
    user_id: int,
    username: str = "",
    months: int = 1,
    added_by: int = 0,
    notes: str = "",
) -> bool:
    """Add or extend premium access. Stacks on existing."""
    c = _users_coll()
    if c is None:
        return False
    try:
        now = time.time()
        months = max(1, int(months))
        expires_at = now + (months * 30 * 86400)

        existing = await c.find_one({"user_id": int(user_id)})
        if existing and existing.get("expires_at", 0) > now:
            expires_at = existing["expires_at"] + (months * 30 * 86400)

        await c.update_one(
            {"user_id": int(user_id)},
            {
                "$set": {
                    "user_id": int(user_id),
                    "username": (username or "").lstrip("@"),
                    "plan_months": int(months),
                    "added_at": now,
                    "added_by": int(added_by),
                    "expires_at": expires_at,
                    "notes": notes or "",
                    "status": "active",
                    "reminders_sent": [],
                },
                
            },
            upsert=True,
        )
        logger.info(
            f"[PREM] user {user_id} +{months}mo → "
            f"expires {datetime.fromtimestamp(expires_at)}"
        )
        return True
    except Exception as e:
        logger.exception(f"[PREM] add: {e}")
        return False


async def get_user(user_id: int) -> Optional[Dict[str, Any]]:
    c = _users_coll()
    if c is None:
        return None
    try:
        return await c.find_one({"user_id": int(user_id)})
    except Exception:
        return None


async def is_premium(user_id: int) -> bool:
    doc = await get_user(user_id)
    if not doc:
        return False
    if doc.get("status") != "active":
        return False
    return doc.get("expires_at", 0) > time.time()


async def is_premium_or_grace(user_id: int) -> bool:
    doc = await get_user(user_id)
    if not doc:
        return False
    if doc.get("status") == "active":
        return True
    expires = doc.get("expires_at", 0)
    if not expires:
        return False
    grace_end = expires + (GRACE_PERIOD_DAYS * 86400)
    return grace_end > time.time()


async def remove_user(user_id: int) -> bool:
    c = _users_coll()
    if c is None:
        return False
    try:
        r = await c.delete_one({"user_id": int(user_id)})
        return r.deleted_count > 0
    except Exception:
        return False


async def list_users(limit: int = 500) -> List[Dict[str, Any]]:
    c = _users_coll()
    if c is None:
        return []
    try:
        cursor = c.find({}).sort("expires_at", 1).limit(int(limit))
        return await cursor.to_list(length=int(limit))
    except Exception:
        return []


async def count_users() -> Dict[str, int]:
    empty = {
        "active": 0, "expiring_10d": 0,
        "expiring_5d": 0, "expiring_1d": 0, "expired": 0,
    }
    c = _users_coll()
    if c is None:
        return empty
    try:
        now = time.time()
        d10 = now + 10 * 86400
        d5 = now + 5 * 86400
        d1 = now + 1 * 86400

        active = await c.count_documents(
            {"status": "active", "expires_at": {"$gt": now}}
        )
        exp10 = await c.count_documents(
            {"status": "active",
             "expires_at": {"$gt": now, "$lte": d10}}
        )
        exp5 = await c.count_documents(
            {"status": "active",
             "expires_at": {"$gt": now, "$lte": d5}}
        )
        exp1 = await c.count_documents(
            {"status": "active",
             "expires_at": {"$gt": now, "$lte": d1}}
        )
        expired = await c.count_documents(
            {"expires_at": {"$lte": now}}
        )

        return {
            "active": active, "expiring_10d": exp10,
            "expiring_5d": exp5, "expiring_1d": exp1,
            "expired": expired,
        }
    except Exception as e:
        logger.warning(f"[PREM] count: {e}")
        return empty


async def find_by_username(username: str) -> Optional[Dict[str, Any]]:
    c = _users_coll()
    if c is None:
        return None
    try:
        uname = (username or "").lstrip("@").lower()
        return await c.find_one(
            {"username": {"$regex": f"^{re.escape(uname)}$",
                          "options": "i"}}
        )
    except Exception:
        return None


async def mark_reminder_sent(user_id: int, reminder: str) -> bool:
    c = _users_coll()
    if c is None:
        return False
    try:
        await c.update_one(
            {"user_id": int(user_id)},
            {"$addToSet": {"reminders_sent": reminder}},
        )
        return True
    except Exception:
        return False


async def was_reminder_sent(user_id: int, reminder: str) -> bool:
    doc = await get_user(user_id)
    if not doc:
        return False
    return reminder in (doc.get("reminders_sent") or [])


# ============================================================
# SLUG
# ============================================================

def make_slug(title: str) -> str:
    if not title:
        return ""
    return re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")


# ============================================================
# MERGE HELPERS (NEW — preserve progress on re-open)
# ============================================================

def _merge_seasons(
    old: Dict[str, Any],
    new: Dict[str, Any],
) -> Dict[str, Any]:
    """
    Merge old + new season dicts.
    • Preserves `watched` and `sent` arrays from OLD
    • Updates `total_eps` to the max of old/new
    • Adds any NEW seasons that didn't exist before
    """
    out: Dict[str, Any] = {}
    old = old or {}
    new = new or {}

    # Start with old seasons
    for sn_str, sdata in old.items():
        if not isinstance(sdata, dict):
            continue
        out[sn_str] = {
            "total_eps": int(sdata.get("total_eps", 0) or 0),
            "watched": list(sdata.get("watched") or []),
            "sent": list(sdata.get("sent") or []),
            "current_ep": int(sdata.get("current_ep", 1) or 1),
        }

    # Overlay new seasons (adding missing ones, updating total_eps)
    for sn_str, sdata in new.items():
        if not isinstance(sdata, dict):
            continue
        new_total = int(sdata.get("total_eps", 0) or 0)
        if sn_str in out:
            # Preserve watched/sent — only refresh total_eps upward
            out[sn_str]["total_eps"] = max(
                out[sn_str]["total_eps"], new_total
            )
        else:
            out[sn_str] = {
                "total_eps": new_total,
                "watched": list(sdata.get("watched") or []),
                "sent": list(sdata.get("sent") or []),
                "current_ep": int(sdata.get("current_ep", 1) or 1),
            }
    return out


def _merge_hits(
    old: List[Dict[str, Any]],
    new: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """
    Union hits by file_id.
    Old hits first (so their position is preserved),
    then any new file_ids appended.
    """
    seen = set()
    out: List[Dict[str, Any]] = []
    for h in list(old or []) + list(new or []):
        if not isinstance(h, dict):
            continue
        fid = h.get("file_id")
        if not fid or fid in seen:
            continue
        seen.add(fid)
        out.append(h)
    return out


# ============================================================
# SESSION CRUD
# ============================================================

async def create_session(
    user_id: int,
    title: str,
    tmdb_id: Optional[int] = None,
    poster: Optional[str] = None,
    language: str = "",
    tmdb_seasons: Optional[List[Dict[str, Any]]] = None,
    hits: Optional[List[Dict[str, Any]]] = None,
) -> bool:
    """
    Create or update a watch session.

    ⚠️ IMPORTANT: when a session already exists, this MERGES data.
    Watch progress (`watched`/`sent`) is NEVER wiped.
    """
    c = _sessions_coll()
    if c is None:
        return False

    try:
        slug = make_slug(title)
        if not slug:
            return False

        now = time.time()
        uid = int(user_id)

        # Build fresh seasons from TMDB data
        fresh_seasons: Dict[str, Dict[str, Any]] = {}
        for s in (tmdb_seasons or []):
            sn = s.get("season")
            if sn is None:
                continue
            fresh_seasons[str(sn)] = {
                "total_eps": int(s.get("episodes", 0) or 0),
                "watched": [],
                "sent": [],
                "current_ep": 1,
            }
        if not fresh_seasons:
            fresh_seasons["1"] = {
                "total_eps": 0, "watched": [],
                "sent": [], "current_ep": 1,
            }

        # Clean hits (JSON-safe)
        clean_hits = _clean_hits(hits or [])

        # ── Check if session already exists ──
        existing = await c.find_one(
            {"user_id": uid, "series_slug": slug}
        )

        if existing:
            # ── MERGE MODE — preserve progress ──
            merged_seasons = _merge_seasons(
                existing.get("seasons") or {},
                fresh_seasons,
            )
            merged_hits = _merge_hits(
                existing.get("hits") or [],
                clean_hits,
            )

            patch = {
                "series_title": str(title)[:200],
                "tmdb_id": int(tmdb_id) if tmdb_id else existing.get("tmdb_id"),
                "poster": poster or existing.get("poster"),
                "language": language or existing.get("language", ""),
                "seasons": merged_seasons,
                "hits": merged_hits,
                "last_activity_at": now,
            }

            # Never un-complete a completed series
            if existing.get("status") == "completed":
                patch.pop("status", None)
                patch.pop("completed_at", None)

            await c.update_one(
                {"_id": existing["_id"]},
                {"$set": patch},
            )
            logger.info(
                f"[PREM] session MERGED u={uid} s={slug} "
                f"(preserved progress)"
            )
            return True

        # ── FRESH INSERT ──
        await c.insert_one({
            "user_id": uid,
            "series_slug": slug,
            "series_title": str(title)[:200],
            "tmdb_id": int(tmdb_id) if tmdb_id else None,
            "poster": poster,
            "language": language or "",
            "seasons": fresh_seasons,
            "hits": clean_hits,
            "started_at": now,
            "last_activity_at": now,
            "status": "watching",
            "completed_at": None,
            "poster_chat_id": uid,
            "current_season": 1,
            "current_episode": 1,
            "rated": False,
            "poster_msg_id": None,
            "current_file_msg_id": None,
        })
        logger.info(f"[PREM] session created u={uid} s={slug}")
        return True

    except Exception as e:
        logger.exception(f"[PREM] create session: {e}")
        return False


def _clean_hits(hits: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Strip non-serializable fields."""
    clean = []
    for h in (hits or []):
        try:
            clean.append({
                "file_id": h.get("file_id") or "",
                "file_unique_id": h.get("file_unique_id"),
                "file_name": h.get("file_name") or "",
                "file_size": h.get("file_size") or 0,
                "season": h.get("season"),
                "episode": h.get("episode"),
                "quality": h.get("quality") or "UNKNOWN",
                "languages": list(
                    h.get("languages") or h.get("audio_languages") or []
                ),
                "title": h.get("title") or "",
                "series_title": h.get("series_title") or "",
            })
        except Exception:
            continue
    return clean


async def get_session(user_id: int, slug: str) -> Optional[Dict[str, Any]]:
    c = _sessions_coll()
    if c is None:
        return None
    try:
        return await c.find_one({
            "user_id": int(user_id), "series_slug": slug,
        })
    except Exception:
        return None


async def list_user_sessions(
    user_id: int,
    status: Optional[str] = "watching",
) -> List[Dict[str, Any]]:
    c = _sessions_coll()
    if c is None:
        return []
    try:
        query: Dict[str, Any] = {"user_id": int(user_id)}
        if status:
            query["status"] = status
        cursor = c.find(query).sort("last_activity_at", -1).limit(50)
        return await cursor.to_list(length=50)
    except Exception:
        return []


async def update_session(user_id: int, slug: str, **patch) -> bool:
    c = _sessions_coll()
    if c is None:
        return False
    try:
        patch["last_activity_at"] = time.time()
        r = await c.update_one(
            {"user_id": int(user_id), "series_slug": slug},
            {"$set": patch},
        )
        return r.matched_count > 0
    except Exception:
        return False


async def mark_watched(
    user_id: int,
    slug: str,
    season: int,
    episode: int,
) -> bool:
    c = _sessions_coll()
    if c is None:
        return False
    try:
        key = f"seasons.{int(season)}.watched"
        await c.update_one(
            {"user_id": int(user_id), "series_slug": slug},
            {
                "$addToSet": {key: int(episode)},
                "$set": {"last_activity_at": time.time()},
            },
        )
        return True
    except Exception:
        return False


async def mark_sent(
    user_id: int,
    slug: str,
    season: int,
    episode: int,
) -> bool:
    c = _sessions_coll()
    if c is None:
        return False
    try:
        key = f"seasons.{int(season)}.sent"
        await c.update_one(
            {"user_id": int(user_id), "series_slug": slug},
            {
                "$addToSet": {key: int(episode)},
                "$set": {"last_activity_at": time.time()},
            },
        )
        return True
    except Exception:
        return False


async def set_current_position(
    user_id: int,
    slug: str,
    season: int,
    episode: int,
) -> bool:
    return await update_session(
        user_id, slug,
        current_season=int(season),
        current_episode=int(episode),
    )


async def update_poster_msg(user_id: int, slug: str, msg_id: int) -> bool:
    return await update_session(user_id, slug, poster_msg_id=int(msg_id))


async def update_current_file_msg(
    user_id: int, slug: str, msg_id: int,
) -> bool:
    return await update_session(
        user_id, slug, current_file_msg_id=int(msg_id)
    )


async def mark_completed(user_id: int, slug: str) -> bool:
    return await update_session(
        user_id, slug,
        status="completed",
        completed_at=time.time(),
    )


async def mark_rated(user_id: int, slug: str) -> bool:
    return await update_session(user_id, slug, rated=True)


async def delete_session(user_id: int, slug: str) -> bool:
    c = _sessions_coll()
    if c is None:
        return False
    try:
        r = await c.delete_one({
            "user_id": int(user_id), "series_slug": slug,
        })
        return r.deleted_count > 0
    except Exception:
        return False


async def count_sessions() -> int:
    c = _sessions_coll()
    if c is None:
        return 0
    try:
        return await c.count_documents({"status": "watching"})
    except Exception:
        return 0


# ============================================================
# PROGRESS
# ============================================================

def compute_progress(session: Dict[str, Any]) -> Dict[str, Any]:
    seasons_raw = session.get("seasons") or {}
    out: Dict[int, Dict[str, Any]] = {}
    total_watched = 0
    total_eps = 0

    for sn_str, s in seasons_raw.items():
        try:
            sn = int(sn_str)
        except ValueError:
            continue
        watched = set(s.get("watched") or [])
        sent = set(s.get("sent") or [])
        total = int(s.get("total_eps", 0) or 0)

        out[sn] = {
            "watched": sorted(watched),
            "sent": sorted(sent),
            "count": len(watched),
            "sent_count": len(sent),
            "total": total,
        }
        total_watched += len(watched)
        total_eps += total

    pct = (total_watched / total_eps * 100) if total_eps else 0.0
    return {
        "seasons": out,
        "total_watched": total_watched,
        "total_eps": total_eps,
        "pct": round(pct, 1),
    }


def find_next_episode(session: Dict[str, Any]) -> Optional[tuple]:
    seasons_raw = session.get("seasons") or {}
    ordered = sorted(int(k) for k in seasons_raw.keys() if k.isdigit())

    for sn in ordered:
        s = seasons_raw.get(str(sn)) or {}
        total = int(s.get("total_eps", 0) or 0)
        if total == 0:
            continue
        watched = set(s.get("watched") or [])
        for ep in range(1, total + 1):
            if ep not in watched:
                return (sn, ep)
    return None


def is_season_complete(session: Dict[str, Any], season: int) -> bool:
    s = (session.get("seasons") or {}).get(str(season)) or {}
    total = int(s.get("total_eps", 0) or 0)
    if total == 0:
        return False
    watched = set(s.get("watched") or [])
    return len(watched) >= total


def is_series_complete(session: Dict[str, Any]) -> bool:
    p = compute_progress(session)
    if p["total_eps"] == 0:
        return False
    return p["total_watched"] >= p["total_eps"]


# ============================================================
# RATINGS
# ============================================================

async def save_rating(user_id: int, slug: str, stars: int) -> bool:
    c = _ratings_coll()
    if c is None:
        return False
    try:
        await c.update_one(
            {"user_id": int(user_id), "series_slug": slug},
            {"$set": {
                "user_id": int(user_id),
                "series_slug": slug,
                "rating": int(stars),
                "rated_at": time.time(),
            }},
            upsert=True,
        )
        return True
    except Exception:
        return False


async def get_rating(user_id: int, slug: str) -> Optional[int]:
    c = _ratings_coll()
    if c is None:
        return None
    try:
        d = await c.find_one({
            "user_id": int(user_id), "series_slug": slug,
        })
        return int(d["rating"]) if d else None
    except Exception:
        return None


# ============================================================
# SETTINGS
# ============================================================

async def get_setting(key: str, default: Any = None) -> Any:
    c = _settings_coll()
    if c is None:
        return default
    try:
        doc = await c.find_one({"_id": "settings"}) or {}
        return doc.get(key, default)
    except Exception:
        return default


async def set_setting(key: str, value: Any) -> bool:
    c = _settings_coll()
    if c is None:
        return False
    try:
        await c.update_one(
            {"_id": "settings"},
            {"$set": {key: value, "updated_at": time.time()}},
            upsert=True,
        )
        return True
    except Exception:
        return False


async def get_contact_admin() -> str:
    return await get_setting("contact_admin", "") or ""


# ============================================================
# CLEANUP
# ============================================================

async def cleanup_inactive() -> int:
    """Delete sessions with no activity for INACTIVITY_DAYS."""
    c = _sessions_coll()
    if c is None:
        return 0
    try:
        cutoff = time.time() - (INACTIVITY_DAYS * 86400)
        r = await c.delete_many({
            "status": "watching",
            "last_activity_at": {"$lt": cutoff},
        })
        if r.deleted_count:
            logger.info(f"[PREM] cleaned {r.deleted_count} inactive")
        return r.deleted_count
    except Exception:
        return 0


async def cleanup_expired() -> int:
    """Delete sessions for users whose grace period expired."""
    c = _sessions_coll()
    u = _users_coll()
    if c is None or u is None:
        return 0
    try:
        cutoff = time.time() - (GRACE_PERIOD_DAYS * 86400)
        expired_uids: List[int] = []
        async for doc in u.find({"expires_at": {"$lt": cutoff}}):
            uid = doc.get("user_id")
            if uid:
                expired_uids.append(int(uid))

        if not expired_uids:
            return 0

        r = await c.delete_many({"user_id": {"$in": expired_uids}})
        if r.deleted_count:
            logger.info(f"[PREM] cleaned {r.deleted_count} expired")
        return r.deleted_count
    except Exception:
        return 0


# ============================================================
# PUBLIC
# ============================================================

__all__ = [
    # Config
    "GRACE_PERIOD_DAYS", "INACTIVITY_DAYS", "PLAN_OPTIONS",
    # Users
    "add_premium_user", "get_user", "is_premium", "is_premium_or_grace",
    "remove_user", "list_users", "count_users",
    "find_by_username", "mark_reminder_sent", "was_reminder_sent",
    # Sessions
    "make_slug", "create_session", "get_session", "list_user_sessions",
    "update_session", "mark_watched", "mark_sent", "set_current_position",
    "update_poster_msg", "update_current_file_msg",
    "mark_completed", "mark_rated", "delete_session", "count_sessions",
    # Progress
    "compute_progress", "find_next_episode",
    "is_season_complete", "is_series_complete",
    # Ratings
    "save_rating", "get_rating",
    # Settings
    "get_setting", "set_setting", "get_contact_admin",
    # Cleanup
    "cleanup_inactive", "cleanup_expired",
]
