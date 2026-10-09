#!/usr/bin/env python3
"""Compare committed supabase/migrations with production's migration history.

Read-only and offline: it reads the committed ``*.sql`` files and an export
of ``supabase_migrations.schema_migrations`` that an operator produced with
the query ``--print-sql`` prints. It never connects to a database. Running
that query against production waits on the owner's OK (backlog Q4).

Why a name match and not a version match: production records one migration
three ways. ``supabase migration repair`` stores the file prefix as the
version (``001``). The hosted flow stored 012-014 under timestamp aliases
(``20260611111920_match_feedback``, MIGRATION_REPAIR.md). MCP
``apply_migration`` stores its own apply-time timestamp and the name it was
given (024 onwards). Counting versions that equal a file prefix reported
"3 of 33" for a fully applied set on 2026-08-14 (docs/RELEASE.md §5). So a
row matches a file when its version is the file's prefix or its name, with
any leading number stripped, is the file's name with its number stripped.

A row whose statements are one element (an MCP apply of the file's bytes) can
also be compared by md5. A difference is reported, not failed, by default:
025-032 went in comment-stripped, which is identical behaviour under a
different hash. ``--strict-content`` fails on it.

Usage:
    python scripts/check_migration_parity.py --print-sql
    python scripts/check_migration_parity.py --applied export.json [--json]
    ... --applied export.csv   # psql --csv output of the same query

Exit codes: 0 in parity, 1 drift (missing, extra, duplicated or ambiguous),
2 unreadable input.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
DEFAULT_MIGRATIONS_DIR = _REPO / "supabase" / "migrations"

# Single-statement rows only: the CLI splits a file into one element per
# statement, so neither statements[1] nor their concatenation is the file.
EXPORT_SQL = """\
-- Read-only. Run against production only with the owner's OK (backlog Q4).
select version,
       name,
       case when coalesce(array_length(statements, 1), 0) = 1
            then md5(statements[1]) end as statements_md5
