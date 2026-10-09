"""The operator docs repeat facts the code owns; fail when the two disagree.

README.md, RUNBOOK.md and docs/product_scope.md went stale for months
(checklist M70): the scope doc still described the April V1 with no flags,
the RUNBOOK listed 6 applied migrations out of 49, and the README pointed at
``src/collectors/school_config.py``, a module that never existed. Each check
below covers one fact a reader acts on.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from backend.lib.release_scope import RELEASE_SCOPE

ROOT = Path(__file__).resolve().parents[1]
DOCS = ("README.md", "RUNBOOK.md", "docs/product_scope.md")

# Versions minted before the repo switched to `supabase migration new`.
# RUNBOOK.md section 4 explains each group; the set is closed.
LEGACY_MIGRATION_VERSIONS = frozenset(
    {f"{n:03d}" for n in range(1, 35)} | {"0181", "0201"}
)

# Written by a command the docs tell the reader to run, so absent on checkout.
GENERATED_PATHS = frozenset({"data/processed/opportunities.json"})

_DOC_FLAG_ROW = re.compile(
    r"^\|\s*`([a-z_]+)`\s*\|\s*`([A-Za-z]+)`\s*\|\s*(on|off)\s*\|", re.M
)
_FRONTEND_FLAG = re.compile(r"^\s*([A-Za-z]+):\s*(true|false),", re.M)
_REPO_PATH = re.compile(
    r"`((?:\.github|backend|config|data|docs|examples|frontend|scripts|src|supabase|tests)"
    r"/[^`\s<>*]*|[A-Za-z_-]+\.(?:md|txt|yaml|toml))`"
)
_MODULE = re.compile(r"python3? -m ((?:backend|scripts|src)(?:\.\w+)+)")


def _doc(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_product_scope_lists_every_release_flag_with_its_state():
    """A flip in the acceptance PR must also flip the row readers see."""
    rows = _DOC_FLAG_ROW.findall(_doc("docs/product_scope.md"))
    assert rows, "docs/product_scope.md: no release-flag table rows found"
    backend = {flag: state == "on" for flag, _, state in rows}
    assert len(backend) == len(rows), "a flag is listed twice"
    assert backend == dict(RELEASE_SCOPE)

    source = _doc("frontend/src/lib/release-scope.ts")
    block = source[source.index("RELEASE_SCOPE = Object.freeze({"):]
    block = block[: block.index("} as const);")]
    frontend = {name: value == "true" for name, value in _FRONTEND_FLAG.findall(block)}
    assert {name: state == "on" for _, name, state in rows} == frontend


def test_new_migrations_take_a_utc_timestamp_version():
    """`supabase migration new` names; a three-digit name would sort first."""
    offenders = []
    for path in sorted((ROOT / "supabase" / "migrations").glob("*.sql")):
        version, _, name = path.stem.partition("_")
        if version in LEGACY_MIGRATION_VERSIONS:
            continue
        try:
            datetime.strptime(version, "%Y%m%d%H%M%S")
        except ValueError:
            offenders.append(path.name)
            continue
        if len(version) != 14 or not name:
            offenders.append(path.name)
    assert not offenders, f"not a YYYYMMDDHHMMSS_<name>.sql migration: {offenders}"


def test_paths_and_modules_the_docs_name_exist():
    missing = []
    for doc in DOCS:
        text = _doc(doc)
        for path in _REPO_PATH.findall(text):
            if path not in GENERATED_PATHS and not (ROOT / path).exists():
                missing.append(f"{doc}: {path}")
        for module in _MODULE.findall(text):
            base = ROOT / module.replace(".", "/")
            if not (base.with_suffix(".py").exists() or (base / "__init__.py").exists()):
                missing.append(f"{doc}: python -m {module}")
    assert not missing, missing
