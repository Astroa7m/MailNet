"""Content Security Policy on what FastAPI serves.

The rule that matters: the nonce in the header must equal the nonce on the
page's own <script>, fresh per request, and nothing else in the page may run
code. If those drift apart the login page silently stops working, which is
exactly the kind of break a test should catch before a user does.
"""
import re
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, "app")
import app.api as api


@pytest.fixture
def client(monkeypatch):
    # Jinja looks templates up relative to the working directory, which is
    # app/ inside the container.
    monkeypatch.chdir("app")
    return TestClient(api.app, follow_redirects=False)


def _nonce(csp: str) -> str:
    m = re.search(r"'nonce-([^']+)'", csp)
    assert m, f"no nonce in policy: {csp}"
    return m.group(1)


def test_login_page_script_carries_the_header_nonce(client):
    r = client.get("/login")
    assert r.status_code == 200
    csp = r.headers["content-security-policy"]
    nonce = _nonce(csp)
    scripts = re.findall(r"<script([^>]*)>", r.text)
    assert scripts, "login page should have its script"
    assert all(f'nonce="{nonce}"' in attrs for attrs in scripts)
    assert "frame-ancestors 'none'" in csp and "object-src 'none'" in csp


def test_nonce_is_fresh_every_request(client):
    a = _nonce(client.get("/login").headers["content-security-policy"])
    b = _nonce(client.get("/login").headers["content-security-policy"])
    assert a != b


@pytest.mark.parametrize("path", ["/login", "/privacy", "/terms"])
def test_no_inline_event_handlers_in_any_page(client, path):
    """The policy blocks onclick="" and friends, so any left behind would be
    a dead button."""
    html = client.get(path).text
    assert not re.search(r"<[^>]+\son[a-z]+\s*=", html), f"inline handler left in {path}"


def test_non_html_responses_allow_nothing(client):
    r = client.get("/admin/stats")  # a JSON 404
    assert r.headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'; sandbox"
