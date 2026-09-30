# Research refresh runner

This local runner refreshes verified professors' research snapshots. It writes a durable run journal and an optional candidate artifact. It does not enable a schedule, update collector health, commit, push, or deploy anything.

## Run and recover

Use a persistent SQLite file on one host, shared by every invocation of this runner. Keep it outside corpus/artifact directories. Do not use an ephemeral CI checkout for state, alternate state files for each run, hard links, or a network filesystem. Preserve the journal with the run exports; deleting it also deletes cooldowns and revoked-identity history.

```sh
python -m scripts.research_refresh run \
  --input /absolute/path/corpus.json \
  --state /absolute/path/research-queue.sqlite \
  --run-id research-uiuc-example \
  --base-sha <full-40-character-git-commit> \
  --shard uiuc --limit 25 --max-requests 50 --max-seconds 120 \
  --min-remaining 0 --out /absolute/path/new-run.json
```

`run` explicitly starts OpenAlex reads. Set `OPENALEX_API_KEY` in the process environment; the new transport uses an Authorization header. The input must include the full corpus needed to detect shared author identities, even when `--shard` selects one school. School selectors reuse the existing rotation registry. `national` selects no faculty and reports zero targets, not a successful school refresh.

A run ID binds its original input digest, Git base, schools and budgets. Reuse that ID and exactly the same input/settings to resume an interrupted run. A completed or deferred run returns its stored report with no requests; use a new ID for the next due batch. Each export path must be new. If export fails after a checkpoint, retrieve the saved report:

```sh
python -m scripts.research_refresh status \
  --state /absolute/path/research-queue.sqlite \
  --run-id research-uiuc-example --out /absolute/path/recovered-run.json
```

The process lock is nonblocking and single-host. A second active invocation fails busy; process exit releases the lock. A newer run that claims a task supersedes an older interrupted run. Resuming the old run reports a conflict instead of issuing more requests for that task.

## Selection, limits and outcomes

- Invalid historical faculty names/source URLs are recorded as `needs_review` with no request or patch, so they do not stop other selected records. They still participate in whole-corpus author collision checks. Duplicate/missing stable IDs and malformed corpus structure fail the run before HTTP.
- Select at most 25 due records, ordered by due time, previous attempt and stable record ID. A valid success, including an empty result, becomes due after 30 days.
- Failed network/server reads retry on later runs after 5 then 10 minutes, at most three attempts. Interrupted targets also have a five-minute cooldown for other runs; the same unfinished run can resume within its original budgets. Invalid responses, incomplete works, client errors and revoked identities require review.
- Identity/department changes retire the previous task binding. Loading an old verified record cannot automatically revive that binding. A genuinely corrected identity is a distinct binding; this runner does not perform administrative re-verification.
- A 429 response stops subsequent requests across the run. A persisted provider cooldown uses the larger valid Retry-After/reset interval, or five minutes if neither is available. Observed remaining credits at or below the configured floor also stop further requests.
- The request cap is reserved before each HTTP call. The original deadline and request count survive restart. The deadline prevents new requests; a per-request timeout of at most 20 seconds and read-loop deadline bound transport work but cannot forcibly interrupt an already blocked socket read. Decoded responses are limited to 8 MiB. There are no hidden retries or followed redirects.
- `credits_observed` sums received credit headers. Missing credit headers or lost responses make `credit_accounting_complete=false`. `unknown_request_count` counts requests whose response was not checkpointed. These are accounting observations, not a guaranteed monetary cap or exactly-once HTTP. A safe GET may repeat after a lost response, inside the remaining request/attempt limits.
- Reports separate `success_nonempty`, `success_empty`, `failed`, `incomplete`, `deferred`, `identity_revoked`, `conflict` and `needs_review`. `attempted` means a request was initiated. Deferred/conflicted targets contain no patch; failures never replace the last successful snapshot.

`status=completed` means the run reached a terminal outcome for its targets. It does not mean every target succeeded. Inspect `counts` and individual outcomes. Counts are derived from saved targets and do not grow when a report is replayed.

## Candidate review and explicit promotion

```sh
python -m scripts.research_refresh candidate \
  --run /absolute/path/new-run.json \
  --repository /absolute/path/checkout --out /absolute/path/new-artifact
python -m scripts.research_refresh verify \
  --artifact /absolute/path/new-artifact \
  --repository /absolute/path/checkout --run-id research-uiuc-example
# This command changes local research fields after the same checks:
python -m scripts.research_refresh promote \
  --artifact /absolute/path/new-artifact \
  --repository /absolute/path/checkout --run-id research-uiuc-example
```

The research-only manifest binds the run, explicit record IDs, identity binding, exact record preimages, Git base, and before/after shard bytes. It independently reconstructs the expected changes from committed shards. The run's corpus hash identifies the original input order; candidate verification proves each selected record against the base, rather than pretending it reconstructed that original list order.

Only research snapshot, refresh-attempt and recent-work fields may change. Confirmed revocation may remove publication attribution status. Same-name sibling records do not inherit another record's patch. Current whole-corpus author collisions are checked again. A changed target shard rejects the candidate; rebuild from current data. Unrelated schools are preserved. An exact already-applied candidate may return `already_applied`.

Promotion uses the existing Git common-directory publication lock, verifies staged bytes, and rolls back ordinary installation errors. This protects cooperating publishers; it is not an atomic multi-file transaction under power loss, and an older writer that ignores the lock is not coordinated automatically. Candidate manifests are local consistency records, not signed proof that provider data is true.

## Remaining before production

- Wire persistent state, the chosen scheduler, verified Git baseline and explicit candidate publication into one operator-owned process. The existing workflow currently does not call this runner or the artifact/PR verifier.
- Exercise real API quotas, persistent-host restart/recovery, cross-run publication and alert delivery in an authorized environment.
- Audit old author attribution and refill missing research. This runner covers research snapshots; it does not prove whole-school coverage, recruiting availability, lab website freshness, or the separate 14-day opportunity freshness target.
- Add a reviewed operational path for tasks needing identity/data correction. Do not clear the queue or rewrite timestamps to make them eligible.

The transport decisions follow [OpenAlex error handling](https://help.openalex.org/api/errors/) and [authentication guidance](https://help.openalex.org/api/authentication/). Transaction checkpoints use [Python SQLite transaction semantics](https://docs.python.org/3/library/sqlite3.html#how-to-use-the-connection-context-manager). TTL, batch size and retry counts are OFE implementation choices, not provider requirements.
