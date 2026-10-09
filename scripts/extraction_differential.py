"""Criterion (E) of fix/tailor-review: résumé extraction returns exactly what origin/main returns.

Backend. ``git show <ref>:backend/routes/tailor.py`` (default ref origin/main) is loaded into a
temporary module beside this working tree's ``backend.routes.tailor``. For every résumé of
tests/fixtures/extraction_differential_cases.json, both modules' route functions
(``extract_bullets`` for /api/tailor/extract-bullets, ``structure_resume`` for /api/tailor/structure)
run on the same text with the same stubbed provider, and their responses are compared field by
field, except ``pipeline_version`` (each pipeline's own stamp: w13.6 on main) and ``generated_at``
(a clock). Each résumé runs:

  * with no provider configured: the local fallback (``_heuristic_bullets``, ``_heuristic_structure``);
  * with a provider that answers every chunk with each reply below, built from the text the
    model is shown (the chunk), or spelled out in the case ("answers", "sections");
  * with a provider that gives no answer, an empty one, or raises.

Replies: the chunk's rows as written and without what leads them (a glyph, a list number, an
ordinal), adjacent rows joined, each row cut in two at its middle space (a cut can part a status
from its claim), each row with a word the résumé lacks, duplicates in another case, the rows inside a
```json fence, prose instead of JSON, and JSON of the wrong shape. A structure reply puts the rows
under the chunk's first row as heading, under "Publications", under a heading in the other language,
under an empty heading with an unknown kind, beside an empty skills section and a non-object. A résumé
longer than one chunk (8,000 characters) runs once with a rate limiter that grants every later
dispatch and once with one that refuses it.

HTTP. The route functions skip what each module's router does before them: this tree's router refuses
a body with more commas than its route class allows (backend.lib.request_body), main's parses every
body. So each résumé also goes, as JSON, through each module's own router in an app of its own (no
provider, and the chunk's rows as the reply), with the status and body compared; so do résumés of
50,001, 59,985 and 60,000 commas, of 60,000 brackets, and one of 60,001 characters, which both refuse.

Both modules import the same backend.lib and backend.schemas modules, so the harness also checks that
what the extraction code calls has the same source here as at the ref: backend/lib/resume_input.py and
backend/lib/llm_budget.py whole, run_blocking and BlockingWorkTimeout in backend/lib/blocking.py, and the
request and response classes in backend/schemas.py.

Frontend. The browser reads a résumé into lines in frontend/src/lib/resume-input.ts and
frontend/src/lib/pdf-parser.ts; TailorModal.tsx prefills its editor with extractBulletLines and splits
the editor into the lines it sends with parseBullets. The harness checks that their source is the same
as at the ref, that the renovation views read a section's
heading with the same expressions as at the ref (``section.heading || section.kind`` and the like, and
no call such as a heading rewrite), and that frontend/src/lib/renovation-review.ts reads no résumé text. A same source is a same output, so these are compared as source, not run.

A pull-request check, not a test: once the branch is merged, main compared with itself proves nothing,
and a later change to extraction is meant to differ. Run from the repository root (needs the ref, e.g.
after ``git fetch origin main``; --ref 6e7530d is the merge base the branch was measured against):

    python scripts/extraction_differential.py [--ref origin/main] [--cases <fixture>] [--list] [--no-http]

Prints the counts and one line per difference (all with --list, else the first 20); exits 1 when any
comparison differs. Provider-free and deterministic.
"""
from __future__ import annotations

import argparse
import ast
import asyncio
import importlib.util
import json
import logging
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi import FastAPI  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from backend.lib import llm_budget  # noqa: E402
from backend.routes import tailor as branch_tailor  # noqa: E402
from backend.schemas import ExtractBulletsRequest, StructureResumeRequest  # noqa: E402

CASES = ROOT / "tests" / "fixtures" / "extraction_differential_cases.json"
SKIP_FIELDS = {"pipeline_version", "generated_at"}
CHUNK = 8_000
# What a row may open with before its words, for the reply that strips it: a glyph or mark run, a
# list number or letter, a roman numeral, a CJK ordinal.
_LEAD = re.compile(r"^\s*(?:[^\w\s(（]+|\(?(?:\d{1,2}|[a-zA-Z]|[ivxIVX]{1,4}|[一二三四五六七八九十]{1,2})[.)、．）]"
                   r"|[（(](?:\d{1,2}|[一二三四五六七八九十]{1,2}|[a-z])[)）]|第[一二三四五六七八九十]+[，,、]|[①-⑳⑴-⒇ⅰ-ⅻⅠ-Ⅻ])\s*")
