"""Email notification service for pipeline error alerts.

Sends plain-text email notifications via SMTP (designed for Gmail with
App Passwords). Structurally satisfies the :class:`~ica.errors.ErrorNotifier`
protocol so it can be used alongside the Slack notifier.
"""

from __future__ import annotations

import re
from email.message import EmailMessage

import aiosmtplib

from ica.logging import get_logger

logger = get_logger(__name__)


def _format_email_body(message: str) -> str:
    """Convert a Slack-formatted error message to plain-text email body.

    Strips Slack ``*bold*`` markers and wraps in a simple email template.
    """
    plain = re.sub(r"\*([^*]+)\*", r"\1", message)
    separator = "=" * 40
    return (
        f"[ica] Pipeline Error Alert\n"
        f"{separator}\n\n"
        f"{plain}\n\n"
        f"---\n"
        f"This is an automated alert from the ica newsletter pipeline.\n"
    )


class EmailNotifier:
    """Sends pipeline error notifications via SMTP email.

    Args:
        smtp_host: SMTP server hostname.
        smtp_port: SMTP server port (587 for STARTTLS).
        username: SMTP login username.
        password: SMTP login password (Gmail App Password).
        from_addr: Sender email address.
        to_addrs: Comma-separated recipient email addresses.
    """

    def __init__(
        self,
        *,
        smtp_host: str,
        smtp_port: int,
        username: str,
        password: str,
        from_addr: str,
        to_addrs: str,
    ) -> None:
        self._smtp_host = smtp_host
        self._smtp_port = smtp_port
        self._username = username
        self._password = password
        self._from_addr = from_addr
        self._to_addrs = [addr.strip() for addr in to_addrs.split(",") if addr.strip()]

    async def send_error(self, message: str) -> None:
        """Send an error notification email."""
        msg = EmailMessage()
        msg["Subject"] = "[ica] Pipeline Error"
        msg["From"] = self._from_addr
        msg["To"] = ", ".join(self._to_addrs)
        msg.set_content(_format_email_body(message))

        await aiosmtplib.send(
            msg,
            hostname=self._smtp_host,
            port=self._smtp_port,
            username=self._username,
            password=self._password,
            start_tls=True,
        )
        logger.info("Error notification email sent to %s", self._to_addrs)
