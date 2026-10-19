# ============================================================
# 🏨 DOWNTOWN VILLA — DATABASE CONTROL CENTER
# ============================================================
#
# Layout: v1 (categories / per-db / collections / docs / indexes /
#         health / perf / audit / errors / dupes / clear / live)
# Colors: v2 (utils/progress.py — storage bar green→red)
#
# Callback prefix: adm:dbc_*
#
# ============================================================

from __future__ import annotations

import asyncio
import logging
import re
import time
from collections import deque
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from core import config
from database import db_registry
from utils import fonts as F
from utils import format as FM
from utils import progress as P

logger = logging.getLogger(__name__)


# ============================================================
# SECTION 1 — AUTH
# ============================================================

def _is_admin(uid) -> bool:
    try:
        return int(uid) in [int(a) for a in config.ADMINS]
    except Exception:
        return False


# ============================================================
# SECTION 2 — CONSTANTS
# ============================================================

IST = timezone(timedelta(hours=5, minutes=30))
BAR_W = 14
DB_STORAGE_CAPACITY = 512 * 1024 * 1024
CACHE_TTL = 8
LIVE_DEFAULT = 3
LIVE_OPTIONS = [3, 15, 30]
RECENT_LIMITS = [5, 10, 20]
COLL_PAGE = 20
MAX_LAT = 30

DIV = F.DIV
DIV_S = F.DIV_S

_SENSITIVE = re.compile(
    r"(token|password|secret|api[_-]?key|api[_-]?hash|session|uri|database_uri|dsn|auth)",
    re.IGNORECASE,
)
_URI_PAT = re.compile(r"mongodb(\+srv)?://[^\s'\"]+", re.IGNORECASE)

# Per-chat live interval + current view
_live_intervals: Dict[int, int] = {}
_live_view: Dict[int, Dict[str, Any]] = {}

# Pending search session (for text input)
_search_pending: Dict[int, Dict[str, Any]] = {}


# ============================================================
# SECTION 3 — HELPERS
# ============================================================

def now_ist() -> str:
    return datetime.now(IST).strftime("%I:%M:%S %p IST")


def esc(s: Any) -> str:
    if s is None:
        return ""
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def redact(v: Any) -> Any:
    if isinstance(v, dict):
        return {
            k: ("🔐 [REDACTED]" if _SENSITIVE.search(str(k)) else redact(val))
            for k, val in v.items()
        }
    if isinstance(v, list):
        return [redact(x) for x in v]
    if isinstance(v, str):
        return _URI_PAT.sub("mongodb://[REDACTED]", v)
    return v


def summarize_doc(doc: Dict[str, Any], maxf: int = 12, maxl: int = 100) -> str:
    safe = redact(doc)
    out = []
    for i, (k, v) in enumerate(safe.items()):
        if i >= maxf:
            out.append(f"  <i>… {F.sc('truncated')}</i>")
            break
        sval = str(v)
        if len(sval) > maxl:
            sval = sval[: maxl - 1] + "…"
        out.append(f"  <b>{esc(k)}</b> : <code>{esc(sval)}</code>")
    return "\n".join(out)


def bar_line(label: str, pct_val: float, width: int = BAR_W) -> str:
    color = P.storage_color(pct_val)
    bar = P.bar(pct_val, "storage", width=width, show_percent=False)
    return (
        f"{color} <b>{F.sc(label)}</b> · <code>{pct_val:.1f}%</code>\n"
        f"<code>{bar}</code>"
    )


def storage_usage_block(
    storage_size: int, width: int = 10, online: bool = True,
) -> str:
    if not online:
        return f"⚪ {F.sc('storage usage unavailable while database is offline')}"

    used = max(0, storage_size)
    remaining = max(0, DB_STORAGE_CAPACITY - used)
    pct = used / DB_STORAGE_CAPACITY * 100
    return "\n".join([
        bar_line("estimated storage used (512 MB cap)", pct, width),
        one_line(
            "used / remaining",
            f"{FM.size(used)} / {FM.size(remaining)}",
            "💾",
        ),
    ])


def one_line(label: str, value: str, icon: str = "•") -> str:
    return f"{icon} {F.sc(label)} · <code>{value}</code>"


# ============================================================
# SECTION 4 — CACHE
# ============================================================

class _Cache:
    def __init__(self, ttl: int = CACHE_TTL):
        self.ttl = ttl
        self._d: Dict[str, Tuple[float, Any]] = {}

    def get(self, k: str):
        e = self._d.get(k)
        if not e:
            return None
        if time.time() - e[0] > self.ttl:
            self._d.pop(k, None)
            return None
        return e[1]

    def set(self, k: str, v: Any):
        self._d[k] = (time.time(), v)

    def invalidate(self, k: Optional[str] = None):
        if k is None:
            self._d.clear()
        else:
            self._d.pop(k, None)


cache = _Cache()


# ============================================================
# SECTION 5 — ERROR BUFFER
# ============================================================

class _Errors:
    def __init__(self, maxlen: int = 50):
        self._q: deque = deque(maxlen=maxlen)

    def record(self, src: str, err: str):
        safe = _URI_PAT.sub("mongodb://[REDACTED]", str(err))
        self._q.append({"ts": now_ist(), "src": src, "err": safe[:280]})

    def recent(self, n: int = 20):
        return list(self._q)[-n:][::-1]


errors = _Errors()


# ============================================================
# SECTION 6 — LATENCY TRACKER
# ============================================================

class _Latency:
    def __init__(self, maxlen: int = MAX_LAT):
        self._d: Dict[str, deque] = {}
        self._m = maxlen

    def record(self, key: str, ms: Optional[float]):
        if ms is None:
            return
        self._d.setdefault(key, deque(maxlen=self._m)).append(round(ms, 1))

    def stats(self, key: str) -> Dict[str, Any]:
        d = list(self._d.get(key, []))
        if not d:
            return {"cur": None, "avg": None, "min": None, "max": None}
        return {
            "cur": d[-1],
            "avg": round(sum(d) / len(d), 1),
            "min": min(d),
            "max": max(d),
        }


latency = _Latency()


# ============================================================
# SECTION 7 — AUDIT LOG
# ============================================================

class _Audit:
    def __init__(self, maxlen: int = 200):
        self._q: deque = deque(maxlen=maxlen)

    def log(self, admin: int, action: str, target: str = "-",
            result: str = "-", extra: str = ""):
        self._q.append({
            "ts": now_ist(), "admin": admin, "action": action,
            "target": target, "result": result, "extra": extra,
        })
        logger.info(f"[AUDIT] admin={admin} action={action} target={target}")

    def recent(self, n: int = 20):
        return list(self._q)[-n:][::-1]


audit = _Audit()


# ============================================================
# SECTION 8 — DIAGNOSTICS
# ============================================================

class Diagnostics:

    @staticmethod
    async def ping(db) -> Optional[float]:
        try:
            t0 = time.time()
            await db.command("ping")
            return (time.time() - t0) * 1000.0
        except Exception as e:
            errors.record("ping", str(e))
            return None

    @staticmethod
    async def db_stats(db) -> Optional[Dict[str, Any]]:
        try:
            return await db.command("dbStats")
        except Exception as e:
            errors.record("dbStats", str(e))
            return None

    @staticmethod
    async def coll_stats(db, name: str) -> Optional[Dict[str, Any]]:
        try:
            return await db.command("collStats", name)
        except Exception as e:
            errors.record(f"collStats:{name}", str(e))
            return None

    @staticmethod
    async def list_collections(db) -> List[str]:
        try:
            return sorted(await db.list_collection_names())
        except Exception as e:
            errors.record("listCollections", str(e))
            return []

    @staticmethod
    async def build_version(db) -> Optional[str]:
        try:
            return (await db.command("buildInfo")).get("version")
        except Exception:
            return None

    @staticmethod
    async def list_indexes(db, coll: str) -> List[Dict[str, Any]]:
        try:
            out = []
            async for ix in db[coll].list_indexes():
                out.append(ix)
            return out
        except Exception as e:
            errors.record(f"listIndexes:{coll}", str(e))
            return []

    @staticmethod
    async def sample(db, coll: str, limit: int = 5) -> List[Dict[str, Any]]:
        try:
            return await db[coll].find({}).limit(limit).to_list(length=limit)
        except Exception as e:
            errors.record(f"sample:{coll}", str(e))
            return []


# ============================================================
# SECTION 9 — STATS MANAGER
# ============================================================

class StatsManager:

    def _entries(self, cat: str) -> List:
        try:
            if cat == "system":
                return db_registry.system_entries()
            if cat == "user":
                return db_registry.user_entries()
            if cat == "media":
                return db_registry.media_entries()
        except Exception:
            pass
        return []

    def _find_entry(self, cat: str, index: int):
        for e in self._entries(cat):
            if e.index == index:
                return e
        return None

    async def db_info(self, cat: str, index: int) -> Optional[Dict[str, Any]]:
        e = self._find_entry(cat, index)
        if not e:
            return None
        return await self._gather(cat, e)

    async def category(self, cat: str) -> Dict[str, Any]:
        key = f"cat:{cat}"
        cached = cache.get(key)
        if cached:
            return cached
        entries = self._entries(cat)
        results = await asyncio.gather(*[self._gather(cat, e) for e in entries])
        totals = self._totals(results)
        data = {
            "items": results,
            "totals": totals,
            "updated": now_ist(),
            "count": len(results),
            "category": cat,
        }
        cache.set(key, data)
        return data

    async def overall(self) -> Dict[str, Any]:
        cached = cache.get("overall")
        if cached:
            return cached
        s, u, m = await asyncio.gather(
            self.category("system"),
            self.category("user"),
            self.category("media"),
        )
        overall_totals = self._merge([
            s["totals"], u["totals"], m["totals"],
        ])
        data = {
            "system": s, "user": u, "media": m,
            "totals": overall_totals,
            "count": s["count"] + u["count"] + m["count"],
            "updated": now_ist(),
        }
        cache.set("overall", data)
        return data

    async def _gather(self, cat: str, entry) -> Dict[str, Any]:
        db = entry.db
        out = {
            "cat": cat, "index": entry.index, "label": entry.label,
            "online": False, "ping_ms": None, "version": None,
            "collections": 0, "objects": 0,
            "data_size": 0, "storage_size": 0, "index_size": 0,
            "avg_obj": 0, "collection_names": [],
        }
        p = await Diagnostics.ping(db)
        if p is None:
            return out
        out["online"] = True
        out["ping_ms"] = round(p, 1)
        latency.record(f"{cat}:{entry.label}", p)

        st = await Diagnostics.db_stats(db)
        if st:
            out["collections"] = st.get("collections", 0)
            out["objects"] = st.get("objects", 0)
            out["data_size"] = st.get("dataSize", 0)
            out["storage_size"] = st.get("storageSize", 0)
            out["index_size"] = st.get("indexSize", 0)
            out["avg_obj"] = st.get("avgObjSize", 0) or 0

        out["collection_names"] = await Diagnostics.list_collections(db)
        out["version"] = await Diagnostics.build_version(db)
        return out

    def _totals(self, items: List[Dict[str, Any]]) -> Dict[str, int]:
        t = {"objects": 0, "data_size": 0, "storage_size": 0,
             "index_size": 0, "collections": 0}
        for i in items:
            if not i["online"]:
                continue
            t["objects"] += i["objects"]
            t["data_size"] += i["data_size"]
            t["storage_size"] += i["storage_size"]
            t["index_size"] += i["index_size"]
            t["collections"] += i["collections"]
        return t

    def _merge(self, totals: List[Dict[str, int]]) -> Dict[str, int]:
        m = {"objects": 0, "data_size": 0, "storage_size": 0,
             "index_size": 0, "collections": 0}
        for t in totals:
            for k in m:
                m[k] += t.get(k, 0)
        return m


