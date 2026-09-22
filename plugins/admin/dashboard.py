# ============================================================
# 🏨 DOWNTOWN VILLA — LIVE DASHBOARD
# ============================================================
#
# Auto-refreshing every 5s. Nothing is stale.
#
# Sections:
#   1. Header + uptime + trends
#   2. System health (CPU/RAM/Disk/Net) — storage bars
#   3. Database shards — per pool, per shard
#   4. Bot stats (users, searches, files, etc.)
#   5. Cache namespaces + hit rate
#   6. Active tasks — progress bars
#   7. Top searches
#   8. Sparkline (last 30 samples)
#   9. Overall health
#
# Every section uses the color-bar engine (utils/progress.py).
#
# ============================================================

from __future__ import annotations

import logging
import os
import shutil
import time
from collections import deque
from datetime import datetime
from typing import Any, Deque, Dict, List, Optional

from pyrogram.enums import ParseMode
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from core import config
from utils import fonts as F
from utils import format as FM
from utils import progress as P

logger = logging.getLogger(__name__)


# ============================================================
# SECTION 1 — SPARKLINE STATE
# ============================================================

# Keep last 30 samples per metric
_SPARK_LEN = 30
_spark: Dict[str, Deque[float]] = {
    "cpu": deque(maxlen=_SPARK_LEN),
    "ram": deque(maxlen=_SPARK_LEN),
    "disk": deque(maxlen=_SPARK_LEN),
    "net_in": deque(maxlen=_SPARK_LEN),
    "net_out": deque(maxlen=_SPARK_LEN),
}

# Network delta tracking
_net_last = {"t": 0.0, "in": 0, "out": 0}

# Trend cache
_last_snapshot: Dict[str, float] = {}


# ============================================================
# SECTION 2 — SAMPLE COLLECTORS
# ============================================================

def _try_import_psutil():
    try:
        import psutil
        return psutil
    except ImportError:
        return None


def _collect_system() -> Dict[str, Any]:
    """Collect CPU / RAM / Disk / Net."""
    psutil = _try_import_psutil()
    out: Dict[str, Any] = {
        "ok": False,
        "cpu": 0.0, "cpu_count": 0,
        "ram_pct": 0.0, "ram_used": 0, "ram_total": 0,
        "disk_pct": 0.0, "disk_used": 0, "disk_total": 0,
        "net_in": 0.0, "net_out": 0.0,
        "load": (0.0, 0.0, 0.0),
    }

    if psutil is None:
        return out

    try:
        out["cpu"] = psutil.cpu_percent(interval=0.05)
        out["cpu_count"] = psutil.cpu_count(logical=True) or 0
    except Exception:
        pass

    try:
        mem = psutil.virtual_memory()
        out["ram_pct"] = mem.percent
        out["ram_used"] = mem.used
        out["ram_total"] = mem.total
    except Exception:
        pass

    try:
        disk = shutil.disk_usage("/")
        out["disk_used"] = disk.used
        out["disk_total"] = disk.total
        out["disk_pct"] = (disk.used / disk.total * 100) if disk.total else 0.0
    except Exception:
        pass

    try:
        net = psutil.net_io_counters()
        now = time.time()
        prev = _net_last
        if prev["t"]:
            dt = max(0.001, now - prev["t"])
            out["net_in"] = (net.bytes_recv - prev["in"]) / dt
            out["net_out"] = (net.bytes_sent - prev["out"]) / dt
        _net_last["t"] = now
        _net_last["in"] = net.bytes_recv
        _net_last["out"] = net.bytes_sent
    except Exception:
        pass

    try:
        out["load"] = os.getloadavg()
    except Exception:
        pass

    out["ok"] = True

    # Push to sparkline
    _spark["cpu"].append(out["cpu"])
    _spark["ram"].append(out["ram_pct"])
    _spark["disk"].append(out["disk_pct"])
    _spark["net_in"].append(out["net_in"])
    _spark["net_out"].append(out["net_out"])

    return out


def _collect_process() -> Dict[str, Any]:
    psutil = _try_import_psutil()
    out = {"cpu": 0.0, "rss": 0, "vms": 0, "threads": 0}
    if psutil is None:
        return out
    try:
        p = psutil.Process(os.getpid())
        out["cpu"] = p.cpu_percent(interval=0.05)
        mem = p.memory_info()
        out["rss"] = mem.rss
        out["vms"] = mem.vms
        out["threads"] = p.num_threads()
    except Exception:
        pass
    return out


