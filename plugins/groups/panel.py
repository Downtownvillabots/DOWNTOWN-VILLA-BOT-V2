# ============================================================
# 🏨 DOWNTOWN VILLA — GROUPS PANEL RENDERER
# ============================================================
#
# Renders every section of the group settings panel.
# Pure UI — no handlers, no DB writes, no session state.
#
# Router (file 4) calls these and edits the message.
#
# Callback scheme (all routed by router.py):
#   ga:s:{section}                    navigate
#   ga:tog:{path}                     toggle boolean
#   ga:set:{path}:{value}             set a value
#   ga:flow:{step_key}                open flow step
#   ga:flow_tog:{step_key}            toggle flow step
#   ga:flow_row:{step_key}:{n}        set per_row
#   ga:flow_skip:{step_key}           toggle auto-skip
#   ga:cap:edit                       start caption edit session
#   ga:cap:reset                      reset caption
#   ga:btn:view:{idx}                 view button
#   ga:btn:add                        start button add session
#   ga:btn:tog:{idx}                  toggle button enabled
#   ga:btn:del:{idx}                  delete button
#   ga:btn_row:{n}                    set buttons per row
#   ga:fsub:add                       add fsub channel
#   ga:fsub:rm:{idx}                  remove fsub channel
#   ga:req_ch:{id}                    set request channel
#   ga:reset_do                       execute reset
#
# ============================================================

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from pyrogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from plugins.groups import state as S
from utils import fonts as F
from utils import format as FM

logger = logging.getLogger(__name__)

# ── short aliases ──
DIV = F.DIV
DIV_S = F.DIV_S


# ============================================================
# SECTION 1 — SHARED HELPERS
# ============================================================

def _on(v: Any) -> str:
    return "🟢 " + F.sc("on") if v else "🔴 " + F.sc("off")


def _line(icon: str, label: str, value: Any) -> str:
    return f"{icon} {F.sc(label)} · <b>{value}</b>"


def _back_close(back: str = "ga:back") -> List[List[InlineKeyboardButton]]:
    return [[
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data=back,
        ),
        InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('close')}",
            callback_data="ga:close",
        ),
    ]]


def _kb(rows: List[List[InlineKeyboardButton]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(rows)


# ============================================================
# SECTION 2 — MAIN PANEL
# ============================================================

async def render_main(chat_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await S.get_config(chat_id)

    mode = str(cfg.get("content_mode", "both"))
    mode_icon = {"movie": "🎬", "series": "📺", "both": "🎬📺"}.get(mode, "🎬📺")

    fsub_n = len((cfg.get("fsub") or {}).get("channels") or [])
    btn_n = len(cfg.get("result_buttons") or [])
    ad_timer = int((cfg.get("auto_delete") or {}).get("bot_timer", 600))
    cap_custom = bool(cfg.get("caption_template"))

    # ── Compact stats summary ──
    st = cfg.get("stats") or {}
    try:
        s_searches = int(st.get("searches_today", 0) or 0)
        s_found = int(st.get("results_found", 0) or 0)
        s_notfound = int(st.get("not_found", 0) or 0)
        s_sent = int(st.get("files_sent", 0) or 0)
    except (TypeError, ValueError):
        s_searches = s_found = s_notfound = s_sent = 0

    if s_searches > 0:
        rate = (s_found / s_searches) * 100
        rate_str = f"{rate:.0f}%"
    else:
        rate_str = "—"

    stats_line = (
        f"📊 {F.sc('stats')} · "
        f"🔎 <b>{s_searches}</b> · "
        f"📤 <b>{s_sent}</b> · "
        f"📈 <b>{rate_str}</b>"
    )

    text = "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"{F.EMO['gear']} <b>{F.fb('GROUP SETTINGS')}</b>",
        DIV, "",
        f"👥 <b>{F.sc(str(cfg.get('title') or chat_id)[:50])}</b>",
        f"🆔 <code>{chat_id}</code>",
        "",
        DIV_S, "",
        _line(mode_icon, "content", mode.upper()),
        _line("🔎", "search", _on(cfg.get("search_enabled", True))),
        _line("💬", "pm search", _on(cfg.get("pm_search_enabled", True))),
        _line("👋", "welcome", _on(cfg.get("welcome_enabled", False))),
        _line("⏱️", "auto-delete", f"{ad_timer}s"),
        _line("📢", "force-sub", f"{fsub_n} channels"),
        _line("🔐", "verify", _on((cfg.get("verify") or {}).get("enabled", False))),
        _line("📝", "caption", "custom" if cap_custom else "global"),
        _line("🔘", "buttons", f"{btn_n}"),
        "",
        DIV_S,
        stats_line,
    ])
    rows = [
        [InlineKeyboardButton(
            f"{F.EMO['search']} {F.sc('search settings')}",
            callback_data="ga:s:search")],
        [InlineKeyboardButton(
            f"{mode_icon} {F.sc('content mode')} · {mode.upper()}",
            callback_data="ga:s:content")],
        [InlineKeyboardButton(
            f"🎯 {F.sc('flow editor')}",
            callback_data="ga:s:flow")],
        [
            InlineKeyboardButton(
                f"📝 {F.sc('caption')}",
                callback_data="ga:s:caption"),
            InlineKeyboardButton(
                f"🔘 {F.sc('buttons')} · {btn_n}",
                callback_data="ga:s:buttons"),
        ],
        [
            InlineKeyboardButton(
                f"👋 {F.sc('welcome')}",
                callback_data="ga:s:welcome"),
            InlineKeyboardButton(
                f"⏱️ {F.sc('auto-delete')}",
                callback_data="ga:s:autodel"),
        ],
        [
            InlineKeyboardButton(
                f"🚫 {F.sc('filters')}",
                callback_data="ga:s:filters"),
            InlineKeyboardButton(
                f"📢 {F.sc('force-sub')} · {fsub_n}",
                callback_data="ga:s:fsub"),
        ],
        [
            InlineKeyboardButton(
                f"🔐 {F.sc('verify')}",
                callback_data="ga:s:verify"),
            InlineKeyboardButton(
                f"🛡️ {F.sc('security')}",
                callback_data="ga:s:security"),
        ],
        [
            InlineKeyboardButton(
                f"📝 {F.sc('requests')}",
                callback_data="ga:s:requests"),
            InlineKeyboardButton(
                f"🎬 {F.sc('metadata')}",
                callback_data="ga:s:metadata"),
        ],
        [
            InlineKeyboardButton(
                f"📊 {F.sc('stats')}",
                callback_data="ga:s:stats"),
            InlineKeyboardButton(
                f"📋 {F.sc('view all')}",
                callback_data="ga:s:view"),
        ],
        [
            InlineKeyboardButton(
                f"♻️ {F.sc('reset all')}",
                callback_data="ga:s:reset"),
            InlineKeyboardButton(
                f"{F.EMO['refresh']} {F.sc('refresh')}",
                callback_data="ga:s:refresh"),
        ],
        [InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('close')}",
            callback_data="ga:close")],
    ]

    return "\n".join(text.split("\n")[:60]), _kb(rows)


