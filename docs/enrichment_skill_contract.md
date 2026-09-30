# Derived majors and skills after normalization

The normalizer, post-normalization enricher and tagger use the same skill classifier. Repeating enrichment or running the real refresh postprocessing step must not promote a technical mention into an applicant requirement.

## Stored meaning

For values newly produced by this batch:

- `eligibility.skills_required`: skills explicitly required in the record's source prose.
- `eligibility.skills_preferred`: skills explicitly preferred in that prose.
- `metadata.skill_mentions`: positive technical mentions without a supported required/preferred qualifier. The field carries `metadata.inferred_fields["metadata.skill_mentions"] = "rule:opportunity_terms"`. It is a weak topic signal, not a missing-skill list or proof that the applicant must know it.
- A domain such as machine learning does not invent Python or PyTorch. Negated or conflicting statements are not added as positive mentions.

This is a finite vocabulary and local language classifier. Its output is derived, not a general semantic guarantee or independently verified source requirement. Original text is retained for review.

## Writers

`enrich_opportunity` uses the title and every available unique `description_raw`, `description_clean`, `description` and `eligibility.eligibility_text_raw` value. It keeps case and HTML paragraph/list boundaries. A title explicitly marked as inferred, including a model-generated URL-import title, is excluded from skill, major and keyword evidence. URL paths, inferred keywords, departments and organization names do not establish skill requirements.

The enricher fills each empty required/preferred array separately, respecting the qualifier rather than array order. It leaves nonempty upstream arrays unchanged. It also marks newly inferred majors and keywords with `rule:enricher`; their presence is not a source-stated major restriction. Existing upstream major/keyword values keep their provenance.

`rule_based_tag` uses the same classifier instead of a domain-to-tools map or a first-two-skills split. `apply_updates` rechecks skill proposals against current source prose, including cached and model-produced proposals. An unsupported model value cannot bypass this check. The LLM batch result's skill fields are replaced by this deterministic classification before application; other tagger fields retain their existing behavior.

Owned derived mentions can be recomputed or cleared when the text changes. Nonempty upstream/manual mentions without this derivation stamp are preserved. This change does not bulk-rewrite old skill arrays whose origin is unknown.

Faculty contacts remain excluded from this opening-field enrichment path. Research prose alone must not create application requirements for a professor.

## Validation and limits

Offline tests cover bare mentions, required/preferred ordering, explicit R programming beside Research/Review, initials and R&D, fallback description storage, negative statements, provenance, forced cached/model proposals, repeated normalize→enrich→tagger roundtrips, and the actual refresh postprocess using a temporary corpus. Model responses are simulated and external networking is blocked.

No live model, real corpus backfill, deployment, or manual correction of legacy inferred requirements is part of this change. Existing LLM input excerpts and non-skill heuristics are separate boundaries; source-bounded skill classification reads complete available source fields locally.
