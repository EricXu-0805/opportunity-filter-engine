# Official website research context

This collector creates a **new review candidate** for 1–10 explicitly selected records. It never edits the input corpus or publishes to the database. The candidate is an operation artifact, not independent proof that a website or statement is correct.

## Current coverage

Only the existing UCB Statistics professor profile template is supported:

- `school: ucb`, `source: ucb_stat_faculty`, `source_type: faculty_research`, `department: Department of Statistics`.
- Exact HTTPS host `statistics.berkeley.edu`, profile path `/people/<slug>`.
- Exactly one full `article.node--type-faculty` with its direct `h3.page--title` matching the record's complete name. Directory/teaser/related-person structures and incomplete names fail closed.
- Only the direct `field--name-field-research-interests` and `field--name-field-research-areas-ref` fields. Complete field values and labels are retained; legacy descriptions, general biography, navigation, publications and arbitrary links are not substituted.
- The current policy does not follow lab links. The historical schema can retain a separately sourced second lab page, but no second-page policy is authorized for current writing use yet.

Reviewed template evidence: `src/collectors/ucb_stat_faculty.py` (`STAT_CONFIG`) and the preserved `PROFILE_WITH_INTERESTS_HTML` fixture in `tests/test_ucb_stat_faculty.py`. This batch used that existing evidence and synthetic transport. It did not perform a fresh live-site check. A local shard preflight found 49 records matching the configured policy; this establishes configuration compatibility, not 49 successful page reads.

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

The candidate contains the input's canonical SHA256, each selected record's pre-read SHA256, and its detached patch. The CLI rechecks input bytes after collection and refuses output if they changed. These checks detect observed drift; they are **not a compare-and-swap publication transaction**. There is no apply/promotion command. A future publisher must revalidate current corpus/record bindings, source policy, attempt times and revocation before any publication; it must not blindly replay these patches.

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

Offline tests cover the existing reviewed HTML fixture, wrong/full/incomplete identities, directory contamination, unsupported source bindings, byte/text limits, Unicode/canonical URL parity, stale success preservation, durable identity revocation, no-proxy pinned transport, redirect/SSRF rejection, streamed failures and candidate I/O conflicts. No actual website, external model, email, whole-corpus refresh, database write or scheduled activation was exercised in this batch.
