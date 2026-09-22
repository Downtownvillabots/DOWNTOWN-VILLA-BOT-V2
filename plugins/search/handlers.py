# ============================================================
# 🏨 DOWNTOWN VILLA — SEARCH HANDLERS (ORCHESTRATION)
# ============================================================
#
# Core search orchestration.
#
# Exposes:
#   start_search(client, user_id, chat_id, query, is_group)
#       → runs the pm_search or movie_search flow
#
#   deliver_file(client, user_id, sid, idx)
#       → delivers a single file from a group session
#
#   quick_search(query, year, is_series)
#       → cache-first search returning hit list
#
# Used by:
#   • plugins/search/auto_filter.py   (PM text)
#   • plugins/search/group_search.py  (group text)
#   • core/start_router.py            (deep-link file delivery)
#
# ============================================================

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from pyrogram import Client
from pyrogram.enums import ParseMode
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from core import config
from utils import fonts as F
from utils import format as FM

logger = logging.getLogger(__name__)


# ============================================================
# SEARCH RESULT (fast path)
# ============================================================

async def quick_search(
    query: str,
    year: Optional[int] = None,
    is_series: bool = False,
) -> Tuple[List[Any], bool]:
    """
    Cache-first search.
    Returns (hits, complete_flag).
    """
    try:
        from media_search.normalizer import parse_query
        norm, parsed_year, parsed_series = parse_query(query)

        use_year = year if year is not None else parsed_year
        use_series = is_series or parsed_series

        if not norm:
            return [], True

        # Cache lookup
        try:
            from plugins.search import instant_cache as IC
            key = IC.build_key(norm, use_year, use_series)
            cached = IC.get(key)
            if cached is not None:
                return cached.get("hits", []), cached.get("complete", True)
        except Exception:
            key = None

        # Run search
        from media_search import engine as _eng_mod
        engine = getattr(_eng_mod, "engine", None)
        if engine is None:
            return [], False

        if use_series:
            result = await engine.search_series(norm, year=use_year)
        else:
            r_movie = await engine.search_movie(norm, year=use_year)
            if r_movie and r_movie.hits:
                result = r_movie
            else:
                result = await engine.search_series(norm, year=use_year)
            if not (result and result.hits):
                result = await engine.search_any(norm, year=use_year)

        hits = list(result.hits or []) if result else []
        complete = bool(getattr(result, "complete", True))

        # Cache store
        if key:
            try:
                from plugins.search import instant_cache as IC
                IC.set(key, {"hits": hits, "complete": complete})
            except Exception:
                pass

        return hits, complete

    except Exception as e:
        logger.exception(f"[SEARCH] quick_search: {e}")
        return [], False


# ============================================================
# START FLOW (PM or Group)
# ============================================================

async def start_search(
    client: Client,
    user_id: int,
    chat_id: int,
    query: str,
    is_group: bool = False,
    message: Optional[Message] = None,
) -> bool:
    """
    Start a search flow. Returns True if started.
    """
    try:
        from core import flow_engine as FE

        # Determine flow name
        if is_group:
            # Detect series vs movie
            from media_search.normalizer import parse_query
            _, _, is_series = parse_query(query)
            flow_name = "series_search" if is_series else "movie_search"
        else:
            flow_name = "pm_search"

        # Start via flow engine
        run = await FE.engine.start(
            user_id=int(user_id),
            chat_id=int(chat_id),
            flow_name=flow_name,
            client=client,
            message=message,
            initial_data={
                "raw_query": query,
                "is_group": bool(is_group),
            },
        )
        if run is None:
            logger.warning(f"[SEARCH] could not start flow: {flow_name}")
            return False

        # Render first step
        result = await FE.engine.render(run)
        if result is None:
            # Flow done with no UI
            return True

        # Send or edit
        if message is not None:
            try:
                sent = await message.reply_text(
                    result.text,
                    reply_markup=result.keyboard,
                    parse_mode=ParseMode.HTML,
                    disable_web_page_preview=True,
                )
                run.message = sent
            except Exception as e:
                logger.debug(f"[SEARCH] send step: {e}")
                return False

        return True

    except Exception as e:
        logger.exception(f"[SEARCH] start_search: {e}")
        return False


