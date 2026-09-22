# ============================================================
# 🏨 DOWNTOWN VILLA — FONTS & EMOJI ENGINE
# ============================================================
#
# THE single source of truth for every fancy font + emoji in the bot.
#
# ============================================================

from __future__ import annotations
from typing import Any, Dict


# ============================================================
# SECTION 1 — BOLD SANS  (𝟬𝟭 𝗮𝗯𝗰 𝗔𝗕𝗖)
# ============================================================

_BOLD_UPPER = (
    "𝗔𝗕𝗖𝗗𝗘𝗙𝗚𝗛𝗜𝗝𝗞𝗟𝗠𝗡𝗢𝗣𝗤𝗥𝗦𝗧𝗨𝗩𝗪𝗫𝗬𝗭"
)
_BOLD_LOWER = (
    "𝗮𝗯𝗰𝗱𝗲𝗳𝗴𝗵𝗶𝗷𝗸𝗹𝗺𝗻𝗼𝗽𝗾𝗿𝘀𝘁𝘂𝘃𝘄𝘅𝘆𝘇"
)
_BOLD_DIGIT = "𝟬𝟭𝟮𝟯𝟰𝟱𝟲𝟳𝟴𝟵"

_BOLD_MAP: Dict[str, str] = {}

for i, ch in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
    _BOLD_MAP[ch] = _BOLD_UPPER[i]
for i, ch in enumerate("abcdefghijklmnopqrstuvwxyz"):
    _BOLD_MAP[ch] = _BOLD_LOWER[i]
for i, ch in enumerate("0123456789"):
    _BOLD_MAP[ch] = _BOLD_DIGIT[i]


def fb(text: Any) -> str:
    """Bold sans: 'Hello' → '𝗛𝗲𝗹𝗹𝗼'"""
    return _apply(text, _BOLD_MAP)


# ============================================================
# SECTION 2 — SMALL CAPS  (ᴀʙᴄ)
# ============================================================

_SC_MAP: Dict[str, str] = {
    "a": "ᴀ", "b": "ʙ", "c": "ᴄ", "d": "ᴅ", "e": "ᴇ", "f": "ꜰ",
    "g": "ɢ", "h": "ʜ", "i": "ɪ", "j": "ᴊ", "k": "ᴋ", "l": "ʟ",
    "m": "ᴍ", "n": "ɴ", "o": "ᴏ", "p": "ᴘ", "q": "ǫ", "r": "ʀ",
    "s": "ꜱ", "t": "ᴛ", "u": "ᴜ", "v": "ᴠ", "w": "ᴡ", "x": "x",
    "y": "ʏ", "z": "ᴢ",
    "A": "ᴀ", "B": "ʙ", "C": "ᴄ", "D": "ᴅ", "E": "ᴇ", "F": "ꜰ",
    "G": "ɢ", "H": "ʜ", "I": "ɪ", "J": "ᴊ", "K": "ᴋ", "L": "ʟ",
    "M": "ᴍ", "N": "ɴ", "O": "ᴏ", "P": "ᴘ", "Q": "ǫ", "R": "ʀ",
    "S": "ꜱ", "T": "ᴛ", "U": "ᴜ", "V": "ᴠ", "W": "ᴡ", "X": "x",
    "Y": "ʏ", "Z": "ᴢ",
}


def sc(text: Any) -> str:
    """Small caps: 'Hello' → 'ʜᴇʟʟᴏ'"""
    return _apply(text, _SC_MAP)


# ============================================================
# SECTION 3 — MONOSPACE  (𝙰𝙱𝙲 𝟶𝟷)
# ============================================================

_MONO_UPPER = (
    "𝙰𝙱𝙲𝙳𝙴𝙵𝙶𝙷𝙸𝙹𝙺𝙻𝙼𝙽𝙾𝙿𝚀𝚁𝚂𝚃𝚄𝚅𝚆𝚇𝚈𝚉"
)
_MONO_LOWER = (
    "𝚊𝚋𝚌𝚍𝚎𝚏𝚐𝚑𝚒𝚓𝚔𝚕𝚖𝚗𝚘𝚙𝚚𝚛𝚜𝚝𝚞𝚟𝚠𝚡𝚢𝚣"
)
_MONO_DIGIT = "𝟶𝟷𝟸𝟹𝟺𝟻𝟼𝟽𝟾𝟿"

_MONO_MAP: Dict[str, str] = {}

for i, ch in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
    _MONO_MAP[ch] = _MONO_UPPER[i]
