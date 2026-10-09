"""Evidence-mapped résumé rewrites: anchors, links, the closed vocabulary, the locks and the review.

Provider-free. The routes that use this module are tested in test_tailor_review.py
(Tailor, renovation, re-optimize) and test_target_resume_ai.py (full target).
"""
from __future__ import annotations

import asyncio
import json
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.lib import evidence_map as em
from backend.lib import target_resume_ai_grounding as grounding
from backend.lib.blocking import BlockingWorkTimeout
from backend.lib.target_resume_ai_grounding import RESUME_VERB_FORMS
from src.evidence import _faculty_profile_summary

CASES = json.loads((Path(__file__).parent / "fixtures" / "evidence_map_cases.json").read_text())["cases"]
AREAS = ("Image-guided adaptive radiation therapy, Functional image-based tumor response assessment and "
         "predication, Task-based medical imaging quality assessment, Medical imaging and image analysis for "
         "diagnosis and radiation therapy, Deep learning for clinical decision-making, Bioimaging at Multi-Scale")


def faculty(**metadata):
    return {"id": "faculty-x", "source_type": "faculty_research", "pi_name": "Hua Li", "department": "Bioengineering",
            "organization": "University of Illinois Urbana-Champaign", "keywords": ["radiation", "imaging", "tumor"],
            "metadata": metadata}


def anchors_for(texts):
    return {f"t{i}": em.Anchor(f"t{i}", {"field": "description", "requirement_index": None, "start": 0,
                                         "end": len(text), "quote": text})
            for i, text in enumerate(texts, start=1) if text}


class TestAnchors:
    @pytest.mark.parametrize("status", [None, "not_accepting_undergraduates", "research_inactive"])
    def test_a_stated_research_areas_list_is_the_only_quotable_faculty_text(self, status):
        record = faculty(research_areas_raw=AREAS, **({"faculty_availability_status": status} if status else {}))
        description = _faculty_profile_summary(record)
        anchors = em.opportunity_anchors(description, [], research_areas=AREAS)
        assert [anchor.text for anchor in anchors] == [area.strip() for area in AREAS.split(",")]
        for anchor in anchors:
            evidence = anchor.evidence
            assert description[evidence["start"]:evidence["end"]] == evidence["quote"]
            assert "Faculty research profile" not in anchor.text and "Contact this" not in anchor.text
            assert "source profile" not in anchor.text

    @pytest.mark.parametrize("status", [None, "not_accepting_undergraduates", "research_inactive"])
    def test_keywords_printed_as_research_areas_are_never_quotable(self, status):
        # _faculty_profile_summary writes the first 6 keywords when no areas were
        # scraped; some are OpenAlex topics with no inference stamp.
        record = faculty(**({"faculty_availability_status": status} if status else {}))
        description = _faculty_profile_summary(record)
        assert "Research areas: radiation, imaging, tumor" in description
        assert em.opportunity_anchors(description, []) == []
        assert em.opportunity_anchors(description, [], research_areas="radiation, imaging") == []

    def test_a_faculty_template_without_areas_has_no_anchor(self):
        description = _faculty_profile_summary({**faculty(), "keywords": []})
        assert em.opportunity_anchors(description, [], research_areas="") == []

    def test_a_semicolon_list_splits_on_semicolons(self):
        areas = "Soil ecology; nitrogen cycling in prairie soils; microbial community assembly"
        description = _faculty_profile_summary(faculty(research_areas_raw=areas))
        assert [a.text for a in em.opportunity_anchors(description, [], research_areas=areas)] == [
            "Soil ecology", "nitrogen cycling in prairie soils", "microbial community assembly"]

    def test_a_posting_splits_into_sentences_and_requirements(self):
        description = ("The Brooks lab studies photosynthesis and nitrogen metabolism. Duties include growing plants "
                       "and analyzing data. For more information, including how to apply, please see full blog posting.")
        anchors = em.opportunity_anchors(description, ["PCR", "Python"])
        assert [a.text for a in anchors] == [
            "The Brooks lab studies photosynthesis and nitrogen metabolism",
            "Duties include growing plants and analyzing data", "PCR", "Python"]
        assert anchors[2].evidence == {"field": "requirement", "requirement_index": 0, "start": 0, "end": 3,
                                       "quote": "PCR"}
        assert [a.id for a in anchors] == ["t1", "t2", "t3", "t4"]

    def test_urls_and_emails_are_cut_out_of_an_anchor(self):
        description = "Apply via https://lab.example.edu/join or write to pi@example.edu about sleep and memory studies."
        texts = [a.text for a in em.opportunity_anchors(description, [])]
        assert all("http" not in text and "@" not in text for text in texts)
        assert "about sleep and memory studies" in texts

    def test_a_long_sentence_splits_at_commas_and_the_list_is_capped(self):
        long = ", ".join(f"topic number {i} in bioinformatics" for i in range(8)) + "."
        assert all(len(a.text) <= em.MAX_ANCHOR_CHARACTERS for a in em.opportunity_anchors(long, []))
        many = " ".join(f"Topic {i} is studied here." for i in range(80))
        assert len(em.opportunity_anchors(many, [])) == em.MAX_ANCHORS

    def test_verified_paper_titles_are_anchors(self):
        anchors = em.opportunity_anchors("", [], paper_titles=["Deep learning for dose prediction"])
        assert anchors[0].evidence == {"field": "paper_title", "paper_index": 0, "start": 0, "end": 33,
                                       "quote": "Deep learning for dose prediction"}

    def test_full_target_anchors_use_available_research_and_lab_only(self):
        research = {"status": "available", "snapshot": {"works": [{"title": "Sleep and memory in aging"}]}}
        lab = {"status": "available", "snapshot": {"pages": [{"sections": [
            {"heading": "Methods", "text": "We use EEG. We run sleep studies."}]}]}}
        target = {"description": "", "requirements": ["EEG"], "context_version": 4, "research": research, "lab": lab}
        fields = [(a.evidence["field"], a.text) for a in em.target_anchors(target)]
        assert fields == [("requirement", "EEG"), ("paper_title", "Sleep and memory in aging"),
                          ("lab_heading", "Methods"), ("lab_text", "We use EEG"), ("lab_text", "We run sleep studies")]
        stale = {**target, "research": {**research, "status": "stale"}, "lab": {**lab, "status": "stale"}}
        assert [a.text for a in em.target_anchors(stale)] == ["EEG"]


class TestSpans:
    @pytest.mark.parametrize(("anchor", "term", "found"), [
        ("Robotics", "R", False), ("Robotics", "robotics", True),
        ("Age-related Differences", "Age", False), ("Age-related Differences", "age-related differences", True),
        ("Aging in Place", "Aging in", False), ("Aging in Place", "Aging in Place", True),
        ("Pathogens and biofilms in drinking water", "drinking water", True),
        ("饮用水管网中的病原体", "病原体", True),
        ("one two three four five six seven", "one two three four five six seven", False),
    ])
    def test_terms_are_word_bounded_with_no_stopword_edges(self, anchor, term, found):
        assert (em.term_span(anchor, term) is not None) is found

    def test_source_spans_tolerate_case_and_spacing_but_not_paraphrase(self):
        original = "Ran PCR  genotyping on 40 lines"
        assert em.source_span(original, "pcr genotyping") == (4, 19)
        assert em.source_span(original, "PCR genotype") is None
        assert em.source_span(original, "on 40 lines") is None


class TestLockWordsScanLinearly:
    @pytest.mark.parametrize("text", ["a-" * 30000, "then " * 12000 + "x", "carefully " * 6000 + "x",
                                      "x, a " + "b" * 60000, "x, a b, " * 6000])
    def test_another_persons_revision_is_read_in_linear_time(self, text):
        # Starting the word anywhere inside "a-a-a-..." or repeating "then" without
        # a bound took about 6 s here; the anchored scan takes ~0.02 s.
        started = time.perf_counter()
        em._OTHER_PERSON.findall(text)
        assert time.perf_counter() - started < 1


