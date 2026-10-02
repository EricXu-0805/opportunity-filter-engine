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


class TestSpanWords:
    @pytest.mark.parametrize("quantity", [
        "thirteen", "fourteen", "sixteen", "seventeen", "eighteen", "nineteen", "twice", "double", "triple", "half",
        "several dozen", "many years", "multiple weeks", "numerous times", "several hundred", "many thousands",
        "several millions", "many months", "several days", "many hours", "several semesters", "many terms",
        "several summers", "many decades", "hundreds", "thousand", "millions", "billion", "tens", "dozens",
        "a million", "a billion", "an order of", "a factor of"])
    def test_a_preposition_before_a_quantity_is_a_span_in_a_translation(self, quantity):
        assert em._has(em._FAMILIES["span"], f"Cut the error by up to {quantity} times.")
        assert em._has(em._FAMILIES["span"], f"Made it about {quantity} as fast.")

    @pytest.mark.parametrize("text", [
        "Gave a talk about sleep.", "Studied plants under drought.", "Read over the protocol.",
        "Walked around the campus.", "Read more than the abstract.", "Read less than the full paper.",
        "Covered up to the third chapter.", "Gave a talk about many species of birds.", "Read papers about multiple sclerosis.",
        "Summarized papers about double-blind trials.", "Wrote a review about triple-negative breast cancer."])
    def test_a_relabel_keeps_a_span_word_in_any_use(self, text):
        assert not em._has(em._FAMILIES["span"], text)
        assert any(pattern.search(text) for pattern in em._LOCK_WORD)

    @pytest.mark.parametrize("text", ["最多降低了一个数量级", "至多 3 次", "多达 40 名", "高达 90%", "不到一周"])
    def test_chinese_up_to_and_less_than_are_spans(self, text):
        assert em._has(em._FAMILIES["span"], text)
        assert not em._has(em._FAMILIES["span"], "引用最多的论文")


class TestStatusStillToCome:
    @pytest.mark.parametrize("text", [
        "Will present a poster.", "Upcoming talk at SfN.", "Paper forthcoming.", "Paper to appear in CHI.",
        "Paper in press at Nature.", "Graduation expected in 2027.", "Launch anticipated next spring.", "预计明年毕业",
        "即将发表", "将于 5 月发表", "将在 SfN 上展示", "将会提交", "将要发表"])
    def test_work_still_to_come_is_its_own_family(self, text):
        assert em._has(em._FAMILIES["future"], text)

    @pytest.mark.parametrize("text", ["Currently revising the paper.", "Paper under review.", "目前在修改终稿", "正在撰写论文"])
    def test_work_under_way_is_not_still_to_come(self, text):
        assert not em._has(em._FAMILIES["future"], text)
        assert em._has(em._FAMILIES["unfinished"], text)


class TestMoreListedShapes:
    def test_in_development_is_work_under_way_but_development_of_is_not(self):
        assert em.UNFINISHED.search("Built the backend for a campus dining app in development.")
        assert not em.UNFINISHED.search("Gained experience in development of ML models.")

    @pytest.mark.parametrize("word", ["unpublished", "unsubmitted", "unfinished", "untested", "unverified",
                                      "unvalidated", "unreviewed"])
    def test_an_un_done_word_is_a_negation_and_no_finished_verb(self, word):
        assert em._has(em._FAMILIES["negation"], f"Built a sensor; accuracy {word}.")
        assert not em._finished_clause(f"Sensor under construction; {word} for months.", wide=True)

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

    @pytest.mark.parametrize("text", ["It went live in March.", "It went online in March.", "It has gone live.",
                                      "It has gone online."])
    def test_going_live_is_a_finished_state(self, text):
        assert em._FINISHED_STATE.search(text)

    @pytest.mark.parametrize(("text", "done"), [("实验室网站开发结束", True), ("项目结束后继续维护", False),
                                                ("项目结束前提交报告", False), ("项目结束时提交报告", False)])
    def test_结束_is_done_unless_it_names_a_time(self, text, done):
        assert em._has_done(text, wide=True) is done

    @pytest.mark.parametrize(("text", "span"), [
        ("Surveyed upwards of 200 students.", True), ("Surveyed close to 200 students.", True),
        ("Lives close to the lab.", False), ("调查了上百名学生", True), ("调查了上千名学生", True), ("调查了上万名学生", True),
        ("上百度搜索资料", False)])
    def test_upwards_of_close_to_and_上百_are_spans(self, text, span):
        assert em._has(em._FAMILIES["span"], text) is span

    @pytest.mark.parametrize("text", ["Lives upwards of the river.", "Lives close to the lab."])
    def test_a_relabel_keeps_upwards_of_and_close_to_in_any_use(self, text):
        assert em._SPAN_WORD.search(text)

    def test_协同_is_shared_work(self):
        assert em._has(em._FAMILIES["team"], "与组员协同完成了测试")


