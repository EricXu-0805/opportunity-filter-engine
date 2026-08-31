"""Tests for the OpenAlex scholarly-record enrichment pass.

The network (`_get`) is monkeypatched; the value under test is the accuracy
gating — institution-id match, surname match, min-works, the majority
field-consistency gate (wrong-person rejection), topic cleaning, and updates-only
apply.
"""
import json

from src.collectors import openalex_enrich as oa
from src.publication_trust import verified_recent_works, works_are_verified


def _author(name, works, inst_ids, topics):
    return {
        "display_name": name,
        "works_count": works,
        "affiliations": [{"institution": {"id": f"https://openalex.org/{i}"}} for i in inst_ids],
        "topics": [{"display_name": d, "field": {"display_name": f}} for d, f in topics],
    }


def test_clean_topic_strips_trailing_generic_noun():
    assert oa._clean_topic("Advanced Clustering Algorithms Research") == "advanced clustering algorithms"
    assert oa._clean_topic("Semiconductor materials and devices") == "semiconductor materials and devices"


def test_clean_topic_flattens_internal_delimiters():
    # OpenAlex compound labels must become a single delimiter-free phrase, else
    # an internal comma shatters one area into several in the faculty title.
    assert oa._clean_topic("Galaxies: formation, evolution, phenomena") == "galaxies formation evolution phenomena"
    assert oa._clean_topic("quantum, superfluid, helium dynamics") == "quantum superfluid helium dynamics"
    assert "," not in oa._clean_topic("stellar, planetary, and galactic")


def test_surname():
    assert oa._surname("Linda Bushnell") == "bushnell"
    assert oa._surname("Joseph A. Marino, III") == "iii" or oa._surname("Joseph A. Marino") == "marino"


def test_the_school_s_author_wins_over_the_more_published_one(monkeypatch):
    """Two OpenAlex authors named Elizabeth Rodrigues both list Grinnell.

    A5007392163 has 20 works and one Grinnell year against three at
    Universidade Federal do Pará; A5072745591 has 12 works and two of its three
    years at Grinnell. "Most works wins" picked the first and offered a
    digital-humanities scholar a materials chemist's research areas. Being the
    more prolific author is not evidence of being this school's.

    "Digital Studies Concentration" mapped to no field family when this was
    written, so the wrong-field gate never ran and institution share was the
    only thing standing between her and the chemist. It maps now, which means
    two independent rules refuse him — so the second half of this test pins the
    share rule on its own, with both candidates field-compatible.
    """
    monkeypatch.setattr(oa, "_get", lambda p: {"results": [
        {"id": "A_chemist", "display_name": "Elizabeth Rodrigues",
         "works_count": 20,
         "affiliations": [
             {"institution": {"id": "https://openalex.org/I173288447"},
              "years": [2022]},
             {"institution": {"id": "https://openalex.org/I999"},
              "years": [2019, 2018, 2017]},
         ],
         "topics": [{"display_name": "Layered Double Hydroxides",
                     "field": {"display_name": "Chemistry"}}]},
        {"id": "A_scholar", "display_name": "Elizabeth Rodrigues",
         "works_count": 12,
         "affiliations": [
             {"institution": {"id": "https://openalex.org/I173288447"},
              "years": [2020, 2017]},
             {"institution": {"id": "https://openalex.org/I888"},
              "years": [2008]},
         ],
         "topics": [{"display_name": "Digital Humanities and Scholarship",
                     "field": {"display_name": "Arts and Humanities"}}]},
    ]})

    best = oa._match_author("Elizabeth (Liz) Rodrigues", "I173288447",
                            "Digital Studies Concentration")

    assert best["id"] == "A_scholar"

    # Same two, both now publishing in a field the department allows: the
    # wrong-field gate has nothing to say and the share rule alone must still
    # prefer the author whose years are mostly at this school over the one with
    # nearly twice the works.
    monkeypatch.setattr(oa, "_get", lambda p: {"results": [
        {"id": "A_prolific", "display_name": "Elizabeth Rodrigues",
         "works_count": 20,
         "affiliations": [
             {"institution": {"id": "https://openalex.org/I173288447"},
              "years": [2022]},
             {"institution": {"id": "https://openalex.org/I999"},
              "years": [2019, 2018, 2017]},
         ],
         "topics": [{"display_name": "Book History",
                     "field": {"display_name": "Arts and Humanities"}}]},
        {"id": "A_scholar", "display_name": "Elizabeth Rodrigues",
         "works_count": 12,
         "affiliations": [
             {"institution": {"id": "https://openalex.org/I173288447"},
              "years": [2020, 2017]},
             {"institution": {"id": "https://openalex.org/I888"},
              "years": [2008]},
         ],
         "topics": [{"display_name": "Digital Humanities and Scholarship",
                     "field": {"display_name": "Arts and Humanities"}}]},
    ]})

    best = oa._match_author("Elizabeth (Liz) Rodrigues", "I173288447",
                            "Digital Studies Concentration")

    assert best["id"] == "A_scholar"


def test_a_lone_affiliation_still_scores_full_share(monkeypatch):
    """A new hire whose only listed institution is the school must not lose for
    having a short history — the share is a ratio, not a year count."""
    monkeypatch.setattr(oa, "_get", lambda p: {"results": [
        {"id": "A_new", "display_name": "Ada Lovelace", "works_count": 9,
         "affiliations": [{"institution": {"id": "https://openalex.org/I1"},
                           "years": [2025]}],
         "topics": [{"display_name": "Analytical Engines"}]},
    ]})

    assert oa._match_author("Ada Lovelace", "I1")["id"] == "A_new"


def test_the_word_department_does_not_name_a_discipline():
    """"dep-ART-ment" contains the table's "art" key, so any department whose
    name missed every earlier key was handed Arts and Humanities on the
    strength of the word "Department" — 13,755 faculty corpus-wide.

    Music and Classics landed there by accident and were fine. Entomology,
    Animal Science, Kinesiology and Pathology were handed a family none of
    their topics belong to, so the majority-compatible gate rejected the
    correct author every time and those faculty were silently never enriched.
    """
    art = {"Arts and Humanities", "Social Sciences"}
    assert oa._dept_fields("Department of Entomology") != art
    assert "Agricultural and Biological Sciences" in oa._dept_fields(
        "Department of Entomology")
    assert "Health Professions" in oa._dept_fields("Department of Pathology")
    assert "Health Professions" in oa._dept_fields("Department of Kinesiology")
    # A department that really is about art still is.
    assert oa._dept_fields("Department of Art History") == art
    assert oa._dept_fields("Art Department") == art
    assert oa._dept_fields("Department of Music") == art
    # An earlier key still wins over the word, as it always did.
    assert "Chemistry" in oa._dept_fields("Department of Chemistry")
    assert oa._dept_fields("Departments") is None


def test_the_umbrella_names_are_gated_too():
    """A department that matches no key is accepted ungated, so the guard
    abstains rather than judges. That was 8,583 of 70,631 enrichment targets
    (12.2%) — one in eight — and the largest single name in it was "School of
    Engineering" (400 people), because every engineering key here is a
    sub-discipline and plain "engineer" was never one. With these added it is
    507 (0.7%).
    """
    assert "Engineering" in oa._dept_fields("School of Engineering")
    assert "Agricultural and Biological Sciences" in oa._dept_fields(
        "College of Agricultural Sciences")
    assert "Social Sciences" in oa._dept_fields("College of Social Sciences and Humanities")
    assert "Arts and Humanities" in oa._dept_fields("Department of Spanish & Portuguese")
    assert "Computer Science" in oa._dept_fields("School of Data Science")
    assert "Environmental Science" in oa._dept_fields("Department of Environmental Sciences")
    assert "Medicine" in oa._dept_fields("Department of Physiology")

    # Order carries meaning. A school of sustainable engineering is judged as
    # engineering, and Environmental Studies is judged as environmental
    # science — not by the "studies" catch-all, which sits last for exactly
    # this reason.
    assert oa._dept_fields("School of Sustainable Engineering and the Built Environment") == oa._ENG
    assert "Earth and Planetary Sciences" in oa._dept_fields("Department of Environmental Studies")
    assert "Physics and Astronomy" not in oa._dept_fields("Department of American Studies")

    # Every key already in the table still answers first.
    assert oa._dept_fields("Department of Electrical Engineering") == oa._ENG
    assert oa._dept_fields("Department of Art History") == {"Arts and Humanities",
                                                           "Social Sciences"}


def test_health_facing_social_science_may_publish_in_medicine():
    """Measured against the cached rosters: gating social work on _SOC alone
    rejected seven correct people, among them Bridget Freisthler (182 works,
    Health Professions / Psychology / Medicine). The majority of a social work
    researcher's topics are clinical, so a family without the health fields
    refuses the person it was meant to confirm.

    The gate keeps its teeth where the wrong-person matches actually came from:
    Ashleigh Jones of Human Development was being handed "Alex K. Jones", 302
    works, all Computer Science — still refused.
    """
    for dept in ("College of Social Work", "Department of Human Development and Family Science",
                 "School of Interdisciplinary Global Studies"):
        fields = oa._dept_fields(dept)
        assert "Medicine" in fields, dept
        assert "Computer Science" not in fields, dept
        assert "Engineering" not in fields, dept

    idx = oa.index_roster([
        _roster_row("Alex K. Jones", works=302, topics=["computer architecture"],
                    fields=["Computer Science", "Computer Science", "Engineering"]),
    ])
    author, why = oa._match_in_roster(
        "Ashleigh Jones", "Department of Human Development and Family Science", idx)
    assert author is None
    assert why == "field_reject"

    idx = oa.index_roster([
        _roster_row("Bridget Freisthler", works=182, topics=["child maltreatment"],
                    fields=["Health Professions", "Psychology", "Medicine"]),
    ])
    author, why = oa._match_in_roster("Bridget Freisthler", "College of Social Work", idx)
    assert why == "ok"
    assert author["topics"] == ["child maltreatment"]


