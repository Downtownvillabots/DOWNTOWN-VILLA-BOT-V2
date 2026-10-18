# ============================================================
# 🏨 DOWNTOWN VILLA — CONFIG ENGINE (FUTURISTIC)
# ============================================================
#
# Single source of truth for every environment variable.
#
# Features (new in v2):
#   • ∞ database shards (system / user / media / backup)
#   • Auto-discovery: reads SYSTEM_DATABASE_01..99
#   • Falls back to legacy DATABASE_URI if no shards given
#   • Type-safe readers with defaults (int/bool/str/list)
#   • Live reload — settings can be re-read without restart
#   • Full config snapshot for admin panel
#   • Validation with friendly errors
#
# ============================================================

from __future__ import annotations

import os
import re
from typing import Any, Dict, List, Optional


# ============================================================
# SECTION 1 — SAFE READERS
# ============================================================

def env_str(name: str, default: str = "") -> str:
    v = os.getenv(name)
    if v is None:
        return default
    v = v.strip()
    return v if v else default


def env_int(name: str, default: int = 0) -> int:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return int(raw.strip())
    except (TypeError, ValueError):
        return default


def env_float(name: str, default: float = 0.0) -> float:
    raw = os.getenv(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw.strip())
    except (TypeError, ValueError):
        return default


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on", "y")


def env_list(name: str, sep: str = " ") -> List[str]:
    raw = os.getenv(name, "")
    if not raw:
        return []
    return [p.strip() for p in raw.replace(",", sep).split(sep) if p.strip()]


def env_ints(name: str, sep: str = " ") -> List[int]:
    out: List[int] = []
    for p in env_list(name, sep):
        try:
            out.append(int(p))
        except (TypeError, ValueError):
            continue
    return out


def env_id_list(name: str) -> List[int]:
    """Parse space/comma separated numeric IDs (with -100 prefix support)."""
    out: List[int] = []
    for p in env_list(name):
        clean = p.lstrip("-")
        if clean.isdigit():
            try:
                out.append(int(p))
            except (TypeError, ValueError):
                continue
    return out


# ============================================================
# SECTION 2 — SHARD DISCOVERY (∞)
# ============================================================

def _discover_shards(
    uri_prefix: str,
    name_prefix: str,
    max_shards: int = 99,
) -> List[Dict[str, Any]]:
    """
    Read SYSTEM_DATABASE_01..N + SYSTEM_DATABASE_NAME_01..N.
    Also accepts SYSTEM_DATABASE_1..N (no zero pad).
    Returns list of {uri, label, index}.
    """
    shards: List[Dict[str, Any]] = []

    for i in range(1, max_shards + 1):
        uri = (
            os.getenv(f"{uri_prefix}_{i:02d}")
            or os.getenv(f"{uri_prefix}_{i}")
        )
        if not uri:
            # Stop at first missing (contiguous convention)
            if i > 1:
                break
            continue

        label = (
            os.getenv(f"{name_prefix}_{i:02d}")
            or os.getenv(f"{name_prefix}_{i}")
            or f"{uri_prefix}-{i:02d}"
        )

        shards.append({
            "uri": uri.strip(),
            "label": label.strip(),
            "index": i,
        })

    return shards


def _fallback_from_legacy(legacy: str, label: str) -> List[Dict[str, Any]]:
    """If no shards configured, fall back to legacy DATABASE_URI."""
    if not legacy:
        return []
    return [{
        "uri": legacy.strip(),
        "label": label,
        "index": 1,
    }]


# ============================================================
# SECTION 3 — DATABASE CONFIG
# ============================================================

