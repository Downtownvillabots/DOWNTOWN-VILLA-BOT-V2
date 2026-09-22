# ============================================================
# 🏨 DOWNTOWN VILLA — SERVER MONITOR (ULTIMATE)
# ============================================================
#
# Live system + process monitor.
#
# Panels:
#   • Overview    → CPU/RAM/Disk/Net + process + load + spark
#   • CPU         → per-core bars + frequency + load avg
#   • Memory      → virtual + swap + top-by-RAM
#   • Disk        → every partition + IO rates
#   • Network     → every interface + IO rates
#   • Process     → self process (RSS/VMS/threads/fd/conns)
#   • Temperature → every sensor + fan speed
#   • Top         → top N by CPU or RAM
#
# Every metric:
#   • Auto-refreshes every 5s
#   • Uses color bars (storage mode)
#   • Shows trend arrows (↑↓→)
#   • Sparkline history
#   • Cancel button everywhere
#
# ============================================================

from __future__ import annotations

import logging
import os
import shutil
import time
from collections import deque
from typing import Any, Deque, Dict, List, Optional, Tuple

from pyrogram.enums import ParseMode
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from core import config
from utils import fonts as F
from utils import format as FM
from utils import progress as P

logger = logging.getLogger(__name__)


# ============================================================
# SECTION 1 — SAFE PSUTIL
# ============================================================

try:
    import psutil as _psutil
except ImportError:
    _psutil = None


def _ps():
    return _psutil


# ============================================================
# SECTION 2 — SPARKLINE STATE (30 samples)
# ============================================================

_SPARK_LEN = 30
_spark: Dict[str, Deque[float]] = {
    "cpu":   deque(maxlen=_SPARK_LEN),
    "ram":   deque(maxlen=_SPARK_LEN),
    "disk":  deque(maxlen=_SPARK_LEN),
    "rx":    deque(maxlen=_SPARK_LEN),
    "tx":    deque(maxlen=_SPARK_LEN),
    "proc":  deque(maxlen=_SPARK_LEN),
}

# I/O delta tracking
_io_last: Dict[str, Dict[str, float]] = {
    "net": {"t": 0.0, "rx": 0.0, "tx": 0.0},
    "disk": {"t": 0.0, "r": 0.0, "w": 0.0},
}

# Trend cache
_trend_last: Dict[str, float] = {}


# ============================================================
# SECTION 3 — SPARKLINE RENDERER
# ============================================================

_SPARK_CHARS = "▁▂▃▄▅▆▇█"


def _sparkline(samples: Deque[float], width: int = 20) -> str:
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


def _trend(key: str, value: float, sensitivity: float = 0.5) -> str:
    prev = _trend_last.get(key)
    _trend_last[key] = value
    if prev is None:
        return "→"
    d = value - prev
    if d > sensitivity:
        return "↑"
    if d < -sensitivity:
        return "↓"
    return "→"


# ============================================================
# SECTION 4 — CPU COLLECTOR
# ============================================================

def _collect_cpu() -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "ok": False,
        "total": 0.0,
        "per_core": [],
        "logical": 0,
        "physical": 0,
        "freq_current": 0.0,
        "freq_min": 0.0,
        "freq_max": 0.0,
        "load": (0.0, 0.0, 0.0),
        "ctx_switches": 0,
        "interrupts": 0,
    }
    ps = _ps()
    if ps is None:
        return out

    try:
        out["total"] = ps.cpu_percent(interval=0.05)
    except Exception:
        pass

    try:
        out["per_core"] = ps.cpu_percent(interval=None, percpu=True)
    except Exception:
        pass

    try:
        out["logical"] = ps.cpu_count(logical=True) or 0
        out["physical"] = ps.cpu_count(logical=False) or 0
    except Exception:
        pass

    try:
        freq = ps.cpu_freq()
        if freq:
            out["freq_current"] = freq.current or 0
            out["freq_min"] = freq.min or 0
            out["freq_max"] = freq.max or 0
    except Exception:
        pass

    try:
        out["load"] = os.getloadavg()
    except Exception:
        pass

    try:
        stats = ps.cpu_stats()
        out["ctx_switches"] = stats.ctx_switches
        out["interrupts"] = stats.interrupts
    except Exception:
        pass

    out["ok"] = True
    _spark["cpu"].append(out["total"])
    return out


# ============================================================
# SECTION 5 — MEMORY COLLECTOR
# ============================================================