# ============================================================
# SECTION 3 — SEARCH
# ============================================================

async def render_search(chat_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await S.get_config(chat_id)
    on_search = cfg.get("search_enabled", True)
    on_pm = cfg.get("pm_search_enabled", True)

    # Cooldown value
    try:
        cd = int((cfg.get("search") or {}).get("cooldown_seconds", 3) or 0)
    except (TypeError, ValueError):
        cd = 3
    cd = max(0, min(300, cd))

    cd_str = "OFF" if cd == 0 else f"{cd}s"

    text = "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"{F.EMO['search']} <b>{F.fb('SEARCH SETTINGS')}</b>",
        DIV, "",
        _line("🔎", "group search", _on(on_search)),
        _line("💬", "pm search", _on(on_pm)),
        _line("⏱️", "cooldown", cd_str),
        "",
        DIV_S,
        f"📌 {F.sc('pm search = answer text sent to bot pm')}",
        f"📌 {F.sc('cooldown = wait time between two searches')}",
        "",
        DIV_S, "",
        f"📊 {F.sc('top groups share an equal cooldown of')} "
        f"<b>3s</b>",
    ])

    # Cooldown preset row(s)
    cd_row1: List[InlineKeyboardButton] = []
    for n in (0, 1, 2, 3):
        mark = "✅ " if n == cd else ""
        label = "OFF" if n == 0 else f"{n}s"
        cd_row1.append(InlineKeyboardButton(
            f"{mark}{label}",
            callback_data=f"ga:cd:{n}",
        ))
    cd_row2: List[InlineKeyboardButton] = []
    for n in (5, 10, 20, 30):
        mark = "✅ " if n == cd else ""
        cd_row2.append(InlineKeyboardButton(
            f"{mark}{n}s",
            callback_data=f"ga:cd:{n}",
        ))

    rows = [
        [InlineKeyboardButton(
            f"🔎 {F.sc('group search')} · {'🟢' if on_search else '🔴'}",
            callback_data="ga:tog:search_enabled")],
        [InlineKeyboardButton(
            f"💬 {F.sc('pm search')} · {'🟢' if on_pm else '🔴'}",
            callback_data="ga:tog:pm_search_enabled")],
        [InlineKeyboardButton(
            f"⏱️ {F.sc('cooldown')} · {cd_str}",
            callback_data="ga:search_noop",
        )],
        cd_row1,
        cd_row2,
        _back_close("ga:back")[0],
    ]
    return "\n".join(text), _kb(rows)


# ============================================================
# SECTION 4 — CONTENT MODE
# ============================================================

async def render_content(chat_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await S.get_config(chat_id)
    mode = str(cfg.get("content_mode", "both"))

    def mark(v: str) -> str:
        return "✅ " if mode == v else ""

    text = "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"🎬 <b>{F.fb('CONTENT MODE')}</b>",
        DIV, "",
        f"📌 {F.sc('what users can search in this group')}",
        "",
        f"🎬 {F.sc('movies only')}",
        f"📺 {F.sc('series only')}",
        f"🎬📺 {F.sc('both')}",
        "",
        f"🎯 {F.sc('current')} · <b>{mode.upper()}</b>",
    ])

    rows = [
        [InlineKeyboardButton(
            f"{mark('movie')}🎬 {F.sc('movies only')}",
            callback_data="ga:set:content:movie")],
        [InlineKeyboardButton(
            f"{mark('series')}📺 {F.sc('series only')}",
            callback_data="ga:set:content:series")],
        [InlineKeyboardButton(
            f"{mark('both')}🎬📺 {F.sc('both')}",
            callback_data="ga:set:content:both")],
        _back_close("ga:back")[0],
    ]
    return "\n".join(text), _kb(rows)


# ============================================================
# SECTION 5 — FLOW (list of steps)
# ============================================================

_FLOW_STEPS = [
    ("base_search",   "🔎", "Search"),
    ("spell_check",   "🔤", "Spell Check"),
    ("suggestions",   "💡", "Suggestions"),
    ("language",      "🌍", "Language"),
    ("season",        "📺", "Season"),
    ("episode",       "🎞️", "Episode"),
    ("quality",       "🎯", "Quality"),
    ("file_delivery", "📤", "Delivery"),
]


# Default orders (mirrors movie/flow.py & series/flow.py)
_DEFAULT_MOVIE_ORDER = [
    "base_search", "spell_check", "suggestions",
    "quality", "file_delivery",
]
_DEFAULT_SERIES_ORDER = [
    "base_search", "spell_check", "suggestions",
    "language", "season", "episode", "quality", "file_delivery",
]


def _resolve_flow_order(
    cfg: Dict[str, Any],
    flow_type: str,
) -> List[str]:
    """
    Return the effective step order for this flow type.

    flow_type: "movie" | "series"
    """
    flow_order = cfg.get("flow_order") or {}
    custom = list(flow_order.get(flow_type) or [])

    default = (
        _DEFAULT_SERIES_ORDER if flow_type == "series"
        else _DEFAULT_MOVIE_ORDER
    )
    allowed = set(default)

    # Keep valid, dedup, drop unknown
    out: List[str] = []
    seen: set = set()
    for k in custom:
        if k in allowed and k not in seen:
            out.append(k)
            seen.add(k)

    # Append any missing defaults
    for k in default:
        if k not in seen:
            out.append(k)
            seen.add(k)

    return out


def _detect_flow_type(cfg: Dict[str, Any]) -> str:
    """Pick which flow type to show by default."""
    mode = str(cfg.get("content_mode", "both")).lower()
    if mode == "series":
        return "series"
    return "movie"  # movie or both → start with movie


