# ============================================================
# 🏨 DOWNTOWN VILLA — ENTRY POINT
# ============================================================
#
# Runs first. Nothing else runs before this.
#
# Boot order:
#   1. Rocket (uvloop + orjson) — must be FIRST
#   2. Logging
#   3. Exception hooks
#   4. Bot startup
#
# ============================================================

from __future__ import annotations

import sys


# ============================================================
# STEP 1 — ROCKET (uvloop + orjson)
# ============================================================
# Must run BEFORE any other import that touches asyncio.

try:
    from core import rocket
    rocket.install()
except Exception as e:
    sys.stderr.write(f"[BOOT] rocket.install failed: {e}\n")


# ============================================================
# STEP 2 — LOGGING
# ============================================================
try:
    from core import logger as CORE_LOGGER
    CORE_LOGGER.setup(
        level="INFO",
        show_banner=True,
        quiet_libs=True,
    )
    CORE_LOGGER.install_exception_hooks()
except Exception as e:
    sys.stderr.write(f"[BOOT] logging setup failed: {e}\n")


# ============================================================
# STEP 3 — STARTUP
# ============================================================

from core.startup import run  # noqa: E402


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        sys.stderr.write("\n[BOOT] interrupted by user\n")
    except Exception as e:
        sys.stderr.write(f"[BOOT] fatal: {e}\n")
        import traceback
        traceback.print_exc()
        sys.exit(1)