def _collect_memory() -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "ok": False,
        "virt_total": 0, "virt_used": 0, "virt_free": 0,
        "virt_pct": 0.0,
        "swap_total": 0, "swap_used": 0, "swap_free": 0,
        "swap_pct": 0.0,
    }
    ps = _ps()
    if ps is None:
        return out

    try:
        v = ps.virtual_memory()
        out["virt_total"] = v.total
        out["virt_used"] = v.used
        out["virt_free"] = v.available
        out["virt_pct"] = v.percent
    except Exception:
        pass

    try:
        s = ps.swap_memory()
        out["swap_total"] = s.total
        out["swap_used"] = s.used
        out["swap_free"] = s.free
        out["swap_pct"] = s.percent
    except Exception:
        pass

    out["ok"] = True
    _spark["ram"].append(out["virt_pct"])
    return out


# ============================================================
# SECTION 6 — DISK COLLECTOR
# ============================================================

def _collect_disk() -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "ok": False,
        "root": {},
        "partitions": [],
        "io_read_rate": 0.0,
        "io_write_rate": 0.0,
        "io_read_total": 0,
        "io_write_total": 0,
    }
    ps = _ps()

    try:
        root = shutil.disk_usage("/")
        out["root"] = {
            "used": root.used,
            "total": root.total,
            "free": root.free,
            "pct": (root.used / root.total * 100) if root.total else 0.0,
        }
        _spark["disk"].append(out["root"]["pct"])
    except Exception:
        pass

    if ps is None:
        return out

    try:
        for part in ps.disk_partitions(all=False):
            try:
                u = ps.disk_usage(part.mountpoint)
                out["partitions"].append({
                    "device": part.device,
                    "mountpoint": part.mountpoint,
                    "fstype": part.fstype,
                    "used": u.used,
                    "total": u.total,
                    "free": u.free,
                    "pct": u.percent,
                })
            except Exception:
                continue
    except Exception:
        pass

    try:
        io = ps.disk_io_counters()
        if io:
            now = time.time()
            prev = _io_last["disk"]
            if prev["t"]:
                dt = max(0.001, now - prev["t"])
                out["io_read_rate"] = (io.read_bytes - prev["r"]) / dt
                out["io_write_rate"] = (io.write_bytes - prev["w"]) / dt
            _io_last["disk"]["t"] = now
            _io_last["disk"]["r"] = io.read_bytes
            _io_last["disk"]["w"] = io.write_bytes
            out["io_read_total"] = io.read_bytes
            out["io_write_total"] = io.write_bytes
    except Exception:
        pass

    out["ok"] = True
    return out


# ============================================================
# SECTION 7 — NETWORK COLLECTOR
# ============================================================

def _collect_network() -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "ok": False,
        "rx_rate": 0.0,
        "tx_rate": 0.0,
        "rx_total": 0,
        "tx_total": 0,
        "packets_rx": 0,
        "packets_tx": 0,
        "interfaces": [],
    }
    ps = _ps()
    if ps is None:
        return out

    try:
        net = ps.net_io_counters()
        if net:
            now = time.time()
            prev = _io_last["net"]
            if prev["t"]:
                dt = max(0.001, now - prev["t"])
                out["rx_rate"] = (net.bytes_recv - prev["rx"]) / dt
                out["tx_rate"] = (net.bytes_sent - prev["tx"]) / dt
            _io_last["net"]["t"] = now
            _io_last["net"]["rx"] = net.bytes_recv
            _io_last["net"]["tx"] = net.bytes_sent
            out["rx_total"] = net.bytes_recv
            out["tx_total"] = net.bytes_sent
            out["packets_rx"] = net.packets_recv
            out["packets_tx"] = net.packets_sent
    except Exception:
        pass

    try:
        per_nic = ps.net_io_counters(pernic=True)
        for name, counters in (per_nic or {}).items():
            out["interfaces"].append({
                "name": name,
                "rx": counters.bytes_recv,
                "tx": counters.bytes_sent,
                "rx_pkts": counters.packets_recv,
                "tx_pkts": counters.packets_sent,
                "err_in": counters.errin,
                "err_out": counters.errout,
                "drop_in": counters.dropin,
                "drop_out": counters.dropout,
            })
    except Exception:
        pass

    out["ok"] = True
    _spark["rx"].append(out["rx_rate"])
    _spark["tx"].append(out["tx_rate"])
    return out


# ============================================================
# SECTION 8 — PROCESS COLLECTOR
# ============================================================

