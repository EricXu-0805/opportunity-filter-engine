"""How many lists and objects, commas and digits, outside JSON strings, the largest legitimate body of each JSON route holds.

backend/lib/request_body.py refuses, before parsing, a body that holds more lists and objects, more
commas between items, or more digits in its numbers, outside its strings than the bounds its route's
endpoint declares. This script finds every route of backend.main.app that reads a JSON body
(json_routes) and prints each route's bounds beside two readings of what a legitimate body holds:

- schema: the largest body the route's request schema accepts, built from its caps (largest_bodies:
  every profile list at its item limit, 512 skills, 15 résumé sections with 100 bullets in all, a
  60,000-character résumé, a full-target draft at the master's caps, an experience master at its
  caps, 50 mailed items, 600 export lines, and so on). Each body is validated against the route's
  request model and sent to its route, which must read it rather than refuse it. A list the schema
  accepts at any length is built at the most items its route reads (5,000 favorite and 5,000
  dismissed ids on /api/matches/view, 100 roadmap ids, 12 legacy résumé bullets), and free-form
  JSON at the largest the app itself produces (a private import's metadata as the import routes
  write it, a heartbeat's detail as the workflows send it). Further bodies put close to the most
  commas their text fields or id lists allow (comma_dense_bodies): a full-target draft whose résumé
  is 60,000 commas, an /api/tailor profile of 159,000 commas, and roadmap and match-view id lists
  of real ids to the body limit.
- tests: the most that any request the given test files send to the route holds, among the
  requests the bounds admitted. pytest runs in this process with a recorder around the bound.

The bodies the browser's Tailor request builders send are pinned by
frontend/src/lib/api.request-containers.test.ts, and tests/test_request_body_bounds.py checks that
each route reads these largest bodies and keeps a margin of at least four times above them.

Run from the repository root:
    python scripts/request_body_containers.py [--tests] [test files ...]
--tests without files reads every tests/test_*.py that names a /api/tailor route, except the two
that send bodies at or past the bounds on purpose (ADVERSARIAL).
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import inspect
import json
import os
import random
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path.cwd()))

from backend.lib import request_body  # noqa: E402
from backend.lib.resume_input import MAX_RESUME_TEXT_CHARACTERS  # noqa: E402

FULL_TARGET = ("/api/tailor/full-target/suggestions", "/api/tailor/full-target/selection-plan")
OWNER = "00000000-0000-4000-8000-000000000001"
EVENT = "00000000-0000-4000-8000-000000000002"
MATERIAL = "00000000-0000-4000-8000-000000000003"
RECORD = "00000000-0000-4000-8000-000000000004"
PRIVATE_TARGET = "private-import:00000000-0000-4000-8000-000000000005"
TARGET_VERSION = "wt1:" + "a" * 64
# Characters a structural count must read past inside a string.
STRUCTURAL = '[]{}",:\\ab∀'
# The largest value a revision may take (backend.schemas.ExperienceEntry, validate_master.positive),
# and a résumé offset's, so the largest bodies carry as many digits outside strings as the schema admits.
MAX_REVISION = 9007199254740991
MAX_OFFSET = 60000


def containers(body: bytes) -> int:
    return request_body.structural_containers(request_body._json_text(body))


def separators(body: bytes) -> int:
    return request_body.structural_separators(request_body._json_text(body))


def digits(body: bytes) -> int:
    return request_body.structural_digits(request_body._json_text(body))


def lane_body_model(route):
    """The model of the JSON body a route's endpoint takes on the request lane
    (request_body.json_body_on_lane), or None."""
    pending = list(route.dependant.dependencies)
    while pending:
        dependency = pending.pop()
        model = getattr(dependency.call, "json_body_model", None)
        if model is not None:
            return model
        pending.extend(dependency.dependencies)
    return None


def _request_parameters(function) -> list[str]:
    """The parameters of a function that hold a Request: annotated as one, or unannotated and named
    request."""
    try:
        parameters = inspect.signature(function).parameters
    except (TypeError, ValueError):
        return []
    return [name for name, parameter in parameters.items()
            if parameter.annotation in ("Request", "fastapi.Request", "starlette.requests.Request")
            or getattr(parameter.annotation, "__name__", "") == "Request"
            or (parameter.annotation is inspect.Parameter.empty and name in ("request", "http_request"))]


def _named_functions(function):
    """The functions a function names: globals, attributes of a module it names, and closures."""
    names, codes = set(), [function.__code__]
    while codes:
        code = codes.pop()
        names.update(code.co_names)
        codes.extend(const for const in code.co_consts if inspect.iscode(const))
    values = [function.__globals__.get(name) for name in names]
    values += [getattr(value, name, None) for value in values if inspect.ismodule(value) for name in names]
    values += [cell.cell_contents for cell in function.__closure__ or () if cell.cell_contents is not None]
    return [inspect.unwrap(value) for value in values if inspect.isfunction(value)]


def _reads_its_request(route) -> bool:
    """Whether the route's endpoint, one of its dependencies, or a function of the app's own code that
    either hands a Request to, calls json(), body() or stream() on that Request."""
    packages = {"backend", "src", route.endpoint.__module__.split(".")[0]}
    pending, seen = [route.endpoint], set()
    dependencies = list(route.dependant.dependencies)
    while dependencies:
        dependency = dependencies.pop()
        pending.append(dependency.call)
        dependencies.extend(dependency.dependencies)
    while pending:
        function = inspect.unwrap(pending.pop())
        if not inspect.isfunction(function) or function in seen or \
                function.__module__.split(".")[0] not in packages:
            continue
        seen.add(function)
        names = _request_parameters(function)
        if function is not route.endpoint and not names:
            continue
        source = inspect.getsource(function)
        if any(re.search(rf"\b{name}\.(?:json|body|stream)\(", source) for name in names):
            return True
        pending.extend(_named_functions(function))
    return False


def json_routes(app=None) -> list[tuple[str, str, object]]:
    """(method, path, route) for every route of the app whose endpoint reads a JSON body.

    FastAPI parses one for a body parameter that is not a form; an endpoint that calls json(),
    body() or stream() on its Request, or hands it to a dependency or a function of the app's own
    code that does, reads one itself; and one that takes its body through
    request_body.json_body_on_lane has it parsed on the request lane. A multipart upload
    (request.form()) is not JSON. An endpoint that declares bounds reads a JSON body, wherever it
    reads it (tests/conftest.py fails a test in which a route reads a body without declaring them).
    """
    from fastapi import params
    from fastapi.routing import APIRoute

    if app is None:
        from backend.main import app
    found = []
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        field = route.body_field
        reads = (field is not None and not isinstance(field.field_info, params.Form)) or \
            lane_body_model(route) is not None or request_body.declared_bounds(route) is not None or \
            _reads_its_request(route)
        if reads:
            found.extend((method, route.path, route) for method in sorted(route.methods))
    return found


def route_bounds(app=None) -> dict[tuple[str, str], request_body.JSONBodyBounds | None]:
    """Each JSON route's declared bounds, None where it declares none."""
    return {(method, path): request_body.declared_bounds(route) for method, path, route in json_routes(app)}