DEPENDENCIES = [  # (file, names compared; None compares the whole file)
    ("backend/lib/resume_input.py", None),
    ("backend/lib/llm_budget.py", None),
    ("backend/lib/blocking.py", ["run_blocking", "BlockingWorkTimeout", "BlockingWorkOverloaded", "SINGLE_LLM_TIMEOUT_SECONDS",
                                 "BLOCKING_AI_MAX_WORKERS", "BLOCKING_AI_MAX_PENDING", "_BLOCKING_AI_EXECUTOR",
                                 "_BLOCKING_AI_CAPACITY", "_bounded_int"]),
    ("backend/schemas.py", ["ExtractBulletsRequest", "ExtractBulletsResponse", "StructureResumeRequest",
                            "StructureResumeResponse", "ResumeSection", "ResumeBullet", "ResumeProcessingCoverage"]),
]
FRONTEND_SAME_FILES = ["frontend/src/lib/resume-input.ts", "frontend/src/lib/pdf-parser.ts"]
TAILOR_MODAL = "frontend/src/components/TailorModal.tsx"
HEADING_VIEWS = ["frontend/src/components/ResumeRenovationModal.tsx", "frontend/src/components/RenovationHistory.tsx"]
RENOVATION_REVIEW = "frontend/src/lib/renovation-review.ts"
# Every expression a view reads a section's heading with: "section.heading || section.kind",
# "s.heading.toUpperCase()", a call that takes the section (shownHeading(s, ...)), and so on.
_HEADING_READ = re.compile(r"[\w.]*\.heading\b(?:\s*\|\|\s*[\w.]+)?(?:\.\w+\(\))?|\w*[Hh]eading\w*\(")


def git_show(ref: str, path: str) -> str:
    return subprocess.run(["git", "show", f"{ref}:{path}"], cwd=ROOT, capture_output=True, text=True, check=True).stdout


def load_ref_tailor(ref: str):
    """The ref's backend/routes/tailor.py as a module of its own, importing this tree's backend packages."""
    source = git_show(ref, "backend/routes/tailor.py")
    with tempfile.TemporaryDirectory() as scratch:
        path = Path(scratch) / "tailor_at_ref.py"
        path.write_text(source)
        spec = importlib.util.spec_from_file_location("tailor_at_ref", path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
    return module


def _definitions(source: str) -> dict[str, str]:
    tree, out = ast.parse(source), {}
    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            out[node.name] = ast.get_source_segment(source, node)
        elif isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name):
                    out[target.id] = ast.get_source_segment(source, node)
    return out


def dependency_differences(ref: str) -> list[str]:
    out = []
    for path, names in DEPENDENCIES:
        here, there = (ROOT / path).read_text(), git_show(ref, path)
        if names is None:
            if here != there:
                out.append(f"{path}: source differs")
            continue
        mine, theirs = _definitions(here), _definitions(there)
        out += [f"{path}: {name} differs" for name in names if mine.get(name) != theirs.get(name) or name not in mine]
    return out


def _tailor_modal_reader(source: str) -> str:
    """BULLET_PREFIX_RE, extractBulletLines and parseBullets as TailorModal.tsx declares them."""
    prefix = re.search(r"^const BULLET_PREFIX_RE = .*$", source, re.M)
    functions = []
    for name in ("extractBulletLines", "parseBullets"):
        start = source.index(f"function {name}(")
        functions.append(source[start:source.index("\n}\n", start) + 3])
    return "\n".join([prefix.group(0) if prefix else "", *functions])


