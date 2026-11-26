from bs4 import BeautifulSoup

from src.collectors import faculty_graph, ncsu_chass
from src.collectors.schools import ncsu_faculty


def person(slug, name, groups):
    by_slug = {identity[0]: wp_id for wp_id, identity in ncsu_chass.REVIEWED_PROFILES.items()}
    return {"id": by_slug.get(slug, -1), "title": {"rendered": name}, "link": f"https://chass.ncsu.edu/people/{slug}/", "group": groups}


def card(row, name, title):
    return f'<div class="person-card"><a class="name" href="{row["link"]}">{name}</a><p class="title">{title}</p></div>'


def test_chass_compares_taxonomy_name_and_rank_before_filtering(monkeypatch):
    retired = person("msdarrah", "Michele Darrah", [11847, 11872])
    concurrent = person("kestewa4", "Katharine Stewart", [11847, 11927])
    second_group = person("smk", "Susan Katz", [11847, 11869, 11937])
    name_conflict = person("sample", "Michael Smith", [11847, 11869])
    name_conflict["id"] = -2
    monkeypatch.setitem(ncsu_chass.REVIEWED_PROFILES, -2, ("sample", "Michael Smith"))
    active = person("core", "Current Colleague", [11847])
    rows = [retired, concurrent, second_group, name_conflict, active]
    html = ''.join([card(retired, 'Michele Darrah', 'Emerita Senior Lecturer'),
                    card(concurrent, 'Katharine Stewart', 'Professor and Vice Provost Emeritus'),
                    card(second_group, 'Susan Katz', 'Associate Professor Emerita'),
                    card(name_conflict, 'James Smith', 'Emeritus')])
    monkeypatch.setattr(faculty_graph, '_wp_get_json', lambda url: rows)
    monkeypatch.setattr(ncsu_chass.ucb_common, 'fetch_soup',
                        lambda url, **kw: BeautifulSoup(html, 'html.parser'))
    coverage = faculty_graph._new_coverage()
    monkeypatch.setattr(faculty_graph, '_ACTIVE_COVERAGE', coverage)
    dept = next(d for d in ncsu_faculty.SCHOOL['departments'] if d['short'] == 'CHASS')
    assert dept['api']['filter_records'] is ncsu_chass.current_faculty
    assert dept['api']['query'].endswith('&orderby=id&order=asc')
    assert dept['roster_is_partial']
    assert {spec['name'] for spec in faculty_graph._fetch_wp_api(dept)} == {
        'Katharine Stewart', 'Susan Katz', 'Current Colleague',
    }
    assert coverage['classified_nonfaculty_rows'] == coverage['ambiguous_rows'] == 1
    assert coverage['raw_roster_rows'] == 5

    html = html.replace('Emerita Senior Lecturer', 'Teaching Professor')
    assert 'Michele Darrah' in {spec['name'] for spec in faculty_graph._fetch_wp_api(dept)}


def test_chass_unreadable_or_duplicate_card_preserves_previous_state(monkeypatch):
    candidate = person('msdarrah', 'Michele Darrah', [11847, 11872])
    current = person('active', 'Active Faculty', [11847])
    real_card = card(candidate, 'Michele Darrah', 'Emerita Senior Lecturer')
    for html in (None, '', real_card + real_card):
        roster = BeautifulSoup(html, 'html.parser') if html is not None else None
        monkeypatch.setattr(ncsu_chass.ucb_common, 'fetch_soup', lambda url, roster=roster, **kw: roster)
        coverage = faculty_graph._new_coverage()
        monkeypatch.setattr(faculty_graph, '_ACTIVE_COVERAGE', coverage)
        assert ncsu_chass.current_faculty([candidate, current]) == [current]
        assert coverage['unparsed_rows'] == 1
        assert coverage['classified_nonfaculty_rows'] == 0


def test_removing_retirement_term_or_changing_the_name_alone_does_not_reopen(monkeypatch):
    target = person('msdarrah', 'Michele Darrah', [11847])
    for name, title in [('Michele Darrah', 'Emerita Senior Lecturer'), ('Michele Darrah', 'Faculty'),
                        ('New Person', 'Assistant Professor')]:
        roster = BeautifulSoup(card(target, name, title), 'html.parser')
        monkeypatch.setattr(ncsu_chass.ucb_common, 'fetch_soup', lambda url, result=roster, **kw: result)
        assert ncsu_chass.current_faculty([target]) == []


def test_bradens_preferred_name_can_restore_only_his_confirmed_appointment(monkeypatch):
    target = person('jpbraden', 'Jeffery Braden', [11847, 11927])
    dept = next(d for d in ncsu_faculty.SCHOOL['departments'] if d['short'] == 'CHASS')
    monkeypatch.setattr(faculty_graph, '_wp_get_json', lambda url: [target])

    def observe(display, rank):
        html = BeautifulSoup(card(target, display, rank), 'html.parser')
        monkeypatch.setattr(ncsu_chass.ucb_common, 'fetch_soup', lambda url, **kw: html)
        return faculty_graph._fetch_wp_api(dept)

    assert observe('Jeff Braden', 'Dean and Professor Emeritus') == []
    assert observe('Different Braden', 'Professor') == []
    target['group'] = [11847]
    assert observe('Jeff Braden', 'Dean and Professor Emeritus') == []
    for cms_name in ('Jeffery Braden', 'Jeff Braden'):
        target['title'] = {'rendered': cms_name}
        returned, = observe('Jeff Braden', 'Professor')
        row = faculty_graph._normalize(ncsu_faculty.SCHOOL, dept, returned)
        assert row['id'] == 'faculty-ncsu-chass-089a76c8'
        assert row['metadata']['is_active']