for i, ch in enumerate("abcdefghijklmnopqrstuvwxyz"):
    _MONO_MAP[ch] = _MONO_LOWER[i]
for i, ch in enumerate("0123456789"):
    _MONO_MAP[ch] = _MONO_DIGIT[i]


def fm(text: Any) -> str:
    """Monospace: 'Hello' → '𝙷𝚎𝚕𝚕𝚘'"""
    return _apply(text, _MONO_MAP)


# ============================================================
# SECTION 4 — ITALIC  (𝘈𝘣𝘤)
# ============================================================

_IT_UPPER = (
    "𝘈𝘉𝘊𝘋𝘌𝘍𝘎𝘏𝘐𝘑𝘒𝘓𝘔𝘕𝘖𝘗𝘘𝘙𝘚𝘛𝘜𝘝𝘞𝘟𝘠𝘡"
)
_IT_LOWER = (
    "𝘢𝘣𝘤𝘥𝘦𝘧𝘨𝘩𝘪𝘫𝘬𝘭𝘮𝘯𝘰𝘱𝘲𝘳𝘴𝘵𝘶𝘷𝘸𝘹𝘺𝘻"
)

_IT_MAP: Dict[str, str] = {}

for i, ch in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
    _IT_MAP[ch] = _IT_UPPER[i]
for i, ch in enumerate("abcdefghijklmnopqrstuvwxyz"):
    _IT_MAP[ch] = _IT_LOWER[i]


def fi(text: Any) -> str:
    """Italic: 'Hello' → '𝘏𝘦𝘭𝘭𝘰'"""
    return _apply(text, _IT_MAP)


# ============================================================
# SECTION 5 — SERIF BOLD  (𝐀𝐛𝐜)
# ============================================================

_SB_UPPER = (
    "𝐀𝐁𝐂𝐃𝐄𝐅𝐆𝐇𝐈𝐉𝐊𝐋𝐌𝐍𝐎𝐏𝐐𝐑𝐒𝐓𝐔𝐕𝐖𝐗𝐘𝐙"
)
_SB_LOWER = (
    "𝐚𝐛𝐜𝐝𝐞𝐟𝐠𝐡𝐢𝐣𝐤𝐥𝐦𝐧𝐨𝐩𝐪𝐫𝐬𝐭𝐮𝐯𝐰𝐱𝐲𝐳"
)
_SB_DIGIT = "𝟎𝟏𝟐𝟑𝟒𝟓𝟔𝟕𝟖𝟗"

_SB_MAP: Dict[str, str] = {}

for i, ch in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
    _SB_MAP[ch] = _SB_UPPER[i]
for i, ch in enumerate("abcdefghijklmnopqrstuvwxyz"):
    _SB_MAP[ch] = _SB_LOWER[i]
for i, ch in enumerate("0123456789"):
    _SB_MAP[ch] = _SB_DIGIT[i]


def fr(text: Any) -> str:
    """Serif bold: 'Hello' → '𝐇𝐞𝐥𝐥𝐨'"""
    return _apply(text, _SB_MAP)


# ============================================================
# SECTION 6 — DOUBLE-STRUCK  (𝔸𝕓𝕔)
# ============================================================

_DS_UPPER = (
    "𝔸𝔹ℂ𝔻𝔼𝔽𝔾ℍ𝕀𝕁𝕂𝕃𝕄ℕ𝕆ℙℚℝ𝕊𝕋𝕌𝕍𝕎𝕏𝕐ℤ"
)
_DS_LOWER = (
    "𝕒𝕓𝕔𝕕𝕖𝕗𝕘𝕙𝕚𝕛𝕜𝕝𝕞𝕟𝕠𝕡𝕢𝕣𝕤𝕥𝕦𝕧𝕨𝕩𝕪𝕫"
)
_DS_DIGIT = "𝟘𝟙𝟚𝟛𝟜𝟝𝟞𝟟𝟠𝟡"

_DS_MAP: Dict[str, str] = {}

for i, ch in enumerate("ABCDEFGHIJKLMNOPQRSTUVWXYZ"):
    _DS_MAP[ch] = _DS_UPPER[i]
for i, ch in enumerate("abcdefghijklmnopqrstuvwxyz"):
    _DS_MAP[ch] = _DS_LOWER[i]
for i, ch in enumerate("0123456789"):
    _DS_MAP[ch] = _DS_DIGIT[i]


def fd(text: Any) -> str:
    """Double-struck: 'Hello' → 'ℍ𝕖𝕝𝕝𝕠'"""
    return _apply(text, _DS_MAP)


# ============================================================
# SECTION 7 — UNDERLINE (for headers)
# ============================================================

