# ============================================================
# 🏨 DOWNTOWN VILLA — DATABASE CONNECTION ENGINE (FUTURISTIC) — A/2
# ============================================================
#
# Manages ∞ shards across 4 pools: SYSTEM / USER / MEDIA / BACKUP.
#
# NEW IN v2:
#   • Auto-rotation: when shard hits threshold → next shard
#   • Live per-shard stats (used MB, % full, doc count)
#   • Clear-shard operation (admin can wipe one shard)
#   • Delete-file operation (remove one file from any shard)
#   • Full health check across all pools
#   • Thresholds configurable per pool
#   • Safe async pool (Motor)
#
# Pools:
#   SYSTEM  → cache, bot state, sessions, flow configs
#   USER    → users, groups, channels, premium
#   MEDIA   → media files
#   BACKUP  → backup state, runs
#
# ============================================================

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from motor.motor_asyncio import AsyncIOMotorClient

from core import config
from core import rocket

logger = logging.getLogger(__name__)


# ============================================================
# SECTION 1 — POOL ENTRY
# ============================================================

@dataclass
class PoolEntry:
    """One shard = one Motor client + one database."""
    pool: str                # system | user | media | backup
    index: int               # 1-based
    label: str               # human-readable
    uri: str                 # mongodb uri
    db_name: str             # database inside cluster
    client: Optional[AsyncIOMotorClient] = None
    db: Any = None
    online: bool = False
    last_ping: float = 0.0
    last_ping_ms: float = 0.0
    error: str = ""

    # Cached stats (refreshed on demand)
    stats: Dict[str, Any] = field(default_factory=dict)

    def is_ready(self) -> bool:
        return self.online and self.db is not None


# ============================================================
# SECTION 2 — POOL CONFIG
# ============================================================

@dataclass
class PoolConfig:
    """Per-pool settings."""
    pool: str
    threshold_mb: int         # rotate when free storage < this
    db_name: str
    max_shards: int = 99


DEFAULT_THRESHOLDS = {
    "system": 100,
    "user": 200,
    "media": 400,
    "backup": 400,
}


def _pool_config(pool: str) -> PoolConfig:
    """Build pool config from env."""
    prefix = pool.upper()
    threshold = config.env_int(
        f"{prefix}_THRESHOLD_MB",
        DEFAULT_THRESHOLDS.get(pool, 400),
    )
    db_name = getattr(
        config.DatabaseConfig,
        f"{pool}_db_name",
        lambda: f"downtown_villa_{pool}",
    )()
    return PoolConfig(
        pool=pool,
        threshold_mb=max(50, threshold),
        db_name=db_name,
    )


# ============================================================
# SECTION 3 — CONNECTION MANAGER
# ============================================================