def test_a_shared_initial_is_not_a_shared_person():
    """Surname + first initial is all that bound a faculty member to a roster
    author, so Christy Hickman was being handed Candice Hickman's research and
    Ashleigh Jones was being handed Alex K. Jones's 302 Computer Science works.
    Both really are C. Hickman and A. Jones at that school, so neither the
    institution gate nor the field gate can see the difference.

    Measured on the cached rosters: 45 of 1,223 accepted matches (3.7%) were
    two different people. Twelve of the thirty-six inspectable ones were
    Chinese or Korean names — Li Wang against Lu Wang, Jun Li against Jie Li,
    Jeongwon Kim against Jiwoong Kim — because a shared surname and initial
    carry the least information exactly where surnames are most shared.
    """
    can = oa._given_names_can_be_one_person
    for faculty, author in (("Christy Hickman", "Candice Hickman"),
                            ("Ashleigh Jones", "Alex K. Jones"),
                            ("Li Wang", "Lu Wang"),
                            ("Jun Li", "Jie Li"),
                            ("Jeongwon Kim", "Jiwoong Kim"),
                            ("Dan Greene", "David L. Greene"),
                            ("Christine Vossler", "Christian A. Vossler")):
        assert not can(faculty, author), (faculty, author)

    # ...and the ways one person is written two ways, each observed as a
    # wrong refusal on those same rosters.
    for faculty, author in (("Michael Guidry", "Mike Guidry"),
                            ("Joe Miles", "Joseph R. Miles"),
                            ("Charlie Kwit", "Charles Kwit"),
                            ("Pam Linden", "Pamela Linden"),
                            ("Oswaldo Rafael Nunez", "Osvaldo Nunez"),
                            ("Pawel Stanislaw Jung", "Paweł S. Jung"),
                            ("Gokhan Mumcu", "Gökhan Mumcu"),
                            ("Elizabeth Rodrigues", "E. Rodrigues"),
                            ("Ada Lovelace", "Ada Lovelace")):
        assert can(faculty, author), (faculty, author)

    # One letter apart is a spelling variant only in a name long enough for
    # that to be true; at three letters it would make Jun and Jie one person.
    assert oa._off_by_one("oswaldo", "osvaldo")
    assert not oa._off_by_one("jun", "jie")


def test_the_roster_refuses_a_stranger_with_the_right_initial():
    idx = oa.index_roster([
        _roster_row("Candice Hickman", works=6, topics=["nursing education"],
                    fields=["Medicine", "Health Professions", "Psychology"]),
    ])
    author, why = oa._match_in_roster("Christy Hickman", "College of Social Work", idx)
    assert author is None
    assert why == "given_name_reject"

    # The same rule settles a collision the fields cannot: two candidates in
    # one compatible family, only one of whom is plausibly this person.
    idx = oa.index_roster([
        _roster_row("Candice Hickman", works=6, topics=["nursing education"],
                    fields=["Medicine", "Health Professions", "Psychology"]),
        _roster_row("Christy L. Hickman", works=20, topics=["child welfare"],
                    fields=["Health Professions", "Psychology", "Social Sciences"]),
    ])
    author, why = oa._match_in_roster("Christy Hickman", "College of Social Work", idx)
    assert why == "ok"
    assert author["topics"] == ["child welfare"]


def test_the_search_path_checks_the_given_name_too(monkeypatch):
    """The surname alone was the whole name test on the search path, weaker
    than the roster path's surname + initial."""
    monkeypatch.setattr(oa, "_get", lambda p: {"results": [
        {"id": "A_stranger", "display_name": "Alex K. Jones", "works_count": 302,
         "affiliations": [{"institution": {"id": "https://openalex.org/I1"},
                           "years": [2024, 2023]}],
         "topics": [{"display_name": "Computer Architecture",
                     "field": {"display_name": "Computer Science"}}]},
    ]})
    # The department is the stranger's own field, so the wrong-field gate has
    # nothing to say and only the name can refuse him.
    assert oa._dept_fields("Department of Computer Science") == oa._ENG
    assert oa._match_author("Ashleigh Jones", "I1",
                            "Department of Computer Science") is None


def test_author_topics_requires_institution_and_surname(monkeypatch):
    # right surname but WRONG institution -> no match
    monkeypatch.setattr(oa, "_get", lambda p: {"results": [
        _author("Linda Bushnell", 80, ["I999"], [("control systems", "Engineering")])]})
    assert oa.author_topics("Linda Bushnell", "I201448701", "Electrical Engineering") == []
    # right institution + surname + field-compatible -> topics
    monkeypatch.setattr(oa, "_get", lambda p: {"results": [
        _author("Linda Bushnell", 80, ["I201448701"],
                [("control systems", "Engineering"), ("network security", "Computer Science")])]})
    out = oa.author_topics("Linda Bushnell", "I201448701", "Electrical Engineering")
    assert "control systems" in out and "network security" in out


def test_author_topics_majority_field_gate_rejects_wrong_person(monkeypatch):
    # same name, same institution, but a seismologist (Earth Sciences) — must be
    # rejected for an Electrical Engineering professor even though one topic is
    # mis-labelled Computer Science.
    monkeypatch.setattr(oa, "_get", lambda p: {"results": [
        _author("M. E. West", 236, ["I130701444"], [
            ("earthquake and tectonic", "Earth and Planetary Sciences"),
            ("seismology", "Computer Science"),
            ("seismic waves", "Earth and Planetary Sciences"),
            ("geochemical analysis", "Earth and Planetary Sciences"),
            ("geophysics", "Earth and Planetary Sciences")])]})
    assert oa.author_topics("Michael E West", "I130701444", "School of Electrical Engineering") == []


def test_match_author_middle_name_fallback(monkeypatch):
    # Directories that print full legal names ("Iain Douglas Boyd") get ZERO
    # results from OpenAlex full-text author search (indexed as "Iain D. Boyd"),
    # which silently zeroed out whole schools (boulder). The first+last retry
    # must recover the match — and every candidate it returns still passes the
    # same institution gate (the same-surname humanities professor loses).
    def _fake_get(p):
        if p["search"] == "Iain Douglas Boyd":
            return {"results": []}
        assert p["search"] == "Iain Boyd"
        return {"results": [
            _author("Iain D. Boyd", 500, ["I188538660"], [("hypersonic flows", "Engineering")]),
            _author("Iain Boyd Whyte", 90, ["I999"], [("architectural history", "Arts and Humanities")]),
        ]}
    monkeypatch.setattr(oa, "_get", _fake_get)
    best = oa._match_author("Iain Douglas Boyd", "I188538660", "Department of Aerospace Engineering Sciences")
    assert best is not None and best["display_name"] == "Iain D. Boyd"


def test_match_author_two_token_name_has_no_fallback(monkeypatch):
    # A 2-token name has no simplified variant — a miss stays a single query,
    # so unmatched faculty don't double the API spend.
    calls = []
    def _fake_get(p):
        calls.append(p["search"])
        return {"results": []}
    monkeypatch.setattr(oa, "_get", _fake_get)
    assert oa._match_author("Jane Roe", "I201448701", "Electrical Engineering") is None
    assert calls == ["Jane Roe"]


def test_name_variants():
    assert oa._name_variants("Iain Douglas Boyd") == ["Iain Douglas Boyd", "Iain Boyd"]
    assert oa._name_variants("Linda Bushnell") == ["Linda Bushnell"]
    assert oa._name_variants("Allison Paige Anderson Hayman") == [
        "Allison Paige Anderson Hayman", "Allison Hayman"]


def test_author_topics_min_works(monkeypatch):
    monkeypatch.setattr(oa, "_get", lambda p: {"results": [
        _author("Jane Roe", 3, ["I201448701"], [("topic", "Engineering")])]})
    assert oa.author_topics("Jane Roe", "I201448701", "Electrical Engineering") == []


def test_school_inst_covers_every_registered_school():
    # A school missing here silently gets zero OpenAlex enrichment (its
    # faculty never become harvest targets), so the map must cover every
    # registered school — the gap that hid ucb/umich/princeton.
    from src.collectors.schools import SCHOOL_CONFIGS

    slugs = {cfg["school_slug"] for cfg in SCHOOL_CONFIGS} | {"uiuc", "ucb"}
    missing = slugs - set(oa.SCHOOL_INST)
    assert not missing, f"schools without an OpenAlex institution id: {missing}"


def test_targets_accepts_newly_mapped_schools():
    opps = [
        {"source_type": "faculty_research", "pi_name": "A", "school": "ucb",
         "url": "https://eecs.berkeley.edu/a"},
        {"source_type": "faculty_research", "pi_name": "B", "school": "princeton",
         "url": "https://math.princeton.edu/b"},
        {"source_type": "faculty_research", "pi_name": "C", "school": "unmapped-school",
         "url": "https://x.edu/c"},
    ]
    assert [o["pi_name"] for o in oa._targets(opps, None)] == ["A", "B"]


