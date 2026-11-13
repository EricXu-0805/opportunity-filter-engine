"""M174: one word of a sentence is no interest match.

A chip is the whole text the student typed between two commas, and a keyword
of a row matched it from inside on a single word: the chip "i want to study
how neural circuits encode memory" matched every row tagged "memory",
humanities rows among them, and the card named the whole sentence as the
interest the row matches. A chip of six words or more now matches a keyword
found inside it only when the keyword has two words or more. Words are split
on spaces and hyphens, as _TERM_GAP splits them; a piece with no letter or
digit is no word. Shorter chips, keywords of two words or more, a chip found
inside a keyword and equal terms match as before.
"""
from __future__ import annotations

from src.matcher import ranker as rk
from src.matcher.config import MATCHER_VERSION
from src.matcher.ranker import rank_opportunity, score_upside

MEMORY = "i want to study how neural circuits encode memory"


def _row(*keywords):
    return {
        "id": "m174-sentence", "title": "Lab", "opportunity_type": "research", "source": "uiuc_faculty",
        "source_type": "faculty_research", "school": "uiuc", "keywords": list(keywords), "pi_name": "",
        "description_raw": "Students join the lab for a semester.", "eligibility": {}, "application": {},
        "metadata": {"is_active": True},
    }


def _profile(*chips):
    return {"research_interests_text": ", ".join(chips), "desired_fields": list(chips),
            "seeking_type": ["research"]}


def _matched(chip, *keywords):
    interests = rk._ProfileInterests({"desired_fields": [chip]})
    return interests.chips.overlap(rk._build_opp_static({"keywords": list(keywords)}).ov_kws)


def _interest_lines(fit):
    return [line for line in fit if line.startswith("Matches your interests")]


def test_a_sentence_chip_takes_no_one_word_keyword_from_inside():
    profile = _profile(MEMORY)
    for keyword in ("memory", "circuits"):
        row = _row(keyword)
        assert _matched(MEMORY, keyword) == set()
        assert rk._desired_field_overlap({MEMORY}, [keyword]) == set()
        score, fit, _ = score_upside(profile, row, precomputed_sim=0.0)
        assert _interest_lines(fit) == []
        assert score == score_upside(profile, _row("zoology"), precomputed_sim=0.0)[0]
        assert rank_opportunity(profile, row, precomputed_sim=0.0).field_relevant is False


def test_five_words_still_take_a_one_word_keyword_and_six_do_not():
    five, six = "i want to study robotics", "i would like to study robotics"
    assert _matched(five, "robotics") == {five}
    _, fit, _ = score_upside(_profile(five), _row("robotics"), precomputed_sim=0.0)
    assert _interest_lines(fit) == [f"Matches your interests: {five}"]
    assert rank_opportunity(_profile(five), _row("robotics"), precomputed_sim=0.0).field_relevant is True
    assert _matched(six, "robotics") == set()
    assert rank_opportunity(_profile(six), _row("robotics"), precomputed_sim=0.0).field_relevant is False


def test_a_sentence_chip_still_matches_a_phrase_inside_it_and_a_keyword_that_holds_it():
    assert _matched(MEMORY, "neural circuits") == {MEMORY}
    assert _matched(MEMORY, "memory", "neural circuits") == {MEMORY}
    assert _matched(MEMORY, "memory") == set()
    _, fit, _ = score_upside(_profile(MEMORY), _row("memory", "neural circuits"), precomputed_sim=0.0)
    assert _interest_lines(fit) == [f"Matches your interests: {MEMORY}"]
    held = "machine learning for robotic arm control"
    assert _matched(held, f"{held} systems") == {held}
    assert _matched(held, held) == {held}


def test_words_are_split_on_spaces_and_hyphens_and_need_a_letter_or_digit():
    # Five pieces between spaces, six words: the hyphen splits one.
    hyphened = "i like bio-inspired soft robotics"
    assert _matched(hyphened, "robotics") == set()
    assert _matched(hyphened, "soft robotics") == {hyphened}
    # Six pieces between spaces, five words: the em dash has no letter.
    dashed = "i want to — study robotics"
    assert _matched(dashed, "robotics") == {dashed}
    # An em dash splits no word: "memory—circuits" is one of five.
    joined = "i want to study memory—circuits"
    assert _matched(joined, "circuits") == {joined}
    # A keyword's hyphen splits it as well: "x-ray" has two words.
    imaging = "i want to use x-ray imaging in medicine"
    assert _matched(imaging, "x-ray") == {imaging}
    assert _matched(imaging, "imaging") == set()
    # A keyword with no letter or digit has no word, which is fewer than two.
    dotted, short = "i want to study robotics....and vision", "i study robotics....and vision"
    assert _matched(dotted, "....") == set()
    assert _matched(short, "....") == {short}


def test_only_a_keyword_that_a_sentence_chip_holds_has_its_words_counted(monkeypatch):
    counted = []
    real = rk._word_count

    def spy(term):
        counted.append(term)
        return real(term)

    monkeypatch.setattr(rk, "_word_count", spy)
    keywords = ("robotics", "zoology", "memory", "neural circuits")
    short = rk._ChipMatch({"robotics", "computer vision"}, rk._kw_word_re)
    sentence = rk._ChipMatch({"robotics", MEMORY}, rk._kw_word_re)
    counted.clear()
    short.overlap(keywords)
    assert counted == []
    assert sentence.overlap(keywords) == {"robotics", MEMORY}
    assert counted == ["memory", "neural circuits"]


def test_the_matcher_version_moved_for_the_match():
    assert int(MATCHER_VERSION.split(".")[0]) >= 39