stats = StatsManager()


# ============================================================
# SECTION 10 — LIVE MONITOR
# ============================================================

class LiveMonitor:
    def __init__(self):
        self._tasks: Dict[int, asyncio.Task] = {}
        self._state: Dict[int, Dict[str, Any]] = {}

    def is_live(self, chat_id: int) -> bool:
        t = self._tasks.get(chat_id)
        return t is not None and not t.done()

    def interval(self, chat_id: int) -> int:
        return _live_intervals.get(chat_id, LIVE_DEFAULT)

    async def start(self, client, chat_id, msg_id, view, extra):
        await self.stop(chat_id)
        self._state[chat_id] = {
            "interval": self.interval(chat_id),
            "view": view,
            "extra": extra,
        }
        self._tasks[chat_id] = asyncio.create_task(
            self._loop(client, chat_id, msg_id)
        )

    async def stop(self, chat_id):
        t = self._tasks.pop(chat_id, None)
        self._state.pop(chat_id, None)
        if t and not t.done():
            t.cancel()
            try:
                await t
            except Exception:
                pass

    async def _loop(self, client, chat_id, msg_id):
        try:
            while True:
                await asyncio.sleep(self.interval(chat_id))
                cache.invalidate()
                try:
                    cur = _live_view.get(
                        chat_id, {"view": "main", "extra": {}})
                    text, kb = await build_view(cur["view"], cur["extra"])
                    if cur["view"] == "main":
                        kb = kb_main(chat_id)

                    await client.edit_message_text(
                        chat_id=chat_id,
                        message_id=msg_id,
                        text=text,
                        reply_markup=kb,
                        parse_mode=ParseMode.HTML,
                        disable_web_page_preview=True,
                    )
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    err = str(e).lower()
                    if "not modified" in err:
                        continue
                    if "message to edit not found" in err:
                        return
        except asyncio.CancelledError:
            return


live = LiveMonitor()


# ============================================================
# SECTION 11 — CONFIRMATIONS
# ============================================================

class Confirmations:
    def __init__(self, ttl: int = 180):
        self._p: Dict[str, Dict[str, Any]] = {}
        self._ttl = ttl

    def _k(self, uid, tok):
        return f"{uid}:{tok}"

    def start(self, uid, tok, payload):
        self._p[self._k(uid, tok)] = {
            "step": 1, "payload": payload,
            "exp": time.time() + self._ttl,
        }

    def get(self, uid, tok):
        e = self._p.get(self._k(uid, tok))
        if not e:
            return None
        if time.time() > e["exp"]:
            self._p.pop(self._k(uid, tok), None)
            return None
        return e

    def advance(self, uid, tok):
        e = self.get(uid, tok)
        if not e:
            return None
        e["step"] += 1
        e["exp"] = time.time() + self._ttl
        return e

    def cancel(self, uid, tok):
        self._p.pop(self._k(uid, tok), None)

    def cleanup(self):
        now = time.time()
        for k in list(self._p.keys()):
            if self._p[k]["exp"] < now:
                self._p.pop(k, None)


confirms = Confirmations()


# ============================================================
# SECTION 11b — TELEGRAM FILE IDENTITY ACROSS MEDIA SHARDS
# ============================================================

async def _scan_media_file_identity_duplicates(entries, remove: bool = False):
    """Find repeated Telegram file_unique_id values across MEDIA shards."""
    offline = [entry.label for entry in entries if not entry.online]
    if offline:
        raise RuntimeError(f"MEDIA shard(s) offline: {', '.join(offline)}")

    seen_unique_ids = set()
    duplicate_ids: Dict[int, List[Any]] = {}
    per_shard: Dict[int, Dict[str, Any]] = {}
    total_duplicates = 0

    for entry in entries:
        collection = entry.db["media_files"]
        cursor = collection.find(
            {},
            {"_id": 1, "file_unique_id": 1},
        ).sort("_id", 1)
        async for doc in cursor:
            unique_id = doc.get("file_unique_id")
            unique_id = unique_id if isinstance(unique_id, str) else ""
            if not unique_id:
                continue

            is_duplicate = unique_id in seen_unique_ids
            seen_unique_ids.add(unique_id)

            if not is_duplicate:
                continue

            total_duplicates += 1
            shard = per_shard.setdefault(entry.index, {
                "name": entry.label,
                "duplicates": 0,
                "deleted": 0,
            })
            shard["duplicates"] += 1
            if remove:
                duplicate_ids.setdefault(entry.index, []).append(doc["_id"])

    deleted = 0
    if remove:
        entries_by_index = {entry.index: entry for entry in entries}
        for index, ids in duplicate_ids.items():
            entry = entries_by_index[index]
            for offset in range(0, len(ids), 500):
                result = await entry.db["media_files"].delete_many({
                    "_id": {"$in": ids[offset:offset + 500]},
                })
                count = int(result.deleted_count)
                per_shard[index]["deleted"] += count
                deleted += count

    return {
        "duplicates": total_duplicates,
        "deleted": deleted,
        "per_shard": list(per_shard.values()),
    }


# ============================================================
# SECTION 12 — DUPLICATE SCAN (Telegram file identity)
# ============================================================

async def duplicate_scan(cat: str, index: int) -> Dict[str, Any]:
    """Scan indexed files across all online MEDIA shards."""
    if cat != "media":
        return {"ok": False, "reason": "File identity scans are for MEDIA databases"}
    if not stats._find_entry(cat, index):
        return {"ok": False, "reason": "DB not found"}

    entries = sorted(stats._entries("media"), key=lambda e: e.index)
    if not entries:
        return {"ok": False, "reason": "No MEDIA databases are online"}

    try:
        result = await _scan_media_file_identity_duplicates(entries)
    except Exception as e:
        errors.record("dup:media:media_files", str(e))
        return {"ok": False, "reason": "MEDIA file scan failed"}

    return {
        "ok": True,
        "total": result["duplicates"],
        "per_collection": result["per_shard"],
        "key_used": ["file_unique_id"],
    }


async def do_dup_scan_coll(cat: str, index: int, name: str):
    """Scan ONE collection for duplicates across multiple keys."""
    entry = stats._find_entry(cat, index)
    if not entry or not entry.online:
        return (
            f"❌ {F.sc('db offline')}",
            InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"{F.EMO['back']} {F.sc('back')}",
                    callback_data=f"adm:dbc_coll:{cat}:{index}:{name}")]]),
        )

    result: Dict[str, List[Dict[str, Any]]] = {}
    scan_error = False
    for key in ("file_id", "file_unique_id"):
        try:
            pipeline = [
                {"$match": {
                    key: {"$type": "string", "$ne": ""},
                }},
                {"$group": {"_id": f"${key}", "n": {"$sum": 1}}},
                {"$match": {"n": {"$gt": 1}}},
                {"$sort": {"n": -1}},
                {"$limit": 10},
            ]
            rows = await entry.db[name].aggregate(pipeline).to_list(length=10)
            if rows:
                result[key] = rows
        except Exception as e:
            errors.record(f"dup_coll:{name}:{key}", str(e))
            scan_error = True

    lines = [
        _header(), "",
        f"🧹 <b>{F.fb('DUPLICATE SCAN')}</b>",
        F.DIV, "",
        f"📚 {F.sc('collection')} · <code>{esc(name)}</code>",
        f"🗄️ {F.sc('database')} · {cat.upper()} {index:02d}",
        "",
    ]
    if scan_error:
        lines.append(f"🔴 {F.sc('scan failed; see database errors')}")
        return "\n".join(lines), InlineKeyboardMarkup([[
            InlineKeyboardButton(
                f"{F.EMO['back']} {F.sc('back')}",
                callback_data=f"adm:dbc_coll:{cat}:{index}:{name}")]])


    if not result:
        lines.append(f"🟢 {F.sc('no duplicates found')}")
    else:
        total = sum(len(v) for v in result.values())
        lines.append(f"📊 {F.sc('total groups')} · <b>{total}</b>")
        lines.append("")
        for k, items in result.items():
            lines.append(f"<b>{F.fb(f'BY {k.upper()}')}</b>")
            for item in items[:10]:
                val = str(item["_id"])[:40]
                cnt = item["n"]
                lines.append(
                    f"  • <code>{esc(val)}</code> · <b>{cnt}x</b>"
                )
            lines.append("")

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"{F.EMO['refresh']} {F.sc('rescan')}",
            callback_data=f"adm:dbc_dup_coll:{cat}:{index}:{name}")],
        [
            InlineKeyboardButton(
                f"📄 {F.sc('recent docs')}",
                callback_data=f"adm:dbc_recent:{cat}:{index}:{name}:5"),
            InlineKeyboardButton(
                f"{F.EMO['back']} {F.sc('back')}",
                callback_data=f"adm:dbc_coll:{cat}:{index}:{name}"),
        ],
    ])
    return "\n".join(lines), kb


