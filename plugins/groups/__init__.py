# ============================================================
# 🏨 DOWNTOWN VILLA — GROUPS PACKAGE (FINAL)
# ============================================================
#
# Auto-discovery + explicit ordering.
#
# Why this file matters:
#   Pyrogram registers handlers ONLY when a module is imported.
#   Importing a module fires @Client.on_* decorators → handlers register.
#   So this file MUST import every handler-carrying module.
#
# Import order is critical:
#   state → panel → router → commands → admin_list → text_input
#   shared/* (search → suggestions → delivery → deep_link →
#            callbacks → request_flow)
#   movie/* (flow → handler)
#   series/* (flow → tmdb → handler)
#
# Modules that register handlers:
#   • router.py           (ga:*)
#   • commands.py         (/settings, /reload, /ban, /filter, ...)
#   • admin_list.py       (glist:*)
#   • text_input.py       (private text sessions)
#   • shared/callbacks.py (sr:*)
#   • movie/handler.py    (group text — movie flow)
#   • series/handler.py   (group text — series wizard)
#
# Everything else (state, panel, shared/search, etc.) is a library.
#
# ============================================================

from __future__ import annotations

import importlib
import logging
from typing import Dict, List, Tuple

logger = logging.getLogger(__name__)

# Bump on breaking changes to the module surface
__version__ = "1.0.0"


# ============================================================
# SECTION 1 — MODULE LOAD ORDER
# ============================================================

# (full_module_path, friendly_name)
_ORDERED_MODULES: List[Tuple[str, str]] = [
    # ── Core (no handler deps) ──
    ("plugins.groups.state",           "state"),
    ("plugins.groups.panel",           "panel"),

    # ── Routers + commands ──
    ("plugins.groups.router",          "router"),
    ("plugins.groups.commands",        "commands"),
    ("plugins.groups.admin_list",      "admin_list"),
    ("plugins.groups.text_input",      "text_input"),

    # ── Shared (library → then handlers) ──
    ("plugins.groups.shared.search",         "shared.search"),
    ("plugins.groups.shared.suggestions",    "shared.suggestions"),
    ("plugins.groups.shared.delivery",       "shared.delivery"),
    ("plugins.groups.shared.deep_link",      "shared.deep_link"),
    ("plugins.groups.shared.request_flow",   "shared.request_flow"),
    ("plugins.groups.shared.callbacks",      "shared.callbacks"),

    # ── Movie (library → then handler) ──
    ("plugins.groups.movie.flow",      "movie.flow"),
    ("plugins.groups.movie.handler",   "movie.handler"),

    # ── Series (library → then handler) ──
    ("plugins.groups.series.flow",     "series.flow"),
    ("plugins.groups.series.tmdb",     "series.tmdb"),
    ("plugins.groups.series.handler",  "series.handler"),
]


# ============================================================
# SECTION 2 — DISCOVERY STATE
# ============================================================

_loaded: Dict[str, bool] = {}
_failed: Dict[str, str] = {}
_discovered = False


# ============================================================
# SECTION 3 — IMPORT
# ============================================================

def _import_one(path: str, name: str) -> bool:
    """Import one module. Isolate failures."""
    try:
        importlib.import_module(path)
        _loaded[name] = True
        logger.debug(f"[GROUPS] ✅ {name}")
        return True
    except Exception as e:
        _loaded[name] = False
        _failed[name] = f"{type(e).__name__}: {e}"
        logger.exception(f"[GROUPS] ❌ {name} ({path}): {e}")
        return False


def discover() -> None:
    """
    Import every module in order. Safe to call once.
    """
    global _discovered
    if _discovered:
        return
    _discovered = True

    logger.info(f"[GROUPS] loading {len(_ORDERED_MODULES)} modules…")

    for path, name in _ORDERED_MODULES:
        _import_one(path, name)

    ok = sum(1 for v in _loaded.values() if v)
    fail = len(_failed)

    logger.info(f"[GROUPS] loaded {ok}/{len(_ORDERED_MODULES)} modules")
    if fail:
        for name, err in _failed.items():
            logger.error(f"[GROUPS] failed: {name} → {err}")


def loaded() -> List[str]:
    return sorted(n for n, ok in _loaded.items() if ok)


def failed() -> Dict[str, str]:
    return dict(_failed)


def summary() -> str:
    """One-line summary for startup banner."""
    ok = sum(1 for v in _loaded.values() if v)
    total = len(_ORDERED_MODULES)
    if _failed:
        return f"groups: {ok}/{total} loaded ({len(_failed)} failed)"
    return f"groups: {ok}/{total} loaded ✅"


# ============================================================
# SECTION 4 — STARTUP HOOK
# ============================================================

def ensure_startup() -> None:
    """
    Called by core.startup after client boots.
    Ensures text_input cleanup loop is running.
    """
    try:
        from plugins.groups import text_input
        text_input.ensure_cleanup()
    except Exception as e:
        logger.debug(f"[GROUPS] startup hook: {e}")


# ============================================================
# SECTION 5 — PUBLIC API (re-export common helpers)
# ============================================================

def get_config_sync():
    """Read-only alias for state.get_config (await it)."""
    from plugins.groups.state import get_config
    return get_config


def get_panel_sync():
    """Read-only alias for panel module."""
    from plugins.groups import panel
    return panel


def get_router_sync():
    """Read-only alias for router module."""
    from plugins.groups import router
    return router


def snapshot() -> dict:
    return {
        "version": __version__,
        "discovered": _discovered,
        "loaded_count": sum(1 for v in _loaded.values() if v),
        "total_count": len(_ORDERED_MODULES),
        "failed": dict(_failed),
        "loaded": loaded(),
    }


# ============================================================
# SECTION 6 — SELF-TEST (non-fatal)
# ============================================================

def _self_test() -> bool:
    """Quick sanity — verify critical modules are loaded."""
    critical = ["state", "panel", "router", "movie.handler", "series.handler"]
    for c in critical:
        if not _loaded.get(c):
            logger.error(f"[GROUPS] critical module missing: {c}")
            return False
    return True


# ============================================================
# SECTION 7 — AUTO-RUN ON IMPORT
# ============================================================

discover()

try:
    _SELF_TEST_OK = _self_test()
except Exception:
    _SELF_TEST_OK = False


# ============================================================
# SECTION 8 — PUBLIC EXPORTS
# ============================================================

__all__ = [
    "__version__",
    "discover",
    "loaded",
    "failed",
    "summary",
    "ensure_startup",
    "snapshot",
    "get_config_sync",
    "get_panel_sync",
    "get_router_sync",
]
