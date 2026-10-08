# ============================================================
# 🏨 DOWNTOWN VILLA — OTT CONFIG
# ============================================================

from __future__ import annotations

from plugins.broadcast.config import (
    fb, sc, _esc, _fmt_int, _fmt_size, _fmt_duration,
    _progress_colored, DIV, DIV2, _is_admin,
)

CHECK_WINDOWS = [(23, 6), (12, 18)]
CHECK_INTERVAL_SEC = 3600
FILE_CHECK_LIMIT = 100

WEEKLY_DAY = 0
WEEKLY_HOUR = 10
WEEKLY_MINUTE_WINDOW = 5

HYPE_HOUR = 20
PENDING_SCAN_INTERVAL = 60

SESSION_TTL = 900
CONFIRM_TTL = 300
JOB_TTL = 3600
SETUP_TTL = 6 * 3600

REGIONS = ["IN", "US", "GB", "AE", "SA", "AU", "CA", "SG", "MY"]

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

PRIORITY_LANGS = ["ml", "ta", "en", "hi"]

LANGUAGE_LABELS = {
    "ml": "Malayalam", "ta": "Tamil", "en": "English", "hi": "Hindi",
    "te": "Telugu", "kn": "Kannada", "bn": "Bengali", "mr": "Marathi",
    "pa": "Punjabi", "gu": "Gujarati", "ur": "Urdu", "ko": "Korean",
    "ja": "Japanese", "zh": "Chinese", "es": "Spanish", "fr": "French",
    "de": "German", "ar": "Arabic", "tr": "Turkish", "th": "Thai",
}
DEFAULT_LANGS = ["ml", "ta", "en", "hi"]

MIN_VOTE_PRESETS = [0, 5, 10, 20, 50]
NOTIFY_TTL_PRESETS = [1, 6, 12, 24, 48]
BROADCAST_TTL_PRESETS = [1, 6, 12, 24, 72, 168]
BC_DELETE_HOURS = [0, 1, 6, 12, 24, 72, 168]

INDIAN_OTTS = "8|9|119|122|220|232|237|2336|11|10|15|18"

DEFAULT_SETTINGS = {
    "region": "IN",
    "languages": DEFAULT_LANGS,
    "min_vote_count": 0,
    "notify_ttl_hours": 12,
    "broadcast_ttl_hours": 24,
    "share_button": True,
    "notify_button": True,
    "weekly_enabled": True,
    "hype_enabled": True,
    "auto_delete_broadcast": True,
    "ott_broadcast_channel": 0,
    "weekly_target_admin": 0,
    "file_list_per_page": 8,
}

PREFIX = "ott"
