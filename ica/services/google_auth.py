"""Shared Google service account credential loading.

Provides :func:`load_credentials` used by both
:mod:`~ica.services.google_docs` and :mod:`~ica.services.google_sheets`.
"""

from __future__ import annotations

import json
from pathlib import Path

from google.oauth2.service_account import Credentials as ServiceAccountCredentials


def load_credentials(
    credentials_path: Path,
    scopes: list[str],
) -> ServiceAccountCredentials:
    """Load Google service account credentials from a JSON key file.

    Args:
        credentials_path: Path to the service account JSON key file.
        scopes: OAuth2 scopes to request.

    Returns:
        Scoped credentials ready for API use.

    Raises:
        FileNotFoundError: If the credentials file does not exist.
        ValueError: If the file is not valid JSON or not a service account key.
    """
    path = Path(credentials_path)
    if not path.exists():
        raise FileNotFoundError(f"Credentials file not found: {path}")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise ValueError(f"Invalid credentials file: {exc}") from exc

    if not isinstance(data, dict) or "type" not in data:
        raise ValueError("Credentials file must be a JSON object with a 'type' field")

    if data["type"] != "service_account":
        raise ValueError(
            f"Unsupported credential type: {data['type']!r}. Only 'service_account' is supported."
        )

    return ServiceAccountCredentials.from_service_account_info(  # type: ignore[no-untyped-call,no-any-return]
        data,
        scopes=scopes,
    )
