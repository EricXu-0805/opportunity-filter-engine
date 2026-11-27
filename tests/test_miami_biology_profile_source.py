import json

from bs4 import BeautifulSoup

from src.collectors import faculty_graph, ucb_common
from src.collectors.schools import miami_faculty


def test_named_citation_preserves_old_id_and_allows_a_public_profile_to_return(monkeypatch, tmp_path):
    school = miami_faculty.SCHOOL
    dept = next(d for d in school["departments"] if d["short"] == "BIO")
    owner = dept["reserved_profile_identity"]
    old_id = "faculty-miami-bio-4dfe1b88"
    school_site = "https://people.miami.edu/profile/"
    safe = school_site + "verified-individual"
    namesake = school_site + "distinct-person"
    citation = dept["directory_url"] + "#:~:text=DeAngelis"
    monkeypatch.setattr(miami_faculty, "SCHOOL", {**school, "departments": [dept]})
    monkeypatch.setattr(faculty_graph, "_PROFILE_ENRICH", False)

    store = tmp_path / "opportunities.json"
    store.write_text("[]")
    monkeypatch.setattr(ucb_common, "PROCESSED_FILE", store)

    def card(name, profile, email):
        # The normal Cascade collector reads email from its encoded data-code attribute.
        address = email.encode("utf-16-be").hex()
        return f"""<div class="people-profile"><div class="profile-name"><span>{name}</span></div>
          <div class="profile-position"><span>Research Professor</span></div>
          <a class="url-rewrite" href="{profile}">Visit Profile Page</a>
          <a class="email-decode" data-code="{address}"></a></div>"""

    def fetch(*cards):
        html = BeautifulSoup("".join(cards), "html.parser")
        monkeypatch.setattr(ucb_common, "fetch_soup", lambda *_a, **_k: html)
        return {r["id"]: r for r in miami_faculty.fetch_and_normalize(deep=True)}

    old = fetch(card("&#8204;Don  DeAngelis", f" //{owner['profile']} ", owner["email"]))[old_id]
    assert old["pi_name"] == "Don DeAngelis" and old["source_url"] == citation
    assert old["contact_email"] == owner["email"] and old["metadata"]["faculty_title"] == "Research Professor"

    encoded = f" //{owner['profile'].replace('@', '%40')} "
    for email in (owner["email"], ""):
        private = fetch(card("Don DeAngelis", encoded, email))[old_id]
        assert private["source_url"] == citation
    bare = fetch(card("Don DeAngelis", "", owner["email"]))[old_id]
    assert bare["source_url"] == citation

    distinct = card("Don DeAngelis", namesake, "other@example.edu")
    separate = fetch(distinct)
    assert old_id not in separate and len(separate) == 1
    assert next(iter(separate.values()))["source_url"] == namesake
    assert not fetch(card("Don DeAngelis", dept["directory_url"], ""))

    observed = fetch(card("Don DeAngelis", safe, owner["email"]), distinct)
    assert set(observed) == set(separate) | {old_id}
    assert observed[old_id]["url"] == observed[old_id]["source_url"] == safe


    # Only a previously confirmed individual page can identify the same person
    # if a later roster omits their address.
    miami_faculty.merge_into_processed(list(observed.values()))
    without_contact = fetch(card("Don DeAngelis", safe, ""), distinct)
    assert set(without_contact) == set(observed)
    assert without_contact[old_id]["url"] == without_contact[old_id]["source_url"] == safe
    assert not without_contact[old_id].get("contact_email")
    assert not fetch(card("Don DeAngelis", school_site + "unknown", ""))

    # A different record reusing a URL is not a prior observation of this ID.
    other_owner = dict(observed[old_id], id="faculty-miami-bio-another")
    store.write_text(json.dumps([other_owner]))
    assert not fetch(card("Don DeAngelis", safe, ""))


def test_chemistry_secondary_citation_survives_replay_and_yields_to_changed_roster(monkeypatch, tmp_path):
    from copy import deepcopy

    from backend.lib.opportunity_detail import _professor_or_lab

    store = tmp_path / 'opportunities.json'
    original = next(r for r in json.loads((miami_faculty.ucb_common.PROCESSED_FILE.parent / 'shards' / 'miami.json').read_text())
                    if r['id'] == 'faculty-miami-chem-a0149798')
    person = 'Claes R. Wahlestedt'
    old = 'https://people.miami.edu/profile/5ee1f54d90d032382411370bb611716e'
    citation = ('https://med.miami.edu/graduate-studies/doctoral-programs/'
                'biochemistry-and-molecular-biology/faculty-profiles#:~:text=Claes%20Wahlestedt')
    rank = 'Professor of Chemistry (Secondary)'
    previous = deepcopy(original)
    previous.update(url=old + ' ', source_url=old + ' ')
    previous['metadata']['faculty_title'] = 'Professor'
    previous['metadata'].pop('faculty_title_observation', None)
    store.write_text(json.dumps([previous]))
    monkeypatch.setattr(ucb_common, 'PROCESSED_FILE', store)

    def fetch(rows):
        monkeypatch.setattr(faculty_graph, 'fetch_and_normalize', lambda *a, **kw: deepcopy(rows))
        return miami_faculty.fetch_and_normalize()

    for _ in range(2):
        (row,) = fetch([previous])
        assert miami_faculty.merge_into_processed([row]) == (0, 1)
        (saved,) = json.loads(store.read_bytes())
        assert saved['id'] == previous['id'] and saved['pi_name'] == person
        assert saved['url'] == saved['source_url'] == citation
        assert saved['metadata']['first_seen_at'] == previous['metadata']['first_seen_at']
        assert saved['metadata']['last_seen_at'] == previous['metadata']['last_seen_at']
        field = _professor_or_lab(saved, saved).build({})
        assert field['explicit']['faculty_rank'] == rank
        assert field['quotes']['faculty_rank'] == {'text': rank, 'source_url': citation, 'observed_at': '2026-11-27'}
    before = store.read_bytes()
    assert miami_faculty.merge_into_processed(fetch([])) == (0, 0)
    assert store.read_bytes() == before
    newer = 'https://people.miami.edu/profile/verified-new-profile'
    person_returns = deepcopy(previous)
    person_returns.update(url=newer, source_url=newer)
    person_returns['metadata']['faculty_title'] = 'Distinguished Professor'
    (row,) = fetch([person_returns])
    miami_faculty.merge_into_processed([row])
    (saved,) = json.loads(store.read_bytes())
    assert saved['url'] == saved['source_url'] == newer
    assert saved['metadata']['faculty_title'] == 'Distinguished Professor'
    assert 'faculty_title_observation' not in saved['metadata']
    anonym = deepcopy(previous)
    anonym['pi_name'] = 'Distinct Member'
    inactive = deepcopy(previous)
    inactive['metadata']['is_active'] = False
    another = deepcopy(previous)
    another['id'] = 'faculty-miami-chem-other'
    assert fetch([anonym, inactive, another]) == [anonym, inactive, another]
