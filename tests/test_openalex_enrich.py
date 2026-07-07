"""Tests for the OpenAlex scholarly-record enrichment pass.

The network (`_get`) is monkeypatched; the value under test is the accuracy
gating — institution-id match, surname match, min-works, the majority
field-consistency gate (wrong-person rejection), topic cleaning, and updates-only
apply.
"""
from src.collectors import openalex_enrich as oa


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
    with caplog.at_level("WARNING", logger="src.collectors.openalex_enrich"):
        assert oa._get({"search": "x"}) == {}
        assert oa._get({"search": "y"}) == {}
    warnings = [r for r in caplog.records if "429" in r.getMessage()]
    assert len(warnings) == 1  # surfaced, but not once per author


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
         "metadata": {"recent_works": [{"title": "old", "year": 2020}]}},
        {"pi_name": "D Other", "school": "not-registered", "url": "https://y.edu/d",
         "source_type": "faculty_research"},
    ]

    def _fake_match(name, inst_id, dept=""):
        return {"id": "A1"} if "Match" in name and "No" not in name else None

    monkeypatch.setattr(oa, "_match_author", _fake_match)
    monkeypatch.setattr(oa, "author_recent_works",
                        lambda aid, dept="": [{"title": "Recent Paper", "year": 2026}])
    mapping = oa.harvest_works(opps, throttle=0)
    # keyworded faculty ARE works targets; already-enriched + unmapped schools are not
    assert mapping == {"https://x.edu/a": [{"title": "Recent Paper", "year": 2026}]}


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
    assert opps[1]["metadata"]["recent_works"] == [{"title": "keep me", "year": 2020}]
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
