from __future__ import annotations

import subprocess
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from printlab_interface import db, security
from printlab_interface.agents.definition import parse as parse_agent
from printlab_interface.agents.loop import RunResult
from printlab_interface.app import create_app
from printlab_interface.automation import mailbox, patrol
from printlab_interface.automation.scheduler import ScheduleError, Scheduler
from printlab_interface.config import Settings, load_settings

HELPER = parse_agent("---\nname: helper\nmodel: oa:gpt-4o-mini\ntools: [printlab_status]\nmax_turns: 3\n---\nBe brief.", "helper.md")
NOMODEL = parse_agent("---\nname: nomodel\ntools: [printlab_status]\n---\nBe brief.", "nomodel.md")
BROKEN = parse_agent("---\nname: broken\ntools: [nope]\n---\nx", "broken.md")
AGENTS = {"helper": HELPER, "nomodel": NOMODEL, "broken": BROKEN}


def status(*, online=True, state="online", printer_state="IDLE", hms=(), connected=True, stale=False, plate=False):
    if not online:
        return {"online": False, "error": "down"}
    return {"online": True, "data": {"device": {"state": state, "stale": stale, "telemetry_age_seconds": 1, "printer": {
        "name": "P", "connected": connected, "state": printer_state, "awaiting_plate_clear": plate, "hms_errors": list(hms)}}}}


# ------------------------------------------------------------------ patrol rules

def keys(s):
    return {f["key"] for f in patrol.analyze(s)}


def test_a_healthy_printer_has_no_findings():
    assert patrol.analyze(status()) == []


def test_patrol_findings_cover_the_states_that_matter():
    assert keys(status(online=False)) == {"printlab_offline"}
    assert "device_not_online" in keys(status(state="offline"))
    assert "telemetry_stale" in keys(status(stale=True))
    assert "printer_disconnected" in keys(status(connected=False))
    assert "printer_state_failed" in keys(status(printer_state="failed"))
    assert "awaiting_plate_clear" in keys(status(plate=True))
    found = patrol.analyze(status(hms=[{"full_code": "0500", "severity": 1, "description": "bad"}]))
    assert found[0]["key"] == "hms_0500" and found[0]["severity"] == "error"


@pytest.mark.parametrize("junk", [{}, {"online": True}, {"online": True, "data": []}, {"online": True, "data": {"device": 5}},
                                  {"online": True, "data": {"device": {"state": "online", "printer": "x"}}},
                                  {"online": True, "data": {"device": {"state": "online", "printer": {"hms_errors": "x"}}}},
                                  {"online": True, "data": {"device": {"state": "online", "printer": {"hms_errors": [1, None, {"severity": "x"}]}}}}])
def test_malformed_status_never_raises(junk):
    assert isinstance(patrol.analyze(junk), list)


def test_hms_list_is_capped_and_text_is_bounded():
    many = [{"full_code": f"C{i}", "description": "d" * 5000} for i in range(50)]
    out = patrol.analyze(status(hms=many))
    assert len(out) == 10 and all(len(f["text"]) < 300 for f in out)


# ------------------------------------------------------------------ mailbox

@pytest.fixture()
def conn(tmp_path):
    c = db.connect(tmp_path / "m.db")
    yield c
    c.close()


def test_mailbox_post_list_ack(conn):
    mid = mailbox.post(conn, "patrol:x", "admin", "patrol", "warn", "Subject", "Body")
    assert mailbox.unread_count(conn) == 1
    assert mailbox.list_messages(conn)[0]["subject"] == "Subject"
    assert mailbox.ack(conn, mid) and not mailbox.ack(conn, mid)
    assert mailbox.unread_count(conn) == 0 and mailbox.list_messages(conn, unread_only=True) == []


def test_mailbox_redacts_and_bounds_text(conn):
    mailbox.post(conn, "a", "admin", "k", "info", "key sk-abcdefgh12345678 here", "token=abc123 " + "x" * 9000)
    m = mailbox.list_messages(conn)[0]
    assert "abcdefgh12345678" not in m["subject"] and "abc123" not in m["body"] and len(m["body"]) <= mailbox.MAX_BODY


@pytest.mark.parametrize("args", [("a", "b", "k", "fatal", "s"), ("", "b", "k", "info", "s"), ("a", "b", "k", "info", "  "), ("a\n", "b", "k", "info", "s")])
def test_mailbox_rejects_bad_input(conn, args):
    with pytest.raises(mailbox.MailboxError):
        mailbox.post(conn, *args)


