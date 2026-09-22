# ============================================================
# 🏨 DOWNTOWN VILLA — REQUESTS AUTO-DISCOVERY
# ============================================================

from __future__ import annotations
import importlib, logging, pkgutil
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)
_loaded: List[str] = []
_failed: List[str] = []

_PKG = __name__[:-9] if __name__.endswith(".__init__") else __name__
_done = False


def discover() -> None:
    global _loaded, _failed, _done
    if _done: return
    _done = True
    _loaded.clear(); _failed.clear()
    pkg_dir = Path(__file__).parent
    for mod in pkgutil.iter_modules([str(pkg_dir)]):
        if mod.name.startswith("_"): continue
        full = f"{_PKG}.{mod.name}"
        try:
            importlib.import_module(full)
            _loaded.append(mod.name)
        except Exception as e:
            logger.exception(f"[REQUESTS] failed: {full}: {e}")
            _failed.append(mod.name)
    logger.info(f"[REQUESTS] loaded {len(_loaded)} ({len(_failed)} failed)")


def loaded(): return list(_loaded)
def failed(): return list(_failed)

if __name__ == _PKG: discover()
__all__ = ["discover", "loaded", "failed"]
