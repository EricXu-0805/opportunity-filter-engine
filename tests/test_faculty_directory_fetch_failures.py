from unittest.mock import Mock

import pytest
import requests

from src.collectors import faculty_graph as fg
from src.collectors import ucb_common
from src.collectors.schools.umn_faculty import SCHOOL
from src.normalizers.deactivate_stale_faculty import finalize_unit_ledger


@pytest.mark.parametrize("answers, reason, attempts", [
    ([429, 429, 429], "http_429", 3),
    ([503, 503, 503], "http_503", 3),
    ([403], "http_403", 1),
    ([requests.exceptions.Timeout()] * 3, "timeout", 3),
    ([requests.exceptions.ConnectionError()] * 3, "connection_failed", 3),
    ([429, 200], None, 2),
    ([200], None, 1),
    ([], "rate_limit_circuit_open", 0),
])
def test_empty_umn_roster_reports_the_terminal_fetch_or_a_real_empty_page(monkeypatch, answers, reason, attempts):
    dept = next(d for d in SCHOOL["departments"] if d["short"].lower() == "ansci")
    url = dept["scrape"]["url"]
    session = Mock()
    events = []
    for answer in answers:
        if isinstance(answer, int):
            response = requests.Response()
            response.status_code = answer
            response.url = url
            response._content = b"<html><body>No roster cards</body></html>"
            answer = response
        events.append(answer)
    session.get.side_effect = events
    monkeypatch.setattr(ucb_common.requests, "Session", lambda: session)
    monkeypatch.setattr(ucb_common.time, "sleep", lambda delay: None)
    monkeypatch.setattr(ucb_common, "_consecutive_429", {})
    monkeypatch.setattr(ucb_common, "_rate_limited_hosts", set() if answers else {"ansci.umn.edu"})

    ledger = {}
    assert fg.fetch_and_normalize(dict(SCHOOL, departments=[dept]), deep=True, unit_ledger=ledger) == []
    # A failed or empty directory with a known prior person must retain them.
    prior = fg._normalize(SCHOOL, dept, fg.faculty("Sam Baidoo", title="Professor",
                          url="https://ansci.umn.edu/people/sam-baidoo"))
    assert prior["id"] == "faculty-umn-ansci-72a6966b"
    finalize_unit_ledger(ledger, [prior], SCHOOL["source"])
    unit = ledger["ansci"]
    assert session.get.call_count == attempts
    assert unit["baseline_active_count"] == 1 and unit["retirement_authorized"] is False
    assert unit["parse_status"] == "zero_rows"
    assert unit["fetch_status"] == ("failed" if reason else "ok")
    assert unit.get("directory_fetch_failure") == reason
    assert unit["failure_reason"] == reason
