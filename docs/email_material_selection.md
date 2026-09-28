# Email material selection

Current pipeline: `w12.15`.

## Experience selection

All public email routes use the same selection function, including initial generation, variants, streaming, whole-body refinement, and selected-text refinement.

- An experience must be explicitly confirmed. Resume-derived entries must still match the current resume signature and quoted range.
- Ranking uses target-side lexical overlap: admitted legacy research fields/requirements, plus the titles and available abstracts from a validated current research snapshot and complete headings/text from a validated current official website snapshot.
- Stale, invalid, unavailable or revoked sources do not supply the new snapshot terms. An explicit public context is authoritative; rejected public data cannot fall back to a retained private snapshot.
- Snapshot dates, source URLs, link captions, identity cards and department labels are not added as topical evidence. Student interests and student skills never become target-side ranking terms.
- Ties preserve source-entry order. Select at most eight whole entries within 4,000 Unicode codepoints. Skip an entry that does not fit; never cut its qualifying sentence. Selection omissions remain visible in the existing experience receipt.
- Templates may quote one whole selected example of at most 220 characters with at least two overlapping target terms. This separate limit remains unchanged.

This is a lexical priority, not a semantic matching score or proof that an experience transfers to a lab. English word splitting and simple suffix matching remain limited. A title or website publication list does not establish a paper's methods; target research does not establish student competence or completed reading.

## AI student input

The student brief now encodes each field as JSON data. It preserves all admitted skill names and claimable levels, all coursework that passes the existing course validator, the full admitted interest text, name/year/major/school, profile links, and the whole selected experience entries. It does not add a second prefix limit or flatten multiline experience qualifiers. Rank wording changes apply to instructions and labels, not quoted student facts, source research fields or complete research/lab snapshots.

Unconfirmed imported skills retain the existing conservative claimable level. Student interests remain aspirations. Contact history, availability and paper-reading attestations remain separately validated. Editing instructions and previous drafts remain editing inputs, not new facts.

Before every provider call, the serialized complete messages must fit 120,000 Unicode codepoints. Oversized requests return `EMAIL_INPUT_TOO_LARGE`, without truncation or a successful template response. Streaming terminates with an error event. This is a per-call limit: a later judging, critique or revision rejection can follow earlier successful draft calls. It is not a token estimate.

## Boundaries still open

- The existing `ProfileRequest` limits and transformations are unchanged. Examples: at most 50 skills/courses, 50-character skill names, 100-character course entries, 2,000-character interests and 100-character name/year/major. This change preserves fields after that admission; it does not claim arbitrary-length source ingestion.
- The template keeps its existing shorter presentation. Full AI input does not mean the final email should repeat every fact.
- A confirmed supplement reaches email as an experience entry; its activity title, organization and dates remain in the resume master and are not yet carried as bound email context.
- Deterministic checks and captured test inputs do not establish live-model writing quality, broad semantic entailment, delivery, or production readiness. Human review should separately assess facts, specificity, naturalness and the clarity of the request.