def _collect_process() -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "ok": False,
        "pid": os.getpid(),
        "cpu": 0.0,
        "rss": 0,
        "vms": 0,
        "threads": 0,
        "children": 0,
        "open_files": 0,
        "connections": 0,
        "status": "unknown",
        "create_time": 0.0,
        "age": 0.0,
        "nice": 0,
    }
    ps = _ps()
    if ps is None:
        return out

    try:
        p = ps.Process(os.getpid())
        out["cpu"] = p.cpu_percent(interval=0.05)
        mem = p.memory_info()
        out["rss"] = mem.rss
        out["vms"] = mem.vms
        out["threads"] = p.num_threads()
        out["children"] = len(p.children(recursive=True))
        out["status"] = p.status()
        out["create_time"] = p.create_time()
        out["age"] = time.time() - p.create_time()
        try:
            out["nice"] = p.nice()
        except Exception:
            pass
    except Exception:
        pass

    try:
        p = ps.Process(os.getpid())
        try:
            out["open_files"] = len(p.open_files())
        except Exception:
            out["open_files"] = -1
        try:
            out["connections"] = len(p.net_connections())
        except Exception:
            out["connections"] = -1
    except Exception:
        pass

    out["ok"] = True
    _spark["proc"].append(out["cpu"])
    return out


# ============================================================
# SECTION 9 — TEMPERATURE + FANS
# ============================================================

def _collect_temperature() -> Dict[str, Any]:
    out: Dict[str, Any] = {
        "ok": False,
        "sensors": {},
        "fans": {},
        "battery": {},
    }
    ps = _ps()
    if ps is None:
        return out

    try:
        temps = ps.sensors_temperatures()
        for name, entries in (temps or {}).items():
            out["sensors"][name] = [
                {
                    "label": getattr(e, "label", "") or "",
                    "current": getattr(e, "current", 0) or 0,
                    "high": getattr(e, "high", 0) or 0,
                    "critical": getattr(e, "critical", 0) or 0,
                }
                for e in entries
            ]
    except Exception:
        pass

    try:
        fans = ps.sensors_fans()
        for name, entries in (fans or {}).items():
            out["fans"][name] = [
                {
                    "label": getattr(e, "label", "") or "",
                    "current": getattr(e, "current", 0) or 0,
                }
                for e in entries
            ]
    except Exception:
        pass

    try:
        bat = ps.sensors_battery()
        if bat:
            out["battery"] = {
                "percent": bat.percent,
                "plugged": bat.power_plugged,
                "time_left": bat.secsleft if bat.secsleft > 0 else -1,
            }
    except Exception:
        pass

    out["ok"] = True
    return out


# ============================================================
# SECTION 10 — TOP PROCESSES
# ============================================================

def _collect_top(sort_by: str = "cpu", limit: int = 10) -> List[Dict[str, Any]]:
    ps = _ps()
    if ps is None:
        return []

    out: List[Dict[str, Any]] = []
    try:
        for p in ps.process_iter(attrs=[
            "pid", "name", "cpu_percent", "memory_percent",
            "memory_info", "status", "username",
        ]):
            try:
                info = p.info
                mem_info = info.get("memory_info")
                out.append({
                    "pid": info.get("pid"),
                    "name": (info.get("name") or "")[:20],
                    "cpu": info.get("cpu_percent") or 0.0,
                    "mem_pct": info.get("memory_percent") or 0.0,
                    "rss": getattr(mem_info, "rss", 0) if mem_info else 0,
                    "status": info.get("status") or "",
                    "user": (info.get("username") or "")[:12],
                })
            except Exception:
                continue
    except Exception:
        return []

    if sort_by == "mem":
        out.sort(key=lambda x: x["mem_pct"], reverse=True)
    else:
        out.sort(key=lambda x: x["cpu"], reverse=True)

    return out[:limit]


# ============================================================
# SECTION 11 — KEYBOARD BUILDERS
# ============================================================

