# ============================================================
# 🏨 DOWNTOWN VILLA — MEDIA MODELS
# ============================================================
#
# Shared data classes for the search pipeline.
#
# Used by:
#   • media_search/engine.py       (SearchResult)
#   • media_search/sessions.py     (Session)
#   • media_search/delivery.py     (FileHit)
#   • plugins/search/handlers.py   (FileHit)
#   • plugins/search/group_search  (Session.candidates)
#   • core/start_router.py         (FileHit)
#
# ============================================================

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional


# ============================================================
# FILE HIT — one file from the DB
# ============================================================

@dataclass
class FileHit:
    """One media file returned by the search engine."""

    # ── Telegram identity ──
    file_id: str = ""
    file_unique_id: Optional[str] = None
    file_name: Optional[str] = None
    file_size: int = 0

    # ── Content ──
    title: str = ""
    normalized_title: str = ""
    year: Optional[int] = None
    type: str = "movie"                 # movie | series | unknown

    # ── Release info ──
    quality: Optional[str] = None
    codec: Optional[str] = None
    audio_languages: List[str] = field(default_factory=list)
    subtitle_languages: List[str] = field(default_factory=list)
    has_subtitle: bool = False

    # ── Series-only ──
    series_title: Optional[str] = None
    season: Optional[int] = None
    episode: Optional[int] = None

    # ── Provenance (optional) ──
    source_channel_id: Optional[int] = None
    source_message_id: Optional[int] = None
    source_shard: Optional[int] = None

    # ── Ranking helpers ──
    rank_score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FileHit":
        if not isinstance(data, dict):
            return cls()
        try:
            return cls(
                file_id=str(data.get("file_id") or ""),
                file_unique_id=data.get("file_unique_id"),
                file_name=data.get("file_name"),
                file_size=int(data.get("file_size") or 0),
                title=str(data.get("title") or ""),
                normalized_title=str(data.get("normalized_title") or ""),
                year=_to_int(data.get("year")),
                type=str(data.get("type") or "movie"),
                quality=data.get("quality"),
                codec=data.get("codec"),
                audio_languages=list(
                    data.get("audio_languages")
                    or data.get("languages")
                    or []
                ),
                subtitle_languages=list(
                    data.get("subtitle_languages") or []
                ),
                has_subtitle=bool(data.get("has_subtitle")),
                series_title=data.get("series_title"),
                season=_to_int(data.get("season")),
                episode=_to_int(data.get("episode")),
                source_channel_id=_to_int(data.get("source_channel_id")),
                source_message_id=_to_int(data.get("source_message_id")),
                source_shard=_to_int(data.get("source_shard")),
                rank_score=float(data.get("rank_score") or 0.0),
            )
        except Exception:
            return cls()

    # ── Helpers ──

    def display_name(self) -> str:
        if self.series_title:
            s = f"S{self.season:02d}" if self.season else ""
            e = f"E{self.episode:02d}" if self.episode else ""
            sep = s + e
            return f"{self.series_title} {sep}".strip() or self.title
        return self.title or self.file_name or "?"

    def is_series(self) -> bool:
        return self.type == "series" or (
            self.season is not None and self.episode is not None
        )


# ============================================================
# SEARCH RESULT — engine output
# ============================================================

@dataclass
class SearchResult:
    """Aggregate result from the search engine."""

    query: str = ""
    normalized_query: str = ""
    year: Optional[int] = None
    is_series: bool = False

    hits: List[FileHit] = field(default_factory=list)

    # ── Diagnostics ──
    complete: bool = True              # all shards responded
    shard_count: int = 0
    shard_ok: int = 0
    shard_failed: int = 0
    elapsed_ms: float = 0.0
    cached: bool = False

    def __len__(self) -> int:
        return len(self.hits)

    def is_empty(self) -> bool:
        return not self.hits


# ============================================================
# SESSION — group search short-lived state
# ============================================================

@dataclass
class Session:
    """A search session bound to (user, chat, query)."""

    session_id: str = field(
        default_factory=lambda: uuid.uuid4().hex[:12]
    )
    user_id: int = 0
    chat_id: int = 0

    query: str = ""
    normalized_query: str = ""
    mode: str = "movie"                # movie | series | any
    year: Optional[int] = None

    candidates: List[Dict[str, Any]] = field(default_factory=list)

    # ── Meta ──
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    expires_at: float = field(
        default_factory=lambda: time.time() + 1800
    )

    def is_expired(self) -> bool:
        return time.time() > self.expires_at

    def touch(self) -> None:
        self.updated_at = time.time()


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
# EXPORTS
# ============================================================

__all__ = [
    "FileHit",
    "SearchResult",
    "Session",
]
