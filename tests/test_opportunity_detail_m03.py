"""M03: opportunity detail coverage with explicit provenance and fail-closed unknowns.

Every test here is about one of three states — source, inferred, unknown — and
the collapses the brief forbids: unknown → false, unknown → unpaid, unknown →
not eligible, unknown → no deadline, school location → opportunity location,
inferred skill → hard requirement.
"""
from __future__ import annotations

import copy
import json

import pytest
from fastapi.testclient import TestClient

from backend.lib.opportunity_detail import (
    DETAIL_FIELD_NAMES,
    DETAIL_FIELDS_VERSION,
    FIELD_FACETS,
    build_detail_fields,
    unknown_facets,
)
from backend.main import app
from backend.routes import opportunities as opportunities_module
from backend.routes.opportunities import _redact
from scripts.generate_detail_fields_contract import CASES, CONTRACT_PATH, render_contract
from src.collectors import uiuc_sro as sro
from src.collectors.base import RawOpportunity
from src.contact_instructions import CAPTURE_KEY
from src.evidence import (
    inferred_method,
    neutralize_unverified_faculty_claims,
    stamp_collector_templates,
)
from src.matcher.ranker import score_eligibility, score_upside
from src.normalizers.normalizer import normalize

_CASES = dict(CASES)


def _served(record: dict) -> tuple[dict, dict]:
    """(public payload, canonical) exactly as the detail route builds them."""
    canonical = copy.deepcopy(record)
    neutralize_unverified_faculty_claims(canonical)
    stamp_collector_templates(canonical)
    return _redact(canonical), canonical


def _fields(record: dict) -> dict:
    payload, canonical = _served(record)
    return build_detail_fields(payload, canonical)["fields"]


def _listing(**overrides) -> dict:
    base = {
        "id": "m03-listing",
        "source": "duke_research_programs",
        "source_type": "campus_program",
        "source_url": "https://example.edu/p",
        "url": "https://example.edu/p",
        "title": "Program",
        "organization": "Duke University",
        "eligibility": {},
        "application": {},
        "metadata": {"is_active": True, "last_verified": "2026-09-01T00:00:00"},
    }
    base.update(overrides)
    return base


def _where(field: dict, facet: str) -> str:
    in_source = facet in field["explicit"]
    in_inferred = facet in field["inferred"]
    in_unknown = facet in field["unknown"]
    # A facet is unknown only when it is in neither value bucket.
    assert in_unknown == (not in_source and not in_inferred)
    if in_source:
        return "source"
    return "inferred" if in_inferred else "unknown"


# ---------------------------------------------------------------------------
# Envelope shape
# ---------------------------------------------------------------------------

class TestEnvelope:
    def test_every_field_and_facet_is_reported(self):
        detail = build_detail_fields(*_served(_listing()))
        assert detail["version"] == DETAIL_FIELDS_VERSION
        assert tuple(detail["fields"]) == DETAIL_FIELD_NAMES
        for name, field in detail["fields"].items():
            facets = set(field["explicit"]) | set(field["inferred"]) | set(field["unknown"])
            assert facets == set(FIELD_FACETS[name]), name
            assert field["state"] in {"source", "inferred", "unknown"}
            assert set(field["provenance"]) == {"source_url", "observed_at"}

    def test_builder_does_not_mutate_its_inputs(self):
        payload, canonical = _served(_CASES["simplify_internship_template"])
        before = (copy.deepcopy(payload), copy.deepcopy(canonical))
        build_detail_fields(payload, canonical)
        assert (payload, canonical) == before

    def test_rejects_non_dict_inputs(self):
        with pytest.raises(TypeError):
            build_detail_fields([], {})


# ---------------------------------------------------------------------------
# Source-confirmed, inferred, unknown
# ---------------------------------------------------------------------------

