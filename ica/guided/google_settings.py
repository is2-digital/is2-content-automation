"""Guided-mode Google service settings validation.

Checks that test-specific Google target IDs are configured when the guided
run path includes steps that interact with Google Sheets or Google Docs.
This validation runs at guided-run startup — not during normal production
pipeline execution — so the settings remain optional in :class:`Settings`.
"""

from __future__ import annotations

from ica.pipeline.orchestrator import StepName

# ---------------------------------------------------------------------------
# Step → Google service mapping
# ---------------------------------------------------------------------------

#: Steps that create or read from Google Sheets (article curation spreadsheet).
STEPS_REQUIRING_SHEETS: frozenset[StepName] = frozenset({
    StepName.CURATION,
    StepName.SUMMARIZATION,
})

#: Steps that create Google Docs (markdown, HTML, email subject, social, carousel).
STEPS_REQUIRING_DOCS: frozenset[StepName] = frozenset({
    StepName.MARKDOWN_GENERATION,
    StepName.HTML_GENERATION,
    StepName.EMAIL_SUBJECT,
    StepName.SOCIAL_MEDIA,
    StepName.LINKEDIN_CAROUSEL,
})

#: All steps that require any Google service.
STEPS_REQUIRING_GOOGLE: frozenset[StepName] = STEPS_REQUIRING_SHEETS | STEPS_REQUIRING_DOCS


class GuidedGoogleSettingsError(Exception):
    """Raised when guided-mode Google target settings are missing."""


def validate_google_settings(run_steps: list[StepName]) -> None:
    """Validate that required Google test-target settings are present.

    Called at guided-run startup.  If any step in *run_steps* needs Google
    Sheets or Docs and the corresponding test-target ID is not configured,
    raises :class:`GuidedGoogleSettingsError` with a human-readable message
    listing what's missing and how to fix it.

    Args:
        run_steps: The ordered list of steps that will execute in this run.

    Raises:
        GuidedGoogleSettingsError: If one or more required settings are empty.
    """
    from ica.config.settings import get_settings

    settings = get_settings()

    needs_sheets = any(s in STEPS_REQUIRING_SHEETS for s in run_steps)
    needs_docs = any(s in STEPS_REQUIRING_DOCS for s in run_steps)

    if not needs_sheets and not needs_docs:
        return

    missing: list[str] = []

    if needs_sheets and not settings.guided_test_spreadsheet_id:
        sheet_steps = sorted(s.value for s in run_steps if s in STEPS_REQUIRING_SHEETS)
        missing.append(
            f"  GUIDED_TEST_SPREADSHEET_ID  (needed by: {', '.join(sheet_steps)})\n"
            f"    Set this to a Google Sheets ID reserved for testing.\n"
            f"    The service account must have edit access."
        )

    if needs_docs and not settings.guided_test_drive_folder_id:
        doc_steps = sorted(s.value for s in run_steps if s in STEPS_REQUIRING_DOCS)
        missing.append(
            f"  GUIDED_TEST_DRIVE_FOLDER_ID  (needed by: {', '.join(doc_steps)})\n"
            f"    Set this to a Google Drive folder ID (or Shared Drive ID)\n"
            f"    where test documents will be created."
        )

    if missing:
        detail = "\n\n".join(missing)
        raise GuidedGoogleSettingsError(
            f"Missing guided-mode Google settings:\n\n{detail}\n\n"
            f"Add these to your .env file or set them as environment variables.\n"
            f"See .env-example for reference."
        )
