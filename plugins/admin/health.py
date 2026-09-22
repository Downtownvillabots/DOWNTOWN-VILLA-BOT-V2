# ============================================================
# 🏨 DOWNTOWN VILLA — HEALTH CHECK CENTER (ULTIMATE)
# ============================================================
#
# Full subsystem health check — every major component.
#
# Checks:
#   • Telegram client       (online, latency)
#   • Databases            (all 4 pools, per shard)
#   • Cache                (per namespace hit rate)
#   • Tasks                (running / failed)
#   • Flow engine          (active runs)
#   • Locks                (rate limiter status)
#   • Rocket               (uvloop + orjson)
#   • Logs                 (recent errors + warnings)
#   • Client uptime
#
# Verdict: overall health score 0-100 with color bar.
#
# ============================================================

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from pyrogram.enums import ParseMode
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from core import config
from utils import fonts as F
from utils import format as FM
from utils import progress as P

logger = logging.getLogger(__name__)


# ============================================================
# SECTION 1 — SUB-CHECKS
# ============================================================

async def _check_client() -> Dict[str, Any]:
    out = {"name": "Telegram", "ok": False, "detail": "", "extra": {}}
    try:
        from core.client import client as c
        if c is None:
            out["detail"] = "not started"
            return out

        t0 = time.perf_counter()
        me = await c.identity()
        latency_ms = (time.perf_counter() - t0) * 1000.0

        out["ok"] = True
        out["detail"] = f"@{me.username}"
        out["extra"] = {
            "latency_ms": round(latency_ms, 1),
            "bot_id": me.id,
            "uptime": c.uptime if hasattr(c, "uptime") else 0,
        }
    except Exception as e:
        out["detail"] = str(e)[:80]
    return out


async def _check_databases() -> Dict[str, Any]:
    out = {"name": "Databases", "ok": False, "detail": "", "extra": {}}
    try:
        from database import db_manager as mgr
        if mgr is None:
            out["detail"] = "no manager"
            return out

        total = 0
        online = 0
        used_mb = 0.0
        for pool_name in ("system", "user", "media", "backup"):
            entries = mgr.entries(pool_name)
            total += len(entries)
            for e in entries:
                if e.online:
                    online += 1
                    # best-effort used_mb
                    try:
                        stats = await e.db.command("dbStats")
                        used_mb += (
                            (stats.get("storageSize", 0) or 0)
                            + (stats.get("indexSize", 0) or 0)
                        ) / (1024 * 1024)
                    except Exception:
                        pass

        out["ok"] = (online == total) if total else False
        out["detail"] = f"{online}/{total} shards online"
        out["extra"] = {
            "total": total, "online": online,
            "used_mb": round(used_mb, 2),
        }
    except Exception as e:
        out["detail"] = str(e)[:80]
    return out


def _check_cache() -> Dict[str, Any]:
    out = {"name": "Cache", "ok": False, "detail": "", "extra": {}}
    try:
        from utils import cache as C
        stats = C.cache.stats()
        total_hits = sum(n.hits for n in stats)
        total_miss = sum(n.misses for n in stats)
        req = total_hits + total_miss
        rate = (total_hits / req * 100) if req else 0.0

        out["ok"] = True
        out["detail"] = f"{len(stats)} namespaces"
        out["extra"] = {
            "hit_rate": round(rate, 1),
            "entries": C.cache.total_entries(),
            "namespaces": len(stats),
        }
    except Exception as e:
        out["detail"] = str(e)[:80]
    return out


def _check_tasks() -> Dict[str, Any]:
    out = {"name": "Tasks", "ok": True, "detail": "", "extra": {}}
    try:
        from plugins.admin import tasks as T
        snap = T.snapshot()
        running = snap.get("running", 0)
        counters = snap.get("counters", {})

        out["detail"] = f"{running} running"
        out["extra"] = {
            "running": running,
            "started_total": counters.get("started_total", 0),
            "failed_total": counters.get("failed_total", 0),
        }

        # Unhealthy if too many failures
        failed = counters.get("failed_total", 0)
        started = counters.get("started_total", 0)
        if started > 0 and failed / started > 0.5:
            out["ok"] = False
    except Exception as e:
        out["detail"] = str(e)[:80]
    return out