# ============================================================
# SECTION 13 — VIEW BUILDERS
# ============================================================

def _header() -> str:
    return (
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>\n"
        f"{F.EMO['db']} <b>{F.fb('DATABASE CONTROL CENTER')}</b>\n"
        f"{F.DIV}"
    )


def _status(items: List[Dict[str, Any]]) -> str:
    if not items:
        return f"⚪ {F.sc('no databases')}"
    up = sum(1 for i in items if i["online"])
    if up == len(items):
        return f"🟢 {F.sc('healthy')}"
    if up == 0:
        return f"🔴 {F.sc('offline')}"
    return f"🟡 {up}/{len(items)} {F.sc('online')}"


def _db_block(cat: str, d: Dict[str, Any]) -> str:
    status = "🟢" if d["online"] else "🔴"
    ping = f"{d['ping_ms']}ms" if d["ping_ms"] is not None else "—"
    label = d.get("label") or f"{cat}-{d['index']:02d}"

    lines = [
        f"{status} <b>{F.fb(f'{cat.upper()} DB {d['index']:02d}')}</b>",
        F.DIV_S,
        one_line("cluster", esc(label), "🏷️"),
        one_line("ping", ping, "⏱️"),
        one_line("documents", FM.num(d["objects"]), "📦"),
        one_line("storage", FM.size(d["storage_size"]), "💾"),
        one_line("data", FM.size(d["data_size"]), "📄"),
        one_line("indexes", FM.size(d["index_size"]), "🧩"),
        one_line("collections", FM.num(d["collections"]), "🗂️"),
        "",
        storage_usage_block(d["storage_size"], online=d["online"]),
    ]

    return "\n".join(lines)


def _totals_block(t: Dict[str, int]) -> str:
    return "\n".join([
        f"📊 <b>{F.fb('ALL DATABASES TOTAL')}</b>",
        F.DIV_S,
        one_line("documents", FM.num(t["objects"]), "📦"),
        one_line("storage", FM.size(t["storage_size"]), "💾"),
        one_line("data", FM.size(t["data_size"]), "📄"),
        one_line("indexes", FM.size(t["index_size"]), "🧩"),
        one_line("collections", FM.num(t["collections"]), "🗂️"),
    ])


# ============================================================
# SECTION 14 — VIEW MAIN
# ============================================================

def kb_main(chat_id: int = 0) -> InlineKeyboardMarkup:
    cur_iv = _live_intervals.get(chat_id, LIVE_DEFAULT)
    is_live = live.is_live(chat_id)

    rows: List[List[InlineKeyboardButton]] = [
        [InlineKeyboardButton(
            f"{F.EMO['server']} {F.sc('system databases')}",
            callback_data="adm:dbc_cat:system")],
        [InlineKeyboardButton(
            f"{F.EMO['users']} {F.sc('user databases')}",
            callback_data="adm:dbc_cat:user")],
        [InlineKeyboardButton(
            f"{F.EMO['film']} {F.sc('media databases')}",
            callback_data="adm:dbc_cat:media")],
        [InlineKeyboardButton(
            f"{F.EMO['chart']} {F.sc('overall')}",
            callback_data="adm:dbc_cat:overall")],
        [
            InlineKeyboardButton(
                f"❤️ {F.sc('health')}",
                callback_data="adm:dbc_health:overall"),
            InlineKeyboardButton(
                f"⚡ {F.sc('performance')}",
                callback_data="adm:dbc_perf:overall"),
        ],
        [
            InlineKeyboardButton(
                f"🧹 {F.sc('duplicates')}",
                callback_data="adm:dbc_dups:media:1"),
            InlineKeyboardButton(
                f"🧩 {F.sc('indexes')}",
                callback_data="adm:dbc_colls:media:1:1"),
        ],
        [
            InlineKeyboardButton(
                f"📋 {F.sc('activity log')}",
                callback_data="adm:dbc_audit"),
            InlineKeyboardButton(
                f"🚨 {F.sc('errors')}",
                callback_data="adm:dbc_errors"),
        ],
    ]

    # Live toggle
    live_label = (
        f"🔴 {F.sc('stop live')}" if is_live
        else f"📡 {F.sc('start live')}"
    )
    rows.append([InlineKeyboardButton(
        live_label, callback_data="adm:dbc_live_toggle")])

    # Interval row
    iv_row = []
    for n in LIVE_OPTIONS:
        mark = "✅ " if (is_live and n == cur_iv) else ""
        iv_row.append(InlineKeyboardButton(
            f"{mark}{n}s", callback_data=f"adm:dbc_livego:{n}"))
    rows.append(iv_row)

    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['refresh']} {F.sc('refresh')}",
            callback_data="adm:dbc_refresh"),
        InlineKeyboardButton(
            f"{F.EMO['close']} {F.sc('close')}",
            callback_data="adm:dbc_close"),
    ])

    return InlineKeyboardMarkup(rows)


async def view_main():
    data = await stats.overall()
    s, u, m = data["system"], data["user"], data["media"]
    tot = data["totals"]

    total_docs = max(1,
        s["totals"]["objects"] + u["totals"]["objects"] + m["totals"]["objects"])
    sp = (s["totals"]["objects"] / total_docs) * 100
    up = (u["totals"]["objects"] / total_docs) * 100
    mp = (m["totals"]["objects"] / total_docs) * 100

    lines = [
        _header(), "",
        f"{F.EMO['clock']} {F.sc('updated')} · <code>{data['updated']}</code>",
        "",
        f"<b>{F.fb('DATABASE CATEGORIES')}</b>",
        f"{F.EMO['server']} {F.sc('system')} · <b>{s['count']}</b> {F.sc('databases')}",
        f"{F.EMO['users']} {F.sc('user')} · <b>{u['count']}</b> {F.sc('databases')}",
        f"{F.EMO['film']} {F.sc('media')} · <b>{m['count']}</b> {F.sc('databases')}",
        f"{F.EMO['db']} {F.sc('total')} · <b>{data['count']}</b> {F.sc('databases')}",
        "",
        f"<b>{F.fb('DOCUMENT DISTRIBUTION')}</b>",
        bar_line("system", sp, width=10),
        bar_line("user", up, width=10),
        bar_line("media", mp, width=10),
        "",
        F.DIV,
        _totals_block(tot),
        F.DIV,
        "",
        f"<b>{F.fb('SYSTEM STATUS')}</b>",
        f"{F.EMO['server']} {F.sc('system')} · {_status(s['items'])}",
        f"{F.EMO['users']} {F.sc('user')} · {_status(u['items'])}",
        f"{F.EMO['film']} {F.sc('media')} · {_status(m['items'])}",
        "",
        F.DIV_S,
        f"📡 {F.sc('live monitoring')} · 🟢 {F.sc('ready')}",
    ]
    return "\n".join(lines), kb_main(0)


# ============================================================
# SECTION 15 — VIEW CATEGORY
# ============================================================

def kb_category(cat, data):
    rows: List[List[InlineKeyboardButton]] = []
    pair: List[InlineKeyboardButton] = []
    for item in data["items"]:
        emoji = "🟢" if item["online"] else "🔴"
        label = f"{emoji} {cat.upper()} {item['index']:02d}"
        pair.append(InlineKeyboardButton(
            label, callback_data=f"adm:dbc_db:{cat}:{item['index']}"))
        if len(pair) == 2:
            rows.append(pair)
            pair = []
    if pair:
        rows.append(pair)

    rows.append([InlineKeyboardButton(
        f"📊 {F.sc('all')} {cat.upper()}",
        callback_data=f"adm:dbc_catall:{cat}")])

    if cat != "overall":
        rows.append([
            InlineKeyboardButton(
                f"❤️ {F.sc('health')}",
                callback_data=f"adm:dbc_health:{cat}"),
            InlineKeyboardButton(
                f"⚡ {F.sc('performance')}",
                callback_data=f"adm:dbc_perf:{cat}"),
        ])

    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['refresh']} {F.sc('refresh')}",
            callback_data=f"adm:dbc_cat:{cat}"),
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data="adm:dbc_main"),
    ])
    return InlineKeyboardMarkup(rows)


async def view_category(cat: str):
    if cat == "overall":
        return await view_main()
    data = await stats.category(cat)

    titles = {
        "system": (F.EMO['server'], "SYSTEM DATABASE CONTROL"),
        "user":   (F.EMO['users'],  "USER DATABASE CONTROL"),
        "media":  (F.EMO['film'],   "MEDIA DATABASE CONTROL"),
    }
    icon, t = titles.get(cat, (F.EMO['db'], "DATABASE CONTROL"))

    lines = [
        _header(), "",
        f"{icon} <b>{F.fb(t)}</b>",
        F.DIV, "",
        f"📊 <b>{data['count']} {F.sc('configured')}</b>",
        f"🕐 <code>{data['updated']}</code>",
        "",
    ]
    for item in data["items"]:
        lines.append(_db_block(cat, item))
        lines.append("")
        lines.append(F.DIV)
        lines.append("")
    lines.append(_totals_block(data["totals"]))
    return "\n".join(lines), kb_category(cat, data)


# ============================================================
# SECTION 16 — VIEW DB
# ============================================================

def kb_db(cat, index):
    search_row = [InlineKeyboardButton(
        f"🔍 {F.sc('search')}",
        callback_data=f"adm:dbc_search:{cat}:{index}")]
    if cat == "media":
        search_row.append(InlineKeyboardButton(
            f"🧹 {F.sc('duplicates')}",
            callback_data=f"adm:dbc_dups:{cat}:{index}"))
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"🧱 {F.sc('collections')}",
                callback_data=f"adm:dbc_colls:{cat}:{index}:1"),
            InlineKeyboardButton(
                f"📊 {F.sc('statistics')}",
                callback_data=f"adm:dbc_stats:{cat}:{index}"),
        ],
        search_row,
        [
            InlineKeyboardButton(
                f"🧩 {F.sc('indexes')}",
                callback_data=f"adm:dbc_colls:{cat}:{index}:1"),
            InlineKeyboardButton(
                f"🗑️ {F.sc('clear data')}",
                callback_data=f"adm:dbc_clear:{cat}:{index}"),
        ],
        [
            InlineKeyboardButton(
                f"❤️ {F.sc('health')}",
                callback_data=f"adm:dbc_health:{cat}"),
            InlineKeyboardButton(
                f"⚡ {F.sc('performance')}",
                callback_data=f"adm:dbc_perf:{cat}"),
        ],
        [
            InlineKeyboardButton(
                f"{F.EMO['refresh']} {F.sc('refresh')}",
                callback_data=f"adm:dbc_db:{cat}:{index}"),
            InlineKeyboardButton(
                f"{F.EMO['back']} {F.sc('back')}",
                callback_data=f"adm:dbc_cat:{cat}"),
        ],
    ])


