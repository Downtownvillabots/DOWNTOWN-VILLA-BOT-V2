# ============================================================
# 🏨 DOWNTOWN VILLA — STEP: BASE SEARCH
# ============================================================
#
# The very first step of every search flow.
# Takes the raw user query and does the initial DB lookup.
#
# Customization (from /flow editor):
#   • Per-row layout
#   • Max results to show
#   • Auto-skip when DB returns empty (default: OFF — we
#     want to show "not found" so suggestions can kick in)
#   • Custom label
#
# Data output (adds to ctx.data):
#   {
#     "raw_query":         str,
#     "normalized_query":  str,
#     "year":              int | None,
#     "is_series":         bool,
#     "hits":              list[dict],   # empty on miss
#     "complete":          bool,         # all shards OK
#     "search_error":      str | None,
#   }
#
# ============================================================

from __future__ import annotations

import logging
from typing import Any, Optional

from pyrogram.enums import ParseMode
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from core.flow_engine import (
    BaseStep, RenderResult, StepContext, StepResult,
    register_step,
)
from core.flow_engine import cancel_button
from utils import fonts as F
from utils import format as FM

logger = logging.getLogger(__name__)


@register_step
class BaseSearchStep(BaseStep):
    """
    Initial search — takes raw text, returns DB hits.
    Never shows a keyboard; auto-advances.
    """

    type_name = "base_search"
    display_name = "Base Search"
    icon = "🔎"
    help_text = "Initial DB lookup for the user query"
    default_enabled = True
    default_order = 10
    mandatory = True

    # ────────── RENDER ──────────

    async def render(self, ctx: StepContext) -> RenderResult:
        """
        Show a small status while searching, then hand off.

        This step is a "loader" — it performs the actual search
        and stores results in ctx.data, then auto-advances.
        """
        raw = self._extract_query(ctx)

        # No query yet → ask the user
        if not raw:
            text = "\n".join([
                f"{F.EMO['search']} <b>{F.fb('SEARCH')}</b>",
                F.DIV,
                "",
                f"{F.EMO['spark']} <i>{F.sc('type a movie or series name')}</i>",
                f"{F.EMO['info']} {F.sc('example')} · <code>Interstellar 2014</code>",
                "",
                F.DIV_S,
            ])
            kb = self._build_prompt_kb(ctx)
            return RenderResult(text=text, keyboard=kb)

        # We have a query → run search silently and auto-advance
        result = await self._do_search(ctx, raw)

        # If nothing found, we still advance — the suggestions
        # step (or missing step) will handle it downstream.
        ctx.data.update(result)

        return RenderResult(auto_skip=True)

    # ────────── INPUT ──────────

    async def on_input(self, ctx: StepContext, value: Any) -> StepResult:
        """
        Value is either a raw string (PM) or callback payload.
        """
        # Raw text from PM
        if isinstance(value, str):
            ctx.data["raw_query"] = value.strip()
            return StepResult(action="stay")

        # Callback objects
        data = ""
        if isinstance(value, CallbackQuery):
            data = str(value.data or "")

        # cancel handled by engine
        if data.startswith("cancel:flow:"):
            return StepResult(action="cancel")

        # Any other callback → treat as "re-run"
        return StepResult(action="stay")

    # ────────── HELPERS ──────────

    def _extract_query(self, ctx: StepContext) -> str:
        """Pull query from earlier data or the incoming message."""
        q = ctx.data.get("raw_query")
        if q:
            return str(q).strip()

        # Look at incoming message text
        msg = ctx.message
        if msg is not None:
            text = getattr(msg, "text", None) or getattr(msg, "caption", None)
            if text and not str(text).startswith("/"):
                return str(text).strip()

        return ""

    def _build_prompt_kb(self, ctx: StepContext) -> InlineKeyboardMarkup:
        return InlineKeyboardMarkup([[
            cancel_button(ctx.run_id),
        ]])

    async def _do_search(self, ctx: StepContext, raw: str) -> dict:
        """Run search across all media shards."""
        out: dict = {
            "raw_query": raw,
            "normalized_query": "",
            "year": None,
            "is_series": False,
            "hits": [],
            "complete": False,
            "search_error": None,
        }

        try:
            from media_search.normalizer import parse_query
            from media_search import engine as _eng_mod

            norm, year, is_series = parse_query(raw)
            out["normalized_query"] = norm
            out["year"] = year
            out["is_series"] = is_series

            if not norm:
                out["search_error"] = "empty query after normalize"
                return out

            engine = getattr(_eng_mod, "engine", None)
            if engine is None:
                out["search_error"] = "engine unavailable"
                return out

            # Run search
            try:
                if is_series:
                    result = await engine.search_series(norm, year=year)
                else:
                    r_movie = await engine.search_movie(norm, year=year)
                    if r_movie and r_movie.hits:
                        result = r_movie
                    else:
                        result = await engine.search_series(norm, year=year)
            except Exception as e:
                logger.exception(f"[STEPS] search engine error: {e}")
                out["search_error"] = str(e)
                return out

            # Retry without year on empty
            if (not result or not result.hits) and year:
                try:
                    retry = await engine.search_any(norm, year=None)
                    if retry and retry.hits:
                        result = retry
                except Exception:
                    pass

            if result is not None:
                out["hits"] = list(result.hits or [])
                out["complete"] = bool(getattr(result, "complete", True))
            else:
                out["complete"] = True

            logger.info(
                f"[STEPS] search '{raw}' → {len(out['hits'])} hits "
                f"(complete={out['complete']})"
            )

        except Exception as e:
            logger.exception(f"[STEPS] base_search crash: {e}")
            out["search_error"] = str(e)

        return out


# ============================================================
# SELF-CHECK
# ============================================================

def _self_check() -> bool:
    from core.flow_engine import get_step
    return get_step("base_search") is not None


try:
    _SELF_CHECK_PASS = _self_check()
except Exception:
    _SELF_CHECK_PASS = False
