# ============================================================
# 🏨 DOWNTOWN VILLA — TASKS MONITOR (ULTIMATE)
# ============================================================
#
# Live view of every task running inside the bot.
#
# Tracks:
#   • Flow engine runs (search flows per user)
#   • Background asyncio tasks (backup, indexing, broadcast)
#   • Custom registered tasks (via public API)
#   • System-level trackers (cleanup, watcher, scheduler)
#
# Features:
#   • Live progress bars (indexing mode)
#   • Speed + ETA per task
#   • Cancel any task (with confirm)
#   • Filter by status / type
#   • Sort by age / progress / type
#   • Sparkline history of task count
#   • Auto-refresh every 5s
#   • Cancel button everywhere
#
# ============================================================

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque, Counter
from typing import Any, Deque, Dict, List, Optional, Tuple

from pyrogram.enums import ParseMode
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
)

from core import config
from utils import fonts as F
from utils import format as FM
from utils import progress as P

logger = logging.getLogger(__name__)


# ============================================================
# SECTION 1 — PUBLIC TASK REGISTRY
# ============================================================
#
# Other modules (backup, indexing, broadcast) can register
# their long-running tasks here for unified monitoring.
#
# Usage:
#   from plugins.admin.tasks import register_task
#   tid = register_task(
#       "backup", "Backup worker",
#       total=10000,
#       owner="admin",
#       meta={"channel": "-100xxx"}
#   )
#   # later:
#   update_task(tid, current=500, speed=12.5)
#   finish_task(tid, "completed")
#

_tasks: Dict[str, Dict[str, Any]] = {}
_task_lock = asyncio.Lock()

# Sparkline: task count over time
_spark_count: Deque[int] = deque(maxlen=30)
_spark_started: Deque[int] = deque(maxlen=30)
_spark_finished: Deque[int] = deque(maxlen=30)

# Counters
_counters = {
    "started_total": 0,
    "finished_total": 0,
    "cancelled_total": 0,
    "failed_total": 0,
}


def register_task(
    task_type: str,
    name: str,
    total: int = 0,
    owner: str = "",
    meta: Optional[Dict[str, Any]] = None,
) -> str:
    """Register a new task. Returns task id."""
    tid = f"{task_type[:3]}_{int(time.time())}_{id(meta) % 10000:04d}"
    _tasks[tid] = {
        "id": tid,
        "type": task_type,
        "name": name,
        "owner": owner,
        "total": int(total),
        "current": 0,
        "speed": 0.0,
        "started": time.time(),
        "updated": time.time(),
        "status": "running",
        "message": "",
        "meta": dict(meta or {}),
        "cancel_fn": None,
    }
    _counters["started_total"] += 1
    logger.info(f"[TASKS] registered {tid} type={task_type} name={name}")
    return tid


def update_task(
    tid: str,
    current: Optional[int] = None,
    total: Optional[int] = None,
    speed: Optional[float] = None,
    message: Optional[str] = None,
    status: Optional[str] = None,
    cancel_fn: Optional[Any] = None,
) -> bool:
    """Update task progress."""
    t = _tasks.get(tid)
    if not t:
        return False
    if current is not None:
        t["current"] = int(current)
    if total is not None:
        t["total"] = int(total)
    if speed is not None:
        t["speed"] = float(speed)
    if message is not None:
        t["message"] = str(message)
    if status is not None:
        t["status"] = str(status)
    if cancel_fn is not None:
        t["cancel_fn"] = cancel_fn
    t["updated"] = time.time()
    return True


def finish_task(tid: str, status: str = "completed") -> bool:
    """Mark task as finished."""
    t = _tasks.get(tid)
    if not t:
        return False
    t["status"] = status
    t["updated"] = time.time()
    t["finished"] = time.time()

    if status == "completed":
        _counters["finished_total"] += 1
    elif status == "cancelled":
        _counters["cancelled_total"] += 1
    elif status == "failed":
        _counters["failed_total"] += 1

    logger.info(f"[TASKS] finished {tid} status={status}")
    return True


def remove_task(tid: str) -> bool:
    return _tasks.pop(tid, None) is not None


def get_task(tid: str) -> Optional[Dict[str, Any]]:
    return _tasks.get(tid)


async def cancel_task(tid: str) -> bool:
    """Call the task's cancel function if any."""
    t = _tasks.get(tid)
    if not t:
        return False
    fn = t.get("cancel_fn")
    try:
        if fn is not None:
            result = fn()
            if asyncio.iscoroutine(result):
                await result
        t["status"] = "cancelled"
        t["updated"] = time.time()
        t["finished"] = time.time()
        _counters["cancelled_total"] += 1
        return True
    except Exception as e:
        logger.warning(f"[TASKS] cancel {tid}: {e}")
        return False