class DatabaseConfig:
    """Static DB config accessors."""

    # ────────── SYSTEM ──────────

    @staticmethod
    def system_shards() -> List[Dict[str, Any]]:
        shards = _discover_shards(
            "SYSTEM_DATABASE",
            "SYSTEM_DATABASE_NAME",
        )
        if shards:
            return shards
        return _fallback_from_legacy(
            env_str("DATABASE_URI"),
            env_str("SYSTEM_DATABASE_NAME_01", "SYSTEM-01"),
        )

    @staticmethod
    def system_db_name() -> str:
        return env_str("SYSTEM_DATABASE_DB", "downtown_villa_system")

    # ────────── USER ──────────

    @staticmethod
    def user_shards() -> List[Dict[str, Any]]:
        shards = _discover_shards(
            "USER_DATABASE",
            "USER_DATABASE_NAME",
        )
        if shards:
            return shards
        sys_shards = DatabaseConfig.system_shards()
        if sys_shards:
            return [{
                "uri": sys_shards[0]["uri"],
                "label": "USERS-01",
                "index": 1,
            }]
        return []

    @staticmethod
    def user_db_name() -> str:
        return env_str("USER_DATABASE_DB", "downtown_villa_user")

    # ────────── MEDIA ──────────

    @staticmethod
    def media_shards() -> List[Dict[str, Any]]:
        shards = _discover_shards(
            "MEDIA_DATABASE",
            "MEDIA_DATABASE_NAME",
        )
        if shards:
            return shards
        user_shards = DatabaseConfig.user_shards()
        if user_shards:
            return [{
                "uri": user_shards[0]["uri"],
                "label": "MEDIA-01",
                "index": 1,
            }]
        return []

    @staticmethod
    def media_db_name() -> str:
        return env_str("MEDIA_DATABASE_DB", "downtown_villa_media")

    # ────────── BACKUP (same ∞ pattern) ──────────

    @staticmethod
    def backup_shards() -> List[Dict[str, Any]]:
        shards = _discover_shards(
            "BACKUP_DATABASE",
            "BACKUP_DATABASE_NAME",
        )
        if shards:
            return shards
        # Fallback: use media shard 0 with a backup DB name
        media = DatabaseConfig.media_shards()
        if media:
            return [{
                "uri": media[0]["uri"],
                "label": "BACKUP-01",
                "index": 1,
            }]
        return []

    @staticmethod
    def backup_db_name() -> str:
        return env_str("BACKUP_DATABASE_DB", "downtown_villa_backup")


# ============================================================
# SECTION 4 — BOT CONFIG
# ============================================================

API_ID: int = env_int("API_ID", 0)
API_HASH: str = env_str("API_HASH", "")
BOT_TOKEN: str = env_str("BOT_TOKEN", "")
SESSION: str = env_str("SESSION", "downtown_villa")

ADMINS: List[int] = env_ints("ADMINS")
LOG_CHANNEL: int = env_int("LOG_CHANNEL", 0)
PORT: int = env_int("PORT", 8080)


# ============================================================
# SECTION 5 — CHANNELS
# ============================================================

DATABASE_CHANNEL_IDS: List[int] = (
    env_id_list("DATABASE_CHANNEL_IDS")
    or env_id_list("DATABASE_CHANNEL_ID")
)
DATABASE_CHANNEL_ID: Optional[int] = (
    DATABASE_CHANNEL_IDS[0] if DATABASE_CHANNEL_IDS else None
)

BACKUP_CHANNEL_ID: Optional[int] = (
    env_int("BACKUP_CHANNEL_ID", 0) or None
)
BACKUP_STORAGE_CHANNEL_ID: Optional[int] = (
    env_int("BACKUP_STORAGE_CHANNEL_ID", 0) or None
)

REQST_CHANNEL: Optional[int] = env_int("REQST_CHANNEL", 0) or None
BROADCAST_CHANNEL_ID: Optional[int] = env_int("BROADCAST_CHANNEL_ID", 0) or None
MOVIE_UPDATE_CHANNEL: Optional[int] = env_int("MOVIE_UPDATE_CHANNEL", 0) or None

AUTH_CHANNELS: List[int] = env_id_list("AUTH_CHANNELS")
AUTH_REQ_CHANNELS: List[int] = env_id_list("AUTH_REQ_CHANNELS")
SERIES_GROUP_ID: Optional[int] = env_int("SERIES_GROUP_ID", 0) or None


# ============================================================
# SECTION 6 — LINKS
# ============================================================

SUPPORT_CHAT: str = env_str("SUPPORT_CHAT", "https://t.me/")
SUPPORT_CHAT_ID: Optional[int] = env_int("SUPPORT_CHAT_ID", 0) or None

UPDATE_CHNL_LNK: str = env_str("UPDATE_CHNL_LNK", "https://t.me/")
OWNER_LNK: str = env_str("OWNER_LNK", "https://t.me/")
GRP_LNK: str = env_str("GRP_LNK", "https://t.me/")


