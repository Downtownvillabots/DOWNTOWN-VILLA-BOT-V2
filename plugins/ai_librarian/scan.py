# ============================================================
# 🎛️ AI LIBRARIAN — ENGINE SEARCH · PARSER · CATALOG
# ============================================================
from __future__ import annotations
import logging, re
from collections import defaultdict
from typing import Any, Dict, List, Set, Tuple

from plugins.ai_librarian.fonts import (
    QUALITY_RANK, _normalize,
)

logger = logging.getLogger(__name__)


# ── ENGINE SEARCH ──
async def _engine_search(title, season=None, language=None, quality=None):
    try:
        from media_search.engine import engine
        from media_search.normalizer import normalize
    except Exception as e:
        logger.exception(f"[AI] engine import failed: {e}")
        return []

    all_files = []
    try:
        norm = normalize(title)
        result = await engine.search_series(norm)
        hits = result.hits if result is not None else None
        if not hits:
            result = await engine.search_any(norm)
            hits = result.hits if result is not None else None
        hits = hits or []

        logger.info(f"[AI] engine: {len(hits)} hits for {norm!r}")

        for h in hits:
            h_season = getattr(h, "season", None)
            h_episode = getattr(h, "episode", None)
            h_quality = getattr(h, "quality", None)
            h_langs = list(getattr(h, "audio_languages", []) or [])
            file_name = getattr(h, "file_name", "") or ""

            if h_season is None or h_episode is None or not h_quality or not h_langs:
                p = _parse_filename_light(file_name)
                if h_season is None: h_season = p.get("season")
                if h_episode is None: h_episode = p.get("episode")
                if not h_quality: h_quality = p.get("quality")
                if not h_langs: h_langs = p.get("languages") or []

            if season is not None and h_season != season: continue
            if language:
                ll = language.lower()
                hl = [l.lower() for l in h_langs]
                if hl and not any(ll in l or l in ll for l in hl): continue
            if quality and h_quality:
                if h_quality.upper() != quality.upper(): continue

            all_files.append({
                "file_hit": h,
                "file_id": getattr(h, "file_id", "") or "",
                "file_unique_id": getattr(h, "file_unique_id", None),
                "file_name": file_name,
                "file_size": getattr(h, "file_size", 0) or 0,
                "season": h_season,
                "episode": h_episode,
                "quality": (h_quality or "UNKNOWN"),
                "languages": h_langs,
                "title": getattr(h, "title", "") or "",
                "series_title": getattr(h, "series_title", None) or "",
                "chat_id": getattr(h, "chat_id", None),
                "message_id": getattr(h, "message_id", None) or
                              getattr(h, "msg_id", None),
            })
    except Exception as e:
        logger.exception(f"[AI] engine search failed: {e}")

    return _dedupe_by_episode(all_files)


async def _smart_db_search(title):
    """Same as series_group — try shorter prefixes if full fails."""
    norm = _normalize(title)
    if not norm: return None
    words = norm.split()
    for i in range(len(words), max(0, len(words) - 4), -1):
        partial = " ".join(words[:i])
        hits = await _engine_search(partial)
        if hits:
            matched = hits[0].get("series_title") or hits[0].get("title") or partial
            logger.info(f"[AI] smart: {title!r} → {matched!r} ({len(hits)})")
            return {"matched_title": matched, "hits": hits}
    return None


# ── FILENAME PARSER ──
_SE_PATTERNS = [
    re.compile(r"[sS](\d{1,2})[\s._-]?[eE][pP]?(\d{1,3})"),
    re.compile(r"\b(\d{1,2})[xX](\d{1,3})\b"),
    re.compile(r"[sS]eason[\s._-]?(\d{1,2})[\s._-]?[eE]pisode[\s._-]?(\d{1,3})"),
    re.compile(r"[sS](\d{1,2})[\s._-]+[eE](\d{1,3})"),
]
_SEASON_ONLY = [
    re.compile(r"\b[sS](\d{1,2})\b(?![\s._-]?[eE])"),
    re.compile(r"[sS]eason[\s._-]?(\d{1,2})\b(?![\s._-]?[eE])"),
]
_QUALITY_MARKERS = [
    ("4320p", "4320P"), ("2160p", "2160P"), ("4k", "4K"), ("uhd", "UHD"),
    ("1440p", "1440P"), ("1080p", "1080P"), ("fullhd", "1080P"), ("fhd", "1080P"),
    ("720p", "720P"), ("576p", "576P"), ("480p", "480P"), ("360p", "360P"),
]
_LANG_ALIASES = {
    "English": ["english", "eng"], "Hindi": ["hindi", "hin"],
    "Tamil": ["tamil", "tam"], "Telugu": ["telugu", "tel"],
    "Malayalam": ["malayalam", "mal"], "Kannada": ["kannada", "kan"],
    "Bengali": ["bengali", "bangla"], "Marathi": ["marathi"],
    "Punjabi": ["punjabi"], "Korean": ["korean"], "Japanese": ["japanese"],
    "Chinese": ["chinese", "mandarin"], "Spanish": ["spanish"],
    "French": ["french"], "German": ["german"], "Italian": ["italian"],
    "Portuguese": ["portuguese"], "Russian": ["russian"], "Turkish": ["turkish"],
    "Arabic": ["arabic"], "Thai": ["thai"],
}