class _Resp429:
    status_code = 429

    @staticmethod
    def json():
        return {"error": "budget exhausted"}


def test_get_warns_once_on_429(monkeypatch, caplog):
    monkeypatch.setattr(oa.requests, "get", lambda *a, **k: _Resp429())
    monkeypatch.setattr(oa, "_warned_429", False)
    monkeypatch.setattr(oa, "_RETRY_429_WAIT", 0)
    with caplog.at_level("WARNING", logger="src.collectors.openalex_enrich"):
        assert oa._get({"search": "x"}) == {}
        assert oa._get({"search": "y"}) == {}
    warnings = [r for r in caplog.records if "429" in r.getMessage()]
    assert len(warnings) == 1  # surfaced, but not once per author
    assert oa._warned_429 is True


def test_get_transient_429_recovers_without_flag(monkeypatch):
    # A single burst 429 followed by a 200 is a per-second rate limit, not
    # budget exhaustion — must NOT set the abort flag.
    class _Ok:
        status_code = 200

        @staticmethod
        def json():
            return {"results": [{"display_name": "ok"}]}

    responses = [_Resp429(), _Ok()]
    monkeypatch.setattr(oa.requests, "get", lambda *a, **k: responses.pop(0))
    monkeypatch.setattr(oa, "_warned_429", False)
    monkeypatch.setattr(oa, "_RETRY_429_WAIT", 0)
    out = oa._get({"search": "x"})
    assert out["results"][0]["display_name"] == "ok"
    assert oa._warned_429 is False


def test_harvest_works_aborts_on_confirmed_429_and_resumes_past_misses(monkeypatch, tmp_path):
    # Misses go to the .misses sidecar; a resumed run skips BOTH matches and
    # misses (every miss already cost a metered call); a confirmed 429 aborts
    # instead of burning through the target list, without recording the
    # aborted target as a miss.
    import json as _json

    opps = [
        {"source_type": "faculty_research", "pi_name": f"P{i} Roe", "school": "uw",
         "url": f"https://x.edu/p{i}"}
        for i in range(4)
    ]
    ckpt = str(tmp_path / "works.json")

    monkeypatch.setattr(oa, "_warned_429", False)
    monkeypatch.setattr(oa, "_match_author", lambda *a, **k: None)  # all miss
    mapping = oa.harvest_works(opps, checkpoint_path=ckpt, throttle=0)
    assert mapping == {}
    assert sorted(_json.load(open(ckpt + ".misses"))) == [oa._person_key(o) for o in opps]

    # Resume: all four known misses are skipped — zero further lookups.
    calls = []
    monkeypatch.setattr(oa, "_match_author", lambda *a, **k: calls.append(1))
    oa.harvest_works(opps, checkpoint_path=ckpt, resume=True, throttle=0)
    assert calls == []

    # Confirmed 429 aborts on a fresh target; the aborted target is not a miss.
    def _flag_and_miss(*a, **k):
        oa._warned_429 = True
        return None

    monkeypatch.setattr(oa, "_match_author", _flag_and_miss)
    fresh = [{"source_type": "faculty_research", "pi_name": "New Person", "school": "uw",
              "url": "https://x.edu/new"}]
    ckpt2 = str(tmp_path / "works2.json")
    oa.harvest_works(fresh, checkpoint_path=ckpt2, throttle=0)
    assert _json.load(open(ckpt2 + ".misses")) == []
    monkeypatch.setattr(oa, "_warned_429", False)


def test_apply_is_updates_only():
    opps = [
        {"pi_name": "A", "school": "uw", "url": "https://x.edu/a"},
        {"pi_name": "E", "school": "uw", "url": "https://x.edu/e", "keywords": ["existing"]},
    ]
    n = oa.apply_openalex(opps, {"https://x.edu/a": ["robotics"], "https://x.edu/e": ["nope"]})
    assert n == 1
    assert opps[0]["keywords"] == ["robotics"]
    assert opps[1]["keywords"] == ["existing"]


class _Resp200:
    status_code = 200

    def __init__(self, payload):
        self._payload = payload

    def json(self):
        return self._payload


def _work(title, year, field="Engineering"):
    return {"display_name": title, "publication_year": year,
            "primary_topic": {"field": {"display_name": field}}}


def test_author_recent_works_fetch(monkeypatch):
    seen = {}

    def _fake_get(url, params=None, headers=None, timeout=None):
        seen["url"], seen["params"] = url, params
        return _Resp200({"results": [
            _work("Soft  Robotic\nGrippers for Fruit Harvesting", 2026),
            _work("No Year Paper", None),
            _work("T" * 500, 2025),
            _work("Fourth Paper Beyond Cap", 2024),
        ]})

    monkeypatch.setattr(oa.requests, "get", _fake_get)
    works = oa.author_recent_works("https://openalex.org/A123", "Mechanical Engineering")
    assert seen["url"] == oa._WORKS_API
    assert seen["params"]["filter"] == "author.id:https://openalex.org/A123"
    assert seen["params"]["sort"] == "publication_date:desc"
    assert seen["params"]["per-page"] == oa._WORKS_FETCH
    assert seen["params"]["select"] == "display_name,publication_year,primary_topic"
    # whitespace collapsed, yearless dropped, titles capped at 200, max 3 kept
    assert works[0] == {"title": "Soft Robotic Grippers for Fruit Harvesting", "year": 2026}
    assert len(works[1]["title"]) == 200
    assert len(works) <= oa._MAX_WORKS
    assert all(w["year"] for w in works)


def test_author_recent_works_drops_wrong_field_conflation(monkeypatch):
    # OpenAlex conflates same-name people: a CS/NLP professor's author id gets
    # a myocardial-biology paper as the most recent work. The per-work field
    # filter must drop it and keep the real CS papers behind it.
    monkeypatch.setattr(oa.requests, "get", lambda *a, **k: _Resp200({"results": [
        _work("MiR-32-3p improves ISO induced AC16 myocardial cell injury", 2026,
              field="Biochemistry, Genetics and Molecular Biology"),
        _work("Structure-guided discovery of pyrazolo-pyridin-amines", 2026, field="Medicine"),
        _work("Dense Passage Retrieval for Open-Domain QA", 2025, field="Computer Science"),
        _work("Evaluating Large Language Models", 2024, field="Computer Science"),
    ]}))
    works = oa.author_recent_works("A1", "Department of Computer Science")
    assert [w["title"] for w in works] == [
        "Dense Passage Retrieval for Open-Domain QA",
        "Evaluating Large Language Models",
    ]


def test_the_authors_own_fields_outrank_the_department_family(monkeypatch):
    # Production 2026-08-30. A student's generated cold email told Zhi-Pei
    # Liang — UIUC ECE, MRI reconstruction — that his "recent paper" was
    # "SearchAuditor: Auditing and Attributing Failures in Long-Horizon Search
    # Agents". His two other cited papers were geochemical anomaly detection
    # and multi-agent figure generation. None are his: the author id was
    # correct and OpenAlex had conflated other people's work into it, which
    # newest-first surfaces first.
    #
    # The department gate could not stop it, and for this professor it points
    # the wrong way: Electrical & Computer Engineering maps to nine fields
    # including Computer Science and Environmental Science, so all three
    # intruders pass — while his own MRI papers sit under Medicine, which ECE
    # does not map to, so they were being dropped.
    #
    # His own topic profile says Medicine and Engineering, and it is a majority
    # signal over 364 works rather than a recency sample of three. When we have
    # it, the department is a worse proxy for the same question.
    monkeypatch.setattr(oa.requests, "get", lambda *a, **k: _Resp200({"results": [
        _work("SearchAuditor: Auditing Long-Horizon Search Agents", 2026,
              field="Computer Science"),
        _work("Spectral-Spatial Networks for Geochemical Anomalies", 2026,
              field="Environmental Science"),
        _work("Crafter: Editable Scientific Figure Generation", 2026,
              field="Computer Science"),
        _work("Subspace Imaging for High-Resolution MR Spectroscopy", 2025,
              field="Medicine"),
    ]}))
    dept = "Electrical & Computer Engineering"
    assert "Computer Science" in oa._dept_fields(dept)
    assert "Medicine" not in oa._dept_fields(dept)

    assert [w["title"] for w in oa.author_recent_works("A1", dept)] == [
        "SearchAuditor: Auditing Long-Horizon Search Agents",
        "Spectral-Spatial Networks for Geochemical Anomalies",
        "Crafter: Editable Scientific Figure Generation",
    ]
    assert [
        w["title"] for w in
        oa.author_recent_works("A1", dept, author_fields=["Medicine", "Medicine", "Engineering"])
    ] == ["Subspace Imaging for High-Resolution MR Spectroscopy"]


def test_author_recent_works_ungated_dept_keeps_all(monkeypatch):
    # A department with no field mapping can't be judged, so every work passes
    # (same philosophy as the ungated author-topics path).
    monkeypatch.setattr(oa.requests, "get", lambda *a, **k: _Resp200({"results": [
        _work("An Interdisciplinary Study", 2026, field="Medicine"),
    ]}))
    assert oa.author_recent_works("A1", "Zzz Unit") == [
        {"title": "An Interdisciplinary Study", "year": 2026}]