class TestThreeStates:
    def test_source_confirmed_field_is_confirmed(self):
        fields = _fields(_CASES["curated_campus_program"])
        assert fields["eligibility"]["state"] == "source"
        assert fields["eligibility"]["explicit"]["majors"] == ["Biology", "Chemistry"]
        assert fields["eligibility"]["explicit"]["international_students"] == "yes"
        assert fields["funding"]["explicit"] == {"paid": "stipend", "compensation": "$5,000"}
        assert fields["timing"]["explicit"]["deadline"] == "2027-02-01"

    def test_inferred_field_is_labeled_inferred_with_a_basis(self):
        fields = _fields(_CASES["stamped_listing"])
        assert fields["funding"]["state"] == "inferred"
        assert fields["funding"]["inferred"]["paid"] == {"value": "yes", "basis": "text_scan"}
        assert fields["eligibility"]["inferred"]["majors"]["basis"] == "text_scan"
        # And never double-counted as a source statement.
        assert "paid" not in fields["funding"]["explicit"]
        assert "majors" not in fields["eligibility"]["explicit"]

    def test_missing_field_is_unknown(self):
        fields = _fields(_CASES["legacy_sparse"])
        for name in DETAIL_FIELD_NAMES:
            assert fields[name]["state"] == "unknown", name
            assert fields[name]["explicit"] == {} and fields[name]["inferred"] == {}

    def test_corpus_spelling_of_unknown_is_unknown(self):
        fields = _fields(_listing(
            paid="unknown", remote_option="unknown",
            eligibility={"international_friendly": "unknown", "preferred_year": ["unknown"]},
        ))
        assert _where(fields["funding"], "paid") == "unknown"
        assert _where(fields["eligibility"], "international_students") == "unknown"
        assert _where(fields["eligibility"], "class_year") == "unknown"
        assert _where(fields["location"], "remote_option") == "unknown"

    def test_unrecognised_stamp_prefix_is_still_an_inference(self):
        record = _listing(paid="yes")
        record["metadata"]["inferred_fields"] = {"paid": "heuristic:new_producer"}
        fields = _fields(record)
        assert _where(fields["funding"], "paid") == "inferred"

    def test_research_areas_keep_explicit_and_inferred_apart(self):
        fields = _fields(_CASES["faculty_profile"])
        research = fields["research_content"]
        assert research["explicit"]["research_areas"] == "Analytical engines; number theory"
        assert research["inferred"]["research_areas"] == {
            "value": ["analytical engines", "number theory"],
            "basis": "external_enrichment",
        }
        assert research["unknown"] == []


# ---------------------------------------------------------------------------
# The forbidden collapses
# ---------------------------------------------------------------------------