async def _collect_db() -> Dict[str, Any]:
    """Collect all shards from all pools."""
    out: Dict[str, Any] = {
        "pools": {},
        "total_shards": 0,
        "online_shards": 0,
    }
    try:
        from database import db_registry
        snap = await db_registry.snapshot()
        out["pools"] = snap.get("pools", {})
        for pool_name, info in out["pools"].items():
            out["total_shards"] += info.get("total", 0)
            out["online_shards"] += info.get("online", 0)
    except Exception as e:
        logger.debug(f"[DASH] db snapshot: {e}")
    return out


def _collect_cache() -> Dict[str, Any]:
    try:
        from utils import cache as C
        return {
            "total": C.cache.total_entries(),
            "namespaces": C.cache.stats(),
        }
    except Exception:
        return {"total": 0, "namespaces": []}


def _collect_tasks() -> List[Dict[str, Any]]:
    try:
        from core import flow_engine as FE
        runs = FE.active_runs()
        out = []
        for r in runs[:8]:
            cfg = r.current_step_cfg() or {}
            steps_total = len(r.flow.sorted_steps())
            out.append({
                "run_id": r.run_id[:8],
                "user_id": r.user_id,
                "flow": r.flow_name,
                "step": r.step_index + 1,
                "total": steps_total,
                "step_type": cfg.get("type", "?"),
                "age": time.time() - r.started_at,
            })
        return out
    except Exception:
        return []


def _collect_bot_stats() -> Dict[str, Any]:
    """Bot event stats from the tracker."""
    try:
        # Prefer new centralized stats
        from plugins.admin import stats as _stats_mod
        return _stats_mod.live_snapshot()
    except Exception:
        pass

    # Fallback minimal
    return {
        "users": 0, "searches": 0, "commands": 0,
        "callbacks": 0, "files_sent": 0, "errors": 0,
    }


def _collect_uptime() -> float:
    try:
        from core.client import client as c
        if c is not None and getattr(c, "started_at", None):
            return time.time() - c.started_at
    except Exception:
        pass
    return 0.0


# ============================================================
# SECTION 3 — SPARKLINE RENDERER
# ============================================================

_SPARK_CHARS = "▁▂▃▄▅▆▇█"


def _render_sparkline(samples: Deque[float], width: int = 20) -> str:
    """Return a tiny sparkline of the last N samples."""
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


# ============================================================
# SECTION 4 — TREND
# ============================================================

def _trend(key: str, value: float) -> str:
    """Compare with last snapshot — return ↑↓→."""
    prev = _last_snapshot.get(key)
    _last_snapshot[key] = value
    if prev is None:
        return "→"
    delta = value - prev
    if delta > 0.5:
        return "↑"
    if delta < -0.5:
        return "↓"
    return "→"


# ============================================================
# SECTION 5 — MAIN BUILDER
# ============================================================

