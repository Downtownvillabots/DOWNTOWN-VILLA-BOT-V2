# ============================================================
# 🏨 DOWNTOWN VILLA — DATABASE CONFIG
# ============================================================
#
# Reads shard configurations from env.
# Supports ∞ shards per pool.
#
# Env pattern:
#   SYSTEM_DATABASE_01=mongodb+srv://...
#   SYSTEM_DATABASE_NAME_01=SYSTEM-01
#   SYSTEM_DATABASE_DB=downtown_villa_system
#
# Same for USER_* / MEDIA_* / BACKUP_*
#
# ============================================================

from __future__ import annotations

import os
from typing import Any, Dict, List


def _read_shards(uri_prefix: str, name_prefix: str) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for i in range(1, 100):
        uri = (
            os.getenv(f"{uri_prefix}_{i:02d}")
            or os.getenv(f"{uri_prefix}_{i}")
        )
        if not uri:
            if i > 1:
                break
            continue
        label = (
            os.getenv(f"{name_prefix}_{i:02d}")
            or os.getenv(f"{name_prefix}_{i}")
            or f"{uri_prefix}-{i:02d}"
        )
        out.append({
            "uri": uri.strip(),
            "label": label.strip(),
            "index": i,
        })
    return out


class DatabaseConfig:
    """Static DB config reader."""

    # ────────── SYSTEM ──────────

    @staticmethod
    def system_shards() -> List[Dict[str, Any]]:
        shards = _read_shards("SYSTEM_DATABASE", "SYSTEM_DATABASE_NAME")
        if shards:
            return shards
        legacy = os.getenv("DATABASE_URI", "").strip()
        if legacy:
            return [{
                "uri": legacy,
                "label": "SYSTEM-01",
                "index": 1,
            }]
        return []

    @staticmethod
    def system_db_name() -> str:
        return os.getenv("SYSTEM_DATABASE_DB", "downtown_villa_system")

    # ────────── USER ──────────

    @staticmethod
    def user_shards() -> List[Dict[str, Any]]:
        shards = _read_shards("USER_DATABASE", "USER_DATABASE_NAME")
        if shards:
            return shards
        # fallback: reuse system
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
        return os.getenv("USER_DATABASE_DB", "downtown_villa_user")

    # ────────── MEDIA ──────────

    @staticmethod
    def media_shards() -> List[Dict[str, Any]]:
        shards = _read_shards("MEDIA_DATABASE", "MEDIA_DATABASE_NAME")
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
        return os.getenv("MEDIA_DATABASE_DB", "downtown_villa_media")

    # ────────── BACKUP ──────────

    @staticmethod
    def backup_shards() -> List[Dict[str, Any]]:
        shards = _read_shards("BACKUP_DATABASE", "BACKUP_DATABASE_NAME")
        if shards:
            return shards
        # fallback: reuse media
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
        return os.getenv("BACKUP_DATABASE_DB", "downtown_villa_backup")


__all__ = ["DatabaseConfig"]
