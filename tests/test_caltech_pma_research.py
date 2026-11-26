from copy import deepcopy
from datetime import UTC, datetime, timedelta

import pytest

from backend.lib.opportunity_detail import build_detail_fields
from backend.lib.public_opportunity_detail import project_public_detail
from src.collectors.lab_website import collect_lab_snapshot
from src.lab_context import reviewed_profile_policy

URL = "https://www.pma.caltech.edu/people/example"
RECORD = {
    "id": "faculty-caltech-phys-example", "school": "caltech", "source": "caltech_faculty",
    "source_type": "faculty_research", "department": "Physics", "pi_name": "Example Person",
    "source_url": URL, "url": URL, "metadata": {"is_active": True, "last_verified": "2026-01-03"},
}
PROFILE = """<main id="content" class="person-page2"><div class="width-1440-container">
<h1 class="sr-only">Example Person</h1>{body}</div></main>"""
OVERVIEW = """<section class="block-PersonProfileBlock"><div class="person-page2__profile-block">
<div class="person-page2__profile-block__profile profile-text"><div class="rich-text">
<h4><b>Research Interests:</b></h4><ul>
<li><a href="/papers/example">Quantum topology</a> (<b>we are</b> <a href="/jobs">hiring!</a>)</li>
<li>Representation (theory)</li>
<li>Quantum invariants (see Math. J. 29, 2020, 2040003)</li></ul>
<h4>Seminars</h4><ul><li>Unrelated event</li></ul></div></div></div></section>"""
SUMMARY = """<section class="block-PersonPageAttributeBlock">
<div class="person-page2__field field__research_summary">
<h4>Research Interest: Precision optics and quantum measurement</h4></div></section>"""


def read_profile(record, html, now):
    def fetch(url):
        assert url == URL
        return {"requested_url": url, "source_url": url, "html": html.encode()}, None
    return collect_lab_snapshot(record, now=now, fetch=fetch)


@pytest.mark.parametrize(("body", "topics"), [
    (OVERVIEW, ["Quantum topology", "Representation (theory)", "Quantum invariants"]),
    (SUMMARY, ["Precision optics and quantum measurement"]),
])
def test_source_bound_topics_in_normal_detail_and_complete_excerpts(body, topics):
    record = deepcopy(RECORD)
    now = datetime.now(UTC) - timedelta(minutes=1)
    record["metadata"].update(read_profile(record, PROFILE.format(body=body), now))
    detail = project_public_detail(record)
    assert detail["lab_context"]["status"] == "available"
    assert detail["research_areas"] == topics
    fields = build_detail_fields(detail, record)["fields"]["research_content"]
    assert fields["explicit"]["research_areas"] == ", ".join(topics)
    assert fields["provenance"] == {"source_url": URL, "observed_at": record["metadata"]["lab_snapshot"]["checked_at"]}
    assert "research_areas" not in record
    if body == OVERVIEW:
        sections = detail["lab_context"]["snapshot"]["pages"][0]["sections"]
        assert [item["text"] for item in sections] == [
            "Quantum topology (we are hiring!)", "Representation (theory)",
            "Quantum invariants (see Math. J. 29, 2020, 2040003)",
        ]
        assert "Unrelated event" not in str(detail)


@pytest.mark.parametrize("change", [
    lambda html: PROFILE.format(body=SUMMARY.replace("Precision optics", "<nav>Department links</nav>")),
    lambda html: html.replace("</ul>\n<h4>Seminars", "</ul>Covered only until last year.<h4>Seminars"),
    lambda html: html.replace("<h4>Seminars", "<p>Only during one term</p><h4>Seminars"),
    lambda html: html.replace("Research Interests:", "Former Research Interests:"),
    lambda html: html.replace("<li>Representation (theory)", "<li><section>Outside block</section>"),
    lambda html: html.replace("<h1 class=", "<h1>Second record</h1><h1 class="),
])
def test_changed_source_layout_cannot_mint_topics(change):
    patch = read_profile(deepcopy(RECORD), change(PROFILE.format(body=OVERVIEW)), datetime.now(UTC))
    assert "lab_snapshot" not in patch


def test_source_identity_age_and_privacy_gate_the_detail_fact():
    now = datetime.now(UTC) - timedelta(minutes=2)
    record = deepcopy(RECORD)
    old = read_profile(record, PROFILE.format(body=OVERVIEW), now - timedelta(days=31))
    record["metadata"].update(old)
    assert "research_areas" not in project_public_detail(record)
    record["metadata"].update(read_profile(record, PROFILE.format(body=OVERVIEW), now))
    mismatch = read_profile(record, PROFILE.format(body=SUMMARY).replace("Example Person", "Other Person"), now + timedelta(seconds=1))
    assert mismatch["lab_refresh"]["reason"] == "identity_mismatch"
    record["metadata"].update(mismatch)
    record["metadata"].update(collect_lab_snapshot(record, now=now + timedelta(seconds=2), fetch=lambda _: (None, "request_failed")))
    assert "research_areas" not in project_public_detail(record)
    private = PROFILE.format(body=SUMMARY.replace("Precision optics", "private@example.edu"))
    record["metadata"].update(read_profile(record, private, now + timedelta(seconds=3)))
    assert "research_areas" not in project_public_detail(record)


@pytest.mark.parametrize("patch", [{"department": "Mathematics"}, {"source": "other_faculty"},
                                    {"school": "other"}, {"url": "https://www.pma.caltech.edu/people/changed"},
                                    {"url": "https://other.caltech.edu/people/example",
                                     "source_url": "https://other.caltech.edu/people/example"}])
def test_only_reviewed_binding_is_eligible(patch):
    assert reviewed_profile_policy({**RECORD, **patch}) is None
