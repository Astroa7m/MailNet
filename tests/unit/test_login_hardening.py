"""Logout CSRF guard, timezone validation, prod docs/cookie flag
(security review F13, F14, F15, F17)."""
import sys

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, "app")
import app.api as api


@pytest.fixture
def client():
    return TestClient(api.app, follow_redirects=False)


# ---- F13: logout is not a silent cross-site GET ------------------------------

def test_logout_cross_site_gets_confirm_not_logout(client):
    r = client.get("/logout", headers={"sec-fetch-site": "cross-site"})
    assert r.status_code == 200 and "Log out" in r.text


def test_logout_same_origin_redirects(client):
    r = client.get("/logout", headers={"sec-fetch-site": "same-origin"})
    assert r.status_code in (302, 307) and r.headers["location"] == "/"


def test_logout_post_clears_and_redirects(client):
    r = client.post("/logout")
    assert r.status_code == 303 and r.headers["location"] == "/"


# ---- F15: a timezone from a query string is validated ------------------------

def test_safe_tz_accepts_real_zone():
    assert api._safe_tz("Asia/Muscat") == "Asia/Muscat"


def test_safe_tz_rejects_injection_and_junk():
    assert api._safe_tz("'; DROP TABLE users; --") == "UTC"
    assert api._safe_tz("<script>alert(1)</script>") == "UTC"
    assert api._safe_tz(None) == "UTC"
    assert api._safe_tz("Not/AZone") == "UTC"


# ---- F14 / F17: production flag is not an exact-string trap ------------------

def test_is_production_is_case_and_space_insensitive():
    assert api._is_production("production")
    assert api._is_production("Production ")
    assert api._is_production("  PRODUCTION")
    assert not api._is_production("prod")
    assert not api._is_production(None)
    assert not api._is_production("")


def test_docs_are_open_outside_production():
    # The suite runs with ENVIRONMENT unset, so docs stay available locally.
    assert api.app.docs_url == "/docs"
    assert api.app.openapi_url == "/openapi.json"
