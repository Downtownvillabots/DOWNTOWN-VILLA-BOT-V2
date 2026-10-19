from __future__ import annotations

from typing import Any, Dict, Optional

import aiohttp

_session: Optional[aiohttp.ClientSession] = None


async def get_json(
    url: str,
    params: Dict[str, Any],
    timeout: float,
) -> Optional[Dict[str, Any]]:
    global _session

    if _session is None or _session.closed:
        connector = aiohttp.TCPConnector(
            limit=30,
            limit_per_host=8,
            ttl_dns_cache=300,
        )
        _session = aiohttp.ClientSession(connector=connector)

    try:
        async with _session.get(
            url,
            params=params,
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as response:
            if response.status != 200:
                return None
            payload = await response.json()
            return payload if isinstance(payload, dict) else None
    except (aiohttp.ClientError, TimeoutError, ValueError):
        return None


async def close() -> None:
    global _session
    if _session is not None and not _session.closed:
        await _session.close()
    _session = None


__all__ = ["get_json", "close"]
