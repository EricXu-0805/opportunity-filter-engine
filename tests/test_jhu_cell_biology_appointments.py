import json

from bs4 import BeautifulSoup

from src.collectors import jhu_cell_biology, ucb_common
from src.collectors.schools import jhu_faculty
from src.evidence import source_last_seen_at, source_verified_at
from src.normalizers.deactivate_stale_faculty import deactivate_retired_title_faculty

PETER = "faculty-jhu-som-11652663"
MIKE = "faculty-jhu-som-30d887bb"
OTHER = "faculty-jhu-som-b7693f4f"
PETER_URL = "https://cellbio.jhmi.edu/people/peter-n-devreotes-ph-d/"
MIKE_URL = "https://cellbio.jhmi.edu/people/michael-piacentino-ph-d/"


def test_roster_identity_title_outages_and_return_to_primary(monkeypatch, tmp_path):
    som = next(d for d in jhu_faculty.SCHOOL["departments"] if d["short"] == "SOM")
    monkeypatch.setattr(jhu_faculty, "SCHOOL", {**jhu_faculty.SCHOOL, "departments": [som]})
    path = tmp_path / "corpus.json"
    monkeypatch.setattr(ucb_common, "PROCESSED_FILE", path)
    path.write_text("[]")
    faculty = {PETER_URL: ["Peter N. Devreotes", "Named Professor / Director Emeritus / Distinguished Service Professor",
                           "primary-faculty"],
               MIKE_URL: ["Michael Piacentino", "Assistant Professor", "primary-faculty"]}
    missing = set()
    changed_name = False
    duplicate = False
    challenge = False

    def fetch(url, **kwargs):
        if url in missing:
            return None
        if url == jhu_cell_biology.ROSTER:
            markup = ""
            for link, (name, title, section) in faculty.items():
                card = (f'<div class="pendari_people_grid_item {section}"><div class="info">'
                        f'<h3><a href="{link}">{name}, Ph.D.</a></h3>'
                        f'<div class="title">{title}</div></div></div>')
                markup += card
                if duplicate and link == MIKE_URL:
                    markup += card
            if challenge:
                markup = "<html><title>One moment, please...</title></html>"
        elif url in faculty:
            name, title, _ = faculty[url]
            if changed_name and url == MIKE_URL:
                name = "Other Person"
            markup = f'<h1>{name}, Ph.D.</h1><div class="person-page"><div class="title">{title}</div></div>'
        else:
            return None
        return ucb_common._mark_fetched_soup_observation(
            BeautifulSoup(markup, "html.parser"), requested_url=url, final_url=url)

    monkeypatch.setattr(ucb_common, "fetch_soup", fetch)

    def read(count):
        ledger = {}
        fetched = jhu_faculty.fetch_and_normalize(unit_ledger=ledger)
        assert ledger["som"]["live_roster_count"] == count
        assert ledger["som"]["retained_only_count"] == len(fetched) - count
        jhu_faculty.merge_into_processed(fetched)
        rows = json.loads(path.read_bytes())
        deactivate_retired_title_faculty(rows)
        path.write_text(json.dumps(rows))
        return {r["id"]: r for r in rows}

    first = read(2)
    assert first[MIKE]["metadata"]["faculty_title"] == "Assistant Professor"
    assert "x.com/" not in first[MIKE]["description_clean"]
    assert first[PETER]["metadata"]["faculty_title"] == "Named Professor"
    assert first[PETER]["metadata"]["is_active"]
    assert source_verified_at(first[PETER]) is None
    assert source_last_seen_at(first[OTHER]) is None
    # A reused source URL or opportunity ID cannot turn a different person into this verified faculty member.
    suspect = dict(first[MIKE], pi_name="Other Person", url="https://profiles.hopkinsmedicine.org/provider/michael-piacentino/2777533")
    assert jhu_cell_biology.observe([suspect]) == 0
    missing.add(MIKE_URL)
    second = read(1)
    assert second[MIKE] == first[MIKE]
    assert source_last_seen_at(second[PETER]) > source_last_seen_at(first[PETER])
    missing.clear()
    challenge = True
    assert read(0)[PETER] == second[PETER]
    challenge = False
    duplicate = True
    assert read(1)[MIKE] == first[MIKE]
    duplicate = False
    changed_name = True
    mismatch = read(1)[MIKE]
    assert not mismatch["metadata"]["faculty_title"]
    assert source_last_seen_at(mismatch) == source_last_seen_at(first[MIKE])
    changed_name = False
    faculty[MIKE_URL][1:] = ["Professor Emeritus", "faculty-emeritus-emerita"]
    retired = read(2)[MIKE]
    assert retired["metadata"]["is_active"] is False
    assert retired["metadata"]["faculty_title"] == "Professor Emeritus"
    faculty[MIKE_URL][1:] = ["Professor", "primary-faculty"]
    restored = read(2)[MIKE]
    assert restored["metadata"]["is_active"] and restored["url"] == MIKE_URL
    assert restored["metadata"]["first_seen_at"] == first[MIKE]["metadata"]["first_seen_at"]
