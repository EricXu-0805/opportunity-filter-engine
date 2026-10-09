"""Longest event-loop stall while the contract and the claim locks read adversarial lines at the cap.

The contract (check_rewrite), the claim locks (gate) and the posting-free alternative
(without_terms) run on a worker thread, but a regex holds the GIL for its whole call, so
one long call stalls the event loop however the call is scheduled. This script runs
those checks, on a worker thread, over lines filled to the 6,000-character cap with
adversarial units (runs of one character, alternating scripts, short clauses, brackets,
lock words, whitespace) while the main thread's event loop wakes every millisecond, and
prints the longest wake-up delay per shape and overall.

Run from the repository root:  python scripts/rewrite_check_lag.py [--threshold 0.25] [--only SUBSTRING]
Deterministic inputs; timings vary with machine load, so a shape over the threshold is
re-run alone (up to three times) and reported with its best run.
"""
from __future__ import annotations

import argparse
import asyncio
import sys
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))

from backend.lib import evidence_map as em  # noqa: E402

CAP = em.MAX_TEXT_CHARACTERS
BULLET = 500

CHARS = [" ", "a", "A", "1", "中", "我", "了", "的", "为", "在", "-", ".", ",", ";", ":", "(", ")", "[", "（", "，",
         "。", "、", "；", "'", "’", "\n", "\t", "\u3000", "\u00a0", "\u200b", "~", "+", "%", "/", "_", "&", "\"", "“"]
MIXED = ["a中", "中a", "a 中 ", "1中", "中1", "a1", "1a", "a-", "a.", "a,", "a, ", "a; ", "a. ", "A. ", "a，", "a。",
         "a、", "I ", "I, ", "my ", "a我", "我a", "本人", "a本人", "1 ", "1.", "1,", "1, ", "2024 ", "40% ", "~3 ", ">3 ",
         "3+ ", "3余", "(a) ", "((", "))", "([", "a (b) ", "“a” ", "\"a\" ", "a\n", "a\r\n", " \t\n", "a \u00a0",
         "a\u3000", "Dr. ", "e.g. ", "a.b ", "x, a b, ", "a-b-", "a’s ", "n't "]
WORDS_EN = ["not ", "never ", "no ", "did not ", "didn't ", "without ", "helped ", "assisted ", "team ", "with my team ",
            "our team ", "teammates ", "we ", "with ", "and ", "or ", "but ", "by ", "of ", "the ", "as ", "an ",
            "about ", "over ", "under ", "since ", "until ", "per ", "only ", "just ", "alone ", "submitted ",
            "accepted ", "published ", "preprint ", "under review ", "in preparation ", "planned ", "will ",
            "hoping to ", "plan to ", "currently ", "ongoing ", "led ", "lead ", "leading ", "built ", "building ",
            "developed ", "developing ", "responsible for ", "in charge of ", "worked on ", "served as ",
            "co-authored ", "revised ", "edited ", "revised by ", "advisor ", "Sam revised ", "my part was ",
            "I designed ", "research group ", "lab ", "project ", "applying ", "relevant ", "robust ", "novel ",
            "proficient ", "experience ", "aing or bing ", "helped aing or bing ", "and building ", "or testing ",
            "to ", "for ", "in ", "on ", "at ", "from ", "then ", "carefully ", "which ", "who ", "that ",
            "a student ", "students ", "two other students ", "with fellow ", "participated in ", "contributed to ",
            "independently ", "draft ", "prototype ", "simulated ", "unpublished ", "approximately ", "at least ",
            "more than ", "as many as ", "a few ", "several hundred ", "twice ", "order of ", "Responsible for ",
            "Research assistant ", "Volunteer at ", "tested ", "reached ", "set ", "read ", "running ", "ran ",
            "wrote ", "written ", "to appear ", "in press ", "lead author ", "first author ", "owned ", "own ",
            "led the team ", "managed ", "supervised by ", "supervised ", "mentored ", "taught ", "and I ",
            "I helped ", "my advisor ", "PI ", "the TA ", "starter code from ", "adapted from ", "based on "]
