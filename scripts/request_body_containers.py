"""How many lists and objects, outside JSON strings, the largest legitimate body of each route holds.

backend/lib/request_body.py refuses, before parsing, a body that holds more lists and objects
outside its strings than its route's bound. This script prints each bound beside two readings
of what a legitimate body holds:

- schema: the largest body the route's request schema accepts, built from its caps (every
  profile list at its item limit, 512 skills, 15 résumé sections with 100 bullets in all, a
  60,000-character résumé). Each body is sent to its route, which must parse and validate it
  (404 for the stubbed-out target, 200 for an extraction route) rather than refuse it.
- tests: the most that any request the given test files send to the route holds, among the
  requests the bounds admitted. pytest runs in this process with a recorder around the bound.

The bodies the browser's request builders send are pinned by
frontend/src/lib/api.request-containers.test.ts, and tests/test_request_body_bounds.py checks that
each route reads these largest bodies and keeps a margin of at least four times above them.

Run from the repository root:
    python scripts/request_body_containers.py [--tests] [test files ...]
--tests without files reads every tests/test_*.py that names a /api/tailor route, except the two
that send bodies at or past the bounds on purpose (ADVERSARIAL).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))

from backend.lib import request_body  # noqa: E402
from backend.lib.resume_input import MAX_RESUME_TEXT_CHARACTERS  # noqa: E402

FULL_TARGET = ("/api/tailor/full-target/suggestions", "/api/tailor/full-target/selection-plan")
BOUNDS = {
    "/api/tailor": request_body.MAX_JSON_CONTAINERS,
    "/api/tailor/bullet": request_body.MAX_JSON_CONTAINERS,
    "/api/tailor/renovate": request_body.MAX_JSON_CONTAINERS,
    "/api/tailor/extract-bullets": request_body.MAX_RESUME_JSON_CONTAINERS,
    "/api/tailor/structure": request_body.MAX_RESUME_JSON_CONTAINERS,
    **{path: request_body.MAX_FULL_TARGET_JSON_CONTAINERS for path in FULL_TARGET},
}


def containers(body: bytes) -> int:
    return request_body.structural_containers(request_body._json_text(body))


def largest_profile() -> dict:
    """backend.schemas.ProfileRequest at every list's item limit (PROFILE_LIST_LIMITS, PROFILE_SKILL_LIMIT)."""
    from backend.schemas import PROFILE_LIST_LIMITS, PROFILE_SKILL_LIMIT
    profile = {"name": "Sample Student", "major": "Computer Science", "research_interests_text": "Robotics.",
               "preferences": {"min_match_threshold": 25}}
    for field, (count, _) in PROFILE_LIST_LIMITS.items():
        profile[field] = ["research" if field == "seeking_type" else f"{field} {i}" for i in range(count)]
    profile["hard_skills"] = [{"name": f"Skill {i}", "level": "beginner", "source": "resume", "confirmed": True}
                              for i in range(PROFILE_SKILL_LIMIT)]
    return profile


