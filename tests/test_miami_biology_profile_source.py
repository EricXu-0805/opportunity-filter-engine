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