def test_author_recent_works_dedups_preprint_published_pairs(monkeypatch):
    monkeypatch.setattr(oa.requests, "get", lambda *a, **k: _Resp200({"results": [
        _work("Same Paper Twice", 2026),
        _work("same  paper twice", 2026),
        _work("A Different Paper", 2025),
    ]}))
    works = oa.author_recent_works("A1", "Electrical Engineering")
    assert [w["title"] for w in works] == ["Same Paper Twice", "A Different Paper"]


def test_harvest_works_targets_matched_authors_only(monkeypatch):
    opps = [
        {"pi_name": "A Match", "school": "uw", "url": "https://x.edu/a",
         "keywords": ["robotics"], "source_type": "faculty_research"},
        {"pi_name": "B NoMatch", "school": "uw", "url": "https://x.edu/b",
         "source_type": "faculty_research"},
        {"pi_name": "C Done", "school": "uw", "url": "https://x.edu/c",
         "source_type": "faculty_research",
         "metadata": {"recent_works": [{"title": "old", "year": 2020}],
                      "publication_attribution_status": oa.ATTRIBUTION_VERIFIED}},
        {"pi_name": "D Other", "school": "not-registered", "url": "https://y.edu/d",
         "source_type": "faculty_research"},
    ]

    def _fake_match(name, inst_id, dept=""):
        return {"id": "A1"} if "Match" in name and "No" not in name else None

    monkeypatch.setattr(oa, "_match_author", _fake_match)
    monkeypatch.setattr(oa, "author_recent_works",
                        lambda aid, dept="", **kw: [{"title": "Recent Paper", "year": 2026}])
    mapping = oa.harvest_works(opps, throttle=0)
    # keyworded faculty ARE works targets; VERIFIED-enriched + unmapped schools
    # are not (holding unverifiable papers does not make a record done) — and the entry carries the resolved author id (the provenance
    # apply_works turns into a verified_author_id stamp).
    assert mapping == {"https://x.edu/a#a match": {
        "author_id": "A1", "works": [{"title": "Recent Paper", "year": 2026}]}}


def test_apply_works_is_updates_only_and_capped():
    opps = [
        {"pi_name": "A", "school": "uw", "url": "https://x.edu/a",
         "source_type": "faculty_research"},
        {"pi_name": "B", "school": "uw", "url": "https://x.edu/b",
         "source_type": "faculty_research",
         "metadata": {"recent_works": [{"title": "keep me", "year": 2020}]}},
        {"pi_name": "C", "school": "uw", "url": "https://x.edu/c",
         "source_type": "faculty_research"},
    ]
    mapping = {
        "https://x.edu/a": [{"title": "W" * 300, "year": 2026},
                            {"title": "Second", "year": 2025},
                            {"title": "Third", "year": 2024},
                            {"title": "Fourth", "year": 2023}],
        "https://x.edu/b": [{"title": "overwrite attempt", "year": 2026}],
    }
    before = len(opps)
    n = oa.apply_works(opps, mapping)
    assert n == 1
    assert len(opps) == before
    stored = opps[0]["metadata"]["recent_works"]
    assert len(stored) == oa._MAX_WORKS
    assert len(stored[0]["title"]) == oa._TITLE_CAP
    # legacy bare-list entries carry no author id → stamped name_match
    assert opps[0]["metadata"]["publication_attribution_status"] == oa.ATTRIBUTION_NAME_MATCH
    assert opps[1]["metadata"]["recent_works"] == [{"title": "keep me", "year": 2020}]
    # untouched records are never retro-stamped
    assert "publication_attribution_status" not in opps[1]["metadata"]
    assert "metadata" not in opps[2] or not opps[2]["metadata"].get("recent_works")


def test_apply_works_upgrades_when_store_is_richer():
    # Re-applying the fuller works library promotes a 1-paper record to the full
    # set (the LFS-era 1 -> 3 upgrade), but never downgrades a richer record.
    opps = [
        {"pi_name": "A", "school": "uw", "url": "https://x.edu/a",
         "source_type": "faculty_research",
         "metadata": {"recent_works": [{"title": "solo", "year": 2024}]}},
        {"pi_name": "B", "school": "uw", "url": "https://x.edu/b",
         "source_type": "faculty_research",
         "metadata": {"recent_works": [{"title": "p1", "year": 2026},
                                       {"title": "p2", "year": 2025},
                                       {"title": "p3", "year": 2024}]}},
    ]
    mapping = {
        "https://x.edu/a": [{"title": "n1", "year": 2026}, {"title": "n2", "year": 2025},
                            {"title": "n3", "year": 2024}],
        "https://x.edu/b": [{"title": "only one", "year": 2026}],  # fewer -> no downgrade
    }
    n = oa.apply_works(opps, mapping)
    assert n == 1
    assert len(opps[0]["metadata"]["recent_works"]) == 3  # 1 -> 3 upgrade
    assert opps[1]["metadata"]["recent_works"][0]["title"] == "p1"  # unchanged


def test_apply_works_stamps_verified_for_id_resolved_entries():
    # The current harvest format carries the resolved OpenAlex author id →
    # verified_author_id; a dict entry WITHOUT one degrades honestly to
    # name_match rather than claiming verification it can't prove.
    opps = [
        {"pi_name": "A", "school": "uw", "url": "https://x.edu/a",
         "source_type": "faculty_research"},
        {"pi_name": "B", "school": "uw", "url": "https://x.edu/b",
         "source_type": "faculty_research"},
    ]
    mapping = {
        "https://x.edu/a": {"author_id": "https://openalex.org/A123",
                            "works": [{"title": "Verified Paper", "year": 2026}]},
        "https://x.edu/b": {"works": [{"title": "Idless Paper", "year": 2026}]},
    }
    assert oa.apply_works(opps, mapping) == 2
    assert opps[0]["metadata"]["publication_attribution_status"] == oa.ATTRIBUTION_VERIFIED
    assert opps[1]["metadata"]["publication_attribution_status"] == oa.ATTRIBUTION_NAME_MATCH


def test_apply_works_upgrade_restamps_with_the_new_entrys_status():
    # The stamp describes the works actually stored: when a verified harvest
    # replaces a name_match set, the stamp upgrades with it — and stays put
    # when the entry is not richer (works unchanged ⟹ label unchanged).
    opps = [
        {"pi_name": "A", "school": "uw", "url": "https://x.edu/a",
         "source_type": "faculty_research",
         "metadata": {"recent_works": [{"title": "old", "year": 2020}],
                      "publication_attribution_status": oa.ATTRIBUTION_NAME_MATCH}},
        {"pi_name": "B", "school": "uw", "url": "https://x.edu/b",
         "source_type": "faculty_research",
         "metadata": {"recent_works": [{"title": "b1", "year": 2026},
                                       {"title": "b2", "year": 2025}],
                      "publication_attribution_status": oa.ATTRIBUTION_VERIFIED}},
    ]
    mapping = {
        "https://x.edu/a": {"author_id": "A9",
                            "works": [{"title": "n1", "year": 2026},
                                      {"title": "n2", "year": 2025}]},
        "https://x.edu/b": [{"title": "not richer", "year": 2026}],
    }
    assert oa.apply_works(opps, mapping) == 1
    assert opps[0]["metadata"]["publication_attribution_status"] == oa.ATTRIBUTION_VERIFIED
    assert opps[1]["metadata"]["publication_attribution_status"] == oa.ATTRIBUTION_VERIFIED
    assert opps[1]["metadata"]["recent_works"][0]["title"] == "b1"


def test_harvest_works_shared_url_keys_per_person(monkeypatch):
    # 430 JHU Krieger faculty share one directory URL; a url-keyed mapping let
    # the last-harvested person's papers overwrite everyone else's slot and
    # apply_works then stamped one person's works onto the whole department.
    opps = [
        {"pi_name": "Erik Andersen", "school": "uw", "url": "https://x.edu/dir",
         "source_type": "faculty_research"},
        {"pi_name": "Gira Bhabha", "school": "uw", "url": "https://x.edu/dir",
         "source_type": "faculty_research"},
    ]
    monkeypatch.setattr(oa, "_match_author", lambda name, *a, **k: {"id": name.split()[0]})
    monkeypatch.setattr(oa, "author_recent_works",
                        lambda aid, dept="", **kw: [{"title": f"{aid} paper", "year": 2026}])
    mapping = oa.harvest_works(opps, throttle=0)
    assert mapping == {
        "https://x.edu/dir#erik andersen": {
            "author_id": "Erik", "works": [{"title": "Erik paper", "year": 2026}]},
        "https://x.edu/dir#gira bhabha": {
            "author_id": "Gira", "works": [{"title": "Gira paper", "year": 2026}]},
    }


