from email_client.BaseEmailProvider import EmailClient


class OutlookClient(EmailClient):
    async def send_email(self, to, subject, body): raise NotImplementedError("Outlook not yet supported")

    async def draft_email(self, to, subject, body): raise NotImplementedError("Outlook not yet supported")

    async def send_draft(self, draft_id): raise NotImplementedError("Outlook not yet supported")

    async def search_emails(self, sender=None, subject=None, has_attachment=False, after=None, before=None,
                            unread=False, label=None, msg_id=None, max_results=10): raise NotImplementedError(
        "Outlook not yet supported")

    async def read_emails(self, max_results=5, days_back=5): raise NotImplementedError("Outlook not yet supported")

    async def reply_to_email(self, msg_id, body): raise NotImplementedError("Outlook not yet supported")

    async def delete_email(self, msg_id): raise NotImplementedError("Outlook not yet supported")

    async def archive_email(self, msg_id): raise NotImplementedError("Outlook not yet supported")

    async def toggle_label_email(self, msg_id, label_name, action="add"): raise NotImplementedError(
        "Outlook not yet supported")
