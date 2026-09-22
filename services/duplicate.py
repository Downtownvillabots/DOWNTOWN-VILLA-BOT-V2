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
# RULE: this is only a HINT. The pipeline ALWAYS does a real
# DB check afterward. If the bloom misses, DB still catches it.
#
# ============================================================

from __future__ import annotations

import hashlib
import logging
import threading
from typing import Optional, Set

logger = logging.getLogger(__name__)


# ── CONFIG ──
BLOOM_MAX = 2_000_000


# ── STATE ──
_bloom: Set[str] = set()
_lock = threading.Lock()
_stats = {"hits": 0, "misses": 0, "added": 0, "evicted": 0}


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
                    {}, {"_id": 1}
                ).limit(limit)
                async for doc in cursor:
                    fp = str(doc.get("_id") or "")
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
    "_bloom_check",
    "_bloom_add",
    "load_from_db",
    "reset",
    "stats",
    "BLOOM_MAX",
]
