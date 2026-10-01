"""CMU's login-only project list, published from a dated snapshot.

The list is a Google Sheet only a CMU Andrew account can open, so it enters
the corpus as data/snapshots/cmu_uro_projects.json (exported by hand, turned
into the snapshot by the importer, reviewed) and
src/collectors/cmu_uro_projects.py turns it into listings on every CMU
refresh. These pin the promises that make that honest:

  * only the approved fields leave the sheet — a title, the person who listed
    the project, when, how to reach them — in the site and in the public
    repository alike; no synopsis, skills, inquiry text or anyone else's
    address, and no address where the listing asked for a form;
  * every listing says it is a dated snapshot, and nothing stays live past
    the snapshot's end or is deleted;
  * every CMU refresh runs it, nothing else fills in its contacts, and the
    importer keeps the next export inside the same scope.

The reminder that the snapshot needs a new export is tested in
test_snapshot_reminder.py.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from datetime import date

import pytest

from backend.lib.opportunity_detail import build_detail_fields
from backend.lib.public_projection import contains_embedded_email
from src.collectors import cmu_uro_projects as uro
from src.collectors import pi_enricher
from src.collectors import refresh_all as refresh_all_mod
from src.collectors.campus_graph import SOURCE_TYPES
from src.collectors.refresh_contract import expected_sources, shard_of_source
from src.normalizers.deactivate_past import deactivate_past
from src.normalizers.enricher import infer_keywords, infer_majors
from src.normalizers.school_audience import SOURCE_DEFAULTS
from src.opportunity_terms import extract_skill_requirements
from tests.test_refresh_all import _stub_all_collectors

URO_PAGE = "https://www.cmu.edu/uro/getting-started-in-research/index.html"
SHEET = "https://docs.google.com/spreadsheets/d/1doUAfTmVYeswzP_yHGnWQM32RKtWp6l8OpRRneghz3k/edit"
BEFORE_EXPIRY = date(2026, 9, 30)
AFTER_EXPIRY = date(2027, 5, 16)
ADDRESS = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")


@pytest.fixture(scope="module")
def snapshot() -> dict:
    return uro.load_snapshot()


@pytest.fixture(scope="module")
def records() -> list[dict]:
    return uro.fetch_and_normalize(today=BEFORE_EXPIRY)


def _by_name(records, name):
    (match,) = (r for r in records if r["pi_name"] == name)
    return match


def _copy(value):
    return json.loads(json.dumps(value))


# ---------------------------------------------------------------- snapshot


class TestSnapshotFile:
    def test_the_committed_snapshot_validates(self, snapshot):
        assert uro.validate_snapshot(snapshot) == []
        meta = snapshot["snapshot"]
        assert meta["snapshot_date"] == "2026-09-14"
        assert meta["valid_until"] == "2027-05-15"
        assert meta["refresh_due"] == "2027-01-11"
        assert meta["contributor"] == "Stephen Huang"
        assert meta["public_listing_url"] == URO_PAGE
        assert meta["source_sheet_url"] == SHEET

    def test_it_keeps_only_the_approved_fields(self, snapshot):
        """Title, the person who listed it, when, and how to reach them."""
        for row in snapshot["projects"]:
            assert tuple(row) == uro.ROW_FIELDS, row["id"]

    def test_the_only_addresses_in_the_file_are_the_listed_contacts(self, snapshot):
        text = uro.SNAPSHOT_FILE.read_text(encoding="utf-8")
        contacts = {row["contact_email"] for row in snapshot["projects"] if row["contact_email"]}
        assert set(ADDRESS.findall(text)) == contacts
        assert len(contacts) == 25

    def test_the_university_of_pittsburgh_response_stays_out(self, snapshot):
        assert len(snapshot["projects"]) == 38
        (excluded,) = snapshot["snapshot"]["excluded_responses"]
        assert excluded["id"] not in {row["id"] for row in snapshot["projects"]}
        assert "Pittsburgh" in excluded["reason"]

    @pytest.mark.parametrize("breakage, message", [
        (lambda s: s["projects"][0].update(synopsis="My lab studies..."), "not a published field"),
        (lambda s: s["snapshot"].update(skills_text="Python"), "snapshot.skills_text is not a known"),
        (lambda s: s["projects"][0].update(title="Write to lab@example.edu"), "title shows an email address"),
        (lambda s: s["snapshot"].update(access="or ask someone@example.edu"), "no row's contact_email"),
        (lambda s: s["projects"][0].update(contact_email=None), "must be an address"),
        (lambda s: s["projects"][1].update(contact_email="someone@example.edu"), "must be null"),
        (lambda s: s["projects"][1].update(application_url=None), "must be an https link"),
        (lambda s: s["projects"][0].update(contact_basis="guessed"), "contact_basis must be one of"),
        (lambda s: s["projects"][0].update(title=""), "title is empty"),
        (lambda s: s["projects"][0].update(position="Not specified in extracted row"),
         "position is a placeholder"),
        (lambda s: s["projects"][0].update(department="N/A"), "department is a placeholder"),
        (lambda s: s["projects"][1].update(id=s["projects"][0]["id"]), "duplicates the id"),
        (lambda s: s["projects"][0].update(id=s["snapshot"]["excluded_responses"][0]["id"]),
         "listed in excluded_responses"),
        (lambda s: s["snapshot"].update(refresh_due="2027-06-01"),
         "snapshot_date <= refresh_due <= valid_until"),
    ])
    def test_validation_refuses_what_must_not_be_published(self, snapshot, breakage, message):
        broken = _copy(snapshot)
        breakage(broken)
        assert any(message in p for p in uro.validate_snapshot(broken)), uro.validate_snapshot(broken)

    def test_an_empty_or_unreadable_snapshot_raises_rather_than_publishing(self, tmp_path, snapshot):
        empty = _copy(snapshot)
        empty["projects"] = []
        path = tmp_path / "snap.json"
        path.write_text(json.dumps(empty), encoding="utf-8")
        with pytest.raises(uro.SnapshotError, match="non-empty"):
            uro.fetch_and_normalize(path=path)


# ----------------------------------------------------------------- records


class TestRecords:
    def test_emits_all_38_with_the_required_fields(self, records):
        assert len(records) == 38
        for r in records:
            for key in ("id", "source", "source_type", "title", "url", "source_url",
                        "organization", "department", "pi_name", "description_clean",
                        "eligibility", "application"):
                assert r[key], (r["id"], key)
            md = r["metadata"]
            for key in ("confidence_score", "first_seen_at", "last_seen_at", "is_active"):
                assert key in md, (r["id"], key)
            assert r["source"] == "cmu_uro_projects"
            assert r["source_type"] == "campus_program"
            assert r["campus_source_type"] == "program" and "program" in SOURCE_TYPES
            assert (r["school"], r["audience"]) == ("cmu", "campus")
            assert r["url"] == URO_PAGE
            assert r["source_url"] == SHEET
            assert r["organization"] == "Carnegie Mellon University"
            assert md["is_active"] is True
            assert md["expires_at"] == "2027-05-15"
            assert md["source_snapshot"]["contributed_by"] == "Stephen Huang"

    def test_never_refreshed_silently(self, records):
        """A refresh re-emits the snapshot; it does not re-check the sheet."""
        assert {r["metadata"]["last_verified"] for r in records} == {"2026-09-14"}

    def test_every_description_is_the_dated_caveat_and_nothing_from_the_sheet(self, snapshot, records):
        rows = {row["id"]: row for row in snapshot["projects"]}
        for r in records:
            text = r["description_clean"]
            assert text == r["description_raw"] == uro.compose_description(rows[r["id"]], snapshot["snapshot"])
            assert "this copy was taken 2026-09-14" in text
            assert "may not be updated as positions are filled" in text
        # Only the contact-route sentence differs from one listing to the next.
        assert len({r["description_clean"] for r in records}) == 4

    def test_the_description_adds_no_keyword_major_or_skill(self, records):
        """Inference reads the listing's title and department; our caveat must
        not read as a subject area on every row."""
        for text in {r["description_clean"] for r in records}:
            probe = {"title": "", "description_clean": text, "department": "", "lab_or_program": ""}
            assert infer_keywords(probe) == [] and infer_majors(probe) == []
            assert extract_skill_requirements(text) == {"required": [], "preferred": [], "mentioned": []}

    def test_ids_are_deterministic_and_unique(self, records):
        again = uro.fetch_and_normalize(today=BEFORE_EXPIRY)
        assert [r["id"] for r in records] == [r["id"] for r in again]
        assert len({r["id"] for r in records}) == 38
        assert all(re.fullmatch(r"cmu-uro-[0-9a-f]{12}", r["id"]) for r in records)
        # Pinned: a changed derivation would duplicate the rows on the next import.
        nagle = _by_name(records, "Stephanie Tristram-Nagle")
        assert nagle["id"] == "cmu-uro-a1add4211b2f" == uro.project_id("2026-08-05T07:31:11", "stn@cmu.edu")

    def test_the_surname_only_row_has_the_full_name_the_sheet_shows(self, records):
        assert [r["pi_name"] for r in records if "Wang" in r["pi_name"]] == ["Qiaosi (Chelsea) Wang"]

    def test_an_address_only_where_the_listing_asks_for_email(self, snapshot, records):
        with_email = [r for r in records if r["contact_email"]]
        assert len(with_email) == 32
        bases = {row["id"]: row["contact_basis"] for row in snapshot["projects"]}
        assert {bases[r["id"]] for r in with_email} == uro.EMAIL_BASES
        for name in ("David Mortensen", "Yorie Nakahira", "Vernelle Noel", "Julie Downs", "David Held",
                     "Vickie Webster-Wood"):
            assert _by_name(records, name)["contact_email"] is None, name

    def test_where_the_listing_routes_students_to_someone_else_cmus_list_is_the_route(
            self, snapshot, records):
        """Held names a student per project; Webster-Wood asks for an email to
        a student lead with her in CC and a tag in the subject, which this
        site cannot carry. Neither row shows an address, not even the lister's
        own: each points to CMU's list, the official route."""
        rows = {row["name"]: row for row in snapshot["projects"]}
        for name in ("David Held", "Vickie Webster-Wood"):
            row = rows[name]
            assert (row["contact_basis"], row["contact_email"], row["application_url"]) == (
                "listed_contacts", None, None), name
            record = _by_name(records, name)
            assert record["url"] == URO_PAGE
            assert record["application"]["contact_method"] == "unknown"
            text = record["description_clean"]
            assert "someone other than the person shown here" in text
            assert "how to reach them is on CMU's list" in text
            assert "Getting Started in Research page" in text
        assert [row["name"] for row in snapshot["projects"]
                if row["contact_basis"] == "listed_contacts"] == ["David Held", "Vickie Webster-Wood"]

    def test_form_and_page_routes_are_the_application_link(self, records):
        for name in ("David Mortensen", "Yorie Nakahira", "Vernelle Noel", "Julie Downs"):
            application = _by_name(records, name)["application"]
            assert application["application_url"].startswith("https://")
            assert "?" not in application["application_url"]  # no share-tracking query
            assert application["contact_method"] == "website"
        assert _by_name(records, "Justin Chan")["application"]["application_url"] is None
        held = _by_name(records, "David Held")
        assert held["application"]["application_url"] is None

    def test_no_public_field_would_be_blanked_by_email_redaction(self, records):
        """The public projection blanks a whole field that shows an address."""
        for r in records:
            fields = [r["title"], r["description_clean"], r["description_raw"], r["pi_name"],
                      r["department"], r["lab_or_program"], r["metadata"]["notes"],
                      r["metadata"]["faculty_title"], *r["keywords"]]
            assert not any(contains_embedded_email(f) for f in fields), r["id"]

    def test_stated_rank_decides_the_honorific(self, records):
        assert _by_name(records, "Cailyn Smith")["metadata"]["faculty_title"] == "PhD Student"
        assert _by_name(records, "Olive Nichols")["metadata"]["faculty_title"] == "Lab Manager"

    def test_nothing_reads_as_the_listings_own_skills_or_materials(self, records):
        """Skills and application materials are not transcribed, so whatever
        the rules read from a title shows as an inference, never as stated."""
        for r in records:
            fields = build_detail_fields(r, r)["fields"]
            assert not fields["required_skills"]["explicit"], r["id"]
            assert "requirements" not in fields["application_method"]["explicit"], r["id"]
            assert not any(len(s) <= 1 for s in r["eligibility"]["skills_preferred"])