class TestNoCollapse:
    def test_unknown_eligibility_is_not_ineligible(self):
        # The template most collectors write when the page is silent:
        # citizenship_required False beside international_friendly unknown.
        fields = _fields(_listing(
            source="ucb_urap_projects", source_type="ucb_program",
            eligibility={"citizenship_required": False, "international_friendly": "unknown"},
        ))
        elig = fields["eligibility"]
        assert _where(elig, "international_students") == "unknown"
        assert _where(elig, "citizenship") == "unknown"
        # Nothing anywhere says "no" or "required".
        assert "no" not in json.dumps(elig["explicit"])

    def test_unknown_eligibility_is_not_ineligible_in_the_ranker(self):
        profile = {"international_student": True, "year": "sophomore", "major": "Biology"}
        unknown = _listing(
            opportunity_type="research",
            eligibility={"citizenship_required": None, "international_friendly": "unknown"},
        )
        restricted = _listing(
            opportunity_type="research",
            eligibility={"citizenship_required": True, "international_friendly": "no"},
        )
        unknown_score, _, unknown_gaps = score_eligibility(profile, unknown)
        restricted_score, _, restricted_gaps = score_eligibility(profile, restricted)
        assert unknown_score > restricted_score
        assert "Requires US citizenship or permanent residency" in restricted_gaps
        assert "Requires US citizenship or permanent residency" not in unknown_gaps

    def test_citizenship_false_counts_only_beside_a_stated_welcome(self):
        stated = _fields(_listing(eligibility={
            "citizenship_required": False, "international_friendly": "yes",
        }))
        assert stated["eligibility"]["explicit"]["citizenship"] == "not_required"
        bare = _fields(_listing(eligibility={"citizenship_required": False}))
        assert _where(bare["eligibility"], "citizenship") == "unknown"

    def test_unknown_funding_is_not_unpaid(self):
        for paid in (None, "", "unknown", "garbage"):
            fields = _fields(_listing(paid=paid))
            assert _where(fields["funding"], "paid") == "unknown", paid
        # The ranker agrees: unknown scores above an explicit "no".
        unknown_score, _, unknown_gaps = score_upside({}, _listing(paid="unknown"))
        unpaid_score, _, _ = score_upside({}, _listing(paid="no"))
        assert unknown_score > unpaid_score
        assert not any("unpaid" in g.lower() for g in unknown_gaps)

    def test_explicit_unpaid_stays_unpaid(self):
        fields = _fields(_listing(source="ucb_urap_projects", source_type="ucb_program", paid="no"))
        assert fields["funding"]["explicit"]["paid"] == "no"

    def test_absent_deadline_is_unknown_not_no_deadline(self):
        # is_rolling=True is Simplify's blanket default and is_rolling=False
        # the faculty default; neither is a statement about deadlines.
        for is_rolling in (True, False, None):
            fields = _fields(_listing(deadline=None, is_rolling=is_rolling))
            assert _where(fields["timing"], "deadline") == "unknown"
            assert _where(fields["timing"], "rolling") == "unknown"

    def test_rolling_needs_a_source_note(self):
        record = _listing(deadline=None)
        record["metadata"]["deadline_note"] = "Rolling admissions through May"
        fields = _fields(record)
        assert fields["timing"]["explicit"]["rolling"] is True

    def test_estimated_deadline_is_inferred(self):
        fields = _fields(_CASES["nsf_reu_policy"])
        assert fields["timing"]["inferred"]["deadline"] == {"value": "2027-02-15", "basis": "estimate"}
        unstamped = _listing(deadline="2027-03-01", deadline_is_estimate=True)
        assert _where(_fields(unstamped)["timing"], "deadline") == "inferred"


class TestLocation:
    def test_school_location_is_not_opportunity_location(self):
        payload, canonical = _served(_CASES["curated_campus_program"])
        fields = build_detail_fields(payload, canonical)["fields"]
        assert _where(fields["location"], "location") == "unknown"
        assert payload["location_attribution"] == "institution"

    def test_faculty_affiliation_is_not_opportunity_location(self):
        payload, canonical = _served(_CASES["faculty_profile"])
        fields = build_detail_fields(payload, canonical)["fields"]
        assert _where(fields["location"], "location") == "unknown"
        assert payload["location_attribution"] == "institution"

    def test_posting_location_is_source(self):
        payload, canonical = _served(_CASES["simplify_internship_template"])
        fields = build_detail_fields(payload, canonical)["fields"]
        assert fields["location"]["explicit"]["location"] == "Seattle, WA"
        assert "location_attribution" not in payload

    def test_campus_fallback_only_is_the_template(self):
        parsed = _fields(_listing(source="ucb_urap_projects", source_type="ucb_program", location="Richmond, CA"))
        fallback = _fields(_listing(source="ucb_urap_projects", source_type="ucb_program", location="Berkeley, CA"))
        assert parsed["location"]["explicit"]["location"] == "Richmond, CA"
        assert _where(fallback["location"], "location") == "unknown"

    def test_award_institution_location_is_inferred(self):
        payload, canonical = _served(_CASES["nsf_reu_policy"])
        fields = build_detail_fields(payload, canonical)["fields"]
        assert fields["location"]["inferred"]["location"]["basis"] == "derived_from_source"
        assert payload["location_attribution"] == "inferred"


