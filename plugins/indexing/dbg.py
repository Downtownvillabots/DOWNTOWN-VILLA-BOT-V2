# ============================================================
# 🏨 DOWNTOWN VILLA — /dbg (indexing diagnostic)
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
    filters.command(["dbg", "dbgidx", "dbgindex"]) & filters.private,
    group=-8250,
)
async def cmd_dbg(client: Client, message: Message):
    if not message.from_user or not _is_admin(message.from_user.id):
        return

    lines: List[str] = ["🔧 <b>INDEXING DIAGNOSTIC</b>"]
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━")

    # ── 1. Registry
    try:
        from database import db_registry
        all_entries = db_registry.media_entries()
        online = [e for e in all_entries if e.online]
        lines.append(f"📦 media shards : <b>{len(all_entries)}</b>")
        lines.append(f"🟢 online       : <b>{len(online)}</b>")
        for e in all_entries:
            lines.append(
                f"   • DB{e.index} <code>{e.label}</code> "
                f"{'🟢' if e.online else '🔴'}"
            )
    except Exception as e:
        lines.append(f"❌ registry error: <code>{e}</code>")
        return await message.reply_text(
            "\n".join(lines), parse_mode=ParseMode.HTML,
        )

    # ── 2. Doc counts per shard
    lines.append("")
    lines.append("📊 <b>DOC COUNTS</b>")
    total_docs = 0
    for e in online:
        try:
            n = await e.db["media_files"].estimated_document_count()
            total_docs += n
            lines.append(f"   • DB{e.index}: <b>{n}</b> docs")
        except Exception as ex:
            lines.append(f"   • DB{e.index}: ❌ {ex}")
    lines.append(f"   🗄️ <b>total: {total_docs}</b> docs")

    # ── 3. Sample one doc
    lines.append("")
    lines.append("🔍 <b>SAMPLE DOC</b>")
    sample: Dict[str, Any] = {}
    for e in online:
        try:
            doc = await e.db["media_files"].find_one({})
            if doc:
                sample = doc
                lines.append(f"   shard = DB{e.index}")
                keys = list(doc.keys())[:15]
                lines.append(f"   keys = <code>{keys}</code>")
                lines.append(
                    f"   _id  = <code>{str(doc.get('_id'))[:40]}</code>"
                )
                lines.append(
                    f"   file_id = <code>{str(doc.get('file_id'))[:40]}</code>"
                )
                lines.append(
                    f"   file_unique_id = "
                    f"<code>{str(doc.get('file_unique_id'))[:40]}</code>"
                )
                break
        except Exception:
            continue

    if not sample:
        lines.append("   ⚪ no documents found in any shard")

    # ── 4. Fingerprint test
    lines.append("")
    lines.append("🧬 <b>FINGERPRINT TEST</b>")
    try:
        from services.duplicate import compute_fingerprint
        test_id = "BQACAgQAAxkBAAIC_test_fake_123"
        fp = compute_fingerprint(test_id)
        lines.append(f"   fp('fake') = <code>{fp}</code>")

        if sample.get("file_id"):
            real_fp = compute_fingerprint(str(sample["file_id"]))
            lines.append(
                f"   fp(sample.file_id) = <code>{real_fp}</code>"
            )
            lines.append(
                f"   sample._id == fp? "
                f"<b>{str(sample.get('_id')) == real_fp}</b>"
            )
    except Exception as e:
        lines.append(f"   ❌ {e}")

    # ── 5. Dedup test
    lines.append("")
    lines.append("♻️ <b>DEDUP TEST</b>")
    if sample.get("file_id"):
        try:
            from plugins.indexing.worker import _is_exact_duplicate
            result = await _is_exact_duplicate(str(sample["file_id"]))
            lines.append(
                f"   _is_exact_duplicate(sample) = "
                f"<b>{result}</b> (expect: True)"
            )
        except Exception as e:
            lines.append(f"   ❌ {e}")
    else:
        lines.append("   ⚪ no sample to test")

    # ── 6. Bloom stats
    lines.append("")
    lines.append("🌸 <b>BLOOM</b>")
    try:
        from services.duplicate import stats as bloom_stats
        st = bloom_stats()
        lines.append(f"   size    = <b>{st.get('size', 0)}</b>")
        lines.append(f"   hits    = <b>{st.get('hits', 0)}</b>")
        lines.append(f"   misses  = <b>{st.get('misses', 0)}</b>")
        lines.append(f"   added   = <b>{st.get('added', 0)}</b>")
    except Exception as e:
        lines.append(f"   ❌ {e}")

    # ── 7. Indexes on media_files
    lines.append("")
    lines.append("🧩 <b>INDEXES (shard 1)</b>")
    for e in online[:1]:
        try:
            idxs = []
            async for ix in e.db["media_files"].list_indexes():
                idxs.append(ix.get("name", "?"))
            lines.append(f"   <code>{idxs}</code>")
        except Exception as ex:
            lines.append(f"   ❌ {ex}")

    # ── 8. Worker status
    lines.append("")
    lines.append("🏗️ <b>WORKER</b>")
    try:
        from plugins.indexing import worker as WK
        w = WK.status()
        lines.append(f"   running   = <b>{w.get('running')}</b>")
        lines.append(f"   paused    = <b>{w.get('paused')}</b>")
        lines.append(f"   saved     = <b>{w.get('saved')}</b>")
        lines.append(f"   dup       = <b>{w.get('duplicate_id')}</b>")
        lines.append(f"   checked   = <b>{w.get('dups_checked')}</b>")
        lines.append(f"   processed = <b>{w.get('processed')}</b>")
        lines.append(f"   failed    = <b>{w.get('failed')}</b>")
        lines.append(f"   last_err  = "
                     f"<code>{str(w.get('last_error'))[:80]}</code>")
    except Exception as e:
        lines.append(f"   ❌ {e}")

    lines.append("")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("📌 send this output to admin")

    text = "\n".join(lines)[:4000]
    await message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )
