"""Shared helpers for safely interpolating user text into LLM prompts.

Previously ``_sanitize_field`` was copy-pasted byte-for-byte in
``backend/routes/cold_email.py`` and ``backend/routes/tailor.py``. Hoisting it
here keeps the prompt-injection defense in one place so a fix (or a future
hardening) applies to every LLM touchpoint at once.
"""

from __future__ import annotations


def sanitize_field(value: object, *, max_len: int = 600) -> str:
    """Flatten a free-text profile field for safe prompt interpolation.

    Collapses all whitespace (incl. newlines) to single spaces so a user
    supplied field cannot inject fake ``Subject:`` / role lines or multi-line
    instructions into the LLM prompt, then truncates to ``max_len``.
    """
    return " ".join(str(value).split())[:max_len]
