"""Section headings and status rows under a glyph bullet, as the extraction routes read them.

The extraction routes (/api/tailor/extract-bullets, /api/tailor/structure) accept a model line only
where a résumé item starts and ends, and the no-model fallback returns each item whole. A row under a
glyph bullet is then either a row of its own or the rest of that bullet:

  * a section heading read as the rest of the bullet loses that bullet on both routes (the model's
    line for it is refused) and glues the heading onto it in the fallback; main keeps every one;
  * a status, share or negation row read as a row of its own lets the model's cut of the bullet
    above it, without that row, be accepted; main accepts every contiguous cut.

Placements: every heading below, in title case, in capitals, with a colon and in sentence case
(English), or as written (Chinese), under each of a few bullets with no closing mark, between a
bullet above and one below. A placement is kept when both routes, given a model that answers the
student's three bullets, return exactly those three, and the fallback returns them too.

Run from the repository root, with checkouts beside it:

    git worktree add ../main-checkout origin/main
    python scripts/extraction_heading_probe.py --main-root ../main-checkout [--other-root ../other] [--list]

Each root is probed in a subprocess there (PYTHONPATH=<root>), with the model stubbed at
routes.tailor.chat_completion; no provider is called. Deterministic.
"""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path.cwd()

EN_HEADINGS = [
    "Education", "Experience", "Research Experience", "Work Experience", "Professional Experience", "Projects",
    "Academic Projects", "Personal Projects", "Selected Projects", "Team Projects", "Group Projects", "Publications",
    "Selected Publications", "Papers", "Presentations", "Posters", "Conference Presentations",
    "Publications & Presentations", "Publications and Presentations", "Skills", "Technical Skills", "Languages",
    "Awards", "Honors", "Honors & Awards", "Honors and Awards", "Activities", "Extracurricular Activities",
    "Leadership", "Leadership Experience", "Leadership & Involvement", "Campus Involvement", "Involvement", "Service",
    "Community Service", "Volunteer Experience", "Volunteering", "Teaching", "Teaching Experience",
    "Relevant Coursework", "Coursework", "Certifications", "Interests", "References", "Summary", "Objective",
    "Collaborations", "Collaborative Projects", "Ongoing Projects", "Current Projects", "Research in Progress",
    "Works in Progress", "Work in Progress", "Manuscripts in Preparation", "Manuscripts Under Review",
    "Papers Under Review", "Submitted Manuscripts", "Planned Research", "Future Research", "Accepted Papers",
    "Submitted Papers", "Forthcoming Publications", "Preprints", "Peer-Reviewed Publications", "Journal Articles",
    "Conference Papers", "Patents", "Grants", "Fellowships", "Scholarships", "Research Interests",
    "Additional Information", "Additional Experience", "Other Experience", "Related Experience", "Internships",
    "Employment", "Employment History", "Clubs and Organizations", "Student Organizations",
    "Professional Affiliations", "Memberships", "Outreach", "Mentoring", "Mentorship", "Independent Research",
    "Undergraduate Research", "Research Projects", "Lab Experience", "Field Experience", "Clinical Experience",
    "Shadowing", "Hackathons", "Competitions", "Athletics", "Military Service", "Study Abroad", "Hobbies",
    "Invited Talks", "Talks", "Workshops", "Professional Development", "Training", "Team Experience",
    "Team Leadership", "Joint Projects", "Co-Authored Publications", "Pending Publications",
    "Publications in Preparation", "Drafts", "Works Cited", "Group Work", "Partnerships", "Contributions",
    "Contributed Talks", "Unpublished Work", "Projects Not Listed Above", "Under Review", "In Progress",
    "Planned Projects", "Upcoming Presentations", "Expected Graduation", "Assisted Research", "Supported Projects",
]
EN_WRITTEN = ["Leadership, Service & Involvement", "Honors, Awards & Scholarships", "Publications (Selected)",
              "Projects (Team)", "Research and Teaching Experience at UIUC", "Skills & Interests",
              "Research, Teaching & Team Projects", "Publications / Presentations", "Selected Publications*",
              "Team Projects (2024)", "Projects - Team", "Research Experience — Ongoing"]
ZH_HEADINGS = [
    "教育背景", "教育经历", "科研经历", "研究经历", "项目经历", "实习经历", "工作经历", "实践经历", "校园经历", "社团经历",
    "学生工作", "志愿服务", "志愿者经历", "获奖情况", "荣誉奖项", "奖励荣誉", "专业技能", "技能", "语言能力", "论文发表",
    "发表论文", "学术论文", "在投论文", "论文与专利", "学术成果", "科研成果", "合作项目", "合作研究", "参与项目", "团队项目",
    "课程项目", "个人项目", "竞赛经历", "比赛获奖", "自我评价", "个人简介", "兴趣爱好", "证书", "资格证书", "相关课程",
    "主修课程", "领导经历", "海外经历", "交流经历", "研究兴趣", "进行中的项目", "在研项目", "拟开展研究", "计划研究",
    "未发表论文", "待发表论文", "已发表论文", "论文成果", "合作发表", "团队经历", "协助研究", "参与研究", "在研课题",
    "主持项目", "项目经历：", "论文发表（第一作者）", "科研经历 Research", "发表论文与会议报告", "专利与论文",
]
# Rows that finish the bullet above them: a status, a share of the work or a negation.
STATUS_ROWS = [
    "Under Review", "In Preparation", "Work in Progress", "Manuscript in Preparation", "Paper Under Review",
    "Paper Accepted", "Draft Submitted", "Team Project", "Group Project", "Team Effort", "Joint Work",
    "Thesis in Progress", "Article Submitted to Nature", "Not Yet Submitted", "Submitted to Nature",
    "Collaborative Project", "Planned Study", "Ongoing Work", "Pending Review", "Accepted Paper", "Under review",
    "Work in progress", "Manuscript in preparation", "Team project", "Paper under review", "In progress",
    "Planned for 2026", "Expected May 2026", "With Two Graduate Students", "Team of 4", "Second Author",
    "Co-First Author", "Unpublished", "Preprint", "Forthcoming", "Status: under review",
    "尚未投稿", "已投稿", "论文在投", "论文撰写中", "项目进行中", "文章已接收", "计划投稿", "待发表", "论文准备中", "团队合作",
    "小组项目", "合作完成", "与两名研究生合作", "计划于 2026 年投稿", "在投", "撰写中", "正在投稿", "共同第一作者",
]

