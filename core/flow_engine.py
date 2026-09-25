# ============================================================
# 🏨 DOWNTOWN VILLA — FLOW ENGINE (FUTURISTIC) — PART A/4
# ============================================================
#
# Universal step-based flow engine.
#
# WHY THIS EXISTS:
#   The old bot had flow logic hardcoded in 4+ places:
#     • group_search.py
#     • series_group.py
#     • handlers.py (PM)
#     • premium_watch.py
#
#   Every flow had its own "what comes next" logic.
#   Changing the order = editing code = deploy = risk.
#
# NEW DESIGN:
#   Every flow is a list of STEPS.
#   Every step is a MODULE with a known interface.
#   Every step is fully configurable from Telegram:
#     • ON / OFF
#     • Order (drag up / down)
#     • Layout (1 / 2 / 3 per row)
#     • Auto-skip rules
#     • Custom label
#     • Cancel button (always visible)
#
#   Adding a new step = drop a file in core/steps/
#   Removing a step   = toggle OFF from Telegram
#   Changing order    = drag from Telegram
#
# NO CODE CHANGES EVER after deploy.
#
# PART A: Core data structures + registries
# PART B: Config storage + flow builder
# PART C: Runtime engine (execute, advance, cancel)
# PART D: Telegram editor UI
#
# ============================================================

from __future__ import annotations

import logging
import time
import uuid
from dataclasses import dataclass, field, asdict
from typing import (
    Any, Awaitable, Callable, Dict, List, Optional,
    Tuple, Type,
)

from pyrogram import Client
from pyrogram.types import CallbackQuery, Message

logger = logging.getLogger(__name__)


# ============================================================
# SECTION 1 — STEP INTERFACE CONTRACT
# ============================================================
#
# Every step is a Python class that implements this contract.
# The engine does NOT know what a "language" or "quality" is —
# it just calls these methods.
#
# Required methods:
#   render(ctx)     → returns (text, keyboard) or None to auto-skip
#   on_input(ctx)   → handles user callback input; returns next action
#
# Optional overrides:
#   should_skip(ctx)
#   default_config()
#   validate_config(cfg)
#
# ============================================================

@dataclass
class StepContext:
    """
    Everything a step needs to render itself + process input.

    Passed through every step. Steps ADD to `data`, never overwrite.
    """
    # Who
    user_id: int
    chat_id: int
    is_group: bool = False

    # Where we are
    run_id: str = ""
    flow_name: str = ""
    step_index: int = 0
    step_type: str = ""

    # Accumulated state
    data: Dict[str, Any] = field(default_factory=dict)

    # Config for the CURRENT step
    step_cfg: Dict[str, Any] = field(default_factory=dict)

    # Full flow config (in case step wants neighbours)
    flow_cfg: Dict[str, Any] = field(default_factory=dict)

    # Live session reference (set by engine)
    session: Any = None

    # Client reference (set by engine)
    client: Optional[Client] = None

    # Original message (if any)
    message: Optional[Message] = None

    # Original callback (if any)
    callback: Optional[CallbackQuery] = None

    # Debug flag — when True, no side effects
    dry_run: bool = False

    # Free-form scratchpad (per-step)
    scratch: Dict[str, Any] = field(default_factory=dict)


@dataclass
class StepResult:
    """
    What a step returns after handling input.

    action:
      "next"     → go to next step
      "back"     → go to previous step
      "cancel"   → cancel the entire flow
      "stay"     → re-render same step
      "done"     → flow finished successfully
      "jump"     → jump to step_index in `jump_to`
      "repeat"   → re-render but with new config (rare)
    """
    action: str
    data: Dict[str, Any] = field(default_factory=dict)
    jump_to: Optional[int] = None
    message: Optional[str] = None
    extra: Dict[str, Any] = field(default_factory=dict)


@dataclass
class RenderResult:
    """
    What a step returns when it's time to show UI.

    If `text` is None → step wants to auto-skip.
    """
    text: Optional[str] = None
    keyboard: Any = None
    auto_skip: bool = False
    data: Dict[str, Any] = field(default_factory=dict)


# Type aliases for the contract
StepRenderFn = Callable[[StepContext], Awaitable[RenderResult]]
StepInputFn = Callable[[StepContext, Any], Awaitable[StepResult]]


# ============================================================
# SECTION 2 — STEP BASE CLASS
# ============================================================

class BaseStep:
    """
    Base class for every step.

    Subclass this, implement render() and on_input().
    """
    # Unique identifier (e.g., "language", "quality")
    type_name: str = "base"

    # Human-readable name for admin UI
    display_name: str = "Base Step"

    # Emoji for admin UI
    icon: str = "⚙️"

    # Short help text
    help_text: str = "Base step — override me"

    # Set True if step is mandatory (cannot be disabled)
    mandatory: bool = False

    # Set True if step must run in the initial visible order
    # (used only for defaults)
    default_enabled: bool = True

    # Default position when a flow is created (lower = earlier)
    default_order: int = 100

    async def render(self, ctx: StepContext) -> RenderResult:
        """
        Return the UI for this step.
        Return RenderResult(auto_skip=True) to skip silently.
        """
        return RenderResult(
            text="(empty step)",
            keyboard=None,
            auto_skip=True,
        )

    async def on_input(self, ctx: StepContext, value: Any) -> StepResult:
        """
        Handle user input for this step.
        Must return a StepResult.
        """
        return StepResult(action="next")

    def should_skip(self, ctx: StepContext) -> bool:
        """Optional: return True to skip step without rendering."""
        return False

    @classmethod
    def default_config(cls) -> Dict[str, Any]:
        """Return the default config dict for this step type."""
        return {
            "type": cls.type_name,
            "enabled": cls.default_enabled,
            "order": cls.default_order,
            "per_row": 2,
            "max_items": 10,
            "auto_skip_if_one": True,
            "cancel_enabled": True,
            "back_enabled": True,
            "label": cls.display_name,
            "icons": {},
            "custom": {},
        }

    @classmethod
    def validate_config(cls, cfg: Dict[str, Any]) -> List[str]:
        """Return list of validation errors (empty = OK)."""
        errors: List[str] = []
        if "type" not in cfg:
            errors.append("missing 'type'")
        if cfg.get("per_row", 2) not in (1, 2, 3):
            errors.append("per_row must be 1, 2, or 3")
        if cfg.get("max_items", 10) < 1:
            errors.append("max_items must be >= 1")
        return errors


# ============================================================
# SECTION 3 — STEP REGISTRY
# ============================================================

_step_registry: Dict[str, Type[BaseStep]] = {}
_step_instances: Dict[str, BaseStep] = {}


def register_step(cls: Type[BaseStep]) -> Type[BaseStep]:
    """
    Class decorator — registers a step with the engine.

    Usage:
        @register_step
        class LanguageStep(BaseStep):
            type_name = "language"
            ...
    """
    if not cls.type_name or cls.type_name == "base":
        raise ValueError(f"{cls.__name__}: type_name must be set")

    if cls.type_name in _step_registry:
        logger.warning(
            f"[FLOW] overriding existing step type: {cls.type_name}"
        )

    _step_registry[cls.type_name] = cls
    _step_instances[cls.type_name] = cls()
    logger.info(f"[FLOW] Step registered: {cls.type_name} ({cls.__name__})")
    return cls


def get_step(type_name: str) -> Optional[BaseStep]:
    """Return the singleton instance for a step type."""
    return _step_instances.get(type_name)


def get_step_class(type_name: str) -> Optional[Type[BaseStep]]:
    return _step_registry.get(type_name)


def list_steps() -> List[str]:
    return sorted(_step_registry.keys())


def step_info() -> List[Dict[str, Any]]:
    """Return metadata for admin UI."""
    out = []
    for name, cls in _step_registry.items():
        out.append({
            "type": name,
            "display_name": cls.display_name,
            "icon": cls.icon,
            "help": cls.help_text,
            "mandatory": cls.mandatory,
            "default_enabled": cls.default_enabled,
            "default_order": cls.default_order,
        })
    out.sort(key=lambda x: x["default_order"])
    return out


# ============================================================
# SECTION 4 — FLOW DEFINITION
# ============================================================

