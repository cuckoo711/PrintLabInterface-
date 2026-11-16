from __future__ import annotations

import json
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from printlab_interface import db, security
from printlab_interface.app import create_app
from printlab_interface.config import Settings
from printlab_interface.providers import store

WEB = Path(__file__).resolve().parents[1] / "src" / "printlab_interface" / "web"
ADMIN_HTML = (WEB / "admin.html").read_text(encoding="utf-8")
ADMIN_JS = (WEB / "admin.js").read_text(encoding="utf-8")
SECRET = "sk-admin-export-SECRET-0123456789"


@pytest.fixture()
def api(tmp_path):
    agents = tmp_path / "agents"; agents.mkdir()
    (agents / "helper.md").write_text("---\nname: helper\nmodel: oa:gpt-4o-mini\ntools: [printlab_status]\n---\nBe brief.", encoding="utf-8")
    settings = Settings(data_dir=tmp_path / "data", printlab_root=None, printlab_url="http://127.0.0.1:9", http_timeout_s=0.5,
                        extra_hosts=frozenset({"testserver"}), agents_dir=agents, workflows_dir=tmp_path / "none")
    settings.data_dir.mkdir(parents=True)
    conn = db.connect(settings.db_path); store.init(conn); store.add_provider(conn, "oa", "OpenAI test", "openai"); store.add_key(conn, "oa", "main", SECRET, 5)
    store.set_override(conn, "oa", "gpt-4o-mini", {"supports_vision": True}); conn.close()
    app = create_app(settings)
    with TestClient(app) as client:
        client.headers.update({security.HEADER: app.state.admin_token})
        yield SimpleNamespace(client=client, app=app, settings=settings)


# ------------------------------------------------------------------ page

@pytest.mark.parametrize("path,media", [("/admin", "text/html"), ("/admin/", "text/html"), ("/admin/admin.js", "text/javascript"), ("/admin/app.css", "text/css")])
def test_admin_page_loads_without_a_token_and_carries_strict_headers(api, path, media):
    r = TestClient(api.app).get(path)
    assert r.status_code == 200 and r.headers["content-type"].startswith(media)
    csp = r.headers["content-security-policy"]
    assert "default-src 'none'" in csp and "script-src 'self'" in csp and "unsafe-inline" not in csp and "frame-ancestors 'none'" in csp
    assert r.headers["x-frame-options"] == "DENY" and r.headers["cache-control"] == "no-store"


def test_the_page_holds_no_secret_and_every_data_route_still_needs_the_token(api):
    anon = TestClient(api.app)
    token = api.app.state.admin_token
    assert token not in anon.get("/admin").text + anon.get("/admin/admin.js").text
    for path in ("/api/export", "/api/providers", "/api/scheduler", "/api/mailbox", "/api/audit"):
        assert anon.get(path).status_code == 401, path


def test_admin_html_has_no_inline_script_style_handler_or_remote_reference():
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", ADMIN_HTML, re.I)
    assert not re.search(r"<style\b|\sstyle\s*=|\son[a-z]+\s*=|javascript:", ADMIN_HTML, re.I)
    assert not re.search(r"(?:src|href|action)\s*=\s*[\"'](?:https?:)?//", ADMIN_HTML, re.I)
    assert 'lang="zh-CN"' in ADMIN_HTML and 'name="viewport"' in ADMIN_HTML


def test_admin_js_never_writes_server_text_as_html_and_keeps_the_token_in_memory():
    for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "eval(", "new Function", "localStorage", "sessionStorage", "document.cookie"):
        assert banned not in ADMIN_JS, banned
    assert "location.search" not in ADMIN_JS and "location.hash" not in ADMIN_JS


def test_every_form_control_has_a_label():
    ids = set(re.findall(r'<(?:input|select|textarea)\b[^>]*\bid="([^"]+)"', ADMIN_HTML))
    labelled = set(re.findall(r'<label[^>]*\bfor="([^"]+)"', ADMIN_HTML))
    wrapped = {"mail-unread"}  # the checkbox sits inside its own <label>
    assert ids - labelled - wrapped == set(), ids - labelled - wrapped


def test_destructive_buttons_ask_first():
    assert ADMIN_JS.count("confirm(") >= 4  # delete key, delete provider, delete schedule, run an agent schedule


# ------------------------------------------------------------------ export

def test_export_has_no_key_in_any_form(api):
    r = api.client.get("/api/export")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    text = r.text
    assert SECRET not in text and "SECRET-0123" not in text
    with db.session(api.settings.db_path) as conn:
        sealed = conn.execute("SELECT sealed FROM provider_keys").fetchone()["sealed"]
    assert sealed and sealed not in text and "sealed" not in text
    data = r.json()
    assert data["format"] == 1 and "No API keys" in data["note"]
    key = data["providers"][0]["keys"][0]
    assert set(key) == {"id", "label", "hint", "priority", "disabled", "invalid"} and key["label"] == "main"
    assert data["model_overrides"] == [{"prefix": "oa", "model": "gpt-4o-mini", "values": {"supports_vision": True}}]


def test_export_includes_schedules_and_is_audited_without_content(api):
    made = api.client.post("/api/schedules", json={"name": "watch", "kind": "patrol", "interval_s": 60})
    assert made.status_code == 201
    data = api.client.get("/api/export").json()
    assert [s["name"] for s in data["schedules"]] == ["watch"] and "seen_seq" not in data["schedules"][0]
    rows = api.client.get("/api/audit?limit=20").json()
    export_rows = [r for r in rows if r["action"] == "export"]
    assert export_rows and SECRET not in json.dumps(rows)
    assert "providers=1" in export_rows[0]["detail"]


def test_export_of_an_empty_installation_works(tmp_path):
    settings = Settings(data_dir=tmp_path / "d", printlab_root=None, printlab_url="http://127.0.0.1:9", http_timeout_s=0.5,
                        extra_hosts=frozenset({"testserver"}), agents_dir=tmp_path / "a", workflows_dir=tmp_path / "w")
    app = create_app(settings)
    with TestClient(app) as c:
        c.headers.update({security.HEADER: app.state.admin_token})
        data = c.get("/api/export").json()
    assert data["providers"] == [] and data["schedules"] == [] and data["model_overrides"] == []
