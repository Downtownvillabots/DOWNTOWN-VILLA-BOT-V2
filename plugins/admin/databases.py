# ============================================================
# 🏨 DOWNTOWN VILLA — DB BROWSER
# ============================================================
#
# Live view of every shard across every pool.
# Full control: clear shard, clear pool, clear ALL, delete doc.
#
# Every destructive action is 3-step confirmed.
# Every panel has ❌ Cancel button.
#
# ============================================================

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

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
# SECTION 1 — CONFIRMATION STORE
# ============================================================

# token → {kind, pool, index, step, created, expires}
_confirms: Dict[str, Dict[str, Any]] = {}

CONFIRM_TTL = 120.0


def _new_confirm(kind: str, **kwargs) -> str:
    token = f"{kind[:3]}{int(time.time())}{id(kwargs) % 100000:05d}"
    _confirms[token] = {
        "kind": kind,
        "step": 1,
        "created": time.time(),
        "expires": time.time() + CONFIRM_TTL,
        **kwargs,
    }
    return token


def _get_confirm(token: str) -> Optional[Dict[str, Any]]:
    c = _confirms.get(token)
    if not c:
        return None
    if time.time() > c["expires"]:
        _confirms.pop(token, None)
        return None
    return c


def _advance_confirm(token: str) -> Optional[Dict[str, Any]]:
    c = _get_confirm(token)
    if not c:
        return None
    c["step"] += 1
    c["expires"] = time.time() + CONFIRM_TTL
    return c


def _drop_confirm(token: str) -> None:
    _confirms.pop(token, None)


def _cleanup_confirms() -> None:
    now = time.time()
    for t in list(_confirms.keys()):
        if _confirms[t]["expires"] < now:
            _confirms.pop(t, None)


# ============================================================
# SECTION 2 — DB ACCESS
# ============================================================

def _db_manager():
    try:
        from database import db_manager as _m
        return _m
    except Exception:
        return None


async def _list_collections(entry) -> List[Tuple[str, int]]:
    """Return [(collection_name, doc_count)] for one shard."""
    out: List[Tuple[str, int]] = []
    try:
        names = await entry.db.list_collection_names()
        for name in sorted(names):
            try:
                count = await entry.db[name].count_documents({})
                out.append((name, count))
            except Exception:
                out.append((name, -1))
    except Exception as e:
        logger.debug(f"[DB-PANEL] list collections: {e}")
    return out


async def _shard_capacity(entry) -> Tuple[float, float]:
    """Return (used_mb, threshold_mb) for one shard."""
    cfg = _pool_config(entry.pool)
    threshold = cfg["threshold_mb"]
    try:
        stats = await entry.db.command("dbStats")
        used = ((stats.get("storageSize", 0) or 0)
                + (stats.get("indexSize", 0) or 0))
        used_mb = used / (1024 * 1024)
        return used_mb, threshold
    except Exception:
        return 0.0, threshold


def _pool_config(pool: str) -> Dict[str, Any]:
    """Return threshold and label for a pool."""
    thresholds = {
        "system": 100,
        "user": 200,
        "media": 400,
        "backup": 400,
    }
    prefix = pool.upper()
    threshold = config.env_int(
        f"{prefix}_THRESHOLD_MB",
        thresholds.get(pool, 400),
    )
    return {"threshold_mb": max(50, threshold)}


# ============================================================
# SECTION 3 — INDEX PAGE
# ============================================================

