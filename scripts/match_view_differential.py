#!/usr/bin/env python3
"""Compare the results page's responses between two checkouts, JSON for JSON (M74).

M74 stopped projecting a card for every visible row of a match snapshot: the
view pass reads a compact view row per record and only the served page is
projected. Nothing a response carries may change. This script asks one
checkout's app every question the results page can ask, for many synthetic
profiles, and writes every response; ``compare`` then holds two such files
equal byte for byte after JSON parsing.

    # 1. a plain copy of the base commit's code (no git worktree needed)
    git archive <base> backend src scripts config examples | tar -x -C /tmp/base
    # 2. both captures read this checkout's corpus files, then compare
    python scripts/match_view_differential.py run --base-root /tmp/base

    python scripts/match_view_differential.py capture --code-root PATH --out FILE
    python scripts/match_view_differential.py compare BASE_FILE HEAD_FILE
    python scripts/match_view_differential.py rows     # this checkout only

What one capture asks, per profile: the first page; every tab; each filter
value; each sort; searches including text that only a redacted contact
carries ("@", "edu", an email local part and domain read off the corpus,
"email", "redacted"); combinations; favourites and dismissals taken from the
profile's own results; a later ``today``; page sizes 10 and 100; pages two
and three by cursor for a few views; the /matches list and its next page; and
/matches/{id}/explain for two served rows (its release gate opened in both).

``rows`` checks the other half of the argument directly: for every record of
the corpus, the view row built from the record equals the row read off its
fully projected card.

Both captures run the real app in-process through its own lifespan, with the
provider, Supabase and Sentry settings blanked (nothing leaves the machine)
and the release SHA unset, and both read the same corpus files, so the
corpus generation token and every result-set id can match. Run them on the
same calendar day: the ranking reads it.
"""
from __future__ import annotations

import argparse
import gzip
import importlib.util
import json
import os
import re
import subprocess
import sys
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]

ISOLATION_ENV = {
    "OFE_DISABLE_RATE_LIMIT": "1",
    "OPENROUTER_API_KEY": "",
    "OPENAI_API_KEY": "",
    "GEMINI_API_KEY": "",
    "SUPABASE_URL": "",
    "SUPABASE_SERVICE_ROLE_KEY": "",
    "OFE_MATERIAL_ARCHIVE_ENABLED": "0",
    "SENTRY_DSN": "",
    "RENDER_GIT_COMMIT": "",
    "OFE_RELEASE_SHA": "",
}


def _measure_module():
    """The #1047 personas live in the latency script; load it by path."""
    spec = importlib.util.spec_from_file_location(
        "_measure_match_latency", PROJECT_ROOT / "scripts" / "measure_match_latency.py",
    )
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # its dataclasses look their module up
    spec.loader.exec_module(module)
    return module


