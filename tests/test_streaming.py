"""Streamed replies and paged history: what the chat page relies on to show text as it arrives and to read long chats in pages."""
from __future__ import annotations

import copy
from types import SimpleNamespace

import pytest

from printlab_interface import db
from printlab_interface.agents import sessions
from printlab_interface.agents.loop import AgentRunner, Cancel, Event
from printlab_interface.agents.manager import ActiveRun, RunManager
from printlab_interface.providers import store
from printlab_interface.providers.gateway import Gateway, GatewayError, MAX_STREAM_CHARS
from printlab_interface.providers.key_pool import KeyPool

KEY_A, KEY_B = "sk-stream-AAAAAAAAAAAAAAAA", "sk-stream-BBBBBBBBBBBBBBBB"
MSG = [{"role": "user", "content": "hi"}]


def chunk(text=None, *, finish=None, usage=None, calls=None):
    delta = SimpleNamespace(content=text, tool_calls=calls)
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta, finish_reason=finish)], usage=usage)


def usage_chunk(pt=7, ct=3):
    return SimpleNamespace(choices=[], usage=SimpleNamespace(prompt_tokens=pt, completion_tokens=ct, total_tokens=pt + ct))


class FakeStream:
    """What litellm returns for stream=True: an iterator with close(). `fail_at` raises after that many chunks."""

    def __init__(self, chunks, fail_at=None, error=None):
        self.chunks, self.fail_at, self.error, self.closed, self.read = list(chunks), fail_at, error, False, 0

    def __iter__(self):
        for i, c in enumerate(self.chunks):
            if self.fail_at is not None and i == self.fail_at:
                raise self.error or RuntimeError("stream broke")
            self.read += 1
            yield c

    def close(self):
        self.closed = True


class StatusError(Exception):
    def __init__(self, status):
        super().__init__("boom"); self.status_code = status


@pytest.fixture()
def env(tmp_path):
    path = tmp_path / "i.db"
    conn = db.connect(path); store.init(conn)
    store.add_provider(conn, "oa", "t", "openai")
    store.add_key(conn, "oa", "first", KEY_A, priority=1)
    store.add_key(conn, "oa", "second", KEY_B, priority=2)
    conn.close()
    calls, queue = [], []

    def fake_call(**kw):
        calls.append(copy.copy(kw))
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    return SimpleNamespace(path=path, calls=calls, queue=queue, gw=Gateway(path, pool=KeyPool(), call=fake_call))


def test_a_streamed_reply_hands_on_each_piece_and_still_returns_the_whole_reply(env):
    stream = FakeStream([chunk("Hel"), chunk("lo "), chunk("there", finish="stop"), usage_chunk()])
    env.queue.append(stream)
    seen = []
    r = env.gw.complete("oa:gpt-4o-mini", MSG, on_delta=seen.append)
    assert seen == ["Hel", "lo ", "there"] and r.text == "Hello there"
    assert r.finish_reason == "stop" and r.usage["total_tokens"] == 10
    assert env.calls[0]["stream"] is True and env.calls[0]["stream_options"] == {"include_usage": True}
    assert stream.closed  # the connection is always released


def test_without_a_listener_nothing_is_streamed(env):
    env.queue.append(SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="plain", tool_calls=None), finish_reason="stop")],
                                     usage=SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2)))
    assert env.gw.complete("oa:gpt-4o-mini", MSG).text == "plain"
    assert "stream" not in env.calls[0]


def test_tool_calls_arriving_in_fragments_are_put_back_together(env):
    part1 = SimpleNamespace(index=0, id="call_1", function=SimpleNamespace(name="printlab_", arguments='{"a"'))
    part2 = SimpleNamespace(index=0, id=None, function=SimpleNamespace(name="status", arguments=': 1}'))
    other = SimpleNamespace(index=1, id="call_2", function=SimpleNamespace(name="printlab_materials", arguments=""))
    env.queue.append(FakeStream([chunk(calls=[part1]), chunk(calls=[part2, other], finish="tool_calls"), usage_chunk()]))
    seen = []
    r = env.gw.complete("oa:gpt-4o-mini", MSG, on_delta=seen.append)
    assert seen == [] and r.text == ""
    assert [(c["id"], c["name"], c["arguments"]) for c in r.tool_calls] == [("call_1", "printlab_status", '{"a": 1}'), ("call_2", "printlab_materials", "{}")]


def test_a_stop_request_ends_the_read_early_and_closes_the_stream(env):
    stream = FakeStream([chunk("a"), chunk("b"), chunk("c"), chunk("d")])
    env.queue.append(stream)
    stop, seen = {"now": False}, []

    def on_delta(piece):
        seen.append(piece)
        if piece == "b":
            stop["now"] = True

    r = env.gw.complete("oa:gpt-4o-mini", MSG, on_delta=on_delta, should_stop=lambda: stop["now"])
    # at most one more piece is pulled from the wire before the stop is noticed, and it is not handed on
    assert seen == ["a", "b"] and r.text == "ab" and stream.read <= 3 and stream.closed


