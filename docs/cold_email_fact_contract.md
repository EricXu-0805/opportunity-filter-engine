# Cold Email fact and draft contract

Updated 2026-09-05. Pipeline version: `w12.2`. See also `docs/matching_logic.md`;
Cold Email retains its existing AI pipeline and deterministic fallback, while
Match remains deterministic by default.

## Evidence

- Student interests may explain motivation, but do not establish competence.
  First-person experience claims must be supported by the student's own skills,
  coursework or resume evidence. Target vocabulary cannot supply that support.
- Quantified achievements are checked against student resume bullets. The
  quantity and unit must be present; target facts, the current draft, and an edit
  instruction are not new student evidence.
- Beginner skills must not inherit the stronger wording of another skill in
  the same list. Templates separate experience from foundational knowledge.
- Generation, pipeline critique/revision, and interactive refinement share the
  same fact checks. Refinement receives both student and target briefs. An
  unsupported old draft cannot be preserved as a trusted fallback; the fallback
  rebuilds a deterministic draft when necessary.
- Normal requests such as a 15-minute conversation, course identifiers and
  dates must not be confused with invented achievements. Tests include honest
  mixed sentences that state existing experience and a separate new interest.

These are bounded English pattern and vocabulary checks, not semantic
entailment. Reusing an already-supported number for a different metric or
project is not fully detected. Full per-claim source identity, versioned
dependencies, and human review of authorized sample emails remain necessary.
The checks do not prove reply rates or the quality of every provider output.

## Draft lifetime

The modal binds pending work to the original owner epoch, profile, target and
open session. A close or identity transition retires that session immediately.
Results, failure feedback, extracted bullets and cached drafts from retired
sessions are discarded; a late stream error cannot launch another generation.

An edit revision protects manual body, subject and recipient changes as well
as variant selection. A late AI response remains selectable as a variant but
cannot replace newer manual work. Refinement is serialized and each result
updates its own chat message. Background template enrichment does not replace
an existing AI draft. Clipboard feedback is also session-bound.

Requests already dispatched are not forcibly cancelled. These client guards
prevent stale continuation and display; they are not a substitute for server
authorization. No email is sent by the modal. Copying or opening a composer
only exposes a confirmation prompt; explicit successful contact confirmation
is still required before recording contact in Tracker.

## Regression evidence

- `tests/test_cold_email_fact_contract.py`: initial generation and refinement
  evidence, common competence phrasing, unsupported quantities, safe positive
  examples, provider fallback, and template skill levels.
- `tests/test_cold_email.py`, `tests/test_cold_email_boundary.py`,
  `tests/test_grounding.py`, plus relevant backend refinement tests: existing
  generation, greeting, contact and evidence boundaries.
- `frontend/src/components/ColdEmailModal.async.test.tsx` and the existing modal,
  confirmation and tracking suites: deferred results and actual user edits
  using real component/owner logic and controlled network responses.
