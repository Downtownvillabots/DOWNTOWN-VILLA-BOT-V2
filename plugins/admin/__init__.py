# ============================================================
# 🏨 DOWNTOWN VILLA — ADMIN CONTROL CENTER
# ============================================================
#
# Auto-discovers every submodule in plugins/admin/.
# Each file self-registers via @Client.on_message / @Client.on_callback_query.
#
# To add a new admin module:
#   1. Drop a .py file here with handlers
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
    """Import every .py module in this package (except __init__)."""
    global _loaded, _failed
    _loaded.clear()
    _failed.clear()

    pkg_dir = Path(__file__).parent

    for mod_info in pkgutil.iter_modules([str(pkg_dir)]):
        name = mod_info.name
        if name.startswith("_"):
            continue

        full = f"{__package__}.{name}"
        try:
            importlib.import_module(full)
            _loaded.append(name)
        except Exception as e:
            logger.exception(f"[ADMIN] failed: {full}: {e}")
            _failed.append(name)

    logger.info(
        f"[ADMIN] loaded {len(_loaded)} modules "
        f"({len(_failed)} failed)"
    )


def loaded() -> List[str]:
    return list(_loaded)


def failed() -> List[str]:
    return list(_failed)


discover()


__all__ = ["discover", "loaded", "failed"]
