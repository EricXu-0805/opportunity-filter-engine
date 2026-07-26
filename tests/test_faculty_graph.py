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
            lambda url, **_kw: BeautifulSoup(SAMPLE_HTML, "html.parser"),
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
        monkeypatch.setattr("src.collectors.ucb_common.fetch_soup", lambda url, **_kw: None)
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
                            lambda url, **_kw: BeautifulSoup(html, "html.parser"))
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

    def test_title_label_prefix_stripped_from_description(self):
        """A card whose rank field carries its scraped label ("Position title:
        Professor …") must not leak the label into the title or description."""
        dept = SCHOOL["departments"][0]
        person = {"name": "Henry Bunn", "url": "https://x.edu/p/bunn",
                  "title": "Position title: Glynn LL Isaac Professor"}
        opp = fg._normalize(SCHOOL, dept, person)
        assert opp is not None
        assert "Position title:" not in opp["description_clean"]
        assert "Glynn LL Isaac Professor" in opp["description_clean"]

    def test_link_filter_drops_nonperson_cards(self, monkeypatch):
        """Some directory pages (e.g. Stanford English /people/faculty) mix
        person cards with featured-publication cards in the same markup; the
        publication cards link to /publications/<book> and were leaking in as
        faculty named after book titles. ``link_filter`` keeps only cards whose
        href matches the person path."""
        from bs4 import BeautifulSoup
        html = """
        <div class="hb-card"><span class="hb-card__title"><a href="/people/jane-roe">Jane Roe</a></span></div>
        <div class="hb-card"><span class="hb-card__title"><a href="/publications/the-wayfinder">The Wayfinder</a></span></div>
        """
        monkeypatch.setattr("src.collectors.ucb_common.fetch_soup",
                            lambda url, **_kw: BeautifulSoup(html, "html.parser"))
        dept = {"short": "ENGLISH", "scrape": {
            "url": "https://english.stanford.edu/people/faculty",
            "link_filter": "/people/",
            "selectors": {"card": "div.hb-card", "name": ".hb-card__title a", "link": ".hb-card__title a"},
        }}
        people = fg._scrape_directory(dept)
        assert [p["name"] for p in people] == ["Jane Roe"]

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
            lambda url, **_kw: BeautifulSoup(pages[url], "html.parser") if url in pages else None,
        )
        dept = {"short": "X", "scrape": {
            "url": "https://x.edu/f",
            "selectors": {"card": "div.c", "name": ".n", "link": ".n"},
            "paginate": {"param": "page", "start": 1, "max": 5},
        }}
        names = [p["name"] for p in fg._scrape_directory(dept)]
        assert names == ["Ann Alpha", "Ben Beta"]  # page 2 repeats -> pagination stops

    def test_rank_html_entities_are_decoded_like_the_name(self, monkeypatch):
        """The rank is spliced into the generated prose, so an undecoded entity
        reaches the student ("Professor of Materials Science &amp; Engineering").
        The name was already decoded; the title was not."""
        from bs4 import BeautifulSoup
        listing = ('<div class="c"><a class="n" href="/p/a">Jane Roe</a>'
                   '<span class="t">Professor of Materials Science &amp;amp; Engineering</span></div>')
        monkeypatch.setattr(
            "src.collectors.ucb_common.fetch_soup",
            lambda url, **_kw: BeautifulSoup(listing, "html.parser"),
        )
        school = {"school_slug": "x", "source": "x_faculty", "organization": "X University",
                  "id_prefix": "x", "location": "Somewhere"}
        dept = {"short": "MSE", "name": "Department of Materials Science", "majors": [],
                "scrape": {"url": "https://x.edu/f",
                           "selectors": {"card": "div.c", "name": ".n", "link": ".n", "title": ".t"}}}
        people = fg._scrape_directory(dept)
        rec = fg._normalize(school, dept, people[0])
        desc = rec.get("description_clean") or ""
        assert "&amp;" not in desc
        assert "Materials Science & Engineering" in desc

    def test_pagination_survives_a_transient_page_failure(self, monkeypatch):
        """A page that fails to fetch must not end the walk. Drexel's CoE lost 25
        of ~116 professors — the whole Sh-Z tail — because page 16 of 21 came
        back slow and the loop treated that as the end of the directory."""
        from bs4 import BeautifulSoup
        pages = {
            "https://x.edu/f": '<div class="c"><a class="n" href="/p/a">Ann Alpha</a></div>',
            "https://x.edu/f?page=1": '<div class="c"><a class="n" href="/p/b">Ben Beta</a></div>',
            "https://x.edu/f?page=2": '<div class="c"><a class="n" href="/p/c">Cy Gamma</a></div>',
        }
        failed = {"once": False}

        def flaky(url, **_kw):
            # page=1 fails the first time only, exactly like a slow render.
            if url.endswith("?page=1") and not failed["once"]:
                failed["once"] = True
                return None
            return BeautifulSoup(pages[url], "html.parser") if url in pages else None

        monkeypatch.setattr("src.collectors.ucb_common.fetch_soup", flaky)
        dept = {"short": "X", "scrape": {
            "url": "https://x.edu/f",
            "selectors": {"card": "div.c", "name": ".n", "link": ".n"},
            "paginate": {"param": "page", "start": 1, "max": 5},
        }}
        names = [p["name"] for p in fg._scrape_directory(dept)]
        assert names == ["Ann Alpha", "Ben Beta", "Cy Gamma"]

    def test_pagination_survives_one_barren_page_then_continues(self, monkeypatch):
        """A single page whose cards haven't hydrated yields nothing new, which
        is indistinguishable from the end of the roster — keep walking, and stop
        only after two barren pages in a row."""
        from bs4 import BeautifulSoup
        pages = {
            "https://x.edu/f": '<div class="c"><a class="n" href="/p/a">Ann Alpha</a></div>',
            "https://x.edu/f?page=1": "<div></div>",  # hydrated late: no cards
            "https://x.edu/f?page=2": '<div class="c"><a class="n" href="/p/c">Cy Gamma</a></div>',
        }
        monkeypatch.setattr(
            "src.collectors.ucb_common.fetch_soup",
            lambda url, **_kw: BeautifulSoup(pages[url], "html.parser") if url in pages else None,
        )
        dept = {"short": "X", "scrape": {
            "url": "https://x.edu/f",
            "selectors": {"card": "div.c", "name": ".n", "link": ".n"},
            "paginate": {"param": "page", "start": 1, "max": 5},
        }}
        names = [p["name"] for p in fg._scrape_directory(dept)]
        assert names == ["Ann Alpha", "Cy Gamma"]

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
            lambda url, **_kw: BeautifulSoup(profile if url.endswith("/people/ada") else listing,
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

        def fake_soup(url, **_kw):
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

    def test_profile_enrich_render_uses_headless_for_walled_profiles(self, monkeypatch):
        """render:True routes the per-profile fetch through the headless browser
        (Princeton dept subdomains / umich, whose profiles sit behind the same
        Cloudflare wall as the listing), lifting the email + research-areas the
        listing omits — and never falls back to a plain fetch_soup."""
        from bs4 import BeautifulSoup
        profile = ('<div class="field--name-field-ps-people-email">'
                   '<a href="mailto:nverma@princeton.edu">nverma@princeton.edu</a></div>'
                   '<div class="field--name-field-research-areas">'
                   '<div class="field__item">Computing &amp; Networking</div>'
                   '<div class="field__item">Integrated Circuits &amp; Systems</div></div>')
        monkeypatch.setattr(fg, "_render_soup",
                            lambda url, **kw: BeautifulSoup(profile, "html.parser"))
        monkeypatch.setattr("src.collectors.ucb_common.fetch_soup",
                            lambda url, **_kw: (_ for _ in ()).throw(
                                AssertionError("plain fetch_soup used for a render profile")))
        monkeypatch.setattr(fg, "_PROFILE_ENRICH", True)
        enr = {"render": True,
               "email_selector": ".field--name-field-ps-people-email a[href^='mailto:']",
               "research_items_selector": ".field--name-field-research-areas .field__item"}
        people = [{"name": "Naveen Verma", "title": "Professor",
                   "url": "https://ece.princeton.edu/people/nverma",
                   "email": None, "research_areas": "", "keywords": []}]
        out = fg._apply_profile_enrich(people, enr)
        assert out[0]["email"] == "nverma@princeton.edu"
        assert {"Computing & Networking", "Integrated Circuits & Systems"} <= set(out[0]["keywords"])

    def test_hash_paginate_uses_single_render_session(self, monkeypatch):
        """A hash-router directory (scrape.paginate.mode='hash') is walked in one
        interactive render session via _render_paginated_soup, not the fetch-per-URL
        loop (a fresh load with the fragment pre-set never leaves page 1)."""
        from bs4 import BeautifulSoup
        page_html = ('<div class="person"><h2 class="name">'
                     '<a href="/p/a">Ada Prof</a></h2><p class="title">Professor</p></div>')
        calls = {"paged": 0}

        def fake_paginated(url, param="page", max_pages=12, card_sel="", timeout_ms=60000):
            calls["paged"] += 1
            return BeautifulSoup(page_html, "html.parser")

        monkeypatch.setattr(fg, "_render_paginated_soup", fake_paginated)
        monkeypatch.setattr(fg, "_render_soup",
                            lambda *a, **k: (_ for _ in ()).throw(
                                AssertionError("hash-paginate must not use per-URL render")))
        dept = {"short": "CHEM", "scrape": {
            "url": "https://lsa.umich.edu/chem/people/faculty.html", "render": True,
            "selectors": {"card": ".person", "name": ".name", "title": ".title"},
            "paginate": {"mode": "hash", "param": "page", "max": 5},
        }}
        people = fg._scrape_directory(dept)
        assert calls["paged"] == 1
        assert any(p["name"] == "Ada Prof" for p in people)

    def test_research_join_fills_areas_from_aggregator_page(self, monkeypatch):
        """When research areas live only on one shared page (a "research
        interests" index, or the directory card when the roster is fetched via
        API) keyed by each person's profile slug, research_join joins them: one
        fetch maps slug -> areas, accumulating across repeats (a person listed
        under several headings), and fills any spec with no areas of its own.
        GT Mathematics' aggregator + UCLA Sociology / UW Genome Sciences listings
        are the live cases."""
        page = ('<li><a href="https://x.edu/people/ada-l">Ada L</a> &mdash; '
                'Topology, Geometry</li>'
                '<li><a href="/people/ada-l">Ada L</a> &mdash; Number Theory</li>')

        class Resp:
            text = page

            def raise_for_status(self):
                return None

        monkeypatch.setattr("requests.get", lambda *a, **k: Resp())
        dept = {"research_join": {
            "url": "https://x.edu/agg",
            "item_re": (r'<li><a href="[^"]*/people/(?P<key>[^"]+)">'
                        r"(?P<name>[^<]+)</a>\s*&mdash;\s*(?P<areas>[^<]+)</li>"),
            "key": "slug"}}
        specs = [fg.faculty("Ada L", title="Professor",
                            url="https://x.edu/people/ada-l")]
        fg._apply_research_join(dept, specs)
        # areas accumulate across both <li> entries for the same slug
        assert {"Topology", "Geometry", "Number Theory"} <= set(
            fg._clean_keywords(specs[0]))

    def test_digitalmeasures_enrich_pulls_research_expertise(self, monkeypatch):
        """McCombs-style profiles render client-side from a public Digital
        Measures report keyed by ?username=; the enrich pulls the "Research
        Expertise" records block (tags stripped) as comma-split-ready text."""
        payload = {"items": [
            {"heading": {"value": "Biography"},
             "data": {"records": [{"value": "bio text"}]}},
            {"heading": {"value": "Research Expertise"}},
            {"data": {"records": [
                {"value": "Machine Learning, <b>Optimization</b>, Supply Chains"}]}},
        ]}

        class Resp:
            def json(self):
                return payload

        monkeypatch.setattr("requests.get", lambda *a, **k: Resp())
        txt = fg._fetch_digitalmeasures(
            "https://x.edu/profile/?username=abc123",
            {"client": "c", "report": "r", "heading": "Research Expertise"})
        assert txt == "Machine Learning, Optimization, Supply Chains"
        # no username in the URL -> no call, empty
        assert fg._fetch_digitalmeasures("https://x.edu/profile/", {"client": "c"}) == ""

    def test_research_join_does_not_override_existing_areas(self, monkeypatch):
        """The join only fills genuine blanks — a spec that already carries its
        own research_areas is left untouched."""
        class Resp:
            text = '<li><a href="/people/x">X</a> &mdash; Wrong Area</li>'

            def raise_for_status(self):
                return None

        monkeypatch.setattr("requests.get", lambda *a, **k: Resp())
        dept = {"research_join": {
            "url": "https://x.edu/agg",
            "item_re": r'/people/(?P<key>[^"]+)">[^<]+</a>\s*&mdash;\s*(?P<areas>[^<]+)</li>',
            "key": "slug"}}
        specs = [fg.faculty("X", url="https://x.edu/people/x",
                            research_areas="Real Area")]
        fg._apply_research_join(dept, specs)
        assert specs[0]["research_areas"] == "Real Area"

    def test_profile_enrich_selector_harvests_taxonomy_links_as_atomic_keywords(self, monkeypatch):
        """Taxonomy-links markup (UW Drupal "Fields of Interest": each area is a
        separate <a>, no delimiter) must be harvested per-element, NOT comma-split:
        a comma-bearing area ("Astrophysics, Cosmology & Gravitation") stays one
        keyword. The selector path sets ``keywords`` directly (the atomic, curated
        path), so it never re-shatters. In-scope junk + dup are dropped."""
        from bs4 import BeautifulSoup
        listing = ('<div class="c"><a class="n" href="/people/ada">Ada Q. Lovelace</a>'
                   '<span class="t">Professor</span></div>')
        profile = ('<div class="views-field views-field-term-node-tid"><span class="field-content">'
                   '<a href="/fields/cm">Condensed Matter</a>'
                   '<a href="/fields/ac">Astrophysics, Cosmology &amp; Gravitation</a>'
                   '<a href="/fields/cm">Condensed Matter</a>'      # dup → folded
                   '<a href="/fields/faculty">Faculty</a>'          # in-scope but junk-gated
                   '</span></div>'
                   '<nav class="menu"><a href="/people/faculty">All Faculty</a></nav>')  # out of scope
        monkeypatch.setattr(
            "src.collectors.ucb_common.fetch_soup",
            lambda url, **_kw: BeautifulSoup(profile if url.endswith("/people/ada") else listing,
                                      "html.parser"),
        )
        monkeypatch.setattr(fg, "_PROFILE_ENRICH", True)
        dept = {"short": "PHYS", "scrape": {
            "url": "https://phys.washington.edu/people/faculty",
            "selectors": {"card": "div.c", "name": ".n", "link": ".n", "title": ".t"},
            "profile_enrich": {"research_items_selector": ".views-field-term-node-tid a"},
        }}
        people = fg._scrape_directory(dept)
        assert len(people) == 1
        assert people[0]["keywords"] == ["Condensed Matter", "Astrophysics, Cosmology & Gravitation"]
        kws = fg._clean_keywords(people[0])
        assert "Condensed Matter" in kws
        # comma folded to " / " so the title-parenthetical subset invariant holds
        assert "Astrophysics / Cosmology & Gravitation" in kws
        assert "Faculty" not in kws and "All Faculty" not in kws

    def test_clean_selector_items_dedupes_filters_junk_and_caps(self):
        """The selector harvest is defended even when a selector slightly
        over-captures: dedupe (case-insensitive), drop DQ-junk terms and prose
        fragments (>8 words), and cap the count so a runaway selector can't dump
        a whole nav/publication list into one faculty's keywords."""
        from bs4 import BeautifulSoup
        parts = ['<a>Faculty</a>',                       # junk → dropped
                 '<a>Machine Learning</a>',
                 '<a>machine learning</a>',              # case-dup → dropped
                 '<a>' + 'word ' * 10 + '</a>']          # prose fragment → dropped
        parts += [f'<a>Area {i}</a>' for i in range(1, 14)]  # 13 distinct areas
        soup = BeautifulSoup('<div class="r">' + ''.join(parts) + '</div>', "html.parser")
        items = fg._clean_selector_items(soup, ".r a")
        assert len(items) == fg._RESEARCH_ITEMS_CAP            # capped at 12
        assert "Faculty" not in items
        assert items.count("Machine Learning") == 1           # deduped
        assert all(len(i.split()) <= 8 for i in items)        # no prose fragment

    def test_profile_enrich_research_html_re_splits_on_br(self, monkeypatch):
        """A profile research block that separates areas with <br> (no comma/semi)
        — e.g. UTexas ME's "<p class=dept-resarea-p>A<br>B<br>C</p>" — must split
        into separate keywords; the engine converts <br> to a delimiter before
        flattening tags so _clean_keywords can split it (else one >6-word blob is
        dropped and the faculty wrongly stays broad)."""
        from bs4 import BeautifulSoup
        listing = ('<div class="c"><a class="n" href="/people/ada">Ada Lovelace</a></div>')
        profile = ('<p class="dept-resarea-p">Advanced Manufacturing<br>'
                   'Robotics and Intelligent Systems<br>Thermal Fluids</p>')
        monkeypatch.setattr(
            "src.collectors.ucb_common.fetch_soup",
            lambda url, **_kw: BeautifulSoup(profile if url.endswith("/people/ada") else listing,
                                      "html.parser"))
        monkeypatch.setattr(fg, "_PROFILE_ENRICH", True)
        dept = {"short": "ME", "scrape": {
            "url": "https://www.me.utexas.edu/people/faculty-directory",
            "selectors": {"card": "div.c", "name": ".n", "link": ".n"},
            "profile_enrich": {"research_html_re": r'<p class="dept-resarea-p">(.*?)</p>'}}}
        people = fg._scrape_directory(dept)
        kws = fg._clean_keywords(people[0])
        assert {"Advanced Manufacturing", "Robotics and Intelligent Systems",
                "Thermal Fluids"} <= set(kws)

    def test_scrape_card_research_re_extracts_delimited_line(self, monkeypatch):
        """A listing card with the research as a plain <br>-delimited text line (no
        per-area element) — e.g. UCLA Physics — is harvested via a card-level
        research_re; _clean_keywords then splits the captured line into keywords."""
        from bs4 import BeautifulSoup
        html = ('<table><tbody>'
                '<tr><td><h5>Ada Lovelace</h5><p>Professor<br>'
                'High Energy, Astroparticle, Neurophysics<br>Office: 1-234<br>'
                'Phone: 5</p></td></tr></tbody></table>')
        monkeypatch.setattr("src.collectors.ucb_common.fetch_soup",
                            lambda url, **_kw: BeautifulSoup(html, "html.parser"))
        dept = {"short": "PHYS", "scrape": {
            "url": "https://pa.ucla.edu/faculty.html",
            "selectors": {"card": "tbody tr", "name": "h5", "link": "a",
                          "research_re": r"<br\s*/?>\s*([^<]+?)\s*<br\s*/?>\s*(?:Office|Phone)"},
        }}
        people = fg._scrape_directory(dept)
        assert len(people) == 1
        kws = fg._clean_keywords(people[0])
        assert {"High Energy", "Astroparticle", "Neurophysics"} <= set(kws)

    def test_profile_enrich_cap_keywords_two_hop(self, monkeypatch):
        """Stanford's on-site profiles are prose but link to a central CAP profile
        whose JSON API exposes a clean ``data.keywords`` field. The two-hop pass
        (page -> CAP id -> CAP JSON) folds the comma/newline-delimited keywords
        into separate research keywords."""
        from bs4 import BeautifulSoup
        listing = '<ul><li><a class="t" href="/people/ada">Ada Lovelace</a></li></ul>'
        profile = ('<a href="https://profiles.stanford.edu/41654">View Full '
                   'Stanford Profile</a><p>prose bio only here</p>')
        monkeypatch.setattr(
            "src.collectors.ucb_common.fetch_soup",
            lambda url, **_kw: BeautifulSoup(profile if url.endswith("/people/ada") else listing,
                                      "html.parser"))
        monkeypatch.setattr(fg, "_wp_get_json", lambda url, **_kw: {"data": {"keywords": [
            "Oceanography, Biogeochemistry, Climate Change"]}} if "41654" in url else None)
        monkeypatch.setattr(fg, "_PROFILE_ENRICH", True)
        dept = {"short": "ESYS", "scrape": {
            "url": "https://earthsystemscience.stanford.edu/faculty/faculty",
            "selectors": {"card": "li", "name": ".t", "link": ".t"},
            "profile_enrich": {"cap_keywords": True}}}
        people = fg._scrape_directory(dept)
        kws = fg._clean_keywords(people[0])
        assert {"Oceanography", "Biogeochemistry", "Climate Change"} <= set(kws)

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


class TestCuratedKeywordHygiene:
    """Curated/taxonomy keyword lists get the same hygiene the derived branch
    already applies (regression: the 6 multi-school configs shipped trailing
    periods, prose fragments, and duplicate keywords verbatim)."""

    def test_curated_strips_edge_punct_and_dedupes(self):
        person = {"keywords": ["Genetics.", "genetics", " Genomics ", "Evolution"]}
        kws = fg._clean_keywords(person)
        assert kws == ["Genetics", "Genomics", "Evolution"]  # period + dup dropped

    def test_curated_drops_prose_fragment_lead(self):
        person = {"keywords": ["with emphasis on control", "robotics",
                               "my research explores memory"]}
        kws = fg._clean_keywords(person)
        assert kws == ["robotics"]

    def test_curated_keeps_determiner_led_humanities_area(self):
        """The narrow prose-lead filter must NOT nuke legitimate determiner-led
        research areas ("the Enlightenment", "in situ microscopy")."""
        person = {"keywords": ["the Enlightenment", "in situ microscopy", "the Cold War"]}
        assert fg._clean_keywords(person) == ["the Enlightenment", "in situ microscopy", "the Cold War"]

    def test_curated_folds_internal_comma(self):
        person = {"keywords": ["Plants, Soil and Algae"]}
        assert fg._clean_keywords(person) == ["Plants / Soil and Algae"]

    def test_curated_splits_semicolon_chip(self):
        """A semicolon inside one taxonomy chip always delimits separate areas
        (regression: USC Thornton shipped 'Classical Guitar; Composition')."""
        person = {"keywords": ["Classical Guitar; Composition", "jazz"]}
        assert fg._clean_keywords(person) == ["Classical Guitar", "Composition", "jazz"]

    def test_curated_drops_academic_unit_name(self):
        """An academic-unit name is never a research area (regression: USC
        Annenberg profiles fill the expertise field with the school name)."""
        person = {"keywords": [
            "USC Annenberg School for Communication and Journalism",
            "Department of Chemistry", "media studies"]}
        assert fg._clean_keywords(person) == ["media studies"]


class TestEmailObfuscationDecoding:
    """UMass-style obfuscation: rot13 ``data-mail-to`` on teaser profiles,
    spamspan "[at]/[dot]" text on person-theme profiles, and hand-quoted
    '"at"' text (Rochester CS) — all decode to the published address."""

    def test_clean_email_normalizes_written_out_at_dot(self):
        assert fg._clean_email("anderson [at] ecs [dot] umass [dot] edu") == "anderson@ecs.umass.edu"
        assert fg._clean_email('lane "at" cs.rochester.edu') == "lane@cs.rochester.edu"
        assert fg._clean_email("plain@umass.edu") == "plain@umass.edu"

    def test_clean_email_hyphen_wrapped_at(self):
        # "-at-" / " -at- " obfuscation (umich, utexas directories)
        assert fg._clean_email("aclassen-at-umich.edu") == "aclassen@umich.edu"
        assert fg._clean_email("eckirk -at- austin.utexas.edu") == "eckirk@austin.utexas.edu"
        # a real hyphenated local part containing "at" must NOT be split
        assert fg._clean_email("jane.at-large@stanford.edu") == "jane.at-large@stanford.edu"

    def test_clean_email_repairs_clipped_edu_tld(self):
        assert fg._clean_email("premg@arizona.ed") == "premg@arizona.edu"
        assert fg._clean_email("jnisbet@uci.ed") == "jnisbet@uci.edu"
        # a well-formed .edu is untouched
        assert fg._clean_email("x@duke.edu") == "x@duke.edu"

    def test_clean_email_rejects_domainless_and_junk(self):
        assert fg._clean_email("mtcraig@umich") is None  # no TLD
        assert fg._clean_email("n/a") is None
        assert fg._clean_email("(301) 405-5935") is None

    def test_is_person_name_rejects_error_pages(self):
        from src.collectors.ucb_common import _is_person_name
        assert not _is_person_name("403 - Page Not Available")
        assert not _is_person_name("404 Not Found")
        assert not _is_person_name("500 Internal Server Error")
        assert not _is_person_name("n/a")
        # real names that merely contain "null"/one-word must still pass
        assert _is_person_name("Susan Cohen Pannullo")
        assert _is_person_name("Haroon Burhanullah")

    def test_decode_rot13_data_mail_to(self):
        from bs4 import BeautifulSoup
        el = BeautifulSoup(
            '<a data-mail-to="nyunevev/ng/purz/qbg/hznff/qbg/rqh">Email</a>',
            "html.parser").a
        assert fg._decode_rot13email(el) == "alhariri@chem.umass.edu"
        assert fg._email_from_el(el) == "alhariri@chem.umass.edu"

    def test_rot13_ignores_plain_anchor(self):
        from bs4 import BeautifulSoup
        el = BeautifulSoup('<a href="mailto:x@y.edu">x</a>', "html.parser").a
        assert fg._decode_rot13email(el) is None
        assert fg._email_from_el(el) == "x@y.edu"

    def test_template_placeholder_addresses_are_rejected(self):
        # UKy Math publishes the literal "firstname.lastname[AT]uky.edu"; the
        # [AT] de-obfuscation turns that stub into an address-shaped string that
        # belongs to nobody. Shipping it is a guaranteed bounce that reads as a
        # fabricated contact. (Yale had the same stub already in the corpus.)
        assert fg._clean_email("firstname.lastname[AT]uky.edu") is None
        assert fg._clean_email("firstname.lastname@yale.edu") is None
        assert fg._clean_email("noreply@x.edu") is None

    def test_placeholder_rule_does_not_eat_real_surnames(self):
        # The rule anchors on the whole local part, so real people whose names
        # merely start with those letters are untouched.
        assert fg._clean_email("nameera.patel@x.edu") == "nameera.patel@x.edu"
        assert fg._clean_email("testa.rossi@x.edu") == "testa.rossi@x.edu"
        assert fg._clean_email("emailia.smith@x.edu") == "emailia.smith@x.edu"

    def test_stale_mailto_href_loses_to_displayed_address(self):
        # UTD MSE/CS ship rows whose mailto: was copy-pasted from the row above,
        # so the link points at a DIFFERENT professor than the address it
        # displays. Taking the href handed students the wrong person's address
        # and, because merge dedupes on email, deleted the person the stale href
        # named (I-Ling Yen). The rendered text wins when the two disagree.
        from bs4 import BeautifulSoup
        el = BeautifulSoup(
            '<a href="mailto:orlando.auciello@utdallas.edu">'
            'kevin.brenner@utdallas.edu</a>', "html.parser").a
        assert fg._email_from_el(el) == "kevin.brenner@utdallas.edu"

    def test_href_still_wins_over_non_address_link_text(self):
        # The carve-out is narrow: only when BOTH are addresses. A normal
        # "Email Me" label must not shadow the real mailto.
        from bs4 import BeautifulSoup
        el = BeautifulSoup('<a href="mailto:real@x.edu">Email Me</a>', "html.parser").a
        assert fg._email_from_el(el) == "real@x.edu"

    def test_decode_reversed_data_user_domain(self):
        # UGA College of Education (people.coe.uga.edu) cloak: both attribute
        # strings are simply reversed and joined client-side.
        from bs4 import BeautifulSoup
        el = BeautifulSoup(
            '<span class="cloaked-e-mail" data-user="maharba.anna"'
            ' data-domain="ude.agu">E-mail</span>', "html.parser").span
        assert fg._decode_reversed_email(el) == "anna.abraham@uga.edu"
        assert fg._email_from_el(el) == "anna.abraham@uga.edu"
        # ...also when the attrs sit on a descendant of the selected element.
        wrap = BeautifulSoup(
            '<p><span data-user="eod.nhoj" data-domain="ude.agu">E-mail</span></p>',
            "html.parser").p
        assert fg._decode_reversed_email(wrap) == "john.doe@uga.edu"

    def test_reversed_ignores_plain_anchor(self):
        from bs4 import BeautifulSoup
        el = BeautifulSoup('<a href="mailto:x@y.edu">x</a>', "html.parser").a
        assert fg._decode_reversed_email(el) is None


class TestCorpusFacultyHygiene:
    def test_clean_corpus_rebuilds_title_parenthetical(self):
        rec = {
            "source_type": "faculty_research",
            "title": "Research with Prof. Ada Lovelace — CS (genetics, genetics, foo.)",
            "keywords": ["genetics", "genetics", "foo."],
        }
        fg.clean_corpus_faculty_keywords([rec])
        assert rec["keywords"] == ["genetics", "foo"]
        assert rec["title"] == "Research with Prof. Ada Lovelace — CS (genetics, foo)"

    def test_clean_corpus_leaves_parenless_title_alone(self):
        rec = {
            "source_type": "faculty_research",
            "title": "Research with Prof. Ada Lovelace — HIST",
            "keywords": ["architecture, design, and social history"],
        }
        fg.clean_corpus_faculty_keywords([rec])
        assert rec["keywords"] == ["architecture / design / and social history"]
        assert rec["title"] == "Research with Prof. Ada Lovelace — HIST"

    def test_clean_corpus_strips_bare_nav_keyword(self):
        """A bare nav word ("Research", "News") entering via the monthly
        profile-enrichment pass (not the collector's own _clean_keywords) must
        be stripped by the corpus-wide hygiene — else it fails the DQ gate's
        no-bare-nav-keyword invariant (2026-07-13: a Gies faculty carried a bare
        "research"). Multi-word phrases containing the word are kept."""
        rec = {
            "source_type": "faculty_research",
            "title": "Research with Prof. Grace Hopper — BUS",
            "keywords": ["Research", "supply chain", "News", "health services research"],
        }
        fg.clean_corpus_faculty_keywords([rec])
        assert rec["keywords"] == ["supply chain", "health services research"]


def _fac_rec(id_, *, school, pi_name, dept, email=None, url="", keywords=None,
             source=None, is_active=True):
    return {
        "id": id_,
        "source": source or f"{school}_faculty",
        "source_type": "faculty_research",
        "school": school,
        "pi_name": pi_name,
        "department": dept,
        "contact_email": email,
        "url": url,
        "title": f"Research with Prof. {pi_name} — X",
        "keywords": keywords or [],
        "metadata": {"is_active": is_active},
    }


class TestCollapseSamePersonFaculty:
    def test_same_email_same_person_collapses_keeping_richer(self):
        a = _fac_rec("a", school="utexas", pi_name="J. Eric Bickel", dept="ME",
                     email="bickel@utexas.edu", url="https://me/bickel", keywords=["decision analysis"])
        b = _fac_rec("b", school="utexas", pi_name="Eric Bickel", dept="PGE",
                     email="bickel@utexas.edu", url="", keywords=["a", "b", "c", "d"])
        res = fg.collapse_same_person_faculty([a, b])
        kept_ids = {o["id"] for o in res["kept"]}
        assert kept_ids == {"b"}  # b is keyword-richer
        assert res["removed_by_school"] == {"utexas": 1}
        # loser's profile URL is merged onto the survivor (b had none)
        assert next(o for o in res["kept"] if o["id"] == "b")["url"] == "https://me/bickel"

    def test_same_email_different_people_nulls_shared_inbox(self):
        a = _fac_rec("a", school="uiuc", pi_name="Lauren Anaya", dept="Law",
                     email="jhadler@illinois.edu")
        b = _fac_rec("b", school="uiuc", pi_name="Stephen Rushin", dept="Law",
                     email="jhadler@illinois.edu")
        res = fg.collapse_same_person_faculty([a, b])
        assert {o["id"] for o in res["kept"]} == {"a", "b"}  # both kept
        assert a["contact_email"] is None and b["contact_email"] is None
        assert res["nulled_by_school"] == {"uiuc": 2}

    def test_umbrella_collapse_keeps_peer_appointment(self):
        """A College of Computing umbrella listing collapses into the specific
        home school, but a genuine second appointment (City & Regional Planning)
        is left as its own record."""
        coc = _fac_rec("coc", school="gatech", pi_name="Clio Andris",
                       dept="College of Computing", keywords=["gis"])
        ic = _fac_rec("ic", school="gatech", pi_name="Clio Andris",
                      dept="School of Interactive Computing", keywords=["gis", "hci", "maps"])
        crp = _fac_rec("crp", school="gatech", pi_name="Clio Andris",
                       dept="School of City & Regional Planning", keywords=["planning"])
        res = fg.collapse_same_person_faculty([coc, ic, crp])
        assert {o["id"] for o in res["kept"]} == {"ic", "crp"}  # only umbrella dropped
        assert res["removed_by_school"] == {"gatech": 1}

    def test_credential_suffix_same_url_same_dept_collapses(self):
        """"Scott L. Delp, Ph.D." and "Scott L. Delp" on ONE profile URL in ONE
        department are a scrape artifact, not a joint appointment (2026-07
        audit: two such Stanford pairs survived every dedup pass)."""
        a = _fac_rec("a", school="stanford", pi_name="Scott L. Delp, Ph.D.",
                     dept="Department of Mechanical Engineering",
                     url="https://me.stanford.edu/delp", keywords=["biomechanics"])
        b = _fac_rec("b", school="stanford", pi_name="Scott L. Delp",
                     dept="Department of Mechanical Engineering",
                     url="https://me.stanford.edu/delp/",
                     keywords=["biomechanics", "neuromuscular simulation"])
        res = fg.collapse_same_person_faculty([a, b])
        assert {o["id"] for o in res["kept"]} == {"b"}
        assert res["removed_by_school"] == {"stanford": 1}

    def test_credential_suffix_across_depts_stays(self):
        """The same name variants on DIFFERENT departments AND DIFFERENT URLs
        (a genuine cross-appointment, one profile page per department) keep both
        records — only the shared-profile-URL case collapses."""
        a = _fac_rec("a", school="stanford", pi_name="Scott L. Delp, Ph.D.",
                     dept="Department of Mechanical Engineering",
                     url="https://me.stanford.edu/delp")
        b = _fac_rec("b", school="stanford", pi_name="Scott L. Delp",
                     dept="Department of Bioengineering",
                     url="https://bioe.stanford.edu/delp")
        res = fg.collapse_same_person_faculty([a, b])
        assert {o["id"] for o in res["kept"]} == {"a", "b"}

    def test_cross_dept_same_profile_url_collapses(self):
        """A cross-listed professor whose ONE profile URL is linked from several
        department directories (UCLA Luskin: Public Policy + Urban Planning +
        Social Welfare) is scraped once per directory, email-less. Same name +
        same profile URL ⟹ one person, so collapse regardless of department —
        exactly what the data-quality gate (no two faculty at one URL) requires.
        (2026-07-10: 5 such UCLA profs failed every UCLA-shard refresh.)"""
        recs = [
            _fac_rec("pp", school="ucla", pi_name="Michael Lens", dept="Public Policy",
                     url="https://luskin.ucla.edu/person/michael-lens", keywords=["housing"]),
            _fac_rec("up", school="ucla", pi_name="Michael Lens", dept="Urban Planning",
                     url="https://luskin.ucla.edu/person/michael-lens",
                     keywords=["housing", "urban inequality", "transportation"]),
            _fac_rec("sw", school="ucla", pi_name="Michael Lens", dept="Social Welfare",
                     url="https://luskin.ucla.edu/person/michael-lens/", keywords=["housing"]),
        ]
        res = fg.collapse_same_person_faculty(recs)
        assert {o["id"] for o in res["kept"]} == {"up"}  # richest record kept
        assert res["removed_by_school"] == {"ucla": 2}

    def test_same_url_collapses_when_emails_differ(self):
        """Same profile URL + same name but the two department rosters scraped
        DIFFERENT (or only one) emails. The email pass never groups them (keys
        differ) and the name pass skips them (it only considers email-less
        records) — so the pair slipped through and failed the data-quality gate
        (2026-07-14: Cornell's Kin Fai Mak, Physics + Applied & Engineering
        Physics, at one physics.cornell.edu profile URL). One URL + one name is
        one person regardless of email: collapse and keep the richer record."""
        a = _fac_rec("phys", school="cornell", pi_name="Kin Fai Mak", dept="Physics",
                     email="kfm61@cornell.edu",
                     url="https://physics.cornell.edu/kin-fai-mak",
                     keywords=["condensed matter", "2d materials"])
        b = _fac_rec("aep", school="cornell", pi_name="Kin Fai Mak",
                     dept="Applied & Engineering Physics", email=None,
                     url="https://physics.cornell.edu/kin-fai-mak/", keywords=["physics"])
        res = fg.collapse_same_person_faculty([a, b])
        assert {o["id"] for o in res["kept"]} == {"phys"}  # keyword-richer + has email
        assert res["removed_by_school"] == {"cornell": 1}
        # the survivor keeps its email; no duplicate remains at the shared URL
        assert next(o for o in res["kept"] if o["id"] == "phys")["contact_email"] == "kfm61@cornell.edu"

    def test_inactive_tombstone_duplicate_is_dropped(self):
        """A partial re-scrape can deactivate one department's listing while the
        same professor stays active under another. Collapse only dedupes active
        faculty, but the DQ gate counts inactive ones too, so the stale
        tombstone + live record collide on shared email (2026-07-12: UC Berkeley
        Tony Keaveny, ME tombstone vs live BioE, every Tuesday). Drop the
        tombstone; never touch the live record."""
        live = _fac_rec("bioe", school="ucb", pi_name="Tony Keaveny", dept="Bioengineering",
                        source="ucb_bioe_faculty", email="tonykeaveny@berkeley.edu",
                        url="https://bioeng.berkeley.edu/person/tony-keaveny", keywords=["biomechanics"])
        tomb = _fac_rec("me", school="ucb", pi_name="Tony M. Keaveny", dept="Mechanical Engineering",
                        source="ucb_me_faculty", email="tonykeaveny@berkeley.edu",
                        url="https://me.berkeley.edu/people/tony-keaveny", keywords=["orthopaedics"],
                        is_active=False)
        res = fg.collapse_same_person_faculty([live, tomb])
        assert {o["id"] for o in res["kept"]} == {"bioe"}  # live survives, tombstone dropped
        assert res["removed_by_school"] == {"ucb": 1}

    def test_inactive_tombstone_kept_when_no_active_duplicate(self):
        """An inactive tombstone with no live duplicate is a real deactivation
        record — left in place (the drop only removes tombstones a live record
        supersedes)."""
        tomb = _fac_rec("gone", school="ucb", pi_name="Departed Prof", dept="Physics",
                        source="ucb_phys_faculty", email="departed@berkeley.edu",
                        url="https://physics.berkeley.edu/departed", is_active=False)
        res = fg.collapse_same_person_faculty([tomb])
        assert {o["id"] for o in res["kept"]} == {"gone"}
        assert res["removed_by_school"] == {}

    def test_syndicated_same_slug_profile_collapses(self):
        """A professor cross-listed on two department sites serving the SAME
        profile slug with the same (or stub-subset) keywords is one syndicated
        profile, not a joint appointment (2026-07 dogfood: Caltech Abu-Mostafa
        appeared twice in Eric's top-100; 15% of Caltech faculty duplicated)."""
        cms = _fac_rec("cms", school="caltech", pi_name="Yaser S. Abu-Mostafa",
                       dept="Computing + Mathematical Sciences",
                       url="https://www.cms.caltech.edu/people/yaser",
                       keywords=["machine learning", "artificial intelligence"])
        ee = _fac_rec("ee", school="caltech", pi_name="Yaser S. Abu-Mostafa",
                      dept="Electrical Engineering",
                      url="https://www.ee.caltech.edu/people/yaser",
                      keywords=["machine learning", "artificial intelligence", "neural networks"])
        res = fg.collapse_same_person_faculty([cms, ee])
        assert {o["id"] for o in res["kept"]} == {"ee"}  # keyword-richer
        assert res["removed_by_school"] == {"caltech": 1}

    def test_syndicated_slug_merges_across_email_states_and_keeps_address(self):
        """The syndication pass must work across email states: one department's
        scrape captured the mailto, the other didn't — the email-keyed passes
        all miss that pair, the richer email-less twin outranks the contactable
        one, and the user sees the person twice (35 such groups measured
        2026-07-16). The merge keeps the richer record and propagates the
        loser's address onto it."""
        rich = _fac_rec("rich", school="gatech", pi_name="Divya Mahajan",
                        dept="School of Computer Science",
                        url="https://scs.gatech.edu/people/divya-mahajan",
                        keywords=["computer architecture", "ML systems", "accelerators"])
        stub = _fac_rec("stub", school="gatech", pi_name="Divya Mahajan",
                        dept="School of ECE", email="divya.mahajan@gatech.edu",
                        url="https://ece.gatech.edu/people/divya-mahajan",
                        keywords=["computer architecture", "ML systems"])
        res = fg.collapse_same_person_faculty([rich, stub])
        kept = res["kept"]
        assert [o["id"] for o in kept] == ["rich"]
        assert kept[0]["contact_email"] == "divya.mahajan@gatech.edu"

    def test_syndicated_slug_merges_keywordless_stub_into_rich_record(self):
        """A keyword-less directory stub sharing the rich record's slug has no
        department-specific content to preserve — it merges (GT CS listed a
        keyword-less Divya Mahajan stub next to her rich contactable ECE
        record). Both-empty pairs still stay (no evidence either way)."""
        rich = _fac_rec("rich", school="gatech", pi_name="Divya Mahajan",
                        dept="ECE", email="divya.mahajan@gatech.edu",
                        url="https://ece.gatech.edu/directory/divya-mahajan",
                        keywords=["computer architecture"])
        stub = _fac_rec("stub", school="gatech", pi_name="Divya Mahajan",
                        dept="College of Computing",
                        url="https://www.cc.gatech.edu/people/divya-mahajan")
        res = fg.collapse_same_person_faculty([rich, stub])
        assert [o["id"] for o in res["kept"]] == ["rich"]

    def test_same_slug_but_department_specific_keywords_stays(self):
        """Same slug across dept sites but genuinely different research blurbs
        (neither keyword set contains the other) = per-department curated
        profiles — both records stay."""
        a = _fac_rec("a", school="cornell", pi_name="Jo Roe", dept="Physics",
                     url="https://physics.cornell.edu/jo-roe",
                     keywords=["quantum optics", "photonics"])
        b = _fac_rec("b", school="cornell", pi_name="Jo Roe", dept="Applied Physics",
                     url="https://aep.cornell.edu/jo-roe",
                     keywords=["superconductivity", "materials"])
        res = fg.collapse_same_person_faculty([a, b])
        assert {o["id"] for o in res["kept"]} == {"a", "b"}

    def test_peer_joint_appointment_without_umbrella_is_left(self):
        """Stanford Applied Physics + Physics (no email, no umbrella) stay two
        records — the conservative no-email rule only collapses umbrella rosters."""
        a = _fac_rec("a", school="stanford", pi_name="Jane Doe", dept="Department of Applied Physics")
        b = _fac_rec("b", school="stanford", pi_name="Jane Doe", dept="Department of Physics")
        res = fg.collapse_same_person_faculty([a, b])
        assert {o["id"] for o in res["kept"]} == {"a", "b"}
        assert res["removed_by_school"] == {}


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
                            lambda url, **_kw: records if "page=1" in url else [])
        monkeypatch.setattr(fg, "_enrich_profile", lambda url, enrich:
                            ("Associate Professor", "Cognitive Psychology", [], None, True)
                            if "ada" in url else ("Lecturer", "", [], None, True))
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
                            lambda url, **_kw: BeautifulSoup(self._PROFILE_HTML, "html.parser"))
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
                            lambda url, **_kw: BeautifulSoup(html, "html.parser"))
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
                            lambda url, **_kw: BeautifulSoup(html, "html.parser"))
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
                            lambda url, **_kw: BeautifulSoup(html, "html.parser"))
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
                            lambda url, **_kw: BeautifulSoup(html, "html.parser"))
        dept = {"short": "X", "scrape": {
            "url": "https://x.edu/f",
            "selectors": {"card": "div.c", "name": ".n", "link": ".n"},
            "name_flip": True,
        }}
        assert fg._scrape_directory(dept)[0]["name"] == "Wei Zhang"

    def test_scrape_name_title_case_only_when_all_caps(self, monkeypatch):
        """SHOUTING rosters (UGA Pharmacy) retitle; mixed-case names (McLean)
        pass through untouched so their internal caps survive."""
        from bs4 import BeautifulSoup
        html = """
        <div class="c"><a class="n" href="/p/a">J. WARREN BEACH</a><p>Professor</p></div>
        <div class="c"><a class="n" href="/p/b">Sarah McLean</a><p>Professor</p></div>
        """
        monkeypatch.setattr("src.collectors.ucb_common.fetch_soup",
                            lambda url, **_kw: BeautifulSoup(html, "html.parser"))
        dept = {"short": "X", "scrape": {
            "url": "https://x.edu/f",
            "selectors": {"card": "div.c", "name": ".n", "link": ".n", "title": "p",
                          "name_title_case": True},
        }}
        assert [p["name"] for p in fg._scrape_directory(dept)] == [
            "J. Warren Beach", "Sarah McLean"]

    def test_scrape_title_html_re_captures_bare_text_rank(self, monkeypatch):
        """A rank that lives as bare text between markup with no element of its
        own (UGA Law's ``<a>Name</a><br>Title<br><a mailto>``) comes out of the
        serialized card, and still drives the ladder gate."""
        from bs4 import BeautifulSoup
        html = """
        <table>
        <tr><td class="t"><a href="/profile/ada">Ada Real</a><br/>Associate Professor of Law<br/>
            <a href="mailto:ada@x.edu">ada@x.edu</a></td></tr>
        <tr><td class="t"><a href="/profile/em">Em Past</a><br/>Professor Emerita<br/>
            <a href="mailto:em@x.edu">em@x.edu</a></td></tr>
        </table>
        """
        monkeypatch.setattr("src.collectors.ucb_common.fetch_soup",
                            lambda url, **_kw: BeautifulSoup(html, "html.parser"))
        dept = {"short": "LAW", "scrape": {
            "url": "https://x.edu/f",
            "selectors": {"card": "tr:has(td.t)", "name": "td.t > a[href^='/profile/']",
                          "link": "td.t > a[href^='/profile/']",
                          "title_html_re": r"</a>\s*<br\s*/?>\s*(.*?)<br",
                          "email": "a[href^='mailto:']"},
            "ladder_filter": {"require": r"professor", "drop": r"emerit"},
        }}
        people = fg._scrape_directory(dept)
        assert [p["name"] for p in people] == ["Ada Real"]
        assert people[0]["title"] == "Associate Professor of Law"
        assert people[0]["email"] == "ada@x.edu"

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
                            lambda url, **_kw: BeautifulSoup(html, "html.parser"))
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
                            lambda url, **_kw: BeautifulSoup(html, "html.parser"))
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

    def test_json_dir_research_field_list_and_array_segment(self, monkeypatch):
        """UCSD-Biology shape: sections[].title area tags win, prose fallback."""
        payload = [
            {"fname": "Tag", "lname": "Ged",
             "titleInfo": {"standardTitle": "Professor"},
             "profileInfo": {"sections": [{"title": "Neurobiology"},
                                          {"title": "Genetics"}],
                             "researchSummary": "prose fallback"}},
            {"fname": "Pro", "lname": "Se",
             "titleInfo": {"standardTitle": "Professor"},
             "profileInfo": {"sections": [],
                             "researchSummary": "Studies kelp forests"}},
        ]

        class _Resp:
            def raise_for_status(self): pass
            def json(self): return payload

        monkeypatch.setattr("requests.get", lambda *a, **k: _Resp())
        dept = {"short": "BIO", "json_dir": {
            "url": "https://x.edu/api", "name_fields": ["fname", "lname"],
            "title_field": "titleInfo.standardTitle",
            "research_field": ["profileInfo.sections[].title",
                               "profileInfo.researchSummary"]}}
        people = fg._fetch_json_dir(dept)
        assert people[0]["keywords"] == ["Neurobiology", "Genetics"]
        assert people[1]["research_areas"] == "Studies kelp forests"

    def test_json_dir_dotted_paths_reach_nested_fields(self, monkeypatch):
        """UCSD-Biology shape: rank nested at titleInfo.standardTitle."""
        payload = [
            {"person": {"first": "Rosalind", "last": "Franklin"},
             "titleInfo": {"standardTitle": "Distinguished Professor"},
             "contact": {"email": "rf@ucsd.edu"}, "profileUrl": "https://x.edu/rf/"},
            {"person": {"first": "Ret", "last": "Ired"},
             "titleInfo": {"standardTitle": "Professor Emeritus"},
             "contact": {"email": "ri@ucsd.edu"}},
            # missing nested hop → title falls back to default, ladder-kept
            {"person": {"first": "Flat", "last": "Record"}, "titleInfo": None},
        ]

        class _Resp:
            def raise_for_status(self): pass
            def json(self): return payload

        monkeypatch.setattr("requests.get", lambda *a, **k: _Resp())
        dept = {"short": "BIO", "json_dir": {
            "url": "https://x.edu/api/faculty",
            "name_fields": ["person.first", "person.last"],
            "title_field": "titleInfo.standardTitle",
            "email_field": "contact.email",
            "link_field": "profileUrl",
            "ladder_filter": {"require": r"\bprofessor\b", "drop": r"\bemerit"}}}
        people = fg._fetch_json_dir(dept)
        assert [p["name"] for p in people] == ["Rosalind Franklin", "Flat Record"]
        assert people[0]["title"] == "Distinguished Professor"
        assert people[0]["email"] == "rf@ucsd.edu"
        assert people[0]["url"] == "https://x.edu/rf/"


