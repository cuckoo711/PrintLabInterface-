"""Tools the model may call. The model fills in validated values; it never writes a command line.

Each tool owns a fixed argv template. Arguments are checked against a small schema before
they are placed into the template, and the finished argv is checked again by the PrintLab
policy (which refuses anything dangerous no matter what the tool says). Two independent
layers, so a bug in one tool definition cannot reach the printer.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Callable

PROJECT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,63}$")
MODEL_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*(?: [A-Za-z0-9][A-Za-z0-9._-]*){0,2}")  # e.g. "H2C", "A1 mini", "X1 Carbon"
JOB_ID = PROJECT_ID


class ToolArgError(ValueError):
    pass


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    parameters: dict[str, Any]  # JSON schema sent to the model
    build_argv: Callable[[dict[str, Any]], list[str]]
    tier: str  # "read" | "write"

    def schema_for_model(self) -> dict[str, Any]:
        return {"type": "function", "function": {"name": self.name, "description": self.description, "parameters": self.parameters}}


def _check(args: Any, allowed: dict[str, Callable[[Any], Any]], required: set[str] = frozenset()) -> dict[str, Any]:
    if not isinstance(args, dict):
        raise ToolArgError("arguments must be an object")
    unknown = set(args) - set(allowed)
    if unknown:
        raise ToolArgError(f"unknown argument(s): {sorted(unknown)}")
    missing = required - set(args)
    if missing:
        raise ToolArgError(f"missing argument(s): {sorted(missing)}")
    return {k: allowed[k](v) for k, v in args.items()}


def _project(value: Any) -> str:
    if not isinstance(value, str) or not PROJECT_ID.fullmatch(value):
        raise ToolArgError("project must be an id such as P001 (letters, digits, '-' or '_')")
    return value


def _model(value: Any) -> str:
    if not isinstance(value, str) or len(value) > 40 or not MODEL_NAME.fullmatch(value):
        raise ToolArgError("model must be a short printer model name such as H2C")
    return value


def _enum(*options: str) -> Callable[[Any], str]:
    def check(value: Any) -> str:
        if value not in options:
            raise ToolArgError(f"must be one of {list(options)}")
        return value
    return check


def _bool(value: Any) -> bool:
    if not isinstance(value, bool):
        raise ToolArgError("must be true or false")
    return value


_NO_ARGS = {"type": "object", "properties": {}, "additionalProperties": False}


def _simple(command: list[str]) -> Callable[[dict[str, Any]], list[str]]:
    def build(args: dict[str, Any]) -> list[str]:
        _check(args, {})
        return list(command)
    return build


def _context(args: dict[str, Any]) -> list[str]:
    a = _check(args, {"project": _project})
    return ["context", *( [a["project"]] if "project" in a else [] )]


def _confirmation(args: dict[str, Any]) -> list[str]:
    a = _check(args, {"project": _project, "job": lambda v: _project(v)}, {"project"})
    return ["confirmation", a["project"], *( [a["job"]] if "job" in a else [] )]


def _dispatch_plan(args: dict[str, Any]) -> list[str]:
    a = _check(args, {"model": _model, "feeding": _enum("ams", "external", "unknown"),
                      "bambuddy_permission": _enum("unknown", "granted", "declined"), "keep_cloud": _bool})
    argv = ["dispatch-plan"]
    if "model" in a:
        argv += ["--model", a["model"]]
    if "feeding" in a:
        argv += ["--feeding", a["feeding"]]
    if "bambuddy_permission" in a:
        argv += ["--bambuddy-permission", a["bambuddy_permission"]]
    if a.get("keep_cloud"):
        argv.append("--keep-cloud")
    return argv


def _workspace_show(args: dict[str, Any]) -> list[str]:
    a = _check(args, {"document": _enum("profile", "taste", "lessons", "team", "device")}, {"document"})
    return ["workspace", "show", a["document"]]


def _shop_list(args: dict[str, Any]) -> list[str]:
    a = _check(args, {"project": _project})
    return ["shop", "list", *( [a["project"]] if "project" in a else [] )]


def _constraints_show(args: dict[str, Any]) -> list[str]:
    a = _check(args, {"project": _project}, {"project"})
    return ["constraints", "show", a["project"]]


def _profiles(args: dict[str, Any]) -> list[str]:
    a = _check(args, {"model": _model})
    return ["workspace", "profiles", *( ["--model", a["model"]] if "model" in a else [] )]


_PROJECT_PROP = {"type": "string", "description": "Project id, for example P001."}

TOOLS: dict[str, ToolSpec] = {t.name: t for t in [
    ToolSpec("printlab_status", "Current printer connection state and the list of projects. Read-only.", _NO_ARGS,
             _simple(["status"]), "read"),
    ToolSpec("printlab_materials", "Live filament slots and the shared inventory ledger. Remaining amounts are estimates unless marked measured. Read-only.",
             _NO_ARGS, _simple(["materials"]), "read"),
    ToolSpec("printlab_doctor", "Check that PrintLab's slicer, Blender, CAD python and offline inspector are available. Read-only.",
             _NO_ARGS, _simple(["doctor"]), "read"),
    ToolSpec("printlab_context", "Shared context for a project (brief, decisions, latest handoff). Without a project it lists the shared documents. Read-only.",
             {"type": "object", "properties": {"project": _PROJECT_PROP}, "additionalProperties": False}, _context, "read"),
    ToolSpec("printlab_confirmation", "The confirmation card for a project: preserved answers and what is still missing. Read-only.",
             {"type": "object", "properties": {"project": _PROJECT_PROP, "job": {"type": "string", "description": "Optional job id."}},
              "required": ["project"], "additionalProperties": False}, _confirmation, "read"),
    ToolSpec("printlab_dispatch_plan", "Advice on which sending route fits a printer model and feeding method. It never sends anything. Read-only.",
             {"type": "object", "properties": {
                 "model": {"type": "string", "description": "Printer model, for example H2C. Defaults to the saved device card."},
                 "feeding": {"type": "string", "enum": ["ams", "external", "unknown"]},
                 "bambuddy_permission": {"type": "string", "enum": ["unknown", "granted", "declined"]},
                 "keep_cloud": {"type": "boolean"}}, "additionalProperties": False}, _dispatch_plan, "read"),
    ToolSpec("printlab_workspace_show", "Read a shared workspace document (user profile, taste, lessons, team, or device card). Read-only.",
             {"type": "object", "properties": {"document": {"type": "string", "enum": ["profile", "taste", "lessons", "team", "device"]}},
              "required": ["document"], "additionalProperties": False}, _workspace_show, "read"),
    ToolSpec("printlab_shop_list", "The shared shopping list, optionally for one project. Read-only.",
             {"type": "object", "properties": {"project": _PROJECT_PROP}, "additionalProperties": False}, _shop_list, "read"),
    ToolSpec("printlab_constraints_show", "The device and material constraints captured for a project. Read-only.",
             {"type": "object", "properties": {"project": _PROJECT_PROP}, "required": ["project"], "additionalProperties": False},
             _constraints_show, "read"),
    ToolSpec("printlab_machine_profiles", "Official slicer presets installed for a printer model. Read-only.",
             {"type": "object", "properties": {"model": {"type": "string"}}, "additionalProperties": False}, _profiles, "read"),
    ToolSpec("printlab_prepared_list", "Print jobs that are prepared but not sent. Read-only; it cannot start or approve anything.",
             _NO_ARGS, _simple(["prepared", "list"]), "read"),
]}


def get(name: str) -> ToolSpec:
    try:
        return TOOLS[name]
    except KeyError:
        raise ToolArgError(f"unknown tool '{name}'") from None
