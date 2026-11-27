import json

from bs4 import BeautifulSoup

from src.collectors import faculty_graph
from src.collectors.schools.casewestern_faculty import SCHOOL

ANTH = next(unit for unit in SCHOOL["departments"] if unit["short"] == "ANTH")
GOLDSTEIN = "faculty-casewestern-anth-363b4aa1"
PROFILE = "https://anthropology.case.edu/emeriti/melvyn-c-goldstein"


def card(name, url, title):
    return (
        '<div class="directory-row"><div class="directory-data">'
        f'<a href="{url}">{name}</a></div><div class="directory-data">{title}</div>'
        '<div class="directory-data"></div></div>'
    )


def test_anthropology_emeriti_with_other_roles_keep_saved_id_on_return(tmp_path, monkeypatch):
    retired = card("Melvyn C. Goldstein", PROFILE, "Distinguished University Professor; Co-Director")
    current = card("Janet McGrath", "/faculty/janet-mc-grath", "Professor and Chair of Anthropology")
    adjacent = card("Lee Hoffer", "/faculty/lee-hoffer", "Professor of Anthropology and Psychiatry")
    active = f"<h3>Faculty</h3>{current}<h3>Secondary Faculty</h3>{adjacent}"
    observed = active + "<h3>Emeriti Faculty</h3>" + retired
    monkeypatch.setattr("src.collectors.ucb_common.fetch_soup", lambda *_a, **_kw:
                        BeautifulSoup(observed, "html.parser") if observed else None)
    path = tmp_path / "opportunities.json"
    monkeypatch.setattr("src.collectors.ucb_common.PROCESSED_FILE", path)
    archived = {"id": GOLDSTEIN, "metadata": {"first_seen_at": "2020-01-01", "is_active": False,
                                             "deactivation_reason": "retired_title"}}
    path.write_text(json.dumps([archived]))

    def refresh():
        rows = [faculty_graph._normalize(SCHOOL, ANTH, person)
                for person in faculty_graph._scrape_directory(ANTH)]
        faculty_graph.merge_into_processed(rows)
        return {row["pi_name"] for row in rows}

    for _ in range(2):
        assert refresh() == {"Janet McGrath", "Lee Hoffer"}
    observed = ""
    assert refresh() == set()
    assert next(r for r in json.loads(path.read_text()) if r["id"] == GOLDSTEIN) == archived

    # The same URL also occurs in the active group, as on a returning appointment.
    observed = active.replace(current, current + retired) + "<h3>Emeriti Faculty</h3>" + retired
    assert refresh() == {"Janet McGrath", "Lee Hoffer", "Melvyn C. Goldstein"}
    [restored] = [r for r in json.loads(path.read_text()) if r["id"] == GOLDSTEIN]
    assert restored["metadata"]["is_active"] is True
    assert restored["metadata"]["first_seen_at"] == "2020-01-01"
    assert "deactivation_reason" not in restored["metadata"]
