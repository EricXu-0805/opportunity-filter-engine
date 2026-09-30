# Email application conditions

B54 adds one source assessment shared by public opportunity detail, email generation/refinement, manual-draft checks, and the email UI. Conditions describe the opportunity. They do not establish that the student is eligible, prepared documents, attached files, or submitted an application.

## What counts as evidence

`build_target_conditions(record)` reads the canonical stored record. It ignores cached `target_conditions`. Only `metadata.contact_instruction_sources` can supply a stated condition: the record URL must still match, a faculty source must still match the professor name, and the source must carry a valid timezone-aware check time. The source must be no more than 60 days old and not future dated. This 60-day window is a product freshness rule, not proof that the page has not changed since the check.

The finite parser checks retained headings and complete paragraphs. It supports clear English minimum-GPA, class-year, required/preferred-skill, eligible-major, citizenship, international-applicant, deadline, rolling-application, and material forms. Mixed graduate/undergraduate audiences, conditions, alternatives that cannot be represented safely, optional wording, unsupported language, and dates without a year remain available for review. It never supplies a missing year, time, or timezone. A heading `Minimum GPA` plus body `3.0` is supported; the heading and body remain separate source strings.

Citizenship alternatives such as “US citizens or permanent residents” retain the complete restriction expression; they are not collapsed into a citizens-only boolean. Conflicting normalized values and retained source values remain conflicts. Existing field conflict records also prevent a stated result. No manual-review flag, high confidence score, current corpus date, profile/lab identity evidence, or lack of an inference stamp can promote a legacy value.

The existing collectors were not backfilled. A read-only B54 audit of the local stored corpus found 140,454 records and zero retained `contact_instruction_sources`; therefore the current corpus's existing values remain unverified/inferred/policy, not newly source-verified. Controlled source fixtures test the stated path. Future successful collector reads can retain the additional relevant sections. The loader still removes legacy `eligibility_text_raw`, which may contain a short description rather than original eligibility text; this batch does not claim that legacy field reaches live writing requests.

## Public receipt

`target_conditions` is recomputed from canonical evidence in public projection and included in `writing_target_version`. Email responses use that same public receipt with their outer `target_version`. The public projector applies existing URL/contact privacy. If a condition's value, heading, quote, or source URL is changed by that projection, that condition becomes `unknown / excluded / source_not_public` with null value and no sources. Its modified quote is not signed as original evidence. Other unchanged conditions remain separate.

```json
{
  "version": 1,
  "record_kind": "listing",
  "conditions": [{
    "field": "eligibility.min_gpa",
    "category": "eligibility",
    "status": "stated",
    "value": 3.0,
    "usage": "usable",
    "reason": "source_stated",
    "sources": [{
      "heading": "Undergraduate applicants > Minimum GPA",
      "quote": "3.0",
      "source_url": "https://example.edu/program",
      "checked_at": "2026-09-28T12:00:00+00:00"
    }]
  }],
  "template_request": null
}
```

- `record_kind`: `listing`, `faculty_contact`, `unverified`.
- `category`: `eligibility`, `deadline`, `materials`.
- `status`: `stated`, `inferred`, `policy`, `unverified`, `unknown`, `stale`, `conflicting`.
- `usage`: `usable` only for `stated`; `ask_only` for conditions that need checking; `excluded` for overflow or source text that cannot be publicly represented.
- `value`: string, finite number, boolean, string array, or null. False and zero are not missing values. An unknown value does not mean “no requirement.”
- `reason`: `source_stated`, `inferred_field`, `program_policy`, `unverified_legacy_value`, `no_source_evidence`, `source_stale`, `source_conflict`, `normalized_source_conflict`, `source_binding_mismatch`, `source_unavailable`, `unsupported_source_wording`, `source_overflow`, `source_not_public`.
- Source `heading` is optional; `quote`, `source_url`, and timezone-aware `checked_at` are required. Quotes remain complete paragraphs. The receipt does not expose internal inference methods or raw metadata.

Field whitelist: `eligibility.preferred_year`, `eligibility.min_gpa`, `eligibility.majors`, `eligibility.skills_required`, `eligibility.skills_preferred`, `eligibility.citizenship_required`, `eligibility.international_friendly`, `eligibility.work_auth_notes`, `eligibility.eligibility_text_raw`, `deadline`, `is_rolling`, `application.requires_resume`, `application.requires_cover_letter`, `application.requires_transcript`, `application.requires_recommendation`.

The receipt has at most 15 fields, each at most once, and 40 source quotes per field. Quote/heading/URL/check-time limits are 4,000/1,000/2,000/80 Unicode codepoints. A value string is at most 20,000 codepoints; an array has at most 512 strings of at most 1,000 each. An oversized field is excluded explicitly, never clipped into usable evidence. The template request is at most 500 codepoints. Full serialized model input retains the separate 120,000-character prompt limit; this receipt does not bypass it.

Faculty contacts do not receive a checklist generated from directory defaults. Only relevant, identity-bound retained source paragraphs can produce a faculty condition; the generic template helper always returns null for faculty contacts. A listing with no conditions also gets no invented checklist.

## Consumer functions

- `build_target_conditions(record, *, now=None)`: canonical raw evidence to receipt; no network or mutation.
- `validate_public_target_conditions(value)`: detached shape-checked receipt, or null. This checks structure, not source authenticity.
- `email_target_conditions(projected_opportunity)`: use the public receipt when present. A malformed present receipt fails closed without recovering authority from raw legacy values. Only internal callers without a public receipt use the builder.
- `target_conditions_brief(context)`: full receipt with an explicit target-versus-student role boundary.
- `target_conditions_vocabulary(context)`: only usable source/value text.
- `target_conditions_template_request(context)`: derive at most one practical request from current conditions. Stated materials support a preparation/submission question. Otherwise a known pending field determines one specific clarification. Cached template text is never trusted after a condition changes.
- `target_condition_claim_violations(text, context, student_evidence_texts=())`: the finite deterministic claim check described below.

The getter is for internally produced public projections. Accepting an arbitrary request object's receipt through its shape validator does not authenticate it; routes must resolve the current canonical target first.

## Output check and limits

The output check returns a subset of `unsupported_eligibility_claim`, `unsupported_deadline_claim`, `unsupported_material_claim`, `unsupported_attachment_claim`. It checks specific English and Chinese claim forms. It rejects blanket claims of satisfying eligibility, unconfirmed personal citizenship/GPA, target GPA/deadline/material claims without usable evidence, preferred skills promoted to required skills, invented deadline time/timezone, and invented document type/count qualifiers. A positive student GPA or citizenship claim needs positive personal evidence; a negated statement or another program's/another person's numbers do not establish it. Existing email fact/attribution checks remain in place.

Questions, preparation offers, and confirmed personal facts remain possible. “I meet with my mentor,” “I submitted a paper to the workshop,” and “I attached a sensor” are not application-eligibility or email-attachment assertions. This boundary does not create an attachment-confirmation schema; current-email document attachment/submission assertions remain unsupported.

These are bounded language rules, not a general semantic validator. A result without findings does not prove arbitrary wording correct. Unsupported languages and complex conditions need source review; target terms never authorize rewriting the student's own facts. A stored source can be stale or revoked, and changing/removing it changes the public receipt and target version. No live webpage fetch, real model, email send, production data write, or historical corpus backfill is part of this batch's tests.
