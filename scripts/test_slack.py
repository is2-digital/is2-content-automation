"""Slack integration test — auth, messaging, and interactive button callbacks.

Usage:
    python scripts/test_slack.py

Requires SLACK_BOT_TOKEN, SLACK_APP_TOKEN, and SLACK_CHANNEL in .env.dev.
"""

import asyncio
import os
import sys

from dotenv import load_dotenv

load_dotenv(".env.dev")

bot_token = os.environ.get("SLACK_BOT_TOKEN", "")
app_token = os.environ.get("SLACK_APP_TOKEN", "")
channel = os.environ.get("SLACK_CHANNEL", "")

if not bot_token or not app_token or not channel:
    print("ERROR: Set SLACK_BOT_TOKEN, SLACK_APP_TOKEN, and SLACK_CHANNEL in .env.dev")
    sys.exit(1)

print(f"Bot token: {bot_token[:10]}...{bot_token[-4:]}")
print(f"App token: {app_token[:10]}...{app_token[-4:]}")
print(f"Channel:   {channel}")


async def main() -> None:
    from slack_bolt.adapter.socket_mode.async_handler import AsyncSocketModeHandler
    from slack_bolt.async_app import AsyncApp

    from ica.services.slack import SlackService

    # 1. Test auth
    print("\n--- 1. Testing auth ---")
    svc = SlackService(token=bot_token, channel=channel)
    auth = await svc.client.auth_test()
    print(f"  Bot user: {auth['user']} (team: {auth['team']})")

    # 2. Test plain message
    print("\n--- 2. Sending plain message ---")
    await svc.send_message(channel, "Test: plain message from ica integration test.")
    print("  Sent.")

    # 3. Test interactive button (send_and_wait approval)
    print("\n--- 3. Testing interactive button (send_and_wait) ---")
    print("  Sending approval button to channel...")
    print("  >>> Click the button in Slack within 60s <<<")

    bolt_app = AsyncApp(token=bot_token)
    svc.register_handlers(bolt_app)
    handler = AsyncSocketModeHandler(bolt_app, app_token)
    await handler.connect_async()
    print("  Socket Mode connected.")

    try:
        await asyncio.wait_for(
            svc.send_and_wait(
                channel,
                "Integration test: click the button to confirm interactions work.",
                approve_label="Confirm",
            ),
            timeout=60,
        )
        print("  Button click received! Interactive callbacks working.")
    except asyncio.TimeoutError:
        print("  TIMEOUT: No button click received within 60s.")
        print("  Check that Interactivity is enabled in your Slack app settings.")
        await handler.close_async()
        sys.exit(1)

    # 4. Test form with dropdown (send_and_wait_form)
    print("\n--- 4. Testing dropdown form (send_and_wait_form) ---")
    print("  >>> Click the button, select from dropdown, then submit <<<")
    try:
        form_result = await asyncio.wait_for(
            svc.send_and_wait_form(
                "Integration test: select a theme from the dropdown.",
                form_fields=[
                    {
                        "fieldLabel": "Theme",
                        "fieldType": "dropdown",
                        "fieldOptions": [
                            {"option": "AI for Small Business"},
                            {"option": "Automation Trends"},
                            {"option": "Digital Marketing with AI"},
                        ],
                        "requiredField": True,
                    },
                ],
                button_label="Select Theme",
                form_title="Theme Selection",
                form_description="Pick your preferred newsletter theme.",
            ),
            timeout=60,
        )
        print(f"  Form submitted! Response: {form_result}")
    except asyncio.TimeoutError:
        print("  TIMEOUT: No form submission within 60s.")
        await handler.close_async()
        sys.exit(1)

    # 5. Test freetext modal (send_and_wait_freetext)
    print("\n--- 5. Testing freetext input (send_and_wait_freetext) ---")
    print("  >>> Click the button, type some feedback, then submit <<<")
    try:
        freetext_result = await asyncio.wait_for(
            svc.send_and_wait_freetext(
                "Integration test: enter some feedback text.",
                button_label="Add Feedback",
                form_title="Feedback",
                form_description="Type anything to confirm freetext modals work.",
            ),
            timeout=60,
        )
        print(f"  Freetext submitted! Response: {freetext_result!r}")
    except asyncio.TimeoutError:
        print("  TIMEOUT: No freetext submission within 60s.")
        await handler.close_async()
        sys.exit(1)

    await handler.close_async()
    print("  Socket Mode disconnected.")

    print("\nAll tests passed!")


asyncio.run(main())
