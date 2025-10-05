import asyncio
import json
import os
import time
import webbrowser
from typing import Dict, Optional, Any

import aiohttp
from dotenv import load_dotenv
from msal import ConfidentialClientApplication

from email_client.BaseEmailProvider import EmailClient
from email_client.models import EmailingStatus

GRAPH_API = "https://graph.microsoft.com/v1.0"


# testing at https://developer.microsoft.com/en-us/graph/graph-explorer
class OutlookClient(EmailClient):
    SCOPES = [
        "https://graph.microsoft.com/Mail.ReadWrite",
        "https://graph.microsoft.com/Mail.Send",
        "https://graph.microsoft.com/MailboxSettings.ReadWrite",
        "https://graph.microsoft.com/User.Read"
    ]

    def __init__(self, client_id: str, client_secret: str, redirect_uri: str, token_file: str = "graph_token.json"):
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.token_file = token_file
        self.authority = "https://login.microsoftonline.com/consumers"
        self.app = ConfidentialClientApplication(
            client_id=self.client_id,
            client_credential=self.client_secret,
            authority=self.authority
        )
        self.token = self._load_or_authenticate()
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Content-Type": "application/json"
        }

    def _load_or_authenticate(self) -> str:
        if os.path.exists(self.token_file):
            with open(self.token_file, "r") as f:
                token_data = json.load(f)
                if token_data.get("expires_at", 0) > time.time():
                    return token_data["access_token"]
                if "refresh_token" in token_data:
                    return self._refresh_token(token_data["refresh_token"])

        # Launch browser for user consent
        auth_flow = self.app.initiate_auth_code_flow(
            scopes=self.SCOPES,
            redirect_uri=self.redirect_uri
        )
        print(f"\n Opening browser for authentication: {auth_flow['auth_uri']}")
        webbrowser.open(auth_flow['auth_uri'])
        code = input("Paste the authorization code here: ").strip()
        auth_response = {"code": code, "state": auth_flow["state"]}
        return self._exchange_code(auth_flow, auth_response)

    def _exchange_code(self, flow: dict, auth_response: dict) -> str:
        result = self.app.acquire_token_by_auth_code_flow(flow, auth_response)
        return self._store_token(result)

    def _refresh_token(self, refresh_token: str) -> str:
        result = self.app.acquire_token_by_refresh_token(refresh_token, scopes=self.SCOPES)
        return self._store_token(result)

    def _store_token(self, result: dict) -> str:
        if "access_token" in result:
            result["expires_at"] = time.time() + result.get("expires_in", 3600)
            with open(self.token_file, "w") as f:
                json.dump(result, f)
            return result["access_token"]
        raise Exception(f"Token acquisition failed: {result.get('error_description')}")

    async def _request(self, method: str, endpoint: str, **kwargs) -> dict[str, Any]:
        url = f"{GRAPH_API}{endpoint}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.request(method, url, headers=self.headers, **kwargs) as resp:

                    if resp.status in {200, 201, 202, 204}:
                        try:
                            data = await resp.json()
                            return data
                        except aiohttp.ContentTypeError:
                            return {}

                        # If failure, try to extract error
                    try:
                        error_data = await resp.json()
                    except aiohttp.ContentTypeError:
                        error_data = {}

                    raise Exception(resp.reason, error_data.get("error"))

        except Exception as e:
            raise RuntimeError(f"Request to {url} failed: {e}") from e

    async def send_email(self, to: str, subject: str, body: str) -> Dict[str, Any]:
        try:
            payload = {
                "message": {
                    "subject": subject,
                    "body": {"contentType": "Text", "content": body},
                    "toRecipients": [{"emailAddress": {"address": to}}]
                }
            }

            send_res = await self._request("POST", "/me/sendMail", json=payload)
            result = {self.OP_RESULT: EmailingStatus.SUCCEEDED, self.OP_MESSAGE: self.SEND_EMAIL_SUCCESS_MESSAGE,
                      "result": send_res}
            return result
        except Exception as e:
            result = {self.OP_RESULT: EmailingStatus.FAILED, self.OP_MESSAGE: str(e)}
            return result

    async def draft_email(self, to: str, subject: str, body: str) -> Dict[str, Any]:
        try:
            payload = {
                "subject": subject,
                "body": {"contentType": "Text", "content": body},
                "toRecipients": [{"emailAddress": {"address": to}}],
                "isDraft": "true"
            }
            draft_res = await self._request("POST", "/me/messages", json=payload)
            draft_id = {"draftId": draft_res['id']}
            result = {self.OP_RESULT: EmailingStatus.SUCCEEDED, self.OP_MESSAGE: self.DRAFT_EMAIL_SUCCESS_MESSAGE,
                      "result": draft_id}
            return result
        except Exception as e:
            result = {self.OP_RESULT: EmailingStatus.FAILED, self.OP_MESSAGE: str(e)}
            return result

    async def send_draft(self, draft_id: str) -> Dict[str, Any]:
        try:
            send_res = await self._request("POST", f"/me/messages/{draft_id}/send")
            result = {self.OP_RESULT: EmailingStatus.SUCCEEDED, self.OP_MESSAGE: self.SEND_DRAFT_EMAIL_SUCCESS_MESSAGE,
                      "result": send_res}
            return result
        except Exception as e:
            result = {self.OP_RESULT: EmailingStatus.FAILED, self.OP_MESSAGE: str(e)}
            return result

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
    ) -> Dict[str, Any]:
        raise NotImplementedError("Awaiting implementation")

    async def read_emails(self, max_results: int = 5, days_back: int = 5) -> Dict[str, Any]:
        raise NotImplementedError("Awaiting implementation")

    async def reply_to_email(self, msg_id: str, body: str) -> Dict[str, Any]:
        try:
            draft_resp = await self._request("POST", f"/me/messages/{msg_id}/reply")
            result = {self.OP_RESULT: EmailingStatus.SUCCEEDED, self.OP_MESSAGE: self.REPLY_TO_EMAIL_SUCCESS_MESSAGE,
                      "result": draft_resp}
            return result
        except Exception as e:
            result = {self.OP_RESULT: EmailingStatus.FAILED, self.OP_MESSAGE: str(e)}
            return result

    async def delete_email(self, msg_id: str) -> Dict[str, Any]:

        try:
            del_resp = await self._request("DELETE", f"/me/messages/{msg_id}")
            result = {self.OP_RESULT: EmailingStatus.SUCCEEDED, self.OP_MESSAGE: self.DELETE_EMAIL_SUCCESS_MESSAGE,
                      "result": del_resp}
            return result
        except Exception as e:
            result = {self.OP_RESULT: EmailingStatus.FAILED, self.OP_MESSAGE: str(e)}
            return result

    async def archive_email(self, msg_id: str) -> Dict[str, Any]:
        try:
            payload = {
                "destinationId": "Archive"
            }
            archive_resp = await self._request("POST", f"/me/messages/{msg_id}/move", json=payload)
            result = {self.OP_RESULT: EmailingStatus.SUCCEEDED, self.OP_MESSAGE: self.ARCHIVE_EMAIL_SUCCESS_MESSAGE,
                      "result": archive_resp}
            return result
        except Exception as e:
            result = {self.OP_RESULT: EmailingStatus.FAILED, self.OP_MESSAGE: str(e)}
            return result

    async def toggle_label_email(self, msg_id: str, label_name: str, action: str = "add") -> Dict[str, Any]:
        raise NotImplementedError("Awaiting implementation")


