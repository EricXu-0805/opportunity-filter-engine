"""Offline tests for src.collectors.uiuc_sro helpers.

Focus: _clean_compensation reduces the deep-scraped paid_info blob (±40-char
windows around paid keywords joined with ' | ', which leaks adjacent
Duration/Citizenship metadata) to a clean value. Mirrors the frontend
cleanCompensation so source data and display agree.
"""

from __future__ import annotations

import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from src.collectors import uiuc_sro
from src.collectors.base import RawOpportunity
from src.collectors.import_document import MAX_DEPTH, MAX_NODES
from src.collectors.uiuc_sro import UIUCSROCollector, _clean_compensation
from src.contact_instructions import CAPTURE_KEY
from tests.test_import_document import CROWDED_MARKUP, _growth


def test_extracts_dollar_amount_from_leaked_blob():
    raw = "Science & Technology Duration 10 weeks Compensation $6,500 Citizenship Requirement No"
    assert _clean_compensation(raw) == "$6,500"


def test_extracts_qualitative_label():
    raw = "& Behavior Duration Varies Compensation Paid Program Citizenship Requirement No Citi"
    assert _clean_compensation(raw) == "Paid Program"


def test_bare_paid_mention_when_no_value():
    # Dirty blob (the ' | ' marks the leaked-window concatenation) with no
    # dollar amount and no "Compensation <label>" token → bare "paid" fallback.
    raw = "interns are paid | Behavioral Sciences Duration 12 weeks Compensation Varies by Position"
    assert _clean_compensation(raw) == "Paid"


def test_clean_value_passes_through_untouched():
    assert _clean_compensation("$5,000 stipend") == "$5,000 stipend"
    assert _clean_compensation("Paid") == "Paid"


def test_empty_and_unparseable():
    assert _clean_compensation("") == ""
    assert _clean_compensation(None) == ""
    # A long blob with no dollar/qualitative/keyword signal yields '' (caller
    # falls back to the paid badge) rather than dumping the leaked metadata.
    assert _clean_compensation("x" * 200) == ""


# ── detail pages are parsed within the import reader's limits ──────────────
# A detail page was parsed with plain bs4 up to three times: by the capture,
# by its Drupal-field fallback and by the detail parser. On 2026-10-09 one of 30,000
# <br> then 30,000 </p> held the collector 6.6 s of CPU, and a <meta> content
# of 100,000 line breaks 10.8 s, each quadratic in the markup.

_DETAIL = "https://researchops.web.illinois.edu/opportunity/summer-research"


def _drupal_page(where, markup):
    """A detail page whose eligibility only its Drupal field holds, with markup in its head or body."""
    head, body = (markup, "") if where == "head" else ("", markup)
    return (f"<html><head><title>Summer research</title>{head}</head><body><article><h1>Summer research</h1>"
            '<div class="field--name-field-eligibility"><div class="field__label">Eligibility</div>'
            '<div class="field__item">A minimum GPA of 3.0 is required.</div></div>'
            f"{body}</article></body></html>")


class _Detail:
    def __init__(self, html):
        self.text, self.url = html, _DETAIL

    def raise_for_status(self):
        pass


def _scrape():
    record = RawOpportunity(source="uiuc_sro", source_url=UIUCSROCollector.BASE_URL + "?page=0",
                            title="Summer research", description_raw="List summary", url=_DETAIL)
    collector = UIUCSROCollector(deep=True)
    collector._fetch_detail_page(record)
    return record, collector.evidence


@pytest.mark.parametrize(("where", "build", "size"), CROWDED_MARKUP)
def test_a_crowded_detail_page_is_scraped_in_linear_time(monkeypatch, where, build, size):
    page = {}
    monkeypatch.setattr(uiuc_sro.requests, "get", lambda *_a, **_k: _Detail(page["html"]))

    def scrape(html):
        page["html"] = html
        record, _evidence = _scrape()
        return record.extra_fields[CAPTURE_KEY]["status"], record.extra_fields.get("eligibility_text")
    small, large = (_drupal_page(where, build(count)) for count in (size // 4, size))
    assert scrape(small) == scrape(large) == ("captured", "Eligibility A minimum GPA of 3.0 is required.")
    growth = _growth(scrape, small, large)
    assert growth < 8, f"four times the markup took {growth:.1f} times as long"


@pytest.mark.parametrize("markup", [
    pytest.param("<div>" * (MAX_DEPTH + 1) + "x", id="too-deep"),
    pytest.param("<i></i>" * MAX_NODES, id="too-many-nodes"),
])
def test_a_detail_page_past_the_limits_is_a_failed_check(monkeypatch, markup):
    monkeypatch.setattr(uiuc_sro.requests, "get", lambda *_a, **_k: _Detail(_drupal_page("body", markup)))
    record, evidence = _scrape()
    capture = record.extra_fields[CAPTURE_KEY]
    assert (capture["status"], capture["reason"]) == ("failed", "too_large")
    assert "deep_scraped" not in record.extra_fields and "eligibility_text" not in record.extra_fields
    assert evidence["detail_errors"] == [{"source_url": _DETAIL, "reason": "too_large"}]
    assert evidence["condition_capture_counts"]["failed"] == 1
