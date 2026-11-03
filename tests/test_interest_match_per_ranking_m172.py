"""M172: interest matching prepares the profile's terms once per ranking.

The chip overlap, the topic check, the interest bonus and the upside layer
derived the same values from the profile on every scored row, and decided
whether a chip matches a keyword again on every row that carries the keyword.
A ranking now prepares the profile once (_ProfileInterests), decides each
distinct keyword once, and makes a chip a pattern only when a keyword
contains it. These tests hold the new path to the rule as the ranking ran it
before, and count the work instead of timing it.

An interest line names at most eight of the chips it matched, the first in
alphabetical order; the score still counts every match.
"""
from __future__ import annotations

import random

import pytest

from src.evidence import stamp_inferred
from src.matcher import ranker as rk
from src.matcher.config import (
    INTEREST_BONUS_CAP,
    INTEREST_BONUS_PER_HIT,
    MATCHER_VERSION,
    TOPIC_MISMATCH_PENALTY,
    TOPIC_UNKNOWN_PENALTY,
)
from src.matcher.reason_keys import reason_key


def _overlap_before(desired, keywords, reverse_re):
    """The chip overlap as it ran before M172, row by row, with how each chip
    matched. ``reverse_re`` is _kw_word_re on the ranking path (the static
    path then) and _word_re on _desired_field_overlap's own."""
    if not desired or not keywords:
        return {}
    kws = [k.lower().strip() for k in keywords if k and k.strip()]
    kw_set = set(kws)
    kw_canon = {rk._canonicalize_skill(k) for k in kws}
    containment_res = [
        reverse_re(k) for k in kws
        if len(k) >= 4 and not (" " not in k and k in rk._LOW_SIGNAL_ALIGN_TOKENS)
    ]
    matched = {}
    for d in desired:
        dl = d.lower().strip()
        if not dl:
            continue
        dc = rk._canonicalize_skill(dl)
        if dl in kw_set or dc in kw_canon or dc in kw_set:
            matched[d] = "same term" if dl in kw_set else "same canonical form"
            continue
        if " " not in dl and dl in rk._LOW_SIGNAL_ALIGN_TOKENS:
            continue
        if len(dl) >= 4:
            dl_re = rk._word_re(dl)
            if any(dl_re.search(k) for k in kws):
                matched[d] = "chip in keyword"
                continue
        if any(p.search(dl) for p in containment_res):
            matched[d] = "keyword in chip"
    return matched


_LOW = sorted(rk._LOW_SIGNAL_ALIGN_TOKENS)
_SYNONYM_GROUPS = [sorted(group | {name}) for name, group in sorted(rk.SKILL_SYNONYMS.items())]
_SYNONYMS = sorted({spelling for group in _SYNONYM_GROUPS for spelling in group})
_WORDS = [
    "machine", "learning", "robot", "robotics", "vision", "neuro", "neuroscience", "bio", "biology", "deep",
    "ml", "ai", "c++", "c#", ".net", "x-ray", "human-computer", "interaction", "naïve", "\ufb01nance", "İstanbul",
    "k", "_", "1", "2d", "(", ")", "/", "-", "'s", "gene", "genetics", "eugene", "quantum", "physics",
]
# Unicode spaces and hyphens, the en dash, tab, punctuation and none at all.
_GAPS = [" ", " ", " ", "-", "/", ", ", "  ", "\t", "", "_", ".", "\u2013", "\u00a0", "\u2010", "\u3000", "\u2009"]
_ENDS = ["(", ")", ".", "-", "#", "+", "'", '"', "/", ":", "?"]


def _phrase(rnd, most=5):
    words = [rnd.choice(_WORDS + _LOW + _SYNONYMS) for _ in range(rnd.randint(1, most))]
    out = words[0]
    for word in words[1:]:
        out += rnd.choice(_GAPS) + word
    pick = rnd.random()
    if pick < 0.15:
        out = out.upper() if rnd.random() < 0.5 else out.title()
    elif pick < 0.25:
        out = rnd.choice(_ENDS) + out
    elif pick < 0.35:
        out += rnd.choice(_ENDS)
    if rnd.random() < 0.1:
        out = rnd.choice([" ", "\t", "\u00a0"]) + out + rnd.choice(["", " ", "\u3000"])
    return out