async def test():
    load_dotenv()
    client_id = os.getenv("AZURE_APPLICATION_CLIENT_ID")
    client_secret = os.getenv("AZURE_SECRET_VALUE")
    graph_client = OutlookClient(client_id=client_id, client_secret=client_secret,
                                 redirect_uri="http://localhost:3000/callback")

    print("Starting tests")

    """SENDING EMAIL"""
    result = await graph_client.send_email("ahmed123.as27@hotmail.com", "sending email from python",
                                           "Hello\nDw this is a test")
    print(f"Done sending email.\nResult: {result}")

    """DRAFTING EMAIL"""
    result = await graph_client.draft_email("ahmed123.as27@hotmail.com", "draft email from python",
                                            "Hello\nDw this is a test draft")
    print(f"Done drafting email\n\nResult: {result}")
    result = await graph_client.send_draft(result['result']['id'])
    print(f"Done sending draft email.\nResult: {result}")

    """SEARCHING EMAIL"""
    result = await graph_client.search_emails(sender="ahmed123.as27@hotmail.com")
    print(f"Done searching emails, result:\n{result}\n")

    result = await graph_client.search_emails(msg_id="199b039b68508ad4")
    print(f"Done searching emails by id, result:\n{result}\n")

    """READ EMAIL"""
    result = await graph_client.read_emails()
    print(f"Done reading emails, result:\n{result}\n")

    """REPLYING TO EMAIL"""
    result = await graph_client.reply_to_email(result["result"][0]["id"], "Yeah sure, cool test, wow.")
    print(f"Done replying to email.\nResult: {result}")

    """DELETING EMAIL"""
    await graph_client.send_email("ahmed123.as27@hotmail.com", "This email is going to be deleted",
                                  "Hello\nDw this will be deleted")
    to_be_deleted = await graph_client.search_emails(subject="This email is going to be deleted", max_results=1)
    result = await graph_client.delete_email(to_be_deleted["result"][0]["id"])
    print(f"Done deleting email.\nResult: {result}")

    """ARCHIVING EMAIL"""
    await graph_client.send_email("ahmed123.as27@hotmail.com", "This email is going to be archived",
                                  "Hello\nDw this will be archived")
    to_be_archived = await graph_client.search_emails(subject="This email is going to be archived", max_results=1)
    result = await graph_client.archive_email(to_be_archived["result"][0]["id"])
    print(f"Done archiving email.\nResult: {result}")

    """LABELLING EMAIL"""
    await graph_client.send_email("ahmed123.as27@hotmail.com", "This email is going to be labelled",
                                  "Hello\nDw this will be labelled")
    to_be_labelled = await graph_client.search_emails(subject="This email is going to be labelled", max_results=1)
    result = await graph_client.toggle_label_email(to_be_labelled["result"][0]["id"], "starred")
    print(f"Done labelling email with correct label.\nResult: {result}")

    result = await graph_client.toggle_label_email(to_be_labelled["result"][0]["id"], "Fun")
    print(f"Done labelling email with wrong label.\nResult: {result}")

    result = await graph_client.toggle_label_email(to_be_labelled["result"][0]["id"], "inbox", action="remove")
    print(f"Done removing label from email.\nResult: {result}")


if __name__ == "__main__":
    asyncio.run(test())
