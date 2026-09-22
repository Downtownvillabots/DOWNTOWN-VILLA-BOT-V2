# ============================================================
# 🏨 DOWNTOWN VILLA — STEPS AUTO-DISCOVERY
# ============================================================
#
# Every file in this folder that contains a @register_step
# class gets auto-imported on boot.
#
# To add a new step:
#   1. Create core/steps/my_step.py
#   2. Add `class MyStep(BaseStep)` with @register_step
#   3. Restart bot — done.
#
# No changes needed in this file.
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
    """Import every .py module in this package."""
    global _loaded, _failed
    _loaded.clear()
    _failed.clear()

    pkg_dir = Path(__file__).parent

    for mod_info in pkgutil.iter_modules([str(pkg_dir)]):
        name = mod_info.name

        # Skip private / dunder files
        if name.startswith("_"):
            continue

        full_name = f"{__name__}.{name}"
        try:
            importlib.import_module(full_name)
            _loaded.append(name)
        except Exception as e:
            logger.exception(f"[STEPS] failed to import {full_name}: {e}")
            _failed.append(name)

    logger.info(
        f"[STEPS] Loaded {len(_loaded)} steps, "
        f"{len(_failed)} failed"
    )


def loaded_steps() -> List[str]:
    return list(_loaded)


def failed_steps() -> List[str]:
    return list(_failed)


# Auto-discover on package import
discover()


__all__ = [
    "discover",
    "loaded_steps",
    "failed_steps",
]
