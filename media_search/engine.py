# ============================================================
# 🏨 DOWNTOWN VILLA — SEARCH ENGINE
# ============================================================
#
# Multi-shard search core.
#
# Public API (singleton):
#   engine.search_movie(query, year=None)   → SearchResult
#   engine.search_series(query, year=None)  → SearchResult
#   engine.search_any(query, year=None)     → SearchResult
#   engine.search_all(query)                → SearchResult
#
# HOW IT WORKS:
#   1. Normalize the query
#   2. Cache lookup (instant_cache)
#   3. Query every online media shard in parallel
#   4. Merge + dedupe + rank
#   5. Cache store + return
#
# PERFORMANCE:
#   • Shards queried in parallel via asyncio.gather
#   • Per-shard timeout (config.SHARD_TIMEOUT, default 6s)
#   • Concurrency-limited (config.SHARD_CONCURRENCY, default 10)
#
# ============================================================

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from core import config
from media_search.models import FileHit, SearchResult
from media_search.normalizer import parse_query
from media_search.ranker import ranker

logger = logging.getLogger(__name__)


# ── CONFIG ──

SHARD_TIMEOUT = float(getattr(config, "SHARD_TIMEOUT", 6) or 6)
SHARD_CONCURRENCY = int(getattr(config, "SHARD_CONCURRENCY", 10) or 10)
MAX_RESULTS = int(getattr(config, "MAX_SEARCH_RESULTS", 200) or 200)
CACHE_TTL = float(getattr(config, "SEARCH_CACHE_TTL", 300) or 300)


# ============================================================
# ENGINE
# ============================================================

