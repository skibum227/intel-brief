"""
Google OAuth handler. Tokens are stored outside the repo at:
  ~/.config/intel-brief/google_token.json

On first run this opens a browser for OAuth consent. Subsequent runs
use the cached token and refresh silently.

Setup:
  1. Go to https://console.cloud.google.com
  2. Create a project → enable Gmail API + Google Calendar API
  3. Credentials → Create OAuth 2.0 Client ID (Desktop app)
  4. Download JSON → save to ~/.config/intel-brief/google_credentials.json
"""

from pathlib import Path
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
]

CONFIG_DIR = Path.home() / ".config" / "intel-brief"
TOKEN_PATH = CONFIG_DIR / "google_token.json"
CREDENTIALS_PATH = CONFIG_DIR / "google_credentials.json"


def get_google_credentials() -> Credentials:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    creds = None

    if TOKEN_PATH.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_PATH), SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CREDENTIALS_PATH.exists():
                raise FileNotFoundError(
                    f"\nGoogle credentials not found at: {CREDENTIALS_PATH}\n\n"
                    "To set up:\n"
                    "  1. Go to https://console.cloud.google.com\n"
                    "  2. Create a project, enable Gmail API + Google Calendar API\n"
                    "  3. Credentials → Create OAuth 2.0 Client ID (Desktop app)\n"
                    f"  4. Download JSON → save to: {CREDENTIALS_PATH}\n"
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_PATH), SCOPES)
            creds = flow.run_local_server(port=0)

        TOKEN_PATH.write_text(creds.to_json())

    return creds
