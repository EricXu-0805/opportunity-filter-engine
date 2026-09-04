"""Offline tests for scripts/truthfulness_audit.py — the manual
sample-verification framework.

Locks in: every category gets a sample file with the full row schema;
verification_status derivation mirrors the Phase-1 audit rules; sampling is
deterministic for a given seed; and the report gate is FAIL-CLOSED (any
pending, any unresolved critical, or a missing category file => NO-GO).
"""

from __future__ import annotations

import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from truthfulness_audit import (
    CATEGORIES,
    ROW_FIELDS,
    derive_verification_status,
    main,
)


def _rec(rid, **overrides):
    """A minimal-but-schema-shaped corpus record."""
    record = {
        "id": rid,
        "source": "test_faculty",
        "source_url": f"https://example.edu/{rid}",
        "source_type": "faculty_research",
        "title": f"Research with Prof. {rid}",
        "organization": "Test University",
        "department": "Department of Testing",
        "pi_name": f"Pat {rid.title()}",
        "contact_email": f"{rid}@example.edu",
        "url": f"https://example.edu/{rid}",
        "deadline": None,
        "is_rolling": True,
        "eligibility": {
            "international_friendly": "unknown",
            "citizenship_required": False,
            "eligibility_text_raw": "",
            "work_auth_notes": "",
        },
        "keywords": ["testing"],
        "school": "testu",
        "metadata": {
            "faculty_title": "Assistant Professor",
            "research_areas_raw": "testing",
            "is_active": True,
        },
    }
    meta = overrides.pop("metadata", None)
    elig = overrides.pop("eligibility", None)
    record.update(overrides)
    if meta:
        record["metadata"] = {**record["metadata"], **meta}
    if elig:
        record["eligibility"] = {**record["eligibility"], **elig}
    return record


def _synthetic_corpus():
    """~18 tiny records with at least one risk case per category."""
    blanket_kw = ["artificial intelligence", "machine learning"]
    return [
        # multi-campus org: same org string under two school slugs
        _rec("purdue-a", organization="Purdue University", school="purdue",
             metadata={"faculty_title": "Professor",
                       "recent_works": [{"title": "Paper One"}, {"title": "Paper Two"}],
                       "email_source": "profile_page"}),
        _rec("purduefw-b", organization="Purdue University", school="purduefw"),
        # similarly-named orgs sharing the word "Columbia"
        _rec("columbia-a", organization="Columbia University", school="columbia"),
        _rec("ccc-a", organization="Columbia College Chicago", school="ccc",
             metadata={"faculty_title": "Professor Emeritus"}),
        # constructed / wayback / null / generic emails
        _rec("stan-a", school="stanford", organization="Stanford University",
             metadata={"email_source": "constructed_sunetid"}),
        _rec("stan-b", school="stanford", organization="Stanford University",
             metadata={"email_source": "wayback"}),
        _rec("stan-c", school="stanford", organization="Stanford University",
             contact_email=None, department="",
             metadata={"faculty_title": ""}),
        # same pi_name under two schools + non-professor rank + initials-only
        _rec("mit-a", school="mit", organization="MIT", pi_name="John Doe",
             department="Institute for Data Science",
             metadata={"faculty_title": "Lecturer"}, keywords=[]),
        _rec("yale-a", school="yale", organization="Yale University",
             pi_name="John Doe", metadata={"faculty_title": "Senior Research Scientist"}),
        _rec("mit-b", school="mit", organization="MIT", pi_name="J. R. Smith",
             metadata={"recent_works": [{"title": "Old Paper"}],
                       "research_areas_raw": ""}),
        # dept-blanket keywords: 3 records, same school+dept, identical keywords
        _rec("mit-e1", school="mit", organization="MIT",
             department="EECS", keywords=blanket_kw, metadata={"research_areas_raw": ""}),
        _rec("mit-e2", school="mit", organization="MIT",
             department="EECS", keywords=blanket_kw, metadata={"research_areas_raw": ""}),
        _rec("mit-e3", school="mit", organization="MIT",
             department="EECS", keywords=blanket_kw, metadata={"research_areas_raw": ""}),
        # past explicit deadline
        _rec("mit-d", school="mit", organization="MIT",
             deadline="2025-01-15", is_rolling=False),
        # nsf_reu policy-derived intl "no" + estimated deadline
        _rec("reu-a", source="nsf_reu", source_type="summer_program",
             school=None, organization="NSF REU Site", pi_name=None,
             deadline="2026-02-01", is_rolling=False, deadline_is_estimate=True,
             eligibility={"international_friendly": "no", "citizenship_required": True},
             metadata={"faculty_title": ""}),
        # campus programs: status unknown/discovered/stale-year, intl yes,
        # generic email, rolling-with-note
        _rec("prog-a", source="testu_research_programs", source_type="campus_program",
             campus_source_type="program", pi_name=None,
             title="Summer Research Program 2019", contact_email="info@example.edu",
             eligibility={"international_friendly": "yes"},
             metadata={"faculty_title": "", "status": "unknown", "discovered": True,
                       "collector_source": "campus_graph",
                       "deadline_note": "Applications reviewed monthly"}),
        _rec("prog-b", source="testu_research_programs", source_type="campus_program",
             campus_source_type="program", pi_name=None,
             title="Undergraduate Research Fellowship",
             eligibility={"international_friendly": "yes"},
             metadata={"faculty_title": "", "status": "open",
                       "collector_source": "campus_graph"}),
        # job-board record: must NOT land in the program category
        _rec("job-a", source="simplify_internships", source_type="internship",
             organization="BigCo", school=None, pi_name=None,
             metadata={"faculty_title": ""}),
        # inactive record: must never be sampled
        _rec("dead-a", metadata={"is_active": False}),
    ]


