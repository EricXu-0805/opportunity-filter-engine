"""Mirror TargetResumeV1's complete immutable evidence tree on the server.

Signatures bind submitted snapshots, not current cloud-profile ownership or truth.
All limits reject; this module never slices, strips or repairs source material.
"""
from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy

from backend.lib.target_resume_ai_schema import MAX_DOCUMENT_BYTES, MAX_SAFE_INTEGER

DIGEST = re.compile(r"^[0-9a-f]{64}$")
FINGERPRINT = re.compile(r"^v1:sha256:[0-9a-f]{64}$")
BASIC = ("name", "email", "phone", "location")
EDUCATION = ("school", "degree", "field", "start", "end")
ACTIVITY = ("title", "organization", "location", "start", "end", "url")
PUBLICATION = ("title", "authors", "venue", "date", "publication_status", "url", "doi")
SECTIONS = ("basics", "education", "activities", "publications", "skills")
STATUSES = {"candidate", "confirmed", "rejected", "withdrawn"}


class InvalidTargetResume(ValueError):
    """Safe error code; never include any student text or model output."""


def fail(code="invalid_document"):
    raise InvalidTargetResume(code)


def shape(value, required, optional=()):
    if type(value) is not dict or not set(required) <= value.keys() or value.keys() - set(required) - set(optional):
        fail()


def text(value, maximum=None, nonblank=False):
    if type(value) is not str or "\x00" in value:
        fail("invalid_unicode")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        fail("invalid_unicode")
    if maximum is not None and len(value) > maximum or nonblank and not value.strip():
        fail()
    return value


def positive(value):
    if type(value) is not int or not 0 < value <= MAX_SAFE_INTEGER:
        fail()


def identifier(value, maximum=80):
    return text(value, maximum, True)


def array(value, maximum=300):
    if type(value) is not list or len(value) > maximum:
        fail()
    return value


def canonical(value):
    def check(item, depth=0):
        if depth > 32:
            fail("invalid_json")
        if isinstance(item, str):
            text(item)
        elif item is None or type(item) is bool:
            return
        elif type(item) is int:
            if abs(item) > MAX_SAFE_INTEGER:
                fail("invalid_json")
        elif type(item) is list:
            for child in item:
                check(child, depth + 1)
        elif type(item) is dict:
            for key, child in item.items():
                text(key)
                check(child, depth + 1)
        else:
            fail("invalid_json")
    check(value)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def fingerprint(value):
    return "v1:sha256:" + hashlib.sha256(canonical(value).encode("utf-8")).hexdigest()


def valid_source(source, max_quote):
    if type(source) is not dict:
        fail("invalid_source")
    if source.get("kind") == "manual":
        shape(source, ("kind",))
        return
    shape(source, ("kind", "signature", "quote", "start", "end"))
    if source["kind"] != "resume" or not isinstance(source["signature"], str) or not DIGEST.fullmatch(source["signature"]):
        fail("invalid_source")
    text(source["quote"], max_quote, True)
    start, end = source["start"], source["end"]
    if type(start) is not int or type(end) is not int or not 0 <= start < end <= 60000 or end - start != len(source["quote"]):
        fail("invalid_source")


def validate_entries(entries):
    seen = set()
    total = quotes = 0
    for entry in array(entries, 100):
        shape(entry, ("id", "revision", "status", "text", "source"))
        identifier(entry["id"])
        positive(entry["revision"])
        if entry["status"] not in STATUSES or entry["id"] in seen:
            fail("invalid_experiences")
        seen.add(entry["id"])
        text(entry["text"], 6000, True)
        valid_source(entry["source"], 6000)
        total += len(entry["text"])
        quotes += len(entry["source"].get("quote", ""))
    if total > 60000 or quotes > 60000:
        fail("invalid_experiences")


