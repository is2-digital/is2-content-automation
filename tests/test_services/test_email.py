"""Tests for ica.services.email — email notification service.

Covers:
- _format_email_body: Slack bold marker stripping, header/footer
- EmailNotifier: SMTP send with correct params, error propagation
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

from ica.services.email import EmailNotifier, _format_email_body

# -----------------------------------------------------------------------
# _format_email_body
# -----------------------------------------------------------------------


class TestFormatEmailBody:
    """_format_email_body — converts Slack mrkdwn to plain-text email."""

    def test_strips_bold_markers(self) -> None:
        result = _format_email_body("*bold text* normal")
        assert "*" not in result
        assert "bold text" in result
        assert "normal" in result

    def test_includes_header(self) -> None:
        result = _format_email_body("test message")
        assert "[ica] Pipeline Error Alert" in result

    def test_includes_footer(self) -> None:
        result = _format_email_body("test message")
        assert "automated alert" in result

    def test_includes_message(self) -> None:
        result = _format_email_body("Something went wrong")
        assert "Something went wrong" in result

    def test_multiple_bold_sections(self) -> None:
        result = _format_email_body("*Execution Stopped* at step, *error*: boom")
        assert "Execution Stopped" in result
        assert "error" in result
        assert "*" not in result

    def test_no_bold_markers(self) -> None:
        result = _format_email_body("plain text only")
        assert "plain text only" in result

    def test_includes_separator(self) -> None:
        result = _format_email_body("msg")
        assert "===" in result


# -----------------------------------------------------------------------
# EmailNotifier
# -----------------------------------------------------------------------


class TestEmailNotifier:
    """EmailNotifier — sends error notification via SMTP."""

    def _make_notifier(self) -> EmailNotifier:
        return EmailNotifier(
            smtp_host="smtp.gmail.com",
            smtp_port=587,
            username="user@gmail.com",
            password="app-password",
            from_addr="user@gmail.com",
            to_addrs="alert@example.com, ops@example.com",
        )

    @pytest.mark.asyncio
    async def test_sends_email(self) -> None:
        notifier = self._make_notifier()
        with patch("ica.services.email.aiosmtplib.send", new_callable=AsyncMock) as mock_send:
            await notifier.send_error("Pipeline broke")
            mock_send.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_subject_line(self) -> None:
        notifier = self._make_notifier()
        with patch("ica.services.email.aiosmtplib.send", new_callable=AsyncMock) as mock_send:
            await notifier.send_error("test")
            msg = mock_send.call_args[0][0]
            assert msg["Subject"] == "[ica] Pipeline Error"

    @pytest.mark.asyncio
    async def test_recipients(self) -> None:
        notifier = self._make_notifier()
        with patch("ica.services.email.aiosmtplib.send", new_callable=AsyncMock) as mock_send:
            await notifier.send_error("test")
            msg = mock_send.call_args[0][0]
            assert "alert@example.com" in msg["To"]
            assert "ops@example.com" in msg["To"]

    @pytest.mark.asyncio
    async def test_from_address(self) -> None:
        notifier = self._make_notifier()
        with patch("ica.services.email.aiosmtplib.send", new_callable=AsyncMock) as mock_send:
            await notifier.send_error("test")
            msg = mock_send.call_args[0][0]
            assert msg["From"] == "user@gmail.com"

    @pytest.mark.asyncio
    async def test_starttls_enabled(self) -> None:
        notifier = self._make_notifier()
        with patch("ica.services.email.aiosmtplib.send", new_callable=AsyncMock) as mock_send:
            await notifier.send_error("test")
            kwargs = mock_send.call_args[1]
            assert kwargs["start_tls"] is True

    @pytest.mark.asyncio
    async def test_smtp_credentials(self) -> None:
        notifier = self._make_notifier()
        with patch("ica.services.email.aiosmtplib.send", new_callable=AsyncMock) as mock_send:
            await notifier.send_error("test")
            kwargs = mock_send.call_args[1]
            assert kwargs["hostname"] == "smtp.gmail.com"
            assert kwargs["port"] == 587
            assert kwargs["username"] == "user@gmail.com"
            assert kwargs["password"] == "app-password"

    @pytest.mark.asyncio
    async def test_error_propagates(self) -> None:
        notifier = self._make_notifier()
        with (
            patch(
                "ica.services.email.aiosmtplib.send",
                new_callable=AsyncMock,
                side_effect=ConnectionRefusedError("SMTP down"),
            ),
            pytest.raises(ConnectionRefusedError),
        ):
            await notifier.send_error("test")

    @pytest.mark.asyncio
    async def test_body_contains_message(self) -> None:
        notifier = self._make_notifier()
        with patch("ica.services.email.aiosmtplib.send", new_callable=AsyncMock) as mock_send:
            await notifier.send_error("*Execution Stopped* at step")
            msg = mock_send.call_args[0][0]
            body = msg.get_content()
            assert "Execution Stopped" in body
            assert "*" not in body

    def test_to_addrs_parsing(self) -> None:
        notifier = EmailNotifier(
            smtp_host="h",
            smtp_port=587,
            username="u",
            password="p",
            from_addr="f",
            to_addrs=" a@b.com , c@d.com , ",
        )
        assert notifier._to_addrs == ["a@b.com", "c@d.com"]