async def render_flow(
    chat_id: int,
    flow_type: Optional[str] = None,
) -> Tuple[str, InlineKeyboardMarkup]:
    """
    Flow editor — reorder + configure steps.

    When the group is content_mode="both", a Movie/Series tab
    switcher appears at the top.
    """
    cfg = await S.get_config(chat_id)
    flow = cfg.get("flow") or {}
    mode = str(cfg.get("content_mode", "both")).lower()

    # Which flow are we editing?
    if flow_type not in ("movie", "series"):
        flow_type = _detect_flow_type(cfg)

    order = _resolve_flow_order(cfg, flow_type)
    flow_label = "MOVIE" if flow_type == "movie" else "SERIES"
    flow_icon = "🎬" if flow_type == "movie" else "📺"

    text_lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"🎯 <b>{F.fb('FLOW EDITOR')}</b>",
        DIV, "",
        f"📌 {F.sc('customize the search flow for this group')}",
        "",
    ]

    rows: List[List[InlineKeyboardButton]] = []

    # ── Movie/Series tab switcher (only for "both" groups) ──
    if mode == "both":
        rows.append([
            InlineKeyboardButton(
                f"{'✅ ' if flow_type == 'movie' else ''}"
                f"🎬 {F.sc('movie')}",
                callback_data="ga:flow_tab:movie",
            ),
            InlineKeyboardButton(
                f"{'✅ ' if flow_type == 'series' else ''}"
                f"📺 {F.sc('series')}",
                callback_data="ga:flow_tab:series",
            ),
        ])

    text_lines += [
        f"{flow_icon} <b>{F.sc(flow_label)} FLOW</b> · "
        f"<code>{len(order)}</code> {F.sc('steps')}",
        "",
        f"📌 {F.sc('tap a step to configure')}",
        f"📌 {F.sc('use ⬆️⬇️ to reorder')}",
        "",
    ]

    # ── Step rows with reorder arrows ──
    icon_map = {k: ic for k, ic, _ in _FLOW_STEPS}
    label_map = {k: lbl for k, _, lbl in _FLOW_STEPS}

    for i, key in enumerate(order):
        s = flow.get(key) or {}
        enabled = s.get("enabled", True)
        per_row = s.get("per_row", 2)
        marker = "🟢" if enabled else "🔴"
        icon = icon_map.get(key, "⚙️")
        label = label_map.get(key, key)

        # Truncate label so row fits
        short = label[:14]

        text_lines.append(
            f"{marker} <b>{i + 1:02d}.</b> {icon} "
            f"{F.sc(label)} · <code>{per_row}/row</code>"
        )

        # Row: [step button] [up] [down]
        step_btn = InlineKeyboardButton(
            f"{marker} {i + 1:02d}. {icon} {short}",
            callback_data=f"ga:flow:{key}",
        )
        if i > 0:
            up_btn = InlineKeyboardButton(
                "⬆️",
                callback_data=f"ga:flow_up:{flow_type}:{i}",
            )
        else:
            up_btn = InlineKeyboardButton(
                "·", callback_data="ga:flow_noop",
            )
        if i < len(order) - 1:
            down_btn = InlineKeyboardButton(
                "⬇️",
                callback_data=f"ga:flow_down:{flow_type}:{i}",
            )
        else:
            down_btn = InlineKeyboardButton(
                "·", callback_data="ga:flow_noop",
            )

        rows.append([step_btn, up_btn, down_btn])

    # Reset order button
    if (cfg.get("flow_order") or {}).get(flow_type):
        rows.append([InlineKeyboardButton(
            f"♻️ {F.sc('reset order')}",
            callback_data=f"ga:flow_rst_order:{flow_type}",
        )])

    rows.append(_back_close("ga:back")[0])
    return "\n".join(text_lines), _kb(rows)


async def render_flow_step(
    chat_id: int, step_key: str,
    flow_type: str = "movie",
) -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await S.get_config(chat_id)
    flow = cfg.get("flow") or {}
    s = flow.get(step_key) or {}

    labels = {k: lbl for k, _, lbl in _FLOW_STEPS}
    icons = {k: ic for k, ic, _ in _FLOW_STEPS}
    label = labels.get(step_key, step_key)
    icon = icons.get(step_key, "⚙️")

    enabled = s.get("enabled", True)
    per_row = int(s.get("per_row", 2))
    auto_skip = bool(s.get("auto_skip", True))

    text = "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"{icon} <b>{F.fb(label.upper())}</b>",
        DIV, "",
        _line("⚙️", "enabled", _on(enabled)),
        _line("📐", "layout", f"{per_row}/row"),
        _line("🔄", "auto-skip", _on(auto_skip)),
        "",
        DIV_S,
        f"📌 {F.sc('changes apply instantly')}",
    ])

    rows: List[List[InlineKeyboardButton]] = []

    rows.append([InlineKeyboardButton(
        f"{'🔴 ' + F.sc('disable') if enabled else '🟢 ' + F.sc('enable')}",
        callback_data=f"ga:flow_tog:{step_key}",
    )])

    layout_row: List[InlineKeyboardButton] = []
    for n in (1, 2, 3, 4):
        mark = "✅ " if per_row == n else ""
        layout_row.append(InlineKeyboardButton(
            f"{mark}{n}/row",
            callback_data=f"ga:flow_row:{step_key}:{n}",
        ))
    rows.append(layout_row)

        if step_key in ("language", "season", "episode", "quality"):
        rows.append([InlineKeyboardButton(
            f"🔄 {F.sc('auto-skip if one')} · {'🟢' if auto_skip else '🔴'}",
            callback_data=f"ga:flow_skip:{step_key}",
        )])

    # ✨ Advanced settings button — only if this step has any
    if step_key in (
        "spell_check", "suggestions", "file_delivery",
        "language", "season", "episode", "quality",
    ):
        rows.append([InlineKeyboardButton(
            f"⚙️ {F.sc('advanced settings')}",
            callback_data=f"ga:flow_adv:{step_key}",
        )])

    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data=f"ga:s:flow:{flow_type}",
        ),
        InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('close')}",
            callback_data="ga:close",
        ),
    ])
    return "\n".join(text), _kb(rows)

