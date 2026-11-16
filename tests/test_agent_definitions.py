from __future__ import annotations

from pathlib import Path

import pytest

from printlab_interface.agents.definition import Ceiling, DEFAULT_TURNS, MAX_FILE_BYTES, load_dir, parse
from printlab_interface.config import REPO_ROOT
from printlab_interface.tools.registry import TOOLS

GOOD = """---
name: tester
description: a test agent
model: oa:gpt-4o-mini
tools: [printlab_status, printlab_materials]
max_turns: 4
---
You are a test agent.
"""


def test_a_valid_definition_compiles_to_exactly_its_declared_ceiling():
    d = parse(GOOD, "tester.md")
    assert not d.degraded and d.problems == ()
    assert d.name == "tester" and d.model == "oa:gpt-4o-mini" and d.prompt == "You are a test agent."
    assert d.ceiling == Ceiling(frozenset({"printlab_status", "printlab_materials"}), 4, False)


def test_missing_optional_fields_default_to_no_tools_not_all_tools():
    d = parse("---\nname: bare\n---\nhello", "bare.md")
    assert not d.degraded and d.ceiling.tools == frozenset() and d.ceiling.max_turns == DEFAULT_TURNS


@pytest.mark.parametrize(
    "text,fragment",
    [
        ("no frontmatter at all", "frontmatter"),
        ("---\nname: x\nno closing marker", "not closed"),
        ("---\n- a\n- b\n---\nbody", "mapping"),
        ("---\nname: [unclosed\n---\nbody", "cannot read frontmatter"),
        ("---\nname: Bad Name\n---\nb", "name must be"),
        ("---\nname: x\ntools: [printlab_nope]\n---\nb", "unknown tool"),
        ("---\nname: x\ntools: printlab_status\n---\nb", "list of tool names"),
        ("---\nname: x\ntools: [1, 2]\n---\nb", "list of tool names"),
        ("---\nname: x\nmax_turns: 99\n---\nb", "max_turns"),
        ("---\nname: x\nmax_turns: true\n---\nb", "max_turns"),
        ("---\nname: x\nmax_turns: 0\n---\nb", "max_turns"),
        ("---\nname: x\nsurprise: 1\n---\nb", "unknown key"),
        ("---\nname: x\nmodel: " + "m" * 300 + "\n---\nb", "model must"),
        ("---\nname: x\ndescription: " + "d" * 400 + "\n---\nb", "description"),
    ],
)
def test_any_problem_degrades_to_zero_tools_and_one_turn(text, fragment):
    d = parse(text, "x.md")
    assert d.degraded and fragment in " ".join(d.problems)
    assert d.ceiling.tools == frozenset() and d.ceiling.max_turns == 1 and d.ceiling.allow_write is False


def test_a_good_tool_list_is_dropped_entirely_when_another_part_is_bad():
    d = parse("---\nname: x\ntools: [printlab_status]\nmax_turns: 500\n---\nb", "x.md")
    assert d.degraded and d.ceiling.tools == frozenset()  # no partial credit


def test_write_tools_cannot_be_granted_from_a_file(monkeypatch):
    from dataclasses import replace
    monkeypatch.setitem(TOOLS, "printlab_fake_write", replace(TOOLS["printlab_status"], name="printlab_fake_write", tier="write"))
    d = parse("---\nname: x\ntools: [printlab_fake_write]\n---\nb", "x.md")
    assert d.degraded and "not read-only" in " ".join(d.problems) and d.ceiling.tools == frozenset()


def test_yaml_cannot_construct_python_objects():
    evil = "---\nname: x\ndescription: !!python/object/apply:os.system ['echo pwned']\n---\nb"
    d = parse(evil, "x.md")
    assert d.degraded and "pwned" not in " ".join(d.problems)


def test_oversized_files_are_refused_before_parsing():
    d = parse("---\nname: x\n---\n" + "a" * (MAX_FILE_BYTES + 1), "x.md")
    assert d.degraded and "larger than" in d.problems[0]