class TestCleanEmail:
    def test_percent_encoded_display_name_form(self):
        assert fg._clean_email(
            "mailto:Anthony%20Harb%20%3Canharb%40ucsd.edu%3E") == "anharb@ucsd.edu"

    def test_trailing_whitespace_and_query(self):
        assert fg._clean_email("mailto:bchoivanos@ucsd.edu ") == "bchoivanos@ucsd.edu"
        assert fg._clean_email("mailto:a@x.edu?subject=hi") == "a@x.edu"

    def test_empty_degrades_to_none(self):
        assert fg._clean_email("") is None


class TestTitleRe:
    def test_title_re_extracts_loose_text_rank(self):
        """UCSD Communication-style card: rank is loose text, no stable element."""
        from bs4 import BeautifulSoup
        html = """<ul>
        <li class='card'><span class='data'>
          <p class='h3'><a href='/f/ada.html'>Ada Prof</a></p>
          Associate Professor, Chair
          <p>Research Interests: media studies</p>
        </span></li>
        </ul>"""
        soup = BeautifulSoup(html, "html.parser")
        people = fg._parse_cards(soup, {
            "card": "li.card", "name": "p.h3 > a",
            "title_re": r"((?:(?:Distinguished|Associate|Assistant)\s+)?Professor(?:,\s*Chair)?)",
        }, "https://x.edu/")
        assert people[0]["title"] == "Associate Professor, Chair"

    def test_title_re_miss_keeps_default(self):
        from bs4 import BeautifulSoup
        soup = BeautifulSoup(
            "<li class='card'><a href='/a.html'>Ada Prof</a></li>", "html.parser")
        people = fg._parse_cards(soup, {
            "card": "li.card", "name": ":self", "title_re": r"(Regius Chair)"},
            "https://x.edu/")
        assert people[0]["title"] == "Professor"


