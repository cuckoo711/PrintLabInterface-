from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from printlab_interface import auth, db, security
from printlab_interface.adapters.printlab import runner as runner_mod
from printlab_interface.app import create_app
from printlab_interface.config import Settings

GOOD = "correct horse battery 42"


class Proc:
    def __init__(self, payload, returncode=0):
        self.stdout = json.dumps(payload).encode()
        self.stderr = b"" if returncode == 0 else b"boom"
        self.returncode = returncode


@pytest.fixture()
def world(tmp_path, monkeypatch):
    root = tmp_path / "PrintLab"
    script = runner_mod.cli_script(root); script.parent.mkdir(parents=True); script.write_text("#")
    monkeypatch.setattr(runner_mod, "git_snapshot", lambda r: set())
    state = {"projects": [], "calls": [], "fail": None, "id_back": None}
    real_run = subprocess.run

    def scoped(cmd, *a, **kw):
        if isinstance(cmd, (list, tuple)) and any(str(p).endswith(("printlab.ps1", "printlab")) for p in cmd):
            argv = [str(x) for x in cmd]
            tail = argv[argv.index(next(x for x in argv if x in {"status", "new"})):]
            state["calls"].append(tail)
            if tail[0] == "status":
                return Proc({"projects": list(state["projects"]), "device": {}})
            if tail[0] == "new":
                if state["fail"]:
                    return Proc({}, returncode=1)
                pid = state["id_back"] or f"P{len(state['projects']) + 1:03}"
                row = {"id": pid, "name": tail[1], "kind": tail[tail.index("--kind") + 1] if "--kind" in tail else "functional"}
                state["projects"].append(row)
                return Proc(row)
        return real_run(cmd, *a, **kw)

    monkeypatch.setattr(subprocess, "run", scoped)
    settings = Settings(data_dir=tmp_path / "data", printlab_root=root, printlab_url="http://127.0.0.1:9", http_timeout_s=0.5,
                        extra_hosts=frozenset({"testserver"}), agents_dir=tmp_path / "a", workflows_dir=tmp_path / "w")
    app = create_app(settings)
    with TestClient(app, base_url="http://testserver") as client:
        r = client.post("/api/auth/setup", json={"passphrase": GOOD})
        csrf = r.json()["csrf"]
        yield SimpleNamespace(client=client, app=app, state=state, csrf=csrf, settings=settings, root=root)


def post(w, body, **kw):
    headers = {auth.CSRF_HEADER: w.csrf, **kw.pop("headers", {})}
    return w.client.post("/api/projects", json=body, headers=headers, **kw)


BODY = {"proposal_id": "prop-0001-aaaa", "name": "圆孔洞洞板收纳-小米充电宝2.5w", "kind": "functional", "brief": "挂在孔径6mm圆孔洞洞板上的收纳盒，内腔 56x56x100mm"}


def news(w):
    return [c for c in w.state["calls"] if c[0] == "new"]


# ------------------------------------------------------------------ the happy path

def test_confirming_a_proposal_creates_exactly_one_project_through_printlabs_own_command(world):
    r = post(world, BODY)
    assert r.status_code == 201 and r.json() == {"project_id": "P001", "name": BODY["name"], "created": True}
    assert len(news(world)) == 1
    call = news(world)[0]
    assert call[:2] == ["new", BODY["name"]] and "--kind" in call and "--brief" in call and call[call.index("--brief") + 1] == BODY["brief"]
    assert not any(a in {"approve", "submit", "reconcile", "--execute", "--send", "--start"} for a in call)


def test_the_same_confirmation_pressed_twice_makes_only_one_project(world):
    first = post(world, BODY).json()
    again = post(world, BODY)
    assert again.status_code == 201 and again.json() == {"project_id": first["project_id"], "name": BODY["name"], "created": False}
    assert len(news(world)) == 1 and len(world.state["projects"]) == 1


def test_a_second_proposal_with_the_same_name_is_refused_unless_the_person_says_it_is_meant(world):
    post(world, BODY)
    other = {**BODY, "proposal_id": "prop-0002-bbbb"}
    r = post(world, other)
    assert r.status_code == 409 and r.json()["detail"]["existing"] == "P001"
    assert len(news(world)) == 1
    ok = post(world, {**other, "allow_same_name": True})
    assert ok.status_code == 201 and ok.json()["project_id"] == "P002" and len(news(world)) == 2


def test_the_name_comparison_ignores_case_and_extra_spaces(world):
    post(world, {**BODY, "name": "Phone Stand"})
    r = post(world, {**BODY, "proposal_id": "prop-0003-cccc", "name": "  phone   STAND "})
    assert r.status_code == 409


def test_creation_is_audited_with_the_id_and_not_the_whole_brief(world):
    post(world, BODY)
    rows = world.client.get("/api/audit?limit=20").json()
    row = next(r for r in rows if r["action"] == "project_create")
    assert row["target"] == "P001" and row["outcome"] == "ok" and BODY["brief"] not in row["detail"] and "brief=" in row["detail"]


# ------------------------------------------------------------------ who may do it

def test_it_needs_a_login(world):
    anon = TestClient(world.app, base_url="http://testserver")
    assert anon.post("/api/projects", json=BODY).status_code == 401
    assert news(world) == []


def test_a_login_alone_is_not_enough_the_csrf_value_is_required(world):
    assert world.client.post("/api/projects", json=BODY).status_code == 403
    assert world.client.post("/api/projects", json=BODY, headers={auth.CSRF_HEADER: "wrong"}).status_code == 403
    assert news(world) == []