@dataclass
class FlowDefinition:
    """
    A named flow — an ordered list of step configs.

    This is what gets stored in DB per group / globally.
    """
    name: str
    display_name: str = ""
    icon: str = "⚙️"
    description: str = ""

    # Ordered list of step configs
    steps: List[Dict[str, Any]] = field(default_factory=list)

    # Flow-level toggles
    cancel_enabled: bool = True
    back_enabled: bool = True
    auto_start: bool = True

    # Free-form extras (for future expansion)
    extras: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "FlowDefinition":
        return cls(
            name=data.get("name", ""),
            display_name=data.get("display_name", ""),
            icon=data.get("icon", "⚙️"),
            description=data.get("description", ""),
            steps=list(data.get("steps") or []),
            cancel_enabled=data.get("cancel_enabled", True),
            back_enabled=data.get("back_enabled", True),
            auto_start=data.get("auto_start", True),
            extras=dict(data.get("extras") or {}),
        )

    def sorted_steps(self) -> List[Dict[str, Any]]:
        """Return steps sorted by their order field, enabled only."""
        enabled = [s for s in self.steps if s.get("enabled", True)]
        return sorted(enabled, key=lambda s: s.get("order", 100))

    def all_steps_sorted(self) -> List[Dict[str, Any]]:
        """Return ALL steps (including disabled) sorted by order."""
        return sorted(self.steps, key=lambda s: s.get("order", 100))


# ============================================================
# SECTION 5 — FLOW REGISTRY
# ============================================================

_flow_registry: Dict[str, FlowDefinition] = {}


def register_flow(flow: FlowDefinition) -> None:
    """Register a flow definition (default)."""
    _flow_registry[flow.name] = flow
    logger.info(
        f"[FLOW] Flow registered: {flow.name} "
        f"({len(flow.steps)} steps)"
    )


def get_flow(name: str) -> Optional[FlowDefinition]:
    return _flow_registry.get(name)


def list_flows() -> List[str]:
    return sorted(_flow_registry.keys())


def flow_info() -> List[Dict[str, Any]]:
    """Metadata for admin UI."""
    out = []
    for name, flow in _flow_registry.items():
        out.append({
            "name": name,
            "display_name": flow.display_name or name,
            "icon": flow.icon,
            "description": flow.description,
            "step_count": len(flow.sorted_steps()),
            "total_steps": len(flow.steps),
        })
    return out


def unregister_flow(name: str) -> bool:
    return _flow_registry.pop(name, None) is not None


# ============================================================
# SECTION 6 — FLOW BUILDER HELPERS
# ============================================================

def build_default_flow(
    name: str,
    display_name: str = "",
    icon: str = "⚙️",
    description: str = "",
    step_order: Optional[List[str]] = None,
    overrides: Optional[Dict[str, Dict[str, Any]]] = None,
) -> FlowDefinition:
    """
    Build a flow from registered steps.

    step_order:   explicit list of step type names (in order).
                  If None → use all registered steps sorted by
                  their default_order.

    overrides:    per-step-type config patches.
                  e.g. {"language": {"per_row": 1}}
    """
    overrides = overrides or {}

    if step_order is None:
        step_order = [
            info["type"] for info in step_info()
        ]

    steps: List[Dict[str, Any]] = []
    for i, type_name in enumerate(step_order):
        cls = get_step_class(type_name)
        if cls is None:
            logger.warning(f"[FLOW] unknown step in builder: {type_name}")
            continue

        cfg = cls.default_config()
        cfg["order"] = i * 10

        # Apply overrides
        if type_name in overrides:
            patch = overrides[type_name]
            cfg.update(patch)

        steps.append(cfg)

    return FlowDefinition(
        name=name,
        display_name=display_name or name,
        icon=icon,
        description=description,
        steps=steps,
    )


# ============================================================
# SECTION 7 — VALIDATION
# ============================================================

def validate_flow(flow: FlowDefinition) -> List[str]:
    """Return list of errors (empty = OK)."""
    errors: List[str] = []

    if not flow.name:
        errors.append("flow.name required")

    if not flow.steps:
        errors.append("flow must have at least one step")

    for i, step in enumerate(flow.steps):
        type_name = step.get("type")
        if not type_name:
            errors.append(f"step#{i}: missing type")
            continue

        cls = get_step_class(type_name)
        if cls is None:
            errors.append(f"step#{i}: unknown type '{type_name}'")
            continue

        step_errors = cls.validate_config(step)
        for err in step_errors:
            errors.append(f"step#{i} ({type_name}): {err}")

    return errors


# ============================================================
# SECTION 8 — SNAPSHOT FOR ADMIN
# ============================================================

def snapshot() -> Dict[str, Any]:
    return {
        "steps": step_info(),
        "flows": flow_info(),
        "step_count": len(_step_registry),
        "flow_count": len(_flow_registry),
    }


# ============================================================
# SECTION 9 — PUBLIC EXPORTS
# ============================================================

__all__ = [
    # Data classes
    "StepContext",
    "StepResult",
    "RenderResult",
    "BaseStep",
    "FlowDefinition",
    # Step registry
    "register_step",
    "get_step",
    "get_step_class",
    "list_steps",
    "step_info",
    # Flow registry
    "register_flow",
    "get_flow",
    "list_flows",
    "flow_info",
    "unregister_flow",
    # Helpers
    "build_default_flow",
    "validate_flow",
    "snapshot",
]


# ============================================================
# END OF core/flow_engine.py — PART A/4
# ============================================================


# ============================================================
# 🏨 DOWNTOWN VILLA — FLOW ENGINE — PART B/4
# ============================================================
#
# Config storage layer.
#
# Handles:
#   • Load flow config from DB (per-group or global)
#   • Save flow config to DB
#   • Auto-migration when new steps are added to code
#   • Default flow builder from registered steps
#   • Config diffing (what changed)
#   • Config cloning (duplicate a group's flow)
#
# Storage layout:
#   Collection: flow_configs
#   Document per group (or "_global" for defaults):
#   {
#     "chat_id": 123,
#     "flows": {
#        "movie_search": { ...FlowDefinition dict... },
#        "series_search": { ... },
#        "pm_search": { ... },
#        "broadcast": { ... },
#     },
#     "updated_at": datetime,
#   }
#
# ============================================================


import copy
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from core.flow_engine import (
    FlowDefinition, get_step_class, step_info,
    build_default_flow, validate_flow,
    get_flow, list_flows, flow_info,
)

logger = logging.getLogger(__name__)


# ============================================================
# SECTION 1 — CONSTANTS
# ============================================================

GLOBAL_KEY = "_global"


# ============================================================
# SECTION 2 — DB ACCESS
# ============================================================

def _coll():
    """Get the flow_configs collection (system DB)."""
    try:
        from database import db_registry
        db = db_registry.get_system_db()
        if db is None:
            return None
        return db["flow_configs"]
    except Exception as e:
        logger.debug(f"[FLOW] coll error: {e}")
        return None


async def _load_doc(chat_id: int) -> Optional[Dict[str, Any]]:
    """Load a flow config document from DB."""
    c = _coll()
    if c is None:
        return None
    try:
        return await c.find_one({"chat_id": int(chat_id)})
    except Exception as e:
        logger.debug(f"[FLOW] load error: {e}")
        return None


async def _save_doc(chat_id: int, doc: Dict[str, Any]) -> bool:
    """Save a flow config document."""
    c = _coll()
    if c is None:
        return False
    try:
        doc = dict(doc)
        doc["chat_id"] = int(chat_id)
        doc["updated_at"] = datetime.utcnow()
        await c.update_one(
            {"chat_id": int(chat_id)},
            {"$set": doc},
            upsert=True,
        )
        return True
    except Exception as e:
        logger.warning(f"[FLOW] save error: {e}")
        return False


# ============================================================
# SECTION 3 — DEFAULT FLOWS (built from registered steps)
# ============================================================

# Map: flow_name → list of step type names in default order
# These are constructed at engine boot, but only used when no
# user config exists yet.

_DEFAULT_STEP_ORDER: Dict[str, List[str]] = {}