class TestDepartmentField:
    """A single college-wide directory that carries each person's home
    department/school in a card field lands per-record department attribution
    (OSU Liberal Arts' ``div.school``), overriding the config's umbrella name."""

    _HTML = """<div>
      <div class='row'>
        <div class='dir-name'><a href='/directory/ada'>Ada Prof</a></div>
        <div class='school'>School of Public Policy</div>
        <div class='position'>Associate Professor</div>
      </div>
      <div class='row'>
        <div class='dir-name'><a href='/directory/lee'>Lee Prof</a></div>
        <div class='school'>School of Writing, Literature &amp; Film</div>
        <div class='position'>Professor</div>
      </div>
      <div class='row'>
        <div class='dir-name'><a href='/directory/kim'>Kim Prof</a></div>
        <div class='position'>Professor</div>
      </div>
    </div>"""

    _SEL = {"card": "div.row", "name": "div.dir-name a",
            "link": "div.dir-name a", "title": "div.position",
            "department_field": "div.school"}

    def test_parse_reads_per_card_department(self):
        from bs4 import BeautifulSoup
        people = fg._parse_cards(BeautifulSoup(self._HTML, "html.parser"),
                                 self._SEL, "https://x.edu/directory")
        by_name = {p["name"]: p for p in people}
        assert by_name["Ada Prof"]["department"] == "School of Public Policy"
        # HTML entity in the field is decoded to text.
        assert by_name["Lee Prof"]["department"] == "School of Writing, Literature & Film"
        # A card missing the field yields an empty override (falls back downstream).
        assert by_name["Kim Prof"]["department"] == ""

    def test_normalize_prefers_card_department_over_config(self):
        dept = {"short": "CLA", "name": "College of Liberal Arts", "majors": []}
        school = {"school_slug": "oregonstate", "source": "oregonstate_faculty",
                  "organization": "Oregon State University", "location": "Corvallis, OR",
                  "id_prefix": "oregonstate", "audience": "unknown", "work_auth_notes": ""}
        spec = fg.faculty("Ada Prof", url="https://x.edu/directory/ada",
                          department="School of Public Policy")
        rec = fg._normalize(school, dept, spec)
        assert rec["department"] == "School of Public Policy"
        # Absent per-card department → config umbrella name is kept.
        spec2 = fg.faculty("Kim Prof", url="https://x.edu/directory/kim")
        assert fg._normalize(school, dept, spec2)["department"] == "College of Liberal Arts"

    def test_normalize_department_map_rewrites_and_drops(self):
        dept = {"short": "CLA", "name": "College of Liberal Arts", "majors": [],
                "department_map": {"SPP": "School of Public Policy"}}
        school = {"school_slug": "oregonstate", "source": "oregonstate_faculty",
                  "organization": "Oregon State University", "location": "Corvallis, OR",
                  "id_prefix": "oregonstate", "audience": "unknown", "work_auth_notes": ""}
        spec = fg.faculty("Ada Prof", url="https://x.edu/a", department="SPP")
        assert fg._normalize(school, dept, spec)["department"] == "School of Public Policy"
        # An unmapped raw value falls back to the umbrella name.
        spec2 = fg.faculty("Lee Prof", url="https://x.edu/l", department="Unknown Unit")
        assert fg._normalize(school, dept, spec2)["department"] == "College of Liberal Arts"


