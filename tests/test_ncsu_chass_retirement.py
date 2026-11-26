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


def test_reviewed_public_names_keep_the_same_id_when_reappointed(monkeypatch):
    dept = next(d for d in ncsu_faculty.SCHOOL['departments'] if d['short'] == 'CHASS')
    cases = [
        ('mehasket', 'Mary E Haskett', 'Mary Haskett', 'dcb028fb', 11927),
        ('mershon', 'Donald H. Mershon', 'Donald Mershon', 'ff4905cc', 11927),
        ('wpshaw', 'William Shaw', 'William Shaw PhD', '38b191e6', 11869),
        ('peblank', 'Philip Blank', 'Philip Blank Jr', '1894dc04', 11869),
        ('dbgreene', 'David Greene', 'David Greene Jr', '165fe06b', 11967),
        ('pond', 'Samuel Pond', 'Samuel Pond III', 'd8c4ba8d', 11927),
        ('jnwall', 'John N Wall', 'John Wall', '98436171', 11869),
        ('mjohnson', 'Melissa A. Johnson', 'Melissa Johnson', 'acb2eb75', 11866),
        ('ronczaja', 'Ron Czaja', 'Ronald Czaja', '825124c2', 11945),
        ('pmccall', 'Patty McCall', 'Patricia McCall', '8874c982', 11945),
        ('rsmoog', 'Bob Moog', 'Robert Moog', 'd8305216', 11936),
        ('mlsalsta', 'Louise Salstad', 'M Salstad', '49e38fb4', 11872),
        ('wwbarnha', 'Wilton Barnhardt', 'William Barnhardt', 'f779aad1', 11869),
        ('ryoung', 'RV Young', 'Robert Young Jr', '84e6cecc', 11869),
        ('mpc', 'Mike Carter', 'Michael Carter', 'b1612d52', 11869),
        ('penrose', 'Nancy Penrose', 'Ann Penrose', '98d2e744', 11869),
        ('jwclark', 'Jim Clark', 'James Clark Jr', '34b13b74', 11869),
        ('grimwood', 'Michael Grimwood', 'James Grimwood', '0ed45fbe', 11869),
        ('cwarren', 'Cat Warren', 'Catherine Warren', '5148f03d', 11869),
        ('rblarson', 'Bob Larson', 'Robert Larson', 'fbcc8754', 11866),
    ]
    rows = [person(slug, full, [11847, term]) for slug, full, _, _, term in cases]
    monkeypatch.setattr(faculty_graph, '_wp_get_json', lambda url: rows)

    def observe(rank):
        source = ''.join(card(r, display, rank) for r, (_, _, display, _, _) in zip(rows, cases, strict=True))
        roster = BeautifulSoup(source, 'html.parser')
        monkeypatch.setattr(ncsu_chass.ucb_common, 'fetch_soup', lambda url, **kw: roster)
        return faculty_graph._fetch_wp_api(dept)

    assert observe('Emeritus') == []
    for row, (_, _, display, _, _) in zip(rows, cases, strict=True):
        row['group'] = [11847]
        row['title'] = {'rendered': display}
    listed = observe('Professor')
    assert {faculty_graph._normalize(ncsu_faculty.SCHOOL, dept, r)['id'] for r in listed} == {
        'faculty-ncsu-chass-' + suffix for _, _, _, suffix, _ in cases
    }


def test_funkhousers_former_deanship_retires_only_his_reviewed_post(monkeypatch):
    target = person('edwardt', 'Edward Funkhouser', [11847, 11866])
    rank = 'Former Associate Professor & Associate Dean'
    roster = BeautifulSoup(card(target, 'Edward Funkhouser', rank), 'html.parser')
    monkeypatch.setattr(ncsu_chass.ucb_common, 'fetch_soup', lambda url, **kw: roster)
    assert ncsu_chass.current_faculty([target]) == []
    assert ncsu_chass.RETIRED_TITLES_BY_POST.get(ncsu_chass.BRADEN_POST) != rank

    roster.select_one('.title').string = 'Professor'
    target['group'] = [11847]
    assert ncsu_chass.current_faculty([target]) == [target]


