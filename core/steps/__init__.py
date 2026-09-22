# ============================================================
# 🏨 DOWNTOWN VILLA — STEPS + FLOW REGISTRATION
# ============================================================
#
# Loads all step modules, registers default flows.
#
# Default flows built here:
#   • movie_search    → PM + Group movie flow
#   • series_search   → series flow (Language → Season → Episode → Quality)
#   • pm_search       → PM search flow
#   • broadcast       → for later use
#
# ============================================================

from __future__ import annotations

import importlib
import logging
import pkgutil
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)

_loaded: List[str] = []
_failed: List[str] = []
_registered = False


def discover() -> None:
    """Import every .py in this package."""
    global _loaded, _failed
    _loaded.clear()
    _failed.clear()

    pkg_dir = Path(__file__).parent

    for mod_info in pkgutil.iter_modules([str(pkg_dir)]):
        name = mod_info.name
        if name.startswith("_"):
            continue
        full = f"{__name__}.{name}"
        try:
            importlib.import_module(full)
            _loaded.append(name)
        except Exception as e:
            logger.exception(f"[STEPS] failed: {full}: {e}")
            _failed.append(name)

    logger.info(
        f"[STEPS] loaded {len(_loaded)} steps "
        f"({len(_failed)} failed)"
    )


def register_default_flows() -> None:
    """Build and register every default flow."""
    global _registered
    if _registered:
        return

    from core.flow_engine import (
        build_default_flow, register_flow, list_steps,
    )
    from core import flow_engine as _fe

    # ────────── MOVIE FLOW ──────────
    # search → spell → suggestions → language → quality → delivery
    movie_order = [
        "base_search",
        "spell_check",
        "suggestions",
        "language",
        "quality",
        "file_delivery",
    ]

    movie_flow = build_default_flow(
        name="movie_search",
        display_name="Movie Search",
        icon="🎬",
        description="Full movie search flow",
        step_order=movie_order,
    )
    register_flow(movie_flow)
    _fe.set_default_order("movie_search", movie_order)

    # ────────── SERIES FLOW ──────────
    # search → spell → suggestions → language → season → episode → quality → delivery
    series_order = [
        "base_search",
        "spell_check",
        "suggestions",
        "language",
        "season",
        "episode",
        "quality",
        "file_delivery",
    ]

    series_flow = build_default_flow(
        name="series_search",
        display_name="Series Search",
        icon="📺",
        description="Full series search flow",
        step_order=series_order,
    )
    register_flow(series_flow)
    _fe.set_default_order("series_search", series_order)

    # ────────── PM SEARCH FLOW ──────────
    # Simplified — skips group-only steps
    pm_order = [
        "base_search",
        "spell_check",
        "suggestions",
        "file_delivery",
    ]

    pm_flow = build_default_flow(
        name="pm_search",
        display_name="PM Search",
        icon="💬",
        description="Simplified PM search flow",
        step_order=pm_order,
    )
    register_flow(pm_flow)
    _fe.set_default_order("pm_search", pm_order)

    # ────────── BROADCAST FLOW (placeholder) ──────────
    broadcast_order = ["file_delivery"]
    b_flow = build_default_flow(
        name="broadcast",
        display_name="Broadcast",
        icon="📢",
        description="Broadcast delivery flow",
        step_order=broadcast_order,
    )
    register_flow(b_flow)
    _fe.set_default_order("broadcast", broadcast_order)

    _registered = True
    logger.info(
        f"[STEPS] registered 4 default flows · "
        f"{len(list_steps())} steps available"
    )


def loaded_steps() -> List[str]:
    return list(_loaded)


def failed_steps() -> List[str]:
    return list(_failed)


# ── Auto-run on import ──
discover()
register_default_flows()


__all__ = [
    "discover",
    "register_default_flows",
    "loaded_steps",
    "failed_steps",
]
