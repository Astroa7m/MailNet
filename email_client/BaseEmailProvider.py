from abc import ABC, abstractmethod
from typing import Tuple, Dict, Union, List, Optional

from common import assign_doc


class EmailClient(ABC):
    """
     Abstract base class for email client integrations.

    This interface defines a unified set of asynchronous methods for interacting with email providers
    such as Gmail, Outlook, or custom IMAP services. It enables agentic orchestration of email workflows
    including sending, reading, searching, replying, archiving, and label management.

    Concrete implementations (e.g., GmailClient, OutlookClient (WIP)) must implement all methods to ensure
    consistent behavior across providers.

    All methods within this class return a tuple of the following keys:
    - 'operation_status': Indicates operation success/failure status. Possible values: 'succeeded' or 'failed'.
    Based on Enum class (EmailingStatus) under util module

    - 'operation_message': A descriptive message about the current operation success/failure.

    - 'result': Could contain either:
        * A dict contains metadata about the email being processed (e.g., message ID, thread ID).
        * A list of dict containing metadata, which could happen in two scenarios only.
        By either calling read_emails which returns a list or calling search_emails without msg_id
    """
    OP_RESULT = "operation_status"
    OP_MESSAGE = "operation_message"

    @assign_doc()
    @abstractmethod
    async def send_email(self, to: str, subject: str, body: str) -> Tuple[str, str, Dict]:
        pass

    @assign_doc()
    @abstractmethod
    async def draft_email(self, to: str, subject: str, body: str) -> Tuple[str, str, Dict]:
        pass

    @assign_doc()
    @abstractmethod
    async def send_draft(self, draft_id: str) -> Tuple[str, str, Dict]:
        pass

    @assign_doc()
    @abstractmethod
    async def search_emails(
            self,
            sender: Optional[str] = None,
            subject: Optional[str] = None,
            has_attachment: bool = False,
            after: Optional[str] = None,
            before: Optional[str] = None,
            unread: bool = False,
            label: Optional[str] = None,
            msg_id: Optional[str] = None,
            max_results: int = 10
    ) -> Tuple[str, str, List[Dict]]:
        pass

    @assign_doc()
    @abstractmethod
    async def read_emails(self, max_results: int = 5, days_back: int = 5) -> Tuple[str, str, List[Dict]]:
        pass

    @assign_doc()
    @abstractmethod
    async def reply_to_email(self, msg_id: str, body: str) -> Tuple[str, str, Dict]:
        pass

    @assign_doc()
    @abstractmethod
    async def delete_email(self, msg_id: str) -> Tuple[str, str, Dict]:
        pass

    @assign_doc()
    @abstractmethod
    async def archive_email(self, msg_id: str) -> Tuple[str, str, Dict]:
        pass

    @assign_doc()
    @abstractmethod
    async def toggle_label_email(self, msg_id: str, label_name: str, action: str = "add") -> Tuple[str, str, Dict]:
        pass