def _generated_cases(seed, count):
    rnd = random.Random(seed)
    for _ in range(count):
        chips = [_phrase(rnd) for _ in range(rnd.randint(0, 8))]
        if chips and rnd.random() < 0.3:
            chips.append(rnd.choice(chips) + " " + _phrase(rnd, 2))
        if chips and rnd.random() < 0.3:
            chip = rnd.choice(chips)
            chips.append(rnd.choice([chip.upper(), f" {chip} ", chip.lower() + "\t"]))
        rows = [[_phrase(rnd) for _ in range(rnd.randint(0, 8))] for _ in range(6)]
        if rnd.random() < 0.3:
            group = rnd.choice(_SYNONYM_GROUPS)
            chips.append(rnd.choice(group))
            rnd.choice(rows).append(rnd.choice(group).title())
        if chips and rnd.random() < 0.3:
            for keywords in rows:
                keywords.append(f"{_phrase(rnd, 1)} {rnd.choice(chips).lower()} {_phrase(rnd, 1)}")
            chips.append(" ".join(rnd.choice(rows[0] or ["x"]) for _ in range(2)))
        yield chips, rows


@pytest.fixture
def fresh_keyword_patterns(monkeypatch):
    monkeypatch.setattr(rk, "_kw_word_res", {})


def test_the_ranking_overlap_matches_the_rule_it_had_on_generated_profiles(fresh_keyword_patterns):
    seen = {"same term": 0, "same canonical form": 0, "chip in keyword": 0, "keyword in chip": 0}
    for chips, rows in _generated_cases(seed=172, count=2000):
        desired = {chip.lower() for chip in chips}
        interests = rk._ProfileInterests({"desired_fields": chips})
        for keywords in rows:
            before = _overlap_before(desired, keywords, rk._kw_word_re)
            static = rk._build_opp_static({"keywords": keywords})
            assert interests.chips.overlap(static.ov_kws) == set(before), (chips, keywords)
            for how in before.values():
                seen[how] += 1
    assert min(seen.values()) >= 100, seen


def test_the_direct_overlap_keeps_its_own_rule_on_generated_profiles(fresh_keyword_patterns):
    """_desired_field_overlap finds a keyword inside a chip with _word_re,
    which differs from the ranking's _kw_word_re at punctuation."""
    differ = 0
    for chips, rows in _generated_cases(seed=271, count=2000):
        desired = {chip.lower() for chip in chips}
        for keywords in rows:
            before = set(_overlap_before(desired, keywords, rk._word_re))
            assert rk._desired_field_overlap(desired, keywords) == before, (chips, keywords)
            differ += before != set(_overlap_before(desired, keywords, rk._kw_word_re))
    assert differ > 0


def test_a_chip_whose_canonical_form_is_the_keyword_matches_it(monkeypatch):
    """The rule's third equality. Today's synonym table maps every canonical
    form to itself, which makes it a case of the second; both paths keep it."""
    monkeypatch.setattr(rk, "_SYNONYM_LOOKUP", {"qa": "qb", "qb": "qc"})
    assert _overlap_before({"qa"}, ["qb"], rk._kw_word_re) == {"qa": "same canonical form"}
    assert rk._ProfileInterests({"desired_fields": ["QA"]}).chips.overlap(("qb",)) == {"qa"}
    assert rk._desired_field_overlap({"qa"}, ["QB"]) == {"qa"}


def _row(i, keywords, **fields):
    return {
        "id": f"m172-{i}", "title": f"Lab {i}", "opportunity_type": "research", "source": "uiuc_faculty",
        "source_type": "faculty_research", "school": "uiuc", "keywords": list(keywords), "pi_name": "",
        "description_raw": "Students join the lab for a semester.", "eligibility": {}, "application": {},
        "metadata": {"is_active": True}, **fields,
    }


def _profile(**fields):
    return {
        "year": "junior", "major": "Computer Science", "home_school": "uiuc", "include_cross_school": True,
        "seeking_type": [], "desired_fields": [], "research_interests_text": "",
        "preferences": {"min_match_threshold": 0}, **fields,
    }


def test_a_term_no_keyword_contains_never_becomes_a_pattern():
    """A chip can hold a keyword without any keyword holding the chip: it
    still matches, and _word_re keeps nothing for it, nor for a chip that is
    in no keyword at all."""
    corpus = [_row(i, keywords) for i, keywords in enumerate([["robotics"], ["machine learning"], ["optics"]] * 4)]
    profile = _profile(desired_fields=["robotics " + "y" * 292, "machine learning " + "z" * 3000, "zoology"])
    rk._word_re.cache_clear()
    results = rk.rank_all(profile, corpus)
    assert rk._word_re.cache_info().currsize == 0
    relevant = {r.opportunity_id: r.field_relevant for r in results}
    assert relevant == {row["id"]: row["keywords"] != ["optics"] for row in corpus}