def test_apply_works_bare_url_never_applies_to_shared_url():
    opps = [
        {"pi_name": "A One", "school": "uw", "url": "https://x.edu/dir",
         "source_type": "faculty_research"},
        {"pi_name": "B Two", "school": "uw", "url": "https://x.edu/dir",
         "source_type": "faculty_research"},
        {"pi_name": "C Solo", "school": "uw", "url": "https://x.edu/c",
         "source_type": "faculty_research"},
    ]
    mapping = {
        "https://x.edu/dir": [{"title": "someone's paper", "year": 2026}],  # legacy bare key
        "https://x.edu/c": [{"title": "c paper", "year": 2026}],
        "https://x.edu/dir#a one": [{"title": "a's own paper", "year": 2026}],
    }
    n = oa.apply_works(opps, mapping)
    assert n == 2
    assert opps[0]["metadata"]["recent_works"][0]["title"] == "a's own paper"
    assert "metadata" not in opps[1] or not (opps[1].get("metadata") or {}).get("recent_works")
    assert opps[2]["metadata"]["recent_works"][0]["title"] == "c paper"


def test_apply_openalex_bare_url_never_applies_to_shared_url():
    opps = [
        {"pi_name": "A One", "school": "uw", "url": "https://x.edu/dir",
         "source_type": "faculty_research"},
        {"pi_name": "B Two", "school": "uw", "url": "https://x.edu/dir",
         "source_type": "faculty_research"},
        {"pi_name": "C Solo", "school": "uw", "url": "https://x.edu/c",
         "source_type": "faculty_research"},
    ]
    mapping = {
        "https://x.edu/dir": ["someone's topics"],
        "https://x.edu/c": ["c topics"],
        "https://x.edu/dir#b two": ["b's own topics"],
    }
    n = oa.apply_openalex(opps, mapping)
    assert n == 2
    assert not opps[0].get("keywords")
    assert opps[1]["keywords"] == ["b's own topics"]
    assert opps[2]["keywords"] == ["c topics"]


def test_apply_works_dedups_punctuation_variant_titles():
    # The committed store predates _title_key: journals republish preprints with
    # hyphen/case drift ("Older-Onset" vs "older onset") and both got stored.
    opps = [{"pi_name": "A", "school": "uw", "url": "https://x.edu/a",
             "source_type": "faculty_research"}]
    mapping = {"https://x.edu/a": [
        {"title": "CGM in Older-Onset Diabetes", "year": 2026},
        {"title": "CGM in older onset diabetes", "year": 2026},
        {"title": "A Different Paper", "year": 2025},
    ]}
    oa.apply_works(opps, mapping)
    titles = [w["title"] for w in opps[0]["metadata"]["recent_works"]]
    assert titles == ["CGM in Older-Onset Diabetes", "A Different Paper"]


# ---------------------------------------------------------------------------
# Papers we already paid for, that no email can cite
#
# 15,917 faculty records in the corpus hold 47,024 harvested publications and
# exactly zero of them pass ``works_are_verified``: they were harvested before
# the attribution stamp existed. Two selection rules then made that state
# permanent, and each one is sufficient on its own —
#
#   _works_targets skipped any record that HAD works, so the re-harvest that
#   would resolve an author id never selected them;
#   apply_works required strictly more papers, and 15,327 of the 15,917 already
#   hold _MAX_WORKS, so even a completed re-harvest would have written nothing.
#
# Together: the papers are in the corpus, invisible to every serving path, and
# unreachable by the only pass that could make them visible.
# ---------------------------------------------------------------------------


def _faculty(url, name, works=None, status=None, gate=None):
    o = {"pi_name": name, "school": "uw", "url": url,
         "source_type": "faculty_research"}
    if works is not None:
        md = {"recent_works": works}
        if status:
            md["publication_attribution_status"] = status
        if gate is not None:
            md["works_gate"] = gate
        o["metadata"] = md
    return o


def test_unverified_works_do_not_make_a_record_done():
    # The record LOOKS harvested and is worth nothing to a cold email. It is a
    # target until its papers are attributable to the person we would name AND
    # were chosen by the gate we currently trust.
    unstamped = _faculty("https://x.edu/a", "A Prof",
                         [{"title": "old", "year": 2020}])
    name_matched = _faculty("https://x.edu/b", "B Prof",
                            [{"title": "old", "year": 2020}],
                            oa.ATTRIBUTION_NAME_MATCH)
    old_gate = _faculty("https://x.edu/c", "C Prof",
                        [{"title": "old", "year": 2020}],
                        oa.ATTRIBUTION_VERIFIED)
    current = _faculty("https://x.edu/d", "D Prof",
                       [{"title": "old", "year": 2020}],
                       oa.ATTRIBUTION_VERIFIED, gate=oa._WORKS_GATE)
    targets = oa._works_targets([unstamped, name_matched, old_gate, current], None)
    # C is verified, but by the department-family gate #846 replaced: it is
    # holding whatever that family let through, which is why it is here.
    assert [t["pi_name"] for t in targets] == ["A Prof", "B Prof", "C Prof"]


def test_a_stricter_gate_may_return_fewer_papers_and_still_win():
    # 3 -> 1 is a correction, not a regression: the papers the newer gate drops
    # are the ones it exists to drop. Without this the records most in need of
    # fixing are exactly the ones that keep their old citations.
    three = [{"title": "P1", "year": 2026}, {"title": "P2", "year": 2025},
             {"title": "P3", "year": 2024}]
    stale = _faculty("https://x.edu/a", "A Prof", list(three),
                     oa.ATTRIBUTION_VERIFIED)
    assert oa.apply_works([stale], {"https://x.edu/a": {
        "author_id": "A1", "works": [{"title": "Only Real One", "year": 2026}]}}) == 1
    md = stale["metadata"]
    assert [w["title"] for w in md["recent_works"]] == ["Only Real One"]
    assert md["works_gate"] == oa._WORKS_GATE

    # ...and once it carries the current gate, a shorter list is a regression
    # again and must be refused.
    assert oa.apply_works([stale], {"https://x.edu/a": {
        "author_id": "A1", "works": []}}) == 0
    fresh = _faculty("https://x.edu/b", "B Prof",
                     [{"title": "Keep", "year": 2026}, {"title": "These", "year": 2025}],
                     oa.ATTRIBUTION_VERIFIED, gate=oa._WORKS_GATE)
    assert oa.apply_works([fresh], {"https://x.edu/b": {
        "author_id": "A2", "works": [{"title": "Just One", "year": 2026}]}}) == 0
    assert len(fresh["metadata"]["recent_works"]) == 2


def test_the_same_three_papers_are_an_upgrade_once_they_carry_an_author_id():
    # The decisive case: _MAX_WORKS is 3 and 15,327 records already hold 3, so
    # a `len(clean) > len(existing)` rule rejects every completed re-harvest of
    # the exact population the re-harvest exists for.
    same = [{"title": "P1", "year": 2026}, {"title": "P2", "year": 2025},
            {"title": "P3", "year": 2024}]
    opp = _faculty("https://x.edu/a", "A Prof", list(same))
    assert oa.apply_works([opp], {"https://x.edu/a": {"author_id": "A1",
                                                      "works": list(same)}}) == 1
    assert opp["metadata"]["publication_attribution_status"] == oa.ATTRIBUTION_VERIFIED


def test_one_citable_paper_beats_three_uncitable_ones():
    # Fewer papers, but the three it replaces were unusable by every serving
    # path — so the record goes from zero citable papers to one.
    opp = _faculty("https://x.edu/a", "A Prof",
                   [{"title": "P1", "year": 2026}, {"title": "P2", "year": 2025},
                    {"title": "P3", "year": 2024}])
    mapping = {"https://x.edu/a": {"author_id": "A1",
                                   "works": [{"title": "Real", "year": 2026}]}}
    assert oa.apply_works([opp], mapping) == 1
    assert [w["title"] for w in opp["metadata"]["recent_works"]] == ["Real"]
    assert opp["metadata"]["publication_attribution_status"] == oa.ATTRIBUTION_VERIFIED


def test_a_verified_record_is_never_traded_back_for_more_unverified_papers():
    # The rule reads in one direction only. Three name-matched titles must not
    # displace one paper we can actually attribute.
    opp = _faculty("https://x.edu/a", "A Prof", [{"title": "Real", "year": 2026}],
                   oa.ATTRIBUTION_VERIFIED)
    mapping = {"https://x.edu/a": [{"title": "P1", "year": 2026},
                                   {"title": "P2", "year": 2025},
                                   {"title": "P3", "year": 2024}]}
    assert oa.apply_works([opp], mapping) == 0
    assert [w["title"] for w in opp["metadata"]["recent_works"]] == ["Real"]


def test_a_reharvest_actually_reaches_a_stamped_state(monkeypatch):
    # End to end over both gates, because fixing either one alone leaves the
    # count at zero: target selection -> harvest -> apply -> citable.
    opp = _faculty("https://x.edu/a", "A Prof",
                   [{"title": "P1", "year": 2026}, {"title": "P2", "year": 2025},
                    {"title": "P3", "year": 2024}])
    monkeypatch.setattr(oa, "_match_author", lambda name, inst, dept="": {"id": "A1"})
    monkeypatch.setattr(oa, "author_recent_works",
                        lambda aid, dept="", **kw: [{"title": "P1", "year": 2026},
                                              {"title": "P2", "year": 2025},
                                              {"title": "P3", "year": 2024}])
    assert works_are_verified(opp) is False
    mapping = oa.harvest_works([opp], throttle=0)
    assert oa.apply_works([opp], mapping) == 1
    assert works_are_verified(opp) is True
    assert len(verified_recent_works(opp)) == 3


# --- roster harvest (institution-paged, 1 credit per 100 authors) ------------

