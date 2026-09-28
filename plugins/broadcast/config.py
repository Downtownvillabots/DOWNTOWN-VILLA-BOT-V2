# ============================================================
# 🏨 DOWNTOWN VILLA — BROADCAST CONFIG
# ============================================================

from __future__ import annotations
import os
from typing import List

try:
    from core.config import ADMINS as _ADMINS
    ADMINS: List[int] = [int(a) for a in (_ADMINS or [])]
except Exception:
    ADMINS = []

_RAW = os.getenv("BROADCAST_CHANNEL_ID", "0").strip()
try:
    BROADCAST_CHANNEL_ID = int(_RAW) or None
except (TypeError, ValueError):
    BROADCAST_CHANNEL_ID = None

SESSION_TTL = 900
SOURCE_TTL = 3600
PROGRESS_EDIT_INTERVAL = 2.5
BROADCAST_BATCH_SIZE = 30
BROADCAST_CONCURRENCY = 5
DEFAULT_DELAY = 0.05
AUTODELETE_SCAN_INTERVAL = 60
DEBOUNCE_SECONDS = 2.5

DIV = "━" * 26
DIV2 = "─" * 26

DEFAULT_BROADCAST_CAPTION = (
    "🎬 <b>{file_name}</b>\n"
    "📦 Size: <code>{file_size}</code>\n"
    "⭐ Rating: <b>{rating}</b>\n"
    "\n"
    "⚡ <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>"
)

CAPTION_TEMPLATES = {
    "default": DEFAULT_BROADCAST_CAPTION,
    "movies": (
        "🎬 <b>{file_name}</b>\n"
        "📅 Year: <b>{year}</b>\n"
        "📦 Size: <code>{file_size}</code>\n"
        "⭐ Rating: <b>{rating}</b>\n\n"
        "⚡ <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>"
    ),
    "series": (
        "📺 <b>{file_name}</b>\n"
        "📅 Year: <b>{year}</b>\n"
        "📦 Size: <code>{file_size}</code>\n\n"
        "⚡ <b>𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔</b>"
    ),
    "minimal": "🎬 <b>{file_name}</b>\n📦 {file_size}",
}

AUTODELETE_PRESETS = [
    (1,  86400,   "1 DAY"),
    (3,  259200,  "3 DAYS"),
    (7,  604800,  "7 DAYS"),
    (10, 864000,  "10 DAYS"),
    (30, 2592000, "30 DAYS"),
    (0,  0,       "NEVER"),
]
AUTODELETE_LABELS = {d: label for _, d, label in AUTODELETE_PRESETS}
AUTODELETE_SECONDS = {d: s for d, s, _ in AUTODELETE_PRESETS}

# Fancy fonts
_M_BOLD = {
    **{chr(ord('A') + i): "𝗔𝗕𝗖𝗗𝗘𝗙𝗚𝗛𝗜𝗝𝗞𝗟𝗠𝗡𝗢𝗣𝗤𝗥𝗦𝗧𝗨𝗩𝗪𝗫𝗬𝗭"[i] for i in range(26)},
    **{chr(ord('a') + i): "𝗮𝗯𝗰𝗱𝗲𝗳𝗴𝗵𝗶𝗷𝗸𝗹𝗺𝗻𝗼𝗽𝗾𝗿𝘀𝘁𝘂𝘃𝘄𝘅𝘆𝘇"[i] for i in range(26)},
    **{chr(ord('0') + i): "𝟬𝟭𝟮𝟯𝟰𝟱𝟲𝟳𝟴𝟵"[i] for i in range(10)},
}
_M_SC = {
    'a':'ᴀ','b':'ʙ','c':'ᴄ','d':'ᴅ','e':'ᴇ','f':'ꜰ','g':'ɢ','h':'ʜ','i':'ɪ',
    'j':'ᴊ','k':'ᴋ','l':'ʟ','m':'ᴍ','n':'ɴ','o':'ᴏ','p':'ᴘ','q':'ǫ','r':'ʀ',
    's':'ꜱ','t':'ᴛ','u':'ᴜ','v':'ᴠ','w':'ᴡ','x':'x','y':'ʏ','z':'ᴢ',
    'A':'ᴀ','B':'ʙ','C':'ᴄ','D':'ᴅ','E':'ᴇ','F':'ꜰ','G':'ɢ','H':'ʜ','I':'ɪ',
    'J':'ᴊ','K':'ᴋ','L':'ʟ','M':'ᴍ','N':'ɴ','O':'ᴏ','P':'ᴘ','Q':'ǫ','R':'ʀ',
    'S':'ꜱ','T':'ᴛ','U':'ᴜ','V':'ᴠ','W':'ᴡ','X':'x','Y':'ʏ','Z':'ᴢ',
}


def fb(s) -> str:
    return "".join(_M_BOLD.get(c, c) for c in str(s))


def sc(s) -> str:
    return "".join(_M_SC.get(c, c) for c in str(s))


def _fmt_int(n) -> str:
    try:
        return f"{int(n):,}"
    except (TypeError, ValueError):
        return "0"


def _fmt_size(size) -> str:
    if not size:
        return "0 B"
    try:
        s = float(size)
    except (TypeError, ValueError):
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    i = 0
    while s >= 1024 and i < len(units) - 1:
        s /= 1024.0
        i += 1
    return f"{s:.2f} {units[i]}"


def _fmt_duration(seconds: float) -> str:
    try:
        seconds = int(max(0, seconds))
    except (TypeError, ValueError):
        return "0s"
    if seconds < 60:
        return f"{seconds}s"
    m, s = divmod(seconds, 60)
    if m < 60:
        return f"{m}m {s}s"
    h, m = divmod(m, 60)
    if h < 24:
        return f"{h}h {m}m"
    d, h = divmod(h, 24)
    return f"{d}d {h}h"


def _esc(text) -> str:
    if text is None:
        return ""
    return (str(text)
            .replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;"))


def _progress_colored(current, total, width=10) -> str:
    if total <= 0:
        return "⬛" * width + " 0%"
    pct = min(100.0, (current / total) * 100.0)
    filled = max(0, min(width, int(width * pct / 100.0)))
    empty = width - filled
    if pct >= 80:
        block = "🟩"
    elif pct >= 50:
        block = "🟨"
    elif pct >= 25:
        block = "🟧"
    else:
        block = "🟥"
    return block * filled + "⬛" * empty + f" {pct:.1f}%"


def _is_admin(user_id) -> bool:
    try:
        return int(user_id) in ADMINS
    except Exception:
        return False
