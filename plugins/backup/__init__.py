# ============================================================
# 🏨 DOWNTOWN VILLA — BACKUP PLUGIN AUTO-DISCOVERY
# ============================================================
#
# Imports every .py in this package.
# Each module registers its own handlers.
#
# To add a new backup module:
#   1. Drop a .py file here
#   2. Restart bot
#   3. Done.
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


def discover() -> None:
    """Import every module in this package."""
    global _loaded, _failed
    _loaded.clear()
    _failed.clear()

    pkg_dir = Path(__file__).parent

    for mod in pkgutil.iter_modules([str(pkg_dir)]):
        name = mod.name
        if name.startswith("_"):
            continue
        full = f"{__name__}.{name}"
        try:
            importlib.import_module(full)
            _loaded.append(name)
        except Exception as e:
            logger.exception(f"[BACKUP] failed to import {full}: {e}")
            _failed.append(name)

    logger.info(
        f"[BACKUP] loaded {len(_loaded)} modules, "
        f"{len(_failed)} failed"
    )


def loaded() -> List[str]:
    return list(_loaded)


def failed() -> List[str]:
    return list(_failed)


# Auto-discover
discover()


__all__ = ["discover", "loaded", "failed"]
