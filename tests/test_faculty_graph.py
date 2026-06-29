"""Tests for the school-agnostic faculty_graph engine + the Michigan config.

Curated-seed path only for the data assertions (no network). The best-effort
scrape layer is exercised with injected sample HTML so the reusable parser is
covered without hitting a (Cloudflare-walled) live directory.

Locks in the invariants the data-quality gate depends on — every record is
``faculty_research`` with a person pi_name, clean keywords, a title whose
parenthetical is a subset of its keywords, and no two records in the school
sharing a non-null contact_email — so a config edit can't silently break them.
"""

from __future__ import annotations

import re

import pytest

from src.collectors import faculty_graph as fg
from src.collectors.schools.umich_faculty import SCHOOL
from src.collectors.ucb_common import _is_person_name
from src.collectors.uiuc_faculty import _is_junk_keyword
from src.normalizers.deactivate_stale_faculty import FACULTY_SOURCES
from src.normalizers.school_audience import SOURCE_DEFAULTS

# --- Validator --------------------------------------------------------------

class TestValidator:
    def test_michigan_config_is_valid(self):
        assert fg.validate(SCHOOL) == []

    def test_missing_required_field_flagged(self):
        bad = {k: v for k, v in SCHOOL.items() if k != "source"}
        assert any("source" in e for e in fg.validate(bad))

    def test_department_without_faculty_or_scrape_flagged(self):
        bad = {**SCHOOL, "departments": [{"short": "X", "name": "X Dept"}]}
        assert any("no curated faculty" in e for e in fg.validate(bad))

    def test_fetch_rejects_invalid_config(self):
        with pytest.raises(ValueError):
            fg.fetch_and_normalize({"school_slug": "x", "departments": []})


# --- Registration contract --------------------------------------------------

class TestRegistration:
    def test_source_in_source_defaults(self):
        assert SOURCE_DEFAULTS[SCHOOL["source"]] == ("umich", "unknown")

    def test_source_in_faculty_sources(self):
        # Else stale professors are never retired by deactivate_stale_faculty.
        assert SCHOOL["source"] in FACULTY_SOURCES


# --- Seed normalization -----------------------------------------------------

@pytest.fixture(scope="module")
def recs():
    return fg.fetch_and_normalize(SCHOOL, deep=False)


class TestSeedNormalization:
    def test_produces_records(self, recs):
        assert len(recs) >= 40

    def test_all_faculty_research(self, recs):
        for o in recs:
            assert o["source_type"] == "faculty_research"
            assert o["source"] == "umich_faculty"
            assert o["school"] == "umich"
            assert o["audience"] == "unknown"

    def test_ids_unique_and_namespaced(self, recs):
        ids = [o["id"] for o in recs]
        assert len(ids) == len(set(ids))
        assert all(o["id"].startswith("faculty-umich-") for o in recs)

    def test_pi_names_are_people(self, recs):
        for o in recs:
            assert _is_person_name(o["pi_name"]), o["pi_name"]

    def test_required_schema_fields(self, recs):
        for o in recs:
            assert isinstance(o["eligibility"], dict)
            assert isinstance(o["metadata"], dict)
            assert isinstance(o["keywords"], list)
            assert len(o["description_clean"]) <= 1500
            assert o["deadline"] is None

    def test_title_parenthetical_is_subset_of_keywords(self, recs):
        for o in recs:
            m = re.search(r" — .+? \((.+)\)$", o["title"])
            if not m:
                continue
            shown = {a.strip().lower() for a in m.group(1).split(",")}
            kws = {(k or "").strip().lower() for k in o["keywords"]}
            assert not (shown - kws), f"{o['id']}: {shown - kws}"

    def test_keywords_have_no_junk(self, recs):
        for o in recs:
            for k in o["keywords"]:
                assert not _is_junk_keyword(k), f"{o['id']}: {k!r}"

    def test_no_shared_non_null_email(self, recs):
        """The school-scoped equivalent of the ucb joint-appointment gate: two
        umich_faculty records must not share a non-null contact_email."""
        from collections import defaultdict
        by_email = defaultdict(list)
        for o in recs:
            e = (o.get("contact_email") or "").strip().lower()
            if e:
                by_email[e].append(o["pi_name"])
        dups = {e: v for e, v in by_email.items() if len(v) > 1}
        assert not dups, f"shared emails: {dups}"

    def test_distinct_same_name_professors_both_kept(self, recs):
        """Michigan has two different professors named 'Wei Lu' (ECE memristors,
        ME batteries). A name-based de-dup would drop one; keep both."""
        wei_lu = [o for o in recs if o["pi_name"] == "Wei Lu"]
        assert len(wei_lu) == 2
        assert {o["contact_email"] for o in wei_lu} == {"wluee@umich.edu", "weilu@umich.edu"}

    def test_email_optional(self, recs):
        # Some have confirmed emails, some intentionally None (not guessed).
        assert any(o["contact_email"] for o in recs)
        assert any(o["contact_email"] is None for o in recs)


# --- Best-effort scrape layer (injected HTML, no network) -------------------

SAMPLE_HTML = """
<html><body>
  <div class="card"><h3><a href="/people/jane-doe/">Jane Q. Researcher</a></h3>
    <span class="rank">Assistant Professor</span></div>
  <div class="card"><h3><a href="/people/john-roe/">John Roe</a></h3>
    <span class="rank">Professor</span></div>
  <div class="card"><h3><a href="/about/">Department of Widgets</a></h3>
    <span class="rank">Office</span></div>
</body></html>
"""


