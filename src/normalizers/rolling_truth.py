"""Deadline / is_rolling contradiction guard.

``is_rolling=True`` and a fixed ``deadline`` are contradictory claims about the
same record, and both are load-bearing: the fellowships UI filters on
``is_rolling is True`` and ``deactivate_past`` skips rolling records entirely,
so a record carrying both shows under "rolling" AND survives its own expiry.
:func:`reconcile_rolling_with_deadline` demotes ``is_rolling`` ONLY on that
contradiction — a real deadline present with no source text saying rolling.

Deliberately NOT done here (Codex's rolling_truth.py did, and it was dropped):
demoting no-deadline records whose text merely lacks the word "rolling". 719
fellowship/summer-program records carry that shape today — the R70-A migration
set them True as the safe no-deadline default, the DQ audit targets zero
"no deadline AND no is_rolling" records, and faculty labs genuinely accept
inquiries year-round (see ``enricher.is_rolling_deadline``). Blanket demotion
would flip all 719 and re-open the DQ hole. This pass never promotes either:
False/absent values are left alone.
"""

from __future__ import annotations

import re

_ROLLING_RE = re.compile(r"\brolling\b", re.IGNORECASE)
_NOT_ROLLING_RE = re.compile(r"\b(?:not|non)[\s-]+rolling\b", re.IGNORECASE)

# Source-derived text only: collector notes, inferred keywords, URLs, and
# source names are not evidence that applications are rolling.
_ROLLING_EVIDENCE_PATHS: tuple[tuple[str, ...], ...] = (
    ("deadline",),
    ("title",),
    ("description_clean",),
    ("description_raw",),
    ("eligibility", "eligibility_text_raw"),
)


def text_explicitly_marks_rolling(value: object) -> bool:
    """True only for affirmative, explicit "rolling" source text."""
    if not isinstance(value, str) or not value.strip():
        return False
    if _NOT_ROLLING_RE.search(value):
        return False
    return _ROLLING_RE.search(value) is not None


def _nested_value(record: dict, path: tuple[str, ...]) -> object:
    value: object = record
    for key in path:
        if not isinstance(value, dict):
            return None
        value = value.get(key)
    return value


def record_text_marks_rolling(record: dict) -> bool:
    """Whether any allowlisted source-text field explicitly says rolling."""
    return any(
        text_explicitly_marks_rolling(_nested_value(record, path))
        for path in _ROLLING_EVIDENCE_PATHS
    )


def has_fixed_deadline(record: dict) -> bool:
    """A non-empty structured deadline that isn't itself just rolling prose."""
    value = record.get("deadline")
    return (
        isinstance(value, str)
        and bool(value.strip())
        and not text_explicitly_marks_rolling(value)
    )


def reconcile_rolling_with_deadline(record: dict) -> bool:
    """Demote a contradictory ``is_rolling=True`` in place; return changed.

    Fires only when the record carries a fixed deadline AND no source text
    saying rolling — the two claims cannot both be true, and the deadline is
    the structured, collector-verified one. Never promotes, never touches
    deadline-less records (faculty labs stay honestly rolling).
    """
    if record.get("is_rolling") is not True:
        return False
    if not has_fixed_deadline(record):
        return False
    if record_text_marks_rolling(record):
        return False
    record["is_rolling"] = False
    return True