def _personas() -> dict[str, dict]:
    measure = _measure_module()
    profile = measure._profile
    extra = {
        "tamu_mech": profile(
            "tamu_mech", home_school="tamu", school="Texas A&M", year="junior",
            major="Mechanical Engineering", college="College of Engineering",
            interests="robotics, manufacturing, finite element analysis",
            seeking=["research", "internship"],
            skills=[("SolidWorks", "experienced"), ("MATLAB", "beginner")],
            coursework=["MEEN 357"],
        ),
        "psu_chem_intl": profile(
            "psu_chem_intl", home_school="psu", school="Penn State", year="sophomore",
            major="Chemistry", college="Eberly College of Science",
            interests="organic synthesis, catalysis, spectroscopy",
            seeking=["research", "summer_program"],
            skills=[("NMR", "beginner")], coursework=["CHEM 210"], international=True,
        ),
        "northwestern_journalism": profile(
            "northwestern_journalism", home_school="northwestern", school="Northwestern",
            year="senior", major="Journalism", college="Medill School of Journalism",
            interests="media studies, data journalism",
            seeking=["research", "internship"],
            skills=[("Python", "beginner")], coursework=["JOUR 201"],
        ),
        "jhu_neuro_no_interests": profile(
            "jhu_neuro_no_interests", home_school="jhu", school="Johns Hopkins", year="freshman",
            major="Neuroscience", college="Krieger School of Arts and Sciences",
            interests="", seeking=["research", "internship"], skills=[], coursework=[],
        ),
        "bu_cs_strict": {
            **profile(
                "bu_cs_strict", home_school="bu", school="Boston University", year="junior",
                major="Computer Science", college="College of Arts and Sciences",
                interests="computer security, cryptography",
                seeking=["research"], skills=[("C", "experienced")], coursework=["CS 350"],
            ),
            "preferences": {
                "min_match_threshold": 50, "show_reach_opportunities": False,
                "prioritize_paid": False, "exclude_citizenship_restricted": True,
            },
        },
        "osu_econ_cross": {
            **profile(
                "osu_econ_cross", home_school="osu", school="Ohio State", year="sophomore",
                major="Economics", college="College of Arts and Sciences",
                interests="behavioral economics, labor markets",
                seeking=["research"], skills=[("Stata", "beginner")], coursework=["ECON 4001"],
            ),
            "include_cross_school": True,
        },
        "uw_bio_explore_cross": {
            **profile(
                "uw_bio_explore_cross", home_school="uw", school="University of Washington",
                year="junior", major="Biology", college="College of Arts and Sciences",
                interests="marine biology, ecology",
                seeking=["research", "summer_program"],
                skills=[("R", "beginner")], coursework=["BIOL 180"], international=True,
            ),
            "include_cross_school": True,
            "exploring": True,
        },
    }
    return {**measure.PERSONAS, **extra}


_EMAIL_RE = re.compile(r"([A-Za-z][A-Za-z0-9._%+-]{3,})@([A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,})")


def _contact_terms(corpus: list[dict]) -> tuple[str, str]:
    """An email local part and domain that the corpus's descriptions carry."""
    for record in corpus:
        match = _EMAIL_RE.search(str(record.get("description_clean") or ""))
        if match:
            return match.group(1).lower(), match.group(2).lower()
    return "jane.doe", "example.edu"


SEARCHES = [
    "machine learning", "Machine Learning", " ml ", "ml", "ai", "nlp", "edu", "@", "email",
    "redacted", "[email redacted]", "[", "prof", "research", "lab", "university",
    "neuroscience", "power electronics", "epidemiology", "c++", "summer", "deadline in",
]


def _views(favorites: list[str], dismissed: list[str], sources: list[str],
           local_part: str, domain: str, today: str) -> list[tuple[str, dict]]:
    views: list[tuple[str, dict]] = [
        ("first_page", {}),
        ("tab_all", {"tab": "all"}),
        ("tab_good_match", {"tab": "good_match"}),
        ("tab_reach", {"tab": "reach"}),
        ("tab_starred", {"tab": "starred", "favorite_ids": favorites}),
        ("first_page_with_favorites", {"favorite_ids": favorites}),
        ("dismissed", {"tab": "all", "dismissed_ids": dismissed}),
        ("dismissed_shown", {"tab": "all", "dismissed_ids": dismissed, "show_dismissed": True}),
        ("paid_yes", {"tab": "all", "paid": "yes"}),
        ("paid_no", {"tab": "all", "paid": "no"}),
        ("intl_yes", {"tab": "all", "intl": "yes"}),
        ("intl_no", {"tab": "all", "intl": "no"}),
        ("on_campus_yes", {"tab": "all", "on_campus": "yes"}),
        ("on_campus_no", {"tab": "all", "on_campus": "no"}),
        ("deadline_rolling", {"tab": "all", "deadline": "rolling"}),
        ("deadline_7", {"tab": "all", "deadline": "7"}),
        ("deadline_14", {"tab": "all", "deadline": "14"}),
        ("deadline_30", {"tab": "all", "deadline": "30"}),
        ("deadline_passed", {"tab": "all", "deadline": "passed"}),
        ("scope_campus", {"tab": "all", "scope": "campus"}),
        ("scope_open", {"tab": "all", "scope": "open"}),
        ("min_score_50", {"tab": "all", "min_score": 50}),
        ("min_score_75", {"tab": "all", "min_score": 75}),
        ("source_none_such", {"tab": "all", "source": "no_such_source"}),
        ("sort_newest_all", {"tab": "all", "sort_by": "newest"}),
        ("sort_deadline_all", {"tab": "all", "sort_by": "deadline"}),
        ("sort_newest_first_page", {"sort_by": "newest"}),
        ("sort_deadline_good_match", {"tab": "good_match", "sort_by": "deadline"}),
        ("later_today_deadlines", {
            "tab": "all", "sort_by": "deadline",
            "today": (date.fromisoformat(today) + timedelta(days=30)).isoformat(),
        }),
        ("combo_reach_paid_newest", {"tab": "reach", "paid": "yes", "sort_by": "newest"}),
        ("combo_search_edu_deadline", {"tab": "all", "search_query": "edu", "sort_by": "deadline"}),
        ("combo_search_research_good_match_scope", {
            "tab": "good_match", "search_query": "research", "scope": "open", "min_score": 40,
        }),
        ("combo_starred_search", {"tab": "starred", "favorite_ids": favorites, "search_query": "lab"}),
    ]
    for index, source in enumerate(sources[:3]):
        views.append((f"source_{index}", {"tab": "all", "source": source}))
        views.append((f"source_{index}_search_ml", {"tab": "all", "source": source, "search_query": "ml"}))
    for query in [*SEARCHES, local_part, domain, f"{local_part}@{domain}"]:
        views.append((f"search:{query}", {"tab": "all", "search_query": query}))
    return views