def _write_corpus(tmp_path):
    corpus = tmp_path / "corpus.json"
    corpus.write_text(json.dumps(_synthetic_corpus()), encoding="utf-8")
    return corpus


def _run_sample(tmp_path, out_name="samples", seed=20260731, per_category=6):
    corpus = _write_corpus(tmp_path)
    out = tmp_path / out_name
    rc = main(["sample", "--corpus", str(corpus), "--out", str(out),
               "--seed", str(seed), "--per-category", str(per_category)])
    assert rc == 0
    return out


def _load(path):
    return json.loads(path.read_text(encoding="utf-8"))


# ------------------------------------------------------------ sample command

def test_sample_produces_every_category_with_row_schema(tmp_path):
    out = _run_sample(tmp_path)
    for cat in CATEGORIES:
        data = _load(out / f"{cat}.json")
        assert data["category"] == cat
        assert data["seed"] == 20260731
        assert isinstance(data["risk_pool_gaps"], list)
        assert len(data["samples"]) >= 1, f"no samples for {cat}"
        for row in data["samples"]:
            assert set(row) == set(ROW_FIELDS), f"row schema mismatch in {cat}"
            assert row["review_result"] == "pending"
            assert row["entity_type"] == cat
            assert row["entity_id"] != "dead-a", "inactive record was sampled"


def test_program_pool_excludes_job_boards(tmp_path):
    out = _run_sample(tmp_path)
    data = _load(out / "program.json")
    ids = {row["entity_id"] for row in data["samples"]}
    assert "job-a" not in ids
    assert ids <= {"prog-a", "prog-b", "reu-a"}


# ------------------------------------------- verification_status derivation

def test_verification_status_derivation():
    # publication without attribution status => unverified (fail-closed)
    assert derive_verification_status(
        "publication", {"metadata": {"recent_works": [{"title": "X"}]}}) == "unverified"
    assert derive_verification_status(
        "publication", {"metadata": {"recent_works": [{"title": "X"}],
                                     "publication_attribution_status": "verified_author_id"}},
    ) == "verified"
    # constructed_* email => inferred; profile_page => verified; null => unknown
    assert derive_verification_status(
        "email", {"contact_email": "a@b.edu",
                  "metadata": {"email_source": "constructed_sunetid"}}) == "inferred"
    assert derive_verification_status(
        "email", {"contact_email": "a@b.edu",
                  "metadata": {"email_source": "profile_page"}}) == "verified"
    assert derive_verification_status("email", {"contact_email": None, "metadata": {}}) == "unknown"
    # intl unknown stays unknown; a yes/no claim is unverified
    assert derive_verification_status(
        "international", {"eligibility": {"international_friendly": "unknown"}}) == "unknown"
    assert derive_verification_status(
        "international", {"eligibility": {"international_friendly": "yes"}}) == "unverified"
    # estimated deadline => inferred; blanket faculty rolling => policy_default
    assert derive_verification_status(
        "deadline", {"deadline": "2026-05-01", "deadline_is_estimate": True}) == "inferred"
    assert derive_verification_status(
        "deadline", {"is_rolling": True, "source_type": "faculty_research"}) == "policy_default"