def test_each_distinct_keyword_is_decided_once_per_ranking(monkeypatch):
    decided = []
    real = rk._ChipMatch._keyword_chips

    def spy(self, keyword):
        decided.append(keyword)
        return real(self, keyword)

    monkeypatch.setattr(rk._ChipMatch, "_keyword_chips", spy)
    spellings = [["Robotics", "machine learning"], ["robotics ", "Optics"], [" MACHINE LEARNING", "optics"]]
    corpus = [_row(i, spellings[i % 3]) for i in range(30)]
    profile = _profile(desired_fields=["robotics", "learning", "optics lab"])
    rk.rank_all(profile, corpus)
    assert sorted(decided) == ["machine learning", "optics", "robotics"]
    rk.rank_all(profile, corpus)
    assert len(decided) == 6


def _bonus_before(profile, opportunity):
    """_interest_bonus as it counted before M172: token by token."""
    interests = str(profile.get("research_interests_text") or "").strip()
    if len(interests) < 4:
        return 0.0
    signal_text = rk._opp_static(opportunity).signal_text
    tokens = rk._interest_bonus_tokens(interests)
    if not signal_text or not tokens:
        return 0.0
    hits = sum(1 for t in tokens if f" {t}" in signal_text)
    return min(INTEREST_BONUS_CAP, hits * INTEREST_BONUS_PER_HIT) if hits else 0.0


def _penalty_before(profile, opportunity):
    """_topic_alignment_penalty as it read the text before M172."""
    if opportunity.get("opportunity_type", "") != "research" or profile.get("exploring"):
        return 1.0
    interest = (profile.get("research_interests_text") or "").strip().lower()
    tokens, canon_tokens = rk._topic_interest_sets(interest)
    if len(tokens) < 2:
        return 1.0
    st = rk._opp_static(opportunity)
    if not st.topic_has_specific:
        return TOPIC_UNKNOWN_PENALTY
    stems = frozenset(rk._stem_align_token(t) for t in tokens - rk._LOW_SIGNAL_ALIGN_TOKENS)
    for kw, canon, keyword_stems in st.topic_candidates:
        if (
            kw in tokens or canon in canon_tokens or canon in tokens
            or (len(kw) >= 4 and kw in interest) or (canon != kw and len(canon) >= 4 and canon in interest)
            or keyword_stems & stems
        ):
            return 1.0
    return TOPIC_MISMATCH_PENALTY


def _filler(count):
    """``count`` distinct letter-only words that no row below contains."""
    letters = "bcdfghjklmnpqrstvwxz"
    return " ".join(f"qu{letters[i // 20]}{letters[i % 20]}" for i in range(count))


_TEXT_ROWS = [
    _row(1, ["genetics"], title="Genetics Lab"),
    _row(2, ["political theory"], title="Eugene Center"),
    _row(3, ["gene therapy", "Genomics"], title="Gene Therapy Program"),
    _row(4, [" gene", "zoology"], title="Zoology Lab"),
    _row(5, ["neuroscience"], title="Neural Circuits Lab", lab_or_program="Brain Institute"),
    _row(6, ["ml"], title="Vision Lab"),
    _row(7, ["genes"], title="Heredity Lab"),
    _row(8, ["undergraduate research"], title="Summer Program"),
    _row(9, ["genetics"], title="Genetics Lab", opportunity_type="internship"),
    _row(10, [], title="Gene Lab"),
    _row(12, ["designs"], title="Studio Lab"),
    _row(13, [" nlp"], title="Language Lab"),
]


@pytest.mark.parametrize("text", [
    "gene",
    "dna",
    "gene editing and neuroscience",
    "  Gene editing, genomic medicine and machine learning  ",
    "eugene studies of zoology and theory",
    "genetic counseling, gene expression",
    _filler(63) + " gene",
    _filler(64) + " gene",
    _filler(70) + " gene neuroscience zoology",
    "  " + _filler(80) + " Genetics, eugenics, genes and gene drives ",
    _filler(90) + " machine learning",
    " gen ",
    "design of genomics tools",
    "  nlpx and corpora",
], ids=["four characters", "three characters", "short", "spaces and capitals", "eugene", "genetic",
        "tokens up to the switch", "tokens past the switch",
        "many tokens", "many tokens, spaces and capitals", "many tokens and a phrase",
        "three letters between spaces", "a broad word whose plural is a topic", "a keyword's space against the text's"])