def test_a_reply_that_never_stops_is_cut_at_a_fixed_size(env):
    big = "x" * 10_000
    stream = FakeStream([chunk(big) for _ in range(MAX_STREAM_CHARS // 10_000 + 5)])
    env.queue.append(stream)
    r = env.gw.complete("oa:gpt-4o-mini", MSG, on_delta=lambda piece: None)
    assert len(r.text) <= MAX_STREAM_CHARS + 10_000 and r.truncated and stream.closed


def test_a_failure_before_any_text_moves_to_the_next_key(env):
    env.queue += [StatusError(429), FakeStream([chunk("ok", finish="stop"), usage_chunk()])]
    r = env.gw.complete("oa:gpt-4o-mini", MSG, on_delta=lambda piece: None)
    assert r.text == "ok" and len(env.calls) == 2 and env.calls[0]["api_key"] != env.calls[1]["api_key"]


def test_a_failure_after_text_was_shown_does_not_start_over_on_another_key(env):
    # The person has already read the first words; a second key would produce a different reply on top of them.
    stream = FakeStream([chunk("partial "), chunk("more")], fail_at=1, error=StatusError(429))
    env.queue += [stream, FakeStream([chunk("never used", finish="stop")])]
    seen = []
    with pytest.raises(GatewayError):
        env.gw.complete("oa:gpt-4o-mini", MSG, on_delta=seen.append)
    assert seen == ["partial "] and len(env.calls) == 1 and stream.closed


# ---- the loop ----

def runner_with(env, script):
    from printlab_interface.tools.gateway import ToolGateway
    from printlab_interface.adapters.printlab.runner import PrintLabRunner
    env.queue += script
    tools = ToolGateway(PrintLabRunner(env.path.parent / "PrintLab", env.path.parent / "run"), audit_db=lambda: db.connect(env.path))
    return AgentRunner(env.gw, tools)


def agent():
    from printlab_interface.agents.definition import parse
    return parse("---\nname: t\nmodel: oa:gpt-4o-mini\ntools: []\nmax_turns: 2\n---\nBe brief.", "t.md")


def test_the_loop_emits_pieces_then_the_whole_reply(env):
    runner = runner_with(env, [FakeStream([chunk("Hi "), chunk("you", finish="stop"), usage_chunk()])])
    events: list[Event] = []
    result = runner.run(agent(), "hello", on_event=events.append)
    kinds = [e.kind for e in events]
    assert [e.data["text"] for e in events if e.kind == "text_delta"] == ["Hi ", "you"]
    assert kinds.index("text_delta") < kinds.index("text")
    assert [e.data["text"] for e in events if e.kind == "text"] == ["Hi you"] and result.text == "Hi you" and result.status == "done"


def test_a_cancel_during_streaming_stops_reading_and_drops_the_reply(env):
    stream = FakeStream([chunk(str(i)) for i in range(50)])
    runner = runner_with(env, [stream])
    cancel = Cancel()
    events: list[Event] = []

    def on_event(e):
        events.append(e)
        if e.kind == "text_delta" and e.data["text"] == "3":
            cancel.set()

    result = runner.run(agent(), "hello", cancel=cancel, on_event=on_event)
    assert result.status == "cancelled" and stream.read < 10 and stream.closed
    assert not [e for e in events if e.kind == "text"]  # a cancelled reply is not announced as an answer


# ---- the queue ----

def test_a_slow_reader_loses_pieces_but_never_the_whole_reply_or_the_end(tmp_path):
    manager = RunManager(tmp_path / "x.db", runner=None, max_concurrent=1)
    active = ActiveRun("r", "s", Cancel())
    from printlab_interface.agents import manager as manager_mod
    for i in range(manager_mod.EVENT_QUEUE_SIZE):
        manager._push(active, Event("text_delta", {"text": str(i)}))
    manager._push(active, Event("text_delta", {"text": "dropped"}))  # queue full: a piece may be lost
    assert active.events.qsize() == manager_mod.EVENT_QUEUE_SIZE
    manager._push(active, Event("text", {"text": "the whole reply"}), must_keep=True)
    drained = []
    while not active.events.empty():
        drained.append(active.events.get_nowait())
    assert drained[-1].kind == "text" and drained[-1].data["text"] == "the whole reply"
    assert "dropped" not in [e.data.get("text") for e in drained]


def test_the_run_manager_keeps_every_event_kind_except_pieces():
    src = (__import__("pathlib").Path(manager_path()).read_text(encoding="utf-8"))
    assert 'must_keep=event.kind != "text_delta"' in src


def manager_path():
    import printlab_interface.agents.manager as m
    return m.__file__


# ---- paged history ----

@pytest.fixture()
def conn(tmp_path):
    c = db.connect(tmp_path / "s.db"); sessions.init(c)
    yield c
    c.close()


def fill(conn, n):
    s = sessions.create(conn, "tester")
    for i in range(n):
        sessions.add_message(conn, s.id, "user" if i % 2 == 0 else "assistant", f"m{i}")
    return s.id


def test_the_newest_page_comes_first_and_older_pages_follow_without_gaps_or_repeats(conn):
    sid = fill(conn, 25)
    page, more = sessions.messages_page(conn, sid, None, 10)
    assert [m["content"] for m in page] == [f"m{i}" for i in range(15, 25)] and more
    older, more = sessions.messages_page(conn, sid, page[0]["id"], 10)
    assert [m["content"] for m in older] == [f"m{i}" for i in range(5, 15)] and more
    oldest, more = sessions.messages_page(conn, sid, older[0]["id"], 10)
    assert [m["content"] for m in oldest] == [f"m{i}" for i in range(5)] and not more


def test_a_chat_that_fits_in_one_page_says_there_is_no_more(conn):
    sid = fill(conn, 4)
    page, more = sessions.messages_page(conn, sid, None, 10)
    assert len(page) == 4 and not more
    assert sessions.messages_page(conn, sid, None, 4) == (page, False)  # exactly one full page is not "more"


def test_a_page_is_bounded_whatever_is_asked(conn):
    sid = fill(conn, 3)
    assert len(sessions.messages_page(conn, sid, None, 10**9)[0]) == 3
    assert len(sessions.messages_page(conn, sid, None, -5)[0]) == 1
    with pytest.raises(sessions.SessionError):
        sessions.messages_page(conn, "nope")