async def render_flow_step_advanced(
    chat_id: int, step_key: str,
    flow_type: str = "movie",
) -> Tuple[str, InlineKeyboardMarkup]:
    """
    Advanced settings for one flow step.

    Exposes every fine-grained knob the admin flow editor has:
      • spell_check      → threshold, max_corrections
      • suggestions      → min_score, provider, show_rating/year/icon
      • file_delivery    → sort_order, size_format, show_quality/name, name_max_len
      • language         → max_items
      • season           → max_items
      • episode          → max_items, per_page
      • quality          → max_items
    """
    cfg = await S.get_config(chat_id)
    flow = cfg.get("flow") or {}
    s = flow.get(step_key) or {}

    labels = {k: lbl for k, _, lbl in _FLOW_STEPS}
    icons = {k: ic for k, ic, _ in _FLOW_STEPS}
    label = labels.get(step_key, step_key)
    icon = icons.get(step_key, "⚙️")

    text_lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"{icon} <b>{F.fb(f'{label.upper()} · ADVANCED')}</b>",
        DIV, "",
        f"🏷️ {F.sc('type')} · <code>{step_key}</code>",
        "",
    ]

    rows: List[List[InlineKeyboardButton]] = []

    def _opt_row(
        field: str,
        options: List[Tuple[Any, str]],
        current: Any,
    ) -> List[InlineKeyboardButton]:
        r: List[InlineKeyboardButton] = []
        for value, lbl in options:
            mark = "✅ " if current == value else ""
            r.append(InlineKeyboardButton(
                f"{mark}{lbl}",
                callback_data=f"ga:flow_set:{step_key}:{field}:{value}",
            ))
        return r

    # ─────────────────────────────────────────────
    # SPELL CHECK
    # ─────────────────────────────────────────────
    if step_key == "spell_check":
        threshold = int(s.get("threshold", 82))
        max_corr = int(s.get("max_corrections", 1))

        text_lines += [
            f"🎯 {F.sc('match threshold')} · <b>{threshold}</b>",
            f"🔁 {F.sc('max corrections')} · <b>{max_corr}</b>",
            "",
            f"📌 {F.sc('higher threshold = stricter spelling')}",
            f"📌 {F.sc('82 recommended')}",
        ]

        rows.append([InlineKeyboardButton(
            f"🎯 {F.sc('threshold')}",
            callback_data="ga:flow_noop",
        )])
        row1: List[InlineKeyboardButton] = []
        for n in (60, 70, 75, 82):
            row1.append(InlineKeyboardButton(
                f"{'✅ ' if n == threshold else ''}{n}",
                callback_data=f"ga:flow_set:{step_key}:threshold:{n}",
            ))
        rows.append(row1)
        row2: List[InlineKeyboardButton] = []
        for n in (85, 90, 95):
            row2.append(InlineKeyboardButton(
                f"{'✅ ' if n == threshold else ''}{n}",
                callback_data=f"ga:flow_set:{step_key}:threshold:{n}",
            ))
        rows.append(row2)

        rows.append([InlineKeyboardButton(
            f"🔁 {F.sc('max corrections')}",
            callback_data="ga:flow_noop",
        )])
        rows.append(_opt_row(
            "max_corrections",
            [(1, "1"), (2, "2"), (3, "3")],
            max_corr,
        ))

    # ─────────────────────────────────────────────
    # SUGGESTIONS
    # ─────────────────────────────────────────────
    elif step_key == "suggestions":
        min_score = int(s.get("min_score", 45))
        provider = str(s.get("provider", "both"))
        show_rating = bool(s.get("show_rating", True))
        show_year = bool(s.get("show_year", True))
        show_icon = bool(s.get("show_icon", True))

        text_lines += [
            f"🎯 {F.sc('min match score')} · <b>{min_score}</b>",
            f"📡 {F.sc('provider')} · <b>{provider}</b>",
            f"⭐ {F.sc('show rating')} · {_on(show_rating)}",
            f"📅 {F.sc('show year')} · {_on(show_year)}",
            f"🎬 {F.sc('show icon')} · {_on(show_icon)}",
            "",
            f"📌 {F.sc('lower score = more suggestions')}",
            f"📌 {F.sc('45 recommended')}",
        ]

        rows.append([InlineKeyboardButton(
            f"🎯 {F.sc('min score')}",
            callback_data="ga:flow_noop",
        )])
        row1 = []
        for n in (30, 40, 45, 50):
            row1.append(InlineKeyboardButton(
                f"{'✅ ' if n == min_score else ''}{n}",
                callback_data=f"ga:flow_set:{step_key}:min_score:{n}",
            ))
        rows.append(row1)
        row2 = []
        for n in (60, 70, 80):
            row2.append(InlineKeyboardButton(
                f"{'✅ ' if n == min_score else ''}{n}",
                callback_data=f"ga:flow_set:{step_key}:min_score:{n}",
            ))
        rows.append(row2)

        rows.append([InlineKeyboardButton(
            f"📡 {F.sc('provider')}",
            callback_data="ga:flow_noop",
        )])
        rows.append([
            InlineKeyboardButton(
                f"{'✅ ' if provider == 'tmdb' else ''}TMDB",
                callback_data=f"ga:flow_set:{step_key}:provider:tmdb",
            ),
            InlineKeyboardButton(
                f"{'✅ ' if provider == 'imdb' else ''}IMDb",
                callback_data=f"ga:flow_set:{step_key}:provider:imdb",
            ),
            InlineKeyboardButton(
                f"{'✅ ' if provider == 'both' else ''}Both",
                callback_data=f"ga:flow_set:{step_key}:provider:both",
            ),
        ])

        rows.append([
            InlineKeyboardButton(
                f"⭐ {_on(show_rating)}",
                callback_data=f"ga:flow_togf:{step_key}:show_rating",
            ),
            InlineKeyboardButton(
                f"📅 {_on(show_year)}",
                callback_data=f"ga:flow_togf:{step_key}:show_year",
            ),
            InlineKeyboardButton(
                f"🎬 {_on(show_icon)}",
                callback_data=f"ga:flow_togf:{step_key}:show_icon",
            ),
        ])

    # ─────────────────────────────────────────────
    # FILE DELIVERY
    # ─────────────────────────────────────────────
    elif step_key == "file_delivery":
        sort_order = str(s.get("sort_order", "small_to_big"))
        size_fmt = str(s.get("size_format", "short"))
        show_quality = bool(s.get("show_quality", True))
        show_name = bool(s.get("show_name", True))
        name_len = int(s.get("name_max_len", 34))
        max_items = int(s.get("max_items", 15))

        text_lines += [
            f"📊 {F.sc('sort')} · <b>{sort_order}</b>",
            f"💾 {F.sc('size format')} · <b>{size_fmt}</b>",
            f"🎯 {F.sc('show quality')} · {_on(show_quality)}",
            f"📛 {F.sc('show name')} · {_on(show_name)}",
            f"📏 {F.sc('name max len')} · <b>{name_len}</b>",
            f"🔢 {F.sc('max files')} · <b>{max_items}</b>",
        ]

        rows.append([InlineKeyboardButton(
            f"📊 {F.sc('sort order')}",
            callback_data="ga:flow_noop",
        )])
        rows.append([
            InlineKeyboardButton(
                f"{'✅ ' if sort_order == 'small_to_big' else ''}📈 small→big",
                callback_data=f"ga:flow_set:{step_key}:sort_order:small_to_big",
            ),
            InlineKeyboardButton(
                f"{'✅ ' if sort_order == 'big_to_small' else ''}📉 big→small",
                callback_data=f"ga:flow_set:{step_key}:sort_order:big_to_small",
            ),
        ])

        rows.append([InlineKeyboardButton(
            f"💾 {F.sc('size format')}",
            callback_data="ga:flow_noop",
        )])
        rows.append([
            InlineKeyboardButton(
                f"{'✅ ' if size_fmt == 'short' else ''}short (1.4G)",
                callback_data=f"ga:flow_set:{step_key}:size_format:short",
            ),
            InlineKeyboardButton(
                f"{'✅ ' if size_fmt == 'full' else ''}full (1.4 GB)",
                callback_data=f"ga:flow_set:{step_key}:size_format:full",
            ),
        ])

        rows.append([
            InlineKeyboardButton(
                f"🎯 {_on(show_quality)}",
                callback_data=f"ga:flow_togf:{step_key}:show_quality",
            ),
            InlineKeyboardButton(
                f"📛 {_on(show_name)}",
                callback_data=f"ga:flow_togf:{step_key}:show_name",
            ),
        ])

        rows.append([InlineKeyboardButton(
            f"📏 {F.sc('name max length')}",
            callback_data="ga:flow_noop",
        )])
        lrow1 = []
        for n in (20, 25, 30):
            lrow1.append(InlineKeyboardButton(
                f"{'✅ ' if n == name_len else ''}{n}",
                callback_data=f"ga:flow_set:{step_key}:name_max_len:{n}",
            ))
        rows.append(lrow1)
        lrow2 = []
        for n in (34, 40, 50):
            lrow2.append(InlineKeyboardButton(
                f"{'✅ ' if n == name_len else ''}{n}",
                callback_data=f"ga:flow_set:{step_key}:name_max_len:{n}",
            ))
        rows.append(lrow2)

        rows.append([InlineKeyboardButton(
            f"🔢 {F.sc('max files per search')}",
            callback_data="ga:flow_noop",
        )])
        mrow1 = []
        for n in (5, 10, 15):
            mrow1.append(InlineKeyboardButton(
                f"{'✅ ' if n == max_items else ''}{n}",
                callback_data=f"ga:flow_set:{step_key}:max_items:{n}",
            ))
        rows.append(mrow1)
        mrow2 = []
        for n in (20, 25, 30):
            mrow2.append(InlineKeyboardButton(
                f"{'✅ ' if n == max_items else ''}{n}",
                callback_data=f"ga:flow_set:{step_key}:max_items:{n}",
            ))
        rows.append(mrow2)

    # ─────────────────────────────────────────────
    # WIZARD STEPS (language / season / episode / quality)
    # ─────────────────────────────────────────────
    elif step_key in ("language", "season", "episode", "quality"):
        max_items = int(s.get("max_items", 12))
        per_page = int(s.get("per_page", 10)) if step_key == "episode" else None

        text_lines += [
            f"🔢 {F.sc('max items')} · <b>{max_items}</b>",
        ]
        if per_page is not None:
            text_lines.append(f"📄 {F.sc('per page')} · <b>{per_page}</b>")

        # max_items options depend on step
        item_opts_map = {
            "language": [3, 5, 8, 12, 15, 20],
            "season":   [5, 10, 12, 15, 20, 30],
            "episode":  [10, 20, 30, 50, 75, 100],
            "quality":  [3, 5, 8, 10, 12, 15],
        }
        opts = item_opts_map.get(step_key, [5, 10, 15, 20, 25, 30])

        rows.append([InlineKeyboardButton(
            f"🔢 {F.sc('max items')}",
            callback_data="ga:flow_noop",
        )])
        irow1 = []
        for n in opts[:3]:
            irow1.append(InlineKeyboardButton(
                f"{'✅ ' if n == max_items else ''}{n}",
                callback_data=f"ga:flow_set:{step_key}:max_items:{n}",
            ))
        rows.append(irow1)
        irow2 = []
        for n in opts[3:]:
            irow2.append(InlineKeyboardButton(
                f"{'✅ ' if n == max_items else ''}{n}",
                callback_data=f"ga:flow_set:{step_key}:max_items:{n}",
            ))
        rows.append(irow2)

        if per_page is not None:
            rows.append([InlineKeyboardButton(
                f"📄 {F.sc('episodes per page')}",
                callback_data="ga:flow_noop",
            )])
            prow = []
            for n in (5, 10, 15, 20):
                prow.append(InlineKeyboardButton(
                    f"{'✅ ' if n == per_page else ''}{n}",
                    callback_data=f"ga:flow_set:{step_key}:per_page:{n}",
                ))
            rows.append(prow)

    # ─────────────────────────────────────────────
    # NO ADVANCED OPTIONS
    # ─────────────────────────────────────────────
    else:
        text_lines.append(
            f"⚪ {F.sc('no advanced settings for this step')}"
        )

    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data=f"ga:flow:{flow_type}:{step_key}",
        ),
        InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('close')}",
            callback_data="ga:close",
        ),
    ])
    return "\n".join(text_lines), _kb(rows)