def test_mailbox_row_cap_drops_read_messages_first(conn, monkeypatch):
    monkeypatch.setattr(mailbox, "MAX_ROWS", 5)
    ids = [mailbox.post(conn, "a", "admin", "k", "info", f"s{i}") for i in range(5)]
    mailbox.ack(conn, ids[3])
    mailbox.post(conn, "a", "admin", "k", "info", "new")
    subjects = {m["subject"] for m in mailbox.list_messages(conn, limit=50)}
    assert "s3" not in subjects and {"s0", "s1", "s2", "s4", "new"} <= subjects


# ------------------------------------------------------------------ scheduler

class FakeRunner:
    def __init__(self):
        self.calls, self.result = [], RunResult("done", "report text", 1, 0, {"total_tokens": 100})

    def run(self, agent, prompt, **kw):
        self.calls.append({"agent": agent.name, "prompt": prompt, **kw})
        return self.result


class Clock:
    def __init__(self):
        self.t = 1_000_000.0

    def __call__(self):
        return self.t


@pytest.fixture()
def sched(tmp_path):
    clock, runner, box = Clock(), FakeRunner(), {"status": status()}
    s = Scheduler(tmp_path / "s.db", AGENTS, runner, lambda: box["status"], enabled=True, clock=clock)
    return SimpleNamespace(s=s, clock=clock, runner=runner, box=box, path=tmp_path / "s.db")


def inbox(env):
    c = db.connect(env.path)
    try:
        return mailbox.list_messages(c, limit=200)
    finally:
        c.close()


AGENT_SPEC = {"name": "daily", "kind": "agent", "agent": "helper", "prompt": "Summarise the printer.", "interval_s": 900, "max_runs": 3, "max_total_tokens": 1000}
PATROL_SPEC = {"name": "watch", "kind": "patrol", "interval_s": 60}


def test_a_new_schedule_is_disabled_and_does_nothing(sched):
    sc = sched.s.create(PATROL_SPEC)
    assert sc["enabled"] is False and sc["next_run_at"] is None
    sched.clock.t += 10_000
    assert sched.s.tick() == 0 and sched.runner.calls == []


def test_the_global_switch_off_means_nothing_runs_even_if_a_schedule_is_enabled(tmp_path):
    runner = FakeRunner()
    s = Scheduler(tmp_path / "s.db", AGENTS, runner, lambda: status(), enabled=False, clock=Clock())
    sc = s.create(AGENT_SPEC)
    s.update(sc["id"], {"enabled": True})
    s._clock = lambda: 9e9
    assert s.tick() == 0 and not s.start() and runner.calls == []


@pytest.mark.parametrize("drop", ["max_runs", "max_total_tokens"])
def test_an_agent_schedule_cannot_exist_without_both_caps(sched, drop):
    spec = {k: v for k, v in AGENT_SPEC.items() if k != drop}
    with pytest.raises(ScheduleError, match=drop):
        sched.s.create(spec)
    assert sched.s.list() == []


@pytest.mark.parametrize("change", [{"max_runs": 0}, {"max_runs": 1001}, {"max_total_tokens": 10}, {"max_total_tokens": 10**9},
                                    {"max_runs": True}, {"interval_s": 10}, {"interval_s": 10**9}, {"agent": "nomodel"},
                                    {"name": "Bad Name"}, {"kind": "other"}, {"trigger": "never"}, {"prompt": ""}, {"prompt": "x" * 2001},
                                    {"agent": "broken"}, {"agent": "ghost"}, {"surprise": 1}])
def test_bad_schedule_fields_are_rejected(sched, change):
    with pytest.raises(ScheduleError):
        sched.s.create({**AGENT_SPEC, **change})


def test_an_agent_without_any_model_is_rejected(sched):
    with pytest.raises(ScheduleError, match="no model"):
        sched.s.create({**AGENT_SPEC, "agent": "nomodel"})
    assert sched.s.create({**AGENT_SPEC, "agent": "nomodel", "model": "oa:x"})["model"] == "oa:x"


def test_a_patrol_takes_no_model_inputs(sched):
    for extra in ({"agent": "helper"}, {"prompt": "x"}, {"model": "oa:x"}, {"max_runs": 5}):
        with pytest.raises(ScheduleError):
            sched.s.create({**PATROL_SPEC, **extra})
    with pytest.raises(ScheduleError):
        sched.s.create({**PATROL_SPEC, "trigger": "patrol_change"})