class TestRunsAreReadOnce:
    @pytest.mark.parametrize(("name", "read", "text"), [
        ("_SPAN", lambda text: em._SPAN.findall(text), "1" * 60000),
        ("_TEAM_ZH_EXTRA", lambda text: em._TEAM_ZH_EXTRA.findall(text), "1" * 60000),
        ("_URL_OR_EMAIL", lambda text: em._URL_OR_EMAIL.findall(text), "开发" * 30000)])
    def test_a_long_run_of_digits_or_word_characters_is_read_in_linear_time(self, name, read, text):
        # Each of these took 9 to 36 s on such a run before its start was anchored.
        started = time.perf_counter()
        read(text)
        assert time.perf_counter() - started < 1, name


class TestLinesAreReadInLinearTime:
    """A run of spaces, of 为 or 为打下 or of personal markers is read once.

    Each of these started a scan at every character of the run, or read the rest of
    the line once per marker: 0.04 to 1.4 s at 6,000 characters. Every check reads a
    whole line, and a regex holds the GIL while it runs, worker thread or not.
    """

    @pytest.mark.parametrize(("name", "read", "text"), [pytest.param(*case, id=case[0]) for case in [
        ("_LIST_ITEM", lambda text: em._LIST_ITEM.findall(text), " " * 60000 + "x"),
        ("_FACULTY_TAIL", lambda text: em._FACULTY_TAIL.search(text), " " * 60000 + "x"),
        ("strip_json_fence", em.strip_json_fence, "```x" + " " * 60000 + "y"),
        ("RELEVANCE_PADDING 为", lambda text: grounding.RELEVANCE_PADDING.findall(text), "为" * 60000),
        ("RELEVANCE_PADDING building", lambda text: grounding.RELEVANCE_PADDING.findall(text), "，building" * 6000),
        ("APPENDED_RELEVANCE spaces", lambda text: grounding.APPENDED_RELEVANCE.findall(text), " " * 60000 + "x"),
        ("APPENDED_RELEVANCE 为打下", lambda text: grounding.APPENDED_RELEVANCE.findall(text), "为打下" * 20000),
        ("_CLAUSE_BREAK", lambda text: grounding._CLAUSE_BREAK.findall(text), " " * 60000 + "x"),
        ("_NOUN_END", lambda text: grounding._NOUN_END.split(text, maxsplit=1), " " * 60000 + "x"),
        ("clauses", grounding.clauses, " " * 60000 + "x"),
        ("supported_claim_upgrade_detected", lambda text: grounding.supported_claim_upgrade_detected(text, [text, "z"]),
         " " * 60000 + "x"),
        ("_TEAM_HEADER search", lambda text: em._TEAM_HEADER.search(text), "与" * 60000),
        ("_OTHER_SUBJECT search", lambda text: grounding._OTHER_SUBJECT.search(text), "1" * 60000),
        ("_STUDENT_AGENT search", lambda text: grounding._STUDENT_AGENT.search(text), "1" * 60000),
        ("_BY search", lambda text: grounding._BY.search(text), " " * 60000 + "x"),
        ("_CJK_RUN_END search", lambda text: grounding._CJK_RUN_END.search(text), "中" * 60000 + "x"),
        ("_marks_own_part", em._marks_own_part, "I " * 30000),
        ("_marks_own_part glued", em._marks_own_part, "a我" * 30000)]])
    def test_a_long_run_is_read_in_linear_time(self, name, read, text):
        started = time.perf_counter()
        read(text)
        assert time.perf_counter() - started < 1, name

    @pytest.mark.parametrize(("text", "marks"), [
        ("Built a rover with two teammates; I designed the mount.", True),
        ("As part of a four-person team, I helped design the mount.", False),
        ("With my team, I built the rover.", False),
        ("With my team, I built the rover; I wrote its tests.", True),
        ("With my teammates and my group, I built the rover.", True),
        ("I designed the mount with my team.", False),
        ("和 teammates我负责建模，我写了报告，我做了测试。", True),
        ("我负责建模，和 teammates一起，我写了报告。", True),
        ("我负责建模，我写了报告，和 teammates一起。", False), ("With my team, 我负责建模。", False)])
    def test_the_last_two_markers_and_a_glued_我_decide_the_students_part(self, text, marks):
        assert em._marks_own_part(text) is marks

    @pytest.mark.parametrize("unit", [" ", "为打下", "为", "在实验室", "I ", "a我"], ids=repr)
    def test_a_line_at_the_cap_is_checked_in_well_under_a_second(self, unit):
        line = (unit * 6000)[:6000]
        started = time.perf_counter()
        grounding.claim_upgrade_findings(line[:-1] + "x", line)
        assert time.perf_counter() - started < 1, unit


class TestSpanWords:
    @pytest.mark.parametrize("quantity", [
        "thirteen", "fourteen", "sixteen", "seventeen", "eighteen", "nineteen", "twice", "double", "triple", "half",
        "several dozen", "many years", "multiple weeks", "numerous times", "several hundred", "many thousands",
        "several millions", "many months", "several days", "many hours", "several semesters", "many terms",
        "several summers", "many decades", "hundreds", "thousand", "millions", "billion", "tens", "dozens",
        "a million", "a billion", "an order of", "a factor of"])
    def test_a_preposition_before_a_quantity_is_a_span(self, quantity):
        assert em._SPAN.search(f"Cut the error by up to {quantity} times.")
        assert em._SPAN.search(f"Made it about {quantity} as fast.")

    @pytest.mark.parametrize("text", [
        "Gave a talk about sleep.", "Studied plants under drought.", "Read over the protocol.",
        "Walked around the campus.", "Read more than the abstract.", "Read less than the full paper.",
        "Covered up to the third chapter.", "Gave a talk about many species of birds.", "Read papers about multiple sclerosis.",
        "Summarized papers about double-blind trials.", "Wrote a review about triple-negative breast cancer."])
    def test_a_relabel_keeps_a_span_word_in_any_use(self, text):
        assert not em._SPAN.search(text)
        assert any(pattern.search(text) for pattern in em._LOCK_WORD)

    @pytest.mark.parametrize("text", ["最多降低了一个数量级", "至多 3 次", "多达 40 名", "高达 90%", "不到一周"])
    def test_chinese_up_to_and_less_than_are_spans(self, text):
        assert em._SPAN.search(text)
        assert not em._SPAN.search("引用最多的论文")


class TestMoreListedShapes:
    def test_in_development_is_work_under_way_but_development_of_is_not(self):
        assert em.UNFINISHED.search("Built the backend for a campus dining app in development.")
        assert not em.UNFINISHED.search("Gained experience in development of ML models.")

    @pytest.mark.parametrize("word", ["unpublished", "unsubmitted", "unfinished", "untested", "unverified",
                                      "unvalidated", "unreviewed"])
    def test_an_un_done_word_is_a_relabel_lock_word(self, word):
        assert em._relabel_swap_refusal(f"{word} EEG recordings", "EEG data") == "relabel_drops_protected"

    @pytest.mark.parametrize("text", [
        "在学长指导下搭建了节点", "在学姐指导下搭建了节点", "在主管指导下整理了数据", "Supervised by a senior student.",
        "Drafted it; a senior student corrected it.", "Drafted it; Sam reviewed it.", "Drafted it; Sam proofread it.",
        "Drafted it, reviewed by the lab manager.", "Drafted it, corrected by Sam.", "Drafted it, proofread by Sam.",
        "Drafted it; Sam, a senior student, reviewed it."])
    def test_another_persons_review_or_correction_is_their_part(self, text):
        assert em._OTHER_PERSON.search(text)

    @pytest.mark.parametrize("text", ["Reviewed 30 papers for the club.", "Corrected 40 exams.",
                                      "Drafted the report and proofread it.", "Published a peer-reviewed paper."])
    def test_the_students_own_review_is_no_one_elses_part(self, text):
        assert not em._OTHER_PERSON.search(text)

    @pytest.mark.parametrize(("text", "span"), [
        ("Surveyed upwards of 200 students.", True), ("Surveyed close to 200 students.", True),
        ("Lives close to the lab.", False), ("调查了上百名学生", True), ("调查了上千名学生", True), ("调查了上万名学生", True),
        ("上百度搜索资料", False)])
    def test_upwards_of_close_to_and_上百_are_spans(self, text, span):
        assert bool(em._SPAN.search(text)) is span

    @pytest.mark.parametrize("text", ["Lives upwards of the river.", "Lives close to the lab."])
    def test_a_relabel_keeps_upwards_of_and_close_to_in_any_use(self, text):
        assert em._SPAN_WORD.search(text)

    def test_协同_is_shared_work(self):
        assert em._TEAM_ZH_EXTRA.search("与组员协同完成了测试")