def _nav_kb(current: str = "overview") -> InlineKeyboardMarkup:
    """Standard nav row for server sub-panels."""
    def btn(page: str, icon: str, label: str) -> InlineKeyboardButton:
        mark = "✅ " if page == current else ""
        return InlineKeyboardButton(
            f"{mark}{icon} {F.sc(label)}",
            callback_data=f"adm:sv:{page}",
        )

    rows = [
        [
            btn("overview", "🖥️", "overview"),
            btn("cpu", "⚡", "cpu"),
        ],
        [
            btn("memory", "🧠", "memory"),
            btn("disk", "💽", "disk"),
        ],
        [
            btn("network", "🌐", "net"),
            btn("process", "⚙️", "process"),
        ],
        [
            btn("temp", "🌡️", "temp"),
            btn("top", "🏆", "top"),
        ],
    ]

    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['refresh']} {F.sc('refresh')}",
            callback_data=f"adm:sv:{current}",
        ),
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data="adm:home",
        ),
    ])
    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('close')}",
            callback_data="adm:close",
        ),
    ])

    return InlineKeyboardMarkup(rows)


# ============================================================
# SECTION 12 — OVERVIEW PAGE
# ============================================================

async def build() -> Tuple[str, InlineKeyboardMarkup]:
    """Main server overview."""
    cpu = _collect_cpu()
    mem = _collect_memory()
    disk = _collect_disk()
    net = _collect_network()
    proc = _collect_process()

    lines: List[str] = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"🖥️ <b>{F.fb('SERVER MONITOR')}</b>",
        F.DIV,
        "",
    ]

    # CPU
    cpu_pct = cpu["total"]
    lines.append(
        f"{F.EMO['cpu']} <b>{F.sc('cpu')}</b> · "
        f"<b>{cpu_pct:.1f}%</b> {_trend('cpu', cpu_pct)} "
        f"· <code>{cpu['logical']}c</code>"
    )
    lines.append(f"<code>{P.bar(cpu_pct, 'storage', width=14)}</code>")
    lines.append("")

    # RAM
    ram_pct = mem["virt_pct"]
    lines.append(
        f"{F.EMO['ram']} <b>{F.sc('ram')}</b> · "
        f"<b>{ram_pct:.1f}%</b> {_trend('ram', ram_pct)}"
    )
    lines.append(f"<code>{P.bar(ram_pct, 'storage', width=14)}</code>")
    lines.append(
        f"   {FM.size(mem['virt_used'])} / {FM.size(mem['virt_total'])}"
    )
    lines.append("")

    # Disk
    root = disk.get("root") or {}
    disk_pct = root.get("pct", 0.0)
    lines.append(
        f"{F.EMO['disk']} <b>{F.sc('disk')}</b> · "
        f"<b>{disk_pct:.1f}%</b> {_trend('disk', disk_pct)}"
    )
    lines.append(f"<code>{P.bar(disk_pct, 'storage', width=14)}</code>")
    lines.append(
        f"   {FM.size(root.get('used', 0))} / "
        f"{FM.size(root.get('total', 0))}"
    )
    lines.append("")

    # Network
    lines.append(
        f"{F.EMO['net']} <b>{F.sc('net')}</b> · "
        f"↓ <b>{FM.speed(net['rx_rate'])}</b> "
        f"↑ <b>{FM.speed(net['tx_rate'])}</b>"
    )
    lines.append("")

    # Process
    lines.append(F.DIV_S)
    lines.append(f"⚙️ <b>{F.fb('PROCESS')}</b>")
    lines.append(F.DIV_S)
    lines.append("")
    lines.append(
        f"{F.EMO['rocket']} CPU · <b>{proc['cpu']:.1f}%</b> "
        f"{_trend('proc_cpu', proc['cpu'])}"
    )
    lines.append(
        f"{F.EMO['ram']} RSS · <b>{FM.size(proc['rss'])}</b>"
    )
    lines.append(
        f"🧵 Threads · <b>{proc['threads']}</b> · "
        f"👶 Children · <b>{proc['children']}</b>"
    )
    lines.append(
        f"📁 Files · <b>{proc['open_files']}</b> · "
        f"🔌 Conns · <b>{proc['connections']}</b>"
    )
    lines.append(
        f"🕒 Age · <b>{FM.duration_short(proc['age'])}</b>"
    )
    lines.append("")

    # Load
    l1, l5, l15 = cpu.get("load", (0.0, 0.0, 0.0))
    lines.append(F.DIV_S)
    lines.append(
        f"📊 {F.sc('load avg')} · "
        f"<b>{l1:.2f}</b> / <b>{l5:.2f}</b> / <b>{l15:.2f}</b>"
    )
    lines.append("")

    # Sparkline
    lines.append(F.DIV_S)
    lines.append(f"{F.EMO['spark']} <b>{F.sc('sparkline')}</b>")
    lines.append(F.DIV_S)
    lines.append(f"CPU  <code>{_sparkline(_spark['cpu'], 20)}</code>")
    lines.append(f"RAM  <code>{_sparkline(_spark['ram'], 20)}</code>")
    lines.append(f"DISK <code>{_sparkline(_spark['disk'], 20)}</code>")
    lines.append("")

    lines.append(
        f"🕒 <code>{FM.datetime_()}</code>"
    )

    text = "\n".join(lines)[:4000]
    return text, _nav_kb("overview")