def validate_master(master):
    shape(master, ("version", "id", "revision", "source_signature", "basics", "education", "activities", "publications", "skills", "other_sections", "section_order", "unmapped_ranges"))
    if type(master["version"]) is not int or master["version"] != 1:
        fail("invalid_master")
    positive(master["revision"])
    signature = master["source_signature"]
    if signature is not None and (not isinstance(signature, str) or not DIGEST.fullmatch(signature)):
        fail("invalid_source")
    seen = set()
    counts = {"facts": 0, "values": 0, "quotes": 0, "records": 0, "refs": 0}

    def unique(value, record=False):
        identifier(value)
        if value in seen:
            fail("duplicate_id")
        seen.add(value)
        if record:
            counts["records"] += 1

    def fact(value):
        shape(value, ("id", "revision", "status", "value", "source"))
        unique(value["id"])
        positive(value["revision"])
        if value["status"] not in STATUSES:
            fail("invalid_fact")
        text(value["value"], 60000, True)
        valid_source(value["source"], 60000)
        counts["facts"] += 1
        counts["values"] += len(value["value"])
        counts["quotes"] += len(value["source"].get("quote", ""))

    def fields(item, keys):
        for key in keys:
            if key in item:
                fact(item[key])

    def references(value):
        refs = set()
        for ref in array(value):
            shape(ref, ("id", "revision"))
            identifier(ref["id"])
            positive(ref["revision"])
            if ref["id"] in refs:
                fail("invalid_reference")
            refs.add(ref["id"])
            counts["refs"] += 1

    unique(master["id"])
    shape(master["basics"], ("links",), BASIC)
    fields(master["basics"], BASIC)
    for link in array(master["basics"]["links"]):
        shape(link, ("id", "label", "url"))
        unique(link["id"], True)
        text(link["label"], 120, True)
        fact(link["url"])
    for name, keys in (("education", EDUCATION), ("activities", ACTIVITY), ("publications", PUBLICATION)):
        for item in array(master[name]):
            shape(item, ("id", "details", "kind") if name == "activities" else ("id", "details"), keys)
            unique(item["id"], True)
            if name == "activities" and item["kind"] not in {"employment", "research", "project", "volunteer", "other"}:
                fail("invalid_master")
            fields(item, keys)
            references(item["details"])
    for item in array(master["skills"]):
        fact(item)
    section_ids = set(SECTIONS)
    for section in array(master["other_sections"]):
        shape(section, ("id", "heading", "items"))
        unique(section["id"], True)
        if section["id"] in section_ids:
            fail("invalid_order")
        section_ids.add(section["id"])
        text(section["heading"], 120, True)
        for item in array(section["items"]):
            fact(item)
    order = array(master["section_order"], 305)
    if any(type(item) is not str for item in order) or len(order) != len(section_ids) or set(order) != section_ids:
        fail("invalid_order")
    end = 0
    for interval in array(master["unmapped_ranges"]):
        shape(interval, ("start", "end"))
        left, right = interval["start"], interval["end"]
        if signature is None or type(left) is not int or type(right) is not int or not end <= left < right <= 60000:
            fail("invalid_range")
        end = right
    if any(counts[key] > 300 for key in ("facts", "records", "refs")) or counts["values"] > 60000 or counts["quotes"] > 60000:
        fail("invalid_master")


def active(item, raw, signature):
    source = item["source"]
    return item["status"] == "confirmed" and (source["kind"] == "manual" or (
        source["signature"] == signature and raw[source["start"]:source["end"]] == source["quote"]
    ))


def confirmed_document(snapshot, signature):
    master, raw = snapshot["resume_master"], snapshot["resume_text"]
    entries = {entry["id"]: entry for entry in snapshot["experience_entries"]}
    sections = {}
    sequence = 0

    def line(role, label, original, kind, item):
        nonlocal sequence
        sequence += 1
        return {"id": f"line-{sequence}", "role": role, "label": label, "original": original,
                "evidence": {"kind": kind, "id": item["id"], "revision": item["revision"]}}

    def field(fact, role, label=""):
        return [line(role, label, fact["value"], "fact", fact)] if fact and active(fact, raw, signature) else []

    def fields(item, keys):
        return [row for key in keys for row in field(item.get(key), key)]

    def details(refs):
        return [line("experience", "", entries[ref["id"]]["text"], "experience", entries[ref["id"]])
                for ref in refs if ref["id"] in entries and entries[ref["id"]]["revision"] == ref["revision"]
                and active(entries[ref["id"]], raw, signature)]

    def block(ident, lines):
        return {"id": ident, "lines": lines}

    def section(ident, kind, blocks, heading=""):
        sections[ident] = {"id": ident, "kind": kind, "heading": heading,
                           "blocks": [item for item in blocks if item["lines"]]}

    section("basics", "basics", [block(master["id"], fields(master["basics"], BASIC)),
        *[block(link["id"], field(link["url"], "url", link["label"])) for link in master["basics"]["links"]]])
    for name, keys in (("education", EDUCATION), ("activities", ACTIVITY), ("publications", PUBLICATION)):
        section(name, name, [block(item["id"], fields(item, keys) + details(item["details"])) for item in master[name]])
    section("skills", "skills", [block(fact["id"], field(fact, "skill")) for fact in master["skills"]])
    for item in master["other_sections"]:
        section(item["id"], "other", [block(fact["id"], field(fact, "other", item["heading"])) for fact in item["items"]], item["heading"])
    return {"sections": [sections[ident] for ident in master["section_order"] if sections[ident]["blocks"]]}


