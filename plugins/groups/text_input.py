# ============================================================
# 🏨 DOWNTOWN VILLA — GROUPS TEXT INPUT
# ============================================================
#
# Captures plain text messages when an admin has an active
# session (opened by a button in the panel).
#
# Handles sessions:
#   cap_edit       → set caption template (or "-" to reset)
#   btn_add        → add result button (Name | URL)
#   w_edit         → set welcome message
#   flt_add        → add banned word
#   fs_add         → add fsub channel (id or @username)
#   v_url          → set shortener URL
#   v_time         → set verify time (seconds)
#   req_ch         → set request channel
#
# A session is created by router.py::_sess_new(uid, step, chat_id).
# Any private text from that user is routed here.
#
# Handler group: -8490 (runs AFTER commands at -8500)
# This ensures "/command" text is NOT captured (filters exclude '/').
#
# ============================================================

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from core import config
from plugins.groups import state as S
from plugins.groups import router as R
from utils import fonts as F

logger = logging.getLogger(__name__)


# ============================================================
# SECTION 1 — AUTH
# ============================================================

def _is_bot_admin(uid) -> bool:
    try:
        return int(uid) in [int(a) for a in config.ADMINS]
    except Exception:
        return False


async def _is_group_admin(
    client: Client, chat_id: int, user_id: int,
) -> bool:
    if _is_bot_admin(user_id):
        return True
    try:
        m = await client.get_chat_member(chat_id, user_id)
        st = getattr(m, "status", None)
        st = st.name.lower() if hasattr(st, "name") else str(st).lower()
        return st in ("administrator", "creator", "owner")
    except Exception:
        return False


# ============================================================
# SECTION 2 — URL NORMALIZER
# ============================================================

def _normalize_url(raw: str) -> Optional[str]:
    """Best-effort normalize user URL into a valid t.me / http URL."""
    if not raw:
        return None
    url = raw.strip()
    if not url:
        return None

    # @username
    if url.startswith("@"):
        return f"https://t.me/{url[1:]}"

    # t.me/xxx
    if url.startswith("t.me/"):
        return f"https://{url}"

    # already-valid
    if (url.startswith("http://")
            or url.startswith("https://")
            or url.startswith("tg://")):
        return url

    # looks like a domain
    if "." in url and " " not in url:
        return f"https://{url}"

    return None


# ============================================================
# SECTION 3 — MAIN HANDLER
# ============================================================

@Client.on_message(
    filters.private
    & filters.text
    & ~filters.regex(r"^/")
    & ~filters.regex(r"^ga:")
    & ~filters.regex(r"^glist:")
    & ~filters.regex(r"^adm:")
    & ~filters.regex(r"^pms:")
    & ~filters.regex(r"^pmsa:")
    & ~filters.regex(r"^idx:")
    & ~filters.regex(r"^dtvb:")
    & ~filters.regex(r"^bc:")
    & ~filters.regex(r"^sr:"),
    group=-8490,
)
async def groups_text_input(client: Client, message: Message):
    try:
        if not message.from_user:
            return

        uid = message.from_user.id
        session = R.get_session(uid)
        if not session:
            return

        step = session.get("step")
        chat_id = session.get("chat_id")
        text = (message.text or "").strip()

        if not step or not chat_id:
            R.drop_session(uid)
            return

        if not text:
            return

        # Verify admin still has rights
        if not await _is_group_admin(client, chat_id, uid):
            R.drop_session(uid)
            return await message.reply_text(
                f"{F.EMO['cross']} {F.sc('you are no longer admin there')}",
                parse_mode=ParseMode.HTML,
            )

        # ── DISPATCH ──
        if step == "cap_edit":
            await _handle_cap_edit(message, chat_id, text, uid)
        elif step == "btn_add":
            await _handle_btn_add(message, chat_id, text, uid)
        elif step == "w_edit":
            await _handle_w_edit(message, chat_id, text, uid)
        elif step == "flt_add":
            await _handle_flt_add(message, chat_id, text, uid)
        elif step == "fs_add":
            await _handle_fs_add(client, message, chat_id, text, uid)
        elif step == "v_url":
            await _handle_v_url(message, chat_id, text, uid)
        elif step == "v_time":
            await _handle_v_time(message, chat_id, text, uid)
        elif step == "req_ch":
            await _handle_req_ch(client, message, chat_id, text, uid)
        else:
            # Unknown step (e.g. "view" from admin_list.py).
            # Don't drop the session — the user may have typed
            # text by mistake. Let it expire naturally.
            logger.debug(
                f"[GROUPS-TEXT] ignoring step={step!r} for uid={uid}"
            )
            return

        # Block further handlers (avoid double replies)
        try:
            message.stop_propagation()
        except Exception:
            pass

    except Exception as e:
        logger.exception(f"[GROUPS-TEXT] handler: {e}")
        try:
            message.stop_propagation()
        except Exception:
            pass


