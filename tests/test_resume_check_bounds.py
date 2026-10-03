"""Work bound of the résumé and email claim checks.

* Ordinary English and Chinese evidence decides as recorded and stays far below
  the work limit.
* Large inputs decide as recorded within a time budget.
* A check past the work limit fails closed and stops early: it reports the size
  finding, so the caller keeps the original wording.
* The helpers that replaced a single pattern or a loop agree with the reference
  forms on generated input.
"""

from __future__ import annotations

import itertools
import random
import re
import time

import pytest

from backend.lib import email_experience_attribution as ea
from backend.lib import target_resume_ai_grounding as grounding

SIZE_FINDING = "unsupported experience attribution: input exceeds the supported size"
EMAIL = "I built a parser for the lab. I tested the model with PyTorch."
ENGLISH_ENTRY = "I built a parser for the lab.\nI tested the model with PyTorch."
BOTH_UNSUPPORTED = ["unsupported experience attribution: personal build",
                    "unsupported experience attribution: personal test"]
BUDGET_SECONDS = 2.0


@pytest.fixture
def work_spent(monkeypatch):
    """The most work any single check spent while the test ran."""
    meters: list = []

    class Meter(ea._Work):
        def __init__(self) -> None:
            super().__init__()
            meters.append(self)

    monkeypatch.setattr(ea, "_Work", Meter)
    return lambda: max((ea._WORK_LIMIT - meter.left for meter in meters), default=0)


def test_work_past_the_limit_raises():
    work = ea._Work()
    work.spend(ea._WORK_LIMIT)
    with pytest.raises(ea._OverLimit):
        work.spend(1)


# --------------------------------------------------------------------------- #
# Ordinary English evidence.
# --------------------------------------------------------------------------- #
BULLETS = [
    "Developed a Python data pipeline to process 2 TB of sensor logs, reducing processing time by 35%.",
    "Built a React dashboard for lab members and deployed it on AWS using Docker.",
    "Implemented a convolutional neural network in PyTorch and trained it on 50,000 labeled images.",
    "Designed and tested a REST API in Flask serving 1,200 daily users.",
    "Led a team of 4 students to build a mobile app for campus dining.",
    "Analyzed 10 years of climate data with pandas and presented findings to the research group.",
    "Collected and processed survey responses from 300 participants for a psychology study.",
    "Maintained the lab's GitHub repositories and wrote documentation for new members.",
    "Debugged memory leaks in a C++ simulation engine, improving runtime stability.",
    "Created automated unit tests with pytest, increasing code coverage from 40% to 85%.",
    "Evaluated three transformer models on a sentiment classification benchmark.",
    "Measured signal latency across 12 FPGA boards and reported results weekly.",
    "Wrote a literature review on graph neural networks for drug discovery.",
    "Trained 15 new volunteers and managed weekly schedules for the tutoring center.",
    "Built an ETL workflow in Airflow that processed 5 million records daily.",
    "Designed PCB layouts in KiCad and tested the boards in the lab.",
    "Implemented a Raft consensus protocol in Go for a distributed systems course.",
    "Analyzed fMRI scans of 40 subjects using FSL and wrote analysis scripts in Python.",
    "Wrote Verilog modules for a 5-stage pipelined RISC-V processor and debugged hazards.",
    "Designed an experiment with 120 participants and analyzed the results in R.",
]
PLACES = ["", "", " at Alpha Lab", " in 2024", " at Beta Research Group in 2023", " during Fall 2024"]
ORDINARY_EMAIL = ("Dear Dr. Lee,\n\n" + " ".join("I " + bullet[0].lower() + bullet[1:] for bullet in BULLETS[:12])
                  + "\n\nBest regards,\nSam")


def _ordinary_entries() -> list[str]:
    """100 entries of ordinary bullets, about 600 characters each."""
    texts, index = [], 0
    for _ in range(100):
        lines: list[str] = []
        while sum(len(line) + 1 for line in lines) < 560:
            bullet, place = BULLETS[index % len(BULLETS)], PLACES[index % len(PLACES)]
            lines.append(bullet[:-1] + place + "." if place else bullet)
            index += 1
        texts.append("\n".join(lines)[:600])
    return texts


