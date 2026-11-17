from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from printlab_interface import web
from printlab_interface.app import create_app

WEB = Path(web.__file__).parent
HTML = (WEB / "chat.html").read_text(encoding="utf-8")
JS = (WEB / "app.js").read_text(encoding="utf-8")
CSS = (WEB / "app.css").read_text(encoding="utf-8")


@pytest.fixture()
def client(settings):
    with TestClient(create_app(settings)) as c:
        yield c


@pytest.mark.parametrize("path,media", [("/chat", "text/html"), ("/chat/", "text/html"), ("/chat/app.js", "text/javascript"), ("/chat/app.css", "text/css")])
def test_page_and_assets_load_without_a_token_and_carry_strict_headers(client, path, media):
    r = client.get(path)
    assert r.status_code == 200 and r.headers["content-type"].startswith(media)
    csp = r.headers["content-security-policy"]
    for needle in ("default-src 'none'", "script-src 'self'", "frame-ancestors 'none'", "base-uri 'none'", "form-action 'none'"):
        assert needle in csp
    assert "unsafe-inline" not in csp and "unsafe-eval" not in csp and "http:" not in csp and "https:" not in csp
    assert r.headers["x-content-type-options"] == "nosniff" and r.headers["x-frame-options"] == "DENY"
    assert r.headers["cache-control"] == "no-store" and r.headers["referrer-policy"] == "no-referrer"


def test_the_page_holds_no_secret_and_the_api_it_calls_still_demands_the_token(client):
    assert "x-admin-token" in JS  # the script sends it ...
    for secret_file in (client.app.state.settings.data_dir / "admin_token",):
        if secret_file.exists():
            assert secret_file.read_text().strip() not in client.get("/chat/app.js").text + client.get("/chat").text
    assert client.get("/api/agents").status_code == 401


@pytest.mark.parametrize("path", ["/chat/../secrets", "/chat/%2e%2e/app.py", "/chat/app.py", "/chat/chat.html", "/chat/..%5capp.js", "/chat/nope"])
def test_only_the_three_known_files_are_served(client, path):
    assert client.get(path).status_code in {404, 400, 307, 308}
    assert client.get(path).status_code != 200


def test_wrong_host_is_refused_for_the_page_too(client):
    assert client.get("/chat", headers={"host": "evil.example.com"}).status_code == 400


def test_html_has_no_inline_script_style_handler_or_remote_reference():
    assert not re.search(r"<script(?![^>]*\bsrc=)[^>]*>", HTML, re.I), "inline <script>"
    assert not re.search(r"<style\b", HTML, re.I) and not re.search(r"\sstyle\s*=", HTML, re.I)
    assert not re.search(r"\son[a-z]+\s*=", HTML, re.I), "inline event handler"
    assert not re.search(r"(?:src|href|action)\s*=\s*[\"'](?:https?:)?//", HTML, re.I), "remote reference"
    assert not re.search(r"javascript:", HTML, re.I)
    assert 'lang="zh-CN"' in HTML and 'name="viewport"' in HTML


def test_html_has_labels_and_live_regions_for_assistive_tech():
    for control in ("token", "agent", "model", "message"):
        assert f'for="{control}"' in HTML, f"no <label for={control}>"
    assert 'role="log"' in HTML and 'aria-live="polite"' in HTML and 'role="alert"' in HTML
    assert 'type="password"' in HTML and 'autocomplete="off"' in HTML


@pytest.mark.parametrize(
    "pattern,why",
    [(r"\binnerHTML\b", "innerHTML renders untrusted model text as markup"), (r"\bouterHTML\b", "outerHTML"), (r"insertAdjacentHTML", "insertAdjacentHTML"),
     (r"document\.write", "document.write"), (r"\beval\s*\(", "eval"), (r"new\s+Function\b", "Function constructor"),
     (r"\blocalStorage\b", "token must not persist"), (r"\bsessionStorage\b", "token must not persist"), (r"document\.cookie", "cookie"),
     (r"location\.(?:search|hash)", "token must not travel in the URL"), (r"https?://", "no absolute URLs"), (r"\bEventSource\b", "cannot send the token header")],
)
def test_script_avoids_dangerous_apis(pattern, why):
    code = re.sub(r"//[^\n]*", "", JS)  # comments may mention what is avoided
    # The one reviewed use of location.hash: reading a draft handed over from the PrintLab workbench. It is not the token,
    # and it is pinned to this exact expression so any other read of the address still fails this test.
    code = code.replace("/^#draft=(.*)$/.exec(location.hash)", "")
    assert not re.search(pattern, code), why


def test_script_renders_server_text_only_through_textContent_and_clears_the_token_field():
    assert JS.count("textContent") >= 6
    assert re.search(r'\$\("token"\)\.value\s*=\s*""', JS), "the token input must be emptied after use"
    assert 'credentials: "omit"' in JS and 'cache: "no-store"' in JS


def test_css_has_no_remote_imports_and_respects_keyboard_focus():
    assert "@import" not in CSS and "url(" not in CSS
    assert ":focus-visible" in CSS and "prefers-color-scheme" in CSS


