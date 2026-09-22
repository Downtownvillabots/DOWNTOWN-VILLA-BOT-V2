# ============================================================
# 🏨 DOWNTOWN VILLA — STEP: SUGGESTIONS
# ============================================================
#
# Shown when the base search returned zero hits.
#
# ONE engine, THREE renderers:
#   • PM         → clean list, tap to deliver
#   • Group      → "did you mean?" list, tap → file list
#   • Series Grp → shows S/E hints, ratings, season count
#
# Data output:
#   {
#     "suggestions":       list[dict],
#     "selected_suggestion": dict | None,
#   }
#
# ============================================================

from __future__ import annotations

import logging
from typing import Any, Optional

from pyrogram.enums import ParseMode
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup,
)

from core.flow_engine import (
    BaseStep, RenderResult, StepContext, StepResult, register_step,
    cancel_button,
)
from utils import fonts as F

logger = logging.getLogger(__name__)


@register_step
class SuggestionsStep(BaseStep):

    type_name = "suggestions"
    display_name = "Suggestions"
    icon = "💡"
    help_text = "IMDb/TMDB fallback when DB has no match"
    default_enabled = True
    default_order = 30

    # ────────── RENDER ──────────

    async def render(self, ctx: StepContext) -> RenderResult:
        # Only when base search found nothing
        if ctx.data.get("hits"):
            return RenderResult(auto_skip=True)

        # Only once
        if ctx.data.get("suggestions_tried"):
            return RenderResult(auto_skip=True)

        raw = ctx.data.get("raw_query") or ""
        if not raw:
            return RenderResult(auto_skip=True)

        ctx.data["suggestions_tried"] = True

        is_series = bool(ctx.data.get("is_series"))
        max_items = int(ctx.step_cfg.get("max_items", 8))
        per_row = int(ctx.step_cfg.get("per_row", 1))

        # Fetch suggestions via shared engine
        try:
            from media_search.spell_check import (
                get_suggestions, clean_query,
            )
        except Exception as e:
            logger.debug(f"[STEPS] suggestions import: {e}")
            return RenderResult(auto_skip=True)

        cleaned = clean_query(raw)
        suggestions: list = []
        try:
            suggestions = await get_suggestions(cleaned, is_series=is_series)
            if not suggestions and cleaned != raw:
                suggestions = await get_suggestions(raw, is_series=is_series)
        except Exception as e:
            logger.debug(f"[STEPS] get_suggestions: {e}")

        if not suggestions:
            return RenderResult(auto_skip=True)

        suggestions = suggestions[:max_items]
        ctx.data["suggestions"] = suggestions

        # Render context
        renderer = self._pick_renderer(ctx)
        text = self._render_text(ctx, raw, suggestions, renderer)
        kb = self._render_kb(ctx, suggestions, per_row)

        return RenderResult(text=text, keyboard=kb)

    # ────────── RENDERERS ──────────

    def _pick_renderer(self, ctx: StepContext) -> str:
        if ctx.is_group:
            return "group"
        return "pm"

    def _render_text(self, ctx, raw, suggestions, renderer) -> str:
        header_lines = [
            f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
            f"{F.EMO['search']} <b>{F.fb('DID YOU MEAN?')}</b>",
            F.DIV,
            "",
            f"🔍 {F.sc('you searched')} · <code>{F.sc(raw)}</code>",
            "",
            f"{F.EMO['spark']} <b>{len(suggestions)}</b> {F.sc('suggestions')}",
            "",
        ]

        rows = []
        for i, s in enumerate(suggestions, 1):
            title = s.get("title") or "?"
            year = s.get("year")
            rating = s.get("rating")
            kind = (s.get("kind") or s.get("type") or "").lower()

            line = f"<b>{i:02d}.</b> {F.EMO['film']} <b>{title}</b>"
            if year:
                line += f" <code>({year})</code>"
            if rating:
                line += f" · ⭐ <code>{rating}</code>"
            if kind and renderer == "group":
                line += f" · <i>{kind[:3]}</i>"
            rows.append(line)

        rows += [
            "",
            F.DIV_S,
            f"{F.EMO['info']} <i>{F.sc('tap one to search for files')}</i>",
        ]
        return "\n".join(header_lines + rows)

    def _render_kb(self, ctx, suggestions, per_row) -> InlineKeyboardMarkup:
        rows = []
        row = []
        for i, s in enumerate(suggestions):
            title = (s.get("title") or "?")[:30]
            year = s.get("year")
            label = f"{F.EMO['film']} {title}"
            if year:
                label += f" ({year})"
            if len(label) > 45:
                label = label[:42] + "…"
            row.append(InlineKeyboardButton(
                label,
                callback_data=f"sug:pick:{ctx.run_id}:{i}",
            ))
            if len(row) == max(1, min(3, per_row)):
                rows.append(row)
                row = []
        if row:
            rows.append(row)

        rows.append([
            InlineKeyboardButton(
                f"{F.EMO['search']} {F.sc('search google')}",
                url=f"https://www.google.com/search?q={ctx.data.get('raw_query', '')}",
            ),
        ])
        rows.append([
            cancel_button(ctx.run_id),
        ])
        return InlineKeyboardMarkup(rows)

    # ────────── INPUT ──────────

    async def on_input(self, ctx: StepContext, value: Any) -> StepResult:
        if not isinstance(value, CallbackQuery):
            return StepResult(action="stay")

        data = str(value.data or "")

        if data.startswith("cancel:flow:"):
            return StepResult(action="cancel")

        if data.startswith("sug:pick:"):
            try:
                _, _, run_id, idx_str = data.split(":", 3)
                idx = int(idx_str)
            except Exception:
                return StepResult(action="stay")

            suggestions = ctx.data.get("suggestions") or []
            if idx < 0 or idx >= len(suggestions):
                return StepResult(action="stay")

            chosen = suggestions[idx]
            ctx.data["selected_suggestion"] = chosen

            # Re-run search with the chosen title
            try:
                from media_search.normalizer import parse_query
                from media_search import engine as _eng_mod

                title = chosen.get("title") or ""
                year = chosen.get("year")

                norm, _, is_series = parse_query(title)
                engine = getattr(_eng_mod, "engine", None)
                hits: list = []
                if engine is not None and norm:
                    if is_series:
                        r = await engine.search_series(norm, year=year)
                    else:
                        r = await engine.search_movie(norm, year=year)
                        if not (r and r.hits):
                            r = await engine.search_series(norm, year=year)
                    hits = list(r.hits or []) if r else []

                ctx.data["hits"] = hits
                ctx.data["raw_query"] = title
                ctx.data["normalized_query"] = norm
                ctx.data["is_series"] = is_series
                ctx.data["year"] = year
            except Exception as e:
                logger.debug(f"[STEPS] suggestion rerun: {e}")

            return StepResult(action="next")

        return StepResult(action="stay")
