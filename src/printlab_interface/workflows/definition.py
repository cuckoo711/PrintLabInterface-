"""Workflow definitions (YAML) and their validation.

A workflow is an ordered list of stages. There is no free-form branching: the shape is fixed
so that every path can be reasoned about and tested.

Stage kinds:
  agent     run one agent definition with a prompt template; the model's text becomes that stage's output
  evidence  run ONE read-only PrintLab command; code (not the model) decides pass/fail from the JSON it returns
  human     stop and wait for a person to answer yes/no
  handoff   last stage; ends the workflow and tells the person what to do next by hand

Rules enforced here, so a bad file can never run:
  * an evidence command must classify as READ under the PrintLab policy;
  * templates may only use {project}, {brief} and {out:<earlier stage id>}; they are filled by plain
    substitution, never str.format, so no attribute or index access is possible;
  * nothing may follow a handoff, and the handoff is mandatory: a workflow always ends with a person;
  * any problem rejects the whole file (there is no partial or "best effort" workflow).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from ..adapters.printlab.policy import check_cli
from ..agents.definition import AgentDefinition

NAME = re.compile(r"[a-z][a-z0-9_-]{0,31}")
STAGE_ID = re.compile(r"[a-z][a-z0-9_]{0,31}")
FIELD_PATH = re.compile(r"[A-Za-z_][A-Za-z0-9_]{0,40}(?:\.[A-Za-z_][A-Za-z0-9_]{0,40}){0,5}")
PLACEHOLDER = re.compile(r"\{(project|brief|out:[a-z][a-z0-9_]{0,31})\}")
ANY_BRACE = re.compile(r"[{}]")
MAX_FILE_BYTES = 64_000
MAX_STAGES = 20
MAX_TEXT = 4000
KINDS = {"agent", "evidence", "human", "handoff"}
KEYS = {
    "agent": {"id", "kind", "agent", "prompt"},
    "evidence": {"id", "kind", "command", "pass_when"},
    "human": {"id", "kind", "question", "show"},
    "handoff": {"id", "kind", "message"},
}
TOP_KEYS = {"name", "description", "model", "stages"}


class DefinitionError(ValueError):
    pass


@dataclass(frozen=True)
class Stage:
    id: str
    kind: str
    agent: str = ""
    prompt: str = ""
    command: tuple[str, ...] = ()
    field: str = ""
    equals: Any = None
    question: str = ""
    show: tuple[str, ...] = ()
    message: str = ""


@dataclass(frozen=True)
class WorkflowDefinition:
    name: str
    description: str
    model: str
    stages: tuple[Stage, ...]
    source: str
    problems: tuple[str, ...] = field(default_factory=tuple)

    @property
    def valid(self) -> bool:
        return not self.problems

    @property
    def needs_project(self) -> bool:
        texts = [s.prompt for s in self.stages] + [a for s in self.stages for a in s.command]
        return any("{project}" in t for t in texts)

    def stage(self, stage_id: str) -> Stage:
        return next(s for s in self.stages if s.id == stage_id)


def _text(value: Any, label: str, problems: list[str], *, required: bool = True) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str) or (required and not value.strip()) or len(value) > MAX_TEXT or "\x00" in value:
        problems.append(f"{label} must be non-empty text of at most {MAX_TEXT} characters")
        return ""
    return value


def _check_template(text: str, label: str, earlier: set[str], problems: list[str]) -> None:
    stripped = PLACEHOLDER.sub("", text)
    if ANY_BRACE.search(stripped):
        problems.append(f"{label} has a '{{' or '}}' that is not one of {{project}}, {{brief}}, {{out:<stage>}}")
    for ref in PLACEHOLDER.findall(text):
        if ref.startswith("out:") and ref[4:] not in earlier:
            problems.append(f"{label} refers to '{ref[4:]}', which is not an earlier stage")


def parse(text: str, source: str, agents: dict[str, AgentDefinition]) -> WorkflowDefinition:
    stem = Path(source).stem
    fallback = stem if NAME.fullmatch(stem) else "invalid"

    def bad(problems: list[str], name: str = fallback) -> WorkflowDefinition:
        return WorkflowDefinition(name, "", "", (), source, tuple(problems))

    if len(text.encode("utf-8")) > MAX_FILE_BYTES:
        return bad([f"file is larger than {MAX_FILE_BYTES} bytes"])
    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        return bad([f"cannot read YAML: {str(exc).splitlines()[0][:120]}"])
    if not isinstance(data, dict):
        return bad(["the file must be a mapping"])

    problems: list[str] = []
    if set(data) - TOP_KEYS:
        problems.append(f"unknown top-level key(s) {sorted(set(data) - TOP_KEYS)}")
    name = data.get("name", fallback)
    if not isinstance(name, str) or not NAME.fullmatch(name):
        problems.append("name must be 1-32 chars: lowercase letters, digits, '-' or '_'")
        name = fallback
    description = data.get("description", "")
    if not isinstance(description, str) or len(description) > 300:
        problems.append("description must be text of at most 300 characters")
        description = ""
    model = data.get("model", "")
    if not isinstance(model, str) or len(model) > 200 or any(ord(c) < 32 for c in model):
        problems.append("model must be a short prefix:model string or empty")
        model = ""

    raw_stages = data.get("stages")
    if not isinstance(raw_stages, list) or not raw_stages:
        return bad(problems + ["stages must be a non-empty list"], name)
    if len(raw_stages) > MAX_STAGES:
        return bad(problems + [f"at most {MAX_STAGES} stages"], name)

    stages: list[Stage] = []
    seen: set[str] = set()
    for index, raw in enumerate(raw_stages):
        where = f"stage {index + 1}"
        if not isinstance(raw, dict):
            problems.append(f"{where} must be a mapping")
            continue
        stage_id = raw.get("id")
        if not isinstance(stage_id, str) or not STAGE_ID.fullmatch(stage_id) or "__" in stage_id:
            problems.append(f"{where}: id must be lowercase letters, digits, single '_' (max 32)")
            continue
        where = f"stage '{stage_id}'"
        if stage_id in seen:
            problems.append(f"{where}: duplicate id")
            continue
        kind = raw.get("kind")
        if kind not in KINDS:
            problems.append(f"{where}: kind must be one of {sorted(KINDS)}")
            seen.add(stage_id)
            continue
        extra = set(raw) - KEYS[kind]
        if extra:
            problems.append(f"{where}: unknown key(s) {sorted(extra)} for kind '{kind}'")

        if kind == "agent":
            agent_name = raw.get("agent")
            prompt = _text(raw.get("prompt"), f"{where}: prompt", problems)
            if not isinstance(agent_name, str) or agent_name not in agents:
                problems.append(f"{where}: unknown agent '{agent_name}'")
            elif agents[agent_name].degraded:
                problems.append(f"{where}: agent '{agent_name}' has an invalid definition")
            _check_template(prompt, f"{where}: prompt", seen, problems)
            stages.append(Stage(stage_id, kind, agent=str(agent_name), prompt=prompt))
        elif kind == "evidence":
            command = raw.get("command")
            when = raw.get("pass_when")
            argv: tuple[str, ...] = ()
            if not isinstance(command, list) or not command or len(command) > 8 or not all(isinstance(c, str) and c and len(c) <= 200 for c in command):
                problems.append(f"{where}: command must be a short list of non-empty strings")
            else:
                argv = tuple(command)
                for arg in argv:
                    _check_template(arg, f"{where}: command", set(), problems)
                    if "{out:" in arg or "{brief}" in arg:
                        problems.append(f"{where}: a command may only use {{project}}, never model text or the brief")
                probe = [a.replace("{project}", "P000") for a in argv]
                try:
                    # check_cli, not classify: it also refuses execution flags and control characters.
                    verdict = check_cli(probe, allow_write=False)
                except PermissionError as exc:
                    problems.append(f"{where}: command refused ({exc})")
                else:
                    if not verdict.allowed or verdict.tier != "read":
                        problems.append(f"{where}: command must be read-only; policy says '{verdict.tier}' ({verdict.reason})")
            fld, eq = "", None
            if not isinstance(when, dict) or set(when) != {"field", "equals"}:
                problems.append(f"{where}: pass_when must be a mapping with exactly 'field' and 'equals'")
            else:
                fld, eq = when["field"], when["equals"]
                if not isinstance(fld, str) or not FIELD_PATH.fullmatch(fld):
                    problems.append(f"{where}: pass_when.field must be a dotted name such as 'status'")
                    fld = ""
                if isinstance(eq, bool) or not isinstance(eq, (str, int)) or (isinstance(eq, str) and len(eq) > 100):
                    if not isinstance(eq, bool):
                        problems.append(f"{where}: pass_when.equals must be a short string, integer or boolean")
            stages.append(Stage(stage_id, kind, command=argv, field=fld, equals=eq))
        elif kind == "human":
            question = _text(raw.get("question"), f"{where}: question", problems)
            show = raw.get("show", [])
            if not isinstance(show, list) or not all(isinstance(x, str) and x in seen for x in show):
                problems.append(f"{where}: show must list earlier stage ids")
                show = []
            stages.append(Stage(stage_id, kind, question=question, show=tuple(show)))
        else:  # handoff
            message = _text(raw.get("message"), f"{where}: message", problems)
            _check_template(message, f"{where}: message", seen, problems)
            stages.append(Stage(stage_id, kind, message=message))
        seen.add(stage_id)

    kinds = [s.kind for s in stages]
    if "handoff" not in kinds:
        problems.append("the last stage must be a handoff (a workflow always ends with a person)")
    elif kinds.index("handoff") != len(raw_stages) - 1 or kinds.count("handoff") != 1:
        problems.append("a handoff must be the single, last stage")

    if problems:
        return bad(problems, name)  # fail closed: no stages survive
    return WorkflowDefinition(name, description, model, tuple(stages), source)


def load_dir(directory: Path, agents: dict[str, AgentDefinition]) -> dict[str, WorkflowDefinition]:
    found: dict[str, WorkflowDefinition] = {}
    if not directory.is_dir():
        return found
    for path in sorted(list(directory.glob("*.yaml")) + list(directory.glob("*.yml"))):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            wf = WorkflowDefinition(path.stem if NAME.fullmatch(path.stem) else "invalid", "", "", (), str(path), (f"cannot read file: {type(exc).__name__}",))
        else:
            wf = parse(text, str(path), agents)
        if wf.name in found:
            wf = WorkflowDefinition(wf.name, "", "", (), str(path), (f"duplicate workflow name '{wf.name}'",))
        found[wf.name] = wf
    return found


def render(template: str, *, project: str, brief: str, outputs: dict[str, str], limit: int = 3000) -> str:
    """Plain substitution. Prior model output is wrapped as data and length-limited."""
    def fill(match: re.Match) -> str:
        key = match.group(1)
        if key == "project":
            return project
        if key == "brief":
            return brief
        text = outputs.get(key[4:], "")
        text = text[:limit].replace("</stage-output>", "<\\/stage-output>")
        return f"<stage-output id=\"{key[4:]}\">{text}</stage-output>"

    return PLACEHOLDER.sub(fill, template)
