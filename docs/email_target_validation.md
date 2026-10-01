# Email draft condition checks

The source rules and receipt are defined in [email_target_conditions.md](email_target_conditions.md). This document covers the actual email consumers in pipeline `w12.19`.

- Generation, stream completion, variants, full refinement and selection refinement return the current `target_conditions` receipt with `target_version`. The email routes read the central public projection; they do not reconstruct source evidence from fields removed by projection.
- Every model stage receives the same complete target-condition receipt. Only usable source terms enter target vocabulary. They never become student experience, personal eligibility or evidence of an attached file. Recorded legacy skills and application URLs are labeled as recorded data.
- A generated unsupported condition claim is rejected. Generation can recover to a checked template. If a later revision is invalid, the pipeline can keep the earlier valid draft. Template requests use one source-supported material request or one relevant pending-field question. An empty receipt does not produce a generic eligibility checklist.
- A rejected refinement returns `outcome: no_change`, `reason: target_conditions`, and finite `condition_issues`. Full refinement preserves the existing body under the established email-address redaction rule; selection refinement returns no replacement. Unknown manual wording is not a reason to replace an entire draft. The same preservation applies when the model is unavailable or a faculty profile lacks research material. A preserved draft can still require review.

## Manual editing

`POST /api/cold-email/validate` is provider-free and does not rewrite, save or send the draft. It accepts `opportunity_id`, required `expected_target_version`, `profile`, optional confirmed `experience_evidence` and `contact_context`, and the exact `subject` and `body`. Subject and body limits are 2,000 and 5,000 UTF-16 units. Invalid Unicode and NUL characters are rejected without echoing input.

The response contains `opportunity_id`, `target_version`, `pipeline_version`, `contact_context_receipt`, required `target_conditions`, `outcome`, and `issues`. It does not return a body. `outcome` is `ready` only when these finite checks report no issues; this is not a qualification, semantic correctness or delivery guarantee.

Issues are limited to:

- `unsupported_eligibility_claim`
- `unsupported_deadline_claim`
- `unsupported_material_claim`
- `unsupported_attachment_claim`
- `empty_draft`

The manual check uses the existing current-target and contact-policy guards. It deliberately does not apply the generated-email vocabulary whitelist to arbitrary manual writing. A source's minimum GPA cannot establish a student's GPA. A confirmed positive personal GPA fact remains usable; another person's or a negated GPA statement cannot authorize it. No submitted-file contract exists, so current-email attachment claims remain unsupported.

Open/Gmail/Outlook use the current draft's validation result. The explicit draft-only copy path remains an offline backup. Neither path changes the historical meaning of an already-sent tracking record.

## Capacity and evidence limits

Model messages retain the existing 120,000 compact-JSON codepoint limit before each provider call. An oversized first prompt makes zero provider calls; a later oversized stage may follow earlier accepted calls. Pure-template variants and manual validation make no model call and do not pretend to have a model prompt limit. Their input/source contracts remain bounded independently.

B54 checks use synthetic student/target records, real local HTTP routes and controlled provider replies. Captured examples prove transport, rejection and recovery behavior. They do not measure live model writing quality, verify real personal qualifications, backfill source evidence or prove email delivery.