class TestProfileCoreFieldEnrich:
    """Link-list directories (UCSD Literature/Theatre): title/email/ladder all
    live on the profile page; the ``always`` flag runs the pass without the
    OFE_ENRICH_PROFILES env gate and ``ladder_recheck`` gates after titles exist."""

    _LISTING = """<div><h1>Faculty</h1><div class='row'>
      <a href='/people/faculty/ada.html'>Prof, Ada</a>
      <a href='/people/faculty/lee.html'>Lect, Lee</a>
    </div></div>"""

    def _run(self, monkeypatch):
        from bs4 import BeautifulSoup
        profiles = {
            "https://x.edu/people/faculty/ada.html": (
                "<header class='hd'><p class='subhead'>Professor</p></header>"
                "<article class='ct'><li class='email'>"
                "<a href='mailto:ada@x.edu'>e</a></li></article>"),
            "https://x.edu/people/faculty/lee.html": (
                "<header class='hd'><p class='subhead'>Senior Continuing Lecturer"
                "</p></header><article class='ct'><li class='email'>"
                "<a href='mailto:lee@x.edu'>e</a></li></article>"),
        }
        import src.collectors.ucb_common as ucb_common
        monkeypatch.setattr(
            ucb_common, "fetch_soup",
            lambda url, **k: BeautifulSoup(self._LISTING, "html.parser")
            if "faculty/index" in url else BeautifulSoup(profiles[url], "html.parser"))
        dept = {"short": "LIT", "scrape": {
            "url": "https://x.edu/people/faculty/index.html",
            "selectors": {"card": "div.row > a", "name": ":self", "link": ":self"},
            "name_flip": True,
            "profile_enrich": {
                "always": True,
                "title_selector": "header.hd p.subhead",
                "email_selector": "article.ct li.email a[href^='mailto:']",
                "ladder_recheck": {"require": r"\bprofessor\b",
                                   "drop": r"\blecturer|\bemerit"},
            },
        }}
        return dept

    def test_profile_pass_fills_title_email_and_ladder_gates(self, monkeypatch):
        dept = self._run(monkeypatch)
        people = fg._scrape_directory(dept)
        assert [p["name"] for p in people] == ["Ada Prof"]
        assert people[0]["title"] == "Professor"
        assert people[0]["email"] == "ada@x.edu"


