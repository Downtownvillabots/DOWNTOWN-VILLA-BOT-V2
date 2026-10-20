# ============================================================
# 🏨 DOWNTOWN VILLA — SEARCH ENGINE (v2)
# ============================================================
#
# Multi-shard search — v2 schema aware.
#
# Matches against:
#   title · normalized_title · series_title
#   normalized_series_title · file_name · caption
#
# No hard `type` filter at query time — v2 docs may have
# empty type from old indexing. Filter happens after merge.
#
# ============================================================

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any, Dict, List, Optional

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
    """Searches across all media shards (v2 aware)."""

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
            from media_search import instant_cache as IC
            cached = IC.get(cache_key)
            if cached:
                if cached.get("complete", True):
                    result.hits = [
                        FileHit.from_dict(h) for h in cached.get("hits") or []
                    ]
                    result.complete = True
                    result.cached = True
                    result.elapsed_ms = (time.time() - t0) * 1000
                    return result
        except Exception:
            pass

        # ── Shard list ──
        all_shards = self._all_shards()
        shards = [
            entry for entry in all_shards
            if entry.online and entry.db is not None
        ]
        result.shard_count = len(all_shards)
        result.shard_failed = len(all_shards) - len(shards)
        if not shards:
            result.complete = False
            result.elapsed_ms = (time.time() - t0) * 1000
            logger.warning(
                "[ENGINE] no online media shards (%d configured)",
                len(all_shards),
            )
            return result

        # ── Parallel query ──
        sem = self._get_sem()

        async def _one(entry) -> Optional[List[FileHit]]:
            async with sem:
                try:
                    return await asyncio.wait_for(
                        self._query_shard(entry, norm, use_year, kind),
                        timeout=SHARD_TIMEOUT,
                    )
                except asyncio.TimeoutError:
                    logger.warning(
                        f"[ENGINE] shard timeout: {entry.label}"
                    )
                    entry.online = False
                    entry.error = "search timed out"
                    return None
                except Exception as e:
                    logger.exception(
                        f"[ENGINE] shard error {entry.label}: {e}"
                    )
                    entry.online = False
                    entry.error = str(e)[:200]
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
        if deduped and result.complete:
            try:
                from media_search import instant_cache as IC
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

    # ── SHARD QUERY (v2 aware) ──

    async def _query_shard(
        self,
        entry: Any,
        norm: str,
        year: Optional[int],
        kind: str,
    ) -> Optional[List[FileHit]]:
        """Query one media shard — matches title, file_name, caption."""
        try:
            coll = entry.db["media_files"]
        except Exception as e:
            logger.exception(f"[ENGINE] {entry.label} collection: {e}")
            entry.online = False
            entry.error = str(e)[:200]
            return None

        query = self._build_query(norm, year, kind)

        hits: List[FileHit] = []
        try:
            cursor = coll.find(query).limit(MAX_RESULTS)
            docs = await cursor.to_list(length=MAX_RESULTS)
        except Exception as e:
            logger.exception(f"[ENGINE] {entry.label} find: {e}")
            entry.online = False
            entry.error = str(e)[:200]
            return None

        for doc in docs:
            h = self._doc_to_hit(doc, entry)
            if h:
                hits.append(h)

        logger.debug(
            f"[ENGINE] shard {entry.label} → {len(hits)} hits "
            f"(query={list(query.keys())})"
        )
        return hits

    # ── QUERY BUILDER ──

    def _build_query(
        self,
        norm: str,
        year: Optional[int],
        kind: str,
    ) -> Dict[str, Any]:
        """
        Build a MongoDB query that works on v2 schema:
          • title           (clean extracted)
          • normalized_title
          • series_title
          • normalized_series_title
          • file_name       (full original)
          • caption         (raw caption text)

        Uses plain string $regex with $options:'i' — safest
        across MongoDB drivers.
        """
        # Escape user input for regex safety
        safe = re.escape(norm.strip())

        # Loose word-boundary match if multiple words
        words = [re.escape(w) for w in norm.split() if w]
        if not words:
            words = [safe]

        # Single-word: match anywhere (case-insensitive)
        # Multi-word: all words must appear (any order)
        if len(words) == 1:
            pattern = safe
        else:
            pattern = "".join(f"(?=.*{w})" for w in words)

        title_or: List[Dict[str, Any]] = [
            {"title":                  {"$regex": pattern, "$options": "i"}},
            {"normalized_title":       {"$regex": pattern, "$options": "i"}},
            {"series_title":           {"$regex": pattern, "$options": "i"}},
            {"normalized_series_title":{"$regex": pattern, "$options": "i"}},
            {"file_name":              {"$regex": pattern, "$options": "i"}},
            {"caption":                {"$regex": pattern, "$options": "i"}},
        ]

        clauses: List[Dict[str, Any]] = [{"$or": title_or}]

        # Year filter — accept int, str, or empty
        if year:
            try:
                y_int = int(year)
                clauses.append({"$or": [
                    {"year": y_int},
                    {"year": str(year)},
                    {"year": None},
                    {"year": ""},
                ]})
            except (TypeError, ValueError):
                pass

        if len(clauses) == 1:
            return clauses[0]
        return {"$and": clauses}

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

            # Clean title fallback
            title = str(
                doc.get("title")
                or doc.get("series_title")
                or _clean_from_filename(doc.get("file_name"))
                or ""
            )

            return FileHit(
                file_id=str(file_id),
                file_unique_id=doc.get("file_unique_id"),
                file_name=doc.get("file_name") or "",
                file_size=int(doc.get("file_size") or 0),
                title=title,
                normalized_title=str(doc.get("normalized_title") or ""),
                year=_to_int(doc.get("year")),
                type=str(doc.get("type") or ""),
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
        if is_series_hint:
            series = [h for h in hits if h.is_series()]
            if series:
                return series
        return hits

    def _dedupe(self, hits: List[FileHit]) -> List[FileHit]:
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

    def _all_shards(self) -> List[Any]:
        try:
            from database import db_registry
            return db_registry.media_entries()
        except Exception as e:
            logger.warning(f"[ENGINE] shard list: {e}")
            return []

    def _online_shards(self) -> List[Any]:
        return [
            entry for entry in self._all_shards()
            if entry.online and entry.db is not None
        ]

    # ── CACHE KEY ──

    def _cache_key(
        self,
        norm: str,
        year: Optional[int],
        kind: str,
    ) -> str:
        return f"search|{kind}|{norm}|{year or ''}"

    # ── INVALIDATE ──

    def invalidate(self, norm: str = "") -> int:
        try:
            from media_search import instant_cache as IC
            if not norm:
                return IC.clear()
            normalized, _, _ = parse_query(norm)
            if not normalized:
                return 0
            return sum(
                int(
                    IC.invalidate_prefix(
                        self._cache_key(normalized, None, kind)
                    ) or 0
                )
                for kind in ("movie", "series", "any")
            )
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


_JUNK_FROM_FILENAME = re.compile(
    r"\b(?:"
    r"www\.[a-z0-9.-]+|t\.me/[a-z0-9_]+|@[a-z0-9_]+|"
    r"x264|x265|h\.?264|h\.?265|hevc|avc|aac|ac3|dts|"
    r"\d{1,2}bit|10bit|8bit|hdr|sdr|"
    r"web-?dl|webrip|bluray|brrip|bdrip|hdrip|dvdrip|"
    r"1080p|720p|480p|2160p|4k|uhd|fhd|hd|sd"
    r")\b",
    re.IGNORECASE,
)


def _clean_from_filename(name: Any) -> str:
    """Best-effort title from a raw filename (used when title missing)."""
    if not name:
        return ""
    try:
        t = str(name)
        # strip extension
        t = re.sub(r"\.[a-z0-9]{2,5}$", "", t, flags=re.IGNORECASE)
        # replace separators
        t = re.sub(r"[._\-]+", " ", t)
        # remove junk
        t = _JUNK_FROM_FILENAME.sub(" ", t)
        # collapse
        t = re.sub(r"\s+", " ", t).strip(" -_")
        return t[:200]
    except Exception:
        return ""


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
