# ============================================================
# 🏨 DOWNTOWN VILLA — OTT CONFIG
# ============================================================

from __future__ import annotations

from plugins.broadcast.config import (
    fb, sc, _esc, _fmt_int, _fmt_size, _fmt_duration,
    DIV, DIV2, _is_admin,
)

PREFIX = "ott"

# All selectable languages (20)
ALL_LANGS = [
    ("ml", "MALAYALAM"),
    ("ta", "TAMIL"),
    ("en", "ENGLISH"),
    ("hi", "HINDI"),
    ("kn", "KANNADA"),
    ("te", "TELUGU"),
    ("bn", "BENGALI"),
    ("mr", "MARATHI"),
    ("pa", "PUNJABI"),
    ("gu", "GUJARATI"),
    ("ur", "URDU"),
    ("ko", "KOREAN"),
    ("ja", "JAPANESE"),
    ("zh", "CHINESE"),
    ("es", "SPANISH"),
    ("fr", "FRENCH"),
    ("de", "GERMAN"),
    ("ar", "ARABIC"),
    ("tr", "TURKISH"),
    ("th", "THAI"),
]

LANG_CODES = [c for c, _ in ALL_LANGS]
LANGUAGE_LABELS = dict(ALL_LANGS)
LANGUAGE_LABELS = {c: lbl.title() for c, lbl in ALL_LANGS}

DEFAULT_FAV_LANGS = ["ml", "ta", "en", "hi"]

PRIORITY_LANGS = ["ml", "ta", "en", "hi"]

INDIAN_OTTS = "8|9|119|122|220|232|237|2336|11|10|15|18"

FREQ_MODES = ["off", "daily", "weekly", "monthly"]
FREQ_HOURS = [6, 9, 12, 15, 18, 21]
FREQ_DAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]
FREQ_MONTH_DAYS = [1, 5, 10, 15, 20, 25, 28]

__all__ = [
    "PREFIX", "ALL_LANGS", "LANG_CODES", "LANGUAGE_LABELS",
    "DEFAULT_FAV_LANGS", "PRIORITY_LANGS", "INDIAN_OTTS",
    "FREQ_MODES", "FREQ_HOURS", "FREQ_DAYS", "FREQ_MONTH_DAYS",
    "fb", "sc", "_esc", "_fmt_int", "_fmt_size", "_fmt_duration",
    "DIV", "DIV2", "_is_admin",
]
