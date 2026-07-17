"""Manual eyeball harness for the cold-email AI pipeline — NOT CI.

Runs sampled opportunities × student personas through BOTH engines and prints
the template vs pipeline outputs side by side, plus stage/gate stats, so a
human can judge templated-ness ("套话感") directly. Costs real LLM tokens.

Usage:
    set -a; source backend/.env; set +a
    python scripts/cold_email_eyeball.py [N_OPPS=3]

The thin-freshman persona is deliberately included: an empty profile is where
a model is most tempted to copy the few-shot example's facts, so any concrete
claim appearing in that persona's email is a red flag to investigate.
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import backend.routes.cold_email as ce  # noqa: E402
from backend.data_loader import load_opportunities  # noqa: E402
from backend.lib.grounding import LENIENT_PROSE, validate_no_fabrication  # noqa: E402
from backend.lib.llm import is_configured  # noqa: E402
from src.recommender.cold_email import generate_cold_email  # noqa: E402

PERSONAS: list[tuple[str, dict, list[str]]] = [
    (
        "CS junior + resume bullets",
        {
            "name": "Alex Chen", "year": "junior", "major": "Computer Science",
            "school": "UIUC",
            "hard_skills": [
                {"name": "Python", "level": "expert"},
                {"name": "PyTorch", "level": "experienced"},
            ],
            "coursework": ["CS 225", "CS 446"],
            "research_interests_text": "machine learning and computer vision",
        },
        [
            "Built an image-classification pipeline in PyTorch for a course "
            "project, reaching 91% accuracy on CIFAR-10",
            "Led a 3-person team building a Flask web app for campus club "
            "event scheduling",
        ],
    ),
    (
        "Bio sophomore, no bullets",
        {
            "name": "Maria Lopez", "year": "sophomore", "major": "Molecular Biology",
            "school": "UIUC",
            "hard_skills": [{"name": "pipetting", "level": "experienced"}],
            "coursework": ["MCB 150", "CHEM 232"],
            "research_interests_text": "gene regulation and cell signaling",
        },
        [],
    ),
    (
        "THIN freshman (exemplar-copy risk)",
        {
            "name": "Sam Park", "year": "freshman", "major": "Undeclared",
            "school": "UIUC", "hard_skills": [], "coursework": [],
            "research_interests_text": "",
        },
        [],
    ),
]


def _pick_opportunities(n: int) -> list[dict]:
    """Research postings with a PI + recent works + keywords, one per school."""
    seen_schools: set[str] = set()
    picked: list[dict] = []
    for opp in load_opportunities():
        if opp.get("opportunity_type") != "research":
            continue
        meta = opp.get("metadata") or {}
        if not (opp.get("pi_name") and meta.get("recent_works") and opp.get("keywords")):
            continue
        school = str(opp.get("school") or "?")
        if school in seen_schools:
            continue
        seen_schools.add(school)
        picked.append(opp)
        if len(picked) >= n:
            break
    return picked


def _run_pipeline_counted(profile: dict, opp: dict, bullets: list[str]) -> tuple[str | None, int]:
    """Run the pipeline with a call-counting chat wrapper (draft=1, +critique=2,
    +revise=3) so the printout shows which stages fired."""
    calls = 0
    real_chat = ce.chat_completion

    def counting_chat(messages, *a, **k):
        nonlocal calls
        calls += 1
        return real_chat(messages, *a, **k)

    ce.chat_completion = counting_chat
    try:
        return ce._pipeline_generate(profile, opp, None, bullets), calls
    finally:
        ce.chat_completion = real_chat


def main() -> None:
    if not is_configured():
        sys.exit("No LLM provider configured — source backend/.env first.")
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    opps = _pick_opportunities(n)
    print(f"=== eyeball run: {len(opps)} opportunities × rotating personas ===\n")

    for i, opp in enumerate(opps):
        label, profile, bullets = PERSONAS[i % len(PERSONAS)]
        pi = opp.get("pi_name")
        print("=" * 78)
        print(f"[{i + 1}] {opp.get('school')} · {pi} · {str(opp.get('title'))[:70]}")
        print(f"    persona: {label}")
        print("=" * 78)

        template_text = generate_cold_email(profile, opp)
        print("\n--- TEMPLATE ENGINE " + "-" * 50)
        print(template_text)

        ai_text, n_calls = _run_pipeline_counted(profile, opp, bullets)

        stage = {1: "draft only", 2: "draft+critique (passed)", 3: "draft+critique+REVISE"}
        print(f"\n--- AI PIPELINE  [{stage.get(n_calls, f'{n_calls} calls')}] " + "-" * 30)
        if not ai_text:
            print("(pipeline returned None — would fall back to template)")
            continue
        print(ai_text)

        p = ce._common_parts(profile, opp, resume_bullets=bullets)
        corpus = ce._build_email_corpus(p, opp)
        passed, fabricated = validate_no_fabrication(
            ai_text, corpus, extra_allow=ce._EMAIL_SCAFFOLDING, policy=LENIENT_PROSE,
        )
        print(f"\n    final gate: {'PASS' if passed else 'REJECT -> template'}"
              + (f"  (fabricated: {fabricated[:5]})" if not passed else ""))
        print()


if __name__ == "__main__":
    main()
