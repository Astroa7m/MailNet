import asyncio

from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
import os.path, pickle, base64
from email.mime.text import MIMEText

SCOPES = [
    'https://mail.google.com/',
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/gmail.labels',
    'https://www.googleapis.com/auth/gmail.modify',
]


def _get_gmail_service_sync():
    creds = None

    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES
            )
            creds = flow.run_local_server(port=0, include_granted_scopes='true')

        with open('token.json', 'w') as token:
            token.write(creds.to_json())

    return build('gmail', 'v1', credentials=creds)


def _get_after_date(days_back=5):
    cutoff = datetime.utcnow() - timedelta(days=days_back)
    return cutoff.strftime('%Y/%m/%d')


def _prep_message_raw(to, subject, body, original_msg_id=None):
    message = MIMEText(body)
    message['to'] = to
    message['subject'] = subject

    if original_msg_id:
        message['In-Reply-To'] = original_msg_id
        message['References'] = original_msg_id

    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    return raw


async def _get_labels():
    try:
        service = await get_gmail_service()
        labels = await asyncio.to_thread(service.users().labels().list(userId='me').execute)
        return labels.get('labels', [])
    except Exception as e:
        print(f"Label fetch failed: {e}")
        return []


async def get_gmail_service():
    return await asyncio.to_thread(_get_gmail_service_sync)


async def send_email(to, subject, body):
    try:
        service = await get_gmail_service()
        raw = _prep_message_raw(to, subject, body)
        await asyncio.to_thread(service.users().messages().send(userId='me', body={'raw': raw}).execute)
    except Exception as e:
        print(f"Send failed: {e}")


async def draft_email(to, subject, body):
    try:
        service = await get_gmail_service()
        raw = _prep_message_raw(to, subject, body)
        draft = {"message": {"raw": raw}}
        response = await asyncio.to_thread(service.users().drafts().create(userId='me', body=draft).execute)
        return response['id']
    except Exception as e:
        print(f"Draft failed: {e}")


async def send_draft(draft_id):
    try:
        service = await get_gmail_service()
        await asyncio.to_thread(service.users().drafts().send(userId='me', body={'id': draft_id}).execute)
    except Exception as e:
        print(f"Send draft failed: {e}")


from datetime import datetime, timedelta


def extract_body(payload):
    if 'parts' in payload:
        for part in payload['parts']:
            if part.get('mimeType') == 'text/plain' and 'body' in part:
                data = part['body'].get('data')
                if data:
                    return base64.urlsafe_b64decode(data).decode(errors='ignore')
    # Fallback to top-level body
    data = payload.get('body', {}).get('data')
    if data:
        return base64.urlsafe_b64decode(data).decode(errors='ignore')
    return ""


def extract_attachments(payload):
    attachments = []
    if 'parts' in payload:
        for part in payload['parts']:
            filename = part.get('filename')
            if filename:
                attachments.append(filename)
    return attachments


def convert_to_datetime(timestamp):
    try:
        return datetime.fromtimestamp(int(timestamp) / 1000).isoformat()
    except:
        return None


async def search_emails(sender=None, subject=None, has_attachment=False, after=None, before=None,
                        unread=False, label=None, msg_id=None, max_results=10):
    try:
        service = await get_gmail_service()

        def parse_msg(msg_data):
            payload = msg_data.get('payload', {})
            headers = payload.get('headers', [])
            subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), 'No Subject')
            sender = next((h['value'] for h in headers if h['name'].lower() == 'from'), 'Unknown Sender')
            body = extract_body(payload)
            attachments = extract_attachments(payload)
            return {
                'id': msg_data['id'],
                'threadId': msg_data.get('threadId'),
                'subject': subject,
                'sender': sender,
                'body': body,
                'attachments': attachments,
                'labelIds': msg_data.get('labelIds', []),
                'dateTime': convert_to_datetime(msg_data.get('internalDate'))
            }

        if msg_id:
            msg_data = await asyncio.to_thread(
                service.users().messages().get(userId='me', id=msg_id, format='full').execute
            )
            return [parse_msg(msg_data)]

        query_parts = []
        if sender: query_parts.append(f"from:{sender}")
        if subject: query_parts.append(f"subject:{subject}")
        if has_attachment: query_parts.append("has:attachment")
        if after: query_parts.append(f"after:{after}")
        if before: query_parts.append(f"before:{before}")
        if unread: query_parts.append("is:unread")
        if label: query_parts.append(f"label:{label}")

        query = " ".join(query_parts)
        results = await asyncio.to_thread(
            service.users().messages().list(userId='me', q=query, maxResults=max_results).execute
        )
        messages = results.get('messages', [])
        enriched = []

        for msg in messages:
            msg_data = await asyncio.to_thread(
                service.users().messages().get(userId='me', id=msg['id'], format='full').execute
            )
            enriched.append(parse_msg(msg_data))

        return enriched

    except Exception as e:
        print(f"Search failed: {e}")
        return []


