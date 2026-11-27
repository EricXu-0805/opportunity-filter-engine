import json
from copy import deepcopy

import pytest
from bs4 import BeautifulSoup

from src.collectors import faculty_graph, ucb_common, vt_aoe
from src.collectors.schools import vt_faculty


def fetched(url, fragment, final=None, day="2026-11-24"):
    page = BeautifulSoup(f"<main>{fragment}</main>", "html.parser")
    return ucb_common._mark_fetched_soup_observation(page, requested_url=url, final_url=final or url,
                                                     observed_at=f"{day}T09:00:00+00:00")


def profile(name, *titles):
    fields = ''.join(f'<div class="vt-bio-title"><div class="vt-person-title">{t}</div></div>' for t in titles)
    return (f'<div class="vt-bio-info"><h1 class="vt-bio-name">{name}</h1>{fields}</div>'
            '<section><h2>Research expertise</h2><div class="vt-person-title">Professor of Flight</div></section>')


def listing(name, path, section):
    return (f'<section><h3>{section}</h3><div class="vt-list-item-wrapper">'
            f'<h4 class="vt-list-item-heading" data-itemtype="bio"><a class="vt-list-item-title-link" '
            f'href="{path}">{name}<span>, bio</span></a></h4></div></section>')


@pytest.mark.parametrize('monthly', [False, True])
def test_read_stated_role_and_current_group_without_affecting_appointment(monkeypatch, tmp_path, monthly):
    dept = next(d for d in vt_faculty.SCHOOL['departments'] if d['short'] == 'AOE')
    monkeypatch.setattr(vt_faculty, 'SCHOOL', {**vt_faculty.SCHOOL, 'departments': [dept]})
    monkeypatch.setattr(faculty_graph, '_PROFILE_ENRICH', monthly)
    monkeypatch.setattr(vt_aoe.time, 'sleep', lambda _: None)
    directory = vt_aoe.DIRECTORY
    pages, calls = {}, []
    database = tmp_path / 'opportunities.json'
    database.write_text('[]')
    monkeypatch.setattr(ucb_common, 'PROCESSED_FILE', database)

    def fetch(url, **_):
        calls.append(url)
        return pages.get(url)

    monkeypatch.setattr(ucb_common, 'fetch_soup', fetch)
    person = 'Jamie (Jay) Roe'
    url = 'https://www.aoe.vt.edu/people/adjunct/roe.html'
    pages[directory] = fetched(directory, listing(person, url, 'Adjunct faculty'))

    def run():
        calls.clear()
        (current,) = vt_faculty.fetch_and_normalize()
        vt_faculty.merge_into_processed([current])
        (saved,) = json.loads(database.read_text())
        assert saved['metadata']['is_active'] is True
        assert saved['metadata']['directory_section'] == 'Adjunct faculty'
        return saved

    pages[url] = fetched(url, profile('Jay Roe', 'Associate Professor'))
    first = run()
    assert calls.count(url) == 1
    old_meta = first['metadata']
    assert old_meta['faculty_title'] == 'Associate Professor'
    assert old_meta['faculty_title_observation'] == {'name': person, 'title': 'Associate Professor', 'source': url,
                                                    'profile': url, 'roster_url': directory, 'checked_on': '2026-11-24'}
    from backend.lib.opportunity_detail import _professor_or_lab

    facts = _professor_or_lab(first, first).build({})
    assert facts['explicit']['faculty_rank'] == 'Associate Professor'
    assert facts['explicit']['faculty_directory_section'] == 'Adjunct faculty'
    assert facts['quotes']['faculty_rank']['source_url'] == url
    assert facts['quotes']['faculty_directory_section']['source_url'] == directory
    changed = deepcopy(first)
    changed['pi_name'] = 'A Second Person'
    assert 'faculty_directory_section' not in _professor_or_lab(changed, first).build({})['explicit']
    del pages[url]
    held = run()['metadata']
    assert held['faculty_title_read_status'] == 'unavailable'
    assert held['faculty_title_observation'] == old_meta['faculty_title_observation']
    for unreadable, destination in [
        ('<title>Just a moment...</title><h1>Checking your browser</h1>', url),
        ('<h1>Sign in</h1><p>Login required to access this resource</p>', 'https://www.aoe.vt.edu/login'),
        ('<section>Temporarily unavailable. Please try later.</section>', url),
    ]:
        pages[url] = fetched(url, unreadable, final=destination, day='2026-11-26')
        held = run()['metadata']
        assert held['faculty_title_read_status'] == 'unavailable'
        assert held['faculty_title'] == 'Associate Professor'
        assert held['faculty_title_observation'] == old_meta['faculty_title_observation']
    pages[url] = fetched(url, profile('Jay Zhang', 'Professor'),
                         final='https://www.aoe.vt.edu/people/faculty/zhang.html', day='2026-11-26')
    reassigned = run()['metadata']
    assert not reassigned['faculty_title'] and 'faculty_title_observation' not in reassigned
    assert reassigned['faculty_title_read_status'] == 'unconfirmed'
    for bad in (profile('Jay Roe'), profile('Jay Zhang', 'Professor'), profile('Jay Roe', 'Professor', 'Scientist'),
                profile('Jay Roe', 'My research interests include another professor’s work')):
        pages[url] = fetched(url, bad)
        current = run()
        assert not current['metadata']['faculty_title']
        assert current['metadata']['faculty_title_read_status'] == 'unconfirmed'
        assert 'faculty_title_observation' not in current['metadata']
    pages[url] = fetched(url, profile('Jay Roe', 'Professor'), final='https://other.vt.edu/roe')
    assert not run()['metadata']['faculty_title']
    pages[url] = fetched(url, profile('Jay Roe', 'Research Scientist'), day='2026-11-27')
    current = run()
    assert current['id'] == first['id'] and current['metadata']['first_seen_at'] == old_meta['first_seen_at']
    assert current['metadata']['faculty_title'] == 'Research Scientist'
    assert current['metadata']['faculty_title_observation']['checked_on'] == '2026-11-27'
    assert current['application'] == first['application']
    historical = deepcopy(current)
    vt_aoe.mark_emeritus(historical, '2026-11-28')
    assert historical['metadata']['directory_section'] == 'Emeritus faculty'
    assert 'faculty_title_read_status' not in historical['metadata']


def test_same_name_two_current_biographies_and_missing_middle_name_are_not_interchangeable(monkeypatch):
    assert vt_aoe._heading_matches('Alex Q. Roe', 'Alex Roe')
    assert not vt_aoe._heading_matches('Alex Q. Roe', 'Alex P. Roe')
    assert not vt_aoe._heading_matches('Alex Dallas Roe', 'Alex Dale Roe')
    obs = vt_aoe.RosterObservation()
    url = 'https://www.aoe.vt.edu/people/faculty/roe.html'
    other = 'https://www.aoe.vt.edu/people/faculty/other.html'
    obs.read(fetched(vt_aoe.DIRECTORY, listing('Alex Roe', url, 'Faculty') + listing('Alex Roe', other, 'Faculty')))
    row = {'id': 'faculty-vt-aoe-original', 'pi_name': 'Alex Roe', 'url': url, 'metadata': {'faculty_title': ''}}
    monkeypatch.setattr(ucb_common, 'fetch_soup', lambda *a, **k: pytest.fail('ambiguous roster destination fetched'))
    obs.update_current_ranks([row])
    assert row['metadata'] == {'faculty_title': ''}
