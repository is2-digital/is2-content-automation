"""Boolean normalizer for Google Sheets string values.

Converts string representations of booleans (as found in Google Sheets cells)
to Python ``bool`` values. This is a direct port of the n8n Field Mapping
Set node expression used in the curated-articles subworkflow:

.. code-block:: javascript

    $json.approved && $json.approved.toString().toLowerCase() === 'yes'

The n8n pattern treats ``"yes"`` (case-insensitive) as ``True`` and everything
else—including ``"no"``, ``"true"``, ``"false"``, empty strings, and ``None``—as
``False``.  This module preserves that exact behavior.
"""

from __future__ import annotations


def normalize_boolean(value: str | bool | None) -> bool:
    """Convert a Google Sheets cell value to a Python boolean.

    Matches the n8n Field Mapping expression: a value is truthy **only** when
    it is the string ``"yes"`` (case-insensitive, whitespace-trimmed).

    Args:
        value: The raw cell value.  May be a string (``"yes"``, ``"Yes"``,
            ``"YES"``, ``"no"``, ``"true"``, ``"false"``, ``""``), an
            already-coerced ``bool``, or ``None``.

    Returns:
        ``True`` if *value* is the string ``"yes"`` (case-insensitive) or the
        boolean ``True``; ``False`` otherwise.
    """
    if value is None:
        return False

    if isinstance(value, bool):
        return value

    cleaned = str(value).strip().lower()
    return cleaned == "yes"
