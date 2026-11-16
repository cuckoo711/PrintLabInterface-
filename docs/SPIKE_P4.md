# P4-0 Spike: LangGraph checkpoints and human-confirmation stops

Date: 2026-11-17 (system time). Script: [spike_p4.py](spike_p4.py).

## Conclusion

**Use LangGraph with the SQLite checkpointer for the workflow engine.** Every behaviour the human-confirmation design needs was observed with a real model (`mimo:mimo-v2.6-flash` through our own gateway), not a mock.

## What was observed

| Behaviour | Result |
| --- | --- |
| A graph pauses at `interrupt(...)` and reports the payload to the caller | yes |
| The pause survives the process exiting (checkpoint file on disk) | yes |
| A **separate OS process** resumes the same thread with `Command(resume=...)` | yes |
| A node that already ran is **not run again** on resume (model called once per model node) | yes: the first process made 1 model call, the resuming process made 1 (the node after the stop), none repeated |
| Resuming a thread that already finished | harmless: 0 model calls, same stored result |
| Answering "no" takes the other branch | yes: 0 model calls, summary says it was declined |
| Model calls counted from our own audit table (not the script's claims) | yes; 5 calls in total from the spike: 3 flow calls plus 2 diagnostic calls |

Packages (installed into the repo `.venv` only):

| Package | Version | License (package metadata) |
| --- | --- | --- |
| langgraph | 1.2.22 | MIT |
| langgraph-checkpoint | 4.3.2 | MIT |
| langgraph-checkpoint-sqlite | 3.1.3 | MIT |
| aiosqlite | 0.22.1 | MIT |
| sqlite-vec | 0.1.9 | "MIT License, Apache License, Version 2.0" (ships a native `vec0.dll`) |

`sqlite-vec` is a dependency of the checkpointer that we do not use. It is a native binary on Windows. It was not examined beyond its declared license and file list.

## Design rules this implies

1. **A resumed `interrupt` re-runs its own node from the top.** The node containing `interrupt(...)` must not call the model or cause any side effect before the `interrupt` call. The spike's `confirm` node does nothing else, and that is the pattern to keep.
2. Model-calling nodes and the confirmation node are separate nodes.
3. State stored in a checkpoint is whatever the nodes return. Anything sensitive must not be put in state; checkpoints are not redacted by us.
4. The checkpoint file is separate from `interface.db` so it can be deleted or moved without touching providers or keys.

## A defect this found (fixed)

With `max_tokens=120` the model's plan ended mid-sentence (`"... a 30 mm vertical spine and"`) and the **next** model call received that fragment as its input. Our gateway reported the call as a success. The provider had set `finish_reason="length"`.

Fix, with tests (including a mutation check): `CallResult.truncated`, a `truncated` field on `/api/chat`, and a new agent-run status `truncated` that keeps the text that did arrive and says it was cut off. A workflow node must check `truncated` before passing text onward.

## Not verified

- Concurrency: two processes resuming the same thread at the same time.
- Checkpoint growth over many steps, and cleaning old threads.
- Behaviour when the model call inside a node fails halfway (the checkpoint should hold the state from before that node, which is what LangGraph documents, but it was not forced here).
- Time-travel or editing a checkpoint by hand.
- Only one provider was exercised.