def test_live_chass_rank_is_bound_to_one_named_card_and_survives_only_an_outage(monkeypatch):
    target = person("cynthia", "Cynthia Hyman", [11847])
    dept = next(d for d in ncsu_faculty.SCHOOL["departments"] if d["short"] == "CHASS")
    monkeypatch.setitem(ncsu_faculty.SCHOOL, "departments", [dept])
    monkeypatch.setattr(faculty_graph, "_wp_get_json", lambda url: [target])
    monkeypatch.delenv("OFE_ENRICH_PROFILES", raising=False)

    def fetch(html):
        roster = BeautifulSoup(html, "html.parser") if html is not None else None
        monkeypatch.setattr(ncsu_chass.ucb_common, "fetch_soup", lambda *_args, **_kwargs: roster)
        row, = ncsu_faculty.fetch_and_normalize()
        return row

    old = fetch(card(target, "Cynthia Hyman", "Senior Lecturer"))
    assert old["metadata"]["faculty_title"] == "Senior Lecturer"
    evidence = old["metadata"]["faculty_title_observation"]
    assert evidence["source"] == ncsu_chass.FACULTY_URL and evidence["profile"] == target["link"]
    outage = fetch(None)
    ncsu_chass.retain_unread_title(old, outage)
    assert outage["metadata"]["faculty_title_observation"] == evidence
    other = fetch(None)
    other["url"] = "https://chass.ncsu.edu/people/someone-else/"
    ncsu_chass.retain_unread_title(old, other)
    assert not other["metadata"]["faculty_title"]

    for rejected in (
        card(target, "Another Person", "Professor"),
        card(target, "Cynthia Hyman", "Professor Emerita"),
        card(target, "Cynthia Hyman", "Visiting Professor"),
        card(target, "Cynthia Hyman", "Professor") * 2,
        card(target, "Cynthia Hyman", "Professor") + card(target, "Cynthia Hyman", "").replace('<p class="title"></p>', ""),
    ):
        current = fetch(rejected)
        ncsu_chass.retain_unread_title(old, current)
        assert not current["metadata"]["faculty_title"]
    promoted = fetch(card(target, "Cynthia Hyman", "Teaching Professor"))
    assert promoted["id"] == old["id"]
    assert promoted["metadata"]["faculty_title"] == "Teaching Professor"


def test_active_rank_name_variant_requires_the_reviewed_post_profile_and_spelling(monkeypatch):
    post, (slug, canonical_name, alias) = next(
        (k, v) for k, v in ncsu_chass.CURRENT_RANK_NAME_VARIANTS.items() if v[1] == "Victoria J. Gallagher"
    )
    target = person(slug, canonical_name, [11847])
    target["id"] = post
    dept = next(d for d in ncsu_faculty.SCHOOL["departments"] if d["short"] == "CHASS")
    monkeypatch.setitem(ncsu_faculty.SCHOOL, "departments", [dept])
    monkeypatch.setattr(faculty_graph, "_wp_get_json", lambda _url: [target])
    monkeypatch.delenv("OFE_ENRICH_PROFILES", raising=False)

    def fetch(display, title):
        roster = BeautifulSoup(card(target, display, title), "html.parser")
        monkeypatch.setattr(ncsu_chass.ucb_common, "fetch_soup", lambda *_args, **_kwargs: roster)
        row, = ncsu_faculty.fetch_and_normalize()
        return row

    for wp_name, public_name in [(canonical_name, alias), (alias, alias), (alias, canonical_name)]:
        target["title"] = {"rendered": wp_name}
        row = fetch(public_name, "Teaching Professor")
        assert row["id"] == "faculty-ncsu-chass-c0cf55cb"
        assert row["metadata"]["faculty_title"] == "Teaching Professor"
        observation = row["metadata"]["faculty_title_observation"]
        assert observation["cms_post_id"] == post and observation["directory_name"] == public_name

    target["title"] = {"rendered": canonical_name}
    assert not fetch("Victoria K. Gallagher", "Professor")["metadata"]["faculty_title"]
    assert not fetch(alias, "Professor Emerita")["metadata"]["faculty_title"]

    target["id"] = -99
    assert not fetch(alias, "Professor")["metadata"]["faculty_title"]
    target["id"] = post
    target["link"] = "https://chass.ncsu.edu/people/different-profile/"
    assert not fetch(alias, "Professor")["metadata"]["faculty_title"]