class TestBoundsAndApproximations:
    @pytest.mark.parametrize(("text", "token"), [
        ("~300 images", "~300"), ("~ 300 images", "~300"), ("≈300 images", "≈300"), (">90% accuracy", ">90%"),
        ("<50 ms", "<50"), ("≤5 runs", "≤5"), ("≥99% uptime", "≥99%"), ("40+ participants", "40+"),
        ("1,000+ users", "1000+"), ("90%+ accuracy", "90%+"), ("~1,000 users", "~1000")])
    def test_a_number_keeps_its_bound_or_approximation_sign(self, text, token):
        assert em.tokens(text)[0] == token

    @pytest.mark.parametrize("text", [
        "Labeled fewer than 300 images.", "Drew as many as 200 students.", "Lifted as much as 5 kg.",
        "Needed as few as 3 runs.", "Used as little as 2 ml.", "Reached accuracy as high as 95%.",
        "Kept error as low as 1%.", "Interviewed some 30 farmers.", "Reached an estimated 2,000 readers.",
        "Reached estimated 2,000 readers.", "Tested 40 or so samples.", "Waited a week or so.", "Surveyed 200-odd students.",
        "Annotated ~300 images.", "Annotated ≈300 images.", "Cut latency to <50 ms.", "Reached >90% accuracy.",
        "Kept runs ≤5.", "Kept uptime ≥99%.", "Recruited 40+ participants.", "Reached 90%+ accuracy.",
        "检测了近 40 份水样", "检测了近百份水样", "接近 90%", "招募了 40 余名参与者", "十余名学生", "招募了 40 多名参与者",
        "三十多名学生", "准确率达到 90% 以上", "18 岁以下", "3 年以上", "百人以上", "最多 12 名", "每周最多辅导 12 名学生",
        "历时近两年", *(f"近{number}" for number in "一二两三四五六七八九十百千万几半"),
        *(f"{number}{word}" for number in "十百千万" for word in "余多"), "3 小时以上", "100 名以下",
        *(f"{number}人以上" for number in "十百千万"), "Reached an estimated two thousand readers."])
    def test_a_bound_or_an_estimate_is_a_span(self, text):
        assert em._has(em._FAMILIES["span"], text)

    @pytest.mark.parametrize("text", [
        *(f"{verb}不到数据" for verb in "找做想看达得用等买收见听"), "得票最多的人",
        *(f"得票最多{mark}" for mark in ("。", "，", ",", "；", ";", "）", ")", "")), "附近 3 家医院", "最近 3 年",
        "近五年的数据", "近三年来", "近两年内", "近 10 个月间", "近 3 年来的", "近两个月的", "近三周的", "近十天的",
        "近 5 日的", "近两个季度的", "近两学期的", "近期参加了比赛", "靠近校园的实验室", "其余 3 人", "Analyzed some data.",
        "Estimated the cost of the trip.", "Recruited fewer participants than expected."])
    def test_a_verb_a_superlative_or_a_recent_past_is_no_span(self, text):
        assert not em._has(em._FAMILIES["span"], text)

    @pytest.mark.parametrize("text", [
        "Recruited fewer than expected.", "Ran as many as needed.", "Used as much as needed.", "Needed as few as possible.",
        "Spent as little as possible.", "Scored as high as the PI.", "Priced as low as the rest."])
    def test_a_relabel_keeps_a_comparison_word_in_any_use(self, text):
        assert em._SPAN_WORD.search(text) and not em._SPAN.search(text)


