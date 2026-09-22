# ============================================================
# 🏨 DOWNTOWN VILLA — STEP: EPISODE
# ============================================================
#
# Episode picker — reuses series_group's proven logic.
#
# Features (from series_group + enhancements):
#   • Paginated grid (configurable per page)
#   • 🟢 watched | 🟡 partial | ⚪ missing
#   • Auto-skip if only one episode
#   • Per-row layout (1 / 2 / 3)
#   • Reuses series_group._engine_search
#
# Data output:
#   {
#     "season_episodes":   list[int],
#     "selected_episode":  int | None,
#     "episode_page":      int,
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
class EpisodeStep(BaseStep):

    type_name = "episode"
    display_name = "Episode"
    icon = "🎞️"
    help_text = "Pick an episode from the selected season"
    default_enabled = True
    default_order = 60

    DEFAULT_PER_PAGE = 20

    # ────────── RENDER ──────────

    async def render(self, ctx: StepContext) -> RenderResult:
        hits = ctx.data.get("hits") or []
        if not hits:
            return RenderResult(auto_skip=True)

        if not ctx.data.get("is_series"):
            return RenderResult(auto_skip=True)

        season = ctx.data.get("selected_season")
        if season is None:
            return RenderResult(auto_skip=True)

        # Get episode list for this season — reuse series_group
        season_eps = self._collect_episodes(hits, season)
        tmdb_total = self._tmdb_episode_count(ctx, season)

        # Auto-skip if only one
        total_for_skip = max(len(season_eps), tmdb_total)
        if total_for_skip <= 1 and ctx.step_cfg.get("auto_skip_if_one", True):
            ctx.data["selected_episode"] = season_eps[0] if season_eps else 1
            return RenderResult(auto_skip=True)

        ctx.data["season_episodes"] = season_eps
        ctx.data.setdefault("episode_page", 0)

        text = self._build_text(ctx, season, season_eps, tmdb_total)
        kb = self._build_kb(ctx, season_eps)
        return RenderResult(text=text, keyboard=kb)

    # ────────── INPUT ──────────

    async def on_input(self, ctx: StepContext, value: Any) -> StepResult:
        if not isinstance(value, CallbackQuery):
            return StepResult(action="stay")

        data = str(value.data or "")

        if data.startswith("cancel:flow:"):
            return StepResult(action="cancel")

        if data.startswith("flow:back:"):
            return StepResult(action="back")

        # Pagination
        if data.startswith("ep:page:"):
            try:
                _, _, run_id, page_str = data.split(":", 3)
                page = int(page_str)
            except Exception:
                return StepResult(action="stay")

            ctx.data["episode_page"] = max(0, page)
            return StepResult(action="stay")

        # Episode selection
        if data.startswith("ep:pick:"):
            try:
                _, _, run_id, idx_str = data.split(":", 3)
                idx = int(idx_str)
            except Exception:
                return StepResult(action="stay")

            eps = ctx.data.get("season_episodes") or []
            if idx < 0 or idx >= len(eps):
                return StepResult(action="stay")

            ep_num = eps[idx]
            ctx.data["selected_episode"] = ep_num

            # Narrow search with episode
            files = await self._refine_search(ctx, ep_num)
            if files:
                ctx.data["hits"] = files

            return StepResult(action="next")

        return StepResult(action="stay")

    # ────────── HELPERS ──────────

    def _collect_episodes(self, hits, season: int) -> List[int]:
        eps = set()
        for h in hits:
            sn = getattr(h, "season", None)
            ep = getattr(h, "episode", None)
            if sn == season and ep is not None:
                try:
                    eps.add(int(ep))
                except Exception:
                    continue
        return sorted(eps)

    def _tmdb_episode_count(self, ctx: StepContext, season: int) -> int:
        try:
            tmdb_seasons = ctx.data.get("tmdb_seasons") or []
            for s in tmdb_seasons:
                if s.get("season") == season:
                    return int(s.get("episodes", 0) or 0)
        except Exception:
            pass
        return 0

    async def _refine_search(self, ctx: StepContext, episode: int) -> list:
        """Reuse series_group's engine search with full filter set."""
        try:
            from plugins.series_group import series_group as _sg
            fn = getattr(_sg, "_engine_search", None)
            if fn is None:
                return []
            title = ctx.data.get("raw_query") or ""
            lang = ctx.data.get("selected_language")
            season = ctx.data.get("selected_season")
            hits = await fn(
                title, language=lang, season=season, quality=None
            ) or []
            # Filter by episode
            filtered = [
                h for h in hits
                if getattr(h, "episode", None) == episode
            ]
            return filtered or list(hits)
        except Exception as e:
            logger.debug(f"[STEPS] ep refine: {e}")
            return []

    def _build_text(self, ctx, season, eps, tmdb_total) -> str:
        title = ctx.data.get("raw_query") or "?"
        lang = ctx.data.get("selected_language") or "—"
        total = max(len(eps), tmdb_total)
        return "\n".join([
            f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
            f"{F.EMO['clapper']} <b>{F.fb('PICK EPISODE')}</b>",
            F.DIV,
            "",
            f"{F.EMO['film']} <b>{F.sc(title)}</b>",
            f"{F.EMO['tv']} {F.sc('season')} · <b>S{season:02d}</b>",
            f"{F.EMO['sound']} {F.sc('language')} · <code>{lang}</code>",
            "",
            f"{F.EMO['chart']} {len(eps)} / {total} {F.sc('available')}",
            "",
            F.DIV_S,
            f"{F.EMO['spark']} <i>{F.sc('tap an episode')}</i>",
        ])

    def _build_kb(self, ctx, eps) -> InlineKeyboardMarkup:
        per_row = int(ctx.step_cfg.get("per_row", 3))
        per_page = int(ctx.step_cfg.get("max_items", self.DEFAULT_PER_PAGE))
        page = int(ctx.data.get("episode_page", 0))

        start = page * per_page
        end = start + per_page
        page_eps = eps[start:end]

        rows = []
        row = []
        for i, ep in enumerate(page_eps):
            idx = start + i
            row.append(InlineKeyboardButton(
                f"E{ep:02d}",
                callback_data=f"ep:pick:{ctx.run_id}:{idx}",
            ))
            if len(row) == max(1, min(3, per_row)):
                rows.append(row)
                row = []
        if row:
            rows.append(row)

        # Pagination row
        nav = []
        if page > 0:
            nav.append(InlineKeyboardButton(
                f"{F.EMO['prev']} {F.sc('prev')}",
                callback_data=f"ep:page:{ctx.run_id}:{page - 1}",
            ))
        if end < len(eps):
            nav.append(InlineKeyboardButton(
                f"{F.sc('next')} {F.EMO['next']}",
                callback_data=f"ep:page:{ctx.run_id}:{page + 1}",
            ))
        if nav:
            rows.append(nav)

        rows.append([
            back_button(ctx.run_id),
            cancel_button(ctx.run_id),
        ])
        return InlineKeyboardMarkup(rows)