class TestScrapeLayer:
    def test_scrape_disabled_without_config(self):
        assert fg._scrape_directory({"short": "X"}) == []

    def test_scrape_parses_cards_and_skips_nonpersons(self, monkeypatch):
        from bs4 import BeautifulSoup
        monkeypatch.setattr(
            "src.collectors.ucb_common.fetch_soup",
            lambda url: BeautifulSoup(SAMPLE_HTML, "html.parser"),
        )
        dept = {
            "short": "WID",
            "scrape": {
                "url": "https://example.edu/widgets/faculty",
                "selectors": {"card": "div.card", "name": "h3 a", "link": "h3 a", "title": "span.rank"},
            },
        }
        people = fg._scrape_directory(dept)
        names = {p["name"] for p in people}
        assert "Jane Q. Researcher" in names and "John Roe" in names
        # "Department of Widgets" is an institution label, not a person.
        assert "Department of Widgets" not in names

    def test_scrape_failure_degrades_to_empty(self, monkeypatch):
        monkeypatch.setattr("src.collectors.ucb_common.fetch_soup", lambda url: None)
        dept = {"short": "WID", "scrape": {"url": "https://example.edu/x", "selectors": {"card": "div"}}}
        assert fg._scrape_directory(dept) == []

    def test_scrape_captures_research_email_and_absolutizes_href(self, monkeypatch):
        """Rich cards (e.g. UW ECE) expose interests + a mailto inline, and link
        with a relative href — deep mode must land keyworded, emailed faculty
        with an absolute profile URL in one pass."""
        from bs4 import BeautifulSoup
        html = """
        <div class="entry">
          <span class="nm"><a href="/people/ada/">Ada Q. Lovelace</a></span>
          <span class="ti">Associate Professor</span>
          <span class="ri">Machine learning, computer vision, and Robotics</span>
          <span class="em"><a href="mailto:ada@uw.edu?subject=hi">ada@uw.edu</a></span>
        </div>
        """
        monkeypatch.setattr("src.collectors.ucb_common.fetch_soup",
                            lambda url: BeautifulSoup(html, "html.parser"))
        dept = {"short": "ECE", "scrape": {
            "url": "https://www.ece.uw.edu/faculty/",
            "selectors": {"card": "div.entry", "name": ".nm a", "link": ".nm a",
                          "title": ".ti", "research": ".ri", "email": ".em a"},
        }}
        people = fg._scrape_directory(dept)
        assert len(people) == 1
        p = people[0]
        assert p["url"] == "https://www.ece.uw.edu/people/ada/"  # relative -> absolute
        assert p["email"] == "ada@uw.edu"  # mailto: + ?subject stripped
        assert "Machine learning" in p["research_areas"]

    def test_scrape_follows_pagination_until_no_new(self, monkeypatch):
        """A paginated directory (e.g. GT College of Computing) must be followed
        via ``?page=N`` and stop the moment a page surfaces no new (name, url) —
        so a 200-professor school isn't truncated to its first page or looped."""
        from bs4 import BeautifulSoup
        pages = {
            "https://x.edu/f": '<div class="c"><a class="n" href="/p/a">Ann Alpha</a></div>',
            "https://x.edu/f?page=1": '<div class="c"><a class="n" href="/p/b">Ben Beta</a></div>',
            "https://x.edu/f?page=2": '<div class="c"><a class="n" href="/p/a">Ann Alpha</a></div>',
        }
        monkeypatch.setattr(
            "src.collectors.ucb_common.fetch_soup",
            lambda url: BeautifulSoup(pages[url], "html.parser") if url in pages else None,
        )
        dept = {"short": "X", "scrape": {
            "url": "https://x.edu/f",
            "selectors": {"card": "div.c", "name": ".n", "link": ".n"},
            "paginate": {"param": "page", "start": 1, "max": 5},
        }}
        names = [p["name"] for p in fg._scrape_directory(dept)]
        assert names == ["Ann Alpha", "Ben Beta"]  # page 2 repeats -> pagination stops

    def test_profile_enrich_fills_research_from_profile_when_enabled(self, monkeypatch):
        """A listing that carries name/title only can be enriched per-profile: the
        gated pass follows each profile link and lifts a "<strong>Research Areas:
        </strong> A; B</p>" block into research_areas (GT College of Computing)."""
        from bs4 import BeautifulSoup
        listing = ('<div class="c"><a class="n" href="/people/ada">Ada Q. Lovelace</a>'
                   '<span class="t">Professor</span></div>')
        profile = ('<p class="card-block__text"><strong>Research Areas:</strong><br>'
                   'Machine Learning; Computer Vision; Robotics</p>')
        monkeypatch.setattr(
            "src.collectors.ucb_common.fetch_soup",
            lambda url: BeautifulSoup(profile if url.endswith("/people/ada") else listing,
                                      "html.parser"),
        )
        monkeypatch.setattr(fg, "_PROFILE_ENRICH", True)
        dept = {"short": "CS", "scrape": {
            "url": "https://www.cc.gatech.edu/people/faculty",
            "selectors": {"card": "div.c", "name": ".n", "link": ".n", "title": ".t"},
            "profile_enrich": {"research_html_re": r"Research Areas?:?\s*</strong>(.*?)</p>"},
        }}
        people = fg._scrape_directory(dept)
        assert len(people) == 1
        kws = fg._clean_keywords(people[0])
        assert {"Machine Learning", "Computer Vision", "Robotics"} <= set(kws)

    def test_profile_enrich_skipped_when_flag_disabled(self, monkeypatch):
        """The per-profile pass is cost-gated: with OFE_ENRICH_PROFILES unset the
        listing scrape never fetches profile pages (CI / weekly refresh pay
        nothing; richer-dedup keeps any prior enrichment), so broad stays broad."""
        from bs4 import BeautifulSoup
        calls = []

        def fake_soup(url):
            calls.append(url)
            return BeautifulSoup('<div class="c"><a class="n" href="/people/ada">'
                                 'Ada Q. Lovelace</a></div>', "html.parser")

        monkeypatch.setattr("src.collectors.ucb_common.fetch_soup", fake_soup)
        monkeypatch.setattr(fg, "_PROFILE_ENRICH", False)
        dept = {"short": "CS", "scrape": {
            "url": "https://www.cc.gatech.edu/people/faculty",
            "selectors": {"card": "div.c", "name": ".n", "link": ".n"},
            "profile_enrich": {"research_html_re": r"Research Areas?:?\s*</strong>(.*?)</p>"},
        }}
        people = fg._scrape_directory(dept)
        assert len(people) == 1
        assert people[0]["research_areas"] == ""  # not enriched
        assert calls == ["https://www.cc.gatech.edu/people/faculty"]  # only the listing

    def test_in_memoriam_name_is_dropped(self):
        """A name carrying a (birth-death) year range is an in-memoriam directory
        entry, not active faculty — drop it (GT CoC lists the late
        'Alberto Apostolico (1948-2015)' among its people)."""
        school = {**SCHOOL, "departments": [{
            "short": "CS", "name": "Computer Science", "majors": ["Computer Science"],
            "faculty": [fg.faculty("Ada Lovelace", keywords=["computing"]),
                        fg.faculty("Alberto Apostolico (1948-2015)", keywords=["algorithms"])],
        }]}
        names = {r["pi_name"] for r in fg.fetch_and_normalize(school, deep=False)}
        assert "Ada Lovelace" in names
        assert not any("Apostolico" in n for n in names)

    def test_clean_keywords_strips_oxford_comma_connective(self):
        """An Oxford-comma tail ("..., and Robotics") splits into a clause led by
        'and' — the connective must be stripped so the keyword clears the DQ junk
        filter (regression: UW ECE 'and Wireless power transfer')."""
        person = {"research_areas": "Machine learning, computer vision, and Robotics"}
        kws = fg._clean_keywords(person)
        assert "Robotics" in kws
        assert not any(k.lower().startswith("and ") for k in kws)
        for k in kws:
            assert not _is_junk_keyword(k), k

    def test_clean_keywords_trims_edge_punct_and_drops_unbalanced_parens(self):
        """Comma-splitting a parenthetical research blob leaves a dangling
        "(species interactions" and a trailing period ("Genomics.") — trim the
        edge punctuation and drop the unbalanced-paren fragment (GT Biology)."""
        person = {"research_areas": "Speciation, secondary contact (species interactions, Genomics."}
        kws = fg._clean_keywords(person)
        assert "Speciation" in kws
        assert "Genomics" in kws  # trailing period trimmed
        assert "secondary contact (species interactions" not in kws
        assert not any("(" in k and ")" not in k for k in kws)  # no dangling open paren

    def test_clean_keywords_strips_research_label_prefix(self):
        """A directory that prefixes its research block with a section label
        ("Research Interests: semantics, syntax") leaves the label stuck to the
        first term after the comma split — it must be dropped so the term clears
        the DQ junk filter (regression: UCLA Linguistics 'dd.interest')."""
        person = {"research_areas": "Research Interests: semantics, syntax, phonology"}
        kws = fg._clean_keywords(person)
        assert "semantics" in kws
        assert not any(k.lower().startswith("research interest") for k in kws)
        for k in kws:
            assert not _is_junk_keyword(k), k
        # other common labels
        assert "machine learning" in fg._clean_keywords(
            {"research_areas": "Areas of Expertise: machine learning, robotics"}
        )

    def test_clean_keywords_drops_prose_and_gate_junk(self):
        """A free-text interests field (some directories store a bio there) must
        not ship sentence fragments or anything the DQ junk gate would reject —
        the derived keywords honour the same junk definition the gate enforces."""
        person = {"research_areas": (
            "Phonology, My research interests include the politics of memory, "
            "African American literature (1945-present), working memory")}
        kws = fg._clean_keywords(person)
        assert "Phonology" in kws            # a real short topic survives
        from src.collectors.uiuc_faculty import _is_junk_keyword
        for k in kws:
            assert not _is_junk_keyword(k), k
        # the prose clause / date-tagged / gerund-flagged fragments are gone
        assert not any("research interests include" in k.lower() for k in kws)
        assert not any("1945" in k for k in kws)