class TestFinishedClause:
    @pytest.mark.parametrize(("text", "finished"), [
        ("Tutoring 30 students; graded 40 exams.", True), ("Developing a parser and tested it.", True),
        ("Developing a website; carefully tested the login page.", True), ("Paper accepted at CHI 2026.", True),
        ("Lab website under development; homepage launched.", True), ("Wired 3 sensors.", True),
        ("Developing a dashboard, used by 5 lab members.", False), ("Planned to survey 50 users.", False),
        ("Interested in robotics.", False), ("Dashboard under development; in planned studies.", False),
        ("Developing a website for the lab.", False), ("Developing automated pipelines for the lab.", False),
        ("Developing a parser but tested it.", True), ("Developing a parser then tested it.", True),
        ("Developing a parser; also tested it.", True), ("Developing a parser; later tested it.", True),
        ("Developing a parser, which I tested.", True), ("Developing a parser; that we tested.", True),
        ("Mentoring students, who tested the app.", True), ("Developing a parser; we tested it.", True),
        ("Developing a parser; have tested it.", True), ("Developing a parser; has tested it.", True),
        ("Developing a parser; had tested it.", True), ("Developing a parser; later we tested it.", True),
        ("Developing a parser; we have tested it.", True), ("Developing a dashboard; need more data.", False)])
    def test_a_clause_opens_with_a_finished_verb(self, text, finished):
        assert em._finished_clause(text) is finished

    @pytest.mark.parametrize("word", ["expected", "anticipated", "planned", "proposed", "scheduled", "intended",
                                      "unfinished", "unpublished", "unsubmitted"])
    def test_a_status_word_is_no_finished_headline_or_verb(self, word):
        for wide in (False, True):
            assert not em._finished_clause(f"Lab site under development; completion {word} next month.", wide=wide)
            # A known verb opening a clause is read as before: "Planned the outreach event" is finished.
            opening = em._finished_clause(f"Lab site under development; {word} next month.", wide=wide)
            assert opening is bool(em.verb_use(word))

    @pytest.mark.parametrize("word", ["delayed", "postponed", "requested", "needed", "mailed"])
    def test_a_headline_licenses_a_done_mark_only_with_a_known_verb(self, word):
        text = f"Lab site under development; completion {word} next month."
        assert not em._finished_clause(text)
        assert em._finished_clause(text, wide=True)

    @pytest.mark.parametrize("word", ["approved", "archived", "awarded", "funded", "granted", "posted", "released"])
    def test_a_listed_finished_event_is_a_headline(self, word):
        assert em._finished_clause(f"Paper under review; preprint {word} on arXiv.")


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
    def test_other_collaborators_are_a_team(self, text):
        assert em._TEAM_OTHERS.search(text)
        assert em._has(em._FAMILIES["team"], text)

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

    @pytest.mark.parametrize(("chinese", "shares"), [
        ("参与了数据分析", True), ("为项目贡献了代码", True), ("招募了 40 名参与者", False), ("参加了 iGEM 比赛", False),
        ("为参与者准备了问卷", False),
        ("开展一项有 50 名被试参与的实验", False), ("两位同学参与了测试", False), ("组织了一场有五十名学生参与的比赛", False)])
    def test_a_chinese_share_of_the_work_is_taken_by_the_student(self, chinese, shares):
        assert em._shares_work(chinese) is shares
        assert em._PARTICIPATION_ZH.search(chinese) or not shares

    def test_participants_are_people_not_a_share(self):
        assert not em._PARTICIPATION_EN.search("Recruited 40 participants.")