async def view_db(cat: str, index: int):
    info = await stats.db_info(cat, index)
    if not info:
        return (
            f"❌ {F.sc('database not found')}",
            InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"{F.EMO['back']} {F.sc('back')}",
                    callback_data=f"adm:dbc_cat:{cat}")]]),
        )

    status = f"🟢 {F.sc('online')}" if info["online"] else f"🔴 {F.sc('offline')}"
    ping = f"{info['ping_ms']}ms" if info["ping_ms"] is not None else "—"
    ver = info["version"] or "—"

    overhead = (info["index_size"] / max(1, info["data_size"])) * 100
    eff = (info["data_size"] / max(1, info["storage_size"])) * 100

    lines = [
        _header(), "",
        f"🗄️ <b>{F.fb(f'{cat.upper()} DATABASE {info['index']:02d}')}</b>",
        F.DIV, "",
        one_line("cluster", esc(info['label']), "🏷️"),
        f"📡 {F.sc('status')} · {status}",
        one_line("ping", ping, "⏱️"),
        one_line("mongodb", esc(ver), "🍃"),
        "",
        one_line("documents", FM.num(info['objects']), "📦"),
        one_line("collections", FM.num(info['collections']), "🗂️"),
        one_line("data", FM.size(info['data_size']), "📄"),
        one_line("storage", FM.size(info['storage_size']), "💾"),
        one_line("indexes", FM.size(info['index_size']), "🧩"),
        one_line("avg object", FM.size(int(info['avg_obj'] or 0)), "📐"),
        "",
        storage_usage_block(info["storage_size"], online=info["online"]),
        "",
        f"<b>{F.fb('PERFORMANCE METRICS')}</b>",
        bar_line("index overhead", overhead, width=10),
        bar_line("storage efficiency", eff, width=10),
        "",
        F.DIV,
        f"📚 <b>{F.fb('COLLECTIONS')}</b>",
        F.DIV,
    ]

    names = info["collection_names"]
    if not names:
        lines.append(f"⚪ {F.sc('no collections')}")
    else:
        for i, n in enumerate(names[:20], 1):
            lines.append(f"  <b>{i:02d}.</b> <code>{esc(n)}</code>")
        if len(names) > 20:
            lines.append(f"  <i>… +{len(names) - 20} {F.sc('more')}</i>")

    return "\n".join(lines), kb_db(cat, index)


# ============================================================
# SECTION 17 — VIEW COLLECTIONS
# ============================================================

def kb_colls(cat, index, page, total_pages, names):
    rows: List[List[InlineKeyboardButton]] = [
        [InlineKeyboardButton(
            f"📁 {n[:40]}",
            callback_data=f"adm:dbc_coll:{cat}:{index}:{n}")]
        for n in names[:COLL_PAGE]
    ]
    nav: List[InlineKeyboardButton] = []
    if page > 1:
        nav.append(InlineKeyboardButton(
            f"{F.EMO['prev']} {F.sc('prev')}",
            callback_data=f"adm:dbc_colls:{cat}:{index}:{page - 1}"))
    nav.append(InlineKeyboardButton(
        f"{page}/{total_pages}", callback_data="adm:dbc_noop"))
    if page < total_pages:
        nav.append(InlineKeyboardButton(
            f"{F.sc('next')} {F.EMO['next']}",
            callback_data=f"adm:dbc_colls:{cat}:{index}:{page + 1}"))
    if nav:
        rows.append(nav)
    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data=f"adm:dbc_db:{cat}:{index}"),
        InlineKeyboardButton(
            f"{F.EMO['brand']} {F.sc('home')}",
            callback_data="adm:dbc_main"),
    ])
    return InlineKeyboardMarkup(rows)


async def view_colls(cat: str, index: int, page: int):
    info = await stats.db_info(cat, index)
    if not info:
        return (
            f"❌ {F.sc('db not found')}",
            InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"{F.EMO['back']} {F.sc('back')}",
                    callback_data=f"adm:dbc_cat:{cat}")]]),
        )
    names = info["collection_names"]
    total = len(names)
    tp = max(1, (total + COLL_PAGE - 1) // COLL_PAGE)
    page = max(1, min(page, tp))
    start = (page - 1) * COLL_PAGE
    slice_ = names[start:start + COLL_PAGE]

    lines = [
        _header(), "",
        f"🧱 <b>{F.fb(f'COLLECTIONS — {cat.upper()} DB {index:02d}')}</b>",
        F.DIV, "",
        f"📊 {F.sc('total')} · <code>{total}</code>",
        f"📄 {F.sc('page')} · <code>{page}/{tp}</code>",
        "",
    ]
    for i, n in enumerate(slice_, start=start + 1):
        lines.append(f"  <b>{i:02d}.</b> <code>{esc(n)}</code>")

    return "\n".join(lines), kb_colls(cat, index, page, tp, slice_)


# ============================================================
# SECTION 18 — VIEW COLLECTION DETAIL
# ============================================================

def kb_coll(cat, index, name):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton(
                f"📄 {F.sc('recent docs')}",
                callback_data=f"adm:dbc_recent:{cat}:{index}:{name}:5"),
            InlineKeyboardButton(
                f"🔑 {F.sc('indexes')}",
                callback_data=f"adm:dbc_idx:{cat}:{index}:{name}"),
        ],
        [
            InlineKeyboardButton(
                f"🧹 {F.sc('find duplicates')}",
                callback_data=f"adm:dbc_dup_coll:{cat}:{index}:{name}"),
            InlineKeyboardButton(
                f"🔍 {F.sc('search')}",
                callback_data=f"adm:dbc_search_coll:{cat}:{index}:{name}"),
        ],
        [InlineKeyboardButton(
            f"🗑️ {F.sc('clear collection')}",
            callback_data=f"adm:dbc_clear_coll:{cat}:{index}:{name}")],
        [
            InlineKeyboardButton(
                f"{F.EMO['refresh']} {F.sc('refresh')}",
                callback_data=f"adm:dbc_coll:{cat}:{index}:{name}"),
            InlineKeyboardButton(
                f"{F.EMO['back']} {F.sc('back')}",
                callback_data=f"adm:dbc_colls:{cat}:{index}:1"),
        ],
    ])


async def view_coll(cat: str, index: int, name: str):
    entry = stats._find_entry(cat, index)
    if not entry:
        return (
            f"❌ {F.sc('db not found')}",
            InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"{F.EMO['back']} {F.sc('back')}",
                    callback_data=f"adm:dbc_cat:{cat}")]]),
        )

    st = await Diagnostics.coll_stats(entry.db, name)

    lines = [
        _header(), "",
        f"🧱 <b>{F.fb('COLLECTION')}</b>",
        F.DIV, "",
        f"📚 {F.sc('name')} · <code>{esc(name)}</code>",
        f"🗄️ {F.sc('database')} · {cat.upper()} {index:02d} ({esc(entry.label)})",
        "",
    ]

    if st:
        data_sz = st.get("size", 0) or 0
        stor_sz = st.get("storageSize", 0) or 0
        idx_sz = st.get("totalIndexSize", 0) or 0
        eff = (data_sz / max(1, stor_sz)) * 100
        oh = (idx_sz / max(1, data_sz)) * 100

        lines += [
            one_line("documents", FM.num(st.get("count", 0)), "📦"),
            one_line("data", FM.size(data_sz), "📄"),
            one_line("storage", FM.size(stor_sz), "💾"),
            one_line("index size", FM.size(idx_sz), "🧩"),
            one_line("avg object",
                     FM.size(int(st.get("avgObjSize", 0) or 0)), "📐"),
            one_line("indexes",
                     str(len(st.get("indexSizes", {}) or {})), "🔑"),
            "",
            f"<b>{F.fb('METRICS')}</b>",
            bar_line("storage efficiency", eff, width=10),
            bar_line("index overhead", oh, width=10),
        ]
    else:
        lines.append(f"⚪ {F.sc('statistics unavailable')}")

    return "\n".join(lines), kb_coll(cat, index, name)


# ============================================================
# SECTION 19 — VIEW RECENT DOCS
# ============================================================

async def view_recent(cat: str, index: int, name: str, limit: int):
    entry = stats._find_entry(cat, index)
    if not entry:
        return (
            f"❌ {F.sc('db not found')}",
            InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"{F.EMO['back']} {F.sc('back')}",
                    callback_data=f"adm:dbc_cat:{cat}")]]),
        )

    docs = await Diagnostics.sample(entry.db, name, limit)
    lines = [
        _header(), "",
        f"📄 <b>{F.fb('RECENT DOCUMENTS')}</b>",
        f"📚 <code>{esc(name)}</code>",
        F.DIV, "",
        f"🔢 {F.sc('limit')} · <code>{limit}</code>",
        f"📊 {F.sc('returned')} · <code>{len(docs)}</code>",
        "",
    ]
    if not docs:
        lines.append(f"⚪ {F.sc('no documents')}")
    for i, d in enumerate(docs, 1):
        lines.append(f"<b>{F.fb(f'DOCUMENT {i:02d}')}</b>")
        lines.append(summarize_doc(d))
        lines.append("")

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"LIMIT {n}",
            callback_data=f"adm:dbc_recent:{cat}:{index}:{name}:{n}")
         for n in RECENT_LIMITS],
        [
            InlineKeyboardButton(
                f"{F.EMO['refresh']} {F.sc('refresh')}",
                callback_data=f"adm:dbc_recent:{cat}:{index}:{name}:{limit}"),
            InlineKeyboardButton(
                f"{F.EMO['back']} {F.sc('back')}",
                callback_data=f"adm:dbc_coll:{cat}:{index}:{name}"),
        ],
    ])
    return "\n".join(lines), kb


# ============================================================
# SECTION 20 — VIEW INDEXES
# ============================================================