PROBE = r"""
import json, logging, os, sys, warnings
warnings.filterwarnings("ignore")
logging.disable(logging.CRITICAL)
os.environ["OFE_DISABLE_RATE_LIMIT"] = "1"
from fastapi.testclient import TestClient
from backend.main import app
from backend.routes import tailor

spec = json.load(sys.stdin)
client = TestClient(app)
tailor.is_configured = lambda: True
TOP = {"en": ("EXPERIENCE", "Ran 40 overnight EEG sessions with 20 participants"), "zh": ("项目经历", "搭建了校园农场的土壤湿度传感器网络")}
LAST = {"en": "Wrote a data logger in C for the club", "zh": "用 C 语言为社团编写了数据记录程序"}


def lines(path, resume, answer):
    def model(messages, **kwargs):
        if "Structure it now" in messages[1]["content"]:
            return json.dumps({"sections": [{"heading": "Experience", "kind": "experience", "bullets": answer}]})
        return json.dumps({"bullets": answer})
    tailor.chat_completion = model
    body = client.post(path, json={"resume_text": resume, "locale": "en"}).json()
    return body["bullets"] if path.endswith("extract-bullets") else [
        bullet["text"] for section in body["sections"] for bullet in section["bullets"]]


PATHS = ("/api/tailor/extract-bullets", "/api/tailor/structure")
headings = {}
for heading, bullet, lang in spec["headings"]:
    top, first = TOP[lang]
    bullets = [first, bullet, LAST[lang]]
    resume = f"{top}\n• {first}\n• {bullet}\n{heading}\n• {LAST[lang]}\n"
    kept = all(lines(path, resume, bullets) == bullets for path in PATHS) and tailor._heuristic_bullets(resume) == bullets
    headings[f"{heading} || {bullet}"] = kept
statuses = {}
for row, lang in spec["statuses"]:
    cut = "搭建了校园农场的土壤湿度传感器网络" if lang == "zh" else "Co-authored a paper on soil moisture sensing for the farm"
    last = "用 C 语言为社团编写了数据记录程序" if lang == "zh" else "Cleaned 200 survey responses"
    resume = f"{TOP[lang][0]}\n• {cut}\n{row}\n• {last}\n"
    statuses[row] = all(cut in lines(path, resume, [cut, last]) for path in PATHS)
json.dump({"headings": headings, "statuses": statuses}, sys.stdout, ensure_ascii=False)
"""


def placements() -> list[tuple[str, str, str]]:
    english = [variant for heading in EN_HEADINGS
               for variant in (heading, heading.upper(), heading + ":", heading[0] + heading[1:].lower())]
    en_bullets = ["Designed a sensor rig for the team", "Built a Python parser", "Cleaned 212 survey responses in R",
                  "Wrote the lab's data logger in C"]
    zh_bullets = ["为社团设计了一套传感器测试台", "清洗并分析了 200 份问卷数据"]
    return ([(heading, bullet, "en") for heading in [*english, *EN_WRITTEN] for bullet in en_bullets]
            + [(heading, bullet, "zh") for heading in ZH_HEADINGS for bullet in zh_bullets])


def probe(root: Path) -> dict:
    spec = {"headings": placements(),
            "statuses": [(row, "en" if row.isascii() else "zh") for row in STATUS_ROWS]}
    env = {**os.environ, "PYTHONPATH": str(root), "PYTHONWARNINGS": "ignore"}
    done = subprocess.run([sys.executable, "-c", PROBE], input=json.dumps(spec), capture_output=True, text=True,
                          cwd=root, env=env, check=True)
    return json.loads(done.stdout)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--main-root", required=True, help="a checkout of origin/main")
    parser.add_argument("--other-root", action="append", default=[], help="another checkout to compare (repeatable)")
    parser.add_argument("--list", action="store_true", help="list each heading and status row that differs from main")
    args = parser.parse_args()
    roots = {"branch": ROOT, "main": Path(args.main_root).resolve(),
             **{str(Path(other)): Path(other).resolve() for other in args.other_root}}
    results = {name: probe(root) for name, root in roots.items()}
    main_result = results["main"]
    total = len(main_result["headings"])
    for name, result in results.items():
        lost = [key for key, kept in result["headings"].items() if not kept]
        regressed = [key for key in lost if main_result["headings"][key]]
        headings = sorted({key.split(" || ")[0] for key in regressed})
        print(f"{name}: placements {total}, bullet lost or glued {len(lost)}, of which main keeps {len(regressed)}"
              f" ({len(headings)} headings)")
        cut = [row for row, accepted in result["statuses"].items() if accepted]
        print(f"{name}: status rows {len(result['statuses'])}, cut above accepted {len(cut)}")
        if args.list and name != "main":
            for heading in headings:
                print(f"  heading, bullet lost or glued: {heading}")
            for row in cut:
                print(f"  status row, cut above accepted: {row}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