# ============================================================
# SECTION 6 — CAPTION
# ============================================================

async def render_caption(chat_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await S.get_config(chat_id)
    tpl = cfg.get("caption_template")
    has = bool(tpl)

    text_lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"📝 <b>{F.fb('CAPTION TEMPLATE')}</b>",
        DIV, "",
        f"📌 {F.sc('per-group caption for delivered files')}",
        "",
        f"🎯 {F.sc('status')} · "
        f"{'🟢 custom' if has else '⚪ global'}",
    ]
    if has:
        text_lines += ["", f"<code>{F.sc(str(tpl)[:400])}</code>"]

    text_lines += [
        "",
        DIV_S,
        f"📌 {F.sc('variables')}:",
        "<code>{title}</code> <code>{year}</code>",
        "<code>{quality}</code> <code>{codec}</code>",
        "<code>{audio}</code> <code>{subtitle}</code>",
        "<code>{size}</code> <code>{season}</code>",
        "<code>{episode}</code> <code>{bot_username}</code>",
    ]

    rows = [[InlineKeyboardButton(
        f"✏️ {F.sc('edit caption')}",
        callback_data="ga:cap:edit",
    )]]
    if has:
        rows.append([InlineKeyboardButton(
            f"👁️ {F.sc('preview')}",
            callback_data="ga:cap:preview",
        )])
        rows.append([InlineKeyboardButton(
            f"♻️ {F.sc('reset to global')}",
            callback_data="ga:cap:reset",
        )])
    rows.append(_back_close("ga:back")[0])
    return "\n".join(text_lines), _kb(rows)


async def render_caption_preview(chat_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await S.get_config(chat_id)
    tpl = cfg.get("caption_template") or ""

    sample = {
        "title": "Karnan", "year": "2021",
        "quality": "1080P", "codec": "HEVC",
        "audio": "Tamil", "subtitle": "English",
        "size": "1.4 GB", "season": "", "episode": "",
        "bot_username": "examplebot",
        "bot_link": "https://t.me/examplebot",
    }
    try:
        rendered = tpl.format(**sample)
    except Exception as e:
        rendered = f"(error: {e})\n\n{tpl}"

    text = "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"👁️ <b>{F.fb('CAPTION PREVIEW')}</b>",
        DIV, "",
        rendered,
    ])

    rows = [[
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data="ga:s:caption",
        ),
        InlineKeyboardButton(
            f"{F.EMO['cross']} {F.sc('close')}",
            callback_data="ga:close",
        ),
    ]]
    return "\n".join(text)[:4000], _kb(rows)


# ============================================================
# SECTION 7 — BUTTONS
# ============================================================