# --- WordPress-REST api source (UCLA-style, no network in tests) -------------

class TestWordPressApiSource:
    def test_flip_name_inverts_last_first(self):
        assert fg._flip_name("Zhou, Hong") == "Hong Zhou"
        assert fg._flip_name("Wang, Sining (Cindy)") == "Sining (Cindy) Wang"
        assert fg._flip_name("Giulia Palermo") == "Giulia Palermo"  # no comma untouched

    def test_wp_api_filters_category_and_drops_junk_keywords(self, monkeypatch):
        """A WP directory mixes faculty + staff; the category filter keeps only
        the Faculty term, taxonomy terms become keywords, and a non-research term
        (Instructional) is dropped — all without per-profile fetches."""
        records = [
            {"title": {"rendered": "Zhao, Lei"}, "link": "https://x.edu/d/zhao/",
             "directory-category": [88], "specialties": [10, 11]},
            {"title": {"rendered": "Helpdesk, Staff"}, "link": "https://x.edu/d/help/",
             "directory-category": [136], "specialties": []},
        ]

        def fake_json(url):
            if "/specialties" in url:
                return [{"id": 10, "name": "Robotics"}, {"id": 11, "name": "Instructional"}]
            if "page=1" in url:
                return records
            return []

        monkeypatch.setattr(fg, "_wp_get_json", fake_json)
        dept = {"short": "CHEM", "api": {
            "type": "wp", "base": "https://x.edu", "post_type": "directory",
            "category_include": {"directory-category": [88]},
            "keyword_tax": ["specialties"], "keyword_drop": ["instructional"],
            "name_flip": True,
        }}
        people = fg._fetch_wp_api(dept)
        assert len(people) == 1  # staff excluded by category
        assert people[0]["name"] == "Lei Zhao"  # flipped
        assert people[0]["keywords"] == ["Robotics"]  # Instructional dropped

    def test_wp_api_profile_enrich_requires_professor(self, monkeypatch):
        """profile_enrich sets rank from the profile and, with require_professor,
        drops a Lecturer while keeping a professor + their Primary-Area keyword."""
        records = [
            {"title": {"rendered": "Ada Prof"}, "link": "https://x.edu/f/ada/"},
            {"title": {"rendered": "Lee Lecturer"}, "link": "https://x.edu/f/lee/"},
        ]
        monkeypatch.setattr(fg, "_wp_get_json",
                            lambda url: records if "page=1" in url else [])
        monkeypatch.setattr(fg, "_enrich_profile", lambda url, enrich:
                            ("Associate Professor", "Cognitive Psychology")
                            if "ada" in url else ("Lecturer", ""))
        dept = {"short": "PSYCH", "api": {
            "type": "wp", "base": "https://x.edu", "post_type": "faculty-page",
            "profile_enrich": {"require_professor": True},
        }}
        people = fg._fetch_wp_api(dept)
        assert [p["name"] for p in people] == ["Ada Prof"]  # lecturer dropped
        assert people[0]["title"] == "Associate Professor"
        assert "Cognitive Psychology" in people[0]["keywords"]

    def test_wp_api_degrades_to_empty_without_block(self):
        assert fg._fetch_wp_api({"short": "X"}) == []
        assert fg._fetch_wp_api({"short": "X", "api": {"type": "drupal"}}) == []