@pytest.mark.parametrize("exploring", [False, True], ids=["focused", "exploring"])
def test_the_bonus_and_topic_check_read_the_text_as_they_did(text, exploring):
    """With or without the prepared interests, and on either side of the
    point where the bonus counts from the row's words: "gene" hits Genetics
    and Gene Therapy, never Eugene."""
    profile = _profile(research_interests_text=text, exploring=exploring)
    interests = rk._ProfileInterests(profile)
    for row in _TEXT_ROWS:
        assert rk._interest_bonus(profile, row) == rk._interest_bonus(profile, row, interests) == _bonus_before(
            profile, row), row["id"]
        assert (
            rk._topic_alignment_penalty(profile, row)
            == rk._topic_alignment_penalty(profile, row, interests)
            == _penalty_before(profile, row)
        ), row["id"]


def test_the_bonus_counts_a_whole_word_and_a_word_beginning_from_the_rows_side():
    text = _filler(70) + " gene genetics zoology"
    interests = rk._ProfileInterests(_profile(research_interests_text=text))
    assert len(interests.bonus_tokens) > 64
    hits = [rk._interest_bonus({}, row, interests) / INTEREST_BONUS_PER_HIT for row in _TEXT_ROWS[:4]]
    assert hits == [2, 0, 1, 2]


def test_the_upside_layer_names_what_the_text_holds_as_written():
    """The lab's words the research text holds, read off the text as given:
    lower-cased, not stripped."""
    row = _row(11, ["Neuroscience", "memory ", "zoology", "Sleep"], title="Memory Lab", source_type="job_board")
    profile = _profile(research_interests_text="Neuroscience of Memory ")
    interests = rk._ProfileInterests(profile)
    for given in (None, interests):
        _, fit, _ = rk.score_upside(profile, row, precomputed_sim=0.5, interests=given)
        assert "Your interest in neuroscience, memory  closely matches their work on neuroscience, memory , zoology" in fit
    assert dict(interests.in_research_text) == {"neuroscience": True, "memory ": True, "zoology": False, "sleep": False}


def test_the_text_values_are_derived_once_per_ranking(monkeypatch):
    calls = {"_interest_bonus_tokens": 0, "_topic_interest_sets": 0}
    for name in calls:
        real = getattr(rk, name)
        assert not hasattr(real, "cache_info")

        def spy(text, _real=real, _name=name):
            calls[_name] += 1
            return _real(text)

        monkeypatch.setattr(rk, name, spy)
    corpus = [_row(i, [["genetics"], ["neuroscience"], ["zoology"]][i % 3]) for i in range(30)]
    rk.rank_all(_profile(research_interests_text="gene editing and neuroscience"), corpus)
    assert calls == {"_interest_bonus_tokens": 1, "_topic_interest_sets": 1}


def test_each_substring_test_on_the_text_runs_once_per_ranking(monkeypatch):
    tested = []
    real = rk._InText.__missing__

    def spy(self, phrase):
        tested.append((id(self), phrase))
        return real(self, phrase)

    monkeypatch.setattr(rk._InText, "__missing__", spy)
    corpus = [_row(i, [["genetics", "zoology"], ["neuroscience"]][i % 2]) for i in range(40)]
    text = "Applied zoology, and the neuroscience of memory"
    rk.rank_all(_profile(research_interests_text=text), corpus)
    assert tested
    assert len(tested) == len(set(tested))


@pytest.fixture
def isolated_corpus_generation():
    import src.matcher.embeddings as emb

    saved = (emb._tfidf_vectorizer, emb._tfidf_fitted, rk._corpus_ref,
             rk._corpus_rows, rk._static_cache, rk._static_texts, rk._sim_matrix)
    yield
    (emb._tfidf_vectorizer, emb._tfidf_fitted, rk._corpus_ref,
     rk._corpus_rows, rk._static_cache, rk._static_texts, rk._sim_matrix) = saved