class Pick:
    """List sizes and free text for a body: the largest (every list at its cap), or random ones."""

    def __init__(self, rng: random.Random | None = None):
        self.rng = rng

    def count(self, cap: int, least: int = 0) -> int:
        return cap if self.rng is None else self.rng.randint(least, cap)

    def text(self, fill: str, limit: int = 40) -> str:
        """`fill`, or a random nonblank, trimmed text of characters the count reads past."""
        if self.rng is None:
            return fill
        size = self.rng.randint(1, max(1, min(limit, 40)))
        return "a" + "".join(self.rng.choice(STRUCTURAL) for _ in range(size - 1))


def largest_profile(pick: Pick | None = None) -> dict:
    """backend.schemas.ProfileRequest at every list's item limit (PROFILE_LIST_LIMITS, PROFILE_SKILL_LIMIT)."""
    from backend.schemas import PROFILE_LIST_LIMITS, PROFILE_SKILL_LIMIT
    pick = pick or Pick()
    profile = {"name": pick.text("Sample Student"), "major": "Computer Science",
               "research_interests_text": pick.text("Robotics."), "preferences": {"min_match_threshold": 25}}
    for field, (count, _) in PROFILE_LIST_LIMITS.items():
        profile[field] = ["research" if field == "seeking_type" else pick.text(f"{field} {i}")
                          for i in range(pick.count(count))]
    profile["hard_skills"] = [{"name": pick.text(f"Skill {i}"), "level": "beginner", "source": "resume",
                               "confirmed": True} for i in range(pick.count(PROFILE_SKILL_LIMIT))]
    return profile


def largest_draft(raw: str = ("Built a robot in Python. " * 2400)[:MAX_RESUME_TEXT_CHARACTERS]) -> dict:
    """A full-target draft at the master's caps (target_resume_ai_validation): 100 experience entries,
    300 activity records each citing one entry, 300 facts each a skill of its own, 300 unmapped
    ranges. Every record, fact and citation becomes a block or line of the document, each a list
    or object, so no other split of the caps holds more lists and objects. Every revision is at the
    schema's maximum, so the draft and its mirrored document carry as many digits as the schema admits."""
    from backend.lib.target_resume_ai_validation import confirmed_document, fingerprint
    from backend.routes import target_resume_ai as full_route

    signature = hashlib.sha256(raw.encode()).hexdigest()
    entries = [{"id": f"e{i}", "revision": MAX_REVISION, "status": "confirmed", "text": f"Built rig {i} in Python.",
                "source": resume_source(raw, signature, 10000 + 25 * i)} for i in range(100)]
    snapshot = {"resume_text": raw, "experience_entries": entries, "resume_master": largest_master(signature, raw=raw)}
    target = full_route.authoritative_target({
        "id": "target", "title": "Research", "organization": "Example Lab", "source_url": "https://example.edu/lab",
        "description_clean": "Research robots with Python.", "eligibility": {"skills_required": ["Python"]},
        "source_type": "campus_program", "opportunity_type": "research", "metadata": {"is_active": True}})
    doc = {"kind": "full_resume", "version": 1, "id": "draft", "opportunity_id": "target",
           "base": {"master_id": "master", "master_revision": MAX_REVISION, "source_signature": signature,
                    "profile_signature": "v1:sha256:" + "a" * 64, "target_signature": fingerprint(target)},
           "base_snapshot": snapshot, "target_snapshot": target, "document": confirmed_document(snapshot, signature)}
    for section in doc["document"]["sections"]:
        section["included"] = True
        for block in section["blocks"]:
            block["included"] = True
            for row in block["lines"]:
                row.update(text=row["original"], included=True)
    return doc


def resume_source(raw: str, signature: str, start: int) -> dict:
    """A résumé-kind source quoting 24 characters of `raw` from a five-digit offset, so each fact or
    entry that carries it holds a revision and two offsets outside its strings."""
    return {"kind": "resume", "signature": signature, "quote": raw[start:start + 24], "start": start, "end": start + 24}


