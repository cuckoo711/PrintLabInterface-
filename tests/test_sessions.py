from __future__ import annotations

import pytest

from printlab_interface import db
from printlab_interface.agents import sessions

SECRET = "sk-session-SECRET-0123456789ABC"


@pytest.fixture()
def conn(tmp_path):
    c = db.connect(tmp_path / "s.db")
    sessions.init(c)
    yield c
    c.close()


def test_create_list_get_and_title_from_first_message(conn):
    s = sessions.create(conn, "sarah", "What filament   is loaded\nright now?")
    assert s.title == "What filament is loaded right now?" and sessions.get(conn, s.id).agent == "sarah"
    assert [x["id"] for x in sessions.list_sessions(conn, "sarah")] == [s.id]
    assert sessions.list_sessions(conn, "mike") == []


def test_title_is_redacted_and_truncated(conn):
    s = sessions.create(conn, "sarah", f"my key is {SECRET} " + "x" * 300)
    assert SECRET not in s.title and len(s.title) <= sessions.MAX_TITLE_CHARS


def test_messages_round_trip_in_order_and_history_returns_the_latest(conn):
    s = sessions.create(conn, "sarah")
    for i in range(5):
        sessions.add_message(conn, s.id, "user" if i % 2 == 0 else "assistant", f"m{i}")
    assert [m["content"] for m in sessions.messages(conn, s.id)] == ["m0", "m1", "m2", "m3", "m4"]
    assert [m["content"] for m in sessions.history(conn, s.id, limit=2)] == ["m3", "m4"]
    assert set(sessions.history(conn, s.id)[0]) == {"role", "content"}


def test_message_text_is_redacted_before_it_is_stored(conn):
    s = sessions.create(conn, "sarah")
    sessions.add_message(conn, s.id, "user", f"use api_key={SECRET} please")
    stored = sessions.messages(conn, s.id)[0]["content"]
    assert SECRET not in stored
    raw = " ".join(str(tuple(r)) for r in conn.execute("SELECT * FROM messages"))
    assert SECRET not in raw


@pytest.mark.parametrize("role,content", [("system", "x"), ("tool", "x"), ("user", ""), ("user", "   "), ("assistant", None)])
def test_only_nonempty_user_and_assistant_messages_are_stored(conn, role, content):
    s = sessions.create(conn, "a")
    with pytest.raises(sessions.SessionError):
        sessions.add_message(conn, s.id, role, content)
    assert sessions.messages(conn, s.id) == []


def test_unknown_session_is_an_error_everywhere(conn):
    for fn in (lambda: sessions.get(conn, "nope"), lambda: sessions.history(conn, "nope"), lambda: sessions.messages(conn, "nope"),
               lambda: sessions.add_message(conn, "nope", "user", "x"), lambda: sessions.start_run(conn, "nope", "m"), lambda: sessions.delete(conn, "nope")):
        with pytest.raises(sessions.SessionError):
            fn()


def test_limits_are_enforced(conn, monkeypatch):
    monkeypatch.setattr(sessions, "MAX_SESSIONS_PER_AGENT", 2)
    monkeypatch.setattr(sessions, "MAX_MESSAGES_PER_SESSION", 3)
    s1 = sessions.create(conn, "a"); sessions.create(conn, "a")
    with pytest.raises(sessions.SessionError, match="too many"):
        sessions.create(conn, "a")
    sessions.create(conn, "other")  # a different agent has its own budget
    for _ in range(3):
        sessions.add_message(conn, s1.id, "user", "x")
    with pytest.raises(sessions.SessionError, match="full"):
        sessions.add_message(conn, s1.id, "user", "x")


def test_overlong_message_is_cut(conn):
    s = sessions.create(conn, "a")
    sessions.add_message(conn, s.id, "user", "y" * 50_000)
    assert len(sessions.messages(conn, s.id)[0]["content"]) == sessions.MAX_MESSAGE_CHARS


def test_deleting_a_session_removes_messages_and_runs(conn):
    s = sessions.create(conn, "a")
    sessions.add_message(conn, s.id, "user", "x")
    rid = sessions.start_run(conn, s.id, "oa:m")
    sessions.finish_run(conn, rid, status="done", turns=1, tool_calls=0, tools=[], usage={}, error=None)
    sessions.delete(conn, s.id)
    assert conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0] == 0


def test_run_records_tool_names_and_counts_but_never_tool_output(conn):
    s = sessions.create(conn, "a")
    rid = sessions.start_run(conn, s.id, "oa:m")
    sessions.finish_run(conn, rid, status="done", turns=2, tool_calls=3, tools=["printlab_status", "printlab_status", "printlab_materials"],
                        usage={"prompt_tokens": 7, "completion_tokens": 3}, error=f"boom {SECRET}")
    run = sessions.list_runs(conn, s.id)[0]
    assert run["tools"] == ["printlab_materials", "printlab_status"] and run["prompt_tokens"] == 7 and run["status"] == "done"
    assert SECRET not in str(run) and run["finished_at"] is not None
    assert "tool_result" not in {r[1] for r in conn.execute("PRAGMA table_info(runs)")}


def test_runs_left_running_are_marked_interrupted_after_a_restart(conn):
    s = sessions.create(conn, "a")
    r1 = sessions.start_run(conn, s.id, "m"); r2 = sessions.start_run(conn, s.id, "m")
    sessions.finish_run(conn, r2, status="done", turns=1, tool_calls=0, tools=[], usage={}, error=None)
    assert sessions.abandon_unfinished(conn) == 1
    states = {r["id"]: r["status"] for r in sessions.list_runs(conn, s.id)}
    assert states == {r1: "interrupted", r2: "done"}


def test_foreign_keys_are_enforced(conn):
    with pytest.raises(Exception):
        conn.execute("INSERT INTO messages(session_id,role,content,created_at) VALUES('ghost','user','x',0)")