class TestDoneMarks:
    @pytest.mark.parametrize("text", [
        "开发过网站", "曾为实验室开发网站", "开发出网站", "网站开发完毕", "建成网站", "网站上线", "网站投入使用", "网站交付",
        "开发好网站", "写完论文", "论文定稿", "大楼竣工", "工程完工", "新馆落成", "测试成功", "整理成表格", "做好网站",
        "搭好装置", "造出原型", "编好程序", "画完图纸", "拍完视频", "跑完实验", "修好设备", "装好系统"])
    def test_only_the_refusing_rules_read_the_wider_done_marks(self, text):
        assert em._has_done(text, wide=True)
        assert not em._has_done(text)

    @pytest.mark.parametrize("text", [
        *(f"{word}过网站" for word in "经通不超难错跳越太"), *(f"数据过{word}" for word in "程滤去度敏期量渡于多少来年往半夜节"),
        *(f"曾{word}指导" for word in "老教博同先女医总"), *(f"开发出{word}" for word in "版现席差发口生门国境台租"),
        *(f"开发成{word}" for word in "员果绩本像为立熟长分型"), *(f"开发好{word}" for word in "的奇评友处感转像"),
        *(f"开发完{word}" for word in "善整全美备"), "网站上线前", "能分析出基因", "可以写完论文",
        *(f"{word}上线" for word in ("预计", "即将", "将于", "将在", "将会", "将要", "计划", "打算", "准备", "拟", "希望",
                                     "尚未", "没", "待"))])
    def test_a_word_that_only_looks_like_a_done_mark_states_nothing_done(self, text):
        assert not em._has_done(text, wide=True)

    @pytest.mark.parametrize("text", [
        *(f"The site {aux} complete." for aux in ("is", "are", "was", "were", "has been", "have been", "had been",
                                                  "now", "already")),
        *(f"The site is {state}." for state in ("complete", "completed", "finished", "done", "live", "online",
                                                "launched", "deployed", "published", "released", "in use",
                                                "operational")),
        *(f"The site is {adverb} complete." for adverb in ("now", "already", "fully", "successfully"))])
    def test_a_finished_state_is_read_for_the_rule_it_triggers(self, text):
        assert em._FINISHED_STATE.search(text)

    @pytest.mark.parametrize("text", ["The site is not yet complete.", "Built an online course.", "Paper is under review.",
                                      "A live dashboard."])
    def test_a_state_still_to_come_is_no_finished_state(self, text):
        assert not em._FINISHED_STATE.search(text)


class TestUnknownVerbs:
    @pytest.mark.parametrize("word", ["fine-tuning", "scraping", "wiring", "filming", "proofreading", "pipetting",
                                      "cloning", "parsing", "porting", "rendering", "animating", "coaching",
                                      "profiling", "crawling", "developing"])
    def test_an_ing_word_is_a_verb_form_whether_or_not_the_list_knows_it(self, word):
        assert grounding.ing_form(word)
        assert em._progressive_led(f"{word.capitalize()} a model for the lab.")

    @pytest.mark.parametrize("word", [
        "during", "morning", "evening", "spring", "string", "nothing", "something", "anything", "everything",
        "ceiling", "sibling", "having", "upcoming", "ongoing", "incoming", "outgoing", "following", "including",
        "according", "regarding", "concerning", "considering", "pending", "notwithstanding", "existing",
        "remaining", "accounting", "nursing", "banking", "housing", "funding", "clothing", "catering", "wedding",
        "opening", "offering", "thing", "being"])
    def test_a_noun_or_preposition_in_ing_leads_no_progressive_line(self, word):
        assert not grounding.ing_form(word)
        assert not em._progressive_led(f"{word.capitalize()} shift at the food bank; sorted 500 cans.")

    @pytest.mark.parametrize("word", ["Using", "Applying", "Leveraging", "Utilizing", "Utilising", "Employing"])
    def test_a_method_leads_no_progressive_line(self, word):
        assert not em._progressive_led(f"{word} R, cleaned 212 survey responses.")


class TestLeadingClause:
    @pytest.mark.parametrize(("chinese", "leading"), [
        ("目前，开发了网站；撰写了综述。", "开发了网站"), ("目前:开发了网站", "开发了网站"),
        ("本人目前：开发了网站", "开发了网站"), ("我目前,开发了网站", "开发了网站"),
        ("项目进行中，为实验室开发了网站", "为实验室开发了网站"), ("目前正在开发中，开发了网站", "开发了网站"),
        ("正在为实验室开发网站，撰写了综述", "正在为实验室开发网站"), ("系统开发中；负责后端", "负责后端"),
        ("目前在实验室，开发了网站", "目前在实验室"), ("目前", "")])
    def test_the_leading_verb_is_in_the_first_clause_that_is_more_than_a_lead_marker(self, chinese, leading):
        assert em._leading_clause(chinese) == leading

    @pytest.mark.parametrize("chinese", ["预约系统（开发中），撰写了文档", "预约系统(开发中)，撰写了文档"])
    def test_a_bracketed_verb_and_中_marks_the_work_not_the_verb(self, chinese):
        assert em._leading_clause(chinese) == "撰写了文档"
        assert em._lead_spans(chinese)

    @pytest.mark.parametrize("prefix", ["本人", "我们", "我", "本学期", "这学期", "今年", "今年暑假", "今年寒假", "今年夏天",
                                        "暑假", "暑假期间", "寒假", "寒假期间", "最近", "近期", "目前", "现在", "现", "也",
                                        "目前我", "本学期我们"])
    def test_a_subject_or_a_time_word_may_stand_before_正在(self, prefix):
        assert em._lead_spans(f"{prefix}正在开发网站") == [(0, len(prefix) + 2)]

    @pytest.mark.parametrize("chinese", ["为实验室正在开发网站", "网站正在开发", "上学期开发了网站"])
    def test_other_words_before_正在_make_no_lead(self, chinese):
        assert em._lead_spans(chinese) == []

    @pytest.mark.parametrize(("chinese", "parts"), [
        ("开发了网站并撰写了一篇综述", 2), ("开发了网站、撰写了综述", 2), ("开发了网站，撰写了综述", 2),
        ("开发了网站；已撰写综述", 2), ("设计并测试了登录页面", 1), ("已撰写了一篇综述", 1), ("正在开发网站", 0)])
    def test_each_part_with_its_own_done_mark_counts_once(self, chinese, parts):
        assert em._done_parts(chinese) == parts


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


