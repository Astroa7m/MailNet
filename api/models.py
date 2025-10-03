from enum import Enum

from pydantic import BaseModel


class Provider(Enum):
    GOOGLE = "google"
    OUTLOOK = "outlook"


class SendEmailRequest(BaseModel):
    to: str
    subject: str
    body: str


class DraftEmailRequest(BaseModel):
    to: str
    subject: str
    body: str


class SendDraftRequest(BaseModel):
    draft_id: str


class ReplyEmailRequest(BaseModel):
    msg_id: str
    body: str


class ToggleLabelRequest(BaseModel):
    msg_id: str
    label_name: str
    action: str = "add"