WORDS_ZH = ["正在", "开发中", "撰写中", "计划", "将", "将于", "已", "完成", "未", "不", "没有", "从未", "协助", "帮助", "参与",
            "团队", "我们", "与组员一起", "导师", "基于", "参考", "约", "超过", "左右", "以来", "至今", "起", "本人只负责",
            "负责", "担任", "已投稿", "发表", "在实验室", "为打下", "过", "曾", "上线", "联合", "课题组", "两人", "3人",
            "一起", "同学", "独立", "仅", "只", "初稿", "原型", "仿真", "体现了", "熟练", "领导", "带领", "主导",
            "预计", "即将", "进行中", "在投", "待发表", "目前", "希望", "打算", "想要", "开发了网站，", "系统开发中，",
            "撰写了", "了一篇", "的", "中的", "并", "而且", "，并", "；", "。我", "我负责", "和 teammates", "只（", "（开发中）"]
PAIRS = ["not helped ", "helped not ", "team I ", "I team ", "never submitted ", "submitted never ", "with my team I ",
         "I, with my team, ", "led y. never led z. ", "led y. not led z. ", "developed with my team ",
         "planned and built ", "built and planned ", "helped build and tested ", "since 2024 until 2025 ",
         "about 40 samples, ", "Sam, a senior student, revised it; ", "edited by the lab manager; ",
         "未参与开发，", "本人只负责建模，", "与导师一起组织了 40 场访谈，", "正在撰写论文，", "开发中的系统，",
         "with two teammates; I designed ", "Built X with a friend; I wrote Y. ", "co-authored a paper, submitted, ",
         "Research assistant in the lab since Fall 2025, scheduling ", "Course assistant for CS 124, holding ",
         "helped aing and bing or cing ", "a, b and c or d, ", "1, 2 and 3 ", "(in preparation) ", "（撰写中）",
         "under development ", "in development ", "will be published ", "to be submitted ", "hoping to publish "]
FILLS = CHARS + MIXED + WORDS_EN + WORDS_ZH + PAIRS