def exact_items(items, expected):
    array(items, 1000)
    by_id = {item["id"]: item for item in expected}
    if len(items) != len(expected) or any(type(item) is not dict or type(item.get("id")) is not str for item in items):
        fail("invalid_evidence")
    ids = [item["id"] for item in items]
    if len(set(ids)) != len(ids) or set(ids) != by_id.keys():
        fail("invalid_evidence")
    return by_id


def validate_document(value):
    serialized = canonical(value)
    if len(serialized.encode("utf-8")) > MAX_DOCUMENT_BYTES:
        fail("document_too_large")
    doc = deepcopy(value)
    shape(doc, ("kind", "version", "id", "opportunity_id", "base", "base_snapshot", "target_snapshot", "document"))
    if doc["kind"] != "full_resume" or type(doc["version"]) is not int or doc["version"] != 1:
        fail()
    identifier(doc["id"])
    identifier(doc["opportunity_id"], 200)
    base = doc["base"]
    shape(base, ("master_id", "master_revision", "profile_signature", "source_signature", "target_signature"))
    for key, pattern in (("source_signature", DIGEST), ("profile_signature", FINGERPRINT), ("target_signature", FINGERPRINT)):
        if type(base[key]) is not str or not pattern.fullmatch(base[key]):
            fail("invalid_signature")
    snapshot = doc["base_snapshot"]
    shape(snapshot, ("resume_text", "experience_entries", "resume_master"))
    raw = text(snapshot["resume_text"], 60000)
    validate_entries(snapshot["experience_entries"])
    validate_master(snapshot["resume_master"])
    if base["master_id"] != snapshot["resume_master"]["id"] or type(base["master_revision"]) is not int or base["master_revision"] != snapshot["resume_master"]["revision"]:
        fail("invalid_evidence")
    if hashlib.sha256(raw.encode("utf-8")).hexdigest() != base["source_signature"]:
        fail("invalid_signature")
    target = doc["target_snapshot"]
    shape(target, ("opportunity_id", "title", "organization", "source_url", "description", "requirements"))
    identifier(target["opportunity_id"], 200)
    for key in ("title", "organization", "source_url", "description"):
        text(target[key])
    for requirement in array(target["requirements"], 100000):
        text(requirement)
    if target["opportunity_id"] != doc["opportunity_id"] or fingerprint(target) != base["target_signature"]:
        fail("invalid_signature")
    shape(doc["document"], ("sections",))
    expected = confirmed_document(snapshot, base["source_signature"])
    if not expected["sections"]:
        fail("confirmed_content_required")
    sections = exact_items(doc["document"]["sections"], expected["sections"])
    for section in doc["document"]["sections"]:
        shape(section, ("id", "kind", "heading", "included", "blocks"))
        original = sections[section["id"]]
        if any(section[key] != original[key] for key in ("kind", "heading")) or type(section["included"]) is not bool:
            fail("invalid_evidence")
        blocks = exact_items(section["blocks"], original["blocks"])
        for block in section["blocks"]:
            shape(block, ("id", "included", "lines"))
            if type(block["included"]) is not bool:
                fail()
            lines = exact_items(block["lines"], blocks[block["id"]]["lines"])
            for row in block["lines"]:
                shape(row, ("id", "role", "label", "original", "text", "included", "evidence"))
                shape(row["evidence"], ("kind", "id", "revision"))
                if any(row[key] != lines[row["id"]][key] for key in ("role", "label", "original", "evidence")) or type(row["included"]) is not bool:
                    fail("invalid_evidence")
                if type(row["evidence"]["revision"]) is not int:
                    fail("invalid_evidence")
                text(row["text"])
    return doc


def units_for(doc):
    units, protected = [], 0
    for section in doc["document"]["sections"]:
        for block in section["blocks"]:
            for row in block["lines"]:
                if section["kind"] == "basics":
                    protected += 1
                    continue
                units.append({"unit_id": row["id"], "section_id": section["id"], "block_id": block["id"],
                              "evidence": deepcopy(row["evidence"]), "role": row["role"], "label": row["label"],
                              "original": row["original"], "before_text": row["text"]})
    return units, protected
