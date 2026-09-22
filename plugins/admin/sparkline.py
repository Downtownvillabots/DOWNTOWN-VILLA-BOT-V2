# ============================================================
# 🏨 DOWNTOWN VILLA — SPARKLINE PANEL (ULTIMATE)
# ============================================================
#
# Big dedicated sparkline view.
#
# Each metric gets:
#   • Current value
#   • Color bar (storage mode)
#   • 30-sample sparkline (larger)
#   • Min / max / avg
#   • Trend arrow
#
# Metrics tracked:
#   • CPU %
#   • RAM %
#   • Disk %
#   • Network RX / TX rate
#   • Process CPU %
#   • Searches / min
#   • Files sent / min
#   • Commands / min
#
# Auto-refreshes every 5s.
#
# ============================================================

from __future__ import annotations

import logging
import os
import time
from collections import deque
from typing import Any, Deque, Dict, List, Tuple

from pyrogram.enums import ParseMode
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from core import config
from utils import fonts as F
from utils import format as FM
from utils import progress as P

logger = logging.getLogger(__name__)


# ============================================================
# SECTION 1 — SHARED SPARK BUFFER
# ============================================================
#
# We re-use the buffers from server.py + stats.py so that
# both panels show the same history.
#

_SPARK_LEN = 40  # bit longer for this page

# Own buffers (independent, in case other modules aren't loaded)
_spark: Dict[str, Deque[float]] = {
    "cpu":       deque(maxlen=_SPARK_LEN),
    "ram":       deque(maxlen=_SPARK_LEN),
    "disk":      deque(maxlen=_SPARK_LEN),
    "net_rx":    deque(maxlen=_SPARK_LEN),
    "net_tx":    deque(maxlen=_SPARK_LEN),
    "proc":      deque(maxlen=_SPARK_LEN),
    "searches":  deque(maxlen=_SPARK_LEN),
    "files":     deque(maxlen=_SPARK_LEN),
    "commands":  deque(maxlen=_SPARK_LEN),
}

# Last collection timestamps
_last_sample = 0.0
SAMPLE_INTERVAL = 5.0

# I/O last
_io_last = {"t": 0.0, "rx": 0, "tx": 0}


# ============================================================
# SECTION 2 — SAMPLING
# ============================================================

def _sample() -> None:
    """Take one sample of every metric. Cached for 5s."""
    global _last_sample
    now = time.time()
    if now - _last_sample < SAMPLE_INTERVAL:
        return
    _last_sample = now

    try:
        import psutil as ps
    except ImportError:
        ps = None

    if ps is not None:
        # CPU
        try:
            _spark["cpu"].append(ps.cpu_percent(interval=None))
        except Exception:
            _spark["cpu"].append(0)

        # RAM
        try:
            _spark["ram"].append(ps.virtual_memory().percent)
        except Exception:
            _spark["ram"].append(0)

        # Disk
        try:
            import shutil
            d = shutil.disk_usage("/")
            _spark["disk"].append(
                (d.used / d.total * 100) if d.total else 0
            )
        except Exception:
            _spark["disk"].append(0)

        # Network rates
        try:
            net = ps.net_io_counters()
            prev = _io_last
            if prev["t"]:
                dt = max(0.001, now - prev["t"])
                _spark["net_rx"].append((net.bytes_recv - prev["rx"]) / dt)
                _spark["net_tx"].append((net.bytes_sent - prev["tx"]) / dt)
            else:
                _spark["net_rx"].append(0)
                _spark["net_tx"].append(0)
            _io_last["t"] = now
            _io_last["rx"] = net.bytes_recv
            _io_last["tx"] = net.bytes_sent
        except Exception:
            _spark["net_rx"].append(0)
            _spark["net_tx"].append(0)

        # Process CPU
        try:
            p = ps.Process(os.getpid())
            _spark["proc"].append(p.cpu_percent(interval=None))
        except Exception:
            _spark["proc"].append(0)

    # Bot event rates from stats module
    try:
        from plugins.admin import stats as S
        _spark["searches"].append(S._rate("search", 60))
        _spark["files"].append(S._rate("file_sent", 60))
        _spark["commands"].append(S._rate("command", 60))
    except Exception:
        for k in ("searches", "files", "commands"):
            _spark[k].append(0)


# ============================================================
# SECTION 3 — SPARK RENDERING
# ============================================================

_SPARK_CHARS = "▁▂▃▄▅▆▇█"


def _render(samples: Deque[float], width: int = 30) -> str:
    if not samples:
        return "—"
    data = list(samples)[-width:]
    if len(data) < 2:
        return "—"
    lo = min(data)
    hi = max(data)
    span = max(0.001, hi - lo)
    out = []
    for v in data:
        idx = int((v - lo) / span * (len(_SPARK_CHARS) - 1))
        idx = max(0, min(len(_SPARK_CHARS) - 1, idx))
        out.append(_SPARK_CHARS[idx])
    return "".join(out)


def _stats(samples: Deque[float]) -> Tuple[float, float, float, float]:
    """Return (current, min, max, avg)."""
    if not samples:
        return (0.0, 0.0, 0.0, 0.0)
    data = list(samples)
    return (
        data[-1],
        min(data),
        max(data),
        sum(data) / len(data),
    )


# ============================================================
# SECTION 4 — FORMATTERS
# ============================================================

def _fmt_pct(v: float) -> str:
    return f"{v:.1f}%"