async def build() -> tuple:
    """Build the live dashboard text + keyboard."""
    sys_m = _collect_system()
    proc = _collect_process()
    db = await _collect_db()
    cache = _collect_cache()
    tasks = _collect_tasks()
    bot = _collect_bot_stats()
    uptime = _collect_uptime()

    # Capacity used from DB_CAPACITY_MB env
    db_cap = config.DB_CAPACITY_MB

    # ────────── HEADER ──────────
    lines: List[str] = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"{F.EMO['bar']} <b>{F.fb('LIVE DASHBOARD')}</b>",
        F.DIV,
        "",
        f"{F.EMO['clock']} {F.sc('uptime')} · "
        f"<b>{FM.duration_short(uptime)}</b>",
        f"{F.EMO['gear']} {F.sc('admins')} · "
        f"<b>{len(config.ADMINS)}</b>",
        f"🕒 <code>{FM.datetime_()}</code>",
        "",
    ]

    # ────────── SYSTEM HEALTH ──────────
    lines.append(F.DIV_S)
    lines.append(f"🖥️ <b>{F.fb('SYSTEM HEALTH')}</b>")
    lines.append(F.DIV_S)
    lines.append("")

    if sys_m["ok"]:
        cpu = sys_m["cpu"]
        ram = sys_m["ram_pct"]
        disk = sys_m["disk_pct"]

        lines.append(
            f"{F.EMO['cpu']} {F.sc('cpu')} · "
            f"<b>{cpu:.1f}%</b> {_trend('cpu', cpu)}"
        )
        lines.append(f"<code>{P.bar(cpu, 'storage')}</code>")
        lines.append("")

        lines.append(
            f"{F.EMO['ram']} {F.sc('ram')} · "
            f"<b>{ram:.1f}%</b> {_trend('ram', ram)}"
        )
        lines.append(f"<code>{P.bar(ram, 'storage')}</code>")
        lines.append("")

        lines.append(
            f"{F.EMO['disk']} {F.sc('disk')} · "
            f"<b>{disk:.1f}%</b> {_trend('disk', disk)}"
        )
        lines.append(f"<code>{P.bar(disk, 'storage')}</code>")
        lines.append("")

        lines.append(
            f"{F.EMO['net']} {F.sc('net')} · "
            f"↓ <b>{FM.speed(sys_m['net_in'])}</b> "
            f"↑ <b>{FM.speed(sys_m['net_out'])}</b>"
        )
        lines.append("")
        lines.append(f"{F.EMO['rocket']} {F.sc('process')} · "
                     f"CPU <b>{proc['cpu']:.1f}%</b> "
                     f"· RAM <b>{FM.size_short(proc['rss'])}</b> "
                     f"· 🧵 <b>{proc['threads']}</b>")
    else:
        lines.append(f"{F.EMO['cross']} {F.sc('psutil unavailable')}")

    lines.append("")

    # ────────── DATABASES ──────────
    lines.append(F.DIV_S)
    lines.append(f"{F.EMO['db']} <b>{F.fb('DATABASES')}</b> "
                 f"· {db['online_shards']}/{db['total_shards']} 🟢")
    lines.append(F.DIV_S)
    lines.append("")

    pool_icons = {
        "system": "⚙️", "user": "👤",
        "media": "🎬", "backup": "💾",
    }
    for pool_name, info in db.get("pools", {}).items():
        icon = pool_icons.get(pool_name, "📦")
        lines.append(
            f"{icon} <b>{F.sc(pool_name)}</b> · "
            f"<code>{info.get('online', 0)}/{info.get('total', 0)}</code> "
            f"· {FM.size(info.get('total_used_mb', 0) * 1024 * 1024)}"
        )
        for shard in info.get("shards", [])[:3]:
            if not shard.get("online"):
                lines.append(f"  🔴 <code>{shard.get('label', '?')}</code> offline")
                continue
            pct = shard.get("pct", 0.0)
            used = shard.get("used_mb", 0.0)
            threshold = shard.get("threshold_mb", db_cap)
            lines.append(
                f"  {P.storage_color(pct)} "
                f"<code>{shard.get('label', '?')}</code> · "
                f"{P.bar(pct, 'storage', width=6, show_percent=False)} "
                f"<b>{pct:.0f}%</b> "
                f"· {used:.0f}/{threshold}MB"
            )
        if len(info.get("shards", [])) > 3:
            lines.append(f"  <i>… +{len(info['shards']) - 3} more</i>")
        lines.append("")

    # ────────── BOT STATS ──────────
    lines.append(F.DIV_S)
    lines.append(f"{F.EMO['chart']} <b>{F.fb('BOT STATS')}</b>")
    lines.append(F.DIV_S)
    lines.append("")

    lines.append(
        f"{F.EMO['users']} {F.sc('users')} · "
        f"<b>{FM.num(bot.get('users', 0))}</b>"
    )
    lines.append(
        f"{F.EMO['search']} {F.sc('searches')} · "
        f"<b>{FM.num(bot.get('searches', 0))}</b>"
    )
    lines.append(
        f"{F.EMO['send']} {F.sc('files sent')} · "
        f"<b>{FM.num(bot.get('files_sent', 0))}</b>"
    )
    lines.append(
        f"⌨️ {F.sc('commands')} · "
        f"<b>{FM.num(bot.get('commands', 0))}</b>"
    )
    lines.append(
        f"{F.EMO['warn']} {F.sc('errors')} · "
        f"<b>{FM.num(bot.get('errors', 0))}</b>"
    )
    lines.append("")

    # ────────── CACHE ──────────
    lines.append(F.DIV_S)
    lines.append(f"{F.EMO['package']} <b>{F.fb('CACHE')}</b> "
                 f"· <b>{FM.num(cache['total'])}</b>")
    lines.append(F.DIV_S)
    lines.append("")

    for ns in cache.get("namespaces", [])[:4]:
        name = ns.get("name", "?")
        size = ns.get("size", 0)
        hit_rate = ns.get("hit_rate", 0.0)
        max_e = max(1, ns.get("max_entries", 1))
        lines.append(
            f"• <code>{name}</code> · "
            f"{P.bar(size / max_e * 100, 'storage', width=5, show_percent=False)} "
            f"<b>{size}</b> "
            f"· {hit_rate:.0f}% hit"
        )
    if not cache.get("namespaces"):
        lines.append(f"⚪ {F.sc('empty')}")
    lines.append("")

    # ────────── TASKS ──────────
    lines.append(F.DIV_S)
    lines.append(f"{F.EMO['rocket']} <b>{F.fb('ACTIVE TASKS')}</b> "
                 f"· <b>{len(tasks)}</b>")
    lines.append(F.DIV_S)
    lines.append("")

    for t in tasks[:4]:
        pct = (t["step"] / max(1, t["total"])) * 100
        lines.append(
            f"• <code>{t['run_id']}</code> · "
            f"{F.sc(t['flow'])} · "
            f"{P.bar(pct, 'indexing', width=5, show_percent=False)} "
            f"<b>{t['step']}/{t['total']}</b>"
        )
    if not tasks:
        lines.append(f"⚪ {F.sc('idle')}")
    lines.append("")

    # ────────── SPARKLINE ──────────
    lines.append(F.DIV_S)
    lines.append(f"{F.EMO['spark']} <b>{F.fb('SPARKLINE')}</b> "
                 f"· last {_SPARK_LEN} samples")
    lines.append(F.DIV_S)
    lines.append("")
    lines.append(
        f"CPU  <code>{_render_sparkline(_spark['cpu'], 20)}</code>"
    )
    lines.append(
        f"RAM  <code>{_render_sparkline(_spark['ram'], 20)}</code>"
    )
    lines.append(
        f"DISK <code>{_render_sparkline(_spark['disk'], 20)}</code>"
    )
    lines.append("")

    # ────────── HEALTH SUMMARY ──────────
    health_score = 100.0
    if sys_m["cpu"] > 90:
        health_score -= 10
    if sys_m["ram_pct"] > 90:
        health_score -= 10
    if sys_m["disk_pct"] > 90:
        health_score -= 10
    if bot.get("errors", 0) > 50:
        health_score -= 10

    lines.append(F.DIV)
    lines.append(
        f"{F.EMO['trophy']} <b>{F.fb('OVERALL HEALTH')}</b> · "
        f"<b>{health_score:.0f}%</b>"
    )
    lines.append(f"<code>{P.bar(health_score, 'indexing', width=16)}</code>")

    text = "\n".join(lines)

    # Truncate safely
    if len(text) > 4000:
        text = text[:3950] + "\n…truncated"

    # ────────── KEYBOARD ──────────
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"{F.EMO['refresh']} {F.sc('refresh')}",
                callback_data="adm:page:dashboard",
            ),
            InlineKeyboardButton(
                f"{F.EMO['db']} {F.sc('databases')}",
                callback_data="adm:page:databases",
            ),
        ],
        [
            InlineKeyboardButton(
                f"{F.EMO['server']} {F.sc('server')}",
                callback_data="adm:page:server",
            ),
            InlineKeyboardButton(
                f"❤️ {F.sc('health')}",
                callback_data="adm:page:health",
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

    return text, kb


# ============================================================
# SECTION 6 — SNAPSHOT
# ============================================================

def snapshot() -> Dict[str, Any]:
    """Lightweight status for other modules."""
    return {
        "cpu": list(_spark["cpu"])[-1] if _spark["cpu"] else 0,
        "ram": list(_spark["ram"])[-1] if _spark["ram"] else 0,
        "disk": list(_spark["disk"])[-1] if _spark["disk"] else 0,
    }


# ============================================================
# PUBLIC EXPORTS
# ============================================================

__all__ = ["build", "snapshot"]