def frontend_differences(ref: str) -> list[str]:
    out = [f"{path}: source differs" for path in FRONTEND_SAME_FILES if (ROOT / path).read_text() != git_show(ref, path)]
    if _tailor_modal_reader((ROOT / TAILOR_MODAL).read_text()) != _tailor_modal_reader(git_show(ref, TAILOR_MODAL)):
        out.append(f"{TAILOR_MODAL}: BULLET_PREFIX_RE, extractBulletLines or parseBullets differs")
    for path in HEADING_VIEWS:
        mine, theirs = Counter(_HEADING_READ.findall((ROOT / path).read_text())), Counter(_HEADING_READ.findall(git_show(ref, path)))
        out += [f"{path}: reads a heading as {expression} {count - theirs[expression]} more times than the ref"
                for expression, count in sorted(mine.items()) if count > theirs[expression]]
        out += [f"{path}: reads a heading as {expression} {count - mine[expression]} fewer times than the ref"
                for expression, count in sorted(theirs.items()) if count > mine[expression]]
    if re.search(r"resume|résumé|\.split\(", (ROOT / RENOVATION_REVIEW).read_text(), re.I):
        out.append(f"{RENOVATION_REVIEW}: reads résumé text")
    return out


# ------------------------------------------------------------------ replies


def _rows(text: str) -> list[str]:
    return [row.strip() for row in text.splitlines() if row.strip()]


def _unled(row: str) -> str:
    return _LEAD.sub("", row, count=1).strip() or row


