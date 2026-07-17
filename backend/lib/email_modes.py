"""Single source of truth for cold-email *modes*.

A mode has two facets that used to be defined in three separate places:

* **Draft voice** — the tone the LLM writes the draft in. Voice changes word
  choice and warmth only; the body structure and the anti-fabrication gate are
  unchanged, so a voice never licenses a new factual claim. (Was
  ``cold_email._TONE_INSTRUCTIONS``.)
* **Edit ops** — the deterministic regex edits the no-LLM ``/cold-email/refine``
  fallback applies when the user asks to make a draft more formal / shorter /
  enthusiastic. (Was ``cold_email._FORMAL_SUBS`` / ``_ENTHUSIASTIC_SUBS`` /
  ``_CONCISE_FILLERS``.)

Keeping both here removes the drift risk between the generator's tone overlay
and the refiner's edit tables.
"""
from __future__ import annotations

import re

# ---- Draft-time voices -----------------------------------------------------
# Keyed by the four values ``ColdEmailRequest.style`` validates.
DRAFT_VOICES: dict[str, str] = {
    "professional": (
        "Voice: professional and measured. Courteous, precise, no slang. "
        "Let competence and specificity carry the message."
    ),
    "warm": (
        "Voice: warm and personable while staying professional. A genuine, "
        "human tone — express sincere interest in the work itself, not just "
        "the position."
    ),
    "friendly": (
        "Voice: friendly and approachable. Conversational but still respectful "
        "of the professor's time; relaxed phrasing, never stiff or formulaic."
    ),
    "lively": (
        "Voice: energetic and enthusiastic. Convey real excitement about the "
        "research — but ground every statement in a specific fact and keep the "
        "banned-filler rules. Show enthusiasm through specifics, never through "
        "adjectives like 'passionate', 'thrilled', or 'excited'."
    ),
}

# Suggested default voice per detected lab type. Honest heuristic from the
# lab_type signal we already have — NOT from any professor-personality data
# (that would need non-public admit history; out of scope on compliance).
RECOMMENDED_VOICE_BY_LAB_TYPE: dict[str, str] = {
    "dry": "professional",
    "wet": "warm",
    "humanities": "friendly",
}


def draft_voice(style: str | None) -> str:
    """The voice directive for a style, or '' when no/unknown style is given."""
    return DRAFT_VOICES.get(style or "", "")


def recommended_voice(lab_type: str | None) -> str:
    return RECOMMENDED_VOICE_BY_LAB_TYPE.get(lab_type or "", "professional")


# ---- Deterministic edit operations (no-LLM refine fallback) -----------------
# Word-boundary + case-insensitive so the quick-action buttons fire on real
# drafts ("I Would Love", trailing punctuation) instead of only exact-case
# substrings.
_FORMAL_SUBS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bI would love\b", re.IGNORECASE), "I would greatly appreciate"),
    (re.compile(r"\bI am a fast learner\b", re.IGNORECASE),
     "I am committed to continuous professional development"),
    (re.compile(r"\bBest regards\b", re.IGNORECASE), "Respectfully"),
]
_ENTHUSIASTIC_SUBS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bI am very interested\b", re.IGNORECASE), "I am truly excited about"),
    (re.compile(r"\bI really enjoyed\b", re.IGNORECASE), "I was fascinated by"),
    (re.compile(r"\bI would love the chance\b", re.IGNORECASE),
     "I would be thrilled at the opportunity"),
]
_CONCISE_FILLERS: tuple[str, ...] = ("fast learner", "eager to pick up")

# Each op: the instruction keywords that select it, and how it edits. Category
# order (formal → concise → enthusiastic) is preserved by ``EDIT_OPS`` insertion
# order so ``_local_refine`` applies them deterministically.
EDIT_OPS: dict[str, dict] = {
    "formal": {"keywords": ("formal", "professional"), "subs": _FORMAL_SUBS},
    "concise": {"keywords": ("short", "concise", "brief", "trim"), "drop_fillers": _CONCISE_FILLERS},
    "enthusiastic": {"keywords": ("enthus", "excit", "energy", "passion"), "subs": _ENTHUSIASTIC_SUBS},
}
