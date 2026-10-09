"""How many other-script translation shapes reach the faithfulness review (criterion 3).

language() and tokens() read only ASCII letters and CJK ideographs. This probe builds,
for lines written in part in another script (Hangul, kana, Cyrillic, Greek, Arabic,
Hebrew, Thai, Devanagari), three shapes that replace or gloss the line's own words in
English:

  relabel      the line's phrase "Python <own words>" relabelled to the posting's
               "Python data pipeline" (one relabel op);
  conjunction  the line reordered with lead_with and its own "and" word written
               as the English "and";
  glue         the line reordered with lead_with, every letter of its own kept,
               and the English "and" added between its tool names.

A shape "reaches review" when backend.lib.evidence_map.check_rewrite and then
evidence_map.gate leave it "pending", exactly as backend/routes/tailor.py
(_checked_outcomes) and backend/lib/target_resume_ai.py (parse_output) call them;
such a rewrite is shown whenever the review accepts it. Every count should be 0.

Run from the repository root (stdlib + repository imports, deterministic):
    python scripts/other_script_probe.py
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.lib import evidence_map as em  # noqa: E402

# (script, line, its phrase naming the pipeline, line with its own "and" between Python and SQL,
#  that line reordered with the English "and", its own words for "data analysis")
LINES = [
    ("hangul", "Python 데이터 파이프라인 구축 및 유지보수 담당", "Python 데이터 파이프라인",
     "Python 및 SQL 데이터 정리 담당", "SQL and Python 데이터 정리 담당", "데이터 분석"),
    ("kana", "Python データパイプライン の かいはつ を たんとう", "Python データパイプライン",
     "Python と SQL で データ を せいり", "SQL and Python で データ を せいり", "データ ぶんせき"),
    ("cyrillic", "Разработка: Python конвейер данных для лаборатории", "Python конвейер данных",
     "Python и SQL для обработки данных", "SQL and Python для обработки данных", "Анализ данных"),
    ("greek", "Ανάπτυξη Python αγωγού δεδομένων για το εργαστήριο", "Python αγωγού δεδομένων",
     "Python και SQL για ανάλυση δεδομένων", "SQL and Python για ανάλυση δεδομένων", "Ανάλυση δεδομένων"),
    ("arabic", "تطوير Python خط بيانات للمختبر", "Python خط بيانات",
     "Python و SQL لتحليل البيانات", "SQL and Python لتحليل البيانات", "تحليل البيانات"),
    ("hebrew", "פיתוח Python צינור נתונים למעבדה", "Python צינור נתונים",
     "Python ו SQL לניתוח נתונים", "SQL and Python לניתוח נתונים", "ניתוח נתונים"),
    ("thai", "พัฒนา Python ไปป์ไลน์ ข้อมูล สำหรับ ห้องแล็บ", "Python ไปป์ไลน์ ข้อมูล",
     "Python และ SQL สำหรับ วิเคราะห์ ข้อมูล", "SQL and Python สำหรับ วิเคราะห์ ข้อมูล", "วิเคราะห์ ข้อมูล"),
    ("devanagari", "प्रयोगशाला के लिए Python डेटा पाइपलाइन विकसित की", "Python डेटा पाइपलाइन",
     "Python और SQL से डेटा विश्लेषण", "SQL and Python से डेटा विश्लेषण", "डेटा विश्लेषण"),
]
PIPELINE = "Experience building a Python data pipeline is required."
SQL = "Experience with SQL is required."
SHAPES = ("relabel", "conjunction", "glue")


def _anchor(text: str) -> dict:
    return {"t1": em.Anchor("t1", {"field": "description", "requirement_index": None, "start": 0, "end": len(text),
                                   "quote": text})}


def reaches_review(original: str, row: dict, anchor: str) -> tuple[bool, str]:
    unit = em.Unit("b1", original, original)
    outcome = em.check_rewrite(unit, {"unit_id": "b1", **row}, _anchor(anchor), output_language=em.language(original))
    if outcome.status == "pending":
        outcome = em.gate(outcome, unit)
    return outcome.status == "pending", outcome.detail or outcome.status


def shapes(line: str, phrase: str, conjunction_line: str, conjunction_rewrite: str, own: str) -> dict:
    sql_link = [{"id": "L1", "anchor": "t1", "term": "SQL", "source": "SQL", "relation": "same"}]
    lead_with = [{"op": "lead_with", "link": "L1"}]
    return {
        "relabel": (line, {"links": [{"id": "L1", "anchor": "t1", "term": "Python data pipeline", "source": phrase,
                                      "relation": "same"}], "decision": "rewrite",
                           "ops": [{"op": "relabel", "link": "L1", "from": phrase, "to": "Python data pipeline"}],
                           "text": line.replace(phrase, "Python data pipeline"), "keep_reason": None}, PIPELINE),
        "conjunction": (conjunction_line, {"links": sql_link, "decision": "rewrite", "ops": lead_with,
                                           "text": conjunction_rewrite, "keep_reason": None}, SQL),
        "glue": (f"{own}: Python, SQL", {"links": sql_link, "decision": "rewrite", "ops": lead_with,
                                         "text": f"SQL and Python: {own}", "keep_reason": None}, SQL),
    }


def main() -> int:
    counts = dict.fromkeys(SHAPES, 0)
    for script, *texts in LINES:
        for shape, (original, row, anchor) in shapes(*texts).items():
            reached, detail = reaches_review(original, row, anchor)
            counts[shape] += reached
            print(f"{script:11s} {shape:12s} {'REACHES REVIEW' if reached else 'kept (' + detail + ')'}")
    total = len(LINES)
    print(f"relabel out of another script reaching review: {counts['relabel']} of {total}")
    print(f"own conjunction written in English reaching review: {counts['conjunction']} of {total}")
    print(f"English function word added to the line reaching review: {counts['glue']} of {total}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
