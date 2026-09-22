# ============================================================
# 🏨 DOWNTOWN VILLA — ACHIEVEMENTS / BADGES
# ============================================================
#
# Badges awarded to premium users based on their watch activity.
#
# Each badge is a code + display name + emoji.
# Computed on-demand from user's sessions — no separate storage.
#
# ============================================================

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


# ============================================================
# BADGE DEFINITIONS
# ============================================================

BADGES = {
    "first": {
        "name": "First Steps",
        "icon": "🥇",
        "desc": "Watched your first episode",
    },
    "binger": {
        "name": "Binge Watcher",
        "icon": "🔥",
        "desc": "Watched 10+ episodes",
    },
    "marathoner": {
        "name": "Marathoner",
        "icon": "⚡",
        "desc": "Watched 50+ episodes",
    },
    "centurion": {
        "name": "Centurion",
        "icon": "💯",
        "desc": "Watched 100+ episodes",
    },
    "completest": {
        "name": "Completionist",
        "icon": "🏆",
        "desc": "Finished a full series",
    },
    "collector": {
        "name": "Series Collector",
        "icon": "📚",
        "desc": "Watching 5+ series at once",
    },
    "critic": {
        "name": "The Critic",
        "icon": "⭐",
        "desc": "Rated 5+ series",
    },
    "loyal": {
        "name": "Loyal Fan",
        "icon": "💎",
        "desc": "Premium for 90+ days",
    },
}


# ============================================================
# COMPUTE
# ============================================================

async def compute_for_user(user_id: int) -> List[Dict[str, Any]]:
    """
    Return list of earned badges for a user.
    """
    earned: List[str] = []

    try:
        from plugins.premium import state as S

        sessions = await S.list_user_sessions(user_id, status=None)
        total_watched = 0
        completed = 0
        rating_count = 0

        for s in (sessions or []):
            p = S.compute_progress(s)
            total_watched += p["total_watched"]
            if s.get("status") == "completed":
                completed += 1
            if s.get("rated"):
                rating_count += 1

        active = [s for s in sessions if s.get("status") == "watching"]

        # Apply rules
        if total_watched >= 1:
            earned.append("first")
        if total_watched >= 10:
            earned.append("binger")
        if total_watched >= 50:
            earned.append("marathoner")
        if total_watched >= 100:
            earned.append("centurion")
        if completed >= 1:
            earned.append("completest")
        if len(active) >= 5:
            earned.append("collector")
        if rating_count >= 5:
            earned.append("critic")

        # Loyalty
        user = await S.get_user(user_id)
        if user:
            added_at = float(user.get("added_at", 0) or 0)
            if added_at and (time.time() - added_at) >= 90 * 86400:
                earned.append("loyal")

    except Exception as e:
        logger.debug(f"[PREM-BADGE] compute: {e}")

    # Build response
    out: List[Dict[str, Any]] = []
    for code in earned:
        info = BADGES.get(code)
        if info:
            out.append({"code": code, **info})
    return out


# ============================================================
# RENDER
# ============================================================

def render_badges(badges: List[Dict[str, Any]], limit: int = 5) -> str:
    """Return a short text rendering of earned badges."""
    if not badges:
        return ""
    parts = []
    for b in badges[:limit]:
        parts.append(f"{b['icon']} {b['name']}")
    return " · ".join(parts)


def render_full(badges: List[Dict[str, Any]]) -> str:
    """Return a multiline description of badges."""
    if not badges:
        return "no badges yet"
    lines = []
    for b in badges:
        lines.append(f"{b['icon']} <b>{b['name']}</b> — {b['desc']}")
    return "\n".join(lines)


# ============================================================
# PUBLIC
# ============================================================

__all__ = ["BADGES", "compute_for_user", "render_badges", "render_full"]