# ============================================================
# SECTION 13 — CPU PAGE
# ============================================================

async def build_cpu() -> Tuple[str, InlineKeyboardMarkup]:
    cpu = _collect_cpu()

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"⚡ <b>{F.fb('CPU DETAIL')}</b>",
        F.DIV,
        "",
        f"{F.EMO['cpu']} {F.sc('total')} · "
        f"<b>{cpu['total']:.1f}%</b> {_trend('cpu', cpu['total'])}",
        f"<code>{P.bar(cpu['total'], 'storage', width=16)}</code>",
        "",
        f"{F.EMO['info']} {F.sc('logical')} · <b>{cpu['logical']}</b>",
        f"{F.EMO['info']} {F.sc('physical')} · <b>{cpu['physical']}</b>",
    ]

    if cpu.get("freq_current"):
        lines.append(
            f"⚡ {F.sc('freq')} · "
            f"<b>{cpu['freq_current']:.0f} MHz</b>"
        )
        if cpu.get("freq_max"):
            lines.append(
                f"   range · {cpu['freq_min']:.0f} – "
                f"{cpu['freq_max']:.0f} MHz"
            )

    l1, l5, l15 = cpu.get("load", (0.0, 0.0, 0.0))
    lines += [
        "",
        F.DIV_S,
        f"📊 {F.sc('load avg')}",
        F.DIV_S,
        f"1m  <b>{l1:.2f}</b>",
        f"5m  <b>{l5:.2f}</b>",
        f"15m <b>{l15:.2f}</b>",
        "",
    ]

    per_core = cpu.get("per_core") or []
    if per_core:
        lines.append(F.DIV_S)
        lines.append(f"🔢 <b>{F.sc('per core')}</b>")
        lines.append(F.DIV_S)
        lines.append("")
        for i, val in enumerate(per_core):
            lines.append(
                f"C{i:02d} "
                f"{P.bar(val, 'storage', width=8, show_percent=False)} "
                f"<b>{val:.0f}%</b>"
            )

    lines += [
        "",
        F.DIV_S,
        f"🔁 {F.sc('ctx switches')} · "
        f"<b>{FM.num(cpu.get('ctx_switches', 0))}</b>",
        f"⚡ {F.sc('interrupts')} · "
        f"<b>{FM.num(cpu.get('interrupts', 0))}</b>",
        "",
        f"🕒 <code>{FM.datetime_()}</code>",
    ]

    text = "\n".join(lines)[:4000]
    return text, _nav_kb("cpu")


# ============================================================
# SECTION 14 — MEMORY PAGE
# ============================================================

async def build_memory() -> Tuple[str, InlineKeyboardMarkup]:
    mem = _collect_memory()

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"🧠 <b>{F.fb('MEMORY DETAIL')}</b>",
        F.DIV,
        "",
        f"{F.EMO['ram']} <b>{F.sc('virtual')}</b> · "
        f"<b>{mem['virt_pct']:.1f}%</b> "
        f"{_trend('ram', mem['virt_pct'])}",
        f"<code>{P.bar(mem['virt_pct'], 'storage', width=16)}</code>",
        "",
        f"💾 Total · <b>{FM.size(mem['virt_total'])}</b>",
        f"📊 Used  · <b>{FM.size(mem['virt_used'])}</b>",
        f"🟢 Free  · <b>{FM.size(mem['virt_free'])}</b>",
        "",
        F.DIV_S,
        f"🔁 <b>{F.sc('swap')}</b> · "
        f"<b>{mem['swap_pct']:.1f}%</b>",
        F.DIV_S,
        "",
        f"<code>{P.bar(mem['swap_pct'], 'storage', width=16)}</code>",
        "",
        f"💾 Total · <b>{FM.size(mem['swap_total'])}</b>",
        f"📊 Used  · <b>{FM.size(mem['swap_used'])}</b>",
        f"🟢 Free  · <b>{FM.size(mem['swap_free'])}</b>",
        "",
    ]

    # Top by RAM
    tops = _collect_top(sort_by="mem", limit=8)
    if tops:
        lines.append(F.DIV_S)
        lines.append(f"🏆 <b>{F.sc('top by ram')}</b>")
        lines.append(F.DIV_S)
        lines.append("")
        for i, p in enumerate(tops, 1):
            lines.append(
                f"{i:02d}. <code>{p['name'][:16]}</code> · "
                f"<b>{p['mem_pct']:.1f}%</b> "
                f"· {FM.size(p['rss'])}"
            )

    lines += [
        "",
        f"🕒 <code>{FM.datetime_()}</code>",
    ]

    text = "\n".join(lines)[:4000]
    return text, _nav_kb("memory")