class TestBoundsAndApproximations:
    @pytest.mark.parametrize(("text", "token"), [
        ("~300 images", "~300"), ("~ 300 images", "~300"), ("≈300 images", "≈300"), (">90% accuracy", ">90%"),
        ("<50 ms", "<50"), ("≤5 runs", "≤5"), ("≥99% uptime", "≥99%"), ("40+ participants", "40+"),
        ("1,000+ users", "1000+"), ("90%+ accuracy", "90%+"), ("~1,000 users", "~1000")])
    def test_a_number_keeps_its_bound_or_approximation_sign(self, text, token):
        assert em.tokens(text)[0] == token

    @pytest.mark.parametrize("text", [
        "Drew as many as 200 students.", "Lifted as much as 5 kg.", "Reached accuracy as high as 95%.",
        "Interviewed some 30 farmers.", "Tested 40 or so samples.", "Waited a week or so.", "Surveyed 200-odd students.",
        "Annotated ~300 images.", "Annotated ≈300 images.", "Cut latency to <50 ms.", "Reached >90% accuracy.",
        "Kept runs ≤5.", "Kept uptime ≥99%.", "Recruited 40+ participants.", "Reached 90%+ accuracy.",
        "招募了 40 余名参与者", "十余名学生", "三十多名学生", "最多 12 名", "每周最多辅导 12 名学生",
        *(f"{number}{word}" for number in "十百千万" for word in "余多")])
    def test_a_bound_or_an_estimate_is_a_span(self, text):
        assert em._SPAN.search(text)

    @pytest.mark.parametrize("text", [
        "Labeled fewer than 300 images.", "Needed as few as 3 runs.", "Used as little as 2 ml.", "Kept error as low as 1%.",
        "Reached an estimated 2,000 readers.", "检测了近 40 份水样", "招募了 40 多名参与者", "准确率达到 90% 以上",
        "18 岁以下"])
    def test_a_bound_the_span_words_leave_out_is_left_to_the_review(self, text):
        # Each also matched a faithful line's verb, model name or place ("Estimated 3 models",
        # GPT-4 多模态, 靠近 3 号楼, 2% 以下 for "below 2%"); dropping one reaches the review.
        assert not em._SPAN.search(text)

    @pytest.mark.parametrize("text", [
        "得票最多的人",
        *(f"得票最多{mark}" for mark in ("。", "，", ",", "；", ";", "）", ")", "")), "附近 3 家医院", "最近 3 年",
        "近五年的数据", "近三年来", "近两年内", "近 10 个月间", "近 3 年来的", "近两个月的", "近三周的", "近十天的",
        "近 5 日的", "近两个季度的", "近两学期的", "近期参加了比赛", "靠近校园的实验室", "其余 3 人", "Analyzed some data.",
        "Estimated the cost of the trip.", "Recruited fewer participants than expected."])
    def test_a_verb_a_superlative_or_a_recent_past_is_no_span(self, text):
        assert not em._SPAN.search(text)

    @pytest.mark.parametrize("verb", "找做想看达得用等买收见听")
    def test_不到_after_a_verb_is_still_a_span(self, verb):
        # 用不到 100 行 bounds a number and 找不到 or 达不到 denies; only _SPAN reads them.
        assert em._SPAN.search(f"{verb}不到数据")

    @pytest.mark.parametrize("text", [
        "Recruited fewer than expected.", "Ran as many as needed.", "Used as much as needed.", "Needed as few as possible.",
        "Spent as little as possible.", "Scored as high as the PI.", "Priced as low as the rest."])
    def test_a_relabel_keeps_a_comparison_word_in_any_use(self, text):
        assert em._SPAN_WORD.search(text) and not em._SPAN.search(text)


class TestTeamAndShare:
    @pytest.mark.parametrize("text", [
        *(f"Designed it with three other {noun}." for noun in (
            "students", "interns", "volunteers", "members", "researchers", "undergrads", "undergraduates",
            "participants", "tutors", "employees")),
        "Designed it with another student.", "Sorted cans alongside two other volunteers.",
        "Cleaned data with fellow interns.", "Built it with my fellow lab members.", "Wrote it among other researchers.",
        "Built it together with other undergraduates.", "Built it with several other students.",
        "Built it with four other students.", "Built it with 12 other students.", "Built it with the others.",
        "Built it with colleagues.", "Built it with peers.", "Built it with co-workers.", "Built it with coworkers.",
        "Built it with others.",
        *(f"与{other}三名{noun}一起" for other in ("另外", "另一", "其他", "其余")
          for noun in ("学生", "同学", "志愿者", "实习生", "成员", "研究员", "同事", "队员"))])
    def test_other_collaborators_are_a_relabel_lock_word(self, text):
        assert em._TEAM_OTHERS.search(text)
        assert em._TEAM_OTHERS in em._LOCK_WORD

    @pytest.mark.parametrize("text", ["Tutored 30 students in calculus.", "Held office hours with 30 students.",
                                      "Trained 5 colleagues in Excel.", "Met with members of the public.",
                                      "为其他学院开发了网站"])
    def test_people_the_work_serves_are_no_team(self, text):
        assert not em._TEAM_OTHERS.search(text)

    @pytest.mark.parametrize("text", [
        "Participated in the analysis.", "Participating in a study.", "Participation in a study.",
        "Contributed to the design.", "Contributing to a review.", "Made contributions to the code.",
        "Core contributor to the library.", "Involved in collecting data.", "Involvement in a project.",
        "Took part in testing.", "Take part in testing.", "Takes part in testing.", "Taking part in testing."])
    def test_a_share_of_the_work_is_an_english_participation_word(self, text):
        assert em._PARTICIPATION_EN.search(text)

    def test_participants_are_people_not_a_share(self):
        assert not em._PARTICIPATION_EN.search("Recruited 40 participants.")


class TestUnknownVerbs:
    @pytest.mark.parametrize(("original", "proposed"), [
        ("Visiting student at Peking University in Summer 2025, analyzing 30 EEG recordings.",
         "Analyzed 30 EEG recordings as visiting student at Peking University in Summer 2025."),
        ("Fundraising chair for CSSA since Fall 2025, organizing 3 charity galas.",
         "Organized 3 charity galas as fundraising chair for CSSA since Fall 2025."),
        ("Swimming instructor at the ARC since May 2025, teaching 40 children a week.",
         "Taught 40 children a week as swimming instructor at the ARC since May 2025.")])
    def test_a_role_word_in_ing_keeps_verb_first_open(self, original, proposed):
        assert not grounding.status_upgraded(proposed, original)

    @pytest.mark.parametrize(("original", "proposed", "upgraded"), [
        ("Wiring 3 soil sensors.", "Soil sensors: wired 3.", True),
        ("Also scraping 2,000 postings.", "Postings: scraped 2,000.", True),
        ("Wiring 3 soil sensors.", "Soil sensors: wiring 3.", False),
        ("Wired 2 sensors; now wiring 3 more.", "Now wiring 3 more; wired 2 sensors.", False),
        ("Wiring the sensor wires.", "Sensor wires: wired them.", True),
        ("Wiring the sensor wires.", "Sensor wires: wiring them.", False),
        ("Organizers of the club fair: booked 40 booths.", "Organized the club fair: booked 40 booths.", False)])
    def test_an_unknown_lead_is_finished_only_by_its_own_ed_form(self, original, proposed, upgraded):
        assert grounding.status_upgraded(proposed, original) is upgraded


class TestOwnPastVerbs:
    @pytest.mark.parametrize(("original", "proposed", "upgraded"), [
        ("Setting up a server for the lab.", "Lab: set up a server.", True),
        ("Reading 30 papers for a review.", "Review: read 30 papers.", True),
        ("Setting up a server for the lab.", "Lab: setting up a server.", False),
        ("Read 20 papers last fall; now reading 10 more.", "Now reading 10 more; read 20 papers last fall.", False),
        ("Volunteering at a food bank, sorting donations.", "Food bank volunteer: sorting donations.", False)])
    def test_a_verb_that_is_its_own_past_finishes_work_under_way(self, original, proposed, upgraded):
        assert grounding.status_upgraded(proposed, original) is upgraded