# --- UCLA Samueli seas-people AJAX source (no network in tests) --------------

class TestSeasAjaxSource:
    _AJAX_HTML = """
      <div class="seas-people-container core-cs">
        <div class="card">
          <div class="people-title"><a href="https://samueli.ucla.edu/people/ada/">Ada Byron</a></div>
          <div class="card_description"><p><i>Professor</i></p></div>
          <a class="mailto-link" href="mailto:ada@ucla.edu?subject=x">email</a>
        </div>
      </div>
      <div class="seas-people-container emeriti-cs">
        <div class="card">
          <div class="people-title"><a href="https://samueli.ucla.edu/people/old/">Olde Prof</a></div>
          <div class="card_description"><p><i>Professor Emeritus</i></p></div>
        </div>
      </div>
    """
    _PROFILE_HTML = """
      <div class="et_pb_toggle"><div class="et_pb_toggle_title">Research and Interests</div>
      <div class="et_pb_toggle_content"><p>Machine learning</p><p>Cryptography</p>
      <p>This is a long prose sentence describing the research program in great detail and depth.</p>
      </div></div>
    """

    def test_seas_keeps_ladder_drops_emeriti_and_enriches(self, monkeypatch):
        from bs4 import BeautifulSoup

        class _Resp:
            text = self._AJAX_HTML
            def raise_for_status(self): pass

        monkeypatch.setattr("requests.post", lambda *a, **k: _Resp())
        monkeypatch.setattr("src.collectors.ucb_common.fetch_soup",
                            lambda url: BeautifulSoup(self._PROFILE_HTML, "html.parser"))
        dept = {"short": "CS", "ajax": {"type": "seas", "department": "cs",
                                        "research_enrich": True}}
        people = fg._fetch_seas_ajax(dept)
        assert [p["name"] for p in people] == ["Ada Byron"]  # emeriti container dropped
        p = people[0]
        assert p["email"] == "ada@ucla.edu"  # ?subject stripped
        assert p["keywords"] == ["Machine learning", "Cryptography"]  # prose line dropped

    def test_seas_degrades_to_empty_without_block(self):
        assert fg._fetch_seas_ajax({"short": "X"}) == []
        assert fg._fetch_seas_ajax({"short": "X", "ajax": {"type": "other"}}) == []


# --- scrape title-based ladder filter + name-flip (no network) ---------------