SHARD_FIELDS = ("title", "pi_name", "department", "contact_email", "description_clean",
                "application.application_url", "application.contact_method",
                "metadata.contact_basis", "metadata.faculty_title", "metadata.expires_at")


def _field(record: dict, path: str):
    for part in path.split("."):
        record = record[part]
    return record


class TestCommittedShard:
    def test_the_cmu_shard_publishes_what_the_snapshot_says(self, records):
        """The shard is what the site serves. A snapshot edit that never went
        through the pipeline into it would keep publishing the old rows."""
        shard_file = uro.PROJECT_ROOT / "data" / "processed" / "shards" / "cmu.json"
        shard = json.loads(shard_file.read_text(encoding="utf-8"))
        published = {r["id"]: r for r in shard if r.get("source") == uro.SOURCE}
        assert set(published) == {r["id"] for r in records}
        stale = [(r["id"], path) for r in records for path in SHARD_FIELDS
                 if _field(published[r["id"]], path) != _field(r, path)]
        assert stale == []


# ------------------------------------------------------------------ expiry


class TestExpiry:
    def test_rows_stay_active_through_the_last_valid_day(self):
        assert all(r["metadata"]["is_active"] for r in uro.fetch_and_normalize(today=date(2027, 5, 15)))

    def test_after_valid_until_every_row_is_retired_with_its_reason(self):
        expired = uro.fetch_and_normalize(today=AFTER_EXPIRY)
        assert len(expired) == 38
        for r in expired:
            md = r["metadata"]
            assert md["is_active"] is False
            assert md["deactivation_reason"] == "expired"
            assert md["deactivated_at"] == "2027-05-16"

    def test_deactivate_past_retires_an_expired_row_even_though_it_is_rolling(self, records):
        record = _copy(records[0])
        assert record["is_rolling"] is True
        counts = deactivate_past([record], today=date(2027, 5, 15))
        assert record["metadata"]["is_active"] is True and counts["newly_deactivated"] == 0
        counts = deactivate_past([record], today=AFTER_EXPIRY)
        assert counts["newly_deactivated"] == 1
        assert record["metadata"]["deactivation_reason"] == "expired"
        assert record["metadata"]["deactivated_at"] == "2027-05-16"

    def test_merge_retires_absent_rows_and_never_deletes(self, monkeypatch, tmp_path, records):
        processed = tmp_path / "opportunities.json"
        other = {"id": "cmu-other", "source": "cmu_research_programs", "metadata": {"is_active": True}}
        processed.write_text(json.dumps([other]), encoding="utf-8")
        monkeypatch.setattr(uro, "PROCESSED_FILE", processed)

        assert uro.merge_into_processed(_copy(records)) == (38, 0)
        first_seen = {r["id"]: r["metadata"]["first_seen_at"]
                      for r in json.loads(processed.read_text(encoding="utf-8"))
                      if r["source"] == "cmu_uro_projects"}
        # A later snapshot drops one response: kept, retired, never deleted.
        later = _copy(records[1:])
        for r in later:
            r["metadata"]["first_seen_at"] = "2027-01-20T00:00:00"
        assert uro.merge_into_processed(later) == (0, 37)
        stored = {r["id"]: r for r in json.loads(processed.read_text(encoding="utf-8"))}
        assert len(stored) == 39
        dropped = stored[records[0]["id"]]["metadata"]
        assert dropped["is_active"] is False
        assert dropped["deactivation_reason"] == "absent_from_snapshot"
        assert stored["cmu-other"]["metadata"]["is_active"] is True
        assert all(stored[r["id"]]["metadata"]["first_seen_at"] == first_seen[r["id"]] for r in later)

    def test_an_expired_emission_keeps_the_day_it_was_first_retired(self, monkeypatch, tmp_path):
        processed = tmp_path / "opportunities.json"
        processed.write_text("[]", encoding="utf-8")
        monkeypatch.setattr(uro, "PROCESSED_FILE", processed)
        live = uro.fetch_and_normalize(today=BEFORE_EXPIRY)
        uro.merge_into_processed(live)
        stored = json.loads(processed.read_text(encoding="utf-8"))
        deactivate_past(stored, today=date(2027, 5, 20))
        processed.write_text(json.dumps(stored), encoding="utf-8")
        uro.merge_into_processed(uro.fetch_and_normalize(today=date(2027, 5, 27)))
        for r in json.loads(processed.read_text(encoding="utf-8")):
            assert r["metadata"]["deactivated_at"] == "2027-05-20"
            assert r["metadata"]["deactivation_reason"] == "expired"


