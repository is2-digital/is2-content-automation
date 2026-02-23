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

    Creates both :class:`~ica.config.settings.Settings` and
    :class:`~ica.config.llm_config.LLMConfig` instances and checks:

    1. All required environment variables are present (Pydantic validation).
    2. ``TIMEZONE`` is a valid IANA timezone identifier.
    3. All LLM model identifiers are non-empty and contain a ``/`` separator
       (OpenRouter ``provider/model`` format).

    Returns:
        A :class:`ValidationResult` with ``ok=True`` if everything passes,
        or ``ok=False`` with a tuple of error descriptions.
    """
    errors: list[str] = []

    # --- Validate core settings ---
    try:
        from ica.config.settings import Settings

        settings = Settings(_env_file=None)  # type: ignore[call-arg]
    except ValidationError as exc:
        for err in exc.errors():
            loc = ".".join(str(p) for p in err["loc"])
            errors.append(f"Settings: {loc} — {err['msg']}")
        return ValidationResult(ok=False, errors=tuple(errors))

    # --- Validate timezone ---
    try:
        zoneinfo.ZoneInfo(settings.timezone)
    except (KeyError, ValueError, zoneinfo.ZoneInfoNotFoundError):
        errors.append(
            f"TIMEZONE: '{settings.timezone}' is not a valid IANA timezone"
        )

    # --- Validate LLM config ---
    try:
        from ica.config.llm_config import LLMConfig, LLMPurpose

        llm_config = LLMConfig(_env_file=None)  # type: ignore[call-arg]
    except ValidationError as exc:
        for err in exc.errors():
            loc = ".".join(str(p) for p in err["loc"])
            errors.append(f"LLMConfig: {loc} — {err['msg']}")
        return ValidationResult(ok=False, errors=tuple(errors))

    # --- Validate LLM model format (provider/model) ---
    for purpose in LLMPurpose:
        model_id: str = getattr(llm_config, purpose.value)
        if not model_id or not model_id.strip():
            errors.append(f"{purpose.value}: model identifier is empty")
        elif "/" not in model_id:
            errors.append(
                f"{purpose.value}: '{model_id}' missing provider/model separator '/'"
            )

    return ValidationResult(ok=len(errors) == 0, errors=tuple(errors))