class TestJsonDirPostAndMaps:
    def test_post_field_filters_and_title_map(self, monkeypatch):
        """UCSD-Math shape: POST-only HR feed, job codes, class/status gates."""
        payload = [
            {"employee_preferred_first_name_current": "Ada",
             "employee_preferred_last_name_current": "Lovelace",
             "employee_class": "Academic: Faculty", "employee_status": "Active",
             "job_code": "001200", "identity_email_address_current": "ada@x.edu"},
            {"employee_preferred_first_name_current": "Ret",
             "employee_preferred_last_name_current": "Ired",
             "employee_class": "Academic: Faculty", "employee_status": "Retired",
             "job_code": "001100", "identity_email_address_current": "ri@x.edu"},
            {"employee_preferred_first_name_current": "Sta",
             "employee_preferred_last_name_current": "Ffer",
             "employee_class": "Staff", "employee_status": "Active",
             "job_code": "007700", "identity_email_address_current": "st@x.edu"},
        ]

        class _Resp:
            def raise_for_status(self): pass
            def json(self): return payload

        posts = {}

        def _post(url, data=None, headers=None, timeout=None):
            posts["data"] = data
            return _Resp()

        monkeypatch.setattr("requests.post", _post)
        monkeypatch.setattr("requests.get",
                            lambda *a, **k: (_ for _ in ()).throw(AssertionError("GET used")))
        dept = {"short": "MATH", "json_dir": {
            "url": "https://soeapp.x.edu/tools/eah/department.php",
            "method": "post", "data": {"department_code[]": "000212"},
            "name_fields": ["employee_preferred_first_name_current",
                            "employee_preferred_last_name_current"],
            "title_field": "job_code",
            "title_map": {"001100": "Professor", "001200": "Associate Professor"},
            "email_field": "identity_email_address_current",
            "field_filters": [
                {"field": "employee_class", "include": r"^Academic: Faculty$"},
                {"field": "employee_status", "exclude": r"Retired|Terminated"},
                {"field": "job_code", "include": r"^(001100|001200)$"},
            ]}}
        people = fg._fetch_json_dir(dept)
        assert posts["data"] == {"department_code[]": "000212"}
        assert [p["name"] for p in people] == ["Ada Lovelace"]
        assert people[0]["title"] == "Associate Professor"