class TestScrapeLadderFilter:
    def test_ladder_filter_drops_nonladder_titles(self, monkeypatch):
        from bs4 import BeautifulSoup
        html = """
        <div class="c"><a class="n" href="/p/a">Ada Real</a><span class="t">Professor</span></div>
        <div class="c"><a class="n" href="/p/b">Bob Old</a><span class="t">Professor Emeritus</span></div>
        <div class="c"><a class="n" href="/p/c">Cy Adj</a><span class="t">Adjunct Professor</span></div>
        <div class="c"><a class="n" href="/p/d">Di Teach</a><span class="t">Teaching Professor</span></div>
        """
        monkeypatch.setattr("src.collectors.ucb_common.fetch_soup",
                            lambda url: BeautifulSoup(html, "html.parser"))
        dept = {"short": "X", "scrape": {
            "url": "https://x.edu/f",
            "selectors": {"card": "div.c", "name": ".n", "link": ".n", "title": ".t"},
            "ladder_filter": {"require": r"professor", "drop": r"emerit|adjunct|teaching"},
        }}
        names = [p["name"] for p in fg._scrape_directory(dept)]
        assert names == ["Ada Real"]

    def test_section_filter_keeps_only_matching_heading(self, monkeypatch):
        """A single-page role-grouped directory: keep only cards under the
        ``Faculty`` heading, excluding Teaching Faculty / Affiliate / Emeritus —
        even when an Affiliate carries a real "Professor" title that a
        ladder_filter would wrongly keep."""
        from bs4 import BeautifulSoup
        html = """
        <h2>Faculty</h2>
        <div class="c"><a class="n" href="/p/a">Ada Core</a></div>
        <div class="c"><a class="n" href="/p/b">Bea Core</a></div>
        <h2>Teaching Faculty</h2>
        <div class="c"><a class="n" href="/p/c">Cy Teach</a></div>
        <h2>Affiliate</h2>
        <div class="c"><a class="n" href="/p/d">Di Other</a></div>
        <h2>Emeritus Professor</h2>
        <div class="c"><a class="n" href="/p/e">Ed Old</a></div>
        """
        monkeypatch.setattr("src.collectors.ucb_common.fetch_soup",
                            lambda url: BeautifulSoup(html, "html.parser"))
        dept = {"short": "X", "scrape": {
            "url": "https://x.edu/f",
            "selectors": {"card": "div.c", "name": ".n", "link": ".n"},
            "section_filter": {"include": r"^faculty$"},
        }}
        names = [p["name"] for p in fg._scrape_directory(dept)]
        assert names == ["Ada Core", "Bea Core"]

    def test_title_strip_after_trims_contact_blob(self, monkeypatch):
        """A directory that crams rank + office + phone into one cell keeps only
        the text before the first contact marker, and the trimmed title still
        drives ladder filtering (the emeritus row is dropped)."""
        from bs4 import BeautifulSoup
        html = """
        <div class="c"><h5>Ada Real</h5><p>Professor Plasma Physics Office: PAB 1 Phone: 310-000</p></div>
        <div class="c"><h5>Bob Old</h5><p>Professor Emeritus Astro Office: PAB 2 Phone: 310-111</p></div>
        """
        monkeypatch.setattr("src.collectors.ucb_common.fetch_soup",
                            lambda url: BeautifulSoup(html, "html.parser"))
        dept = {"short": "X", "scrape": {
            "url": "https://x.edu/f",
            "selectors": {"card": "div.c", "name": "h5", "link": "h5", "title": "p",
                          "title_strip_after": r"\s*(Office|Phone)\b"},
            "ladder_filter": {"require": r"professor", "drop": r"emerit"},
        }}
        people = fg._scrape_directory(dept)
        assert [p["name"] for p in people] == ["Ada Real"]
        assert people[0]["title"] == "Professor Plasma Physics"

    def test_scrape_name_flip(self, monkeypatch):
        from bs4 import BeautifulSoup
        html = '<div class="c"><a class="n" href="/p/a">Zhang, Wei</a></div>'
        monkeypatch.setattr("src.collectors.ucb_common.fetch_soup",
                            lambda url: BeautifulSoup(html, "html.parser"))
        dept = {"short": "X", "scrape": {
            "url": "https://x.edu/f",
            "selectors": {"card": "div.c", "name": ".n", "link": ".n"},
            "name_flip": True,
        }}
        assert fg._scrape_directory(dept)[0]["name"] == "Wei Zhang"

    def test_scrape_name_strip_and_self_link_list(self, monkeypatch):
        """A link-list directory (each faculty is a bare <a> whose text is
        prefixed boilerplate) is parsed with card=the anchor, name=":self", and a
        ``name_strip`` regex to recover the clean name."""
        from bs4 import BeautifulSoup
        html = """
        <div class="grid">
          <a href="/directory/ada-byron">Learn more about Ada Byron</a>
          <a href="/directory/grace-hopper">Learn more about Grace Hopper</a>
        </div>
        """
        monkeypatch.setattr("src.collectors.ucb_common.fetch_soup",
                            lambda url: BeautifulSoup(html, "html.parser"))
        dept = {"short": "X", "scrape": {
            "url": "https://x.edu/dir",
            "selectors": {"card": "a[href*='/directory/']", "name": ":self",
                          "link": ":self", "name_strip": r"^Learn more about\s+"},
        }}
        people = fg._scrape_directory(dept)
        assert [p["name"] for p in people] == ["Ada Byron", "Grace Hopper"]
        assert people[0]["url"] == "https://x.edu/directory/ada-byron"

    def test_scrape_research_items_collects_clean_keywords(self, monkeypatch):
        """A Stanford-style hb-card lists each research area as its own taxonomy
        link; ``research_items`` collects them as separate keywords and drops the
        "Research Area(s)" label cell + any institute-affiliation junk."""
        from bs4 import BeautifulSoup
        html = """
        <div class="hb-card">
          <span class="views-field-title"><a href="/people/ada">Ada Lovelace</a></span>
          <div class="views-field-field-hs-person-research">
            <div class="field__label">Research Area(s)</div>
            <a href="/t/1">Probability Theory</a>
            <a href="/t/2">Information Theory</a>
            <a href="/inst">Stanford Institute for Theoretical Physics</a>
          </div>
        </div>
        """
        monkeypatch.setattr("src.collectors.ucb_common.fetch_soup",
                            lambda url: BeautifulSoup(html, "html.parser"))
        dept = {"short": "STATS", "scrape": {
            "url": "https://statistics.stanford.edu/people/faculty",
            "selectors": {"card": "div.hb-card", "name": ".views-field-title a",
                          "link": ".views-field-title a",
                          "research_items": ".views-field-field-hs-person-research a"},
        }}
        people = fg._scrape_directory(dept)
        assert len(people) == 1
        kws = people[0]["keywords"]
        assert "Probability Theory" in kws and "Information Theory" in kws
        assert not any("Institute" in k for k in kws)  # affiliation junk dropped


# --- Algolia directory source (no network in tests) -------------------------

class TestAlgoliaSource:
    def test_algolia_joins_name_research_and_drops_emeriti(self, monkeypatch):
        hits = [
            {"name_first": "Ada", "name_last": "Byron",
             "areas_of_research": ["Particle Physics", "Cosmology"],
             "titles_general": "Professor", "email": "ada@utexas.edu",
             "profile_link": "https://physics.utexas.edu/directory/ada/"},
            {"name_first": "Old", "name_last": "Timer",
             "areas_of_research": "Optics", "titles_general": "Professor Emeritus",
             "profile_link": "https://physics.utexas.edu/directory/old/"},
        ]

        class _Resp:
            def raise_for_status(self): pass
            def json(self): return {"hits": hits}

        monkeypatch.setattr("requests.post", lambda *a, **k: _Resp())
        dept = {"short": "PHYS", "algolia": {
            "app_id": "R1M3WN6NBD", "api_key": "k", "index": "directory_LIVE",
            "filters": 'department:"Physics"', "drop_title_re": r"emerit",
        }}
        people = fg._fetch_algolia(dept)
        assert [p["name"] for p in people] == ["Ada Byron"]  # emeritus dropped
        assert people[0]["email"] == "ada@utexas.edu"
        assert "Particle Physics" in people[0]["research_areas"]

    def test_algolia_degrades_without_block(self):
        assert fg._fetch_algolia({"short": "X"}) == []