# ============================================================
# SECTION 2 — AUTO-COLLECT FROM OTHER SOURCES
# ============================================================

def _collect_flow_runs() -> List[Dict[str, Any]]:
    """Collect active flow engine runs."""
    out: List[Dict[str, Any]] = []
    try:
        from core import flow_engine as FE
        for run in FE.active_runs():
            cfg = run.current_step_cfg() or {}
            total_steps = len(run.flow.sorted_steps())
            out.append({
                "id": f"flow_{run.run_id[:8]}",
                "type": "flow",
                "name": f"{run.flow_name}",
                "owner": str(run.user_id),
                "total": total_steps,
                "current": run.step_index + 1,
                "speed": 0.0,
                "started": run.started_at,
                "updated": run.updated_at,
                "status": "running",
                "message": f"step: {cfg.get('type', '?')}",
                "meta": {
                    "run_id": run.run_id,
                    "chat_id": run.chat_id,
                },
            })
    except Exception:
        pass
    return out


def _collect_asyncio_tasks() -> List[Dict[str, Any]]:
    """Collect top-level asyncio tasks (excluding internal)."""
    out: List[Dict[str, Any]] = []
    try:
        for t in asyncio.all_tasks():
            if t.done():
                continue
            name = t.get_name() or "task"
            # Skip internal tasks
            if name.startswith("Task-") and len(out) > 30:
                continue
            out.append({
                "id": f"async_{id(t) % 100000:05d}",
                "type": "async",
                "name": name[:40],
                "owner": "system",
                "total": 0,
                "current": 0,
                "speed": 0.0,
                "started": 0,
                "updated": 0,
                "status": "running",
                "message": "",
                "meta": {},
            })
    except Exception:
        pass
    return out[:30]


def _collect_all() -> List[Dict[str, Any]]:
    """Merge all task sources."""
    merged: List[Dict[str, Any]] = []
    merged.extend(list(_tasks.values()))
    merged.extend(_collect_flow_runs())
    merged.extend(_collect_asyncio_tasks())

    # Deduplicate by id
    seen = set()
    out = []
    for t in merged:
        if t["id"] in seen:
            continue
        seen.add(t["id"])
        out.append(t)
    return out


# ============================================================
# SECTION 3 — SPARKLINE
# ============================================================

_SPARK_CHARS = "▁▂▃▄▅▆▇█"


def _sparkline(samples: Deque, width: int = 20) -> str:
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


def _track_sparkline(tasks: List[Dict[str, Any]]) -> None:
    running = [t for t in tasks if t.get("status") == "running"]
    _spark_count.append(len(running))


# ============================================================
# SECTION 4 — FILTER + SORT STATE
# ============================================================

_filters = {
    "status": "all",       # all | running | finished | failed
    "type": "all",         # all | flow | backup | indexing | broadcast | async
    "sort": "age",         # age | progress | type | speed
}


def _set_filter(key: str, value: str) -> None:
    if key in _filters:
        _filters[key] = value


