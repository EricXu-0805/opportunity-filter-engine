# Email activity context

Pipeline: `w12.16`. This contract binds supplied student facts; it does not verify that the work happened or authenticate the current cloud profile.

## Request and compatibility

- V1 remains `{version: 1, resume_text, entries}`. Its confirmed text remains usable without inferred activity context.
- V2 is `{version: 2, resume_text, entries, resume_master}`. `resume_master` must be the complete current validated `ResumeMasterV1`, or explicit `null`.
- The stored experience-entry format is unchanged. The frontend sends the current accepted profile and invalidates old work when that profile changes. The backend validates the supplied snapshot, not an independently loaded cloud revision.
- Activity, education and publication `details` link entries by exact `id` and `revision`. Multiple referring records produce `activity_ambiguous`; a known outdated reference produces `activity_reference_mismatch`. Those entries are excluded and require review.
- A confirmed entry without a reference remains usable with `context: null`. Removing an activity relation does not withdraw the entry's independently confirmed text. Withdrawing the entry itself still makes its text unusable.

## Bound input and receipt

V2 selected entries contain their complete original `excerpt`, source reference and:

```json
{
  "context": {
    "master_id": "current-master-id",
    "master_revision": 5,
    "section": "activities",
    "id": "activity-id",
    "kind": "project",
    "fields": {
      "title": {"id": "title-fact", "revision": 1, "status": "confirmed", "value": "Project Alpha", "source": {"kind": "manual"}}
    }
  }
}
```

`section` can also be `education` or `publications`; those omit `kind`. Each field retains its full admitted value, revision and source, including a resume quote when present. Only confirmed fields whose resume source still matches the complete submitted text/signature are included. Unconfirmed or stale fields are omitted with `activity_context_unconfirmed` and `needs_review`; they do not return through another record. The submitted master remains unchanged.

The JSON student brief pairs each selected original with its own context. The same selection reaches initial generation, streaming, refinement and selected-text refinement; judging, critique and revision receive the same brief. A category such as `research` is not evidence of a student job title.

## Attribution checks

The existing finite English action checker now checks exact admitted activity names and explicitly stated years against each entry's own record. It handles known name/date prefixes and suffixes, named headings, subsequent action clauses, and separate explicitly named activities in a sentence. The original entry's explicitly stated year can also support that entry's date. A shared name requires a disambiguating field.

For example, Alpha's “I built the parser” cannot support “At Beta Lab, I built the parser,” even when Beta is another legitimate activity in the profile. A date from Beta cannot be moved onto Alpha's contribution. A copied activity field is not broadcast as support for every entry. Explicit unknown or deleted organization names cannot be treated as unscoped claims. An independent original can itself supply its stated organization/year. Unclassified capitalized qualifiers in a bound original (such as a method or object) may be reproduced as that exact admitted clause; they do not become reusable activity aliases. Invalid AI output goes through the existing safe template/local recovery path.

This is still a bounded syntax check. Unrecognized verbs, aliases, pronouns and arbitrary paraphrases are not general semantic verification. Original text, tested scope rules, model input completeness and real writing quality remain separate claims.

## Capacity

- Existing experience admission remains 100 entries, 6,000 Unicode codepoints per entry and 60,000 total text/quote codepoints.
- The full master keeps its existing 300-record/fact/reference and 60,000-value/quote limits; invalid or oversized snapshots are rejected rather than trimmed.
- Selection still admits at most eight whole experience texts within 4,000 codepoints; template examples retain their 220-character limit. Background does not consume or enlarge that text-selection budget.
- Full selected background is never shortened. Every provider call must still fit 120,000 serialized JSON codepoints, including repeated context and escaped characters. Over-limit requests return `EMAIL_INPUT_TOO_LARGE`; streaming terminates with an error. A late-stage limit may follow earlier accepted calls.

## Evidence

The B52 synthetic fixture uses two independently confirmed activities with different contributions and dates. Captured FastAPI generation/stream/refine requests accept the correct Alpha claim and reject its reassignment to Beta. Model replies are controlled fixtures. No real model, email, cloud write, migration, deployment or corpus application is part of this verification.
