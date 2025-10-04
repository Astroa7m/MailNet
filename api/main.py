from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Depends
import os
from api.models import Provider, SendEmailRequest, DraftEmailRequest, ToggleLabelRequest, ReplyEmailRequest, \
    SendDraftRequest
from email_client import BaseEmailProvider
from email_client.gmail_helpers import GmailClient
from email_client.outlook_helpers import OutlookClient

app = FastAPI(title="Email MCP Server")

# by default, will change later
provider = Provider.GOOGLE


def get_client(provider: Provider) -> BaseEmailProvider:
    path = Path(__file__).resolve().parents[1]
    credentials = path / "credentials.json"
    token = path / "token.json"
    return GmailClient(credentials, token) if provider == Provider.GOOGLE else OutlookClient()


import time
start = time.time()
client = get_client(provider)
print("Client initialized in", time.time() - start, "seconds")

@app.post("/send_email")
async def send_email(req: SendEmailRequest, client=Depends(get_client)):
    return await client.send_email(req.to, req.subject, req.body)

@app.post("/draft_email")
async def draft_email(req: DraftEmailRequest, client=Depends(get_client)):
    return await client.draft_email(req.to, req.subject, req.body)

@app.post("/send_draft")
async def send_draft(req: SendDraftRequest, client=Depends(get_client)):
    return await client.send_draft(req.draft_id)

@app.get("/read_emails")
async def read_emails(max_results: int = 5, days_back: int = 5, client=Depends(get_client)):
    return await client.read_emails(max_results=max_results, days_back=days_back)

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

@app.post("/reply_to_email")
async def reply_to_email(req: ReplyEmailRequest, client=Depends(get_client)):
    return await client.reply_to_email(req.msg_id, req.body)

@app.delete("/delete_email/{msg_id}")
async def delete_email(msg_id: str, client=Depends(get_client)):
    return await client.delete_email(msg_id)

@app.post("/archive_email/{msg_id}")
async def archive_email(msg_id: str, client=Depends(get_client)):
    return await client.archive_email(msg_id)

@app.post("/toggle_label")
async def toggle_label(req: ToggleLabelRequest, client=Depends(get_client)):
    return await client.toggle_label_email(req.msg_id, req.label_name, req.action)




