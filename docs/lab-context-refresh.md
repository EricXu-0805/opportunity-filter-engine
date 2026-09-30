# Official website research context

This collector creates a **new review candidate** for 1–10 explicitly selected records. The collector never edits the input corpus or publishes to the database. A separate, explicit local application command is described below. The candidate is an operation artifact, not independent proof that a website or statement is correct.

## Current coverage

Only reviewed UCB Statistics professor profile layouts are supported:

- `school: ucb`, `source: ucb_stat_faculty`, `source_type: faculty_research`, `department: Department of Statistics`.
- Exact HTTPS host `statistics.berkeley.edu`, profile path `/people/<slug>`.
- Exactly one full `article.node--type-faculty`. The historical layout uses its direct `h3.page--title`; the current layout uses one direct `div.node__content` and its `div.node_top > div.node_top_copy > h1.page--title`. Both require the record's complete name. Duplicate identities, directory/teaser/related-person structures and incomplete names fail closed.
- Read direct `field--name-field-research-interests` and `field--name-field-research-areas-ref` fields from the selected layout. In the current layout, also retain the complete direct `field--name-body.field__item` value, including biography and research limitations; an absent label remains empty. Known field classes under an unexpected tag or nested container reject the page instead of being silently omitted. General navigation, publications, legacy record descriptions and arbitrary links are not substituted.
- The current policy does not follow lab links. The historical schema can retain a separately sourced second lab page, but no second-page policy is authorized for current writing use yet.