async def build_index() -> Tuple[str, InlineKeyboardMarkup]:
    """
    Main DB browser page — all 4 pools.
    """
    mgr = _db_manager()
    if mgr is None:
        return _offline_page()

    lines: List[str] = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"{F.EMO['db']} <b>{F.fb('DATABASE BROWSER')}</b>",
        F.DIV,
        "",
    ]

    # Count summary
    total_shards = 0
    total_online = 0
    total_used = 0.0

    pool_data: Dict[str, Dict[str, Any]] = {}

    for pool_name in ("system", "user", "media", "backup"):
        entries = mgr.entries(pool_name)
        online = [e for e in entries if e.online]
        used_mb_total = 0.0
        for e in online:
            used, _ = await _shard_capacity(e)
            used_mb_total += used
        pool_data[pool_name] = {
            "total": len(entries),
            "online": len(online),
            "used_mb": used_mb_total,
        }
        total_shards += len(entries)
        total_online += len(online)
        total_used += used_mb_total

    # Header stats
    lines.append(
        f"{F.EMO['check']} {F.sc('online')} · "
        f"<b>{total_online}</b> / {total_shards}"
    )
    lines.append(
        f"{F.EMO['storage']} {F.sc('total used')} · "
        f"<b>{FM.size(total_used * 1024 * 1024)}</b>"
    )
    lines.append(
        f"{F.EMO['clock']} <code>{FM.datetime_()}</code>"
    )
    lines.append("")

    # Pools overview
    pool_meta = {
        "system": ("⚙️", "System", "cache · state · sessions · flows"),
        "user":   ("👤", "User",   "users · groups · premium"),
        "media":  ("🎬", "Media",  "media files"),
        "backup": ("💾", "Backup", "backup state · runs"),
    }

    for pool_name, (icon, name, desc) in pool_meta.items():
        info = pool_data[pool_name]
        if info["total"] == 0:
            status = "⚪"
        elif info["online"] == info["total"]:
            status = "🟢"
        elif info["online"] == 0:
            status = "🔴"
        else:
            status = "🟡"

        lines.append(
            f"{status} {icon} <b>{F.sc(name)}</b> · "
            f"<code>{info['online']}/{info['total']}</code> "
            f"· {FM.size(info['used_mb'] * 1024 * 1024)}"
        )
        lines.append(f"   <i>{F.sc(desc)}</i>")
        lines.append("")

    lines.append(F.DIV_S)
    lines.append(f"📌 {F.sc('tap a pool to see shards')}")
    lines.append(f"📌 {F.sc('every action is live')}")

    # Keyboard
    rows: List[List[InlineKeyboardButton]] = []

    # Pool buttons
    for pool_name, (icon, name, _) in pool_meta.items():
        info = pool_data[pool_name]
        rows.append([InlineKeyboardButton(
            f"{icon} {name.upper()} · "
            f"{info['online']}/{info['total']} shards",
            callback_data=f"adm:db_pool:{pool_name}",
        )])

    # Nuke row
    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['warn']} {F.sc('NUKE ALL DATA')}",
            callback_data="adm:db_nuke_all",
        ),
    ])

    # Nav row
    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['refresh']} {F.sc('refresh')}",
            callback_data="adm:page:databases",
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

    text = "\n".join(lines)[:4000]
    return text, InlineKeyboardMarkup(rows)


def _offline_page() -> Tuple[str, InlineKeyboardMarkup]:
    text = "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"{F.EMO['db']} <b>{F.fb('DATABASE BROWSER')}</b>",
        F.DIV,
        "",
        f"{F.EMO['cross']} <b>{F.fb('DATABASE MANAGER NOT FOUND')}</b>",
        "",
        f"📌 {F.sc('check your config')}",
    ])
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data="adm:home",
        ),
    ]])
    return text, kb


# ============================================================
# SECTION 4 — POOL PAGE
# ============================================================

