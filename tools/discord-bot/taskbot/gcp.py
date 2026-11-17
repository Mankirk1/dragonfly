"""Google sign-in without key files.

On a Google Cloud VM the bot uses the VM's attached service account (Application
Default Credentials), so no private key ever exists on disk. The Discord token can
live in Secret Manager and be read at start-up. A key file is still accepted for
running elsewhere, but isn't needed or recommended.
"""

from __future__ import annotations

import base64
import re
from typing import Any

from .config import ConfigError, Settings

SHEETS_SCOPE = "https://www.googleapis.com/auth/spreadsheets"
CLOUD_SCOPE = "https://www.googleapis.com/auth/cloud-platform"
_SECRET_NAME = re.compile(r"projects/[\w.-]+/secrets/[\w-]+/versions/(latest|\d+)")


def sheets_credentials(settings: Settings) -> Any:
    """Credentials for the Sheets API, limited to spreadsheets."""
    if settings.google_credentials_json or settings.google_credentials_file:
        from google.oauth2.service_account import Credentials

        return Credentials.from_service_account_info(
            settings.google_credentials(), scopes=[SHEETS_SCOPE]
        )
    import google.auth

    try:
        creds, _ = google.auth.default(scopes=[SHEETS_SCOPE])
    except google.auth.exceptions.DefaultCredentialsError as exc:
        raise ConfigError(
            "No Google credentials found. On the Google Cloud VM, attach the bot's service "
            "account with the spreadsheets scope (see the README)."
        ) from exc
    return creds


def read_secret(name: str, session: Any = None) -> str:
    """Read a Secret Manager secret version, e.g. projects/p/secrets/s/versions/latest."""
    if not _SECRET_NAME.fullmatch(name):
        raise ConfigError(
            "TASKBOT_DISCORD_TOKEN_SECRET must look like "
            "projects/PROJECT_ID/secrets/SECRET_NAME/versions/latest"
        )
    if session is None:
        import google.auth
        from google.auth.transport.requests import AuthorizedSession

        creds, _ = google.auth.default(scopes=[CLOUD_SCOPE])
        session = AuthorizedSession(creds)
    response = session.get(f"https://secretmanager.googleapis.com/v1/{name}:access", timeout=30)
    if response.status_code != 200:
        # Don't echo the response body: keep anything sensitive out of the logs.
        raise ConfigError(
            f"Couldn't read the secret {name} (HTTP {response.status_code}). Check the bot's "
            "service account has Secret Manager Secret Accessor on it."
        )
    value = base64.b64decode(response.json()["payload"]["data"]).decode("utf-8").strip()
    if not value:
        raise ConfigError(f"The secret {name} is empty")
    return value
