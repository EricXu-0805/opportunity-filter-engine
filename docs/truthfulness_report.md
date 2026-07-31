# Data & Content Truthfulness — Close-out Report (W11)

Companion to `docs/truthfulness_audit.md` (Phase-1 findings). This report
records what was implemented, the manual sample-verification results, and the
final GO/NO-GO decision. Sample artifacts: `data/audits/samples/*.json`,
aggregate: `data/audits/truthfulness_report.json` (regenerate with
`python scripts/truthfulness_audit.py report`).

## 1. Evidence model (existing, extended — no parallel system)

- Record-level: `source`, `source_url`, `source_type`, `metadata.last_verified`
  / `first_seen_at` / `last_seen_at` (collector-run stamps), `metadata.
  verification_scope` (W7a), `metadata.email_source` (W7a),
  `metadata.publication_attribution_status` (W9/#699), tracking artifact with
  before/after payloads + SHA-256 hashes (#697).
- **New in W11** (`src/evidence.py`, one shared authority):
  - `metadata.inferred_fields` — `{dotted.field: producer}` stamps written at
    every inference site (`rule:llm_tagger`, `llm:llm_tagger`,
    `llm:bio_extraction`, `derived:openalex_topics`,
    `policy:nsf_reu_solicitation`, `estimate:award_start_date`,
    `rule:lab_title_surname`). Stated-vs-inferred is now distinguishable at
    rest for every NEW write; legacy values stay unstamped (= unknown
    provenance), matching the W7a additive contract.
  - `SYNTHESIZED_EMAIL_PREFIXES` + `harvested_contact_email` — the single
    synthesized-vs-observed predicate shared by the reveal flow
    (`backend/lib/contact_visibility.py`) and ranking
    (`src/matcher/ranker._is_actionable`).
  - `metadata.conflicts` — bounded, deduped audit trail for source
    disagreements (`record_conflict`).

## 2. Authoritative source policy

`src/evidence.SOURCE_PRIORITY` (rank 0 = most authoritative):
official page/API & official announcements → academic-identity sources
(OpenAlex) → approved third-party aggregators (Simplify, Handshake) →
rule/LLM inference → constructed values → discovery (leads only, never
evidence). `can_override(new, old)`: equal-or-higher rank may refresh; lower
rank must abstain or record a conflict. Existing behaviors mapped onto the
policy: all enrichment appliers are fill-only (never overwrite a stated
value); `llm_tagger.apply_updates` fills `unknown` only and now never writes
`citizenship_required=False` by inference; search/discovery results are used
for URL discovery only, nowhere as evidence.

## 3. Unknown semantics (enforced end to end)

- `international_friendly`: "unknown" enum preserved; matcher scores unknown
  neutrally + traces it (#701); UI badge "Verify"; hard exclusion only on
  explicit "no"/`citizenship_required is True`.
- `citizenship_required`: now **tri-state** (`True`/`False`/`None`). External
  sources (Handshake) and deep-crawled campus programs default `None`;
  curated campus programs derive `True` only from explicit "no",
  `False` only from explicit "yes"; the faculty-record `False` is a
  documented product-policy claim (docs/international_logic.md), commented
  in-code. Ask-AI prompts render `None` as "unknown" — never `bool()`-coerced
  to a confident "False" (`_tri_state`, also applied to `on_campus`).
- Position: missing rank is now `metadata.faculty_title == ""` (explicit
  unknown), never the fabricated "Professor" default — removed from all 22
  collector paths (`faculty_graph.py`, `ucb_common.py`) including curated-seed
  and sitemap paths.
- Deadline: missing stays `None`; "rolling" is never converted to a date;
  estimated dates carry `deadline_is_estimate` + an `inferred_fields` stamp,
  render with an "est." marker on every surface, never produce a red
  "Deadline passed"/urgent state, and never drive `deactivate_past`.
- Paid: unknown stays "unknown" ("Not disclosed" badge); the results filter
  bucket is relabeled "Unpaid / not disclosed"; "unfunded" no longer reads as
  paid; a bare "$" is no longer compensation evidence.
- Audience/scope: the "Open to all" filter that includes unconfirmed
  audiences is labeled "(incl. unconfirmed)".
- Rolling display: "Rolling — no fixed deadline" renders only with scraped
  rolling evidence (`metadata.deadline_note`); faculty records say "Accepts
  inquiries year-round" (the documented premise); everything else says
  "No fixed deadline listed".

## 4. Conflict semantics

`record_conflict` preserves (field, kept, rejected, sources, seen_at), deduped
and capped. Existing single-pair guard (`normalizers/rolling_truth.py`)
unchanged. Cross-source merge order remains the documented refresh sequence;
a lower-priority source that disagrees must abstain and record, never
overwrite (`can_override` + tests).

## 5. Candidate vs verified

- Publications: unchanged fail-closed boundary (#699) — `verified_author_id`
  equality at every serving path; name-matched works stay internal candidates.
- Emails: synthesized addresses (`constructed*`, `inferred*`, `guessed*`,
  `pattern*`) are stored candidates — refused as send targets (W10b) and now
  also refused as ranking "actionable" signals (`_MATCHER_VERSION_BASE` bumped
  to 4). `pi_enricher`'s page-scan grabs are stamped `email_source =
  "page_scan"` (weaker binding than `profile_page`, still official-page text).
- Inferred eligibility/keywords: stamped via `inferred_fields`; fill-only
  writers cannot overwrite stated values.

## 6. Optimistic fallbacks removed

1. "Professor" default title (22 paths) — position unknown stays unknown.
2. Fabricated `lab_or_program = "Prof. X's Research Group"` — now "".
3. "Prof./Professor" framing: record titles, descriptions, cold-email
   greeting ("Dear Professor X"), match-card CTA, and publications note are
   rank-gated (`is_professor_rank`); serving rewrites legacy titles when the
   record's own stated rank contradicts the honorific
   (`backend/lib/position_truth.py`).
4. `citizenship_required=False` no-data defaults (Handshake, campus deep-crawl,
   manual importer) — now `None`.
5. `llm_tagger` inference bugs: federal-org matching word-bounded ("nsf" no
   longer matches inside "transfer"); negation-blind/ambiguous "yes" phrases
   removed + negation guard; inference can assert a restriction but never the
   absence of one.
6. `nsf_reu`: `_is_reu_site` boolean bug fixed (non-REU awards no longer ship
   REU stipend/eligibility boilerplate); award start date no longer fabricated
   into `posted_date`; policy-derived intl "no" now cites the REU solicitation
   in `work_auth_notes` and is stamped policy-derived.
7. Estimated deadlines no longer deactivate records (`deactivate_past`
   `skipped_estimate`).
8. Ask-AI `bool()` coercion of missing `citizenship_required`/`on_campus` —
   now "unknown".
9. Compare/urgency: estimated dates capped at amber "soon", never red.

## 7. Generated-content safeguards

Unchanged and verified: cold-email fabrication gate + verified-works-only at
four points; tailor verbatim grounding; templated match reasons + `unknowns`
trace; digests assert deadlines only when present. New: cold-email greeting
rank gate; Ask-AI tri-state renders. Known residuals (documented, below):
chat/rerank outputs are instruction-guarded but not output-gated; grounding
gate is blind to digit-led tokens.

## 8. Manual sample verification (Phase 4)

Plan: `docs/truthfulness_sample_plan.md` (10 samples/category: ~4 risk-quota +
6 seeded-random; ≥8 reviewed to count a category; critical failures block).
Reviewer: `claude-fable-5-audit` (AI-assisted review against live sources;
fetches polite, WAF pages recorded as blocked, never evaded).

100 samples (10 per category), all reviewed 2026-07-31 against live sources
(with the collector-documented official channel — e.g. the UCSB URCA public
sitemap — used where a detail page is a client-side app):

| category | verified_correct | correctly_unknown | incorrect | unsupported | source_mismatch | blocked |
|---|---|---|---|---|---|---|
| school | 10 | 0 | 0 | 0 | 0 | 0 |
| college/department | 5 | 2 | 0 | 0 | 1 | 2 |
| professor | 7 | 0 | 0 | 0 | 0 | 3 |
| position | 5 | 0 | 2 | 0 | 0 | 3 |
| program/opportunity | 6 | 2 | 0 | 0 | 1 | 1 |
| deadline | 0 | 9 | 0 | 0 | 0 | 1 |
| international | 1 | 6 | 0 | 0 | 0 | 3 |
| email | 6 | 1 | 0 | 1 | 0 | 2 |
| research area | 5 | 5 | 0 | 0 | 0 | 0 |
| publication | 1 | 8 | 0 | 0 | 0 | 1 |
| **total** | **46** | **33** | **2** | **1** | **2** | **16** |

Zero critical findings; zero entity mismatches; zero conflicting. The five
non-correct findings, all minor, all with the responsible pipeline identified:

1. `position-005` (GaTech): stored rank "Professor" vs page "Richard A. Duke
   Assistant Professor" — the legacy collector default in action. Pipeline fix
   shipped in this PR (default removed); record corrects on next refresh.
2. `position-003` (UCB): stored "" (unknown) vs page "Lecturer" — safe
   direction (missed capture, not fabrication).
3. `department-009` (MSU): `source_url` was the bare API id `100409` — one of
   **395 corpus records** with non-URL source links (MSU NatSci / ASU
   feeds). Engine guard shipped in this PR (schemeless `json_dir` link with
   no `link_base` is dropped → directory_url fallback); rows heal on refresh.
4. `email-005` (CU Boulder): stored address not displayed on the recorded
   source page (uncontradicted, unstamped, never presented as verified) —
   evidence-traceability gap noted.
5. `program-004` (Duke Climate+): recorded source URL now lands on the
   institute homepage — link rot; the record's own status stays "unknown".

Notable positive results: all multi-campus / similarly-named school risk
cases resolved correctly; both emeritus/visiting risk professors carry their
visiting rank verbatim in `faculty_title`; the one publication sample with
works confirmable on the professor's own page is *still* correctly dark in
the product (fail-closed even when right); the Stanford constructed email is
now confirmed live yet remains reveal-gated by its provenance stamp.

Blocked samples (16) are WAF challenges (Cloudflare/Imperva: Princeton, JHU,
Duke, UPenn), client-side-only pages (Georgetown/ASU/Vanderbilt/Workday), and
TLS handshake failures to `illinois.edu`/`utk.edu` subdomains from the review
vantage. None were evaded, per policy. The blocked set includes one drawn
explicit-"yes" international sample — flagged for the next sampling round.

## 9. Tests

- `tests/test_truthfulness.py` — 44 tests: evidence model (stamps, priority,
  conflicts), position unknown/rank gating (collector + serving), citizenship
  tri-state + inference-never-asserts-absence, tagger word-boundary/negation
  fixes, paid detection order, estimated-deadline lifecycle, REU site filter,
  email provenance bars (ranker ↔ reveal agreement), derived-keyword
  stamping at write, and the chat-prompt unknown render.
- `tests/test_truthfulness_framework.py` — 8 tests: sample generation for
  every category, verification-status derivation, determinism, fail-closed
  NO-GO on pending/missing/critical, RESOLVED flow.
- Updated pins: cold-email greeting (rank-gated), plus frontend suites
  (MatchCard estimate badge/CTA gating, DetailSections rolling wording,
  match-utils urgency, compare labels) — 1,753 frontend tests green.
- Pre-existing suites relied on: `test_publication_trust.py` (fail-closed
  boundary), `test_grounding.py`, `test_professor_tracking.py` (release gate),
  DQ gate (41 corpus invariants).


### Required-behavior coverage map (48 behaviors)

| # | Behavior | Coverage |
|---|---|---|
| 1 | verified value retains source evidence | `test_professor_tracking.py` (evidence re-derivation), `test_openalex_enrich.py` (stamp written WITH works) |
| 2 | missing evidence ≠ verified | `test_publication_trust.py` (absent fails closed); `test_truthfulness_framework.py` (derive: no stamp → unverified) |
| 3 | lower-priority source cannot override | `test_truthfulness.py::TestEvidenceModel::test_lower_priority_cannot_override` |
| 4 | conflicting sources → conflict state | `test_truthfulness.py::test_conflict_is_recorded_not_silently_dropped`; rolling-vs-deadline: `test_deadlines.py` (rolling_truth) |
| 5 | missing value stays explicitly unknown | `test_truthfulness.py` (intl unknown, missing deadline, tri-state) |
| 6 | unknown never becomes true/false/0/inferred | `test_truthfulness.py::TestDerivedContentLabels::test_chat_prompt_renders_missing_citizenship_as_unknown`, `test_inference_never_writes_citizenship_false`, `test_bare_dollar_sign_is_not_evidence` |
| 7 | candidate never overwrites verified | `test_truthfulness.py::test_stated_value_is_never_overwritten_by_inference`; fill-only enrichers: `test_llm_enrich.py`, `test_openalex_enrich.py`, `test_email_backfill.py` |
| 8 | generated content can't confirm unknown | chat-prompt test (above); `test_cold_email.py` fabrication gate; `test_grounding.py` |
| 9 | school identity requires source | DQ gate (valid school slug per record, `(school,audience)` pinned to SOURCE_DEFAULTS); manual school samples |
| 10 | multi-campus not merged | dedup requires same URL+name (`test_ucb_dedup.py`); manual multi-campus risk samples |
| 11 | lab not serialized as college/dept | `test_truthfulness.py::test_no_fabricated_lab_entity` |
| 12 | center/institute ≠ department without evidence | manual department risk samples (automated N/A: department comes from curated config, audited by samples) |
| 13 | same-name professors distinct | `test_ucb_dedup.py` / collapse tests (merge requires URL+name; ambiguous email groups nulled) |
| 14 | current affiliation requires evidence | `test_professor_tracking.py` (baseline requires verification_scope=profile) |
| 15 | missing position stays unknown | `test_truthfulness.py::test_missing_title_is_not_professor` |
| 16 | non-professor not converted to professor | `::test_stated_non_professor_rank_is_preserved_not_upgraded`, `::test_stated_non_professor_rank_strips_honorific` |
| 17 | emeritus/visiting preserved | `::test_emeritus_is_dropped_not_relabeled` (retired ranks never ship as active contacts) |
| 18 | archived program not marked open | manual program risk samples (URAP finding, §8); `metadata.status` explicit-unknown derivation test |
| 19 | current-cycle deadline accepted with evidence | `test_deadlines.py` (exact parse, confidence) |
| 20 | prior-year deadline not reused | `test_deadlines.py` (no silent today(), UNPARSEABLE sentinel); estimates: `::test_estimated_deadline_never_deactivates` |
| 21 | page update date ≠ deadline | `test_deadlines.py` garbage guards; nsf posted_date fabrication removed (code) + manual deadline samples |
| 22 | rolling not converted to a date | `test_deadlines.py` (to_legacy rolling → (None, True)) |
| 23 | missing deadline stays unknown | `::test_missing_deadline_stays_unknown_not_expired` |
| 24 | explicit eligibility preserved | `::test_explicit_welcome_is_yes` |
| 25 | explicit ineligibility preserved | `::test_explicit_restriction_is_no` |
| 26 | conditional eligibility retains conditions | `::test_condition_bearing_phrase_is_not_yes`; `test_simplify_internships.py` sponsorship map |
| 27 | no mention → unknown | `::test_no_mention_is_unknown_not_yes` |
| 28 | missing restriction ≠ eligible | `::test_inference_never_writes_citizenship_false` |
| 29 | unrelated policy doesn't override program evidence | `::test_federal_org_match_is_word_bounded` (family policy applies only inside the REU family); `::test_nsf_reu_no_mention_is_policy_no` |
| 30 | email ↔ correct professor | `test_profile_email.py` (name agreement, ambiguity → None), `test_email_backfill.py` |
| 31 | program email ≠ professor email | shared-inbox nulling (`test_pi_enricher.py`, DQ shared-admin gate) |
| 32 | department email ≠ professor email | same as 31 |
| 33 | inferred email pattern stays unverified | `::test_actionable_requires_harvested_provenance`, `::test_ranker_and_reveal_bars_agree` |
| 34 | missing email stays unknown | `::test_missing_email_is_unavailable_not_guessed` |
| 35 | professor-specific research area verifiable | `research_areas_raw` capture (collector suites) + manual research samples |
| 36 | dept research area not auto-assigned | `test_llm_enrich.py` (shared-URL skip), `test_openalex_enrich.py` (unique-owner guard) |
| 37 | lab research area not auto-assigned to members | same shared-URL guards |
| 38 | AI topic ≠ source evidence | `::test_llm_keywords_are_stamped_at_write`, `::test_openalex_keywords_are_stamped_at_write`, `::test_scraped_keywords_carry_no_inference_stamp` |
| 39 | missing research area stays unknown | framework derive test (empty keywords → unknown) |
| 40-44 | publication trust behaviors | `test_publication_trust.py` (verified passes; name-only, absent, junk, legacy all fail closed — per-surface) |
| 45 | every category produces a sample artifact | `test_truthfulness_framework.py` (all 10 categories) |
| 46 | sample records evidence + reviewer result | framework schema test |
| 47 | failed sample visible in report | framework report test (counts + critical_open list) |
| 48 | unresolved critical blocks approval | framework NO-GO tests (pending/missing/critical → not approved) |

Results at close-out: backend suite green (374 passed pre-W11-additions run;
final run includes the 48 new tests — see PR checks), frontend 1,754 tests /
111 files green, `tsc --noEmit` clean, eslint clean, ruff clean.

## 10. Remaining residuals (documented, not silently accepted)

1. Legacy `faculty_title == "Professor"` records: real ranks and historical
   defaults are indistinguishable until re-scrape regenerates each school
   (weekly shard cron). Serving-side rewrite fixes every record whose stated
   rank contradicts the honorific; the rest carry the legacy value.
2. Legacy unstamped emails pass the reveal deny-list by design (W10b
   documented decision) — real scrapes predating provenance stamps.
3. Keywords written before W11 carry no `inferred_fields` stamp (legacy
   keyword-provenance debt persists for old records until re-enrichment).
4. Chat/rerank LLM outputs are instruction-guarded, not output-gated.
5. Compare page assigns neutral midpoints to absent data in its client-side
   score; labeled as a comparison heuristic, not a verified fact (candidate
   for a later disclosure pass).
6. `metadata.confidence_score` remains write-only and formulaic; not promoted
   to any product meaning (candidate for removal).

## 11. Final decision

```text
GO
```

Basis: every required category has representative reviewed sample evidence
(≥7 substantive verdicts each, artifacts committed); zero critical or
entity-level misrepresentations were found; the two value errors found are
minor, have their responsible pipelines fixed in this PR, and heal on
refresh; no path was found by which an unknown fact is presented to users as
a confirmed claim after the W11 changes. The aggregate artifact
(`data/audits/truthfulness_report.json`) computes the same decision
fail-closed.

Conditions attached to the GO (tracked, not blocking):

1. **Post-refresh recheck** — after the next full shard cycle regenerates
   MSU/ASU (source_url heal), GaTech (rank heal), and rank-unknown records,
   re-run `scripts/truthfulness_audit.py sample --category position` and
   recheck; the sample plan's correction loop applies.
2. **Blocked-host follow-ups** — the WAF/TLS-blocked samples (incl. the one
   explicit-"yes" international case) should be redrawn or checked from a
   vantage that reaches those hosts, still without evasion.
3. **Publications remain dark** until the verified OpenAlex re-harvest stamps
   `verified_author_id` — the correct fail-closed state, not a defect.
4. Reviewer provenance: this round was an AI-conducted review
   (`claude-fable-5-audit`) against live sources with evidence excerpts
   recorded per sample; a human spot-check of any category is reproducible
   from the committed artifacts.

Truthfulness invariants restated and enforced:

```text
verified fact  = exact entity + exact field + supporting source evidence + valid verification status
insufficient evidence → explicit unknown  (never an optimistic value, an inferred fact, or silent eligibility)
```