# ------------------------------------------------------------------ wiring


class TestWiring:
    def test_registered_as_a_cmu_campus_source(self):
        assert SOURCE_DEFAULTS["cmu_uro_projects"] == ("cmu", "campus")
        assert shard_of_source("cmu_uro_projects") == "cmu"
        for deep in (True, False):
            assert "cmu_uro_projects" in expected_sources({"cmu"}, national=False, deep=deep)

    @pytest.mark.parametrize("deep", [True, False])
    def test_every_cmu_refresh_runs_it(self, monkeypatch, tmp_path, deep):
        _stub_all_collectors(monkeypatch, tmp_path)
        summary = refresh_all_mod.refresh_all(deep=deep, schools={"cmu"})
        assert summary["sources"]["cmu_uro_projects"]["status"] == "ok"

    def test_other_shards_do_not_run_it(self, monkeypatch, tmp_path):
        _stub_all_collectors(monkeypatch, tmp_path)
        summary = refresh_all_mod.refresh_all(deep=False, schools={"uw"})
        assert "cmu_uro_projects" not in summary["sources"]

    def test_the_pi_enricher_never_scrapes_a_contact_onto_a_snapshot_row(self, monkeypatch, records):
        held = _copy(_by_name(records, "David Held"))

        def no_fetch(url):
            raise AssertionError(f"scraped {url}")

        monkeypatch.setattr(pi_enricher, "_fetch_soup", no_fetch)
        stats = pi_enricher.enrich_opportunities([held], save=False, max_scrapes=5)
        assert stats["skipped_program"] == 1
        assert held["contact_email"] is None