class TestSkills:
    def test_inferred_skills_are_never_required(self):
        for name in ("stamped_listing", "simplify_internship_template"):
            skills = _fields(_CASES[name])["required_skills"]
            assert "required" not in skills["explicit"], name
            assert "preferred" not in skills["explicit"], name
            assert skills["inferred"]["mentioned"]["basis"] == "text_scan"

    def test_unstamped_uncurated_skills_are_still_inferred(self):
        # ~2,400 internship skill lists predate the tagger's stamps.
        fields = _fields(_listing(
            source="simplify_internships", source_type="internship",
            eligibility={"skills_required": ["Python"]},
        ))
        assert "required" not in fields["required_skills"]["explicit"]
        assert fields["required_skills"]["inferred"]["mentioned"]["value"] == ["Python"]

    def test_curated_skills_are_required(self):
        fields = _fields(_listing(
            source="manual", source_type="manual",
            eligibility={"skills_required": ["Python"], "skills_preferred": ["R"]},
        ))
        assert fields["required_skills"]["explicit"] == {"required": ["Python"], "preferred": ["R"]}
        assert "mentioned" not in fields["required_skills"]["inferred"]


# ---------------------------------------------------------------------------
# Collector templates and old records
# ---------------------------------------------------------------------------

class TestCollectorTemplates:
    def test_simplify_stipend_is_a_collector_default(self):
        payload, canonical = _served(_CASES["simplify_internship_template"])
        fields = build_detail_fields(payload, canonical)["fields"]
        assert fields["funding"]["inferred"]["paid"] == {"value": "stipend", "basis": "collector_default"}
        assert payload["paid_attribution"] == "inferred"
        assert inferred_method(canonical, "paid") == "default:simplify_feed_has_no_pay_field"

    def test_simplify_stipend_no_longer_claims_includes_stipend(self):
        _, canonical = _served(_CASES["simplify_internship_template"])
        score, fits, _ = score_upside({}, canonical)
        assert "Includes stipend" not in fits
        # The expectation still scores: only the claim is withdrawn.
        stated = _listing(source="duke_research_programs", paid="stipend")
        stated_score, stated_fits, _ = score_upside({}, stated)
        assert "Includes stipend" in stated_fits
        assert score == pytest.approx(stated_score, abs=25)

    def test_template_stamp_never_overrides_and_is_idempotent(self):
        record = copy.deepcopy(_CASES["simplify_internship_template"])
        record["metadata"]["inferred_fields"] = {"paid": "rule:detect_paid_from_text"}
        stamp_collector_templates(record)
        stamp_collector_templates(record)
        assert inferred_method(record, "paid") == "rule:detect_paid_from_text"
        real = copy.deepcopy(_CASES["simplify_internship_template"])
        real["paid"] = "yes"
        stamp_collector_templates(real)
        assert inferred_method(real, "paid") is None

    def test_template_class_years_are_unknown(self):
        for years in (
            ["freshman", "sophomore", "junior", "senior"],
            ["sophomore", "junior", "senior"],
            ["freshman", "sophomore", "junior"],
        ):
            fields = _fields(_listing(eligibility={"preferred_year": years}))
            assert _where(fields["eligibility"], "class_year") == "unknown", years
        stated = _fields(_listing(eligibility={"preferred_year": ["junior", "senior"]}))
        assert stated["eligibility"]["explicit"]["class_year"] == ["junior", "senior"]

    def test_default_effort_and_template_requirements_are_unknown(self):
        fields = _fields(_CASES["simplify_internship_template"])
        app = fields["application_method"]
        assert _where(app, "effort") == "unknown"
        assert _where(app, "requirements") == "unknown"
        assert app["inferred"]["contact_method"]["basis"] == "collector_default"

    def test_nsf_program_element_is_not_a_department(self):
        assert _where(_fields(_CASES["nsf_reu_policy"])["department"], "department") == "unknown"

    def test_company_is_not_a_lab(self):
        fields = _fields(_CASES["simplify_internship_template"])
        assert _where(fields["professor_or_lab"], "lab_or_program") == "unknown"