def _roster_row(name, works=40, topics=(), fields=()):
    return {"id": f"A{abs(hash(name)) % 10**8}", "name": name, "works": works,
            "topics": list(topics), "fields": list(fields)}


def test_roster_refuses_two_same_named_colleagues():
    """The Grinnell bug's real fix. Without affiliation years there is no honest
    way to rank two same-named authors at one school, and 'most works wins' is
    what handed a digital-humanities scholar a chemist's research areas.

    Both rows carry fields, because every real roster row does: across the
    miami, syracuse and utk rosters, 16 of 22,609 authors have no field, and
    each of those has no topic to give a professor either.
    """
    idx = oa.index_roster([
        _roster_row("Elizabeth Rodrigues", works=12, topics=["digital humanities"],
                    fields=["Arts and Humanities"]),
        _roster_row("Elizabeth Rodrigues", works=300, topics=["polymer chemistry"],
                    fields=["Chemistry"]),
    ])
    # "Digital Studies" now maps to a field family, so the chemist is refused
    # on the evidence and the ambiguity dissolves — a better answer than
    # refusing both, and the outcome this collision should have had all along.
    author, why = oa._match_in_roster("Elizabeth Rodrigues", "Digital Studies", idx)
    assert why == "ok"
    assert author["topics"] == ["digital humanities"]

    # Two colleagues the fields cannot separate: the refusal rule still holds.
    idx = oa.index_roster([
        _roster_row("Elizabeth Rodrigues", works=12, topics=["digital humanities"],
                    fields=["Arts and Humanities"]),
        _roster_row("Elizabeth Rodrigues", works=300, topics=["book history"],
                    fields=["Arts and Humanities"]),
    ])
    author, why = oa._match_in_roster("Elizabeth Rodrigues", "Digital Studies", idx)
    assert author is None
    assert why == "ambiguous"


def test_roster_full_given_name_breaks_an_initial_collision():
    """Two authors share the surname and first initial; only one shares the
    whole given name, so the ambiguity is real only for the other."""
    idx = oa.index_roster([
        _roster_row("Robert Chen", topics=["robotics"]),
        _roster_row("Rachel Chen", topics=["immunology"]),
    ])
    author, why = oa._match_in_roster("Robert Chen", "", idx)
    assert why == "ok"
    assert author["name"] == "Robert Chen"


def test_roster_applies_the_department_field_gate():
    idx = oa.index_roster([
        _roster_row("Jane Seismic", topics=["seismic waves"],
                fields=["Earth and Planetary Sciences"] * 4),
    ])
    _, why = oa._match_in_roster("Jane Seismic", "Electrical Engineering", idx)
    assert why == "field_reject"


def test_roster_holds_the_min_works_floor():
    idx = oa.index_roster([_roster_row("Ann Novice", works=oa._MIN_WORKS - 1,
                                   topics=["genomics"])])
    _, why = oa._match_in_roster("Ann Novice", "", idx)
    assert why == "absent"


def test_roster_matching_folds_accents():
    idx = oa.index_roster([_roster_row("Jose Angel Nunez", topics=["optics"])])
    author, why = oa._match_in_roster("José Ángel Núñez", "", idx)
    assert why == "ok" and author is not None


def test_fetch_roster_pages_with_filters_and_never_a_search(monkeypatch):
    """The whole economics of this path: a pure filter page is 1 credit, a name
    search is 10. A 'search' key creeping into these params costs 10x silently."""
    seen = []

    def fake_get(params, url=oa._API, timeout=20):
        seen.append(params)
        if len(seen) == 1:
            return {"results": [{"display_name": "A", "works_count": 9, "topics": []}],
                    "meta": {"next_cursor": "c2"}}
        return {"results": [{"display_name": "B", "works_count": 9, "topics": []}],
                "meta": {"next_cursor": None}}

    monkeypatch.setattr(oa, "_get", fake_get)
    out = oa.fetch_roster("I1")
    assert [a["name"] for a in out["authors"]] == ["A", "B"]
    assert out["complete"] is True
    assert all("search" not in p for p in seen)
    assert all("search" not in str(p.get("filter", "")) for p in seen)
    assert [p.get("cursor") for p in seen] == ["*", "c2"]


def test_fetch_roster_keeps_what_it_read_when_the_budget_dies(monkeypatch):
    """_get returns {} on a confirmed 429. The page already paid for must not be
    thrown away — tomorrow's run resumes from the cache, not from zero."""
    calls = []

    def fake_get(params, url=oa._API, timeout=20):
        calls.append(params)
        if len(calls) == 1:
            return {"results": [{"display_name": "A", "works_count": 9, "topics": []}],
                    "meta": {"next_cursor": "c2"}}
        return {}

    monkeypatch.setattr(oa, "_get", fake_get)
    out = oa.fetch_roster("I1")
    assert [a["name"] for a in out["authors"]] == ["A"]
    assert out["complete"] is False, "a page that never arrived is not a finished roster"
    assert out["cursor"] == "c2", "the cursor must survive so tomorrow resumes here"


def test_roster_harvest_keys_what_apply_openalex_reads(monkeypatch, tmp_path):
    """Wiring: the roster harvest must emit the SAME url#name keys the existing
    apply step consumes, or it produces a mapping nothing can spend."""
    monkeypatch.setattr(oa, "SCHOOL_INST", {"jhu": "I145311948"})
    monkeypatch.setattr(oa, "fetch_roster", lambda inst, **kw: {
        "authors": [_roster_row("Erik Andersen", topics=["Genetics of aging"],
                                fields=["Biochemistry, Genetics and Molecular Biology"] * 4)],
        "cursor": None, "expected": 1, "complete": True,
    })
    opps = [{
        "source_type": "faculty_research", "school": "jhu",
        "pi_name": "Erik Andersen", "department": "Department of Biology",
        "url": "https://krieger.jhu.edu/bio/andersen", "keywords": [],
    }]
    mapping, reasons = oa.harvest_openalex_roster(
        opps, schools=["jhu"], roster_dir=str(tmp_path))
    assert reasons.get("ok") == 1
    assert oa.apply_openalex(opps, mapping) == 1
    assert opps[0]["keywords"] == ["genetics of aging"]


def test_roster_harvest_reuses_the_cached_roster(monkeypatch, tmp_path):
    """A re-run after the daily budget resets must not re-buy the roster."""
    monkeypatch.setattr(oa, "SCHOOL_INST", {"jhu": "I1"})
    fetches = []

    def counted(inst, **kw):
        fetches.append(inst)
        return {"authors": [_roster_row(
            "Erik Andersen", topics=["Genetics of aging"],
            fields=["Biochemistry, Genetics and Molecular Biology"] * 4)],
            "cursor": None, "expected": 1, "complete": True}

    monkeypatch.setattr(oa, "fetch_roster", counted)
    opps = [{"source_type": "faculty_research", "school": "jhu",
             "pi_name": "Erik Andersen", "department": "Department of Biology",
             "url": "https://x/andersen", "keywords": []}]
    oa.harvest_openalex_roster(opps, schools=["jhu"], roster_dir=str(tmp_path))
    oa.harvest_openalex_roster(opps, schools=["jhu"], roster_dir=str(tmp_path))
    assert len(fetches) == 1


def test_fetch_roster_stops_on_an_empty_page_even_with_a_cursor(monkeypatch):
    """An empty page ends the roster. Treating only a missing `results` key as
    the end (rather than an empty one) keeps paging a school that has no more
    authors — spending a credit per page against a cursor the API will keep
    handing back."""
    pages = [
        {"results": [{"display_name": "A", "works_count": 9, "topics": []}],
         "meta": {"next_cursor": "c2"}},
        {"results": [], "meta": {"next_cursor": "c3"}},
        {"results": [{"display_name": "B", "works_count": 9, "topics": []}],
         "meta": {"next_cursor": None}},
    ]
    calls = []

    def fake_get(params, url=oa._API, timeout=20):
        calls.append(params)
        return pages[len(calls) - 1]

    monkeypatch.setattr(oa, "_get", fake_get)
    out = oa.fetch_roster("I1")
    assert [a["name"] for a in out["authors"]] == ["A"]
    assert len(calls) == 2


def test_a_truncated_roster_is_never_reported_complete(monkeypatch):
    """The defect this rule exists for: a timed-out page and a finished roster
    both reach the loop as an empty dict. Reading that as "done" cached 300 of
    Cincinnati's 6,925 authors and then scored the school 4% matched — misses
    that look exactly like real ones."""
    calls = []

    def fake_get(params, url=oa._API, timeout=20):
        calls.append(params)
        if len(calls) == 1:
            return {"results": [{"display_name": "A", "works_count": 9, "topics": []}],
                    "meta": {"next_cursor": "c2", "count": 6925}}
        return {}

    monkeypatch.setattr(oa, "_get", fake_get)
    out = oa.fetch_roster("I1")
    assert out["expected"] == 6925
    assert len(out["authors"]) == 1
    assert out["complete"] is False


