# ============================================================
# 🏨 DOWNTOWN VILLA — STEP: QUALITY
# ============================================================
#
# Quality picker — reuses series_group admin preference system.
#
# Features (from series_group):
#   • Admin-set preferred qualities for a series
#   • Falls back to locally available qualities
#   • Ranked by quality value (2160p → 480p)
#   • Fully customizable per_row + max_items
#
# Data output:
#   {
#     "available_qualities":  list[str],
#     "selected_quality":     str | None,
#     "final_files":          list[dict],
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
class QualityStep(BaseStep):

    type_name = "quality"
    display_name = "Quality"
    icon = "🎯"
    help_text = "Pick a quality tier"
    default_enabled = True
    default_order = 70

    QUALITY_RANK = {
        "4320P": 100, "8K": 100, "2160P": 90, "4K": 90, "UHD": 90,
        "1440P": 80, "2K": 80, "1080P": 70, "FULLHD": 70, "FHD": 70,
        "720P": 60, "HD": 60, "576P": 50, "480P": 40, "SD": 40,
        "360P": 30, "240P": 20, "UNKNOWN": 25,
    }

    # ────────── RENDER ──────────

    async def render(self, ctx: StepContext) -> RenderResult:
        hits = ctx.data.get("hits") or []
        if not hits:
            return RenderResult(auto_skip=True)

        # Collect available qualities
        available = sorted(
            {str(getattr(h, "quality", "")).upper() for h in hits
             if getattr(h, "quality", None)},
            key=lambda q: self.QUALITY_RANK.get(q, 0),
            reverse=True,
        )

        if not available:
            return RenderResult(auto_skip=True)

        # Admin preference override (reuse series_group._get_series_pref)
        admin_prefs = await self._admin_prefs(ctx)
        if admin_prefs:
            final = [q for q in admin_prefs if q in available]
            if not final:
                final = admin_prefs  # show admin list anyway
        else:
            final = available

        # Auto-skip if only one
        if len(final) <= 1 and ctx.step_cfg.get("auto_skip_if_one", True):
            chosen = final[0] if final else available[0]
            ctx.data["selected_quality"] = chosen
            ctx.data["final_files"] = self._filter_by_quality(hits, chosen)
            return RenderResult(auto_skip=True)

        ctx.data["available_qualities"] = final

        text = self._build_text(ctx, final, len(hits))
        kb = self._build_kb(ctx, final)
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

        if data.startswith("qual:pick:"):
            try:
                _, _, run_id, idx_str = data.split(":", 3)
                idx = int(idx_str)
            except Exception:
                return StepResult(action="stay")

            quals = ctx.data.get("available_qualities") or []
            if idx < 0 or idx >= len(quals):
                return StepResult(action="stay")

            chosen = quals[idx]
            ctx.data["selected_quality"] = chosen

            files = self._filter_by_quality(
                ctx.data.get("hits") or [], chosen
            )
            ctx.data["final_files"] = files
            if files:
                ctx.data["hits"] = files

            return StepResult(action="next")

        return StepResult(action="stay")

    # ────────── HELPERS ──────────

    async def _admin_prefs(self, ctx: StepContext) -> List[str]:
        """Reuse series_group's admin preference per series slug."""
        try:
            from plugins.series_group import series_group as _sg
            fn = getattr(_sg, "_get_series_pref", None)
            if fn is None:
                return []
            title = ctx.data.get("raw_query") or ""
            slug = self._slug(title)
            pref = await fn(slug) or {}
            return list(pref.get("qualities") or [])
        except Exception as e:
            logger.debug(f"[STEPS] admin_prefs: {e}")
            return []

    def _slug(self, text: str) -> str:
        import re
        if not text:
            return ""
        return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")

    def _filter_by_quality(self, hits, quality: str) -> list:
        q = quality.upper()
        return [
            h for h in hits
            if str(getattr(h, "quality", "")).upper() == q
            or str(getattr(h, "quality", "")).upper() == "UNKNOWN"
        ]

    def _build_text(self, ctx, quals, hit_count) -> str:
        title = ctx.data.get("raw_query") or "?"
        lines = [
            f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
            f"{F.EMO['spark']} <b>{F.fb('PICK QUALITY')}</b>",
            F.DIV,
            "",
            f"{F.EMO['film']} <b>{F.sc(title)}</b>",
        ]
        season = ctx.data.get("selected_season")
        if season is not None:
            lines.append(f"{F.EMO['tv']} {F.sc('season')} · <b>S{season:02d}</b>")
        episode = ctx.data.get("selected_episode")
        if episode is not None:
            lines.append(f"{F.EMO['clapper']} {F.sc('episode')} · <b>E{episode:02d}</b>")
        lines += [
            "",
            f"{F.EMO['chart']} {F.sc('files to send')} · <b>{hit_count}</b>",
            "",
            F.DIV_S,
            f"{F.EMO['spark']} <i>{F.sc('tap a quality')}</i>",
        ]
        return "\n".join(lines)

    def _build_kb(self, ctx, quals) -> InlineKeyboardMarkup:
        per_row = int(ctx.step_cfg.get("per_row", 2))
        rows = []
        row = []
        for i, q in enumerate(quals):
            row.append(InlineKeyboardButton(
                f"🎯 {q}",
                callback_data=f"qual:pick:{ctx.run_id}:{i}",
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