_UL_REPLACEMENTS = {
    "0": "0̲", "1": "1̲", "2": "2̲", "3": "3̲", "4": "4̲",
    "5": "5̲", "6": "6̲", "7": "7̲", "8": "8̲", "9": "9̲",
}


def fu(text: Any) -> str:
    """Underline digits (safe for HTML)."""
    return _apply(text, _UL_REPLACEMENTS)


# ============================================================
# SECTION 8 — CORE APPLIER
# ============================================================

def _apply(text: Any, mapping: Dict[str, str]) -> str:
    """Map every char through a font dictionary."""
    if text is None:
        return ""
    try:
        s = str(text)
    except Exception:
        return ""
    if not s:
        return ""
    return "".join(mapping.get(c, c) for c in s)


# ============================================================
# SECTION 9 — FANCY SHORTCUTS
# ============================================================

FANCY: Dict[str, str] = {
    # Core
    "downtown_villa":  "𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔",
    "brand":           "𝗗𝗢𝗪𝗡𝗧𝗢𝗪𝗡 𝗩𝗜𝗟𝗟𝗔",
    "admin":           "ᴀᴅᴍɪɴ",
    "owner":           "ᴏᴡɴᴇʀ",
    "user":            "ᴜꜱᴇʀ",
    "guest":           "ɢᴜᴇꜱᴛ",

    # Actions
    "search":          "ꜱᴇᴀʀᴄʜ",
    "searching":       "ꜱᴇᴀʀᴄʜɪɴɢ",
    "loading":         "ʟᴏᴀᴅɪɴɢ",
    "please_wait":     "ᴘʟᴇᴀꜱᴇ ᴡᴀɪᴛ",
    "processing":      "ᴘʀᴏᴄᴇꜱꜱɪɴɢ",
    "uploading":       "ᴜᴘʟᴏᴀᴅɪɴɢ",
    "downloading":     "ᴅᴏᴡɴʟᴏᴀᴅɪɴɢ",
    "completed":       "ᴄᴏᴍᴘʟᴇᴛᴇᴅ",
    "failed":          "ꜰᴀɪʟᴇᴅ",
    "cancelled":       "ᴄᴀɴᴄᴇʟʟᴇᴅ",
    "paused":          "ᴘᴀᴜꜱᴇᴅ",
    "running":         "ʀᴜɴɴɪɴɢ",
    "stopped":         "ꜱᴛᴏᴘᴘᴇᴅ",
    "ready":           "ʀᴇᴀᴅʏ",

    # Status
    "online":          "ᴏɴʟɪɴᴇ",
    "offline":         "ᴏꜰꜰʟɪɴᴇ",
    "healthy":         "ʜᴇᴀʟᴛʜʏ",
    "warning":         "ᴡᴀʀɴɪɴɢ",
    "critical":        "ᴄʀɪᴛɪᴄᴀʟ",
    "error":           "ᴇʀʀᴏʀ",
    "success":         "ꜱᴜᴄᴄᴇꜱꜱ",
    "info":            "ɪɴꜰᴏ",
    "error_short":     "ᴇʀʀ",

    # Content
    "movie":           "ᴍᴏᴠɪᴇ",
    "movies":          "ᴍᴏᴠɪᴇꜱ",
    "series":          "ꜱᴇʀɪᴇꜱ",
    "season":          "ꜱᴇᴀꜱᴏɴ",
    "episode":         "ᴇᴘɪꜱᴏᴅᴇ",
    "quality":         "Qᴜᴀʟɪᴛʏ",
    "language":        "ʟᴀɴɢᴜᴀɢᴇ",
    "audio":           "ᴀᴜᴅɪᴏ",
    "subtitle":        "ꜱᴜʙᴛɪᴛʟᴇ",
    "size":            "ꜱɪᴢᴇ",
    "rating":          "ʀᴀᴛɪɴɢ",
    "genre":           "ɢᴇɴʀᴇ",
    "year":            "ʏᴇᴀʀ",
    "runtime":         "ʀᴜɴᴛɪᴍᴇ",
    "director":        "ᴅɪʀᴇᴄᴛᴏʀ",
    "cast":            "ᴄᴀꜱᴛ",
    "plot":            "ᴘʟᴏᴛ",

    # Backup
    "backup":          "ʙᴀᴄᴋᴜᴘ",
    "database":        "ᴅᴀᴛᴀʙᴀꜱᴇ",
    "storage":         "ꜱᴛᴏʀᴀɢᴇ",
    "shard":           "ꜱʜᴀʀᴅ",
    "documents":       "ᴅᴏᴄᴜᴍᴇɴᴛꜱ",
    "collections":     "ᴄᴏʟʟᴇᴄᴛɪᴏɴꜱ",

    # Server
    "server":          "ꜱᴇʀᴠᴇʀ",
    "cpu":             "ᴄᴘᴜ",
    "ram":             "ʀᴀᴍ",
    "disk":            "ᴅɪꜱᴋ",
    "network":         "ɴᴇᴛᴡᴏʀᴋ",
    "uptime":          "ᴜᴘᴛɪᴍᴇ",
    "process":         "ᴘʀᴏᴄᴇꜱꜱ",

    # Premium
    "premium":         "ᴘʀᴇᴍɪᴜᴍ",
    "watch":           "ᴡᴀᴛᴄʜ",
    "progress":        "ᴘʀᴏɢʀᴇꜱꜱ",
    "rating_short":    "ʀᴀᴛᴇ",

    # OTT
    "releases":        "ʀᴇʟᴇᴀꜱᴇꜱ",
    "weekly":          "ᴡᴇᴇᴋʟʏ",
    "notify":          "ɴᴏᴛɪꜰʏ",
    "subscribed":      "ꜱᴜʙꜱᴄʀɪʙᴇᴅ",

    # Misc
    "cancel":          "ᴄᴀɴᴄᴇʟ",
    "close":           "ᴄʟᴏꜱᴇ",
    "back":            "ʙᴀᴄᴋ",
    "next":            "ɴᴇxᴛ",
    "previous":        "ᴘʀᴇᴠ",
    "refresh":         "ʀᴇꜰʀᴇꜱʜ",
    "reset":           "ʀᴇꜱᴇᴛ",
    "start":           "ꜱᴛᴀʀᴛ",
    "stop":            "ꜱᴛᴏᴘ",
    "pause":           "ᴘᴀᴜꜱᴇ",
    "resume":          "ʀᴇꜱᴜᴍᴇ",
    "retry":           "ʀᴇᴛʀʏ",
    "confirm":         "ᴄᴏɴꜰɪʀᴍ",
    "delete":          "ᴅᴇʟᴇᴛᴇ",
    "add":             "ᴀᴅᴅ",
    "remove":          "ʀᴇᴍᴏᴠᴇ",
    "edit":            "ᴇᴅɪᴛ",
    "save":            "ꜱᴀᴠᴇ",
    "settings":        "ꜱᴇᴛᴛɪɴɢꜱ",
    "stats":           "ꜱᴛᴀᴛꜱ",
    "history":         "ʜɪꜱᴛᴏʀʏ",
    "logs":            "ʟᴏɢꜱ",
    "activity":        "ᴀᴄᴛɪᴠɪᴛʏ",
    "tasks":           "ᴛᴀꜱᴋꜱ",
    "trending":        "ᴛʀᴇɴᴅɪɴɢ",
    "request":         "ʀᴇǫᴜᴇꜱᴛ",
    "missing":         "ᴍɪꜱꜱɪɴɢ",
}


