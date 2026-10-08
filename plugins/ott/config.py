# ============================================================
# 🏨 DOWNTOWN VILLA — OTT CONFIG
# ============================================================

from __future__ import annotations

from plugins.broadcast.config import (
    fb, sc, _esc, _fmt_int, _fmt_size, _fmt_duration,
    _progress_colored, DIV, DIV2, _is_admin,
)

# ── File checker windows ──
CHECK_WINDOWS = [(23, 6), (12, 18)]
CHECK_INTERVAL_SEC = 3600
FILE_CHECK_LIMIT = 100

# ── Weekly post ──
WEEKLY_DAY = 0
WEEKLY_HOUR = 10
WEEKLY_MINUTE_WINDOW = 5

HYPE_HOUR = 20
PENDING_SCAN_INTERVAL = 60

# ── TTLs ──
SESSION_TTL = 900
CONFIRM_TTL = 300
JOB_TTL = 3600
SETUP_TTL = 1800

# ── Regions ──
REGIONS = ["IN", "US", "GB", "AE", "SA", "AU", "CA", "SG", "MY"]

# ── PRIMARY LANGUAGE BUTTONS (shown on home page) ──
PRIMARY_LANGS = [
    ("ml", "Malayalam"),
    ("kn", "Kannada"),
    ("te", "Telugu"),
    ("hi", "Hindi"),
    ("en", "English"),
    ("ta", "Tamil"),
    ("bn", "Bengali"),
    ("mr", "Marathi"),
]

# ── Weekly fetch priority ──
PRIORITY_LANGS = ["ml", "ta", "en", "hi"]

# ── All language labels ──
LANGUAGE_LABELS = {
    "ml": "Malayalam", "ta": "Tamil", "en": "English", "hi": "Hindi",
    "te": "Telugu", "kn": "Kannada", "bn": "Bengali", "mr": "Marathi",
    "pa": "Punjabi", "gu": "Gujarati", "ur": "Urdu", "ko": "Korean",
    "ja": "Japanese", "zh": "Chinese", "es": "Spanish", "fr": "French",
    "de": "German", "ar": "Arabic", "tr": "Turkish", "th": "Thai",
}
DEFAULT_LANGS = ["ml", "ta", "en", "hi"]

# ── Presets ──
MIN_VOTE_PRESETS = [5, 10, 20, 50]
NOTIFY_TTL_PRESETS = [1, 6, 12, 24, 48]
BROADCAST_TTL_PRESETS = [1, 6, 12, 24, 72, 168]
BC_DELETE_HOURS = [0, 1, 6, 12, 24, 72, 168]

# ── OTT release type (TMDB) ──
# 1=Premiere, 2=Limited, 3=Theatrical, 4=Digital/OTT, 5=Physical, 6=TV
OTT_RELEASE_TYPE = 4

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
    "ott_broadcast_channel": 0,
    "weekly_target_admin": 0,
}

PREFIX = "ott"
