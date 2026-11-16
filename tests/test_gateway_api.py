from __future__ import annotations

import logging
import sqlite3
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from printlab_interface import db, security
from printlab_interface.app import create_app
from printlab_interface.providers import store
from printlab_interface.providers.gateway import Gateway, GatewayError
from printlab_interface.providers.key_pool import KeyPool

SECRET_A = "sk-test-AAAAAAAAAAAAAAAAAAAA"
SECRET_B = "sk-test-BBBBBBBBBBBBBBBBBBBB"


class StatusError(Exception):
    def __init__(self, status, msg="boom"):
        super().__init__(msg)
        self.status_code = status


def ok_response(text="hello", pt=10, ct=5):
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=text), finish_reason="stop")],
        usage=SimpleNamespace(prompt_tokens=pt, completion_tokens=ct, total_tokens=pt + ct),
    )


@pytest.fixture()
def gw_env(tmp_path):
    path = tmp_path / "i.db"
    conn = db.connect(path); store.init(conn)
    store.add_provider(conn, "oa", "OpenAI test", "openai")
    store.add_key(conn, "oa", "first", SECRET_A, priority=1)
    store.add_key(conn, "oa", "second", SECRET_B, priority=2)
    conn.close()
    calls = []
    behaviour = {"queue": []}

    def fake_call(**kw):
        calls.append(kw)
        action = behaviour["queue"].pop(0) if behaviour["queue"] else ok_response()
        if isinstance(action, Exception):
            raise action
        return action

    return SimpleNamespace(path=path, calls=calls, behaviour=behaviour, gw=Gateway(path, pool=KeyPool(), call=fake_call))


MSG = [{"role": "user", "content": "hi"}]


def test_success_returns_text_usage_and_cost_and_uses_litellm_style_model(gw_env):
    r = gw_env.gw.complete("oa:gpt-4o-mini", MSG, max_tokens=50, temperature=0.2, timeout_s=30)
    assert r.text == "hello" and r.usage["total_tokens"] == 15 and r.attempts == 1
    assert r.cost_usd and r.cost_usd > 0
    kw = gw_env.calls[0]
    assert kw["model"] == "openai/gpt-4o-mini" and kw["api_key"] == SECRET_A and kw["max_tokens"] == 50
    assert kw["num_retries"] == 0 and kw["timeout"] == 30


def test_max_tokens_is_capped_by_the_model_card(gw_env):
    gw_env.gw.complete("oa:gpt-4o-mini", MSG, max_tokens=10_000_000)
    assert gw_env.calls[0]["max_tokens"] == 16384


def test_a_401_disables_that_key_for_good_and_fails_over_to_the_next(gw_env):
    gw_env.behaviour["queue"] = [StatusError(401)]
    r = gw_env.gw.complete("oa:gpt-4o-mini", MSG)
    assert r.attempts == 2 and [c["api_key"] for c in gw_env.calls] == [SECRET_A, SECRET_B]
    conn = db.connect(gw_env.path)
    states = {row["label"]: row["invalid"] for row in conn.execute("SELECT label, invalid FROM provider_keys")}
    conn.close()
    assert states == {"first": 1, "second": 0}
    gw_env.calls.clear()
    gw_env.gw.complete("oa:gpt-4o-mini", MSG)
    assert [c["api_key"] for c in gw_env.calls] == [SECRET_B]  # persisted: the bad key is not retried


def test_rate_limit_cools_the_key_and_a_neutral_500_does_not_switch_keys(gw_env):
    gw_env.behaviour["queue"] = [StatusError(429, "slow")]
    gw_env.gw.complete("oa:gpt-4o-mini", MSG)
    assert gw_env.calls[-1]["api_key"] == SECRET_B
    gw_env.calls.clear()
    gw_env.behaviour["queue"] = [StatusError(500, "server")]
    with pytest.raises(GatewayError) as exc:
        gw_env.gw.complete("oa:gpt-4o-mini", MSG, session="neutral")
    assert exc.value.status == 500 and len(gw_env.calls) == 1


def test_all_keys_failing_raises_instead_of_looping_forever(gw_env):
    gw_env.behaviour["queue"] = [StatusError(429), StatusError(429), StatusError(429)]
    with pytest.raises(GatewayError):
        gw_env.gw.complete("oa:gpt-4o-mini", MSG)
    assert len(gw_env.calls) <= 3


