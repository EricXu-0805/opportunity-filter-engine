# Résumé writing quality: local evidence contract (w14.0)

Scope: `/api/tailor`, `/api/tailor/renovate`, and `/api/tailor/bullet`. This supplements the historical `tailor_boundary_report.md`; that report describes an earlier implementation, not the current storage/export system.

## w14.0: evidence-mapped rewrites

`backend/lib/evidence_map.py` holds the contract these routes and full-target v6 share.

- The server cuts numbered anchors from the target: the description (a faculty directory template only through its source-stated `metadata.research_areas_raw`), requirements unless inferred, and recent-works titles that pass the publication trust gate. URLs, e-mail addresses and posting boilerplate are cut out. A target with no quotable text gets no model call; every bullet comes back kept with `target_has_no_text`.
- One generation call per request, ending at most 40 s into it. The model links phrases of each bullet to anchor words and declares its moves: `lead_with`, `relabel` (a "same" link only), `verb_first`, `personal_first`, `tighten`, or `translate` when the bullet is not in the UI locale's language. Broader and cross-language relabels and trimming are not offered (calibration, 2026-09-30).
- A rewrite may add only words of its own evidence plus a declared relabel's term; it passes the relabel-term filters, the claim locks (actor, qualifier, intent, status, setting, quantity, denial, team, publication) and one fail-closed faithfulness review that also judges each used link. Only an accepted rewrite is shown; every other bullet comes back as written with its reason (`no_link`, `already_aligned`, `no_safe_change`, `cosmetic_only`, `beyond_allowed_edit`, `rewrite_rejected`, `review_rejected`, `review_unavailable`, `model_unavailable`).
- A relabel renames only what its link's source names: its "from" lies inside that source, and the swap may not lose a number, a qualifier, a status, another person's part or a personal marker. No move adds "I", "my", 本人 or 我. Each publication status, shared credit ("with two teammates", 与组员一起) and since/until stays on its own work or action.
- A translation is checked in both directions for numbers (month names count), names, every qualifier family, and any setting, quality or relevance claim the other line lacks; the claim locks compare those three only within one language.
- The selection plan's compress rewrites have no review behind them, so their gate keeps the source-checks-v3 reading of actions: team credit never hides a new action there.
- The student's profile, confirmed skills and interests stay in the prompt as direction, never evidence. After "Use kept as new originals", `source_bullets` carries each line's evidence so reviewed wording never becomes evidence; the saved draft keeps those sources across a reload.

The sections below describe the w13.5 evidence rules; where they differ from the list above (rejection behaviour, `source_evidence`), the list above applies.

## What changed

The old vocabulary check pooled a student's profile and all submitted bullets. It could accept project A's technology or number in project B, and accept “I led” when the original said “I did not lead.” Controlled provider-free HTTP tests reproduced both errors in the real routes.

Each rewrite now uses the corresponding original bullet as its evidence:

- `/tailor`: the source selected by the existing `source_index` association.
- `/tailor/renovate`: that foregrounded bullet's `base_text`; another bullet or a profile skill is not evidence of work on this project.
- `/tailor/bullet`: `base_text` when provided. The editable `current_text` is sent separately to guide phrasing, not to establish additional facts. Older callers that omit the base provide their current bullet as the only source; this is caller-supplied evidence, not independent verification.

`source_evidence` is checked against the same local original. An unrelated or fabricated quote is removed instead of displayed as proof. The known concrete-term/number validator and the same conservative EN/ZH claim locks used by full-target AI apply to these three routes. Missing detail is not filled from the student's skill list, another project or the opportunity's vocabulary.

On rejection, `/tailor` keeps its existing original fallback/partial-suggestion behavior; Renovate leaves the original bullet and its rollback floor intact; single-bullet optimization returns the user's `current_text` unchanged with `changed=false` and a warning. A rejected suggestion does not replace manual edits with the base text. Saving and confirmation flows are unchanged.

## Target relevance and missing information

Single-bullet optimization now receives the detached public target's professor name, organization and description excerpt. The description uses the existing 1,200-character budget and whitespace sanitization; When the clean field is absent, the already-public `description_raw` is allowed as a fallback; no unprojected collector record or contact-reveal payload is read here. The prompt separates target relevance from student evidence and treats these fields as data, not instructions. Existing output/token/time/provider-call budgets are unchanged.

The model should emphasize a supported action, method or result relevant to the public research description. A general skill does not establish its use on this project. When a source lacks personal role, method or a supported outcome, preserve the stated contribution; students can supply and confirm facts through the existing full-résumé supplement flow. This change does not add an automatic question generator or a professor-paper retrieval system.

## Evidence and limits

`tests/test_resume_writing_quality.py` supplies controlled model outputs through the real HTTP handlers. It checks cross-project technology/number leakage; profile-only skill transfer; English and Chinese negation/team/publication upgrades; truthful reordering; local quotations; retained manual wording; and bounded public research context. Existing parser/index/localization positive fixtures now contain the actual actions their generated examples claim. Their positive assertions remain; the old vague source-to-stronger-action pairs are retained as negative cases.

These are bounded regression checks, not semantic entailment. Exact sensitive-clause preservation can reject a valid paraphrase or translation; unlisted action synonyms, generic claims and a mismatched relationship between already-present numbers can still escape token checks. Keeping the original available is safer than silently asserting a stronger contribution. The full-target pipeline already has independent confirmed-entry evidence and uses the same claim locks. The shared helper now separates explicit English/Chinese contrast clauses, so a negative first clause cannot exempt a new affirmative responsibility/publication claim after “but” or “但”. This fix also applies to full-target suggestions and is covered by their existing regressions plus the new paired receipt cases.

No real model output or human résumé review was evaluated here. Naturalness, useful professor/lab alignment, bilingual rewrite quality and follow-up question quality still require fixed real samples with human judgments. Passing these tests does not complete M36/M38–M40 or prove that generated résumés are ready to send.