# ---------------------------------------------------------------- importer

HEADER = [
    "Timestamp", "Email Address", "Last Name", "First Name", "College/School Affiliation",
    "Department Affiliation(s)",
    "Your Title (e.g., Assistant Professor, Associate Director, Librarian, etc.)",
    "Please enter a short synopsis of the type of research you conduct. You can list specific "
    "projects here, or give a general overview of your research.",
    'Please list a target "end date" of your research.',
    "Please list any preferred skills, qualifications, or other requirements for the research.",
    "How should students inquire about the research? (e.g. email address, link to complete a "
    "form, etc.) If the point of contact for this project is someone other than you, please "
    "list a contact name and email address.",
    "Keywords to describe your research/lab/ongoing project(s)",
]
FORM = "https://docs.google.com/forms/d/e/1FAIpQLSexample/viewform"


def _response(ts, email, last, first, inquiry, synopsis="SYNOPSIS-NOT-PUBLISHED"):
    return [ts, email, last, first, "Example College", "Example Dept", "Associate Professor",
            synopsis, "ongoing", "SKILLS-NOT-PUBLISHED", inquiry, "KEYWORDS-NOT-PUBLISHED"]


def _export(tmp_path, *responses):
    path = tmp_path / "export.csv"
    with path.open("w", encoding="utf-8", newline="") as f:
        csv.writer(f).writerows([HEADER, *responses])
    return path