def _ordinary_materials(texts: list[str], organizations=("Alpha Lab", "Beta Research Group", "Gamma Institute"),
                        title: str = "Research Assistant") -> list[dict]:
    materials = []
    for index, text in enumerate(texts):
        context = None
        if index % 2 == 0:
            context = {"master_id": "m1", "master_revision": 1, "section": "activities", "id": f"a{index % 12}",
                       "fields": {"organization": {"value": organizations[index % 3]}, "title": {"value": title},
                                  "start": {"value": "Jan 2023"}, "end": {"value": "May 2024"}}}
        materials.append({"id": f"e{index}", "revision": 1, "excerpt": text, "context": context})
    return materials


def test_ordinary_evidence_decides_as_recorded_and_stays_below_the_limit(work_spent):
    texts = _ordinary_entries()
    assert len(texts) == 100
    assert ea.experience_attribution_violations(ORDINARY_EMAIL, texts) == []
    materials = _ordinary_materials(texts)
    assert ea.experience_attribution_violations(ORDINARY_EMAIL, texts, activity_materials=materials) == [
        "unsupported experience attribution: personal analyze",
        "unsupported experience attribution: personal build",
        "unsupported experience attribution: personal implement",
        "unsupported experience attribution: personal lead",
        "unsupported experience attribution: personal measure",
    ]
    assert ea.unsupported_experience_claims(ORDINARY_EMAIL, texts, activity_materials=materials) == [
        "I built a React dashboard for lab members",
        "I implemented a convolutional neural network in PyTorch",
        "I led a team of 4 students to build a mobile app for campus dining",
        "I analyzed 10 years of climate data with pandas and presented findings to the research group",
        "I measured signal latency across 12 FPGA boards and reported results weekly",
    ]
    assert work_spent() < ea._WORK_LIMIT // 10


def test_long_draft_against_repetitive_evidence_stays_below_the_limit(work_spent):
    objects = ["Python scripts for data cleaning", "Python tools for lab automation", "Python dashboards for the team"]
    texts = ["\n".join(f"Developed {objects[(entry + line) % 3]} in week {entry * 10 + line}." for line in range(10))
             for entry in range(100)]
    draft = " ".join(f"I developed {objects[index % 3]}." for index in range(60))
    assert ea.experience_attribution_violations(draft, texts) == []
    assert ea.experience_attribution_violations(draft, texts, activity_materials=_ordinary_materials(texts)) == [
        "unsupported experience attribution: personal develop"]
    assert work_spent() < ea._WORK_LIMIT // 10