def _fmt_rate(v: float) -> str:
    if v < 1024:
        return f"{v:.1f}/s"
    return FM.speed(v)


def _fmt_count(v: float) -> str:
    return f"{v:.1f}/min"


# ============================================================
# SECTION 5 — KEYBOARD
# ============================================================

def _nav_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"{F.EMO['refresh']} {F.sc('refresh')}",
                callback_data="adm:page:sparkline",
            ),
            InlineKeyboardButton(
                f"❤️ {F.sc('health')}",
                callback_data="adm:page:health",
            ),
        ],
        [
            InlineKeyboardButton(
                f"🖥️ {F.sc('server')}",
                callback_data="adm:page:server",
            ),
            InlineKeyboardButton(
                f"{F.EMO['chart']} {F.sc('stats')}",
                callback_data="adm:page:stats",
            ),
        ],
        [
            InlineKeyboardButton(
                f"{F.EMO['back']} {F.sc('back')}",
                callback_data="adm:home",
            ),
            InlineKeyboardButton(
                f"{F.EMO['cross']} {F.sc('close')}",
                callback_data="adm:close",
            ),
        ],
    ])


# ============================================================
# SECTION 6 — MAIN BUILDER
# ============================================================

async def build() -> Tuple[str, InlineKeyboardMarkup]:
    """Big sparkline view."""
    _sample()

    lines: List[str] = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"{F.EMO['spark']} <b>{F.fb('SPARKLINE')}</b> "
        f"· last {_SPARK_LEN} samples",
        F.DIV,
        "",
    ]

    # System metrics with bars
    lines.append(F.DIV_S)
    lines.append(f"🖥️ <b>{F.fb('SYSTEM')}</b>")
    lines.append(F.DIV_S)
    lines.append("")

    for key, label, bar_mode in (
        ("cpu", "CPU", "storage"),
        ("ram", "RAM", "storage"),
        ("disk", "DISK", "storage"),
    ):
        samples = _spark[key]
        cur, lo, hi, avg = _stats(samples)
        lines.append(
            f"{F.EMO.get(key, '📊')} <b>{F.sc(label)}</b> · "
            f"<b>{_fmt_pct(cur)}</b>"
        )
        lines.append(f"<code>{P.bar(cur, bar_mode, width=14)}</code>")
        lines.append(f"<code>{_render(samples, 30)}</code>")
        lines.append(
            f"   min <b>{_fmt_pct(lo)}</b> · "
            f"max <b>{_fmt_pct(hi)}</b> · "
            f"avg <b>{_fmt_pct(avg)}</b>"
        )
        lines.append("")

    # Network
    lines.append(F.DIV_S)
    lines.append(f"{F.EMO['net']} <b>{F.fb('NETWORK')}</b>")
    lines.append(F.DIV_S)
    lines.append("")
    for key, label in (("net_rx", "RX"), ("net_tx", "TX")):
        samples = _spark[key]
        cur, lo, hi, avg = _stats(samples)
        lines.append(
            f"📡 <b>{F.sc(label)}</b> · <b>{_fmt_rate(cur)}</b>"
        )
        lines.append(f"<code>{_render(samples, 30)}</code>")
        lines.append(
            f"   min <b>{_fmt_rate(lo)}</b> · "
            f"max <b>{_fmt_rate(hi)}</b>"
        )
        lines.append("")

    # Process
    lines.append(F.DIV_S)
    lines.append(f"⚙️ <b>{F.fb('PROCESS')}</b>")
    lines.append(F.DIV_S)
    lines.append("")
    samples = _spark["proc"]
    cur, lo, hi, avg = _stats(samples)
    lines.append(f"🔥 <b>{F.sc('CPU')}</b> · <b>{_fmt_pct(cur)}</b>")
    lines.append(f"<code>{_render(samples, 30)}</code>")
    lines.append(
        f"   min <b>{_fmt_pct(lo)}</b> · "
        f"max <b>{_fmt_pct(hi)}</b> · "
        f"avg <b>{_fmt_pct(avg)}</b>"
    )
    lines.append("")

    # Bot event rates
    lines.append(F.DIV_S)
    lines.append(f"{F.EMO['chart']} <b>{F.fb('BOT EVENTS')}</b> "
                 f"· per minute")
    lines.append(F.DIV_S)
    lines.append("")
    for key, label in (
        ("searches", "Searches"),
        ("files", "Files"),
        ("commands", "Commands"),
    ):
        samples = _spark[key]
        cur, lo, hi, avg = _stats(samples)
        lines.append(
            f"📊 <b>{F.sc(label)}</b> · <b>{_fmt_count(cur)}</b>"
        )
        lines.append(f"<code>{_render(samples, 30)}</code>")
        lines.append(
            f"   max <b>{_fmt_count(hi)}</b> · "
            f"avg <b>{_fmt_count(avg)}</b>"
        )
        lines.append("")

    lines.append(F.DIV_S)
    lines.append(f"🕒 <code>{FM.datetime_()}</code>")

    text = "\n".join(lines)[:4000]
    return text, _nav_kb()


# ============================================================
# SECTION 7 — SNAPSHOT
# ============================================================

def snapshot() -> Dict[str, Any]:
    return {
        k: list(v)[-1] if v else 0.0
        for k, v in _spark.items()
    }


# ============================================================
# PUBLIC EXPORTS
# ============================================================

__all__ = ["build", "snapshot"]