from supabase_migrations.schema_migrations
order by version;
"""

_PREFIX_RE = re.compile(r"^(\d+)_(.+)$")


@dataclass(frozen=True)
class Committed:
    filename: str
    prefix: str
    bare_name: str
    md5: str


@dataclass(frozen=True)
class Applied:
    version: str
    name: str | None
    statements_md5: str | None

    def as_dict(self) -> dict:
        return {"version": self.version, "name": self.name}


def _bare(name: str) -> str:
    stem = name[:-4] if name.endswith(".sql") else name
    match = _PREFIX_RE.match(stem)
    return (match.group(2) if match else stem).strip().lower()


def committed_migrations(directory: Path = DEFAULT_MIGRATIONS_DIR) -> list[Committed]:
    out: list[Committed] = []
    for path in sorted(directory.glob("*.sql")):
        match = _PREFIX_RE.match(path.stem)
        out.append(Committed(
            filename=path.name,
            prefix=match.group(1) if match else "",
            bare_name=_bare(path.name),
            md5=hashlib.md5(path.read_bytes()).hexdigest(),  # noqa: S324 — matches Postgres md5()
        ))
    return out


def _text(value: object) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def applied_rows(rows: list[dict]) -> list[Applied]:
    out: list[Applied] = []
    for row in rows:
        version = _text(row.get("version"))
        if version is None:
            raise ValueError(f"row without a version: {row!r}")
        out.append(Applied(version=version, name=_text(row.get("name")),
                           statements_md5=_text(row.get("statements_md5"))))
    return out


def load_export(path: Path) -> list[dict]:
    """Rows from a JSON export (a list, or under rows/result/migrations) or CSV."""
    raw = sys.stdin.read() if str(path) == "-" else path.read_text(encoding="utf-8")
    stripped = raw.lstrip()
    if stripped.startswith(("[", "{")):
        payload = json.loads(raw)
        if isinstance(payload, dict):
            payload = next((payload[k] for k in ("rows", "result", "migrations")
                            if isinstance(payload.get(k), list)), None)
        if not isinstance(payload, list) or not all(isinstance(r, dict) for r in payload):
            raise ValueError("JSON export must be a list of {version, name} objects")
        return payload
    reader = csv.DictReader(io.StringIO(raw))
    if not reader.fieldnames or "version" not in reader.fieldnames:
        raise ValueError("CSV export needs a header with at least a version column")
    return [{key: (value or None) for key, value in row.items()} for row in reader]


def compare(committed: list[Committed], applied: list[Applied], *,
            strict_content: bool = False) -> dict:
    hits: dict[str, list[Applied]] = {c.filename: [] for c in committed}
    matched: list[dict] = []
    extra: list[dict] = []
    ambiguous: list[dict] = []
    for row in applied:
        by_version = [c for c in committed if c.prefix and row.version == c.prefix]
        by_name = ([c for c in committed if row.name and _bare(row.name) == c.bare_name]
                   if not by_version else [])
        candidates = by_version or by_name
        if not candidates:
            extra.append(row.as_dict())
            continue
        if len(candidates) > 1:
            ambiguous.append({**row.as_dict(),
                              "files": [c.filename for c in candidates]})
            continue
        target = candidates[0]
        hits[target.filename].append(row)
        matched.append({"file": target.filename, **row.as_dict(),
                        "matched_by": "version" if by_version else "name"})

    content = {"matching": [], "differs": [], "not_comparable": []}
    for c in committed:
        rows = hits[c.filename]
        if len(rows) != 1:
            continue
        recorded = rows[0].statements_md5
        if recorded is None:
            content["not_comparable"].append(c.filename)
        elif recorded.lower() == c.md5:
            content["matching"].append(c.filename)
        else:
            content["differs"].append(c.filename)

    missing = [name for name, rows in hits.items() if not rows]
    duplicates = {name: len(rows) for name, rows in hits.items() if len(rows) > 1}
    in_parity = not (missing or extra or duplicates or ambiguous
                     or (strict_content and content["differs"]))
    return {"in_parity": in_parity, "committed": len(committed), "applied": len(applied),
            "matched": matched, "missing": missing, "extra": extra,
            "duplicates": duplicates, "ambiguous": ambiguous, "content": content}


def _print_report(report: dict) -> None:
    print(f"committed migrations: {report['committed']}, applied rows: {report['applied']}")
    print(f"  matched by version: {sum(m['matched_by'] == 'version' for m in report['matched'])}"
          f", by name: {sum(m['matched_by'] == 'name' for m in report['matched'])}")
    for label, key in (("missing in production", "missing"),
                       ("applied but not committed", "extra"),
                       ("recorded more than once", "duplicates"),
                       ("ambiguous rows", "ambiguous")):
        items = report[key]
        if items:
            print(f"  {label}: {len(items)}")
            for item in (items.items() if isinstance(items, dict) else items):
                print(f"    - {item}")
    content = report["content"]
    print(f"  content md5: {len(content['matching'])} match, {len(content['differs'])} differ, "
          f"{len(content['not_comparable'])} not comparable")
    for name in content["differs"]:
        print(f"    - differs: {name}")
    print("IN PARITY" if report["in_parity"] else "DRIFT")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--applied", type=Path,
                    help="export of schema_migrations (JSON or CSV; '-' for stdin)")
    ap.add_argument("--migrations-dir", type=Path, default=DEFAULT_MIGRATIONS_DIR)
    ap.add_argument("--print-sql", action="store_true",
                    help="print the read-only export query and exit")
    ap.add_argument("--strict-content", action="store_true",
                    help="also fail when a single-statement row's md5 differs")
    ap.add_argument("--json", action="store_true", help="print the report as JSON")
    args = ap.parse_args(argv)

    if args.print_sql:
        print(EXPORT_SQL, end="")
        return 0
    if args.applied is None:
        ap.error("--applied is required (or use --print-sql)")
    try:
        rows = applied_rows(load_export(args.applied))
    except (OSError, ValueError, json.JSONDecodeError, csv.Error) as exc:
        print(f"::error::cannot read {args.applied}: {exc}")
        return 2
    report = compare(committed_migrations(args.migrations_dir), rows,
                     strict_content=args.strict_content)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        _print_report(report)
    return 0 if report["in_parity"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
