# ============================================================
# 🏨 DOWNTOWN VILLA — BACKFILL normalized_title for old docs
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
    filters.command(["pmbackfill", "pmfix"]) & filters.private,
    group=-8152,
)
async def cmd_backfill(client: Client, message: Message):
    if not message.from_user or not _is_admin(message.from_user.id):
        return

    status = await message.reply_text(
        "🧬 backfilling normalized fields…\n"
        "this may take 1-2 minutes"
    )

    try:
        from media_search.normalizer import normalize
    except Exception:
        return await status.edit_text("❌ normalizer missing")

    from database import db_registry

    total = 0
    updated = 0
    per: List[str] = []

    for e in db_registry.media_entries():
        if not e.online:
            continue
        shard_n = 0
        try:
            coll = e.db["media_files"]
            cursor = coll.find({}, {
                "_id": 1,
                "title": 1,
                "type": 1,
                "file_name": 1,
                "season": 1,
                "episode": 1,
                "normalized_title": 1,
            })
            async for doc in cursor:
                total += 1
                tid = doc.get("_id")
                title = doc.get("title") or ""

                # Fallback title from file_name if missing
                if not title:
                    fn = doc.get("file_name") or ""
                    if fn:
                        import re
                        t = re.sub(r"\.[a-z0-9]{2,5}$", "", fn, flags=re.IGNORECASE)
                        t = re.sub(r"[._\-]+", " ", t)
                        t = t.split("[")[0].split("{")[0].split("(")[0]
                        t = re.sub(r"\s+", " ", t).strip(" -_")
                        title = t[:200]

                if not title:
                    continue

                n = normalize(title)

                patch: Dict[str, Any] = {"normalized_title": n}

                # Fix type
                rtype = doc.get("type") or ""
                if rtype not in ("movie", "series"):
                    if doc.get("season") is not None or doc.get("episode") is not None:
                        rtype = "series"
                    else:
                        rtype = "movie"
                    patch["type"] = rtype

                if rtype == "series":
                    patch["series_title"] = doc.get("title") or title
                    patch["normalized_series_title"] = n

                try:
                    await coll.update_one({"_id": tid}, {"$set": patch})
                    shard_n += 1
                except Exception:
                    continue

            per.append(f"• DB{e.index} <code>{e.label}</code> · <b>{shard_n}</b>")
            updated += shard_n
        except Exception as ex:
            per.append(f"❌ DB{e.index}: <code>{ex}</code>")

    lines = [
        "🧬 <b>BACKFILL COMPLETE</b>",
        "━" * 22,
        f"📄 scanned · <b>{total}</b>",
        f"✅ updated · <b>{updated}</b>",
        "",
    ] + per
    await status.edit_text(
        "\n".join(lines)[:4000],
        parse_mode=ParseMode.HTML,
    )