# ============================================================
# SECTION 7 — FEATURE FLAGS
# ============================================================

FORCE_SUB_ENABLED: bool = env_bool("FORCE_SUB_ENABLED", False)
AUTO_DELETE_ENABLED: bool = env_bool("AUTO_DELETE_ENABLED", True)
AUTO_DELETE_MINUTES: int = env_int("AUTO_DELETE_MINUTES", 10)
AUTO_INDEXING_ENABLED: bool = env_bool("AUTO_INDEXING_ENABLED", True)
INDEXING_THRESHOLD_MB: int = env_int("INDEXING_THRESHOLD_MB", 400)

BACKUP_AUTO_START: bool = env_bool("BACKUP_AUTO_START", False)
BACKUP_WATCH_INTERVAL: int = env_int("BACKUP_WATCH_INTERVAL", 5)
BACKUP_UPLOAD_DELAY: float = env_float("BACKUP_UPLOAD_DELAY", 0.5)
BACKUP_MAX_RETRIES: int = env_int("BACKUP_MAX_RETRIES", 8)
BACKUP_RETRY_DELAY: int = env_int("BACKUP_RETRY_DELAY", 5)

MAINTENANCE_MODE: bool = env_bool("MAINTENANCE_MODE", False)
PM_SEARCH_ENABLED: bool = env_bool("PM_SEARCH_ENABLED", True)


# ============================================================
# SECTION 8 — METADATA
# ============================================================

TMDB_API_KEY: str = env_str("TMDB_API_KEY", "")
OMDB_API_KEY: str = env_str("OMDB_API_KEY", "")
METADATA_PROVIDER: str = env_str("METADATA_PROVIDER", "tmdb").lower()
METADATA_TIMEOUT: int = env_int("METADATA_TIMEOUT", 3)
METADATA_CACHE_TTL: int = env_int("METADATA_CACHE_TTL", 3600)


# ============================================================
# SECTION 9 — SEARCH TUNING
# ============================================================

SEARCH_PAGE_SIZE: int = env_int("SEARCH_PAGE_SIZE", 10)
MAX_SEARCH_RESULTS: int = env_int("MAX_SEARCH_RESULTS", 200)
SEARCH_CACHE_TTL: int = env_int("SEARCH_CACHE_TTL", 300)
SEARCH_SESSION_TTL: int = env_int("SEARCH_SESSION_TTL", 1800)
SHARD_TIMEOUT: int = env_int("SHARD_TIMEOUT", 6)
SHARD_CONCURRENCY: int = env_int("SHARD_CONCURRENCY", 10)

PREFERRED_QUALITY: str = env_str("PREFERRED_QUALITY", "1080p")
PREFERRED_CODEC: str = env_str("PREFERRED_CODEC", "HEVC")
PREFERRED_AUDIO: str = env_str("PREFERRED_AUDIO", "ENGLISH")
PREFERRED_SUBTITLE: str = env_str("PREFERRED_SUBTITLE", "ENGLISH")

SPELL_CHECK_THRESHOLD: int = env_int("SPELL_CHECK_THRESHOLD", 85)
SPELL_CHECK_CANDIDATES: int = env_int("SPELL_CHECK_CANDIDATES", 5)
MAX_LIST_ELM: int = env_int("MAX_LIST_ELM", 10)


# ============================================================
# SECTION 10 — CAPACITY
# ============================================================

DB_CAPACITY_MB: int = env_int("DB_CAPACITY_MB", 512)
ATLAS_API_PUBLIC_KEY: str = env_str("ATLAS_API_PUBLIC_KEY")
ATLAS_API_PRIVATE_KEY: str = env_str("ATLAS_API_PRIVATE_KEY")


def atlas_project_id(pool: str, index: int) -> str:
    """Return a per-shard Atlas project ID, falling back to the shared ID."""
    specific = env_str(f"ATLAS_PROJECT_ID_{pool.upper()}_{index:02d}")
    return specific or env_str("ATLAS_PROJECT_ID")


# ============================================================
# SECTION 11 — SNAPSHOT FOR ADMIN
# ============================================================

def snapshot() -> Dict[str, Any]:
    """Non-secret snapshot for admin panel."""
    return {
        "session": SESSION,
        "admins": len(ADMINS),
        "log_channel": LOG_CHANNEL,
        "database_channels": DATABASE_CHANNEL_IDS,
        "backup_channel": BACKUP_CHANNEL_ID,
        "storage_channel": BACKUP_STORAGE_CHANNEL_ID,
        "reqst_channel": REQST_CHANNEL,
        "broadcast_channel": BROADCAST_CHANNEL_ID,
        "movie_update_channel": MOVIE_UPDATE_CHANNEL,
        "auth_channels": AUTH_CHANNELS,
        "shards": {
            "system": len(DatabaseConfig.system_shards()),
            "user": len(DatabaseConfig.user_shards()),
            "media": len(DatabaseConfig.media_shards()),
            "backup": len(DatabaseConfig.backup_shards()),
        },
        "features": {
            "force_sub": FORCE_SUB_ENABLED,
            "auto_delete": AUTO_DELETE_ENABLED,
            "auto_index": AUTO_INDEXING_ENABLED,
            "backup_auto": BACKUP_AUTO_START,
            "pm_search": PM_SEARCH_ENABLED,
            "maintenance": MAINTENANCE_MODE,
        },
        "metadata_provider": METADATA_PROVIDER,
        "db_capacity_mb": DB_CAPACITY_MB,
    }


# ============================================================
# SECTION 12 — VALIDATION
# ============================================================

def validate() -> List[str]:
    """Return list of fatal config errors (empty = OK)."""
    errors: List[str] = []

    if not API_ID:
        errors.append("API_ID missing")
    if not API_HASH:
        errors.append("API_HASH missing")
    if not BOT_TOKEN:
        errors.append("BOT_TOKEN missing")
    if not ADMINS:
        errors.append("ADMINS missing")
    if not DatabaseConfig.system_shards():
        errors.append("No SYSTEM database configured")

    return errors


# ============================================================
# SECTION 13 — PUBLIC EXPORTS
# ============================================================

__all__ = [
    # Readers
    "env_str", "env_int", "env_float", "env_bool",
    "env_list", "env_ints", "env_id_list",
    # DB config
    "DatabaseConfig",
    # Bot
    "API_ID", "API_HASH", "BOT_TOKEN", "SESSION",
    "ADMINS", "LOG_CHANNEL", "PORT",
    # Channels
    "DATABASE_CHANNEL_IDS", "DATABASE_CHANNEL_ID",
    "BACKUP_CHANNEL_ID", "BACKUP_STORAGE_CHANNEL_ID",
    "REQST_CHANNEL", "BROADCAST_CHANNEL_ID", "MOVIE_UPDATE_CHANNEL",
    "AUTH_CHANNELS", "AUTH_REQ_CHANNELS", "SERIES_GROUP_ID",
    # Links
    "SUPPORT_CHAT", "SUPPORT_CHAT_ID",
    "UPDATE_CHNL_LNK", "OWNER_LNK", "GRP_LNK",
    # Flags
    "FORCE_SUB_ENABLED", "AUTO_DELETE_ENABLED", "AUTO_DELETE_MINUTES",
    "AUTO_INDEXING_ENABLED", "INDEXING_THRESHOLD_MB",
    "BACKUP_AUTO_START", "BACKUP_WATCH_INTERVAL",
    "BACKUP_UPLOAD_DELAY", "BACKUP_MAX_RETRIES", "BACKUP_RETRY_DELAY",
    "MAINTENANCE_MODE", "PM_SEARCH_ENABLED",
    # Metadata
    "TMDB_API_KEY", "OMDB_API_KEY", "METADATA_PROVIDER",
    "METADATA_TIMEOUT", "METADATA_CACHE_TTL",
    # Search
    "SEARCH_PAGE_SIZE", "MAX_SEARCH_RESULTS", "SEARCH_CACHE_TTL",
    "SEARCH_SESSION_TTL", "SHARD_TIMEOUT", "SHARD_CONCURRENCY",
    "PREFERRED_QUALITY", "PREFERRED_CODEC",
    "PREFERRED_AUDIO", "PREFERRED_SUBTITLE",
    "SPELL_CHECK_THRESHOLD", "SPELL_CHECK_CANDIDATES", "MAX_LIST_ELM",
    # Capacity
    "DB_CAPACITY_MB",
    # Helpers
    "snapshot", "validate",
]