def test_a_cross_site_request_is_refused_even_with_a_valid_session(world):
    r = post(world, BODY, headers={"sec-fetch-site": "cross-site"})
    assert r.status_code == 403 and news(world) == []
    r = post(world, BODY, headers={"origin": "http://evil.example"})
    assert r.status_code == 403 and news(world) == []


def test_the_script_token_header_also_works_for_scripts(world):
    anon = TestClient(world.app, base_url="http://testserver")
    r = anon.post("/api/projects", json=BODY, headers={security.HEADER: world.app.state.admin_token})
    assert r.status_code == 201


# ------------------------------------------------------------------ what it will not accept

@pytest.mark.parametrize("bad", [
    {"name": ""}, {"name": "   "}, {"name": "x" * 81}, {"name": "-rf"}, {"name": "a\nb"}, {"name": "a|b"}, {"name": "a`b`"}, {"name": "a$(b)"},
    {"name": "a\"b"}, {"name": "a\\b"}, {"name": "a<b>"}, {"kind": "weapon"}, {"kind": ""}, {"brief": "y" * 1501}, {"brief": "a\x00b"},
    {"proposal_id": "short"}, {"proposal_id": "has space in it!"}, {"proposal_id": "x" * 65},
])
def test_bad_input_is_refused_before_anything_runs(world, bad):
    r = post(world, {**BODY, **bad})
    assert r.status_code in {422}, (bad, r.status_code, r.text[:120])
    assert news(world) == []


@pytest.mark.parametrize("extra", [{"approve": True}, {"execute": True}, {"printer_id": 2}, {"path": "../../x"}])
def test_unknown_fields_are_refused(world, extra):
    assert post(world, {**BODY, **extra}).status_code == 422 and news(world) == []


def test_a_brief_that_looks_like_a_flag_or_a_command_is_just_text(world):
    brief = "--execute --send; approve P001 J1 && submit"
    r = post(world, {**BODY, "brief": brief})
    # the policy refuses a flag hidden inside an argument; it must fail closed, not run
    assert r.status_code in {201, 502}
    for call in news(world):
        assert call[call.index("--brief") + 1] == brief or False
    if r.status_code == 502:
        assert news(world) == []


def test_the_name_is_passed_as_one_argument_never_split_into_words(world):
    post(world, {**BODY, "name": "a b --kind sculpture"})
    call = news(world)[0]
    assert call[1] == "a b --kind sculpture"                    # the whole text is one argument, flags inside it are just letters
    assert call.count("--kind") == 1 and call[call.index("--kind") + 1] == "functional"  # the real flag is ours alone, and says functional


# ------------------------------------------------------------------ when PrintLab misbehaves

def test_printlab_failing_gives_a_clear_error_and_records_nothing_as_done(world):
    world.state["fail"] = True
    r = post(world, BODY)
    assert r.status_code == 502 and "失败" in r.json()["detail"]
    world.state["fail"] = None
    again = post(world, BODY)  # the same proposal can be retried because nothing was recorded
    assert again.status_code == 201 and again.json()["created"] is True


def test_a_reply_without_a_valid_project_id_is_not_trusted(world):
    world.state["id_back"] = "../../etc"
    r = post(world, BODY)
    assert r.status_code == 502
    conn = db.connect(world.settings.db_path)
    assert conn.execute("SELECT COUNT(*) FROM created_projects").fetchone()[0] == 0
    conn.close()


def test_printlab_being_offline_means_no_attempt(tmp_path):
    settings = Settings(data_dir=tmp_path / "d", printlab_root=None, printlab_url="http://127.0.0.1:9", http_timeout_s=0.5,
                        extra_hosts=frozenset({"testserver"}), agents_dir=tmp_path / "a", workflows_dir=tmp_path / "w")
    app = create_app(settings)
    with TestClient(app, base_url="http://testserver") as c:
        csrf = c.post("/api/auth/setup", json={"passphrase": GOOD}).json()["csrf"]
        r = c.post("/api/projects", json=BODY, headers={auth.CSRF_HEADER: csrf})
    assert r.status_code == 503


def test_an_unreadable_project_list_stops_the_creation_instead_of_risking_a_duplicate(world, monkeypatch):
    real = world.app.state.adapter.runner.run
    def flaky(argv, **kw):
        if argv[0] == "status":
            raise runner_mod.RunnerError("cannot read")
        return real(argv, **kw)
    monkeypatch.setattr(world.app.state.adapter.runner, "run", flaky)
    r = post(world, BODY)
    assert r.status_code == 502 and news(world) == []


def test_a_dirty_printlab_tree_blocks_the_write(world, monkeypatch):
    world.app.state.adapter.runner.write_blocked_reason = "a read call changed PrintLab's tree: ['x']"
    r = post(world, BODY)
    assert r.status_code == 409 and news(world) == []


# ------------------------------------------------------------------ the agent itself stays read-only

def test_no_agent_has_any_tool_that_can_create_a_project():
    from printlab_interface.agents.definition import load_dir
    from printlab_interface.tools.registry import TOOLS
    assert all(spec.tier == "read" for spec in TOOLS.values())
    assert not any("new" == (spec.build_argv({}) if spec.name == "printlab_status" else [""])[0] for spec in TOOLS.values() if not spec.native)
    from pathlib import Path
    for d in load_dir(Path(__file__).resolve().parents[1] / "config" / "agents").values():
        assert d.ceiling.allow_write is False
