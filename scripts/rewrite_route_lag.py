"""Longest event-loop stall per résumé-rewrite route, driving the real HTTP handlers at the input caps.

Each request goes through backend.main.app over httpx.ASGITransport with the provider
stubbed: generation returns a rewrite for every unit (verb_first, so the contract and the
claim locks read it), and the review accepts every pair. While a request runs, the event
loop wakes every millisecond (the longest wake-up delay is the longest stall) and a
heartbeat asks /api/tailor/status again and again (the longest gap between answers is
what another student would have waited). Request bodies are encoded before the clock
starts and responses decoded after it stops, so only server work is timed.

Routes: /api/tailor, /api/tailor/bullet, /api/tailor/renovate,
/api/tailor/full-target/suggestions and /api/tailor/full-target/selection-plan.
Caps: 12 bullets x 500 characters and 6,000 characters of sources per /api/tailor request;
a 500-character bullet on a 6,000-character base_text and a 300-character instruction for
/bullet; 15 sections, 100 bullets, 8 foregrounded 500-character bullets and a 1 MiB body for
/renovate; 8 experience lines (6,000 characters together) and 12 fact lines (16,000 with them)
of 20 selected units, 100 entries in the draft, and a 2 MiB draft for full target.

Run from the repository root:
    python scripts/rewrite_route_lag.py [--threshold 0.25] [--only TEXT] [--concurrent 1,4,10] [--no-fills]
                                        [--switch-interval SECONDS]
--concurrent sends that many identical requests at once; a comma-separated list measures every
case at each level in turn and prints the worst stall per route for each. Ten at once is one
client's limit for /api/tailor* (backend/main.py RATE_LIMITS: "/api/tailor": (10, 60)).
Deterministic inputs; timings vary with load, so a case over the threshold is re-run (up to
three times) and reported with its best run.

--switch-interval sets sys.setswitchinterval for the run (Python's default is 0.005 s): how long
a thread may hold the GIL while another waits for it. The routes' checks run on worker threads
(backend.lib.blocking); a status gap that shrinks with the interval while the stall does not
is the event loop waiting for the GIL behind them.
"""
from __future__ import annotations

import argparse
import asyncio
import gc
import hashlib
import json
import os
import sys
import time
from copy import deepcopy
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))
os.environ.setdefault("OFE_DISABLE_RATE_LIMIT", "1")

import httpx  # noqa: E402

from backend import main as main_module  # noqa: E402
from backend.lib import evidence_map as em  # noqa: E402
from backend.lib import release_scope  # noqa: E402
from backend.lib import target_resume_ai as engine  # noqa: E402
from backend.lib.target_resume_ai_validation import confirmed_document, fingerprint, units_for  # noqa: E402
from backend.routes import tailor  # noqa: E402
from backend.routes import target_resume_ai as full_route  # noqa: E402

app = main_module.app
OPPORTUNITY = {
    "id": "probe-target", "title": "Research Tools", "organization": "Example Lab",
    "source_url": "https://example.edu/lab",
    "description_clean": "Research Python parsers. Build EEG data pipelines with the team. Analyze survey data in R.",
    "eligibility": {"skills_required": ["Python"]}, "source_type": "campus_program",
    "opportunity_type": "research", "metadata": {"is_active": True},
}
PROFILE = {"name": "Sample Student", "school": "UIUC", "year": "sophomore", "major": "Psychology",
           "hard_skills": [{"name": "R", "level": "experienced"}], "coursework": ["PSYC 238"],
           "research_interests_text": "human factors"}
# "for" and "the": the English evidence round 4's default keep asks of a Latin-script line, so the
# claim locks still read every English case (without it the contract keeps the line before them).
OPENER, ZH_OPENER = "Responsible for building the ", "负责"