async def render_buttons(chat_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await S.get_config(chat_id)
    btns = cfg.get("result_buttons") or []
    per_row = int(cfg.get("buttons_per_row", 2))

    text_lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"🔘 <b>{F.fb('RESULT BUTTONS')}</b>",
        DIV, "",
        f"📊 {F.sc('total')} · <b>{len(btns)}</b>",
        f"📐 {F.sc('per row')} · <b>{per_row}</b>",
        "",
    ]

    rows: List[List[InlineKeyboardButton]] = []

    for i, b in enumerate(btns, 1):
        enabled = b.get("enabled", True)
        marker = "🟢" if enabled else "🔴"
        name = str(b.get("name", "?"))[:36]
        text_lines.append(f"<b>{i:02d}.</b> {marker} {F.sc(name)}")

        rows.append([InlineKeyboardButton(
            f"{marker} {i}. {name[:26]}",
            callback_data=f"ga:btn:view:{i - 1}",
        )])

    rows.append([InlineKeyboardButton(
        f"➕ {F.sc('add button')}",
        callback_data="ga:btn:add",
    )])

    per_row_row: List[InlineKeyboardButton] = []
    for n in (1, 2, 3):
        mark = "✅ " if per_row == n else ""
        per_row_row.append(InlineKeyboardButton(
            f"{mark}{n}/row",
            callback_data=f"ga:btn_row:{n}",
        ))
    rows.append(per_row_row)

    rows.append(_back_close("ga:back")[0])
    return "\n".join(text_lines), _kb(rows)


async def render_button_view(
    chat_id: int, idx: int,
) -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await S.get_config(chat_id)
    btns = cfg.get("result_buttons") or []

    if idx < 0 or idx >= len(btns):
        return await render_buttons(chat_id)

    b = btns[idx]
    enabled = b.get("enabled", True)

    text = "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"🔘 <b>{F.fb('BUTTON DETAIL')}</b>",
        DIV, "",
        _line("📛", "name", F.sc(str(b.get("name", "?"))[:60])),
        f"🔗 {F.sc('url')} · <code>{str(b.get('url', '?'))[:60]}</code>",
        _line("⚙️", "status", _on(enabled)),
    ])

    rows = [
        [InlineKeyboardButton(
            f"{'🔴 ' + F.sc('disable') if enabled else '🟢 ' + F.sc('enable')}",
            callback_data=f"ga:btn:tog:{idx}",
        )],
        [InlineKeyboardButton(
            f"🗑️ {F.sc('delete')}",
            callback_data=f"ga:btn:del:{idx}",
        )],
        _back_close("ga:s:buttons")[0],
    ]
    return "\n".join(text), _kb(rows)


# ============================================================
# SECTION 8 — WELCOME
# ============================================================

async def render_welcome(chat_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await S.get_config(chat_id)
    w_on = cfg.get("welcome_enabled", False)
    w_text = cfg.get("welcome_text")
    ad_on = cfg.get("welcome_auto_delete", True)
    ad_secs = int(cfg.get("welcome_delete_after", 600))

    text_lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"👋 <b>{F.fb('WELCOME MESSAGE')}</b>",
        DIV, "",
        _line("📢", "enabled", _on(w_on)),
        _line("⏱️", "auto-delete", _on(ad_on)),
        _line("⏳", "delete after", f"{ad_secs}s"),
    ]
    if w_text:
        text_lines += [
            "",
            f"📝 {F.sc('current')}:",
            f"<code>{F.sc(str(w_text)[:300])}</code>",
        ]

    rows = [
        [InlineKeyboardButton(
            f"{'🔴 ' + F.sc('disable') if w_on else '🟢 ' + F.sc('enable')}",
            callback_data="ga:w_tog",
        )],
        [InlineKeyboardButton(
            f"✏️ {F.sc('edit text')}",
            callback_data="ga:w_edit",
        )],
        [InlineKeyboardButton(
            f"⏱️ {F.sc('auto-delete')} · {'🟢' if ad_on else '🔴'}",
            callback_data="ga:w_adtog",
        )],
        _back_close("ga:back")[0],
    ]
    return "\n".join(text_lines), _kb(rows)


# ============================================================
# SECTION 9 — AUTO-DELETE
# ============================================================

async def render_autodel(chat_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await S.get_config(chat_id)
    ad = cfg.get("auto_delete") or {}

    bot_on = ad.get("bot_messages", True)
    bot_timer = int(ad.get("bot_timer", 600))
    user_on = ad.get("user_messages", True)
    keep_n = int(ad.get("keep_last_n", 10))
    cmd_on = ad.get("command_messages", True)

    text = "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"⏱️ <b>{F.fb('AUTO-DELETE')}</b>",
        DIV, "",
        _line("🤖", "bot messages", _on(bot_on)),
        _line("⏳", "bot timer", f"{bot_timer}s"),
        _line("👤", "user messages", _on(user_on)),
        _line("🔢", "keep last", keep_n),
        _line("⌨️", "command messages", _on(cmd_on)),
        "",
        DIV_S,
        f"📌 {F.sc('bot = delete our sent files/messages')}",
        f"📌 {F.sc('user = clean up user messages')}",
    ])

    rows: List[List[InlineKeyboardButton]] = [
        [InlineKeyboardButton(
            f"🤖 {F.sc('bot messages')} · {'🟢' if bot_on else '🔴'}",
            callback_data="ga:ad_tog:bot_messages")],
    ]

    timer_row: List[InlineKeyboardButton] = []
    for secs, label in [(60, "1m"), (300, "5m"), (600, "10m"),
                        (1800, "30m"), (3600, "1h"), (0, "OFF")]:
        mark = "✅ " if bot_timer == secs else ""
        timer_row.append(InlineKeyboardButton(
            f"{mark}{label}",
            callback_data=f"ga:ad_timer:{secs}",
        ))
    rows.append(timer_row)

    rows.append([InlineKeyboardButton(
        f"👤 {F.sc('user messages')} · {'🟢' if user_on else '🔴'}",
        callback_data="ga:ad_tog:user_messages")])

    keep_row: List[InlineKeyboardButton] = []
    for n in (5, 10, 20, 50):
        mark = "✅ " if keep_n == n else ""
        keep_row.append(InlineKeyboardButton(
            f"{mark}{n}",
            callback_data=f"ga:ad_keep:{n}",
        ))
    rows.append(keep_row)

    rows.append([InlineKeyboardButton(
        f"⌨️ {F.sc('command messages')} · {'🟢' if cmd_on else '🔴'}",
        callback_data="ga:ad_tog:command_messages")])

    rows.append(_back_close("ga:back")[0])
    return "\n".join(text), _kb(rows)


# ============================================================
# SECTION 10 — FILTERS
# ============================================================

async def render_filters(chat_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await S.get_config(chat_id)
    filt = cfg.get("filters") or {}

    bl_on = filt.get("banned_links", True)
    bf_on = filt.get("block_forward", False)
    bm_on = filt.get("block_media", False)
    words = filt.get("banned_words") or []

    text = "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"🚫 <b>{F.fb('FILTERS')}</b>",
        DIV, "",
        _line("🔗", "block links", _on(bl_on)),
        _line("➡️", "block forwards", _on(bf_on)),
        _line("📎", "block media", _on(bm_on)),
        _line("🔤", "banned words", f"{len(words)}"),
    ])

    rows = [
        [
            InlineKeyboardButton(
                f"🔗 {F.sc('links')} · {'🟢' if bl_on else '🔴'}",
                callback_data="ga:flt_tog:banned_links"),
            InlineKeyboardButton(
                f"➡️ {F.sc('forwards')} · {'🟢' if bf_on else '🔴'}",
                callback_data="ga:flt_tog:block_forward"),
        ],
        [InlineKeyboardButton(
            f"📎 {F.sc('media')} · {'🟢' if bm_on else '🔴'}",
            callback_data="ga:flt_tog:block_media")],
        [InlineKeyboardButton(
            f"🔤 {F.sc('banned words')} ({len(words)})",
            callback_data="ga:flt_words")],
        [InlineKeyboardButton(
            f"➕ {F.sc('add word')}",
            callback_data="ga:flt_add")],
        _back_close("ga:back")[0],
    ]
    return "\n".join(text), _kb(rows)


