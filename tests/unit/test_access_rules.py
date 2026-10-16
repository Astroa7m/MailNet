"""Who sees the analytics dashboard, and what an unknown path does.

- The dashboard opens only for addresses in ANALYTICS_ADMIN_EMAILS, matched
  against the stored Gmail OR Outlook address (never the session's claim).
- A path no route matches sends a browser home; a real endpoint that answers
  404 on purpose keeps answering 404.
"""
import sys

import pytest
from bson import ObjectId
from fastapi.testclient import TestClient

sys.path.insert(0, "app")
import app.api as api

ME = str(ObjectId())


class _Users:
    def __init__(self, doc):
        self.doc = doc

    def find_one(self, *_a, **_k):
        return self.doc


@pytest.fixture
def account(monkeypatch):
    def _set(google=None, outlook=None, allow=("me@gmail.com", "me@hotmail.com")):
        monkeypatch.setattr(api, "ANALYTICS_ADMIN_EMAILS", set(allow))
        monkeypatch.setattr(api, "db", {"users": _Users({"google_email": google, "outlook_email": outlook})})
    return _set


def test_gmail_on_the_list_can_view(account):
    account(google="Me@Gmail.com")
    assert api._can_view_analytics(ME)


def test_outlook_on_the_list_can_view(account):
    account(outlook="me@hotmail.com")
    assert api._can_view_analytics(ME)


def test_anyone_else_cannot(account):
    account(google="someone@gmail.com", outlook="someone@hotmail.com")
    assert not api._can_view_analytics(ME)


def test_empty_list_locks_everyone_out(account):
    account(google="me@gmail.com", allow=())
    assert not api._can_view_analytics(ME)


def test_unset_or_blank_env_means_nobody(monkeypatch):
    """No fallback to ADMIN_EMAIL or anything else hidden in code."""
    monkeypatch.delenv("ANALYTICS_ADMIN_EMAILS", raising=False)
    assert api._load_analytics_admins() == set()
    monkeypatch.setenv("ANALYTICS_ADMIN_EMAILS", " , ")
    assert api._load_analytics_admins() == set()
    monkeypatch.setenv("ANALYTICS_ADMIN_EMAILS", "A@x.com, b@y.com")
    assert api._load_analytics_admins() == {"a@x.com", "b@y.com"}


def test_no_session_or_bad_id_is_refused(account):
    account(google="me@gmail.com")
    assert not api._can_view_analytics(None)
    assert not api._can_view_analytics("not-an-object-id")


@pytest.fixture
def client():
    return TestClient(api.app, follow_redirects=False)


def test_unknown_path_redirects_home(client, monkeypatch):
    monkeypatch.setenv("FRONTEND_URL", "https://getmailnet.com")
    r = client.get("/wp-admin/install.php")
    assert r.status_code == 302 and r.headers["location"] == "https://getmailnet.com"


def test_admin_stats_without_a_session_stays_a_plain_404(client):
    """A real endpoint refusing on purpose must not turn into a redirect."""
    r = client.get("/admin/stats")
    assert r.status_code == 404


def test_unknown_non_get_is_still_a_404(client):
    assert client.post("/definitely-not-a-route").status_code == 404
