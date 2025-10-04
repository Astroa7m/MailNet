from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Depends

from api.models import Provider
from common import assign_doc
from email_client import BaseEmailProvider
from email_client.gmail_helpers import GmailClient
from email_client.outlook_helpers import OutlookClient

app = FastAPI(title="Email MCP Server")

# by default provider = Google, will change later
def get_client(provider: Provider = Provider.GOOGLE) -> BaseEmailProvider:
    path = Path(__file__).resolve().parents[1]
    credentials = path / "credentials.json"
    token = path / "token.json"
    return GmailClient(credentials, token) if provider == Provider.GOOGLE else OutlookClient()


import time

start = time.time()
print("Client initialized in", time.time() - start, "seconds")


@assign_doc()
@app.post("/send_email")
async def send_email(to, subject, body, client=Depends(get_client)):
    return await client.send_email(to, subject, body)


@assign_doc()
@app.post("/draft_email")
async def draft_email(to: str, subject: str, body: str, client=Depends(get_client)):
    return await client.draft_email(to, subject, body)


@assign_doc()
@app.post("/send_draft")
async def send_draft(draft_id: str, client=Depends(get_client)):
    return await client.send_draft(draft_id)


@assign_doc()
@app.get("/read_emails")
async def read_emails(max_results: int = 5, days_back: int = 5, client=Depends(get_client)):
    return await client.read_emails(max_results=max_results, days_back=days_back)


@assign_doc()
@app.get("/search_emails")
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
        client=Depends(get_client)
):
    return await client.search_emails(
        sender, subject, has_attachment, after, before, unread, label, msg_id, max_results
    )


@assign_doc()
@app.post("/reply_to_email")
async def reply_to_email(msg_id: str, body: str, client=Depends(get_client)):
    return await client.reply_to_email(msg_id, body)


@assign_doc()
@app.delete("/delete_email/{msg_id}")
async def delete_email(msg_id: str, client=Depends(get_client)):
    return await client.delete_email(msg_id)


@assign_doc()
@app.post("/archive_email/{msg_id}")
async def archive_email(msg_id: str, client=Depends(get_client)):
    return await client.archive_email(msg_id)


@assign_doc()
@app.post("/toggle_label")
async def toggle_label(msg_id: str, label_name: str, action: str = "add", client=Depends(get_client)):
    return await client.toggle_label_email(msg_id, label_name, action)