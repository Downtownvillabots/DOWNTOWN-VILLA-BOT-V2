# ============================================================
# 🏨 DOWNTOWN VILLA — DATABASE PACKAGE
# ============================================================
#
# Public API for the entire bot:
#
#   from database import db_manager, db_registry
#
# ============================================================

from database.connection import (
    DatabaseManager,
    PoolEntry,
    db_manager,
)
from database.connection import (
    DatabaseRegistry,
    db_registry,
)
from database.config import DatabaseConfig


__all__ = [
    "DatabaseManager",
    "DatabaseRegistry",
    "PoolEntry",
    "DatabaseConfig",
    "db_manager",
    "db_registry",
]