# ============================================================
# DELIVER FILE (deep-link from group)
# ============================================================

async def deliver_file(
    client: Client,
    user_id: int,
    sid: str,
    idx: int,
) -> Tuple[bool, str]:
    """
    Deliver a file from a search session.
    Returns (ok, error_message).
    """
    try:
        from media_search import sessions as _sess_mod
        from media_search import delivery as _del_mod
        from media_search.models import FileHit

        session = await _sess_mod.sessions.get(sid)
        if not session:
            return False, "⚠️ session expired"

        if idx < 0 or idx >= len(session.candidates):
            return False, "❌ invalid file"

        data = session.candidates[idx]

        # Build FileHit
        hit = FileHit(
            file_id=data.get("file_id", ""),
            file_unique_id=data.get("file_unique_id"),
            file_name=data.get("file_name"),
            file_size=data.get("file_size"),
            title=data.get("title", ""),
            normalized_title="",
            year=data.get("year"),
            type=data.get("type", "movie"),
            quality=data.get("quality"),
            codec=data.get("codec"),
            audio_languages=list(data.get("audio_languages") or []),
            subtitle_languages=list(data.get("subtitle_languages") or []),
            has_subtitle=bool(data.get("has_subtitle")),
            series_title=data.get("series_title"),
            season=data.get("season"),
            episode=data.get("episode"),
        )

        ok, err = await _del_mod.delivery.send_file(
            client, user_id, hit
        )
        return ok, err or ""

    except Exception as e:
        logger.exception(f"[SEARCH] deliver_file: {e}")
        return False, f"❌ {type(e).__name__}"


# ============================================================
# FORMAT HELPERS
# ============================================================

def format_results_header(
    query: str,
    count: int,
    is_group: bool = False,
) -> str:
    """Standard search results header."""
    return "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"{F.EMO['search']} <b>{F.fb('SEARCH RESULTS')}</b>",
        F.DIV,
        "",
        f"🔍 {F.sc('query')} · <code>{F.sc(query[:50])}</code>",
        f"📦 {F.sc('files')} · <b>{FM.num(count)}</b>",
        "",
        F.DIV_S,
        f"📌 {F.sc('tap a file to receive it')}",
    ])


def build_result_buttons(
    run_id: str,
    session_id: str,
    hits: List[Any],
    max_show: int = 10,
    per_row: int = 1,
) -> InlineKeyboardMarkup:
    """Build the search result buttons (deep-link enabled)."""
    rows: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []

    for i, hit in enumerate(hits[:max_show]):
        size = FM.size_short(getattr(hit, "file_size", 0))
        name = str(getattr(hit, "file_name", "") or "file")[:34]
        quality = str(getattr(hit, "quality", "") or "").upper()
        label = f"📦 {size}"
        if quality:
            label += f" · {quality}"
        label += f" · {name}"
        if len(label) > 60:
            label = label[:57] + "…"

        row.append(InlineKeyboardButton(
            label,
            callback_data=f"sr:file:{session_id}:{i}",
        ))
        if len(row) >= max(1, min(3, per_row)):
            rows.append(row)
            row = []

    if row:
        rows.append(row)

    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('cancel')}",
            callback_data=f"cancel:flow:{run_id}",
        ),
    ])

    return InlineKeyboardMarkup(rows)


# ============================================================
# STATS
# ============================================================

_search_count = 0


def track_search_event() -> None:
    global _search_count
    _search_count += 1
    try:
        from plugins.admin import stats as S
        S.track_search(0, "")
    except Exception:
        pass


def snapshot() -> Dict[str, Any]:
    return {
        "searches_handled": _search_count,
    }


__all__ = [
    "quick_search",
    "start_search",
    "deliver_file",
    "format_results_header",
    "build_result_buttons",
    "track_search_event",
    "snapshot",
]
