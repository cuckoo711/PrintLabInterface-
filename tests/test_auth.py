from __future__ import annotations

import sqlite3
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from printlab_interface import auth, db, security
from printlab_interface.app import create_app
from printlab_interface.config import Settings

GOOD = "correct horse battery 42"


@pytest.fixture()
def env(tmp_path):
    settings = Settings(data_dir=tmp_path / "data", printlab_root=None, printlab_url="http://127.0.0.1:9", http_timeout_s=0.5,
                        extra_hosts=frozenset({"testserver"}), agents_dir=tmp_path / "a", workflows_dir=tmp_path / "w")
    app = create_app(settings)
    with TestClient(app, base_url="http://testserver") as client:
        yield SimpleNamespace(client=client, app=app, settings=settings)


def fresh(env):
    return TestClient(env.app, base_url="http://testserver")


def set_up(env, passphrase=GOOD):
    r = env.client.post("/api/auth/setup", json={"passphrase": passphrase})
    assert r.status_code == 201, r.text
    return r.json()["csrf"]


# ------------------------------------------------------------------ first-time setup

def test_the_first_visit_sees_that_no_passphrase_exists_yet(env):
    s = env.client.get("/api/auth/state").json()
    assert s == {"passphrase_set": False, "logged_in": False, "csrf": None, "locked_seconds": 0}


def test_setting_a_passphrase_logs_you_in_and_closes_setup_for_good(env):
    csrf = set_up(env)
    assert env.client.get("/api/auth/state").json()["logged_in"] is True
    assert env.client.get("/api/agents").status_code == 200  # the cookie alone is enough for a read
    again = fresh(env).post("/api/auth/setup", json={"passphrase": "another one entirely"})
    assert again.status_code == 409  # nobody can take over by calling setup a second time
    assert fresh(env).post("/api/auth/login", json={"passphrase": GOOD}).status_code == 200
    assert csrf


def test_a_generated_passphrase_is_shown_once_and_works(env):
    r = env.client.post("/api/auth/setup", json={})
    assert r.status_code == 201
    shown = r.json()["generated_passphrase"]
    assert shown and len(shown) >= 20
    assert fresh(env).post("/api/auth/login", json={"passphrase": shown}).status_code == 200
    assert env.client.get("/api/auth/state").json().get("generated_passphrase") is None  # never offered again


@pytest.mark.parametrize("bad", ["short", "aaaaaaaaaaaa", " leading space here", "trailing space here ", "x" * 201])
def test_weak_or_odd_passphrases_are_refused_and_nothing_is_set(env, bad):
    assert env.client.post("/api/auth/setup", json={"passphrase": bad}).status_code in {422}
    assert env.client.get("/api/auth/state").json()["passphrase_set"] is False


def test_setup_is_refused_when_the_request_does_not_come_from_this_machine(env):
    foreign = TestClient(env.app, base_url="http://testserver", client=("203.0.113.9", 5000))
    assert foreign.post("/api/auth/setup", json={"passphrase": GOOD}).status_code == 403
    assert env.client.get("/api/auth/state").json()["passphrase_set"] is False


def test_setup_is_refused_for_a_cross_site_request(env):
    r = env.client.post("/api/auth/setup", json={"passphrase": GOOD}, headers={"sec-fetch-site": "cross-site"})
    assert r.status_code == 403
    r = env.client.post("/api/auth/setup", json={"passphrase": GOOD}, headers={"origin": "http://evil.example"})
    assert r.status_code == 403
    assert env.client.get("/api/auth/state").json()["passphrase_set"] is False


def test_two_setups_racing_cannot_both_win(env):
    conn = db.connect(env.settings.db_path)
    auth.set_passphrase(conn, GOOD)
    with pytest.raises(auth.AuthError):
        auth.set_passphrase(conn, "a second different passphrase")
    conn.close()


# ------------------------------------------------------------------ what is stored

def test_the_passphrase_and_the_session_id_are_never_stored_in_clear(env):
    set_up(env)
    sid = env.client.cookies.get(auth.COOKIE)
    assert sid
    raw = env.settings.db_path.read_bytes() + b"".join(p.read_bytes() for p in env.settings.data_dir.glob("interface.db-*"))
    assert GOOD.encode() not in raw and sid.encode() not in raw
    conn = db.connect(env.settings.db_path)
    row = conn.execute("SELECT * FROM auth_passphrase").fetchone()
    assert len(row["salt"]) == 16 and len(row["hash"]) == 32 and row["n"] >= 2**14
    assert conn.execute("SELECT sid_hash FROM auth_sessions").fetchone()["sid_hash"] != sid
    conn.close()