def f(key: str) -> str:
    """Lookup a shortcut label from FANCY. Falls back to sc() on miss."""
    if not key:
        return ""
    k = str(key).strip().lower()
    if k in FANCY:
        return FANCY[k]
    return sc(k)


# ============================================================
# SECTION 10 — EMOJI MAP
# ============================================================

EMO: Dict[str, str] = {
    # Brand / status
    "brand":       "🏨",
    "bot":         "🤖",
    "crown":       "👑",
    "star":        "⭐",
    "spark":       "✨",
    "fire":        "🔥",
    "rocket":      "🚀",
    "party":       "🎉",
    "trophy":      "🏆",
    "gift":        "🎁",
    "bell":        "🔔",
    "gear":        "⚙️",
    "lock":        "🔒",
    "key":         "🔑",

    # Status dots
    "green":       "🟢",
    "yellow":      "🟡",
    "orange":      "🟠",
    "red":         "🔴",
    "white":       "⚪",
    "black":       "⚫",
    "blue":        "🔵",

    # Progress blocks
    "block_green":  "🟩",
    "block_yellow": "🟨",
    "block_orange": "🟧",
    "block_red":    "🟥",
    "block_empty":  "⬛",

    # Actions
    "ok":          "✅",
    "cross":       "❌",
    "warn":        "⚠️",
    "info":        "ℹ️",
    "play":        "▶️",
    "pause":       "⏸️",
    "stop":        "⏹️",
    "next":        "⏭️",
    "prev":        "⏮️",
    "refresh":     "🔄",
    "reset":       "♻️",
    "back":        "◀️",
    "close":       "❌",
    "check":       "☑️",
    "box":         "⬜",
    "eye":         "👁️",
    "trash":       "🗑️",
    "plus":        "➕",
    "minus":       "➖",
    "send":        "📥",
    "share":       "📤",
    "search":      "🔎",
    "loading":     "⏳",
    "clock":       "⏰",

    # Content
    "film":        "🎬",
    "tv":          "📺",
    "clapper":     "🎞️",
    "dna":         "🧬",
    "sound":       "🔊",
    "sub":         "📝",
    "size":        "💾",
    "cal":         "📅",
    "rating":      "⭐",

    # User
    "user":        "👤",
    "users":       "👥",
    "id":          "🆔",
    "group":       "👥",
    "channel":     "📢",

    # Data
    "db":          "🗄️",
    "package":     "📦",
    "file":        "📄",
    "puzzle":      "🧩",
    "folder":      "🗂️",
    "chart":       "📊",
    "bar":         "📊",

    # Server
    "server":      "🖥️",
    "cpu":         "⚡",
    "ram":         "🧠",
    "disk":        "💽",
    "net":         "🌐",
    "wifi":        "📡",

    # Premium
    "watch":       "💎",
    "premium":     "👑",

    # OTT
    "calendar":    "📅",
    "release":     "🚀",
}


