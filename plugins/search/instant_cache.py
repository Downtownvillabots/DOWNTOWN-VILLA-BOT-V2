# ============================================================
# 🏨 DOWNTOWN VILLA — INSTANT SEARCH CACHE
# ============================================================
#
# Fast in-memory + DB fallback cache for search results.
#
# PURPOSE:
#   Repeated searches for the same query hit cache in <10ms
#   instead of a full shard walk (100-500ms).
#
# LAYERS:
#   L1 in-memory LRU (per-query, TTL bound)
#   L2 DB-backed (optional, not enabled here to save IO)
#
# CACHE KEY:
#   normalized_query + year + is_series
#
# ============================================================

from __future__ import annotations

import logging
import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


# ============================================================
# CONFIG
# ============================================================

DEFAULT_TTL = 300.0        # 5 min
DEFAULT_MAX = 500          # max entries


# ============================================================
# CACHE
# ============================================================

_cache: "OrderedDict[str, Tuple[float, Any]]" = OrderedDict()
_hits = 0
_misses = 0
_evictions = 0


# ============================================================
# KEY BUILDER
# ============================================================

def build_key(
    norm: str,
    year: Optional[int] = None,
    is_series: bool = False,
    mode: str = "any",
) -> str:
    return f"{mode}|{norm}|{year or ''}|{int(is_series)}"


# ============================================================
# GET
# ============================================================

def get(key: str) -> Optional[Any]:
    global _hits, _misses
    try:
        item = _cache.get(key)
        if not item:
            _misses += 1
            return None
        expires_at, value = item
        if expires_at < time.time():
            _cache.pop(key, None)
            _misses += 1
            return None
        # LRU bump
        _cache.move_to_end(key)
        _hits += 1
        return value
    except Exception:
        return None


# ============================================================
# SET
# ============================================================

def set(
    key: str,
    value: Any,
    ttl: float = DEFAULT_TTL,
    max_entries: int = DEFAULT_MAX,
) -> None:
    global _evictions
    try:
        now = time.time()
        _cache[key] = (now + ttl, value)
        _cache.move_to_end(key)
        while len(_cache) > max_entries:
            _cache.popitem(last=False)
            _evictions += 1
    except Exception:
        pass


# ============================================================
# INVALIDATE
# ============================================================

def invalidate(key: str) -> None:
    _cache.pop(key, None)


def invalidate_prefix(prefix: str) -> int:
    n = 0
    for k in list(_cache.keys()):
        if k.startswith(prefix):
            _cache.pop(k, None)
            n += 1
    return n


def clear() -> int:
    n = len(_cache)
    _cache.clear()
    return n


def cleanup() -> int:
    """Remove expired entries."""
    now = time.time()
    removed = 0
    for k in list(_cache.keys()):
        item = _cache.get(k)
        if not item:
            continue
        if item[0] < now:
            _cache.pop(k, None)
            removed += 1
    return removed


# ============================================================
# STATS
# ============================================================

def stats() -> Dict[str, Any]:
    total = _hits + _misses
    rate = (_hits / total * 100) if total else 0.0
    return {
        "size": len(_cache),
        "max": DEFAULT_MAX,
        "hits": _hits,
        "misses": _misses,
        "evictions": _evictions,
        "hit_rate": round(rate, 1),
    }


def reset_stats() -> None:
    global _hits, _misses, _evictions
    _hits = 0
    _misses = 0
    _evictions = 0


# ============================================================
# PUBLIC
# ============================================================

__all__ = [
    "build_key", "get", "set",
    "invalidate", "invalidate_prefix",
    "clear", "cleanup", "stats", "reset_stats",
    "DEFAULT_TTL", "DEFAULT_MAX",
]