Reviewed template evidence: the preserved `PROFILE_WITH_INTERESTS_HTML` fixture in `tests/test_ucb_stat_faculty.py`, plus direct reads of the official [Peng Ding](https://statistics.berkeley.edu/people/peng-ding) and [Rasmus Nielsen](https://statistics.berkeley.edu/people/rasmus-nielsen) pages on 2026-09-26. Both current pages initially failed the historical selector; their saved HTML now passes full reviewed-field comparison, including Nielsen's complete description. `tests/test_lab_current_template.py` retains the current structure with synthetic prose. These two observations and the previous 49-record configuration preflight do not establish all-faculty coverage or recruitment availability.

Same names do not transfer authority between records: snapshots bind record ID, complete identity, school, department and exact profile URL. This is a finite template/identity check, not a universal people-disambiguation system.

## Explicit invocation

Run from the repository root in the project environment:

```sh
.venv/bin/python -m scripts.lab_refresh \
  --input path/to/corpus.json \
  --record-id EXISTING_RECORD_ID \
  --out path/to/new-lab-candidate.json
```

Repeat `--record-id` for additional selected records (maximum 10). No URL argument, caller-supplied snapshot or generic `.edu` fallback is accepted. Unsupported records receive an explicit `unsupported_policy` attempt without HTTP. Other schools require reviewed host/path/identity/template policy and tests before support is enabled.

Input must be a JSON record list. Duplicate IDs and malformed record/metadata containers reject the run. Selected IDs must exist and be unique. The output must be a new file in an existing directory. Existing files, symlinks, hard links to the input and same-input paths are refused. A temporary file is flushed and installed exclusively; another writer's output is never overwritten.

The candidate contains the input's canonical SHA256, each selected record's pre-read SHA256, and its detached patch. The CLI rechecks input bytes after collection and refuses output if they changed. These collection checks detect observed drift; they are not a publication transaction. Use the separate local artifact flow below to freeze and apply a candidate; never merge its metadata patches directly.

## Fetch boundary

- One GET per supported selected record; no automatic retry, redirects or inherited environment proxy.
- Resolve immediately before reading; reject any non-public DNS answer. Reuse the existing pinned HTTPS adapter, preserving the original hostname for certificate verification, SNI and Host while connecting to the validated IP.
- Canonical ASCII HTTPS URL only: no credentials, query, fragment, IP literal, explicit port, backslash or normalization drift. Valid punycode is checked by IDNA roundtrip.
- HTML/XHTML only; maximum 5 MiB **decoded** response bytes. Oversized or partial/failed responses cannot become snapshots.
- Socket timeout at most 15 seconds and elapsed-time checks before/after chunks. These stop later reads; they do not forcibly interrupt OS DNS resolution or an already blocked socket read. No strict whole-process deadline is claimed.
- Fixed error codes only in attempts; CLI diagnostics print exception class, never server error bodies, URL credentials or arbitrary exception messages.

## Source state

`metadata.lab_snapshot` stores the last successful source; `metadata.lab_refresh` records the latest attempted observation. Failure patches never replace the successful snapshot or advance its checked time. Missing sections, timeout, HTTP error, redirect and unsupported templates remain explicit failures.

A positively observed identity mismatch also records private `identity_revoked_at`. Later outages carry that revocation forward. Current public context stays unavailable while the old snapshot remains available internally for audit. Only a newly matched profile snapshot with a later observation time clears the revocation. Missing or malformed revocation timestamps fail closed. Candidate preflight rejects time regression relative to previous success, attempt or revocation.

The public context is `available` for up to 30 days after success, then `stale`; invalid identity/policy/source bindings are `unavailable`. Saved historical parsing validates the exact shape and content hash while preserving its recorded status. Current server projection independently rechecks source binding and age. Snapshot hash is a content binding, not authentication or a recruitment guarantee.

Website excerpts can explain the professor's research direction. They do not prove a student has those skills, has read a paper, or that the professor is recruiting.

## Verification scope

Offline tests cover the existing reviewed HTML fixture, wrong/full/incomplete identities, directory contamination, unsupported source bindings, byte/text limits, Unicode/canonical URL parity, stale success preservation, durable identity revocation, no-proxy pinned transport, redirect/SSRF rejection, streamed failures and candidate I/O conflicts. B49 separately read two official faculty pages and one lab website chain to verify structure, then replayed saved HTML without further requests. No actual corpus was refreshed, no model or email was called, and no cloud database or production schedule was changed. Local apply tests use temporary repositories; live-read evidence is not bulk coverage.


## Freeze, verify and apply locally

B49 adds a separate local application flow. It accepts the existing B48 candidate JSON. It does not accept arbitrary replacement corpus files or unsupported-source successes.

1. Use an exact committed Git base and explicitly name the source school shards. The collector input must equal those committed shard arrays concatenated in sorted shard-path order, preserving each array's record order. For one school, use that complete shard as the collector input. The corpus digest and every selected record preimage must match. Extra or omitted records, wrong ordering and a different source scope fail validation.
2. Build a new artifact directory; this step does not change the repository's shards. The artifact contains `candidate.json`, reconstructed shard outputs and `lab_manifest.json` with base, input scope, before/after hashes and record hashes.
3. Review the frozen candidate and manifest, then verify/apply using the candidate SHA256 printed by build as an explicit expected value. The digest is an identity/content receipt, not proof that an HTTP request happened or its prose is true.

```sh
.venv/bin/python -m scripts.lab_candidate build \
  --candidate path/to/new-lab-candidate.json \
  --repo /absolute/path/to/repository \
  --base-sha EXACT_40_CHARACTER_COMMIT \
  --source-shard ucb \
  --out /absolute/path/to/new-artifact-directory

.venv/bin/python -m scripts.lab_candidate verify \
  --artifact /absolute/path/to/new-artifact-directory \
  --repo /absolute/path/to/repository \
  --expected-candidate-sha256 SHA256_PRINTED_BY_BUILD

.venv/bin/python -m scripts.lab_candidate apply \
  --artifact /absolute/path/to/new-artifact-directory \
  --repo /absolute/path/to/repository \
  --expected-candidate-sha256 SHA256_PRINTED_BY_BUILD
```

Repeat `--source-shard` if the original input combined more than one school. The current website policy remains limited to UCB Statistics: `unsupported_policy` and `invalid_target` attempts cannot be promoted into other targets. Unselected records within a named source shard stay unchanged, but **the entire named shard is the conflict boundary**. Any byte change in that shard after the base prevents application, even if it affects a different professor. Valid changes in other shards are preserved. Duplicate record IDs anywhere in the base or current corpus reject the operation.

Verification reconstructs the result from the committed preimage and candidate, rechecks current source policy, exact identity/source binding, schema, observation times and durable revocation, and compares the stored artifact byte for byte. Only `metadata.lab_snapshot` and `metadata.lab_refresh` may change. Paper/research snapshots, recent works, publication attribution, descriptions and arbitrary other fields are retained. Failed observations cannot replace the previous successful snapshot or clear identity revocation. A successful identity recheck must be later than the revocation.

Application uses the existing repository-wide publication lock. It stages and validates all writes before replacement, and holds the same lock through failure recovery. A second application is a no-op only when every affected shard exactly matches the complete expected result; partial results and newer edits are conflicts. The lock coordinates these publication tools; it does not prevent unrelated editors from ignoring the lock, and no universal filesystem transaction is claimed.

On an ordinary install failure or cancellation, captured original files are restored. If restoration itself fails, the operation reports `rollback was incomplete`, retains the original backup file(s) at the reported path(s), and does not claim success. Stop automated retries; inspect the destinations and recover those backups explicitly before proceeding. Never remove a retained backup merely to make a retry pass.

Candidate input/output paths reject symlinks and traversal; artifacts cannot live in the shard tree or Git metadata directory. Existing artifact directories are never replaced. The CLI checks its input candidate again immediately before publishing the new artifact. A failed artifact build may leave an incomplete directory, which verify/apply rejects; it must not be treated as a completed candidate. If the input changes after the final check, the frozen bytes and expected digest still identify the reviewed candidate, not the changed external file.

No Git commit, push, cloud-database update, collector-status update or schedule is part of this command. B49 verification uses independent temporary Git repositories and synthetic website responses; it does not apply to the real project corpus.