async def view_indexes(cat: str, index: int, name: str):
    entry = stats._find_entry(cat, index)
    if not entry:
        return (
            f"❌ {F.sc('db not found')}",
            InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"{F.EMO['back']} {F.sc('back')}",
                    callback_data=f"adm:dbc_cat:{cat}")]]),
        )

    idxs = await Diagnostics.list_indexes(entry.db, name)
    lines = [
        _header(), "",
        f"🔑 <b>{F.fb('INDEXES')}</b>",
        f"📚 <code>{esc(name)}</code>",
        F.DIV, "",
        f"🔢 {F.sc('total')} · <code>{len(idxs)}</code>",
        "",
    ]
    if not idxs:
        lines.append(f"⚪ {F.sc('no indexes')}")
    for i, ix in enumerate(idxs, 1):
        safe = redact(ix)
        lines.append(f"<b>{i:02d}. {esc(safe.get('name', '?'))}</b>")
        lines.append(
            f"  🔑 {F.sc('keys')} · <code>{esc(safe.get('key', {}))}</code>")
        if safe.get("unique"):
            lines.append(f"  ✅ {F.sc('unique')}")
        if safe.get("sparse"):
            lines.append(f"  ✅ {F.sc('sparse')}")
        if "expireAfterSeconds" in safe:
            lines.append(
                f"  ⏱️ {F.sc('ttl')} · "
                f"<code>{safe['expireAfterSeconds']}s</code>")
        lines.append("")

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            f"{F.EMO['refresh']} {F.sc('refresh')}",
            callback_data=f"adm:dbc_idx:{cat}:{index}:{name}"),
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data=f"adm:dbc_coll:{cat}:{index}:{name}"),
    ]])
    return "\n".join(lines), kb


# ============================================================
# SECTION 21 — VIEW HEALTH
# ============================================================

async def view_health(cat: str):
    if cat == "overall":
        data = await stats.overall()
        groups = [
            ("system", data["system"]),
            ("user", data["user"]),
            ("media", data["media"]),
        ]
    else:
        c = await stats.category(cat)
        groups = [(cat, c)]

    lines = [_header(), "", f"❤️ <b>{F.fb('DATABASE HEALTH')}</b>", F.DIV, ""]
    all_ok = True
    for name, cd in groups:
        lines.append(f"<b>{name.upper()}</b> · {_status(cd['items'])}")
        for i in cd["items"]:
            if i["online"]:
                lines.append(
                    f"  🟢 <code>{esc(i['label'])}</code> · "
                    f"<code>{i['ping_ms']}ms</code>"
                )
            else:
                lines.append(
                    f"  🔴 <code>{esc(i['label'])}</code> · {F.sc('offline')}")
                all_ok = False
        lines.append("")

    lines.append(F.DIV)
    lines.append(
        f"🟢 <b>{F.fb('ALL HEALTHY')}</b>" if all_ok
        else f"🟡 <b>{F.fb('WARNINGS PRESENT')}</b>"
    )

    back = "adm:dbc_main" if cat == "overall" else f"adm:dbc_cat:{cat}"
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            f"{F.EMO['refresh']} {F.sc('refresh')}",
            callback_data=f"adm:dbc_health:{cat}"),
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data=back),
    ]])
    return "\n".join(lines), kb


# ============================================================
# SECTION 22 — VIEW PERFORMANCE
# ============================================================

async def view_perf(cat: str):
    if cat == "overall":
        data = await stats.overall()
        groups = [
            ("system", data["system"]),
            ("user", data["user"]),
            ("media", data["media"]),
        ]
    else:
        c = await stats.category(cat)
        groups = [(cat, c)]

    lines = [_header(), "", f"⚡ <b>{F.fb('DATABASE PERFORMANCE')}</b>", F.DIV, ""]
    for name, cd in groups:
        for i in cd["items"]:
            st = latency.stats(f"{name}:{i['label']}")
            cur = st["cur"] if st["cur"] is not None else "—"
            avg = st["avg"] if st["avg"] is not None else "—"
            mn = st["min"] if st["min"] is not None else "—"
            mx = st["max"] if st["max"] is not None else "—"
            lines.append(f"<b>{name.upper()} · {esc(i['label'])}</b>")
            lines.append(f"  ᴄᴜʀ · <code>{cur}ms</code>   ᴀᴠɢ · <code>{avg}ms</code>")
            lines.append(f"  ᴍɪɴ · <code>{mn}ms</code>   ᴍᴀx · <code>{mx}ms</code>")
            if isinstance(st["cur"], (int, float)):
                lat_pct = min(100.0, st["cur"] / 2.0)
                color = P.storage_color(lat_pct)
                bar = P.bar(lat_pct, "storage", width=10, show_percent=False)
                lines.append(f"  {color} <code>{bar}</code>")
            lines.append("")

    back = "adm:dbc_main" if cat == "overall" else f"adm:dbc_cat:{cat}"
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            f"{F.EMO['refresh']} {F.sc('refresh')}",
            callback_data=f"adm:dbc_perf:{cat}"),
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data=back),
    ]])
    return "\n".join(lines), kb


# ============================================================
# SECTION 23 — VIEW AUDIT
# ============================================================

async def view_audit():
    entries = audit.recent(30)
    lines = [_header(), "", f"📋 <b>{F.fb('ACTIVITY LOG')}</b>", F.DIV, ""]
    if not entries:
        lines.append(f"⚪ {F.sc('no activity')}")
    for e in entries:
        lines.append(f"⏱️ <code>{e['ts']}</code>")
        lines.append(f"👤 <code>{e['admin']}</code> · <b>{esc(e['action'])}</b>")
        lines.append(f"🎯 <code>{esc(e['target'])}</code>")
        lines.append(f"✅ <code>{esc(e['result'])}</code>")
        lines.append("")

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            f"{F.EMO['refresh']} {F.sc('refresh')}",
            callback_data="adm:dbc_audit"),
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data="adm:dbc_main"),
    ]])
    return "\n".join(lines), kb


# ============================================================
# SECTION 24 — VIEW ERRORS
# ============================================================

async def view_errors():
    errs = errors.recent(20)
    lines = [_header(), "", f"🚨 <b>{F.fb('DATABASE ERRORS')}</b>", F.DIV, ""]
    if not errs:
        lines.append(f"🟢 {F.sc('no recent errors')}")
    for e in errs:
        lines.append(f"⏱️ <code>{e['ts']}</code>")
        lines.append(f"📍 <b>{esc(e['src'])}</b>")
        lines.append(f"<code>{esc(e['err'])}</code>")
        lines.append("")

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            f"{F.EMO['refresh']} {F.sc('refresh')}",
            callback_data="adm:dbc_errors"),
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data="adm:dbc_main"),
    ]])
    return "\n".join(lines), kb


# ============================================================
# SECTION 25 — VIEW CAT ALL
# ============================================================

async def view_cat_all(cat: str):
    data = await stats.category(cat)
    total_docs = max(1, data["totals"]["objects"])
    lines = [
        _header(), "",
        f"📊 <b>{F.fb(f'ALL {cat.upper()} DATABASES')}</b>",
        F.DIV, "",
        _totals_block(data["totals"]),
        "",
        F.DIV,
        "",
    ]
    for item in data["items"]:
        share = (item["objects"] / total_docs) * 100
        lines.append(_db_block(cat, item, share_pct=share))
        lines.append("")
        lines.append(F.DIV)
        lines.append("")

    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            f"{F.EMO['refresh']} {F.sc('refresh')}",
            callback_data=f"adm:dbc_catall:{cat}"),
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data=f"adm:dbc_cat:{cat}"),
    ]])
    return "\n".join(lines), kb


# ============================================================
# SECTION 26 — VIEW DUPLICATES
# ============================================================

def kb_dups(cat, index):
    rows = [[InlineKeyboardButton(
        f"🔍 {F.sc('start scan')}",
        callback_data=f"adm:dbc_dup_scan:{cat}:{index}")]]
    if cat == "media":
        rows.append([InlineKeyboardButton(
            f"🧹 {F.sc('clear duplicates')}",
            callback_data=f"adm:dbc_dup_remove:{cat}:{index}")])
    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['refresh']} {F.sc('refresh')}",
            callback_data=f"adm:dbc_dups:{cat}:{index}"),
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data=f"adm:dbc_db:{cat}:{index}"),
    ])
    return InlineKeyboardMarkup(rows)


async def view_dups(cat: str, index: int):
    info = await stats.db_info(cat, index)
    if not info:
        return (
            f"❌ {F.sc('db not found')}",
            InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"{F.EMO['back']} {F.sc('back')}",
                    callback_data="adm:dbc_main")]]),
        )

    lines = [
        _header(), "",
        f"🧹 <b>{F.fb('DUPLICATE CONTROL CENTER')}</b>",
        F.DIV, "",
        f"🗄️ {F.sc('target')} · {cat.upper()} DB {index:02d}",
        f"🏷️ {F.sc('cluster')} · <code>{esc(info['label'])}</code>",
        f"📦 {F.sc('scope')} · <code>media_files / Telegram file identity</code>",
        "",
        F.DIV_S,
        f"🔍 {F.sc('scan status')} · <b>{F.sc('ready')}</b>",
        F.DIV_S,
        "",
        f"Press <b>{F.sc('start scan')}</b> to scan media_files across all online MEDIA shards.",
        f"Key checked · <code>file_unique_id</code>",
        "",
        f"⚠️ {F.sc('scan is read-only. Clear removes extra media_files records with a matching file_unique_id across all online MEDIA shards, after 3-step confirmation.')}",
    ]
    return "\n".join(lines), kb_dups(cat, index)


async def view_dup_scan(cat: str, index: int):
    result = await duplicate_scan(cat, index)
    info = await stats.db_info(cat, index)

    lines = [
        _header(), "",
        f"🧹 <b>{F.fb('DUPLICATE SCAN RESULT')}</b>",
        F.DIV, "",
        f"🗄️ {F.sc('target')} · {cat.upper()} DB {index:02d}",
    ]
    if not result.get("ok"):
        lines.append(f"🔴 {F.sc('scan failed')} · {esc(result.get('reason'))}")
        return "\n".join(lines), kb_dups(cat, index)

    lines.append(f"📦 {F.sc('scope')} · <code>media_files / all online MEDIA shards</code>")
    lines.append(
        f"🧹 {F.sc('duplicate records')} · <code>{FM.num(result['total'])}</code>")
    lines.append("")

    if result["per_collection"]:
        lines.append(f"<b>{F.fb('AFFECTED MEDIA SHARDS')}</b>")
        for pc in result["per_collection"][:20]:
            lines.append(
                f"• <code>{esc(pc['name'])}</code> · "
                f"<b>{FM.num(pc['duplicates'])}</b> · <i>file identity</i>"
            )
    else:
        lines.append(f"🟢 {F.sc('no duplicates found')}")

    return "\n".join(lines), kb_dups(cat, index)


