import json
from copy import deepcopy

from bs4 import BeautifulSoup

from src.collectors import jhu_neuroscience, ucb_common
from src.collectors.schools import jhu_faculty
from src.evidence import source_last_seen_at, source_verified_at

SETH = "faculty-jhu-som-ba3abad3"
ERNST = "faculty-jhu-som-fa1fa91f"
JEREMY = "faculty-jhu-som-893e6408"


def _card(profile, name, section, title):
    return (
        f'<li data-type="{section}"><div class="infocontainer"><span class="name">{name}, PhD</span>'
        f'<span>Position: {title}</span></div><a href="/research/faculty/{profile}"></a></li>'
    )


def _page(*cards):
    soup = BeautifulSoup(f'<ul class="facultylist">{"".join(cards)}</ul>', "html.parser")
    return ucb_common._mark_fetched_soup_observation(
        soup, requested_url=jhu_neuroscience.ROSTER, final_url=jhu_neuroscience.ROSTER,
    )


def _profile(url, name, title):
    soup = BeautifulSoup(
        f'<meta property="og:title" content="{name}"><div class="textcontentcontainer">'
        f'<p class="subtitle">{title}</p></div>', "html.parser",
    )
    return ucb_common._mark_fetched_soup_observation(soup, requested_url=url, final_url=url)


def test_department_observation_survives_failed_read_and_yields_to_restored_primary(monkeypatch, tmp_path):
    som = next(d for d in jhu_faculty.SCHOOL["departments"] if d["short"] == "SOM")
    monkeypatch.setattr(jhu_faculty, "SCHOOL", {**jhu_faculty.SCHOOL, "departments": [som]})
    path = tmp_path / "corpus.json"
    monkeypatch.setattr(ucb_common, "PROCESSED_FILE", path)
    path.write_text("[]")
    adjunct = _card(7, "Seth Blackshaw", "Adjunct", "Adjunct Professor of Neuroscience; Professor of Ophthalmology")
    primary = _card(62, "Ernst Niebur", "Primary", "Professor of Neuroscience<br/>Director of Admissions")
    secondary = _card(9, "Jeremy Nathans", "Secondary", "Professor of Molecular Biology and Genetics")
    soup = _page(adjunct, primary, secondary)
    profile_name = "Seth Blackshaw"
    seth_title = "Adjunct Professor of Neuroscience; Professor of Ophthalmology"

    def fetch(url, **kwargs):
        if url == jhu_neuroscience.ROSTER:
            return (ucb_common._mark_fetched_soup_observation(soup, requested_url=url, final_url=url)
                    if soup is not None else None)
        if url.endswith("/7"):
            return _profile(url, profile_name, seth_title) if profile_name else None
        return _profile(url, "Ernst Niebur", "Professor of Neuroscience<br/>Director of Admissions")

    monkeypatch.setattr(ucb_common, "fetch_soup", fetch)

    def refresh():
        ledger = {}
        rows = jhu_faculty.fetch_and_normalize(deep=True, unit_ledger=ledger)
        assert ledger["som"]["live_roster_count"] == sum(source_last_seen_at(r) is not None for r in rows)
        assert ledger["som"]["live_roster_count"] + ledger["som"]["retained_only_count"] == len(rows)
        jhu_faculty.merge_into_processed(rows)
        return {r["id"]: r for r in json.loads(path.read_text())}

    first = refresh()
    assert sum(source_last_seen_at(row) is not None for row in first.values()) == 2
    assert first[SETH]["metadata"]["faculty_title"] == "Adjunct Professor of Neuroscience"
    assert first[ERNST]["metadata"]["faculty_title"] == "Professor of Neuroscience"
    assert source_last_seen_at(first[JEREMY]) is None
    assert source_verified_at(first[SETH]) is None
    receipt = first[SETH]["metadata"]["faculty_title_observation"]
    assert receipt["profile"] == first[SETH]["url"] == f"{jhu_neuroscience.ROSTER}/7"
    assert receipt["source"] == jhu_neuroscience.ROSTER
    assert first[SETH]["source_url"] == first[SETH]["url"]
    second = refresh()
    assert second.keys() == first.keys()
    assert second[SETH]["metadata"]["first_seen_at"] == first[SETH]["metadata"]["first_seen_at"]
    assert source_last_seen_at(second[SETH]) > source_last_seen_at(first[SETH])
    soup = None
    failed = refresh()
    assert failed[SETH] == second[SETH]
    assert source_last_seen_at(failed[JEREMY]) is None

    soup = _page(adjunct)
    profile_name = ""
    assert refresh()[SETH] == second[SETH]
    profile_name = "Someone Else"
    contradicted = refresh()[SETH]
    assert "faculty_title_observation" not in contradicted["metadata"]
    assert contradicted["metadata"]["faculty_title"] == ""
    assert contradicted["url"].endswith("/seth-blackshaw/2777521")
    soup = None
    assert refresh()[SETH]["metadata"]["faculty_title"] == ""

    soup = _page(_card(7, "Seth Blackshaw", "Primary", "Professor of Neuroscience"))
    profile_name = "Seth Blackshaw"
    seth_title = "Professor of Neuroscience"
    restored = refresh()[SETH]
    assert restored["metadata"]["faculty_title"] == "Professor of Neuroscience"
    assert restored["metadata"]["faculty_title_observation"]["section"] == "Primary"
    assert "Adjunct" not in restored["description_clean"]
    assert restored["metadata"]["first_seen_at"] == first[SETH]["metadata"]["first_seen_at"]


def test_observation_requires_both_reviewed_identities_and_one_consistent_card(monkeypatch):
    row = {"id": SETH, "pi_name": "Seth Blackshaw", "source": "jhu_faculty",
           "url": "https://profiles.hopkinsmedicine.org/provider/seth-blackshaw/2777521",
           "department": jhu_neuroscience.DEPARTMENT, "metadata": {"faculty_title": "Professor of Neuroscience"}}
    correct = _card(7, "Seth Blackshaw", "Primary", "Professor of Neuroscience")
    for soup in (
        _page(correct, correct), _page(_card(7, "Someone Else", "Primary", "Professor of Neuroscience")),
        _page(_card(9, "Seth Blackshaw", "Primary", "Professor of Neuroscience")),
        _page(_card(7, "Seth Blackshaw", "Secondary", "Professor of Ophthalmology")),
        _page(_card(7, "Seth Blackshaw", "Adjunct", "Professor of Neuroscience")),
    ):
        candidate = deepcopy(row)
        monkeypatch.setattr(ucb_common, "fetch_soup", lambda url, page=soup: page)
        jhu_neuroscience.observe([candidate])
        assert candidate["url"] == row["url"]
        assert "faculty_title_observation" not in candidate["metadata"]
        assert source_last_seen_at(candidate) is None
    another_unit = {**row, "id": "faculty-jhu-bsph-3ec22da2"}
    monkeypatch.setattr(ucb_common, "fetch_soup", lambda url: _page(correct))
    jhu_neuroscience.observe([another_unit])
    assert "faculty_title_observation" not in another_unit["metadata"]
