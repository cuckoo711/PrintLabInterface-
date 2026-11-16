"""Agent definition files and the capability ceiling they compile to.

A definition is a Markdown file with YAML frontmatter, one per role:

    ---
    name: sarah
    description: 3D-printing advisor
    model: deepseek:deepseek-chat        # optional; empty means "ask the caller"
    tools: [printlab_status, printlab_materials]
    max_turns: 6
    ---
    You are Sarah ...

Rules (the same shape the reference design uses, written from scratch):
  * the ceiling is computed once, when the file is loaded, and stored on the result;
  * a definition can only name tools that exist and that are read-only today;
  * anything wrong with a definition makes it fall back to NO tools, never to "all tools";
  * a parent may hand a child a ceiling that is a subset of its own, never a larger one.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from ..tools.registry import TOOLS

NAME = re.compile(r"[a-z][a-z0-9_-]{0,31}")
MAX_FILE_BYTES = 64_000
MAX_PROMPT_CHARS = 20_000
MAX_TURNS_LIMIT = 12
DEFAULT_TURNS = 6
ALLOWED_KEYS = {"name", "description", "model", "tools", "max_turns"}


@dataclass(frozen=True)
class Ceiling:
    """What an agent may do. Frozen so it cannot be widened after it is computed."""
    tools: frozenset[str] = frozenset()
    max_turns: int = DEFAULT_TURNS
    allow_write: bool = False  # no agent can write yet; the flag exists so widening is an explicit act

    def narrow(self, requested_tools: set[str] | frozenset[str] | None = None, max_turns: int | None = None) -> "Ceiling":
        """A child's ceiling: never larger than this one on any axis."""
        tools = self.tools if requested_tools is None else self.tools & frozenset(requested_tools)
        turns = self.max_turns if max_turns is None else max(1, min(self.max_turns, max_turns))
        return Ceiling(tools, turns, False)


@dataclass(frozen=True)
class AgentDefinition:
    name: str
    description: str
    model: str
    prompt: str
    ceiling: Ceiling
    source: str
    problems: tuple[str, ...] = field(default_factory=tuple)

    @property
    def degraded(self) -> bool:
        return bool(self.problems)


def _split(text: str) -> tuple[dict, str]:
    if not text.startswith("---"):
        raise ValueError("file must start with a '---' frontmatter block")
    parts = text.split("\n---", 1)
    if len(parts) != 2:
        raise ValueError("frontmatter block is not closed with '---'")
    head = parts[0][3:]
    body = parts[1].lstrip("\r\n-").lstrip("\n")
    data = yaml.safe_load(head) or {}  # safe_load: no object construction from the file
    if not isinstance(data, dict):
        raise ValueError("frontmatter must be a mapping")
    return data, body.strip()


def _degraded(name: str, source: str, problems: list[str], description: str = "", prompt: str = "") -> AgentDefinition:
    return AgentDefinition(name, description, "", prompt, Ceiling(frozenset(), 1, False), source, tuple(problems))


def parse(text: str, source: str = "<memory>") -> AgentDefinition:
    stem = Path(source).stem
    fallback_name = stem if NAME.fullmatch(stem) else "invalid"
    if len(text.encode("utf-8")) > MAX_FILE_BYTES:
        return _degraded(fallback_name, source, [f"file is larger than {MAX_FILE_BYTES} bytes"])
    try:
        data, body = _split(text)
    except (ValueError, yaml.YAMLError) as exc:
        return _degraded(fallback_name, source, [f"cannot read frontmatter: {str(exc).splitlines()[0][:120]}"])

    problems: list[str] = []
    unknown = set(data) - ALLOWED_KEYS
    if unknown:
        problems.append(f"unknown key(s) {sorted(unknown)}")
    name = data.get("name", fallback_name)
    if not isinstance(name, str) or not NAME.fullmatch(name):
        problems.append("name must be 1-32 chars: lowercase letters, digits, '-' or '_'")
        name = fallback_name
    description = data.get("description", "")
    if not isinstance(description, str) or len(description) > 300:
        problems.append("description must be text of at most 300 characters")
        description = ""
    model = data.get("model", "")
    if not isinstance(model, str) or len(model) > 200 or any(ord(c) < 32 for c in model):
        problems.append("model must be a short prefix:model string")
        model = ""
    if len(body) > MAX_PROMPT_CHARS:
        problems.append(f"prompt is longer than {MAX_PROMPT_CHARS} characters")
        body = body[:MAX_PROMPT_CHARS]

    raw_tools = data.get("tools", [])
    tools: set[str] = set()
    if not isinstance(raw_tools, list) or not all(isinstance(t, str) for t in raw_tools):
        problems.append("tools must be a list of tool names")
    else:
        for tool in raw_tools:
            spec = TOOLS.get(tool)
            if spec is None:
                problems.append(f"unknown tool '{tool}'")
            elif spec.tier != "read":
                problems.append(f"tool '{tool}' is not read-only and cannot be granted by a definition file")
            else:
                tools.add(tool)

    turns = data.get("max_turns", DEFAULT_TURNS)
    if isinstance(turns, bool) or not isinstance(turns, int) or not 1 <= turns <= MAX_TURNS_LIMIT:
        problems.append(f"max_turns must be an integer 1-{MAX_TURNS_LIMIT}")
        turns = 1

    if problems:
        # Fail closed: an invalid file never gets a partial or default-wide ceiling.
        return _degraded(name, source, problems, description, body)
    return AgentDefinition(name, description, model, body, Ceiling(frozenset(tools), turns, False), source)


def load_dir(directory: Path) -> dict[str, AgentDefinition]:
    """Load every `*.md` definition. A broken file is reported and degraded, never skipped silently."""
    found: dict[str, AgentDefinition] = {}
    if not directory.is_dir():
        return found
    for path in sorted(directory.glob("*.md")):
        if path.is_symlink() or not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            definition = _degraded(path.stem if NAME.fullmatch(path.stem) else "invalid", str(path), [f"cannot read file: {type(exc).__name__}"])
        else:
            definition = parse(text, str(path))
        key = definition.name
        if key in found:
            found[key] = _degraded(key, str(path), [f"duplicate agent name '{key}'"])
        else:
            found[key] = definition
    return found
