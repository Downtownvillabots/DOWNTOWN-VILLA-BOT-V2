# ============================================================
# 🏨 DOWNTOWN VILLA — OTT CONFIG
# ============================================================

from __future__ import annotations
import os
from typing import List

# ── Reuse broadcast fonts/helpers for consistency ──
from plugins.broadcast.config import (
    fb, sc, _esc, _fmt_int, _fmt_size, _fmt_duration,
    _progress_colored, DIV, DIV2, _is_admin,
)

# ── File checker windows (IST) ──
CHECK_WINDOWS = [(23, 6), (12, 18)]
CHECK_INTERVAL_SEC = 3600          # every 1 hour
FILE_CHECK_LIMIT = 100             # only latest 100 files

# ── Weekly post ──
WEEKLY_DAY = 0                     # Monday
WEEKLY_HOUR = 10                   # 10 AM IST
WEEKLY_MINUTE_WINDOW = 5           # fire once within first 5 min

# ── Hype loop ──
HYPE_HOUR = 20                     # 8 PM IST

# ── Auto-delete ──
PENDING_SCAN_INTERVAL = 60

# ── TTLs ──
SESSION_TTL = 900
CONFIRM_TTL = 300
JOB_TTL = 3600

# ── Regions ──
REGIONS = ["IN", "US", "GB", "AE", "SA", "AU", "CA", "SG", "MY"]

# ── Languages (ISO 639-1) ──
LANGUAGE_LABELS = {
    "ml": "Malayalam", "hi": "Hindi", "en": "English",
    "ta": "Tamil", "te": "Telugu", "kn": "Kannada",
    "bn": "Bengali", "mr": "Marathi", "pa": "Punjabi",
    "gu": "Gujarati", "ur": "Urdu", "ko": "Korean",
    "ja": "Japanese", "zh": "Chinese", "es": "Spanish",
    "fr": "French", "de": "German", "ar": "Arabic",
    "tr": "Turkish", "th": "Thai",
}
DEFAULT_LANGS = ["ml", "hi", "en", "ta", "te"]

# ── Min vote count presets ──
MIN_VOTE_PRESETS = [5, 10, 20, 50]

# ── Notify TTL presets (hours) ──
NOTIFY_TTL_PRESETS = [1, 6, 12, 24, 48]

# ── Broadcast TTL presets (hours) ──
BROADCAST_TTL_PRESETS = [1, 6, 12, 24, 72, 168]

# ── Default settings ──
DEFAULT_SETTINGS = {
    "region": "IN",
    "languages": DEFAULT_LANGS,
    "min_vote_count": 5,
    "notify_ttl_hours": 12,
    "broadcast_ttl_hours": 24,
    "share_button": True,
    "notify_button": True,
    "weekly_enabled": True,
    "hype_enabled": True,
    "trending_enabled": True,
    "spotlight_enabled": True,
    "auto_delete_broadcast": True,
    "primary_channel": 0,
    "weekly_target_admin": 0,      # 0 = all ADMINS
}

PREFIX = "ott"