def _current(snapshot, projects=(), excluded=()):
    current = _copy(snapshot)
    current["projects"] = list(projects)
    current["snapshot"]["excluded_responses"] = list(excluded)
    return current


def _import(path, current):
    return uro.import_export(path, current, snapshot_date="2027-01-12", refresh_due="2027-04-01",
                             valid_until="2027-05-15", contributor="A. Tester")


class TestImporter:
    def test_new_responses_get_an_id_a_clear_contact_and_no_sheet_prose(self, tmp_path, snapshot):
        path = _export(
            tmp_path,
            _response("1/5/2027 9:15:00", "ada@example.edu", "Lovelace", "Prof. Ada",
                      "Email me at ada@example.edu"),
            _response("1/6/2027 10:00:00", "bob@example.edu", "Babbage", "Bob",
                      f"Apply here: {FORM}?usp=sharing&ouid=1234567890."),
            _response("1/7/2027 11:30:05", "dee@example.edu", "Dee", "Dee", "via email"),
            _response("1/8/2027 8:00:00", "cy@example.edu", "Cy", "Cy",
                      "Email me and copy our coordinator, manager@example.edu"),
        )
        new, review = _import(path, _current(snapshot))
        ada, bob, dee, cy = new["projects"]
        assert ada["id"] == uro.project_id("2027-01-05T09:15:00", "ada@example.edu")
        assert (ada["name"], ada["listed_on"], ada["title"]) == ("Ada Lovelace", "2027-01-05", "")
        assert (ada["contact_email"], ada["contact_basis"]) == ("ada@example.edu", "listed_address")
        assert (bob["contact_email"], bob["contact_basis"], bob["application_url"]) == (None, "form", FORM)
        assert (dee["contact_email"], dee["contact_basis"]) == ("dee@example.edu", "respondent_address")
        # Another person's address is never picked: a person decides.
        assert (cy["contact_email"], cy["contact_basis"]) == (None, None)
        assert any("choose the contact route" in line and "manager@example.edu" in line for line in review)
        assert sum("write a short title" in line for line in review) == 4

        text = json.dumps(new)
        for secret in ("SYNOPSIS-NOT-PUBLISHED", "SKILLS-NOT-PUBLISHED", "KEYWORDS-NOT-PUBLISHED",
                       "manager@example.edu", "ouid", "Example College"):
            assert secret not in text
        assert tuple(new["projects"][0]) == uro.ROW_FIELDS
        meta = new["snapshot"]
        assert (meta["snapshot_date"], meta["contributor"]) == ("2027-01-12", "A. Tester")
        assert "4 responses" in meta["captured_from"]

        # It does not validate until a person has written titles and chosen cy's route.
        problems = uro.validate_snapshot(new)
        assert sum("title is empty" in p for p in problems) == 4
        for index, row in enumerate(new["projects"]):
            row["title"] = f"Project {index}"
        cy.update(contact_email="cy@example.edu", contact_basis="respondent_address")
        assert uro.validate_snapshot(new) == []

    def test_a_reviewed_response_keeps_its_entry_while_the_export_still_shows_its_contact(
            self, tmp_path, snapshot):
        reviewed = {"id": uro.project_id("2027-01-05T09:15:00", "ada@example.edu"),
                    "listed_on": "2027-01-05", "name": "Ada King, Countess of Lovelace",
                    "position": "Professor", "department": "Mathematical Sciences",
                    "title": "Reviewed title", "contact_email": "ada@example.edu",
                    "contact_basis": "listed_address", "application_url": None}
        gone = dict(reviewed, id="cmu-uro-000000000000", name="Gone Professor")
        same = _export(tmp_path, _response("1/5/2027 9:15:00", "ada@example.edu", "Lovelace",
                                           "Ada", "ada@example.edu"))
        new, review = _import(same, _current(snapshot, [reviewed, gone]))
        assert new["projects"] == [reviewed]
        assert review == ["cmu-uro-000000000000 (Gone Professor): no longer on the list; "
                          "the next refresh retires it"]

        changed = _export(tmp_path, _response("1/5/2027 9:15:00", "ada@example.edu", "Lovelace",
                                              "Ada", "Please use the form: https://forms.gle/abc"))
        new, review = _import(changed, _current(snapshot, [reviewed]))
        (entry,) = new["projects"]
        assert entry["title"] == "Reviewed title"
        assert (entry["contact_email"], entry["contact_basis"]) == (None, None)
        assert any("its answer changed" in line for line in review)

    def test_an_excluded_response_stays_out(self, tmp_path, snapshot):
        excluded_id = uro.project_id("2027-01-05T09:15:00", "someone@pitt.example")
        path = _export(tmp_path, _response("1/5/2027 9:15:00", "someone@pitt.example", "X", "Y",
                                           "someone@pitt.example"))
        new, review = _import(path, _current(snapshot, excluded=[{"id": excluded_id, "reason": "not CMU"}]))
        assert new["projects"] == []
        assert review == [f"{excluded_id}: skipped, it is in excluded_responses"]

    def test_an_export_without_the_expected_columns_is_refused(self, tmp_path):
        path = tmp_path / "export.csv"
        path.write_text("Timestamp,Email Address,Name\n1/5/2027 9:15:00,a@example.edu,A\n", encoding="utf-8")
        with pytest.raises(uro.SnapshotError, match="last name"):
            uro.read_export(path)

    def test_re_importing_the_same_answers_keeps_every_reviewed_entry(self, tmp_path, snapshot):
        """Every contact route the committed rows use survives the carry-over
        check while the export still shows it. (Ids here are synthetic: the
        snapshot does not keep respondent addresses.)"""
        answers = {"listed_address": "{email}", "respondent_address": "email me",
                   "form": "{link}", "web_page": "{link}",
                   "listed_contacts": "Contact the students named above."}
        reviewed, responses = [], []
        for second, row in enumerate(snapshot["projects"]):
            respondent = row["contact_email"] or f"respondent{second}@example.edu"
            listed = date.fromisoformat(row["listed_on"])
            reviewed.append(row | {"id": uro.project_id(f"{row['listed_on']}T12:00:{second:02d}", respondent)})
            answer = answers[row["contact_basis"]].format(email=row["contact_email"],
                                                          link=row["application_url"])
            responses.append(_response(f"{listed.month}/{listed.day}/{listed.year} 12:00:{second:02d}",
                                       respondent, row["name"], "", answer))
        new, review = _import(_export(tmp_path, *responses), _current(snapshot, reviewed))
        assert new["projects"] == reviewed
        assert review == []

    def test_the_export_must_stay_outside_the_repository(self, capsys):
        args = argparse.Namespace(import_csv=str(uro.PROJECT_ROOT / "export.csv"),
                                  snapshot_date="2027-01-12", refresh_due="2027-04-01",
                                  valid_until="2027-05-15", contributor="A. Tester",
                                  contributor_github=None, sheet_url=None, list_name=None)
        assert uro._import_main(args) == 2
        assert "inside the repository" in capsys.readouterr().err