def test_the_audit_trail_records_logins_without_any_secret(env):
    set_up(env)
    fresh(env).post("/api/auth/login", json={"passphrase": "wrong wrong wrong"})
    conn = db.connect(env.settings.db_path)
    rows = " ".join(str(dict(r)) for r in conn.execute("SELECT * FROM audit WHERE target='auth'"))
    conn.close()
    assert "passphrase_set" in rows and "refused" in rows and GOOD not in rows and "wrong wrong wrong" not in rows


# ------------------------------------------------------------------ logging in

def test_login_with_the_right_passphrase_sets_a_strict_http_only_cookie(env):
    set_up(env)
    other = fresh(env)
    r = other.post("/api/auth/login", json={"passphrase": GOOD})
    assert r.status_code == 200 and r.json()["csrf"]
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "samesite=strict" in cookie and "path=/" in cookie and auth.COOKIE in cookie
    assert other.get("/api/agents").status_code == 200


def test_a_wrong_passphrase_is_refused_and_gives_no_session(env):
    set_up(env)
    other = fresh(env)
    r = other.post("/api/auth/login", json={"passphrase": "not the passphrase"})
    assert r.status_code == 401 and "set-cookie" not in r.headers
    assert other.get("/api/agents").status_code == 401


def test_login_before_any_passphrase_exists_is_refused(env):
    assert fresh(env).post("/api/auth/login", json={"passphrase": GOOD}).status_code == 401


def test_repeated_wrong_guesses_lock_the_machine_out_for_a_while(env):
    set_up(env)
    other = fresh(env)
    for _ in range(auth.FAILURES_BEFORE_LOCK):
        assert other.post("/api/auth/login", json={"passphrase": "nope nope nope"}).status_code == 401
    locked = other.post("/api/auth/login", json={"passphrase": GOOD})  # even the right one is refused while locked
    assert locked.status_code == 429 and "秒" in locked.json()["detail"]
    assert env.client.get("/api/auth/state").json()["locked_seconds"] > 0


def test_lockout_lifts_after_the_wait_and_a_success_resets_it():
    now = {"t": 1000.0}
    lock = auth.Lockout(clock=lambda: now["t"])
    for _ in range(auth.FAILURES_BEFORE_LOCK):
        lock.failed()
    assert lock.remaining() > 0
    now["t"] += auth.LOCK_SECONDS + 1
    assert lock.remaining() == 0
    lock.failed(); lock.succeeded()
    assert lock.remaining() == 0 and lock._failures == 0


def test_lockout_grows_with_more_failures():
    now = {"t": 0.0}
    lock = auth.Lockout(clock=lambda: now["t"])
    for _ in range(auth.FAILURES_BEFORE_LOCK):
        lock.failed()
    first = lock.remaining()
    now["t"] += first + 1
    lock.failed()
    assert lock.remaining() > first


def test_unknown_fields_and_wrong_types_in_login_are_rejected(env):
    set_up(env)
    other = fresh(env)
    assert other.post("/api/auth/login", json={"passphrase": GOOD, "admin": True}).status_code == 422
    assert other.post("/api/auth/login", json={"passphrase": 12345}).status_code == 422
    assert other.post("/api/auth/login", json={}).status_code == 422


# ------------------------------------------------------------------ the cookie is not a free pass

def test_a_session_may_read_but_a_change_needs_the_csrf_value(env):
    csrf = set_up(env)
    body = {"name": "watch", "kind": "patrol", "interval_s": 120}
    assert env.client.post("/api/schedules", json=body).status_code == 403  # cookie only: refused
    assert env.client.post("/api/schedules", json=body, headers={auth.CSRF_HEADER: "wrong"}).status_code == 403
    ok = env.client.post("/api/schedules", json=body, headers={auth.CSRF_HEADER: csrf})
    assert ok.status_code == 201


