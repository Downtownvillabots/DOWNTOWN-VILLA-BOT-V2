# ============================================================
# 🏨 DOWNTOWN VILLA — DUPLICATE / FINGERPRINT SERVICE
# ============================================================
#
# Fast in-memory bloom-style set for "have I seen this file?"
#
# Used by:
#   • plugins/indexing/auto.py
#   • plugins/indexing/pipeline.py
#   • plugins/indexing/worker.py
#
# Duplicate decisions use Telegram's stable file_unique_id across every MEDIA
# shard, falling back to file_id only when Telegram does not provide one.
#
# ============================================================

from __future__ import annotations

import asyncio
import base64
import hashlib
import logging
from struct import pack
import threading
from contextlib import asynccontextmanager
from typing import Any, Iterable, Optional, Set

from pyrogram.file_id import FileId

logger = logging.getLogger(__name__)


# ── CONFIG ──
BLOOM_MAX = 2_000_000


# ── STATE ──
_bloom: Set[str] = set()
_lock = threading.Lock()
_stats = {"hits": 0, "misses": 0, "added": 0, "evicted": 0}
_file_id_locks = [asyncio.Lock() for _ in range(256)]


# ── FINGERPRINT ──

def compute_fingerprint(file_id: Optional[str]) -> str:
    """Deterministic fingerprint of a Telegram file_id."""
    if not file_id:
        return ""
    try:
        raw = str(file_id).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()[:32]
    except Exception:
        return ""


def canonical_file_id(file_id: Optional[str]) -> str:
    """Normalize a Telegram file_id like the legacy media database did."""
    if not file_id:
        return ""
    try:
        decoded = FileId.decode(str(file_id))
        raw = pack(
            "<iiqq",
            int(decoded.file_type),
            decoded.dc_id,
            decoded.media_id,
            decoded.access_hash,
        )
        encoded = bytearray()
        zero_count = 0
        for byte in raw + bytes((22, 4)):
            if byte == 0:
                zero_count += 1
                continue
            if zero_count:
                encoded.extend((0, zero_count))
                zero_count = 0
            encoded.append(byte)
        return base64.urlsafe_b64encode(encoded).decode().rstrip("=")
    except (TypeError, ValueError, OverflowError):
        return ""
    except Exception:
        logger.debug("Could not canonicalize Telegram file_id", exc_info=True)
        return ""


def file_id_lock(file_id: str) -> asyncio.Lock:
    """Serialize concurrent checks and writes for the same file ID."""
    digest = hashlib.sha256(file_id.encode("utf-8")).digest()
    return _file_id_locks[int.from_bytes(digest[:4], "big") % len(_file_id_locks)]


@asynccontextmanager
async def file_identity_lock(
    file_id: str,
    file_unique_id: Optional[str] = None,
):
    """Serialize indexing operations sharing either Telegram file identity."""
    lock_indexes = set()
    for identity in (
        file_id,
        canonical_file_id(file_id),
        file_unique_id or "",
    ):
        if identity:
            digest = hashlib.sha256(identity.encode("utf-8")).digest()
            lock_indexes.add(
                int.from_bytes(digest[:4], "big") % len(_file_id_locks)
            )

    locks = [_file_id_locks[index] for index in sorted(lock_indexes)]
    for lock in locks:
        await lock.acquire()
    try:
        yield
    finally:
        for lock in reversed(locks):
            lock.release()