def fit(unit: str, size: int) -> str:
    text = (unit * (size // len(unit) + 1))[:size]
    return text if text.strip() else (unit * (size // len(unit) + 1))[:size]


def bullet(unit: str, size: int) -> str:
    """A line the contract lets verb_first rewrite: a weak opener, then the adversarial run."""
    zh = any("一" <= ch <= "鿿" for ch in unit) and not any(ch.isascii() and ch.isalpha() for ch in unit)
    opener = ZH_OPENER if zh else OPENER
    return opener + fit(unit, size - len(opener))


def verb_first(text: str) -> str:
    if text.startswith(OPENER):
        return "Built the " + text[len(OPENER):]
    if text.startswith(ZH_OPENER):
        return text[len(ZH_OPENER):]
    return text


# ----------------------------------------------------------------------------- stubs

def _accept(pairs, deadline=None):
    for pair in pairs:
        for link in pair.links:
            link.entailed = True
    return ["accepted"] * len(pairs)


def _review_or(generate):
    def model(messages, **kwargs):
        if messages[0]["content"].startswith("FAITHFULNESS REVIEW"):
            pairs = json.loads(messages[1]["content"])["pairs"]
            return json.dumps({"verdicts": [{"index": pair["index"], "changes": "reordered", "faithful": True,
                                             "links": [{"id": link["id"], "entailed": True}
                                                       for link in pair.get("links", [])], "problem": ""}
                                            for pair in pairs]})
        return generate(messages)
    return model


def _tailor_generate(messages):
    content = messages[1]["content"]
    if "DATA (JSON):\n" not in content:  # the renovation plan
        return None
    units = json.loads(content.split("DATA (JSON):\n", 1)[1])["units"]
    return json.dumps({"bullets": [{"unit_id": unit["unit_id"], "links": [], "decision": "rewrite",
                                    "ops": [{"op": "verb_first"}], "text": verb_first(unit.get("current", unit["original"])),
                                    "keep_reason": None} for unit in units]})


def _plan_model(messages, **kwargs):
    """The renovation plan foregrounds every bullet it is shown."""
    ids = []
    for line in messages[1]["content"].splitlines():
        line = line.strip()
        if line.startswith("[section "):
            ids.append((line.split()[1].rstrip("]"), []))
        elif line.startswith("- [") and ids:
            ids[-1][1].append(line[3:].split("]", 1)[0])
    return json.dumps({"sections": [{"id": sid, "bullets": [{"id": bid, "action": "foreground"} for bid in bids]}
                                    for sid, bids in ids]})


def _full_generate(messages):
    units = json.loads(messages[1]["content"])["units"]
    rows = []
    for unit in units:
        if unit["kind"] == "experience":
            rows.append({"unit_id": unit["unit_id"], "priority": "high", "reason": "method_relevance", "links": [],
                         "decision": "rewrite", "ops": [{"op": "verb_first"}], "text": verb_first(unit["original"]),
                         "keep_reason": None})
        else:
            rows.append({"unit_id": unit["unit_id"], "priority": "normal", "reason": "method_relevance", "links": [],
                         "decision": "keep", "ops": [], "text": None, "keep_reason": "no_link"})
    return json.dumps({"units": rows})


def install_stubs() -> None:
    main_module.feature_enabled = lambda feature: True
    release_scope.feature_enabled = lambda feature: True
    for module in (tailor, full_route):
        module.load_opportunities_by_id = lambda: {OPPORTUNITY["id"]: deepcopy(OPPORTUNITY)}
        module.is_configured = lambda: True
    tailor._schedule_usage = lambda *args: None
    tailor.model_for = lambda *args: {}
    em.model_for = lambda *args: {}
    engine.model_for = lambda *args: {}
    engine.llm_budget.exhausted = lambda: False

    def tailor_model(messages, **kwargs):
        if messages[0]["content"].startswith("You plan how to REORGANIZE"):
            return _plan_model(messages)
        return _review_or(_tailor_generate)(messages)

    tailor.chat_completion = tailor_model
    em.chat_completion = _review_or(_tailor_generate)
    engine.chat_completion = _review_or(_full_generate)


# ------------------------------------------------------------------------- documents

def _fact(ident, value):
    return {"id": ident, "revision": 1, "status": "confirmed", "value": value, "source": {"kind": "manual"}}


def full_doc(experiences: list[str], facts: list[str], *, extra_entries: int = 0, line_text: str | None = None) -> dict:
    """A confirmed v4 draft: one activity with ``experiences`` (manual entries) and ``facts`` as skills."""
    raw = "Resume text."
    signature = hashlib.sha256(raw.encode()).hexdigest()
    entries = [{"id": f"exp-{i}", "revision": 1, "status": "confirmed", "text": text, "source": {"kind": "manual"}}
               for i, text in enumerate(experiences)]
    entries += [{"id": f"more-{i}", "revision": 1, "status": "confirmed", "text": fit("Built a parser. ", 580),
                 "source": {"kind": "manual"}} for i in range(extra_entries)]
    master = {"version": 1, "id": "master", "revision": 1, "source_signature": signature,
              "basics": {"name": _fact("name", "Private Student"), "links": []}, "education": [],
              "activities": [{"id": "project", "kind": "project", "title": _fact("title", "Robot project"),
                              "details": [{"id": entry["id"], "revision": 1} for entry in entries]}],
              "publications": [], "skills": [_fact(f"skill-{i}", value) for i, value in enumerate(facts)],
              "other_sections": [], "section_order": ["basics", "education", "activities", "publications", "skills"],
              "unmapped_ranges": []}
    snapshot = {"resume_text": raw, "experience_entries": entries, "resume_master": master}
    target = full_route.authoritative_target(OPPORTUNITY)
    doc = {"kind": "full_resume", "version": 1, "id": "draft", "opportunity_id": OPPORTUNITY["id"],
           "base": {"master_id": "master", "master_revision": 1, "source_signature": signature,
                    "profile_signature": "v1:sha256:" + "a" * 64, "target_signature": fingerprint(target)},
           "base_snapshot": snapshot, "target_snapshot": target, "document": confirmed_document(snapshot, signature)}
    for section in doc["document"]["sections"]:
        section["included"] = True
        for block in section["blocks"]:
            block["included"] = True
            for row in block["lines"]:
                row.update(text=row["original"], included=True)
    if line_text is not None:
        doc["document"]["sections"][1]["blocks"][0]["lines"][0]["text"] = line_text
    return doc


def full_payload(doc: dict, *, plan: bool = False, max_units: int = 20) -> dict:
    units = units_for(doc)[0]
    experiences = [u["unit_id"] for u in units if u["evidence"]["kind"] == "experience" and u["evidence"]["id"].startswith("exp-")]
    facts = [u["unit_id"] for u in units if u["evidence"]["kind"] == "fact"]
    body = {"version": 1, "request_id": "probe", "locale": "en", "draft": doc, "document_signature": fingerprint(doc)}
    if plan:
        body["options"] = {"target_pages": 1}
    else:
        body["selected_unit_ids"] = (experiences[:8] + facts)[:max_units]
    return body


# ----------------------------------------------------------------------------- cases

TAILOR_FILLS = [" ", "a", "中", "a, ", "a，", "x, a b, ", "I, ", "我", "的", "per ", "3余", "led y. never led z. ",
                "developed with my team ", "helped aing or bing ", "not helped ", "正在撰写论文，", "开发中的系统，",
                "with two teammates; I designed ", "Sam, a senior student, revised it; ", "about 40 samples, ",
                "a中", "(", "\u3000", "a\u00a0", "led ", "lead ", "负责", "完成", "a。", "I designed ",
                "Built X with a friend; I wrote Y. ", "with fellow ", "two other students "]


def tailor_cases(fills):
    for fill in fills:
        twelve = [bullet(fill, 500) for _ in range(12)]
        yield f"/api/tailor 12x500 {fill!r}", "/api/tailor", {
            "profile": PROFILE, "opportunity_id": OPPORTUNITY["id"], "locale": "en", "original_bullets": twelve}
        yield f"/api/tailor 1x500 + 6000 source {fill!r}", "/api/tailor", {
            "profile": PROFILE, "opportunity_id": OPPORTUNITY["id"], "locale": "en",
            "original_bullets": [bullet(fill, 500)], "source_bullets": [OPENER + fit(fill, 6000 - len(OPENER))]}
        yield f"/api/tailor 12x500 + 12x500 sources {fill!r}", "/api/tailor", {
            "profile": PROFILE, "opportunity_id": OPPORTUNITY["id"], "locale": "en",
            "original_bullets": twelve, "source_bullets": [OPENER + fit(fill, 500 - len(OPENER))] * 12}
        yield f"/api/tailor/bullet {fill!r}", "/api/tailor/bullet", {
            "profile": PROFILE, "opportunity_id": OPPORTUNITY["id"], "locale": "en",
            "current_text": bullet(fill, 500), "base_text": OPENER + fit(fill, 6000 - len(OPENER)),
            "instruction": fit(fill, 300)}
        sections = [{"id": f"s{s}", "heading": fit(fill, 120), "kind": "experience",
                     "bullets": [{"id": f"s{s}b{b}", "text": bullet(fill, 500)} for b in range(7 if s < 14 else 2)]}
                    for s in range(15)]
        yield f"/api/tailor/renovate 15x100 {fill!r}", "/api/tailor/renovate", {
            "profile": PROFILE, "opportunity_id": OPPORTUNITY["id"], "locale": "en", "sections": sections}
        experiences = [bullet(fill, 750) for _ in range(8)]
        facts = [fit(fill, 833) for _ in range(12)]
        yield f"full-target 8 exp x 750 + 12 facts {fill!r}", "/api/tailor/full-target/suggestions", full_payload(
            full_doc(experiences, facts))
        yield f"full-target 1 exp x 6000 {fill!r}", "/api/tailor/full-target/suggestions", full_payload(
            full_doc([bullet(fill, 6000)], ["Python"]))


NESTED = [[[[[[[[[[[[[[[[[[[[[[[[[[[[[[0]]]]]]]]]]]]]]]]]]]]]]]]]]]]]]


def _junk(kind: str, size: int):
    """About ``size`` bytes of compact JSON with as many containers as fit: what json.loads,
    pydantic and a tree walk pay for per node rather than per byte."""
    if kind == "nested":
        return [NESTED] * (size // 62)
    if kind == "empty lists":
        return [[]] * (size // 3)
    if kind == "empty dicts":
        return [{}] * (size // 3)
    return [0] * (size // 2)


def validation_cases():
    """Request shapes that stress what runs on the event loop before any worker: parsing and validation."""
    one_mib, two_mib = 1024 * 1024 - 2048, 2 * 1024 * 1024 + 64 * 1024 - 2048
    tailor_body = {"profile": PROFILE, "opportunity_id": OPPORTUNITY["id"], "locale": "en"}
    yield "/api/tailor 1 MiB of blank bullets", "/api/tailor", {
        **tailor_body, "original_bullets": [""] * (one_mib // 3)}
    yield "/api/tailor 1 MiB of sources", "/api/tailor", {
        **tailor_body, "original_bullets": ["Built a robot."], "source_bullets": [0] * (one_mib // 2)}
    for kind in ("nested", "empty lists", "flat ints"):
        yield f"/api/tailor 1 MiB {kind} in an unknown field", "/api/tailor", {
            **tailor_body, "original_bullets": ["Built a robot."], "padding": _junk(kind, one_mib)}
        yield f"/api/tailor/bullet 1 MiB {kind} in an unknown field", "/api/tailor/bullet", {
            **tailor_body, "current_text": "Built a robot.", "padding": _junk(kind, one_mib)}
        yield f"/api/tailor/renovate 1 MiB {kind} in an unknown field", "/api/tailor/renovate", {
            **tailor_body, "sections": [], "padding": _junk(kind, one_mib)}
    yield "/api/tailor/bullet 60,000-character current_text", "/api/tailor/bullet", {
        **tailor_body, "current_text": "a " * 30000, "base_text": "a " * 30000}
    big = "a " * 4900
    sections = [{"id": f"s{s}", "heading": "h", "kind": "experience",
                 "bullets": [{"id": f"s{s}b{b}", "text": big if b else bullet("a ", 500)} for b in range(7 if s < 14 else 2)]}
                for s in range(15)]
    yield "/api/tailor/renovate 1 MiB of bullets", "/api/tailor/renovate", {**tailor_body, "sections": sections}
    yield "full-target 2 MiB draft (one line's text)", "/api/tailor/full-target/suggestions", full_payload(
        full_doc([bullet("a ", 6000)], ["Python"], line_text="M" * (2 * 1024 * 1024 - 80 * 1024)))
    yield "full-target 100 entries, 20 units", "/api/tailor/full-target/suggestions", full_payload(
        full_doc([bullet("a ", 750) for _ in range(8)], [fit("a ", 833) for _ in range(12)], extra_entries=92))
    for kind in ("nested", "empty lists", "empty dicts", "flat ints"):
        junk = {"kind": "full_resume", "junk": _junk(kind, two_mib - 300)}
        yield f"full-target 2 MiB junk draft ({kind})", "/api/tailor/full-target/suggestions", {
            "version": 1, "request_id": "probe", "locale": "en", "draft": junk,
            "document_signature": "v1:sha256:" + "0" * 64, "selected_unit_ids": ["line-1"]}
        yield f"selection-plan 2 MiB junk draft ({kind})", "/api/tailor/full-target/selection-plan", {
            "version": 1, "request_id": "probe", "locale": "en", "draft": junk,
            "document_signature": "v1:sha256:" + "0" * 64, "options": {"target_pages": 1}}
    yield "selection-plan 2 MiB draft (one line's text)", "/api/tailor/full-target/selection-plan", full_payload(
        full_doc([bullet("a ", 6000)], ["Python"], line_text="M" * (2 * 1024 * 1024 - 80 * 1024)), plan=True)


# ----------------------------------------------------------------------------- probe

async def _probe(path: str, content: bytes, concurrent: int):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://probe", timeout=300) as client:
        stop = asyncio.Event()
        lag = {"worst": 0.0}
        gaps: list[float] = []

        async def wake():
            while not stop.is_set():
                before = time.perf_counter()
                await asyncio.sleep(0.001)
                lag["worst"] = max(lag["worst"], time.perf_counter() - before - 0.001)

        async def heartbeat():
            last = time.perf_counter()
            while not stop.is_set():
                await client.get("/api/tailor/status")
                now = time.perf_counter()
                gaps.append(now - last)
                last = now
                await asyncio.sleep(0.005)

        waker, beat = asyncio.create_task(wake()), asyncio.create_task(heartbeat())
        await asyncio.sleep(0.02)
        began = time.perf_counter()
        responses = await asyncio.gather(*(client.post(path, content=content, headers={"content-type": "application/json"})
                                           for _ in range(concurrent)))
        wall = time.perf_counter() - began
        stop.set()
        await asyncio.gather(waker, beat)
        return responses[0], lag["worst"], max(gaps) if gaps else 0.0, wall


def summary(response: httpx.Response) -> str:
    try:
        body = response.json()
    except ValueError:
        return f"{response.status_code}"
    if response.status_code != 200:
        return f"{response.status_code} {str(body)[:80]}"
    if "tailored_bullets" in body:
        rows = body["tailored_bullets"]
        return "200 " + ",".join(sorted({row["status"] + ":" + str(row["reason_code"]) for row in rows}))
    if "receipts" in body:
        return "200 " + ",".join(sorted({row["status"] + ":" + str(row["reason_code"]) for row in body["receipts"]}))
    if "sections" in body:
        bullets = [b for s in body["sections"] for b in s["bullets"]]
        return f"200 {sum(b['current'] == 0 for b in bullets)} rewritten, notes {sorted({str(b['note']) for b in bullets})}"
    if "changed" in body:
        return f"200 {body['status']}:{body.get('reason_code')}"
    if "items" in body:
        return f"200 complete={body['complete']} reason={body['reason_code']}"
    return f"{response.status_code}"


def levels(value: str) -> list[int]:
    """--concurrent: one number, or a comma-separated list measured one after the other (1,4,10)."""
    out = [int(part) for part in value.split(",") if part.strip()]
    if not out or min(out) < 1:
        raise argparse.ArgumentTypeError("--concurrent takes positive numbers, e.g. 1,4,10")
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--threshold", type=float, default=0.25)
    parser.add_argument("--only", default="")
    parser.add_argument("--concurrent", type=levels, default=[1],
                        help="identical requests sent at once; a list such as 1,4,10 measures each in turn")
    parser.add_argument("--no-fills", action="store_true", help="only the parsing and validation cases")
    parser.add_argument("--switch-interval", type=float, default=None,
                        help="sys.setswitchinterval for the run, in seconds (Python's default: 0.005)")
    args = parser.parse_args()
    if args.switch_interval is not None:
        sys.setswitchinterval(args.switch_interval)
    install_stubs()
    # Production freezes its startup objects out of the collector (backend.main._warmup).
    gc.collect()
    gc.freeze()
    cases = list(validation_cases())
    if not args.no_fills:
        cases += list(tailor_cases(TAILOR_FILLS))
    cases = [case for case in cases if not args.only or args.only in case[0]]
    results = []
    for concurrent in args.concurrent:
        for name, path, body in cases:
            content = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
            best = None
            for _ in range(3):
                result = asyncio.run(_probe(path, content, concurrent))
                best = result if best is None or result[1] < best[1] else best
                if best[1] <= args.threshold and best[2] <= args.threshold:
                    break
            response, lag, gap, wall = best
            results.append((concurrent, lag, gap, wall, name, summary(response), len(content)))
            print(f"x{concurrent:<3} {lag * 1000:8.1f} ms lag {gap * 1000:8.1f} ms status gap {wall:7.2f} s wall "
                  f"{len(content) / 1024:8.0f} KiB  {name}  -> {summary(response)}", flush=True)
    for concurrent in args.concurrent:
        print(f"\nworst per route at {concurrent} concurrent (longest stall):")
        seen = set()
        for _, lag, gap, _wall, name, outcome, _size in sorted(
                (row for row in results if row[0] == concurrent), key=lambda row: row[1], reverse=True):
            route = name.split(" ")[0]
            if route not in seen:
                seen.add(route)
                print(f"{lag * 1000:8.1f} ms lag {gap * 1000:8.1f} ms gap  {name} -> {outcome}")
    over = [row for row in results if row[1] > args.threshold or row[2] > args.threshold]
    print(f"\ncases: {len(cases)} at each of {len(args.concurrent)} levels ({','.join(map(str, args.concurrent))} "
          f"concurrent); over {args.threshold:.2f} s: {len(over)}")
    for concurrent in args.concurrent:
        print(f"  at {concurrent} concurrent: {sum(row[0] == concurrent for row in over)} over")
    for concurrent, lag, gap, _wall, name, outcome, _size in over:
        print(f"  OVER x{concurrent} {lag:.3f} s lag {gap:.3f} s gap  {name} -> {outcome}")
    return 1 if over else 0


if __name__ == "__main__":
    raise SystemExit(main())
