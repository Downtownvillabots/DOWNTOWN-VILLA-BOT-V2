# ============================================================
# 🏨 DOWNTOWN VILLA — SERIES FLOW CONFIG READER
# ============================================================
#
# Reads the per-group flow config and resolves:
#   • Which steps are enabled (from /admin → Flow Editor)
#   • What order they should run in
#   • Per-step settings (per_row, auto_skip, threshold, max_items)
#
# Series has more steps than movie:
#   base_search → spell_check → suggestions → language
#     → season → episode → quality → file_delivery
#
# Used by:
#   • groups/series/handler.py   (wizard gating)
#
# This module is READ-ONLY — writes go through state.save_field()
# when an admin toggles a step in the panel.
#
# Public API:
#   get_effective_cfg(chat_id)               → dict
#   get_step_order(chat_id)                  → list[str]
#   get_enabled_steps(chat_id)               → list[str]
#   is_step_enabled(chat_id, step_key)       → bool
#   is_auto_skip(chat_id, step_key)          → bool
#   get_step_cfg(chat_id, step_key)          → dict
#   get_per_row(chat_id, step_key)           → int
#   get_max_items(chat_id, step_key, d)      → int
#   label_for(step_key) / icon_for(step_key) → str
#   get_sort_order(chat_id)                  → str
#
# ============================================================

from __future__ import annotations

import logging
from typing import Any, Dict, List

from plugins.groups import state as S

logger = logging.getLogger(__name__)


# ============================================================
# SECTION 1 — DEFAULT STEP ORDER (series flow)
# ============================================================

DEFAULT_SERIES_STEPS: List[str] = [
    "base_search",
    "spell_check",
    "suggestions",
    "language",
    "season",
    "episode",
    "quality",
    "file_delivery",
]

# Steps that cannot be disabled
MANDATORY_STEPS = {"base_search", "file_delivery"}

# Steps that support auto-skip-if-one
AUTO_SKIP_STEPS = {"language", "season", "episode", "quality"}


# ============================================================
# SECTION 2 — STEP METADATA
# ============================================================

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
# SECTION 3 — READ EFFECTIVE CONFIG
# ============================================================

async def get_effective_cfg(chat_id: int) -> Dict[str, Any]:
    """
    Return the group config with `flow` filled from defaults.
    Every known step key is guaranteed present with all fields.
    """
    cfg = await S.get_config(chat_id)
    flow = dict(cfg.get("flow") or {})

    for step in DEFAULT_SERIES_STEPS:
        if step not in flow:
            flow[step] = _default_step_cfg(step)
        else:
            step_cfg = dict(flow[step])
            step_cfg.setdefault("enabled", True)
            step_cfg.setdefault("per_row", _default_per_row(step))
            if step in AUTO_SKIP_STEPS:
                step_cfg.setdefault("auto_skip", True)
            flow[step] = step_cfg

    cfg["flow"] = flow
    return cfg


def _default_step_cfg(step: str) -> Dict[str, Any]:
    base = {
        "enabled": True,
        "per_row": _default_per_row(step),
    }
    if step in AUTO_SKIP_STEPS:
        base["auto_skip"] = True
    return base


def _default_per_row(step: str) -> int:
    if step == "episode":
        return 4
    if step in ("language", "season", "quality"):
        return 2
    if step == "file_delivery":
        return 1
    return 2


# ============================================================
# SECTION 4 — STEP ORDER
# ============================================================

async def get_step_order(chat_id: int) -> List[str]:
    """
    Return the full step order (including disabled).
    Future: read custom order from cfg["flow_order"].
    """
    return list(DEFAULT_SERIES_STEPS)


async def get_enabled_steps(chat_id: int) -> List[str]:
    """
    Return only the enabled steps in flow order.
    Mandatory steps are always included.
    """
    cfg = await get_effective_cfg(chat_id)
    flow = cfg.get("flow") or {}

    out: List[str] = []
    for step in DEFAULT_SERIES_STEPS:
        if step in MANDATORY_STEPS:
            out.append(step)
            continue
        if flow.get(step, {}).get("enabled", True):
            out.append(step)
    return out


# ============================================================
# SECTION 5 — STEP QUERIES
# ============================================================

async def is_step_enabled(chat_id: int, step_key: str) -> bool:
    """
    True if this step should run for this group.
    Mandatory steps always return True.
    """
    if step_key in MANDATORY_STEPS:
        return True

    cfg = await get_effective_cfg(chat_id)
    flow = cfg.get("flow") or {}
    step_cfg = flow.get(step_key) or {}
    return bool(step_cfg.get("enabled", True))


async def is_auto_skip(chat_id: int, step_key: str) -> bool:
    """
    True if the step should auto-skip when only one option exists.
    Only meaningful for AUTO_SKIP_STEPS.
    """
    if step_key not in AUTO_SKIP_STEPS:
        return False

    cfg = await get_effective_cfg(chat_id)
    flow = cfg.get("flow") or {}
    step_cfg = flow.get(step_key) or {}
    return bool(step_cfg.get("auto_skip", True))


async def get_step_cfg(
    chat_id: int, step_key: str,
) -> Dict[str, Any]:
    """Return config for one step. Non-empty."""
    cfg = await get_effective_cfg(chat_id)
    flow = cfg.get("flow") or {}
    return dict(flow.get(step_key) or {})


# ============================================================
# SECTION 6 — STEP LABELS (for UI)
# ============================================================

def label_for(step_key: str) -> str:
    return STEP_LABELS.get(step_key, step_key)


def icon_for(step_key: str) -> str:
    return STEP_ICONS.get(step_key, "⚙️")


# ============================================================
# SECTION 7 — RESOLVERS
# ============================================================

async def get_sort_order(chat_id: int) -> str:
    """Return "small_to_big" or "big_to_small"."""
    cfg = await S.get_config(chat_id)
    return str(cfg.get("sort_order", "small_to_big"))


async def get_per_row(chat_id: int, step_key: str) -> int:
    """Return per_row for a step (1-4)."""
    step_cfg = await get_step_cfg(chat_id, step_key)
    try:
        n = int(step_cfg.get("per_row", 2))
    except (TypeError, ValueError):
        n = 2
    return max(1, min(4, n))


async def get_max_items(
    chat_id: int,
    step_key: str,
    default: int = 10,
) -> int:
    """Return max_items for a step (1-30)."""
    step_cfg = await get_step_cfg(chat_id, step_key)
    try:
        n = int(step_cfg.get("max_items", default))
    except (TypeError, ValueError):
        n = default
    return max(1, min(30, n))


# ============================================================
# SECTION 8 — PUBLIC EXPORTS
# ============================================================

__all__ = [
    "DEFAULT_SERIES_STEPS",
    "MANDATORY_STEPS",
    "AUTO_SKIP_STEPS",
    "STEP_LABELS",
    "STEP_ICONS",
    "get_effective_cfg",
    "get_step_order",
    "get_enabled_steps",
    "is_step_enabled",
    "is_auto_skip",
    "get_step_cfg",
    "label_for",
    "icon_for",
    "get_sort_order",
    "get_per_row",
    "get_max_items",
]
