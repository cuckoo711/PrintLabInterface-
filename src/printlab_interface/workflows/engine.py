"""Workflow engine: runs a WorkflowDefinition on LangGraph with SQLite checkpoints.

Two stores, deliberately separate:
  * the checkpoint file (LangGraph's own): where the graph is paused and what each stage produced;
  * a small `workflow_runs` table in interface.db: what the UI shows and what the engine uses to
    refuse bad requests (resume of an unknown run, a second answer, two things at once).
LangGraph does not reject a resume of an unknown thread, so every public method checks the table first.

Rules:
  * a node that calls a model or runs a command never contains the `interrupt` call, and the
    `interrupt` node does nothing else (a resumed node re-runs from its top);
  * a stage that fails does not move the run forward; the run stops in a state a person can see;
  * `start` is idempotent per request_id; `answer` is idempotent per run + stage;
  * there is no automatic way past a `human` stage and no stage kind that can approve or send a print.
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, TypedDict

from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from .. import db, settings_store
from ..adapters.printlab.policy import PolicyError
from ..adapters.printlab.runner import PrintLabRunner, RunnerError
from ..agents.definition import AgentDefinition
from ..agents.loop import AgentRunner
from ..redact import redact
from .definition import Stage, WorkflowDefinition, render

SCHEMA = """
CREATE TABLE IF NOT EXISTS workflow_runs (
    id            TEXT PRIMARY KEY,
    request_id    TEXT UNIQUE,
    workflow      TEXT NOT NULL,
    project       TEXT NOT NULL DEFAULT '',
    brief         TEXT NOT NULL DEFAULT '',
    model         TEXT NOT NULL DEFAULT '',
    status        TEXT NOT NULL,
    stage         TEXT NOT NULL DEFAULT '',
    detail        TEXT NOT NULL DEFAULT '',
    outputs_json  TEXT NOT NULL DEFAULT '{}',
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS workflow_answers (
    run_id     TEXT NOT NULL REFERENCES workflow_runs(id) ON DELETE CASCADE,
    stage      TEXT NOT NULL,
    answer     TEXT NOT NULL,
    at         REAL NOT NULL,
    PRIMARY KEY (run_id, stage)
);
"""
STATUSES = {"running", "waiting", "blocked", "failed", "finished", "stopped", "interrupted"}
MAX_BRIEF = 4000
MAX_OUTPUT = 12_000
PROJECT_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,63}")
REQUEST_ID = re.compile(r"[A-Za-z0-9_.:-]{8,80}")
MAX_ACTIVE = 4


class EngineError(Exception):
    def __init__(self, message: str, status: int = 400):
        super().__init__(message)
        self.status = status


class StageBlocked(Exception):
    """Raised by a stage that cannot complete. LangGraph leaves its checkpoint pointing AT this stage,
    so a retry re-runs exactly this stage and nothing before it."""


class GraphState(TypedDict, total=False):
    outputs: dict[str, str]
    stop: str


@dataclass
class RunView:
    id: str
    workflow: str
    project: str
    status: str
    stage: str
    detail: str
    outputs: dict[str, str]
    waiting_for: dict[str, Any] | None
    created_at: float
    updated_at: float

    def as_dict(self) -> dict:
        return {k: getattr(self, k) for k in ("id", "workflow", "project", "status", "stage", "detail", "outputs", "waiting_for", "created_at", "updated_at")}


def _dig(data: Any, dotted: str) -> Any:
    for part in dotted.split("."):
        if not isinstance(data, dict) or part not in data:
            return None
        data = data[part]
    return data


class WorkflowEngine:
    def __init__(self, db_path: Path, checkpoint_path: Path, agents: dict[str, AgentDefinition], runner: AgentRunner,
                 printlab: PrintLabRunner | None, workflows: dict[str, WorkflowDefinition]):
        self.db_path = db_path
        self.checkpoint_path = checkpoint_path
        self.agents = agents
        self.agent_runner = runner
        self.printlab = printlab
        self.workflows = workflows
        self._lock = threading.Lock()
        self._busy: set[str] = set()  # run ids with a step in progress in THIS process

    # ---- storage ---------------------------------------------------------
    def _conn(self) -> sqlite3.Connection:
        conn = db.connect(self.db_path)
        conn.executescript(SCHEMA)
        return conn

    def _row(self, conn: sqlite3.Connection, run_id: str) -> sqlite3.Row:
        row = conn.execute("SELECT * FROM workflow_runs WHERE id=?", (run_id,)).fetchone()
        if row is None:
            raise EngineError("unknown workflow run", 404)
        return row

    def _update(self, run_id: str, **fields: Any) -> None:
        if "status" in fields and fields["status"] not in STATUSES:
            raise ValueError(fields["status"])
        if "detail" in fields:
            fields["detail"] = redact(str(fields["detail"]))[:500]
        if "outputs" in fields:
            fields["outputs_json"] = json.dumps(fields.pop("outputs"), ensure_ascii=False)
        fields["updated_at"] = time.time()
        conn = self._conn()
        try:
            cols = ", ".join(f"{k}=?" for k in fields)
            conn.execute(f"UPDATE workflow_runs SET {cols} WHERE id=?", (*fields.values(), run_id))
        finally:
            conn.close()

    def recover(self) -> int:
        """After a restart nothing is really running; show that honestly. A person can continue them."""
        conn = self._conn()
        try:
            return conn.execute("UPDATE workflow_runs SET status='interrupted', detail='the service restarted while this step was running', updated_at=? "
                                "WHERE status='running'", (time.time(),)).rowcount
        finally:
            conn.close()

    # ---- the graph -------------------------------------------------------
    def _build(self, wf: WorkflowDefinition, run_id: str, saver: SqliteSaver):
        graph = StateGraph(GraphState)

        def make_node(stage: Stage) -> Callable[[GraphState], GraphState]:
            def node(state: GraphState) -> GraphState:
                if state.get("stop"):
                    return {}
                outputs = dict(state.get("outputs") or {})
                run = self.view(run_id)
                self._update(run_id, status="running", stage=stage.id, detail="")
                if stage.kind == "agent":
                    return self._agent_stage(stage, run, outputs)
                if stage.kind == "evidence":
                    return self._evidence_stage(stage, run, outputs)
                if stage.kind == "handoff":
                    message = render(stage.message, project=run.project, brief=self._brief(run_id), outputs=outputs)
                    outputs[stage.id] = message[:MAX_OUTPUT]
                    return {"outputs": outputs}
                raise AssertionError("human stages use their own node")
            return node

        def make_human(stage: Stage) -> Callable[[GraphState], GraphState]:
            def node(state: GraphState) -> GraphState:
                if state.get("stop"):
                    return {}
                # Nothing else happens here: this node is re-run from the top when the interrupt resumes.
                answer = interrupt({"stage": stage.id, "question": stage.question})
                outputs = dict(state.get("outputs") or {})
                outputs[stage.id] = str(answer)
                return {"outputs": outputs, "stop": "" if str(answer).lower() in {"yes", "y"} else "declined"}
            return node

        previous = START
        for stage in wf.stages:
            graph.add_node(stage.id, make_human(stage) if stage.kind == "human" else make_node(stage))
            graph.add_edge(previous, stage.id)
            previous = stage.id
        graph.add_edge(previous, END)
        return graph.compile(checkpointer=saver)

    def _brief(self, run_id: str) -> str:
        conn = self._conn()
        try:
            return self._row(conn, run_id)["brief"]
        finally:
            conn.close()

    def _agent_stage(self, stage: Stage, run: RunView, outputs: dict[str, str]) -> GraphState:
        agent = self.agents.get(stage.agent)
        if agent is None or agent.degraded:
            return self._fail(run, stage, outputs, f"agent '{stage.agent}' is not usable")
        prompt = render(stage.prompt, project=run.project, brief=self._brief(run.id), outputs=outputs)
        model = self._model_for(run.id)
        result = self.agent_runner.run(agent, prompt, model=model or None, session=f"wf-{run.id}")
        if result.status != "done":
            return self._fail(run, stage, outputs, f"agent stage ended with status '{result.status}'" + (f": {result.error}" if result.error else ""),
                              partial=result.text)
        outputs[stage.id] = result.text[:MAX_OUTPUT]
        self._update(run.id, outputs=outputs)
        return {"outputs": outputs}

    def _evidence_stage(self, stage: Stage, run: RunView, outputs: dict[str, str]) -> GraphState:
        argv = [a.replace("{project}", run.project) for a in stage.command]
        try:
            # The loader already refused non-read-only commands. PrintLabRunner.run applies the same policy again
            # before any process starts (allow_write defaults to False), so a hand-built stage is refused there.
            if self.printlab is None or not self.printlab.available():
                return self._fail(run, stage, outputs, "PrintLab is not available, so this stage cannot be checked")
            data = self.printlab.run(argv).data
        except (PolicyError, RunnerError) as exc:
            return self._fail(run, stage, outputs, f"check could not run: {exc}")
        actual = _dig(data, stage.field)
        passed = actual == stage.equals
        outputs[stage.id] = json.dumps({"field": stage.field, "expected": stage.equals, "actual": actual, "passed": passed}, ensure_ascii=False)
        self._update(run.id, outputs=outputs)
        if not passed:
            return self._fail(run, stage, outputs, f"PrintLab's check says {stage.field} = {actual!r}, not {stage.equals!r}", keep_output=True)
        return {"outputs": outputs}

    def _fail(self, run: RunView, stage: Stage, outputs: dict[str, str], why: str, partial: str = "", keep_output: bool = False) -> GraphState:
        # Save what we know for the person (the checkpoint is NOT updated when a node raises), then stop here.
        if partial and not keep_output:
            outputs[stage.id + "_partial"] = partial[:MAX_OUTPUT]
        self._update(run.id, outputs=outputs)
        self._update(run.id, status="blocked", stage=stage.id, detail=why)
        raise StageBlocked(why)

    def _model_for(self, run_id: str) -> str:
        conn = self._conn()
        try:
            row = self._row(conn, run_id)
            return row["model"] or self.workflows[row["workflow"]].model or settings_store.get_default_model(conn)
        finally:
            conn.close()

    # ---- public API ------------------------------------------------------
    def view(self, run_id: str) -> RunView:
        conn = self._conn()
        try:
            row = self._row(conn, run_id)
        finally:
            conn.close()
        waiting = None
        if row["status"] == "waiting":
            wf = self.workflows.get(row["workflow"])
            stage = wf.stage(row["stage"]) if wf and any(s.id == row["stage"] for s in wf.stages) else None
            if stage is not None and stage.kind == "human":
                outputs = json.loads(row["outputs_json"])
                waiting = {"stage": stage.id, "question": stage.question, "show": {k: outputs.get(k, "") for k in stage.show}}
        return RunView(row["id"], row["workflow"], row["project"], row["status"], row["stage"], row["detail"],
                       json.loads(row["outputs_json"]), waiting, row["created_at"], row["updated_at"])

    def list_runs(self, limit: int = 30) -> list[dict]:
        conn = self._conn()
        try:
            rows = conn.execute("SELECT id, workflow, project, status, stage, detail, created_at, updated_at FROM workflow_runs ORDER BY created_at DESC LIMIT ?",
                                (max(1, min(int(limit), 100)),)).fetchall()
            return [dict(r) for r in rows]
        finally:
            conn.close()

    def start(self, workflow: str, *, request_id: str, project: str = "", brief: str = "", model: str = "") -> tuple[RunView, bool]:
        """Create a run and execute until the first stop. Returns (view, created). Same request_id returns the same run."""
        wf = self.workflows.get(workflow)
        if wf is None:
            raise EngineError("unknown workflow", 404)
        if not wf.valid:
            raise EngineError("workflow definition is invalid: " + "; ".join(wf.problems))
        if not isinstance(request_id, str) or not REQUEST_ID.fullmatch(request_id):
            raise EngineError("request_id must be 8-80 characters of letters, digits and _.:-")
        if project and not PROJECT_ID.fullmatch(project):
            raise EngineError("project must be a plain id such as P001")
        if wf.needs_project and not project:
            raise EngineError("this workflow needs a project id")
        if not isinstance(brief, str) or len(brief) > MAX_BRIEF:
            raise EngineError(f"brief must be text of at most {MAX_BRIEF} characters")
        if not isinstance(model, str) or len(model) > 200:
            raise EngineError("model is too long")
        if not (model or wf.model) and any(s.kind == "agent" for s in wf.stages):
            raise EngineError("no model chosen: pass `model` or set it in the workflow file")

        conn = self._conn()
        try:
            with self._lock:
                existing = conn.execute("SELECT id, workflow FROM workflow_runs WHERE request_id=?", (request_id,)).fetchone()
                if existing is not None:
                    if existing["workflow"] != workflow:
                        raise EngineError("this request_id was already used for a different workflow", 409)
                    return self.view(existing["id"]), False
                if len(self._busy) >= MAX_ACTIVE:
                    raise EngineError("too many workflow steps in progress", 429)
                run_id = uuid.uuid4().hex[:16]
                now = time.time()
                conn.execute("INSERT INTO workflow_runs(id,request_id,workflow,project,brief,model,status,stage,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                             (run_id, request_id, workflow, project, redact(brief), model, "running", wf.stages[0].id, now, now))
                self._busy.add(run_id)
        finally:
            conn.close()
        self._execute(wf, run_id, None)
        return self.view(run_id), True

    def answer(self, run_id: str, answer: str) -> RunView:
        if answer not in {"yes", "no"}:
            raise EngineError("answer must be 'yes' or 'no'")
        conn = self._conn()
        try:
            with self._lock:
                row = self._row(conn, run_id)
                if row["status"] != "waiting":
                    # The run has moved on, so the stage it is at now is not the one that was answered.
                    # A repeat of an answer that was already given is a harmless no-op; anything else is a conflict.
                    given = {r["answer"] for r in conn.execute("SELECT answer FROM workflow_answers WHERE run_id=?", (run_id,)).fetchall()}
                    if row["status"] in {"finished", "stopped", "running"} and given == {answer}:
                        return self.view(run_id)
                    raise EngineError(f"this run is '{row['status']}', not waiting for an answer", 409)
                if run_id in self._busy:
                    raise EngineError("this run is busy", 409)
                wf = self.workflows.get(row["workflow"])
                stage = next((s for s in wf.stages if s.id == row["stage"]), None) if wf else None
                if stage is None or stage.kind != "human":
                    raise EngineError("this run is not at a confirmation point", 409)
                conn.execute("INSERT INTO workflow_answers(run_id, stage, answer, at) VALUES(?,?,?,?)", (run_id, stage.id, answer, time.time()))
                conn.execute("UPDATE workflow_runs SET status='running', updated_at=? WHERE id=?", (time.time(), run_id))
                self._busy.add(run_id)
        finally:
            conn.close()
        self._execute(wf, run_id, answer)
        return self.view(run_id)

    def retry(self, run_id: str) -> RunView:
        """Continue a run that is blocked or interrupted: the failing stage runs again from its checkpoint."""
        conn = self._conn()
        try:
            with self._lock:
                row = self._row(conn, run_id)
                if row["status"] not in {"blocked", "interrupted"}:
                    raise EngineError(f"a '{row['status']}' run cannot be retried", 409)
                if run_id in self._busy:
                    raise EngineError("this run is busy", 409)
                wf = self.workflows.get(row["workflow"])
                if wf is None or not wf.valid:
                    raise EngineError("workflow definition is missing or invalid", 409)
                conn.execute("UPDATE workflow_runs SET status='running', detail='', updated_at=? WHERE id=?", (time.time(), run_id))
                self._busy.add(run_id)
        finally:
            conn.close()
        self._execute(wf, run_id, None, retry=True)
        return self.view(run_id)

    def stop(self, run_id: str) -> RunView:
        conn = self._conn()
        try:
            with self._lock:
                row = self._row(conn, run_id)
                if run_id in self._busy:
                    raise EngineError("this run is busy; try again when the step ends", 409)
                if row["status"] in {"finished", "stopped"}:
                    return self.view(run_id)
                conn.execute("UPDATE workflow_runs SET status='stopped', detail='stopped by a person', updated_at=? WHERE id=?", (time.time(), run_id))
        finally:
            conn.close()
        return self.view(run_id)

    # ---- execution -------------------------------------------------------
    def _execute(self, wf: WorkflowDefinition, run_id: str, answer: str | None, retry: bool = False) -> None:
        config = {"configurable": {"thread_id": run_id}}
        try:
            self.checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
            with SqliteSaver.from_conn_string(str(self.checkpoint_path)) as saver:
                app = self._build(wf, run_id, saver)
                try:
                    if answer is not None:
                        app.invoke(Command(resume=answer), config)
                    elif retry:
                        app.invoke(None, config)  # continues from the checkpoint: re-runs the stage that raised
                    else:
                        app.invoke({"outputs": {}}, config)
                except StageBlocked:
                    return  # _fail already recorded status 'blocked' and the reason
                self._settle(wf, run_id, app.get_state(config))
        except Exception as exc:  # noqa: BLE001 - leave the run in a visible state, never half-way "running"
            self._update(run_id, status="failed", detail=f"{type(exc).__name__}: {str(exc)[:200]}")
        finally:
            with self._lock:
                self._busy.discard(run_id)

    def _settle(self, wf: WorkflowDefinition, run_id: str, state: Any) -> None:
        outputs = dict(state.values.get("outputs") or {})
        waiting = [t for t in state.tasks if t.interrupts]
        if waiting:
            self._update(run_id, status="waiting", stage=waiting[0].interrupts[0].value["stage"], outputs=outputs, detail="")
        elif state.values.get("stop") == "declined":
            self._update(run_id, status="stopped", detail="a person answered no", outputs=outputs)
        elif not state.next:
            self._update(run_id, status="finished", stage=wf.stages[-1].id, outputs=outputs, detail="")
