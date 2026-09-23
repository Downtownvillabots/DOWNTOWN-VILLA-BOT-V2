# ============================================================
# 🏨 DOWNTOWN VILLA — PM SEARCH DIAGNOSTIC
# ============================================================

from __future__ import annotations
import logging
from typing import Any, Dict, List

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import Message

from core import config

logger = logging.getLogger(__name__)


def _is_admin(uid) -> bool:
    try:
        return int(uid) in [int(a) for a in config.ADMINS]
    except Exception:
        return False


@Client.on_message(
    filters.command(["pmdbg", "pmsdbg"]) & filters.private,
    group=-8155,
)
async def cmd_pmdbg(client: Client, message: Message):
    if not message.from_user or not _is_admin(message.from_user.id):
        return

    status = await message.reply_text("🔧 running PM search diagnostic…")
    lines: List[str] = ["🔧 <b>PM SEARCH DIAGNOSTIC</b>", "━" * 22]

    # 1. Config
    try:
        from plugins.pm_search import state as CFG
        cfg = await CFG.get_cfg()
        lines.append("")
        lines.append("<b>1. CONFIG</b>")
        lines.append(f"enabled = <b>{cfg.get('enabled')}</b>")
        lines.append(f"suggestion_enabled = <b>{cfg.get('suggestion_enabled')}</b>")
        lines.append(f"request_enabled = <b>{cfg.get('request_enabled')}</b>")
    except Exception as e:
        lines.append(f"❌ config: <code>{e}</code>")

    # 2. Shards
    try:
        from database import db_registry
        entries = db_registry.media_entries()
        lines.append("")
        lines.append("<b>2. SHARDS</b>")
        for e in entries:
            try:
                n = await e.db["media_files"].estimated_document_count()
                lines.append(f"DB{e.index} <code>{e.label}</code> · {n} docs")
            except Exception as ex:
                lines.append(f"DB{e.index} ❌ {ex}")
    except Exception as e:
        lines.append(f"❌ shards: <code>{e}</code>")

    # 3. Sample doc fields
    try:
        from database import db_registry
        lines.append("")
        lines.append("<b>3. SAMPLE DOC</b>")
        for e in db_registry.media_entries():
            if not e.online:
                continue
            doc = await e.db["media_files"].find_one({})
            if not doc:
                continue
            keys = list(doc.keys())
            lines.append(f"keys = <code>{keys[:15]}</code>")
            lines.append(f"title = <code>{str(doc.get('title'))[:50]}</code>")
            lines.append(f"normalized_title = <code>{str(doc.get('normalized_title'))[:50]}</code>")
            lines.append(f"file_name = <code>{str(doc.get('file_name'))[:50]}</code>")
            lines.append(f"type = <code>{doc.get('type')}</code>")
            break
    except Exception as e:
        lines.append(f"❌ sample: <code>{e}</code>")

    # 4. Test query
    test_q = "karnan"
    try:
        lines.append("")
        lines.append(f"<b>4. TEST QUERY '{test_q}'</b>")

        from media_search.normalizer import parse_query
        norm, year, is_series = parse_query(test_q)
        lines.append(f"normalized = <code>{norm}</code>")
        lines.append(f"year = <code>{year}</code>")

        from media_search.engine import engine
        result = await engine.search_any(norm, year=year)
        lines.append(f"hits = <b>{len(result.hits)}</b>")
        lines.append(f"complete = <b>{result.complete}</b>")
        lines.append(f"shard_ok = {result.shard_ok} / failed = {result.shard_failed}")
        lines.append(f"elapsed = {result.elapsed_ms:.0f}ms")

        if result.hits:
            h = result.hits[0]
            lines.append("")
            lines.append("<b>first hit:</b>")
            lines.append(f"title = <code>{h.title}</code>")
            lines.append(f"file_name = <code>{str(h.file_name)[:50]}</code>")
            lines.append(f"quality = <code>{h.quality}</code>")
    except Exception as e:
        logger.exception("pmdbg engine")
        lines.append(f"❌ engine: <code>{type(e).__name__}: {e}</code>")

    # 5. Raw Mongo query — direct
    try:
        lines.append("")
        lines.append("<b>5. RAW MONGO TEST</b>")
        import re
        from database import db_registry
        pattern = "karnan"
        mq = {"$or": [
            {"title": {"$regex": pattern, "$options": "i"}},
            {"file_name": {"$regex": pattern, "$options": "i"}},
            {"normalized_title": {"$regex": pattern, "$options": "i"}},
        ]}
        for e in db_registry.media_entries():
            if not e.online:
                continue
            try:
                n = await e.db["media_files"].count_documents(mq)
                lines.append(f"DB{e.index} matches = <b>{n}</b>")
            except Exception as ex:
                lines.append(f"DB{e.index} ❌ {ex}")
    except Exception as e:
        lines.append(f"❌ raw: <code>{e}</code>")

    lines.append("")
    lines.append("━" * 22)

    try:
        await status.edit_text(
            "\n".join(lines)[:4000],
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception:
        pass
