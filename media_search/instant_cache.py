"""Small TTL cache shared by the media search engine and group search."""

from __future__ import annotations

import time
from collections import OrderedDict
from typing import Any, Optional

DEFAULT_TTL = 300.0
MAX_ENTRIES = 5000

_cache: OrderedDict[str, tuple[float, Any]] = OrderedDict()


def build_key(
    normalized_query: str,
    year: Optional[int],
    is_series: bool,
) -> str:
    kind = "series" if is_series else "movie"
    return f"search|{kind}|{normalized_query}|{year or ''}"


def get(key: str) -> Any:
    entry = _cache.get(str(key))
    if entry is None:
        return None
    expires_at, value = entry
    if expires_at <= time.monotonic():
        _cache.pop(str(key), None)
        return None
    _cache.move_to_end(str(key))
    return value


def set(key: str, value: Any, ttl: Optional[float] = None) -> None:
    key = str(key)
    ttl_seconds = DEFAULT_TTL if ttl is None else float(ttl)
    if ttl_seconds <= 0:
        _cache.pop(key, None)
        return

    now = time.monotonic()
    for cached_key, (expires_at, _) in list(_cache.items()):
        if expires_at <= now:
            _cache.pop(cached_key, None)

    _cache[key] = (now + ttl_seconds, value)
    _cache.move_to_end(key)
    while len(_cache) > MAX_ENTRIES:
        _cache.popitem(last=False)


def clear() -> int:
    count = len(_cache)
    _cache.clear()
    return count


def invalidate_prefix(prefix: str) -> int:
    prefix = str(prefix)
    keys = [key for key in _cache if key.startswith(prefix)]
    for key in keys:
        _cache.pop(key, None)
    return len(keys)


__all__ = ["build_key", "get", "set", "clear", "invalidate_prefix"]