def test_an_incomplete_roster_never_matches_a_school(monkeypatch, tmp_path):
    """A partial roster must not be spent: every faculty it cannot see becomes a
    silent miss. Skip the school and keep the cursor for tomorrow."""
    monkeypatch.setattr(oa, "SCHOOL_INST", {"cincinnati": "I1"})
    monkeypatch.setattr(oa, "fetch_roster", lambda inst, **kw: {
        "authors": [_roster_row("Jane Doe", topics=["x"])],
        "cursor": "c9", "expected": 6925, "complete": False,
    })
    opps = [{"source_type": "faculty_research", "school": "cincinnati",
             "pi_name": "Jane Doe", "department": "", "url": "https://x/1",
             "keywords": []}]
    mapping, reasons = oa.harvest_openalex_roster(
        opps, schools=["cincinnati"], roster_dir=str(tmp_path))
    assert mapping == {}
    assert reasons.get("roster_incomplete") == 1
    assert json.load(open(tmp_path / "cincinnati.json"))["cursor"] == "c9"


def test_an_incomplete_roster_resumes_from_its_cursor(monkeypatch, tmp_path):
    monkeypatch.setattr(oa, "SCHOOL_INST", {"cincinnati": "I1"})
    (tmp_path / "cincinnati.json").write_text(json.dumps(
        {"authors": [], "cursor": "c9", "expected": 10, "complete": False}))
    seen = {}

    def resume(inst, **kw):
        seen.update(kw)
        return {"authors": [], "cursor": None, "expected": 0, "complete": True}

    monkeypatch.setattr(oa, "fetch_roster", resume)
    opps = [{"source_type": "faculty_research", "school": "cincinnati",
             "pi_name": "Jane Doe", "department": "", "url": "https://x/1",
             "keywords": []}]
    oa.harvest_openalex_roster(opps, schools=["cincinnati"], roster_dir=str(tmp_path))
    assert seen.get("cursor") == "c9"


def test_usable_topics_are_distinct_after_cleaning():
    """_clean_topic collapses two OpenAlex labels onto one string; a record that
    carries it twice fails the corpus duplicate-keyword gate (it did, on 2 of
    2,676 JHU records) and doubles the word up in the faculty title."""
    out = oa.usable_topics([
        "Advanced Battery Technologies",
        "Advanced battery technologies: research",
        "Solid-state spectroscopy",
    ])
    assert out == sorted(set(out), key=out.index)
    assert len(out) == len({t.lower() for t in out})


def test_usable_topics_looks_past_a_duplicate_to_fill_the_quota():
    """Slicing to max_topics BEFORE cleaning costs the professor a real area
    every time a duplicate lands inside the slice."""
    out = oa.usable_topics(["A research", "A", "B", "C"], max_topics=3)
    assert out == ["a", "b", "c"]


def test_usable_topics_drops_a_topic_too_long_to_be_a_keyword():
    long = " ".join(["word"] * 9)
    assert long not in oa.usable_topics([long, "optics"])


# --- works bought by the page, so the papers can be cited ------------------

def _authored_work(title, year, field, author_ids):
    return {"display_name": title, "publication_year": year,
            "primary_topic": {"field": {"display_name": field}},
            "authorships": [{"author": {"id": f"https://openalex.org/{a}"}}
                            for a in author_ids]}


def test_one_request_buys_a_whole_batch_of_authors(monkeypatch):
    """A /works request costs a credit per REQUEST, not per author, and its
    author.id filter takes an OR list. That is what makes a corpus-wide pass
    affordable: the per-person path costs about 12 credits a professor."""
    calls = []

    def fake_get(params, url=None, timeout=20):
        calls.append(params)
        return {"results": [_authored_work("Shared Paper", 2026, "Engineering", ["A1", "A2"]),
                            _authored_work("Only A2", 2025, "Engineering", ["A2"])],
                "meta": {"next_cursor": None}}

    monkeypatch.setattr(oa, "_get", fake_get)
    got = oa.works_for_authors(["A1", "https://openalex.org/A2"])
    assert len(calls) == 1, "one request must serve the whole batch"
    assert calls[0]["filter"] == "author.id:A1|A2"
    assert calls[0]["per-page"] == oa._WORKS_PAGE_SIZE
    # A work is credited to every author of it that we asked about, and to no
    # one we did not.
    assert [w["display_name"] for w in got["A1"]] == ["Shared Paper"]
    assert [w["display_name"] for w in got["A2"]] == ["Shared Paper", "Only A2"]
    assert oa.works_for_authors([]) == {}


def test_the_papers_a_roster_match_buys_are_citable(monkeypatch, tmp_path):
    """The point of the pass. 15,903 faculty hold real paper titles that no
    serving path may cite, because the committed store keeps only a name-keyed
    association and `verified_recent_works` fails closed. Going back through
    the roster gives the author id those papers were always missing."""
    from src.publication_trust import verified_recent_works

    opp = {"id": "f1", "school": "jhu", "source_type": "faculty_research",
           "pi_name": "Rika Anderson", "url": "https://x.edu/rika",
           "source_url": "https://x.edu/rika", "department": "Department of Biology",
           "metadata": {"recent_works": [{"title": "Old Untraceable Paper", "year": 2019}]}}
    assert verified_recent_works(opp) == []          # what production holds today

    (tmp_path / "jhu.json").write_text(json.dumps({
        "complete": True, "expected": 1,
        "authors": [{"id": "https://openalex.org/A9", "name": "Rika Anderson",
                     "works": 40, "topics": ["hydrothermal vents"],
                     "fields": ["Agricultural and Biological Sciences"]}]}))
    monkeypatch.setattr(oa, "works_for_authors", lambda ids, **kw: {
        "A9": [_authored_work("Microbial Life at Hydrothermal Vents", 2026,
                     "Agricultural and Biological Sciences", ["A9"]),
               _authored_work("Monetary Policy in the Euro Area", 2026,
                              "Economics, Econometrics and Finance", ["A9"])],
    })

    mapping, reasons = oa.harvest_works_by_roster(
        [opp], schools=["jhu"], roster_dir=str(tmp_path))

    key = oa._person_key(opp)
    assert mapping[key]["author_id"] == "A9", "the id is what makes them citable"
    # The per-work field gate still runs. An economics paper is not this
    # biologist's, however recent — while Medicine would have been kept, since
    # a biology department genuinely publishes there.
    assert "Medicine" in oa._dept_fields("Department of Biology")
    assert [w["title"] for w in mapping[key]["works"]] == [
        "Microbial Life at Hydrothermal Vents"]

    assert oa.apply_works([opp], mapping) == 1
    assert [w["title"] for w in verified_recent_works(opp)] == [
        "Microbial Life at Hydrothermal Vents"]


def test_an_incomplete_roster_is_skipped_not_guessed_at(monkeypatch, tmp_path):
    """A miss against a partial roster is indistinguishable from a real one,
    so the school waits for tomorrow's cursor rather than reporting absences
    it cannot stand behind."""
    opp = {"id": "f1", "school": "jhu", "source_type": "faculty_research",
           "pi_name": "Rika Anderson", "url": "https://x.edu/rika",
           "source_url": "https://x.edu/rika", "department": "Department of Biology"}
    (tmp_path / "jhu.json").write_text(json.dumps(
        {"complete": False, "authors": [], "expected": 900}))
    called = []
    monkeypatch.setattr(oa, "_warned_429", False)
    monkeypatch.setattr(oa, "works_for_authors",
                        lambda ids, **kw: called.append(ids) or {})
    # The partial roster is resumed first — that is what this pass can now do —
    # and this run does not finish it either.
    resumed = []
    monkeypatch.setattr(oa, "fetch_roster", lambda inst, **kw: resumed.append(inst) or {
        "complete": False, "authors": [], "expected": 900, "cursor": "next"})

    mapping, reasons = oa.harvest_works_by_roster([opp], schools=["jhu"],
                                                  roster_dir=str(tmp_path))
    assert resumed, "an incomplete roster is resumed, not just skipped"
    assert mapping == {}
    assert reasons["roster_incomplete"] == 1
    assert called == [], "no credit is spent against a partial roster"


def test_the_works_pass_buys_a_roster_it_does_not_have(monkeypatch, tmp_path):
    # The two passes select different people: _targets wants faculty with no
    # research keywords, _works_targets wants faculty with no citable papers.
    # Berkeley has 0 of the first and 2,168 of the second, so the only command
    # that bought rosters could never be asked for Berkeley's — and the pass
    # that needed it read the cache and skipped. Measured on the corpus; the
    # same holds for utexas, uw, ucla and five more.
    opp = {"id": "f1", "school": "jhu", "source_type": "faculty_research",
           "pi_name": "Rika Anderson", "url": "https://x.edu/rika",
           "source_url": "https://x.edu/rika", "department": "Department of Biology"}
    monkeypatch.setattr(oa, "_warned_429", False)
    monkeypatch.setattr(oa, "fetch_roster", lambda inst, **kw: {
        "complete": True, "expected": 1,
        "authors": [{"id": "https://openalex.org/A1", "name": "Rika Anderson",
                     "works": 40, "topics": ["ecology"],
                     "fields": ["Agricultural and Biological Sciences"]}]})
    monkeypatch.setattr(oa, "works_for_authors", lambda ids, **kw: {
        ids[0]: [_authored_work("A Real Paper", 2026,
                                "Agricultural and Biological Sciences", [ids[0]])]})

    mapping, reasons = oa.harvest_works_by_roster([opp], schools=["jhu"],
                                                  roster_dir=str(tmp_path))
    assert reasons.get("no_roster") is None
    assert [w["title"] for w in mapping["https://x.edu/rika#rika anderson"]["works"]] \
        == ["A Real Paper"]
    assert (tmp_path / "jhu.json").exists(), "and it is cached for the next pass"