REVISION_ADVERBS = ("carefully", "thoroughly", "personally", "independently", "jointly", "extensively", "substantially",
                    "heavily", "fully", "completely", "partially", "partly", "lightly", "briefly", "closely", "rigorously",
                    "meticulously", "iteratively", "repeatedly", "manually", "critically", "collaboratively")


class TestAnotherPersonsRevision:
    @pytest.mark.parametrize("text", [
        "Submitted a revised plan.", "Submitted an edited volume.", "Submitted the revised plan.",
        "Submitted this revised plan.", "Submitted these revised plans.", "Submitted those revised plans.",
        "Submitted my revised plan.", "Submitted our revised plan.",
        "Drafted the plan or revised it.", "Drafted the plan and also revised it.", "Drafted the plan and revised it.",
        "I revised the plan.", "Revised the plan.", "We revised the plan.",
        *(f"{adverb.capitalize()} revised the plan." for adverb in REVISION_ADVERBS),
        *(f"Drafted the plan and {adverb} edited it." for adverb in REVISION_ADVERBS),
        "Wrote the proposal, my first grant, and revised it."])
    def test_the_students_own_revision_or_a_version_is_no_one_elses_part(self, text):
        assert not em._OTHER_PERSON.search(text)

    @pytest.mark.parametrize("text", [
        "Drafted it; Sam revised it.", "Drafted it; Sam then revised it.", "Drafted it; Sam also revised it.",
        "Drafted a plan that I revised.", "Drafted it; Sam and I revised it.", "Wrote it, edited by Sam.",
        "Submitted its revised plan.", "Submitted their revised plan.", "Submitted his revised plan.",
        "Submitted her revised plan.", "Drafted it, which we revised.",
        *(f"Drafted it; Sam {adverb} revised it." for adverb in REVISION_ADVERBS),
        *(f"Drafted it; Sam, {det} senior student, revised it." for det in ("a", "the", "my", "our", "his", "her",
                                                                            "their")),
        "Drafted it; Sam, an editor, revised it.", "Drafted it; Sam, a senior student, also revised it.",
        "Drafted it; Sam, a senior student, carefully revised it."])
    def test_a_revision_after_another_word_is_another_persons_part(self, text):
        assert em._OTHER_PERSON.search(text)


class TestLemma:
    def test_every_form_of_every_resume_verb_shares_one_lemma(self):
        bases = sorted({base for base, _ in RESUME_VERB_FORMS.values()})
        assert len(bases) >= 150
        for form, (base, _) in RESUME_VERB_FORMS.items():
            assert em.lemma(form) == em.lemma(base), (form, base)

    @pytest.mark.parametrize(("left", "right"), [
        ("writing", "wrote"), ("making", "made"), ("studying", "studied"), ("images", "imaging"),
        ("scripts", "script"), ("analyses", "analyses"),
    ])
    def test_both_sides_normalize_the_same_way(self, left, right):
        assert em.lemma(left) == em.lemma(right)

    @pytest.mark.parametrize(("text", "will"), [
        ("论文将于 5 月发表", True), ("将在 SfN 上展示海报", True), ("将会提交论文", True), ("将要发表论文", True),
        ("将在线问卷录入系统", False), ("将会议记录整理成表", False), ("将要点整理成表", False), ("将要求整理成表", False),
        ("将数据录入系统", False), ("将会员信息整理成表", False), ("将要素分析结果写成报告", False)])
    def test_a_will_is_content_and_an_object_marker_is_not(self, text, will):
        assert ("将" in em.tokens(text)) is will

    def test_quantity_status_and_personal_words_are_visible(self):
        assert {em.lemma(word) for word in ("over", "since", "per")} <= set(
            em.tokens("over 200 samples since 2024, 3 per week"))
        assert {"中", "已"} <= set(em.tokens("撰写中；已投稿；本人负责"))
        assert em.personal_markers("I built it; my part; 本人负责；我们") == 3


class TestEnvelope:
    ROW = {"unit_id": "b1", "links": [], "decision": "keep", "ops": [], "text": None, "keep_reason": "no_link"}

    def test_a_model_that_corrects_itself_is_read_by_its_last_answer(self):
        first = json.dumps({"bullets": [{**self.ROW, "decision": "rewrite", "text": "x", "keep_reason": None}]})
        second = json.dumps({"bullets": [self.ROW]})
        raw = f"{first}\n\nWait, verb_first does not apply here. Let me correct this output.\n\n{second}"
        assert em.parse_rows(raw, {"b1"}, key="bullets") == {"b1": self.ROW}
        assert em.parse_rows(f"{second}\nThat is my answer.", {"b1"}, key="bullets") == {"b1": self.ROW}

    @pytest.mark.parametrize("raw", ["no JSON at all", '{"units": []}', '{"bullets": {}}', '{"bullets": [], "extra": 1}'])
    def test_an_unusable_reply_is_none(self, raw):
        assert em.parse_rows(raw, {"b1"}, key="bullets") is None


class TestLinks:
    def test_only_literal_links_survive_and_same_needs_a_shared_word(self):
        anchors = anchors_for(["Specific techniques include PCR and cloning", "Deep learning for imaging"])
        raw = [
            {"id": "L1", "anchor": "t1", "term": "PCR", "source": "PCR genotyping", "relation": "same"},
            {"id": "L2", "anchor": "t2", "term": "Deep learning", "source": "image classifier", "relation": "same"},
            {"id": "L3", "anchor": "t9", "term": "PCR", "source": "PCR genotyping", "relation": "same"},
            {"id": "L4", "anchor": "t1", "term": "RNA", "source": "PCR genotyping", "relation": "same"},
        ]
        links = em.verify_links(raw, [(None, "Ran PCR genotyping and an image classifier")], anchors)
        assert [(link.id, link.relation) for link in links] == [("L1", "same"), ("L2", "broader")]
        assert links[0].target_evidence["quote"] == "PCR" and links[0].target_evidence["start"] == 28
        assert links[0].source_evidence == {"start": 4, "end": 18, "quote": "PCR genotyping"}

    def test_a_fourth_link_is_ignored(self):
        anchors = anchors_for(["alpha beta gamma delta"])
        raw = [{"id": f"L{i}", "anchor": "t1", "term": term, "source": term, "relation": "same"}
               for i, term in enumerate(["alpha", "beta", "gamma", "delta"], start=1)]
        assert len(em.verify_links(raw, [(None, "alpha beta gamma delta")], anchors)) == 3


