from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import os.path, pickle

SCOPES = [
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/gmail.labels',
    'https://www.googleapis.com/auth/gmail.modify',

]

def get_gmail_service():
    creds = None
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
        creds = flow.run_local_server(port=0)
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)

    return build('gmail', 'v1', credentials=creds)


import base64
from email.mime.text import MIMEText

def send_email(service, to, subject, body):
    message = MIMEText(body)
    message['to'] = to
    message['subject'] = subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()

    send_message = {'raw': raw}
    service.users().messages().send(userId='me', body=send_message).execute()


def read_emails(service, max_results=5):
  results = service.users().messages().list(userId='me', maxResults=max_results).execute()
  messages = results.get('messages', [])

  for msg in messages:
    msg_data = service.users().messages().get(userId='me', id=msg['id']).execute()
    headers = msg_data['payload']['headers']
    subject = next((h['value'] for h in headers if h['name'] == 'Subject'), 'No Subject')
    sender = next((h['value'] for h in headers if h['name'] == 'From'), 'Unknown Sender')
    print(f"From: {sender}\nSubject: {subject}\n---")




send_email(get_gmail_service(), "ahmed123.as27@gmail.com","Test email subject from python", "test email body from python")