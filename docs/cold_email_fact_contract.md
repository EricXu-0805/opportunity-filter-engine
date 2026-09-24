# Cold Email fact and draft contract

Updated 2026-09-24. Pipeline version: `w12.5`. See also `docs/matching_logic.md`;
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

## Confirmed experience selection (M12/M17 partial)

See `docs/experience_evidence_contract.md` for the versioned input and receipt.
Public email routes no longer treat legacy `resume_bullets` strings as evidence.
They remain parseable and produce an explicit review notice; generation can
still use the existing skills/coursework rules. An explicit empty structured
collection never falls back to those strings or to automatic raw extraction.

- Initial generation, streaming, variants and refinement admit only confirmed
  manual entries or confirmed resume entries whose exact SHA-256 and Unicode
  source range match the supplied current resume. Other entries are excluded
  with a reason. They cannot supply facts to either prompts or final checks.
- All eligible full entries participate in deterministic target relevance
  ranking before the eight-entry / 4,000-total-codepoint prompt cap. Complete
  entries are packed without splitting sentences or clipping qualifiers.
  Nonfitting entries remain in the library and produce a budget notice; a
  valid entry longer than 4,000 codepoints is not yet sent to the model.
- Templates use the same full-entry ranking with the existing two-word minimum
  and at most one complete entry no longer than 220 codepoints. Longer entries
  produce a template-budget notice. A neutral final recovery uses none.
  Local refinement reports complete confirmed facts present in its actual
  input, capped at eight / 4,000 with an explicit partial-receipt notice.
  Every result reports context supplied for its final engine, not sentence-
  by-sentence citations. No provider-call count or total prompt budget grows.
- Complete eligible entry text remains in the deterministic student fact
  corpus. It is not all copied into the LLM prompt. Skills retain their
  separate level-confirmation rules; confirming an experience never upgrades
  a skill level. Target interests do not authenticate student experience.
- Selection is English stem/word overlap, not semantic relevance or proof of
  a project/research connection. Full Match/Tailor/Renovate library consumers
  and arbitrary per-claim source binding remain separate work.
- Generation, variants and refinement report pipeline version `w12.5`.
  The modal's existing current-session variants/version/TTL/corpus guards
  prevent old cached drafts from establishing their own current version.
  These controlled tests do not validate real provider quality or reply rates.

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