async def build_pool(pool: str) -> Tuple[str, InlineKeyboardMarkup]:
    """Show all shards in one pool with capacity bars."""
    mgr = _db_manager()
    if mgr is None:
        return _offline_page()

    entries = mgr.entries(pool)
    if not entries:
        text = "\n".join([
            f"{F.EMO['db']} <b>{F.fb(pool.upper())}</b>",
            F.DIV,
            "",
            f"{F.EMO['cross']} {F.sc('no shards configured')}",
        ])
        return text, _back_only_kb()

    pool_meta = {
        "system": ("⚙️", "System"),
        "user":   ("👤", "User"),
        "media":  ("🎬", "Media"),
        "backup": ("💾", "Backup"),
    }
    icon, name = pool_meta.get(pool, ("📦", pool.title()))

    lines: List[str] = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"{icon} <b>{F.fb(f'{name.upper()} POOL')}</b>",
        F.DIV,
        "",
    ]

    total_docs = 0
    total_used = 0.0

    shard_rows: List[Dict[str, Any]] = []
    for entry in entries:
        if not entry.online:
            shard_rows.append({
                "entry": entry,
                "online": False,
                "used_mb": 0.0,
                "threshold": _pool_config(pool)["threshold_mb"],
                "docs": 0,
            })
            continue

        used_mb, threshold = await _shard_capacity(entry)
        docs = entry.stats.get("objects", 0)
        total_docs += docs
        total_used += used_mb

        shard_rows.append({
            "entry": entry,
            "online": True,
            "used_mb": used_mb,
            "threshold": threshold,
            "docs": docs,
        })

    lines.append(
        f"{F.EMO['package']} {F.sc('shards')} · "
        f"<b>{len(entries)}</b>"
    )
    lines.append(
        f"{F.EMO['file']} {F.sc('total docs')} · "
        f"<b>{FM.num(total_docs)}</b>"
    )
    lines.append(
        f"{F.EMO['storage']} {F.sc('total used')} · "
        f"<b>{FM.size(total_used * 1024 * 1024)}</b>"
    )
    lines.append("")
    lines.append(F.DIV_S)
    lines.append("")

    # Render each shard
    for row in shard_rows:
        entry = row["entry"]
        if not row["online"]:
            lines.append(
                f"🔴 <b>{F.sc(entry.label)}</b> · "
                f"<i>{F.sc('offline')}</i>"
            )
            lines.append("")
            continue

        used = row["used_mb"]
        threshold = row["threshold"]
        pct = (used / threshold * 100) if threshold else 0.0

        lines.append(
            f"{P.storage_color(pct)} <b>{F.sc(entry.label)}</b>"
        )
        lines.append(
            f"{P.bar(pct, 'storage', width=10)} "
            f"· {used:.1f}/{threshold} MB"
        )
        lines.append(
            f"{F.EMO['file']} {FM.num(row['docs'])} docs "
            f"· {F.EMO['clock']} {entry.last_ping_ms:.0f}ms"
        )
        lines.append("")

    # Keyboard
    rows: List[List[InlineKeyboardButton]] = []
    for row in shard_rows:
        entry = row["entry"]
        icon = "🟢" if row["online"] else "🔴"
        rows.append([InlineKeyboardButton(
            f"{icon} {entry.label}",
            callback_data=f"adm:db_shard:{pool}:{entry.index}",
        )])

    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['warn']} {F.sc('CLEAR ENTIRE POOL')}",
            callback_data=f"adm:db_clear_pool:{pool}",
        ),
    ])
    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['refresh']} {F.sc('refresh')}",
            callback_data=f"adm:db_pool:{pool}",
        ),
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data="adm:page:databases",
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
# SECTION 5 — SHARD PAGE
# ============================================================

async def build_shard(pool: str, index: int) -> Tuple[str, InlineKeyboardMarkup]:
    """Show one shard's collections + counts + clear button."""
    mgr = _db_manager()
    if mgr is None:
        return _offline_page()

    entry = mgr.get(pool, index)
    if entry is None:
        return _not_found_page(f"shard {pool}/{index} not found")

    if not entry.online:
        text = "\n".join([
            f"{F.EMO['cross']} <b>{F.fb('SHARD OFFLINE')}</b>",
            F.DIV,
            "",
            f"🏷️ {entry.label}",
            f"⚠️ {entry.error or 'unknown error'}",
        ])
        return text, _back_kb(f"adm:db_pool:{pool}")

    used_mb, threshold = await _shard_capacity(entry)
    pct = (used_mb / threshold * 100) if threshold else 0.0

    collections = await _list_collections(entry)

    lines: List[str] = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"{F.EMO['folder']} <b>{F.fb(entry.label)}</b>",
        F.DIV,
        "",
        f"{F.EMO['db']} {F.sc('pool')} · <code>{entry.pool}</code>",
        f"{F.EMO['id']} {F.sc('index')} · <code>{entry.index}</code>",
        f"{F.EMO['net']} {F.sc('ping')} · <b>{entry.last_ping_ms:.0f}ms</b>",
        "",
        f"{P.storage_color(pct)} <b>{F.sc('storage')}</b>",
        f"<code>{P.bar(pct, 'storage', width=14)}</code>",
        f"{used_mb:.1f} MB / {threshold} MB",
        "",
        F.DIV_S,
        f"{F.EMO['folder']} <b>{F.sc('collections')}</b> · "
        f"<b>{len(collections)}</b>",
        F.DIV_S,
        "",
    ]

    for name, count in collections[:20]:
        count_str = FM.num(count) if count >= 0 else "?"
        lines.append(f"• <code>{name}</code> · <b>{count_str}</b>")
    if len(collections) > 20:
        lines.append(f"<i>… +{len(collections) - 20} more</i>")

    # Keyboard
    rows: List[List[InlineKeyboardButton]] = []

    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['warn']} {F.sc('CLEAR THIS SHARD')}",
            callback_data=f"adm:db_clear_shard:{pool}:{index}",
        ),
    ])

    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['refresh']} {F.sc('refresh')}",
            callback_data=f"adm:db_shard:{pool}:{index}",
        ),
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data=f"adm:db_pool:{pool}",
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
# SECTION 6 — CONFIRMATION CARDS
# ============================================================