def _parse_filename_light(filename):
    out = {"season": None, "episode": None, "quality": None, "languages": []}
    if not filename: return out
    name = filename.rsplit("/", 1)[-1].rsplit("\\", 1)[-1]
    name = re.sub(r"\.(mkv|mp4|avi|mov|wmv|flv|webm|m4v|ts)$", "", name, flags=re.I)
    wl = name.lower()

    for pat in _SE_PATTERNS:
        m = pat.search(name)
        if m:
            try:
                out["season"] = int(m.group(1))
                out["episode"] = int(m.group(2)); break
            except Exception: continue
    if out["season"] is None:
        for pat in _SEASON_ONLY:
            m = pat.search(name)
            if m:
                try: out["season"] = int(m.group(1)); break
                except Exception: continue

    for marker, label in _QUALITY_MARKERS:
        if re.search(r"\b" + re.escape(marker) + r"\b", wl):
            out["quality"] = label; break

    langs = []
    for ln, aliases in _LANG_ALIASES.items():
        for a in aliases:
            if re.search(r"\b" + re.escape(a) + r"\b", wl):
                if ln not in langs: langs.append(ln)
                break
    out["languages"] = langs
    return out


def _dedupe_by_episode(files):
    """1 file per (season, episode, quality)."""
    if not files: return []
    seen_ids: Set[str] = set()
    by_id = []
    for f in files:
        fid = str(f.get("file_id") or f.get("file_unique_id") or "")
        if fid and fid in seen_ids: continue
        if fid: seen_ids.add(fid)
        by_id.append(f)

    def _size(f):
        s = f.get("file_size") or 0
        try: return int(s)
        except (TypeError, ValueError): return 0

    by_id.sort(key=_size, reverse=True)

    seen_keys: Set[Tuple] = set()
    out = []
    for f in by_id:
        s = f.get("season"); e = f.get("episode")
        if e is None:
            p = _parse_filename_light(f.get("file_name") or "")
            if p.get("episode") is not None:
                e = p["episode"]; f["episode"] = e
            if p.get("season") is not None and s is None:
                s = p["season"]; f["season"] = s
        q = (f.get("quality") or "UNKNOWN").upper().strip()
        key = (s, e, q)
        if key in seen_keys: continue
        seen_keys.add(key)
        out.append(f)

    out.sort(key=lambda x: (
        x.get("season") or 0,
        x.get("episode") if x.get("episode") is not None else 9999))
    return out


# ── SUMMARY ──
def _summarize(files):
    qualities: Set[str] = set()
    languages: Set[str] = set()
    seasons: Dict[int, Set[int]] = defaultdict(set)
    for f in files:
        q = f.get("quality") or "UNKNOWN"
        if q != "UNKNOWN": qualities.add(q)
        for l in (f.get("languages") or []): languages.add(l)
        s = f.get("season"); e = f.get("episode")
        if s is not None: seasons[s].add(e if e is not None else 0)
    return {
        "qualities": sorted(qualities, key=lambda x: QUALITY_RANK.get(x, 0),
                            reverse=True),
        "languages": sorted(languages),
        "seasons": {s: sorted(eps) for s, eps in seasons.items()},
        "total_files": len(files),
    }


# ── CATALOG ──
class SeriesCatalog:
    def __init__(self):
        self.data: Dict[str, Dict[str, Any]] = {}

    def add_file(self, f: Dict[str, Any]) -> bool:
        title = (f.get("series_title") or f.get("title") or "").strip()
        if not title: return False
        season = f.get("season")
        episode = f.get("episode")
        if season is None: return False
        quality = (f.get("quality") or "UNKNOWN").upper()
        slug = re.sub(r"[^a-z0-9]+", "_", title.lower()).strip("_")
        if not slug: return False

        if slug not in self.data:
            self.data[slug] = {
                "title": title,
                "seasons": defaultdict(lambda: defaultdict(dict)),
                "file_count": 0,
            }

        self.data[slug]["seasons"][season][episode][quality] = f
        self.data[slug]["file_count"] += 1
        return True

    def list_series(self) -> List[Dict[str, Any]]:
        out = [{"title_slug": k, "title": v["title"],
                "file_count": v["file_count"],
                "season_count": len(v["seasons"])} for k, v in self.data.items()]
        out.sort(key=lambda x: x["title"].lower())
        return out


__all__ = [
    "_engine_search", "_smart_db_search",
    "_parse_filename_light", "_dedupe_by_episode", "_summarize",
    "SeriesCatalog",
]
