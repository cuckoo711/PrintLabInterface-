"""Create a PrintLab project from a proposal the person has just confirmed on the page.

This is the only place the sidecar writes into PrintLab on a person's behalf, so it is kept narrow:
  * the agent never writes. It can only *propose* (a block of text); the person clicks to confirm;
  * the request needs a login, the session's CSRF value and a same-origin request, like every other change;
  * the server re-checks every field itself and does not trust the page;
  * it runs exactly one PrintLab command, ``new``, through PrintLab's own CLI, never by writing files;
  * the same confirmation can only create one project (a repeat returns the project already made);
  * a project whose name matches an existing one is refused unless the person says it is meant;
  * every creation is written to the audit trail.
Nothing here approves, sends, slices, or touches the printer.
"""
from __future__ import annotations

import hashlib
import re
import sqlite3
import time

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from . import db
from .adapters.printlab.policy import PolicyError
from .adapters.printlab.runner import DirtyTreeError, RunnerError
from .security import require_admin

router = APIRouter(prefix="/api", dependencies=[Depends(require_admin)])

NAME_MAX = 80
BRIEF_MAX = 1500
KINDS = ("functional", "sculpture")
SCHEMA = """
CREATE TABLE IF NOT EXISTS created_projects (
    proposal_id TEXT PRIMARY KEY,
    project_id  TEXT NOT NULL,
    name        TEXT NOT NULL,
    created_at  REAL NOT NULL
);
"""
_BAD_NAME = re.compile(r"[\x00-\x1f\x7f<>|\"`$\\]")


class ProjectIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposal_id: str = Field(min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    name: str = Field(min_length=1, max_length=NAME_MAX)
    kind: str = "functional"
    brief: str = Field(default="", max_length=BRIEF_MAX)
    allow_same_name: bool = False


def clean_name(value: str) -> str:
    # Refuse odd characters in what was actually typed. Collapsing spaces first would quietly turn a line break into a space.
    if _BAD_NAME.search(value):
        raise ValueError("项目名里有不允许的字符")
    name = " ".join(value.split())
    if not name or name.startswith("-"):
        raise ValueError("项目名不能为空，也不能以“-”开头")
    return name


def clean_brief(value: str) -> str:
    text = value.replace("\r\n", "\n").strip()
    if any(ord(c) < 32 and c not in "\n\t" for c in text):
        raise ValueError("简介里有不允许的控制字符")
    return text


def _conn(request: Request) -> sqlite3.Connection:
    conn = db.connect(request.app.state.settings.db_path)
    conn.executescript(SCHEMA)
    return conn


def proposal_fingerprint(name: str, kind: str, brief: str) -> str:
    return hashlib.sha256(f"{name}\0{kind}\0{brief}".encode("utf-8")).hexdigest()[:16]


def _existing(runner) -> list[dict]:
    status = runner.run(["status"]).data
    rows = status.get("projects") if isinstance(status, dict) else None
    return rows if isinstance(rows, list) else []


@router.post("/projects", status_code=201)
def create_project(body: ProjectIn, request: Request):
    adapter = request.app.state.adapter
    runner = adapter.runner
    if runner is None or not runner.available():
        raise HTTPException(status_code=503, detail="PrintLab 现在不可用，没有建项目")
    if body.kind not in KINDS:
        raise HTTPException(status_code=422, detail=f"类型只能是 {' 或 '.join(KINDS)}")
    try:
        name, brief = clean_name(body.name), clean_brief(body.brief)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None

    conn = _conn(request)
    try:
        done = conn.execute("SELECT project_id, name FROM created_projects WHERE proposal_id = ?", (body.proposal_id,)).fetchone()
        if done:  # the same confirmation, pressed twice: hand back what was made, create nothing
            return {"project_id": done["project_id"], "name": done["name"], "created": False}
        try:
            same = [p for p in _existing(runner) if str(p.get("name", "")).strip().lower() == name.lower()]
        except (RunnerError, PolicyError) as exc:
            raise HTTPException(status_code=502, detail=f"读不到现有项目，没有建：{str(exc)[:120]}") from None
        if same and not body.allow_same_name:
            raise HTTPException(status_code=409, detail={"message": f"已经有一个叫“{name}”的项目（{same[0].get('id')}）", "existing": same[0].get("id")})
        argv = ["new", name, "--kind", body.kind]
        if brief:
            argv += ["--brief", brief]
        try:
            result = runner.run(argv, allow_write=True)
        except DirtyTreeError as exc:
            raise HTTPException(status_code=409, detail=f"PrintLab 的目录状态不干净，已停止写入：{str(exc)[:160]}") from None
        except (RunnerError, PolicyError) as exc:
            db.record_audit(conn, "admin", "project_create", name[:60], "error", str(exc)[:200])
            raise HTTPException(status_code=502, detail=f"建项目失败：{str(exc)[:160]}") from None
        data = result.data if isinstance(result.data, dict) else {}
        project_id = str(data.get("id") or "")
        if not re.fullmatch(r"P\d{3,}", project_id):
            db.record_audit(conn, "admin", "project_create", name[:60], "error", "PrintLab did not return a project id")
            raise HTTPException(status_code=502, detail="PrintLab 没有返回项目编号，请到 PrintLab 里确认是否已建")
        conn.execute("INSERT OR IGNORE INTO created_projects(proposal_id, project_id, name, created_at) VALUES(?,?,?,?)",
                     (body.proposal_id, project_id, name, time.time()))
        db.record_audit(conn, "admin", "project_create", project_id, "ok", f"name={name[:60]} kind={body.kind} brief={len(brief)} chars")
        return {"project_id": project_id, "name": data.get("name", name), "created": True}
    finally:
        conn.close()
