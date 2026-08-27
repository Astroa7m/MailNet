"""Stub mail tools for the eval harness.

Each function mirrors the real FastMCP server tool in mcp-server/mcp_launcher/
server.py: same name, same signature, same defaults, and the same JSON
envelope ({"operation_status", "operation_message", "result": ...}) returned
as a STRING, which is what reaches the model through langchain-mcp-adapters.
The model under eval cannot tell these from the real tools; the difference is
that they touch a fixture inbox instead of a mailbox and record every call.

present_triage is not an MCP tool in production (it is a frontend CopilotKit
action), but the briefing scenario asserts on it, so a faithful stand-in with
the frontend schema lives here too.
"""
import json
from pathlib import Path
from typing import List, Optional

_FIXTURE = Path(__file__).parent / "fixtures" / "inbox.json"

# Every call lands here as (tool_name, kwargs). Scenarios assert on it.
CALL_LOG: list = []


def reset_log() -> None:
    CALL_LOG.clear()


def _inbox() -> list:
    return json.loads(_FIXTURE.read_text(encoding="utf-8"))


def _ok(result, message="succeeded") -> str:
    return json.dumps(
        {"operation_status": "succeeded", "operation_message": message, "result": result}
    )


async def read_emails(max_results: int = 5, days_back: int = 5, provider: Optional[str] = None):
    """Read the most recent emails from the inbox. Returns newest first."""
    CALL_LOG.append(("read_emails", {"max_results": max_results, "days_back": days_back, "provider": provider}))
    return _ok(_inbox()[: int(max_results)], "emails fetched")


async def search_emails(
    sender: Optional[str] = None,
    subject: Optional[str] = None,
    has_attachment: bool = False,
    after: Optional[str] = None,
    before: Optional[str] = None,
    unread: bool = False,
    label: Optional[str] = None,
    msg_id: Optional[str] = None,
    max_results: int = 10,
    provider: Optional[str] = None,
):
    """Search emails by sender, subject, attachment presence, date range,
    unread state, label, or message id."""
    CALL_LOG.append(("search_emails", {
        "sender": sender, "subject": subject, "has_attachment": has_attachment,
        "after": after, "before": before, "unread": unread, "label": label,
        "msg_id": msg_id, "max_results": max_results, "provider": provider,
    }))
    hits = []
    for m in _inbox():
        if msg_id and m["id"] != msg_id:
            continue
        if sender and sender.lower() not in m["sender"].lower():
            continue
        if subject and subject.lower() not in m["subject"].lower():
            continue
        if has_attachment and not m["attachments"]:
            continue
        if unread and "UNREAD" not in m["labelIds"]:
            continue
        if label and label.upper() not in [x.upper() for x in m["labelIds"]]:
            continue
        hits.append(m)
    return _ok(hits[: int(max_results)], f"{len(hits)} matches")


async def send_email(to: str, subject: str, body: str, attachment_ids: Optional[List[str]] = None):
    """Send an email. If the user attached files, pass their IDs as
    attachment_ids to include the files in the email."""
    CALL_LOG.append(("send_email", {"to": to, "subject": subject, "body": body, "attachment_ids": attachment_ids}))
    return _ok({"id": "sent_stub_001", "to": to, "subject": subject}, "Email has been sent successfully")


async def draft_email(to: str, subject: str, body: str, attachment_ids: Optional[List[str]] = None):
    """Save an email as a draft without sending it."""
    CALL_LOG.append(("draft_email", {"to": to, "subject": subject, "body": body, "attachment_ids": attachment_ids}))
    return _ok({"draft_id": "draft_stub_001", "to": to, "subject": subject}, "Draft saved")


async def send_draft(draft_id: str):
    """Send a previously saved draft by its id."""
    CALL_LOG.append(("send_draft", {"draft_id": draft_id}))
    return _ok({"id": "sent_stub_002", "draft_id": draft_id}, "Draft sent")


async def reply_to_email(msg_id: str, body: str, attachment_ids: Optional[List[str]] = None):
    """Reply to an email identified by msg_id."""
    CALL_LOG.append(("reply_to_email", {"msg_id": msg_id, "body": body, "attachment_ids": attachment_ids}))
    known = {m["id"] for m in _inbox()}
    if msg_id not in known:
        return json.dumps({
            "operation_status": "failed",
            "operation_message": f"message {msg_id} not found",
            "result": None,
        })
    return _ok({"id": "reply_stub_001", "in_reply_to": msg_id}, "Reply sent")


async def delete_email(msg_id: str):
    """Move an email to trash."""
    CALL_LOG.append(("delete_email", {"msg_id": msg_id}))
    return _ok({"id": msg_id, "deleted": True}, "Email deleted")


async def archive_email(msg_id: str):
    """Archive an email (remove it from the inbox without deleting)."""
    CALL_LOG.append(("archive_email", {"msg_id": msg_id}))
    return _ok({"id": msg_id, "archived": True}, "Email archived")


async def toggle_label(msg_id: str, label_name: str, action: str = "add"):
    """Add or remove a label on an email. action is 'add' or 'remove'."""
    CALL_LOG.append(("toggle_label", {"msg_id": msg_id, "label_name": label_name, "action": action}))
    return _ok({"id": msg_id, "label": label_name, "action": action}, "Label updated")


async def download_attachment(msg_id: str, attachment_index: int = 0):
    """Download an attachment from a specific email message."""
    CALL_LOG.append(("download_attachment", {"msg_id": msg_id, "attachment_index": attachment_index}))
    for m in _inbox():
        if m["id"] == msg_id and m["attachments"]:
            att = m["attachments"][int(attachment_index)]
            return _ok({"filename": att["filename"], "mimeType": att["mimeType"],
                        "size": att["size"], "data": "c3R1Yg=="}, "Attachment downloaded")
    return json.dumps({
        "operation_status": "failed",
        "operation_message": "no such attachment",
        "result": None,
    })


async def update_email_settings(new_partial_settings: dict):
    """Updates the persisted email settings with partial overrides. Only
    provided fields are overridden; all others are preserved."""
    CALL_LOG.append(("update_email_settings", {"new_partial_settings": new_partial_settings}))
    return _ok(dict(new_partial_settings), "Settings updated")


async def present_triage(items: list):
    """Present a triaged view of the inbox to the user. Each item needs:
    msg_id, category (urgent | needs_action | fyi), sender, subject, reason."""
    CALL_LOG.append(("present_triage", {"items": items}))
    return _ok({"presented": len(items)}, "Triage rendered")


# Handed to build_agent(prefetched_mcp_tools=STUB_TOOLS). build_agent coerces
# plain async functions through its own coerce_tool path.
STUB_TOOLS = [
    read_emails, search_emails, send_email, draft_email, send_draft,
    reply_to_email, delete_email, archive_email, toggle_label,
    download_attachment, update_email_settings, present_triage,
]