class TestContract:
    @pytest.mark.parametrize("case", CASES, ids=lambda case: case["label"])
    def test_declared_maps(self, case):
        anchors = anchors_for(case["anchors"])
        unit = em.Unit("b1", case["original"], case["original"])
        row = {"unit_id": "b1", "links": case["links"], "decision": "rewrite", "ops": case["ops"],
               "text": case["rewrite"], "keep_reason": None}
        outcome = em.check_rewrite(unit, row, anchors, output_language=em.language(case["original"]))
        if outcome.status == "pending":
            outcome = em.gate(outcome, unit)
        status, code, detail = case["expected"]
        assert (outcome.status, outcome.code) == (status, code), outcome
        assert detail is None or (outcome.detail or "").startswith(detail), outcome.detail

    def test_the_calibration_disabled_moves_are_refused(self):
        refused = [case for case in CASES if case["expected"][2] in ("relabel_not_same", "unknown_op")]
        assert len(refused) >= 14

    @pytest.mark.parametrize(("decision", "links", "text", "keep_reason"), [
        ("keep", [], "Built it.", "no_link"), ("keep", [], None, "maybe"), ("rewrite", [], None, None),
        ("rewrite", [], "  ", None), ("drop", [], None, None),
    ])
    def test_a_malformed_row_is_invalid(self, decision, links, text, keep_reason):
        unit = em.Unit("b1", "Built a rover.", "Built a rover.")
        row = {"unit_id": "b1", "links": links, "decision": decision, "ops": [], "text": text,
               "keep_reason": keep_reason}
        assert em.check_rewrite(unit, row, {}, output_language="en").status == "invalid"
        assert em.check_rewrite(unit, {**row, "extra": 1}, {}, output_language="en").status == "invalid"

    def test_a_row_may_leave_out_the_fields_its_decision_makes_null(self):
        anchors = anchors_for(["Python"])
        unit = em.Unit("b1", "Wrote parser tests for the lab using Python.", "Wrote parser tests for the lab using Python.")
        keep = {"unit_id": "b1", "decision": "keep"}
        assert em.check_rewrite(unit, keep, anchors, output_language="en").code == "no_link"
        rewrite = {"unit_id": "b1", "decision": "rewrite", "ops": [{"op": "lead_with", "link": "L1"}],
                   "links": [{"id": "L1", "anchor": "t1", "term": "Python", "source": "Python", "relation": "same"}],
                   "text": "Using Python, wrote parser tests for the lab."}
        assert em.check_rewrite(unit, rewrite, anchors, output_language="en").status == "pending"

    def test_an_unchanged_rewrite_is_a_keep(self):
        # A rewrite that returns the line as written is a keep, whatever operation it declares.
        unit = em.Unit("b1", "本人负责浊度和 pH 测定。", "本人负责浊度和 pH 测定。")
        row = {"unit_id": "b1", "links": [], "decision": "rewrite", "ops": [{"op": "translate"}],
               "text": " 本人负责浊度和 pH 测定。", "keep_reason": None}
        outcome = em.check_rewrite(unit, row, {}, output_language="zh")
        assert (outcome.status, outcome.code, outcome.detail) == ("kept", "cosmetic_only", "unchanged_text")

    def test_the_server_names_a_keep(self):
        anchors = anchors_for(["PCR genotyping of mutant lines", "Protein folding"])
        unit = em.Unit("b1", "PCR genotyping of 40 lines; maintained stocks.", "PCR genotyping of 40 lines; maintained stocks.")
        row = {"unit_id": "b1", "decision": "keep", "ops": [], "text": None, "keep_reason": "already_aligned"}
        same = [{"id": "L1", "anchor": "t1", "term": "PCR genotyping", "source": "PCR genotyping", "relation": "same"}]
        assert em.check_rewrite(unit, {**row, "links": []}, anchors, output_language="en").code == "no_link"
        assert em.check_rewrite(unit, {**row, "links": same}, anchors, output_language="en").code == "already_aligned"
        other = [{"id": "L1", "anchor": "t1", "term": "mutant lines", "source": "40 lines", "relation": "same"}]
        assert em.check_rewrite(unit, {**row, "links": other}, anchors, output_language="en").code == "no_safe_change"


class TestGate:
    ROVER = ("Built the drivetrain for the Illini Robotics club rover in 2025 with two teammates; I designed the "
             "motor mount in SolidWorks.")

    def test_a_declared_relabel_must_stand_in_the_text_as_written(self):
        original = "Built a PyTorch image classifier for chest X-ray triage."
        model = "Built a PyTorch computer vision model for chest X-ray triage."
        assert em.rewrite_findings(model, original, [("image classifier", "computer vision model")]) == []
        assert "relabel_not_found" in em.rewrite_findings(model, original, [("image classifier", "vision system")])

    def test_a_relabel_is_undone_where_it_stands_as_whole_words(self):
        # "EEG data" first occurs inside "EEG database"; the relabel is the later, whole-word one.
        original = "Built an EEG database and analyzed EEG recordings from 20 infants."
        rewrite = "Built an EEG database and analyzed EEG data from 20 infants."
        assert em.reverse_relabels(rewrite, [("EEG recordings", "EEG data")]) == original
        assert em.rewrite_findings(rewrite, original, [("EEG recordings", "EEG data")]) == []
        assert em.reverse_relabels("Built an EEG database.", [("EEG recordings", "EEG data")]) is None

    def test_the_alternative_undoes_the_relabel_beside_a_word_that_contains_it(self):
        anchors = anchors_for(["EEG data"])
        original = "Responsible for building an EEG database and analyzing EEG recordings from 20 infants."
        unit = em.Unit("b1", original, original)
        ops = [{"op": "relabel", "link": "L1", "from": "EEG recordings", "to": "EEG data"}, {"op": "verb_first"}]
        row = {"unit_id": "b1", "decision": "rewrite", "ops": ops, "keep_reason": None,
               "links": [{"id": "L1", "anchor": "t1", "term": "EEG data", "source": "EEG recordings", "relation": "same"}],
               "text": "Built an EEG database and analyzed EEG data from 20 infants."}
        outcome = em.gate(em.check_rewrite(unit, row, anchors, output_language="en"), unit)
        assert outcome.status == "pending", outcome
        assert em.without_terms(outcome, unit, ops) == "Built an EEG database and analyzed EEG recordings from 20 infants."

    def test_two_relabels_to_one_term_offer_no_version_without_the_terms(self):
        """Undone in list order, each source would go back in the other's place: notebooks cleaned the data."""
        anchors = anchors_for(["Experience writing Python code is required."])
        original = "Responsible for writing Python scripts for data cleaning and Python notebooks for plotting."
        unit = em.Unit("b1", original, original)
        ops = [{"op": "relabel", "link": "L2", "from": "Python notebooks", "to": "Python code"},
               {"op": "relabel", "link": "L1", "from": "Python scripts", "to": "Python code"}, {"op": "verb_first"}]
        row = {"unit_id": "b1", "decision": "rewrite", "ops": ops, "keep_reason": None, "links": [
            {"id": "L1", "anchor": "t1", "term": "Python code", "source": "Python scripts", "relation": "same"},
            {"id": "L2", "anchor": "t1", "term": "Python code", "source": "Python notebooks", "relation": "same"}],
               "text": "Wrote Python code for data cleaning and Python code for plotting."}
        outcome = em.gate(em.check_rewrite(unit, row, anchors, output_language="en"), unit)
        assert outcome.status == "pending", outcome
        assert em.without_terms(outcome, unit, ops) is None
        # Each "to" standing once is undone in its own place, whatever the list order.
        assert em._undo_relabels("Wrote Python code for data cleaning and R notebooks for plotting.",
                                 [("Python notebooks", "R notebooks"), ("Python scripts", "Python code")]) == (
            "Wrote Python scripts for data cleaning and Python notebooks for plotting.")

    def test_a_denial_and_a_team_result_come_from_the_text_as_written(self):
        original = "I built a Python parser. I did not build the compiler."
        assert "denied_action_asserted" in em.rewrite_findings(
            "I built a compiler. I did not build the compiler.", original, [("Python parser", "compiler")])

    def test_a_hard_finding_keeps_the_original_with_the_findings(self):
        unit = em.Unit("b1", "Cleaned 212 survey responses in R.", "Cleaned 212 survey responses in R.")
        pending = em.Outcome("b1", "pending", text="Cleaned 212 survey responses in Python.", ops=["verb_first"])
        kept = em.gate(pending, unit)
        assert (kept.status, kept.code) == ("kept", "rewrite_rejected") and "python" in kept.findings

    def test_the_alternative_takes_the_posting_term_back_out(self):
        anchors = anchors_for(["Survey data dashboards for public health"])
        original = "Built a dashboard in R for the campus food pantry's survey."
        unit = em.Unit("b1", original, original)
        ops = [{"op": "relabel", "link": "L1", "from": "survey", "to": "survey data"}, {"op": "lead_with", "link": "L1"}]
        row = {"unit_id": "b1", "decision": "rewrite", "ops": ops, "keep_reason": None,
               "links": [{"id": "L1", "anchor": "t1", "term": "survey data", "source": "survey", "relation": "same"}],
               "text": "Survey data: built a dashboard in R for the campus food pantry."}
        outcome = em.check_rewrite(unit, row, anchors, output_language="en")
        assert outcome.status == "kept"  # "survey data" leads, but the pantry's survey is not "survey data"
        row["text"] = "Built a survey data dashboard in R for the campus food pantry."
        row["ops"] = [{"op": "relabel", "link": "L1", "from": "survey", "to": "survey data"}]
        unit = em.Unit("b1", "Built a survey dashboard in R for the campus food pantry.",
                       "Built a survey dashboard in R for the campus food pantry.")
        row["links"][0]["source"] = "survey dashboard"
        outcome = em.gate(em.check_rewrite(unit, row, anchors, output_language="en"), unit)
        assert outcome.status == "pending"
        # Without the term only the student's words remain, unchanged: nothing to offer.
        assert em.without_terms(outcome, unit, row["ops"]) is None


def _row(text, links, ops):
    return {"unit_id": "b1", "decision": "rewrite", "text": text, "keep_reason": None,
            "links": [dict(zip(("id", "anchor", "term", "source"), link, strict=True), relation="same") for link in links],
            "ops": ops}


