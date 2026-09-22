# ============================================================
# 🏨 DOWNTOWN VILLA — INDEXING PIPELINE
# ============================================================
#
# Turns a Pyrogram message into a media record + saves to DB.
#
# Called from:
#   • plugins/indexing/worker.py  (manual /index jobs)
#   • plugins/indexing/auto.py    (auto-index on new messages)
#
# RULES (LOCKED):
#   • Only skip if SAME file_id already exists
#   • Never skip for missing metadata / bad name / no caption
#   • Every other file is imported
#
# METADATA SOURCE:
#   • filename — file name only
#   • caption  — caption only
#   • both     — merge (filename first, caption fills gaps)
# ============================================================

from __future__ import annotations

import hashlib
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


# ============================================================
# REGEXES
# ============================================================

_RE_QUALITY = re.compile(
    r"\b(2160p|1440p|1080p|720p|576p|480p|360p|"
    r"4k|uhd|fhd|hd|sd|bluray|blu-ray|brrip|bdrip|"
    r"web-?dl|webrip|web|hdrip|dvdrip|dvdscr|camrip|hdtv)\b",
    re.IGNORECASE,
)

_RE_YEAR = re.compile(r"\b(19[3-9]\d|20[0-4]\d)\b")

_RE_SEASON_EP = re.compile(
    r"\bS(\d{1,2})\s*[\s._-]?\s*E(\d{1,3})\b",
    re.IGNORECASE,
)
_RE_SEASON_EP_ALT = re.compile(
    r"\b(\d{1,2})\s*x\s*(\d{1,3})\b",
    re.IGNORECASE,
)
_RE_SEASON_ONLY = re.compile(
    r"\bS(?:eason)?\s*(\d{1,2})\b",
    re.IGNORECASE,
)
_RE_EP_ONLY = re.compile(
    r"\bE(?:p|pisode)?\s*(\d{1,3})\b",
    re.IGNORECASE,
)

_RE_BRACKETS = re.compile(r"[\[\{\(]([^\]\}\)]*)[\]\}\)]")

_RE_JUNK = re.compile(
    r"\b(esub|esubs|subs|sub|hindi|english|tamil|telugu|malayalam|"
    r"kannada|bengali|marathi|punjabi|urdu|dual\s*audio|multi\s*audio|"
    r"hevc|h\.?264|h\.?265|x264|x265|aac|ac3|dts|ddp?5\.?1|"
    r"10bit|8bit|hdr|sdr|imax|proper|repack|extended|unrated|"
    r"directors?\.?cut|remastered)\b",
    re.IGNORECASE,
)

_LANG_MAP = {
    "english": "English", "eng": "English",
    "hindi": "Hindi", "hin": "Hindi",
    "tamil": "Tamil", "tam": "Tamil",
    "telugu": "Telugu", "tel": "Telugu",
    "malayalam": "Malayalam", "mal": "Malayalam",
    "kannada": "Kannada", "kan": "Kannada",
    "bengali": "Bengali", "ben": "Bengali",
    "marathi": "Marathi", "mar": "Marathi",
    "punjabi": "Punjabi", "pun": "Punjabi",
    "urdu": "Urdu",
    "korean": "Korean", "kor": "Korean",
    "japanese": "Japanese", "jpn": "Japanese",
    "chinese": "Chinese", "chi": "Chinese",
    "spanish": "Spanish", "spa": "Spanish",
    "french": "French", "fre": "French",
    "german": "German", "ger": "German",
    "russian": "Russian", "rus": "Russian",
    "arabic": "Arabic", "ara": "Arabic",
    "turkish": "Turkish", "tur": "Turkish",
    "thai": "Thai",
}

# Extensions to strip from filenames
_RE_EXT = re.compile(r"\.(mkv|mp4|avi|mov|wmv|flv|webm|m4v|ts|m2ts|mpg|mpeg)$", re.IGNORECASE)