PAGED = ("first_page", "tab_all", "sort_newest_all", "search:edu", "search:machine learning", "dismissed")


def _point_loader_at(data_loader, data_dir: Path) -> Path | None:
    """Read the shards the way the deployed API does, even beside a work file."""
    shards = data_dir / "shards"
    if not (data_dir / "opportunities.json").exists():
        data_loader.DATA_DIR = data_dir
        return None
    holder = Path(tempfile.mkdtemp(prefix="ofe-differential-"))
    (holder / "shards").symlink_to(shards.resolve(), target_is_directory=True)
    data_loader.DATA_DIR = holder
    return holder


def capture(args) -> int:
    for name, value in ISOLATION_ENV.items():
        os.environ[name] = value
    # conftest turns snapshot reuse off; page two must read page one's snapshot.
    os.environ.pop("OFE_MATCH_SNAPSHOT_TTL", None)
    personas = _personas()
    if args.profiles:
        personas = {name: personas[name] for name in args.profiles}
    code_root = Path(args.code_root).resolve()
    sys.path.insert(0, str(code_root))

    from fastapi.testclient import TestClient

    import backend
    from backend import data_loader

    holder = _point_loader_at(data_loader, Path(args.data_dir).resolve())
    from backend import main as app_main
    from backend.main import app

    # The compare surface's explain route is closed in this release. Open it
    # in both captures: it serves a snapshot's card too.
    release_check = app_main.feature_enabled
    app_main.feature_enabled = lambda feature: feature == "compare" or release_check(feature)

    started = time.perf_counter()
    today = args.today or date.today().isoformat()
    count = 0
    try:
        with TestClient(app) as client, gzip.open(args.out, "wt", encoding="utf-8") as out:
            corpus = data_loader.load_opportunities()
            local_part, domain = _contact_terms(corpus)
            out.write(json.dumps({
                "header": True,
                "backend": str(Path(backend.__file__).resolve().parent),
                "today": today,
                "records": len(corpus),
                "corpus_generation": data_loader.corpus_version(),
                "contact_terms": [local_part, domain],
                "profiles": list(personas),
            }) + "\n")

            def ask(profile_name: str, label: str, path: str, body: dict, params=None) -> dict:
                nonlocal count
                response = client.post(path, params=params or {}, json=body)
                count += 1
                payload = response.json()
                out.write(json.dumps({
                    "profile": profile_name, "label": label, "path": path,
                    "request": {"params": params or {}, "body": body},
                    "status": response.status_code, "body": payload,
                }, sort_keys=True) + "\n")
                return payload if response.status_code == 200 else {}

            for name, profile in personas.items():
                profile_started = time.perf_counter()

                def view(label, overrides, page_size=50, cursor=None, profile=profile, name=name):
                    body = {
                        "profile": profile,
                        "view": {"today": today, **_FIRST_VIEW, **overrides},
                        "page_size": page_size,
                        "cursor": cursor,
                    }
                    return ask(name, label, "/api/matches/view", body, {"llm": "false"})

                every = view("seed_tab_all", {"tab": "all"}, page_size=100)
                ids = [row["opportunity_id"] for row in every.get("results", [])]
                favorites = [*ids[:3], *ids[-2:], "not-a-real-id"]
                dismissed = ids[1:4]
                sources = [facet["source"] for facet in every.get("source_facets", [])]
                for label, overrides in _views(favorites, dismissed, sources, local_part, domain, today):
                    page = view(label, overrides)
                    if label in PAGED:
                        for number in (2, 3):
                            if not page.get("next_cursor"):
                                break
                            page = view(f"{label}#page{number}", overrides, cursor=page["next_cursor"])
                view("tab_all_size10", {"tab": "all"}, page_size=10)
                view("tab_all_size100", {"tab": "all"}, page_size=100)
                listed = ask(name, "matches", "/api/matches", profile, {"llm": "false", "limit": 100})
                if listed.get("next_cursor"):
                    ask(name, "matches#page2", "/api/matches", profile,
                        {"llm": "false", "limit": 100, "cursor": listed["next_cursor"]})
                for opportunity_id in ids[:2]:
                    ask(name, f"explain:{opportunity_id}", f"/api/matches/{opportunity_id}/explain",
                        profile, {"llm": "false"})
                print(f"[{time.perf_counter() - started:7.1f}s] {name}: "
                      f"{time.perf_counter() - profile_started:.1f}s", file=sys.stderr, flush=True)
    finally:
        if holder is not None:
            (holder / "shards").unlink(missing_ok=True)
            holder.rmdir()
    print(f"{count} responses from {len(personas)} profiles written to {args.out} "
          f"in {time.perf_counter() - started:.1f}s", file=sys.stderr)
    return 0


