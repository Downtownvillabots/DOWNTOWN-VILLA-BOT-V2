# ============================================================
# 🏨 DOWNTOWN VILLA — GROUPS PACKAGE
# ============================================================
#
# Auto-imports every module in:
#   groups/*.py            — state, panel, router, commands, admin_list, text_input
#   groups/shared/*.py     — search, suggestions, delivery, deep_link, callbacks, request_flow
#   groups/movie/*.py      — handler, flow
#   groups/series/*.py     — handler, flow, tmdb
#
# Handler registration happens in each file via @Client.on_* decorators.
# Importing a module fires those decorators → Pyrogram registers handlers.
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

# Import order matters — state first, then everything else.
# Python auto-imports dependencies, but explicit order gives
# readable logs and predictable startup.
_SUBPACKAGES = ("", "shared", "movie", "series")


def _import(full_name: str) -> bool:
    try:
        importlib.import_module(full_name)
        _loaded.append(full_name)
        return True
    except Exception as e:
        logger.exception(f"[GROUPS] failed: {full_name}: {e}")
        _failed.append(full_name)
        return False


def discover() -> None:
    """Import every .py in this package and its subpackages."""
    _loaded.clear()
    _failed.clear()

    pkg_dir = Path(__file__).parent
    base_pkg = __name__

    for sub in _SUBPACKAGES:
        target_dir = pkg_dir / sub if sub else pkg_dir
        if not target_dir.is_dir():
            continue

        for mod in pkgutil.iter_modules([str(target_dir)]):
            name = mod.name
            if name.startswith("_"):
                continue
            full = f"{base_pkg}.{name}" if not sub else f"{base_pkg}.{sub}.{name}"
            _import(full)

    logger.info(
        f"[GROUPS] loaded {len(_loaded)} modules "
        f"({len(_failed)} failed)"
    )


def loaded() -> List[str]:
    return list(_loaded)


def failed() -> List[str]:
    return list(_failed)


# Run on import — this is the entry point when Pyrogram loads plugins.
discover()


__all__ = ["discover", "loaded", "failed"]
