# ============================================================
# 🏨 DOWNTOWN VILLA — OTT AUTO-DISCOVERY
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


# ── PRELOAD: modules that are imported by other submodules ──
# Must load BEFORE discover() to avoid circular-import errors
# (e.g. views.py does `from plugins.ott import progress`).
_PRELOAD = (
    "progress",   # used by views.py
    "config",     # used by nearly everything
    "database",   # used by tmdb, events, etc.
    "state",      # used by panel, channel_flow
)

for _name in _PRELOAD:
    try:
        importlib.import_module(f"{__package__}.{_name}")
    except Exception as _e:
        logger.warning(f"[OTT] preload {_name} failed: {_e}")


def discover() -> None:
    global _loaded, _failed
    _loaded.clear()
    _failed.clear()

    pkg_dir = Path(__file__).parent

    for mod in pkgutil.iter_modules([str(pkg_dir)]):
        name = mod.name
        if name.startswith("_"):
            continue
        if name in _PRELOAD:
            # already loaded above
            _loaded.append(name)
            continue
        full = f"{__package__}.{name}"
        try:
            importlib.import_module(full)
            _loaded.append(name)
        except Exception as e:
            logger.exception(f"[OTT] failed: {full}: {e}")
            _failed.append(name)

    logger.info(
        f"[OTT] loaded {len(_loaded)} modules ({len(_failed)} failed)"
    )


def loaded() -> List[str]:
    return list(_loaded)


def failed() -> List[str]:
    return list(_failed)


discover()

__all__ = ["discover", "loaded", "failed"]