def test_static_files_are_declared_as_package_data():
    text = (WEB.parents[2] / "pyproject.toml").read_text(encoding="utf-8")
    assert "package-data" in text and "*.js" in text and "*.html" in text


def test_cancel_button_is_only_enabled_after_the_server_has_named_the_run():
    """Clicking cancel before the run id is known would silently do nothing (found with a real browser)."""
    code = re.sub(r"//[^\n]*", "", JS)
    set_busy = code[code.index("function setBusy"):code.index("async function loadAgents")]
    assert '$("cancel").disabled = true' in set_busy and "!busy" not in set_busy
    start = code[code.index('name === "start"'):]
    assert '$("cancel").disabled = false' in start.split("\n", 1)[0]


def test_page_declares_an_icon_so_browsers_do_not_request_a_missing_favicon():
    assert 'rel="icon"' in HTML


def test_workflow_panel_has_labelled_controls_and_live_status():
    for control in ("wf-name", "wf-project", "wf-brief"):
        assert f'for="{control}"' in HTML, f"no <label for={control}>"
    assert 'id="wf-status"' in HTML and 'role="status"' in HTML and 'aria-labelledby="wf-title"' in HTML
    for button in ("wf-start", "wf-yes", "wf-no", "wf-retry", "wf-stop", "wf-close"):
        assert f'id="{button}"' in HTML


def test_workflow_script_renders_model_text_only_as_text_and_has_no_polling_hack():
    code = re.sub(r"//[^\n]*", "", JS)
    block = code[code.index("let currentWorkflowRun"):]
    assert "textContent" in block and "innerHTML" not in block
    assert "setInterval" not in code and "originalReveal" not in code
    assert "crypto.getRandomValues" in block, "request ids must be unpredictable, not Math.random"
    assert "Math.random" not in code


def test_workflow_answers_are_exactly_yes_or_no_in_the_script():
    code = re.sub(r"//[^\n]*", "", JS)
    assert '["wf-yes", "yes"]' in code and '["wf-no", "no"]' in code
    assert not re.search(r"answer\s*[:=]\s*\$\(", code), "the answer must never be read from free text"


def test_workflow_lists_load_only_after_the_token_gate_is_passed():
    code = re.sub(r"//[^\n]*", "", JS)
    gate = code[code.index('$("gate-form").addEventListener'):]
    ok_at = gate.index('$("conn").classList.add("ok")')
    assert "loadWorkflows()" in gate[ok_at:ok_at + 200]


@pytest.mark.parametrize("name,html,js", [("chat", HTML, JS), ("admin", (WEB / "admin.html").read_text(encoding="utf-8"), (WEB / "admin.js").read_text(encoding="utf-8"))])
def test_both_pages_link_to_the_printlab_workbench_without_losing_the_token(name, html, js):
    # Opened in a new tab: the token lives only in this page's memory, so navigating away would lose it.
    link = re.search(r'<a id="to-printlab"[^>]*>', html)
    assert link, name
    assert 'target="_blank"' in link.group(0) and 'rel="noreferrer"' in link.group(0), name
    # The address is set by the script (no inline script is allowed) and points at port 8018 on the page's own host.
    assert '$("to-printlab").href = `${location.protocol}//${location.hostname}:8018/`' in js, name
    assert "8018" not in html  # no hard-coded address in the markup
    # Every link to another page opens in a new tab, for the same reason.
    for tag in re.findall(r'<a [^>]*href="/(?:chat|admin)"[^>]*>', html):
        assert 'target="_blank"' in tag and 'rel="noreferrer"' in tag, (name, tag)


def test_the_draft_from_printlab_is_read_once_stripped_from_the_address_and_never_sent():
    # Behaviour is proven in a real browser by tests/browser_smoke.py; these checks pin the safety properties of the script itself.
    assert JS.count("location.hash") == 1 and "/^#draft=(.*)$/.exec(location.hash)" in JS  # the single reviewed read
    assert "history.replaceState(null" in JS  # the fragment is removed from the address as soon as it is read
    # the token never touches the address: the hand-off code does not mention it, and nothing else reads the address either
    takeover = JS[JS.index("(function takeDraft()"):JS.index("})();")]
    assert "token" not in takeover
    assert "MAX_DRAFT = 2000" in JS and ".slice(0, MAX_DRAFT)" in JS  # bounded
    # it is only ever placed in the message box; no code path sends it, stores it, or builds markup from it
    use = JS[JS.index("if (handedOverDraft) {"):]
    use = use[:use.index("handedOverDraft = \"\";")]
    assert '$("message").value = handedOverDraft' in use
    assert "send(" not in use and "requestSubmit" not in use and "fetch(" not in use and "json(" not in use


def test_the_draft_is_cleaned_before_it_is_used():
    takeover = JS[JS.index("(function takeDraft()"):JS.index("})();")]
    # control characters other than the line break are dropped, then the text is cut to the cap and trimmed
    assert r'.filter((c) => c === "\n" || c >= " ")' in takeover
    assert takeover.index(".filter(") < takeover.index(".slice(0, MAX_DRAFT)") < takeover.index(".trim()")
    assert "decodeURIComponent(" in takeover and "catch (_)" in takeover  # a malformed fragment is caught, not thrown