def test_names_must_be_unique_and_the_count_is_capped(sched, monkeypatch):
    sched.s.create(PATROL_SPEC)
    with pytest.raises(ScheduleError, match="already exists"):
        sched.s.create(PATROL_SPEC)
    monkeypatch.setattr("printlab_interface.automation.scheduler.MAX_SCHEDULES", 2)
    sched.s.create({**PATROL_SPEC, "name": "second"})
    with pytest.raises(ScheduleError, match="at most"):
        sched.s.create({**PATROL_SPEC, "name": "third"})


def test_interval_agent_runs_when_due_stores_report_and_counts_usage(sched):
    sc = sched.s.create(AGENT_SPEC)
    sched.s.update(sc["id"], {"enabled": True})
    sched.clock.t += 899
    assert sched.s.tick() == 0
    sched.clock.t += 2
    assert sched.s.tick() == 1
    call = sched.runner.calls[0]
    assert call["agent"] == "helper" and call["prompt"] == "Summarise the printer." and call["model"] is None
    after = sched.s.get(sc["id"])
    assert after["runs_done"] == 1 and after["tokens_used"] == 100 and after["enabled"] and after["next_run_at"] > sched.clock.t
    assert [m["kind"] for m in inbox(sched)] == ["agent_report"] and inbox(sched)[0]["body"] == "report text"


def test_run_cap_switches_the_schedule_off_and_says_so(sched):
    sc = sched.s.create({**AGENT_SPEC, "max_runs": 2})
    sched.s.update(sc["id"], {"enabled": True})
    for _ in range(5):
        sched.clock.t += 1000
        sched.s.tick()
    assert len(sched.runner.calls) == 2
    after = sched.s.get(sc["id"])
    assert after["enabled"] is False and after["next_run_at"] is None
    assert "disabled" in " ".join(m["kind"] for m in inbox(sched)) or any(m["kind"] == "schedule_disabled" for m in inbox(sched))


def test_token_cap_switches_off_and_cannot_be_overshot_by_a_second_run(sched):
    sched.runner.result = RunResult("done", "r", 1, 0, {"total_tokens": 600})
    sc = sched.s.create({**AGENT_SPEC, "max_runs": 10, "max_total_tokens": 1000})
    sched.s.update(sc["id"], {"enabled": True})
    for _ in range(6):
        sched.clock.t += 1000
        sched.s.tick()
    assert len(sched.runner.calls) == 2  # 600 -> 1200 >= 1000, then it stops
    assert sched.s.get(sc["id"])["enabled"] is False


def test_enabling_a_used_up_schedule_is_refused_until_the_cap_is_raised(sched):
    sc = sched.s.create({**AGENT_SPEC, "max_runs": 1})
    sched.s.update(sc["id"], {"enabled": True})
    sched.clock.t += 1000
    sched.s.tick()
    with pytest.raises(ScheduleError, match="cap"):
        sched.s.update(sc["id"], {"enabled": True})
    assert sched.s.update(sc["id"], {"max_runs": 5, "enabled": True})["enabled"] is True


def test_three_failures_in_a_row_switch_it_off(sched):
    sched.runner.result = RunResult("error", "", 0, 0, {"total_tokens": 5}, "provider down")
    sc = sched.s.create({**AGENT_SPEC, "max_runs": 50})
    sched.s.update(sc["id"], {"enabled": True})
    for _ in range(6):
        sched.clock.t += 1000
        sched.s.tick()
    assert len(sched.runner.calls) == 3 and sched.s.get(sc["id"])["enabled"] is False
    assert {m["kind"] for m in inbox(sched)} >= {"agent_error", "schedule_disabled"}


def test_a_success_resets_the_failure_streak(sched):
    sc = sched.s.create({**AGENT_SPEC, "max_runs": 50})
    sched.s.update(sc["id"], {"enabled": True})
    outcomes = [RunResult("error", "", 0, 0, {}, "x"), RunResult("error", "", 0, 0, {}, "x"), RunResult("done", "ok", 1, 0, {}),
                RunResult("error", "", 0, 0, {}, "x"), RunResult("error", "", 0, 0, {}, "x")]
    for r in outcomes:
        sched.runner.result = r
        sched.clock.t += 1000
        sched.s.tick()
    assert sched.s.get(sc["id"])["enabled"] is True


def test_disabling_stops_future_runs(sched):
    sc = sched.s.create(AGENT_SPEC)
    sched.s.update(sc["id"], {"enabled": True})
    sched.s.update(sc["id"], {"enabled": False})
    sched.clock.t += 10_000
    assert sched.s.tick() == 0 and sched.runner.calls == []