class TestDraft:
    @pytest.mark.parametrize("text", [
        "Draft weekly newsletters.", "Write and draft memos.", "Edit or draft memos.", "I draft memos.",
        "We draft memos.", "Will draft memos.", "Help draft memos.", "Helps draft memos.", "Helped draft memos.",
        "Helping draft memos.", "Also draft memos.", "Currently draft memos.", "Volunteered to draft memos.",
        "Edited memos; draft agendas."])
    def test_the_verb_draft_is_no_status(self, text):
        assert not em._DRAFT.search(text)

    @pytest.mark.parametrize("text", ["Wrote a draft manuscript.", "Wrote draft manuscripts.", "Wrote two drafts.",
                                      "Methods section (draft).", "Wrote a first-draft outline.", "撰写了论文初稿。"])
    def test_a_draft_thing_is_a_status(self, text):
        assert em._DRAFT.search(text)


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
        outcome = em.check_rewrite(unit, row, anchors,
                                   output_language=case.get("output") or em.language(case["original"]))
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
        unit = em.Unit("b1", "Wrote parser tests using Python.", "Wrote parser tests using Python.")
        keep = {"unit_id": "b1", "decision": "keep"}
        assert em.check_rewrite(unit, keep, anchors, output_language="en").code == "no_link"
        rewrite = {"unit_id": "b1", "decision": "rewrite", "ops": [{"op": "lead_with", "link": "L1"}],
                   "links": [{"id": "L1", "anchor": "t1", "term": "Python", "source": "Python", "relation": "same"}],
                   "text": "Using Python, wrote parser tests."}
        assert em.check_rewrite(unit, rewrite, anchors, output_language="en").status == "pending"

    def test_an_unchanged_rewrite_is_a_keep(self):
        # A model that "translates" a line already in the output language returns it as written.
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

    def test_a_declared_relabel_is_read_back_for_object_and_quantity_only(self):
        original = "Built a PyTorch image classifier for chest X-ray triage."
        model = "Built a PyTorch computer vision model for chest X-ray triage."
        assert "object_changed" in em.rewrite_findings(model, original, [])
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


class TestSupport:
    """Lines of the same activity the student confirmed may lend their own clauses, word for word."""
    ORIGINAL = "My team built a Python parser; I wrote parser tests."
    SUPPORT = "I ran 12 parser test cases."

    def check(self, text, support=True, ops=("personal_first",)):
        unit = em.Unit("b1", self.ORIGINAL, self.ORIGINAL, support=(("b2", self.SUPPORT),) if support else ())
        row = {"unit_id": "b1", "links": [], "decision": "rewrite", "ops": [{"op": op} for op in ops],
               "text": text, "keep_reason": None}
        outcome = em.check_rewrite(unit, row, {}, output_language="en")
        return em.gate(outcome, unit) if outcome.status == "pending" else outcome

    def test_a_confirmed_clause_may_join_an_allowed_move_and_counts_toward_the_length(self):
        merged = "I wrote parser tests and ran 12 parser test cases; my team built a Python parser."
        assert len(merged) > 1.25 * len(self.ORIGINAL) + 12
        assert self.check(merged).status == "pending"
        assert self.check(merged, support=False).detail.startswith("added:")

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
