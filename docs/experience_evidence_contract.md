# Confirmed experience input for Cold Email

Updated 2026-09-24. Email pipeline `w12.5`. This is the bounded confirmed-
experience consumer for M12/M17, not completion of the full M37 resume library
or the Match, Tailor and Renovate integrations.

## Input and confirmation

All four public email paths (`/cold-email`, `/cold-email/stream`,
`/cold-email/variants`, `/cold-email/refine`) accept this top-level field. It is
not part of the shared `ProfileRequest`:

```json
{
  "experience_evidence": {
    "version": 1,
    "resume_text": "the exact current extracted resume text",
    "entries": [
      {
        "id": "stable-entry-id",
        "revision": 1,
        "status": "confirmed",
        "text": "Built a parser for a student research project.",
        "source": { "kind": "manual" }
      }
    ]
  }
}
```

A resume source instead contains `kind: "resume"`, `signature`, `quote`,
`start`, and `end`. Signature is the 64-character lowercase SHA-256 of the
complete exact `resume_text` encoded as UTF-8. Offsets count Unicode codepoints,
not JavaScript UTF-16 units; the original quote occupies `[start:end]`.
Whitespace and normalization changes invalidate the signature. Browser callers
must hash the source, not a generated summary. This binds a source version; it
is not an identity token or proof of the student's real-world contribution.

- Up to 100 entries; IDs are nonblank and at most 80 codepoints, unique in the
  collection. Revisions are positive safe integers. Status is `candidate`,
  `confirmed`, `rejected`, or `withdrawn`.
- Entry text and each source quote are nonblank and at most 6,000 codepoints.
  Total entry text and total quotes each have a 60,000-codepoint bound; current
  resume text independently has that same bound. Nothing is silently clipped.
- Malformed shapes, counts, duplicate IDs, invalid Unicode and invalid offset
  shapes return 422 with only `loc/msg/type`; errors never echo raw inputs or
  validation context containing resume data.
  A structurally valid historical source whose signature or quote no longer
  matches is excluded and reported for review, rather than being relabelled as
  a current source. Removed sources therefore cannot support generation.
- Only `confirmed` manual entries and `confirmed` current resume entries are
  eligible. Candidate/declined/withdrawn text is excluded from both provider
  context and the full deterministic fact corpus.
- The student can correct entry text and explicitly confirm it. The original
  quote remains unchanged as provenance; the corrected text is the student's
  attestation, not a claim to be a verbatim extraction. Changing a draft or edit
  instruction does not itself confirm new facts or permit attachment/reading
  claims. Skill-level confirmation is a separate contract.
- Legacy `resume_bullets` remains parseable within its old wire bound, but never
  supplies experience facts. Nonempty legacy input emits the notice
  `legacy_resume_bullets_unconfirmed`; the request can still generate from
  existing skills/coursework. Missing or explicitly empty structured evidence
  is never filled from raw strings. The server adds no extraction provider call.

## Selection, budget and receipt

The server ranks the whole eligible collection using the existing target-only
English word/stem overlap and stable source-order ties. It then packs complete
entries into the existing 4,000-codepoint total AI context budget, with at most
eight entries. An entry that does not fit is skipped whole; later entries that
fit remain eligible. No sentence, prefix or tail window is extracted, because
that can remove negation or another factual qualifier. A relevant thirteenth
entry can enter ahead of earlier irrelevant entries. Presentation whitespace
is flattened when constructing the prompt, as before.

The whole eligible text remains in the deterministic fact corpus. A valid
4,001–6,000-codepoint entry stays in the library but cannot enter this bounded
AI context: `experience_prompt_budget_omission` explicitly reports budget
omissions. The student can create and confirm a shorter complete entry; this
package does not yet connect every permitted long entry to the model. Neither
provider-call counts nor the total experience prompt budget are increased.
This does not solve cross-project number reuse or semantic entailment.

Templates quote at most one complete entry of at most 220 codepoints, subject
to the existing minimum two matching words. Larger entries are not excerpted;
`experience_template_budget_omission` reports that limitation on each variant
and template/fallback receipt. The final output gate still applies. A fallback
to an identity-neutral inquiry reports no selected evidence.

All responses, including the streaming `done` event and refinement, include:

```json
{
  "experience_usage": {
    "version": 1,
    "eligible_count": 1,
    "selected": [
      {
        "id": "stable-entry-id",
        "revision": 1,
        "excerpt": "Built a parser for a student research project.",
        "source": { "kind": "manual" }
      }
    ],
    "excluded": [],
    "needs_review": false,
    "notices": []
  }
}
```

A resume receipt source contains only `kind/signature/start/end`, not the full
quote or raw resume. Exclusion reasons are `candidate`, `rejected`, `withdrawn`,
`source_signature_mismatch`, and `source_quote_mismatch`. Candidate or stale
source entries trigger `needs_review`; previously rejected/withdrawn entries
alone do not invite automatic reconfirmation. Legacy unconfirmed strings also
trigger review with their explicit notice.

For successful AI output, `selected` records the context supplied, not a
sentence-by-sentence citation map. Its legacy field name `excerpt` now contains
the complete selected entry text. A final template records only its actually
quoted complete example. Local refinement recognizes complete confirmed entries
in the actual body supplied to the deterministic edit, including entries other
than the template's preferred example; whitespace differences are normalized.
Arbitrary paraphrases are not presented as citations. If an invalid draft is
replaced with a template, the receipt describes the final template instead.

Receipts retain a maximum of eight entries and 4,000 total text codepoints.
Local input can contain more matching facts; `experience_usage_receipt_limit`
then means only part of its supplied evidence is listed, not that the remainder
was unused. Variants each carry their own receipt; the top-level receipt
contains their union (currently at most one example). Frontends must display
the selected variant's receipt and bind cached drafts to the current
profile/evidence revision and pipeline version.

The current request schema is user attestation. The backend does not read a
cloud profile or establish source ownership from a client-supplied digest.
Existing identity isolation, CAS persistence and browser stale-request guards
remain required; a digest must never be used to authorize a private write.

## Bounded verification

`tests/test_experience_evidence.py` covers strict shape/budget validation,
Unicode source ranges, unchanged original text, changed/revoked/declined
sources, explicit legacy exclusion, late relevant entries, full fact corpus,
initial/stream/variants/refinement receipts and final recovery behavior.
Providers are disabled or replaced by local stubs. Existing email selection,
claim and fact-contract fixtures explicitly confirm their positive evidence;
negative assertions and skill-level rules remain unchanged.