# ============================================================
# SECTION 4 — STEP HANDLERS
# ============================================================

async def _handle_cap_edit(
    message: Message, chat_id: int, text: str, uid: int,
) -> None:
    R.drop_session(uid)

    if text == "-":
        await S.save_field(chat_id, "caption_template", None)
        return await message.reply_text(
            "\n".join([
                f"{F.EMO['check']} <b>{F.fb('CAPTION RESET')}</b>",
                F.DIV, "",
                f"📌 {F.sc('now using global caption')}",
            ]),
            parse_mode=ParseMode.HTML,
        )

    if len(text) < 3:
        return await message.reply_text(
            f"{F.EMO['cross']} {F.sc('caption too short')}",
            parse_mode=ParseMode.HTML,
        )

    ok = await S.save_field(chat_id, "caption_template", text)
    if not ok:
        return await message.reply_text(
            f"{F.EMO['cross']} {F.sc('save failed')}",
            parse_mode=ParseMode.HTML,
        )

    await message.reply_text(
        "\n".join([
            f"{F.EMO['check']} <b>{F.fb('CAPTION SAVED')}</b>",
            F.DIV, "",
            f"📝 <b>{F.sc('preview')}</b>",
            "",
            f"<code>{F.sc(text[:400])}</code>",
        ]),
        parse_mode=ParseMode.HTML,
    )


async def _handle_btn_add(
    message: Message, chat_id: int, text: str, uid: int,
) -> None:
    if "|" not in text:
        return await message.reply_text(
            "\n".join([
                f"{F.EMO['cross']} <b>{F.fb('INVALID FORMAT')}</b>",
                F.DIV, "",
                f"📌 {F.sc('send')} <code>Name | URL</code>",
                f"📌 {F.sc('example')}:",
                "<code>Join Channel | https://t.me/example</code>",
            ]),
            parse_mode=ParseMode.HTML,
        )

    name, url_raw = [p.strip() for p in text.split("|", 1)]
    if not name or not url_raw:
        return await message.reply_text(
            f"{F.EMO['cross']} {F.sc('empty name or url')}",
            parse_mode=ParseMode.HTML,
        )

    url = _normalize_url(url_raw)
    if not url:
        return await message.reply_text(
            f"{F.EMO['cross']} {F.sc('invalid URL')}",
            parse_mode=ParseMode.HTML,
        )

    cfg = await S.get_config(chat_id)
    btns = list(cfg.get("result_buttons") or [])
    if len(btns) >= 8:
        R.drop_session(uid)
        return await message.reply_text(
            f"⚠️ {F.sc('max 8 buttons')}",
            parse_mode=ParseMode.HTML,
        )

    btns.append({
        "name": name[:60],
        "url": url,
        "enabled": True,
        "position": len(btns) + 1,
    })
    await S.save_field(chat_id, "result_buttons", btns)
    R.drop_session(uid)

    await message.reply_text(
        "\n".join([
            f"{F.EMO['check']} <b>{F.fb('BUTTON ADDED')}</b>",
            F.DIV, "",
            f"📛 {F.sc(name)}",
            f"🔗 <code>{url[:60]}</code>",
            "",
            f"📊 {F.sc('total')} · <b>{len(btns)}</b>",
        ]),
        parse_mode=ParseMode.HTML,
    )


