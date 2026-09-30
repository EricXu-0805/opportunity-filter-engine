# Email target input

Pipeline: `w12.17`.

## Complete admitted fields

Initial generation, streaming, whole-email refinement and selected-text refinement use the same target brief. Drafting, judging, critique and revision receive that brief unchanged.

The brief carries complete admitted titles, lab/program, organization, department, academic rank, recorded research areas, source/legacy keywords, declared requirements, description, application method/URL, and all admitted publication titles/years. Values are JSON data; line breaks, qualifiers, negations and Unicode are retained. The recipient compatibility line only folds whitespace and does not cut the name.

The previous limits discarded requirements after the fifth item, required-skill text after 200 characters, descriptions/research areas after 600 characters, long identity/application fields, and legacy paper titles after 200 characters. The prompt now contains the full stored fields. This does not recover text that a collector never stored, and it does not establish that each stored record is fresh or correct.

A shorter derived topic and a lab-style classification remain writing aids. They do not replace the full source input. Templates still select a few skills/courses and at most one suitable short paper title; email subjects remain bounded. Those output choices are separate from admission of facts. Template names and profile links are not prefix-clipped by the renderer. Whole confirmed student experiences keep their existing count and character budgets.

## Source boundaries

- The current public writing-target snapshot is authoritative. Contact redaction, safe URLs, source freshness, contact restrictions and target-version checks remain in place. The public contact-scan boundary can redact a field longer than 20,000 characters; this work does not bypass that privacy rule.
- Faculty display summaries are generated product text, so they remain excluded from research evidence. A faculty contact profile does not establish an opening.
- Keywords stamped as inferred remain excluded. Required-skill lists marked `skills_attribution: inferred` or carrying an `eligibility.skills_required` inference stamp do not become email requirements, matching-skill evidence or grounding vocabulary. The underlying description remains available: a mention may support topical relevance, but is not a requirement unless its wording explicitly says so.
- Unstamped legacy values keep the existing admission policy. No page was newly inspected to verify their provenance.
- Paper titles use the existing attribution/current-source gate. Missing, stale, invalid or revoked new snapshots cannot regain authority through a retained raw cache. Lab/research snapshots keep their existing complete, bounded source blocks.
- The shared publication helper returns an empty string when no works are admitted, so other consumers can omit the publication section. Email renders an explicit empty JSON array in its fact sheet.

## Capacity and recovery

Before each model call, the complete messages are serialized with `ensure_ascii=False` and compact separators. The limit remains **120,000 Unicode codepoints**, including JSON escaping, instructions, prior drafts and the edit request. No target field is shortened to make it fit.

An oversized first prompt returns HTTP 413 with `EMAIL_INPUT_TOO_LARGE` before any provider call. Streaming emits a terminal error with the same code and status and does not emit `done`. The failure is not replaced by a successful template or a compatibility retry. A later judge/critique/revision prompt can exceed the same limit after earlier accepted calls; the limit applies separately to each call.

Template-only generation and variants do not call a model and are not subject to a fabricated model-input limit. Profile admission has its own explicit limits and safe 422 errors; see [Profile input contract](profile_input_contract.md). These are separate from the combined email-prompt limit. Non-profile schema errors also use a shared safe response: error type, top-level request location and a fixed message. Private values and unknown object keys are not reflected; `student_name_required` and the dedicated edit-length error remain recognizable.

## Verification limits

Tests use controlled provider results and one unchanged local corpus record. They establish input preservation, source exclusions, deterministic grounding and recovery behavior. They do not establish real-model writing quality, semantic entailment in arbitrary prose, email delivery or deployment readiness. Structured preferred skills, preferred years, citizenship/work-authorization conditions, raw eligibility text, deadlines and additional application-material flags were not included by the old email brief and remain a separate M31 task. Many carry inference markers. They need a per-field provenance and output-claim policy before they can be admitted as qualifications; this batch does not claim complete opportunity-condition coverage.

Other product prompts have separate contracts; this document does not claim all application consumers now receive complete target fields.
