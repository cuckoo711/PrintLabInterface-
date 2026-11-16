"""P0-3 Spike: two-node LangGraph graph, LiteLLM model call, read-only PrintLab CLI.

Throwaway evidence script. It is not part of the package. Run from the repo root:
    .venv/Scripts/python.exe docs/spike_p0_3.py

What it proves (and what it does not):
  * LangGraph can drive: read_status -> summarize, with a typed state.
  * LiteLLM can be called through one interface. Here it uses `mock_response`, so
    NO network request is made and NO API key is needed. A real provider call is
    NOT verified by this script.
  * The PrintLab CLI is invoked read-only (`status`) through a subprocess with a
    whitelisted environment, a timeout and an output cap.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import TypedDict

import litellm
from langgraph.graph import END, START, StateGraph

PRINTLAB_ROOT = Path(os.environ.get("PRINTLAB_ROOT", r"E:\MyProjet\PrintLab"))
CLI = PRINTLAB_ROOT / "Harness" / "bin" / "printlab.ps1"
TIMEOUT_S = 60
MAX_OUTPUT_BYTES = 1_000_000
# Only these variables reach the child process (mirrors the allow-list idea in the reference design).
ENV_ALLOW = (
    "PATH", "PATHEXT", "SYSTEMROOT", "WINDIR", "SYSTEMDRIVE", "COMSPEC", "TEMP", "TMP",
    "USERPROFILE", "USERNAME", "HOMEDRIVE", "HOMEPATH", "APPDATA", "LOCALAPPDATA",
    "PROGRAMDATA", "PROGRAMFILES", "PROGRAMFILES(X86)", "PROGRAMW6432", "ALLUSERSPROFILE", "PUBLIC",
    "COMPUTERNAME", "OS", "PROCESSOR_ARCHITECTURE", "NUMBER_OF_PROCESSORS",
)
# Read-only subcommands only. The real adapter will hold a stricter, tested deny list.
READ_ONLY = {"status", "context", "materials", "doctor", "dispatch-plan"}


class State(TypedDict, total=False):
    status_json: dict
    status_ms: int
    summary: str
    error: str


def run_printlab(subcommand: str) -> dict:
    if subcommand not in READ_ONLY:
        raise PermissionError(f"subcommand not allowed: {subcommand}")
    env = {k: os.environ[k] for k in ENV_ALLOW if k in os.environ}
    env["PYTHONUTF8"] = "1"
    env["PRINTLAB_ROOT"] = str(PRINTLAB_ROOT)
    cmd = ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(CLI), subcommand]
    proc = subprocess.run(cmd, capture_output=True, timeout=TIMEOUT_S, env=env, cwd=str(PRINTLAB_ROOT))
    out = proc.stdout[:MAX_OUTPUT_BYTES].decode("utf-8", errors="replace")
    if proc.returncode != 0:
        err = proc.stderr[:4000].decode("utf-8", errors="replace")
        raise RuntimeError(f"printlab {subcommand} exit={proc.returncode}: {err}")
    return json.loads(out)


def read_status(state: State) -> State:
    started = time.perf_counter()
    try:
        data = run_printlab("status")
    except Exception as exc:  # noqa: BLE001 - spike reports every failure mode
        return {"error": f"{type(exc).__name__}: {exc}"}
    return {"status_json": data, "status_ms": int((time.perf_counter() - started) * 1000)}


def summarize(state: State) -> State:
    if "error" in state:
        return {"summary": f"(no summary: {state['error']})"}
    device = state["status_json"].get("device", {})
    printer = device.get("printer") or {}
    facts = {
        "device_state": device.get("state"),
        "printer": printer.get("name"),
        "printer_state": printer.get("state"),
        "projects": len(state["status_json"].get("projects", [])),
    }
    # mock_response: LiteLLM returns this text without any network call.
    resp = litellm.completion(
        model="openai/gpt-4o-mini",
        messages=[
            {"role": "system", "content": "Summarize the printer status in one sentence."},
            {"role": "user", "content": json.dumps(facts, ensure_ascii=False)},
        ],
        mock_response=f"[mock] {facts['printer']} is {facts['printer_state']} ({facts['device_state']}); "
        f"{facts['projects']} project(s).",
    )
    return {"summary": resp.choices[0].message.content}


def build_graph():
    graph = StateGraph(State)
    graph.add_node("read_status", read_status)
    graph.add_node("summarize", summarize)
    graph.add_edge(START, "read_status")
    graph.add_edge("read_status", "summarize")
    graph.add_edge("summarize", END)
    return graph.compile()


if __name__ == "__main__":
    result = build_graph().invoke({})
    print("status_ms :", result.get("status_ms"))
    print("error     :", result.get("error"))
    print("summary   :", result.get("summary"))
    # Prove the deny path works: a write/dangerous subcommand must be refused before any process starts.
    for bad in ("approve", "submit", "reconcile"):
        try:
            run_printlab(bad)
            print("DENY FAILED for", bad)
            sys.exit(1)
        except PermissionError as exc:
            print("denied    :", exc)
