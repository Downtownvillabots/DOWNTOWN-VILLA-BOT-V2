# ============================================================
# 🏨 DOWNTOWN VILLA — MOVIE FLOW READER (v2)
# ============================================================
#
# Reads the per-group flow config + custom order from DB.
# Every step + setting is controlled by:
#   • /admin → 🎯 Flow Editor → 👥 Groups → <group> → 🎬 Movie Search
#
# Default order (movie):
#   base_search → spell_check → suggestions → quality → file_delivery
#
# Optional steps (available if user adds them in editor):
#   language (for dubbed movies)
#
# What this exposes:
#   • Custom step order (from cfg.flow_order.movie)
#   • Enabled/disabled steps
#   • Per-row layout (1-4)
#   • Auto-skip if one
#   • Max items
#   • Spell check: threshold, max_corrections
#   • Suggestions: min_score, provider, show_rating, show_year, show_icon
#   • Delivery: sort_order, show_quality, show_name, name_max_len
#   • Display: poster, rating, year, genre, language toggles
#
# READ-ONLY. Writes go through state.save_field() when admin taps.
#
# Public API:
#   get_effective_cfg(chat_id)                → dict
#   get_step_order(chat_id)                   → list[str]
#   get_enabled_steps(chat_id)                → list[str]
#   get_wizard_steps(chat_id)                 → list[str]
#   is_step_enabled(chat_id, key)             → bool
#   is_auto_skip(chat_id, key)                → bool
#   get_step_cfg(chat_id, key)                → dict
#   get_per_row(chat_id, key)                 → int (1-4)
#   get_max_items(chat_id, key)               → int
#   get_spell_threshold(chat_id)              → int
#   get_max_corrections(chat_id)              → int
#   get_suggestion_min_score(chat_id)         → int
#   get_suggestion_provider(chat_id)          → str
#   get_suggestion_display(chat_id)           → dict
#   get_delivery_settings(chat_id)            → dict
#   get_display_settings(chat_id)             → dict
#   label_for(key) / icon_for(key)            → str
#
# ============================================================

from __future__ import annotations

import logging
from typing import Any, Dict, List

from plugins.groups import state as S

logger = logging.getLogger(__name__)


# ============================================================
# SECTION 1 — DEFAULTS
# ============================================================

DEFAULT_ORDER: List[str] = [
    "base_search",
    "spell_check",
    "suggestions",
    "quality",
    "file_delivery",
]

# Steps that must always run
MANDATORY_STEPS = {"base_search", "file_delivery"}

# Steps with auto-skip behavior
AUTO_SKIP_STEPS = {"quality", "language"}

# Optional steps the user can add via editor
OPTIONAL_STEPS = {"language", "season", "episode"}

# Steps that appear in the wizard UI
WIZARD_STEPS = {"quality", "language", "file_delivery"}

# All known steps (so custom order can reference any)
ALL_KNOWN_STEPS = {
    "base_search", "spell_check", "suggestions",
    "language", "season", "episode", "quality", "file_delivery",
}

# Step icons + labels (for UI)
STEP_LABELS: Dict[str, str] = {
    "base_search":   "Search",
    "spell_check":   "Spell Check",
    "suggestions":   "Suggestions",
    "language":      "Language",
    "season":        "Season",
    "episode":       "Episode",
    "quality":       "Quality",
    "file_delivery": "Delivery",
}

STEP_ICONS: Dict[str, str] = {
    "base_search":   "🔎",
    "spell_check":   "🔤",
    "suggestions":   "💡",
    "language":      "🌍",
    "season":        "📺",
    "episode":       "🎞️",
    "quality":       "🎯",
    "file_delivery": "📤",
}


# ============================================================
# SECTION 2 — READ CONFIG
# ============================================================

