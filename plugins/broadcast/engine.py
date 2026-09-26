# ============================================================
# 🏨 DOWNTOWN VILLA — BROADCAST ENGINE
# ============================================================
#
# Executes a broadcast run:
#   • Copy source message to every target
#   • Handle FloodWait
#   • Skip blocked/deleted users
#   • Track counters live
#   • Auto-delete for channels + groups + users
#   • Cancel support
#
# ============================================================

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, Callable, Dict, List, Optional

from pyrogram import Client
from pyrogram.errors import (
    FloodWait, RPCError, UserIsBlocked, InputUserDeactivated,
    ChatWriteForbidden, ChatAdminRequired, ChannelPrivate,
    UserNotParticipant, PeerIdInvalid, MessageIdInvalid, ChatForbidden,
    UserDeactivated, UserDeactivatedBan,
)

logger = logging.getLogger(__name__)


STATE: Dict[str, Any] = {
    "running": False,
    "cancel_requested": False,
    "job_id": None,
    "kind": "?",
    "total": 0,
    "sent": 0,
    "failed": 0,
    "blocked": 0,
    "deleted": 0,
    "started_at": None,
    "speed": 0.0,
    "eta_text": "—",
    "last_error": None,
}

_task: Optional[asyncio.Task] = None


# ============================================================
# PUBLIC API
# ============================================================

def is_running() -> bool:
    return STATE["running"]


def status() -> Dict[str, Any]:
    return dict(STATE)


def cancel() -> bool:
    if not STATE["running"]:
        return False
    STATE["cancel_requested"] = True
    return True