class TestColaSource:
    """UT Liberal Arts shared JSON:API (a Vue SPA backed by webeditor.la JSON:API)."""

    def _payload(self):
        return {"data": [
            {"attributes": {"first": "Ada", "last": "Byron",
                            "display_title": "Associate Professor",
                            "email": "ada@utexas.edu", "eid": "ab42",
                            "interests": "Logic, Computation"}},
            {"attributes": {"first": "Old", "last": "Timer",
                            "display_title": "Professor Emeritus",
                            "email": "old@utexas.edu", "eid": "ot1",
                            "interests": "Optics"}},
            {"attributes": {"first": "Vee", "last": "Sitor",
                            "display_title": "Visiting Lecturer",
                            "eid": "vs9", "interests": ""}},
        ]}

    def test_cola_maps_fields_ladder_filters_and_builds_profile_url(self, monkeypatch):
        payload = self._payload()

        class _Resp:
            def raise_for_status(self): pass
            def json(self): return payload

        monkeypatch.setattr("requests.get", lambda *a, **k: _Resp())
        dept = {"short": "GOV", "cola": {
            "base": "https://webeditor.la.utexas.edu/api/v2", "division": "government",
            "profile_base": "https://liberalarts.utexas.edu/government/faculty",
            "ladder_filter": {"require": "profess", "drop": r"emerit|lecturer|visiting"},
        }}
        people = fg._fetch_cola(dept)
        assert [p["name"] for p in people] == ["Ada Byron"]  # emeritus + lecturer dropped
        assert people[0]["email"] == "ada@utexas.edu"
        assert people[0]["url"] == "https://liberalarts.utexas.edu/government/faculty/ab42"
        assert "Logic" in people[0]["research_areas"]

    def test_cola_degrades_without_block(self):
        assert fg._fetch_cola({"short": "X"}) == []

    def test_validate_accepts_cola_block(self):
        school = {"school_slug": "utexas", "source": "utexas_faculty",
                  "organization": "UT Austin", "location": "Austin, TX",
                  "id_prefix": "utexas", "departments": [
                      {"short": "GOV", "name": "Government", "cola": {
                          "base": "b", "division": "government"}}]}
        assert fg.validate(school) == []


class TestJsonDirSource:
    """An authoritative JSON directory feed (Scheller-style static export)."""

    def _payload(self):
        return [
            {"firstName": "Ada", "lastName": "Byron", "title": "Professor",
             "status": ["Faculty"], "academic": ["Finance"],
             "email": "ada@gt.edu", "link": "https://x.edu/ada/"},
            {"firstName": "Old", "lastName": "Timer", "title": "Professor Emeritus",
             "status": ["Faculty"], "academic": ["Finance"], "email": "o@gt.edu"},
            {"firstName": "Gradus", "lastName": "Student", "title": "Ph.D. Student",
             "status": ["Ph.D."], "academic": ["Finance"]},
            {"firstName": "Mark", "lastName": "Etter", "title": "Associate Professor",
             "status": ["Faculty"], "academic": ["Marketing"]},
        ]

    def test_json_dir_filters_area_status_and_ladder(self, monkeypatch):
        payload = self._payload()

        class _Resp:
            def raise_for_status(self): pass
            def json(self): return payload

        monkeypatch.setattr("requests.get", lambda *a, **k: _Resp())
        dept = {"short": "FIN", "json_dir": {
            "url": "https://x.edu/index.json",
            "filter_field": "academic", "filter_value": "Finance",
            "status_field": "status", "status_value": "Faculty",
            "ladder_filter": {"drop": r"emerit"}}}
        people = fg._fetch_json_dir(dept)
        # Marketing (other area) + emeritus + PhD-status all dropped
        assert [p["name"] for p in people] == ["Ada Byron"]
        assert people[0]["email"] == "ada@gt.edu"
        assert people[0]["url"] == "https://x.edu/ada/"

    def test_json_dir_degrades_without_block(self):
        assert fg._fetch_json_dir({"short": "X"}) == []


class TestLinklessDirectoryDedup:
    def test_linkless_directory_is_not_collapsed_to_one(self, monkeypatch):
        """A directory with no per-person profile link (each card's only "link"
        is a shared listing route) must NOT collapse to a single record: every
        card stores the department's listing URL, and the joint-appointment
        URL de-dup ignores that shared listing URL."""
        from bs4 import BeautifulSoup
        html = """
        <div class="card"><div class="nm">Ada Lovelace</div><div class="rk">Professor</div></div>
        <div class="card"><div class="nm">Alan Turing</div><div class="rk">Professor</div></div>
        <div class="card"><div class="nm">Grace Hopper</div><div class="rk">Professor</div></div>
        """
        monkeypatch.setattr("src.collectors.ucb_common.fetch_soup",
                            lambda url: BeautifulSoup(html, "html.parser"))
        listing = "https://stat.example.edu/faculty/"
        school = {
            "school_slug": "ex", "source": "ex_faculty", "id_prefix": "ex",
            "organization": "Example U", "location": "Anytown", "audience": "unknown",
            "departments": [{
                "short": "STAT", "name": "Statistics", "majors": ["Statistics"],
                "scrape": {"url": listing,
                           "selectors": {"card": "div.card", "name": ".nm", "title": ".rk"}},
            }],
        }
        recs = fg.fetch_and_normalize(school, deep=True)
        assert sorted(r["pi_name"] for r in recs) == ["Ada Lovelace", "Alan Turing", "Grace Hopper"]
        assert all(r["url"] == listing for r in recs)  # listing URL kept, not blanked


