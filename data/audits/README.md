# data/audits — manual truthfulness-verification artifacts

Generated and consumed by `scripts/truthfulness_audit.py`
(process: `docs/truthfulness_sample_plan.md`):

- `samples/<category>.json` — per-category review sheets: deterministic
  seeded samples drawn from the corpus, with reviewer verdict fields filled
  in by hand during the audit.
- `truthfulness_report.json` — aggregate of the reviewed samples and the
  fail-closed GO / NO-GO truthfulness decision.

Sample files contain corpus snapshots (`system_value`) from generation time;
re-run the `sample` command after a corpus refresh rather than editing values.
