from __future__ import annotations

import logging

import httpx
import pytest
from fastapi.testclient import TestClient

from printlab_interface import db, redact
from printlab_interface.adapters.printlab import PrintLabAdapter
from printlab_interface.adapters.printlab.http import PrintLabHttp
from printlab_interface.app import create_app
from printlab_interface.config import Settings, load_settings


def test_service_starts_and_is_healthy_with_printlab_absent(settings):
    with TestClient(create_app(settings)) as client:
        assert client.get("/healthz").json()["ok"] is True
        body = client.get("/api/printlab").json()
        assert body["online"] is False and body["cli"] is False and body["http"] is False
        assert body["reason"]
        status = client.get("/api/printlab/status").json()
        assert status["online"] is False and "error" in status


def test_service_creates_its_own_data_and_never_a_printlab_path(settings):
    with TestClient(create_app(settings)):
        pass
    assert settings.db_path.is_file()
    assert settings.run_dir.is_dir()
    assert "PrintLab" not in str(settings.db_path.relative_to(settings.data_dir.parent))


def test_audit_trail_records_startup_and_needs_the_admin_token(settings):
    app = create_app(settings)
    with TestClient(app) as client:
        assert client.get("/api/audit").status_code == 401
        rows = client.get("/api/audit", headers={"x-admin-token": app.state.admin_token}).json()
    assert rows and rows[0]["action"] == "startup"


def test_adapter_reports_online_via_mocked_printlab_http(settings):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/health":
            return httpx.Response(200, json={"ok": True, "version": "0.4.4", "features": ["a", "b"]})
        if request.url.path == "/api/overview":
            return httpx.Response(200, json={"projects": [], "device": {"state": "online"}})
        return httpx.Response(404)

    http = PrintLabHttp("http://printlab.test", transport=httpx.MockTransport(handler))
    adapter = PrintLabAdapter(settings, http=http)
    caps = adapter.describe()
    assert caps["http"] is True and caps["online"] is True and caps["version"] == "0.4.4" and caps["features"] == ["a", "b"]
    assert adapter.read_status()["source"] == "http"


def test_adapter_http_client_never_sends_a_request_for_refused_paths(settings):
    sent = []
    http = PrintLabHttp("http://printlab.test", transport=httpx.MockTransport(lambda r: sent.append(r) or httpx.Response(200, json={})))
    from printlab_interface.adapters.printlab.policy import PolicyError

    with pytest.raises(PolicyError):
        http.get("/api/prepared/P1/J1/start")
    assert sent == []


def test_loopback_only_host_is_enforced():
    with pytest.raises(ValueError, match="loopback"):
        load_settings({"PLI_HOST": "0.0.0.0"})
    assert load_settings({"PLI_HOST": "127.0.0.1"}).host == "127.0.0.1"


def test_empty_printlab_root_means_run_without_printlab():
    assert load_settings({"PLI_PRINTLAB_ROOT": ""}).printlab_root is None


def test_invalid_port_is_rejected():
    with pytest.raises(ValueError):
        load_settings({"PLI_PORT": "70000"})
    with pytest.raises(ValueError):
        load_settings({"PLI_PORT": "abc"})


@pytest.mark.parametrize(
    "raw",
    ["api_key=sk-abcdefghijklmnop", "Authorization: Bearer abcdefgh12345678", "bb_abcdefghijkl", '"access_code": "12345678"',
     "password=hunter2", "host 192.168.7.9 ok"],
)
def test_redaction_removes_secret_shaped_values(raw):
    out = redact.redact(raw)
    for secret in ("abcdefghijklmnop", "abcdefgh12345678", "abcdefghijkl", "12345678", "hunter2", "7.9"):
        assert secret not in out


def test_logging_filter_redacts_formatted_messages(caplog):
    logger = logging.getLogger("redaction_test")
    redact.install(logger)
    logger.addHandler(caplog.handler)
    caplog.set_level(logging.INFO, logger="redaction_test")
    logger.info("calling with key %s", "sk-supersecretvalue123")
    assert "supersecretvalue123" not in caplog.text


def test_audit_detail_is_redacted_and_truncated(settings):
    with db.session(settings.db_path) as conn:
        db.record_audit(conn, "t", "a", "x", "ok", "token=abcdef123456 " + "x" * 5000)
        row = db.recent_audit(conn, 1)[0]
    assert "abcdef123456" not in row["detail"] and len(row["detail"]) <= db.MAX_DETAIL_CHARS


def test_defaults_point_at_a_sibling_printlab_directory():
    s = Settings()
    assert s.port == 8019 and s.host == "127.0.0.1"
    assert s.printlab_root is not None and s.printlab_root.name == "PrintLab"