class TestTrapsTheContractKeeps:
    """Same-language traps a row passed the contract with on 6ed0396 (scripts/trap_review_reach.py's
    exhaustive search, round 1); each is now kept before the claim locks and the review."""

    @pytest.mark.parametrize(("original", "row", "detail"), [
        # A lock word split across two relabels: 初步 lies in neither "from".
        ("汇报了斑马鱼鳍再生的初步结果。", _row("汇报了斑马鱼鳍再生的实验结果。", [("L1", "t2", "生的实", "生的初"),
                                                                ("L2", "t2", "验结果", "步结果")],
                                    [{"op": "relabel", "link": "L1", "from": "生的初", "to": "生的实"},
                                     {"op": "relabel", "link": "L2", "from": "步结果", "to": "验结果"},
                                     {"op": "tighten"}]), "relabel_line_lock_count"),
        ("Cleaned the sales dataset with fellow interns in Excel.",
         _row("Cleaned the sales data records in Excel.", [("L1", "t2", "sales data", "sales dataset with fellow"),
                                                           ("L2", "t2", "records in Excel", "interns in Excel")],
              [{"op": "relabel", "link": "L1", "from": "sales dataset with fellow", "to": "sales data"},
               {"op": "relabel", "link": "L2", "from": "interns in Excel", "to": "records in Excel"},
               {"op": "tighten"}]), "relabel_line_lock_count"),
        # A limit word outside any relabel: "just" is a function word, so no add/drop check sees it.
        ("Analyzed EEG recordings from 20 participants in a sleep study.",
         _row("Analyzed just EEG data from 20 participants in a sleep study.",
              [("L1", "t2", "EEG data", "Analyzed EEG recordings")],
              [{"op": "relabel", "link": "L1", "from": "Analyzed EEG recordings", "to": "EEG data"},
               {"op": "tighten"}]), "relabel_line_lock_count"),
        # Two numbers swap actions through a lead_with on the moved number.
        ("I improved parser throughput by 45% and reduced parser latency by 12%.",
         _row("I improved parser throughput by 12% and reduced parser latency by 45%.", [("L1", "t1", "12%", "12%")],
              [{"op": "lead_with", "link": "L1"}]), "number_moved"),
        ("Improved parser throughput by 45% and reduced parser latency by 12%.",
         _row("Improved parser throughput by 12% and reduced parser latency by 45%.", [("L1", "t1", "12%", "12%")],
              [{"op": "lead_with", "link": "L1"}]), "number_moved"),
        # Added Chinese read as words: 公司 is a setting.
        ("本人开发了解析器。", _row("本人开发了解析器，已部署到公司生产系统。",
                            [("L1", "t2", "析器，已部署到公司生产系统", "了解析器")],
                            [{"op": "relabel", "link": "L1", "from": "了解析器", "to": "了解析器，已部署到公司生产系统"},
                             {"op": "tighten"}]), "relabel_setting"),
        # 本人 dropped after a clause of shared work, through lead_with instead of personal_first.
        ("与两名同学合作搭建了气象站，本人单独编写了数据采集程序。",
         _row("单独编写了数据采集程序并与两名同学合作搭建了气象站。", [("L1", "t1", "了数据", "了数据")],
              [{"op": "lead_with", "link": "L1"}]), "personal_marker_dropped"),
    ], ids=["初步-split", "fellow-interns-split", "just-outside", "number-swap-I", "number-swap", "公司-setting",
            "本人-after-shared-action"])
    def test_the_trap_is_kept_before_the_review(self, original, row, detail):
        anchors = anchors_for(list(dict.fromkeys([original, row["text"]])))
        unit = em.Unit("b1", original, original)
        outcome = em.check_rewrite(unit, row, anchors, output_language=em.language(original))
        assert (outcome.status, outcome.detail) == ("kept", detail)

    @pytest.mark.parametrize(("original", "rewrite", "ops", "links"), [
        # A number fronted with its own phrase opens its clause: left alone.
        ("Presented a poster on sleep and memory at the 2025 undergraduate symposium.",
         "At the 2025 undergraduate symposium, presented a poster on sleep and memory.",
         [{"op": "lead_with", "link": "L1"}], [("L1", "t2", "2025 undergraduate symposium", "2025 undergraduate symposium")]),
        # A number that keeps its word moves with it.
        ("Cleaned the survey data in R and analyzed 120 EEG recordings in MATLAB.",
         "Analyzed 120 EEG recordings in MATLAB and cleaned the survey data in R.",
         [{"op": "lead_with", "link": "L1"}], [("L1", "t2", "120 EEG recordings", "analyzed 120 EEG recordings")]),
        # One relabel that renames a thing keeps every lock word over the line.
        ("Analyzed about 120 EEG recordings from the pilot study in MATLAB.",
         "Analyzed about 120 EEG data from the pilot study in MATLAB.",
         [{"op": "relabel", "link": "L1", "from": "EEG recordings", "to": "EEG data"}],
         [("L1", "t2", "EEG data", "EEG recordings")]),
    ], ids=["fronted-year", "number-with-its-word", "relabel-keeps-locks"])
    def test_a_faithful_reorder_or_relabel_still_reaches_the_locks(self, original, rewrite, ops, links):
        anchors = anchors_for([original, rewrite])
        unit = em.Unit("b1", original, original)
        outcome = em.check_rewrite(unit, _row(rewrite, links, ops), anchors, output_language="en")
        assert outcome.status == "pending", outcome


