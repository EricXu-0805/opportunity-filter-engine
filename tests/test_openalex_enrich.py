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
    assert mapping == {"https://x.edu/a#a match": [{"title": "Recent Paper", "year": 2026}]}


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
                        lambda aid, dept="": [{"title": f"{aid} paper", "year": 2026}])
    mapping = oa.harvest_works(opps, throttle=0)
    assert mapping == {
        "https://x.edu/dir#erik andersen": [{"title": "Erik paper", "year": 2026}],
        "https://x.edu/dir#gira bhabha": [{"title": "Gira paper", "year": 2026}],
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
