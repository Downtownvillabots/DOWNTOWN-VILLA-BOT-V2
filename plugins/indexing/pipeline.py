# ============================================================
# 🏨 DOWNTOWN VILLA — INDEXING PIPELINE
# ============================================================
#
# Uses the SAME pattern as the classic filter-bot indexer:
#
#     media = getattr(message, message.media.value, None)
#     media.file_type = message.media.value
#     media.caption   = message.caption
#     ok, code = await save_file(media)
#
# save_file() does all the real work — dedup, shard, schema.
# This file is just a thin adapter so worker.py / auto.py can
# call it uniformly and get a status dict back.
#
# ============================================================

from __future__ import annotations

import importlib
import logging
from typing import Any, Callable, Dict, Optional, Tuple

from pyrogram import enums

logger = logging.getLogger(__name__)


# ============================================================
# MEDIA TYPES WE ACCEPT (exact same 3 as reference bot)
# ============================================================

_SUPPORTED = (
    enums.MessageMediaType.VIDEO,
    enums.MessageMediaType.AUDIO,
    enums.MessageMediaType.DOCUMENT,
)


# ============================================================
# FIND save_file — TRY THE REFERENCE PATH FIRST
# ============================================================

# The classic path — this is what your reference bot uses.
_CANDIDATES = [
    ("database.ia_filterdb", "save_file"),
    ("database.ia_filter",  "save_file"),
    ("database.media_db",   "save_file"),
    ("database.files_db",   "save_file"),
    ("database.files",      "save_file"),
    ("database.index_db",   "save_file"),
    ("database.index",      "save_file"),
    ("database.media",      "save_file"),
    ("database",            "save_file"),
]

_save_file: Optional[Callable] = None
_save_file_path: Optional[str] = None


def _resolve_save_file() -> Optional[Callable]:
    global _save_file, _save_file_path
    if _save_file is not None:
        return _save_file

    for mod_path, fn_name in _CANDIDATES:
        try:
            mod = importlib.import_module(mod_path)
        except Exception:
            continue
        fn = getattr(mod, fn_name, None)
        if callable(fn):
            _save_file = fn
            _save_file_path = f"{mod_path}.{fn_name}"
            logger.info(f"[PIPELINE] ✅ save_file → {_save_file_path}")
            return fn

    logger.error(
        "[PIPELINE] ❌ save_file NOT FOUND in any candidate module.\n"
        "  Candidates tried:\n"
        + "\n".join(f"    • {m}.{f}" for m, f in _CANDIDATES)
    )
    return None


# Resolve at import time — so __init__.py logs it loudly on boot
_resolve_save_file()


# ============================================================
# MAIN ENTRY
# ============================================================

async def process_message(
    message,
    mode: str = "auto",
    metadata_source: str = "both",
) -> Dict[str, Any]:
    """
    Adapter for worker.py / auto.py.

    Returns:
        {"status": "saved",     "record": {...}}
        {"status": "duplicate", "reason": "same file_id"}
        {"status": "skipped",   "reason": "..."}
        {"status": "error",     "reason": "..."}
    """
    try:
        # ── 1. media type guard (same 3 types as reference) ──
        mt = getattr(message, "media", None)
        if not mt:
            return {"status": "skipped", "reason": "no media"}

        if mt not in _SUPPORTED:
            return {
                "status": "skipped",
                "reason": f"unsupported media: {mt}",
            }

        # ── 2. extract media object — EXACT reference pattern ──
        media = getattr(message, mt.value, None)
        if not media:
            return {"status": "skipped", "reason": "no media object"}

        # ── 3. attach the two attrs save_file() expects ──
        try:
            media.file_type = mt.value
        except Exception:
            pass
        try:
            media.caption = getattr(message, "caption", None)
        except Exception:
            pass

        # ── 4. resolve save_file ──
        fn = _resolve_save_file()
        if fn is None:
            return {"status": "error", "reason": "save_file not found"}

        # ── 5. call it ──
        try:
            result = await fn(media)
        except Exception as e:
            logger.exception(f"[PIPELINE] save_file raised: {e}")
            return {"status": "error", "reason": str(e)[:200]}

        # ── 6. interpret return value ──
        #    reference contract: (ok: bool, code: int)
        #        ok=True       → saved
        #        code=0        → duplicate
        #        code=2        → error
        ok, code = _parse_result(result)

        if ok:
            rec = {
                "file_id": getattr(media, "file_id", None),
                "file_unique_id": getattr(media, "file_unique_id", None),
                "file_name": getattr(media, "file_name", None),
                "file_size": getattr(media, "file_size", 0) or 0,
                "caption": getattr(message, "caption", None),
                "source_channel_id": getattr(
                    getattr(message, "chat", None), "id", None
                ),
                "source_message_id": getattr(message, "id", None),
            }
            logger.info(
                f"[PIPELINE] ✅ saved via {_save_file_path} "
                f"file='{rec.get('file_name') or rec.get('file_id')}'"
            )
            return {"status": "saved", "record": rec}

        if code == 0:
            return {"status": "duplicate", "reason": "same file_id"}

        return {"status": "error", "reason": f"save_file code={code}"}

    except Exception as e:
        logger.exception(f"[PIPELINE] crash: {e}")
        return {"status": "error", "reason": str(e)[:200]}


def _parse_result(result) -> Tuple[bool, int]:
    """Normalize save_file() return into (ok, code)."""
    # (ok, code) tuple — reference bot
    if isinstance(result, tuple):
        if len(result) >= 2:
            try:
                return bool(result[0]), int(result[1])
            except Exception:
                return bool(result[0]), 2
        if len(result) == 1:
            return bool(result[0]), 1

    # bare bool
    if isinstance(result, bool):
        return result, 1 if result else 0

    # None or anything else → treat as success
    if result is None:
        return True, 1

    return bool(result), 1 if result else 0


__all__ = ["process_message"]