# --- University of Washington config (live-scraped, no network in tests) ----

class TestUWConfig:
    def test_uw_config_valid(self):
        from src.collectors.schools.uw_faculty import SCHOOL as UW
        assert fg.validate(UW) == []

    def test_uw_registered_in_source_defaults_and_faculty_sources(self):
        from src.collectors.schools.uw_faculty import SCHOOL as UW
        assert SOURCE_DEFAULTS[UW["source"]] == ("uw", "unknown")
        assert UW["source"] in FACULTY_SOURCES

    def test_uw_every_department_has_a_live_source(self):
        from src.collectors.schools.uw_faculty import SCHOOL as UW
        for dept in UW["departments"]:
            has_scrape = dept.get("scrape", {}).get("selectors", {}).get("card")
            has_api = dept.get("api", {}).get("type") == "wp"
            has_f180 = bool(dept.get("faculty180", {}).get("base"))
            assert has_scrape or has_api or has_f180, dept["short"]


class TestGatechConfig:
    def test_gatech_config_valid(self):
        from src.collectors.schools.gatech_faculty import SCHOOL as GT
        assert fg.validate(GT) == []

    def test_gatech_registered(self):
        from src.collectors.schools.gatech_faculty import SCHOOL as GT
        assert SOURCE_DEFAULTS[GT["source"]] == ("gatech", "unknown")
        assert GT["source"] in FACULTY_SOURCES

    def test_gatech_coc_paginates(self):
        from src.collectors.schools.gatech_faculty import SCHOOL as GT
        cs = next(d for d in GT["departments"] if d["short"] == "CS")
        assert cs["scrape"].get("paginate", {}).get("param") == "page"


class TestStanfordConfig:
    def test_stanford_config_valid(self):
        from src.collectors.schools.stanford_faculty import SCHOOL as SF
        assert fg.validate(SF) == []

    def test_stanford_registered(self):
        from src.collectors.schools.stanford_faculty import SCHOOL as SF
        assert SOURCE_DEFAULTS[SF["source"]] == ("stanford", "unknown")
        assert SF["source"] in FACULTY_SOURCES

    def test_stanford_every_department_has_a_live_source(self):
        from src.collectors.schools.stanford_faculty import SCHOOL as SF
        for dept in SF["departments"]:
            has_scrape = bool(dept.get("scrape", {}).get("selectors", {}).get("card"))
            has_api = bool(dept.get("api", {}).get("base"))  # Law = WordPress REST
            assert has_scrape or has_api, dept["short"]


class TestUTexasConfig:
    def test_utexas_config_valid(self):
        from src.collectors.schools.utexas_faculty import SCHOOL as UT
        assert fg.validate(UT) == []

    def test_utexas_registered(self):
        from src.collectors.schools.utexas_faculty import SCHOOL as UT
        assert SOURCE_DEFAULTS[UT["source"]] == ("utexas", "unknown")
        assert UT["source"] in FACULTY_SOURCES

    def test_utexas_cs_extracts_research_groups(self):
        from src.collectors.schools.utexas_faculty import SCHOOL as UT
        cs = next(d for d in UT["departments"] if d["short"] == "CS")
        assert cs["scrape"]["selectors"].get("research")


class TestWiscConfig:
    def test_wisc_config_valid(self):
        from src.collectors.schools.wisc_faculty import SCHOOL as W
        assert fg.validate(W) == []

    def test_wisc_registered(self):
        from src.collectors.schools.wisc_faculty import SCHOOL as W
        assert SOURCE_DEFAULTS[W["source"]] == ("wisc", "unknown")
        assert W["source"] in FACULTY_SOURCES


class TestUCLAConfig:
    def test_ucla_config_valid(self):
        from src.collectors.schools.ucla_faculty import SCHOOL as U
        assert fg.validate(U) == []

    def test_ucla_registered(self):
        from src.collectors.schools.ucla_faculty import SCHOOL as U
        assert SOURCE_DEFAULTS[U["source"]] == ("ucla", "unknown")
        assert U["source"] in FACULTY_SOURCES

    def test_ucla_every_department_has_a_live_source(self):
        from src.collectors.schools.ucla_faculty import SCHOOL as U
        for dept in U["departments"]:
            if "api" in dept:
                assert dept["api"]["type"] == "wp", dept["short"]
                assert dept["api"]["base"].startswith("https://"), dept["short"]
            elif "ajax" in dept:
                assert dept["ajax"]["type"] == "seas", dept["short"]
                assert dept["ajax"]["department"], dept["short"]
            else:
                assert dept["scrape"]["selectors"].get("card"), dept["short"]


