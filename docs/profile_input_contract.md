# Complete profile input

Profile requests preserve all admitted fields. They do not take the first 50 skills or courses, clip interest text, shorten URLs, or mutate the caller's skill dictionaries. Missing legacy fields retain their existing defaults. The browser keeps the original profile when validation rejects a request.

## Limits

All text limits count Unicode codepoints. A paired emoji counts as one character. Unpaired UTF-16 surrogate values are invalid.

| Field | Maximum |
| --- | --- |
| Research interests | 60,000 characters |
| Skills | 512 items; 1,000 characters each for name and level |
| Coursework and additional majors | 512 items each; 1,000 characters per item |
| Desired fields derived from interests | 512 items; 60,000 characters per item |
| Name | 256 characters |
| School, major, college | 1,000 characters each |
| Year and experience level | 100 characters each |
| Home-school slug | 50 input characters; existing trim/lower/default behavior |
| LinkedIn, GitHub, Scholar URLs | 2,048 characters each |
| Opportunity types | 20 items; 100 characters each |
| Whole normalized profile | 160,000 characters in compact JSON, including escaped characters and model defaults |

Field and whole-profile limits both apply. The aggregate limit includes JSON overhead; multiple fields cannot all independently consume their maximum. The larger total allows a 60,000-character interest and the same complete text in derived desired fields. It does not promise every combination fits.

Skill provenance is unchanged: an absent source remains a student-entered skill; recognized imported sources remain imports; any other source becomes `unknown`. Only boolean `true` confirms the level. Nothing is promoted merely because its name arrived in the profile.

## API errors

An over-limit profile returns HTTP 422 with `detail.code = PROFILE_INPUT_LIMIT_EXCEEDED`, a schema-owned `field`, numeric `actual` and `limit`, `unit` (`characters` or `items`), and `retryable: false`. Invalid profile shape returns `PROFILE_INPUT_INVALID`. Responses do not include submitted content or Pydantic input/context dumps. The shared handler covers normal routes and the cold-email route's dedicated validation wrapper. The existing missing-student-name error remains separate.

These are input-admission limits, not model-token estimates. Complete composed LLM requests have a separate 120,000-character compact-JSON budget. Over-budget writing/chat/match requests are refused before their provider call. For AI reranking, every batch is checked before any batch can call a provider. Rule-only matching does not invoke or inherit the AI prompt limit.

## Consumer paths

- Matching: `ProfileRequest → _normalized_profile → rank_all/rank_visible_universe`; full interests and complete skill/course lists reach scoring. Gap analysis receives the same full model dump. AI reranking's student query retains complete interests, skill names, primary major and additional majors. It is a topic-fit query, not a full resume.
- Match explanation: complete year, major and interest text reach the explanation prompt. This endpoint deliberately summarizes existing match signals; it is not a full-profile writing tool. `MATCH_EXPLANATION_INPUT_TOO_LARGE` and `MATCH_RERANK_INPUT_TOO_LARGE` return HTTP 413 when their complete messages exceed 120,000 characters.
- Cold email: all five profile-bearing routes use the shared schema and safe validation helper. The student brief uses complete admitted profile fields. Email generation has its own prompt budget and verified-experience requirements.
- Legacy tailor and renovation's selected-bullet rewrite share `_ai_tailor_bullets`: full admitted student skill/course/interest content replaces the old first-20/first-15/shortened-interest projections. Single-bullet optimization uses the same profile admission schema, but its writing facts remain the corresponding original bullet; it does not send every profile field to its prompt. Existing structure/macro target summaries and original-bullet limits remain separate. Complete selected-rewrite prompts have their own budget.
- Ask AI: the optional profile goes through this schema; the interest field is no longer shortened to 300 characters. The complete system prompt, history and question are budgeted together, including before streaming begins.
- Roadmap: the shared schema precedes the existing deterministic skill-gap consumer.

## Storage and remaining scope

The existing profile JSON storage and ordinary profile form had no equivalent complete-input budget. This API contract does not rewrite saved profiles, apply a database migration, or delete old values. Shared-profile imports use the frontend admission checks and reject the whole invalid import rather than replacing it with a shortened version.

The optional AI match pass still uses explicitly shortened target summaries and at most two verified publication titles. The explanation still uses selected existing match signals. B53 changes student-input preservation and prompt admission; it does not establish full-target research coverage or semantic matching accuracy. The feature flags for AI refinement and Ask AI remain closed in the accepted release. Their tests explicitly enable those dormant routes.

Tests use synthetic opportunities and provider stubs. They do not establish live-model writing quality, production deployment, or hosted profile-storage migration.
