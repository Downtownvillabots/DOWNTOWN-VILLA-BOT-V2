# ============================================================
# 🏨 DOWNTOWN VILLA — SEARCH RESULT RANKER
# ============================================================

from __future__ import annotations

import logging
import re
from typing import Any, List

from core import config

logger = logging.getLogger(__name__)


# ── QUALITY SCORES ──

_QUALITY_RANK = {
    "2160P": 100, "4K": 100, "UHD": 100,
    "1440P": 85, "2K": 85,
    "1080P": 70, "FHD": 70, "FULLHD": 70,
    "720P": 55, "HD": 55,
    "576P": 40,
    "480P": 30, "SD": 30,
    "360P": 20,
    "240P": 10,
}

_CODEC_RANK = {
    "HEVC": 30, "H265": 30, "X265": 30,
    "AVC": 20, "H264": 20, "X264": 20,
    "AV1": 25,
    "XVID": 10, "DIVX": 10,
}


# ============================================================
# HELPERS (defined BEFORE class so no NameError can happen)
# ============================================================

def _get(hit: Any, key: str) -> Any:
    if isinstance(hit, dict):
        return hit.get(key)
    return getattr(hit, key, None)


def _norm_quality(q: Any) -> str:
    if not q:
        return ""
    s = str(q).upper().strip()
    alias = {
        "4K": "2160P", "UHD": "2160P",
        "FHD": "1080P", "FULLHD": "1080P",
        "HD": "720P", "SD": "480P",
        "2K": "1440P",
    }
    return alias.get(s, s)


def _norm_codec(c: Any) -> str:
    if not c:
        return ""
    s = str(c).upper().strip()
    s = s.replace(" ", "").replace(".", "").replace("-", "")
    return s


def _clean(t: str) -> str:
    if not t:
        return ""
    return re.sub(r"\s+", " ", str(t).lower()).strip()


# ============================================================
# RANKER
# ============================================================

class Ranker:

    def __init__(self) -> None:
        self.pref_quality = _norm_quality(
            getattr(config, "PREFERRED_QUALITY", "1080p")
        )
        self.pref_codec = _norm_codec(
            getattr(config, "PREFERRED_CODEC", "HEVC")
        )
        self.pref_audio = (
            getattr(config, "PREFERRED_AUDIO", "ENGLISH") or ""
        ).upper()
        self.pref_subtitle = (
            getattr(config, "PREFERRED_SUBTITLE", "ENGLISH") or ""
        ).upper()

    def rank(self, hits: List[Any], query: str = "") -> List[Any]:
        if not hits:
            return []
        norm_query = _clean(query)
        scored = []
        for h in hits:
            try:
                scored.append((self.score(h, norm_query), h))
            except Exception as e:
                logger.debug(f"[RANK] score failed: {e}")
                scored.append((0.0, h))
        scored.sort(key=lambda x: x[0], reverse=True)
        return [h for _, h in scored]

    def rank_one(self, hit: Any, query: str = "") -> float:
        return self.score(hit, _clean(query))

    def score(self, hit: Any, norm_query: str = "") -> float:
        score = 0.0

        # Quality
        q = _norm_quality(_get(hit, "quality"))
        score += _QUALITY_RANK.get(q, 25)

        # Codec
        c = _norm_codec(_get(hit, "codec"))
        score += _CODEC_RANK.get(c, 5)

        # Audio language preference
        langs = _get(hit, "audio_languages") or []
        langs_u = [str(x).upper() for x in langs]
        if self.pref_audio and self.pref_audio in langs_u:
            score += 15

        # Subtitle
        if _get(hit, "has_subtitle"):
            score += 5
        subs = _get(hit, "subtitle_languages") or []
        subs_u = [str(x).upper() for x in subs]
        if self.pref_subtitle and self.pref_subtitle in subs_u:
            score += 5

        # File size sanity
        size = int(_get(hit, "file_size") or 0)
        if size > 0:
            mb = size / (1024 * 1024)
            if 300 <= mb <= 8000:
                score += 10
            elif mb < 100:
                score -= 5
            elif mb > 20000:
                score -= 5

        # Title match
        if norm_query:
            title = _clean(
                _get(hit, "title")
                or _get(hit, "series_title")
                or ""
            )
            if title:
                if title == norm_query:
                    score += 20
                elif norm_query in title or title in norm_query:
                    score += 10
                else:
                    q_words = set(norm_query.split())
                    t_words = set(title.split())
                    if q_words & t_words:
                        score += 3

        return score


ranker = Ranker()


__all__ = ["Ranker", "ranker"]