class DatabaseManager:
    """Manages all sharded pools."""

    def __init__(self) -> None:
        self.pools: Dict[str, List[PoolEntry]] = {
            "system": [],
            "user": [],
            "media": [],
            "backup": [],
        }
        self.initialized = False
        self.enabled = False

    # ────────── INITIALIZE ──────────

    async def initialize(self) -> None:
        if self.initialized:
            return

        logger.info("[DB] initializing shards...")

        # SYSTEM
        self.pools["system"] = self._build_pool(
            "system",
            config.DatabaseConfig.system_shards(),
            config.DatabaseConfig.system_db_name(),
        )

        # USER (fallback to system if empty)
        self.pools["user"] = self._build_pool(
            "user",
            config.DatabaseConfig.user_shards()
                or config.DatabaseConfig.system_shards(),
            config.DatabaseConfig.user_db_name(),
        )

        # MEDIA (fallback to user if empty)
        self.pools["media"] = self._build_pool(
            "media",
            config.DatabaseConfig.media_shards()
                or config.DatabaseConfig.user_shards(),
            config.DatabaseConfig.media_db_name(),
        )

        # BACKUP (fallback to media if empty)
        self.pools["backup"] = self._build_pool(
            "backup",
            config.DatabaseConfig.backup_shards()
                or config.DatabaseConfig.media_shards(),
            config.DatabaseConfig.backup_db_name(),
        )

        # Connect all
        await self._connect_all()

        total = sum(len(p) for p in self.pools.values())
        self.enabled = total > 0
        self.initialized = True

        logger.info(
            f"[DB] shards ready — "
            f"system={len(self.pools['system'])} "
            f"user={len(self.pools['user'])} "
            f"media={len(self.pools['media'])} "
            f"backup={len(self.pools['backup'])}"
        )

    def _build_pool(
        self,
        pool: str,
        shard_cfgs: List[Dict[str, Any]],
        db_name: str,
    ) -> List[PoolEntry]:
        entries: List[PoolEntry] = []
        for cfg in shard_cfgs:
            entries.append(PoolEntry(
                pool=pool,
                index=int(cfg.get("index", 1)),
                label=str(cfg.get("label", f"{pool}-{len(entries)+1:02d}")),
                uri=str(cfg.get("uri", "")),
                db_name=db_name,
            ))
        return entries

    async def _connect_all(self) -> None:
        for pool_name, entries in self.pools.items():
            for entry in entries:
                await self._connect_one(entry)

    async def _connect_one(self, entry: PoolEntry) -> bool:
        if not entry.uri:
            entry.error = "no uri"
            return False
        try:
            client = AsyncIOMotorClient(
                entry.uri,
                serverSelectionTimeoutMS=8000,
                connectTimeoutMS=8000,
                socketTimeoutMS=20000,
                maxPoolSize=50,
            )
            db = client[entry.db_name]
            # Ping
            t0 = time.perf_counter()
            await db.command("ping")
            elapsed = (time.perf_counter() - t0) * 1000.0

            entry.client = client
            entry.db = db
            entry.online = True
            entry.last_ping = time.time()
            entry.last_ping_ms = round(elapsed, 2)
            entry.error = ""

            logger.info(
                f"[DB] {entry.pool.upper():6} #{entry.index:02d} "
                f"→ {entry.label} ({entry.last_ping_ms:.0f}ms)"
            )
            return True
        except Exception as e:
            entry.online = False
            entry.error = str(e)[:200]
            logger.warning(
                f"[DB] {entry.pool.upper()} #{entry.index} "
                f"connect failed: {e}"
            )
            return False

    # ────────── ACCESSORS ──────────

    def get(self, pool: str, index: int) -> Optional[PoolEntry]:
        for e in self.pools.get(pool, []):
            if e.index == index:
                return e
        return None

    def entries(self, pool: str) -> List[PoolEntry]:
        return list(self.pools.get(pool, []))

    def online(self, pool: str) -> List[PoolEntry]:
        return [e for e in self.pools.get(pool, []) if e.is_ready()]

    def primary(self, pool: str) -> Optional[PoolEntry]:
        """Return first online shard (or None)."""
        for e in self.pools.get(pool, []):
            if e.is_ready():
                return e
        return None

    def all_entries(self) -> List[PoolEntry]:
        out: List[PoolEntry] = []
        for p in self.pools.values():
            out.extend(p)
        return out

    # ────────── ROTATION ──────────
    #
    # Auto-rotation: when a shard's used storage > threshold, we
    # move to the next shard in the same pool.
    #
    # We cache stats for 60s to avoid hammering Mongo.
    #

    async def pick_shard(self, pool: str) -> Optional[PoolEntry]:
        """Return the next healthy shard for writing."""
        entries = self.pools.get(pool, [])
        if not entries:
            return None

        cfg = _pool_config(pool)

        for entry in entries:
            if not entry.is_ready():
                continue
            used_mb = await self._used_mb(entry)
            if used_mb is None:
                continue
            if used_mb < cfg.threshold_mb:
                return entry

        # All full → return last online anyway (with warning)
        for entry in reversed(entries):
            if entry.is_ready():
                logger.warning(
                    f"[DB] all {pool} shards over "
                    f"{cfg.threshold_mb}MB — using last"
                )
                return entry
        return None

    async def _used_mb(self, entry: PoolEntry) -> Optional[float]:
        """Return used storage in MB (cached 60s)."""
        now = time.time()
        cached = entry.stats.get("used_mb_at", 0)
        if now - cached < 60 and "used_mb" in entry.stats:
            return entry.stats["used_mb"]

        try:
            stats = await entry.db.command("dbStats")
            used = (stats.get("storageSize", 0) or 0) + (
                stats.get("indexSize", 0) or 0
            )
            used_mb = used / (1024 * 1024)
            entry.stats["used_mb"] = used_mb
            entry.stats["used_mb_at"] = now
            entry.stats["data_size"] = stats.get("dataSize", 0)
            entry.stats["storage_size"] = stats.get("storageSize", 0)
            entry.stats["index_size"] = stats.get("indexSize", 0)
            entry.stats["collections"] = stats.get("collections", 0)
            entry.stats["objects"] = stats.get("objects", 0)
            return used_mb
        except Exception as e:
            logger.debug(f"[DB] stats {entry.pool}/{entry.index}: {e}")
            return None

    # ────────── HEALTH ──────────

    async def health(self) -> Dict[str, Any]:
        """Full health check across all pools."""
        out: Dict[str, Any] = {}
        for pool_name in self.pools.keys():
            pool_out: List[Dict[str, Any]] = []
            for entry in self.pools[pool_name]:
                info = {
                    "index": entry.index,
                    "label": entry.label,
                    "online": entry.online,
                    "ping_ms": entry.last_ping_ms,
                    "error": entry.error,
                }
                if entry.online:
                    used_mb = await self._used_mb(entry)
                    info["used_mb"] = round(used_mb or 0, 2)
                pool_out.append(info)
            out[pool_name] = pool_out
        return out

    # ────────── CLEAR SHARD ──────────

    async def clear_shard(self, pool: str, index: int) -> Dict[str, Any]:
        """
        Delete EVERYTHING from one shard (all collections).
        Returns per-collection stats.
        """
        entry = self.get(pool, index)
        if entry is None or not entry.is_ready():
            return {"ok": False, "reason": "shard offline or not found"}

        result = {
            "ok": True,
            "pool": pool,
            "index": index,
            "label": entry.label,
            "collections_cleared": 0,
            "documents_deleted": 0,
            "errors": [],
        }

        try:
            names = await entry.db.list_collection_names()
        except Exception as e:
            return {"ok": False, "reason": f"list failed: {e}"}

        for name in names:
            try:
                r = await entry.db[name].delete_many({})
                result["documents_deleted"] += r.deleted_count
                result["collections_cleared"] += 1
            except Exception as e:
                result["errors"].append(f"{name}: {e}")

        # Invalidate cached stats
        entry.stats.pop("used_mb", None)
        entry.stats.pop("used_mb_at", None)

        logger.warning(
            f"[DB] cleared {pool}/{index} — "
            f"{result['documents_deleted']} docs in "
            f"{result['collections_cleared']} collections"
        )
        return result

    # ────────── CLEAR ALL POOL ──────────

    async def clear_pool(self, pool: str) -> Dict[str, Any]:
        """Clear every shard in a pool."""
        result = {
            "pool": pool,
            "shards": [],
            "total_deleted": 0,
        }
        for entry in self.pools.get(pool, []):
            r = await self.clear_shard(pool, entry.index)
            result["shards"].append(r)
            result["total_deleted"] += r.get("documents_deleted", 0)
        return result

    # ────────── DELETE FILE ──────────

    async def delete_document(
        self,
        pool: str,
        index: int,
        collection: str,
        query: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Delete one document from a specific shard.
        Query example: {"file_id": "BQAC..."}
        """
        entry = self.get(pool, index)
        if entry is None or not entry.is_ready():
            return {"ok": False, "reason": "shard offline"}

        try:
            r = await entry.db[collection].delete_many(query)
            return {
                "ok": True,
                "deleted": r.deleted_count,
                "pool": pool,
                "index": index,
                "collection": collection,
            }
        except Exception as e:
            return {"ok": False, "reason": str(e)}

    async def delete_across_shards(
        self,
        pool: str,
        collection: str,
        query: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Delete a document from every shard in a pool.
        Useful when you don't know which shard holds a file.
        """
        total = 0
        per_shard = []
        for entry in self.pools.get(pool, []):
            if not entry.is_ready():
                continue
            try:
                r = await entry.db[collection].delete_many(query)
                if r.deleted_count:
                    per_shard.append({
                        "index": entry.index,
                        "label": entry.label,
                        "deleted": r.deleted_count,
                    })
                    total += r.deleted_count
            except Exception:
                continue
        return {
            "ok": total > 0,
            "total": total,
            "per_shard": per_shard,
        }

    # ────────── LIVE SNAPSHOT ──────────

    async def snapshot(self) -> Dict[str, Any]:
        """Full snapshot for admin dashboard."""
        out: Dict[str, Any] = {"pools": {}}
        for pool_name, entries in self.pools.items():
            pool_info = {
                "total": len(entries),
                "online": sum(1 for e in entries if e.online),
                "shards": [],
                "total_used_mb": 0.0,
                "total_docs": 0,
                "total_collections": 0,
            }
            cfg = _pool_config(pool_name)
            for entry in entries:
                shard = {
                    "index": entry.index,
                    "label": entry.label,
                    "online": entry.online,
                    "ping_ms": entry.last_ping_ms,
                    "threshold_mb": cfg.threshold_mb,
                }
                if entry.online:
                    used = await self._used_mb(entry)
                    shard["used_mb"] = round(used or 0, 2)
                    shard["pct"] = round(
                        ((used or 0) / cfg.threshold_mb) * 100, 1
                    )
                    shard["docs"] = entry.stats.get("objects", 0)
                    shard["collections"] = entry.stats.get("collections", 0)
                    pool_info["total_used_mb"] += used or 0
                    pool_info["total_docs"] += shard["docs"]
                    pool_info["total_collections"] += shard["collections"]
                pool_info["shards"].append(shard)
            pool_info["total_used_mb"] = round(pool_info["total_used_mb"], 2)
            out["pools"][pool_name] = pool_info
        return out

    # ────────── SHUTDOWN ──────────

    async def close(self) -> None:
        for entries in self.pools.values():
            for entry in entries:
                if entry.client:
                    try:
                        entry.client.close()
                    except Exception:
                        pass
        logger.info("[DB] all shard connections closed")


# ============================================================
# SECTION 4 — SINGLETON
# ============================================================

db_manager = DatabaseManager()


# ============================================================
# SECTION 5 — PUBLIC EXPORTS
# ============================================================

__all__ = [
    "PoolEntry",
    "PoolConfig",
    "DatabaseManager",
    "db_manager",
    "_pool_config",
]

# ============================================================
# 🏨 DOWNTOWN VILLA — DATABASE CONNECTION ENGINE — B/2 (FINAL)
# ============================================================
#
# This part adds:
#   • DatabaseRegistry wrapper (clean public API)
#   • db_registry singleton
#   • Collection helpers per pool
#   • Async iterator over online shards
#   • Stats refresh orchestration
#
# Every other module in the bot imports:
#   from database import db_manager, db_registry
#
# And uses:
#   db = db_registry.get_system_db()
#   shard = await db_registry.pick_media_shard()
#   all_media = db_registry.media_entries()
#
# ============================================================



import asyncio
import logging
from typing import Any, AsyncIterator, Dict, List, Optional

from database.connection import (
    DatabaseManager, PoolEntry, db_manager,
)

logger = logging.getLogger(__name__)


# ============================================================
# SECTION 1 — REGISTRY
# ============================================================

class DatabaseRegistry:
    """
    Thin, safe wrapper around DatabaseManager.

    Provides:
      • Per-pool entry lists
      • Per-pool primary db handles
      • Per-index shard lookups
      • Collection shortcuts
      • Rotation helpers
    """

    def __init__(self, manager: DatabaseManager) -> None:
        self._manager = manager

    # ────────── POOLS ──────────

    def system_entries(self) -> List[PoolEntry]:
        return self._manager.entries("system")

    def user_entries(self) -> List[PoolEntry]:
        return self._manager.entries("user")

    def media_entries(self) -> List[PoolEntry]:
        return self._manager.entries("media")

    def backup_entries(self) -> List[PoolEntry]:
        return self._manager.entries("backup")

    def all_entries(self) -> List[PoolEntry]:
        return self._manager.all_entries()

    # ────────── PRIMARY DB (first online) ──────────

    def get_system_db(self) -> Optional[Any]:
        e = self._manager.primary("system")
        return e.db if e else None

    def get_user_db(self) -> Optional[Any]:
        e = self._manager.primary("user")
        return e.db if e else None

    def get_media_db(self, index: int = 0) -> Optional[Any]:
        """Return media shard by index (0-based for compat)."""
        entries = self.media_entries()
        if not entries:
            return None
        if 0 <= index < len(entries):
            return entries[index].db
        return entries[0].db if entries else None

    def get_backup_db(self, index: int = 0) -> Optional[Any]:
        """Return backup shard by index (0-based)."""
        entries = self.backup_entries()
        if not entries:
            return None
        if 0 <= index < len(entries):
            return entries[index].db
        return entries[0].db if entries else None

    # ────────── CATALOG (metadata/catalog DB) ──────────
    # The catalog lives in the user pool by convention.

    def get_catalog_db(self) -> Optional[Any]:
        return self.get_user_db()

    # ────────── COUNTS ──────────

    def get_media_shard_count(self) -> int:
        return len(self.media_entries())

    def get_user_shard_count(self) -> int:
        return len(self.user_entries())

    def get_system_shard_count(self) -> int:
        return len(self.system_entries())

    def get_backup_shard_count(self) -> int:
        return len(self.backup_entries())

    # ────────── ROTATION ──────────

    async def pick_media_shard(self) -> Optional[PoolEntry]:
        """Return the next media shard for writing."""
        return await self._manager.pick_shard("media")

    async def pick_backup_shard(self) -> Optional[PoolEntry]:
        return await self._manager.pick_shard("backup")

    async def pick_system_shard(self) -> Optional[PoolEntry]:
        return await self._manager.pick_shard("system")

    async def pick_user_shard(self) -> Optional[PoolEntry]:
        return await self._manager.pick_shard("user")

    # ────────── COLLECTION HELPERS ──────────

    def system_collection(self, name: str):
        db = self.get_system_db()
        return db[name] if db is not None else None

    def user_collection(self, name: str):
        db = self.get_user_db()
        return db[name] if db is not None else None

    def catalog_collection(self, name: str):
        db = self.get_catalog_db()
        return db[name] if db is not None else None

    def media_collection(self, name: str = "media_files", index: int = 0):
        db = self.get_media_db(index)
        return db[name] if db is not None else None

    def backup_collection(self, name: str, index: int = 0):
        db = self.get_backup_db(index)
        return db[name] if db is not None else None

    # ────────── ASYNC ITERATORS ──────────

    async def iter_media_shards(self) -> AsyncIterator[PoolEntry]:
        """Yield every online media shard."""
        for e in self.media_entries():
            if e.is_ready():
                yield e

    async def iter_backup_shards(self) -> AsyncIterator[PoolEntry]:
        for e in self.backup_entries():
            if e.is_ready():
                yield e

    async def iter_user_shards(self) -> AsyncIterator[PoolEntry]:
        for e in self.user_entries():
            if e.is_ready():
                yield e

    # ────────── HEALTH ──────────

    async def health(self) -> Dict[str, Any]:
        return await self._manager.health()

    async def snapshot(self) -> Dict[str, Any]:
        return await self._manager.snapshot()

    # ────────── CLEAR / DELETE ──────────

    async def clear_shard(self, pool: str, index: int) -> Dict[str, Any]:
        return await self._manager.clear_shard(pool, index)

    async def clear_pool(self, pool: str) -> Dict[str, Any]:
        return await self._manager.clear_pool(pool)

    async def delete_document(
        self,
        pool: str,
        index: int,
        collection: str,
        query: Dict[str, Any],
    ) -> Dict[str, Any]:
        return await self._manager.delete_document(
            pool, index, collection, query
        )

    async def delete_across_shards(
        self,
        pool: str,
        collection: str,
        query: Dict[str, Any],
    ) -> Dict[str, Any]:
        return await self._manager.delete_across_shards(
            pool, collection, query
        )

    # ────────── BOOT ──────────

    async def initialize(self) -> None:
        await self._manager.initialize()

    async def close(self) -> None:
        await self._manager.close()

    @property
    def enabled(self) -> bool:
        return self._manager.enabled


# ============================================================
# SECTION 2 — SINGLETON
# ============================================================

db_registry = DatabaseRegistry(db_manager)


# ============================================================
# SECTION 3 — SHORTCUT HELPERS (module-level)
# ============================================================

def get_system_db():
    return db_registry.get_system_db()


def get_user_db():
    return db_registry.get_user_db()


def get_catalog_db():
    return db_registry.get_catalog_db()


def get_media_db(index: int = 0):
    return db_registry.get_media_db(index)


def get_backup_db(index: int = 0):
    return db_registry.get_backup_db(index)


def media_entry_count() -> int:
    return db_registry.get_media_shard_count()


def backup_entry_count() -> int:
    return db_registry.get_backup_shard_count()


async def pick_media_shard() -> Optional[PoolEntry]:
    return await db_registry.pick_media_shard()


async def pick_backup_shard() -> Optional[PoolEntry]:
    return await db_registry.pick_backup_shard()


# ============================================================
# SECTION 4 — BOOT / SHUTDOWN HELPERS
# ============================================================

async def boot_database() -> bool:
    """Initialize the DB layer with timing + logging."""
    from core import rocket

    with rocket.timer("db.boot"):
        try:
            await db_registry.initialize()
        except Exception as e:
            logger.exception(f"[DB] boot failed: {e}")
            return False

    if not db_registry.enabled:
        logger.error("[DB] no shards available — DB features disabled")
        return False

    logger.info(
        f"[DB] ✅ ready — "
        f"system={db_registry.get_system_shard_count()} "
        f"user={db_registry.get_user_shard_count()} "
        f"media={db_registry.get_media_shard_count()} "
        f"backup={db_registry.get_backup_shard_count()}"
    )
    return True


async def shutdown_database() -> None:
    try:
        await db_registry.close()
    except Exception as e:
        logger.warning(f"[DB] shutdown: {e}")


# ============================================================
# SECTION 5 — __init__.py CONTENT
# ============================================================
#
# NOTE: This is the content that goes in database/__init__.py
# so that other modules can do:
#
#     from database import db_manager, db_registry
#
# Just paste this block into database/__init__.py

DATABASE_INIT_CONTENT = '''
from database.connection import db_manager, DatabaseManager
from database.connection import DatabaseRegistry, db_registry
from database.config import DatabaseConfig

__all__ = [
    "db_manager",
    "DatabaseManager",
    "DatabaseRegistry",
    "db_registry",
    "DatabaseConfig",
]
'''


# ============================================================
# SECTION 6 — SNAPSHOT
# ============================================================

async def snapshot() -> Dict[str, Any]:
    return await db_registry.snapshot()


# ============================================================
# SECTION 7 — PUBLIC EXPORTS
# ============================================================

__all__ = [
    # Registry
    "DatabaseRegistry",
    "db_registry",
    # Shortcut helpers
    "get_system_db",
    "get_user_db",
    "get_catalog_db",
    "get_media_db",
    "get_backup_db",
    "media_entry_count",
    "backup_entry_count",
    "pick_media_shard",
    "pick_backup_shard",
    # Boot
    "boot_database",
    "shutdown_database",
    # Snapshot
    "snapshot",
    # Init content (paste into __init__.py)
    "DATABASE_INIT_CONTENT",
]


# ============================================================
# END OF database/connection.py — B/2 — FINAL
# ============================================================