def schema_bodies():
    from backend.routes.tailor import TAILOR_PIPELINE_VERSION
    target = {"opportunity_id": "no-such-target", "locale": "en", "expected_target_version": "wt1:" + "a" * 64}
    bullets = [f"Built sensor rig {i} in Python for 40 students." for i in range(12)]
    sections = [{"id": f"s{s}", "heading": f"Section {s}", "kind": "experience",
                 "bullets": [{"id": f"s{s}-b{b}", "text": "Built a robot."} for b in range(7 if s < 10 else 6)]}
                for s in range(15)]
    resume = ("Built a robot, [and] {a rover}. " * (MAX_RESUME_TEXT_CHARACTERS // 32))[:MAX_RESUME_TEXT_CHARACTERS]
    yield "/api/tailor", {**target, "profile": largest_profile(), "original_bullets": bullets,
                          "source_bullets": bullets, "expected_pipeline_version": TAILOR_PIPELINE_VERSION}
    yield "/api/tailor/bullet", {**target, "profile": largest_profile(), "current_text": bullets[0],
                                 "base_text": bullets[0], "instruction": "Lead with the method."}
    yield "/api/tailor/renovate", {**target, "profile": largest_profile(), "sections": sections}
    yield "/api/tailor/extract-bullets", {"resume_text": resume, "expected_pipeline_version": TAILOR_PIPELINE_VERSION}
    yield "/api/tailor/structure", {"resume_text": resume, "locale": "en"}


def largest_draft() -> dict:
    """A full-target draft at the master's caps (target_resume_ai_validation): 100 experience entries,
    300 activity records each citing one entry, 300 facts each a skill of its own, 300 unmapped
    ranges. Every record, fact and citation becomes a block or line of the document, each a list
    or object, so no other split of the caps holds more lists and objects."""
    import hashlib

    from backend.lib.target_resume_ai_validation import confirmed_document, fingerprint
    from backend.routes import target_resume_ai as full_route

    raw = "Built a robot in Python. " * 400
    signature = hashlib.sha256(raw.encode()).hexdigest()
    entries = [{"id": f"e{i}", "revision": 1, "status": "confirmed", "text": f"Built rig {i} in Python.",
                "source": {"kind": "manual"}} for i in range(100)]
    fact = lambda ident, value: {"id": ident, "revision": 1, "status": "confirmed", "value": value,  # noqa: E731
                                 "source": {"kind": "manual"}}
    master = {"version": 1, "id": "master", "revision": 1, "source_signature": signature,
              "basics": {"links": []}, "education": [], "publications": [], "other_sections": [],
              "activities": [{"id": f"a{i}", "kind": "project", "details": [{"id": f"e{i % 100}", "revision": 1}]}
                             for i in range(300)],
              "skills": [fact(f"k{i}", f"Skill {i}") for i in range(300)],
              "section_order": ["basics", "education", "activities", "publications", "skills"],
              "unmapped_ranges": [{"start": 2 * i, "end": 2 * i + 1} for i in range(300)]}
    snapshot = {"resume_text": raw, "experience_entries": entries, "resume_master": master}
    target = full_route.authoritative_target({
        "id": "target", "title": "Research", "organization": "Example Lab", "source_url": "https://example.edu/lab",
        "description_clean": "Research robots with Python.", "eligibility": {"skills_required": ["Python"]},
        "source_type": "campus_program", "opportunity_type": "research", "metadata": {"is_active": True}})
    doc = {"kind": "full_resume", "version": 1, "id": "draft", "opportunity_id": "target",
           "base": {"master_id": "master", "master_revision": 1, "source_signature": signature,
                    "profile_signature": "v1:sha256:" + "a" * 64, "target_signature": fingerprint(target)},
           "base_snapshot": snapshot, "target_snapshot": target, "document": confirmed_document(snapshot, signature)}
    for section in doc["document"]["sections"]:
        section["included"] = True
        for block in section["blocks"]:
            block["included"] = True
            for row in block["lines"]:
                row.update(text=row["original"], included=True)
    return doc


def full_target_bodies():
    """The largest draft in a suggestions request (eight experience units, as many as one call
    rewrites) and in a selection-plan request. Support groups, left out, add at most 49 lists and
    objects (24 groups, each with its list of ids)."""
    from backend.lib.target_resume_ai_schema import MAX_EXPERIENCE_UNITS
    from backend.lib.target_resume_ai_validation import fingerprint, units_for, validate_document

    doc = largest_draft()
    units = [unit["unit_id"] for unit in units_for(validate_document(doc))[0] if unit["role"] == "experience"]
    head = {"version": 1, "request_id": "request", "locale": "en", "draft": doc, "document_signature": fingerprint(doc)}
    yield FULL_TARGET[0], {**head, "selected_unit_ids": units[:MAX_EXPERIENCE_UNITS]}
    yield FULL_TARGET[1], {**head, "options": {"target_pages": 2}}


def schema_readings() -> dict:
    from fastapi.testclient import TestClient

    from backend import main as main_module
    from backend.lib import release_scope
    from backend.routes import tailor
    from backend.routes import target_resume_ai as full_route

    main_module.feature_enabled = release_scope.feature_enabled = lambda feature: True
    tailor.load_opportunities_by_id = full_route.load_opportunities_by_id = lambda: {}
    tailor.is_configured = lambda: False
    client = TestClient(main_module.app)
    out = {}
    for path, body in [*schema_bodies(), *full_target_bodies()]:
        content = json.dumps(body, ensure_ascii=False).encode()
        response = client.post(path, content=content, headers={"content-type": "application/json"})
        out[path] = (containers(content), response.status_code)
    return out


class Recorder:
    """Records each body the bounds see, by route, and whether they admitted it."""

    def __init__(self):
        self.seen = defaultdict(list)
        self.test = ""

    def pytest_runtest_setup(self, item):
        self.test = item.nodeid

    def pytest_configure(self, config):
        from backend.lib.target_resume_plan_schema import FullTargetPlanRequest
        from backend.routes import target_resume_ai as full_route

        real_refuse, real_parsed = request_body.refuse_container_heavy_body, full_route._parsed

        async def refuse(request, *args, **kwargs):
            body = await request.body()
            try:
                await real_refuse(request, *args, **kwargs)
            except Exception:
                self.seen[request.url.path].append((containers(body), False, self.test))
                raise
            self.seen[request.url.path].append((containers(body), True, self.test))

        def parsed(body, content_type, model):
            path = FULL_TARGET[1] if model is FullTargetPlanRequest else FULL_TARGET[0]
            try:
                request_body.check_body_bounds(body, max_containers=request_body.MAX_FULL_TARGET_JSON_CONTAINERS)
            except Exception:
                self.seen[path].append((containers(body), False, self.test))
            else:
                self.seen[path].append((containers(body), True, self.test))
            return real_parsed(body, content_type, model)

        request_body.refuse_container_heavy_body = refuse
        full_route._parsed = parsed
        self.restore = lambda: (setattr(request_body, "refuse_container_heavy_body", real_refuse),
                                setattr(full_route, "_parsed", real_parsed))

    def pytest_unconfigure(self, config):
        """Stop recording, so the schema readings that follow are not counted as the tests'."""
        self.restore()


# These two send bodies at or past the bounds on purpose.
ADVERSARIAL = {"tests/test_request_body_bounds.py", "tests/test_rewrite_cpu_bounds.py"}


def test_files() -> list[str]:
    return sorted(str(path) for path in Path("tests").glob("test_*.py") if str(path) not in ADVERSARIAL and (
        "/api/tailor" in path.read_text(encoding="utf-8") or "full-target/" in path.read_text(encoding="utf-8")))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tests", action="store_true", help="also run test files and record their request bodies")
    parser.add_argument("files", nargs="*")
    args = parser.parse_args()
    os.environ.setdefault("OFE_DISABLE_RATE_LIMIT", "1")
    for key in ("OPENAI_API_KEY", "OPENROUTER_API_KEY", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY"):
        os.environ.pop(key, None)
    recorder = None
    if args.tests or args.files:
        import pytest

        recorder = Recorder()
        files = args.files or test_files()
        code = pytest.main(["-q", "-p", "no:cacheprovider", *files], plugins=[recorder])
        print(f"pytest exit code {int(code)} over {len(files)} files\n")
    schema = schema_readings()
    print(f"{'route':42} {'bound':>7} {'schema':>7} {'status':>6} {'tests':>7} {'bodies':>7}  largest test body")
    for path, bound in BOUNDS.items():
        holds, status = schema.get(path, ("-", "-"))
        admitted = [row for row in (recorder.seen[path] if recorder else []) if row[1]]
        most = max(admitted, default=None)
        tests = f"{most[0]:7d} {len(admitted):7d}  {most[2]}" if most else f"{'-':>7} {'-':>7}"
        print(f"{path:42} {bound:7d} {holds!s:>7} {status!s:>6} {tests}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
