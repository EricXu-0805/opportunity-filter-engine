# Data & Content Truthfulness — Phase 1 Audit

Audited tree: `origin/main` @ `5b56849` (PR #701). Audit date: 2026-07-31.
Method: six parallel code audits (schemas/provenance, collectors/normalizers,
backend API + matching, frontend display, AI-generated content, QA tooling),
cross-checked against the live corpus (78,692 records across shards) and the
merged truthfulness arc (#655 W5, #657 W7a, #663 W9, #697 W8b, #699, #701).

Core invariant audited against:

```text
verified evidence        → value may be presented as verified
missing/ambiguous/inferred evidence → value must remain unknown/unverified/conflicting
```

---

## 1. Existing evidence model (do NOT build a parallel one)

The repo already has a two-tier evidence model. Tier 1 (strong, fail-closed)
covers publications, professor tracking, and email reveal; Tier 2 (weak,
record-level only) covers the corpus body.

| Concept | Existing field / module | State |
|---|---|---|
| Record source | `source`, `source_url`, `source_type` (every record) | PASS |
| Freshness | `metadata.last_verified`, `last_seen_at`, `first_seen_at` | PARTIAL — `last_verified` means "collector ran", not "value verified" (stamped even for offline seed generation, `campus_graph.py`) |
| Verification scope | `metadata.verification_scope` (`curated`/`directory`/`profile`, W7a) | PARTIAL — stamped in code (`faculty_graph.py:471`), absent from shipped shards (0/242 Bowdoin, 0/1,158 UVA sampled); lives only in the tracking artifact |
| Email provenance | `metadata.email_source` + `backend/lib/contact_visibility.py` deny-list | PARTIAL — deny-list fails OPEN for the unstamped legacy majority (~77k/78k); some data values (`directory`, `profile`) have no committed producing code |
| Publication attribution | `metadata.publication_attribution_status` + `src/publication_trust.py` equality gate | PASS — fail-closed at every serving path; corpus 100 % unstamped → honestly dark |
| Field-level evidence text | `metadata.research_areas_raw`, `eligibility.eligibility_text_raw`, tracking before/after payloads + SHA-256 hashes | PARTIAL — only these three |
| Confidence | `metadata.confidence_score` | FAIL — formulaic (`0.7 if email else 0.5`), write-only, never read by matcher/backend; the most-inferred source (nsf_reu) carries the highest value (0.95) |
| Manual review | `metadata.manually_reviewed` | FAIL — vestigial (33/78,692, all `source=manual`); documented "confidence<0.6 → flag for manual review" rule never implemented |
| Conflict status | — | NOT IMPLEMENTED (single hand-built guard: `normalizers/rolling_truth.py`) |
| Collector version | — | NOT IMPLEMENTED (run-level only via `collector_status.json`) |
| Unknown trace at decision time | `MatchResult.unknowns` + neutral scoring (#701) | PASS — omits contact-email absence and `application_effort` |

Answers to the seven mandatory questions, corpus-body tier: (1) where from —
record-level yes, field-level no; (2) exact evidence — only the three fields
above; (3) when checked — conflated with "when regenerated"; (4) stated vs
inferred — **not distinguishable** for intl/paid/skills/keywords written by
`llm_tagger`/`llm_enrich`/`openalex_enrich`; (5) status vocabulary — exists
only for publications/tracking/email; (6) transformed — deadline normalizer
drops confidence/type at `to_legacy` (APPROXIMATE "Spring 2026" → `2026-01-31`
indistinguishable from EXACT); (7) which entity — department attribution is
"which listing page was scraped", cross-listed people get the scraping dept.

## 2. Source priority — NOT IMPLEMENTED

No field-level source-priority rule exists anywhere. Cross-source conflicts are
resolved by (a) merge **order** in `refresh_all.py:559-567` (a Python list
position), (b) keyword-count richness in dedup survivor choice, (c)
latest-scrape-wins wholesale upserts (`merge_into_processed` in every
collector). Enrichment appliers are fill-only (good), but a re-scrape silently
overwrites earlier values with no conflict record. Search snippets are not used
as evidence anywhere (PASS).

## 3. Category verdicts

| Category | Provenance | Explicit unknown | No optimistic completion | Display honesty | Overall |
|---|---|---|---|---|---|
| School | config-curated + source_url | n/a (always present) | PASS | PASS | **PARTIAL** |
| College/department | listing-page attribution only | FAIL (empty string) | FAIL (dept = scraped page; survivor by keyword richness) | PASS (verbatim) | **PARTIAL** |
| Professor (identity/affiliation) | tracking artifact strong; corpus weak | n/a | PASS (conservative merges; same-name merge requires URL+name; ambiguous email groups nulled not merged) | PASS | **PARTIAL** |
| Position | none — synthesized | FAIL | **FAIL — "Professor" default in ~17 code paths; 12 % of displayed faculty are Lecturer/Director per their own `faculty_title`** | FAIL ("Prof." framing universal; `faculty_title` not served to UI) | **FAIL** |
| Program/opportunity | `metadata.status`, `discovered`, `deadline_note` | PASS (`status: unknown`) | PARTIAL (detected-"closed" only edits title suffix, stays active; reachable ⇒ active) | PASS | **PARTIAL** |
| Deadline | none per-field | PARTIAL (null overloaded; `is_rolling` disambiguates) | PARTIAL (no fabrication in normalizer — reference standard; but blanket `is_rolling=True` on 73k faculty records; NSF estimated dates drive real deactivation; `to_legacy` drops APPROXIMATE marker) | FAIL ("Rolling — no fixed deadline" asserted for the blanket default; estimate marker dropped on cards/urgency) | **PARTIAL** |
| International eligibility | `eligibility_text_raw` where scraped | PASS (exemplary enum) | FAIL (`citizenship_required=False` no-data default — no unknown state; nsf_reu no-mention → "no"+True; `llm_tagger` substring bugs: "nsf" in "tra**nsf**er", negation-blind yes-phrases; no stated-vs-inferred stamp) | PASS (unknown → "Verify" badge; matcher hard-excludes only explicit "no") | **PARTIAL** |
| Email | `email_source` (1.6 % coverage July → growing) | PARTIAL (null overloaded: none-found vs never-checked) | PARTIAL (construction is stamped + reveal-gated; but `profile_email` single-candidate heuristic and `pi_enricher` first-email-on-page can bind a wrong address with no stamp; `_is_actionable` ranks synthesized emails without the provenance bar) | PASS (no guessing at serving; honest empty state) | **PARTIAL** |
| Research area | `research_areas_raw` evidence; per-keyword source lost | FAIL (empty list) | PARTIAL (dept themes well-guarded off individuals; but scraped/LLM/OpenAlex keywords indistinguishable at rest — known debt; OpenAlex surname-substring author match feeds keywords ungated) | PARTIAL (neutral "Keywords" label; no provenance distinction) | **PARTIAL** |
| Publication | status stamped with works at write | PASS (absent = unverified, fail-closed) | PASS | PASS (frontend equality gate, test-pinned) | **PASS** |

## 4. Optimistic-completion inventory (exact locations)

Collector tier:
1. `faculty_graph.py` — `"Professor"` title default (:88, :352, :722, :734, :1404, :1460, :1604, :1696, :1757, :1824, :1855-1888, :2043-2060, :2191, :2721, :2821, :2919, :3068); flows into title text (:380) and `metadata.faculty_title` (:460). Same in `ucb_common.py:719`.
2. `faculty_graph.py:408` / `ucb_common.py:768` — invented `lab_or_program = "Prof. X's Research Group"` on every faculty record.
3. `citizenship_required=False` no-data default: `faculty_graph.py:433`, `campus_graph.py:278`, `handshake.py:322`, `manual_importer.py:103`.
4. `nsf_reu.py` — no-mention → `international_friendly="no"` + `citizenship_required=True` (:128-137, :261); fabricated estimated deadlines feed `deactivate_past` (:54-91); award-start-date as `posted_date` (:252); `_is_reu_site` boolean bug (:194-196) admits non-REU awards with REU-specific hardcoded claims at confidence 0.95.
5. `llm_tagger.py` — substring federal-org match (:348-358), negation-blind yes-phrases (:304-321), `citizenship_required` derived from inferred intl (:494-497), `"$"` anywhere ⇒ paid yes (:332); all written with no inferred-vs-stated stamp.
6. `pi_enricher.py` — first school-domain email on page → `contact_email` (:182-186, :230-236) unstamped; coordinator name → `pi_name` (:251-264); `_infer_pi_from_lab` (:191-213).
7. `manual_importer.py:93-94` — import date as `posted_date`.
8. `handshake.py:317` — hardcoded `preferred_year` soph-senior.
9. Universal defaults asserted as data: `preferred_year` all-four-years (fg:428, documented policy), `application_effort`/`contact_method` (fg:439-444), blanket `is_rolling=True` (fg:420).

Serving tier:
10. `backend/schemas.py:33` — `international_student: bool = False` (omitted ⇒ intl protections disarm); `:40` `can_cold_email=True`; `:27` unknown home school ⇒ `"uiuc"` (ranker:2392).
11. `ranker.py:1119-1131` — on-campus F-1 bonus + "no work authorization concerns" reason granted when school fields are missing.
12. `ranker.py:63-74` — `_is_actionable` counts provenance-flagged synthesized emails.
13. `backend/routes/opportunities.py:447/:534` — Ask-AI prompt renders missing `citizenship_required` as literal `False` (same `on_campus` :439).
14. Frontend: "Rolling — no fixed deadline" for the blanket default (`DetailSections.tsx:77-83`); `deadline_is_estimate` dropped on MatchCard badge/urgency (`MatchCard.tsx:231-237`, red "Deadline passed" possible from an estimate); "Unpaid" filter bucket includes unknown (`use-results-filters.ts:82`); scope filter "Open to all" includes `audience==='unknown'` (`discovery-scope.ts:33`) while the chip says "Audience unconfirmed"; universal "Prof."/"Email Professor" framing with `faculty_title` untyped and unread.

## 5. Generated-content audit

| Surface | Verdict |
|---|---|
| Cold email (template + AI + refine) | PASS — verified-works-only at 4 points; dept-name hooks refused; post-generation fabrication gate with template fallback |
| Resume tailor/renovation | PASS — student-only evidence corpus; verbatim grounding; per-bullet `source_evidence` |
| Match reasons (templated) + unknowns trace | PASS |
| Saved-search digests | PASS — templated; deadline line only when a deadline exists |
| Ask-AI chat | PARTIAL — honest fact sheet + "use ONLY" instruction, but no output-side gate; `bool()` coercion bug above |
| LLM rerank `ai_reason` / explain prose | PARTIAL — inputs gated, outputs instruction-only (no grounding validation) |
| LLM-derived keywords at rest | FAIL — grounded at harvest, unlabeled at rest (feeds cold-email hooks, rerank, search) |
| Import extraction | PARTIAL — "never invent" prompt + enum validation + `llm_enriched` stamp, no source-text echo check |

Grounding gate (`backend/lib/grounding.py`) limits: vocabulary-level, letter-led
tokens only (numbers/dates invisible); runs only on cold-email + tailor.

## 6. QA / manual verification state

- DQ gate (41 tests) = shape/coverage/known-corruption pins only; **no value-vs-source verification exists anywhere**.
- Manual tooling is print-only (`cold_email_eyeball.py`, `audit_opportunities.py`); past manual audits survive only as hard-coded regression pins.
- **No manual sample-verification framework, no reviewer/reviewed_at/expected-vs-actual artifact format exists** → NOT IMPLEMENTED.
- No documented sampling standard exists → the sample plan in `docs/truthfulness_sample_plan.md` (new) is proposed per Phase-2.
- Best reusable template: professor-tracking evidence block (before/after + SHA-256 + fail-closed `release_ready`).

## 7. Per-requirement verdicts (audit items 1-18)

1. Schemas per category — inventoried (§1, §3): PARTIAL
2. Collectors/parsers per category — inventoried: PASS (audit coverage)
3. Normalization & fallback logic — §4: FAIL (optimistic completion present)
4. Provenance fields — §1: PARTIAL (two-tier)
5. Source-priority rules — §2: NOT IMPLEMENTED
6. Verification statuses — publications/tracking/email only: PARTIAL
7. Unknown semantics — enums + #701 trace strong; `citizenship_required`, dept "", null overloads: PARTIAL
8. Conflict semantics — NOT IMPLEMENTED (except rolling_truth)
9. API serialization — redaction + fail-closed pubs PASS; Ask-AI bool() FAIL: PARTIAL
10. Frontend display — §4.14: PARTIAL
11. Matching/ranking — neutral unknowns PASS; `_is_actionable`, F-1-bonus-on-missing, effort-untraced: PARTIAL
12. AI/generated content — §5: PARTIAL
13. Manual QA process — §6: PARTIAL (automated only)
14. Sample artifacts/review tools — NOT IMPLEMENTED
15. Inferable/optimistically-completed fields — §4 list
16. Fields losing source evidence — keywords (3 pipelines), deadline type/confidence at `to_legacy`, position (title default), `email_source` gaps
17. Unknown → false/true/zero/empty/hidden — `citizenship_required` (→False), Ask-AI bool render, `international_student` profile default, "Unpaid"/"Open to all" filter buckets, department "" ; deadline unknown ⇒ never expires (lifecycle)
18. Files requiring changes — see Phase-2 plan in the PR description / `docs/truthfulness_report.md`

Overall Phase-1 decision: the repo has a real, recently-built truthfulness
backbone (publications, tracking, matcher unknowns, cold-email/tailor
grounding) but **fails the closeout bar** on: position fabrication, inference
provenance (intl/keywords), source-priority/conflict model, and the complete
absence of a manual sample-verification framework. Phase 2-5 address these.
