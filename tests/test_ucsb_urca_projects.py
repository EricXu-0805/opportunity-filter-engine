"""Tests for the UCSB URCA project-directory collector (ucsb_urca_projects).

The board is a Salesforce Aura SPA, but records are enumerated from a public
sitemap. Parsing tests feed a sitemap fixture (no network); normalization tests
are pure dict transforms.
"""

from __future__ import annotations

from src.collectors import ucsb_urca_projects as u
from src.normalizers.school_audience import SOURCE_DEFAULTS, VALID_AUDIENCES

SITEMAP_FIXTURE = """<?xml version="1.0"?><urlset>
<url><loc>https://ucsb.my.site.com/urca/s/funding-program/a0W1/urca-grants</loc></url>
<url><loc>https://ucsb.my.site.com/urca/s/funding-program/a0W2/summer-2023-chin-40-course-scholarship</loc></url>
<url><loc>https://ucsb.my.site.com/urca/s/funding-program/a0W3/faculty-research-assistant-program</loc></url>
<url><loc>https://ucsb.my.site.com/urca/s/funding-program/a0W4/evolution-of-california-land-snails</loc></url>
<url><loc>https://ucsb.my.site.com/urca/s/funding-program/a0W5/using-dna-barcoding-in-marine-ecology</loc></url>
</urlset>"""


class TestSitemapParse:
    def test_filters_admin_keeps_projects(self, monkeypatch):
        monkeypatch.setattr(u, "_fetch_text",
                            lambda url: SITEMAP_FIXTURE if url == u.SITEMAP_INDEX else "")
        recs = u.scrape_projects()
        titles = [r["title"] for r in recs]
        # the 3 admin/scholarship rows are dropped; 2 real projects remain
        assert titles == ["Evolution Of California Land Snails",
                           "Using DNA Barcoding In Marine Ecology"]

    def test_acronyms_reuppercased(self, monkeypatch):
        monkeypatch.setattr(u, "_fetch_text",
                            lambda url: SITEMAP_FIXTURE if url == u.SITEMAP_INDEX else "")
        titles = [r["title"] for r in u.scrape_projects()]
        assert "DNA" in titles[1]  # not "Dna"

    def test_empty_sitemap_yields_empty(self, monkeypatch):
        monkeypatch.setattr(u, "_fetch_text", lambda url: "")
        assert u.scrape_projects() == []


class TestNormalize:
    def _rec(self):
        return u.normalize_project(
            {"id": "a0W4", "url": "https://ucsb.my.site.com/urca/s/funding-program/a0W4/x",
             "title": "Evolution Of California Land Snails", "slug": "x"})

    def test_school_audience_matches_source_default(self):
        o = self._rec()
        assert (o["school"], o["audience"]) == SOURCE_DEFAULTS[u.SOURCE]
        assert o["audience"] in VALID_AUDIENCES

    def test_schema_and_dq_critical_fields(self):
        o = self._rec()
        assert o["id"].startswith("ucsb-urca-proj-")
        assert o["title"] and o["url"] and o["description_clean"]
        assert len(o["description_clean"]) <= 1500
        assert o["source_type"].startswith("campus_") and "faculty" not in o["source_type"]
        assert o["is_rolling"] is True and o["deadline"] is None

    def test_no_pi_or_email(self):
        """240+ project records with a blank/shared pi_name or email would trip the
        shared-name/inbox DQ gate — both stay None (mentor lives on the URCA page)."""
        o = self._rec()
        assert o["pi_name"] is None and o["contact_email"] is None

    def test_stable_id_across_reruns(self):
        assert self._rec()["id"] == self._rec()["id"]

    def test_empty_scrape_does_not_touch_corpus(self):
        assert u.merge_into_processed([]) == (0, 0)