async def _handle_w_edit(
    message: Message, chat_id: int, text: str, uid: int,
) -> None:
    R.drop_session(uid)

    if len(text) < 3:
        return await message.reply_text(
            f"{F.EMO['cross']} {F.sc('welcome too short')}",
            parse_mode=ParseMode.HTML,
        )

    await S.save_field(chat_id, "welcome_text", text)
    await message.reply_text(
        "\n".join([
            f"{F.EMO['check']} <b>{F.fb('WELCOME SAVED')}</b>",
            F.DIV, "",
            f"📝 <b>{F.sc('preview')}</b>",
            "",
            f"<code>{F.sc(text[:400])}</code>",
        ]),
        parse_mode=ParseMode.HTML,
    )


async def _handle_flt_add(
    message: Message, chat_id: int, text: str, uid: int,
) -> None:
    word = text.lower().strip()
    if not word:
        return await message.reply_text(
            f"{F.EMO['cross']} {F.sc('empty')}",
            parse_mode=ParseMode.HTML,
        )

    cfg = await S.get_config(chat_id)
    words = list((cfg.get("filters") or {}).get("banned_words") or [])

    if word in words:
        R.drop_session(uid)
        return await message.reply_text(
            f"⚠️ {F.sc('already added')}",
            parse_mode=ParseMode.HTML,
        )

    words.append(word)
    await S.save_field(chat_id, "filters.banned_words", words)
    R.drop_session(uid)

    await message.reply_text(
        "\n".join([
            f"{F.EMO['check']} <b>{F.fb('WORD ADDED')}</b>",
            F.DIV, "",
            f"🔤 <code>{word}</code>",
            f"📊 {F.sc('total')} · <b>{len(words)}</b>",
        ]),
        parse_mode=ParseMode.HTML,
    )


async def _handle_fs_add(
    client: Client, message: Message, chat_id: int,
    text: str, uid: int,
) -> None:
    # Parse target
    target: Optional[int] = None

    if text.startswith("@"):
        try:
            ch = await client.get_chat(text)
            target = int(ch.id)
        except Exception as e:
            return await message.reply_text(
                "\n".join([
                    f"{F.EMO['cross']} <b>{F.fb('CANNOT RESOLVE')}</b>",
                    F.DIV, "",
                    f"<code>{str(e)[:120]}</code>",
                ]),
                parse_mode=ParseMode.HTML,
            )
    else:
        try:
            target = int(text)
        except ValueError:
            return await message.reply_text(
                f"{F.EMO['cross']} {F.sc('invalid id or username')}",
                parse_mode=ParseMode.HTML,
            )

    cfg = await S.get_config(chat_id)
    channels = list((cfg.get("fsub") or {}).get("channels") or [])

    if target in channels:
        R.drop_session(uid)
        return await message.reply_text(
            f"⚠️ {F.sc('already added')}",
            parse_mode=ParseMode.HTML,
        )

    channels.append(int(target))
    await S.save_field(chat_id, "fsub.channels", channels)
    R.drop_session(uid)

    await message.reply_text(
        "\n".join([
            f"{F.EMO['check']} <b>{F.fb('CHANNEL ADDED')}</b>",
            F.DIV, "",
            f"🆔 <code>{target}</code>",
            f"📊 {F.sc('total')} · <b>{len(channels)}</b>",
            "",
            f"📌 {F.sc('bot must be admin in that channel')}",
        ]),
        parse_mode=ParseMode.HTML,
    )


