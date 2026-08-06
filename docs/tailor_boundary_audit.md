# Targeted Resume Tailor — Trust, Control & Data-Isolation Audit (W13, Phase 1)

Audited tree: `origin/main` @ `10babf3` (post-W12). Audit date: 2026-08-03.
Method: two full-lifecycle audits (backend routes → prompts → grounding →
persistence → isolation; frontend surfaces → lifecycle actions → save flows →
storage keys → hidden features).

Boundary: tailor = specific target + user-confirmed resume facts +
evidence-backed suggestions + explicit user control — never invented facts,
silent rewrites, cross-user/target mixing, false saved state, or exposure of
unfinished document-renovation capabilities.

## Verdicts (16 audit items)

| # | Item | Verdict | Evidence |
|---|---|---|---|
| 1 | Tailoring flow | PASS | `/tailor` (bullets vs target), `/tailor/extract-bullets` + `/tailor/structure` (verbatim extraction, no advice), `/tailor/renovate` + `/tailor/bullet` (staged renovation); all failure modes degrade to passthrough of the student's own words |
| 2 | Target binding | PARTIAL | `opportunity_id` required + 404 on all generating endpoints; **no target echo / generated_at / pipeline version on responses** (unlike the W12 cold-email stamps) — pairing a suggestion set to its target was entirely the client's bookkeeping. No generic-optimize mode exists |
| 3 | Resume data model | PASS | strict ID hygiene, duplicate-ID and oversize 422s |
| 4 | Fact extraction | PASS | verbatim-contiguous NFKC containment (`_bullet_grounded`); appended-tool/metric and paraphrase rejection tested incl. CJK |
| 5 | Prompt construction | PASS | student-side-only evidence corpus (TAILOR-2 — posting text deliberately excluded so the model can't assert the exact tech the posting screens for); every interpolation sanitized; anti-injection rules; EN/ZH parity. Minor: per-bullet prompt lacked the skill-level-honesty rule |
| 6 | Suggestion schema | PARTIAL | per-bullet `source_evidence` exists but was **never verified** against the corpus (a fabricated "quote" rendered as evidence); **bare-number metrics passed the lenient validator** (letter-initial tokenizer — "45%", "$2M", "2023" invisible); structure headings are AI output without grounding (label-only, bounded — accepted) |
| 7 | Lifecycle states | PASS | variant chain (base_text floor / macro / ai / user variants / current pointer / foreground-keep-demote actions); tailor-side accept-edit-reject per bullet |
| 8 | Apply/reject/edit/restore | PASS | nothing is ever auto-applied to any stored resume — output leaves via clipboard or the modal's own draft only; rollback = pure pointer move; edit appends a user variant; AI re-optimize appends only validated variants |
| 9 | Save implementation | PASS | `(device_id, opportunity_id)` UNIQUE upsert + append-only version snapshots; correct own-row RLS; account-merge covered (migration 021) |
| 10 | Save failure handling | **FAIL** | `saveRenovation` swallowed every error (null session, RLS denial, network) and the modal flashed **"Saved" unconditionally**; plan-failure warning string mismatch (`macro_plan_failed` vs `plan_` prefix) hid degradation |
| 11 | User isolation | PASS | RLS own-row on both tables; drafts under `USER_SCOPED_PREFIXES` cleared on uid change; service role limited to the usage ledger |
| 12 | Target isolation | PARTIAL | storage keyed per (device, opportunity); state reset on target change; **but** the favorites page shares one TailorModal instance across opportunities and `handleGenerate` had no in-flight guard — a slow target-A response could render under target B |
| 13 | Cache/storage | **FAIL** (staleness) | no TTL/versioning: a saved draft always beat a fresh prefill from an updated resume with no signal; a renovation doc built from a since-replaced resume restored with no staleness hint |
| 14 | MTP Renovate inventory | PASS | document round-trip (DOCX/PDF generation, template/ATS conversion, formatting transformation) **does not exist anywhere** — zero dependencies, zero routes, zero UI; intake is text-extraction only (`pdfjs-dist`); output is clipboard text |
| 15 | Exposed-but-unready features | PASS (judgment documented) | the text-level renovation flow is live and ungated — it is NOT classified as unfinished MTP Renovate: it meets the tailor-grade bar (staged grounding, variant lifecycle, 771-line test suite); its two real defects (items 10, 13) are fixed in this close-out. The unfinished document-transformation area has no code to hide; a tripwire test now prevents it shipping silently |
| 16 | Files requiring changes | — | see Phase-2 list in `docs/tailor_boundary_report.md` |

## Spec-mapping notes

- **Session context fields** (`user_id/resume_id/target_id/tailor_session_id/created_at/target_version`) map to: `auth.uid` (device-scoped, account-merged), the (device,opportunity) working-doc row, `opportunity_id`, and the new W13 response stamps (`generated_at` + `pipeline_version`); resume version = the new `resume_sig` fingerprints. The server is deliberately stateless for suggestions — no server-side session table exists or is needed.
- **User fact boundary**: "facts explicitly confirmed by the user" = the resume text/bullets/skills/coursework the user entered (the profile IS the confirmation surface); no separate confirmation flow exists, and none is added — the corpus is exactly the user-entered material.