async def find_exact_file_id(
    file_id: str,
    entries: Optional[Iterable[Any]] = None,
    file_unique_id: Optional[str] = None,
) -> bool:
    """Search shards by Telegram unique ID and legacy canonical file ID."""
    file_unique_id = str(file_unique_id or "")
    raw_file_id = str(file_id or "")
    stable_file_id = canonical_file_id(raw_file_id)
    identity_clauses = []
    if file_unique_id:
        identity_clauses.extend(
            ({"file_unique_id": file_unique_id}, {"_id": file_unique_id})
        )
    for identity in dict.fromkeys((stable_file_id, raw_file_id)):
        if identity:
            identity_clauses.extend(
                ({"file_id": identity}, {"_id": identity})
            )
    if not identity_clauses:
        return False
    identity_query = {"$or": identity_clauses}

    if entries is None:
        from database import db_registry
        entries = db_registry.media_entries()

    media_entries = list(entries)
    online_entries = [entry for entry in media_entries if getattr(entry, "online", False)]

    if not online_entries:
        raise RuntimeError("no online MEDIA shards available for duplicate check")

    offline_labels = [entry.label for entry in media_entries if not getattr(entry, "online", False)]
    if offline_labels:
        raise RuntimeError(
            "cannot guarantee duplicate check; MEDIA shard(s) offline: "
            + ", ".join(sorted(set(offline_labels)))
        )

    errors = []
    for entry in online_entries:
        try:
            existing = await entry.db["media_files"].find_one(
                identity_query,
                {"_id": 1},
            )
            if existing:
                return True
        except Exception as exc:
            errors.append(f"{entry.label}: {type(exc).__name__}")

    if errors:
        detail = "; ".join(errors[:3])
        raise RuntimeError(f"file_id duplicate check failed: {detail}")
    return False


# ── BLOOM ──

def _bloom_check(fp: str) -> bool:
    """True if fingerprint *might* be present."""
    if not fp:
        return False
    with _lock:
        if fp in _bloom:
            _stats["hits"] += 1
            return True
        _stats["misses"] += 1
        return False


def _bloom_add(fp: str) -> None:
    """Add fingerprint to the in-memory set."""
    if not fp:
        return
    with _lock:
        if fp in _bloom:
            return
        # Simple eviction when cap is hit
        if len(_bloom) >= BLOOM_MAX:
            drop = max(1, BLOOM_MAX // 10)
            for _ in range(drop):
                try:
                    _bloom.pop()
                except KeyError:
                    break
            _stats["evicted"] += drop
        _bloom.add(fp)
        _stats["added"] += 1


# ── LOAD FROM DB ──

async def load_from_db(limit: int = BLOOM_MAX) -> int:
    """
    Populate the bloom from all media shards.
    Call once from startup so first searches are fast.
    """
    loaded = 0
    try:
        from database import db_registry
        for entry in db_registry.media_entries():
            if not entry.online:
                continue
            try:
                cursor = entry.db["media_files"].find(
                    {}, {"_id": 1, "fingerprint": 1, "file_id": 1}
                ).limit(limit)
                async for doc in cursor:
                    fp = (
                        str(doc.get("fingerprint") or "")
                        or compute_fingerprint(doc.get("file_id"))
                        or str(doc.get("_id") or "")
                    )
                    if fp:
                        _bloom_add(fp)
                        loaded += 1
                        if loaded >= limit:
                            break
            except Exception:
                continue
            if loaded >= limit:
                break
    except Exception as e:
        logger.warning(f"[BLOOM] load failed: {e}")

    logger.info(f"[BLOOM] loaded {loaded} fingerprints")
    return loaded


# ── UTILITIES ──

def reset() -> None:
    with _lock:
        _bloom.clear()


def stats() -> dict:
    with _lock:
        total = _stats["hits"] + _stats["misses"]
        rate = (_stats["hits"] / total * 100) if total else 0.0
        return {
            "size": len(_bloom),
            "max": BLOOM_MAX,
            "hits": _stats["hits"],
            "misses": _stats["misses"],
            "hit_rate": round(rate, 1),
            "added": _stats["added"],
            "evicted": _stats["evicted"],
        }


# ── EXPORTS ──

__all__ = [
    "compute_fingerprint",
    "canonical_file_id",
    "file_id_lock",
    "file_identity_lock",
    "find_exact_file_id",
    "_bloom_check",
    "_bloom_add",
    "load_from_db",
    "reset",
    "stats",
    "BLOOM_MAX",
]
