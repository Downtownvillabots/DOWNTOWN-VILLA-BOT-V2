# ============================================================
# 🏨 DOWNTOWN VILLA — STEP: FILE DELIVERY
# ============================================================
#
# Final step — sends the file(s) with:
#   • Per-group custom caption template
#   • Per-group custom buttons (from groups collection)
#   • Auto-delete (per-group timer)
#   • Warning message before delete
#   • Batch mode for multi-episode delivery
#
# Fully customizable from /flow and /settings.
#
# Data output:
#   {
#     "delivered":    bool,
#     "sent_count":   int,
#     "failed_count": int,
#     "sent_msg_ids": list[int],
#   }
#
# ============================================================

from __future__ import annotations

import asyncio
import logging
import time
from typing import Any, List, Optional

from pyrogram.enums import ParseMode
from pyrogram.errors import FloodWait, UserIsBlocked
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
)

from core.flow_engine import (
    BaseStep, RenderResult, StepContext, StepResult, register_step,
    cancel_button,
)
from utils import fonts as F
from utils import format as FM

logger = logging.getLogger(__name__)


@register_step
class FileDeliveryStep(BaseStep):

    type_name = "file_delivery"
    display_name = "File Delivery"
    icon = "📤"
    help_text = "Sends file(s) with custom caption + buttons"
    default_enabled = True
    default_order = 100
    mandatory = True

    # ────────── RENDER ──────────

    async def render(self, ctx: StepContext) -> RenderResult:
        hits = ctx.data.get("hits") or []
        if not hits:
            # Nothing to deliver — send a "not found" card
            text = self._not_found_text(ctx)
            kb = self._not_found_kb(ctx)
            return RenderResult(text=text, keyboard=kb)

        # Group-level custom config
        group_cfg = await self._load_group_cfg(ctx)
        caption_tpl = group_cfg.get("caption_template")
        custom_buttons = group_cfg.get("result_buttons") or []
        auto_delete_min = int(group_cfg.get("delete_time") or 0)

        bot_username = self._bot_username(ctx)

        # Send the files
        sent_ids = await self._send_all(
            ctx, hits, caption_tpl, custom_buttons, bot_username
        )
        ctx.data["delivered"] = bool(sent_ids)
        ctx.data["sent_count"] = len(sent_ids)
        ctx.data["failed_count"] = max(0, len(hits) - len(sent_ids))
        ctx.data["sent_msg_ids"] = sent_ids

        # Auto-delete with warning
        if auto_delete_min > 0 and sent_ids:
            await self._schedule_auto_delete(ctx, sent_ids, auto_delete_min)

        # Send a short "done" card
        await self._send_summary(ctx, len(sent_ids), len(hits))

        # Flow is done
        return RenderResult(auto_skip=True)

    # ────────── INPUT ──────────

    async def on_input(self, ctx: StepContext, value: Any) -> StepResult:
        if isinstance(value, CallbackQuery):
            data = str(value.data or "")
            if data.startswith("cancel:flow:"):
                return StepResult(action="cancel")
        return StepResult(action="done")

    # ────────── SEND ENGINE ──────────

    async def _send_all(
        self,
        ctx: StepContext,
        hits: list,
        caption_tpl: Optional[str],
        custom_buttons: list,
        bot_username: str,
    ) -> List[int]:
        """Send each hit — respects FloodWait, handles errors."""
        client = ctx.client
        if client is None:
            return []

        target = ctx.user_id
        sent_ids: List[int] = []

        kb = self._build_buttons(custom_buttons, bot_username)

        for i, hit in enumerate(hits):
            file_id = getattr(hit, "file_id", None)
            if not file_id:
                continue

            caption = self._build_caption(ctx, hit, caption_tpl, bot_username)

            try:
                sent = await client.send_cached_media(
                    chat_id=target,
                    file_id=file_id,
                    caption=caption,
                    reply_markup=kb,
                    parse_mode=ParseMode.HTML,
                )
                if sent and sent.id:
                    sent_ids.append(sent.id)
                await asyncio.sleep(0.5)
            except FloodWait as e:
                await asyncio.sleep(e.value + 2)
                try:
                    sent = await client.send_cached_media(
                        chat_id=target,
                        file_id=file_id,
                        caption=caption,
                        reply_markup=kb,
                        parse_mode=ParseMode.HTML,
                    )
                    if sent and sent.id:
                        sent_ids.append(sent.id)
                except UserIsBlocked:
                    logger.info(f"[DELIVERY] user {target} blocked bot")
                    from services.users import mark_user_blocked
                    await mark_user_blocked(target)
                    break
                except Exception as e2:
                    logger.debug(f"[DELIVERY] retry failed: {e2}")
            except UserIsBlocked:
                logger.info(f"[DELIVERY] user {target} blocked bot")
                from services.users import mark_user_blocked
                await mark_user_blocked(target)
                break
            except Exception as e:
                logger.debug(f"[DELIVERY] file {i}: {e}")

        return sent_ids

    # ────────── CAPTION ──────────

    def _build_caption(
        self,
        ctx: StepContext,
        hit: Any,
        template: Optional[str],
        bot_username: str,
    ) -> str:
        """Build caption from template, fallback to default."""
        if template:
            try:
                return template.format(
                    title=getattr(hit, "title", "") or "—",
                    series_title=getattr(hit, "series_title", "") or "",
                    year=getattr(hit, "year", "") or "",
                    quality=(getattr(hit, "quality", "") or "").upper(),
                    codec=(getattr(hit, "codec", "") or "").upper(),
                    audio=", ".join(getattr(hit, "audio_languages", []) or []) or "—",
                    subtitle=", ".join(getattr(hit, "subtitle_languages", []) or []) or "—",
                    size=FM.size(getattr(hit, "file_size", 0)),
                    season=getattr(hit, "season", "") or "",
                    episode=getattr(hit, "episode", "") or "",
                    bot_username=bot_username,
                    bot_link=f"https://t.me/{bot_username}" if bot_username else "",
                    group_link="",
                    channel_link="",
                )
            except Exception as e:
                logger.debug(f"[DELIVERY] caption render: {e}")

        # Default caption
        title = getattr(hit, "title", "") or getattr(hit, "series_title", "") or "?"
        year = getattr(hit, "year", "")
        quality = (getattr(hit, "quality", "") or "").upper()
        codec = (getattr(hit, "codec", "") or "").upper()
        audio = ", ".join(getattr(hit, "audio_languages", []) or []) or "—"
        subtitle = ", ".join(getattr(hit, "subtitle_languages", []) or []) or "—"
        size = FM.size(getattr(hit, "file_size", 0))

        lines = [f"🎬 <b>{title}</b>"]
        if year:
            lines.append(f"📅 {year}")
        lines.append("")
        if quality:
            lines.append(f"🎞️ {F.sc('quality')}: <code>{quality}</code>")
        if codec:
            lines.append(f"🧬 {F.sc('codec')}: <code>{codec}</code>")
        lines.append(f"🔊 {F.sc('audio')}: <code>{audio}</code>")
        lines.append(f"📝 {F.sc('subtitle')}: <code>{subtitle}</code>")
        lines.append(f"💾 {F.sc('size')}: <code>{size}</code>")
        lines.append("")
        lines.append(f"⚡ <b>{F.fb('DOWNTOWN VILLA')}</b>")
        return "\n".join(lines)

    # ────────── BUTTONS ──────────

    def _build_buttons(
        self,
        custom: list,
        bot_username: str,
    ) -> Optional[InlineKeyboardMarkup]:
        rows: List[List[InlineKeyboardButton]] = []

        # Custom buttons from group settings
        per_row = 2
        row: List[InlineKeyboardButton] = []
        for b in (custom or []):
            if not isinstance(b, dict):
                continue
            name = (b.get("name") or "").strip()
            url = (b.get("url") or "").strip()
            if not name or not url:
                continue
            if url.startswith("@"):
                url = f"https://t.me/{url[1:]}"
            elif not (url.startswith("http://") or url.startswith("https://")
                      or url.startswith("tg://")):
                if "." in url and " " not in url:
                    url = f"https://{url}"
                else:
                    continue

            row.append(InlineKeyboardButton(name[:60], url=url))
            if len(row) == per_row:
                rows.append(row)
                row = []
        if row:
            rows.append(row)

        # Default share row
        if bot_username:
            share_url = (
                f"https://t.me/share/url?"
                f"url=https://t.me/{bot_username}&"
                f"text=Check%20this"
            )
            rows.append([
                InlineKeyboardButton("📤 SHARE", url=share_url),
            ])

        return InlineKeyboardMarkup(rows) if rows else None

    # ────────── AUTO-DELETE ──────────

    async def _schedule_auto_delete(
        self,
        ctx: StepContext,
        sent_ids: List[int],
        minutes: int,
    ) -> None:
        client = ctx.client
        target = ctx.user_id
        if client is None:
            return

        # Send warning
        warn_id = None
        try:
            warn = await client.send_message(
                chat_id=target,
                text=(
                    f"⚠️ {F.sc('this will delete in')} "
                    f"<b>{minutes} {F.sc('minutes')}</b>\n"
                    f"📌 {F.sc('save or forward now')}"
                ),
                parse_mode=ParseMode.HTML,
            )
            if warn:
                warn_id = warn.id
        except Exception:
            pass

        # Schedule
        all_ids = list(sent_ids)
        if warn_id:
            all_ids.append(warn_id)

        asyncio.create_task(
            self._delete_after(client, target, all_ids, minutes * 60)
        )

    async def _delete_after(self, client, chat_id, ids, seconds):
        try:
            await asyncio.sleep(seconds)
            for mid in ids:
                try:
                    await client.delete_messages(chat_id, mid)
                except Exception:
                    pass
        except asyncio.CancelledError:
            return
        except Exception:
            pass

    # ────────── GROUP CONFIG LOADER ──────────

    async def _load_group_cfg(self, ctx: StepContext) -> dict:
        """Load per-group settings, or return empty for PM."""
        if not ctx.is_group:
            return {}
        try:
            from database import db_registry
            db = db_registry.get_user_db()
            if db is None:
                return {}
            doc = await db["groups"].find_one({"chat_id": ctx.chat_id}) or {}
            merged = dict(doc)
            sub = doc.get("settings") or {}
            merged.update(sub)
            return merged
        except Exception as e:
            logger.debug(f"[DELIVERY] load cfg: {e}")
            return {}

    def _bot_username(self, ctx: StepContext) -> str:
        try:
            c = ctx.client
            if c is None:
                return ""
            u = getattr(c, "bot_username", None)
            if callable(u):
                return u()
            return u or ""
        except Exception:
            return ""

    # ────────── NOT-FOUND CARD ──────────

    def _not_found_text(self, ctx: StepContext) -> str:
        raw = ctx.data.get("raw_query") or "?"
        return "\n".join([
            f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
            f"{F.EMO['cross']} <b>{F.fb('NOT AVAILABLE')}</b>",
            F.DIV,
            "",
            f"🔍 {F.sc('you searched')} · <code>{raw}</code>",
            "",
            f"{F.EMO['warn']} {F.sc('no files found')}",
            f"{F.EMO['spark']} {F.sc('try a different name')}",
        ])

    def _not_found_kb(self, ctx: StepContext) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([[
            cancel_button(ctx.run_id),
        ]])

    # ────────── SUMMARY CARD ──────────

    async def _send_summary(
        self,
        ctx: StepContext,
        sent: int,
        total: int,
    ) -> None:
        client = ctx.client
        if client is None:
            return
        try:
            text = "\n".join([
                f"{F.EMO['check']} <b>{F.fb('DONE')}</b>",
                F.DIV,
                "",
                f"✅ {F.sc('sent')} · <b>{sent}</b>",
                f"❌ {F.sc('failed')} · <b>{max(0, total - sent)}</b>",
                "",
                f"{F.EMO['spark']} <i>{F.sc('enjoy!')}</i>",
            ])
            await client.send_message(
                chat_id=ctx.user_id,
                text=text,
                parse_mode=ParseMode.HTML,
            )
        except Exception:
            pass