def test_reviewed_profile_mismatch_restores_only_with_an_observed_named_rank():
    from copy import deepcopy

    original = {
        "id": "faculty-ncsu-chass-existing", "url": "https://chass.ncsu.edu/people/example/",
        "pi_name": "A Teacher", "metadata": {
            "is_active": False, "deactivation_reason": "profile_identity_mismatch",
            "last_seen_at": "2026-07-01", "faculty_title": "Professor",
        },
    }
    recent_url = "https://chass.ncsu.edu/people/new-profile/"
    current = {
        "id": original["id"], "url": recent_url, "pi_name": original["pi_name"],
        "metadata": {"is_active": True, "last_seen_at": "2026-11-26", "faculty_title": "Lecturer"},
    }
    evidence = {"source": ncsu_chass.FACULTY_URL, "profile": recent_url, "name": "A Teacher", "title": "Lecturer"}
    for invalid in (
        None, "unavailable", {**evidence, "name": "Another Person"},
        {**evidence, "profile": original["url"]}, {**evidence, "title": "Assistant Professor"},
    ):
        read = deepcopy(current)
        read["metadata"]["faculty_title_observation"] = invalid
        ncsu_chass.prepare_update(original, read)
        assert read == original
        assert read["metadata"] is not original["metadata"]

    current["metadata"]["faculty_title_observation"] = evidence
    accepted = deepcopy(current)
    ncsu_chass.prepare_update(original, accepted)
    assert accepted == current


def test_one_reviewed_profile_cannot_keep_two_contact_buttons_after_a_name_change(tmp_path, monkeypatch):
    import json
    from copy import deepcopy

    from backend.lib.opportunity_detail import build_detail_fields
    from backend.lib.public_opportunity_detail import project_public_detail
    from src.collectors import ucb_common

    first, second = sorted(ncsu_chass.REVIEWED_CONTACT_IDS)
    shared = ncsu_chass.REVIEWED_CONTACT_URL
    def confirmed(contact_id, name, url):
        return {"id": contact_id, "pi_name": name, "url": url, "source_url": url, "source": "ncsu_faculty",
                "source_type": "faculty_research", "application": {"application_url": url}, "metadata": {
            "is_active": True, "first_seen_at": "2026-01-01", "faculty_title": "Lecturer",
            "faculty_title_observation": {"source": ncsu_chass.FACULTY_URL, "profile": url,
                                          "name": name, "title": "Lecturer"},
        }}

    current = confirmed(first, "First Teacher", shared)
    earlier = confirmed(second, "Second Teacher", shared)
    published = tmp_path / "published.json"
    published.write_text(json.dumps([current, earlier]))
    monkeypatch.setattr(ucb_common, "PROCESSED_FILE", published)

    def merge(*observed):
        ncsu_faculty.merge_into_processed(deepcopy(list(observed)))
        return {v["id"]: v for v in json.loads(published.read_text())}

    rows = merge(current)
    assert rows[first]["metadata"]["is_active"] and not rows[second]["metadata"]["is_active"]
    assert rows[second]["metadata"]["deactivation_reason"] == "profile_identity_mismatch"
    archived = project_public_detail(rows[second])
    assert archived["id"] == second and archived["target_truth"]["reason_code"] == "inactive"
    assert archived["archived_faculty_directory_url"] == ncsu_chass.FACULTY_URL
    assert shared not in json.dumps(archived)
    assert rows[second]["metadata"]["faculty_profile_review"]["source_url"] == shared
    assert project_public_detail(rows[first])["url"] == shared
    facts = build_detail_fields(archived, rows[second])["fields"]
    assert all(fact["provenance"]["source_url"] is None for fact in facts.values())

    other_archive = deepcopy(rows[second])
    other_archive["metadata"]["deactivation_reason"] = "retired_title"
    del other_archive["metadata"]["faculty_profile_review"]
    assert project_public_detail(other_archive)["url"] == shared

    unproven = deepcopy(rows[second])
    unproven["metadata"]["faculty_profile_review"]["roster_url"] = shared
    assert "archived_faculty_directory_url" not in project_public_detail(unproven)
    del unproven["metadata"]["faculty_profile_review"]
    assert shared not in json.dumps(project_public_detail(unproven))
    old_stamp = rows[second]["metadata"]["deactivated_at"]
    unverified = deepcopy(earlier)
    unverified["metadata"].pop("faculty_title_observation")
    assert merge(unverified)[second]["metadata"]["deactivated_at"] == old_stamp

    rows = merge(earlier)
    assert rows[second]["metadata"]["is_active"] and not rows[first]["metadata"]["is_active"]
    restored = project_public_detail(rows[second])
    assert restored["target_truth"]["actionable"] and restored["url"] == shared
    assert "archived_faculty_directory_url" not in restored
    separate = confirmed(first, "First Teacher", "https://chass.ncsu.edu/people/independent/")
    assert all(r["metadata"]["is_active"] for r in merge(earlier, separate).values())
