# Targeted Resume Tailor — Final Verification Report (W13)

Companion to `docs/tailor_boundary_audit.md`. Implemented on
`feat/tailor-boundary`; audit baseline `origin/main` @ `10babf3`.

## The invariant, enforced

```text
Targeted Resume Tailor
  = specific target (required, echoed, stamped)
  + user-confirmed facts (student-entered material is the ONLY corpus)
  + transparent suggestions (verified evidence quotes, diffs, warnings)
  + explicit user control (nothing auto-applies; truthful save states)

NOT invented content (incl. bare-number metrics), silent rewriting,
cross-target leakage, false "Saved", or unfinished document renovation.
```

## 1. Target binding

`opportunity_id` was already required (404 on unknown) on every generating
endpoint; W13 adds the missing half: every `/tailor`, `/tailor/renovate`,
`/tailor/bullet` response now echoes `opportunity_id` and stamps
`generated_at` + `pipeline_version` (`TAILOR_PIPELINE_VERSION`), mirroring
the W12 cold-email provenance contract. The client drops any response whose
echo doesn't match the open target.

## 2. Fact source policy

Unchanged core (already strong): the evidence corpus is student-side ONLY —
posting text is deliberately excluded; extraction is verbatim-contiguous;
every rewrite is validated. W13 closes the two holes:

- **Bare-number metrics** — new `LENIENT_PROSE_NUMERIC` grounding policy:
  digit runs in a rewritten bullet must appear as digit runs in the
  student's material (grouping-punctuation normalized, so "10,000" ↔
  "10000"). An invented "45%", "$2M", or "2023" now rejects the bullet to
  the student's own wording. All three tailor validation sites switched;
  cold email deliberately keeps plain `LENIENT_PROSE` (documented residual).
- **Skill-level honesty** — the per-bullet prompt now carries the same
  never-inflate-levels rule as the batch prompt (EN + ZH).

## 3. Suggestion evidence model

`source_evidence` is now **verified, not trusted**: a quote is shown only
when it actually appears in the student's material (`_verify_evidence` —
punctuation-insensitive contiguous containment; composite citations like
"Python (experienced); CS 225" pass only if every fragment is real).
A fabricated quote degrades to "" and the UI shows no evidence line rather
than a fake one. Applied at all three return paths (tailor bullets,
renovation variants, single-bullet optimize).

## 4. Suggestion lifecycle

Unchanged and confirmed: generated → (accept | edit | reject | restore) all
client-explicit; nothing auto-applies to any stored resume; rollback floor is
always the student's own `base_text`. States map: generated = response/variant,
accepted = variant selected/copied, edited = user variant appended, rejected =
excluded from copy/promote, restored = pointer at base, saved = **confirmed**
persistence only (below).

## 5. Save correctness

- `saveRenovation` now returns success/failure (null session, upsert error →
  `false`) instead of swallowing everything.
- The modal shows **"Saved" only on confirmed persistence**; failures render
  an explicit amber "Save failed — not synced. Retry" state that re-persists
  exactly the payload that failed. Thrown errors and falsy results both land
  in the failed state. Tests: success, failure, thrown, retry-recovers.
- The backend `macro_plan_failed` warning now maps to the degradation banner
  (string-prefix mismatch fixed).

## 6. Isolation guarantees

- **User**: own-row RLS on both renovation tables (device_id = auth.uid, so
  "device" is account-scoped); tailor drafts live under `USER_SCOPED_PREFIXES`
  and are wiped on uid change; account merge moves rows under grant proof.
- **Target**: storage keyed `(device_id, opportunity_id)`; modal state resets
  on target change; **new** generation-counter guard + target-echo check in
  `TailorModal.handleGenerate` closes the favorites-page race where a slow
  target-A response could render under target B. Tests pin both directions
  (mismatched echo dropped, matching echo rendered).

## 7. Staleness

New résumé fingerprints (`hashString(profile.resume_text)`):

- Tailor drafts persist as `{t, s}` envelopes; a restored draft whose sig no
  longer matches shows "Your résumé changed since this draft". Legacy
  plain-string drafts load fine and make **no** staleness claim (unknown ≠
  stale ≠ fresh).
- Renovation docs stamp `resume_sig` on every save; restoring a doc whose sig
  mismatches shows an amber re-renovate hint. Legacy docs: no claim.

## 8. MTP Renovate boundary

Document round-trip capabilities (full layout redesign, ATS templates,
DOCX/PDF generation, formatting preservation) **do not exist in the
codebase** — zero dependencies, routes, or UI; nothing unfinished is
exposed. The live text-level renovation flow is explicitly classified as
meeting the tailor-grade bar (staged grounding + variant lifecycle + test
suite), with its two real defects fixed here. A tripwire test fails the
build if document-generation dependencies or export routes ever appear,
forcing the MTP Renovate gating discussion before anything ships.

## 9. Tests

New: `tests/test_tailor_boundary.py` (16 — numeric grounding incl.
reformatting tolerance and policy separation, evidence verification incl.
composite/word-order cases, response provenance, round-trip tripwire);
frontend +9 (save success/failure/thrown/retry, stale-doc and legacy-doc
claims, mismatched/matching target echo, stale-draft chip, legacy-draft
no-claim) and 3 updated draft-envelope assertions. Existing suites already
pin: target-required 404s, student-side-only corpus, verbatim extraction,
paraphrase rejection, injection guards, variant lifecycle
(`test_tailor_route.py` 44, `test_resume_renovation.py` 38).

Requirement map (28 required behaviors): 1-4 target binding — required-404s
(existing) + echo stamps + drop-mismatch tests + per-target keys; 5-10 fact
safety — existing extraction/corpus suites + numeric policy + evidence
verification; 11-16 lifecycle — existing modal suites + save-truthfulness
tests; 17-20 save correctness — new failure/thrown/retry tests (timeout ==
thrown path); 21-24 isolation — RLS (migrations 020/021, existing) + uid
storage wipe (existing identity-owner tests) + target-echo tests; 25-28 MTP
boundary — tripwire tests (capability absent; nothing to hide, verified).

Results at close-out: backend + frontend suites green, tsc/eslint/ruff clean
(authoritative run: PR checks).

## 10. Remaining risks (documented)

1. Numeric grounding matches digit runs, not semantics: a student's "10" can
   ground an invented "10%" in unlucky phrasing; direction is fail-closed
   overall but not per-unit. Acceptable residual.
2. Cold-email prose keeps the numeral blind spot (deliberate — different
   register; professor briefs carry no student metrics). Follow-up candidate.
3. Structure headings remain AI-labeled organization (bounded, no factual
   claim) — accepted by design.
4. Whole-doc version snapshots still have no restore UI (recovery is manual
   re-renovation; the data is retained).
5. Concurrent tabs still last-writer-win on the renovation doc; the versions
   table is the recovery net. Low traffic, documented.
