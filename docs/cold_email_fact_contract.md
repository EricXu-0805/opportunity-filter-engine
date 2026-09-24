# Cold Email fact and draft contract

Updated 2026-09-24. Pipeline version: `w12.4`. See also `docs/matching_logic.md`;
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
- Generation (including streaming) and variants report the current pipeline version (`w12.4`). Refinement has
  no draft-cache/version field. The modal reuses a cached AI draft only when a
  fresh, session-guarded variants response and the cached generation response
  both have the same nonempty pipeline version, as well as satisfying the
  existing TTL and corpus checks. The comparison version is not hardcoded;
  an old generation response cannot establish its own current version.
- Automatic and manual generation wait for variants from the current target
  session. Late work from an earlier target cannot open that gate. Controlled
  frontend regressions cover these cache/session boundaries; no real provider
  output or overall email quality was validated by those tests.

## Unsupported action claims and skill levels (M32 partial)

- Shared draft, critique/revision and refinement checks reject recognized
  positive attachment and completed-paper-reading statements. The request has
  no actual attachment or reader-confirmation field: a resume upload, paper
  metadata, current draft or edit instruction cannot authorize either claim.
  Offers to provide materials on request, future reading plans, negation and
  ordinary references to a paper remain distinct from completed actions.
- Explicit first-person skill-level claims use `parts.skill_levels`, already
  reduced through the shared confirmed/claimable student-evidence rules.
  A beginner skill cannot become experience/proficiency, and an experienced
  skill cannot become expertise. These checks do not forbid supported project
  actions such as building a Python parser. Known mixed-level/negated clauses
  are separated, and C, C++ and C# remain distinct names.
- Deterministic template and variant outputs pass the same final fact check.
  A rejected or empty template has one finite recovery path: a trusted
  recipient salutation and an explicit research-opening inquiry without
  student identity or competence assertions. It does not call a provider or
  recursively regenerate. A valid user body is preserved during local editing;
  this server check does not monitor or overwrite manual edits in the browser.
- The template label "One example of my experience:" counts examples rather
  than achievements. Only that fixed label is excluded from numeric checking;
  the quoted project and any quantity after it still undergo the normal check.
- Local enthusiastic edits use measured interest wording and do not introduce
  the `thrilled`/`excited` adjectives forbidden by the lively voice rule.
- `tests/test_email_claims.py` and `tests/test_cold_email_claim_contract.py`
  cover recognized positive claims, negative/future controls, real project
  actions, claimable import levels, provider failure, template/variant recovery,
  critique and route wiring with provider calls stubbed.

The new checks are bounded English forms, not a language understanding proof.
They do not cover arbitrary paraphrases, translations, implicit claims or skill
aliases; they do not establish whether reading actually occurred. Cross-project
metric/source binding, attachment/reading confirmation schema and follow-up
questions remain separate work. Authorized real-email review is still needed
for usefulness and false positives; these tests make no deliverability or reply
rate claim.

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