# ============================================================
# SECTION 15 — DISK PAGE
# ============================================================

async def build_disk() -> Tuple[str, InlineKeyboardMarkup]:
    disk = _collect_disk()

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"💽 <b>{F.fb('DISK DETAIL')}</b>",
        F.DIV,
        "",
    ]

    # Root
    root = disk.get("root") or {}
    root_pct = root.get("pct", 0.0)
    lines += [
        f"{F.EMO['disk']} <b>{F.sc('root /')}</b>",
        f"<code>{P.bar(root_pct, 'storage', width=14)}</code>",
        f"📊 {FM.size(root.get('used', 0))} / "
        f"{FM.size(root.get('total', 0))}",
        f"🟢 {FM.size(root.get('free', 0))} free",
        "",
    ]

    # Partitions
    parts = disk.get("partitions") or []
    if parts:
        lines.append(F.DIV_S)
        lines.append(f"📁 <b>{F.sc('partitions')}</b> "
                     f"· <b>{len(parts)}</b>")
        lines.append(F.DIV_S)
        lines.append("")

        for p in parts[:6]:
            pct = p.get("pct", 0.0)
            lines.append(
                f"{P.storage_color(pct)} "
                f"<code>{p['mountpoint']}</code> "
                f"· <b>{pct:.0f}%</b>"
            )
            lines.append(
                f"   <code>{P.bar(pct, 'storage', width=10, show_percent=False)}</code>"
            )
            lines.append(
                f"   {FM.size(p['used'])} / {FM.size(p['total'])} "
                f"· {p.get('fstype', '?')}"
            )
            lines.append("")

        if len(parts) > 6:
            lines.append(f"<i>… +{len(parts) - 6} more</i>")
            lines.append("")

    # IO rates
    lines += [
        F.DIV_S,
        f"🔁 <b>{F.sc('disk io')}</b>",
        F.DIV_S,
        "",
        f"📖 Read  · <b>{FM.speed(disk['io_read_rate'])}</b>",
        f"📝 Write · <b>{FM.speed(disk['io_write_rate'])}</b>",
        "",
        f"📖 Total read  · {FM.size(disk['io_read_total'])}",
        f"📝 Total write · {FM.size(disk['io_write_total'])}",
        "",
        f"🕒 <code>{FM.datetime_()}</code>",
    ]

    text = "\n".join(lines)[:4000]
    return text, _nav_kb("disk")


# ============================================================
# SECTION 16 — NETWORK PAGE
# ============================================================

async def build_network() -> Tuple[str, InlineKeyboardMarkup]:
    net = _collect_network()

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"🌐 <b>{F.fb('NETWORK DETAIL')}</b>",
        F.DIV,
        "",
        f"{F.EMO['net']} <b>{F.sc('throughput')}</b>",
        "",
        f"⬇️ {F.sc('receive')} · <b>{FM.speed(net['rx_rate'])}</b>",
        f"⬆️ {F.sc('send')}    · <b>{FM.speed(net['tx_rate'])}</b>",
        "",
        f"📥 Total RX · {FM.size(net['rx_total'])}",
        f"📤 Total TX · {FM.size(net['tx_total'])}",
        f"📦 Packets RX · {FM.num(net['packets_rx'])}",
        f"📦 Packets TX · {FM.num(net['packets_tx'])}",
        "",
    ]

    # Interfaces
    ifaces = net.get("interfaces") or []
    if ifaces:
        lines.append(F.DIV_S)
        lines.append(f"🔌 <b>{F.sc('interfaces')}</b> "
                     f"· <b>{len(ifaces)}</b>")
        lines.append(F.DIV_S)
        lines.append("")

        for iface in ifaces[:5]:
            lines.append(
                f"• <code>{iface['name']}</code>"
            )
            lines.append(
                f"  ⬇️ {FM.size(iface['rx'])} "
                f"· ⬆️ {FM.size(iface['tx'])}"
            )
            if iface.get("err_in") or iface.get("err_out"):
                lines.append(
                    f"  ⚠️ err in={iface['err_in']} out={iface['err_out']}"
                )
            if iface.get("drop_in") or iface.get("drop_out"):
                lines.append(
                    f"  ⚠️ drop in={iface['drop_in']} out={iface['drop_out']}"
                )
            lines.append("")

        if len(ifaces) > 5:
            lines.append(f"<i>… +{len(ifaces) - 5} more</i>")
            lines.append("")

    lines += [
        F.DIV_S,
        f"{F.EMO['spark']} <b>{F.sc('sparkline')}</b>",
        F.DIV_S,
        f"RX <code>{_sparkline(_spark['rx'], 20)}</code>",
        f"TX <code>{_sparkline(_spark['tx'], 20)}</code>",
        "",
        f"🕒 <code>{FM.datetime_()}</code>",
    ]

    text = "\n".join(lines)[:4000]
    return text, _nav_kb("network")