def build_clear_shard_confirm(pool: str, index: int, step: int) -> Tuple[str, InlineKeyboardMarkup]:
    """3-step confirmation for clearing a shard."""
    titles = {
        1: "⚠️ STEP 1/3 — CLEAR SHARD",
        2: "🚨 STEP 2/3 — FINAL WARNING",
        3: "☢️ STEP 3/3 — PERMANENT DELETE",
    }
    prompts = {
        1: "This will remove ALL data from this shard.",
        2: "This CANNOT be undone.",
        3: "Tap YES to permanently delete everything.",
    }

    title = titles.get(step, "STEP")
    prompt = prompts.get(step, "")

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"<b>{F.fb(title)}</b>",
        F.DIV,
        "",
        f"🎯 {F.sc('target')} · <code>{pool}/{index}</code>",
        "",
        f"{F.EMO['warn']} <b>{F.sc(prompt)}</b>",
        "",
        F.DIV_S,
        f"📌 {F.sc('step')} · <b>{step}</b> / 3",
    ]

    token = _new_confirm("shard", pool=pool, index=index, step=step)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"{F.EMO['warn']} {F.sc('continue')}",
            callback_data=f"adm:db_confirm:{token}",
        )],
        [InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('cancel')}",
            callback_data=f"adm:db_cancel:{token}",
        )],
    ])

    text = "\n".join(lines)[:4000]
    return text, kb


def build_clear_pool_confirm(pool: str, step: int) -> Tuple[str, InlineKeyboardMarkup]:
    titles = {
        1: "⚠️ STEP 1/3 — CLEAR POOL",
        2: "🚨 STEP 2/3 — FINAL WARNING",
        3: "☢️ STEP 3/3 — PERMANENT DELETE",
    }
    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"<b>{F.fb(titles.get(step, 'STEP'))}</b>",
        F.DIV,
        "",
        f"🎯 {F.sc('pool')} · <code>{pool}</code>",
        f"{F.EMO['db']} {F.sc('ALL shards in this pool')}",
        "",
        f"{F.EMO['warn']} <b>{F.sc('this wipes every shard')}</b>",
        "",
        F.DIV_S,
        f"📌 {F.sc('step')} · <b>{step}</b> / 3",
    ]

    token = _new_confirm("pool", pool=pool, step=step)

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"{F.EMO['warn']} {F.sc('continue')}",
            callback_data=f"adm:db_confirm:{token}",
        )],
        [InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('cancel')}",
            callback_data=f"adm:db_cancel:{token}",
        )],
    ])

    text = "\n".join(lines)[:4000]
    return text, kb


def build_nuke_all_confirm(step: int) -> Tuple[str, InlineKeyboardMarkup]:
    """10-step escalation for the ultimate nuke."""
    if step >= 10:
        title = "💀 FINAL CONFIRMATION — TYPE OR TAP"
        prompt = "This will wipe EVERY pool, EVERY shard, EVERYTHING."
    elif step >= 7:
        title = f"☢️ STEP {step}/10 — EXTREME DANGER"
        prompt = "You are about to nuke the entire bot database."
    elif step >= 4:
        title = f"🚨 STEP {step}/10 — WARNING"
        prompt = "All shards will be emptied."
    else:
        title = f"⚠️ STEP {step}/10 — CONFIRM"
        prompt = "This is the ultimate destructive action."

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"<b>{F.fb(title)}</b>",
        F.DIV,
        "",
        f"🎯 {F.sc('target')} · <b>ALL POOLS</b>",
        "",
        f"{F.EMO['warn']} <b>{F.sc(prompt)}</b>",
        "",
        F.DIV_S,
        f"📌 {F.sc('step')} · <b>{step}</b> / 10",
    ]

    token = _new_confirm("nuke", step=step)

    label = (
        f"💀 {F.sc('FINAL — WIPE EVERYTHING')}"
        if step >= 10 else
        f"{F.EMO['warn']} {F.sc('continue')}"
    )

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            label,
            callback_data=f"adm:db_confirm:{token}",
        )],
        [InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('cancel')}",
            callback_data=f"adm:db_cancel:{token}",
        )],
    ])

    text = "\n".join(lines)[:4000]
    return text, kb