# --------------------------------------------------------------------------- #
# Ordinary Chinese evidence: résumé prose with English tool names, one
# paragraph per entry.
# --------------------------------------------------------------------------- #
ZH_SENTENCES = [
    "在自然语言处理实验室担任研究助理，参与基于 Transformer 的中文文本分类项目。",
    "使用 Python 和 PyTorch 实现了 BERT 微调流程，在三个公开数据集上将准确率从 86.2% 提升到 91.5%。",
    "负责数据清洗与标注规范的制定，带领 3 名本科生完成了 2 万条样本的人工标注。",
    "搭建了基于 Docker 的实验环境，并编写自动化测试脚本，使模型训练时间缩短约 30%。",
    "设计并开发了实验室内部使用的数据看板，前端使用 React，后端基于 Flask 提供 REST API 接口。",
    "利用 fMRI 数据分析被试在工作记忆任务中的脑区激活模式，使用 SPM 和 MATLAB 完成预处理与统计分析。",
    "参与开发 AI 辅助诊断系统，与产品经理和设计师沟通需求，完成 15 个页面的 UI 原型。",
    "在实习期间维护公司的 CI/CD 流水线，优化 Jenkins 构建脚本，将平均构建时间从 12 分钟降至 7 分钟。",
    "使用 SQL 和 Python 对用户行为数据进行分析，搭建 BI 报表，为运营团队提供每周数据支持。",
    "将训练好的模型封装为 API 服务并部署到 AWS，日均处理约 5000 次请求。",
    "参与 AI 伦理课题的问卷设计与访谈，共收集有效问卷 312 份，并用 R 语言完成描述性统计。",
    "负责前端 GUI 的重构，把原有的 jQuery 代码迁移到 Vue 3，页面加载速度提升了一倍。",
    "编写了 Linux 下的数据采集脚本，从 12 台传感器节点定时收集温湿度数据并写入 MySQL 数据库。",
    "与导师合作撰写论文一篇，已投稿至 ACL 2024，目前处于审稿阶段。",
    "在暑期科研项目中研究了脑机接口中的 EEG 信号降噪方法，比较了 ICA 与小波变换的效果。",
    "使用 Selenium 编写 UI 自动化测试用例 80 余条，覆盖核心业务流程。",
]
ZH_ENTRIES = ["".join(ZH_SENTENCES[(entry + index) % len(ZH_SENTENCES)] for index in range(120))
              for entry in range(10)]


def test_chinese_evidence_decides_as_recorded_and_stays_below_the_limit(work_spent):
    texts = [ENGLISH_ENTRY, *ZH_ENTRIES]
    assert ea.experience_attribution_violations(EMAIL, texts) == []
    materials = _ordinary_materials(texts, organizations=("Alpha Lab", "清华大学", "Gamma Institute"), title="研究助理")
    assert ea.experience_attribution_violations(EMAIL, texts, activity_materials=materials) == []
    assert ea.unsupported_experience_claims("I built a parser for the lab. I designed the GUI.", texts) == [
        "I designed the GUI"]
    original, reordered = ZH_ENTRIES[0], ZH_ENTRIES[1]
    assert grounding.claim_upgrade_detected(reordered, original) is False
    assert grounding.claim_upgrade_detected("Built a Docker-based experiment environment.", original) is True
    assert grounding.supported_claim_upgrade_detected(ZH_ENTRIES[2], ZH_ENTRIES[:2]) is False
    assert work_spent() < ea._WORK_LIMIT // 100


def test_a_subject_with_no_action_after_it_is_not_counted(work_spent):
    # The "I" of "AI" reads as a subject; no action follows it.
    assert ea.experience_attribution_violations(EMAIL, ["AI，" * 1500]) == BOTH_UNSUPPORTED
    assert work_spent() == 0


# --------------------------------------------------------------------------- #
# Large inputs.
# --------------------------------------------------------------------------- #
def _name(number: int) -> str:
    """A distinct capitalised word without digits."""
    letters = ""
    number += 1
    while number:
        number, rest = divmod(number - 1, 26)
        letters = chr(97 + rest) + letters
    return "Q" + letters


def _materials(texts: list[str], context: dict | None = None) -> list[dict]:
    return [{"id": f"e{index}", "revision": 1, "excerpt": text, "context": context} for index, text in enumerate(texts)]


_NAMED = [" ".join(f"I built a parser at {_name(entry * 25 + line)}." for line in range(25)) for entry in range(32)]

LARGE_INPUTS = {
    "long-blank-run-bullet": (lambda: grounding.claim_upgrade_detected(
        "Built a website.", "Built a" + " " * 2400 + "website for the lab and tested it."), False),
    "long-no-break-run-bullet": (lambda: grounding.claim_upgrade_detected(
        "Built a website.", "Built a" + "\u00a0" * 2400 + "website for the lab and tested it."), False),
    "long-blank-run-evidence": (lambda: ea.experience_attribution_violations(
        EMAIL, ["I built a" + " " * 2400 + "parser for the lab.\nI tested the model with PyTorch."]), []),
    "repeated-settings": (lambda: ea.experience_attribution_violations(
        EMAIL, ["in a " * 16 + ", zzz I built a parser."]), BOTH_UNSUPPORTED),
    "repeated-settings-bullet": (lambda: grounding.claim_upgrade_detected(
        "Built a parser.", "in a " * 16 + ", zzz I built a parser."), True),
    "many-admitted-names": (lambda: ea.experience_attribution_violations(
        EMAIL, _NAMED, activity_materials=_materials(_NAMED)), BOTH_UNSUPPORTED),
}