async def read_emails(max_results=5, days_back=5):
    try:
        after = _get_after_date(days_back)
        return await search_emails(
            max_results=max_results,
            after=after
        )
    except Exception as e:
        print(f"Read failed: {e}")
        return []


async def reply_to_email(msg_id, body):
    try:
        service = await get_gmail_service()
        message_info = (await search_emails(msg_id=msg_id))[0]

        raw = _prep_message_raw(
            to=message_info['sender'],
            subject="Re: " + message_info['subject'],
            body=body,
            original_msg_id=msg_id
        )

        message = {
            'raw': raw,
            'threadId': message_info['threadId']
        }

        await asyncio.to_thread(service.users().messages().send(userId='me', body=message).execute)

    except Exception as e:
        print(f"Reply failed: {e}")


async def delete_email(msg_id):
    try:
        service = await get_gmail_service()
        await asyncio.to_thread(service.users().messages().delete(userId='me', id=msg_id).execute)
    except Exception as e:
        print(f"Delete failed: {e}")


async def archive_email(msg_id):
    try:
        service = await get_gmail_service()
        await asyncio.to_thread(
            service.users().messages().modify(userId='me', id=msg_id, body={'removeLabelIds': ['INBOX']}).execute)
    except Exception as e:
        print(f"Archive failed: {e}")


async def toggle_label_email(msg_id, label_name, action="add"):
    try:
        service = await get_gmail_service()
        labels = await _get_labels()
        label_map = {label['name'].lower(): label['id'] for label in labels}
        label_id = label_map.get(label_name.lower())

        if not label_id:
            print(f"Label '{label_name}' not found.")
            print("Available labels:")
            for name in sorted(label_map.keys()):
                print(f"• {name}")
            return

        msg_data = await asyncio.to_thread(
            service.users().messages().get(userId='me', id=msg_id).execute
        )
        current_labels = msg_data.get('labelIds', [])

        if action == "add":
            if label_id not in current_labels:
                await asyncio.to_thread(service.users().messages().modify(
                    userId='me',
                    id=msg_id,
                    body={'addLabelIds': [label_id]}
                ).execute)
                print(f"Added label '{label_name}' to message {msg_id}")
            else:
                print(f"Label '{label_name}' already present on message {msg_id}")

        elif action == "remove":
            if label_id in current_labels:
                await asyncio.to_thread(service.users().messages().modify(
                    userId='me',
                    id=msg_id,
                    body={'removeLabelIds': [label_id]}
                ).execute)
                print(f"🗑️ Removed label '{label_name}' from message {msg_id}")
            else:
                print(f"Label '{label_name}' not present on message {msg_id}")

        else:
            print(f"Unknown action '{action}'. Use 'add' or 'remove'.")

    except Exception as e:
        print(f"Label processing failed: {e}")


async def test():
    print("Starting tests")
    """SENDING EMAIL"""
    await send_email("ahmed123.as27@gmail.com", "sending email from python", "Hello\nDw this is a test")
    print("Done sending email\n")

    """DRAFTING EMAIL"""
    draftId = await draft_email("ahmed123.as27@gmail.com", "draft email from python", "Hello\nDw this is a test draft")
    print("Done drafting email\n")
    await send_draft(draftId)
    print("Done sending draft email\n")

    """SEARCHING EMAIL"""
    result = await search_emails(sender="ahmed123.as27@gmail.com")
    print(f"Done searching emails, result:\n{result}\n")

    result = await search_emails(msg_id="180c3e86b5c1bc6a")
    print(f"Done searching emails by id, result:\n{result}\n")

    "READ EMAIL"""
    result = await read_emails()
    print(f"Done reading emails, result:\n{result}\n")

    """REPLYING TO EMAIL"""
    await reply_to_email(result[0]["id"], "Yeah sure, cool test, wow.")
    print("Done reply to email")

    """DELETING EMAIL"""
    await send_email("ahmed123.as27@gmail.com", "This email is going to be deleted", "Hello\nDw this will be deleted")
    to_be_deleted = await search_emails(subject="This email is going to be deleted", max_results=1)
    await delete_email(to_be_deleted[0]['id'])
    print("Done deleting email")

    """ARCHIVING EMAIL"""
    await send_email("ahmed123.as27@gmail.com", "This email is going to be archived", "Hello\nDw this will be archived")
    to_be_archived = await search_emails(subject="This email is going to be deleted", max_results=1)
    await archive_email(to_be_archived[0]['id'])
    print("Done archiving email")

    """LABELLING EMAIL"""
    await send_email("ahmed123.as27@gmail.com", "This email is going to be labelled", "Hello\nDw this will be labelled")
    to_be_labelled = await search_emails(subject="This email is going to be labelled", max_results=1)
    await toggle_label_email(to_be_labelled[0]['id'], "starred")
    print("Done labelling email with correct label")

    await toggle_label_email(to_be_labelled[0]['id'], "Fun")
    print("Done labelling email with wrong label")

    await toggle_label_email(to_be_labelled[0]['id'], "starred")
    print("Done removing label from email with")


if __name__ == "__main__":
    asyncio.run(test())
