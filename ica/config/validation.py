"""Startup validation for ica configuration.

Checks that all required environment variables are present and correctly
formatted before the application begins processing.
"""

from __future__ import annotations

import zoneinfo
from dataclasses import dataclass, field

from pydantic import ValidationError


@dataclass(frozen=True)
class ValidationResult:
    """Result of startup configuration validation."""

    ok: bool
    errors: tuple[str, ...] = field(default=())


def validate_config() -> ValidationResult:
    """Validate all application configuration at startup.

    Validates :class:`~ica.config.settings.Settings` and all LLM JSON
    config files:

    1. All required environment variables are present (Pydantic validation).
    2. ``TIMEZONE`` is a valid IANA timezone identifier.
    3. All LLM JSON config files exist and validate against schema.
    4. All model identifiers are non-empty and contain a ``/`` separator
       (OpenRouter ``provider/model`` format).

    Returns:
        A :class:`ValidationResult` with ``ok=True`` if everything passes,
        or ``ok=False`` with a tuple of error descriptions.
    """
    errors: list[str] = []

    # --- Validate core settings ---
    try:
        from ica.config.settings import Settings

        settings = Settings(_env_file=None)
    except ValidationError as exc:
        for err in exc.errors():
            loc = ".".join(str(p) for p in err["loc"])
            errors.append(f"Settings: {loc} — {err['msg']}")
        return ValidationResult(ok=False, errors=tuple(errors))

    # --- Validate timezone ---
    try:
        zoneinfo.ZoneInfo(settings.timezone)
    except (KeyError, ValueError, zoneinfo.ZoneInfoNotFoundError):
        errors.append(f"TIMEZONE: '{settings.timezone}' is not a valid IANA timezone")

    # --- Validate LLM JSON configs ---
    from ica.config.llm_config import _PURPOSE_TO_PROCESS

    validated_processes: set[str] = set()
    for field_name, process_name in _PURPOSE_TO_PROCESS.items():
        if process_name in validated_processes:
            continue
        validated_processes.add(process_name)
        try:
            from ica.llm_configs.loader import load_process_config

            config = load_process_config(process_name)
        except FileNotFoundError:
            errors.append(f"{process_name}: JSON config file not found")
            continue
        except ValueError as exc:
            errors.append(f"{process_name}: {exc}")
            continue

        model_id = config.model
        if not model_id or not model_id.strip():
            errors.append(f"{process_name}: model identifier is empty")
        elif "/" not in model_id:
            errors.append(
                f"{process_name}: '{model_id}' missing provider/model separator '/'"
            )

    # --- Validate email notification config (opt-in) ---
    if settings.email_smtp_user:
        if not settings.email_smtp_password:
            errors.append("EMAIL_SMTP_PASSWORD is required when EMAIL_SMTP_USER is set")
        if not settings.email_from:
            errors.append("EMAIL_FROM is required when EMAIL_SMTP_USER is set")
        if not settings.email_to:
            errors.append("EMAIL_TO is required when EMAIL_SMTP_USER is set")

    return ValidationResult(ok=len(errors) == 0, errors=tuple(errors))