# ============================================================
# SECTION 11 — FORCE-SUB
# ============================================================

async def render_fsub(chat_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await S.get_config(chat_id)
    f = cfg.get("fsub") or {}
    enabled = f.get("enabled", False)
    channels = f.get("channels") or []

    text_lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"📢 <b>{F.fb('FORCE SUBSCRIPTION')}</b>",
        DIV, "",
        _line("⚙️", "enabled", _on(enabled)),
        _line("📊", "channels", f"{len(channels)}"),
        "",
    ]
    for c in channels[:8]:
        text_lines.append(f"• <code>{c}</code>")

    rows = [
        [InlineKeyboardButton(
            f"{'🔴 ' + F.sc('disable') if enabled else '🟢 ' + F.sc('enable')}",
            callback_data="ga:fs_tog")],
        [InlineKeyboardButton(
            f"➕ {F.sc('add channel')}",
            callback_data="ga:fs_add")],
    ]

    if channels:
        for i, c in enumerate(channels[:5]):
            rows.append([InlineKeyboardButton(
                f"🗑️ {str(c)[:40]}",
                callback_data=f"ga:fs_rm:{i}",
            )])

    rows.append(_back_close("ga:back")[0])
    return "\n".join(text_lines), _kb(rows)


# ============================================================
# SECTION 12 — VERIFY
# ============================================================

async def render_verify(chat_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await S.get_config(chat_id)
    v = cfg.get("verify") or {}
    enabled = v.get("enabled", False)
    shortener = v.get("shortener_url")
    vtime = int(v.get("verify_time", 1200))

    text = "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"🔐 <b>{F.fb('VERIFICATION')}</b>",
        DIV, "",
        _line("⚙️", "enabled", _on(enabled)),
        f"🔗 {F.sc('shortener')} · "
        f"<code>{shortener or 'not set'}</code>",
        _line("⏱️", "verify time", f"{vtime}s"),
    ])

    rows = [
        [InlineKeyboardButton(
            f"{'🔴 ' + F.sc('disable') if enabled else '🟢 ' + F.sc('enable')}",
            callback_data="ga:v_tog")],
        [InlineKeyboardButton(
            f"🔗 {F.sc('set shortener')}",
            callback_data="ga:v_url")],
        [InlineKeyboardButton(
            f"⏱️ {F.sc('verify time')}",
            callback_data="ga:v_time")],
        _back_close("ga:back")[0],
    ]
    return "\n".join(text), _kb(rows)


# ============================================================
# SECTION 13 — SECURITY
# ============================================================

async def render_security(chat_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await S.get_config(chat_id)
    sec = cfg.get("security") or {}

    url_on = sec.get("url_blocking", True)
    tg_on = sec.get("telegram_links", True)
    ab_on = sec.get("admin_bypass", True)
    fc_on = sec.get("search_flood_control", True)
    lim = int(sec.get("search_limit", 5))

    text = "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"🛡️ <b>{F.fb('SECURITY')}</b>",
        DIV, "",
        _line("🌐", "url blocking", _on(url_on)),
        _line("🔗", "telegram links", _on(tg_on)),
        _line("👑", "admin bypass", _on(ab_on)),
        _line("⚠️", "flood control", _on(fc_on)),
        _line("📊", "search limit", f"{lim}/min"),
    ])

    rows = [
        [
            InlineKeyboardButton(
                f"🌐 {F.sc('urls')} · {'🟢' if url_on else '🔴'}",
                callback_data="ga:sec:url_blocking"),
            InlineKeyboardButton(
                f"🔗 {F.sc('tg links')} · {'🟢' if tg_on else '🔴'}",
                callback_data="ga:sec:telegram_links"),
        ],
        [InlineKeyboardButton(
            f"👑 {F.sc('admin bypass')} · {'🟢' if ab_on else '🔴'}",
            callback_data="ga:sec:admin_bypass")],
        [InlineKeyboardButton(
            f"⚠️ {F.sc('flood control')} · {'🟢' if fc_on else '🔴'}",
            callback_data="ga:sec:search_flood_control")],
        _back_close("ga:back")[0],
    ]
    return "\n".join(text), _kb(rows)


# ============================================================
# SECTION 14 — REQUESTS
# ============================================================

async def render_requests(chat_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await S.get_config(chat_id)
    r = cfg.get("requests") or {}

    en = r.get("enabled", True)
    pm_upd = r.get("user_pm_update", True)
    dup = r.get("duplicate_check", True)
    ch = r.get("channel")

    text = "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"📝 <b>{F.fb('REQUESTS')}</b>",
        DIV, "",
        _line("⚙️", "enabled", _on(en)),
        _line("💬", "pm update", _on(pm_upd)),
        _line("🔁", "dup check", _on(dup)),
        f"📢 {F.sc('channel')} · <code>{ch or 'global'}</code>",
    ])

    rows = [
        [InlineKeyboardButton(
            f"⚙️ {F.sc('enabled')} · {'🟢' if en else '🔴'}",
            callback_data="ga:req_tog:enabled")],
        [
            InlineKeyboardButton(
                f"💬 {F.sc('pm update')} · {'🟢' if pm_upd else '🔴'}",
                callback_data="ga:req_tog:user_pm_update"),
            InlineKeyboardButton(
                f"🔁 {F.sc('dup check')} · {'🟢' if dup else '🔴'}",
                callback_data="ga:req_tog:duplicate_check"),
        ],
        [InlineKeyboardButton(
            f"📢 {F.sc('set channel')}",
            callback_data="ga:req_ch")],
        _back_close("ga:back")[0],
    ]
    return "\n".join(text), _kb(rows)


# ============================================================
# SECTION 15 — METADATA
# ============================================================

async def render_metadata(chat_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await S.get_config(chat_id)
    m = cfg.get("metadata") or {}

    fields = [
        ("poster", "🖼️", "Poster"),
        ("rating", "⭐", "Rating"),
        ("genre", "🎭", "Genre"),
        ("year", "📅", "Year"),
        ("language", "🌐", "Language"),
    ]

    text_lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"🎬 <b>{F.fb('METADATA DISPLAY')}</b>",
        DIV, "",
        f"📌 {F.sc('what to show with search results')}",
        "",
    ]

    for key, icon, label in fields:
        v = m.get(key, True)
        text_lines.append(f"{icon} {F.sc(label)} · {_on(v)}")

    rows: List[List[InlineKeyboardButton]] = []
    for key, icon, label in fields:
        v = m.get(key, True)
        rows.append([InlineKeyboardButton(
            f"{icon} {label} · {'🟢' if v else '🔴'}",
            callback_data=f"ga:meta_tog:{key}",
        )])

    rows.append(_back_close("ga:back")[0])
    return "\n".join(text_lines), _kb(rows)