class TestResearchJoinEmailKey:
    def test_email_keyed_join_fills_research(self, monkeypatch):
        """UCSD-Math shape: export feed keyed by work email."""
        page = ('[{"field_work_email":"ada@x.edu","view_node_1":"/p/ada",'
                '"field_primary_research_area":"Statistics"}]')

        class _Resp:
            text = page
            def raise_for_status(self): pass

        monkeypatch.setattr("requests.get", lambda *a, **k: _Resp())
        dept = {"short": "MATH", "research_join": {
            "url": "https://x.edu/export", "key": "email",
            "item_re": (r'"field_work_email":\s*"(?P<key>[^"]+)"[^{}]*?'
                        r'"field_primary_research_area":\s*"(?P<areas>[^"]+)"')}}
        specs = [fg.faculty("Ada Lovelace", email="ADA@x.edu"),
                 fg.faculty("No Match", email="nm@x.edu")]
        fg._apply_research_join(dept, specs)
        assert specs[0]["research_areas"] == "Statistics"
        assert not specs[1]["research_areas"]


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
                            lambda url, **_kw: BeautifulSoup(html, "html.parser"))
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
                            lambda url, **_kw: BeautifulSoup(html, "html.parser"))
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
                            lambda url, **_kw: records if "page=1" in url else [])
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

    def test_wp_api_acf_fields_and_ladder_filter(self, monkeypatch):
        """acf_fields walks a dotted path into the ACF block (UGA Terry keeps
        rank at job_titles[0].position.title and a plain acf.email); the same
        ladder gate as the scrape path then drops non-ladder ranks — Terry
        tags lecturers `faculty` too, so the taxonomy alone can't."""
        records = [
            {"title": {"rendered": "Amin Shiri"}, "link": "https://x.edu/d/amin/",
             "employee-type": [4],
             "acf": {"email": "amin@x.edu", "job_titles": [
                 {"position": {"title": "Assistant Professor"}}]}},
            {"title": {"rendered": "Lex Lecturer"}, "link": "https://x.edu/d/lex/",
             "employee-type": [4],
             "acf": {"email": "lex@x.edu", "job_titles": [
                 {"position": {"title": "Senior Lecturer"}}]}},
            {"title": {"rendered": "No Acf"}, "link": "https://x.edu/d/na/",
             "employee-type": [4], "acf": {"email": "", "job_titles": []}},
        ]
        monkeypatch.setattr(fg, "_wp_get_json",
                            lambda url, **_kw: records if "page=1" in url else [])
        dept = {"short": "TERRY", "api": {
            "type": "wp", "base": "https://x.edu", "post_type": "directory",
            "category_include": {"employee-type": [4]},
            "acf_fields": {"title": "job_titles.0.position.title", "email": "email"},
            "ladder_filter": {"drop": r"lecturer|emerit|adjunct"},
        }}
        people = fg._fetch_wp_api(dept)
        assert [p["name"] for p in people] == ["Amin Shiri", "No Acf"]
        assert people[0]["title"] == "Assistant Professor"
        assert people[0]["email"] == "amin@x.edu"
        # ACF miss degrades to the engine default, never raises.
        assert people[1]["title"] == "Professor"
        assert people[1]["email"] is None

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


class TestCleanKeywordsBareNav:
    def test_drops_bare_nav_junk_word(self):
        # A curated keyword list that scraped in a bare "Research" tag drops it
        # but keeps the real areas; a multi-word phrase is never touched.
        person = {"keywords": ["Sustainability", "High Performance Buildings", "Research"]}
        assert fg._clean_keywords(person) == ["Sustainability", "High Performance Buildings"]

    def test_keeps_broad_but_real_field(self):
        # "Design"/"Theory" are broad but real research fields — NOT nav junk.
        person = {"keywords": ["Design", "Theory", "People"]}
        assert fg._clean_keywords(person) == ["Design", "Theory"]

    def test_multiword_with_nav_token_kept(self):
        person = {"keywords": ["Water Resources", "Research Methods"]}
        assert fg._clean_keywords(person) == ["Water Resources", "Research Methods"]


class TestUchicagoConfig:
    def test_uchicago_config_valid(self):
        from src.collectors.schools.uchicago_faculty import SCHOOL as UC
        assert fg.validate(UC) == []

    def test_uchicago_registered(self):
        from src.collectors.schools.uchicago_faculty import SCHOOL as UC
        assert SOURCE_DEFAULTS[UC["source"]] == ("uchicago", "unknown")
        assert UC["source"] in FACULTY_SOURCES

    def test_uchicago_every_department_has_a_live_source(self):
        """33 scrape directories (incl. Booth via headless render) + 9 live
        json_dir feeds (Chemistry's own Pantheon API + the eight BSD depts on
        the shared Referer-gated endpoint). No curated seeds remain — every
        department resolves to a live source, or it's a wiring bug."""
        from src.collectors.schools.uchicago_faculty import SCHOOL as UC
        scraped = {d["short"] for d in UC["departments"] if d.get("scrape", {}).get("selectors", {}).get("card")}
        json_dir = {d["short"] for d in UC["departments"] if d.get("json_dir")}
        curated = {d["short"] for d in UC["departments"] if d.get("faculty")}
        assert scraped == {"CS", "STAT", "MATH", "PHYS", "ASTRO", "ECON", "PSYCH", "PME",
                           "SOC", "POLISCI", "HIST", "ANTHRO", "HDEV",
                           "PHIL", "ENGL", "LING", "GEOS",
                           "HARRIS", "LAW", "CROWN", "DIV", "BOOTH",
                           "CLAS", "CMLT", "EALC", "RLL", "SLAV", "SALC", "CMS",
                           "MUSI", "TAPS", "ARTH", "DOVA"}
        assert json_dir == {"CHEM", "ECEV", "NEURO", "HG", "MGCB", "BMB",
                            "OBA", "PBHS", "MICRO"}
        assert curated == set()  # curated seeds fully migrated to live json_dir
        for d in UC["departments"]:
            assert d["short"] in scraped or d["short"] in json_dir, d["short"]

    def test_uchicago_booth_uses_networkidle_render(self):
        """Booth's Coveo grid populates only after late XHRs — it must render
        (headless) and wait for networkidle, not a fixed settle that grabs 0."""
        from src.collectors.schools.uchicago_faculty import SCHOOL as UC
        booth = next(d for d in UC["departments"] if d["short"] == "BOOTH")
        assert booth["scrape"]["render"] is True
        assert booth["scrape"]["render_wait"] == "networkidle"

    def test_uchicago_bsd_json_dir_uses_referer_primary_and_link_list(self):
        """The BSD feed is shared + Referer-gated + lists joint appointments; the
        config must send a Referer, key on the PRIMARY department (index 0), and
        pull the stable profiles.uchicago.edu link from the websites list."""
        from src.collectors.schools.uchicago_faculty import SCHOOL as UC
        micro = next(d for d in UC["departments"] if d["short"] == "MICRO")
        jd = micro["json_dir"]
        assert jd["headers"]["Referer"].startswith("https://")
        assert jd["filter_index"] == 0 and jd["filter_value"] == "Microbiology"
        assert jd["link_list"]["match_value"] == "Research Network Profile"
        assert jd["research_field"] == "interests[]"

    def test_uchicago_dova_section_filter_is_exact_faculty(self):
        """DoVA groups Faculty / Associate Faculty / Teaching Fellows / Emeritus
        under sibling <h3>s; the filter must anchor ^faculty$ so the adjacent
        'Associate Faculty' and 'Visual Arts Teaching Fellows' groups don't leak."""
        from src.collectors.schools.uchicago_faculty import SCHOOL as UC
        dova = next(d for d in UC["departments"] if d["short"] == "DOVA")
        assert dova["scrape"]["section_filter"] == {"heading": "h3", "include": r"^faculty$"}

    def test_uchicago_paginated_views_carry_page_param(self):
        """The Drupal Views depts (Econ/Psych + the five SSD bio-* views + the
        four professional schools) paginate via ?page=N."""
        from src.collectors.schools.uchicago_faculty import SCHOOL as UC
        for short in ("ECON", "PSYCH", "SOC", "POLISCI", "HIST", "ANTHRO", "HDEV",
                      "HARRIS", "LAW", "CROWN", "DIV"):
            dept = next(d for d in UC["departments"] if d["short"] == short)
            assert dept["scrape"]["paginate"]["param"] == "page", short

    def test_uchicago_philosophy_slices_core_faculty_section(self):
        """Philosophy's single page lists Core/Affiliated/Emeritus under sibling
        <h3> headings; the section_filter keeps only the Core Faculty group."""
        from src.collectors.schools.uchicago_faculty import SCHOOL as UC
        phil = next(d for d in UC["departments"] if d["short"] == "PHIL")
        assert phil["scrape"]["section_filter"] == {"heading": "h3", "include": r"core faculty"}

    def test_uchicago_family_b_tile_selectors(self):
        """The Humanities profile-tile variant reads the name from h2.info and
        title/email from field--name-field-* divs (distinct from the bio-* views)."""
        from src.collectors.schools.uchicago_faculty import SCHOOL as UC
        engl = next(d for d in UC["departments"] if d["short"] == "ENGL")
        sel = engl["scrape"]["selectors"]
        assert sel["name"] == "h2.info > a > span"
        assert sel["title"] == "div.field--name-field-person-faculty-title"

    def test_uchicago_psd_mixitup_fixture_parses_and_ladder_filters(self, monkeypatch):
        """The four PSD departments share one MixItUp CMS: <li class="mix
        <role>"> cards, name in the h3 span, rank in the h3 b. The role class
        scopes the card selector (emeriti carry "emeriti-faculty", never
        "faculty") and stray emeritus *titles* inside .faculty are dropped by
        the title filter."""
        from bs4 import BeautifulSoup
        html = """
        <ul>
          <li class="mix faculty"><a href="/people/profile/matthew-stephens/">
            <div class="people_content"><h3><span>Matthew Stephens</span>
            <b>Chair, Ralph W. Gerard Professor</b></h3></div></a></li>
          <li class="mix faculty"><a href="/people/profile/old-timer/">
            <div class="people_content"><h3><span>Old Timer</span>
            <b>Professor Emeritus</b></h3></div></a></li>
          <li class="mix emeriti-faculty"><a href="/people/profile/gone-emerita/">
            <div class="people_content"><h3><span>Gone Emerita</span>
            <b>Professor</b></h3></div></a></li>
        </ul>
        """
        monkeypatch.setattr("src.collectors.ucb_common.fetch_soup",
                            lambda url, **_kw: BeautifulSoup(html, "html.parser"))
        from src.collectors.schools.uchicago_faculty import SCHOOL as UC
        stat = next(d for d in UC["departments"] if d["short"] == "STAT")
        people = fg._scrape_directory(stat)
        assert [p["name"] for p in people] == ["Matthew Stephens"]
        assert people[0]["url"] == "https://stat.uchicago.edu/people/profile/matthew-stephens/"

    def test_uchicago_bsd_json_dir_primary_link_keywords_and_chair(self, monkeypatch):
        """Drive the MICRO json_dir over a fake shared-BSD payload (no network):
        the primary-appointment filter keeps department[0]=="Microbiology" and
        drops a record whose Microbiology appointment is secondary; the chair
        (title "Chair") survives the drop-only rank filter; interests[] become
        keywords; and link_list resolves the profiles.uchicago.edu URL."""
        class _Resp:
            status_code = 200
            def raise_for_status(self): pass
            def json(self):
                return {"data": [
                    {"firstName": "Tatyana", "lastName": "Golovkina", "title": "Professor",
                     "department": ["Microbiology"], "interests": ["viruses", "bacteria"],
                     "websites": [{"name": "Research Network Profile",
                                   "url": "https://profiles.uchicago.edu/profiles/profile/37082"}]},
                    {"firstName": "Dom", "lastName": "Chair", "title": "Chair",
                     "department": ["Microbiology"], "interests": ["pathogenesis"],
                     "websites": [{"name": "Research Network Profile",
                                   "url": "https://profiles.uchicago.edu/profiles/profile/1"}]},
                    {"firstName": "Cross", "lastName": "Listed", "title": "Professor",
                     "department": ["Medicine", "Microbiology"], "interests": ["x"],
                     "websites": []},
                    {"firstName": "Em", "lastName": "Past", "title": "Professor Emeritus",
                     "department": ["Microbiology"], "interests": [], "websites": []},
                ]}
        monkeypatch.setattr("requests.get", lambda *a, **k: _Resp())
        from src.collectors.schools.uchicago_faculty import SCHOOL as UC
        micro = next(d for d in UC["departments"] if d["short"] == "MICRO")
        people = fg._fetch_json_dir(micro)
        names = {p["name"] for p in people}
        assert "Tatyana Golovkina" in names          # primary Microbiology
        assert "Dom Chair" in names                   # chair kept (drop-only filter)
        assert "Cross Listed" not in names            # secondary appt excluded
        assert "Em Past" not in names                 # emeritus dropped
        golovkina = next(p for p in people if p["name"] == "Tatyana Golovkina")
        assert golovkina["url"] == "https://profiles.uchicago.edu/profiles/profile/37082"
        assert golovkina["keywords"] == ["viruses", "bacteria"]

    def test_uchicago_chemistry_json_dir_link_base_join(self, monkeypatch):
        """Chemistry's feed carries a relative pathAlias; link_base joins it onto
        the department host, and interests[] land as keywords."""
        class _Resp:
            status_code = 200
            def raise_for_status(self): pass
            def json(self):
                return {"data": [
                    {"fullName": "Paul Alivisatos", "title": "Distinguished Service Professor",
                     "pathAlias": "/paul-alivisatos",
                     "interests": ["Materials Chemistry", "Physical Chemistry"]},
                ]}
        monkeypatch.setattr("requests.get", lambda *a, **k: _Resp())
        from src.collectors.schools.uchicago_faculty import SCHOOL as UC
        chem = next(d for d in UC["departments"] if d["short"] == "CHEM")
        people = fg._fetch_json_dir(chem)
        assert people[0]["name"] == "Paul Alivisatos"
        assert people[0]["url"] == "https://chemistry.uchicago.edu/paul-alivisatos"
        assert people[0]["keywords"] == ["Materials Chemistry", "Physical Chemistry"]

    def test_uchicago_bsd_id_is_deterministic(self):
        """The dept+name id scheme is stable (same person ⇒ same id every run),
        so a re-scrape upserts rather than duplicating (SOP §E)."""
        from src.collectors.schools.uchicago_faculty import SCHOOL as UC
        micro = next(d for d in UC["departments"] if d["short"] == "MICRO")
        spec = fg.faculty("Tatyana Golovkina", title="Professor")
        a = fg._normalize(UC, micro, spec)
        b = fg._normalize(UC, micro, spec)
        assert a["id"] == b["id"] == "faculty-uchicago-micro-42a25379"


