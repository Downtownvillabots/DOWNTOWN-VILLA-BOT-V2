# ============================================================
# 🎛️ DOWNTOWN VILLA — AI LIBRARIAN AUTO-DISCOVERY
# ============================================================
from __future__ import annotations
import importlib, logging, pkgutil
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)
_loaded: List[str] = []
_failed: List[str] = []


def discover() -> None:
    global _loaded, _failed
    _loaded.clear(); _failed.clear()
    pkg_dir = Path(__file__).parent
    for mod in pkgutil.iter_modules([str(pkg_dir)]):
        if mod.name.startswith("_"): continue
        full = f"{__package__}.{mod.name}"
        try:
            importlib.import_module(full)
            _loaded.append(mod.name)
        except Exception as e:
            logger.exception(f"[AI-LIB] failed: {full}: {e}")
            _failed.append(mod.name)
    logger.info(f"[AI-LIB] loaded {len(_loaded)} ({len(_failed)} failed)")


def loaded(): return list(_loaded)
def failed(): return list(_failed)


discover()
__all__ = ["discover", "loaded", "failed"]
