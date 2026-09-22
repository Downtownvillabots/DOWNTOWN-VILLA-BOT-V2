# ============================================================
# 🏨 DOWNTOWN VILLA — STEP: SEASON
# ============================================================
#
# Season picker — REUSES series_group's exact working logic.
#
# Icons (from series_group):
#   🟢 full     → all episodes present locally
#   🟡 partial  → some episodes present
#   ⚪ empty    → no local files yet
#
# Fully customizable:
#   • per_row (1 / 2 / 3)
#   • auto_skip_if_one
#   • custom icons
#
# Data output:
#   {
#     "tmdb_seasons":  list[dict],   # [{season, episodes, year}, ...]
#     "local_seasons": dict[int, list[int]],
#     "selected_season": int | None,
#     "files_by_season": list[dict],
#   }
#
# ============================================================

from __future__ import annotations

import logging
from typing import Any, Dict, List

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
class SeasonStep(BaseStep):

    type_name = "season"
    display_name = "Season"
    icon = "📺"
    help_text = "Pick a season — icons show local completion"
    default_enabled = True
    default_order = 50

    # Default icons — overridable per group
    ICONS = {
        "full":    "🟢",
        "partial": "🟡",
        "empty":   "⚪",
    }

    # ────────── RENDER ──────────

    async def render(self, ctx: StepContext) -> RenderResult:
        hits = ctx.data.get("hits") or []
        if not hits:
            return RenderResult(auto_skip=True)

        # Only for series
        if not ctx.data.get("is_series"):
            has_season = any(
                getattr(h, "season", None) is not None for h in hits
            )
            if not has_season:
                return RenderResult(auto_skip=True)

        # TMDB season list (best effort)
        tmdb_seasons = await self._tmdb_seasons(ctx)

        # Local season map — reuse series_group._summarize
        local = self._summarize_local(hits)

        if not tmdb_seasons and not local:
            return RenderResult(auto_skip=True)

        # Auto-skip if single season
        total_seasons = max(len(tmdb_seasons), len(local))
        if total_seasons <= 1 and ctx.step_cfg.get("auto_skip_if_one", True):
            if tmdb_seasons:
                ctx.data["selected_season"] = tmdb_seasons[0].get("season")
            elif local:
                ctx.data["selected_season"] = next(iter(sorted(local)))
            ctx.data["tmdb_seasons"] = tmdb_seasons
            ctx.data["local_seasons"] = local
            return RenderResult(auto_skip=True)

        ctx.data["tmdb_seasons"] = tmdb_seasons
        ctx.data["local_seasons"] = local

        text = self._build_text(ctx, tmdb_seasons, local)
        kb = self._build_kb(ctx, tmdb_seasons, local)
        return RenderResult(text=text, keyboard=kb)

    # ────────── INPUT ──────────

    async def on_input(self, ctx: StepContext, value: Any) -> StepResult:
        if isinstance(value, CallbackQuery):
            data = str(value.data or "")

            if data.startswith("cancel:flow:"):
                return StepResult(action="cancel")

            if data.startswith("flow:back:"):
                return StepResult(action="back")

            if data.startswith("seas:pick:"):
                try:
                    _, _, run_id, idx_str = data.split(":", 3)
                    idx = int(idx_str)
                except Exception:
                    return StepResult(action="stay")

                tmdb_seasons = ctx.data.get("tmdb_seasons") or []
                if idx < 0 or idx >= len(tmdb_seasons):
                    return StepResult(action="stay")

                season_num = tmdb_seasons[idx].get("season")
                ctx.data["selected_season"] = season_num

                # Narrow search with language + season (series_group logic)
                files = await self._refine_search(ctx, season_num)
                ctx.data["files_by_season"] = files
                if files:
                    ctx.data["hits"] = files

                return StepResult(action="next")

        return StepResult(action="stay")

    # ────────── HELPERS ──────────

    async def _tmdb_seasons(self, ctx: StepContext) -> List[Dict[str, Any]]:
        """Reuse series_group's TMDB helper."""
        try:
            from plugins.series_group import series_group as _sg
            seasons_fn = getattr(_sg, "_tmdb_seasons", None)
            details_fn = getattr(_sg, "_tmdb_series_details", None)
            if seasons_fn is None or details_fn is None:
                return []
            details = ctx.data.get("tmdb_details")
            if not details:
                tmdb_id = ctx.data.get("tmdb_id")
                if not tmdb_id:
                    return []
                details = await details_fn(tmdb_id)
                ctx.data["tmdb_details"] = details
            if not details:
                return []
            return list(seasons_fn(details) or [])
        except Exception as e:
            logger.debug(f"[STEPS] tmdb_seasons: {e}")
            return []

    def _summarize_local(self, hits) -> Dict[int, List[int]]:
        """Reuse series_group._summarize output for local seasons."""
        out: Dict[int, List[int]] = {}
        try:
            from plugins.series_group import series_group as _sg
            fn = getattr(_sg, "_summarize", None)
            if fn is not None:
                summary = fn(hits) or {}
                seasons = summary.get("seasons") or {}
                for sn, eps in seasons.items():
                    out[int(sn)] = list(eps)
                return out
        except Exception:
            pass

        # Fallback inline
        for h in hits:
            sn = getattr(h, "season", None)
            ep = getattr(h, "episode", None)
            if sn is None:
                continue
            out.setdefault(int(sn), [])
            if ep is not None:
                out[int(sn)].append(int(ep))
        return out

    async def _refine_search(self, ctx: StepContext, season: int) -> list:
        """Reuse series_group's _engine_search with language + season."""
        try:
            from plugins.series_group import series_group as _sg
            fn = getattr(_sg, "_engine_search", None)
            if fn is None:
                return []
            title = ctx.data.get("raw_query") or ""
            lang = ctx.data.get("selected_language")
            hits = await fn(title, language=lang, season=season) or []
            return list(hits)
        except Exception as e:
            logger.debug(f"[STEPS] refine_search season: {e}")
            return []

    def _icon_for(self, season: int, tmdb_eps: int, local: Dict) -> str:
        local_eps = local.get(season) or []
        count = len([e for e in local_eps if e and e > 0])
        if count == 0:
            return self.ICONS["empty"]
        if tmdb_eps and count >= tmdb_eps:
            return self.ICONS["full"]
        return self.ICONS["partial"]

    def _build_text(self, ctx, tmdb_seasons, local) -> str:
        title = ctx.data.get("raw_query") or "?"
        lang = ctx.data.get("selected_language") or "—"
        lines = [
            f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
            f"{F.EMO['tv']} <b>{F.fb('PICK SEASON')}</b>",
            F.DIV,
            "",
            f"{F.EMO['film']} <b>{F.sc(title)}</b>",
            f"{F.EMO['sound']} {F.sc('language')} · <code>{lang}</code>",
            "",
            f"🟢 {F.sc('full')}   🟡 {F.sc('partial')}   ⚪ {F.sc('no files')}",
            "",
            F.DIV_S,
        ]
        return "\n".join(lines)

    def _build_kb(self, ctx, tmdb_seasons, local) -> InlineKeyboardMarkup:
        per_row = int(ctx.step_cfg.get("per_row", 2))
        rows = []
        row = []
        for i, s in enumerate(tmdb_seasons):
            sn = s.get("season")
            eps = int(s.get("episodes", 0) or 0)
            icon = self._icon_for(sn, eps, local)
            label = f"{icon} S{sn:02d}"
            if eps:
                label += f" · {eps}ᴱ"
            row.append(InlineKeyboardButton(
                label,
                callback_data=f"seas:pick:{ctx.run_id}:{i}",
            ))
            if len(row) == max(1, min(3, per_row)):
                rows.append(row)
                row = []
        if row:
            rows.append(row)

        rows.append([
            back_button(ctx.run_id),
            cancel_button(ctx.run_id),
        ])
        return InlineKeyboardMarkup(rows)
