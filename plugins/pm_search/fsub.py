# ============================================================
# 🏨 DOWNTOWN VILLA — FORCE-SUB
# ============================================================

from __future__ import annotations
import logging
from typing import Any, Dict, List, Tuple

from pyrogram import Client
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from utils import fonts as F

logger = logging.getLogger(__name__)

_MEMBER_OK = ("member", "administrator", "creator", "owner", "restricted")


async def _is_member(client: Client, chat_id: int, user_id: int) -> bool:
    try:
        m = await client.get_chat_member(int(chat_id), int(user_id))
        st = getattr(m, "status", None)
        st_str = (
            st.name.lower() if hasattr(st, "name") else str(st).lower()
        )
        return st_str in _MEMBER_OK
    except Exception as e:
        logger.debug(f"[FSUB] check {chat_id}: {e}")
        return False


async def check_fsub(
    client: Client,
    user_id: int,
    cfg: Dict[str, Any],
) -> Tuple[bool, List[Dict[str, Any]]]:
    if not cfg.get("fsub_enabled"):
        return True, []

    channels = cfg.get("fsub_channels") or []
    if not channels:
        return True, []

    missing: List[Dict[str, Any]] = []

    for ch in channels:
        try:
            cid = int(ch)
        except (TypeError, ValueError):
            continue

        ok = await _is_member(client, cid, user_id)
        if ok:
            continue

        title = str(cid)
        invite = None
        try:
            chat = await client.get_chat(cid)
            title = chat.title or title
            if chat.username:
                invite = f"https://t.me/{chat.username}"
            else:
                try:
                    obj = await client.create_chat_invite_link(cid)
                    invite = obj.invite_link
                except Exception:
                    invite = None
        except Exception as e:
            logger.debug(f"[FSUB] chat {cid}: {e}")

        missing.append({
            "chat_id": cid,
            "title": title,
            "invite_link": invite,
        })

    return (len(missing) == 0), missing


def build_fsub_panel(
    cfg: Dict[str, Any],
    sid: str,
    idx: int,
    missing: List[Dict[str, Any]],
) -> Tuple[str, InlineKeyboardMarkup]:
    title = str(cfg.get("fsub_title") or "🔒 JOIN REQUIRED")
    msg = str(cfg.get("fsub_message") or "")
    join_label = str(cfg.get("fsub_join_label") or "🔔 JOIN")
    try_label = str(cfg.get("fsub_try_label") or "🔄 TRY AGAIN")

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"<b>{F.fb(title)}</b>",
        F.DIV, "",
        msg,
        "",
        F.DIV,
    ]

    rows: List[List[InlineKeyboardButton]] = []
    for m in missing:
        name = str(m.get("title") or "channel")[:40]
        url = m.get("invite_link")
        if url:
            rows.append([InlineKeyboardButton(
                f"{join_label} · {name}", url=url,
            )])
        else:
            rows.append([InlineKeyboardButton(
                f"{join_label} · {name}",
                callback_data=f"pms:noop:{sid}",
            )])

    rows.append([InlineKeyboardButton(
        try_label,
        callback_data=f"pms:try:{sid}:{idx}",
    )])

    return "\n".join(lines)[:4000], InlineKeyboardMarkup(rows)


__all__ = ["check_fsub", "build_fsub_panel"]