# ============================================================
# MAIN ENTRY
# ============================================================

async def process_message(
    message,
    mode: str = "auto",
    metadata_source: str = "both",
) -> Dict[str, Any]:
    """
    Returns:
        {"status": "saved",     "record": {...}}
        {"status": "duplicate", "reason": "same file_id"}
        {"status": "skipped",   "reason": "..."}
        {"status": "error",     "reason": "..."}
    """
    try:
        # 1. pick media
        media = _pick_media(message)
        if not media:
            return {"status": "skipped", "reason": "no media"}

        file_id = media.get("file_id")
        if not file_id:
            return {"status": "skipped", "reason": "no file_id"}

        # 2. fingerprint + duplicate check (ONLY skip reason)
        fingerprint = _fingerprint(file_id)
        if await _already_saved(fingerprint, file_id):
            return {"status": "duplicate", "reason": "same file_id"}

        # 3. extract metadata text based on source
        raw_text = _metadata_text(message, media, metadata_source)

        # 4. parse
        parsed = _parse_metadata(raw_text)

        # 5. classify type (movie / series / unknown)
        ctype = _classify(message, media, parsed, raw_text, mode)

        # 6. build record
        record = _build_record(
            message=message,
            media=media,
            parsed=parsed,
            ctype=ctype,
            fingerprint=fingerprint,
            raw_text=raw_text,
        )

        # 7. enrich with tagger (never blocks)
        try:
            from plugins.indexing import tagger as TG
            record = TG.tag_and_merge(record)
        except Exception as e:
            logger.debug(f"[PIPELINE] tagger: {e}")

        # 8. save
        ok = await _save(record)
        if not ok:
            return {"status": "error", "reason": "save failed"}

        logger.info(
            f"[PIPELINE] ✅ saved type={ctype} "
            f"title='{record.get('title') or record.get('series_title') or '?'}' "
            f"S{record.get('season')}E{record.get('episode')} "
            f"q={record.get('quality')} lang={record.get('audio_languages')}"
        )
        return {"status": "saved", "record": record}

    except Exception as e:
        logger.exception(f"[PIPELINE] crash: {e}")
        return {"status": "error", "reason": str(e)[:200]}


# ============================================================
# MEDIA EXTRACTION
# ============================================================

def _pick_media(message) -> Optional[Dict[str, Any]]:
    try:
        for attr, kind in (
            ("video", "video"),
            ("document", "document"),
            ("audio", "audio"),
            ("animation", "animation"),
        ):
            obj = getattr(message, attr, None)
            if obj is None:
                continue
            return {
                "kind": kind,
                "file_id": getattr(obj, "file_id", None),
                "file_unique_id": getattr(obj, "file_unique_id", None),
                "file_name": getattr(obj, "file_name", None),
                "file_size": getattr(obj, "file_size", 0) or 0,
                "mime_type": getattr(obj, "mime_type", None),
                "duration": getattr(obj, "duration", 0) or 0,
            }
    except Exception:
        pass
    return None


def _fingerprint(file_id: str) -> str:
    try:
        from services.duplicate import compute_fingerprint
        fp = compute_fingerprint(file_id)
        if fp:
            return str(fp)
    except Exception:
        pass
    # fallback — deterministic
    return hashlib.md5(str(file_id).encode()).hexdigest()


# ============================================================
# METADATA TEXT
# ============================================================

def _metadata_text(message, media: Dict[str, Any], source: str) -> str:
    """Merge filename / caption per chosen source."""
    fname = str(media.get("file_name") or "").strip()
    caption = str(getattr(message, "caption", None) or "").strip()

    if source == "filename":
        return fname
    if source == "caption":
        return caption or fname
    # both — filename first, caption fills gaps
    parts = [p for p in (fname, caption) if p]
    return " ".join(parts)


# ============================================================
# PARSER
# ============================================================