async def _handle_v_url(
    message: Message, chat_id: int, text: str, uid: int,
) -> None:
    R.drop_session(uid)

    if not text.startswith("http"):
        return await message.reply_text(
            f"{F.EMO['cross']} {F.sc('must start with http:// or https://')}",
            parse_mode=ParseMode.HTML,
        )

    await S.save_field(chat_id, "verify.shortener_url", text)
    await message.reply_text(
        "\n".join([
            f"{F.EMO['check']} <b>{F.fb('SHORTENER SET')}</b>",
            F.DIV, "",
            f"🔗 <code>{text[:80]}</code>",
        ]),
        parse_mode=ParseMode.HTML,
    )


async def _handle_v_time(
    message: Message, chat_id: int, text: str, uid: int,
) -> None:
    try:
        secs = int(text)
    except ValueError:
        return await message.reply_text(
            f"{F.EMO['cross']} {F.sc('send seconds as a number')}",
            parse_mode=ParseMode.HTML,
        )

    if secs < 60:
        return await message.reply_text(
            f"⚠️ {F.sc('minimum 60 seconds')}",
            parse_mode=ParseMode.HTML,
        )

    if secs > 86400:
        return await message.reply_text(
            f"⚠️ {F.sc('maximum 24 hours (86400s)')}",
            parse_mode=ParseMode.HTML,
        )

    await S.save_field(chat_id, "verify.verify_time", secs)
    R.drop_session(uid)

    mins = secs // 60
    await message.reply_text(
        "\n".join([
            f"{F.EMO['check']} <b>{F.fb('VERIFY TIME SET')}</b>",
            F.DIV, "",
            f"⏱️ <b>{secs}s</b> · (~{mins} min)",
        ]),
        parse_mode=ParseMode.HTML,
    )


async def _handle_req_ch(
    client: Client, message: Message, chat_id: int,
    text: str, uid: int,
) -> None:
    target: Optional[int] = None

    if text.startswith("@"):
        try:
            ch = await client.get_chat(text)
            target = int(ch.id)
        except Exception as e:
            return await message.reply_text(
                "\n".join([
                    f"{F.EMO['cross']} <b>{F.fb('CANNOT RESOLVE')}</b>",
                    F.DIV, "",
                    f"<code>{str(e)[:120]}</code>",
                ]),
                parse_mode=ParseMode.HTML,
            )
    else:
        try:
            target = int(text)
        except ValueError:
            return await message.reply_text(
                f"{F.EMO['cross']} {F.sc('invalid id or username')}",
                parse_mode=ParseMode.HTML,
            )

    await S.save_field(chat_id, "requests.channel", int(target))
    R.drop_session(uid)

    await message.reply_text(
        "\n".join([
            f"{F.EMO['check']} <b>{F.fb('REQUEST CHANNEL SET')}</b>",
            F.DIV, "",
            f"📢 <code>{target}</code>",
        ]),
        parse_mode=ParseMode.HTML,
    )


# ============================================================
# SECTION 5 — TIMEOUT CLEANUP (background)
# ============================================================

async def _cleanup_loop():
    """Drop expired sessions every 60s (defensive)."""
    import asyncio
    while True:
        try:
            await asyncio.sleep(60)
            now = time.time()
            for uid in list(R._sessions.keys()):
                s = R._sessions.get(uid)
                if s and now > s.get("expires", 0):
                    R._sessions.pop(uid, None)
        except asyncio.CancelledError:
            return
        except Exception:
            pass


_cleanup_task = None


def ensure_cleanup() -> None:
    """Start cleanup loop (idempotent). Call from startup.py."""
    global _cleanup_task
    if _cleanup_task and not _cleanup_task.done():
        return
    try:
        import asyncio
        loop = asyncio.get_running_loop()
        _cleanup_task = loop.create_task(_cleanup_loop())
        logger.info("[GROUPS-TEXT] cleanup loop started")
    except RuntimeError:
        pass


# ============================================================
# SECTION 6 — PUBLIC EXPORTS
# ============================================================

__all__ = [
    "groups_text_input",
    "ensure_cleanup",
]
