# Feedback Learning

How thumbs votes (`match_feedback`, migration 012) feed back into ranking quality — offline first, never auto-applied.

## v1 — offline evaluation loop (this PR)

- `GET /api/admin/feedback` returns an `analysis` block once ≥ 50 votes exist: up-rate by bucket, by final_score band, by school, and by list position (captured via `context.position`, migration 018). Keyword-overlap is not captured per vote, and the block says so rather than inventing it.
- `src/matcher/feedback_learning.replay_weights` evaluates ±20% ELIG/READINESS/UPSIDE perturbations against thumb agreement (pairwise up-vs-down concordance). Because 012 stores only `verdict/bucket/final_score` — no per-vote component scores — the replay **degrades honestly** to score-vs-verdict agreement on the stored `final_score` and reports why. It is a pure function and never writes weights.
- Daily feedback digest email appends the one-line analysis summary when available.

## v2 — weight suggestions (unlock at ≥ 300 votes)

- Start persisting per-vote component scores (`eligibility_score/readiness_score/upside_score`) in `context` so `replay_weights` can actually re-rank.
- Report the best candidate + delta in the admin dashboard as a *suggestion* with sample size and a holdout split (train on older votes, verify on newest 30%). A human applies any change via the existing `OFE_W_*` env knobs.

## v3 — bandit / interleaving sketch

- **Interleaving** (team-draft) between current weights and one candidate: serve a mixed list, credit whichever variant contributed the card that got the up-vote/click. Far more sample-efficient than A/B at our volume.
- **Position-bias correction**: votes concentrate on top cards; use the captured `context.position` to fit a propensity curve and inverse-propensity-weight agreement metrics before trusting any comparison.
- Candidate generation stays the ±20% grid (or coordinate descent on the replay objective); at most one live candidate at a time.

## Guardrails

- Weights are **never auto-applied** — every change is offline-replayed first, then human-approved and shipped as an explicit config change.
- Minimum sample gates (50 for analysis, 300 for suggestions); one-sided vote sets yield "agreement undefined", not a recommendation.
- Analysis only reports fields that are actually captured per vote.