async def remove_file_identity_duplicates(
    cat: str, index: int, actor_id: int = 0,
) -> Dict[str, Any]:
    """Keep one record per Telegram file_unique_id across all MEDIA shards."""
    if cat != "media":
        return {
            "ok": False,
            "reason": "File deduplication is limited to MEDIA databases",
        }

    if not stats._find_entry(cat, index):
        return {"ok": False, "reason": "DB not found"}
    entries = sorted(stats._entries("media"), key=lambda e: e.index)
    if not entries:
        return {"ok": False, "reason": "No MEDIA databases are online"}

    try:
        result = await _scan_media_file_identity_duplicates(
            entries,
            remove=True,
        )
    except Exception as e:
        errors.record("dedupe:media:media_files", str(e))
        return {"ok": False, "reason": "MEDIA file deduplication failed"}

    cache.invalidate()
    audit.log(
        actor_id, "deduplicate_telegram_file_identities",
        target="media:all-online-shards",
        result=(
            f"duplicates={result['duplicates']} "
            f"deleted={result['deleted']}"
        ),
    )
    return {
        "ok": True,
        "duplicate_records": result["duplicates"],
        "deleted": result["deleted"],
        "per_collection": result["per_shard"],
    }


# ============================================================
# SECTION 27 — VIEW CLEAR
# ============================================================

async def view_clear(cat: str, index: int):
    info = await stats.db_info(cat, index)
    if not info:
        return (
            f"❌ {F.sc('db not found')}",
            InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"{F.EMO['back']} {F.sc('back')}",
                    callback_data="adm:dbc_main")]]),
        )

    lines = [
        _header(), "",
        f"☢️ <b>{F.fb('DANGER ZONE — CLEAR DATA')}</b>",
        F.DIV, "",
        f"🎯 {F.sc('target')} · {cat.upper()} DB {index:02d}",
        f"🏷️ {F.sc('cluster')} · <code>{esc(info['label'])}</code>",
        f"📦 {F.sc('documents')} · <code>{FM.num(info['objects'])}</code>",
        f"💾 {F.sc('storage')} · <code>{FM.size(info['storage_size'])}</code>",
        "",
        F.DIV,
        f"⚠️ <b>{F.sc('this will remove all documents in all collections.')}</b>",
        f"⚠️ <b>{F.sc('this cannot be undone.')}</b>",
        F.DIV,
        "",
        F.sc("multi-stage confirmation required."),
    ]

    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"🗑️ {F.sc('clear this database')}",
            callback_data=f"adm:dbc_clear_db:{cat}:{index}")],
        [
            InlineKeyboardButton(
                f"{F.EMO['back']} {F.sc('back')}",
                callback_data=f"adm:dbc_db:{cat}:{index}"),
            InlineKeyboardButton(
                f"{F.EMO['cross']} {F.sc('cancel')}",
                callback_data="adm:dbc_main"),
        ],
    ])
    return "\n".join(lines), kb


async def do_clear_db(cat: str, index: int):
    entry = stats._find_entry(cat, index)
    if not entry:
        return (
            f"❌ {F.sc('db not found')}",
            InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"{F.EMO['back']} {F.sc('back')}",
                    callback_data="adm:dbc_main")]]),
        )

    deleted = 0
    dropped = 0
    for name in await Diagnostics.list_collections(entry.db):
        try:
            r = await entry.db[name].delete_many({})
            deleted += r.deleted_count
        except Exception as e:
            errors.record(f"clear:{name}", str(e))
        try:
            await entry.db.drop_collection(name)
            dropped += 1
        except Exception:
            pass

    cache.invalidate()
    audit.log(0, "clear_database",
              target=f"{cat}:{index}",
              result=f"deleted={deleted} dropped={dropped}")

    lines = [
        _header(), "",
        f"🟢 <b>{F.fb('OPERATION COMPLETE')}</b>",
        F.DIV, "",
        f"🎯 {F.sc('target')} · {cat.upper()} DB {index:02d}",
        f"🗑️ {F.sc('documents removed')} · <code>{FM.num(deleted)}</code>",
        f"📦 {F.sc('collections dropped')} · <code>{FM.num(dropped)}</code>",
        f"⏱️ {F.sc('time')} · <code>{now_ist()}</code>",
        f"📊 {F.sc('statistics refreshed')} · 🟢 {F.sc('yes')}",
    ]
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            f"📊 {F.sc('view database')}",
            callback_data=f"adm:dbc_db:{cat}:{index}"),
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data="adm:dbc_main"),
    ]])
    return "\n".join(lines), kb


async def do_clear_coll(cat: str, index: int, name: str):
    """Clear ONE collection."""
    entry = stats._find_entry(cat, index)
    if not entry or not entry.online:
        return (
            f"❌ {F.sc('db offline or not found')}",
            InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"{F.EMO['back']} {F.sc('back')}",
                    callback_data=f"adm:dbc_coll:{cat}:{index}:{name}")]]),
        )

    deleted = 0
    try:
        r = await entry.db[name].delete_many({})
        deleted = r.deleted_count
    except Exception as e:
        errors.record(f"clear_coll:{name}", str(e))
    try:
        await entry.db.drop_collection(name)
    except Exception:
        pass

    cache.invalidate()
    audit.log(0, "clear_collection",
              target=f"{cat}:{index}:{name}",
              result=f"deleted={deleted}")

    lines = [
        _header(), "",
        f"🟢 <b>{F.fb('COLLECTION CLEARED')}</b>",
        F.DIV, "",
        f"📚 {F.sc('collection')} · <code>{esc(name)}</code>",
        f"🗄️ {F.sc('database')} · {cat.upper()} {index:02d}",
        f"🗑️ {F.sc('documents removed')} · <code>{FM.num(deleted)}</code>",
        f"⏱️ {F.sc('time')} · <code>{now_ist()}</code>",
    ]
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton(
            f"📊 {F.sc('view database')}",
            callback_data=f"adm:dbc_db:{cat}:{index}")],
        [InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data=f"adm:dbc_colls:{cat}:{index}:1")],
    ])
    return "\n".join(lines), kb


# ============================================================
# SECTION 28 — VIEW SEARCH
# ============================================================

async def view_search(cat: str, index: int,
                      name: Optional[str] = None,
                      query: Optional[str] = None):
    """Search inside a database (all collections or one)."""
    entry = stats._find_entry(cat, index)
    if not entry:
        return (
            f"❌ {F.sc('db not found')}",
            InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"{F.EMO['back']} {F.sc('back')}",
                    callback_data="adm:dbc_main")]]),
        )

    lines = [
        _header(), "",
        f"🔍 <b>{F.fb('SEARCH DATABASE')}</b>",
        F.DIV, "",
        f"🗄️ {F.sc('database')} · {cat.upper()} {index:02d}",
    ]
    if name:
        lines.append(f"📚 {F.sc('collection')} · <code>{esc(name)}</code>")
    else:
        lines.append(f"📚 {F.sc('collection')} · <i>{F.sc('all')}</i>")
    if query:
        lines.append(f"🔎 {F.sc('query')} · <code>{esc(query)}</code>")
    lines.append("")

    if query:
        regex = re.compile(re.escape(query), re.IGNORECASE)
        results: List[tuple] = []
        try:
            if name:
                colls = [name]
            else:
                colls = await Diagnostics.list_collections(entry.db)
            for c in colls[:20]:
                try:
                    docs = await entry.db[c].find(
                        {"$or": [
                            {"title": regex},
                            {"file_name": regex},
                            {"series_title": regex},
                            {"normalized_title": regex},
                        ]}
                    ).limit(5).to_list(length=5)
                    for d in docs:
                        results.append((c, d))
                except Exception:
                    continue
        except Exception as e:
            errors.record("search", str(e))

        lines.append(f"📊 {F.sc('results')} · <b>{len(results)}</b>")
        lines.append("")
        for c, d in results[:10]:
            lines.append(f"<b>{F.fb('MATCH')}</b> · <code>{esc(c)}</code>")
            lines.append(summarize_doc(d, maxf=6))
            lines.append("")
        if not results:
            lines.append(f"⚪ {F.sc('no matches found')}")
    else:
        lines.append(f"📌 {F.sc('send a search query as text')}")
        lines.append(f"📌 {F.sc('example')} · <code>inception</code>")

    back_cb = (
        f"adm:dbc_coll:{cat}:{index}:{name}"
        if name else f"adm:dbc_db:{cat}:{index}"
    )
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data=back_cb),
    ]])
    return "\n".join(lines), kb


# ============================================================
# SECTION 29 — VIEW ROUTER
# ============================================================

async def build_view(view: str, extra: Dict[str, Any]):
    try:
        if view == "main":
            return await view_main()
        if view == "category":
            return await view_category(extra["cat"])
        if view == "db":
            return await view_db(extra["cat"], extra["index"])
        if view == "colls":
            return await view_colls(
                extra["cat"], extra["index"], extra.get("page", 1))
        if view == "coll":
            return await view_coll(extra["cat"], extra["index"], extra["name"])
        if view == "recent":
            return await view_recent(
                extra["cat"], extra["index"], extra["name"],
                extra.get("limit", 5))
        if view == "indexes":
            return await view_indexes(
                extra["cat"], extra["index"], extra["name"])
        if view == "health":
            return await view_health(extra["cat"])
        if view == "perf":
            return await view_perf(extra["cat"])
        if view == "audit":
            return await view_audit()
        if view == "errors":
            return await view_errors()
        if view == "catall":
            return await view_cat_all(extra["cat"])
        return await view_main()
    except Exception as e:
        logger.exception(f"build_view({view}) failed")
        return (
            f"🔴 {F.sc('render failed')}: <code>{esc(e)}</code>",
            InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"{F.EMO['brand']} {F.sc('home')}",
                    callback_data="adm:dbc_main")]]),
        )


