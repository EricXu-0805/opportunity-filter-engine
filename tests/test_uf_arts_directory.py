"""UF College of the Arts directories are read a page at a time, and each page
was its own unit, so a person's id held the page that listed them: when the
directory repaginated, people already stored were minted again under the next
page's unit. Each school's units now read the whole directory and each keeps
the people whose id the corpus holds under it."""
import hashlib
import json
import re

from bs4 import BeautifulSoup

from src.collectors import faculty_graph as fg

_NAMES = ["Ada Example", "Bo Sample", "Cy Fixture", "Di Placeholder", "Ed Testcase", "Flo Mockup"]
# Stored two to a page, as the page units minted them.
_STORED = {"MUS": _NAMES[0:2], "MUS2": _NAMES[2:4], "MUS3": _NAMES[4:6]}
_SHORTS = ("mus", "mus2", "mus3", "mus4", "mus5", "mus6")


def _uf_id(short, name):
    # faculty_graph mints faculty-{id_prefix}-{short}-{md5("SHORT-name")[:8]}.
    return f"faculty-uf-{short.lower()}-{hashlib.md5(f'{short}-{name}'.encode()).hexdigest()[:8]}"


def _card(name, title="Associate Professor"):
    slug = name.lower().replace(" ", "-")
    return (f'<article class="card-with-image"><a class="linked-title__link" '
            f'href="https://arts.ufl.edu/people/profiles/{slug}/">{name}</a>'
            f'<div class="profile-card__titles">{title}</div>'
            '<ul><li class="unit-list__unit">Performance</li>'
            '<li class="unit-list__unit">School of Music</li></ul></article>')


def _run(monkeypatch, tmp_path, cards, stored=_STORED):
    from src.collectors import ucb_common
    from src.collectors.schools import uf_faculty
    corpus = tmp_path / "opportunities.json"
    corpus.write_text(json.dumps([{"id": _uf_id(short, name), "metadata": {}}
                                  for short, names in stored.items() for name in names]))
    monkeypatch.setattr(ucb_common, "PROCESSED_FILE", corpus)
    monkeypatch.setattr(uf_faculty, "SCHOOL", {**uf_faculty.SCHOOL, "departments": [
        d for d in uf_faculty.SCHOOL["departments"] if d["short"].lower() in _SHORTS]})
    pages = [cards[i:i + 2] for i in range(0, len(cards), 2)]
    requested = []

    def fetch_soup(url, **_kw):
        assert "/school-of-music/directory/" in url
        found = re.search(r"[?&]paged=(\d+)", url)
        n = int(found[1]) if found else 1
        requested.append(n)
        body = "".join(pages[n - 1]) if n <= len(pages) else ""
        return BeautifulSoup(f"<html><body><main>Directory {body}</main></body></html>", "html.parser")

    monkeypatch.setattr(ucb_common, "fetch_soup", fetch_soup)
    ledger: dict = {}
    people = uf_faculty.fetch_and_normalize(unit_ledger=ledger)
    return people, ledger, requested


def test_ids_do_not_depend_on_the_page_that_lists_a_person(monkeypatch, tmp_path):
    stored = {name: _uf_id(short, name) for short, names in _STORED.items() for name in names}
    listed = [_card(name) for name in _NAMES]
    # A staff card at the top moves every professor down one slot, the last of
    # each page onto the next page; a new professor joins at the end.
    shifted = [_card("Office Contact", "Office Manager"), *listed, _card("Gus Newcomer")]
    runs = [_run(monkeypatch, tmp_path, cards) for cards in (listed, shifted)]
    ids = [{p["pi_name"]: p["id"] for p in people} for people, _, _ in runs]
    assert ids[0] == stored
    assert ids[1] == {**stored, "Gus Newcomer": _uf_id("MUS", "Gus Newcomer")}
    # One read of each directory page serves the school's six units.
    assert [sorted(requested) for _, _, requested in runs] == [[1, 2, 3, 4, 5, 6]] * 2


def test_each_unit_observes_the_people_it_holds_wherever_they_are_listed(monkeypatch, tmp_path):
    shifted = [_card("Office Contact", "Office Manager"), *[_card(name) for name in _NAMES]]
    _, ledger, _ = _run(monkeypatch, tmp_path, shifted)
    assert {u: sorted(ledger[u]["observed_entity_ids"]) for u in _SHORTS[:3]} == {
        short.lower(): sorted(_uf_id(short, name) for name in names)
        for short, names in _STORED.items()}
    assert [ledger[u]["coverage"]["parsed_faculty_rows"] for u in _SHORTS] == [2, 2, 2, 0, 0, 0]


def test_a_corpus_that_holds_none_of_the_school_retires_no_one_in_it(monkeypatch, tmp_path):
    from src.normalizers.deactivate_stale_faculty import finalize_unit_ledger
    people, ledger, _ = _run(monkeypatch, tmp_path, [_card(name) for name in _NAMES],
                             stored={"THD": ["Ada Example"]})
    finalize_unit_ledger(ledger, people, "uf_faculty")
    assert {p["id"] for p in people} == {_uf_id("MUS", name) for name in _NAMES}
    assert not any(ledger[u]["retirement_authorized"] for u in _SHORTS)
    assert ledger["mus"]["coverage"]["identity_match_failures"] == 6


def test_a_scrape_unit_left_out_of_its_own_id_namespaces_is_flagged():
    from src.collectors.schools import uf_faculty
    units = [{"short": short, "name": "School of X",
              "scrape": {"url": "https://x.example.edu/directory/", "id_namespaces": shorts}}
             for short, shorts in (("X", ["X", "X2"]), ("X2", ["X", "X3"]))]
    errors = fg.validate({**uf_faculty.SCHOOL, "departments": units})
    assert errors == ["X2: scrape id_namespaces leaves out X2"]