class TestLettersTheTokensCannotRead:
    """language() and tokens() read only ASCII letters and CJK ideographs (round-2 review, criterion 3).

    scripts/other_script_probe.py counts the shapes over eight scripts: 8/8, 8/8 and 8/8 reached the
    review before; 0/8 each now.
    """

    SQL = [("L1", "t1", "SQL", "SQL")]

    @pytest.mark.parametrize(("original", "rewrite", "ops", "links"), [
        # A relabel out of the line's own script: its Korean letters are gone.
        ("Python 데이터 파이프라인 구축 및 유지보수 담당", "Python data pipeline 구축 및 유지보수 담당",
         [{"op": "relabel", "link": "L1", "from": "Python 데이터 파이프라인", "to": "Python data pipeline"}],
         [("L1", "t1", "Python data pipeline", "Python 데이터 파이프라인")]),
        # The line's own conjunction written in English.
        ("Python и SQL для обработки данных", "SQL and Python для обработки данных",
         [{"op": "lead_with", "link": "L1"}], SQL),
        # Every letter kept, English glue added.
        ("データ ぶんせき: Python, SQL", "SQL and Python: データ ぶんせき", [{"op": "lead_with", "link": "L1"}], SQL),
        ("Ανάλυση δεδομένων: Python, SQL", "SQL and Python: Ανάλυση δεδομένων", [{"op": "lead_with", "link": "L1"}], SQL),
    ], ids=["hangul-relabel", "cyrillic-conjunction", "kana-glue", "greek-glue"])
    def test_a_rewrite_that_translates_another_scripts_words_is_kept(self, original, rewrite, ops, links):
        anchors = anchors_for(["Experience building a Python data pipeline with SQL is required."])
        unit = em.Unit("b1", original, original)
        outcome = em.check_rewrite(unit, _row(rewrite, links, ops), anchors, output_language=em.language(original))
        assert (outcome.status, outcome.code, outcome.detail) == ("kept", "beyond_allowed_edit", "wrong_language")

    def test_a_relabel_renames_within_the_script_of_its_from(self):
        # without_terms re-checks a line with _check_same_language alone: the relabel itself is refused there.
        original = "Python 데이터 파이프라인 구축 및 유지보수 담당"
        anchors = anchors_for(["Experience building a Python data pipeline is required."])
        unit = em.Unit("b1", original, original)
        links = em.verify_links([{"id": "L1", "anchor": "t1", "term": "Python data pipeline",
                                  "source": "Python 데이터 파이프라인", "relation": "same"}], unit.sources, anchors)
        ops = [{"op": "relabel", "link": "L1", "from": "Python 데이터 파이프라인", "to": "Python data pipeline"}]
        outcome = em._check_same_language(unit, "Python data pipeline 구축 및 유지보수 담당", links, ops)
        assert (outcome.status, outcome.detail) == ("kept", "relabel_cross_language")

    @pytest.mark.parametrize(("original", "rewrite", "ops", "links"), [
        # A reorder in the line's own words.
        ("Python 및 SQL 데이터 정리 담당", "SQL 및 Python 데이터 정리 담당", [{"op": "lead_with", "link": "L1"}],
         [("L1", "t1", "SQL", "SQL")]),
        # An accented Latin letter is no frame of its own: the English line may gain "as" and "a".
        ("Research assistant in the Café Lab, analyzing Python simulation data for CS 225.",
         "Analyzed Python simulation data for CS 225 as a research assistant in the Café Lab.",
         [{"op": "verb_first"}], []),
    ], ids=["hangul-reorder", "accent-in-an-english-line"])
    def test_a_rewrite_in_the_lines_own_words_still_reaches_the_locks(self, original, rewrite, ops, links):
        anchors = anchors_for(["Experience with SQL is required."])
        unit = em.Unit("b1", original, original)
        outcome = em.check_rewrite(unit, _row(rewrite, links, ops), anchors, output_language=em.language(original))
        assert outcome.status == "pending", outcome


    # Round-3 re-measure (criterion 2b): 33fc0db's rules kept these faithful English rewrites as
    # wrong_language. A Greek letter used as a symbol, the micro sign and an accented Latin letter are
    # English words' letters, not another language; the rewrites go on to the locks and the review.
    # Each line holds two English function words of three letters (round 4's default keep).
    @pytest.mark.parametrize(("original", "rewrite", "ops", "links"), [
        ("Research assistant in the Lee Lab, measuring β-amyloid levels in 40 mouse brains for a study.",
         "Measured β-amyloid levels in 40 mouse brains for a study as a research assistant in the Lee Lab.",
         [{"op": "verb_first"}], []),
        ("Research assistant in the Lee Lab, measuring TNF-α levels in 40 mouse brains for a study.",
         "Measured TNF-α levels in 40 mouse brains for a study as a research assistant in the Lee Lab.",
         [{"op": "verb_first"}], []),
        ("Research assistant in the Lee Lab, measuring α and β waves in 40 EEG recordings.",
         "Measured α and β waves in 40 EEG recordings as a research assistant in the Lee Lab.",
         [{"op": "verb_first"}], []),
        # The micro sign, kept, and written as the Greek mu it stands for.
        ("Research assistant in the Lee Lab, imaging 5 \u00b5m sections of 40 mouse brains for a study.",
         "Imaged 5 \u00b5m sections of 40 mouse brains for a study as a research assistant in the Lee Lab.",
         [{"op": "verb_first"}], []),
        ("Research assistant in the Lee Lab, imaging 5 \u00b5m sections of 40 mouse brains for a study.",
         "Imaged 5 \u03bcm sections of 40 mouse brains for a study as a research assistant in the Lee Lab.",
         [{"op": "verb_first"}], []),
        # A relabel to the posting's unaccented term: "résumé" holds a repeated accented letter.
        ("Built a résumé parser in Python for the career center.",
         "Built a resume parser in Python for the career center.",
         [{"op": "relabel", "link": "L1", "from": "résumé parser", "to": "resume parser"}],
         [("L1", "t1", "resume parser", "résumé parser")]),
    ], ids=["beta-amyloid", "tnf-alpha", "alpha-beta-waves", "micro-sign", "micro-as-mu", "accented-relabel"])
    def test_a_greek_symbol_micro_sign_or_accent_is_no_other_language(self, original, rewrite, ops, links):
        anchors = anchors_for(["Experience building a resume parser in Python is required."])
        unit = em.Unit("b1", original, original)
        outcome = em.check_rewrite(unit, _row(rewrite, links, ops), anchors, output_language=em.language(original))
        assert outcome.status == "pending", outcome

    # Round-3 re-measure (criterion 3): tokens() drops first-person markers and personal_markers()
    # counts them in any script, so an English line that already holds Chinese could have its "I"
    # written as 我 or 本人 and reach the review.
    PRONOUN_LINE = "Responsible for writing Python scripts for 数据清洗; I also tested them."

    @pytest.mark.parametrize("rewrite", [
        "Wrote Python scripts for 数据清洗; 我 also tested them.",
        "Wrote Python scripts for 数据清洗; 本人 also tested them.",
        "Wrote Python scripts for 数据清洗; also tested them 我.",
    ])
    def test_an_english_lines_i_written_in_chinese_is_another_language(self, rewrite):
        unit = em.Unit("b1", self.PRONOUN_LINE, self.PRONOUN_LINE)
        outcome = em.check_rewrite(unit, _row(rewrite, [], [{"op": "verb_first"}]), anchors_for(["Python scripts."]),
                                   output_language=em.language(self.PRONOUN_LINE))
        assert (outcome.status, outcome.detail) == ("kept", "wrong_language")

    def test_an_english_line_that_keeps_its_i_still_reaches_the_locks(self):
        unit = em.Unit("b1", self.PRONOUN_LINE, self.PRONOUN_LINE)
        outcome = em.check_rewrite(unit, _row("Wrote Python scripts for 数据清洗; I also tested them.", [],
                                              [{"op": "verb_first"}]), anchors_for(["Python scripts."]),
                                   output_language=em.language(self.PRONOUN_LINE))
        assert outcome.status == "pending", outcome

    @pytest.mark.parametrize(("text", "symbols"), [
        ("β-amyloid, TNF-α, IL-1β and Aβ42", {"β": 3, "α": 1}),
        ("α = 0.05 and 5 \u00b5m", {"α": 1, "μ": 1}),
        ("β淀粉样蛋白", {"β": 1}),
        ("Ανάλυση δεδομένων", {}),
        ("αβ T cells", {}),
    ])
    def test_which_greek_letters_are_symbols(self, text, symbols):
        assert dict(em._greek_symbols(text)) == symbols


class TestSupport:
    """Lines of the same activity the student confirmed may lend their own clauses, word for word."""
    ORIGINAL = "My team built a Python parser; I wrote parser tests."
    SUPPORT = "I ran 12 parser test cases."

    def check(self, text, support=True, ops=("personal_first",), original=None):
        original = original or self.ORIGINAL
        unit = em.Unit("b1", original, original, support=(("b2", self.SUPPORT),) if support else ())
        row = {"unit_id": "b1", "links": [], "decision": "rewrite", "ops": [{"op": op} for op in ops],
               "text": text, "keep_reason": None}
        outcome = em.check_rewrite(unit, row, {}, output_language="en")
        return em.gate(outcome, unit) if outcome.status == "pending" else outcome

    def test_a_confirmed_clause_may_join_an_allowed_move_and_counts_toward_the_length(self):
        # ORIGINAL holds no two English function words of three letters, so round 4's default keep keeps
        # its merge; a line that holds them ("for", "the") is merged as before.
        original = "My team built a Python parser for the lab; I wrote parser tests."
        merged = "I wrote parser tests and ran 12 parser test cases; my team built a Python parser for the lab."
        assert len(merged) > 1.25 * len(original) + 12
        assert self.check(merged, original=original).status == "pending"
        assert self.check(merged, support=False, original=original).detail.startswith("added:")
        assert self.check("I wrote parser tests and ran 12 parser test cases; my team built a Python parser.").detail == (
            "english_unproven")

    def test_a_merge_still_needs_an_allowed_move(self):
        merged = "My team built a Python parser; I wrote parser tests. I ran 12 parser test cases."
        assert (self.check(merged, ops=()).code, self.check(merged, ops=()).detail) == (
            "beyond_allowed_edit", "no_substantive_op")

    @pytest.mark.parametrize("text", [
        "I wrote 12 parser tests; my team built a Python parser.",  # the support's number on the unit's action
        "I wrote parser tests and ran 12 parser test cases; I built a Python parser.",  # the team's work as mine
    ])
    def test_a_fact_moved_between_confirmed_lines_is_rejected(self, text):
        assert self.check(text).code in ("rewrite_rejected", "beyond_allowed_edit")
        assert self.check(text).status == "kept"

    @pytest.mark.parametrize("support", ["Organized 40 interviews with my advisor; I transcribed them.",
                                         "与导师一起组织了 40 场访谈；本人负责转录。"])
    def test_the_locks_read_a_support_line_in_either_language(self, support):
        """The locks read a unit and its support lines as one evidence text. A Chinese support line used
        to make that text Chinese and skip the actor, qualifier, setting, quality and relevance checks
        for an English rewrite."""
        original = "Reviewed the lab's protocol documents. Our team built a sample tracker."
        unit = em.Unit("b1", original, original, support=(("b2", support),), keyed=True)
        outcome = em.gate(em.Outcome("b1", "pending", text="Our team built a sample tracker. Reviewed the lab's "
                                                            "protocol documents."), unit)
        assert (outcome.code, outcome.findings) == ("rewrite_rejected", ["actor_changed"])