async def build_index():
    """Called by admin.py when the Databases button is tapped."""
    return await view_main()


# ============================================================
# SECTION 30 — CALLBACK ROUTER (priority -9520)
# ============================================================

@Client.on_callback_query(
    filters.regex(r"^adm:dbc_"), group=-9520,
)
async def db_router(client: Client, q: CallbackQuery):
    if not q.from_user or not _is_admin(q.from_user.id):
        return await q.answer("⛔", show_alert=True)

    data = str(q.data)
    parts = data.split(":")
    chat_id = q.message.chat.id if q.message else 0
    if q.message:
        from plugins.admin.admin import suspend_panel
        await suspend_panel(q.message.id)

    # Track current view for live refresh
    if parts[1] == "dbc_main":
        _live_view[chat_id] = {"view": "main", "extra": {}}
    elif parts[1] == "dbc_cat" and len(parts) > 2:
        _live_view[chat_id] = {
            "view": "category", "extra": {"cat": parts[2]}}
    elif parts[1] == "dbc_db" and len(parts) > 3:
        try:
            _live_view[chat_id] = {
                "view": "db",
                "extra": {"cat": parts[2], "index": int(parts[3])},
            }
        except ValueError:
            pass
    elif parts[1] == "dbc_catall" and len(parts) > 2:
        _live_view[chat_id] = {
            "view": "catall", "extra": {"cat": parts[2]}}
    elif parts[1] == "dbc_health" and len(parts) > 2:
        _live_view[chat_id] = {
            "view": "health", "extra": {"cat": parts[2]}}
    elif parts[1] == "dbc_perf" and len(parts) > 2:
        _live_view[chat_id] = {
            "view": "perf", "extra": {"cat": parts[2]}}

    try:
        # ─── MAIN ───
        if data == "adm:dbc_main":
            await live.stop(chat_id)
            text, _ = await build_view("main", {})
            kb = kb_main(chat_id)
            await _edit(q, text, kb)
            return await q.answer()

        # ─── REFRESH ───
        if data == "adm:dbc_refresh":
            cache.invalidate()
            text, _ = await build_view("main", {})
            kb = kb_main(chat_id)
            await _edit(q, text, kb)
            return await q.answer(f"{F.EMO['refresh']} {F.sc('refreshed')}")

        # ─── CLOSE ───
        if data == "adm:dbc_close":
            await live.stop(chat_id)
            try:
                await q.message.delete()
            except Exception:
                pass
            return await q.answer(F.sc("closed"))

        # ─── NOOP ───
        if data == "adm:dbc_noop":
            return await q.answer()

        # ─── LIVE TOGGLE ───
        if parts[1] == "dbc_live_toggle":
            if live.is_live(chat_id):
                await live.stop(chat_id)
                await q.answer(
                    f"🔴 {F.sc('live off')}", show_alert=True)
            else:
                iv = _live_intervals.get(chat_id, LIVE_DEFAULT)
                view = _live_view.get(
                    chat_id, {"view": "main", "extra": {}})
                await live.start(
                    client, chat_id, q.message.id,
                    view["view"], view["extra"])
                await q.answer(
                    f"🟢 {F.sc('live on')} · {iv}s", show_alert=True)
            cache.invalidate()
            cur = _live_view.get(
                chat_id, {"view": "main", "extra": {}})
            text, _ = await build_view(cur["view"], cur["extra"])
            kb = kb_main(chat_id) if cur["view"] == "main" else None
            if kb is None:
                # Rebuild view's own keyboard
                text, kb = await build_view(cur["view"], cur["extra"])
            await _edit(q, text, kb)
            return

        # ─── LIVE INTERVAL ───
        if parts[1] == "dbc_livego":
            interval = int(parts[2])
            _live_intervals[chat_id] = interval
            view = _live_view.get(
                chat_id, {"view": "main", "extra": {}})
            await live.start(
                client, chat_id, q.message.id,
                view["view"], view["extra"])
            await q.answer(
                f"🟢 {F.sc('live on')} · {interval}s", show_alert=True)
            cache.invalidate()
            text, _ = await build_view(view["view"], view["extra"])
            kb = kb_main(chat_id) if view["view"] == "main" else None
            if kb is None:
                text, kb = await build_view(view["view"], view["extra"])
            await _edit(q, text, kb)
            return

        # ─── LEGACY LIVE MENU (still supported) ───
        if parts[1] == "dbc_live":
            chat_id = q.message.chat.id
            if live.is_live(chat_id):
                await live.stop(chat_id)
                return await q.answer(
                    f"🔴 {F.sc('live monitor off')}", show_alert=True)
            rows = [
                [InlineKeyboardButton(
                    f"{n}s", callback_data=f"adm:dbc_livego:{n}")
                 for n in LIVE_OPTIONS],
                [InlineKeyboardButton(
                    f"{F.EMO['cross']} {F.sc('cancel')}",
                    callback_data="adm:dbc_main")],
            ]
            text = (
                f"🟢 <b>{F.fb('LIVE MONITOR')}</b>\n"
                f"{F.sc('choose refresh interval:')}"
            )
            await _edit(q, text, InlineKeyboardMarkup(rows))
            return await q.answer()

        # ─── CATEGORY ───
        if parts[1] == "dbc_cat":
            cat = parts[2]
            text, kb = await build_view("category", {"cat": cat})
            await _edit(q, text, kb)
            return await q.answer()

        # ─── CAT ALL ───
        if parts[1] == "dbc_catall":
            cat = parts[2]
            text, kb = await build_view("catall", {"cat": cat})
            await _edit(q, text, kb)
            return await q.answer()

        # ─── DB ───
        if parts[1] == "dbc_db":
            cat = parts[2]
            idx = int(parts[3])
            text, kb = await build_view("db", {"cat": cat, "index": idx})
            await _edit(q, text, kb)
            return await q.answer()

        # ─── COLLECTIONS ───
        if parts[1] == "dbc_colls":
            cat = parts[2]
            idx = int(parts[3])
            page = int(parts[4])
            text, kb = await build_view(
                "colls", {"cat": cat, "index": idx, "page": page})
            await _edit(q, text, kb)
            return await q.answer()

        # ─── ONE COLLECTION ───
        if parts[1] == "dbc_coll":
            cat = parts[2]
            idx = int(parts[3])
            name = ":".join(parts[4:])
            text, kb = await build_view(
                "coll", {"cat": cat, "index": idx, "name": name})
            await _edit(q, text, kb)
            return await q.answer()

        # ─── RECENT DOCS ───
        if parts[1] == "dbc_recent":
            cat = parts[2]
            idx = int(parts[3])
            limit = int(parts[-1])
            name = ":".join(parts[4:-1])
            text, kb = await build_view(
                "recent",
                {"cat": cat, "index": idx, "name": name, "limit": limit})
            await _edit(q, text, kb)
            return await q.answer()

        # ─── INDEXES ───
        if parts[1] == "dbc_idx":
            cat = parts[2]
            idx = int(parts[3])
            name = ":".join(parts[4:])
            text, kb = await build_view(
                "indexes", {"cat": cat, "index": idx, "name": name})
            await _edit(q, text, kb)
            return await q.answer()

        # ─── HEALTH ───
        if parts[1] == "dbc_health":
            cat = parts[2]
            text, kb = await build_view("health", {"cat": cat})
            await _edit(q, text, kb)
            return await q.answer()

        # ─── PERF ───
        if parts[1] == "dbc_perf":
            cat = parts[2]
            text, kb = await build_view("perf", {"cat": cat})
            await _edit(q, text, kb)
            return await q.answer()

        # ─── AUDIT ───
        if parts[1] == "dbc_audit":
            text, kb = await build_view("audit", {})
            await _edit(q, text, kb)
            return await q.answer()

        # ─── ERRORS ───
        if parts[1] == "dbc_errors":
            text, kb = await build_view("errors", {})
            await _edit(q, text, kb)
            return await q.answer()

        # ─── DUPLICATES ───
        if parts[1] == "dbc_dups":
            cat = parts[2]
            idx = int(parts[3])
            text, kb = await view_dups(cat, idx)
            await _edit(q, text, kb)
            return await q.answer()

        if parts[1] == "dbc_dup_scan":
            cat = parts[2]
            idx = int(parts[3])
            await q.answer(f"🔍 {F.sc('scanning...')}")
            text, kb = await view_dup_scan(cat, idx)
            await _edit(q, text, kb)
            return

        # ─── DUPLICATE SCAN (COLLECTION) ───
        if parts[1] == "dbc_dup_coll":
            cat = parts[2]
            idx = int(parts[3])
            name = ":".join(parts[4:])
            await q.answer(f"🔍 {F.sc('scanning...')}")
            text, kb = await do_dup_scan_coll(cat, idx, name)
            await _edit(q, text, kb)
            return

        if parts[1] == "dbc_dup_remove":
            cat = parts[2]
            idx = int(parts[3])
            if cat != "media":
                return await q.answer(
                    "File deduplication is available for MEDIA databases only.",
                    show_alert=True,
                )
            tok = f"dup:{cat}:{idx}:{int(time.time())}"
            confirms.start(q.from_user.id, tok, {
                "action": "dup_remove", "cat": cat, "index": idx,
            })
            text = (
                f"⚠️ <b>{F.fb('DUPLICATE REMOVAL — STEP 1/3')}</b>\n"
                f"{F.DIV}\n\n"
                f"🎯 {F.sc('target')} · all online MEDIA shards\n\n"
                f"{F.sc('duplicate records in media_files with a matching file_unique_id will be deleted across all online MEDIA shards; one record per unique file ID will be kept.')}\n\n"
                f"{F.sc('continue?')}"
            )
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    f"⚠️ {F.sc('continue')}",
                    callback_data=f"adm:dbc_confirm:{tok}")],
                [InlineKeyboardButton(
                    f"{F.EMO['cross']} {F.sc('cancel')}",
                    callback_data=f"adm:dbc_cancel:{tok}")],
            ])
            await _edit(q, text, kb)
            return await q.answer()

        # ─── CLEAR DB ───
        if parts[1] == "dbc_clear":
            cat = parts[2]
            idx = int(parts[3])
            text, kb = await view_clear(cat, idx)
            await _edit(q, text, kb)
            return await q.answer()

        if parts[1] == "dbc_clear_db":
            cat = parts[2]
            idx = int(parts[3])
            tok = f"clear:{cat}:{idx}:{int(time.time())}"
            confirms.start(q.from_user.id, tok, {
                "action": "clear_db", "cat": cat, "index": idx,
            })
            text = (
                f"⚠️ <b>{F.fb('STEP 1/3 — CLEAR DATABASE')}</b>\n"
                f"{F.DIV}\n\n"
                f"🎯 {cat.upper()} DB {idx:02d}\n\n"
                f"{F.sc('all documents will be removed.')}\n\n"
                f"{F.sc('continue?')}"
            )
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    f"⚠️ {F.sc('continue')}",
                    callback_data=f"adm:dbc_confirm:{tok}")],
                [InlineKeyboardButton(
                    f"{F.EMO['cross']} {F.sc('cancel')}",
                    callback_data=f"adm:dbc_cancel:{tok}")],
            ])
            await _edit(q, text, kb)
            return await q.answer()

        # ─── CLEAR COLLECTION ───
        if parts[1] == "dbc_clear_coll":
            cat = parts[2]
            idx = int(parts[3])
            name = ":".join(parts[4:])
            tok = f"clrcoll:{cat}:{idx}:{name}:{int(time.time())}"
            confirms.start(q.from_user.id, tok, {
                "action": "clear_coll",
                "cat": cat, "index": idx, "name": name,
            })
            text = (
                f"⚠️ <b>{F.fb('CLEAR COLLECTION — STEP 1/3')}</b>\n"
                f"{F.DIV}\n\n"
                f"📚 <code>{esc(name)}</code>\n"
                f"🗄️ {cat.upper()} DB {idx:02d}\n\n"
                f"{F.sc('all documents will be removed.')}\n\n"
                f"{F.sc('continue?')}"
            )
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    f"⚠️ {F.sc('continue')}",
                    callback_data=f"adm:dbc_confirm:{tok}")],
                [InlineKeyboardButton(
                    f"{F.EMO['cross']} {F.sc('cancel')}",
                    callback_data=f"adm:dbc_cancel:{tok}")],
            ])
            await _edit(q, text, kb)
            return await q.answer()

        # ─── CONFIRM ───
        if parts[1] == "dbc_confirm":
            tok = ":".join(parts[2:])
            entry = confirms.get(q.from_user.id, tok)
            if not entry:
                return await q.answer("⏱️ expired", show_alert=True)

            step = entry["step"]
            if step < 3:
                confirms.advance(q.from_user.id, tok)
                if step == 1:
                    text = (
                        f"🚨 <b>{F.fb('STEP 2/3 — FINAL WARNING')}</b>\n"
                        f"{F.DIV}\n\n"
                        f"{F.sc('this cannot be undone.')}\n\n"
                        f"{F.sc('continue?')}"
                    )
                    kb = InlineKeyboardMarkup([
                        [InlineKeyboardButton(
                            f"🚨 {F.sc('continue')}",
                            callback_data=f"adm:dbc_confirm:{tok}")],
                        [InlineKeyboardButton(
                            f"{F.EMO['cross']} {F.sc('cancel')}",
                            callback_data=f"adm:dbc_cancel:{tok}")],
                    ])
                else:
                    text = (
                        f"☢️ <b>{F.fb('STEP 3/3 — PERMANENT DELETION')}</b>\n"
                        f"{F.DIV}\n\n"
                        f"{F.sc('click below to execute.')}"
                    )
                    kb = InlineKeyboardMarkup([
                        [InlineKeyboardButton(
                            f"☢️ {F.sc('yes, permanently delete')}",
                            callback_data=f"adm:dbc_confirm:{tok}")],
                        [InlineKeyboardButton(
                            f"{F.EMO['cross']} {F.sc('cancel')}",
                            callback_data=f"adm:dbc_cancel:{tok}")],
                    ])
                await _edit(q, text, kb)
                return await q.answer()

            confirms.cancel(q.from_user.id, tok)
            payload = entry["payload"]
            action = payload.get("action")

            if action == "clear_db":
                text, kb = await do_clear_db(
                    payload["cat"], payload["index"])
                await _edit(q, text, kb)
                return await q.answer(f"{F.EMO['check']} {F.sc('done')}")

            if action == "clear_coll":
                text, kb = await do_clear_coll(
                    payload["cat"], payload["index"], payload["name"])
                await _edit(q, text, kb)
                return await q.answer(f"{F.EMO['check']} {F.sc('done')}")

            if action == "dup_remove":
                await q.answer("🧹 Deduplicating indexed files across MEDIA shards…")
                await _edit(
                    q,
                    f"🧹 <b>{F.fb('TELEGRAM FILE DEDUPLICATION IN PROGRESS')}</b>\n"
                    f"{F.DIV}\n\n"
                    f"{F.sc('checking media_files across all online MEDIA shards by file_unique_id; one record per unique file ID will be kept.')}",
                    None,
                )
                result = await remove_file_identity_duplicates(
                    payload["cat"], payload["index"], q.from_user.id,
                )
                if result.get("ok"):
                    text_lines = [
                        f"🧹 <b>{F.fb('TELEGRAM FILE DEDUPLICATION COMPLETE')}</b>",
                        F.DIV, "",
                        f"🎯 {F.sc('target')} · all online MEDIA shards",
                        f"🧩 {F.sc('duplicate file records')} · "
                        f"<b>{FM.num(result['duplicate_records'])}</b>",
                        f"🗑️ {F.sc('extra records removed')} · "
                        f"<b>{FM.num(result['deleted'])}</b>",
                        "",
                        f"✅ {F.sc('one record was retained per Telegram file_unique_id')}",
                    ]
                    for item in result["per_collection"][:20]:
                        text_lines.append(
                            f"• <code>{esc(item['name'])}</code> · "
                            f"{FM.num(item['deleted'])} {F.sc('removed')}"
                        )
                    text = "\n".join(text_lines)
                else:
                    text = (
                        f"❌ <b>{F.fb('TELEGRAM FILE DEDUPLICATION INCOMPLETE')}</b>\n"
                        f"{F.DIV}\n\n"
                        f"{F.sc('some indexed files could not be processed; see database errors in the admin panel.')}"
                    )
                kb = InlineKeyboardMarkup([[
                    InlineKeyboardButton(
                        f"{F.EMO['back']} {F.sc('back')}",
                        callback_data=f"adm:dbc_dups:{payload['cat']}:{payload['index']}")]])
                await _edit(q, text, kb)
                return

        # ─── CANCEL ───
        if parts[1] == "dbc_cancel":
            tok = ":".join(parts[2:])
            confirms.cancel(q.from_user.id, tok)
            text = f"{F.EMO['cross']} {F.sc('cancelled')}."
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton(
                    f"{F.EMO['brand']} {F.sc('home')}",
                    callback_data="adm:dbc_main")]])
            await _edit(q, text, kb)
            return await q.answer(F.sc("cancelled"))

        # ─── STATS (redirect to db view) ───
        if parts[1] == "dbc_stats":
            cat = parts[2]
            idx = int(parts[3])
            text, kb = await build_view("db", {"cat": cat, "index": idx})
            await _edit(q, text, kb)
            return await q.answer()

        # ─── SEARCH (DB) ───
        if parts[1] == "dbc_search":
            cat = parts[2]
            idx = int(parts[3])
            _search_pending[q.from_user.id] = {
                "cat": cat, "index": idx, "name": None,
            }
            text, kb = await view_search(cat, idx)
            await _edit(q, text, kb)
            return await q.answer()

        # ─── SEARCH (COLLECTION) ───
        if parts[1] == "dbc_search_coll":
            cat = parts[2]
            idx = int(parts[3])
            name = ":".join(parts[4:])
            _search_pending[q.from_user.id] = {
                "cat": cat, "index": idx, "name": name,
            }
            text, kb = await view_search(cat, idx, name)
            await _edit(q, text, kb)
            return await q.answer()

        return await q.answer(f"❓ {data[:40]}", show_alert=True)

    except Exception as e:
        logger.exception(f"[DB-CENTER] router: {e}")
        try:
            await q.answer(f"❌ {type(e).__name__}", show_alert=True)
        except Exception:
            pass