_FIRST_VIEW = {
    "tab": "high_priority", "search_query": "", "paid": "", "intl": "", "source": "",
    "on_campus": "", "deadline": "", "min_score": 0, "scope": "", "sort_by": "score",
    "show_dismissed": False, "favorite_ids": [], "dismissed_ids": [],
}


def _first_difference(left, right, path="$") -> str | None:
    if type(left) is not type(right):
        return f"{path}: {type(left).__name__} != {type(right).__name__}"
    if isinstance(left, dict):
        for key in sorted(set(left) | set(right)):
            if key not in left or key not in right:
                return f"{path}.{key}: only on {'base' if key in left else 'head'}"
            found = _first_difference(left[key], right[key], f"{path}.{key}")
            if found:
                return found
        return None
    if isinstance(left, list):
        if len(left) != len(right):
            return f"{path}: {len(left)} items != {len(right)}"
        for index, (a, b) in enumerate(zip(left, right, strict=True)):
            found = _first_difference(a, b, f"{path}[{index}]")
            if found:
                return found
        return None
    return None if left == right else f"{path}: {left!r} != {right!r}"


def compare(base_path: str, head_path: str, show: int = 10) -> int:
    with gzip.open(base_path, "rt", encoding="utf-8") as base, gzip.open(head_path, "rt", encoding="utf-8") as head:
        base_lines, head_lines = base.readlines(), head.readlines()
    base_header, head_header = json.loads(base_lines[0]), json.loads(head_lines[0])
    for key in ("today", "records", "corpus_generation", "contact_terms", "profiles"):
        if base_header[key] != head_header[key]:
            print(f"headers differ on {key}: {base_header[key]!r} != {head_header[key]!r}")
            return 1
    if len(base_lines) != len(head_lines):
        print(f"{len(base_lines) - 1} base responses, {len(head_lines) - 1} head responses")
    differences = 0
    statuses: dict[int, int] = {}
    rows = 0
    profiles: set[str] = set()
    for base_line, head_line in zip(base_lines[1:], head_lines[1:], strict=False):
        left, right = json.loads(base_line), json.loads(head_line)
        profiles.add(left["profile"])
        statuses[left["status"]] = statuses.get(left["status"], 0) + 1
        rows += len(left["body"].get("results", [])) if isinstance(left["body"], dict) else 0
        if left == right:
            continue
        differences += 1
        if differences <= show:
            print(f"DIFFERENT {left['profile']} {left['label']}: {_first_difference(left, right)}")
    compared = min(len(base_lines), len(head_lines)) - 1
    print(f"base {base_header['backend']}\nhead {head_header['backend']}")
    print(f"{compared} responses compared over {len(profiles)} profiles "
          f"({rows} result rows, statuses {dict(sorted(statuses.items()))}): "
          f"{compared - differences} identical, {differences} different")
    return 0 if differences == 0 and len(base_lines) == len(head_lines) else 1


