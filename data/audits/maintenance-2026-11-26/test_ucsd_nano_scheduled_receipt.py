"""Rehearse the read-only November 27 verifier using reviewed rows and synthetic run metadata."""

import copy
import json
from datetime import date
from types import SimpleNamespace
from unittest.mock import patch

import check_ucsd_nano_scheduled_original_ids as check
import pytest

DAY = "2026-11-27"
START, SEEN, END = [DAY + t for t in ("T16:10:00Z", "T16:13:11Z", "T16:20:00Z")]


def fixture(jahed=True):
    active, baseline, _ = check.reviewed(jahed)
    prior = list(baseline.values())
    campus = copy.deepcopy(prior)
    for r in campus:
        if r["id"] in active:
            r["metadata"]["last_seen_at"] = SEEN
        if r["id"] == check.JAHED:
            r["metadata"]["faculty_title_observation"]["checked_on"] = DAY
    # The historical whole-campus ledger really counted fewer emitted rows than observed IDs.
    # These synthetic times and counts describe an expected result, not the November 27 run.
    unit = dict(
        unit_id="nano",
        school="ucsd",
        source="ucsd_faculty",
        unit_name=check.UNIT,
        unit_url=check.ROSTER,
        fetch_status="ok",
        parse_status="ok",
        validation_status="ok",
        roster_source_confirmed=True,
        started_at=START,
        completed_at=END,
        observed_entity_ids=list(active),
        observed_count=len(active) - 4,
        live_roster_count=len(active),
        retained_only_count=0,
        missed_present_identities=[],
        retirement_authorized=False,
        completeness_status="partial",
        coverage=dict(
            duplicate_rows=5,
            unparsed_rows=12,
            ambiguous_rows=0,
            identity_match_failures=0,
            parser_errors=0,
            partial_render_rows=0,
        ),
    )
    status = {
        "request": {"schools": ["ucsd"]},
        "release": {"publishable": ["ucsd"], "by_unit": {"ucsd": {"ready": True}}},
        "timestamp": DAY + "T16:26:00Z",
        "sources": {"ucsd_faculty": {"status": "partial_failure", "stale_unit_ledger": {"nano": unit}}},
    }
    run = {
        "id": 123,
        "event": "schedule",
        "head_branch": "main",
        "path": ".github/workflows/refresh-data.yml",
        "created_at": START,
        "run_started_at": START,
        "updated_at": DAY + "T17:00:00Z",
        "status": "completed",
        "head_sha": "run-start",
        "html_url": "fixture-run",
        "conclusion": "failure",
    }  # Another school failed after this verified unit published.
    pr = {
        "head": {"repo": {"full_name": check.REPO}, "ref": "auto/refresh-data-123-r2", "sha": "data-head"},
        "base": {"ref": "main"},
        "created_at": DAY + "T16:34:00Z",
        "merged_at": DAY + "T16:58:00Z",
        "merge_commit_sha": "merged",
        "html_url": "fixture-pr",
    }
    return SimpleNamespace(
        run=run,
        pr=pr,
        campus=campus,
        prior=prior,
        status=status,
        unit=unit,
        jahed=jahed,
        active=active,
        head_blob_same=True,
        parent_changed=True,
        source="reviewed_collector_in_ancestry",
    )


def validate(f):
    def read(rev, path):
        if rev == "merged":
            return json.dumps(f.status if path == check.LEDGER else f.campus).encode()
        if rev == "parent":
            return json.dumps(f.prior).encode()
        return saved_contents(rev, path)

    def oid(rev, path):
        if rev == "parent" and f.parent_changed:
            return "old" + path
        if rev == "data-head" and not f.head_blob_same:
            return "different" + path
        return "published" + path

    saved_contents = check.contents
    report = {}
    args = SimpleNamespace(run=123, data_pr=321, date=date.fromisoformat(DAY), jahed=f.jahed)
    # Resolve the immutable reviewed source before replacing publication reads.
    anchor = check.reviewed(f.jahed)
    with (
        patch.object(check, "get_run", return_value=f.run),
        patch.object(check, "get_pr", return_value=f.pr),
        patch.object(check, "api", return_value={"parents": [{"sha": "parent"}]}),
        patch.object(check, "reviewed", return_value=anchor),
        patch.object(check, "contents", side_effect=read),
        patch.object(check, "object_id", side_effect=oid),
        patch.object(check, "provenance", return_value={"method": f.source}),
    ):
        result, code = check.examine(args, report)
    return code, result, report


def target(f, oid):
    return next(r for r in f.campus if r["id"] == oid)


@pytest.mark.parametrize("jahed", [False, True])
def test_published_unit_with_partial_school_and_legitimate_newcomer(jahed):
    f = fixture(jahed)
    new = copy.deepcopy(target(f, check.KEN))
    new.update(id="faculty-ucsd-nano-newperson", pi_name="Different Person", url="https://example.edu/different")
    f.campus.append(new)
    f.unit["observed_entity_ids"].append(new["id"])
    f.unit["live_roster_count"] += 1
    code, _, r = validate(f)
    assert code == 0
    assert r["other_observed_ids"] == [new["id"]]
    assert len(r["original_identity_comparison"]) == (42 if jahed else 41)
    assert sum(x["expected"] == "cross_department_roster_id" for x in r["original_identity_comparison"].values()) == 9