async def get_effective_cfg(chat_id: int) -> Dict[str, Any]:
    """Group config with flow + flow_order normalized."""
    cfg = await S.get_config(chat_id)

    # Ensure flow dict exists — including all known steps
    flow = dict(cfg.get("flow") or {})
    for key in ALL_KNOWN_STEPS:
        step = dict(flow.get(key) or {})
        step.setdefault("enabled", True)
        step.setdefault("per_row", _default_per_row(key))
        if key in AUTO_SKIP_STEPS:
            step.setdefault("auto_skip", True)
        flow[key] = step
    cfg["flow"] = flow

    # Ensure flow_order
    flow_order = dict(cfg.get("flow_order") or {})
    if not isinstance(flow_order.get("movie"), list):
        flow_order["movie"] = []
    cfg["flow_order"] = flow_order

    return cfg


def _default_per_row(key: str) -> int:
    if key == "episode":
        return 4
    if key in ("language", "season", "quality"):
        return 2
    return 1


# ============================================================
# SECTION 3 — ORDER (custom → fallback to default)
# ============================================================

async def get_step_order(chat_id: int) -> List[str]:
    """
    Return the step order for this group.
    Custom order from DB takes priority. Missing steps
    are appended from DEFAULT_ORDER at the end.
    """
    cfg = await get_effective_cfg(chat_id)
    custom = list((cfg.get("flow_order") or {}).get("movie") or [])

    # Keep only valid keys, no duplicates
    order: List[str] = []
    seen: set = set()
    for k in custom:
        if k in ALL_KNOWN_STEPS and k not in seen:
            order.append(k)
            seen.add(k)

    # Append any missing defaults
    for k in DEFAULT_ORDER:
        if k not in seen:
            order.append(k)
            seen.add(k)

    return order


async def get_enabled_steps(chat_id: int) -> List[str]:
    """Enabled steps in custom order. Mandatory always included."""
    order = await get_step_order(chat_id)
    cfg = await get_effective_cfg(chat_id)
    flow = cfg.get("flow") or {}

    out: List[str] = []
    for k in order:
        if k in MANDATORY_STEPS:
            out.append(k)
            continue
        if flow.get(k, {}).get("enabled", True):
            out.append(k)
    return out


async def get_wizard_steps(chat_id: int) -> List[str]:
    """
    Only the wizard-visible steps (quality/language/delivery)
    in custom order + enabled. Used by the handler to know
    which steps to render.
    """
    enabled = await get_enabled_steps(chat_id)
    return [k for k in enabled if k in WIZARD_STEPS]


# ============================================================
# SECTION 4 — STEP QUERIES
# ============================================================

async def is_step_enabled(chat_id: int, key: str) -> bool:
    if key in MANDATORY_STEPS:
        return True
    cfg = await get_effective_cfg(chat_id)
    step = (cfg.get("flow") or {}).get(key) or {}
    return bool(step.get("enabled", True))


async def is_auto_skip(chat_id: int, key: str) -> bool:
    if key not in AUTO_SKIP_STEPS:
        return False
    cfg = await get_effective_cfg(chat_id)
    step = (cfg.get("flow") or {}).get(key) or {}
    return bool(step.get("auto_skip", True))


async def get_step_cfg(chat_id: int, key: str) -> Dict[str, Any]:
    cfg = await get_effective_cfg(chat_id)
    return dict((cfg.get("flow") or {}).get(key) or {})


async def get_per_row(chat_id: int, key: str) -> int:
    step = await get_step_cfg(chat_id, key)
    try:
        n = int(step.get("per_row", _default_per_row(key)))
    except (TypeError, ValueError):
        n = _default_per_row(key)
    return max(1, min(4, n))


async def get_max_items(chat_id: int, key: str, default: int = 10) -> int:
    step = await get_step_cfg(chat_id, key)
    try:
        n = int(step.get("max_items", default))
    except (TypeError, ValueError):
        n = default
    return max(1, min(30, n))


# ============================================================
# SECTION 5 — ADVANCED SETTINGS
# ============================================================