def set_default_order(flow_name: str, step_types: List[str]) -> None:
    """Register the default step order for a flow."""
    _DEFAULT_STEP_ORDER[flow_name] = list(step_types)
    logger.info(
        f"[FLOW] Default order for '{flow_name}': "
        f"{len(step_types)} steps"
    )


def get_default_order(flow_name: str) -> List[str]:
    """Return the default step order for a flow (or all steps)."""
    if flow_name in _DEFAULT_STEP_ORDER:
        return list(_DEFAULT_STEP_ORDER[flow_name])
    # Fallback: every registered step, sorted by default_order
    return [info["type"] for info in step_info()]


def build_default(flow_name: str) -> FlowDefinition:
    """
    Build the default FlowDefinition for a flow name.
    This is what you get when no custom config exists.
    """
    order = get_default_order(flow_name)
    flow = build_default_flow(
        name=flow_name,
        display_name=flow_name.replace("_", " ").title(),
        step_order=order,
    )
    return flow


# ============================================================
# SECTION 4 — AUTO-MIGRATION
# ============================================================

def migrate_flow(flow: FlowDefinition) -> FlowDefinition:
    """
    Add any newly-registered step types that aren't in the flow yet.
    Preserve the user's existing enabled/order/layout config.
    Remove steps that no longer exist in code (safely).
    """
    # Build a set of existing step types in the stored flow
    existing_types = {s.get("type") for s in flow.steps if s.get("type")}

    # Find all registered step types
    registered_types = {info["type"] for info in step_info()}

    added = []
    removed = []

    # 1. Remove steps that no longer exist in code
    new_steps: List[Dict[str, Any]] = []
    for s in flow.steps:
        t = s.get("type")
        if t in registered_types:
            new_steps.append(s)
        else:
            removed.append(t)

    # 2. Add newly-registered steps not in the stored flow
    for info in step_info():
        if info["type"] not in existing_types:
            cls = get_step_class(info["type"])
            if cls is None:
                continue
            cfg = cls.default_config()
            cfg["order"] = info["default_order"]
            new_steps.append(cfg)
            added.append(info["type"])

    # 3. Re-sort by order
    new_steps.sort(key=lambda s: s.get("order", 100))

    if added or removed:
        logger.info(
            f"[FLOW] Migrated '{flow.name}': "
            f"added={added} removed={removed}"
        )

    flow.steps = new_steps
    return flow


# ============================================================
# SECTION 5 — GET / SET FLOW FOR A CHAT
# ============================================================

async def get_flow_for(
    chat_id: int,
    flow_name: str,
    use_cache: bool = True,
) -> FlowDefinition:
    """
    Return the effective FlowDefinition for a chat.

    Priority:
      1. Chat-specific config
      2. Global config (_global)
      3. Built-in default
    """
    # 1. Chat-specific
    if chat_id:
        doc = await _load_doc(chat_id)
        if doc:
            flows = doc.get("flows") or {}
            if flow_name in flows:
                flow = FlowDefinition.from_dict(flows[flow_name])
                return migrate_flow(flow)

    # 2. Global
    doc = await _load_doc(0)
    if doc:
        flows = doc.get("flows") or {}
        if flow_name in flows:
            flow = FlowDefinition.from_dict(flows[flow_name])
            return migrate_flow(flow)

    # 3. Built-in default
    return build_default(flow_name)


async def set_flow_for(
    chat_id: int,
    flow: FlowDefinition,
) -> bool:
    """Store a FlowDefinition for a chat."""
    errors = validate_flow(flow)
    if errors:
        logger.warning(f"[FLOW] invalid config: {errors}")
        return False

    doc = await _load_doc(chat_id) or {"chat_id": int(chat_id), "flows": {}}
    flows = dict(doc.get("flows") or {})
    flows[flow.name] = flow.to_dict()
    doc["flows"] = flows
    return await _save_doc(chat_id, doc)


async def delete_flow_for(chat_id: int, flow_name: str) -> bool:
    """Remove a chat's custom config for one flow (revert to default)."""
    doc = await _load_doc(chat_id)
    if not doc:
        return False
    flows = dict(doc.get("flows") or {})
    if flow_name not in flows:
        return False
    flows.pop(flow_name, None)
    doc["flows"] = flows
    return await _save_doc(chat_id, doc)


async def reset_all_for(chat_id: int) -> bool:
    """Wipe every custom flow for a chat."""
    c = _coll()
    if c is None:
        return False
    try:
        await c.delete_one({"chat_id": int(chat_id)})
        return True
    except Exception:
        return False


# ============================================================
# SECTION 6 — STEP MUTATION HELPERS
# ============================================================

def find_step(flow: FlowDefinition, type_name: str) -> Optional[Dict[str, Any]]:
    for s in flow.steps:
        if s.get("type") == type_name:
            return s
    return None


def set_step_field(
    flow: FlowDefinition,
    type_name: str,
    field: str,
    value: Any,
) -> bool:
    """Update one field on one step (safe)."""
    step = find_step(flow, type_name)
    if step is None:
        return False
    step[field] = value
    return True


def toggle_step(flow: FlowDefinition, type_name: str) -> Optional[bool]:
    """Toggle enabled on a step. Returns new value or None."""
    step = find_step(flow, type_name)
    if step is None:
        return None
    if step.get("mandatory"):
        return step.get("enabled", True)
    step["enabled"] = not step.get("enabled", True)
    return step["enabled"]


def move_step(
    flow: FlowDefinition,
    type_name: str,
    direction: str = "up",
) -> bool:
    """
    Move a step up or down in the flow.
    Returns True if moved.
    """
    steps = flow.all_steps_sorted()
    idx = next(
        (i for i, s in enumerate(steps) if s.get("type") == type_name),
        -1,
    )
    if idx < 0:
        return False

    if direction == "up" and idx > 0:
        steps[idx - 1], steps[idx] = steps[idx], steps[idx - 1]
    elif direction == "down" and idx < len(steps) - 1:
        steps[idx + 1], steps[idx] = steps[idx], steps[idx + 1]
    else:
        return False

    # Re-index orders
    for i, s in enumerate(steps):
        s["order"] = i * 10

    flow.steps = steps
    return True


def reorder_steps(flow: FlowDefinition, new_order: List[str]) -> bool:
    """
    Set explicit new order by list of type names.
    Steps not in the list keep their relative order at the end.
    """
    steps_by_type = {s.get("type"): s for s in flow.steps}
    new_steps: List[Dict[str, Any]] = []

    for name in new_order:
        if name in steps_by_type:
            s = steps_by_type.pop(name)
            new_steps.append(s)

    for s in steps_by_type.values():
        new_steps.append(s)

    for i, s in enumerate(new_steps):
        s["order"] = i * 10

    flow.steps = new_steps
    return True


def reset_step_to_default(flow: FlowDefinition, type_name: str) -> bool:
    """Reset one step's config to its default."""
    cls = get_step_class(type_name)
    if cls is None:
        return False
    step = find_step(flow, type_name)
    if step is None:
        return False
    default = cls.default_config()
    # Preserve the current order so the flow doesn't shuffle
    default["order"] = step.get("order", 100)
    step.clear()
    step.update(default)
    return True


# ============================================================
# SECTION 7 — DIFF / CLONE
# ============================================================

def diff_flow(before: FlowDefinition, after: FlowDefinition) -> Dict[str, Any]:
    """Return what changed between two flows."""
    changes: Dict[str, Any] = {
        "steps_added": [],
        "steps_removed": [],
        "steps_modified": [],
    }

    before_map = {s.get("type"): s for s in before.steps}
    after_map = {s.get("type"): s for s in after.steps}

    for name in after_map:
        if name not in before_map:
            changes["steps_added"].append(name)

    for name in before_map:
        if name not in after_map:
            changes["steps_removed"].append(name)

    for name in set(before_map.keys()) & set(after_map.keys()):
        a = before_map[name]
        b = after_map[name]
        if a != b:
            changes["steps_modified"].append({
                "type": name,
                "before": a,
                "after": b,
            })

    return changes


def clone_flow(flow: FlowDefinition, new_name: str) -> FlowDefinition:
    """Deep-copy a flow with a new name."""
    cloned = FlowDefinition.from_dict(flow.to_dict())
    cloned.name = new_name
    cloned.display_name = f"{flow.display_name} (copy)"
    return cloned


