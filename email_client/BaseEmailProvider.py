from abc import ABC, abstractmethod
from typing import Tuple, Dict, Union, List, Optional


class EmailClient(ABC):
    OP_RESULT = "operation_status"
    OP_MESSAGE = "operation_message"
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

    @abstractmethod
    async def send_email(self, to: str, subject: str, body: str) -> Tuple[str, str, Dict]:
        """
        Sends an email to the specified recipient.

        Used to initiate outbound communication. Returns metadata about the sent message.

        Args:
            to (str): Recipient email address.
            subject (str): Subject line of the email.
            body (str): Content of the email body (plain text or HTML).

        Returns:
            Tuple[str, str, Dict]: A tuple containing:
                - operation_status: 'succeeded' or 'failed' (EmailingStatus enum).
                - operation_message: Description of the operation result.
                - result: Dict containing metadata (e.g., message ID, thread ID).
        """
        pass

    @abstractmethod
    async def draft_email(self, to: str, subject: str, body: str) -> Tuple[str, str, Dict]:
        """
        Creates a draft email without sending it.

        Used to prepare messages for later review or scheduling.

        Args:
            to (str): Intended recipient email address.
            subject (str): Subject line of the draft.
            body (str): Content of the draft message.

        Returns:
            Tuple[str, str, Dict]: A tuple containing:
                - operation_status: 'succeeded' or 'failed'.
                - operation_message: Description of the draft creation result.
                - result: Dict containing metadata (e.g., draft ID).
        """
        pass

    @abstractmethod
    async def send_draft(self, draft_id: str) -> Tuple[str, str, Dict]:
        """
        Sends a previously created draft email.

        Args:
            draft_id (str): Unique identifier of the draft message.

        Returns:
            Tuple[str, str, Dict]: A tuple containing:
                - operation_status: 'succeeded' or 'failed'.
                - operation_message: Description of the send operation.
                - result: Dict containing metadata about the sent message.
        """
        pass

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
        """
        Searches for emails matching the given filters.

        Used to locate specific messages or threads. Returns a list unless `msg_id` is provided.

        Args:
            sender (Optional[str]): Filter by sender email address.
            subject (Optional[str]): Filter by subject line.
            has_attachment (bool): Whether to filter for messages with attachments.
            after (Optional[str]): Start date in 'YYYY/MM/DD' format.
            before (Optional[str]): End date in 'YYYY/MM/DD' format.
            unread (bool): Whether to filter for unread messages.
            label (Optional[str]): Filter by label or category.
            msg_id (Optional[str]): Search for a specific message ID.
            max_results (int): Maximum number of results to return.

        Returns:
            Tuple[str, str, List[Dict]]: A tuple containing:
                - operation_status: 'succeeded' or 'failed'.
                - operation_message: Description of the search outcome.
                - result: List of message metadata dicts (or single dict if `msg_id` is used).
        """
        pass

    @abstractmethod
    async def read_emails(self, max_results: int = 5, days_back: int = 5) -> Tuple[str, str, List[Dict]]:
        """
        Reads recent emails received within the past `days_back` days.

        Used to retrieve inbox context for summarization, triage, or reply.

        Args:
            max_results (int): Maximum number of messages to return.
            days_back (int): Number of days to look back from today.

        Returns:
            Tuple[str, str, List[Dict]]: A tuple containing:
                - operation_status: 'succeeded' or 'failed'.
                - operation_message: Description of the read operation.
                - result: List of message metadata dicts, sorted by recency.
        """
        pass

    @abstractmethod
    async def reply_to_email(self, msg_id: str, body: str) -> Tuple[str, str, Dict]:
        """
        Sends a reply to the specified message.

        Used to continue a conversation thread.

        Args:
            msg_id (str): ID of the message to reply to.
            body (str): Content of the reply message.

        Returns:
            Tuple[str, str, Dict]: A tuple containing:
                - operation_status: 'succeeded' or 'failed'.
                - operation_message: Description of the reply operation.
                - result: Dict containing metadata about the reply message.
        """
        pass

    @abstractmethod
    async def delete_email(self, msg_id: str) -> Tuple[str, str, Dict]:
        """
        Deletes the specified message.

        Args:
            msg_id (str): ID of the message to delete.

        Returns:
            Tuple[str, str, Dict]: A tuple containing:
                - operation_status: 'succeeded' or 'failed'.
                - operation_message: Description of the deletion result.
                - result: Dict containing deletion metadata or confirmation.
        """
        pass

    @abstractmethod
    async def archive_email(self, msg_id: str) -> Tuple[str, str, Dict]:
        """
        Archives the specified message (e.g., removes it from the inbox).

        Args:
            msg_id (str): ID of the message to archive.

        Returns:
            Tuple[str, str, Dict]: A tuple containing:
                - operation_status: 'succeeded' or 'failed'.
                - operation_message: Description of the archive result.
                - result: Dict containing updated message metadata.
        """
        pass

    @abstractmethod
    async def toggle_label_email(self, msg_id: str, label_name: str, action: str = "add") -> Tuple[str, str, Dict]:
        """
        Adds or removes a label/category from the specified message.

        Used to organize or tag messages for agentic workflows.

        Args:
            msg_id (str): ID of the message to modify.
            label_name (str): Name of the label or category.
            action (str): Either "add" or "remove".

        Returns:
            Tuple[str, str, Dict]: A tuple containing:
                - operation_status: 'succeeded' or 'failed'.
                - operation_message: Description of the label toggle result.
                - result: Dict containing updated message metadata.
        """
        pass