class TestOldRecordsDegradeSafely:
    @pytest.mark.parametrize("shape", [
        {},
        {"eligibility": None, "application": None, "metadata": None},
        {"eligibility": "open to all", "application": ["x"], "metadata": "m"},
        {"eligibility": {"skills_required": "Python", "majors": [1, None, "CS"]}},
        {"eligibility": {"min_gpa": True}},
        {"deadline": "March 1", "posted_date": 20260101},
    ])
    def test_malformed_legacy_shapes_do_not_crash_or_fabricate(self, shape):
        record = {"id": "m03-legacy", "title": "Legacy", **shape}
        fields = _fields(record)
        assert set(fields) == set(DETAIL_FIELD_NAMES)
        elig = fields["eligibility"]
        assert "min_gpa" not in elig["explicit"]
        assert _where(fields["timing"], "deadline") == "unknown"

    def test_unverified_kind_exposes_no_offer_terms(self):
        # 26 rows carry no source_type; the projector strips their offer terms
        # and the detail model must not read them back off the canonical row.
        record = _listing(
            source_type=None, paid="yes", deadline="2027-01-01", location="Anywhere, USA",
            eligibility={"international_friendly": "yes", "majors": ["CS"]},
            application={"application_url": "https://example.edu/apply"},
        )
        del record["source_type"]
        fields = _fields(record)
        for name in ("funding", "timing", "eligibility", "location", "application_method"):
            assert fields[name]["state"] == "unknown", name

    def test_historical_listing_exposes_no_application_url(self):
        record = _listing(application={"application_url": "https://example.edu/apply"})
        record["metadata"]["urap_status"] = "closed"
        assert _where(_fields(record)["application_method"], "application_url") == "unknown"

    def test_backfill_counter_names_unknown_facets(self):
        detail = build_detail_fields(*_served(_CASES["legacy_sparse"]))
        names = set(unknown_facets(detail))
        assert "funding.paid" in names and "eligibility.international_students" in names


class TestCollectorsStopWritingFalse:
    def test_normalizer_citizenship_is_tri_state(self):
        silent = normalize({"title": "RA", "description_raw": "Help in the lab.", "url": "https://x.edu"})
        stated = normalize({
            "title": "RA", "description_raw": "Must be a U.S. citizen.", "url": "https://x.edu",
        })
        assert silent["eligibility"]["citizenship_required"] is None
        assert stated["eligibility"]["citizenship_required"] is True

    def test_normalizer_stamps_keyword_bank_lists(self):
        # A plain mention is not a requirement (it lands in skill_mentions);
        # only requirement wording fills skills_required, and it is still
        # stamped as the rule's reading, never as the source's own list.
        out = normalize({"title": "RA", "description_raw": "Required: Python and machine learning.", "url": "https://x.edu"})
        assert out["eligibility"]["skills_required"]
        assert inferred_method(out, "eligibility.skills_required") == "rule:opportunity_terms"

    def test_simplify_other_sponsorship_is_unknown_citizenship(self):
        from src.collectors.simplify_internships import _SPONSORSHIP_MAP

        assert _SPONSORSHIP_MAP["Other"][1] is None
        assert _SPONSORSHIP_MAP["Does Not Offer Sponsorship"][1] is None
        assert _SPONSORSHIP_MAP["U.S. Citizenship is Required"][1] is True


# ---------------------------------------------------------------------------
# API ↔ frontend
# ---------------------------------------------------------------------------

_CLIENT = TestClient(app)


class TestApiAndFrontendAgree:
    def test_detail_endpoint_serves_the_same_envelope(self, monkeypatch):
        record = copy.deepcopy(_CASES["curated_campus_program"])
        canonical = copy.deepcopy(record)
        neutralize_unverified_faculty_claims(canonical)
        stamp_collector_templates(canonical)
        monkeypatch.setattr(
            opportunities_module, "load_opportunities_by_id", lambda: {canonical["id"]: canonical},
        )
        monkeypatch.setattr(
            opportunities_module, "release_visible_opportunity_by_id",
            lambda by_id, oid: by_id.get(oid),
        )
        response = _CLIENT.get(f"/api/opportunities/{canonical['id']}")
        assert response.status_code == 200, response.text
        body = response.json()
        expected = build_detail_fields(_redact(canonical), canonical)
        assert body["detail_fields"] == expected
        assert body["location_attribution"] == "institution"

    def test_committed_contract_matches_the_backend(self):
        # Regenerate with: python scripts/generate_detail_fields_contract.py
        assert CONTRACT_PATH.read_text(encoding="utf-8") == render_contract()


