"""Read Atlas-reported data-disk space for configured database shards."""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional
from urllib.parse import quote

import httpx

from core import config

logger = logging.getLogger(__name__)

_CACHE_TTL = 60
_cache: Dict[str, tuple[float, Dict[str, Any]]] = {}


def _unavailable(reason: str) -> Dict[str, Any]:
    return {"available": False, "reason": reason}


def _remember(key: str, result: Dict[str, Any]) -> Dict[str, Any]:
    _cache[key] = (time.monotonic(), result)
    return dict(result)


def _latest_value(measurement: Dict[str, Any]) -> Optional[float]:
    points = measurement.get("dataPoints") or []
    values = [point for point in points if point.get("value") is not None]
    if not values:
        return None
    latest = max(values, key=lambda point: point.get("timestamp") or "")
    return float(latest["value"])


async def get_disk_space(entry: Any) -> Dict[str, Any]:
    """Return current host data-disk usage, or an explicit unavailable reason."""
    public_key = config.ATLAS_API_PUBLIC_KEY
    private_key = config.ATLAS_API_PRIVATE_KEY
    project_id = config.atlas_project_id(entry.pool, entry.index)
    if not public_key or not private_key:
        return _unavailable("Atlas API keys are not configured")
    if not project_id:
        return _unavailable("Atlas project ID is not configured")

    try:
        hello = await entry.client.admin.command("hello")
    except Exception as exc:
        logger.warning("Atlas disk lookup could not identify %s DB %02d: %s",
                       entry.pool, entry.index, type(exc).__name__)
        return _unavailable("could not identify the connected Atlas process")

    process_id = hello.get("me")
    if not process_id:
        return _unavailable("MongoDB did not report an Atlas process identifier")

    cache_key = f"{project_id}:{process_id}"
    cached = _cache.get(cache_key)
    if cached and time.monotonic() - cached[0] < _CACHE_TTL:
        return dict(cached[1])

    base_url = "https://cloud.mongodb.com/api/atlas/v2"
    headers = {"Accept": "application/vnd.atlas.2023-01-01+json"}
    auth = httpx.DigestAuth(public_key, private_key)
    timeout = httpx.Timeout(10.0, connect=5.0)
    try:
        async with httpx.AsyncClient(auth=auth, headers=headers,
                                     timeout=timeout) as client:
            process_path = quote(process_id, safe=":")
            path = f"{base_url}/groups/{quote(project_id, safe='')}/processes/{process_path}"
            disks_response = await client.get(f"{path}/disks")
            disks_response.raise_for_status()
            disks = disks_response.json().get("results", [])
            partitions = [
                disk.get("partitionName")
                for disk in disks
                if "data" in str(disk.get("partitionName", "")).lower()
            ]
            if not partitions:
                return _remember(
                    cache_key,
                    _unavailable("Atlas did not report a data-disk partition"),
                )

            free_bytes = 0.0
            used_bytes = 0.0
            for partition in partitions:
                response = await client.get(
                    f"{path}/disks/{quote(partition, safe='')}/measurements",
                    params=[
                        ("m", "DISK_PARTITION_SPACE_FREE"),
                        ("m", "DISK_PARTITION_SPACE_USED"),
                        ("granularity", "PT1M"),
                        ("period", "PT1H"),
                    ],
                )
                response.raise_for_status()
                measurements = {
                    item.get("name"): item
                    for item in response.json().get("measurements", [])
                }
                free = _latest_value(
                    measurements.get("DISK_PARTITION_SPACE_FREE", {})
                )
                used = _latest_value(
                    measurements.get("DISK_PARTITION_SPACE_USED", {})
                )
                if free is None or used is None:
                    return _remember(
                        cache_key,
                        _unavailable("Atlas has no recent data-disk measurements"),
                    )
                free_bytes += free
                used_bytes += used

        result = {
            "available": True,
            "free_bytes": int(free_bytes),
            "used_bytes": int(used_bytes),
            "total_bytes": int(free_bytes + used_bytes),
            "measured_at": time.time(),
        }
        return _remember(cache_key, result)
    except httpx.HTTPStatusError as exc:
        status = exc.response.status_code
        logger.warning("Atlas disk API returned HTTP %s for %s DB %02d",
                       status, entry.pool, entry.index)
        if status in (401, 403):
            reason = "Atlas API key lacks authentication or monitoring access"
        else:
            reason = f"Atlas disk API returned HTTP {status}"
        return _remember(cache_key, _unavailable(reason))
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        logger.warning("Atlas disk lookup failed for %s DB %02d: %s",
                       entry.pool, entry.index, type(exc).__name__)
        return _remember(
            cache_key,
            _unavailable("Atlas disk measurements could not be retrieved"),
        )
