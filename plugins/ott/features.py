# ============================================================
# 🏨 DOWNTOWN VILLA — OTT FEATURES (NEW in v2)
# ============================================================
#
# Advanced OTT experiences:
#   • 🔥 TRENDING    — top-rated this week
#   • ⭐ SPOTLIGHT   — editor pick of the week
#   • 📅 HYPE        — 24h pre-release notify
#   • 🎯 RECOMMEND   — similar movies based on history
#   • 📊 WEEKLY DIGEST — summary stats
#   • 🎁 WATCHLIST   — save-for-later
#
# ============================================================

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from plugins.ott import state as S
from plugins.ott import tmdb as T

logger = logging.getLogger(__name__)


# ============================================================
# TRENDING (top by rating this week)
# ============================================================

async def get_trending(limit: int = 10) -> List[Dict[str, Any]]:
    """Return top-rated movies from this week."""
    wk = S.week_key()
    w = await S.get_week(wk)
    if not w:
        return []

    all_movies = []
    for day_movies in (w.get("days") or []):
        all_movies.extend(day_movies)

    # Sort by vote_average (with min votes for quality)
    all_movies = [
        m for m in all_movies
        if (m.get("vote_count", 0) or 0) >= 10
    ]
    all_movies.sort(
        key=lambda m: (m.get("vote_average", 0) or 0),
        reverse=True,
    )
    return all_movies[:limit]


# ============================================================
# SPOTLIGHT (editor pick)
# ============================================================

async def get_spotlight() -> Optional[Dict[str, Any]]:
    """Return the spotlight movie (highest rating + popularity combo)."""
    wk = S.week_key()
    w = await S.get_week(wk)
    if not w:
        return None

    all_movies = []
    for day_movies in (w.get("days") or []):
        all_movies.extend(day_movies)

    if not all_movies:
        return None

    # Score = rating * log(votes) * popularity_norm
    def score(m):
        try:
            r = float(m.get("vote_average", 0) or 0)
            v = float(m.get("vote_count", 0) or 0)
            p = float(m.get("popularity", 0) or 0)
            return r * (v ** 0.5) * (p ** 0.3)
        except Exception:
            return 0

    all_movies.sort(key=score, reverse=True)
    return all_movies[0]


# ============================================================
# HYPE (24h pre-release)
# ============================================================

async def get_releasing_today() -> List[Dict[str, Any]]:
    """Return movies releasing TODAY (IST)."""
    today = datetime.now(S.IST).strftime("%Y-%m-%d")
    wk = S.week_key()
    w = await S.get_week(wk)
    if not w:
        return []

    out = []
    for day_movies in (w.get("days") or []):
        for m in day_movies:
            if m.get("release_date") == today:
                out.append(m)
    return out


async def get_releasing_tomorrow() -> List[Dict[str, Any]]:
    """Return movies releasing TOMORROW (IST)."""
    tomorrow = (
        datetime.now(S.IST) + timedelta(days=1)
    ).strftime("%Y-%m-%d")
    wk = S.week_key()
    w = await S.get_week(wk)
    if not w:
        return []

    out = []
    for day_movies in (w.get("days") or []):
        for m in day_movies:
            if m.get("release_date") == tomorrow:
                out.append(m)
    return out


# ============================================================
# RECOMMEND (similar to user's watch history)
# ============================================================

async def get_recommendations(
    user_id: int,
    limit: int = 5,
) -> List[Dict[str, Any]]:
    """
    Simple recommendation:
      Look at user's subscription genres,
      find this week's movies matching.
    """
    prefs = await S.get_prefs(user_id)
    user_genres = set(prefs.get("genres") or [])
    user_langs = set(prefs.get("languages") or [])

    # If user has no prefs, use their subs to build prefs
    if not user_genres and not user_langs:
        subs = await S.subs_for_user(user_id, limit=20)
        for s in subs:
            movie = await S.get_movie(s.get("tmdb_id"))
            if not movie:
                continue
            for g in (movie.get("genres") or "").split(","):
                if g.strip():
                    user_genres.add(g.strip().lower())
            if movie.get("original_language"):
                user_langs.add(movie["original_language"].lower())

    # Get this week's movies
    wk = S.week_key()
    w = await S.get_week(wk)
    if not w:
        return []

    candidates = []
    for day_movies in (w.get("days") or []):
        candidates.extend(day_movies)

    # Filter + score
    def match_score(m):
        score = 0
        genre_str = str(m.get("genres") or "").lower()
        for g in user_genres:
            if g in genre_str:
                score += 2
        if (m.get("original_language") or "").lower() in user_langs:
            score += 1
        return score

    scored = [(m, match_score(m)) for m in candidates]
    scored = [(m, s) for m, s in scored if s > 0]
    scored.sort(key=lambda x: x[1], reverse=True)

    return [m for m, _ in scored[:limit]]


# ============================================================
# WEEKLY DIGEST
# ============================================================

async def get_weekly_digest() -> Dict[str, Any]:
    """Summary of the week for newsletters."""
    wk = S.week_key()
    w = await S.get_week(wk)
    if not w:
        return {}

    days = w.get("days") or []
    total = sum(len(d) for d in days)

    counts_per_day = [len(d) for d in days]

    # Genre distribution
    genre_counter: Dict[str, int] = {}
    for d in days:
        for m in d:
            for g in (m.get("genres") or "").split(","):
                g = g.strip()
                if g:
                    genre_counter[g] = genre_counter.get(g, 0) + 1

    # Language distribution
    lang_counter: Dict[str, int] = {}
    for d in days:
        for m in d:
            lang = m.get("original_language") or ""
            if lang:
                lang_counter[lang] = lang_counter.get(lang, 0) + 1

    top_genres = sorted(
        genre_counter.items(), key=lambda x: x[1], reverse=True
    )[:5]
    top_langs = sorted(
        lang_counter.items(), key=lambda x: x[1], reverse=True
    )[:5]

    # Rating avg
    ratings = [
        m.get("vote_average", 0) for d in days for m in d
        if (m.get("vote_count", 0) or 0) >= 10
    ]
    avg_rating = sum(ratings) / len(ratings) if ratings else 0

    return {
        "week": wk,
        "total": total,
        "counts_per_day": counts_per_day,
        "top_genres": top_genres,
        "top_languages": top_langs,
        "avg_rating": round(avg_rating, 2),
    }


# ============================================================
# WATCHLIST HELPERS
# ============================================================

async def add_to_watchlist(user_id: int, tmdb_id: int) -> bool:
    movie = await S.get_movie(tmdb_id)
    if not movie:
        return False
    return await S.watchlist_add(user_id, tmdb_id, movie.get("title", "?"))


async def remove_from_watchlist(user_id: int, tmdb_id: int) -> bool:
    return await S.watchlist_remove(user_id, tmdb_id)


async def get_watchlist(user_id: int) -> List[Dict[str, Any]]:
    return await S.watchlist_get(user_id)


__all__ = [
    "get_trending", "get_spotlight",
    "get_releasing_today", "get_releasing_tomorrow",
    "get_recommendations", "get_weekly_digest",
    "add_to_watchlist", "remove_from_watchlist", "get_watchlist",
]