def test_the_research_text_becomes_one_query_vector_per_ranking(isolated_corpus_generation, monkeypatch):
    import src.matcher.embeddings as emb
    from backend.data_loader import _opportunity_corpus_text

    corpus = [_row(i, [["genetics"], ["neuroscience", "memory"], ["zoology"]][i % 3]) for i in range(30)]
    emb.fit_tfidf_corpus([_opportunity_corpus_text(o) for o in corpus])
    rk.register_corpus(corpus)
    monkeypatch.setattr(rk, "_SIMILARITY_CHUNK_SIZE", 4)
    transformed = []
    real = emb._tfidf_vectorizer.transform

    def spy(documents):
        transformed.append(list(documents))
        return real(documents)

    monkeypatch.setattr(emb._tfidf_vectorizer, "transform", spy)
    text = "The Neuroscience of memory"
    results = rk.rank_all(_profile(research_interests_text=text), corpus)
    assert transformed == [[text.lower()]]
    assert any(r.field_relevant for r in results)


def test_the_served_line_cache_keeps_no_long_line():
    from backend.routes import matches

    matches._served_short_fit_reason.cache_clear()
    long_line = "Matches your interests: " + "robotics " * 120
    assert len(long_line) > 1_000
    assert matches._served_fit_reason(long_line) == long_line
    assert matches._served_short_fit_reason.cache_info().currsize == 0
    short_line = long_line[:1_000]
    assert matches._served_fit_reason(short_line) == short_line
    assert matches._served_short_fit_reason.cache_info().currsize == 1
    assert matches._served_fit_reason("Write to x@example.edu" + " " * 1_000) == "[email redacted]"


_STATED = ["alpha", "bravo", "charlie", "delta", "echo", "foxtrot", "golf", "hotel", "india"]
_INFERRED = ["juliett", "kilo", "lima", "mike", "november", "oscar", "papa", "quebec", "romeo"]


def _interest_lines(fit):
    return [reason for reason in fit if reason.startswith("Matches your interests")]


def test_an_interest_line_names_the_first_eight_chips_it_matched():
    profile = _profile(desired_fields=list(reversed(_STATED)))
    _, fit, _ = rk.score_upside(profile, _row(20, _STATED), precomputed_sim=0.0)
    terms = ", ".join(_STATED[:8])
    assert _interest_lines(fit) == [f"Matches your interests: {terms}"]
    assert reason_key(_interest_lines(fit)[0], "fit") == {"key": "interests_match", "params": {"terms": terms}}


def test_the_plain_and_the_inferred_line_each_name_at_most_eight():
    row = _row(21, _STATED + _INFERRED, research_areas=", ".join(_STATED))
    stamp_inferred(row["metadata"], "keywords", "derived:openalex_topics")
    _, fit, _ = rk.score_upside(_profile(desired_fields=_INFERRED + _STATED), row, precomputed_sim=0.0)
    stated, inferred = ", ".join(_STATED[:8]), ", ".join(_INFERRED[:8])
    assert _interest_lines(fit) == [
        f"Matches your interests: {stated}",
        f"Matches your interests: {inferred}{rk._OUR_TOPICS}",
    ]
    assert [reason_key(line, "fit") for line in _interest_lines(fit)] == [
        {"key": "interests_match", "params": {"terms": stated}},
        {"key": "interests_match_ours", "params": {"terms": inferred}},
    ]


@pytest.mark.parametrize(("fields", "ending"), [
    ({}, ""),
    ({"source": "simplify_internships", "source_type": "internship"}, rk._OUR_TOPICS),
], ids=["the page's topics", "a listing's tags"])
def test_a_line_is_a_repeat_when_the_lab_line_names_every_chip_it_names(fields, ending):
    """The ninth chip, which the line does not name, keeps no line."""
    keywords = ["alpha bravo charlie", "delta echo foxtrot", "golf hotel zulu", "india"]
    profile = _profile(desired_fields=_STATED, research_interests_text="field work")
    row = _row(22, keywords, department="Department of Physics", **fields)
    _, fit, _ = rk.score_upside(profile, row, precomputed_sim=0.0)
    assert _interest_lines(fit) == [f"Matches your interests: {', '.join(_STATED[:8])}{ending}"]
    _, fit, _ = rk.score_upside(profile, row, precomputed_sim=0.5)
    assert fit[-1] == "Department of Physics also works on alpha bravo charlie, delta echo foxtrot, golf hotel zulu"
    assert _interest_lines(fit) == []


def test_the_matcher_version_moved_for_the_sentences():
    assert int(MATCHER_VERSION.split(".")[0]) >= 30
