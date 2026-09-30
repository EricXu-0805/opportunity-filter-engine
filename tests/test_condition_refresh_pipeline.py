"""Offline proof through the real refresh entry and its publication verdict."""
import json
import socket
from copy import deepcopy

import pytest
import requests

from src.collectors import refresh_all, url_parser
from src.collectors.faculty_condition_refresh import refresh_faculty_condition_sources
from src.collectors.refresh_contract import evaluate_refresh_summary
from src.contact_instructions import CAPTURE_KEY, PAGES_KEY, SOURCE_KEY, contact_instructions_for
from tests.test_refresh_all import _stub_with_processed_file
from tests.test_refresh_contract import _graph_ok, _ok, _summary

URL = "https://example.edu/people/jane"


def faculty(ident="jane", school="uw"):
    return {"id": ident, "source": f"{school}_faculty", "school": school,
            "source_type": "faculty_research", "url": URL, "source_url": URL,
            "title": "Research with Jane Scientist", "pi_name": "Jane Scientist",
            "department": "Computer Science", "description_raw": "Research on sensors",
            "research_areas": ["sensors"], "contact_email": "jane@example.edu",
            "metadata": {"is_active": True}}


def response(url=URL):
    r = requests.Response()
    r.status_code = 200
    r.url = url
    r.encoding = "utf-8"
    r._content = b"<html><body><main><h1>Jane Scientist</h1><h2>Undergraduate students</h2><p>Please do not email us directly. Use the application form.</p></main></body></html>"
    r._content_consumed = True
    return r


@pytest.fixture(autouse=True)
def no_external(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: pytest.fail("External network forbidden"))
    monkeypatch.setattr(url_parser, "_host_resolves_to_blocked_ip", lambda host: False)


def stats(school="uw", backlog=0):
    report = refresh_faculty_condition_sources([faculty(str(i), school) for i in range(backlog)], max_requests=0)
    report["records_in_scope"] = backlog
    return report


def test_actual_entry_refreshes_complete_profile_and_reopens_whole_corpus(monkeypatch, tmp_path):
    target, untouched = faculty(), faculty("other", "uiuc")
    path = _stub_with_processed_file(monkeypatch, tmp_path, [target, untouched])
    monkeypatch.setattr(refresh_all, "refresh_faculty_condition_sources", refresh_faculty_condition_sources)
    calls = []
    def get(url, **kwargs):
        calls.append(url)
        return response(url)
    monkeypatch.setattr(url_parser.requests, "get", get)
    result = refresh_all.refresh_all(deep=True, schools={"uw"}, condition_max_requests=1)
    saved = {record["id"]: record for record in json.loads(path.read_text())}
    assert calls == [URL]
    assert set(saved) == {"jane", "other"}
    assert saved["jane"]["metadata"][CAPTURE_KEY]["status"] == "captured"
    assert saved["jane"]["metadata"][PAGES_KEY]["version"] == 1
    assert saved["jane"]["metadata"][SOURCE_KEY]
    assert SOURCE_KEY not in saved["other"]["metadata"]
    assert contact_instructions_for(saved["jane"])["email_policy"] == "form_only"
    assert result["condition_refresh"]["backlog"] == 0
    assert result["condition_refresh"]["requests"] == 1
    assert result["condition_refresh"]["by_school"]["uw"]["attempted"] == 1
    # Reopen through the same real entry. Complete fields and source TTL have
    # distinct behavior: the fresh page should not issue another request.
    monkeypatch.setattr(url_parser.requests, "get", lambda *a, **k: pytest.fail("Fresh page re-fetched"))
    again = refresh_all.refresh_all(deep=True, schools={"uw"})
    assert again["condition_refresh"]["requests"] == 0
    assert again["condition_refresh"]["fresh"] == 1


def test_scoped_callback_checkpoints_full_corpus_before_later_failure(monkeypatch, tmp_path):
    target, other = faculty(), faculty("other", "uiuc")
    target.pop("school")  # source mapping must still scope the pool
    path = _stub_with_processed_file(monkeypatch, tmp_path, [target, other])
    def run(records, *, persist, **kwargs):
        assert [record["id"] for record in records] == ["jane"]
        assert kwargs["max_requests"] == 7 and kwargs["max_pages"] == 3
        records[0]["metadata"]["checkpoint_test"] = "saved"
        persist()
        raise RuntimeError("simulated interruption after checkpoint")
    monkeypatch.setattr(refresh_all, "refresh_faculty_condition_sources", run)
    with pytest.raises(RuntimeError, match="simulated interruption"):
        refresh_all.refresh_all(deep=True, schools={"uw"}, condition_max_requests=7, condition_max_pages=3)
    saved = json.loads(path.read_text())
    assert len(saved) == 2 and saved[0]["metadata"]["checkpoint_test"] == "saved"
    assert saved[1] == other