@pytest.mark.parametrize(
    "kwargs,fragment",
    [({"model_value": "nocolon"}, "prefix"), ({"model_value": "ghost:m"}, "unknown provider"),
     ({"model_value": "oa:m", "messages": []}, "non-empty"), ({"model_value": "oa:m", "messages": [{"role": "boss", "content": "x"}]}, "role"),
     ({"model_value": "oa:m", "temperature": 5}, "temperature"), ({"model_value": "oa:m", "timeout_s": 0}, "timeout"),
     ({"model_value": "oa:m", "reasoning_effort": "extreme"}, "reasoning"),
     ({"model_value": "oa:m", "messages": [{"role": "user", "content": "x" * 500_000}]}, "too large")],
)
def test_bad_requests_fail_before_any_call(gw_env, kwargs, fragment):
    kwargs = dict(kwargs)
    value = kwargs.pop("model_value")
    messages = kwargs.pop("messages", MSG)
    with pytest.raises(GatewayError, match=fragment):
        gw_env.gw.complete(value, messages, **kwargs)
    assert gw_env.calls == []


def test_disabled_provider_is_refused(gw_env):
    conn = db.connect(gw_env.path); store.set_enabled(conn, "oa", False); conn.close()
    with pytest.raises(GatewayError, match="disabled"):
        gw_env.gw.complete("oa:gpt-4o-mini", MSG)


def test_provider_without_keys_is_refused_unless_it_is_a_local_kind(gw_env):
    conn = db.connect(gw_env.path)
    store.add_provider(conn, "ds", "DeepSeek", "deepseek")
    store.add_provider(conn, "loc", "Local", "ollama")
    conn.close()
    with pytest.raises(GatewayError, match="no usable API key"):
        gw_env.gw.complete("ds:deepseek-chat", MSG)
    gw_env.gw.complete("loc:llama3", MSG)
    assert "api_key" not in gw_env.calls[-1]


def test_structured_output_is_refused_when_the_card_says_unsupported(gw_env):
    conn = db.connect(gw_env.path); store.set_override(conn, "oa", "tiny", {"supports_response_schema": False}); conn.close()
    with pytest.raises(GatewayError, match="structured"):
        gw_env.gw.complete("oa:tiny", MSG, response_format={"type": "json_object"})


def test_errors_and_audit_never_contain_the_key(gw_env, caplog):
    gw_env.behaviour["queue"] = [StatusError(500, f"upstream echoed {SECRET_A}")]
    with pytest.raises(GatewayError):
        gw_env.gw.complete("oa:gpt-4o-mini", MSG)
    conn = db.connect(gw_env.path)
    dump = " ".join(str(dict(r)) for r in conn.execute("SELECT * FROM audit"))
    conn.close()
    assert SECRET_A not in dump and SECRET_B not in dump


# ---- store ----------------------------------------------------------------
def test_database_holds_no_plaintext_key(gw_env):
    raw = gw_env.path.read_bytes() + (gw_env.path.with_suffix(".db-wal").read_bytes() if gw_env.path.with_suffix(".db-wal").exists() else b"")
    assert SECRET_A.encode() not in raw and SECRET_B.encode() not in raw


@pytest.mark.parametrize("args", [("Bad Prefix", "n", "openai"), ("ok", "n", "mystery"), ("ok", " ", "openai"), ("ok", "n", "openai_compatible"),
                                  ("ok", "n", "openai", "ftp://x"), ("ok", "n", "openai", "https://u:p@host/v1")])
def test_provider_validation(tmp_path, args):
    conn = db.connect(tmp_path / "x.db"); store.init(conn)
    with pytest.raises(store.StoreError):
        store.add_provider(conn, *args)


def test_duplicate_prefix_and_malformed_keys_are_rejected(tmp_path):
    conn = db.connect(tmp_path / "x.db"); store.init(conn)
    store.add_provider(conn, "a", "A", "openai")
    with pytest.raises(store.StoreError, match="exists"):
        store.add_provider(conn, "a", "A2", "openai")
    for bad in ("short", "has space in key 123456", "", None):
        with pytest.raises(store.StoreError):
            store.add_key(conn, "a", "k", bad)
    with pytest.raises(store.StoreError):
        store.add_key(conn, "a", "k", "sk-valid-key-12345", priority=-1)