# ============================================================
# SECTION 31 — SAFE EDIT
# ============================================================

async def _edit(q: CallbackQuery, text: str, kb) -> None:
    try:
        await q.message.edit_text(
            text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        if "not modified" in str(e).lower():
            return
        logger.debug(f"[DB-CENTER] edit: {e}")


# ============================================================
# SECTION 32 — SEARCH TEXT INPUT
# ============================================================

@Client.on_message(
    filters.private & filters.text & ~filters.regex(r"^/"),
    group=-9510,
)
async def db_search_input(client: Client, message: Message):
    """Capture text when the admin is in search mode."""
    if not message.from_user or not _is_admin(message.from_user.id):
        return
    pending = _search_pending.pop(message.from_user.id, None)
    if not pending:
        return

    query = (message.text or "").strip()
    if not query or query == "-":
        try:
            message.stop_propagation()
        except Exception:
            pass
        return

    try:
        text, kb = await view_search(
            pending["cat"], pending["index"],
            pending.get("name"), query,
        )
        await message.reply_text(
            text, reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        logger.exception(f"[DB-CENTER] search input: {e}")

    try:
        message.stop_propagation()
    except Exception:
        pass


# ============================================================
# SECTION 33 — CLEANUP LOOP
# ============================================================

async def _confirm_cleanup():
    while True:
        try:
            confirms.cleanup()
        except Exception:
            pass
        await asyncio.sleep(60)


_cleanup_task: Optional[asyncio.Task] = None


def ensure_cleanup() -> None:
    global _cleanup_task
    if _cleanup_task and not _cleanup_task.done():
        return
    try:
        loop = asyncio.get_running_loop()
        _cleanup_task = loop.create_task(_confirm_cleanup())
    except RuntimeError:
        pass


# ============================================================
# SECTION 34 — SNAPSHOT
# ============================================================

def snapshot() -> Dict[str, Any]:
    return {
        "live_chats": len(live._tasks),
        "pending_confirms": len(confirms._p),
        "errors_logged": len(errors._q),
    }


# ============================================================
# SECTION 35 — PUBLIC EXPORTS
# ============================================================

__all__ = [
    "build_index",
    "build_view",
    "snapshot",
]