async def clone_flow_between(
    from_chat: int,
    to_chat: int,
    flow_name: str,
) -> bool:
    """Copy one flow config from one chat to another."""
    source = await get_flow_for(from_chat, flow_name)
    return await set_flow_for(to_chat, source)


# ============================================================
# SECTION 8 — BULK OPERATIONS
# ============================================================

async def list_configured_chats() -> List[int]:
    """Return all chat_ids that have custom flow configs."""
    c = _coll()
    if c is None:
        return []
    try:
        cursor = c.find({}, {"chat_id": 1})
        docs = await cursor.to_list(length=1000)
        return [int(d.get("chat_id", 0)) for d in docs if d.get("chat_id")]
    except Exception:
        return []


async def export_config(chat_id: int) -> Dict[str, Any]:
    """Export a chat's entire flow config."""
    doc = await _load_doc(chat_id)
    return dict(doc) if doc else {}


async def import_config(chat_id: int, data: Dict[str, Any]) -> bool:
    """Import a flow config dict for a chat."""
    if not isinstance(data, dict):
        return False
    flows = data.get("flows")
    if not isinstance(flows, dict):
        return False
    payload = {
        "chat_id": int(chat_id),
        "flows": flows,
        "imported_at": datetime.utcnow(),
    }
    return await _save_doc(chat_id, payload)


# ============================================================
# SECTION 9 — SNAPSHOT
# ============================================================

async def snapshot(chat_id: int) -> Dict[str, Any]:
    """Full view of a chat's flow config for admin."""
    out: Dict[str, Any] = {
        "chat_id": int(chat_id),
        "flows": {},
        "has_custom": False,
    }
    doc = await _load_doc(chat_id)
    if doc and doc.get("flows"):
        out["has_custom"] = True
        for name in doc["flows"]:
            flow = await get_flow_for(chat_id, name)
            out["flows"][name] = {
                "step_count": len(flow.sorted_steps()),
                "total_steps": len(flow.steps),
                "steps": [
                    {
                        "type": s.get("type"),
                        "enabled": s.get("enabled", True),
                        "order": s.get("order", 100),
                        "per_row": s.get("per_row", 2),
                    }
                    for s in flow.all_steps_sorted()
                ],
            }
    return out


# ============================================================
# SECTION 10 — PUBLIC EXPORTS
# ============================================================

__all__ = [
    # Defaults
    "set_default_order",
    "get_default_order",
    "build_default",
    # Migration
    "migrate_flow",
    # Get / set
    "get_flow_for",
    "set_flow_for",
    "delete_flow_for",
    "reset_all_for",
    # Mutation
    "find_step",
    "set_step_field",
    "toggle_step",
    "move_step",
    "reorder_steps",
    "reset_step_to_default",
    # Diff / clone
    "diff_flow",
    "clone_flow",
    "clone_flow_between",
    # Bulk
    "list_configured_chats",
    "export_config",
    "import_config",
    # Snapshot
    "snapshot",
]


# ============================================================
# END OF core/flow_engine.py — PART B/4
# ============================================================


# ============================================================
# 🏨 DOWNTOWN VILLA — FLOW ENGINE — PART C/4
# ============================================================
#
# Runtime execution engine.
#
# Responsibilities:
#   • Create flow runs (per user, per chat)
#   • Execute the current step
#   • Advance / go-back / cancel / jump
#   • Handle auto-skip logic
#   • Safe error recovery (never crash the flow)
#   • Timer + step-trace for admin debugging
#   • Session persistence (in-memory + DB backup)
#   • Cleanup of expired runs
#
# Public API (used by handlers):
#   run = await engine.start(user_id, chat_id, flow_name)
#   result = await engine.render(run)
#   result = await engine.handle_input(run, value)
#   await engine.cancel(run)
#
# ============================================================



import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from pyrogram import Client
from pyrogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from core.flow_engine import (
    BaseStep, FlowDefinition, RenderResult, StepContext, StepResult,
    get_flow, get_step, list_steps,
)
from core import rocket
from utils import fonts as F

logger = logging.getLogger(__name__)


# ============================================================
# SECTION 1 — CONSTANTS
# ============================================================

DEFAULT_TTL = 1800.0           # 30 minutes
MAX_TRACE = 30                 # keep last N steps in trace
MAX_STEPS_PER_RUN = 50         # prevent runaway loops


# ============================================================
# SECTION 2 — RUN OBJECT
# ============================================================

@dataclass
class FlowRun:
    """One live execution of a flow for one user."""
    run_id: str
    user_id: int
    chat_id: int
    flow_name: str
    flow: FlowDefinition

    # Position
    step_index: int = 0

    # Accumulated data
    data: Dict[str, Any] = field(default_factory=dict)

    # Timers + trace
    started_at: float = field(default_factory=time.time)
    expires_at: float = field(default_factory=lambda: time.time() + DEFAULT_TTL)
    updated_at: float = field(default_factory=time.time)
    trace: List[Dict[str, Any]] = field(default_factory=list)

    # Original UI (for editing)
    last_text: Optional[str] = None
    last_keyboard: Any = None

    # Refs
    client: Optional[Client] = None
    message: Optional[Message] = None

    def is_expired(self) -> bool:
        return time.time() > self.expires_at

    def touch(self) -> None:
        self.updated_at = time.time()
        self.expires_at = time.time() + DEFAULT_TTL

    def current_step_cfg(self) -> Optional[Dict[str, Any]]:
        steps = self.flow.sorted_steps()
        if 0 <= self.step_index < len(steps):
            return steps[self.step_index]
        return None

    def record_trace(self, step_type: str, action: str, extra: Optional[dict] = None) -> None:
        self.trace.append({
            "t": time.time(),
            "step": step_type,
            "action": action,
            "extra": extra or {},
        })
        if len(self.trace) > MAX_TRACE:
            self.trace = self.trace[-MAX_TRACE:]


# ============================================================
# SECTION 3 — SESSION STORE (in-memory)
# ============================================================

_runs_by_id: Dict[str, FlowRun] = {}
_runs_by_user: Dict[Tuple[int, int, str], str] = {}
_store_lock = asyncio.Lock()


def _user_key(user_id: int, chat_id: int, flow_name: str) -> Tuple[int, int, str]:
    return (int(user_id), int(chat_id), str(flow_name))


async def _store(run: FlowRun) -> None:
    async with _store_lock:
        _runs_by_id[run.run_id] = run
        _runs_by_user[_user_key(run.user_id, run.chat_id, run.flow_name)] = run.run_id


async def _unstore(run: FlowRun) -> None:
    async with _store_lock:
        _runs_by_id.pop(run.run_id, None)
        _runs_by_user.pop(_user_key(run.user_id, run.chat_id, run.flow_name), None)


def get_run(run_id: str) -> Optional[FlowRun]:
    return _runs_by_id.get(run_id)


def get_run_for_user(
    user_id: int,
    chat_id: int,
    flow_name: str,
) -> Optional[FlowRun]:
    rid = _runs_by_user.get(_user_key(user_id, chat_id, flow_name))
    if not rid:
        return None
    return _runs_by_id.get(rid)


def active_runs() -> List[FlowRun]:
    return list(_runs_by_id.values())


# ============================================================
# SECTION 4 — ENGINE
# ============================================================