def _reply(verdicts):
    return json.dumps({"verdicts": verdicts})


def _link(ident="L1"):
    return em.Link(ident, "same", "PCR", "PCR genotyping", {"field": "requirement", "requirement_index": 0,
                                                            "start": 0, "end": 3, "quote": "PCR"},
                   {"start": 4, "end": 18, "quote": "PCR genotyping"})


class TestReview:
    def test_the_payload_carries_links_only_where_there_are_some(self):
        pairs = [em.ReviewPair("a", "b"), em.ReviewPair("c", "d", (_link(),))]
        assert em.review_payload(pairs) == {"pairs": [
            {"index": 1, "original": "a", "rewrite": "b"},
            {"index": 2, "original": "c", "rewrite": "d", "links": [
                {"id": "L1", "source": "PCR genotyping", "target_term": "PCR", "written_as": None}]}]}

    @pytest.mark.parametrize(("verdict", "accepted"), [
        ({"index": 1, "changes": "[ok]", "faithful": True, "links": [{"id": "L1", "entailed": True}]}, True),
        ({"index": 1, "changes": "[ok]", "faithful": True, "links": [{"id": "L1", "entailed": False}]}, False),
        ({"index": 1, "changes": "[ok]", "faithful": True, "links": []}, False),
        ({"index": 1, "changes": "[ok]", "faithful": True}, False),
        ({"index": 1, "changes": "[ok]", "faithful": True, "links": [{"id": "L1", "entailed": True},
                                                                       {"id": "L2", "entailed": True}]}, False),
        ({"index": 1, "changes": "[ok]", "faithful": "true", "links": [{"id": "L1", "entailed": True}]}, False),
        ({"index": 1, "changes": "moved [2]", "faithful": True, "links": [{"id": "L1", "entailed": True}]}, False),
        ({"index": 1, "changes": "[ok]", "faithful": True, "links": [{"id": ["L1"], "entailed": True}]}, False),
        ({"index": 2, "changes": "[ok]", "faithful": True, "links": [{"id": "L1", "entailed": True}]}, False),
    ])
    def test_a_rewrite_passes_only_when_faithful_and_every_link_entailed(self, monkeypatch, verdict, accepted):
        monkeypatch.setattr(em, "chat_completion", lambda *_a, **_k: _reply([verdict]))
        link = _link()
        assert em.ai_review([em.ReviewPair("o", "r", (link,))]) == ["accepted" if accepted else "rejected"]
        assert link.entailed is accepted

    @pytest.mark.parametrize("raw", ["not json", json.dumps([{"index": 1, "faithful": True}]),
                                     _reply([{"index": 1, "faithful": True, "links": []},
                                             {"index": 1, "faithful": False, "links": []}])])
    def test_malformed_or_conflicting_verdicts_reject(self, monkeypatch, raw):
        monkeypatch.setattr(em, "chat_completion", lambda *_a, **_k: raw)
        assert em.ai_review([em.ReviewPair("o", "r")]) == ["rejected"]

    # Round-3 review (criterion 1): a verdict list applied by index let a verdict written for one
    # pair accept another. Each verdict now has to sit at its pair's place with its pair's number.
    @staticmethod
    def _verdict(index, faithful=True, link=None):
        link = link if link is not None else f"L{index}"
        return {"index": index, "changes": "[ok]" if faithful else "dropped the qualifier", "faithful": faithful,
                "links": [{"id": link, "entailed": True}], "problem": "" if faithful else "qualifier"}

    @pytest.mark.parametrize("verdicts", [
        # Pair 1 skipped, pair 2's verdict numbered 1.
        [("v", 1, True, "L1")],
        # Pair 2's verdict numbered 1, then pair 1's numbered 2: a swap no index tells from misnumbering.
        [("v", 2, True, "L2"), ("v", 1, False, "L1")],
        # Two verdicts for pair 1, none for pair 2.
        [("v", 1, True, "L1"), ("v", 1, True, "L1")],
        # One verdict too many.
        [("v", 1, True, "L1"), ("v", 2, True, "L2"), ("v", 3, True, "L1")],
        # The right length, one entry not an object.
        [("v", 1, True, "L1"), "pair 2 is faithful"],
        # The right length, numbered from 0.
        [("v", 0, True, "L1"), ("v", 1, True, "L2")],
        # The right length, an index written as a string.
        [("v", 1, True, "L1"), ("s", "2", True, "L2")],
    ], ids=["skipped-and-renumbered", "swapped", "duplicate", "extra", "not-an-object", "zero-based", "string-index"])
    def test_a_verdict_list_not_tied_to_its_pairs_rejects_every_pair(self, monkeypatch, verdicts):
        built = [entry if isinstance(entry, str) else self._verdict(*entry[1:]) for entry in verdicts]
        monkeypatch.setattr(em, "chat_completion", lambda *_a, **_k: _reply(built))
        links = (_link("L1"), _link("L2"))
        pairs = [em.ReviewPair("o1", "r1", (links[0],)), em.ReviewPair("o2", "r2", (links[1],))]
        assert em.ai_review(pairs) == ["rejected", "rejected"]
        assert [link.entailed for link in links] == [False, False]

    def test_a_complete_list_in_pair_order_judges_each_pair_on_its_own(self, monkeypatch):
        verdicts = [self._verdict(1, faithful=False), self._verdict(2)]
        monkeypatch.setattr(em, "chat_completion", lambda *_a, **_k: _reply(verdicts))
        links = (_link("L1"), _link("L2"))
        pairs = [em.ReviewPair("o1", "r1", (links[0],)), em.ReviewPair("o2", "r2", (links[1],))]
        assert em.ai_review(pairs) == ["rejected", "accepted"]
        assert [link.entailed for link in links] == [False, True]

    def test_no_answer_is_unavailable_not_rejected(self, monkeypatch):
        monkeypatch.setattr(em, "chat_completion", lambda *_a, **_k: None)
        assert em.ai_review([em.ReviewPair("o", "r")]) is None
        assert asyncio.run(em.review_rewrites([em.ReviewPair("o", "r")], em.time.monotonic())) == ["unavailable"]

    def test_the_review_is_skipped_without_time_and_bounded_by_what_is_left(self, monkeypatch):
        calls = []
        monkeypatch.setattr(em, "chat_completion",
                            lambda *_a, **kwargs: calls.append(kwargs) or _reply([{"index": 1, "faithful": True}]))
        clock = {"now": 1000.0}
        monkeypatch.setattr(em, "time", SimpleNamespace(monotonic=lambda: clock["now"]))
        started = 1000.0 - 52.0
        assert asyncio.run(em.review_rewrites([em.ReviewPair("o", "r")], started)) == ["unavailable"]
        assert calls == []
        started = 1000.0 - 38.0
        assert asyncio.run(em.review_rewrites([em.ReviewPair("o", "r")], started)) == ["accepted"]
        assert calls[0]["deadline"] == pytest.approx(1017.0) and calls[0]["request_timeout"] == 45.0

    def test_a_timeout_is_unavailable(self, monkeypatch):
        async def timeout(*_args, **_kwargs):
            raise BlockingWorkTimeout("slow")

        monkeypatch.setattr(em, "run_blocking", timeout)
        assert asyncio.run(em.review_rewrites([em.ReviewPair("o", "r")], em.time.monotonic())) == ["unavailable"]

    def test_the_review_prompt_keeps_every_calibrated_rule_and_asks_about_links(self):
        for phrase in ("keeps the doer and the share the original gives it", "does not make a finished verb faithful",
                       "even when the rest is a plain trim", "must be a faithful translation",
                       "Tag each change with the rule it breaks", "entailed=true only if",
                       "A pair with any entailed=false is faithful=false"):
            assert phrase in em.REVIEW_SYSTEM_PROMPT, phrase