def _halves(row: str) -> list[str]:
    words = row.split(" ")
    if len(words) < 2:
        return [row[: len(row) // 2], row[len(row) // 2:]] if len(row) > 1 else [row]
    middle = len(words) // 2
    return [" ".join(words[:middle]), " ".join(words[middle:])]


def line_replies(chunk: str) -> dict[str, list]:
    rows = _rows(chunk)
    unled = [_unled(row) for row in rows]
    return {
        "rows": unled,
        "raw rows": rows,
        "joined": [f"{a} {b}" for a, b in zip(unled, unled[1:], strict=False)] or unled,
        "cut": [half for row in unled for half in _halves(row)],
        "added word": [f"{row} using Kubernetes" for row in unled],
        "duplicates": [*unled, *(row.upper() for row in unled), *(row.lower() for row in unled)],
    }


def section_reply(lines: list, chunk: str) -> dict:
    rows = _rows(chunk)
    half = len(lines) // 2
    other = "科研经历" if not re.search(r"[一-鿿]", chunk) else "Research Experience"
    return {"sections": [
        {"heading": rows[0] if rows else "", "kind": "experience", "bullets": lines[:half]},
        {"heading": "Publications", "kind": "research", "bullets": lines[half:]},
        {"heading": other, "kind": "projects", "bullets": lines[:1]},
        {"heading": "", "kind": "nonsense", "bullets": lines[-1:]},
        {"heading": "Skills", "kind": "skills", "bullets": []},
        "not a section",
    ]}


RAW_REPLIES = {
    "fenced": lambda body: "```json\n" + body + "\n```",
    "prose": lambda body: "Here are the bullets you asked for:\n" + body,
    "list": lambda body: "[" + body + "]",
    "wrong types": lambda body: json.dumps({"bullets": [1, None, {"x": 1}, ["a"]], "sections": [1, None, {"bullets": 7}]}),
    "string": lambda body: json.dumps({"bullets": "Built a parser", "sections": "Built a parser"}),
}
FAILURES = {"no answer": lambda: None, "empty answer": lambda: "", "raises": lambda: (_ for _ in ()).throw(RuntimeError("boom"))}


def _chunk_of(messages) -> tuple[str, str]:
    content = messages[1]["content"]
    route = "structure" if content.endswith("Structure it now.") else "extract"
    body = content.removeprefix("RESUME:\n")
    return route, body.rsplit("\n\n", 1)[0]


def provider(variant: str, case: dict):
    """A chat_completion stub answering each chunk with reply ``variant``."""
    def answer(messages, **kwargs):
        route, chunk = _chunk_of(messages)
        if variant in FAILURES:
            return FAILURES[variant]()
        kind, _, index = variant.partition("#")
        if kind == "sections":
            return json.dumps({"sections": case["sections"][int(index)]}, ensure_ascii=False)
        if kind == "answers":
            lines = case["answers"][int(index)]
        elif kind in RAW_REPLIES:
            lines = line_replies(chunk)["rows"]
            body = (json.dumps({"sections": section_reply(lines, chunk)["sections"]}, ensure_ascii=False)
                    if route == "structure" else json.dumps({"bullets": lines}, ensure_ascii=False))
            return RAW_REPLIES[kind](body)
        else:
            lines = line_replies(chunk)[kind]
        if route == "structure":
            return json.dumps(section_reply(lines, chunk), ensure_ascii=False)
        return json.dumps({"bullets": lines}, ensure_ascii=False)
    return answer


def variants(case: dict) -> list[str]:
    names = [*line_replies("")]
    names += [f"answers#{index}" for index in range(len(case.get("answers", [])))]
    names += [f"sections#{index}" for index in range(len(case.get("sections", [])))]
    return [*names, *RAW_REPLIES, *FAILURES]


# ------------------------------------------------------------------ runs


def _response(result) -> object:
    if isinstance(result, BaseException):
        return {"exception": type(result).__name__, "message": str(result)}
    return {key: value for key, value in result.model_dump(mode="json").items() if key not in SKIP_FIELDS}


async def _call(module, route: str, text: str, *, configured: bool, reply, grant: bool):
    module.is_configured = lambda: configured
    module.model_for = lambda *args, **kwargs: {}
    module.chat_completion = reply or (lambda *args, **kwargs: None)
    request = SimpleNamespace(state=SimpleNamespace(reserve_llm_dispatch=lambda: grant))
    try:
        if route == "extract":
            return _response(await module.extract_bullets(ExtractBulletsRequest(resume_text=text), request))
        return _response(await module.structure_resume(StructureResumeRequest(resume_text=text, locale="en"), request))
    except Exception as exc:  # noqa: BLE001 - an exception is a response to compare too
        return _response(exc)


async def compare(ref_module, cases: list[dict]) -> tuple[Counter, list[str]]:
    counts: Counter = Counter()
    differences: list[str] = []
    llm_budget.exhausted = lambda: False
    for case in cases:
        text = case["resume"]
        grants = (True, False) if len(text) > CHUNK else (True,)
        runs = [("no provider", False, None, True)]
        runs += [(name, True, provider(name, case), grant) for name in variants(case) for grant in grants]
        for name, configured, reply, grant in runs:
            for route in ("extract", "structure"):
                if route == "extract" and name.startswith("sections#"):
                    continue
                ref_out = await _call(ref_module, route, text, configured=configured, reply=reply, grant=grant)
                here_out = await _call(branch_tailor, route, text, configured=configured, reply=reply, grant=grant)
                counts["comparisons"] += 1
                counts[f"{route} comparisons"] += 1
                if ref_out != here_out:
                    counts["differences"] += 1
                    differences.append(f"{case['id']!r} {route} [{name}{'' if grant else ', later dispatch refused'}]: "
                                       f"ref {json.dumps(ref_out, ensure_ascii=False)[:300]} | "
                                       f"here {json.dumps(here_out, ensure_ascii=False)[:300]}")
                elif "exception" not in ref_out:
                    lines = ref_out.get("bullets") or [b for s in ref_out.get("sections", []) for b in s["bullets"]]
                    counts["comparisons returning lines"] += bool(lines)
        counts["cases"] += 1
    return counts, differences


HTTP_RESUMES = {
    "50,001 commas": "Built a robot, " + "," * 50_001,
    "a line, then 59,985 commas": "Built a robot.\n" + "," * 59_985,
    "60,000 commas": "," * 60_000,
    "60,000 brackets": "[" * 60_000,
    "60,001 characters": "Built a robot.\n" * 4_000 + "x",
}


def compare_http(ref_module, cases: list[dict]) -> tuple[Counter, list[str]]:
    """Each résumé, as JSON, through each module's own router: no provider, then the chunk's rows."""
    clients = {}
    for name, module in (("ref", ref_module), ("here", branch_tailor)):
        app = FastAPI()
        app.include_router(module.router, prefix="/api")
        clients[name] = TestClient(app)
    texts = [(case["id"], case["resume"]) for case in cases] + list(HTTP_RESUMES.items())
    counts: Counter = Counter()
    differences: list[str] = []
    for ident, text in texts:
        for name, configured, reply in (("no provider", False, None), ("rows", True, provider("rows", {}))):
            for route, body in (("extract-bullets", {"resume_text": text}),
                                ("structure", {"resume_text": text, "locale": "en"})):
                answers = []
                for side in ("ref", "here"):
                    module = ref_module if side == "ref" else branch_tailor
                    module.is_configured = lambda configured=configured: configured
                    module.model_for = lambda *args, **kwargs: {}
                    module.chat_completion = reply or (lambda *args, **kwargs: None)
                    response = clients[side].post(f"/api/tailor/{route}", content=json.dumps(body, ensure_ascii=False),
                                                  headers={"content-type": "application/json"})
                    payload = response.json()
                    if isinstance(payload, dict):
                        payload = {key: value for key, value in payload.items() if key not in SKIP_FIELDS}
                    answers.append((response.status_code, payload))
                counts["http comparisons"] += 1
                counts[f"http {answers[0][0]}"] += 1
                if answers[0] != answers[1]:
                    counts["http differences"] += 1
                    differences.append(f"HTTP {ident!r} {route} [{name}]: ref {answers[0][0]} "
                                       f"{json.dumps(answers[0][1], ensure_ascii=False)[:200]} | here {answers[1][0]} "
                                       f"{json.dumps(answers[1][1], ensure_ascii=False)[:200]}")
    return counts, differences


def run(ref: str = "origin/main", cases_path: Path = CASES, http: bool = True) -> dict:
    """Every count and difference."""
    cases = json.loads(cases_path.read_text())["cases"]
    ref_module = load_ref_tailor(ref)
    saved = {name: getattr(branch_tailor, name) for name in ("is_configured", "model_for", "chat_completion")}
    exhausted, disabled = llm_budget.exhausted, logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    try:
        counts, differences = asyncio.run(compare(ref_module, cases))
        if http:
            http_counts, http_differences = compare_http(ref_module, cases)
            counts.update(http_counts)
            differences += http_differences
    finally:
        for name, value in saved.items():
            setattr(branch_tailor, name, value)
        llm_budget.exhausted = exhausted
        logging.disable(disabled)
    return {"counts": counts, "differences": differences, "groups": Counter(case["group"] for case in cases),
            "dependencies": dependency_differences(ref), "frontend": frontend_differences(ref)}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--ref", default="origin/main", help="the git ref whose extraction is the standard")
    parser.add_argument("--cases", default=str(CASES), help="the fixture of résumés")
    parser.add_argument("--list", action="store_true", help="print every difference")
    parser.add_argument("--no-http", action="store_true", help="skip the pass through each module's router")
    args = parser.parse_args()
    result = run(args.ref, Path(args.cases), http=not args.no_http)
    counts = result["counts"]
    print(f"ref {args.ref} ({git_show_rev(args.ref)}): {counts['cases']} résumés "
          f"({', '.join(f'{group} {n}' for group, n in sorted(result['groups'].items()))})")
    print(f"backend comparisons: {counts['comparisons']} (extract {counts['extract comparisons']}, "
          f"structure {counts['structure comparisons']}; {counts['comparisons returning lines']} return lines); "
          f"differences: {counts['differences']}")
    if counts["http comparisons"]:
        statuses = ", ".join(f"{key.split()[1]} {value}" for key, value in sorted(counts.items())
                             if key.startswith("http ") and key.split()[1].isdigit())
        print(f"HTTP comparisons through each module's router: {counts['http comparisons']} (main's status: {statuses}); "
              f"differences: {counts['http differences']}")
    print(f"shared backend modules that differ from the ref: {len(result['dependencies'])}")
    print(f"frontend résumé readers and heading views that differ from the ref: {len(result['frontend'])}")
    for line in (result["differences"] if args.list else result["differences"][:20]):
        print(f"  DIFF {line}")
    for line in result["dependencies"] + result["frontend"]:
        print(f"  DIFF {line}")
    return 1 if counts["differences"] or counts["http differences"] or result["dependencies"] or result["frontend"] else 0


def git_show_rev(ref: str) -> str:
    return subprocess.run(["git", "rev-parse", "--short", ref], cwd=ROOT, capture_output=True, text=True,
                          check=True).stdout.strip()


if __name__ == "__main__":
    raise SystemExit(main())