class FlowEngine:
    """
    Runtime execution engine.
    """

    # ────────── START ──────────

    async def start(
        self,
        user_id: int,
        chat_id: int,
        flow_name: str,
        client: Optional[Client] = None,
        message: Optional[Message] = None,
        initial_data: Optional[Dict[str, Any]] = None,
    ) -> Optional[FlowRun]:
        """
        Start a flow for a user.
        Cancels any existing run with the same (user, chat, flow).
        """
        # Cancel existing
        existing = get_run_for_user(user_id, chat_id, flow_name)
        if existing is not None:
            await self.cancel(existing, silent=True)

        flow = get_flow(flow_name)
        if flow is None:
            logger.warning(f"[FLOW] unknown flow: {flow_name}")
            return None

        run = FlowRun(
            run_id=uuid.uuid4().hex[:12],
            user_id=int(user_id),
            chat_id=int(chat_id),
            flow_name=flow_name,
            flow=flow,
            data=dict(initial_data or {}),
            client=client,
            message=message,
        )

        # Skip auto-start-disabled steps upfront
        await self._skip_to_first_valid(run)

        await _store(run)
        logger.info(
            f"[FLOW] run={run.run_id} user={user_id} "
            f"flow={flow_name} steps={len(flow.sorted_steps())}"
        )
        return run

    # ────────── SKIP-TO-FIRST ──────────

    async def _skip_to_first_valid(self, run: FlowRun) -> None:
        """Move step_index forward while the current step auto-skips."""
        guard = 0
        while guard < MAX_STEPS_PER_RUN:
            guard += 1
            step_cfg = run.current_step_cfg()
            if step_cfg is None:
                return

            step = get_step(step_cfg["type"])
            if step is None:
                run.step_index += 1
                continue

            ctx = self._build_ctx(run, step_cfg)
            try:
                if step.should_skip(ctx):
                    run.step_index += 1
                    run.record_trace(step.type_name, "skip_pre")
                    continue
            except Exception as e:
                logger.debug(f"[FLOW] should_skip error: {e}")

            return

    # ────────── CONTEXT BUILDER ──────────

    def _build_ctx(self, run: FlowRun, step_cfg: Dict[str, Any]) -> StepContext:
        return StepContext(
            user_id=run.user_id,
            chat_id=run.chat_id,
            is_group=run.chat_id < 0,
            run_id=run.run_id,
            flow_name=run.flow_name,
            step_index=run.step_index,
            step_type=step_cfg.get("type", ""),
            data=run.data,
            step_cfg=step_cfg,
            flow_cfg=run.flow.to_dict(),
            session=run,
            client=run.client,
            message=run.message,
        )

    # ────────── RENDER ──────────

    async def render(self, run: FlowRun) -> Optional[RenderResult]:
        """
        Render the current step.
        Auto-advances if step decides to skip.
        Returns the RenderResult from the FIRST non-skipped step, or None.
        """
        guard = 0
        while guard < MAX_STEPS_PER_RUN:
            guard += 1

            if run.is_expired():
                logger.info(f"[FLOW] run={run.run_id} expired mid-render")
                return None

            step_cfg = run.current_step_cfg()
            if step_cfg is None:
                # End of flow
                return None

            step = get_step(step_cfg["type"])
            if step is None:
                run.step_index += 1
                continue

            ctx = self._build_ctx(run, step_cfg)

            try:
                result = await step.render(ctx)
            except Exception as e:
                logger.exception(f"[FLOW] step render crashed: {step.type_name}")
                result = RenderResult(auto_skip=True)

            if result is None:
                result = RenderResult(auto_skip=True)

            if result.auto_skip:
                run.step_index += 1
                run.record_trace(step.type_name, "skip_render")
                continue

            run.last_text = result.text
            run.last_keyboard = result.keyboard
            run.touch()
            return result

        logger.warning(f"[FLOW] run={run.run_id} exceeded step guard")
        return None

    # ────────── HANDLE INPUT ──────────

    async def handle_input(
        self,
        run: FlowRun,
        value: Any,
    ) -> Optional[StepResult]:
        """
        Process user input for the current step.
        Applies the returned action.
        Returns the raw StepResult (for caller to react).
        """
        if run.is_expired():
            return StepResult(action="cancel")

        step_cfg = run.current_step_cfg()
        if step_cfg is None:
            return StepResult(action="done")

        step = get_step(step_cfg["type"])
        if step is None:
            return StepResult(action="next")

        ctx = self._build_ctx(run, step_cfg)

        try:
            result = await step.on_input(ctx, value)
        except Exception as e:
            logger.exception(f"[FLOW] step input crashed: {step.type_name}")
            return StepResult(action="stay")

        if result is None:
            result = StepResult(action="stay")

        run.record_trace(
            step.type_name, result.action,
            extra={"value_preview": str(value)[:60]},
        )

        # Merge any data the step produced
        if result.data:
            run.data.update(result.data)

        # Apply action
        await self._apply_action(run, result)
        return result

    # ────────── APPLY ACTION ──────────

    async def _apply_action(self, run: FlowRun, result: StepResult) -> None:
        action = (result.action or "stay").lower()

        if action == "cancel":
            await self.cancel(run)
            return

        if action == "done":
            await self._unstore(run)
            return

        if action == "next":
            run.step_index += 1
            await self._skip_to_first_valid(run)
            run.touch()
            return

        if action == "back":
            if run.step_index > 0:
                run.step_index -= 1
            run.touch()
            return

        if action == "jump":
            if result.jump_to is not None:
                run.step_index = max(0, int(result.jump_to))
                await self._skip_to_first_valid(run)
            run.touch()
            return

        if action in ("stay", "repeat"):
            run.touch()
            return

        # Unknown action → stay safe
        run.touch()

    # ────────── CANCEL ──────────

    async def cancel(self, run: FlowRun, silent: bool = False) -> None:
        run.record_trace("_engine", "cancel")
        await _unstore(run)
        if not silent:
            logger.info(f"[FLOW] run={run.run_id} cancelled")

    async def cancel_for_user(
        self,
        user_id: int,
        chat_id: int,
        flow_name: str,
    ) -> bool:
        run = get_run_for_user(user_id, chat_id, flow_name)
        if not run:
            return False
        await self.cancel(run)
        return True

    # ────────── GO BACK (helper) ──────────

    async def go_back(self, run: FlowRun) -> Optional[RenderResult]:
        if run.step_index > 0:
            run.step_index -= 1
            run.touch()
        return await self.render(run)

    # ────────── ADVANCE (helper) ──────────

    async def advance(self, run: FlowRun) -> Optional[RenderResult]:
        run.step_index += 1
        await self._skip_to_first_valid(run)
        run.touch()
        return await self.render(run)

    # ────────── FINISH CHECK ──────────

    def is_finished(self, run: FlowRun) -> bool:
        return run.current_step_cfg() is None

    # ────────── TRACE / DIAGNOSTIC ──────────

    def explain(self, run: FlowRun) -> Dict[str, Any]:
        """Full diagnostic snapshot for admin."""
        return {
            "run_id": run.run_id,
            "user_id": run.user_id,
            "chat_id": run.chat_id,
            "flow": run.flow_name,
            "step_index": run.step_index,
            "step_type": (run.current_step_cfg() or {}).get("type"),
            "expired": run.is_expired(),
            "age_s": round(time.time() - run.started_at, 1),
            "trace": run.trace[-10:],
            "data_keys": list(run.data.keys()),
        }


# ============================================================
# SECTION 5 — SINGLETON
# ============================================================

engine = FlowEngine()


# ============================================================
# SECTION 6 — CLEANUP LOOP
# ============================================================

async def cleanup_loop(interval: float = 120.0) -> None:
    """Background: purge expired runs."""
    while True:
        try:
            await asyncio.sleep(interval)
            now = time.time()
            doomed = [r for r in list(_runs_by_id.values()) if r.is_expired()]
            for run in doomed:
                await _unstore(run)
                logger.debug(f"[FLOW] purged expired run {run.run_id}")
        except asyncio.CancelledError:
            return
        except Exception as e:
            logger.debug(f"[FLOW] cleanup error: {e}")


_cleanup_task: Optional[asyncio.Task] = None


def ensure_cleanup(interval: float = 120.0) -> None:
    global _cleanup_task
    if _cleanup_task and not _cleanup_task.done():
        return
    try:
        loop = asyncio.get_running_loop()
        _cleanup_task = loop.create_task(cleanup_loop(interval))
    except RuntimeError:
        pass


# ============================================================
# SECTION 7 — UNIVERSAL CANCEL CALLBACK
# ============================================================
#
# Every step's keyboard should include a callback of form:
#     cancel:flow:{run_id}
# This handler catches them all.
#

