"""P4-0 Spike: LangGraph checkpoint + interrupt, driven by a real model through our gateway.

Two separate OS processes share one SQLite checkpoint file:

    python docs/spike_p4.py start  <checkpoint.db> <thread>   # runs until the human-confirmation point
    python docs/spike_p4.py resume <checkpoint.db> <thread> yes|no

What it must show:
  1. the graph pauses at an interrupt and the pause survives the process exiting;
  2. a second process resumes from the checkpoint;
  3. nodes that already ran are NOT run again (the model is called exactly once per node);
  4. resuming a finished thread is harmless;
  5. a "no" answer takes the other branch.

Real model calls are counted from our own audit table, not from what this script claims.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path
from typing import TypedDict

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from langgraph.checkpoint.sqlite import SqliteSaver  # noqa: E402
from langgraph.graph import END, START, StateGraph  # noqa: E402
from langgraph.types import Command, interrupt  # noqa: E402

from printlab_interface.providers.gateway import Gateway  # noqa: E402

DB = ROOT / "data" / "interface.db"
MODEL = "mimo:mimo-v2.6-flash"


class State(TypedDict, total=False):
    brief: str
    plan: str
    decision: str
    summary: str


def ask(gateway: Gateway, system: str, user: str) -> str:
    result = gateway.complete(MODEL, [{"role": "system", "content": system}, {"role": "user", "content": user}], max_tokens=120, timeout_s=45)
    return result.text.strip()


def build(gateway: Gateway, checkpointer):
    def draft(state: State) -> State:
        return {"plan": ask(gateway, "You help plan a 3D print. Answer in two short sentences, no markdown.", state["brief"])}

    def confirm(state: State) -> State:
        # The model is NOT called in this node: a resumed interrupt re-runs the node from its top.
        answer = interrupt({"question": "Proceed with this plan?", "plan": state["plan"]})
        return {"decision": str(answer)}

    def finalize(state: State) -> State:
        return {"summary": ask(gateway, "Restate the plan in one short sentence, no markdown.", state["plan"])}

    def declined(state: State) -> State:
        return {"summary": "(declined by the human; no model call made)"}

    graph = StateGraph(State)
    graph.add_node("draft", draft)
    graph.add_node("confirm", confirm)
    graph.add_node("finalize", finalize)
    graph.add_node("declined", declined)
    graph.add_edge(START, "draft")
    graph.add_edge("draft", "confirm")
    graph.add_conditional_edges("confirm", lambda s: "finalize" if s["decision"].lower() in {"yes", "y"} else "declined")
    graph.add_edge("finalize", END)
    graph.add_edge("declined", END)
    return graph.compile(checkpointer=checkpointer)


def model_calls() -> int:
    conn = sqlite3.connect(DB)
    try:
        return conn.execute("SELECT COUNT(*) FROM audit WHERE action='model_call' AND outcome='ok'").fetchone()[0]
    finally:
        conn.close()


def main() -> int:
    mode, checkpoint_path, thread = sys.argv[1], sys.argv[2], sys.argv[3]
    config = {"configurable": {"thread_id": thread}}
    before = model_calls()
    gateway = Gateway(DB)
    with SqliteSaver.from_conn_string(checkpoint_path) as saver:
        app = build(gateway, saver)
        if mode == "start":
            out = app.invoke({"brief": "A small hook to hang headphones on a desk edge, PETG, 0.4 mm nozzle."}, config)
        elif mode == "resume":
            out = app.invoke(Command(resume=sys.argv[4]), config)
        else:
            raise SystemExit("mode must be start or resume")
        snap = app.get_state(config)
        report = {
            "mode": mode,
            "interrupted": "__interrupt__" in out,
            "interrupt_payload": [i.value for i in out.get("__interrupt__", [])],
            "next_nodes": list(snap.next),
            "has_plan": bool(out.get("plan")),
            "decision": out.get("decision"),
            "summary": out.get("summary"),
            "model_calls_made_by_this_process": model_calls() - before,
        }
    print("REPORT " + json.dumps(report, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
