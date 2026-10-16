"""Body-size guard and quiet validation errors on /agent (security review F5).

An anonymous caller used to make the server buffer, parse, and validate a 25 MB
body before the 401 check, then get the whole body echoed back in the 422. The
size guard rejects on Content-Length before any parsing, and the validation
handler no longer returns the submitted input.
"""
import asyncio
import json
import sys

import pytest
from fastapi.exceptions import RequestValidationError
from fastapi.testclient import TestClient

sys.path.insert(0, "app")
import app.api as api


@pytest.fixture
def client():
    return TestClient(api.app, follow_redirects=False)


def test_agent_oversized_body_rejected_before_parsing(client):
    big = b"x" * (api._MAX_BODY_BYTES["/agent"] + 1)
    r = client.post("/agent", content=big, headers={"content-type": "application/json"})
    assert r.status_code == 413


def test_agent_small_body_not_blocked_by_size(client):
    # A small body passes the size gate (it may then 401/422/404, just not 413).
    r = client.post("/agent", json={"hello": "world"})
    assert r.status_code != 413


def test_validation_error_does_not_echo_input():
    exc = RequestValidationError([
        {"type": "missing", "loc": ("body", "threadId"), "msg": "field required",
         "input": {"secret_payload": "x" * 5000}},
    ])
    resp = asyncio.run(api._validation_error(None, exc))
    assert resp.status_code == 422
    assert "secret_payload" not in resp.body.decode()
    detail = json.loads(resp.body)["detail"]
    assert all("input" not in d for d in detail)