async def handle_cancel_callback(
    client: Client,
    q: CallbackQuery,
) -> bool:
    """
    Handle `cancel:flow:{run_id}` callbacks.
    Returns True if handled.
    """
    data = str(q.data or "")
    if not data.startswith("cancel:flow:"):
        return False

    try:
        run_id = data.split(":", 2)[2]
    except Exception:
        return False

    run = get_run(run_id)
    if run is not None:
        await engine.cancel(run)

    try:
        await q.message.delete()
    except Exception:
        pass

    await q.answer("❌ Cancelled")
    return True


# ============================================================
# SECTION 8 — STANDARD BUTTONS (built by every step)
# ============================================================

def cancel_button(run_id: str, row: int = 0) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        f"{F.EMO['cross']} {F.sc('cancel')}",
        callback_data=f"cancel:flow:{run_id}",
    )


def back_button(run_id: str) -> InlineKeyboardButton:
    return InlineKeyboardButton(
        f"{F.EMO['back']} {F.sc('back')}",
        callback_data=f"flow:back:{run_id}",
    )


# ============================================================
# SECTION 9 — BACK CALLBACK HANDLER
# ============================================================

async def handle_back_callback(
    client: Client,
    q: CallbackQuery,
) -> bool:
    """Handle `flow:back:{run_id}` callbacks."""
    data = str(q.data or "")
    if not data.startswith("flow:back:"):
        return False

    try:
        run_id = data.split(":", 2)[2]
    except Exception:
        return False

    run = get_run(run_id)
    if run is None:
        await q.answer("⚠️ Session expired")
        return True

    result = await engine.go_back(run)
    if result is None:
        await q.answer("⚠️ Cannot go back")
        return True

    try:
        await q.message.edit_text(
            result.text,
            reply_markup=result.keyboard,
            disable_web_page_preview=True,
        )
    except Exception:
        pass

    await q.answer()
    return True


# ============================================================
# SECTION 10 — SNAPSHOT
# ============================================================

def snapshot() -> Dict[str, Any]:
    return {
        "active_runs": len(_runs_by_id),
        "active_users": len(_runs_by_user),
        "cleanup_running": bool(_cleanup_task and not _cleanup_task.done()),
        "runs": [engine.explain(r) for r in active_runs()[:20]],
    }


# ============================================================
# SECTION 11 — PUBLIC EXPORTS
# ============================================================

__all__ = [
    # Run
    "FlowRun",
    # Store
    "get_run",
    "get_run_for_user",
    "active_runs",
    # Engine
    "FlowEngine",
    "engine",
    # Cleanup
    "ensure_cleanup",
    "cleanup_loop",
    # Universal callbacks
    "handle_cancel_callback",
    "handle_back_callback",
    # Buttons
    "cancel_button",
    "back_button",
    # Snapshot
    "snapshot",
]


# ============================================================
# END OF core/flow_engine.py — PART C/4
# ============================================================

# ============================================================
# 🏨 DOWNTOWN VILLA — FLOW ENGINE — PART D/4 (FINAL)
# ============================================================
#
# Telegram editor UI.
#
# Commands:
#   /flow            → open editor for current chat
#   /flow <name>     → open specific flow
#   /flow_global     → edit global defaults
#
# Features:
#   • List every step with ON/OFF state
#   • Toggle any step
#   • Move up / down
#   • Layout picker (1 / 2 / 3 per row)
#   • Auto-skip toggle
#   • Per-step advanced config
#   • Reset step / whole flow
#   • Clone to another chat
#   • Live preview
#   • Cancel button on every panel
#
# ============================================================


import logging
from typing import Any, Dict, List, Optional

from pyrogram import Client, filters
from pyrogram.enums import ParseMode
from pyrogram.types import (
    CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message,
)

from core.flow_engine import (
    BaseStep, FlowDefinition, get_flow, get_step, list_flows,
    list_steps, step_info, validate_flow,
)
from core.flow_engine import (
    get_flow_for, set_flow_for, delete_flow_for, reset_all_for,
    find_step, set_step_field, toggle_step, move_step, reset_step_to_default,
    build_default, export_config, import_config, snapshot as config_snapshot,
)
from core import config
from utils import fonts as F
from utils import format as FM

logger = logging.getLogger(__name__)


# ============================================================
# SECTION 1 — AUTH
# ============================================================

def _is_admin(uid: int) -> bool:
    try:
        return int(uid) in [int(a) for a in config.ADMINS if str(a).isdigit()]
    except Exception:
        return False


async def _is_group_admin(client: Client, chat_id: int, user_id: int) -> bool:
    if _is_admin(user_id):
        return True
    try:
        m = await client.get_chat_member(chat_id, user_id)
        st = getattr(m, "status", None)
        st = st.name.lower() if hasattr(st, "name") else str(st).lower()
        return st in ("administrator", "creator", "owner")
    except Exception:
        return False


# ============================================================
# SECTION 2 — CALLBACK PREFIX
# ============================================================

PFX = "flw"    # short to fit 64-byte callback limit


def cb(*parts) -> str:
    return ":".join([PFX] + [str(p) for p in parts])


# ============================================================
# SECTION 3 — MAIN PANEL
# ============================================================

async def _render_main(chat_id: int, flow_name: str) -> tuple:
    """Build the main flow editor text + keyboard."""
    flow = await get_flow_for(chat_id, flow_name)

    steps = flow.all_steps_sorted()
    enabled_count = sum(1 for s in steps if s.get("enabled", True))

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"{F.EMO['gear']} <b>{F.fb('FLOW EDITOR')}</b>",
        F.DIV,
        "",
        f"{F.EMO['channel']} {F.sc('chat')} · <code>{chat_id or 'GLOBAL'}</code>",
        f"{F.EMO['book']} {F.sc('flow')} · <b>{flow.display_name or flow_name}</b>",
        "",
        f"{F.EMO['check']} {F.sc('enabled')} · <b>{enabled_count}</b> / {len(steps)}",
        "",
        F.DIV_S,
        f"📋 <b>{F.sc('steps in order')}</b>",
        "",
    ]

    for i, step_cfg in enumerate(steps, 1):
        step = get_step(step_cfg["type"])
        if step is None:
            continue

        enabled = step_cfg.get("enabled", True)
        icon = "🟢" if enabled else "🔴"
        per_row = step_cfg.get("per_row", 2)

        label = step.display_name or step_cfg.get("type", "?")
        lines.append(
            f"{icon} <b>{i:02d}.</b> {step.icon} {F.sc(label)} "
            f"· <code>{per_row}/row</code>"
        )

    lines += [
        "",
        F.DIV_S,
        f"{F.EMO['spark']} {F.sc('tap a step to configure')}",
        f"{F.EMO['clock']} <code>{FM.datetime_()}</code>",
    ]

    # Build keyboard — 2 steps per row for compactness
    rows: List[List[InlineKeyboardButton]] = []
    row: List[InlineKeyboardButton] = []
    for i, step_cfg in enumerate(steps):
        step = get_step(step_cfg["type"])
        if step is None:
            continue
        enabled = step_cfg.get("enabled", True)
        icon = "🟢" if enabled else "🔴"
        label = (step.display_name or step_cfg["type"])[:18]
        row.append(InlineKeyboardButton(
            f"{icon} {label}",
            callback_data=cb("step", flow_name, i),
        ))
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)

    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['refresh']} {F.sc('preview')}",
            callback_data=cb("preview", flow_name),
        ),
        InlineKeyboardButton(
            f"{F.EMO['reset']} {F.sc('reset all')}",
            callback_data=cb("reset_all", flow_name),
        ),
    ])
    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['close']} {F.sc('close')}",
            callback_data="cancel:flow:0",
        ),
    ])

    return "\n".join(lines), InlineKeyboardMarkup(rows)


# ============================================================
# SECTION 4 — STEP DETAIL PANEL
# ============================================================

