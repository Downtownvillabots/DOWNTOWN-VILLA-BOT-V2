# ============================================================
# 🏨 DOWNTOWN VILLA — GROUPS SHARED DEEP LINK
# ============================================================
#
# DB-backed tokens for group → PM delivery.
#
# Two kinds:
#
#   file_{token}     → single file delivery
#     • User taps a file button in a group
#     • Callback:  sr:file:{sid}:{idx}  → creates a file token
#     • OR deep-link button (preferred):
#       https://t.me/{bot}?start=file_{token}
#     • Token stores the hit dict — no dependency on the
#       in-memory media_search session store
#     • Survives bot restart within the TTL window
#
#   deliver_{token}  → batch episode delivery (series)
#     • Created after user picks quality in series flow
#     • Stores all episode hits for a (season, quality) pair
#     • start_router iterates + sends each file
#
# Storage: SYSTEM DB → `group_tokens` collection
# TTL:     1 hour (3600s), Mongo TTL index auto-purges
#
# Public API:
#   create_file_token(user_id, chat_id, hit, query) → str | None
#   create_deliver_token(user_id, chat_id, title, season,
#                        quality, language, hits) → str | None
#   get_token(token) → dict | None
#   mark_used(token) → None
#   purge_expired() → int
#   ensure_indexes() → bool
#
# ============================================================

from __future__ import annotations

import logging
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ============================================================
# SECTION 1 — CONSTANTS
# ============================================================

COLLECTION = "group_tokens"
TTL_SECONDS = 3600
MAX_HITS_PER_DELIVER = 200


# ============================================================
# SECTION 2 — DB ACCESS
# ============================================================

def _coll():
    try:
        from database import db_registry
        db = db_registry.get_system_db()
        if db is None:
            return None
        return db[COLLECTION]
    except Exception as e:
        logger.debug(f"[DL] coll: {e}")
        return None


# ============================================================
# SECTION 3 — TOKEN GENERATION
# ============================================================

def _new_token() -> str:
    """URL-safe random token, 14 chars."""
    return secrets.token_urlsafe(10)[:14]


# ============================================================
# SECTION 4 — CREATE FILE TOKEN
# ============================================================

async def create_file_token(
    user_id: int,
    chat_id: int,
    hit: Dict[str, Any],
    query: str = "",
) -> Optional[str]:
    """
    Store one hit for later PM delivery.

    hit   — plain dict (see shared.search.to_dict)
    query — original search string (for context in PM)
    """
    c = _coll()
    if c is None:
        return None

    if not hit or not hit.get("file_id"):
        return None

    try:
        token = _new_token()
        now = datetime.now(timezone.utc)

        # Keep only the fields delivery needs
        clean_hit = {
            "file_id": str(hit.get("file_id") or ""),
            "file_unique_id": hit.get("file_unique_id"),
            "file_name": str(hit.get("file_name") or ""),
            "file_size": int(hit.get("file_size") or 0),
            "title": str(hit.get("title") or ""),
            "year": hit.get("year"),
            "type": str(hit.get("type") or "movie"),
            "quality": hit.get("quality"),
            "codec": hit.get("codec"),
            "audio_languages": list(hit.get("audio_languages") or []),
            "subtitle_languages": list(hit.get("subtitle_languages") or []),
            "has_subtitle": bool(hit.get("has_subtitle")),
            "series_title": hit.get("series_title"),
            "season": hit.get("season"),
            "episode": hit.get("episode"),
        }

        await c.insert_one({
            "token": token,
            "kind": "file",
            "user_id": int(user_id),
            "chat_id": int(chat_id),
            "query": str(query)[:200],
            "hit": clean_hit,
            "created_at": now,
            "expires_at": now + timedelta(seconds=TTL_SECONDS),
            "used": False,
        })

        logger.debug(f"[DL] file token created: {token}")
        return token

    except Exception as e:
        logger.exception(f"[DL] create_file: {e}")
        return None


# ============================================================
# SECTION 5 — CREATE DELIVER TOKEN (series batch)
# ============================================================

async def create_deliver_token(
    user_id: int,
    chat_id: int,
    title: str,
    season: int,
    quality: str,
    language: str,
    hits: List[Dict[str, Any]],
) -> Optional[str]:
    """
    Store a batch of episode hits for series delivery.

    hits — list of episode dicts (each must have file_id)
    """
    c = _coll()
    if c is None:
        return None

    if not hits:
        return None

    try:
        token = _new_token()
        now = datetime.now(timezone.utc)

        # Clean + cap
        clean_hits: List[Dict[str, Any]] = []
        for h in hits[:MAX_HITS_PER_DELIVER]:
            if not h or not h.get("file_id"):
                continue
            clean_hits.append({
                "file_id": str(h.get("file_id") or ""),
                "file_unique_id": h.get("file_unique_id"),
                "file_name": str(h.get("file_name") or ""),
                "file_size": int(h.get("file_size") or 0),
                "title": str(h.get("title") or ""),
                "quality": h.get("quality"),
                "codec": h.get("codec"),
                "audio_languages": list(h.get("audio_languages") or []),
                "subtitle_languages": list(h.get("subtitle_languages") or []),
                "has_subtitle": bool(h.get("has_subtitle")),
                "season": h.get("season"),
                "episode": h.get("episode"),
            })

        if not clean_hits:
            return None

        # Sort by episode number ascending
        def _ep(h):
            try:
                return int(h.get("episode") or 0)
            except (TypeError, ValueError):
                return 0
        clean_hits.sort(key=_ep)

        await c.insert_one({
            "token": token,
            "kind": "deliver",
            "user_id": int(user_id),
            "chat_id": int(chat_id),
            "title": str(title)[:200],
            "season": int(season or 0),
            "quality": str(quality or "UNKNOWN")[:20],
            "language": str(language or "")[:40],
            "hits": clean_hits,
            "total": len(clean_hits),
            "created_at": now,
            "expires_at": now + timedelta(seconds=TTL_SECONDS),
            "used": False,
        })

        logger.debug(
            f"[DL] deliver token created: {token} "
            f"({len(clean_hits)} eps · S{season:02d} · {quality})"
        )
        return token

    except Exception as e:
        logger.exception(f"[DL] create_deliver: {e}")
        return None