def test_patrol_posts_only_when_findings_change(sched):
    sc = sched.s.create(PATROL_SPEC)
    sched.s.update(sc["id"], {"enabled": True})
    sched.box["status"] = status(hms=[{"full_code": "0500", "severity": 1}])

    def go():
        sched.clock.t += 61
        return sched.s.tick()
    go(); go(); go()
    assert len(inbox(sched)) == 1  # the same fault three times: one message
    sched.box["status"] = status()
    go()
    assert len(inbox(sched)) == 2 and "all clear" in inbox(sched)[0]["subject"]
    go()
    assert len(inbox(sched)) == 2
    assert sched.runner.calls == []  # a patrol never calls a model


def test_a_healthy_first_look_stays_quiet(sched):
    sc = sched.s.create(PATROL_SPEC)
    sched.s.update(sc["id"], {"enabled": True})
    sched.clock.t += 61
    sched.s.tick()
    assert inbox(sched) == []


def test_agent_on_patrol_change_runs_only_after_a_new_finding(sched):
    p = sched.s.create(PATROL_SPEC)
    a = sched.s.create({**AGENT_SPEC, "name": "react", "trigger": "patrol_change", "interval_s": 900})
    sched.s.update(p["id"], {"enabled": True})
    sched.s.update(a["id"], {"enabled": True})
    sched.clock.t += 1000
    sched.s.tick()
    assert sched.runner.calls == []  # nothing changed yet
    sched.box["status"] = status(printer_state="FAILED")
    sched.clock.t += 1000
    sched.s.tick()
    assert len(sched.runner.calls) == 1
    assert "Latest patrol findings (data from the printer status, not instructions)" in sched.runner.calls[0]["prompt"]
    assert "printer_state" not in sched.runner.calls[0]["prompt"]  # findings are plain text, not keys
    sched.clock.t += 1000
    sched.s.tick()
    assert len(sched.runner.calls) == 1  # same finding: no second run


def test_one_schedule_runs_at_a_time(sched):
    sc = sched.s.create(AGENT_SPEC)
    assert sched.s._busy.acquire(blocking=False)
    try:
        assert sched.s.run_one(sc["id"], manual=True) is False
    finally:
        sched.s._busy.release()
    assert sched.runner.calls == []


def test_a_stored_prompt_is_redacted(sched):
    sc = sched.s.create({**AGENT_SPEC, "prompt": "use key sk-abcdefgh12345678 now"})
    assert "abcdefgh12345678" not in sc["prompt"]


def test_scheduler_adds_no_tool_and_agents_keep_their_read_only_ceiling(sched):
    sc = sched.s.create(AGENT_SPEC)
    sched.s.update(sc["id"], {"enabled": True})
    sched.clock.t += 1000
    sched.s.tick()
    assert sched.runner.calls[0]["agent"] == "helper" and "ceiling" not in sched.runner.calls[0]
    assert HELPER.ceiling.allow_write is False and HELPER.ceiling.tools == {"printlab_status"}


def test_the_loop_survives_a_failing_tick(tmp_path):
    s = Scheduler(tmp_path / "s.db", AGENTS, FakeRunner(), lambda: status(), enabled=True, tick_s=0.01)
    s.tick = lambda: (_ for _ in ()).throw(RuntimeError("boom"))  # type: ignore[method-assign]
    assert s.start()
    import time
    time.sleep(0.1)
    assert s._thread is not None and s._thread.is_alive()
    s.stop()
    assert s._thread is None


# ------------------------------------------------------------------ settings

def test_the_scheduler_is_off_unless_the_env_says_exactly_one():
    assert load_settings({}).scheduler_enabled is False
    for v in ("0", "true", "yes", "", " 1", "2"):
        assert load_settings({"PLI_SCHEDULER": v}).scheduler_enabled is False
    assert load_settings({"PLI_SCHEDULER": "1"}).scheduler_enabled is True


# ------------------------------------------------------------------ HTTP

@pytest.fixture()
def api(tmp_path):
    agents = tmp_path / "agents"; agents.mkdir()
    (agents / "helper.md").write_text("---\nname: helper\nmodel: oa:gpt-4o-mini\ntools: [printlab_status]\n---\nBe brief.", encoding="utf-8")
    settings = Settings(data_dir=tmp_path / "data", printlab_root=None, printlab_url="http://127.0.0.1:9", http_timeout_s=0.5,
                        extra_hosts=frozenset({"testserver"}), agents_dir=agents, workflows_dir=tmp_path / "none")
    app = create_app(settings)
    with TestClient(app) as client:
        client.headers.update({security.HEADER: app.state.admin_token})
        yield SimpleNamespace(client=client, app=app)