async def get_spell_threshold(chat_id: int) -> int:
    """0-100 — higher = stricter spelling. Default 82."""
    step = await get_step_cfg(chat_id, "spell_check")
    try:
        n = int(step.get("threshold", 82))
    except (TypeError, ValueError):
        n = 82
    return max(60, min(95, n))


async def get_max_corrections(chat_id: int) -> int:
    """1-3 — how many retry attempts on spell fail."""
    step = await get_step_cfg(chat_id, "spell_check")
    try:
        n = int(step.get("max_corrections", 1))
    except (TypeError, ValueError):
        n = 1
    return max(1, min(3, n))


async def get_suggestion_min_score(chat_id: int) -> int:
    """0-100 — minimum fuzzy score to show a suggestion. Default 45."""
    step = await get_step_cfg(chat_id, "suggestions")
    try:
        n = int(step.get("min_score", 45))
    except (TypeError, ValueError):
        n = 45
    return max(20, min(90, n))


async def get_suggestion_provider(chat_id: int) -> str:
    """'tmdb' | 'imdb' | 'both'"""
    step = await get_step_cfg(chat_id, "suggestions")
    p = str(step.get("provider", "both")).lower()
    if p not in ("tmdb", "imdb", "both"):
        return "both"
    return p


async def get_suggestion_display(chat_id: int) -> Dict[str, bool]:
    """What to show on suggestion buttons."""
    step = await get_step_cfg(chat_id, "suggestions")
    return {
        "show_rating": bool(step.get("show_rating", True)),
        "show_year":   bool(step.get("show_year", True)),
        "show_icon":   bool(step.get("show_icon", True)),
    }


async def get_delivery_settings(chat_id: int) -> Dict[str, Any]:
    """Sort order + button format for file delivery."""
    step = await get_step_cfg(chat_id, "file_delivery")
    sort_order = str(step.get("sort_order", "small_to_big"))
    if sort_order not in ("small_to_big", "big_to_small"):
        sort_order = "small_to_big"

    return {
        "sort_order":     sort_order,
        "show_quality":   bool(step.get("show_quality", True)),
        "show_name":      bool(step.get("show_name", True)),
        "name_max_len":   int(step.get("name_max_len", 34) or 34),
        "size_format":    str(step.get("size_format", "short")),
    }


async def get_display_settings(chat_id: int) -> Dict[str, bool]:
    """Poster / rating / year / genre / language toggles (metadata section)."""
    cfg = await get_effective_cfg(chat_id)
    meta = cfg.get("metadata") or {}
    return {
        "poster":   bool(meta.get("poster", True)),
        "rating":   bool(meta.get("rating", True)),
        "year":     bool(meta.get("year", True)),
        "genre":    bool(meta.get("genre", True)),
        "language": bool(meta.get("language", True)),
    }


# ============================================================
# SECTION 6 — LABELS
# ============================================================

def label_for(key: str) -> str:
    return STEP_LABELS.get(key, key)


def icon_for(key: str) -> str:
    return STEP_ICONS.get(key, "⚙️")


# ============================================================
# SECTION 7 — PUBLIC EXPORTS
# ============================================================

__all__ = [
    "DEFAULT_ORDER",
    "MANDATORY_STEPS",
    "AUTO_SKIP_STEPS",
    "OPTIONAL_STEPS",
    "WIZARD_STEPS",
    "ALL_KNOWN_STEPS",
    "STEP_LABELS",
    "STEP_ICONS",
    # Read
    "get_effective_cfg",
    "get_step_order",
    "get_enabled_steps",
    "get_wizard_steps",
    # Step queries
    "is_step_enabled",
    "is_auto_skip",
    "get_step_cfg",
    "get_per_row",
    "get_max_items",
    # Advanced
    "get_spell_threshold",
    "get_max_corrections",
    "get_suggestion_min_score",
    "get_suggestion_provider",
    "get_suggestion_display",
    "get_delivery_settings",
    "get_display_settings",
    # Labels
    "label_for",
    "icon_for",
]
