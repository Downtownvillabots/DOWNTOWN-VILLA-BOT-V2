# ============================================================
# 🎛️ AI LIBRARIAN — LIVE REFRESHER + STATS + RENDER
# ============================================================
from __future__ import annotations
import asyncio, logging, time
from collections import defaultdict
from typing import Any, Dict, Set

from plugins.ai_librarian.fonts import LIVE_DURATION_SEC, LIVE_REFRESH_SEC
from plugins.ai_librarian.sessions import _get_session
from plugins.ai_librarian.scan import _engine_search, SeriesCatalog
from plugins.ai_librarian.views import (
    _view_live, _view_timeout, kb_live_controls, kb_back,
    _edit_by_ids,
)

logger = logging.getLogger(__name__)


def _compute_stats(catalog_data, tmdb_seasons):
    total_found = 0
    seasons_out: Dict[int, Dict[int, Set[str]]] = defaultdict(
        lambda: defaultdict(set)
    )

    for slug, series in (catalog_data or {}).items():
        for sn, eps in (series.get("seasons") or {}).items():
            for ep, qmap in eps.items():
                if ep is None:
                    ep = 0
                for q in qmap.keys():
                    seasons_out[sn][ep].add(q)
                total_found += 1

    expected_map: Dict[int, Set[int]] = {}
    for s in (tmdb_seasons or []):
        sn = s.get("season")
        eps = s.get("episodes", 0)
        if sn and eps:
            expected_map[sn] = set(range(1, eps + 1))

    return {
        "total_found": total_found,
        "seasons": {sn: dict(e) for sn, e in seasons_out.items()},
        "expected": expected_map,
    }


def _grid_signature(stats):
    parts = []
    for sn in sorted(stats["seasons"].keys()):
        eps = stats["seasons"][sn]
        for ep in sorted(eps.keys()):
            quals = sorted(eps[ep])
            parts.append(f"{sn}:{ep}:{','.join(quals)}")
    return "|".join(parts)


async def _live_refresher(client, uid, chat_id, msg_id):
    """
    Loops for LIVE_DURATION_SEC, re-searching DB every LIVE_REFRESH_SEC,
    editing the message with updated grid.
    """
    started = time.time()
    last_grid_signature = None
    consecutive_complete = 0

    try:
        await asyncio.sleep(2)

        while True:
            elapsed = time.time() - started
            if elapsed >= LIVE_DURATION_SEC:
                logger.info(f"[AI-LIVE] {uid} session timed out")
                await _render_timeout(client, chat_id, msg_id, uid)
                return

            sess = _get_session(uid)
            if not sess or sess.get("action") != "live_scan":
                logger.info(f"[AI-LIVE] {uid} session cancelled")
                return

            search_term = sess.get("search_term") or ""
            if not search_term:
                await asyncio.sleep(LIVE_REFRESH_SEC); continue

            try:
                files = await _engine_search(search_term)
            except Exception as e:
                logger.warning(f"[AI-LIVE] search err: {e}")
                files = []

            cat = SeriesCatalog()
            for f in files:
                cat.add_file(f)

            sess["catalog_data"] = cat.data

            tmdb_seasons = sess.get("tmdb_seasons") or []
            total_expected = sum(s.get("episodes", 0) for s in tmdb_seasons)

            stats = _compute_stats(cat.data, tmdb_seasons)
            grid_sig = _grid_signature(stats)

            if grid_sig != last_grid_signature:
                last_grid_signature = grid_sig
                try:
                    await _render_live(client, chat_id, msg_id, uid,
                                       elapsed=elapsed,
                                       total_expected=total_expected)
                except Exception as e:
                    logger.debug(f"[AI-LIVE] render: {e}")

            if total_expected > 0 and stats["total_found"] >= total_expected:
                consecutive_complete += 1
                if consecutive_complete >= 2:
                    logger.info(f"[AI-LIVE] {uid} all episodes found!")
                    return
            else:
                consecutive_complete = 0

            await asyncio.sleep(LIVE_REFRESH_SEC)
    except asyncio.CancelledError:
        logger.info(f"[AI-LIVE] {uid} task cancelled")
    except Exception as e:
        logger.exception(f"[AI-LIVE] crash: {e}")


async def _render_live(client, chat_id, msg_id, uid, elapsed, total_expected):
    sess = _get_session(uid)
    if not sess: return

    title = sess.get("title") or "?"
    year = sess.get("year") or ""
    catalog_data = sess.get("catalog_data") or {}
    tmdb_seasons = sess.get("tmdb_seasons") or []

    stats = _compute_stats(catalog_data, tmdb_seasons)
    text = _view_live(title, year, elapsed, total_expected, stats, tmdb_seasons)
    kb = kb_live_controls(uid)

    await _edit_by_ids(client, chat_id, msg_id, text, kb)


async def _render_timeout(client, chat_id, msg_id, uid):
    sess = _get_session(uid)
    title = (sess or {}).get("title") or "?"
    try:
        await _edit_by_ids(client, chat_id, msg_id,
                           _view_timeout(title),
                           kb_back("ai:main"))
    except Exception: pass


__all__ = [
    "_compute_stats", "_grid_signature",
    "_live_refresher", "_render_live", "_render_timeout",
]
