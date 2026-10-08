# ============================================================
# 🏨 DOWNTOWN VILLA — OTT CONFIG
# ============================================================

from __future__ import annotations

from plugins.broadcast.config import (
    fb, sc, _esc, _fmt_int, _fmt_size, _fmt_duration,
    DIV, DIV2, _is_admin,
)

PREFIX = "ott"

PRIMARY_LANGS = [
    ("ml", "MALAYALAM"),
    ("ta", "TAMIL"),
    ("en", "ENGLISH"),
    ("hi", "HINDI"),
    ("kn", "KANNADA"),
    ("te", "TELUGU"),
    ("bn", "BENGALI"),
    ("mr", "MARATHI"),
]

LANGUAGE_LABELS = {
    "ml": "Malayalam", "ta": "Tamil", "en": "English", "hi": "Hindi",
    "te": "Telugu", "kn": "Kannada", "bn": "Bengali", "mr": "Marathi",
}

INDIAN_OTTS = "8|9|119|122|220|232|237|2336|11|10|15|18"

FREQ_MODES = ["off", "daily", "weekly", "monthly"]
FREQ_HOURS = [6, 9, 12, 15, 18, 21]
FREQ_DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
FREQ_MONTH_DAYS = [1, 5, 10, 15, 20, 25, 28]

DEFAULT_FAV_LANGS = ["ml", "ta", "en", "hi"]

__all__ = [
    "PREFIX", "PRIMARY_LANGS", "LANGUAGE_LABELS", "INDIAN_OTTS",
    "FREQ_MODES", "FREQ_HOURS", "FREQ_DAYS", "FREQ_MONTH_DAYS",
    "DEFAULT_FAV_LANGS",
    "fb", "sc", "_esc", "_fmt_int", "_fmt_size", "_fmt_duration",
    "DIV", "DIV2", "_is_admin",
]
