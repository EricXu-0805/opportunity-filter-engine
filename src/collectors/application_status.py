"""Fail-closed application-status detection shared by campus collectors."""

from __future__ import annotations

import re

_CLOSED_RE = re.compile(
    r"""
    \b(?:the\s+)?(?:applications?(?:\s+(?:period|window))?|submissions?)\s+
        (?:
            (?:are|is)\s+(?:(?:currently|now|temporarily)\s+)?closed
            |(?:are|is)\s+not\s+(?:(?:currently|now)\s+)?being\s+accepted
            |have\s+(?:now\s+)?closed
            |closed
        )\b
    |
    \bno\s+applications?\s+(?:are|is)\s+being\s+accepted\b
    |
    \b(?:we\s+)?(?:are\s+)?not\s+(?:(?:currently|now)\s+)?accepting\s+
        (?:new\s+)?applications?\b
    |
    \bno\s+longer\s+accepting(?:\s+applications?)?\b
    |
    \b(?:the\s+)?applications?\s+(?:cycle|period|window)\s+
        (?:has\s+)?(?:ended|closed)\b
    |
    \b(?:the\s+)?(?:application\s+)?deadline\s+
        (?:has\s+)?(?:now\s+)?passed\b
    |
    \b(?:our\s+|the\s+|this\s+year['’]?s\s+)?(?:\d{4}\s+)?cohort\s+
        (?:(?:has|have|is|are)\s+(?:already\s+|now\s+)?(?:been\s+)?
            (?:formed|selected|filled|finalized|finalised|chosen|set|complete|full)
        )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

# A cycle that opens LATER. "Applications for 2027 will be open in November
# 2026" and "the application site opens mid November 2026" both say, in the
# present, that applications are not open. They do not say "closed" either —
# this detector has no calendar, and the same page read in December may be
# describing the current cycle — so a match yields "unknown": no suffix, no
# claim. Northwestern SynBREU carried exactly these two sentences under an
# Apply Now button and was served as "(applications open)" (2026-08-31).
_FUTURE_OPEN_RE = re.compile(
    r"""
    \bapplications?\s+(?:for\s+(?:the\s+)?\d{4}\s+)?(?:will|would|should)\s+(?:be\s+)?open(?:ing)?\b
    |
    \b(?:the\s+)?application(?:s)?\s+(?:site|portal|window|period|form|cycle)\s+
        (?:will\s+)?(?:be\s+)?open(?:s|ing)?\s+
        (?:in|on|by|around|mid|early|late)?[-\s]*
        (?:january|february|march|april|may|june|july|august|september|october|november|december)\b
    |
    \bapplications?\s+(?:will\s+)?open(?:s)?\s+
        (?:in|on|by|around|mid|early|late)[-\s]*
        (?:january|february|march|april|may|june|july|august|september|october|november|december)\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

_NEGATED_CURRENT_ACTION_RE = re.compile(
    r"""
    \b(?:
        (?:please\s+)?(?:
            (?:do|must|should|can)\s+not
            |(?:don|mustn|shouldn|can)['’]t
            |cannot
            |never
        )\s+apply\s+now
        |
        (?:the\s+)?apply\s+now
        (?:\s+(?:button|buttons|link|links|option|portal))?\s+
        (?:
            (?:
                (?:(?:are|is|was|were)\s+|(?:has|have)\s+been\s+)?
                (?:disabled|inactive|unavailable|not\s+(?:available|enabled))
            )
            |
            remains?\s+(?:disabled|inactive|unavailable)
        )
    )\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

_STRONG_CURRENT_OPEN_RE = re.compile(
    r"""
    \bapplications?\s+(?:are|is)\s+(?:currently|now)\s+open\b
    |
    \bapply\s+now\b
    |
    \bnow\s+accepting(?:\s+applications?)?\b
    |
    \bnow\s+(?:recruiting|hiring)\b
    """,
    re.IGNORECASE | re.VERBOSE,
)

_BARE_OPEN_RE = re.compile(
    r"\bapplications?\s+(?:(?:are|is)\s+)?open\s*(?=$|[.!\n])",
    re.IGNORECASE,
)
_NEUTRAL_BARE_PREFIX_RE = re.compile(
    r"\s*(?:(?:current\s+)?(?:application\s+)?status\s*:\s*)?",
    re.IGNORECASE,
)
_HISTORICAL_CONTEXT_RE = re.compile(
    r"""
    \b(?:19|20)\d{2}\b
    |
    \b(?:last|previous|prior|past)\s+
        (?:(?:application|funding)\s+)?
        (?:year|cycle|round|term|semester|season)\b
    |
    \b(?:archive|archived|historical)\b
    """,
    re.IGNORECASE | re.VERBOSE,
)


def detect_application_status(page_text: str) -> str:
    """Classify only unambiguous current status; closed always wins.

    University pages often retain prior-cycle and future-cycle copy together.
    A future or recurring phrase such as "applications open next fall" is not
    evidence that applications are open now.
    """

    if not isinstance(page_text, str):
        return "unknown"
    if _CLOSED_RE.search(page_text):
        return "closed"
    if _NEGATED_CURRENT_ACTION_RE.search(page_text):
        return "unknown"
    if _FUTURE_OPEN_RE.search(page_text):
        return "unknown"
    if _STRONG_CURRENT_OPEN_RE.search(page_text):
        return "open"
    for match in _BARE_OPEN_RE.finditer(page_text):
        sentence_start = max(
            page_text.rfind(boundary, 0, match.start())
            for boundary in (".", "!", "?", "\n")
        ) + 1
        prefix = page_text[sentence_start:match.start()]
        if _HISTORICAL_CONTEXT_RE.search(prefix):
            continue
        if _NEUTRAL_BARE_PREFIX_RE.fullmatch(prefix):
            return "open"
    return "unknown"