async def run_broadcast(
    client: Client,
    source_chat_id: int,
    source_msg_id: int,
    targets: List[int],
    kind: str,
    caption_template: Optional[str] = None,
    buttons_list: Optional[List[Dict[str, Any]]] = None,
    autodelete_seconds: int = 0,
    owner: int = 0,
    batch_size: int = 30,
    delay: float = 0.05,
    progress_cb: Optional[Callable[[Dict[str, Any]], Any]] = None,
) -> Dict[str, Any]:
    """Run a broadcast and return the final stats."""
    global _task

    if STATE["running"]:
        return {"ok": False, "reason": "already running"}

    STATE.update({
        "running": True,
        "cancel_requested": False,
        "kind": kind,
        "total": len(targets),
        "sent": 0, "failed": 0, "blocked": 0, "deleted": 0,
        "started_at": time.time(),
        "speed": 0.0,
        "eta_text": "—",
        "last_error": None,
    })

    from plugins.broadcast import state as BS

    job_id = await BS.create_run(
        owner=owner,
        target_kind=kind,
        target_count=len(targets),
        source_msg_id=source_msg_id,
        source_chat_id=source_chat_id,
        autodelete_seconds=autodelete_seconds,
    )
    STATE["job_id"] = job_id

    try:
        try:
            source_msg = await client.get_messages(
                source_chat_id, source_msg_id
            )
        except Exception as e:
            STATE["last_error"] = f"source fetch: {e}"
            return {"ok": False, "reason": str(e)}

        if not source_msg or source_msg.empty:
            STATE["last_error"] = "source message gone"
            return {"ok": False, "reason": "source gone"}

        from plugins.broadcast import templates as T
        cap_tpl = caption_template or await T.get_caption()
        btns = buttons_list if buttons_list is not None else await T.get_buttons()

        caption = T.build_caption(source_msg, cap_tpl)
        kb = T.build_buttons_kb(btns)

        start = time.time()
        sem = asyncio.Semaphore(5)
        lock = asyncio.Lock()

        async def _send(tid: int) -> str:
            if STATE["cancel_requested"]:
                return "cancelled"

            async with sem:
                if STATE["cancel_requested"]:
                    return "cancelled"
                try:
                    sent = await client.copy_message(
                        chat_id=tid,
                        from_chat_id=source_chat_id,
                        message_id=source_msg_id,
                        caption=caption,
                        reply_markup=kb,
                    )

                    # Auto-delete — works for ALL kinds
                    if autodelete_seconds > 0 and sent:
                        try:
                            await BS.schedule_autodelete(
                                tid, sent.id,
                                autodelete_seconds, job_id or "",
                            )
                        except Exception:
                            pass

                    await asyncio.sleep(delay)
                    return "sent"

                except FloodWait as e:
                    await asyncio.sleep(e.value + 2)
                    try:
                        sent = await client.copy_message(
                            chat_id=tid,
                            from_chat_id=source_chat_id,
                            message_id=source_msg_id,
                            caption=caption,
                            reply_markup=kb,
                        )
                        if autodelete_seconds > 0 and sent:
                            try:
                                await BS.schedule_autodelete(
                                    tid, sent.id,
                                    autodelete_seconds, job_id or "",
                                )
                            except Exception:
                                pass
                        return "sent"
                    except Exception:
                        return "failed"

                except (UserIsBlocked, UserDeactivated,
                        UserDeactivatedBan, InputUserDeactivated):
                    return "blocked"
                except (ChatWriteForbidden, ChatForbidden,
                        ChatAdminRequired, ChannelPrivate,
                        UserNotParticipant, PeerIdInvalid,
                        MessageIdInvalid, RPCError):
                    return "failed"
                except Exception as e:
                    STATE["last_error"] = str(e)[:200]
                    return "failed"

        async def _worker(tid: int):
            result = await _send(tid)
            async with lock:
                if result == "sent":
                    STATE["sent"] += 1
                elif result == "blocked":
                    STATE["blocked"] += 1
                elif result == "failed":
                    STATE["failed"] += 1

                if result == "blocked" and kind == "users":
                    asyncio.create_task(_remove_blocked_user(tid))

                if job_id:
                    await BS.increment_run(job_id, **{result: 1})

                done = STATE["sent"] + STATE["failed"] + STATE["blocked"]
                elapsed = max(0.001, time.time() - start)
                STATE["speed"] = done / elapsed
                if STATE["speed"] > 0:
                    remaining = STATE["total"] - done
                    eta = remaining / STATE["speed"]
                    from utils import format as FM
                    STATE["eta_text"] = FM.duration_short(eta)

        for i in range(0, len(targets), batch_size):
            if STATE["cancel_requested"]:
                break
            batch = targets[i:i + batch_size]
            await asyncio.gather(*[_worker(t) for t in batch])

            if progress_cb:
                try:
                    r = progress_cb(status())
                    if asyncio.iscoroutine(r):
                        await r
                except Exception:
                    pass

        final_status = (
            "cancelled" if STATE["cancel_requested"] else "completed"
        )
        if job_id:
            await BS.finish_run(job_id, final_status)

        return {
            "ok": True,
            "job_id": job_id,
            "sent": STATE["sent"],
            "failed": STATE["failed"],
            "blocked": STATE["blocked"],
            "total": STATE["total"],
            "status": final_status,
            "elapsed": time.time() - start,
        }
    finally:
        STATE["running"] = False


# ============================================================
# HELPERS
# ============================================================

async def _remove_blocked_user(uid: int) -> None:
    try:
        from database import db_registry
        db = db_registry.get_user_db()
        if db is None:
            return
        await db["users"].update_one(
            {"user_id": int(uid)},
            {"$set": {"blocked_bot": True}},
        )
    except Exception:
        pass


# ============================================================
# AUTO-DELETE LOOP
# ============================================================

_autodel_task: Optional[asyncio.Task] = None


def ensure_autodelete_loop(client: Client) -> None:
    global _autodel_task
    if _autodel_task and not _autodel_task.done():
        return
    try:
        loop = asyncio.get_running_loop()
        _autodel_task = loop.create_task(_autodelete_loop(client))
    except RuntimeError:
        pass


async def _autodelete_loop(client: Client) -> None:
    while True:
        try:
            await asyncio.sleep(60)
            from plugins.broadcast import state as BS
            due = await BS.due_autodeletes(limit=200)
            for doc in due:
                cid = doc.get("chat_id")
                mid = doc.get("message_id")
                if not cid or not mid:
                    await BS.remove_autodelete(doc.get("_id"))
                    continue
                try:
                    await client.delete_messages(int(cid), int(mid))
                except Exception:
                    pass
                await BS.remove_autodelete(doc.get("_id"))
        except asyncio.CancelledError:
            return
        except Exception:
            pass


__all__ = [
    "run_broadcast", "cancel", "is_running", "status",
    "ensure_autodelete_loop",
]
