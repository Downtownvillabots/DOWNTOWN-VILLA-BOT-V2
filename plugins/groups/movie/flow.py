# ============================================================
# 🏨 DOWNTOWN VILLA — MOVIE FLOW CONFIG READER
# ============================================================
#
# Reads the per-group flow config and resolves:
#   • Which steps are enabled (from /admin → Flow Editor)
#   • What order they should run in
#   • Per-step settings (threshold, max_items, per_row)
#
# Used by:
#   • groups/movie/handler.py     (step gating)
#   • groups/movie/pipeline.py    (executes the steps)
#
# The current handler (File 14) runs a HARDCODED pipeline.
# When we integrate the flow engine (File 19+), the handler
# will consult this module to run steps in the configured order.
#
# This module is READ-ONLY — it never writes config. All writes
# go through state.save_field() when an admin toggles a step.
#
# Public API:
#   get_step_order(chat_id)               → list[str]
#   get_enabled_steps(chat_id)            → list[str]
#   is_step_enabled(chat_id, step_key)    → bool
#   get_step_cfg(chat_id, step_key)       → dict
#   get_effective_cfg(chat_id)            → dict   (merged cfg)
#
# ============================================================

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from plugins.groups import state as S

logger = logging.getLogger(__name__)


# ============================================================
# SECTION 1 — DEFAULT STEP ORDER (movie flow)
# ============================================================

DEFAULT_MOVIE_STEPS: List[str] = [
    "base_search",
    "spell_check",
    "suggestions",
    "quality",
    "file_delivery",
]

# Steps that cannot be disabled
MANDATORY_STEPS = {"base_search", "file_delivery"}


# ============================================================
# SECTION 2 — STEP METADATA
# ============================================================

STEP_LABELS: Dict[str, str] = {
    "base_search":   "Search",
    "spell_check":   "Spell Check",
    "suggestions":   "Suggestions",
    "language":      "Language",
    "quality":       "Quality",
    "file_delivery": "Delivery",
}

STEP_ICONS: Dict[str, str] = {
    "base_search":   "🔎",
    "spell_check":   "🔤",
    "suggestions":   "💡",
    "language":      "🌍",
    "quality":       "🎯",
    "file_delivery": "📤",
}


# ============================================================
# SECTION 3 — READ EFFECTIVE CONFIG
# ============================================================

async def get_effective_cfg(chat_id: int) -> Dict[str, Any]:
    """
    Return the group config with `flow` filled from defaults.
    Always contains every known step key.
    """
    cfg = await S.get_config(chat_id)
    flow = dict(cfg.get("flow") or {})

    # Ensure every default step has an entry
    for step in DEFAULT_MOVIE_STEPS:
        if step not in flow:
            flow[step] = {
                "enabled": True,
                "per_row": 1,
                "auto_skip": True,
            }
        else:
            # Ensure subfields exist
            flow[step].setdefault("enabled", True)
            flow[step].setdefault("per_row", 1)
            flow[step].setdefault("auto_skip", True)

    cfg["flow"] = flow
    return cfg


# ============================================================
# SECTION 4 — STEP ORDER
# ============================================================

async def get_step_order(chat_id: int) -> List[str]:
    """
    Return the full step order (including disabled steps).
    Order is by position in DEFAULT_MOVIE_STEPS.
    """
    # Future: read custom order from cfg["flow_order"]
    return list(DEFAULT_MOVIE_STEPS)


async def get_enabled_steps(chat_id: int) -> List[str]:
    """
    Return only the enabled steps in flow order.
    Mandatory steps are always included.
    """
    cfg = await get_effective_cfg(chat_id)
    flow = cfg.get("flow") or {}

    out: List[str] = []
    for step in DEFAULT_MOVIE_STEPS:
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


async def get_step_cfg(
    chat_id: int, step_key: str,
) -> Dict[str, Any]:
    """
    Return config for one step. Guaranteed non-empty.
    """
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
# SECTION 7 — SORT ORDER RESOLUTION
# ============================================================

async def get_sort_order(chat_id: int) -> str:
    """
    Return "small_to_big" or "big_to_small".
    Falls back to config default if not set per-group.
    """
    cfg = await S.get_config(chat_id)
    return str(cfg.get("sort_order", "small_to_big"))


async def get_per_row(chat_id: int, step_key: str) -> int:
    """
    Return per_row for a step (1-3).
    """
    step_cfg = await get_step_cfg(chat_id, step_key)
    try:
        n = int(step_cfg.get("per_row", 1))
    except (TypeError, ValueError):
        n = 1
    return max(1, min(3, n))


async def get_max_items(chat_id: int, step_key: str, default: int = 10) -> int:
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
    "DEFAULT_MOVIE_STEPS",
    "MANDATORY_STEPS",
    "STEP_LABELS",
    "STEP_ICONS",
    "get_effective_cfg",
    "get_step_order",
    "get_enabled_steps",
    "is_step_enabled",
    "get_step_cfg",
    "label_for",
    "icon_for",
    "get_sort_order",
    "get_per_row",
    "get_max_items",
]