def largest_master(signature: str, entries: int = 100, raw: str | None = None) -> dict:
    """A résumé master at its caps: 300 activity records each citing one entry, 300 skill facts and
    300 unmapped ranges. Every revision is at the schema's maximum and every range runs between
    five-digit offsets. With `raw`, each fact quotes the résumé from a five-digit offset, so the master
    carries as many digits outside strings as the schema admits; without it, facts cite a manual source."""
    source = (lambda i: resume_source(raw, signature, 20000 + 25 * i)) if raw is not None else (lambda i: {"kind": "manual"})
    fact = lambda i, ident, value: {"id": ident, "revision": MAX_REVISION, "status": "confirmed",  # noqa: E731
                                    "value": value, "source": source(i)}
    step = (MAX_OFFSET - 10000) // 300
    return {"version": 1, "id": "master", "revision": MAX_REVISION, "source_signature": signature,
            "basics": {"links": []}, "education": [], "publications": [], "other_sections": [],
            "activities": [{"id": f"a{i}", "kind": "project",
                            "details": [{"id": f"e{i % entries}", "revision": MAX_REVISION}]}
                           for i in range(300)],
            "skills": [fact(i, f"k{i}", f"Skill {i}") for i in range(300)],
            "section_order": ["basics", "education", "activities", "publications", "skills"],
            "unmapped_ranges": [{"start": 10000 + step * i, "end": 10000 + step * i + 10} for i in range(300)]}


def full_target_bodies(doc: dict | None = None):
    """The largest draft in a suggestions request (eight experience units, as many as one call
    rewrites) and in a selection-plan request. Support groups, left out, add at most 49 lists and
    objects (24 groups, each with its list of ids)."""
    from backend.lib.target_resume_ai_schema import MAX_EXPERIENCE_UNITS
    from backend.lib.target_resume_ai_validation import fingerprint, units_for, validate_document

    doc = doc or largest_draft()
    units = [unit["unit_id"] for unit in units_for(validate_document(doc))[0] if unit["role"] == "experience"]
    head = {"version": 1, "request_id": "request", "locale": "en", "draft": doc, "document_signature": fingerprint(doc)}
    yield FULL_TARGET[0], {**head, "selected_unit_ids": units[:MAX_EXPERIENCE_UNITS]}
    yield FULL_TARGET[1], {**head, "options": {"target_pages": 2}}