# ------------------------------------------------------------- determinism

def test_same_seed_produces_identical_samples(tmp_path):
    out1 = _run_sample(tmp_path, out_name="samples1", seed=42)
    out2 = _run_sample(tmp_path, out_name="samples2", seed=42)
    for cat in CATEGORIES:
        d1, d2 = _load(out1 / f"{cat}.json"), _load(out2 / f"{cat}.json")
        assert d1["samples"] == d2["samples"], f"non-deterministic samples for {cat}"
        assert d1["risk_pool_gaps"] == d2["risk_pool_gaps"]


# ---------------------------------------------------------------- report

def _sample_row(cat, seq, review_result="pending", severity=None, notes=""):
    return {
        "sample_id": f"{cat}-{seq:03d}",
        "entity_type": cat,
        "entity_id": f"rec-{cat}-{seq}",
        "field_name": "x",
        "system_value": "v",
        "verification_status": "unverified",
        "source_url": "https://example.edu",
        "source_evidence": "",
        "manual_expected_value": None,
        "review_result": review_result,
        "error_type": None,
        "severity": severity,
        "reviewer": None if review_result == "pending" else "tester",
        "reviewed_at": None if review_result == "pending" else "2026-07-31T00:00:00+00:00",
        "notes": notes,
        "risk_case": None,
    }


def _write_samples_dir(tmp_path, review_result="verified_correct", n=8):
    samples_dir = tmp_path / "review"
    samples_dir.mkdir(exist_ok=True)
    for cat in CATEGORIES:
        payload = {
            "category": cat,
            "generated_at": "2026-07-31T00:00:00+00:00",
            "seed": 1,
            "corpus_records": 18,
            "risk_pool_gaps": [],
            "samples": [_sample_row(cat, i, review_result) for i in range(1, n + 1)],
        }
        (samples_dir / f"{cat}.json").write_text(json.dumps(payload), encoding="utf-8")
    return samples_dir


def _run_report(tmp_path, samples_dir):
    """Run `report` and assert the exit code MATCHES the printed decision.

    The exit code used to be a hardcoded 0, so the GO/NO-GO decision it exists
    to produce could not gate anything: a NO-GO printed its banner and then
    told the caller everything was fine. Every report test now re-checks that
    contract for free.
    """
    out = tmp_path / "report.json"
    rc = main(["report", "--samples", str(samples_dir), "--out", str(out)])
    report = _load(out)
    expected = 0 if report["truthfulness_approved"] else 1
    assert rc == expected, (
        f"decision {report['decision']} must exit {expected}, got {rc}"
    )
    return report


def test_report_all_pending_is_no_go(tmp_path):
    samples_dir = _write_samples_dir(tmp_path, review_result="pending")
    report = _run_report(tmp_path, samples_dir)
    assert report["truthfulness_approved"] is False
    assert report["decision"] == "NO-GO"
    assert all(not c["complete"] for c in report["categories"].values())


def test_report_fully_reviewed_is_go_and_critical_blocks(tmp_path):
    samples_dir = _write_samples_dir(tmp_path, review_result="verified_correct")
    report = _run_report(tmp_path, samples_dir)
    assert report["truthfulness_approved"] is True
    assert report["decision"] == "GO"
    assert report["critical_open"] == []

    # one unresolved critical incorrect_value => NO-GO, listed in critical_open
    email_file = samples_dir / "email.json"
    data = json.loads(email_file.read_text(encoding="utf-8"))
    data["samples"][0] = _sample_row("email", 1, review_result="incorrect_value",
                                     severity="critical")
    email_file.write_text(json.dumps(data), encoding="utf-8")
    report = _run_report(tmp_path, samples_dir)
    assert report["truthfulness_approved"] is False
    assert report["decision"] == "NO-GO"
    assert report["critical_open"] == ["email-001"]

    # same critical with a "RESOLVED:" notes prefix => approved again
    data["samples"][0] = _sample_row("email", 1, review_result="incorrect_value",
                                     severity="critical",
                                     notes="RESOLVED: pipeline fixed in #999, re-scraped")
    email_file.write_text(json.dumps(data), encoding="utf-8")
    report = _run_report(tmp_path, samples_dir)
    assert report["truthfulness_approved"] is True
    assert report["critical_open"] == []


