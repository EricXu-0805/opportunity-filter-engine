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
                            lambda url: BeautifulSoup(html, "html.parser"))
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
                            lambda url: (_ for _ in ()).throw(
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
            lambda url: BeautifulSoup(profile if url.endswith("/people/ada") else listing,
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
            lambda url: BeautifulSoup(profile if url.endswith("/people/ada") else listing,
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
                            lambda url: BeautifulSoup(html, "html.parser"))
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
            lambda url: BeautifulSoup(profile if url.endswith("/people/ada") else listing,
                                      "html.parser"))
        monkeypatch.setattr(fg, "_wp_get_json", lambda url: {"data": {"keywords": [
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


def _fac_rec(id_, *, school, pi_name, dept, email=None, url="", keywords=None):
    return {
        "id": id_,
        "source_type": "faculty_research",
        "school": school,
        "pi_name": pi_name,
        "department": dept,
        "contact_email": email,
        "url": url,
        "title": f"Research with Prof. {pi_name} — X",
        "keywords": keywords or [],
        "metadata": {"is_active": True},
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
                            lambda url: records if "page=1" in url else [])
        monkeypatch.setattr(fg, "_enrich_profile", lambda url, enrich:
                            ("Associate Professor", "Cognitive Psychology", [], None)
                            if "ada" in url else ("Lecturer", "", [], None))
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

    def test_uchicago_every_department_has_a_live_source_or_curated_seeds(self):
        """21 scrape directories + 9 curated API-dump departments (Chemistry +
        the eight BSD sites are JS-only shells; the BSD endpoint needs a Referer
        header the engine doesn't send). Every department must resolve to one or
        the other — a dept with neither is a wiring bug."""
        from src.collectors.schools.uchicago_faculty import SCHOOL as UC
        scraped = {d["short"] for d in UC["departments"] if d.get("scrape", {}).get("selectors", {}).get("card")}
        curated = {d["short"] for d in UC["departments"] if d.get("faculty")}
        assert scraped == {"CS", "STAT", "MATH", "PHYS", "ASTRO", "ECON", "PSYCH", "PME",
                           "SOC", "POLISCI", "HIST", "ANTHRO", "HDEV",
                           "PHIL", "ENGL", "LING", "GEOS",
                           "HARRIS", "LAW", "CROWN", "DIV"}
        assert curated == {"CHEM", "ECEV", "NEURO", "HG", "MGCB", "BMB",
                           "OBA", "PBHS", "MICRO"}
        assert not (scraped & curated)  # a dept is one mechanism or the other
        for d in UC["departments"]:
            assert d["short"] in scraped or len(d["faculty"]) >= 10, d["short"]

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
                            lambda url: BeautifulSoup(html, "html.parser"))
        from src.collectors.schools.uchicago_faculty import SCHOOL as UC
        stat = next(d for d in UC["departments"] if d["short"] == "STAT")
        people = fg._scrape_directory(stat)
        assert [p["name"] for p in people] == ["Matthew Stephens"]
        assert people[0]["url"] == "https://stat.uchicago.edu/people/profile/matthew-stephens/"

    def test_uchicago_curated_id_stability(self):
        """Deterministic ids for the API-dump seeds — drift here duplicates the
        corpus on the next refresh (pin per SOP §E)."""
        from src.collectors.schools.uchicago_faculty import SCHOOL as UC
        recs = fg.fetch_and_normalize(UC, deep=False)
        by_name = {r["pi_name"]: r["id"] for r in recs}
        assert by_name["Paul Alivisatos"] == "faculty-uchicago-chem-d542f26a"
        assert by_name["David Freedman"] == "faculty-uchicago-neuro-64d98df9"
        assert by_name["Joseph Thornton"] == "faculty-uchicago-ecev-99ac4574"
        assert by_name["Melina E Hale"] == "faculty-uchicago-oba-a5bd418d"
        assert by_name["Lin Chen"] == "faculty-uchicago-pbhs-cce0a743"
        assert by_name["Tatyana Golovkina"] == "faculty-uchicago-micro-42a25379"

    def test_uchicago_bsd_chairs_survive_the_rank_filter(self):
        """BSD chairs carry the literal title "Chair" — the dump filter was
        drop-only, so they must be present in the curated seeds."""
        from src.collectors.schools.uchicago_faculty import SCHOOL as UC
        recs = fg.fetch_and_normalize(UC, deep=False)
        assert any(r["pi_name"] == "David Freedman" for r in recs)  # Neurobiology chair
        assert any(r["pi_name"] == "Carole Ober" for r in recs)  # Human Genetics chair


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