# ============================================================
# SECTION 17 — PROCESS PAGE
# ============================================================

async def build_process() -> Tuple[str, InlineKeyboardMarkup]:
    proc = _collect_process()

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"⚙️ <b>{F.fb('PROCESS DETAIL')}</b>",
        F.DIV,
        "",
        f"🆔 PID · <code>{proc['pid']}</code>",
        f"📛 Status · <b>{F.sc(proc['status'])}</b>",
        f"🕒 Age · <b>{FM.duration_short(proc['age'])}</b>",
        f"⚡ Nice · <b>{proc.get('nice', 0)}</b>",
        "",
        F.DIV_S,
        f"{F.EMO['cpu']} <b>{F.sc('cpu usage')}</b>",
        F.DIV_S,
        f"<code>{P.bar(proc['cpu'], 'storage', width=14)}</code>",
        "",
        F.DIV_S,
        f"{F.EMO['ram']} <b>{F.sc('memory')}</b>",
        F.DIV_S,
        f"📊 RSS · <b>{FM.size(proc['rss'])}</b>",
        f"📊 VMS · <b>{FM.size(proc['vms'])}</b>",
        "",
        F.DIV_S,
        f"🔧 <b>{F.sc('resources')}</b>",
        F.DIV_S,
        f"🧵 Threads · <b>{proc['threads']}</b>",
        f"👶 Children · <b>{proc['children']}</b>",
        f"📁 Open files · <b>{proc['open_files']}</b>",
        f"🔌 Connections · <b>{proc['connections']}</b>",
        "",
        F.DIV_S,
        f"{F.EMO['spark']} <b>{F.sc('cpu sparkline')}</b>",
        F.DIV_S,
        f"<code>{_sparkline(_spark['proc'], 20)}</code>",
        "",
        f"🕒 <code>{FM.datetime_()}</code>",
    ]

    text = "\n".join(lines)[:4000]
    return text, _nav_kb("process")


# ============================================================
# SECTION 18 — TEMPERATURE PAGE
# ============================================================

async def build_temp() -> Tuple[str, InlineKeyboardMarkup]:
    temp = _collect_temperature()

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"🌡️ <b>{F.fb('TEMPERATURE / FANS')}</b>",
        F.DIV,
        "",
    ]

    sensors = temp.get("sensors") or {}
    if sensors:
        lines.append(F.DIV_S)
        lines.append(f"🌡️ <b>{F.sc('sensors')}</b>")
        lines.append(F.DIV_S)
        lines.append("")
        for name, entries in sensors.items():
            lines.append(f"<b>{F.sc(name)}</b>")
            for e in entries[:4]:
                cur = e.get("current", 0)
                crit = e.get("critical", 0)
                pct = (cur / crit * 100) if crit else (cur / 100 * 100)
                label = e.get("label") or "?"
                lines.append(
                    f"  {P.storage_color(pct)} "
                    f"<code>{label[:16]}</code> · "
                    f"<b>{cur:.0f}°C</b>"
                )
            lines.append("")
    else:
        lines.append(f"⚪ {F.sc('no sensors available')}")
        lines.append("")

    fans = temp.get("fans") or {}
    if fans:
        lines.append(F.DIV_S)
        lines.append(f"🌀 <b>{F.sc('fans')}</b>")
        lines.append(F.DIV_S)
        lines.append("")
        for name, entries in fans.items():
            for e in entries[:4]:
                label = e.get("label") or "?"
                rpm = e.get("current", 0)
                lines.append(
                    f"  🌀 <code>{label[:16]}</code> · <b>{rpm} RPM</b>"
                )
        lines.append("")

    bat = temp.get("battery") or {}
    if bat:
        lines.append(F.DIV_S)
        lines.append(f"🔋 <b>{F.sc('battery')}</b>")
        F.DIV_S
        lines.append(f"🔋 {bat.get('percent', 0):.0f}% "
                     f"· {'🔌 plugged' if bat.get('plugged') else '🔋 unplugged'}")
        lines.append("")

    lines += [
        f"🕒 <code>{FM.datetime_()}</code>",
    ]

    text = "\n".join(lines)[:4000]
    return text, _nav_kb("temp")


