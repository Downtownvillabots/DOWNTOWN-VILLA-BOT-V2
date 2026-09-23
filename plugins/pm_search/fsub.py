# ============================================================
# 🏨 DOWNTOWN VILLA — FORCE-SUB (robust)
# ============================================================

from __future__ import annotations
import logging
from typing import Any, Dict, List, Tuple, Union

from pyrogram import Client
from pyrogram.errors import (
    UserNotParticipant,
    ChatAdminRequired,
    PeerIdInvalid,
    UsernameInvalid,
    UsernameNotOccupied,
)
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from utils import fonts as F

logger = logging.getLogger(__name__)

_MEMBER_OK = {"member", "administrator", "creator", "owner"}


def _status_str(st: Any) -> str:
    """Normalize pyrogram status (enum / str / dotted path) to lowercase name."""
    if st is None:
        return ""
    if hasattr(st, "name"):
        return st.name.lower()
    s = str(st).lower()
    if "." in s:
        s = s.rsplit(".", 1)[-1]
    return s


def _parse_chat_id(ch: Any) -> Union[int, str, None]:
    """
    Return int for -100… IDs, str for @username, None if unparseable.
    """
    if ch is None:
        return None
    if isinstance(ch, int):
        return ch

    s = str(ch).strip()
    if not s:
        return None

    # @username
    if s.startswith("@"):
        return s

    # t.me/xxx → @xxx
    if "t.me/" in s:
        tail = s.rsplit("t.me/", 1)[-1].split("/")[0].split("?")[0]
        if tail.startswith("+"):
            return None  # private invite link, can't query
        return "@" + tail.lstrip("@")

    # numeric (-100… or plain)
    clean = s.lstrip("-")
    if clean.isdigit():
        try:
            return int(s)
        except (TypeError, ValueError):
            return None

    return None


async def _is_member(client: Client, chat_id: Any, user_id: int) -> bool:
    """
    Check membership. Fail-OPEN when bot can't verify
    (so legit joined users aren't blocked by bot-side issues).
    """
    try:
        m = await client.get_chat_member(chat_id, int(user_id))
        status = _status_str(getattr(m, "status", None))
        logger.info(
            f"[FSUB] user={user_id} chat={chat_id} → status={status!r}"
        )
        if status in _MEMBER_OK:
            return True
        if status == "restricted":
            return bool(getattr(m, "is_member", False))
        return False

    except UserNotParticipant:
        logger.info(f"[FSUB] user={user_id} chat={chat_id} → NOT PARTICIPANT")
        return False

    except ChatAdminRequired:
        logger.warning(
            f"[FSUB] BOT NOT ADMIN in chat={chat_id} → FAIL-OPEN (allow user). "
            f"Promote bot to admin to enforce."
        )
        return True

    except (PeerIdInvalid, UsernameInvalid, UsernameNotOccupied) as e:
        logger.warning(
            f"[FSUB] invalid chat={chat_id}: {type(e).__name__}: {e} → FAIL-OPEN"
        )
        return True

    except Exception as e:
        logger.warning(
            f"[FSUB] check {chat_id}/{user_id}: "
            f"{type(e).__name__}: {e} → FAIL-OPEN"
        )
        return True


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

    for raw in channels:
        cid = _parse_chat_id(raw)
        if cid is None:
            logger.warning(f"[FSUB] skipping invalid entry: {raw!r}")
            continue

        ok = await _is_member(client, cid, user_id)
        if ok:
            continue

        title = str(raw)
        invite: str | None = None
        try:
            chat = await client.get_chat(cid)
            title = getattr(chat, "title", None) or title
            username = getattr(chat, "username", None)
            if username:
                invite = f"https://t.me/{username}"
            else:
                try:
                    obj = await client.create_chat_invite_link(cid)
                    invite = obj.invite_link
                except ChatAdminRequired:
                    logger.warning(
                        f"[FSUB] can't create invite for {cid} (bot not admin)"
                    )
                except Exception as e:
                    logger.debug(f"[FSUB] create link {cid}: {e}")
        except Exception as e:
            logger.debug(f"[FSUB] get_chat {cid}: {e}")

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
