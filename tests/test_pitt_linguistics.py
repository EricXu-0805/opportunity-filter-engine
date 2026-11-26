import pytest
from bs4 import BeautifulSoup

from src.collectors import faculty_graph, ucb_common
from src.collectors.schools.pitt_faculty import SCHOOL

LING = next(unit for unit in SCHOOL["departments"] if unit["short"] == "LING")


@pytest.mark.parametrize("with_person_address", [True, False])
def test_monthly_directory_keeps_each_person_when_their_footer_names_the_department(monkeypatch, with_person_address):
    directory = LING["directory_url"]
    names = [("Melinda Fricke", "melinda-fricke"), ("Amanda Huensch", "amanda-huensch")]
    roster = "<main>" + "".join(
        f'<div class="views-row"><div class="views-field-title"><strong class="field-content">'
        f'<a href="/people/{slug}">{name}</a></strong></div></div>'
        for name, slug in names
    ) + "</main>"
    def read(url, **_kwargs):
        if url == directory:
            return BeautifulSoup(roster, "html.parser")
        name, slug = next((n, s) for n, s in names if url.endswith(s))
        personal = f'<a href="mailto:{slug}@example.edu">Email</a>' if with_person_address else ""
        return BeautifulSoup(f'<h1>{name}</h1><div class="views-field-field-email">{personal}</div>'
                             '<footer><a href="mailto:ling-office@example.edu">Contact our department</a></footer>',
                             "html.parser")

    monkeypatch.setattr(ucb_common, "fetch_soup", read)
    monkeypatch.setattr(faculty_graph, "_PROFILE_ENRICH", True)
    monkeypatch.setattr(faculty_graph.time, "sleep", lambda _seconds: None)
    ledger = {}
    result = faculty_graph.fetch_and_normalize({**SCHOOL, "departments": [LING]}, deep=True, unit_ledger=ledger)
    assert ledger["ling"]["live_roster_count"] == ledger["ling"]["observed_count"] == len(result) == 2
    assert [r["id"] for r in result] == ["faculty-pitt-ling-de044035", "faculty-pitt-ling-00c04191"]
    assert [r["contact_email"] for r in result] == (
        ["melinda-fricke@example.edu", "amanda-huensch@example.edu"] if with_person_address else [None, None]
    )


def test_department_footer_from_a_previous_monthly_run_cannot_be_carried_or_revealed():
    from backend.lib.contact_visibility import verified_send_target
    from src.collectors.uiuc_faculty import _carry_forward_enrichment

    prior = faculty_graph._normalize(SCHOOL, LING, {
        "name": "Melinda Fricke", "title": "Associate Professor", "url": "https://www.linguistics.pitt.edu/people/melinda-fricke",
    })
    incoming = {**prior, "metadata": prior["metadata"].copy()}
    prior["contact_email"] = "LingPitt@pitt.edu"
    assert verified_send_target(prior) == ""
    _carry_forward_enrichment(prior, incoming)
    assert not incoming.get("contact_email")
    assert faculty_graph._clean_email("mailto:lingpitt@pitt.edu") is None
    assert faculty_graph._clean_email("mailto:lingpitt@another.edu") == "lingpitt@another.edu"
    assert faculty_graph._clean_email("mailto:lingpitt2@pitt.edu") == "lingpitt2@pitt.edu"