def test_a_prolific_author_does_not_crowd_out_the_batch(monkeypatch):
    """Asking OpenAlex for three real UCSC authors in one newest-first request
    returned 201 works for the first, 1 for the second and 0 for the third.
    An OR filter sorted by date belongs to whoever publishes most, and paging
    deeper buys more of the same author — so each round drops the authors it
    has already served and re-asks for the rest.
    """
    rounds = []

    def fake_get(params, url=None, timeout=20):
        rounds.append(params["filter"])
        if len(rounds) == 1:                    # a full page, all one author
            return {"results": [_authored_work(f"Prolific {i}", 2026, "Engineering", ["A1"])
                                for i in range(oa._WORKS_PAGE_SIZE)]}
        return {"results": [_authored_work("The Quiet One's Paper", 2025,
                                           "Engineering", ["A2"])]}

    monkeypatch.setattr(oa, "_get", fake_get)
    got = oa.works_for_authors(["A1", "A2"])

    assert rounds == ["author.id:A1|A2", "author.id:A2"], \
        "the served author must be dropped from the second ask"
    assert len(got["A1"]) == oa._WORKS_PAGE_SIZE
    assert [w["display_name"] for w in got["A2"]] == ["The Quiet One's Paper"]


def test_a_round_that_serves_nobody_is_not_bought_twice(monkeypatch):
    """If a full page leaves every author still short, re-asking would return
    the same page for the same credit."""
    calls = []

    def fake_get(params, url=None, timeout=20):
        calls.append(params["filter"])
        # A full page, but spread so thinly that nobody reaches the slack mark.
        return {"results": [_authored_work(f"P{i}", 2026, "Engineering", [f"A{i % 40}"])
                            for i in range(oa._WORKS_PAGE_SIZE)]}

    monkeypatch.setattr(oa, "_get", fake_get)
    oa.works_for_authors([f"A{i}" for i in range(40)])
    assert len(calls) <= 2, calls


def test_an_exhausted_budget_is_not_a_professor_without_papers(monkeypatch, tmp_path):
    """An empty answer from a dead budget is not the claim "this professor has
    no citable paper". Writing the second one would be a lie the next run acts
    on: `_works_targets` skips whoever already looks done, so a false miss is
    how a professor gets locked out of the only pass that can ever cite them —
    the same way 15,917 records were locked out before #804.
    """
    # Alphabetic and distinct: _match_name_key strips digits, so "Person1
    # Smith1" and "Person2 Smith2" are one key and every person would collide.
    def _nym(i):
        a, b, c = "abcdefghijklmnopqrstuvwxyz"[i // 26], "abcdefghijklmnopqrstuvwxyz"[i % 26], "x"
        return f"{a.upper()}nna{b} {c.upper()}yle{a}{b}"

    people = []
    for i in range(60):
        people.append({"id": f"f{i}", "school": "jhu", "source_type": "faculty_research",
                       "pi_name": _nym(i), "url": f"https://x.edu/{i}",
                       "source_url": f"https://x.edu/{i}", "department": "Physics"})
    (tmp_path / "jhu.json").write_text(json.dumps({
        "complete": True, "expected": len(people),
        "authors": [{"id": f"https://openalex.org/A{i}", "name": p["pi_name"],
                     "works": 40, "topics": ["optics"],
                     "fields": ["Physics and Astronomy"]}
                    for i, p in enumerate(people)]}))

    calls = {"n": 0}
    monkeypatch.setattr(oa, "_warned_429", False)

    def dying(ids, **kw):
        calls["n"] += 1
        if calls["n"] == 1:                       # first batch answers normally
            return {ids[0]: [_authored_work("A Real Paper", 2026,
                                            "Physics and Astronomy", [ids[0]])]}
        monkeypatch.setattr(oa, "_warned_429", True)   # budget dies mid-run
        return {}

    monkeypatch.setattr(oa, "works_for_authors", dying)
    mapping, reasons = oa.harvest_works_by_roster(
        people, schools=["jhu"], roster_dir=str(tmp_path))

    with_papers = [k for k, v in mapping.items() if v["works"]]
    assert len(with_papers) == 1, "the one real answer is kept"
    # The rest of that first batch were asked and have nothing citable, which is
    # an answer and is written down as one. Nobody after the 429 is recorded at
    # all — an exhausted budget must never read as "this professor has no
    # papers", because that answer would clear their record.
    assert len(mapping) == oa._WORKS_BATCH, "the answered batch, and only it"
    assert reasons.get("no_usable_work", 0) == oa._WORKS_BATCH - 1, reasons
    assert all(v["works"] == [] for k, v in mapping.items() if k not in with_papers)


def _crowd(surname, n):
    """n other people sharing a surname, so it stops being identifying."""
    return [_roster_row(f"Person{i} {surname}", fields=["Computer Science"])
            for i in range(n)]


def test_a_crowded_surname_must_publish_in_the_department_s_own_field():
    # Production 2026-08-30: UIUC's Arindam Banerjee is a machine-learning
    # professor, and the only "Arindam Banerjee" on UIUC's OpenAlex roster is a
    # peptide chemist (320 works). A School of Computing maps to a field family
    # holding Chemistry, Materials Science and Physics, so the chemist is
    # majority-compatible and wins by being the only candidate. Utah's Travis
    # Martin got "T. P. Martin", 302 works of physics, the same way.
    chemist = _roster_row("Arindam Banerjee", works=320,
                          fields=["Chemistry", "Materials Science", "Engineering"])
    idx = oa.index_roster([chemist, *_crowd("Banerjee", 3)])
    author, why = oa._match_in_roster(
        "Arindam Banerjee", "Siebel School of Computing and Data Science", idx)
    assert author is None
    assert why == "discipline_reject"


def test_a_rare_surname_is_not_asked():
    # The question is only worth asking where surname + first initial has
    # stopped identifying anybody. Deepak Vasisht's OpenAlex profile is labelled
    # Engineering with no Computer Science topic at all — normal for a wireless
    # networking researcher — and his surname is unique on UIUC's roster, so the
    # match must stand. Rejecting him is the cost this condition exists to avoid.
    idx = oa.index_roster([_roster_row("Deepak Vasisht", works=83, fields=["Engineering"])])
    author, why = oa._match_in_roster(
        "Deepak Vasisht", "Siebel School of Computing and Data Science", idx)
    assert why == "ok"
    assert author["name"] == "Deepak Vasisht"


def test_electrical_and_computer_engineering_is_not_a_computing_department():
    # "Electrical & Computer Engineering" contains the word "computer", and its
    # faculty legitimately publish with no Computer Science topic at all —
    # circuits, devices and signal processing are filed as Engineering or
    # Physics and Astronomy. Asking them the computing question would reject a
    # whole discipline, so "electric" answers first.
    idx = oa.index_roster([
        _roster_row("Ada Devicewright", works=364,
                    fields=["Engineering", "Physics and Astronomy", "Engineering"]),
        *_crowd("Devicewright", 4),
    ])
    author, why = oa._match_in_roster(
        "Ada Devicewright", "Electrical & Computer Engineering", idx)
    assert why == "ok"
    assert author["works"] == 364


def test_a_crowded_surname_with_the_field_present_still_matches():
    idx = oa.index_roster([
        _roster_row("Gang Wang", works=200,
                    fields=["Computer Science", "Engineering"]),
        *_crowd("Wang", 5),
    ])
    author, why = oa._match_in_roster(
        "Gang Wang", "Siebel School of Computing and Data Science", idx)
    assert why == "ok"
    assert author["works"] == 200


def test_the_discipline_check_may_not_promote_a_weaker_name_match():
    # UIUC's roster holds the peptide chemist who carries Arindam Banerjee's
    # exact name (no Computer Science topic) and an initials-only "A Banerjee"
    # whose profile does list one. Asking the discipline question BEFORE
    # spending the name evidence dropped the chemist and handed the professor
    # the initials record instead — one wrong person swapped for another, and
    # the record then looks matched rather than refused.
    chemist = _roster_row("Arindam Banerjee", works=320,
                          fields=["Chemistry", "Materials Science", "Engineering"])
    initials = _roster_row("A Banerjee", works=42,
                           fields=["Physics and Astronomy", "Computer Science",
                                   "Mathematics"])
    idx = oa.index_roster([chemist, initials, *_crowd("Banerjee", 3)])
    author, why = oa._match_in_roster(
        "Arindam Banerjee", "Siebel School of Computing and Data Science", idx)
    assert author is None
    assert why == "discipline_reject"


def test_the_discipline_check_still_separates_two_equal_name_matches():
    # The order change must not cost what filtering first was buying: where two
    # candidates match the name equally well, the one that has published in the
    # department's field is the match. Measured on the corpus, eleven records
    # resolve this way and all eleven look right.
    real = _roster_row("Changxi Zheng", works=180,
                       fields=["Computer Science", "Engineering"])
    other = _roster_row("Changxi Zheng", works=60,
                        fields=["Materials Science", "Chemistry", "Engineering"])
    idx = oa.index_roster([real, other, *_crowd("Zheng", 4)])
    author, why = oa._match_in_roster(
        "Changxi Zheng", "Department of Computer Science", idx)
    assert why == "ok"
    assert author["works"] == 180