# ============================================================
# SECTION 6 — READ
# ============================================================

async def get_token(token: str) -> Optional[Dict[str, Any]]:
    """
    Lookup a token. Returns None if not found or expired.
    Does NOT mark as used (see mark_used).
    """
    c = _coll()
    if c is None or not token:
        return None

    try:
        doc = await c.find_one({"token": str(token)})
        if not doc:
            return None

        # Manual expiry check (in case TTL index is lagging)
        exp = doc.get("expires_at")
        if isinstance(exp, datetime):
            # PyMongo returns naive datetimes when tz_aware=False
            now = datetime.utcnow()
            try:
                if exp.tzinfo is not None:
                    now = datetime.now(timezone.utc)
            except Exception:
                pass
            if exp < now:
                try:
                    await c.delete_one({"token": str(token)})
                except Exception:
                    pass
                return None

        doc.pop("_id", None)
        return doc

    except Exception as e:
        logger.debug(f"[DL] get: {e}")
        return None


async def get_file_hit(token: str) -> Optional[Dict[str, Any]]:
    """Shortcut for file tokens."""
    doc = await get_token(token)
    if not doc or doc.get("kind") != "file":
        return None
    return doc.get("hit")


async def get_deliver_batch(token: str) -> Optional[Dict[str, Any]]:
    """
    Shortcut for deliver tokens.
    Returns dict with: title, season, quality, language, hits
    """
    doc = await get_token(token)
    if not doc or doc.get("kind") != "deliver":
        return None
    return {
        "title": doc.get("title") or "",
        "season": doc.get("season") or 0,
        "quality": doc.get("quality") or "",
        "language": doc.get("language") or "",
        "hits": list(doc.get("hits") or []),
    }


# ============================================================
# SECTION 7 — MARK USED
# ============================================================

async def mark_used(token: str) -> None:
    """Soft-mark token as used (does not delete)."""
    c = _coll()
    if c is None or not token:
        return
    try:
        await c.update_one(
            {"token": str(token)},
            {"$set": {"used": True, "used_at": datetime.now(timezone.utc)}},
        )
    except Exception:
        pass


# ============================================================
# SECTION 8 — PURGE EXPIRED
# ============================================================

async def purge_expired() -> int:
    """Delete expired tokens. Returns count removed."""
    c = _coll()
    if c is None:
        return 0
    try:
        r = await c.delete_many({
            "expires_at": {"$lt": datetime.utcnow()}
        })
        return int(r.deleted_count or 0)
    except Exception:
        return 0


# ============================================================
# SECTION 9 — INDEXES
# ============================================================

_indexes_ready = False


async def ensure_indexes() -> bool:
    """Idempotent — safe to call on every boot."""
    global _indexes_ready
    if _indexes_ready:
        return True

    c = _coll()
    if c is None:
        return False

    try:
        await c.create_index("token", unique=True, name="token_uq")
        await c.create_index(
            "expires_at",
            expireAfterSeconds=0,
            name="ttl_expires",
        )
        await c.create_index(
            [("user_id", 1), ("kind", 1)],
            name="user_kind",
        )
        _indexes_ready = True
        logger.info("[DL] indexes ready")
        return True
    except Exception as e:
        logger.warning(f"[DL] index: {e}")
        return False


# ============================================================
# SECTION 10 — DEEP-LINK URL HELPER
# ============================================================

async def make_deep_link(
    client,
    payload: str,
) -> Optional[str]:
    """
    Build https://t.me/{bot}?start={payload}
    Returns None if bot username unavailable.
    """
    try:
        me = await client.identity()
        username = me.username or ""
    except Exception:
        try:
            me = await client.get_me()
            username = me.username or ""
        except Exception:
            username = ""

    if not username:
        return None

    return f"https://t.me/{username}?start={payload}"


# ============================================================
# SECTION 11 — SNAPSHOT
# ============================================================

def snapshot() -> Dict[str, Any]:
    return {
        "collection": COLLECTION,
        "ttl_seconds": TTL_SECONDS,
        "indexes_ready": _indexes_ready,
    }


# ============================================================
# SECTION 12 — PUBLIC EXPORTS
# ============================================================

__all__ = [
    "create_file_token",
    "create_deliver_token",
    "get_token",
    "get_file_hit",
    "get_deliver_batch",
    "mark_used",
    "purge_expired",
    "ensure_indexes",
    "make_deep_link",
    "snapshot",
    "COLLECTION",
    "TTL_SECONDS",
]