# ---------------------------------------------------------------------------
# Listing collectors wired to the contract: uiuc_sro
# ---------------------------------------------------------------------------
# The collector's own fetch and record builder, then the detail route. A
# check of 20 live SRO detail pages on 2026-10-09 found every one a labelled
# record (Sponsoring Institution, Location, Deadline, Duration, Compensation,
# Citizenship Requirement) that main left unknown or read out of keyword
# windows.


def _detail(record: dict) -> tuple[dict, dict]:
    payload, canonical = _served(record)
    return payload, build_detail_fields(payload, canonical)["fields"]


# --- uiuc_sro ---------------------------------------------------------------

_SRO_LIST = "https://researchops.web.illinois.edu/?page=0"
_SRO_DETAIL = "https://researchops.web.illinois.edu/opportunity/example-reu"
_SRO_LINK = "https://reu.example.edu/"


def _sro_field(name: str, label: str, *items: str, hidden: bool = False) -> str:
    if hidden:
        return (f'<div class="block"><div class="field field--name-field-{name} '
                f'field--label-hidden field__item">{items[0]}</div></div>')
    inner = "".join(f'<div class="field__item">{item}</div>' for item in items)
    return (f'<div class="block"><div class="field field--name-field-{name} field--label-inline clearfix">'
            f'<div class="field__label">{label}</div>{inner}</div></div>')


def _sro_detail_html(*, citizenship="US Citizen, National, or Permanent Resident required",
                     compensation="$7,000", deadline=("deadline-date", "3/15/27"), anticipated="Yes",
                     body="<p>Students join a faculty lab for ten weeks.</p>",
                     heading="<h3>Eligibility Requirements</h3>", hidden_link=_SRO_LINK, extra="") -> str:
    link = f'<a href="{_SRO_LINK}">{_SRO_LINK}</a>'
    first = [
        _sro_field("link-to-opportunity", "Link to Opportunity", link),
        _sro_field("contact-email", "Contact Email(s)", '<a href="mailto:reu@example.edu">reu@example.edu</a>'),
    ]
    second = [
        _sro_field("link-to-opportunity", "", f'<a href="{hidden_link}">{hidden_link}</a>', hidden=True),
        _sro_field("sponsoring-institution", "Sponsoring Institution", "Example State University"),
        _sro_field("location", "Location", "Springfield, IL"),
        _sro_field("timing", "Timing", "Summer"),
        _sro_field(deadline[0], "Deadline", deadline[1]),
        _sro_field("deadline-anticipated", "Anticipated Deadline?", anticipated) if anticipated else "",
        _sro_field("research-area", "Research Area", "Natural Sciences", "Science &amp; Technology"),
        _sro_field("duration", "Duration", "10 weeks"),
        _sro_field("compensation", "Compensation", compensation) if compensation else "",
        _sro_field("citizenship-requirement", "Citizenship Requirement", citizenship) if citizenship else "",
    ]
    footer = ('<div class="views-element-container"><div class="views-row"><em class="views-field '
              'views-field-changed"><span class="views-label views-label-changed">This opportunity was '
              'last updated on </span><span class="field-content"><time datetime="2026-03-15T19:16:46-05:00" '
              'class="datetime">3/15/26</time></span></em></div></div>')
    return (f'<html><head><title>Example REU | Undergraduate Research Opportunities</title></head><body><main>'
            f'<article><h1>Example REU</h1><div class="field--name-body">{heading}{body}</div>'
            f'{"".join(first)}<div class="layout__region--second">{"".join(second)}</div>{extra}</article>'
            f'{footer}</main></body></html>')


def _sro_list_html(deadline="Anticipated 3/2/27") -> str:
    return (
        '<html><body><table class="views-table"><tbody><tr>'
        '<td class="views-field views-field-title"><strong><a href="/opportunity/example-reu">Example REU</a>'
        '</strong><br>Students join a faculty lab.</td>'
        '<td class="views-field views-field-field-research-area">Natural Sciences, Science &amp; Technology</td>'
        '<td class="views-field views-field-field-timing">Summer</td>'
        f'<td class="views-field views-field-field-deadline-anticipated views-field-nothing">{deadline}</td>'
        '</tr></tbody></table></body></html>'
    )