class TestUciConfig:
    def test_uci_config_valid(self):
        from src.collectors.schools.uci_faculty import SCHOOL as UCI
        assert fg.validate(UCI) == []

    def test_uci_registered(self):
        from src.collectors.schools.uci_faculty import SCHOOL as UCI
        assert SOURCE_DEFAULTS[UCI["source"]] == ("uci", "unknown")
        assert UCI["source"] in FACULTY_SOURCES

    def test_uci_engineering_shares_one_selector_set(self):
        """The six Samueli departments reuse the Drupal-7 bean-card selectors."""
        from src.collectors.schools.uci_faculty import SCHOOL as UCI
        eng = [d for d in UCI["departments"]
               if d.get("directory_url", "").startswith("https://engineering.uci.edu/dept/")]
        assert {d["short"] for d in eng} == {"EECS", "MAE", "BME", "CBE", "CEE", "MSE"}
        cards = {d["scrape"]["selectors"]["card"] for d in eng}
        assert cards == {"div.bean-call-to-action-block"}

    def test_uci_socsci_field_filter_anchors_on_primary_department(self):
        """The shared social-sciences table concatenates the primary department
        with research-center names; the filter must anchor on 'Department of X'."""
        from src.collectors.schools.uci_faculty import SCHOOL as UCI
        poli = next(d for d in UCI["departments"] if d["short"] == "POLISCI")
        assert poli["scrape"]["field_filter"]["include"].startswith(r"^\s*Department of")

    def test_uci_depth_humanities_bio_professional_added(self):
        """Depth expansion: Bio-Sci central pages, Humanities T1 cards, Merage,
        and the cp-dir professional schools are all registered."""
        from src.collectors.schools.uci_faculty import SCHOOL as UCI
        shorts = {d["short"] for d in UCI["departments"]}
        for s in ("MBB", "NBB", "DCB", "EEB", "HIST", "PHIL", "ARTH", "CLAS",
                  "FMS", "MERAGE", "PUBHLTH", "PHARM", "NURS"):
            assert s in shorts, s

    def test_uci_bio_uses_central_server_rendered_pages(self):
        """Bio depts must scrape the central www.bio.uci.edu pages (server-
        rendered), not the JS-only dept subdomains."""
        from src.collectors.schools.uci_faculty import SCHOOL as UCI
        for s in ("MBB", "NBB", "DCB", "EEB"):
            dept = next(d for d in UCI["departments"] if d["short"] == s)
            assert dept["scrape"]["url"].startswith("https://www.bio.uci.edu/academics/faculty/"), s
            assert not dept["scrape"].get("render")  # server-rendered, no headless needed

    def test_uci_merage_extracts_rank_via_title_re(self):
        """Merage's static table has no rank field — title_re must capture the
        rank from the row text so _LADDER can drop emeriti/lecturers."""
        from src.collectors.schools.uci_faculty import SCHOOL as UCI
        mer = next(d for d in UCI["departments"] if d["short"] == "MERAGE")
        assert mer["scrape"]["selectors"].get("title_re")
        assert "emerit" in mer["scrape"]["ladder_filter"]["drop"]

    def test_uci_hard_depts_added(self):
        """ICS Informatics/Statistics (incomplete-TLS hosts, fetched via the
        engine's InCommon bundle) + the Humanities WYSIWYG core-faculty pages."""
        from src.collectors.schools.uci_faculty import SCHOOL as UCI
        shorts = {d["short"] for d in UCI["departments"]}
        for s in ("INFO", "STAT", "ENGL", "COMPLIT", "EALC", "ELS"):
            assert s in shorts, s

    def test_uci_humanities_wysiwyg_anchors_on_name_paragraph(self):
        """The T2 pages have no card element — the card must anchor on the name
        <p> that carries both a <strong> name and a mailto, or it grabs prose."""
        from src.collectors.schools.uci_faculty import SCHOOL as UCI
        engl = next(d for d in UCI["departments"] if d["short"] == "ENGL")
        assert engl["scrape"]["selectors"]["card"] == "p:has(strong):has(a[href^='mailto:'])"
        assert engl["scrape"]["selectors"]["name"] == "strong"


class TestUcsbConfig:
    def test_ucsb_config_valid(self):
        from src.collectors.schools.ucsb_faculty import SCHOOL as UCSB
        assert fg.validate(UCSB) == []

    def test_ucsb_registered(self):
        from src.collectors.schools.ucsb_faculty import SCHOOL as UCSB
        assert SOURCE_DEFAULTS[UCSB["source"]] == ("ucsb", "unknown")
        assert UCSB["source"] in FACULTY_SOURCES

    def test_ucsb_unfiltered_pages_carry_strict_ladder_filter(self):
        """Family C all-people pages (polsci/soc/chem/math) list grad students and
        emeriti — each must ship a ladder_filter or it pollutes the corpus."""
        from src.collectors.schools.ucsb_faculty import SCHOOL as UCSB
        for short in ("POLSCI", "SOC", "CHEM", "MATH", "MATSCI"):
            dept = next(d for d in UCSB["departments"] if d["short"] == short)
            assert dept["scrape"].get("ladder_filter"), short

    def test_ucsb_depth_humanities_arts_added(self):
        """Depth expansion: the Humanities & Fine Arts + ethnic-studies block
        (Family B) and the custom-theme depts are all registered."""
        from src.collectors.schools.ucsb_faculty import SCHOOL as UCSB
        shorts = {d["short"] for d in UCSB["departments"]}
        for s in ("PHIL", "ARTHI", "LING", "GLOBAL", "CHICST", "BLKST", "THDA",
                  "FRIT", "ASAM", "GEOL", "ENGL", "HIST", "EALCS", "TMP",
                  "MUS", "FAMST", "FEMST"):
            assert s in shorts, s

    def test_ucsb_famB_and_profile_email_depts_use_the_shared_selectors(self):
        """Every Family-B / no-listing-email dept scrapes name+rank off the
        people-profiles theme and backfills email from the profile page (gated)."""
        from src.collectors.schools.ucsb_faculty import SCHOOL as UCSB
        for short in ("PHIL", "ARTHI", "LING", "THDA", "MUS", "FAMST", "FEMST"):
            dept = next(d for d in UCSB["departments"] if d["short"] == short)
            assert dept["scrape"]["profile_enrich"]["email_selector"] == "a[href^='mailto:']", short
            assert dept["scrape"].get("ladder_filter"), short