@pytest.mark.parametrize("shape", LARGE_INPUTS)
def test_large_inputs_decide_as_recorded_within_budget(shape):
    check, expected = LARGE_INPUTS[shape]
    started = time.perf_counter()
    assert check() == expected
    assert time.perf_counter() - started < BUDGET_SECONDS


_LAB = {"master_id": "m", "master_revision": 1, "section": "activities", "id": "a1",
        "fields": {"organization": {"value": "Alpha Lab"}}}
_TAILS = ["I built a parser at Alpha Lab " + "in lab " * 400 for _ in range(4)]
_SUBJECTS = ["z " + "I built a " * 300 for _ in range(6)]
_ZH_ACTIONS = ["测试" + "API build，" * 300 for _ in range(6)]
_FACTS = [" ".join(f"I built parser for lab {_name(entry * 1000 + line)}." for line in range(60)) for entry in range(4)]
_CLAIMS = " ".join(f"I built parser for lab {_name(50000 + line)}." for line in range(240))

PAST_THE_LIMIT = {
    "nested-context-tails": lambda: ea.experience_attribution_violations(
        "I built a parser at Alpha Lab.", _TAILS, activity_materials=_materials(_TAILS, _LAB)),
    "repeated-subjects": lambda: ea.experience_attribution_violations(EMAIL, _SUBJECTS),
    "repeated-subjects-in-chinese-text": lambda: ea.experience_attribution_violations(EMAIL, _ZH_ACTIONS),
    "many-claims-and-facts": lambda: ea.experience_attribution_violations(_CLAIMS, _FACTS),
}


@pytest.mark.parametrize("shape", PAST_THE_LIMIT)
def test_check_past_the_work_limit_fails_closed_early(shape):
    started = time.perf_counter()
    assert PAST_THE_LIMIT[shape]() == [SIZE_FINDING]
    assert time.perf_counter() - started < BUDGET_SECONDS


def test_size_finding_is_not_handed_to_the_reviser_and_keeps_the_original():
    assert ea.experience_attribution_violations(EMAIL, _SUBJECTS) == [SIZE_FINDING]
    assert ea.unsupported_experience_claims(EMAIL, _SUBJECTS) == []
    assert ea.experience_attribution_violations(_CLAIMS, [" ".join(_FACTS)], allow_subjectless_claims=True) == [
        SIZE_FINDING]
    assert grounding.claim_upgrade_detected(_CLAIMS, " ".join(_FACTS)) is True


def test_text_without_a_claim_is_not_compared(work_spent):
    assert ea.experience_attribution_violations("Thank you for your time.", _SUBJECTS) == []
    assert work_spent() == 0


def test_clause_ceiling_fails_closed():
    many = " ".join(f"Tested case {_name(index)}." for index in range(450))
    assert grounding.claim_upgrade_detected(many + " Extra.", many) is True
    assert grounding.claim_upgrade_detected("Built a parser.", "Built a parser for the lab.") is False


# --------------------------------------------------------------------------- #
# Equivalence with the reference forms.
# --------------------------------------------------------------------------- #
_SETTINGS_REFERENCE = re.compile(
    r'(?:(?:at|in|for|on|during|within|through|while|with|as\s+part\s+of|as\s+a\s+member\s+of)\s+[^,]+,?\s*)+', re.I)
_SUFFIX_REFERENCE = re.compile(r"\s+(?:at|in|for|on|during)\s+([^,;.!?]+)[.!?]*$", re.I)