def _apply_filter(tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Filter + sort tasks."""
    out = list(tasks)

    # Status filter
    if _filters["status"] != "all":
        want = _filters["status"]
        out = [t for t in out if t.get("status") == want]

    # Type filter
    if _filters["type"] != "all":
        want = _filters["type"]
        out = [t for t in out if t.get("type") == want]

    # Sort
    s = _filters["sort"]
    if s == "age":
        out.sort(key=lambda t: t.get("started", 0))
    elif s == "progress":
        out.sort(
            key=lambda t: (
                t.get("current", 0) / max(1, t.get("total", 1))
            ),
            reverse=True,
        )
    elif s == "type":
        out.sort(key=lambda t: t.get("type", ""))
    elif s == "speed":
        out.sort(key=lambda t: t.get("speed", 0), reverse=True)

    return out


# ============================================================
# SECTION 5 — KEYBOARD BUILDERS
# ============================================================

def _nav_kb() -> InlineKeyboardMarkup:
    """Filter + sort + nav row."""
    def status_btn(value: str, icon: str, label: str):
        mark = "✅ " if _filters["status"] == value else ""
        return InlineKeyboardButton(
            f"{mark}{icon} {F.sc(label)}",
            callback_data=f"adm:tk:filter:status:{value}",
        )

    def type_btn(value: str, icon: str, label: str):
        mark = "✅ " if _filters["type"] == value else ""
        return InlineKeyboardButton(
            f"{mark}{icon} {F.sc(label)}",
            callback_data=f"adm:tk:filter:type:{value}",
        )

    def sort_btn(value: str, icon: str, label: str):
        mark = "✅ " if _filters["sort"] == value else ""
        return InlineKeyboardButton(
            f"{mark}{icon} {F.sc(label)}",
            callback_data=f"adm:tk:filter:sort:{value}",
        )

    return InlineKeyboardMarkup([
        [
            status_btn("all", "🌐", "all"),
            status_btn("running", "🟢", "running"),
            status_btn("finished", "✅", "done"),
            status_btn("failed", "❌", "failed"),
        ],
        [
            type_btn("all", "🌐", "all"),
            type_btn("flow", "🎯", "flow"),
            type_btn("backup", "💾", "backup"),
        ],
        [
            type_btn("indexing", "📚", "index"),
            type_btn("broadcast", "📢", "bcast"),
            type_btn("async", "⚙️", "async"),
        ],
        [
            sort_btn("age", "🕒", "age"),
            sort_btn("progress", "📊", "prog"),
            sort_btn("speed", "⚡", "speed"),
            sort_btn("type", "🏷️", "type"),
        ],
        [
            InlineKeyboardButton(
                f"{F.EMO['refresh']} {F.sc('refresh')}",
                callback_data="adm:tk:refresh",
            ),
            InlineKeyboardButton(
                f"{F.EMO['warn']} {F.sc('clear done')}",
                callback_data="adm:tk:clear_done",
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
    """Live tasks panel."""
    all_tasks = _collect_all()
    _track_sparkline(all_tasks)

    filtered = _apply_filter(all_tasks)

    # Counters
    total = len(all_tasks)
    running = sum(1 for t in all_tasks if t.get("status") == "running")
    finished = sum(1 for t in all_tasks if t.get("status") == "completed")
    failed = sum(1 for t in all_tasks if t.get("status") == "failed")
    cancelled = sum(1 for t in all_tasks if t.get("status") == "cancelled")

    lines: List[str] = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"{F.EMO['rocket']} <b>{F.fb('LIVE TASK CENTER')}</b>",
        F.DIV,
        "",
        f"{F.EMO['chart']} {F.sc('total')} · <b>{total}</b>",
        f"🟢 {F.sc('running')} · <b>{running}</b>",
        f"✅ {F.sc('done')} · <b>{finished}</b>",
        f"❌ {F.sc('failed')} · <b>{failed}</b>",
        f"🛑 {F.sc('cancelled')} · <b>{cancelled}</b>",
        "",
        f"{F.EMO['bar']} {F.sc('filter')} · "
        f"<code>{_filters['status']}</code> · "
        f"<code>{_filters['type']}</code>",
        f"📊 {F.sc('sort')} · <code>{_filters['sort']}</code>",
        "",
        F.DIV_S,
        "",
    ]

    # Tasks
    if not filtered:
        lines.append(f"⚪ {F.sc('no tasks match')}")
        lines.append("")
    else:
        for t in filtered[:8]:
            lines.extend(_render_task_block(t))

        if len(filtered) > 8:
            lines.append(f"<i>… +{len(filtered) - 8} more</i>")
            lines.append("")

    # Sparkline
    lines.append(F.DIV_S)
    lines.append(f"{F.EMO['spark']} <b>{F.sc('task count')}</b> "
                 f"· last {len(_spark_count)} samples")
    lines.append(F.DIV_S)
    lines.append(f"<code>{_sparkline(_spark_count, 24)}</code>")
    lines.append("")

    # Session counters
    lines.append(F.DIV_S)
    lines.append(f"{F.EMO['chart']} <b>{F.sc('lifetime')}</b>")
    lines.append(F.DIV_S)
    lines.append(
        f"🟢 started · <b>{FM.num(_counters['started_total'])}</b>"
    )
    lines.append(
        f"✅ finished · <b>{FM.num(_counters['finished_total'])}</b>"
    )
    lines.append(
        f"❌ failed · <b>{FM.num(_counters['failed_total'])}</b>"
    )
    lines.append(
        f"🛑 cancelled · <b>{FM.num(_counters['cancelled_total'])}</b>"
    )
    lines.append("")

    lines.append(f"🕒 <code>{FM.datetime_()}</code>")

    text = "\n".join(lines)[:4000]
    return text, _nav_kb()


def _render_task_block(t: Dict[str, Any]) -> List[str]:
    """Render one task as a set of lines."""
    out: List[str] = []

    status = str(t.get("status", "?")).lower()
    type_ = str(t.get("type", "?")).lower()
    name = str(t.get("name", "?"))[:30]
    tid = str(t.get("id", "?"))

    # Status icon
    icon = {
        "running":   "🟢",
        "completed": "✅",
        "failed":    "❌",
        "cancelled": "🛑",
        "paused":    "⏸️",
        "waiting":   "⏳",
    }.get(status, "⚪")

    # Type icon
    type_icon = {
        "flow":      "🎯",
        "backup":    "💾",
        "indexing":  "📚",
        "broadcast": "📢",
        "async":     "⚙️",
        "system":    "🖥️",
    }.get(type_, "📦")

    out.append(f"{icon} {type_icon} <b>{F.sc(name)}</b>")

    # Progress bar
    total = int(t.get("total", 0))
    current = int(t.get("current", 0))

    if total > 0:
        pct = (current / total) * 100
        out.append(
            f"   <code>{P.bar(pct, 'indexing', width=12)}</code> "
            f"<b>{current}/{total}</b>"
        )
    elif status == "running":
        # No progress info — just age
        age = time.time() - t.get("started", time.time())
        out.append(f"   ⏱️ {F.sc('running for')} "
                   f"<b>{FM.duration_short(age)}</b>")

    # Speed + ETA
    speed = float(t.get("speed", 0))
    if speed > 0 and total > 0:
        remaining = max(0, total - current)
        eta_secs = remaining / speed if speed else 0
        out.append(
            f"   ⚡ {F.sc('speed')} · <b>{FM.rate(speed)}</b> "
            f"· ⏱️ {F.sc('eta')} · <b>{FM.duration_short(eta_secs)}</b>"
        )

    # Owner
    owner = str(t.get("owner", "") or "")
    if owner:
        out.append(f"   👤 {F.sc('owner')} · <code>{owner[:20]}</code>")

    # Message
    msg = str(t.get("message", "") or "")
    if msg:
        out.append(f"   💬 <i>{F.sc(msg[:60])}</i>")

    # Task id
    out.append(f"   🆔 <code>{tid[:24]}</code>")

    # Cancel button placeholder — real buttons in keyboard
    out.append("")

    return out


# ============================================================
# SECTION 7 — DETAIL PAGE (per-task)
# ============================================================

async def build_task_detail(tid: str) -> Tuple[str, InlineKeyboardMarkup]:
    """Detail view for one task."""
    t = get_task(tid)

    # If not in own registry, try flow engine
    if t is None and tid.startswith("flow_"):
        try:
            from core import flow_engine as FE
            for run in FE.active_runs():
                if f"flow_{run.run_id[:8]}" == tid:
                    t = {
                        "id": tid,
                        "type": "flow",
                        "name": run.flow_name,
                        "owner": str(run.user_id),
                        "total": len(run.flow.sorted_steps()),
                        "current": run.step_index + 1,
                        "started": run.started_at,
                        "updated": run.updated_at,
                        "status": "running",
                        "message": "",
                        "meta": {"run_id": run.run_id},
                    }
                    break
        except Exception:
            pass

    if t is None:
        text = "\n".join([
            f"{F.EMO['cross']} <b>{F.fb('TASK NOT FOUND')}</b>",
            F.DIV,
            "",
            f"🆔 <code>{tid}</code>",
        ])
        return text, _back_kb()

    type_ = str(t.get("type", "?"))
    status = str(t.get("status", "?"))
    name = str(t.get("name", "?"))
    owner = str(t.get("owner", "") or "")

    # Compute ages
    started = float(t.get("started", 0) or 0)
    updated = float(t.get("updated", 0) or 0)
    finished = float(t.get("finished", 0) or 0)

    age = (finished or time.time()) - started if started else 0
    since_update = time.time() - updated if updated else 0

    lines: List[str] = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"🎯 <b>{F.fb('TASK DETAIL')}</b>",
        F.DIV,
        "",
        f"📛 {F.sc('name')} · <b>{F.sc(name)}</b>",
        f"🏷️ {F.sc('type')} · <code>{type_}</code>",
        f"⚙️ {F.sc('status')} · <b>{F.sc(status)}</b>",
        f"🆔 <code>{tid}</code>",
        "",
    ]

    total = int(t.get("total", 0))
    current = int(t.get("current", 0))

    if total > 0:
        pct = (current / total) * 100
        lines.append(f"{F.EMO['bar']} {F.sc('progress')}")
        lines.append(f"<code>{P.bar(pct, 'indexing', width=16)}</code>")
        lines.append(f"<b>{current}/{total}</b>")
        lines.append("")

    if owner:
        lines.append(f"👤 {F.sc('owner')} · <code>{owner}</code>")

    if started:
        lines.append(f"🕒 {F.sc('started')} · "
                     f"<code>{FM.datetime_(datetime.fromtimestamp(started))}</code>")
    if age:
        lines.append(f"⏱️ {F.sc('age')} · <b>{FM.duration_short(age)}</b>")
    if since_update:
        lines.append(f"🔄 {F.sc('last update')} · "
                     f"<b>{FM.duration_short(since_update)} ago</b>")

    msg = t.get("message") or ""
    if msg:
        lines.append("")
        lines.append(f"{F.EMO['info']} <i>{F.sc(msg[:200])}</i>")

    meta = t.get("meta") or {}
    if meta:
        lines.append("")
        lines.append(F.DIV_S)
        lines.append(f"📦 <b>{F.sc('metadata')}</b>")
        lines.append(F.DIV_S)
        for k, v in list(meta.items())[:6]:
            lines.append(f"• <code>{k}</code> · {F.sc(str(v)[:40])}")

    lines.append("")
    lines.append(f"🕒 <code>{FM.datetime_()}</code>")

    # Buttons
    rows: List[List[InlineKeyboardButton]] = []

    if status == "running" and not tid.startswith(("async_", "flow_")):
        rows.append([InlineKeyboardButton(
            f"🛑 {F.sc('cancel task')}",
            callback_data=f"adm:tk:confirm_cancel:{tid}",
        )])

    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['refresh']} {F.sc('refresh')}",
            callback_data=f"adm:tk:detail:{tid}",
        ),
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data="adm:page:tasks",
        ),
    ])
    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('close')}",
            callback_data="adm:close",
        ),
    ])

    text = "\n".join(lines)[:4000]
    return text, InlineKeyboardMarkup(rows)


# ============================================================
# SECTION 8 — CONFIRM CANCEL
# ============================================================

async def build_cancel_confirm(tid: str) -> Tuple[str, InlineKeyboardMarkup]:
    t = get_task(tid)
    name = t.get("name", "?") if t else "?"

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"{F.EMO['warn']} <b>{F.fb('CONFIRM CANCEL')}</b>",
        F.DIV,
        "",
        f"📛 {F.sc('task')} · <b>{F.sc(name)}</b>",
        "",
        f"{F.EMO['warn']} {F.sc('this will stop the task')}",
        "",
        F.DIV_S,
    ]

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"🛑 {F.sc('yes, cancel')}",
            callback_data=f"adm:tk:do_cancel:{tid}",
        )],
        [InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('no, go back')}",
            callback_data=f"adm:tk:detail:{tid}",
        )],
    ])

    return "\n".join(lines)[:4000], kb


# ============================================================
# SECTION 9 — HELPERS
# ============================================================

def _back_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data="adm:page:tasks",
        ),
        InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('close')}",
            callback_data="adm:close",
        ),
    ]])


def _clear_finished() -> int:
    """Remove all finished / failed / cancelled tasks from registry."""
    doomed = [
        tid for tid, t in _tasks.items()
        if t.get("status") in ("completed", "failed", "cancelled")
    ]
    for tid in doomed:
        _tasks.pop(tid, None)
    return len(doomed)


# ============================================================
# SECTION 10 — SNAPSHOT
# ============================================================

def snapshot() -> Dict[str, Any]:
    all_t = _collect_all()
    return {
        "total": len(all_t),
        "running": sum(1 for t in all_t if t.get("status") == "running"),
        "counters": dict(_counters),
        "filters": dict(_filters),
    }


# ============================================================
# SECTION 11 — AUTO CLEANUP
# ============================================================

async def cleanup_loop(interval: float = 300.0) -> None:
    """Remove stale finished tasks every 5 min."""
    while True:
        try:
            await asyncio.sleep(interval)
            n = _clear_finished()
            if n:
                logger.debug(f"[TASKS] cleaned {n} finished")
        except asyncio.CancelledError:
            return
        except Exception:
            pass


_cleanup_task: Optional[asyncio.Task] = None


def ensure_cleanup() -> None:
    global _cleanup_task
    if _cleanup_task and not _cleanup_task.done():
        return
    try:
        loop = asyncio.get_running_loop()
        _cleanup_task = loop.create_task(cleanup_loop())
    except RuntimeError:
        pass


# ============================================================
# SECTION 12 — DATETIME IMPORT
# ============================================================

from datetime import datetime  # noqa: E402


# ============================================================
# PUBLIC EXPORTS
# ============================================================

__all__ = [
    # Builders
    "build",
    "build_task_detail",
    "build_cancel_confirm",
    # Public API for other modules
    "register_task",
    "update_task",
    "finish_task",
    "remove_task",
    "get_task",
    "cancel_task",
    # Helpers
    "ensure_cleanup",
    "snapshot",
]
