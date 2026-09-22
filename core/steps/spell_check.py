# ============================================================
# 🏨 DOWNTOWN VILLA — STEP: SPELL CHECK
# ============================================================
#
# Ultra spell correction — DB-verified only.
#
# Rules:
#   • Never show a correction unless the corrected title EXISTS in DB
#   • Try up to N candidates (configurable)
#   • Higher fuzzy threshold than v1
#   • Silent when query already matches
#
# Data output:
#   {
#     "corrected_from":    str | None,
#     "corrected_to":      str | None,
#     "spell_checked":     bool,
#   }
#
# ============================================================

from __future__ import annotations

import logging
from typing import Any, Optional

from pyrogram.types import CallbackQuery

from core.flow_engine import (
    BaseStep, RenderResult, StepContext, StepResult, register_step,
)

logger = logging.getLogger(__name__)


@register_step
class SpellCheckStep(BaseStep):

    type_name = "spell_check"
    display_name = "Spell Check"
    icon = "🔤"
    help_text = "Ultra spell correction — DB-verified only"
    default_enabled = True
    default_order = 20

    # ────────── RENDER ──────────

    async def render(self, ctx: StepContext) -> RenderResult:
        # If search already had hits, no need to correct
        if ctx.data.get("hits"):
            return RenderResult(auto_skip=True)

        raw = ctx.data.get("raw_query") or ""
        if not raw:
            return RenderResult(auto_skip=True)

        # Already corrected once? Don't loop.
        if ctx.data.get("spell_checked"):
            return RenderResult(auto_skip=True)

        threshold = int(ctx.step_cfg.get("custom", {}).get(
            "threshold",
            ctx.step_cfg.get("threshold", 85),
        ))
        candidates = int(ctx.step_cfg.get("custom", {}).get(
            "candidates",
            ctx.step_cfg.get("candidates", 5),
        ))

        try:
            from media_search.spell_check import (
                get_suggestions, clean_query,
                ai_spell_check,
            )
            from media_search.normalizer import parse_query
        except Exception as e:
            logger.debug(f"[STEPS] spell_check import: {e}")
            return RenderResult(auto_skip=True)

        cleaned = clean_query(raw)
        is_series = bool(ctx.data.get("is_series"))

        # Try spell correction
        corrected: Optional[str] = None
        try:
            corrected = await ai_spell_check(cleaned, is_series=is_series)
            if not corrected and cleaned != raw:
                corrected = await ai_spell_check(raw, is_series=is_series)
        except Exception as e:
            logger.debug(f"[STEPS] ai_spell_check: {e}")

        ctx.data["spell_checked"] = True

        if not corrected or corrected.strip().lower() == raw.strip().lower():
            return RenderResult(auto_skip=True)

        # We have a correction — re-run search with it
        logger.info(f"[STEPS] spell corrected: '{raw}' → '{corrected}'")

        norm, year, is_series = parse_query(corrected)
        corrected_hits = await self._rerun_search(norm, year, is_series)

        if not corrected_hits:
            # Correction exists but DB has no files → ignore correction
            return RenderResult(auto_skip=True)

        # Store both — downstream steps know about the change
        ctx.data["corrected_from"] = raw
        ctx.data["corrected_to"] = corrected
        ctx.data["hits"] = corrected_hits
        ctx.data["normalized_query"] = norm
        ctx.data["year"] = year
        ctx.data["is_series"] = is_series

        return RenderResult(auto_skip=True)

    async def _rerun_search(self, norm, year, is_series) -> list:
        try:
            from media_search import engine as _eng_mod
            engine = getattr(_eng_mod, "engine", None)
            if engine is None:
                return []
            if is_series:
                result = await engine.search_series(norm, year=year)
            else:
                result = await engine.search_movie(norm, year=year)
                if not (result and result.hits):
                    result = await engine.search_series(norm, year=year)
            return list(result.hits or []) if result else []
        except Exception as e:
            logger.debug(f"[STEPS] rerun search: {e}")
            return []

    async def on_input(self, ctx: StepContext, value: Any) -> StepResult:
        if isinstance(value, CallbackQuery):
            data = str(value.data or "")
            if data.startswith("cancel:flow:"):
                return StepResult(action="cancel")
        return StepResult(action="next")