# ============================================================
# SECTION 10B — SAFE EMOJI WRAPPER (Fix B)
# ============================================================
#
# Any missing key returns a fallback (🔹) instead of raising
# KeyError. This makes F.EMO['anything'] safe everywhere.
# ============================================================

class _EmojiMap(dict):
    """Emoji dict that returns a fallback for missing keys."""

    _FALLBACK = "🔹"

    def __missing__(self, key):
        try:
            import logging
            logging.getLogger("downtown.fonts").debug(
                f"[EMO] missing key: {key!r}"
            )
        except Exception:
            pass
        return self._FALLBACK


EMO = _EmojiMap(EMO)


def e(key: str, default: str = "") -> str:
    """Shortcut for EMO lookup."""
    if default:
        return EMO.get(key, default)
    return EMO.get(key, _EmojiMap._FALLBACK)


# ============================================================
# SECTION 11 — LAYOUT HELPERS
# ============================================================

DIV = "━" * 26
DIV_S = "┄" * 26
DIV_L = "─" * 30
DIV_DOT = "·" * 26


def header(title: str) -> str:
    """Fancy header block."""
    return f"{EMO['brand']} <b>{fb('DOWNTOWN VILLA')}</b>\n{fb(title)}"


def divider(kind: str = "solid") -> str:
    """Divider shortcut."""
    return {
        "solid":  DIV,
        "soft":   DIV_S,
        "line":   DIV_L,
        "dots":   DIV_DOT,
    }.get(kind, DIV)


def title_line(emoji_key: str, text: str) -> str:
    """Line like: '🎬 SEARCH'"""
    return f"{e(emoji_key)} <b>{fb(text)}</b>"


def row(emoji_key: str, label: str, value: str) -> str:
    """Line like: '📦 Documents · 12,345'"""
    return f"{e(emoji_key)} {sc(label)} · <b>{value}</b>"


# ============================================================
# SECTION 12 — SELF CHECK
# ============================================================

def _self_check() -> bool:
    """Verify all fonts return distinct outputs."""
    ok = True

    if fb("A") == "A":
        ok = False
    if sc("a") == "a":
        ok = False
    if fm("1") == "1":
        ok = False
    if fi("A") == "A":
        ok = False
    if fr("A") == "A":
        ok = False

    if f("search") != "ꜱᴇᴀʀᴄʜ":
        ok = False
    if e("crown") != "👑":
        ok = False

    # Fix B check — unknown key must not raise
    try:
        _ = EMO["this_key_does_not_exist"]
    except KeyError:
        ok = False
    except Exception:
        ok = False

    return ok


try:
    _SELF_CHECK_PASS = _self_check()
except Exception:
    _SELF_CHECK_PASS = False


# ============================================================
# SECTION 13 — PUBLIC EXPORTS
# ============================================================

__all__ = [
    # Fonts
    "fb", "sc", "fm", "fi", "fr", "fd", "fu",
    # Shortcuts
    "f", "e", "FANCY", "EMO",
    # Layouts
    "DIV", "DIV_S", "DIV_L", "DIV_DOT",
    "header", "divider", "title_line", "row",
]