@pytest.mark.parametrize("kwargs,reason", [({"deep": False, "schools": {"uw"}}, "quick_mode"),
                                           ({"deep": True, "national": True}, "national_only")])
def test_outside_condition_scope_never_calls_runner(monkeypatch, tmp_path, kwargs, reason):
    _stub_with_processed_file(monkeypatch, tmp_path, [faculty()])
    monkeypatch.setattr(refresh_all, "refresh_faculty_condition_sources", lambda *a, **k: pytest.fail("Wrong scope"))
    result = refresh_all.refresh_all(**kwargs)
    assert result["condition_refresh"] == {"version": 1, "status": "skipped", "reason": reason}


def test_zero_budget_still_reports_real_backlog_without_requests(monkeypatch, tmp_path):
    _stub_with_processed_file(monkeypatch, tmp_path, [faculty()])
    monkeypatch.setattr(refresh_all, "refresh_faculty_condition_sources", refresh_faculty_condition_sources)
    monkeypatch.setattr(url_parser.requests, "get", lambda *a, **k: pytest.fail("Zero budget sent request"))
    result = refresh_all.refresh_all(deep=True, schools={"uw"}, condition_max_requests=0)
    report = result["condition_refresh"]
    assert report["status"] == "partial" and report["backlog"] == 1
    assert report["attempted"] == report["requests"] == 0
    assert any(d["kind"] == "condition_refresh" and d["source"] == "uw_faculty"
               for d in result["release"]["degradations"])


@pytest.mark.parametrize("key,value", [("condition_max_requests", -1), ("condition_max_requests", True),
                                        ("condition_max_pages", 10001)])
def test_bad_budget_rejected_before_collectors(monkeypatch, key, value):
    monkeypatch.setattr(refresh_all, "fetch_campus_graph_with_evidence", lambda *a, **k: pytest.fail("Collector started"))
    with pytest.raises(ValueError):
        refresh_all.refresh_all(schools={"uw"}, **{key: value})


def valid_summary():
    return _summary({"uw", "wisc"}, {"campus_graph:uw": _graph_ok(), "uw_faculty": _ok(),
                                     "campus_graph:wisc": _graph_ok(), "wisc_faculty": _ok()})


def test_backlog_degrades_only_named_school_without_blocking_preserved_data():
    summary = valid_summary()
    summary["condition_refresh"] = {"version": 1, "status": "partial", **stats(backlog=2)}
    result = evaluate_refresh_summary(summary, schools={"uw", "wisc"}, national=False, deep=True)
    assert result["ready"] is True and result["status"] == "degraded"
    assert result["degradations"] == [{"kind": "condition_refresh", "source": "uw_faculty",
                                      "detail": "backlog=2, unchecked=0, rejected=0"}]
    assert result["publishable"] == ["uw", "wisc"]


@pytest.mark.parametrize("change", ["empty_school_counts", "negative", "claims_ok", "invalid_skip", "bad_version", "bool_version", "bad_status_type", "wrong_school", "claimed_records", "hidden_failure"])
def test_malformed_condition_progress_cannot_claim_success(change):
    summary = valid_summary()
    report = {"version": 1, "status": "partial", **deepcopy(stats(backlog=2))}
    if change == "empty_school_counts": report["by_school"] = {}
    if change == "negative": report["by_school"]["uw"]["backlog"] = -1
    if change == "claims_ok": report["status"] = "ok"
    if change == "invalid_skip": report.update(status="skipped", reason="quick_mode")
    if change == "bad_version": report["version"] = 2
    if change == "bool_version": report["version"] = True
    if change == "bad_status_type": report["status"] = ["ok"]
    if change == "wrong_school": report["by_school"]["mit"] = report["by_school"].pop("uw")
    if change == "claimed_records": report["records_in_scope"] = 100
    if change == "hidden_failure":
        report["condition_capture_counts"]["failed"] = 1
        report.update(status="ok", backlog=0)
    summary["condition_refresh"] = report
    result = evaluate_refresh_summary(summary, schools={"uw", "wisc"}, national=False, deep=True)
    assert result["ready"] is False