# ============================================================
# SECTION 7 — ACTION EXECUTORS
# ============================================================

async def do_clear_shard(pool: str, index: int) -> Dict[str, Any]:
    """Execute shard wipe."""
    mgr = _db_manager()
    if mgr is None:
        return {"ok": False, "reason": "no manager"}
    try:
        return await mgr.clear_shard(pool, index)
    except Exception as e:
        logger.exception(f"[DB-PANEL] clear_shard: {e}")
        return {"ok": False, "reason": str(e)}


async def do_clear_pool(pool: str) -> Dict[str, Any]:
    """Execute pool wipe."""
    mgr = _db_manager()
    if mgr is None:
        return {"ok": False, "reason": "no manager"}
    try:
        return await mgr.clear_pool(pool)
    except Exception as e:
        logger.exception(f"[DB-PANEL] clear_pool: {e}")
        return {"ok": False, "reason": str(e)}


async def do_nuke_all() -> Dict[str, Any]:
    """Execute ALL pool wipe — the ultimate."""
    mgr = _db_manager()
    if mgr is None:
        return {"ok": False, "reason": "no manager"}
    out = {"pools": {}, "total": 0, "ok": True}
    for pool in ("system", "user", "media", "backup"):
        try:
            r = await mgr.clear_pool(pool)
            out["pools"][pool] = r.get("total_deleted", 0)
            out["total"] += r.get("total_deleted", 0)
        except Exception as e:
            out["pools"][pool] = f"error: {e}"
            out["ok"] = False
    logger.warning(f"[DB-PANEL] NUKE ALL — {out['total']} docs deleted")
    return out


# ============================================================
# SECTION 8 — RESULT CARDS
# ============================================================

def build_result_card(title: str, result: Dict[str, Any], back_cb: str) -> Tuple[str, InlineKeyboardMarkup]:
    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"<b>{F.fb(title)}</b>",
        F.DIV,
        "",
    ]

    if not result.get("ok", True) and "reason" in result:
        lines.append(f"{F.EMO['cross']} {F.sc('failed')} · "
                     f"<code>{result['reason']}</code>")
    else:
        lines.append(f"{F.EMO['check']} <b>{F.sc('completed')}</b>")
        if "documents_deleted" in result:
            lines.append(
                f"{F.EMO['trash']} {F.sc('docs deleted')} · "
                f"<b>{FM.num(result['documents_deleted'])}</b>"
            )
        if "collections_cleared" in result:
            lines.append(
                f"{F.EMO['folder']} {F.sc('collections')} · "
                f"<b>{result['collections_cleared']}</b>"
            )
        if "total" in result:
            lines.append(
                f"{F.EMO['trash']} {F.sc('total deleted')} · "
                f"<b>{FM.num(result['total'])}</b>"
            )
        if "pools" in result:
            for p, n in result["pools"].items():
                lines.append(f"• {p} · <b>{n}</b>")

    lines += [
        "",
        F.DIV_S,
        f"🕒 <code>{FM.datetime_()}</code>",
    ]

    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"{F.EMO['refresh']} {F.sc('refresh')}",
                callback_data="adm:page:databases",
            ),
            InlineKeyboardButton(
                f"{F.EMO['back']} {F.sc('back')}",
                callback_data=back_cb,
            ),
        ],
    ])

    return "\n".join(lines)[:4000], kb


# ============================================================
# SECTION 9 — HELPERS
# ============================================================

def _back_only_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data="adm:page:databases",
        ),
    ]])


def _back_kb(target: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data=target,
        ),
        InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('close')}",
            callback_data="adm:close",
        ),
    ]])


def _not_found_page(msg: str) -> Tuple[str, InlineKeyboardMarkup]:
    text = "\n".join([
        f"{F.EMO['cross']} <b>{F.fb('NOT FOUND')}</b>",
        F.DIV,
        "",
        f"<i>{F.sc(msg)}</i>",
    ])
    return text, _back_only_kb()


# ============================================================
# SECTION 10 — PUBLIC EXPORTS
# ============================================================

__all__ = [
    "build_index",
    "build_pool",
    "build_shard",
    "build_clear_shard_confirm",
    "build_clear_pool_confirm",
    "build_nuke_all_confirm",
    "build_result_card",
    "do_clear_shard",
    "do_clear_pool",
    "do_nuke_all",
    "_get_confirm",
    "_advance_confirm",
    "_drop_confirm",
    "_cleanup_confirms",
]
