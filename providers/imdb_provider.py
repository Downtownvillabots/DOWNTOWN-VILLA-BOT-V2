from __future__ import annotations

import logging
from typing import Any, Dict, List

from core import config
from providers.http_client import get_json

logger = logging.getLogger(__name__)

OMDB_URL = "https://www.omdbapi.com/"


async def search(
    query: str,
    kind: str = "any",
) -> List[Dict[str, Any]]:
    """Search IMDb-indexed titles through the configured OMDb API key."""
    api_key = str(getattr(config, "OMDB_API_KEY", "") or "").strip()
    if not api_key or not query.strip():
        return []

    params = {"apikey": api_key, "s": query.strip()}
    if kind in ("movie", "series"):
        params["type"] = kind
    payload = await get_json(
        OMDB_URL,
        params,
        timeout=float(getattr(config, "METADATA_TIMEOUT", 5) or 5),
    )
    if not payload or payload.get("Response") != "True":
        if payload and payload.get("Error"):
            logger.debug("[IMDb] search: %s", payload["Error"])
        return []

    results: List[Dict[str, Any]] = []
    for item in payload.get("Search") or []:
        title = str(item.get("Title") or "").strip()
        imdb_id = str(item.get("imdbID") or "").strip()
        if not title or not imdb_id:
            continue
        year = str(item.get("Year") or "")
        results.append({
            "title": title,
            "year": year[:4],
            "kind": "series" if item.get("Type") == "series" else "movie",
            "poster": item.get("Poster") if item.get("Poster") != "N/A" else None,
            "imdb_id": imdb_id,
            "rating": 0.0,
            "votes": 0,
        })
    return results


__all__ = ["search"]