def test_a_cross_site_request_with_a_valid_cookie_is_refused_even_for_a_read(env):
    csrf = set_up(env)
    assert env.client.get("/api/agents", headers={"sec-fetch-site": "cross-site"}).status_code == 403
    assert env.client.get("/api/agents", headers={"origin": "http://evil.example"}).status_code == 403
    assert env.client.post("/api/schedules", json={"name": "x", "kind": "patrol", "interval_s": 120},
                           headers={auth.CSRF_HEADER: csrf, "sec-fetch-site": "cross-site"}).status_code == 403
    assert env.client.get("/api/agents", headers={"sec-fetch-site": "same-origin"}).status_code == 200


def test_the_csrf_value_of_another_session_does_not_work(env):
    set_up(env)
    other = fresh(env)
    other_csrf = other.post("/api/auth/login", json={"passphrase": GOOD}).json()["csrf"]
    body = {"name": "watch", "kind": "patrol", "interval_s": 120}
    assert env.client.post("/api/schedules", json=body, headers={auth.CSRF_HEADER: other_csrf}).status_code == 403


def test_no_cookie_and_no_token_is_refused_everywhere(env):
    set_up(env)
    anon = fresh(env)
    for method, path in [("get", "/api/agents"), ("get", "/api/providers"), ("get", "/api/export"), ("get", "/api/audit"), ("get", "/api/mailbox"),
                         ("get", "/api/scheduler"), ("get", "/api/workflows"), ("post", "/api/schedules")]:
        assert getattr(anon, method)(path).status_code == 401, path


def test_an_invented_or_malformed_cookie_is_refused(env):
    set_up(env)
    for value in ["", "x", "a" * 500, "../../etc", "null"]:
        c = fresh(env)
        c.cookies.set(auth.COOKIE, value)
        assert c.get("/api/agents").status_code == 401, value


# ------------------------------------------------------------------ sessions end

def test_logout_ends_the_session_and_needs_the_csrf_value(env):
    csrf = set_up(env)
    assert env.client.post("/api/auth/logout").status_code == 403  # cookie alone cannot log you out either
    assert env.client.post("/api/auth/logout", headers={auth.CSRF_HEADER: csrf}).status_code == 200
    assert env.client.get("/api/agents").status_code == 401


def test_a_session_expires(env):
    conn = db.connect(env.settings.db_path)
    auth.init(conn)
    sid, _ = auth.create_session(conn, now=1000.0)
    assert auth.find_session(conn, sid, now=1000.0 + auth.SESSION_SECONDS - 1) is not None
    assert auth.find_session(conn, sid, now=1000.0 + auth.SESSION_SECONDS + 1) is None
    conn.close()


def test_old_sessions_are_swept_and_their_number_is_capped(env):
    conn = db.connect(env.settings.db_path)
    auth.init(conn)
    for i in range(auth.MAX_SESSIONS + 15):
        auth.create_session(conn, now=1000.0 + i)
    assert conn.execute("SELECT COUNT(*) FROM auth_sessions").fetchone()[0] <= auth.MAX_SESSIONS
    newest, _ = auth.create_session(conn, now=5000.0)
    assert auth.find_session(conn, newest, now=5001.0) is not None  # an old forgotten browser never blocks a new login
    conn.close()


def test_a_session_survives_a_restart_of_the_service(env, tmp_path):
    set_up(env)
    sid = env.client.cookies.get(auth.COOKIE)
    app2 = create_app(env.settings)
    with TestClient(app2, base_url="http://testserver") as c2:
        c2.cookies.set(auth.COOKIE, sid)
        assert c2.get("/api/agents").status_code == 200


# ------------------------------------------------------------------ the older token header still works, and stays strict

def test_the_script_token_header_still_works_without_any_passphrase(env):
    assert env.client.get("/api/agents", headers={security.HEADER: env.app.state.admin_token}).status_code == 200
    assert env.client.get("/api/agents", headers={security.HEADER: "wrong"}).status_code == 401


def test_a_wrong_token_header_is_not_rescued_by_a_valid_session(env):
    set_up(env)
    assert env.client.get("/api/agents", headers={security.HEADER: "wrong"}).status_code == 401  # a bad credential is an error, not a fallback


def test_the_pages_no_longer_tell_people_to_look_for_a_token_file():
    from pathlib import Path
    web = Path(__file__).resolve().parents[1] / "src" / "printlab_interface" / "web"
    for name in ("chat.html", "admin.html"):
        text = (web / name).read_text(encoding="utf-8")
        assert "admin_token" not in text and "管理令牌" not in text, name
