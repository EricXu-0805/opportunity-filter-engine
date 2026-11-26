from copy import deepcopy

from bs4 import BeautifulSoup

from backend.lib.opportunity_detail import build_detail_fields
from backend.lib.public_opportunity_detail import project_public_detail
from src.collectors import faculty_graph as fg
from src.collectors import ucb_common
from src.collectors.schools.uva_faculty import SCHOOL
from src.collectors.uiuc_faculty import _carry_forward_enrichment
from src.evidence import stamp_inferred

DEPT = next(d for d in SCHOOL["departments"] if d["short"] == "BIOL")
INDEX = DEPT["research_join"]["url"]
PROFILE = "https://bio.as.virginia.edu/people/avery-sample"
OBSERVED = "2026-11-26T10:30:00+00:00"


def card(name, link, area):
    return (f'<div class="views-row"><div class="views-field-field-intro-text"><div class="field-content">{area}'
            f'</div></div><div class="views-field-field-pi">PI: <a href="{link}">{name}</a></div></div>')


def capture(monkeypatch, cards, final=INDEX):
    soup = BeautifulSoup(f'<div class="research-blocks">{cards}</div>', "html.parser")
    ucb_common._mark_fetched_soup_observation(soup, requested_url=INDEX, final_url=final, observed_at=OBSERVED)
    monkeypatch.setattr(ucb_common, "fetch_soup", lambda _url: soup)


def person(**extra):
    return fg.faculty("Avery Sample", title="Professor", url=PROFILE, **extra)


def normalized(spec):
    return fg._normalize(SCHOOL, DEPT, spec)


def test_identity_requires_same_link_and_name_and_projects_the_source_only_on_research(monkeypatch):
    item = card("Avery Sample", "/people/avery-sample", "Cell shape and development")
    unrelated = card("Robin Example", "/people/another", "Plant growth")
    capture(monkeypatch, unrelated + item)
    target, prior = person(), person(research_areas="An existing individual statement")
    fg._apply_research_join(DEPT, [target, prior])
    assert prior["research_areas"] == "An existing individual statement"
    original = normalized(target)
    field = build_detail_fields(project_public_detail(original), original)["fields"]
    assert field["research_content"]["explicit"]["research_areas"] == "Cell shape and development"
    assert field["research_content"]["provenance"] == {"source_url": INDEX, "observed_at": OBSERVED}
    assert field["department"]["provenance"]["source_url"] == PROFILE
    for invalid in (card("Casey Sample", "/people/avery-sample", "Other person"),
                    card("Avery Sample", "/people/other", "Other profile"),
                    card("Avery Sample", "https://other.example/people/avery-sample", "Different host"),
                    item + card("Avery Sample", "/people/avery-sample", "Conflicting second card")):
        capture(monkeypatch, invalid)
        candidate = person()
        fg._apply_research_join(DEPT, [candidate])
        assert not candidate["research_areas"]


def test_failed_reads_preserve_dated_source_and_successful_removal_withdraws_only_its_facts(monkeypatch):
    capture(monkeypatch, card("Avery Sample", PROFILE, "Cell development"))
    target = person()
    fg._apply_research_join(DEPT, [target])
    stored = normalized(target)
    # Redirects and failed reads carry the previous observation without dating it anew.
    capture(monkeypatch, card("Avery Sample", PROFILE, "Other"), final="https://example.com/")
    checked = person()
    fg._apply_research_join(DEPT, [checked])
    failed = normalized(checked)
    _carry_forward_enrichment(stored, failed)
    assert failed["metadata"]["research_areas_raw"] == "Cell development"
    assert failed["metadata"]["research_areas_source_url"] == INDEX
    assert failed["metadata"]["research_areas_verified_at"] == OBSERVED
    rebound = normalized(fg.faculty("Different Person", url=PROFILE))
    _carry_forward_enrichment(stored, rebound)
    assert not rebound["metadata"]["research_areas_raw"] and not rebound["keywords"]
    updated_area = "Development across a wide range of tissues and the recovery of damaged cells"
    capture(monkeypatch, card("Avery Sample", PROFILE, updated_area))
    updated = person()
    fg._apply_research_join(DEPT, [updated])
    updated = normalized(updated)
    _carry_forward_enrichment(stored, updated)
    assert updated["metadata"]["research_areas_raw"] == updated_area
    assert not updated["keywords"]
    # A complete index now describes a different person. The earlier summary and its
    # derived keywords must not come back through the regular merge.
    capture(monkeypatch, card("Another Person", "/people/another", "Elsewhere"))
    checked = person()
    fg._apply_research_join(DEPT, [checked])
    current = normalized(checked)
    _carry_forward_enrichment(stored, current)
    assert not current["metadata"]["research_areas_raw"] and not current["keywords"]
    assert "research_areas_source_url" not in current["metadata"]
    independent = deepcopy(stored)
    independent["keywords"] = ["protein geometry", "cell recognition"]
    stamp_inferred(independent["metadata"], "keywords", "derived:openalex_topics")
    fresh = normalized(checked)
    _carry_forward_enrichment(independent, fresh)
    assert fresh["keywords"] == independent["keywords"]
    assert not fresh["metadata"]["research_areas_raw"]