def fit(unit: str, size: int) -> str:
    text = (unit * (size // len(unit) + 1))[:size]
    return text if text.strip() else unit * (size // len(unit))


def rotate(text: str, share: float = 0.5) -> str:
    words = text.split(" ")
    cut = max(1, int(len(words) * share))
    return " ".join(words[cut:] + words[:cut]).strip() or text[::-1]


def cases(unit: str):
    """(name, Unit, rewrites) at the caps: /tailor's 500-character bullet on a 6,000-character source,
    full target's 6,000-character line, and that line split into a unit and a support line."""
    evidence = fit(unit, CAP)
    bullet = fit(unit, BULLET - len("Responsible for "))
    tailor_current = "Responsible for " + bullet
    rewrites_tailor = [bullet[:1].upper() + bullet[1:], rotate(tailor_current), tailor_current[::-1][:BULLET + 120]]
    rewrites_full = [rotate(evidence), rotate(evidence, 0.1), evidence[::-1]]
    half = CAP // 2
    yield "tailor", em.Unit("b1", evidence, tailor_current), rewrites_tailor
    yield "full", em.Unit("b1", evidence, evidence, keyed=True), rewrites_full
    yield "full+support", em.Unit("b1", evidence[:half], evidence[:half], support=(("s1", evidence[half:]),),
                                  keyed=True), [rotate(evidence[:half]), rotate(evidence)[:CAP]]


def declarations(unit: em.Unit, rewrite: str):
    """Rows that open each path through the contract: verb_first, personal_first, lead_with and relabel."""
    words = [word.strip(".,;:()（）") for word in unit.current.split()]
    word = next((w for w in words if len(w) > 3), words[0] if words else unit.current[:4]) or unit.current[:4]
    anchors = {"t1": em.Anchor("t1", {"field": "description", "requirement_index": None, "start": 0,
                                      "end": len(word) + 5, "quote": word + " data"})}
    link = {"id": "L1", "anchor": "t1", "term": word + " data", "source": word, "relation": "same"}
    long_source = {"id": "L2", "anchor": "t1", "term": word, "source": unit.current[:2000], "relation": "same"}
    rows = [([{"op": "verb_first"}], []), ([{"op": "personal_first"}], []),
            ([{"op": "lead_with", "link": "L1"}], [link]),
            ([{"op": "relabel", "link": "L1", "from": word, "to": word + " data"}], [link]),
            ([{"op": "lead_with", "link": "L2"}, {"op": "tighten"}], [long_source])]
    for ops, links in rows:
        yield anchors, {"unit_id": "b1", "decision": "rewrite", "text": rewrite, "keep_reason": None,
                        "links": links, "ops": ops}


def work(unit: em.Unit, rewrites: list[str]) -> None:
    language = em.language(unit.current)
    for rewrite in rewrites:
        for anchors, row in declarations(unit, rewrite):
            outcome = em.check_rewrite(unit, row, anchors, output_language=language)
            if outcome.status == "pending":
                outcome = em.gate(outcome, unit)
                if outcome.status == "pending":
                    em.without_terms(outcome, unit, row["ops"])
        # Every rewrite is read by the locks here, whether or not a row passes the contract,
        # and the alternative's relabel path is read with a relabel that stands in the text.
        pending = em.Outcome("b1", "pending", text=rewrite)
        em.gate(pending, unit)
        words = rewrite.split()
        if words:
            em.without_terms(em.Outcome("b1", "pending", text=rewrite, relabels=[(words[0], words[0])]), unit,
                             [{"op": "verb_first"}])


async def lag_while(target, *args) -> tuple[float, float, float]:
    """(longest event-loop wake-up delay, worker CPU seconds, wall seconds) while ``target`` runs on a thread."""
    cpu = {}

    def run():
        started = time.thread_time()
        target(*args)
        cpu["seconds"] = time.thread_time() - started

    thread = threading.Thread(target=run, name="ofe-blocking-ai-probe")
    worst, began = 0.0, time.perf_counter()
    thread.start()
    while thread.is_alive():
        before = time.perf_counter()
        await asyncio.sleep(0.001)
        worst = max(worst, time.perf_counter() - before - 0.001)
    thread.join()
    return worst, cpu.get("seconds", float("nan")), time.perf_counter() - began


def measure(unit: em.Unit, rewrites: list[str], repeats: int, threshold: float) -> tuple[float, float, float]:
    best = None
    for _ in range(repeats):
        result = asyncio.run(lag_while(work, unit, rewrites))
        best = result if best is None or result[0] < best[0] else best
        if best[0] <= threshold:
            break
    return best


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--threshold", type=float, default=0.25)
    parser.add_argument("--only", default="")
    parser.add_argument("--quiet", action="store_true", help="print only shapes over half the threshold")
    args = parser.parse_args()
    rows = []
    for fill in FILLS:
        if args.only and args.only not in fill:
            continue
        for mode, unit, rewrites in cases(fill):
            lag, cpu, wall = measure(unit, rewrites, 3, args.threshold)
            rows.append((lag, cpu, wall, mode, fill))
            if not args.quiet or lag > args.threshold / 2:
                print(f"{lag * 1000:8.1f} ms lag  {cpu:7.3f} s cpu  {wall:7.3f} s wall  {mode:13} {fill!r}", flush=True)
    rows.sort(reverse=True)
    print("\nworst event-loop stalls:")
    for lag, cpu, _wall, mode, fill in rows[:10]:
        print(f"{lag * 1000:8.1f} ms lag  {cpu:7.3f} s cpu  {mode:13} {fill!r}")
    by_cpu = sorted(rows, key=lambda row: -row[1])
    print("\nmost worker CPU per unit:")
    for lag, cpu, _wall, mode, fill in by_cpu[:10]:
        print(f"{cpu:7.3f} s cpu  {lag * 1000:8.1f} ms lag  {mode:13} {fill!r}")
    over = [row for row in rows if row[0] > args.threshold]
    print(f"\nshapes: {len(rows)}; over {args.threshold:.2f} s: {len(over)}; worst lag {rows[0][0]:.3f} s; "
          f"worst worker CPU {by_cpu[0][1]:.3f} s")
    return 1 if over else 0


if __name__ == "__main__":
    raise SystemExit(main())
