# Cold Email fact and draft contract

Updated 2026-09-24. Pipeline version: `w12.3`. See also `docs/matching_logic.md`;
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

## Experience selection (M31 partial)

- Initial AI generation and interactive refinement use the same student brief:
  rank all accepted resume bullets against the target's stated research and
  requirements, keep input order for ties, then take at most eight. A relevant
  ninth-to-twelfth bullet can therefore displace an earlier weak match.
- Deterministic templates and their variants use the same ranking with a
  two-shared-word minimum before quoting one example. The introduction says
  it is an example of the student's experience, not proof it is "most relevant".
- Student interests remain available as aspirations but never contribute to
  target relevance. Original bullet strings and the full accepted evidence
  list remain intact for factual validation; selection does not blend projects.
- This is English stem/word overlap, not semantic relevance or verification of
  a problem/method/project connection. The existing request limit is still
  twelve bullets of at most 500 characters; this change does not search every
  experience in a full resume. M31 still requires per-email research-connection
  review and evidence coverage beyond this bounded input.
- Generation (including streaming) and variants report `w12.3`. Refinement has
  no draft-cache/version field. The modal reuses a cached AI draft only when a
  fresh, session-guarded variants response and the cached generation response
  both have the same nonempty pipeline version, as well as satisfying the
  existing TTL and corpus checks. The comparison version is not hardcoded;
  an old generation response cannot establish its own current version.
- Automatic and manual generation wait for variants from the current target
  session. Late work from an earlier target cannot open that gate. Controlled
  frontend regressions cover these cache/session boundaries; no real provider
  output or overall email quality was validated by those tests.

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

- `tests/test_cold_email_resume_selection.py`: late relevant evidence, unrelated
  interests, stable source selection, and initial/refine/template route coverage.
- `tests/test_cold_email_fact_contract.py`: initial generation and refinement
  evidence, common competence phrasing, unsupported quantities, safe positive
  examples, provider fallback, and template skill levels.
- `tests/test_cold_email.py`, `tests/test_cold_email_boundary.py`,
  `tests/test_grounding.py`, plus relevant backend refinement tests: existing
  generation, greeting, contact and evidence boundaries.
- `frontend/src/components/ColdEmailModal.async.test.tsx` and the existing modal,
  confirmation and tracking suites: deferred results and actual user edits
  using real component/owner logic and controlled network responses.