def _sro_response(html: str, url: str):
    class Response:
        text = html
        content = html.encode()

        def raise_for_status(self):
            return None

    response = Response()
    response.url = url
    return response


def _sro_fetch(monkeypatch, detail_html: str | None, *, list_html: str | None = None) -> dict:
    """One list page, one detail page, through the collector's own fetch path."""
    empty = '<html><body><table class="views-table"><tbody></tbody></table></body></html>'

    def get(url, **kwargs):
        if url.endswith("?page=0"):
            return _sro_response(list_html or _sro_list_html(), url)
        if "?page=" in url:
            return _sro_response(empty, url)
        if detail_html is None:
            raise TimeoutError("detail page down")
        return _sro_response(detail_html, url)

    monkeypatch.setattr(sro.requests, "get", get)
    monkeypatch.setattr(sro, "DEEP_SCRAPE_DELAY", 0)
    monkeypatch.setattr(sro.UIUCSROCollector, "_rate_limit", lambda self: None)
    records, _ = sro.fetch_and_normalize_with_evidence(deep=True)
    assert len(records) == 1
    return records[0]


class TestUiucSroContract:
    def test_detail_page_fields_are_read_as_the_page_states_them(self, monkeypatch):
        record = _sro_fetch(monkeypatch, _sro_detail_html())
        assert record["metadata"][CAPTURE_KEY]["status"] == "captured"
        payload, fields = _detail(record)
        assert fields["school"]["explicit"] == {"institution": "Example State University"}
        assert fields["location"]["explicit"] == {"location": "Springfield, IL"}
        assert "location_attribution" not in payload
        assert fields["timing"]["inferred"]["deadline"] == {"value": "2027-03-15", "basis": "estimate"}
        assert fields["timing"]["explicit"]["application_window"] == "3/15/27 (anticipated)"
        assert fields["timing"]["explicit"]["duration"] == "Summer (10 weeks)"
        assert fields["funding"]["explicit"] == {"paid": "yes", "compensation": "$7,000"}
        elig = fields["eligibility"]
        assert elig["explicit"]["citizenship"] == "required"
        assert elig["explicit"]["work_authorization_notes"] == "US Citizen, National, or Permanent Resident required"
        assert elig["inferred"]["international_students"] == {"value": "no", "basis": "derived_from_source"}
        assert fields["research_content"]["explicit"]["research_areas"] == ["Natural Sciences", "Science & Technology"]
        assert fields["application_method"]["explicit"]["application_url"] == _SRO_LINK
        # Every fact is on the detail page; the list page it was found on
        # moves as rows are added and states none of the detail fields.
        checked = record["metadata"]["last_verified"]
        assert checked
        for name in ("school", "eligibility", "funding", "timing", "research_content"):
            assert fields[name]["provenance"] == {"source_url": _SRO_DETAIL, "observed_at": checked}, name

    def test_capture_accepts_the_structured_page(self):
        result = sro.UIUCSROCollector._capture_detail_html(
            _sro_detail_html(), source_url=_SRO_DETAIL, checked_at="2026-10-09T00:00:00+00:00",
        )
        assert result["status"] == "captured"
        sections = result["sources"][0]["sections"]
        assert any(s["heading"].endswith("Citizenship Requirement") for s in sections)

    @pytest.mark.parametrize("variant", ["unlabelled_condition", "hidden_link_differs"])
    def test_capture_still_refuses_what_it_cannot_place(self, variant):
        html = (_sro_detail_html(extra="<div>Applicants must be U.S. citizens.</div>")
                if variant == "unlabelled_condition"
                else _sro_detail_html(hidden_link="https://other.example.edu/apply"))
        result = sro.UIUCSROCollector._capture_detail_html(html, source_url=_SRO_DETAIL)
        assert result["status"] == "unsupported"

    def test_rolling_free_text_deadline(self, monkeypatch):
        record = _sro_fetch(monkeypatch, _sro_detail_html(deadline=("deadline-free-text", "Rolling"), anticipated=""))
        _, fields = _detail(record)
        assert fields["timing"]["explicit"]["rolling"] is True
        assert _where(fields["timing"], "deadline") == "unknown"

    def test_no_requirement_beside_a_restriction_is_unknown(self, monkeypatch):
        record = _sro_fetch(monkeypatch, _sro_detail_html(
            citizenship="No Citizenship Requirements",
            body="<p>Most program funding is restricted to U.S. citizens and permanent residents.</p>",
        ))
        _, fields = _detail(record)
        assert _where(fields["eligibility"], "citizenship") == "unknown"
        assert _where(fields["eligibility"], "international_students") == "unknown"
        assert fields["eligibility"]["explicit"]["work_authorization_notes"] == "No Citizenship Requirements"

    def test_no_requirement_is_stated_not_required(self, monkeypatch):
        record = _sro_fetch(monkeypatch, _sro_detail_html(citizenship="No Citizenship Requirements"))
        _, fields = _detail(record)
        assert fields["eligibility"]["explicit"]["citizenship"] == "not_required"
        assert fields["eligibility"]["inferred"]["international_students"]["value"] == "yes"

    def test_pay_without_a_compensation_field_is_a_text_scan(self, monkeypatch):
        record = _sro_fetch(monkeypatch, _sro_detail_html(
            compensation="", body="<p>Participants receive a stipend and housing.</p>",
        ))
        payload, fields = _detail(record)
        assert fields["funding"]["inferred"]["paid"] == {"value": "yes", "basis": "text_scan"}
        assert _where(fields["funding"], "compensation") == "unknown"
        assert payload["paid_attribution"] == "inferred"

    def test_list_row_anticipated_deadline_is_an_estimate(self):
        raw = RawOpportunity(
            source="uiuc_sro", source_url=_SRO_LIST, title="Example REU", description_raw="",
            url=_SRO_DETAIL, extra_fields={"research_area": "Natural Sciences", "timing": "Summer",
                                           "deadline_raw": "Anticipated 3/2/27"},
        )
        record = sro.raw_to_normalized(raw)
        assert record["deadline"] == "2027-03-02" and record["deadline_is_estimate"] is True
        _, fields = _detail(record)
        assert fields["timing"]["inferred"]["deadline"]["basis"] == "estimate"
        assert fields["timing"]["explicit"]["application_window"] == "3/2/27 (anticipated)"

    def test_list_only_refresh_keeps_the_detail_facts(self, monkeypatch, tmp_path):
        before = _sro_fetch(monkeypatch, _sro_detail_html())
        incoming = _sro_fetch(monkeypatch, None, list_html=_sro_list_html(deadline=""))
        path = tmp_path / "records.json"
        path.write_text(json.dumps([before]))
        sro.merge_into_processed([incoming], str(path))
        saved = json.loads(path.read_text())[0]
        for key in ("organization", "location", "duration", "deadline", "deadline_is_estimate",
                    "compensation_details", "eligibility", "application"):
            assert saved[key] == before[key], key
        assert saved["metadata"]["deadline_note"] == before["metadata"]["deadline_note"]
        assert saved["metadata"]["last_verified"] == before["metadata"]["last_verified"]

    def test_legacy_record_degrades_without_a_rescrape(self):
        # The shape every SRO row has on main: found on a list page, notes
        # assembled from keyword windows, pay and intl read by keyword scan.
        legacy = _listing(
            id="sro-legacy", source="uiuc_sro", source_type="summer_program",
            source_url=_SRO_LIST, url=_SRO_DETAIL, organization="", location="",
            keywords=["Natural Sciences"], duration="Summer",
            eligibility={
                "citizenship_required": False, "international_friendly": "yes",
                "work_auth_notes": "weeks Compensation $7,000 Citizenship Requirement No Citize | Citizenship Re",
            },
        )
        _, fields = _detail(legacy)
        elig = fields["eligibility"]
        assert elig["explicit"]["citizenship"] == "not_required"
        assert elig["inferred"]["international_students"]["basis"] == "derived_from_source"
        assert _where(elig, "work_authorization_notes") == "unknown"
        assert fields["research_content"]["explicit"]["research_areas"] == ["Natural Sciences"]
        assert fields["eligibility"]["provenance"]["source_url"] == _SRO_DETAIL