def rows(args) -> int:
    """Every corpus record: the built view row equals the row read off its card."""
    for name, value in ISOLATION_ENV.items():
        os.environ[name] = value
    sys.path.insert(0, str(PROJECT_ROOT))
    from backend import data_loader
    from backend.routes import matches

    holder = _point_loader_at(data_loader, Path(args.data_dir).resolve())
    try:
        corpus = data_loader.load_opportunities()
    finally:
        if holder is not None:
            (holder / "shards").unlink(missing_ok=True)
            holder.rmdir()
    started = time.perf_counter()
    redacts = matches._memoized(matches.contains_embedded_email)
    mismatched = []
    for record in corpus:
        built = matches._match_view_row(record, redacts)
        read = matches._view_row_from_card(matches._match_card(record), record=record)
        if built != read:
            mismatched.append(record.get("id"))
    print(f"{len(corpus)} records in {time.perf_counter() - started:.1f}s: "
          f"{len(corpus) - len(mismatched)} rows equal, {len(mismatched)} different {mismatched[:10]}")
    return 0 if not mismatched else 1


def run(args) -> int:
    with tempfile.TemporaryDirectory(prefix="ofe-differential-") as scratch:
        outputs = {}
        today = args.today or date.today().isoformat()
        for side, root in (("base", args.base_root), ("head", str(PROJECT_ROOT))):
            outputs[side] = str(Path(args.keep or scratch) / f"{side}.jsonl.gz")
            command = [
                sys.executable, str(Path(__file__).resolve()), "capture",
                "--code-root", root, "--data-dir", args.data_dir, "--out", outputs[side],
                "--today", today, *(["--profiles", *args.profiles] if args.profiles else []),
            ]
            print(f"capturing {side} from {root}", file=sys.stderr, flush=True)
            env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
            subprocess.run(command, check=True, env=env)
        return compare(outputs["base"], outputs["head"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    commands = parser.add_subparsers(dest="command", required=True)
    default_data = str(PROJECT_ROOT / "data" / "processed")

    capture_parser = commands.add_parser("capture", help="write one checkout's responses")
    capture_parser.add_argument("--code-root", default=str(PROJECT_ROOT))
    capture_parser.add_argument("--data-dir", default=default_data)
    capture_parser.add_argument("--out", required=True)
    capture_parser.add_argument("--today", help="the view's calendar day (default: today)")
    capture_parser.add_argument("--profiles", nargs="*", help="persona names (default: all)")

    compare_parser = commands.add_parser("compare", help="compare two capture files")
    compare_parser.add_argument("base")
    compare_parser.add_argument("head")

    rows_parser = commands.add_parser("rows", help="built view rows against projected cards, every record")
    rows_parser.add_argument("--data-dir", default=default_data)

    run_parser = commands.add_parser("run", help="capture base and this checkout, then compare")
    run_parser.add_argument("--base-root", required=True)
    run_parser.add_argument("--data-dir", default=default_data)
    run_parser.add_argument("--today")
    run_parser.add_argument("--profiles", nargs="*")
    run_parser.add_argument("--keep", help="directory to keep the capture files in")

    args = parser.parse_args(argv)
    if args.command == "capture":
        return capture(args)
    if args.command == "compare":
        return compare(args.base, args.head)
    if args.command == "rows":
        return rows(args)
    return run(args)


if __name__ == "__main__":
    raise SystemExit(main())