# ============================================================
# SECTION 16 — STATS
# ============================================================

async def render_stats(chat_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await S.get_config(chat_id)
    st = cfg.get("stats") or {}

    def _i(k: str) -> int:
        try:
            return int(st.get(k, 0) or 0)
        except (TypeError, ValueError):
            return 0

    searches = _i("searches_today")
    found = _i("results_found")
    notfound = _i("not_found")
    sent = _i("files_sent")

    if searches > 0:
        rate = (found / searches) * 100
        rate_str = f"{rate:.1f}%"
    else:
        rate_str = "—"

    # Last updated timestamp
    updated = st.get("updated_at")
    if updated is not None:
        try:
            if hasattr(updated, "strftime"):
                updated_str = updated.strftime("%d %b %Y · %H:%M")
            else:
                updated_str = str(updated)[:19]
        except Exception:
            updated_str = "—"
    else:
        updated_str = "—"

    sugg_shown = _i("suggestions_shown")
    sugg_clicked = _i("suggestions_clicked")
    sugg_led = _i("suggestions_led_to_files")
    reqs = _i("requests_sent")

    text = "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"📊 <b>{F.fb('GROUP STATS')}</b>",
        DIV, "",
        f"👥 <b>{F.sc(str(cfg.get('title') or chat_id)[:50])}</b>",
        f"🆔 <code>{chat_id}</code>",
        "",
        DIV_S, "",
        _line("🔎", "searches today", FM.num(searches)),
        _line("✅", "results found", FM.num(found)),
        _line("❌", "not found", FM.num(notfound)),
        _line("📤", "files sent", FM.num(sent)),
        "",
        DIV_S,
        _line("💡", "suggestions shown", FM.num(sugg_shown)),
        _line("👆", "suggestions clicked", FM.num(sugg_clicked)),
        _line("🎯", "sugg → files", FM.num(sugg_led)),
        _line("📩", "requests sent", FM.num(reqs)),
        "",
        DIV_S, "",
        f"📈 {F.sc('success rate')} · <b>{rate_str}</b>",
        f"🕒 {F.sc('last updated')} · <code>{updated_str}</code>",
        "",
        DIV_S,
        f"📌 {F.sc('counters reset when you tap')} "
        f"<b>{F.sc('reset stats')}</b>",
    ])
    rows = [
        [InlineKeyboardButton(
            f"🔄 {F.sc('refresh')}",
            callback_data="ga:s:stats")],
        [InlineKeyboardButton(
            f"🗑️ {F.sc('reset stats')}",
            callback_data="ga:stats_reset")],
        _back_close("ga:back")[0],
    ]
    return "\n".join(text), _kb(rows)


# ============================================================
# SECTION 17 — VIEW ALL
# ============================================================

async def render_view(chat_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await S.get_config(chat_id)

    ad = cfg.get("auto_delete") or {}
    fsub = cfg.get("fsub") or {}
    filt = cfg.get("filters") or {}
    ver = cfg.get("verify") or {}

    text = "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"📋 <b>{F.fb('ALL SETTINGS')}</b>",
        DIV, "",
        _line("🎬", "content", str(cfg.get("content_mode", "both")).upper()),
        _line("🔎", "search", _on(cfg.get("search_enabled", True))),
        _line("💬", "pm search", _on(cfg.get("pm_search_enabled", True))),
        _line("👋", "welcome", _on(cfg.get("welcome_enabled", False))),
        _line("⏱️", "auto-delete", f"{ad.get('bot_timer', 600)}s"),
        _line("🔢", "keep last", ad.get("keep_last_n", 10)),
        _line("📢", "fsub", f"{len(fsub.get('channels') or [])}"),
        _line("📝", "caption",
              "custom" if cfg.get("caption_template") else "global"),
        _line("🔘", "buttons", f"{len(cfg.get('result_buttons') or [])}"),
        _line("🚫", "banned words",
              f"{len(filt.get('banned_words') or [])}"),
        _line("🔐", "verify", _on(ver.get("enabled", False))),
        "",
        DIV_S,
        _line("🔎", "searches today",
              FM.num((cfg.get("stats") or {}).get("searches_today", 0))),
        _line("📤", "files sent",
              FM.num((cfg.get("stats") or {}).get("files_sent", 0))),
    ])

    rows = [_back_close("ga:back")[0]]
    return "\n".join(text), _kb(rows)


# ============================================================
# SECTION 18 — RESET (confirm)
# ============================================================

async def render_reset(chat_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    text = "\n".join([
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"♻️ <b>{F.fb('RESET ALL SETTINGS')}</b>",
        DIV, "",
        f"{F.EMO['warn']} {F.sc('this will restore all defaults')}",
        "",
        f"📌 {F.sc('title + username are kept')}",
        f"📌 {F.sc('everything else is reset')}",
    ])

    rows = [
        [InlineKeyboardButton(
            f"♻️ {F.sc('yes, reset all')}",
            callback_data="ga:reset_do")],
        [InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('cancel')}",
            callback_data="ga:back")],
    ]
    return "\n".join(text), _kb(rows)


# ============================================================
# SECTION 19 — WORDS LIST (helpers panel)
# ============================================================

async def render_words_list(chat_id: int) -> Tuple[str, InlineKeyboardMarkup]:
    cfg = await S.get_config(chat_id)
    words = ((cfg.get("filters") or {}).get("banned_words") or [])

    text_lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"🔤 <b>{F.fb('BANNED WORDS')}</b>",
        DIV, "",
    ]
    if not words:
        text_lines.append(f"⚪ {F.sc('no words yet')}")
    else:
        for i, w in enumerate(words, 1):
            text_lines.append(f"<b>{i:02d}.</b> <code>{w}</code>")

    rows = [
        [InlineKeyboardButton(
            f"🗑️ {F.sc('clear all')}",
            callback_data="ga:flt_clear")],
        [InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data="ga:s:filters")],
    ]
    return "\n".join(text_lines), _kb(rows)


# ============================================================
# SECTION 20 — PUBLIC EXPORTS
# ============================================================

__all__ = [
    "render_main",
    "render_search",
    "render_content",
    "render_flow", "render_flow_step",
    "render_flow_step_advanced"
    "render_caption", "render_caption_preview",
    "render_buttons", "render_button_view",
    "render_welcome",
    "render_autodel",
    "render_filters", "render_words_list",
    "render_fsub",
    "render_verify",
    "render_security",
    "render_requests",
    "render_metadata",
    "render_stats",
    "render_view",
    "render_reset",
]