def _strings(tokens: list[str], longest: int):
    for size in range(longest + 1):
        for parts in itertools.product(tokens, repeat=size):
            yield "".join(parts)


def test_settings_prefix_matches_the_reference_pattern():
    tokens = ["in ", "As part of ", "with", "x", ",", " ", "\t"]
    for text in _strings(tokens, 6):
        assert ea._context_prefix(text) == bool(_SETTINGS_REFERENCE.fullmatch(text)), text


def test_activity_suffix_matches_the_reference_pattern():
    # No token opens with a preposition or ends with a colon, so the suffix is
    # the only reference these strings can hold.
    tokens = [" at ", " in ", "Alpha", "lab", "2024", ",", ";", ".", "!", "1.5", "\n"]
    for text in _strings(tokens, 5):
        reference = _SUFFIX_REFERENCE.search(text)
        expected = [reference[1].strip()] if reference else []
        expected = [value for value in expected if value[:1].isupper() or re.search(r"\blab\b", value, re.I)
                    or re.fullmatch(r"(?:19|20)\d{2}", value)]
        assert ea._explicit_activity_references(text) == expected, text


def test_care_qualifier_matches_the_reference_pattern():
    tokens = ["not ", "only ", "x ", "carefully", "1.5", ".", ";", " ", "\n"]
    for text in _strings(tokens, 5):
        reference, found = ea._CARE_QUALIFIER.search(text), ea._care_qualifier(text)
        assert (reference and (reference.span(), reference[1])) == (found and (found.span(), found[1])), text


def test_token_run_containment_matches_the_reference_loop():
    for haystack in _strings(["a", "b", "ab"], 4):
        for needle in _strings(["a", "b", "ab"], 2):
            h, n = tuple(haystack), tuple(needle)
            reference = bool(n) and any(h[i:i + len(n)] == n for i in range(len(h) - len(n) + 1))
            assert ea._contains(h, n) == reference


def _reference_remove(text: str, names) -> str:
    for name in sorted(names, key=len, reverse=True):
        text = re.sub(r"(?<!\w)" + re.escape(name) + r"(?!\w)", " ", text)
    return text


def _reference_without_suffix(text: str, names) -> str:
    for match in re.finditer(r"\s+(?:in|for|on|during|at|from|since)\s+", text, re.I):
        remainder = _reference_remove(" ".join(text[match.end():].strip(" ,.!?").casefold().split()), names)
        if not re.sub(r"\b(?:in|for|on|during|at|from|to|since|until|the|and)\b|[,–—-]", " ", remainder).strip():
            return text[:match.start()]
    return text


def test_admitted_name_lookups_match_the_reference_loops():
    names = ["alpha", "lab", "alpha lab", "beta lab", "2024", "the alpha lab", "-", "(x)", "x-", "-y", "lab-",
             "a", "alpha-lab", "dr. smith", "c++", "ab_c", "é", "lab lab"]
    words = ["alpha", "Lab", "lab", "beta", "2024", "the", "and", "in", "at", "for", "from", "-", "(x)", "x-",
             "-y", ",", "–", ".", "x", "dr.", "smith", "c++", "ab_c", "é"]
    rng = random.Random(20261002)
    for _ in range(3000):
        chosen = rng.sample(names, rng.randint(0, 7))
        aliases = ea._Aliases({name: {("$experience", "e0", "1")} for name in chosen})
        aliases.names = ea._Names(aliases, ea._Work())
        text = " ".join(rng.choice(words) for _ in range(rng.randint(0, 9)))
        folded = " ".join(text.casefold().split())
        assert ea._remove_names(folded, aliases.names) == _reference_remove(folded, chosen), (chosen, text)
        assert ea._without_activity_suffix("x " + text, aliases) == _reference_without_suffix("x " + text, chosen)
        assert ea._only_known_context(text, aliases) == (
            _reference_without_suffix("fact " + text, chosen) == "fact"), (chosen, text)
