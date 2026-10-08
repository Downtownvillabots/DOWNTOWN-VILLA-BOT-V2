# ============================================================
# 🏨 DOWNTOWN VILLA — OTT CONFIG
# ============================================================

from __future__ import annotations

from plugins.broadcast.config import (
    fb, sc, _esc, _fmt_int, _fmt_size, _fmt_duration,
    DIV, DIV2, _is_admin,
)

WEEK_DAY = 0            # unused now, weekly post removed
PREFIX = "ott"

REGIONS = ["IN", "US", "GB", "AE", "SA", "AU", "CA", "SG", "MY"]

PRIMARY_LANGS = [
    ("ml", "MALAYALAM"),
    ("kn", "KANNADA"),
    ("te", "TELUGU"),
    ("hi", "HINDI"),
    ("en", "ENGLISH"),
    ("ta", "TAMIL"),
    ("bn", "BENGALI"),
    ("mr", "MARATHI"),
]

PRIORITY_LANGS = ["ml", "ta", "en", "hi"]

LANGUAGE_LABELS = {
    "ml": "Malayalam", "ta": "Tamil", "en": "English", "hi": "Hindi",
    "te": "Telugu", "kn": "Kannada", "bn": "Bengali", "mr": "Marathi",
    "pa": "Punjabi", "gu": "Gujarati", "ur": "Urdu", "ko": "Korean",
    "ja": "Japanese", "zh": "Chinese", "es": "Spanish", "fr": "French",
    "de": "German", "ar": "Arabic", "tr": "Turkish", "th": "Thai",
}

INDIAN_OTTS = "8|9|119|122|220|232|237|2336|11|10|15|18"

DEFAULT_SETTINGS = {
    "region": "IN",
    "languages": PRIORITY_LANGS,
    "min_vote_count": 0,
}

__all__ = [
    "PREFIX", "REGIONS", "PRIMARY_LANGS", "PRIORITY_LANGS",
    "LANGUAGE_LABELS", "INDIAN_OTTS", "DEFAULT_SETTINGS",
    "fb", "sc", "_esc", "_fmt_int", "_fmt_size", "_fmt_duration",
    "DIV", "DIV2", "_is_admin",
]