def test_deleting_a_provider_removes_its_keys_and_overrides(tmp_path):
    conn = db.connect(tmp_path / "x.db"); store.init(conn)
    store.add_provider(conn, "a", "A", "openai"); store.add_key(conn, "a", "k", "sk-valid-key-12345"); store.set_override(conn, "a", "m", {"max_input_tokens": 5})
    store.delete_provider(conn, "a")
    assert conn.execute("SELECT COUNT(*) FROM provider_keys").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM model_overrides").fetchone()[0] == 0


# ---- admin API ------------------------------------------------------------
@pytest.fixture()
def client(settings, monkeypatch):
    app = create_app(settings)
    with TestClient(app) as c:
        c.headers.update({security.HEADER: app.state.admin_token})
        c.app_state = app.state
        yield c


def test_every_provider_route_requires_the_admin_token(settings):
    with TestClient(create_app(settings)) as anon:
        for method, path in [("get", "/api/providers"), ("post", "/api/providers"), ("post", "/api/providers/x/keys"),
                             ("delete", "/api/providers/x"), ("post", "/api/chat"), ("get", "/api/audit"),
                             ("get", "/api/models/x/y/card"), ("put", "/api/models/x/y/override")]:
            assert getattr(anon, method)(path).status_code == 401, (method, path)
        assert anon.get("/api/providers", headers={security.HEADER: "wrong"}).status_code == 401
        assert anon.get("/healthz").status_code == 200  # health stays open


def test_host_header_must_be_loopback(settings):
    with TestClient(create_app(settings)) as c:
        assert c.get("/healthz", headers={"host": "evil.example.com"}).status_code == 400
        assert c.get("/healthz", headers={"host": "127.0.0.1.evil.com"}).status_code == 400
        assert c.get(f"/healthz", headers={"host": f"127.0.0.1:{settings.port}"}).status_code == 200


def test_token_file_is_created_once_and_never_served(settings):
    app = create_app(settings)
    with TestClient(app) as c:
        token = app.state.admin_token
        assert len(token) >= 32 and (settings.data_dir / "admin_token").read_text().strip() == token
        assert token not in c.get("/healthz").text and token not in c.get("/api/printlab").text
    app2 = create_app(settings)
    with TestClient(app2):
        assert app2.state.admin_token == token


def test_key_is_write_only_through_the_api(client):
    assert client.post("/api/providers", json={"prefix": "oa", "name": "OpenAI", "kind": "openai"}).status_code == 201
    saved = client.post("/api/providers/oa/keys", json={"label": "main", "api_key": SECRET_A, "priority": 1})
    assert saved.status_code == 201 and SECRET_A not in saved.text
    listing = client.get("/api/providers")
    assert listing.status_code == 200 and SECRET_A not in listing.text and listing.json()[0]["keys"][0]["hint"].startswith("sk-")
    audit = client.get("/api/audit").text
    assert SECRET_A not in audit and "key_add" in audit


def test_api_validation_errors_are_400_and_do_not_echo_secrets(client):
    r = client.post("/api/providers", json={"prefix": "Bad Prefix", "name": "x", "kind": "openai"})
    assert r.status_code == 400
    client.post("/api/providers", json={"prefix": "oa", "name": "OpenAI", "kind": "openai"})
    r = client.post("/api/providers/oa/keys", json={"label": "k", "api_key": "short"})
    assert r.status_code == 422
    assert '"input"' not in r.text and '"short"' not in r.text  # the rejected value is never echoed back
    assert r.json()["detail"][0]["loc"] == ["body", "api_key"]
    leaked = client.post("/api/providers/oa/keys", json={"label": "k", "api_key": "sk-bad key with spaces-1234"})
    assert leaked.status_code == 400 and "sk-bad" not in leaked.text
    assert client.post("/api/providers/ghost/keys", json={"api_key": SECRET_A}).status_code == 400


