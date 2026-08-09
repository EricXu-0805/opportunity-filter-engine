"""Tests for the UCSB URCA project-directory collector (ucsb_urca_projects).

The board is a Salesforce Aura SPA, but records are enumerated from a public
sitemap. Parsing tests feed a sitemap fixture (no network); normalization tests
are pure dict transforms.
"""

from __future__ import annotations

import json

import pytest

from src.collectors import ucsb_urca_projects as u
from src.normalizers.school_audience import SOURCE_DEFAULTS, VALID_AUDIENCES

SITEMAP_FIXTURE = """<?xml version="1.0"?><urlset>
<url><loc>https://ucsb.my.site.com/urca/s/funding-program/a0W1/urca-grants</loc></url>
<url><loc>https://ucsb.my.site.com/urca/s/funding-program/a0W2/summer-2023-chin-40-course-scholarship</loc></url>
<url><loc>https://ucsb.my.site.com/urca/s/funding-program/a0W3/faculty-research-assistant-program</loc></url>
<url><loc>https://ucsb.my.site.com/urca/s/funding-program/a0W4/evolution-of-california-land-snails</loc></url>
<url><loc>https://ucsb.my.site.com/urca/s/funding-program/a0W5/using-dna-barcoding-in-marine-ecology</loc></url>
</urlset>"""
FUNDING_CURRENT = (
    "https://ucsb.my.site.com/urca/s/"
    "sitemap-outfunds__funding_program__c-1.xml"
)
FUNDING_WEEKLY = (
    "https://ucsb.my.site.com/urca/s/"
    "sitemap-outfunds__funding_program__c-weekly.xml"
)
LIVE_INDEX_FIXTURE = f"""<?xml version="1.0"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>{FUNDING_CURRENT}</loc></sitemap>
  <sitemap><loc>{FUNDING_WEEKLY}</loc></sitemap>
  <sitemap><loc>https://ucsb.my.site.com/urca/s/sitemap-view-1.xml</loc></sitemap>
  <sitemap><loc>https://ucsb.my.site.com/urca/s/sitemap-listview-1.xml</loc></sitemap>
</sitemapindex>"""


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

    def test_network_failure_is_not_confirmed_empty(self, monkeypatch):
        monkeypatch.setattr(u, "_fetch_text", lambda url: "")
        records, evidence = u.scrape_projects_with_evidence()
        assert records == []
        assert evidence["empty_confirmed"] is False
        assert evidence["sitemap_complete"] is False

    def test_valid_empty_urlset_is_not_enough_to_confirm_empty_season(
        self,
        monkeypatch,
    ):
        monkeypatch.setattr(
            u,
            "_fetch_text",
            lambda url: '<?xml version="1.0"?><urlset></urlset>',
        )
        records, evidence = u.scrape_projects_with_evidence()
        assert records == []
        assert evidence["sitemap_structure_complete"] is True
        assert evidence["empty_confirmed"] is False
        assert evidence["sitemap_complete"] is False

    def test_live_index_shape_ignores_known_non_target_siblings(self, monkeypatch):
        pages = {
            u.SITEMAP_INDEX: LIVE_INDEX_FIXTURE,
            FUNDING_CURRENT: """<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
              <url><loc>https://ucsb.my.site.com/urca/s/funding-program/a0W4/evolution-of-california-land-snails</loc></url>
            </urlset>""",
            FUNDING_WEEKLY: """<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
              <url><loc>https://ucsb.my.site.com/urca/s/funding-program/a0W5/using-dna-barcoding-in-marine-ecology</loc></url>
            </urlset>""",
        }
        monkeypatch.setattr(u, "_fetch_text", pages.get)

        records, evidence = u.scrape_projects_with_evidence()

        assert [record["id"] for record in records] == ["a0W4", "a0W5"]
        assert evidence == {
            "sitemap_complete": True,
            "sitemap_structure_complete": True,
            "sitemaps_expected": 2,
            "sitemaps_loaded": 2,
            "locations_seen": 2,
            "recognized_locations": 2,
            "unexpected_location_count": 0,
            "unexpected_location_samples": [],
            "empty_confirmed": False,
        }

    def test_partial_positive_child_failure_is_not_complete(self, monkeypatch):
        pages = {
            u.SITEMAP_INDEX: LIVE_INDEX_FIXTURE,
            FUNDING_CURRENT: """<urlset>
              <url><loc>https://ucsb.my.site.com/urca/s/funding-program/a0W4/evolution-of-california-land-snails</loc></url>
            </urlset>""",
            FUNDING_WEEKLY: "",
        }
        monkeypatch.setattr(u, "_fetch_text", pages.get)

        records, evidence = u.scrape_projects_with_evidence()

        assert [record["id"] for record in records] == ["a0W4"]
        assert evidence["sitemap_complete"] is False
        assert evidence["sitemaps_expected"] == 2
        assert evidence["sitemaps_loaded"] == 1
        assert evidence["empty_confirmed"] is False

    def test_unknown_record_location_blocks_complete_empty_claim(self, monkeypatch):
        monkeypatch.setattr(
            u,
            "_fetch_text",
            lambda url: """<urlset>
              <url><loc>https://ucsb.my.site.com/urca/s/new-project/a0W9/renamed-route</loc></url>
            </urlset>""",
        )

        records, evidence = u.scrape_projects_with_evidence()

        assert records == []
        assert evidence["sitemap_complete"] is False
        assert evidence["unexpected_location_count"] == 1
        assert evidence["empty_confirmed"] is False

    def test_url_entry_without_loc_is_schema_drift_not_empty(self, monkeypatch):
        monkeypatch.setattr(
            u,
            "_fetch_text",
            lambda url: """<urlset>
              <url><xloc>https://ucsb.my.site.com/urca/s/funding-program/a0W9/x</xloc></url>
            </urlset>""",
        )

        records, evidence = u.scrape_projects_with_evidence()

        assert records == []
        assert evidence["sitemap_complete"] is False
        assert evidence["empty_confirmed"] is False

    def test_unknown_index_sibling_is_schema_drift(self, monkeypatch):
        index = LIVE_INDEX_FIXTURE.replace(
            "</sitemapindex>",
            "<sitemap><loc>https://ucsb.my.site.com/urca/s/sitemap-other-1.xml</loc></sitemap>"
            "</sitemapindex>",
        )
        monkeypatch.setattr(
            u,
            "_fetch_text",
            lambda url: index if url == u.SITEMAP_INDEX else "<urlset/>",
        )

        records, evidence = u.scrape_projects_with_evidence()

        assert records == []
        assert evidence["sitemap_complete"] is False
        assert evidence["unexpected_location_count"] == 1

    def test_missing_known_funding_child_is_incomplete(self, monkeypatch):
        index = LIVE_INDEX_FIXTURE.replace(
            f"  <sitemap><loc>{FUNDING_CURRENT}</loc></sitemap>\n",
            "",
        )
        monkeypatch.setattr(
            u,
            "_fetch_text",
            lambda url: index if url == u.SITEMAP_INDEX else "<urlset/>",
        )

        records, evidence = u.scrape_projects_with_evidence()

        assert records == []
        assert evidence["sitemap_complete"] is False
        assert evidence["sitemaps_expected"] == 1
        assert evidence["missing_sitemap_count"] == 1

    def test_absent_weekly_delta_is_a_complete_snapshot(self, monkeypatch):
        """Salesforce publishes the weekly delta only when it has one.

        Observed live on 2026-08-08: the URCA index listed the full
        ``-1`` enumeration plus the two view sitemaps, and
        ``-weekly.xml`` 404ed. Requiring the delta made every snapshot
        incomplete, which errored the source and blocked the whole
        Saturday shard's publication for three weeks.
        """
        index = LIVE_INDEX_FIXTURE.replace(
            f"  <sitemap><loc>{FUNDING_WEEKLY}</loc></sitemap>\n",
            "",
        )
        pages = {
            u.SITEMAP_INDEX: index,
            FUNDING_CURRENT: """<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
              <url><loc>https://ucsb.my.site.com/urca/s/funding-program/a0W4/evolution-of-california-land-snails</loc></url>
            </urlset>""",
        }
        monkeypatch.setattr(u, "_fetch_text", pages.get)

        records, evidence = u.scrape_projects_with_evidence()

        assert [record["id"] for record in records] == ["a0W4"]
        assert evidence["sitemap_complete"] is True
        assert evidence["sitemaps_expected"] == 1
        assert evidence["sitemaps_loaded"] == 1
        assert evidence["unexpected_location_count"] == 0


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

    def test_complete_empty_snapshot_fails_before_retiring_old_projects(
        self,
        monkeypatch,
        tmp_path,
    ):
        old = self._rec()
        processed = tmp_path / "opportunities.json"
        processed.write_text(json.dumps([old]), encoding="utf-8")
        monkeypatch.setattr(u, "PROCESSED_FILE", processed)
        before = processed.read_bytes()

        with pytest.raises(
            u.UnsafeUrcaSnapshotError,
            match="zero-record",
        ):
            u.merge_snapshot_into_processed(
                [],
                snapshot_complete=True,
            )

        assert processed.read_bytes() == before
        saved = json.loads(processed.read_text(encoding="utf-8"))[0]
        assert saved["metadata"]["is_active"] is True

    def test_100_to_1_snapshot_fails_before_retiring_99_projects(
        self,
        monkeypatch,
        tmp_path,
    ):
        existing = [
            u.normalize_project(
                {
                    "id": f"a0W-{number:03d}",
                    "url": (
                        "https://ucsb.my.site.com/urca/s/funding-program/"
                        f"a0W-{number:03d}/project-{number}"
                    ),
                    "title": f"Project {number}",
                    "slug": f"project-{number}",
                }
            )
            for number in range(100)
        ]
        processed = tmp_path / "opportunities.json"
        processed.write_text(json.dumps(existing), encoding="utf-8")
        monkeypatch.setattr(u, "PROCESSED_FILE", processed)
        before = processed.read_bytes()

        with pytest.raises(
            u.UnsafeUrcaSnapshotError,
            match=r"1/100.*below 80%",
        ):
            u.merge_snapshot_into_processed(
                [existing[0]],
                snapshot_complete=True,
            )

        assert processed.read_bytes() == before
        saved = json.loads(processed.read_text(encoding="utf-8"))
        assert len(saved) == 100
        assert all(row["metadata"]["is_active"] for row in saved)

    def test_same_size_disjoint_ids_cannot_retire_entire_snapshot(
        self,
        monkeypatch,
        tmp_path,
    ):
        existing = [
            u.normalize_project(
                {
                    "id": f"old-{number}",
                    "url": (
                        "https://ucsb.my.site.com/urca/s/funding-program/"
                        f"old-{number}/old-project-{number}"
                    ),
                    "title": f"Old Project {number}",
                    "slug": f"old-project-{number}",
                }
            )
            for number in range(5)
        ]
        incoming = [
            u.normalize_project(
                {
                    "id": f"new-{number}",
                    "url": (
                        "https://ucsb.my.site.com/urca/s/funding-program/"
                        f"new-{number}/new-project-{number}"
                    ),
                    "title": f"New Project {number}",
                    "slug": f"new-project-{number}",
                }
            )
            for number in range(5)
        ]
        processed = tmp_path / "opportunities.json"
        processed.write_text(json.dumps(existing), encoding="utf-8")
        monkeypatch.setattr(u, "PROCESSED_FILE", processed)
        before = processed.read_bytes()

        with pytest.raises(
            u.UnsafeUrcaSnapshotError,
            match=r"0/5.*below 80%",
        ):
            u.merge_snapshot_into_processed(
                incoming,
                snapshot_complete=True,
            )

        assert processed.read_bytes() == before

    def test_complete_nonempty_snapshot_retires_only_missing_projects(
        self,
        monkeypatch,
        tmp_path,
    ):
        present = self._rec()
        existing = [present]
        for number in range(1, 5):
            existing.append(
                u.normalize_project(
                    {
                        "id": f"a0W-{number}",
                        "url": (
                            "https://ucsb.my.site.com/urca/s/funding-program/"
                            f"a0W-{number}/project-{number}"
                        ),
                        "title": f"Project {number}",
                        "slug": f"project-{number}",
                    }
                )
            )
        missing = existing[-1]
        processed = tmp_path / "opportunities.json"
        processed.write_text(
            json.dumps(existing),
            encoding="utf-8",
        )
        monkeypatch.setattr(u, "PROCESSED_FILE", processed)

        result = u.merge_snapshot_into_processed(
            existing[:-1],
            snapshot_complete=True,
        )

        assert result == (0, 4, 1)
        saved = {
            row["id"]: row
            for row in json.loads(processed.read_text(encoding="utf-8"))
        }
        assert saved[present["id"]]["metadata"]["is_active"] is True
        assert saved[missing["id"]]["metadata"]["is_active"] is False

    def test_incomplete_snapshot_never_retires_missing_projects(
        self,
        monkeypatch,
        tmp_path,
    ):
        old = self._rec()
        processed = tmp_path / "opportunities.json"
        processed.write_text(json.dumps([old]), encoding="utf-8")
        monkeypatch.setattr(u, "PROCESSED_FILE", processed)

        result = u.merge_snapshot_into_processed(
            [],
            snapshot_complete=False,
        )

        assert result == (0, 0, 0)
        saved = json.loads(processed.read_text(encoding="utf-8"))[0]
        assert saved["metadata"]["is_active"] is True
