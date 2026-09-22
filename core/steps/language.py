# ============================================================
# 🏨 DOWNTOWN VILLA — STEP: LANGUAGE
# ============================================================
#
# Language picker — reuses series_group's proven logic.
#
# Rules (from series_group):
#   • TMDB langs order first
#   • Local DB languages on top (🟢 = has files)
#   • TMDB-only langs shown (⚪ = no local files yet)
#   • Selected language narrows search downstream
#
# Data output:
#   {
#     "available_langs":   list[str],
#     "ordered_langs":     list[str],
#     "selected_language": str | None,
#     "files_by_lang":     list[dict],
#   }
#
# ============================================================

from __future__ import annotations

import logging
from typing import Any, List

from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
)

from core.flow_engine import (
    BaseStep, RenderResult, StepContext, StepResult, register_step,
    cancel_button, back_button,
)
from utils import fonts as F

logger = logging.getLogger(__name__)


@register_step
class LanguageStep(BaseStep):

    type_name = "language"
    display_name = "Language"
    icon = "🌍"
    help_text = "Pick the audio language"
    default_enabled = True
    default_order = 40

    DEFAULT_LANGS = [
        "English", "Hindi", "Tamil", "Telugu",
        "Malayalam", "Kannada", "Bengali",
    ]

    # ────────── RENDER ──────────

    async def render(self, ctx: StepContext) -> RenderResult:
        hits = ctx.data.get("hits") or []
        if not hits:
            return RenderResult(auto_skip=True)

        # Local langs from hits
        local: List[str] = []
        for h in hits:
            langs = getattr(h, "audio_languages", None) or []
            for lang in langs:
                norm = self._norm(lang)
                if norm and norm not in local:
                    local.append(norm)

        # TMDB langs (best effort — may be empty)
        tmdb_langs = await self._tmdb_langs(ctx)
        ordered = self._order_langs(tmdb_langs, local)

        # Auto-skip if only one language and rule enabled
        if len(ordered) <= 1 and ctx.step_cfg.get("auto_skip_if_one", True):
            ctx.data["selected_language"] = ordered[0] if ordered else ""
            return RenderResult(auto_skip=True)

        if not ordered:
            return RenderResult(auto_skip=True)

        ctx.data["available_langs"] = local
        ctx.data["ordered_langs"] = ordered

        text = self._build_text(ctx, ordered, local)
        kb = self._build_kb(ctx, ordered, local)
        return RenderResult(text=text, keyboard=kb)

    # ────────── INPUT ──────────

    async def on_input(self, ctx: StepContext, value: Any) -> StepResult:
        if isinstance(value, CallbackQuery):
            data = str(value.data or "")

            if data.startswith("cancel:flow:"):
                return StepResult(action="cancel")

            if data.startswith("flow:back:"):
                return StepResult(action="back")

            if data.startswith("lang:pick:"):
                try:
                    _, _, run_id, idx_str = data.split(":", 3)
                    idx = int(idx_str)
                except Exception:
                    return StepResult(action="stay")

                ordered = ctx.data.get("ordered_langs") or []
                if idx < 0 or idx >= len(ordered):
                    return StepResult(action="stay")

                chosen = ordered[idx]
                ctx.data["selected_language"] = chosen

                # Narrow search with selected language
                files = await self._refine_search(ctx, chosen)
                ctx.data["files_by_lang"] = files
                if files:
                    ctx.data["hits"] = files

                return StepResult(action="next")

        return StepResult(action="stay")

    # ────────── HELPERS ──────────

    def _norm(self, lang: Any) -> str:
        if not lang:
            return ""
        return str(lang).strip().title()

    def _order_langs(self, tmdb: List[str], local: List[str]) -> List[str]:
        base = []
        # Local first
        for l in local:
            if l and l not in base:
                base.append(l)
        # TMDB + defaults
        for l in (tmdb or self.DEFAULT_LANGS):
            n = self._norm(l)
            if n and n not in base:
                base.append(n)
        return base[:8]

    async def _tmdb_langs(self, ctx: StepContext) -> List[str]:
        """Reuse series_group's TMDB helper."""
        try:
            from plugins.series_group import series_group as _sg
            fn = getattr(_sg, "_tmdb_languages", None)
            if fn is None:
                return []
            tmdb_id = ctx.data.get("tmdb_id")
            if not tmdb_id:
                return []
            details = ctx.data.get("tmdb_details")
            if not details:
                details_fn = getattr(_sg, "_tmdb_series_details", None)
                if details_fn:
                    details = await details_fn(tmdb_id)
                    ctx.data["tmdb_details"] = details
            if not details:
                return []
            return list(fn(details) or [])
        except Exception as e:
            logger.debug(f"[STEPS] tmdb_langs: {e}")
            return []

    async def _refine_search(self, ctx: StepContext, language: str) -> list:
        """Reuse series_group's engine search."""
        try:
            from plugins.series_group import series_group as _sg
            fn = getattr(_sg, "_engine_search", None)
            if fn is None:
                return []
            title = ctx.data.get("raw_query") or ""
            hits = await fn(title, language=language) or []
            return list(hits)
        except Exception as e:
            logger.debug(f"[STEPS] refine_search: {e}")
            return []

    def _build_text(self, ctx, ordered, local) -> str:
        lines = [
            f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
            f"{F.EMO['lang'] if hasattr(F.EMO, 'lang') else F.EMO['sound']} "
            f"<b>{F.fb('PICK LANGUAGE')}</b>",
            F.DIV,
            "",
            f"🟢 {F.sc('has files')}   ⚪ {F.sc('tmdb only')}",
            "",
            F.DIV_S,
            f"{F.EMO['spark']} <i>{F.sc('tap a language to continue')}</i>",
        ]
        return "\n".join(lines)

    def _build_kb(self, ctx, ordered, local) -> InlineKeyboardMarkup:
        per_row = int(ctx.step_cfg.get("per_row", 2))
        rows = []
        row = []
        for i, lang in enumerate(ordered):
            icon = "🟢" if lang in local else "⚪"
            label = f"{icon} {lang}"
            row.append(InlineKeyboardButton(
                label,
                callback_data=f"lang:pick:{ctx.run_id}:{i}",
            ))
            if len(row) == max(1, min(3, per_row)):
                rows.append(row)
                row = []
        if row:
            rows.append(row)

        # Cancel + Back row
        rows.append([
            back_button(ctx.run_id),
            cancel_button(ctx.run_id),
        ])
        return InlineKeyboardMarkup(rows)