def test_model_card_and_override_endpoints(client):
    client.post("/api/providers", json={"prefix": "oa", "name": "OpenAI", "kind": "openai"})
    card = client.get("/api/models/oa/gpt-4o-mini/card").json()
    assert card["max_input_tokens"] == 128000 and card["sources"]["max_input_tokens"] == "catalog"
    changed = client.put("/api/models/oa/gpt-4o-mini/override", json={"values": {"max_input_tokens": 1000}}).json()
    assert changed["max_input_tokens"] == 1000 and changed["sources"]["max_input_tokens"] == "override"
    assert client.put("/api/models/oa/gpt-4o-mini/override", json={"values": {"api_key": 1}}).status_code == 400
    assert client.get("/api/models/ghost/x/card").status_code == 400


def test_chat_endpoint_maps_gateway_failures_to_http_codes_without_leaking(client):
    client.post("/api/providers", json={"prefix": "oa", "name": "OpenAI", "kind": "openai"})
    client.post("/api/providers/oa/keys", json={"api_key": SECRET_A})

    def failing(**kw):
        raise StatusError(429, f"limit for {SECRET_A}")

    client.app_state.gateway = Gateway(client.app_state.settings.db_path, pool=KeyPool(), call=failing)
    r = client.post("/api/chat", json={"model": "oa:gpt-4o-mini", "messages": MSG})
    assert r.status_code == 429
    assert client.post("/api/chat", json={"model": "nocolon", "messages": MSG}).status_code == 400
    assert client.post("/api/chat", json={"model": "oa:m", "messages": MSG, "reasoning_effort": "extreme"}).status_code == 422


def test_production_settings_do_not_whitelist_the_test_host(tmp_path):
    from printlab_interface.config import Settings
    prod = Settings(data_dir=tmp_path / "d", printlab_root=None, printlab_url="http://127.0.0.1:9", http_timeout_s=0.5)
    assert prod.extra_hosts == frozenset()
    with TestClient(create_app(prod)) as c:
        assert c.get("/healthz").status_code == 400  # TestClient sends Host: testserver
        assert c.get("/healthz", headers={"host": f"127.0.0.1:{prod.port}"}).status_code == 200


ODD_KEY = "zq9-unknown-shape-KEY-0123456789abcdef"  # matches none of the redactor's patterns


def _gateway_with_key(tmp_path, key):
    path = tmp_path / "scrub.db"
    conn = db.connect(path); store.init(conn)
    store.add_provider(conn, "oa", "t", "openai"); store.add_key(conn, "oa", "k", key); conn.close()
    return path


@pytest.mark.parametrize("echo", [ODD_KEY, ODD_KEY.upper(), ODD_KEY.lower(), __import__("urllib.parse", fromlist=["quote"]).quote(ODD_KEY + " x/y", safe="")])
def test_an_upstream_error_that_echoes_the_key_never_reaches_the_caller_or_the_audit(tmp_path, echo):
    path = _gateway_with_key(tmp_path, ODD_KEY)

    def failing(**kw):
        raise StatusError(500, f"Incorrect API key provided: {echo}. See docs.")

    gw = Gateway(path, pool=KeyPool(), call=failing)
    with pytest.raises(GatewayError) as exc:
        gw.complete("oa:gpt-4o-mini", MSG)
    assert ODD_KEY not in str(exc.value) and ODD_KEY.lower() not in str(exc.value).lower()
    conn = db.connect(path)
    dump = " ".join(str(dict(r)) for r in conn.execute("SELECT * FROM audit")); conn.close()
    assert ODD_KEY.lower() not in dump.lower()


def test_the_scrub_runs_even_when_the_error_text_is_long(tmp_path):
    path = _gateway_with_key(tmp_path, ODD_KEY)

    def failing(**kw):
        raise StatusError(500, "x" * 280 + ODD_KEY)  # the key sits across the 300-char cut

    with pytest.raises(GatewayError) as exc:
        Gateway(path, pool=KeyPool(), call=failing).complete("oa:gpt-4o-mini", MSG)
    assert ODD_KEY[:20] not in str(exc.value)


def test_tp_style_keys_are_redacted_by_shape_as_a_second_line_of_defence():
    from printlab_interface import redact
    assert "FAKEFAKEFAKE" not in redact.redact("key tp-FAKEFAKEFAKE0123456789abcdef failed")
    assert redact.redact("a tp-short is not a key") == "a tp-short is not a key"