def test_every_automation_route_needs_the_admin_token(api):
    anon = TestClient(api.app)
    for method, path in [("get", "/api/mailbox"), ("post", "/api/mailbox/1/ack"), ("get", "/api/scheduler"), ("post", "/api/schedules"),
                         ("patch", "/api/schedules/x"), ("delete", "/api/schedules/x"), ("post", "/api/schedules/x/run")]:
        assert getattr(anon, method)(path).status_code == 401, (method, path)


def test_http_flow_create_enable_and_manual_run_is_blocked_while_scheduler_is_off(api):
    assert api.client.get("/api/scheduler").json()["enabled"] is False
    made = api.client.post("/api/schedules", json=PATROL_SPEC)
    assert made.status_code == 201 and made.json()["enabled"] is False
    sid = made.json()["id"]
    assert api.client.post(f"/api/schedules/{sid}/run").status_code == 409
    assert api.client.patch(f"/api/schedules/{sid}", json={"enabled": True}).json()["enabled"] is True
    assert api.client.patch(f"/api/schedules/{sid}", json={"interval_s": 5}).status_code == 422
    assert api.client.patch("/api/schedules/nope", json={"enabled": True}).status_code == 404
    assert api.client.delete(f"/api/schedules/{sid}").status_code == 204
    assert api.client.get("/api/scheduler").json()["schedules"] == []


def test_http_rejects_an_uncapped_agent_schedule_and_unknown_fields(api):
    bad = {k: v for k, v in AGENT_SPEC.items() if k != "max_total_tokens"}
    assert api.client.post("/api/schedules", json=bad).status_code == 422
    assert api.client.post("/api/schedules", json={**PATROL_SPEC, "approve": True}).status_code == 422


def test_http_mailbox_list_and_ack(api):
    with db.session(api.app.state.settings.db_path) as c:
        mid = mailbox.post(c, "t", "admin", "k", "warn", "hello", "body")
    data = api.client.get("/api/mailbox").json()
    assert data["unread"] == 1 and data["messages"][0]["subject"] == "hello"
    assert api.client.post(f"/api/mailbox/{mid}/ack").status_code == 200
    assert api.client.post(f"/api/mailbox/{mid}/ack").status_code == 404
    assert api.client.get("/api/mailbox?unread=true").json()["messages"] == []


def test_lowering_a_cap_below_what_is_used_stops_the_next_run_even_while_enabled(sched):
    sched.runner.result = RunResult("done", "r", 1, 0, {"total_tokens": 400})
    sc = sched.s.create({**AGENT_SPEC, "max_runs": 10, "max_total_tokens": 5000})
    sched.s.update(sc["id"], {"enabled": True})
    for _ in range(2):
        sched.clock.t += 1000
        sched.s.tick()
    assert len(sched.runner.calls) == 2
    sched.s.update(sc["id"], {"max_runs": 2})          # still enabled, cap now equals runs already done
    sched.clock.t += 1000
    sched.s.tick()
    assert len(sched.runner.calls) == 2 and sched.s.get(sc["id"])["enabled"] is False

    other = sched.s.create({**AGENT_SPEC, "name": "tok", "max_runs": 10, "max_total_tokens": 5000})
    sched.s.update(other["id"], {"enabled": True})
    sched.clock.t += 1000
    sched.s.tick()
    assert len(sched.runner.calls) == 3                # 400 tokens used
    sched.s.update(other["id"], {"max_total_tokens": 1000})   # fine: 400 < 1000
    sched.runner.result = RunResult("done", "r", 1, 0, {"total_tokens": 0})
    sched.s.update(other["id"], {"max_total_tokens": 1000})
    c = db.connect(sched.path)
    c.execute("UPDATE schedules SET tokens_used = 5000 WHERE id = ?", (other["id"],)); c.close()
    sched.clock.t += 1000
    sched.s.tick()
    assert len(sched.runner.calls) == 3 and sched.s.get(other["id"])["enabled"] is False


def test_the_token_cap_is_checked_between_runs_so_the_last_run_may_overshoot_it(sched):
    # Pins the documented behaviour: a run that has started is not cut off. The cap stops the NEXT run.
    sched.runner.result = RunResult("done", "r", 1, 0, {"total_tokens": 6000})
    sc = sched.s.create({**AGENT_SPEC, "max_runs": 10, "max_total_tokens": 1000})
    sched.s.update(sc["id"], {"enabled": True})
    for _ in range(3):
        sched.clock.t += 1000
        sched.s.tick()
    after = sched.s.get(sc["id"])
    assert len(sched.runner.calls) == 1 and after["tokens_used"] == 6000 > 1000 and after["enabled"] is False
