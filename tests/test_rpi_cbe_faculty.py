from bs4 import BeautifulSoup

from src.collectors import faculty_graph, ucb_common
from src.collectors.schools.rpi_faculty import SCHOOL


def test_cbe_reads_ranked_faculty_cards_and_keeps_reviewed_id(monkeypatch):
    def card(name, slug, rank):
        return (
            '<div class="profile-card card">'
            f'<div class="profile-card-name"><a href="https://faculty.rpi.edu/{slug}">{name}</a></div>'
            f'<div class="profile-card-title">{rank}</div></div>'
        )

    html = (
        '<h2>Faculty</h2>'
        + card('Nihat Baysal', 'nihat-baysal', 'Professor of Practice')
        + card('Missing Rank', 'missing', '')
        + '<h2>Affiliated Faculty</h2>' + card('Joint Member', 'joint', 'Professor')
        + '<h2>Emeritus</h2>' + card('Former Member', 'former', 'Professor Emeritus')
    )
    monkeypatch.setattr(ucb_common, 'fetch_soup', lambda *_args, **_kw: BeautifulSoup(html, 'html.parser'))
    dept = next(d for d in SCHOOL['departments'] if d['short'] == 'CBE')
    people = faculty_graph._scrape_directory(dept)
    assert [p['name'] for p in people] == ['Nihat Baysal']
    row = faculty_graph._normalize(SCHOOL, dept, people[0])
    assert row['id'] == 'faculty-rpi-cbe-331484da'
    assert row['url'] == 'https://faculty.rpi.edu/nihat-baysal'
    assert row['metadata']['faculty_title'] == 'Professor of Practice'
