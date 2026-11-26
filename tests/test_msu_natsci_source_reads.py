"""A non-JSON response is evidence about the directory, never a zero-person count."""
import json

import pytest
import requests

from src.collectors import faculty_graph as fg
from src.collectors.schools.msu_faculty import SCHOOL
from src.normalizers.deactivate_stale_faculty import finalize_unit_ledger

BMB = next(dept for dept in SCHOOL["departments"] if dept["short"] == "BMB")
CLAIRE = {
    "id": 100493, "name": "Claire Vieille",
    "organizationTitles": [{"organizationId": 6, "title": "Associate Professor"}],
}
STAFF = {
    "id": 1, "name": "Sam Example",
    "organizationTitles": [{"organizationId": 6, "title": "Office Assistant"}],
}


def page(rows, total, pages=1):
    return {"results": rows, "resultCount": total, "pageCount": pages}


@pytest.mark.parametrize(("answers", "fetch", "parse", "reason", "raw", "missing", "faculty"), [
    ([b"<html>Directory unavailable</html>"], "failed", "zero_rows", "invalid_json", 0, 1, 0),
    ([403], "failed", "zero_rows", "http_403", 0, 1, 0),
    ([requests.Timeout()], "failed", "zero_rows", "timeout", 0, 1, 0),
    ([requests.ConnectionError()], "failed", "zero_rows", "connection_failed", 0, 1, 0),
    ([{}], "failed", "zero_rows", "invalid_roster_rows", 0, 1, 0),
    ([{"results": "unavailable"}], "failed", "zero_rows", "invalid_roster_rows", 0, 1, 0),
    ([page([], 0)], "ok", "zero_rows", None, 0, 0, 0),
    ([page([STAFF], 1)], "ok", "zero_rows", None, 1, 0, 0),
    ([page([CLAIRE], 2, 2), 503], "partial", "ok", "http_503", 1, 1, 1),
    ([page([CLAIRE], 1, 2), 503], "partial", "ok", "http_503", 1, 0, 1),
    ([page([CLAIRE], 2, 2), page([STAFF], 2, 2)], "ok", "ok", None, 2, 0, 1),
    ([page([CLAIRE], 2, 2), page([CLAIRE], 2, 2)], "ok", "ok", None, 2, 1, 1),
])
def test_msu_reports_each_directory_read_and_keeps_historical_id(
        monkeypatch, answers, fetch, parse, reason, raw, missing, faculty):
    calls = []

    def get(url, **kwargs):
        calls.append(url)
        item = answers[len(calls) - 1]
        if isinstance(item, Exception):
            raise item
        response = requests.Response()
        response.url = url
        response.status_code = item if isinstance(item, int) else 200
        response._content = item if isinstance(item, bytes) else json.dumps(item).encode()
        return response

    monkeypatch.setattr(requests, "get", get)
    school = dict(SCHOOL, departments=[BMB])
    ledger = {}
    people = fg.fetch_and_normalize(school, deep=True, unit_ledger=ledger)
    prior = fg._normalize(school, BMB, fg.faculty(
        "Kathleen Hoag", title="Professor", url=BMB["directory_url"]))
    finalize_unit_ledger(ledger, [prior], school["source"])
    unit = ledger["bmb"]
    assert len(calls) == len(answers)
    assert len(people) == faculty
    assert unit["fetch_status"] == fetch and unit["parse_status"] == parse
    assert unit.get("directory_fetch_failure") == reason
    assert unit["coverage"]["raw_roster_rows"] == raw
    assert unit["coverage"]["partial_render_rows"] == missing
    assert unit["baseline_active_count"] == 1 and not unit["retirement_authorized"]
    if reason:
        assert unit["failure_reason"] == reason
    if people:
        assert people[0]["pi_name"] == "Claire Vieille"
        assert people[0]["url"].endswith("/100493")