def largest_evidence(pick: Pick) -> dict:
    """backend.schemas.ExperienceEvidence at its caps: 100 entries quoting the résumé, and a master."""
    raw = ("Built a robot in Python. " * (MAX_RESUME_TEXT_CHARACTERS // 25))[:MAX_RESUME_TEXT_CHARACTERS]
    signature = hashlib.sha256(raw.encode()).hexdigest()
    count = pick.count(100)
    entries = [{"id": f"e{i}", "revision": MAX_REVISION, "status": "confirmed", "text": pick.text(f"Built rig {i}."),
                "source": resume_source(raw, signature, 10000 + 25 * i)} for i in range(count)]
    master = largest_master(signature, max(count, 1), raw=raw) if pick.count(1) else None
    return {"version": 2, "resume_text": raw, "entries": entries, "resume_master": master}


def largest_contact(pick: Pick, first_contact: bool = False) -> dict:
    """backend.schemas.EmailContactContext with every part its purpose allows."""
    availability = {"text": pick.text("Free on Mondays."), "confirmed": True}
    if first_contact:
        return {"version": 1, "purpose": "first_contact", "availability": availability}
    return {"version": 1, "purpose": "follow_up", "availability": availability,
            "follow_up": {"sent_confirmed": True, "previous_message": pick.text("Hello again."), "sent_on": "2026-09-01",
                          "reply_status": "received", "reply_text": pick.text("Thanks.")},
            "paper_reading": {"title": pick.text("A paper"), "work_id": "https://openalex.org/W1",
                              "snapshot_version": "rs1:" + "b" * 64, "year": 2025, "level": "abstract",
                              "confirmed": True}}


def ids(count: int, prefix: str = "") -> list[str]:
    """Hex opportunity ids of 16 characters (real corpus ids are 11 characters or longer)."""
    return [f"{prefix}{i:016x}"[-16:] for i in range(count)]


def largest_import_metadata(pick: Pick) -> dict:
    """A private import's extra_fields at the most structure the import routes write: the URL
    parser's fields, model suggestions, and contact-instruction capture of 8 sources of 160 sections
    each with a ledger of 32 pages (src/contact_instructions.py caps), within 256 KiB."""
    from src.contact_instructions import CAPTURE_KEY, PAGES_KEY, SOURCE_KEY

    receipt = {"version": 1, "status": "captured", "reason": None, "attempted_at": "2026-09-01T00:00:00Z",
               "source_url": "https://example.edu/a", "record_source_url": "https://example.edu/a"}
    sources = [{"source_url": f"https://example.edu/{s}", "record_source_url": "https://example.edu/a",
                "checked_at": "2026-09-01T00:00:00Z",
                "sections": [{"heading": "H", "text": pick.text("T")} for _ in range(pick.count(160, 1))]}
               for s in range(pick.count(8))]
    pages = [{"requested_source_url": f"https://example.edu/{p}", "record_source_url": "https://example.edu/a",
              "receipt": receipt, "last_success": receipt, "last_clear": None} for p in range(pick.count(32))]
    return {"domain": "example.edu", "description_source": "page_text", "page_meta_summary": pick.text("Lab."),
            "needs_manual_review": True, "llm_enriched": True, "ai_input_scope": "source_excerpt",
            "suggested_skills": [pick.text(f"Skill {i}") for i in range(pick.count(200))],
            "preferred_year": ["freshman", "sophomore", "junior", "senior"],
            "inferred_fields": {key: "llm:url_parser" for key in (
                "organization", "opportunity_type", "location", "on_campus", "paid", "deadline",
                "suggested_description", "suggested_skills", "preferred_year", "international_friendly")},
            CAPTURE_KEY: receipt, SOURCE_KEY: sources, PAGES_KEY: {"version": 1, "pages": pages}}


def export_body(pick: Pick) -> dict:
    """backend.lib.target_resume_export_schema.ExportRequest at its caps: 305 sections, 600 blocks
    and 600 lines, signed."""
    from backend.lib.target_resume_export_schema import export_signature

    lines = pick.count(600, 305)
    sections = [{"kind": "other", "heading": pick.text(f"Section {s}"), "blocks": []} for s in range(305)]
    for i in range(lines):
        sections[i if i < 305 else 0]["blocks"].append(
            {"lines": [{"role": "experience", "label": "", "text": pick.text(f"Built rig {i}.")}]})
    projection = {"version": 1, "template": "standard-v1", "locale": "en", "page_size": "letter", "sections": sections}
    return {"version": 1, "request_id": "request", "format": "pdf", "document_signature": "v1:sha256:" + "c" * 64,
            "export_signature": export_signature(projection), "projection": projection}


def tailor_bodies(pick: Pick):
    from backend.routes.tailor import TAILOR_PIPELINE_VERSION
    target = {"opportunity_id": "no-such-target", "locale": "en", "expected_target_version": TARGET_VERSION}
    bullets = [pick.text(f"Built sensor rig {i} in Python for 40 students.") for i in range(pick.count(12, 1))]
    sections = [{"id": f"s{s}", "heading": pick.text(f"Section {s}"), "kind": "experience",
                 "bullets": [{"id": f"s{s}-b{b}", "text": pick.text("Built a robot.")} for b in range(7 if s < 10 else 6)]}
                for s in range(pick.count(15))]
    resume = ("Built a robot, [and] {a rover}. " * (MAX_RESUME_TEXT_CHARACTERS // 32))[:MAX_RESUME_TEXT_CHARACTERS]
    yield "POST", "/api/tailor", "/api/tailor", {
        **target, "profile": largest_profile(pick), "original_bullets": bullets, "source_bullets": bullets,
        "expected_pipeline_version": TAILOR_PIPELINE_VERSION}
    yield "POST", "/api/tailor/bullet", "/api/tailor/bullet", {
        **target, "profile": largest_profile(pick), "current_text": bullets[0], "base_text": bullets[0],
        "instruction": "Lead with the method."}
    yield "POST", "/api/tailor/renovate", "/api/tailor/renovate", {
        **target, "profile": largest_profile(pick), "sections": sections}
    yield "POST", "/api/tailor/extract-bullets", "/api/tailor/extract-bullets", {
        "resume_text": resume, "expected_pipeline_version": TAILOR_PIPELINE_VERSION}
    yield "POST", "/api/tailor/structure", "/api/tailor/structure", {"resume_text": resume, "locale": "en"}


def email_bodies(pick: Pick):
    profile, evidence = largest_profile(pick), largest_evidence(pick)
    bullets = [pick.text(f"Built rig {i}.") for i in range(pick.count(12))]
    request = {"contact_context": largest_contact(pick), "expected_target_version": TARGET_VERSION,
               "profile": profile, "opportunity_id": "no-such-target", "engine": "template", "style": "warm",
               "resume_bullets": bullets, "experience_evidence": evidence}
    for path in ("/api/cold-email", "/api/cold-email/stream", "/api/cold-email/variants"):
        yield "POST", path, path, request
    yield "POST", "/api/cold-email/refine", "/api/cold-email/refine", {
        "selection": {"start_utf16": 0, "end_utf16": 5, "text": "Hello"}, "contact_context": largest_contact(pick),
        "expected_target_version": TARGET_VERSION, "current_body": "Hello, professor.",
        "instruction": "Shorter.", "subject": "Research", "profile": profile, "opportunity_id": "no-such-target",
        "resume_bullets": bullets, "experience_evidence": evidence}
    yield "POST", "/api/cold-email/validate", "/api/cold-email/validate", {
        **request, "subject": "Research", "body": "Hello, professor."}
    scope = {"expected_owner_id": OWNER}
    private = {**scope, "expected_target_version": "pwt1:" + "a" * 64, "profile": profile,
               "experience_evidence": evidence, "contact_context": largest_contact(pick, first_contact=True),
               "engine": "template"}
    template = "/api/private-import-targets/{target_id}/cold-email/"
    concrete = f"/api/private-import-targets/{PRIVATE_TARGET}/cold-email/"
    yield "POST", template + "variants", concrete + "variants", private
    yield "POST", template + "validate", concrete + "validate", {
        **private, "subject": "Research", "body": "Hello, professor.", "recipient": "pi@example.edu",
        "contact_requirements_reviewed": True}


def largest_bodies(pick: Pick | None = None):
    """(method, path, concrete path, body): the largest body each JSON route's request schema accepts,
    or with `pick` a random valid one."""
    pick = pick or Pick()
    yield "POST", "/api/matches", "/api/matches", largest_profile(pick)
    view = {"tab": "starred", "search_query": pick.text("q" * 200, 200), "paid": "yes", "intl": "no",
            "source": pick.text("s" * 100, 100), "on_campus": "yes", "deadline": "30", "min_score": 50,
            "scope": "campus", "sort_by": "deadline", "show_dismissed": True,
            "favorite_ids": ids(pick.count(5_000)), "dismissed_ids": ids(pick.count(5_000), "d"),
            "today": "2026-10-09"}
    yield "POST", "/api/matches/view", "/api/matches/view", {
        "profile": largest_profile(pick), "view": view, "page_size": 100, "cursor": None}
    for kind in ("gaps", "explain"):
        yield "POST", f"/api/matches/{{opportunity_id}}/{kind}", f"/api/matches/no-such-target/{kind}", largest_profile(pick)
    yield "POST", "/api/roadmap", "/api/roadmap", {"profile": largest_profile(pick), "opportunity_ids": ids(pick.count(100))}
    yield "POST", "/api/opportunities/batch", "/api/opportunities/batch", {"ids": ids(pick.count(200))}
    yield "POST", "/api/opportunities/{opportunity_id}/chat", "/api/opportunities/no-such-target/chat", {
        "message": pick.text("m" * 2000, 2000), "profile": largest_profile(pick), "model": "default",
        "history": [{"role": ("user", "assistant")[i % 2], "content": pick.text("Hello.")} for i in range(pick.count(20))]}
    yield from email_bodies(pick)
    yield from tailor_bodies(pick)
    for path, body in full_target_bodies():
        yield "POST", path, path, body
    yield "POST", "/api/resume/full-target/export", "/api/resume/full-target/export", export_body(pick)
    for prefix, event in (("application", "application_event_id"), ("contact", "contact_event_id")):
        yield "DELETE", f"/api/{prefix}-materials/{{record_id}}", f"/api/{prefix}-materials/{RECORD}", {
            "expected_owner_id": OWNER, "opportunity_id": "o" * 200, event: EVENT, "material_id": MATERIAL}
    yield "POST", "/api/private-import-targets/resolved", "/api/private-import-targets/resolved", {
        "expected_owner_id": OWNER, "ids": [f"private-import:00000000-0000-4000-8000-{i:012d}"
                                           for i in range(pick.count(100, 1))]}
    target = f"/api/private-import-targets/{PRIVATE_TARGET}"
    yield "PUT", "/api/private-import-targets/{target_id}", target, {
        "expected_owner_id": OWNER, "expected_revision": 0, "opportunity": {
            "source": "url_parser", "title": pick.text("Research assistant"), "description_raw": pick.text("Join us."),
            "source_url": "https://example.edu/a", "url": "https://example.edu/a", "organization": "Example Lab",
            "deadline": "2026-12-01", "posted_date": "2026-09-01", "location": "Urbana", "raw_html": "<p>Join us.</p>",
            "extra_fields": largest_import_metadata(pick)}}
    yield "DELETE", "/api/private-import-targets/{target_id}", target, {"expected_owner_id": OWNER, "expected_revision": 1}
    yield from other_bodies(pick)


def other_bodies(pick: Pick):
    """The admin, mail, import, follow and operations routes."""
    yield "PATCH", "/api/admin/feedback/{ticket_id}", f"/api/admin/feedback/{RECORD}", {
        "status": "resolved", "priority": "high", "assigned_to": "operator", "resolution": "fixed",
        "resolution_note": pick.text("Done.")}
    yield "POST", "/api/admin/feedback/{ticket_id}/reply", f"/api/admin/feedback/{RECORD}/reply", {
        "reply": pick.text("Thanks."), "deliver": True}
    item = {"opportunity_id": "0088a9eb2812c2f4", "title": "Lab", "url": "https://example.edu/a", "score": 91.0,
            "source": "Example", "deadline": "2026-12-01", "record_kind": "listing"}
    yield "POST", "/api/email/send-matches", "/api/email/send-matches", {
        "email": "student@example.edu", "subject_hint": "Matches",
        "items": [{**item, "organization": "Example Lab"} for _ in range(pick.count(50))]}
    yield "POST", "/api/email/send-favorites", "/api/email/send-favorites", {
        "email": "student@example.edu",
        "items": [{**item, "notes": pick.text("Apply."), "status": "saved"} for _ in range(pick.count(50))]}
    # A literal address is refused before any network work, after the body is read.
    yield "POST", "/api/import-url", "/api/import-url", {"url": "https://127.0.0.1/" + "a" * 2000}
    tail = pick.text("")
    yield "POST", "/api/import-text", "/api/import-text", {"text": ("Research assistant. " * 2_500)[:50_000 - len(tail)] + tail}
    yield "POST", "/api/professors/updates", "/api/professors/updates", {"ids": ids(pick.count(200)), "limit": 200}
    yield "PATCH", "/api/admin/ops/incidents/{incident_id}", f"/api/admin/ops/incidents/{RECORD}", {
        "status": "resolved", "priority": "high", "assigned_to": "operator", "resolution": "fixed",
        "resolution_note": pick.text("Done.")}
    yield "POST", "/api/admin/ops/incidents/{incident_id}/retry", f"/api/admin/ops/incidents/{RECORD}/retry", {
        "note": pick.text("Retry.")}
    # The workflows' largest check-in (.github/workflows/refresh-data.yml).
    yield "POST", "/api/cron/heartbeat", "/api/cron/heartbeat", {
        "name": "refresh_data", "detail": {"run_id": "1", "shard": "uiuc,ucb", "mode": "deep"}}


def request_model(route):
    """The model a route validates its JSON body against."""
    from backend.lib.material_archive_schema import ContactMaterialDeletion, MaterialDeletion
    from backend.lib.target_resume_ai_schema import FullTargetRequest
    from backend.lib.target_resume_plan_schema import FullTargetPlanRequest

    manual = {FULL_TARGET[0]: FullTargetRequest, FULL_TARGET[1]: FullTargetPlanRequest,
              "/api/application-materials/{record_id}": MaterialDeletion,
              "/api/contact-materials/{record_id}": ContactMaterialDeletion}
    if route.path in manual:
        return manual[route.path]
    from pydantic import TypeAdapter
    return TypeAdapter(lane_body_model(route) or route.body_field.field_info.annotation)


def validation_errors(route, body) -> int:
    """How many errors validating `body` against the route's request model builds (0 when valid)."""
    from pydantic import ValidationError

    model = request_model(route)
    try:
        if hasattr(model, "validate_python"):
            model.validate_python(body, from_attributes=True)
        else:
            model.model_validate(body)
    except ValidationError as exc:
        return exc.error_count()
    return 0


def validate(route, body) -> None:
    """Raise unless `body` is valid for the route's request model (the full-target draft as the lane
    checks it)."""
    model = request_model(route)
    if hasattr(model, "validate_python"):
        model.validate_python(body, from_attributes=True)  # as fastapi.routing validates a body
    else:
        model.model_validate(body)
    if route.path in FULL_TARGET:
        from backend.lib.target_resume_ai_validation import validate_document
        validate_document(body["draft"])


def comma_dense_bodies():
    """Legitimate bodies with the most commas their text fields or id lists allow, nearly all inside strings."""
    resume = "," * MAX_RESUME_TEXT_CHARACTERS
    path, body = next(full_target_bodies(largest_draft(resume)))
    yield "full-target draft, résumé of 60,000 commas", path, body
    # A profile holds at most PROFILE_MAX_CHARACTERS (160,000) characters (backend/schemas.py); this one 159,000 commas.
    profile = {"name": "Sample Student", "research_interests_text": resume, "desired_fields": [resume, "," * 39_000]}
    yield "profile text of 159,000 commas", "/api/tailor", {
        "opportunity_id": "no-such-target", "locale": "en", "profile": profile, "original_bullets": ["Built a robot."]}
    # The shortest corpus id has 11 characters; the browser sends every favorite and dismissed id.
    room = (1024 * 1024 - 2048) // 14
    yield "roadmap ids to the body limit", "/api/roadmap", {
        "profile": {"name": "Sample Student"}, "opportunity_ids": [f"{i:011x}" for i in range(room)]}
    yield "match-view ids to the body limit", "/api/matches/view", {
        "profile": {"name": "Sample Student"}, "page_size": 50, "cursor": None, "view": {
            "favorite_ids": [f"{i:011x}" for i in range(room // 2)],
            "dismissed_ids": [f"{i:011x}" for i in range(room // 2, room - 20)], "today": "2026-10-09"}}


def body_limit(method: str, path: str) -> int:
    """The most a route reads (backend.main.RequestBodyLimitMiddleware, and the private-import screen)."""
    from backend.lib import private_import_targets_schema as private
    from backend.lib import target_resume_ai_schema as full_target
    from backend.lib import target_resume_export_schema as export

    if path.startswith("/api/private-import-targets"):
        return private.MAX_BODY_BYTES if method == "PUT" or "/cold-email/" in path else (
            private.MAX_BODY_BYTES - private.MAX_PAYLOAD_BYTES)
    if path.startswith("/api/tailor/full-target"):
        return full_target.MAX_BODY_BYTES
    if path == "/api/resume/full-target/export":
        return export.MAX_BODY_BYTES
    return request_body.DEFAULT_MAX_REQUEST_BODY_BYTES


def schema_sites(annotation):
    """(kind, path, detail) for each value, list, typed map and closed model a request schema declares,
    with its JSON path (0 for a list's first item, "key" for a map's values): ("value", path, None) for
    the body and every field, item and map value, whatever its type; ("list", path, (most items its
    field allows or None, the item's closed model or None)); ("map", path, None); and ("keys", path,
    model)."""
    import types
    import typing

    from pydantic import BaseModel

    def closed(kind):
        return kind if isinstance(kind, type) and issubclass(kind, BaseModel) and \
            kind.model_config.get("extra") == "forbid" else None

    def visit(kind, path, metadata, seen, member=False):
        while typing.get_origin(kind) is typing.Annotated:
            kind, *extra = typing.get_args(kind)
            metadata = [*metadata, *(part for item in extra for part in getattr(item, "metadata", [item]))]
        if not member:
            yield "value", path, None
        origin, args = typing.get_origin(kind), typing.get_args(kind)
        if origin in (typing.Union, types.UnionType):
            for member_kind in args:
                yield from visit(member_kind, path, metadata, seen, member=True)
        elif origin in (list, set, frozenset, tuple) and args:
            most = min((item.max_length for item in metadata if type(item).__name__ == "MaxLen"), default=None)
            yield "list", path, (most, closed(args[0]))
            yield from visit(args[0], (*path, 0), [], seen)
        elif origin is dict and args and args[1] not in (typing.Any, object):
            yield "map", path, None
            yield from visit(args[1], (*path, "key"), [], seen)
        elif isinstance(kind, type) and issubclass(kind, BaseModel) and kind not in seen:
            if closed(kind):
                yield "keys", path, kind
            for name, field in kind.model_fields.items():
                yield from visit(field.annotation, (*path, field.alias or name), list(field.metadata), (*seen, kind))

    yield from visit(annotation, (), [], ())


def _placed(body, path: tuple, value, copies: dict | None = None):
    """`body` with `value` at `path`, creating the objects and lists on the way. `copies` maps the
    path of a list on the way to how many copies of its first item it holds."""
    if not path:
        return value
    node = body
    for step, following in zip(path, (*path[1:], None), strict=True):
        if following is None:
            if isinstance(step, int):
                node[:1] = [value]
            else:
                node[step] = value
            break
        empty = [] if isinstance(following, int) else {}
        if isinstance(step, int):
            if not node or not isinstance(node[0], type(empty)):
                node[:1] = [empty]
            node = node[0]
        else:
            if not isinstance(node.get(step), type(empty)):
                node[step] = empty
            node = node[step]
    for prefix, count in (copies or {}).items():
        holder = _found(body, prefix)
        holder[:] = [json.loads(json.dumps(holder[0])) for _ in range(count)]
    return body


def _found(body, path: tuple):
    for step in path:
        if isinstance(step, int):
            body = body[0] if isinstance(body, list) and body else None
        else:
            body = body.get(step) if isinstance(body, dict) else None
    return body


def _counts(body) -> tuple[int, int, int, int]:
    content = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
    return containers(content), separators(content), digits(content), len(content)


def _first_items(value):
    """`value` with every list cut to its first item: the most room the bounds leave for one field."""
    if isinstance(value, list):
        return [_first_items(item) for item in value[:1]]
    if isinstance(value, dict):
        return {key: _first_items(item) for key, item in value.items()}
    return value


# One item of each JSON type; a list takes at most some of them.
JSON_ITEMS = (0, "x", None, {}, [])
# The items of a list put in place of any value of a schema: a number no string or integer field takes.
WRONG_ITEM = 1.5e300


def validation_bodies(app=None):
    """(method, template, path, name, body) for every JSON route: its largest valid body, every list cut
    to its first item, with one value, list, typed map or closed model of its request schema filled:
    a value with a list of numbers or an object, whatever type the schema gives it; a list or typed
    map with items of each JSON type (and, in a list of closed models, items of undeclared keys); a
    closed model with undeclared keys. Each is filled in one copy of the list or object that holds it
    and in as many copies as each list on its path allows, with as many items or keys as the route's
    bounds and body limit admit, and with as many as its field allows."""
    if app is None:
        from backend.main import app
    routes = {(method, path): route for method, path, route in json_routes(app)}
    for method, template, path, largest in largest_bodies():
        base = _first_items(largest)
        route = routes[method, template]
        bounds = request_body.declared_bounds(route) or request_body.DOCUMENT_BOUNDS
        limit = body_limit(method, path) - 4096
        model = request_model(route)
        sites = list(schema_sites(getattr(model, "_type", model)))
        most = {site: detail[0] for kind, site, detail in sites if kind == "list"}
        for kind, site, detail in sites:
            where = ".".join(map(str, site)) or "(body)"
            spreads = [{}] + [{site[:i]: most.get(site[:i]) or 10} for i, step in enumerate(site) if isinstance(step, int)]
            if kind == "keys":
                start = _found(base, site)
                plans = [("keys", dict(start) if isinstance(start, dict) else {}, None),
                         ("keys", {}, len(detail.model_fields))]
            elif kind == "value":
                plans = [("list", WRONG_ITEM, None), ("map", 0, None)]
            else:
                cap, item_model = detail if kind == "list" else (None, None)
                items = [*JSON_ITEMS, *([{f"undeclared{i}": 0 for i in range(len(item_model.model_fields))}]
                                        if item_model else [])]
                plans = [(kind, item, count) for item in items for count in {None, cap}]
            for shape, fill, count in plans:
                for copies in spreads:
                    times = max([1, *copies.values()])
                    empty = fill if shape == "keys" else [] if shape == "list" else {}
                    trial = _placed(json.loads(json.dumps(base)), site, empty, copies)
                    lists, commas, numerals, size = _counts(trial)
                    lists, commas, room = bounds.containers - lists - 8, bounds.separators - commas - 8, limit - size
                    numerals = bounds.digits - numerals - 8
                    if shape == "keys":
                        many = min(commas, numerals, room // 20) // times if count is None else count
                        if many <= 0:
                            continue
                        keys = {f"undeclared{i}": 0 for i in range(many)}
                        body = _placed(json.loads(json.dumps(base)), site, {**empty, **keys}, copies)
                        name = f"{where}: {len(empty) + many:,} keys"
                    else:
                        item = json.dumps(fill, separators=(",", ":")).encode()
                        per, figures = containers(item), digits(item)
                        many = min(commas // (separators(item) + 1), lists // per if per else commas,
                                   numerals // figures if figures else commas,
                                   room // (len(item) + (1 if shape == "list" else 12))) // times
                        many = many if count is None else min(many, count)
                        if many <= 0:
                            continue
                        value = [fill] * many if shape == "list" else {f"k{i}": fill for i in range(many)}
                        body = _placed(json.loads(json.dumps(base)), site, value, copies)
                        held = f"a list of {many:,} x {item.decode()}" if shape == "list" else f"an object of {many:,} keys"
                        name = f"{where}: {held if kind == 'value' else f'{many:,} x {item.decode()}'}"
                    if copies:
                        name += f" in {times:,} copies of {'.'.join(map(str, next(iter(copies)))) or '(body)'}"
                    lists, commas, numerals, size = _counts(body)
                    if lists <= bounds.containers and commas <= bounds.separators and numerals <= bounds.digits \
                            and size <= limit:
                        yield method, template, path, name, body


@contextlib.contextmanager
def reading(app_module=None):
    """Requests reach the point where their body is parsed: release features on, no corpus, no
    configured provider, a caller already verified, no network. Yields the list of paths whose body
    was parsed; a parsed body is answered as invalid ([]), so no endpoint runs on it."""
    from pydantic import TypeAdapter
    from starlette.requests import Request

    from backend import main as main_module
    from backend.lib import private_import_targets as storage
    from backend.lib import release_scope
    from backend.routes import private_import_targets as targets
    from backend.routes import target_resume_ai as full_route

    @contextlib.asynccontextmanager
    async def verified(*args, **kwargs):
        yield

    parsed, real_json, real_loads = [], Request.json, full_route.json

    async def recording(self):
        parsed.append(self.url.path)
        await real_json(self)
        return []

    class Lane:
        JSONDecodeError = json.JSONDecodeError

        @staticmethod
        def loads(body):
            parsed.append("full-target lane")
            real_loads.loads(body)
            return []

    real_lane, any_value = request_body.validated_json_body, TypeAdapter(object)

    def on_lane(body, content_type, adapter):
        parsed.append("request lane")
        real_lane(body, content_type, any_value)
        return real_lane(b"[]", "application/json", adapter)

    saved = [(main_module, "feature_enabled"), (release_scope, "feature_enabled"),
             (storage, "caller_verified_before_parsing"), (targets, "caller_verified_before_parsing"),
             (full_route, "json"), (Request, "json"), (request_body, "validated_json_body")]
    old = [(owner, name, getattr(owner, name)) for owner, name in saved]
    main_module.feature_enabled = release_scope.feature_enabled = lambda feature: True
    storage.caller_verified_before_parsing = targets.caller_verified_before_parsing = verified
    full_route.json, Request.json, request_body.validated_json_body = Lane, recording, on_lane
    try:
        yield parsed
    finally:
        for owner, name, value in old:
            setattr(owner, name, value)


def send(client, method: str, path: str, content: bytes):
    return client.request(method, path, content=content, headers={
        "content-type": "application/json", "authorization": "Bearer reader"})


def schema_readings() -> tuple[dict, list]:
    from fastapi.testclient import TestClient

    from backend import main as main_module

    routes = {(method, path): route for method, path, route in json_routes(main_module.app)}
    out, dense = {}, []
    client = TestClient(main_module.app)
    with reading() as parsed:
        for method, template, path, body in largest_bodies():
            validate(routes[method, template], body)
            content = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
            parsed.clear()
            response = send(client, method, path, content)
            out[method, template] = (containers(content), separators(content), digits(content), response.status_code,
                                     bool(parsed))
        for name, path, body in comma_dense_bodies():
            content = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
            parsed.clear()
            response = send(client, "POST", path, content)
            dense.append((name, path, content.count(b","), separators(content), response.status_code, bool(parsed)))
    return out, dense


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
            route = getattr(request.scope.get("route"), "path", request.url.path)
            key = (request.method, route)
            try:
                await real_refuse(request, *args, **kwargs)
            except Exception:
                self.seen[key].append((containers(body), False, self.test))
                raise
            self.seen[key].append((containers(body), True, self.test))

        def parsed(body, content_type, model):
            key = ("POST", FULL_TARGET[1] if model is FullTargetPlanRequest else FULL_TARGET[0])
            try:
                bounds = request_body.DOCUMENT_BOUNDS
                request_body.check_body_bounds(body, bounds.separators, bounds.containers, bounds.digits)
            except Exception:
                self.seen[key].append((containers(body), False, self.test))
            else:
                self.seen[key].append((containers(body), True, self.test))
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
    for key in ("OPENAI_API_KEY", "OPENROUTER_API_KEY", "DEEPSEEK_API_KEY", "ANTHROPIC_API_KEY",
                "SUPABASE_URL", "SUPABASE_SERVICE_ROLE_KEY"):
        os.environ.pop(key, None)
    recorder = None
    if args.tests or args.files:
        import pytest

        recorder = Recorder()
        files = args.files or test_files()
        code = pytest.main(["-q", "-p", "no:cacheprovider", *files], plugins=[recorder])
        print(f"pytest exit code {int(code)} over {len(files)} files\n")
    bounds = route_bounds()
    schema, dense = schema_readings()
    print("lists and objects, commas, and digits, outside strings; 'read' = the route parsed the largest body")
    print(f"{'route':66} {'bound':>7} {'schema':>7} {'bound':>7} {'schema':>7} {'bound':>7} {'schema':>7} "
          f"{'status':>6} {'read':>5} {'tests':>7} {'bodies':>7}")
    for (method, path), bound in bounds.items():
        holds, commas, numerals, status, read = schema.get((method, path), ("-", "-", "-", "-", "-"))
        admitted = [row for row in (recorder.seen[method, path] if recorder else []) if row[1]]
        most = max(admitted, default=None)
        tests = f"{most[0]:7d} {len(admitted):7d}  {most[2]}" if most else f"{'-':>7} {'-':>7}"
        bound = bound or ("-", "-", "-")
        print(f"{method + ' ' + path:66} {bound[0]!s:>7} {holds!s:>7} {bound[1]!s:>7} {commas!s:>7} "
              f"{bound[2]!s:>7} {numerals!s:>7} {status!s:>6} {read!s:>5} {tests}")
    print("\ncomma-dense legitimate bodies")
    for name, path, raw, commas, status, read in dense:
        print(f"{path:42} commas in the body {raw:7d}, outside strings {commas:6d}, status {status}, read {read}  {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