def _check_flow_engine() -> Dict[str, Any]:
    out = {"name": "Flow Engine", "ok": True, "detail": "", "extra": {}}
    try:
        from core import flow_engine as FE
        runs = FE.active_runs()
        flows_registered = 0
        try:
            from core.flow_engine import list_flows
            flows_registered = len(list_flows())
        except Exception:
            pass

        out["detail"] = f"{len(runs)} active runs"
        out["extra"] = {
            "active_runs": len(runs),
            "flows": flows_registered,
        }
    except Exception as e:
        out["detail"] = str(e)[:80]
        out["ok"] = False
    return out


def _check_locks() -> Dict[str, Any]:
    out = {"name": "Rate Limits", "ok": True, "detail": "", "extra": {}}
    try:
        from utils import locks as LK
        stats = LK.stats()
        rate_limiters = stats.get("rate_limiters", {})
        total_allowed = sum(r.get("allowed", 0) for r in rate_limiters.values())
        total_denied = sum(r.get("denied", 0) for r in rate_limiters.values())

        out["detail"] = f"{len(rate_limiters)} limiters"
        out["extra"] = {
            "limiters": len(rate_limiters),
            "allowed": total_allowed,
            "denied": total_denied,
        }
    except Exception as e:
        out["detail"] = str(e)[:80]
    return out


def _check_rocket() -> Dict[str, Any]:
    out = {"name": "Rocket", "ok": True, "detail": "", "extra": {}}
    try:
        from core import rocket as R
        if not R.is_ready():
            out["ok"] = False
            out["detail"] = "not installed"
            return out
        stats = R.report()
        out["detail"] = (
            f"uvloop={'✅' if stats.get('uvloop') else '❌'} "
            f"orjson={'✅' if stats.get('orjson') else '❌'}"
        )
        out["extra"] = stats
    except Exception as e:
        out["detail"] = str(e)[:80]
    return out


def _check_logs() -> Dict[str, Any]:
    out = {"name": "Logs", "ok": True, "detail": "", "extra": {}}
    try:
        from core import logger as L
        recent = L.memory_logs(limit=200)
        cutoff = time.time() - 300.0
        recent5 = [e for e in recent if e.get("timestamp", 0) >= cutoff]

        errors = sum(
            1 for e in recent5
            if str(e.get("level", "")).upper() in ("ERROR", "CRITICAL")
        )
        warnings = sum(
            1 for e in recent5
            if str(e.get("level", "")).upper() in ("WARNING", "WARN")
        )

        out["detail"] = f"{errors} err · {warnings} warn (5m)"
        out["extra"] = {"errors_5m": errors, "warnings_5m": warnings}

        if errors > 30:
            out["ok"] = False
    except Exception as e:
        out["detail"] = str(e)[:80]
    return out


# ============================================================
# SECTION 2 — HEALTH SCORE
# ============================================================

def _score(checks: List[Dict[str, Any]]) -> float:
    """
    Compute health score 0-100.
    Every failed check subtracts.
    Extra penalties for specific issues.
    """
    if not checks:
        return 0.0

    score = 100.0
    for c in checks:
        if not c.get("ok"):
            score -= 15.0
            continue

        extra = c.get("extra", {}) or {}

        # DB-specific penalties
        if c["name"] == "Databases":
            total = extra.get("total", 0)
            online = extra.get("online", 0)
            if total > 0:
                ratio = online / total
                if ratio < 1.0:
                    score -= (1.0 - ratio) * 20.0

        # Task-specific penalties
        if c["name"] == "Tasks":
            failed = extra.get("failed_total", 0)
            started = extra.get("started_total", 1)
            if started > 0:
                failure_rate = failed / started
                if failure_rate > 0.3:
                    score -= (failure_rate - 0.3) * 30.0

        # Log penalties
        if c["name"] == "Logs":
            errors_5m = extra.get("errors_5m", 0)
            if errors_5m > 10:
                score -= (errors_5m - 10) * 0.5

    return max(0.0, min(100.0, score))


def _status_emoji(score: float) -> str:
    if score >= 90:
        return "🟢"
    if score >= 75:
        return "🟡"
    if score >= 50:
        return "🟠"
    return "🔴"


def _status_text(score: float) -> str:
    if score >= 90:
        return "EXCELLENT"
    if score >= 75:
        return "GOOD"
    if score >= 50:
        return "DEGRADED"
    return "CRITICAL"


# ============================================================
# SECTION 3 — KEYBOARD
# ============================================================

