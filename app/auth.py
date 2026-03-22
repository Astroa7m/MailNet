import json
import os
import time
import webbrowser

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from msal import ConfidentialClientApplication


class GmailAuth:
    """Handles Gmail OAuth2 authentication"""

    SCOPES = [
        'https://mail.google.com/',
        'https://www.googleapis.com/auth/gmail.send',
        'https://www.googleapis.com/auth/gmail.labels',
        'https://www.googleapis.com/auth/gmail.modify',
    ]

    def __init__(self, credential_file: str, token_file: str = "google_token.json"):
        """
        Initialize Gmail authentication

        Args:
            credential_file: Path to Google OAuth2 credentials JSON file
            token_file: Path where the token will be saved (default: google_token.json)
        """
        self.credential_file = credential_file
        self.token_file = token_file

    def authenticate(self) -> str:
        """
        Authenticate and generate access token
        Opens browser for user consent if needed

        Returns:
            str: Access token
        """
        creds = None

        # Try to load existing token
        if os.path.exists(self.token_file):
            creds = Credentials.from_authorized_user_file(self.token_file, self.SCOPES)

        # If no valid credentials, get new ones
        if not creds or not creds.valid:
            if creds and creds.expired and creds.refresh_token:
                # Refresh expired token
                creds.refresh(Request())
            else:
                # Get new token via browser
                flow = InstalledAppFlow.from_client_secrets_file(
                    self.credential_file,
                    self.SCOPES
                )
                creds = flow.run_local_server(port=0, include_granted_scopes='true')

            # Save the token
            with open(self.token_file, 'w') as token:
                token.write(creds.to_json())

        return creds.token


class OutlookAuth:
    """Handles Outlook/Microsoft OAuth2 authentication"""

    SCOPES = [
        "https://graph.microsoft.com/Mail.ReadWrite",
        "https://graph.microsoft.com/Mail.Send",
        "https://graph.microsoft.com/MailboxSettings.ReadWrite",
        "https://graph.microsoft.com/User.Read"
    ]

    def __init__(self, client_id: str, client_secret: str, redirect_uri: str,
                 token_file: str = "azure_token.json"):
        """
        Initialize Outlook authentication

        Args:
            client_id: Azure app client ID
            client_secret: Azure app client secret
            redirect_uri: Redirect URI configured in Azure app
            token_file: Path where the token will be saved (default: azure_token.json)
        """
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

    def authenticate(self) -> str:
        """
        Authenticate and generate access token
        Opens browser for user consent if needed

        Returns:
            str: Access token
        """
        # Try to load existing token
        if os.path.exists(self.token_file):
            with open(self.token_file, "r") as f:
                token_data = json.load(f)

                # Check if token is still valid
                if token_data.get("expires_at", 0) > time.time():
                    return token_data["access_token"]

                # Try to refresh if expired
                if "refresh_token" in token_data:
                    return self._refresh_token(token_data["refresh_token"])

        # Get new token via browser
        return self._get_new_token()

    def _get_new_token(self) -> str:
        """Get new token by opening browser for user consent"""
        auth_flow = self.app.initiate_auth_code_flow(
            scopes=self.SCOPES,
            redirect_uri=self.redirect_uri
        )

        print(f"\nOpening browser for authentication: {auth_flow['auth_uri']}")
        webbrowser.open(auth_flow['auth_uri'])

        # Get authorization code from user
        code = input("Paste the authorization code here: ").strip()

        # Exchange code for token
        auth_response = {"code": code, "state": auth_flow["state"]}
        result = self.app.acquire_token_by_auth_code_flow(auth_flow, auth_response)

        return self._store_token(result)

    def _refresh_token(self, refresh_token: str) -> str:
        """Refresh an expired token"""
        result = self.app.acquire_token_by_refresh_token(
            refresh_token,
            scopes=self.SCOPES
        )
        return self._store_token(result)

    def _store_token(self, result: dict) -> str:
        """Save token to file"""
        if "access_token" in result:
            result["expires_at"] = time.time() + result.get("expires_in", 3600)
            with open(self.token_file, "w") as f:
                json.dump(result, f)
            return result["access_token"]

        raise Exception(f"Token acquisition failed: {result.get('error_description')}")


# Example usage:
if __name__ == "__main__":
    # Gmail authentication
    print("=== Gmail Authentication ===")
    gmail_auth = GmailAuth(credential_file="path/to/credentials.json")
    gmail_token = gmail_auth.authenticate()
    print(f"Gmail token generated successfully!")

    # Outlook authentication
    print("\n=== Outlook Authentication ===")
    outlook_auth = OutlookAuth(
        client_id="your-client-id",
        client_secret="your-client-secret",
        redirect_uri="http://localhost"
    )
    outlook_token = outlook_auth.authenticate()
    print(f"Outlook token generated successfully!")