@pytest.mark.parametrize(
    "kind",
    [
        "campus_blob",
        "first_parent",
        "wrong_unit",
        "wrong_read_time",
        "PR_predated_read",
        "ledger_timestamp",
        "school_withheld",
        "copied_but_unobserved",
        "stale_Ken",
        "stale_Jahed_citation",
        "wrong_archive_profile",
        "wrong_archive_reason",
        "archive_seen_again",
        "duplicate_original",
        "duplicate_ledger_id",
        "wrong_Ken",
        "wrong_active_name",
        "reassigned_unit",
        "missed_regular",
        "identity_loss",
        "ambiguous_retention",
        "duplicate_person",
    ],
)
def test_published_discrepancies(kind):
    f = fixture()
    old = next(iter(check.ARCHIVES))
    person = f.active[0]
    if kind == "campus_blob":
        f.head_blob_same = False
    elif kind == "first_parent":
        f.parent_changed = False
    elif kind == "wrong_unit":
        f.unit["source"] = "ucsd_sibling"
    elif kind == "wrong_read_time":
        f.unit["started_at"] = "2026-11-20T10:00:00Z"
    elif kind == "PR_predated_read":
        f.pr["created_at"] = DAY + "T16:11:00Z"
    elif kind == "ledger_timestamp":
        f.status["timestamp"] = "2026-11-20T10:00:00Z"
    elif kind == "school_withheld":
        f.status["release"]["publishable"] = []
    elif kind == "copied_but_unobserved":
        f.unit["observed_entity_ids"].remove(check.JAHED)
    elif kind == "stale_Ken":
        target(f, check.KEN)["metadata"]["last_seen_at"] = "2026-11-20T10:00:00Z"
    elif kind == "stale_Jahed_citation":
        target(f, check.JAHED)["metadata"]["faculty_title_observation"]["checked_on"] = "2026-11-26"
    elif kind == "wrong_archive_profile":
        target(f, old)["url"] = check.JACOBS + "527"
    elif kind == "wrong_archive_reason":
        target(f, old)["metadata"]["deactivation_reason"] = "not_recent"
    elif kind == "archive_seen_again":
        f.unit["observed_entity_ids"].append(old)
    elif kind == "duplicate_original":
        f.campus.append(copy.deepcopy(target(f, check.KEN)))
    elif kind == "duplicate_ledger_id":
        f.unit["observed_entity_ids"].append(check.KEN)
    elif kind == "wrong_Ken":
        target(f, check.KEN)["url"] = check.JACOBS + "527"
    elif kind == "wrong_active_name":
        target(f, person)["pi_name"] = "Another Person"
    elif kind == "reassigned_unit":
        target(f, person)["department"] = "Another Department"
    elif kind == "missed_regular":
        f.unit["observed_entity_ids"].remove(person)
    elif kind == "identity_loss":
        f.unit["missed_present_identities"] = [["name", "missing person"]]
    elif kind == "ambiguous_retention":
        f.unit["retained_only_count"] = 1
    elif kind == "duplicate_person":
        extra = copy.deepcopy(target(f, check.KEN))
        extra["id"] = "faculty-ucsd-nano-double"
        f.campus.append(extra)
    assert validate(f)[0] == 1


@pytest.mark.parametrize(
    "kind", ["other_workflow", "wrong_date", "manual", "wrong_branch", "foreign_PR", "wrong_PR_branch"]
)
def test_provenance_of_run_and_data_pr(kind):
    f = fixture()
    if kind == "other_workflow":
        f.run["path"] = ".github/workflows/ci.yml"
    if kind == "wrong_date":
        f.run["created_at"] = "2026-11-20T15:00:00Z"
    if kind == "manual":
        f.run["event"] = "workflow_dispatch"
    if kind == "wrong_branch":
        f.run["head_branch"] = "audit/local"
    if kind == "foreign_PR":
        f.pr["head"]["repo"]["full_name"] = "someone/else"
    if kind == "wrong_PR_branch":
        f.pr["head"]["ref"] = "auto/refresh-data-122"
    with pytest.raises(ValueError):
        validate(f)


def test_copy_on_an_unverified_collector_cannot_establish_the_fix():
    f = fixture()
    f.source = "unconfirmed"
    assert validate(f)[0] == 2


def test_comparing_known_code_even_when_fingerprints_differ():
    assert check.fingerprints(check.B19) != check.fingerprints(check.B20)
    old = "4fc6b5d01dda219e159f7d9cb108ce6e5b20fc49"
    assert check.fingerprints(old) not in (check.fingerprints(check.B19), check.fingerprints(check.B20))