async def _render_step(
    chat_id: int,
    flow_name: str,
    step_index: int,
) -> Optional[tuple]:
    flow = await get_flow_for(chat_id, flow_name)
    steps = flow.all_steps_sorted()

    if step_index < 0 or step_index >= len(steps):
        return None

    step_cfg = steps[step_index]
    step = get_step(step_cfg["type"])
    if step is None:
        return None

    enabled = step_cfg.get("enabled", True)
    per_row = step_cfg.get("per_row", 2)
    auto_skip = step_cfg.get("auto_skip_if_one", True)

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"{step.icon} <b>{F.fb(step.display_name or step_cfg['type'])}</b>",
        F.DIV,
        "",
        f"{F.EMO['info']} <i>{F.sc(step.help_text)}</i>",
        "",
        f"📌 {F.sc('type')} · <code>{step_cfg['type']}</code>",
        f"📌 {F.sc('position')} · <b>{step_index + 1}</b> / {len(steps)}",
        f"📌 {F.sc('status')} · {'🟢 ' + F.sc('enabled') if enabled else '🔴 ' + F.sc('disabled')}",
        f"📌 {F.sc('layout')} · <b>{per_row}</b> {F.sc('per row')}",
        f"📌 {F.sc('auto-skip')} · {'🟢' if auto_skip else '🔴'}",
        "",
        F.DIV_S,
    ]

    rows: List[List[InlineKeyboardButton]] = []

    # Toggle row
    rows.append([
        InlineKeyboardButton(
            f"{'🔴 ' + F.sc('disable') if enabled else '🟢 ' + F.sc('enable')}",
            callback_data=cb("toggle", flow_name, step_index),
        ),
    ])

    # Layout picker (1/2/3 per row)
    layout_row: List[InlineKeyboardButton] = []
    for n in (1, 2, 3):
        mark = "✅" if n == per_row else "  "
        layout_row.append(InlineKeyboardButton(
            f"{mark} {n}/row",
            callback_data=cb("layout", flow_name, step_index, n),
        ))
    rows.append(layout_row)

    # Auto-skip toggle
    rows.append([
        InlineKeyboardButton(
            f"{'🟢' if auto_skip else '🔴'} {F.sc('auto-skip if one')}",
            callback_data=cb("autoskip", flow_name, step_index),
        ),
    ])

    # Move up/down
    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['prev']} {F.sc('move up')}",
            callback_data=cb("moveup", flow_name, step_index),
        ),
        InlineKeyboardButton(
            f"{F.EMO['next']} {F.sc('move down')}",
            callback_data=cb("movedown", flow_name, step_index),
        ),
    ])

    # Advanced + Reset
    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['gear']} {F.sc('advanced')}",
            callback_data=cb("advanced", flow_name, step_index),
        ),
        InlineKeyboardButton(
            f"{F.EMO['reset']} {F.sc('reset step')}",
            callback_data=cb("reset_step", flow_name, step_index),
        ),
    ])

    # Back
    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data=cb("main", flow_name),
        ),
        InlineKeyboardButton(
            f"{F.EMO['close']} {F.sc('close')}",
            callback_data="cancel:flow:0",
        ),
    ])

    return "\n".join(lines), InlineKeyboardMarkup(rows)


# ============================================================
# SECTION 5 — ADVANCED PANEL
# ============================================================

async def _render_advanced(
    chat_id: int,
    flow_name: str,
    step_index: int,
) -> Optional[tuple]:
    flow = await get_flow_for(chat_id, flow_name)
    steps = flow.all_steps_sorted()

    if step_index < 0 or step_index >= len(steps):
        return None

    step_cfg = steps[step_index]
    step = get_step(step_cfg["type"])
    if step is None:
        return None

    custom = step_cfg.get("custom") or {}
    max_items = step_cfg.get("max_items", 10)

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"{F.EMO['gear']} <b>{F.fb('ADVANCED')}</b> · {step.icon} {F.sc(step.display_name)}",
        F.DIV,
        "",
        f"{F.EMO['bar']} {F.sc('max items')} · <b>{max_items}</b>",
        "",
        F.DIV_S,
        f"⚙️ <b>{F.sc('custom settings')}</b>",
        "",
    ]

    if not custom:
        lines.append(f"{F.EMO['box']} <i>{F.sc('no custom settings yet')}</i>")
    else:
        for k, v in list(custom.items())[:10]:
            lines.append(f"• <code>{k}</code> · <b>{v}</b>")

    lines += [
        "",
        F.DIV_S,
        f"{F.EMO['spark']} {F.sc('changes apply instantly')}",
    ]

    rows: List[List[InlineKeyboardButton]] = []

    # Max items picker
    for n in (3, 5, 10, 15, 20):
        mark = "✅" if n == max_items else ""
        label = f"{mark} {n}".strip()
        rows.append([InlineKeyboardButton(
            label,
            callback_data=cb("maxitems", flow_name, step_index, n),
        )]) if False else None

    # Simpler: one row of max items
    items_row: List[InlineKeyboardButton] = []
    for n in (3, 5, 10, 15, 20):
        mark = "✅" if n == max_items else ""
        items_row.append(InlineKeyboardButton(
            f"{mark}{n}",
            callback_data=cb("maxitems", flow_name, step_index, n),
        ))
    rows.append(items_row)

    rows.append([
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data=cb("step", flow_name, step_index),
        ),
        InlineKeyboardButton(
            f"{F.EMO['close']} {F.sc('close')}",
            callback_data="cancel:flow:0",
        ),
    ])

    return "\n".join(lines), InlineKeyboardMarkup(rows)


# ============================================================
# SECTION 6 — PREVIEW PANEL
# ============================================================

async def _render_preview(chat_id: int, flow_name: str) -> tuple:
    flow = await get_flow_for(chat_id, flow_name)
    steps = flow.sorted_steps()

    lines = [
        f"{F.EMO['brand']} <b>{F.fb('DOWNTOWN VILLA')}</b>",
        f"{F.EMO['eye']} <b>{F.fb('FLOW PREVIEW')}</b>",
        F.DIV,
        "",
        f"{F.EMO['book']} {F.sc('flow')} · <b>{flow.display_name}</b>",
        f"{F.EMO['chart']} {F.sc('active steps')} · <b>{len(steps)}</b>",
        "",
        F.DIV_S,
        "",
    ]

    for i, step_cfg in enumerate(steps, 1):
        step = get_step(step_cfg["type"])
        if step is None:
            continue
        per_row = step_cfg.get("per_row", 2)
        lines.append(
            f"<b>{i:02d}.</b> {step.icon} {F.sc(step.display_name)} "
            f"· <code>{per_row}/row</code>"
        )

    lines += [
        "",
        F.DIV_S,
        f"{F.EMO['spark']} {F.sc('this is the order users will see')}",
    ]

    rows = [[
        InlineKeyboardButton(
            f"{F.EMO['back']} {F.sc('back')}",
            callback_data=cb("main", flow_name),
        ),
        InlineKeyboardButton(
            f"{F.EMO['close']} {F.sc('close')}",
            callback_data="cancel:flow:0",
        ),
    ]]

    return "\n".join(lines), InlineKeyboardMarkup(rows)


# ============================================================
# SECTION 7 — COMMAND ENTRY
# ============================================================