class SearchEngine:
    """Searches across all media shards."""

    def __init__(self) -> None:
        self._sem: Optional[asyncio.Semaphore] = None

    def _get_sem(self) -> asyncio.Semaphore:
        if self._sem is None:
            self._sem = asyncio.Semaphore(SHARD_CONCURRENCY)
        return self._sem

    # ── PUBLIC ──

    async def search_movie(
        self,
        query: str,
        year: Optional[int] = None,
    ) -> SearchResult:
        return await self._search(query, year=year, kind="movie")

    async def search_series(
        self,
        query: str,
        year: Optional[int] = None,
    ) -> SearchResult:
        return await self._search(query, year=year, kind="series")

    async def search_any(
        self,
        query: str,
        year: Optional[int] = None,
    ) -> SearchResult:
        return await self._search(query, year=year, kind="any")

    async def search_all(self, query: str) -> SearchResult:
        return await self._search(query, year=None, kind="any")

    # ── CORE ──

    async def _search(
        self,
        query: str,
        year: Optional[int],
        kind: str,
    ) -> SearchResult:
        t0 = time.time()

        norm, parsed_year, is_series = parse_query(query)
        use_year = year if year is not None else parsed_year

        result = SearchResult(
            query=str(query or ""),
            normalized_query=norm,
            year=use_year,
            is_series=(kind == "series") or is_series,
        )

        if not norm:
            result.complete = True
            result.elapsed_ms = (time.time() - t0) * 1000
            return result

        # ── Cache lookup ──
        cache_key = self._cache_key(norm, use_year, kind)
        try:
            from plugins.search import instant_cache as IC
            cached = IC.get(cache_key)
            if cached:
                result.hits = [
                    FileHit.from_dict(h) for h in cached.get("hits") or []
                ]
                result.complete = bool(cached.get("complete", True))
                result.cached = True
                result.elapsed_ms = (time.time() - t0) * 1000
                return result
        except Exception:
            pass

        # ── Shard list ──
        shards = self._online_shards()
        result.shard_count = len(shards)
        if not shards:
            result.complete = True
            result.elapsed_ms = (time.time() - t0) * 1000
            return result

        # ── Parallel query ──
        sem = self._get_sem()

        async def _one(entry):
            async with sem:
                try:
                    return await asyncio.wait_for(
                        self._query_shard(entry, norm, use_year, kind),
                        timeout=SHARD_TIMEOUT,
                    )
                except asyncio.TimeoutError:
                    logger.debug(
                        f"[ENGINE] shard timeout: {entry.label}"
                    )
                    return None
                except Exception as e:
                    logger.debug(
                        f"[ENGINE] shard error {entry.label}: {e}"
                    )
                    return None

        raw = await asyncio.gather(
            *[_one(s) for s in shards],
            return_exceptions=False,
        )

        # ── Merge ──
        collected: List[FileHit] = []
        for batch in raw:
            if batch is None:
                result.shard_failed += 1
                continue
            result.shard_ok += 1
            collected.extend(batch)

        result.complete = result.shard_failed == 0

        # ── Filter by kind ──
        filtered = self._filter_by_kind(collected, kind, is_series)

        # ── Dedupe ──
        deduped = self._dedupe(filtered)

        # ── Rank ──
        deduped = ranker.rank(deduped, norm)

        # ── Cap ──
        if len(deduped) > MAX_RESULTS:
            deduped = deduped[:MAX_RESULTS]

        result.hits = deduped
        result.elapsed_ms = (time.time() - t0) * 1000

        # ── Cache store ──
        try:
            from plugins.search import instant_cache as IC
            IC.set(
                cache_key,
                {
                    "hits": [h.to_dict() for h in deduped],
                    "complete": result.complete,
                },
                ttl=CACHE_TTL,
            )
        except Exception:
            pass

        logger.info(
            f"[ENGINE] '{norm}' kind={kind} year={use_year} → "
            f"{len(deduped)} hits in {result.elapsed_ms:.0f}ms "
            f"({result.shard_ok}/{result.shard_count} shards)"
        )
        return result

    # ── SHARD QUERY ──

    async def _query_shard(
        self,
        entry: Any,
        norm: str,
        year: Optional[int],
        kind: str,
    ) -> List[FileHit]:
        """Query one media shard."""
        try:
            coll = entry.db["media_files"]
        except Exception:
            return []

        # Build regex-based query
        pattern = self._build_pattern(norm)
        or_clauses: List[Dict[str, Any]] = [
            {"title": pattern},
            {"series_title": pattern},
            {"normalized_title": pattern},
            {"file_name": pattern},
        ]

        query: Dict[str, Any] = {"$or": or_clauses}

        # Year filter (loose — allow None too)
        if year:
            query = {"$and": [
                {"$or": or_clauses},
                {"$or": [
                    {"year": str(year)},
                    {"year": int(year)},
                    {"year": None},
                ]},
            ]}

        hits: List[FileHit] = []
        try:
            cursor = coll.find(query).limit(MAX_RESULTS)
            docs = await cursor.to_list(length=MAX_RESULTS)
        except Exception as e:
            logger.debug(f"[ENGINE] {entry.label} find: {e}")
            return []

        for doc in docs:
            h = self._doc_to_hit(doc, entry)
            if h:
                hits.append(h)
        return hits

    def _build_pattern(self, norm: str) -> re.Pattern:
        """Loose regex — matches if title contains the words."""
        words = [re.escape(w) for w in norm.split() if w]
        if not words:
            return re.compile(r"$^")
        if len(words) == 1:
            return re.compile(re.escape(words[0]), re.IGNORECASE)
        # All words present, in any order
        pattern = r"(?=.*" + r")(?=.*".join(words) + ")"
        try:
            return re.compile(pattern, re.IGNORECASE)
        except re.error:
            return re.compile(re.escape(norm), re.IGNORECASE)

    # ── DOC → HIT ──

    def _doc_to_hit(
        self,
        doc: Dict[str, Any],
        entry: Any,
    ) -> Optional[FileHit]:
        try:
            file_id = doc.get("file_id")
            if not file_id:
                return None

            return FileHit(
                file_id=str(file_id),
                file_unique_id=doc.get("file_unique_id"),
                file_name=doc.get("file_name") or "",
                file_size=int(doc.get("file_size") or 0),
                title=str(doc.get("title") or doc.get("series_title") or ""),
                normalized_title=str(doc.get("normalized_title") or ""),
                year=_to_int(doc.get("year")),
                type=str(doc.get("type") or "movie"),
                quality=doc.get("quality"),
                codec=doc.get("codec"),
                audio_languages=list(
                    doc.get("audio_languages")
                    or doc.get("languages")
                    or []
                ),
                subtitle_languages=list(
                    doc.get("subtitle_languages") or []
                ),
                has_subtitle=bool(doc.get("has_subtitle")),
                series_title=doc.get("series_title"),
                season=_to_int(doc.get("season")),
                episode=_to_int(doc.get("episode")),
                source_channel_id=_to_int(doc.get("source_channel_id")),
                source_message_id=_to_int(doc.get("source_message_id")),
                source_shard=int(getattr(entry, "index", 0) or 0),
            )
        except Exception as e:
            logger.debug(f"[ENGINE] doc→hit: {e}")
            return None

    # ── FILTERS ──

    def _filter_by_kind(
        self,
        hits: List[FileHit],
        kind: str,
        is_series_hint: bool,
    ) -> List[FileHit]:
        if kind == "movie":
            out = [h for h in hits if not h.is_series()]
            return out or hits
        if kind == "series":
            out = [h for h in hits if h.is_series()]
            return out or hits
        # any
        if is_series_hint:
            series = [h for h in hits if h.is_series()]
            if series:
                return series
        return hits

    def _dedupe(self, hits: List[FileHit]) -> List[FileHit]:
        """Same file_id → keep first (highest ranked source wins)."""
        seen: set = set()
        out: List[FileHit] = []
        for h in hits:
            key = h.file_unique_id or h.file_id
            if not key:
                continue
            if key in seen:
                continue
            seen.add(key)
            out.append(h)
        return out

    # ── SHARD LIST ──

    def _online_shards(self) -> List[Any]:
        try:
            from database import db_registry
            return [
                e for e in db_registry.media_entries()
                if e.online and e.db is not None
            ]
        except Exception as e:
            logger.warning(f"[ENGINE] shard list: {e}")
            return []

    # ── CACHE KEY ──

    def _cache_key(
        self,
        norm: str,
        year: Optional[int],
        kind: str,
    ) -> str:
        return f"search|{kind}|{norm}|{year or ''}"

    # ── MANUAL INVALIDATE ──

    def invalidate(self, norm: str = "") -> int:
        try:
            from plugins.search import instant_cache as IC
            if not norm:
                return IC.clear()
            return IC.invalidate_prefix(f"search|")
        except Exception:
            return 0

    # ── STATS ──

    def stats(self) -> Dict[str, Any]:
        shards = self._online_shards()
        return {
            "online_shards": len(shards),
            "shard_timeout": SHARD_TIMEOUT,
            "concurrency": SHARD_CONCURRENCY,
            "max_results": MAX_RESULTS,
        }


# ============================================================
# HELPERS
# ============================================================

def _to_int(v: Any) -> Optional[int]:
    if v is None or v == "":
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


# ============================================================
# SINGLETON
# ============================================================

engine = SearchEngine()


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    "SearchEngine",
    "engine",
]