def test_report_missing_category_file_is_no_go(tmp_path):
    samples_dir = _write_samples_dir(tmp_path, review_result="verified_correct")
    (samples_dir / "publication.json").unlink()
    report = _run_report(tmp_path, samples_dir)
    assert report["truthfulness_approved"] is False
    assert report["decision"] == "NO-GO"
    assert report["categories"]["publication"]["present"] is False


def test_report_under_eight_samples_is_incomplete(tmp_path):
    samples_dir = _write_samples_dir(tmp_path, review_result="verified_correct", n=5)
    report = _run_report(tmp_path, samples_dir)
    assert report["truthfulness_approved"] is False
    assert all(c["sample_count"] == 5 and not c["complete"]
               for c in report["categories"].values())


# ------------------------------------------------------------- exit contract

def test_report_exit_code_carries_the_decision(tmp_path, capsys):
    """NO-GO must exit 1; GO must exit 0 — and both must print the summary.

    `run_report` returned 0 unconditionally, which made the fail-closed gate
    decorative: `truthfulness_audit.py report` inside a CI step or a `&&` chain
    reported success while the report on disk said NO-GO. The human summary is
    still printed before the non-zero exit, so a blocked release stays
    diagnosable rather than merely broken.
    """
    out = tmp_path / "report.json"

    no_go = _write_samples_dir(tmp_path, review_result="pending")
    assert main(["report", "--samples", str(no_go), "--out", str(out)]) == 1
    printed = capsys.readouterr().out
    assert "TRUTHFULNESS DECISION: NO-GO" in printed
    assert "category" in printed, "the per-category table must still print"
    assert _load(out)["decision"] == "NO-GO", "the report must still be written"

    go = _write_samples_dir(tmp_path, review_result="verified_correct")
    assert main(["report", "--samples", str(go), "--out", str(out)]) == 0
    assert "TRUTHFULNESS DECISION: GO" in capsys.readouterr().out


def test_sample_still_exits_zero(tmp_path):
    """Drawing samples has no verdict to report — only `report` gates."""
    corpus = _write_corpus(tmp_path)
    assert main(["sample", "--corpus", str(corpus),
                 "--out", str(tmp_path / "s"), "--seed", "7",
                 "--per-category", "4"]) == 0


# ---------------------------------------------------------------------------
# Coverage: how much the corpus claims at all, which no sample of ten can say
#
# Two holes found by hand on 2026-08-23 were invisible to a report that
# returned GO on the same corpus, both days:
#
#   * 47,024 harvested publications on 15,917 professors, 0 of them passing
#     the attribution gate, so no cold email had ever cited a paper;
#   * a stale-faculty pass structurally unable to reach 98.4% of the corpus.
#
# Neither is a truthfulness failure. A record that claims nothing is perfectly
# truthful, and the sample-based audit is right to pass it. What was missing
# is a number for the silence — so coverage is REPORTED and never gated, the
# same call made for `no_channel` in the reminders cron.
# ---------------------------------------------------------------------------


def test_sampling_records_corpus_wide_stratum_counts(tmp_path):
    from scripts.truthfulness_audit import RISK_SELECTORS

    samples_dir = tmp_path / "samples"
    corpus = _write_corpus(tmp_path)
    main(["sample", "--corpus", str(corpus), "--out", str(samples_dir), "--seed", "1"])
    data = json.loads((samples_dir / "publication.json").read_text(encoding="utf-8"))
    coverage = data["coverage"]
    assert coverage["pool"] > 0
    # Every stratum is counted, including the ones at zero — a stratum that
    # drops out of the report because nothing matched is exactly the hole.
    assert set(coverage["strata"]) == {tag for tag, _ in RISK_SELECTORS["publication"]}


def test_a_capability_nothing_uses_reads_as_zero_not_as_absent(tmp_path):
    samples_dir = tmp_path / "samples"
    corpus = _write_corpus(tmp_path)
    main(["sample", "--corpus", str(corpus), "--out", str(samples_dir), "--seed", "1"])
    coverage = json.loads(
        (samples_dir / "publication.json").read_text(encoding="utf-8")
    )["coverage"]
    # The fixture corpus stamps no attribution, so this is the 0-of-N state the
    # real corpus was in and nothing reported.
    assert coverage["strata"]["verified_author_id"] == 0