@Client.on_message(
    filters.command(["flow", "floweditor"]) & filters.private,
    group=-8500,
)
async def cmd_flow(client: Client, message: Message):
    """Open the flow editor."""
    if not message.from_user:
        return
    uid = message.from_user.id

    # Parse flow name from args (default: movie_search)
    parts = (message.text or "").split(maxsplit=1)
    flow_name = parts[1].strip() if len(parts) > 1 else "movie_search"

    if flow_name == "global":
        chat_id = 0
    else:
        chat_id = uid  # personal default

    if not _is_admin(uid):
        # Allow group admins in group context — for now admin-only PM
        return await message.reply_text(
            f"{F.EMO['cross']} {F.sc('admins only')}",
            parse_mode=ParseMode.HTML,
        )

    try:
        text, kb = await _render_main(chat_id, flow_name)
    except Exception as e:
        logger.exception(f"[FLOW] render_main: {e}")
        return await message.reply_text(f"❌ {e}")

    await message.reply_text(
        text,
        reply_markup=kb,
        parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


@Client.on_message(
    filters.command(["flow_global"]) & filters.private,
    group=-8500,
)
async def cmd_flow_global(client: Client, message: Message):
    if not message.from_user or not _is_admin(message.from_user.id):
        return
    text, kb = await _render_main(0, "movie_search")
    await message.reply_text(
        text, reply_markup=kb, parse_mode=ParseMode.HTML,
        disable_web_page_preview=True,
    )


# ============================================================
# SECTION 8 — CALLBACK ROUTER
# ============================================================

@Client.on_callback_query(
    filters.regex(rf"^{PFX}:"),
    group=-8500,
)
async def flow_router(client: Client, q: CallbackQuery):
    if not q.from_user or not _is_admin(q.from_user.id):
        return await q.answer("❌ Admin only", show_alert=True)

    # callback format: flw:action:flow_name:arg1:arg2...
    parts = str(q.data).split(":")
    if len(parts) < 3:
        return await q.answer("❌ Invalid")

    action = parts[1]
    flow_name = parts[2]
    args = parts[3:] if len(parts) > 3 else []

    chat_id = q.from_user.id

    try:
        # ────────── MAIN ──────────
        if action == "main":
            text, kb = await _render_main(chat_id, flow_name)
            await _safe_edit(q, text, kb)
            return await q.answer()

        # ────────── STEP ──────────
        if action == "step":
            idx = int(args[0]) if args else 0
            r = await _render_step(chat_id, flow_name, idx)
            if r is None:
                return await q.answer("⚠️ Step not found", show_alert=True)
            text, kb = r
            await _safe_edit(q, text, kb)
            return await q.answer()

        # ────────── TOGGLE ──────────
        if action == "toggle":
            idx = int(args[0]) if args else 0
            flow = await get_flow_for(chat_id, flow_name)
            steps = flow.all_steps_sorted()
            if 0 <= idx < len(steps):
                new_state = toggle_step(flow, steps[idx]["type"])
                await set_flow_for(chat_id, flow)
                await q.answer(f"{'🟢 Enabled' if new_state else '🔴 Disabled'}")
            r = await _render_step(chat_id, flow_name, idx)
            if r:
                await _safe_edit(q, r[0], r[1])
            return

        # ────────── LAYOUT ──────────
        if action == "layout":
            idx = int(args[0]) if args else 0
            n = int(args[1]) if len(args) > 1 else 2
            flow = await get_flow_for(chat_id, flow_name)
            steps = flow.all_steps_sorted()
            if 0 <= idx < len(steps):
                set_step_field(flow, steps[idx]["type"], "per_row", n)
                await set_flow_for(chat_id, flow)
            await q.answer(f"✅ {n} per row")
            r = await _render_step(chat_id, flow_name, idx)
            if r:
                await _safe_edit(q, r[0], r[1])
            return

        # ────────── AUTOSKIP ──────────
        if action == "autoskip":
            idx = int(args[0]) if args else 0
            flow = await get_flow_for(chat_id, flow_name)
            steps = flow.all_steps_sorted()
            if 0 <= idx < len(steps):
                current = steps[idx].get("auto_skip_if_one", True)
                set_step_field(flow, steps[idx]["type"], "auto_skip_if_one", not current)
                await set_flow_for(chat_id, flow)
            await q.answer("✅ Toggled")
            r = await _render_step(chat_id, flow_name, idx)
            if r:
                await _safe_edit(q, r[0], r[1])
            return

        # ────────── MOVE UP ──────────
        if action == "moveup":
            idx = int(args[0]) if args else 0
            flow = await get_flow_for(chat_id, flow_name)
            steps = flow.all_steps_sorted()
            if 0 <= idx < len(steps):
                moved = move_step(flow, steps[idx]["type"], "up")
                if moved:
                    await set_flow_for(chat_id, flow)
                    idx -= 1
                    await q.answer("⬆️ Moved")
                else:
                    await q.answer("⚠️ Already at top")
            r = await _render_step(chat_id, flow_name, idx)
            if r:
                await _safe_edit(q, r[0], r[1])
            return

        # ────────── MOVE DOWN ──────────
        if action == "movedown":
            idx = int(args[0]) if args else 0
            flow = await get_flow_for(chat_id, flow_name)
            steps = flow.all_steps_sorted()
            if 0 <= idx < len(steps):
                moved = move_step(flow, steps[idx]["type"], "down")
                if moved:
                    await set_flow_for(chat_id, flow)
                    idx += 1
                    await q.answer("⬇️ Moved")
                else:
                    await q.answer("⚠️ Already at bottom")
            r = await _render_step(chat_id, flow_name, idx)
            if r:
                await _safe_edit(q, r[0], r[1])
            return

        # ────────── RESET STEP ──────────
        if action == "reset_step":
            idx = int(args[0]) if args else 0
            flow = await get_flow_for(chat_id, flow_name)
            steps = flow.all_steps_sorted()
            if 0 <= idx < len(steps):
                reset_step_to_default(flow, steps[idx]["type"])
                await set_flow_for(chat_id, flow)
            await q.answer("♻️ Reset")
            r = await _render_step(chat_id, flow_name, idx)
            if r:
                await _safe_edit(q, r[0], r[1])
            return

        # ────────── ADVANCED ──────────
        if action == "advanced":
            idx = int(args[0]) if args else 0
            r = await _render_advanced(chat_id, flow_name, idx)
            if r:
                await _safe_edit(q, r[0], r[1])
            return await q.answer()

        # ────────── MAX ITEMS ──────────
        if action == "maxitems":
            idx = int(args[0]) if args else 0
            n = int(args[1]) if len(args) > 1 else 10
            flow = await get_flow_for(chat_id, flow_name)
            steps = flow.all_steps_sorted()
            if 0 <= idx < len(steps):
                set_step_field(flow, steps[idx]["type"], "max_items", n)
                await set_flow_for(chat_id, flow)
            await q.answer(f"✅ Max {n}")
            r = await _render_advanced(chat_id, flow_name, idx)
            if r:
                await _safe_edit(q, r[0], r[1])
            return

        # ────────── PREVIEW ──────────
        if action == "preview":
            text, kb = await _render_preview(chat_id, flow_name)
            await _safe_edit(q, text, kb)
            return await q.answer()

        # ────────── RESET ALL ──────────
        if action == "reset_all":
            text = "\n".join([
                f"{F.EMO['warn']} <b>{F.fb('RESET FLOW?')}</b>",
                F.DIV,
                "",
                f"{F.EMO['warn']} {F.sc('all custom settings will be lost')}",
                f"{F.EMO['info']} {F.sc('flow will revert to defaults')}",
                "",
                F.DIV_S,
            ])
            kb = InlineKeyboardMarkup([
                [InlineKeyboardButton(
                    f"{F.EMO['cross']} {F.sc('yes, reset')}",
                    callback_data=cb("reset_do", flow_name),
                )],
                [InlineKeyboardButton(
                    f"{F.EMO['back']} {F.sc('cancel')}",
                    callback_data=cb("main", flow_name),
                )],
            ])
            await _safe_edit(q, text, kb)
            return await q.answer()

        if action == "reset_do":
            await delete_flow_for(chat_id, flow_name)
            await q.answer("♻️ Reset complete")
            text, kb = await _render_main(chat_id, flow_name)
            await _safe_edit(q, text, kb)
            return

    except Exception as e:
        logger.exception(f"[FLOW] callback error: {e}")
        try:
            await q.answer(f"❌ {e}"[:180], show_alert=True)
        except Exception:
            pass


# ============================================================
# SECTION 9 — SAFE EDIT
# ============================================================

async def _safe_edit(q: CallbackQuery, text: str, kb) -> None:
    try:
        await q.message.edit_text(
            text,
            reply_markup=kb,
            parse_mode=ParseMode.HTML,
            disable_web_page_preview=True,
        )
    except Exception as e:
        msg = str(e).lower()
        if "not modified" in msg:
            return
        logger.debug(f"[FLOW] edit: {e}")


# ============================================================
# SECTION 10 — SNAPSHOT
# ============================================================

def snapshot() -> Dict[str, Any]:
    return {
        "registered_steps": len(list_steps()),
        "registered_flows": len(list_flows()),
        "step_names": list_steps(),
    }


# ============================================================
# SECTION 11 — PUBLIC EXPORTS
# ============================================================

__all__ = [
    "snapshot",
]


# ============================================================
# END OF core/flow_engine.py — PART D/4 — FINAL
# ============================================================
