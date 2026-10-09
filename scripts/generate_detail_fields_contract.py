"""Generate the M03 detail-fields contract shared by the API and the frontend.

Each case is a canonical corpus record run through the real detail-route
projection (``backend.routes.opportunities._redact``) and then
``build_detail_fields`` — the exact path ``GET /opportunities/{id}`` takes. The
output is committed at ``frontend/src/lib/detail-fields.contract.json``:

* ``tests/test_opportunity_detail_m03.py`` regenerates it and fails on drift,
  so a backend semantics change cannot land without the fixture moving too;
* ``frontend/src/lib/detail-fields.contract.test.tsx`` renders every case and
  asserts each facet shows the state the server assigned — so the page cannot
  show "Source says" where the API said inferred, or a value where it said
  unknown.

Run from the repo root:  python scripts/generate_detail_fields_contract.py
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

CONTRACT_PATH = _REPO / "frontend" / "src" / "lib" / "detail-fields.contract.json"

_SEEN = "2026-09-01T00:00:00"

CASES: list[tuple[str, dict]] = [
    (
        # A configured campus program (campus_graph spec): majors, class years,
        # an intl welcome and a pay value typed into the collector config —
        # ours, not the page's — beside the host school's city in `location`.
        "curated_campus_program",
        {
            "id": "contract-campus-1",
            "source": "duke_research_programs",
            "source_type": "campus_program",
            "source_url": "https://example.edu/programs/surf",
            "url": "https://example.edu/programs/surf",
            "title": "Summer Undergraduate Research Fellowship",
            "organization": "Duke University",
            "department": "Biology",
            "lab_or_program": "SURF",
            "location": "Durham, NC",
            "remote_option": "unknown",
            "paid": "stipend",
            "compensation_details": "$5,000",
            "deadline": "2027-02-01",
            "keywords": ["biology", "undergraduate research"],
            "eligibility": {
                "preferred_year": ["sophomore", "junior"],
                "majors": ["Biology", "Chemistry"],
                "skills_required": [],
                "skills_preferred": [],
                "citizenship_required": False,
                "international_friendly": "yes",
                "work_auth_notes": "",
            },
            "application": {
                "contact_method": "website",
                "requires_resume": "unknown",
                "application_effort": "medium",
                "application_url": "https://example.edu/programs/surf/apply",
            },
            "metadata": {
                "is_active": True,
                "last_verified": _SEEN,
                "last_seen_at": _SEEN,
                "deadline_note": "Applications reviewed on a rolling basis",
            },
        },
    ),
    (
        # The Simplify template: a defaulted "stipend", the three-year class
        # list, tagger-written skills without a stamp, a derived intl "no"
        # from the sponsorship enum, and a location read off the posting.
        "simplify_internship_template",
        {
            "id": "contract-simplify-1",
            "source": "simplify_internships",
            "source_type": "internship",
            "source_url": "https://jobs.example.com/123",
            "url": "https://jobs.example.com/123",
            "title": "Software Engineering Intern",
            "organization": "ExampleCorp",
            "department": "",
            "lab_or_program": "ExampleCorp",
            "location": "Seattle, WA",
            "remote_option": "unknown",
            "paid": "stipend",
            "compensation_details": "",
            "deadline": None,
            "is_rolling": True,
            "posted_date": "2026-08-20",
            "duration": "Summer 2027",
            "keywords": ["software engineering"],
            "eligibility": {
                "preferred_year": ["sophomore", "junior", "senior"],
                "majors": ["Computer Science"],
                "skills_required": ["Python", "Java"],
                "skills_preferred": [],
                "citizenship_required": None,
                "international_friendly": "no",
                "work_auth_notes": "Employer does not offer visa sponsorship.",
            },
            "application": {
                "contact_method": "online",
                "requires_resume": "yes",
                "application_effort": "medium",
                "application_url": "https://jobs.example.com/123",
            },
            "metadata": {"is_active": True, "last_verified": _SEEN},
        },
    ),
    (
        # NSF REU: program-policy pay, intl and citizenship; an estimated
        # deadline; the award start date; the awardee's city.
        "nsf_reu_policy",
        {
            "id": "contract-nsf-1",
            "source": "nsf_reu",
            "source_type": "summer_program",
            "source_url": "https://www.nsf.gov/awardsearch/showAward?AWD_ID=1",
            "url": "https://www.nsf.gov/awardsearch/showAward?AWD_ID=1",
            "title": "REU: Materials Science",
            "organization": "Example State University",
            "department": "REU Sites",
            "lab_or_program": "Materials Science REU",
            "pi_name": "Jane Doe",
            "location": "Springfield, IL",
            "remote_option": "no",
            "paid": "yes",
            "compensation_details": "NSF-funded stipend (typically $6,000-$7,000 for 10 weeks)",
            "deadline": "2027-02-15",
            "deadline_is_estimate": True,
            "start_date": "2026-06-01",
            "duration": "Summer (8-10 weeks)",
            "keywords": ["materials science"],
            "eligibility": {
                "preferred_year": ["freshman", "sophomore", "junior"],
                "majors": ["Physics"],
                "skills_required": [],
                "skills_preferred": [],
                "citizenship_required": True,
                "international_friendly": "no",
            },
            "application": {
                "contact_method": "online",
                "requires_resume": "yes",
                "application_effort": "medium",
                "application_url": "https://example.edu/reu/apply",
            },
            "metadata": {
                "is_active": True,
                "last_verified": _SEEN,
                "inferred_fields": {
                    "paid": "policy:nsf_reu_solicitation",
                    "deadline": "estimate:award_start_date",
                    "eligibility.international_friendly": "policy:nsf_reu_solicitation",
                    "eligibility.citizenship_required": "policy:nsf_reu_solicitation",
                },
            },
        },
    ),
    (
        # A tagger-stamped listing: skills and majors read out of prose, a pay
        # value read out of "in many cases, funding or a stipend".
        "stamped_listing",
        {
            "id": "contract-stamped-1",
            "source": "uiuc_sro",
            "source_type": "summer_program",
            "source_url": "https://example.edu/sro/1",
            "url": "https://example.edu/sro/1",
            "title": "Summer Research Opportunity",
            "organization": "University of Illinois",
            "location": "",
            "paid": "yes",
            "keywords": ["chemistry"],
            "eligibility": {
                "preferred_year": ["unknown"],
                "majors": ["Chemistry"],
                "skills_required": ["MATLAB"],
                "skills_preferred": ["MATLAB"],
                "citizenship_required": None,
                "international_friendly": "unknown",
            },
            "application": {"contact_method": "online", "application_url": "https://example.edu/sro/1/apply"},
            "metadata": {
                "is_active": True,
                "last_verified": _SEEN,
                "inferred_fields": {
                    "eligibility.skills_required": "rule:keyword_bank",
                    "eligibility.skills_preferred": "rule:keyword_bank",
                    "eligibility.majors": "rule:sro_research_area_bank",
                    "paid": "rule:detect_paid_from_text",
                },
            },
        },
    ),
    (
        # A faculty directory profile: identity and research text are the
        # page's; every offer term is unknown; location is the campus city.
        "faculty_profile",
        {
            "id": "contract-faculty-1",
            "source": "umich_faculty",
            "source_type": "faculty_research",
            "source_url": "https://example.edu/people/ada",
            "url": "https://example.edu/people/ada",
            "title": "Ada Lovelace",
            "organization": "University of Michigan",
            "department": "Mathematics",
            "lab_or_program": "",
            "pi_name": "Ada Lovelace",
            "location": "Ann Arbor, MI",
            "paid": "unknown",
            "keywords": ["analytical engines", "number theory"],
            "eligibility": {
                "preferred_year": ["unknown"],
                "majors": [],
                "skills_required": [],
                "skills_preferred": [],
                "citizenship_required": None,
                "international_friendly": "unknown",
            },
            "application": {"contact_method": "email", "application_url": None},
            "metadata": {
                "is_active": True,
                "last_verified": _SEEN,
                "faculty_title": "Professor",
                "research_areas_raw": "Analytical engines; number theory",
                "inferred_fields": {"keywords": "derived:openalex_topics"},
            },
        },
    ),
    (
        # An SRO row read off its labelled detail page: sponsor, location,
        # citizenship field, compensation and an anticipated deadline, found
        # on the paginated list but stated on the detail page.
        "sro_structured_listing",
        {
            "id": "contract-sro-1",
            "source": "uiuc_sro",
            "source_type": "summer_program",
            "source_url": "https://researchops.web.illinois.edu/?page=3",
            "url": "https://researchops.web.illinois.edu/opportunity/example-reu",
            "title": "Example REU",
            "organization": "Example State University",
            "department": "",
            "lab_or_program": "Example REU",
            "location": "Springfield, IL",
            "remote_option": "unknown",
            "paid": "yes",
            "compensation_details": "$7,000",
            "deadline": "2027-03-15",
            "deadline_is_estimate": True,
            "is_rolling": False,
            "duration": "Summer (10 weeks)",
            "keywords": ["Natural Sciences", "Science & Technology"],
            "eligibility": {
                "preferred_year": ["freshman", "sophomore", "junior", "senior"],
                "majors": ["Physics"],
                "skills_required": [],
                "skills_preferred": [],
                "citizenship_required": True,
                "international_friendly": "no",
                "work_auth_notes": "US Citizen, National, or Permanent Resident required",
            },
            "application": {
                "contact_method": "online",
                "requires_resume": "unknown",
                "application_effort": "medium",
                "application_url": "https://reu.example.edu/",
            },
            "metadata": {
                "is_active": True,
                "last_verified": _SEEN,
                "deadline_note": "3/15/27 (anticipated)",
                "inferred_fields": {"eligibility.majors": "rule:research_area_bank"},
            },
        },
    ),
    (
        # A legacy row with almost nothing on it, and malformed sub-objects.
        "legacy_sparse",
        {
            "id": "contract-legacy-1",
            "source": "manual",
            "source_type": "manual",
            "title": "Legacy row",
            "organization": "",
            "eligibility": ["not", "a", "dict"],
            "application": "apply by email",
            "metadata": {"is_active": True},
        },
    ),
]


def build_contract() -> dict:
    """Run every case through the real detail-route projection."""
    from backend.lib.opportunity_detail import (
        DETAIL_FIELD_NAMES,
        DETAIL_FIELDS_VERSION,
        FIELD_FACETS,
        build_detail_fields,
    )
    from backend.routes.opportunities import _redact
    from src.evidence import neutralize_unverified_faculty_claims, stamp_collector_templates

    cases = []
    for name, record in CASES:
        canonical = copy.deepcopy(record)
        # What the loader does to every served record.
        neutralize_unverified_faculty_claims(canonical)
        stamp_collector_templates(canonical)
        payload = _redact(canonical)
        cases.append({
            "name": name,
            "detail_fields": build_detail_fields(payload, canonical),
            "location_attribution": payload.get("location_attribution"),
            "paid_attribution": payload.get("paid_attribution"),
        })
    return {
        "_generated_by": "scripts/generate_detail_fields_contract.py",
        "version": DETAIL_FIELDS_VERSION,
        "field_names": list(DETAIL_FIELD_NAMES),
        "field_facets": {k: list(v) for k, v in FIELD_FACETS.items()},
        "cases": cases,
    }


def render_contract() -> str:
    return json.dumps(build_contract(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main() -> int:
    CONTRACT_PATH.write_text(render_contract(), encoding="utf-8")
    print(f"wrote {CONTRACT_PATH.relative_to(_REPO)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