def test_coverage_reaches_the_report_and_does_not_gate_it(tmp_path):
    samples_dir = _write_samples_dir(tmp_path, review_result="verified_correct")
    # A category whose capability covers nothing at all.
    path = samples_dir / "publication.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["coverage"] = {"pool": 1000, "strata": {"verified_author_id": 0}}
    path.write_text(json.dumps(data), encoding="utf-8")

    report = _run_report(tmp_path, samples_dir)
    assert report["categories"]["publication"]["coverage"]["strata"] == {
        "verified_author_id": 0
    }
    # Zero coverage is not a truthfulness finding.
    assert report["decision"] == "GO"


def test_resampling_refuses_to_discard_human_verdicts(tmp_path, capsys):
    """A verdict is the one input the audit cannot re-derive.

    Everything else in a sample file comes from the corpus and regenerates for
    free. A review_result is a person having opened a source page and checked
    a record against it. `sample` rewrites each category file wholesale, so
    re-running it on a reviewed directory silently reset every verdict to
    pending — which is exactly what happened while building the coverage block
    above: ten verdicts across publication.json alone, recoverable only
    because they were still in git.
    """
    samples_dir = _write_samples_dir(tmp_path, review_result="verified_correct")
    corpus = _write_corpus(tmp_path)
    rc = main(["sample", "--corpus", str(corpus), "--out", str(samples_dir),
               "--seed", "1"])
    assert rc == 2
    assert "refusing to overwrite reviewed samples" in capsys.readouterr().err
    after = json.loads((samples_dir / "email.json").read_text(encoding="utf-8"))
    assert all(s["review_result"] == "verified_correct" for s in after["samples"])


def test_force_still_resamples(tmp_path):
    samples_dir = _write_samples_dir(tmp_path, review_result="verified_correct")
    corpus = _write_corpus(tmp_path)
    assert main(["sample", "--corpus", str(corpus), "--out", str(samples_dir),
                 "--seed", "1", "--force"]) == 0
    after = json.loads((samples_dir / "email.json").read_text(encoding="utf-8"))
    assert all(s["review_result"] == "pending" for s in after["samples"])


def test_an_unreviewed_directory_resamples_without_a_flag(tmp_path):
    # The guard must not make the ordinary first run harder.
    samples_dir = _write_samples_dir(tmp_path, review_result="pending")
    corpus = _write_corpus(tmp_path)
    assert main(["sample", "--corpus", str(corpus), "--out", str(samples_dir),
                 "--seed", "1"]) == 0


class TestAnEstimatedReuDeadlineIsNotBeforeItsAward:
    """The estimate reads the award start's month and year and returns a spring
    date in that SAME year. An award beginning in the autumn funds the
    following summer's cohort, so all 398 such records carried a deadline five
    to ten months before the grant that funds them began — and long past by the
    time a student saw it."""

    @staticmethod
    def _estimate(start: str) -> str | None:
        from src.collectors.nsf_reu import _estimate_reu_deadline

        return _estimate_reu_deadline(start)

    def test_an_autumn_award_points_at_the_next_spring(self):
        assert self._estimate("12/15/2025") == "2026-02-15"
        assert self._estimate("09/01/2026") == "2027-02-15"
        assert self._estimate("10/01/2026") == "2027-02-15"

    def test_a_summer_award_still_closes_before_it_starts(self):
        # Applications for a summer cohort genuinely close two to three months
        # before the award lands; only the autumn branch moved.
        assert self._estimate("06/01/2026") == "2026-03-01"
        assert self._estimate("05/01/2026") == "2026-03-01"
        assert self._estimate("08/15/2026") == "2026-04-01"

    def test_no_estimate_precedes_its_own_award_by_a_season(self):
        from datetime import date

        for month in range(1, 13):
            start = date(2026, month, 1)
            estimate = self._estimate(f"{month}/1/2026")
            assert estimate is not None
            gap = (start - date.fromisoformat(estimate)).days
            assert gap < 150, f"month {month}: estimate {estimate} is {gap} days early"