# ============================================================
# SECTION 19 — TOP PAGE
# ============================================================

async def build_top(sort_by: str = "cpu") -> Tuple[str, InlineKeyboardMarkup]:
    tops = _collect_top(sort_by=sort_by, limit=12)

    label = "CPU" if sort_by == "cpu" else "RAM"

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"🏆 <b>{F.fb('TOP PROCESSES')}</b> · {label}",
        F.DIV,
        "",
    ]

    if not tops:
        lines.append(f"⚪ {F.sc('no process data')}")
    else:
        for i, p in enumerate(tops, 1):
            val = p["cpu"] if sort_by == "cpu" else p["mem_pct"]
            pct = min(100.0, val)
            lines.append(
                f"<b>{i:02d}.</b> <code>{p['name']}</code> "
                f"· PID <code>{p['pid']}</code>"
            )
            lines.append(
                f"   {P.storage_color(pct)} "
                f"<code>{P.bar(pct, 'storage', width=10, show_percent=False)}</code> "
                f"<b>{val:.1f}%</b>"
            )
            lines.append(
                f"   💾 {FM.size(p['rss'])} · "
                f"👤 {F.sc(p['user'])}"
            )
            lines.append("")

    rows = [
        [
            InlineKeyboardButton(
                f"{'✅ ' if sort_by == 'cpu' else ''}⚡ {F.sc('sort by cpu')}",
                callback_data="adm:sv:top:cpu",
            ),
            InlineKeyboardButton(
                f"{'✅ ' if sort_by == 'mem' else ''}🧠 {F.sc('sort by ram')}",
                callback_data="adm:sv:top:mem",
            ),
        ],
        [
            InlineKeyboardButton(
                f"{F.EMO['refresh']} {F.sc('refresh')}",
                callback_data=f"adm:sv:top:{sort_by}",
            ),
            InlineKeyboardButton(
                f"{F.EMO['back']} {F.sc('back')}",
                callback_data="adm:sv:overview",
            ),
        ],
        [
            InlineKeyboardButton(
                f"{F.EMO['cross']} {F.sc('close')}",
                callback_data="adm:close",
            ),
        ],
    ]

    lines.append(f"🕒 <code>{FM.datetime_()}</code>")

    text = "\n".join(lines)[:4000]
    return text, InlineKeyboardMarkup(rows)


# ============================================================
# SECTION 20 — ROUTER HELPER
# ============================================================

async def route(page: str, arg: Optional[str] = None) -> Tuple[str, InlineKeyboardMarkup]:
    """Route a sub-page name → (text, kb)."""
    if page == "overview":
        return await build()
    if page == "cpu":
        return await build_cpu()
    if page == "memory":
        return await build_memory()
    if page == "disk":
        return await build_disk()
    if page == "network":
        return await build_network()
    if page == "process":
        return await build_process()
    if page == "temp":
        return await build_temp()
    if page == "top":
        sort_by = arg if arg in ("cpu", "mem") else "cpu"
        return await build_top(sort_by)
    return await build()


# ============================================================
# SECTION 21 — SNAPSHOT
# ============================================================

def snapshot() -> Dict[str, Any]:
    return {
        "cpu": list(_spark["cpu"])[-1] if _spark["cpu"] else 0,
        "ram": list(_spark["ram"])[-1] if _spark["ram"] else 0,
        "disk": list(_spark["disk"])[-1] if _spark["disk"] else 0,
    }


# ============================================================
# PUBLIC EXPORTS
# ============================================================

__all__ = [
    "build",
    "build_cpu",
    "build_memory",
    "build_disk",
    "build_network",
    "build_process",
    "build_temp",
    "build_top",
    "route",
    "snapshot",
]