class TestFullCoverageEngineAdditions:
    """Engine capabilities added for the UW full-coverage expansion."""

    def test_strip_pronouns_drops_trailing_clause_only(self):
        assert fg._strip_pronouns("Laura E Frantz she,her") == "Laura E Frantz"
        assert fg._strip_pronouns("Jonika Hash - she, her") == "Jonika Hash"
        assert fg._strip_pronouns("X Y (they/them)") == "X Y"
        # a real name is never touched
        assert fg._strip_pronouns("Christopher Hees") == "Christopher Hees"
        assert fg._strip_pronouns("Sarah Theimer") == "Sarah Theimer"

    def test_field_filter_keeps_home_department_cards(self, monkeypatch):
        """A flat grid mixes home-department faculty with cross-listed affiliates
        that carry a clean 'Professor' title; field_filter gates on the per-card
        department field, and an empty field counts as home (kept)."""
        from bs4 import BeautifulSoup
        html = """
        <div class="c"><a class="n" href="/p/a">Home One</a><span class="dept">Microbiology</span></div>
        <div class="c"><a class="n" href="/p/b">Away Two</a><span class="dept">Department of Pediatrics</span></div>
        <div class="c"><a class="n" href="/p/c">Home Three</a><span class="dept"></span></div>
        """
        monkeypatch.setattr("src.collectors.ucb_common.fetch_soup",
                            lambda url: BeautifulSoup(html, "html.parser"))
        dept = {"short": "MICRO", "scrape": {
            "url": "https://micro.x.edu/faculty",
            "selectors": {"card": "div.c", "name": ".n", "link": ".n"},
            "field_filter": {"selector": ".dept", "exclude": r"pediatric|harvard|surgery"},
        }}
        names = [p["name"] for p in fg._scrape_directory(dept)]
        assert names == ["Home One", "Home Three"]  # away affiliate dropped, blank kept

    def test_wp_api_category_exclude_and_meta_fields(self, monkeypatch):
        """category_exclude prunes a person double-tagged Faculty+Emeritus; rank +
        email are read off the WP meta box."""
        records = [
            {"title": {"rendered": "Pat Active"}, "link": "https://x.edu/p/pat/",
             "people-group": [84], "meta_box": {"job_title": "Teaching Professor",
                                                 "email_address": "pat@x.edu"}},
            {"title": {"rendered": "Em Retired"}, "link": "https://x.edu/p/em/",
             "people-group": [84, 99], "meta_box": {"job_title": "Professor"}},
        ]
        monkeypatch.setattr(fg, "_wp_get_json",
                            lambda url: records if "page=1" in url else [])
        dept = {"short": "COM", "api": {
            "type": "wp", "base": "https://x.edu", "post_type": "person",
            "category_include": {"people-group": [84]},
            "category_exclude": {"people-group": [99]},
            "meta_title_field": "job_title", "meta_email_field": "email_address",
        }}
        people = fg._fetch_wp_api(dept)
        assert [p["name"] for p in people] == ["Pat Active"]  # emeritus excluded
        assert people[0]["title"] == "Teaching Professor"
        assert people[0]["email"] == "pat@x.edu"

    def test_faculty180_paginates_filters_and_keeps_ladder(self, monkeypatch):
        """faculty180 reads the admin-ajax users feed, drops non-ladder by rank,
        and builds first+last names."""
        pages = {
            "1": {"users": [
                {"pid": 1, "firstname": "Ada", "lastname": "Real", "rank": "Professor",
                 "email": "ada@x.edu", "slug": "ada-real"},
                {"pid": 2, "firstname": "Em", "lastname": "Past", "rank": "Professor Emeritus",
                 "email": "em@x.edu", "slug": "em-past"},
            ]},
            "2": {"users": []},
        }

        class _Resp:
            def __init__(self, page): self._page = page
            def raise_for_status(self): pass
            def json(self): return pages.get(self._page, {"users": []})

        monkeypatch.setattr("requests.post",
                            lambda *a, **k: _Resp(k.get("data", {}).get("searchpage", "1")))
        dept = {"short": "NURS", "faculty180": {
            "base": "https://nursing.x.edu", "per_page": 2,
            "ladder_filter": {"require": r"profess", "drop": r"emerit"},
        }}
        people = fg._fetch_faculty180(dept)
        assert [p["name"] for p in people] == ["Ada Real"]  # emeritus dropped
        assert people[0]["url"] == "https://nursing.x.edu/person/1-ada-real/"
        assert people[0]["email"] == "ada@x.edu"

    def test_faculty180_degrades_without_block(self):
        assert fg._fetch_faculty180({"short": "X"}) == []


class TestNameCleaners:
    def test_strip_credentials(self):
        assert fg._strip_credentials("Frank Alber, PhD") == "Frank Alber"
        assert fg._strip_credentials("Jane Doe, MD, MPH") == "Jane Doe"
        assert fg._strip_credentials("Anne Marie, RN") == "Anne Marie"
        # professional fellowship/licensure acronyms after the degree (pharmacy/
        # nursing/medical directories) — an unknown trailing acronym must not
        # block the whole strip.
        assert fg._strip_credentials("Jamie C. Barner, Ph.D., FAACP, FAPhA") == "Jamie C. Barner"
        assert fg._strip_credentials("Travis J. Carlson, Pharm.D., BCPS") == "Travis J. Carlson"
        assert fg._strip_credentials("Noël Busch-Armendariz, Ph.D., LMSW, MSSW") == "Noël Busch-Armendariz"
        # hyphenated board-certification suffixes (nursing/medical): "ACNS-BC", "FNP-BC"
        assert fg._strip_credentials("Élise Knudsen, PhD, RN, ACNS-BC") == "Élise Knudsen"
        assert fg._strip_credentials("Jane Doe, DNP, FNP-BC") == "Jane Doe"
        # a hyphenated surname is not a credential
        assert fg._strip_credentials("Anne Lopez-Garcia") == "Anne Lopez-Garcia"
        # a real two-part name with an internal comma is not a credential
        assert fg._strip_credentials("Garcia, Maria") == "Garcia, Maria"
        assert fg._strip_credentials("Christopher Hees") == "Christopher Hees"
        # generational suffix is not a credential (handled by _flip_name)
        assert fg._strip_credentials("Martin Luther King, Jr.") == "Martin Luther King, Jr."

    def test_flip_name_handles_generational_suffix(self):
        assert fg._flip_name("Little, Jr., Arthur L.") == "Arthur L. Little Jr."
        assert fg._flip_name("Smith, Arthur, III") == "Arthur Smith III"
        assert fg._flip_name("Zhou, Hong") == "Hong Zhou"  # plain still works