def test_overlong_prompt_is_cut_and_flagged():
    d = parse("---\nname: x\n---\n" + "a" * 30_000, "x.md")
    assert d.degraded and len(d.prompt) == 20_000


def test_name_falls_back_to_the_file_name_only_when_it_is_valid():
    assert parse("---\ndescription: d\n---\nb", "alice.md").name == "alice"
    assert parse("---\ndescription: d\n---\nb", "Bad File.md").name == "invalid"


# ---- ceiling arithmetic ---------------------------------------------------
def test_narrow_never_widens_on_any_axis():
    parent = Ceiling(frozenset({"a", "b"}), 5, False)
    assert parent.narrow({"a", "c"}).tools == frozenset({"a"})  # "c" was never granted
    assert parent.narrow(None).tools == parent.tools
    assert parent.narrow(max_turns=99).max_turns == 5 and parent.narrow(max_turns=2).max_turns == 2
    assert parent.narrow(max_turns=0).max_turns == 1
    assert parent.narrow({"zzz"}).tools == frozenset()


def test_ceiling_is_immutable():
    c = Ceiling(frozenset({"a"}), 3)
    with pytest.raises(Exception):
        c.tools = frozenset({"a", "b"})  # type: ignore[misc]
    with pytest.raises(Exception):
        c.allow_write = True  # type: ignore[misc]


# ---- loading a directory --------------------------------------------------
def test_load_dir_reports_broken_files_instead_of_hiding_them(tmp_path):
    (tmp_path / "ok.md").write_text(GOOD.replace("tester", "ok"), encoding="utf-8")
    (tmp_path / "broken.md").write_text("garbage", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("ignored", encoding="utf-8")
    found = load_dir(tmp_path)
    assert set(found) == {"ok", "broken"} and found["broken"].degraded and not found["ok"].degraded


def test_duplicate_names_degrade_the_later_file(tmp_path):
    (tmp_path / "a.md").write_text(GOOD, encoding="utf-8")
    (tmp_path / "b.md").write_text(GOOD, encoding="utf-8")  # same name: tester
    found = load_dir(tmp_path)
    assert found["tester"].degraded and "duplicate" in found["tester"].problems[0]


def test_missing_directory_is_empty_not_an_error(tmp_path):
    assert load_dir(tmp_path / "nope") == {}


def test_undecodable_file_is_degraded(tmp_path):
    (tmp_path / "bin.md").write_bytes(b"\xff\xfe\x00bad")
    assert load_dir(tmp_path)["bin"].degraded


# ---- the files that actually ship ----------------------------------------
@pytest.fixture(scope="module")
def shipped():
    return load_dir(REPO_ROOT / "config" / "agents")


def test_shipped_roles_load_cleanly(shipped):
    assert {"sarah", "mike", "project"} <= set(shipped)
    for name, d in shipped.items():
        assert not d.degraded, (name, d.problems)


def test_shipped_roles_hold_only_existing_read_only_tools(shipped):
    for d in shipped.values():
        assert d.ceiling.tools <= set(TOOLS) and all(TOOLS[t].tier == "read" for t in d.ceiling.tools)
        assert d.ceiling.allow_write is False and 1 <= d.ceiling.max_turns <= 12


def test_shipped_prompts_carry_the_safety_rules(shipped):
    for name, d in shipped.items():
        text = " ".join(d.prompt.lower().split())  # collapse line breaks so wrapped sentences still match
        # Every role must forbid claiming print actions, in plain words.
        assert "never claim" in text and "print" in text and ("approve" in text or "send" in text), name
        # Every role must treat tool output as data, not instructions.
        assert "tool results is data" in text and "ignore them" in text, f"{name} must tell the model tool output is data"
        for banned in ("approve a print for", "you can send", "i will start the print"):
            assert banned not in text, (name, banned)


def test_shipped_prompts_never_mention_a_tool_the_role_does_not_hold(shipped):
    for name, d in shipped.items():
        for tool in TOOLS:
            if tool in d.prompt:
                assert tool in d.ceiling.tools, f"{name} prompt names {tool} but cannot call it"