def _parse_metadata(text: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "title": None,
        "year": None,
        "season": None,
        "episode": None,
        "quality": None,
        "audio_languages": [],
    }
    if not text:
        return out

    t = str(text)

    # strip extension from anywhere
    t_noext = _RE_EXT.sub("", t)

    # quality
    q = _RE_QUALITY.search(t_noext)
    if q:
        out["quality"] = _norm_quality(q.group(1))

    # year
    ym = _RE_YEAR.search(t_noext)
    if ym:
        out["year"] = int(ym.group(1))

    # SxxExx
    se = _RE_SEASON_EP.search(t_noext) or _RE_SEASON_EP_ALT.search(t_noext)
    if se:
        out["season"] = int(se.group(1))
        out["episode"] = int(se.group(2))
    else:
        sm = _RE_SEASON_ONLY.search(t_noext)
        if sm:
            out["season"] = int(sm.group(1))
        em = _RE_EP_ONLY.search(t_noext)
        if em:
            out["episode"] = int(em.group(1))

    # languages from bracketed groups + free text
    out["audio_languages"] = _extract_languages(t_noext)

    # title — from filename (before any bracket/quality/year tokens)
    out["title"] = _extract_title(t_noext, media=None)

    return out


def _extract_languages(text: str) -> List[str]:
    found: List[str] = []
    low = text.lower()

    # bracket content first
    for grp in _RE_BRACKETS.findall(text):
        for token in re.split(r"[\s,+/|&]+", grp.lower()):
            tok = token.strip()
            if tok in _LANG_MAP:
                name = _LANG_MAP[tok]
                if name not in found:
                    found.append(name)

    # free text — word boundary only for longer names (3+ letters)
    for alias, name in _LANG_MAP.items():
        if len(alias) < 3:
            continue
        if re.search(rf"\b{re.escape(alias)}\b", low):
            if name not in found:
                found.append(name)

    return found


