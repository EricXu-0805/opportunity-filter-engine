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


# ── a full harvest is a complete source check ──────────────────────────────
# Every national refresh since the source started recording its evidence has
# ended "Source check incomplete" with two causes, both ours. The listing was
# read one page too far: ?page=12 is past the end, so Drupal renders "No
# results found" and no table, which the collector counted as a failed page.
# And five detail pages repeat their "Link to Opportunity" field in a hidden
# copy that shows the whole URL, while the labelled field shows Drupal's
# trimmed "…" text; the copy did not read the same, stayed unparsed, and a URL
# containing "email" or "apply" (or a page with an Eligibility heading) made
# the page unsupported. The fixtures are trimmed copies of pages saved
# 2026-10-22; contact addresses are placeholders.

_FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "uiuc")


def _fixture(name):
    with open(os.path.join(_FIXTURES, name), encoding="utf-8") as f:
        return f.read()


class _Page:
    def __init__(self, url, html):
        self.url, self.text = url, html

    def raise_for_status(self):
        pass


def test_the_listing_stops_at_the_page_its_pager_marks_last(monkeypatch):
    # The pager of ?page=10 names ?page=10 current and links a next page, so
    # serving it for the earlier pages never reads as an end either.
    pages = {UIUCSROCollector.BASE_URL + f"?page={n}": "sro_list_page10.html" for n in range(11)}
    pages[UIUCSROCollector.BASE_URL + "?page=11"] = "sro_list_page11.html"
    pages[UIUCSROCollector.BASE_URL + "?page=12"] = "sro_list_page12.html"
    requested = []

    def get(url, *_a, **_k):
        requested.append(url)
        return _Page(url, _fixture(pages[url]))

    monkeypatch.setattr(uiuc_sro.requests, "get", get)
    collector = UIUCSROCollector(config={"rate_limit_delay": 0})
    records = collector.collect()
    evidence = collector.evidence
    assert requested[-1] == UIUCSROCollector.BASE_URL + "?page=11"
    assert len(requested) == 12 and len(records) == 11 * 2 + 4
    assert (evidence["list_pages_attempted"], evidence["list_pages_loaded"],
            evidence["list_pages_failed"]) == (12, 12, 0)
    assert evidence["list_complete"] is True and evidence["list_errors"] == []


def test_a_page_past_the_end_still_is_not_a_listing(monkeypatch):
    """If the pager is ever unreadable, reading past the end stays a failure."""
    page = _fixture("sro_list_page12.html")
    monkeypatch.setattr(uiuc_sro.requests, "get", lambda url, *_a, **_k: _Page(url, page))
    collector = UIUCSROCollector(config={"rate_limit_delay": 0})
    assert collector.collect() == []
    assert collector.evidence["list_complete"] is False
    assert collector.evidence["list_errors"] == [
        {"reason": "unsupported_list", "source_url": UIUCSROCollector.BASE_URL + "?page=0"}]


@pytest.mark.parametrize("name", ["sro_detail_chbsp.html", "sro_detail_lurie.html"])
def test_a_hidden_copy_of_a_trimmed_link_field_is_the_same_field(monkeypatch, name):
    monkeypatch.setattr(uiuc_sro.requests, "get", lambda *_a, **_k: _Detail(_fixture(name)))
    record, evidence = _scrape()
    assert record.extra_fields[CAPTURE_KEY]["status"] == "captured"
    assert evidence["detail_errors"] == []
    assert record.extra_fields["program_url"].startswith("https://www.")


def test_a_hidden_link_copy_that_points_elsewhere_keeps_the_page_unsupported(monkeypatch):
    page = _fixture("sro_detail_chbsp.html")
    hidden = page.index("field--name-field-link-to-opportunity field--type-link field--label-hidden")
    page = page[:hidden] + page[hidden:].replace("https://www.mskcc.org/", "https://example.org/", 2)
    assert page.count("https://example.org/") == 2
    monkeypatch.setattr(uiuc_sro.requests, "get", lambda *_a, **_k: _Detail(page))
    record, evidence = _scrape()
    assert record.extra_fields[CAPTURE_KEY]["status"] == "unsupported"
    assert evidence["detail_errors"] == [{"source_url": _DETAIL, "reason": "unparsed_relevant_content"}]