class TestBoulderConfig:
    def test_boulder_config_valid(self):
        from src.collectors.schools.boulder_faculty import SCHOOL as BOULDER
        assert fg.validate(BOULDER) == []

    def test_boulder_registered(self):
        from src.collectors.schools.boulder_faculty import SCHOOL as BOULDER
        assert SOURCE_DEFAULTS[BOULDER["source"]] == ("boulder", "unknown")
        assert BOULDER["source"] in FACULTY_SOURCES

    def test_boulder_every_dept_gates_the_vivo_role_sections(self):
        """Every CU Experts dept page lists the roster in role-grouped h3
        sections ("faculty administrative position" / "faculty position" /
        "other researchers and staff") — each dept must keep only the anchored
        faculty-position section AND ladder-filter the loose-text ranks
        (Adjoint/clinical/visiting ride the same section)."""
        from src.collectors.schools.boulder_faculty import SCHOOL as BOULDER
        for dept in BOULDER["departments"]:
            sf = dept["scrape"].get("section_filter")
            assert sf and sf["include"] == r"^faculty position$", dept["short"]
            assert dept["scrape"].get("ladder_filter"), dept["short"]

    def test_boulder_vivo_cards_parse(self):
        """Representative CU Experts markup: the section gate keeps only the
        faculty-position rows, the last-comma title_re extracts the loose-text
        rank, name_flip un-inverts "Last, First", and the ladder gate drops the
        Adjoint/Lecturer rows and the rank-less row (whose mis-captured first
        name never matches the professor require-gate)."""
        from bs4 import BeautifulSoup

        from src.collectors.schools.boulder_faculty import SCHOOL as BOULDER
        html = """
        <ul><li class="subclass"><h3>faculty administrative position</h3>
          <ul class="subclass-property-list">
            <li><a href="/display/fisid_1" title="person name">Evans, John A</a>, Chair</li>
          </ul></li>
        <li class="subclass"><h3>faculty position</h3>
          <ul class="subclass-property-list">
            <li><a href="/display/fisid_1" title="person name">Evans, John A</a>, Associate Professor</li>
            <li><a href="/display/fisid_2" title="person name">Baker, Daniel N</a>, Professor Adjoint (Academic)</li>
            <li><a href="/display/fisid_3" title="person name">Allred, Aaron</a>, Lecturer</li>
            <li><a href="/display/fisid_4" title="person name">Doe, Jane</a></li>
            <li><a href="/display/fisid_5" title="person name">Frew, Eric W</a>, Professor</li>
          </ul></li>
        <li class="subclass"><h3>other researchers and staff</h3>
          <ul class="subclass-property-list">
            <li><a href="/display/fisid_6" title="person name">Smith, Bob</a>, Research Associate</li>
          </ul></li></ul>
        """
        scrape = BOULDER["departments"][0]["scrape"]
        people = fg._parse_cards(
            BeautifulSoup(html, "html.parser"), scrape["selectors"],
            "https://experts.colorado.edu/display/deptid_10318",
            ladder_filter=scrape["ladder_filter"], name_flip=True,
            section_filter=scrape["section_filter"])
        assert [(p["name"], p["title"]) for p in people] == [
            ("John A Evans", "Associate Professor"),
            ("Eric W Frew", "Professor"),
        ]
        assert people[0]["url"] == "https://experts.colorado.edu/display/fisid_1"


class TestNameLastSplitCells:
    def test_two_cell_name_is_joined(self, monkeypatch):
        """UCI Chemistry's Drupal table splits the name across a first-name and a
        last-name cell; the engine joins them via the ``name_last`` selector."""
        from bs4 import BeautifulSoup
        html = """<table><tbody>
          <tr class='odd'>
            <td class='first'>Ioan</td><td class='last'>Andricioaei</td>
            <td class='title'>Professor</td>
            <td class='email'>andricio@uci.edu</td>
            <td class='pos'>Faculty</td>
          </tr>
          <tr class='even'>
            <td class='first'>Retta</td><td class='last'>Retired</td>
            <td class='title'>Professor Emeritus</td>
            <td class='email'>rr@uci.edu</td>
            <td class='pos'>Emeritus Faculty</td>
          </tr>
        </tbody></table>"""
        soup = BeautifulSoup(html, "html.parser")
        people = fg._parse_cards(soup, {
            "card": "tr.odd, tr.even",
            "name": "td.first", "name_last": "td.last",
            "title": "td.title", "email": "td.email",
        }, "https://x.edu/", ladder_filter={"require": r"\bprofessor\b", "drop": r"\bemerit"})
        assert [p["name"] for p in people] == ["Ioan Andricioaei"]
        assert people[0]["email"] == "andricio@uci.edu"


class TestMergePreservesRecentWorks:
    def _record(self, **overrides):
        rec = {
            "id": "umich-eng-jane-roe",
            "source": "umich_faculty",
            "source_type": "faculty_research",
            "school": "umich",
            "pi_name": "Jane Roe",
            "department": "Mechanical Engineering",
            "keywords": ["soft robotics", "grippers"],
            "title": "Research with Prof. Jane Roe — ME (soft robotics, grippers)",
            "url": "https://me.umich.edu/jane-roe",
            "metadata": {"first_seen_at": "2026-01-01T00:00:00Z"},
        }
        rec.update(overrides)
        return rec

    def test_equally_rich_rescrape_keeps_recent_works(self, tmp_path, monkeypatch):
        """metadata.recent_works is run-once OpenAlex enrichment no scrape can
        reproduce, and the merge replaces metadata wholesale — so it must be
        carried even when the richer-gate does NOT fire (equal keywords)."""
        import json as _json

        works = [{"title": "Soft Robotic Grippers for Fruit Harvesting", "year": 2026}]
        committed = self._record()
        committed["metadata"]["recent_works"] = works
        pf = tmp_path / "opportunities.json"
        pf.write_text(_json.dumps([committed]))
        monkeypatch.setattr("src.collectors.ucb_common.PROCESSED_FILE", pf)

        added, updated = fg.merge_into_processed([self._record()])
        assert (added, updated) == (0, 1)
        saved = _json.loads(pf.read_text())
        assert len(saved) == 1
        assert saved[0]["metadata"]["recent_works"] == works
        assert saved[0]["metadata"]["first_seen_at"] == "2026-01-01T00:00:00Z"

    def test_keyword_richer_rescrape_updates_keywords_but_keeps_works(
        self, tmp_path, monkeypatch,
    ):
        import json as _json

        works = [{"title": "Soft Robotic Grippers for Fruit Harvesting", "year": 2026}]
        committed = self._record()
        committed["metadata"]["recent_works"] = works
        pf = tmp_path / "opportunities.json"
        pf.write_text(_json.dumps([committed]))
        monkeypatch.setattr("src.collectors.ucb_common.PROCESSED_FILE", pf)

        richer = self._record(
            keywords=["soft robotics", "grippers", "haptics"],
            title="Research with Prof. Jane Roe — ME (soft robotics, grippers, haptics)",
        )
        fg.merge_into_processed([richer])
        saved = _json.loads(pf.read_text())[0]
        assert saved["keywords"] == ["soft robotics", "grippers", "haptics"]
        assert saved["metadata"]["recent_works"] == works


class TestFreshmanNotLockedOut:
    def test_default_year_stamp_includes_freshman(self):
        """Directory scrapes never state year preferences, so the blanket
        [sophomore, junior, senior] stamp structurally locked freshmen out of
        every faculty match at every school (year score 50 vs 100). Lock out
        only when a posting explicitly does (Eric 2026-07-16)."""
        school = {"source": "x_faculty", "organization": "X", "location": "X",
                  "school_slug": "uw", "work_auth_notes": "", "id_prefix": "x"}
        rec = fg._normalize(school, {"name": "Dept of Widgets", "short": "WID"},
                            {"name": "Jane Q. Researcher", "link": "https://x.edu/jane"})
        assert rec["eligibility"]["preferred_year"] == [
            "freshman", "sophomore", "junior", "senior"]


# --- Additive identity provenance (W7a) --------------------------------------

class TestIdentityProvenance:
    """Provenance annotates where a record's fields were extracted; it is never
    a condition for keeping them. A person spec without hints (legacy path,
    un-tagged collector) must normalize byte-identically to the historical
    output — email included."""

    def _dept(self):
        return SCHOOL["departments"][0]

    def test_no_hints_produces_historical_metadata(self):
        person = {"name": "Grace Hopper", "url": "https://x.edu/p/hopper",
                  "title": "Professor", "email": "ghopper@x.edu"}
        opp = fg._normalize(SCHOOL, self._dept(), person)
        assert opp["contact_email"] == "ghopper@x.edu"
        assert opp["metadata"]["curated"] is True
        assert "verification_scope" not in opp["metadata"]
        assert "email_source" not in opp["metadata"]

    def test_hints_copied_into_metadata(self):
        person = {"name": "Grace Hopper", "url": "https://x.edu/p/hopper",
                  "title": "Professor", "email": "ghopper@x.edu",
                  "_verification_scope": "profile", "_email_source": "profile_page"}
        opp = fg._normalize(SCHOOL, self._dept(), person)
        assert opp["contact_email"] == "ghopper@x.edu"
        assert opp["metadata"]["verification_scope"] == "profile"
        assert opp["metadata"]["email_source"] == "profile_page"

    def test_bogus_scope_hint_ignored(self):
        person = {"name": "Grace Hopper", "url": "https://x.edu/p/hopper",
                  "title": "Professor", "email": "ghopper@x.edu",
                  "_verification_scope": "trust_me"}
        opp = fg._normalize(SCHOOL, self._dept(), person)
        assert "verification_scope" not in opp["metadata"]

    def test_curated_seeds_tagged_curated(self, recs):
        assert all(r["metadata"]["verification_scope"] == "curated" for r in recs)
        # and the curated tag never leaks the internal hint key into records
        assert all("_verification_scope" not in r for r in recs)

    def test_seed_configs_not_mutated_by_harvest(self):
        dept = SCHOOL["departments"][0]
        before = [dict(p) for p in dept["faculty"]]
        fg.fetch_and_normalize(SCHOOL, deep=False)
        assert dept["faculty"] == before  # copies were tagged, not the config

    def test_merge_faculty_fields_carries_email_with_its_provenance(self):
        survivor = {"contact_email": None, "metadata": {}}
        loser = {"contact_email": "ada@x.edu",
                 "metadata": {"email_source": "profile_page"}}
        fg._merge_faculty_fields(survivor, loser)
        assert survivor["contact_email"] == "ada@x.edu"
        assert survivor["metadata"]["email_source"] == "profile_page"

    def test_merge_faculty_fields_adopts_provenance_less_email(self):
        # Legacy emails without provenance are first-class forever.
        survivor = {"contact_email": "", "metadata": {}}
        loser = {"contact_email": "legacy@x.edu", "metadata": {}}
        fg._merge_faculty_fields(survivor, loser)
        assert survivor["contact_email"] == "legacy@x.edu"
        assert "email_source" not in survivor["metadata"]

    def test_merge_faculty_fields_never_clears_surviving_email(self):
        # The anti-gating invariant: a survivor's provenance-less email is
        # kept, never wiped for lacking a stamp.
        survivor = {"contact_email": "keep@x.edu", "metadata": {}}
        loser = {"contact_email": "other@x.edu",
                 "metadata": {"email_source": "profile_page"}}
        fg._merge_faculty_fields(survivor, loser)
        assert survivor["contact_email"] == "keep@x.edu"
        assert "email_source" not in survivor["metadata"]

    def test_profile_enrich_stamps_scope_and_email_source(self, monkeypatch):
        monkeypatch.setattr(fg, "_enrich_profile", lambda url, enr:
                            ("", "robotics", [], "ada@x.edu", True))
        people = [{"name": "Ada", "url": "https://x.edu/p/ada"}]
        out = fg._apply_profile_enrich(
            people, {"always": True, "email_selector": ".email"})
        assert out[0]["email"] == "ada@x.edu"
        assert out[0]["_email_source"] == "profile_page"
        assert out[0]["_verification_scope"] == "profile"

    def test_profile_enrich_failed_fetch_stamps_nothing(self, monkeypatch):
        monkeypatch.setattr(fg, "_enrich_profile", lambda url, enr:
                            ("", "", [], None, False))
        people = [{"name": "Ada", "url": "https://x.edu/p/ada",
                   "email": "kept@x.edu"}]
        out = fg._apply_profile_enrich(
            people, {"always": True, "email_selector": ".email"})
        assert out[0]["email"] == "kept@x.edu"
        assert "_verification_scope" not in out[0]
        assert "_email_source" not in out[0]