def _nav_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"{F.EMO['refresh']} {F.sc('recheck')}",
                callback_data="adm:page:health",
            ),
            InlineKeyboardButton(
                f"{F.EMO['spark']} {F.sc('sparkline')}",
                callback_data="adm:page:sparkline",
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
# SECTION 4 — MAIN BUILDER
# ============================================================

async def build() -> Tuple[str, InlineKeyboardMarkup]:
    """Full health check panel."""
    client_h = await _check_client()
    db_h = await _check_databases()
    cache_h = _check_cache()
    tasks_h = _check_tasks()
    flow_h = _check_flow_engine()
    locks_h = _check_locks()
    rocket_h = _check_rocket()
    logs_h = _check_logs()

    checks = [
        client_h, db_h, cache_h, tasks_h,
        flow_h, locks_h, rocket_h, logs_h,
    ]

    score = _score(checks)
    status_icon = _status_emoji(score)
    status_text = _status_text(score)

    lines: List[str] = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"❤️ <b>{F.fb('HEALTH CENTER')}</b>",
        F.DIV,
        "",
        f"{status_icon} <b>{F.fb(status_text)}</b> · "
        f"<b>{score:.0f}%</b>",
        f"<code>{P.bar(score, 'indexing', width=18)}</code>",
        "",
        F.DIV_S,
        f"🔍 <b>{F.fb('CHECKS')}</b>",
        F.DIV_S,
        "",
    ]

    for c in checks:
        icon = "🟢" if c.get("ok") else "🔴"
        name = c.get("name", "?")
        detail = c.get("detail", "")
        lines.append(
            f"{icon} <b>{F.sc(name)}</b>"
            + (f" · <i>{F.sc(detail)}</i>" if detail else "")
        )

        extra = c.get("extra") or {}
        if extra:
            sub = _extra_line(name, extra)
            if sub:
                lines.append(f"   {sub}")

    lines.append("")
    lines.append(F.DIV_S)
    lines.append(f"🕒 <code>{FM.datetime_()}</code>")

    text = "\n".join(lines)[:4000]
    return text, _nav_kb()


def _extra_line(name: str, extra: Dict[str, Any]) -> str:
    """Return a compact sub-line for one check's extra data."""
    try:
        if name == "Telegram":
            lat = extra.get("latency_ms")
            up = extra.get("uptime", 0)
            parts = []
            if lat:
                parts.append(f"⚡ {lat}ms")
            if up:
                parts.append(f"🕒 {FM.duration_short(up)}")
            return " · ".join(parts)

        if name == "Databases":
            used = extra.get("used_mb", 0)
            return f"💾 {used:.1f} MB total"

        if name == "Cache":
            rate = extra.get("hit_rate", 0)
            entries = extra.get("entries", 0)
            return f"📊 hit {rate:.0f}% · {FM.num(entries)} entries"

        if name == "Tasks":
            started = extra.get("started_total", 0)
            failed = extra.get("failed_total", 0)
            return f"🟢 {started} started · ❌ {failed} failed"

        if name == "Flow Engine":
            return f"🎯 {extra.get('flows', 0)} flows registered"

        if name == "Rate Limits":
            a = extra.get("allowed", 0)
            d = extra.get("denied", 0)
            return f"✅ {FM.num(a)} allowed · 🛑 {FM.num(d)} denied"

        if name == "Logs":
            e = extra.get("errors_5m", 0)
            w = extra.get("warnings_5m", 0)
            return f"🔴 {e} err · 🟡 {w} warn (5m)"

    except Exception:
        pass
    return ""


# ============================================================
# SECTION 5 — SNAPSHOT
# ============================================================

async def snapshot() -> Dict[str, Any]:
    """Compact health snapshot for other modules."""
    client_h = await _check_client()
    db_h = await _check_databases()
    cache_h = _check_cache()
    tasks_h = _check_tasks()
    logs_h = _check_logs()
    score = _score([client_h, db_h, cache_h, tasks_h, logs_h])
    return {
        "score": round(score, 1),
        "status": _status_text(score),
        "checks": {
            "client": client_h["ok"],
            "databases": db_h["ok"],
            "cache": cache_h["ok"],
            "tasks": tasks_h["ok"],
            "logs": logs_h["ok"],
        },
    }


# ============================================================
# PUBLIC EXPORTS
# ============================================================

__all__ = ["build", "snapshot"]