def _extract_title(text: str, media=None) -> Optional[str]:
    if not text:
        return None
    t = str(text)

    # cut at first bracket / year / quality marker
    t = re.split(r"[\[\{\(]", t, maxsplit=1)[0]

    # strip extension
    t = _RE_EXT.sub("", t)

    # cut at quality / SxxExx / year
    for pat in (_RE_QUALITY, _RE_SEASON_EP, _RE_SEASON_EP_ALT, _RE_YEAR):
        m = pat.search(t)
        if m:
            t = t[: m.start()]
            break

    # strip junk tags
    t = _RE_JUNK.sub(" ", t)

    # normalize separators
    t = re.sub(r"[._\-]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip(" -|·")

    return t[:200] or None


def _norm_quality(q: str) -> str:
    q = (q or "").upper()
    alias = {
        "4K": "2160P", "UHD": "2160P",
        "FHD": "1080P", "HD": "720P", "SD": "480P",
        "WEB": "WEB-DL", "WEBRIP": "WEBRIP",
        "BLU-RAY": "BLURAY", "BDRIP": "BLURAY",
    }
    return alias.get(q, q)


# ============================================================
# CLASSIFY
# ============================================================

def _classify(
    message,
    media: Dict[str, Any],
    parsed: Dict[str, Any],
    raw_text: str,
    mode: str,
) -> str:
    """
    Returns "movie" | "series" | "unknown".
    Uses plugins.indexing.classify if available, else local heuristics.
    """
    try:
        from plugins.indexing import classify as CL

        seed = {
            "type": None,
            "title": parsed.get("title"),
            "year": parsed.get("year"),
            "season": parsed.get("season"),
            "episode": parsed.get("episode"),
            "file_name": media.get("file_name"),
            "caption": getattr(message, "caption", None),
        }
        r = CL.classify(text=raw_text, record=seed)
        if r in ("movie", "series", "unknown"):
            return r
    except Exception as e:
        logger.debug(f"[PIPELINE] classify: {e}")

    # fallback heuristics
    if parsed.get("season") is not None or parsed.get("episode") is not None:
        return "series"
    if parsed.get("year") and parsed.get("title"):
        return "movie"
    return "unknown"


# ============================================================
# RECORD
# ============================================================

def _build_record(
    message,
    media: Dict[str, Any],
    parsed: Dict[str, Any],
    ctype: str,
    fingerprint: str,
    raw_text: str,
) -> Dict[str, Any]:
    chat = getattr(message, "chat", None)
    from_user = getattr(message, "from_user", None)

    chat_id = getattr(chat, "id", None)
    chat_title = getattr(chat, "title", None) or ""
    msg_id = getattr(message, "id", None)
    date = getattr(message, "date", None)

    title = parsed.get("title") or ""
    is_series = ctype == "series"

    rec: Dict[str, Any] = {
        "_id": fingerprint,
        "fingerprint": fingerprint,

        # media
        "file_id": media.get("file_id"),
        "file_unique_id": media.get("file_unique_id"),
        "file_name": media.get("file_name") or "",
        "file_size": int(media.get("file_size") or 0),
        "mime_type": media.get("mime_type"),
        "duration": int(media.get("duration") or 0),
        "media_kind": media.get("kind"),

        # classification
        "type": ctype,
        "title": title,
        "series_title": title if is_series else None,
        "year": parsed.get("year"),
        "season": parsed.get("season"),
        "episode": parsed.get("episode"),
        "quality": parsed.get("quality") or "UNKNOWN",
        "audio_languages": list(parsed.get("audio_languages") or []),
        "languages": list(parsed.get("audio_languages") or []),  # alias

        # provenance
        "source_channel_id": int(chat_id) if chat_id else None,
        "source_channel_title": str(chat_title)[:200],
        "source_message_id": int(msg_id) if msg_id else None,
        "source_user_id": getattr(from_user, "id", None) if from_user else None,

        # raw
        "caption": str(getattr(message, "caption", None) or "")[:1000],
        "raw_text": str(raw_text or "")[:2000],

        # flags
        "indexed_by": "pipeline",

        # timestamps
        "created_at": datetime.utcnow(),
        "source_date": date,
    }

    return rec


# ============================================================
# DUPLICATE CHECK (same file_id only)
# ============================================================

async def _already_saved(fingerprint: str, file_id: str) -> bool:
    # fast bloom
    try:
        from services.duplicate import _bloom_check
        if _bloom_check(fingerprint):
            # fall through to DB verify anyway — bloom can false-positive
            pass
    except Exception:
        pass

    try:
        from database import db_registry
        for entry in db_registry.media_entries():
            try:
                doc = await entry.db["media_files"].find_one(
                    {"$or": [
                        {"_id": fingerprint},
                        {"file_id": file_id},
                    ]},
                    {"_id": 1},
                )
                if doc:
                    return True
            except Exception:
                continue
    except Exception as e:
        logger.debug(f"[PIPELINE] dup check: {e}")

    return False


# ============================================================
# SAVE
# ============================================================

async def _save(record: Dict[str, Any]) -> bool:
    try:
        from database import db_registry
        entries = list(db_registry.media_entries())
        if not entries:
            logger.warning("[PIPELINE] no media shards available")
            return False

        # shard selection — deterministic by fingerprint
        h = hashlib.md5(str(record["_id"]).encode()).hexdigest()
        idx = int(h, 16) % len(entries)
        target = entries[idx]

        payload = dict(record)
        await target.db["media_files"].update_one(
            {"_id": payload["_id"]},
            {"$set": payload},
            upsert=True,
        )

        # best-effort: update bloom filter
        try:
            from services.duplicate import _bloom_add
            _bloom_add(payload["_id"])
        except Exception:
            pass

        return True

    except Exception as e:
        logger.exception(f"[PIPELINE] save: {e}")
        return False


__all__ = ["process_message"]
