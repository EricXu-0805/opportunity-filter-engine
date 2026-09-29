# Opportunity skill and major labels

B57 separates three kinds of skill labels. These labels are rules inferred from retained text; they do not prove that a live source was checked or that a student qualifies.

- **Required:** local text explicitly states a requirement, such as `Python is required`.
- **Preferred:** local text explicitly states a preference, such as `SQL is preferred`.
- **Mentioned:** affirmative technical use or mention without an individual unconditional requirement, such as `We use MATLAB`.
- A requirement or preference must modify the skill phrase. `We use Python and require a CV` and `The Python tutorial is required` keep Python only as a mention; the material/course requirement does not transfer to the skill.
- A negated skill does not become a positive mention. Conflicting required/preferred assertions are omitted. `Python is not required but preferred` retains only the explicit preference.
- An alternative or conditional requirement (`Python or R`, `or equivalent`, `unless`, `if`, `when`) is kept as a mention. The current schema cannot represent requirement groups, so neither alternative is represented as individually mandatory.

## Shared functions

`src.opportunity_terms.extract_skill_mentions(text)` returns lexical technical mentions in first-occurrence order. This function is diagnostic: it can detect a technical term inside a negative sentence.

`extract_skill_requirements(text)` returns disjoint `required`, `preferred`, and `mentioned` arrays. Only these classified arrays may become positive opportunity signals. Both functions are deterministic, use no model or network, and do not truncate source text.

Token boundaries distinguish Java from JavaScript and C from C++/C#. R/C/Go/React and other ambiguous terms require local technical context, a technical list, or applicable explicit qualification wording. Initials, URLs, email addresses and known local nontechnical meanings do not supply skills. `Research using R programming` remains a valid R mention; there is no paragraph-wide “Research” blocklist.

## Normalization and provenance

The normalizer classifies the source title, full `description_raw`, and `eligibility_text`. A title explicitly stamped as model-inferred is retained for presentation with its stamp but is excluded from skill, major, keyword and opportunity-type extraction. Model skill suggestions are not input evidence for this classifier.

- Rule-derived required/preferred skills and majors receive the `rule:opportunity_terms` stamp at their `eligibility.*` paths.
- Bare positive mentions are stored at `metadata.skill_mentions`; that exact path also receives `rule:opportunity_terms`.
- Source keyword extraction receives `keywords: rule:normalizer`.
- Ambiguous major acronyms such as IS/CS/STAT must occupy a bounded education phrase (`IS students`, `majoring in CS and ECE`). Ordinary `is` and `This IS a notice for students` produce no IS major.
- Full field names remain inferred relevance labels, not verified admission restrictions.
- `description_raw` and the independent contact-source ledger are preserved. The existing 1500-character `description_clean` summary is unchanged and is not the classifier's source.

## Limits

These are finite English lexical rules, not general semantic extraction. They do not establish admissions eligibility, verify individual pages, infer proficiency, or prove writing quality. Unrecognized syntax can under-classify a genuine condition. Conditional/alternative groups lose their detailed logical structure in the positive mention label; the full original sentence remains available for review. A source term can describe a project rather than a student's required ability, so all derived labels retain inference provenance.

The existing major and keyword vocabulary is still a finite relevance vocabulary. Acronym extraction is deliberately conservative and preserves case. No real corpus was rewritten in B57; historical unstamped labels require a separate reviewed migration. Matching and public presentation must respect provenance rather than treating missing stamps as newly verified source evidence.
