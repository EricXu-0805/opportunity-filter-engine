"""Shared helpers for safely interpolating user text into LLM prompts.

Previously ``_sanitize_field`` was copy-pasted byte-for-byte in
``backend/routes/cold_email.py`` and ``backend/routes/tailor.py``. Hoisting it
here keeps the prompt-injection defense in one place so a fix (or a future
hardening) applies to every LLM touchpoint at once.
"""

from __future__ import annotations


def sanitize_field(value: object, *, max_len: int | None = 600) -> str:
    """Flatten whitespace for a single-line prompt field.

    ``max_len=None`` retains the complete field; use a serialized message
    budget at the provider boundary for that path. The legacy default still
    clips excerpts. Whitespace formatting is not a prompt-injection guarantee:
    external text remains untrusted data even when it occupies one line.
    """
    return " ".join(str(value).split())[:max_len]
