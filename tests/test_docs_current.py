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

# Timestamp versions committed when the rule below was written. A new one must
# sort after the last of them: a back-dated file replays before migrations it
# may depend on, the same hazard a three-digit name has.
TIMESTAMP_VERSIONS_AT_WRITING = frozenset({
    "20260819164641", "20260924181610", "20260925052636", "20260925095707",
    "20260925104726", "20260925115022", "20260925151438", "20260926093008",
    "20260926100530", "20260926113133", "20260929041441", "20260930090000",
    "20260930220000",
})

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
_COMMAND_PATH = re.compile(
    r"\b(?:python3?(?:\.\d+)?|bash) +((?:backend|scripts|src|supabase|tests)/[^\s`]+)"
)
_LINK_TARGET = re.compile(r"\]\(([^)\s#]+)[^)\s]*\)")
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


def test_new_migrations_take_a_utc_timestamp_after_the_last_one():
    """`supabase migration new` names, later than every file before the rule.

    A three-digit name or a back-dated timestamp would sort before migrations
    it may depend on.
    """
    newest_at_writing = max(TIMESTAMP_VERSIONS_AT_WRITING)
    offenders = []
    for path in sorted((ROOT / "supabase" / "migrations").glob("*.sql")):
        version, _, name = path.stem.partition("_")
        if version in LEGACY_MIGRATION_VERSIONS | TIMESTAMP_VERSIONS_AT_WRITING:
            continue
        try:
            datetime.strptime(version, "%Y%m%d%H%M%S")
        except ValueError:
            offenders.append(path.name)
            continue
        if len(version) != 14 or not name or version <= newest_at_writing:
            offenders.append(path.name)
    assert not offenders, (
        f"not a YYYYMMDDHHMMSS_<name>.sql migration later than {newest_at_writing}: "
        f"{offenders}"
    )


def test_paths_and_modules_the_docs_name_exist():
    """Backticked paths, script paths in commands, link and image targets.

    Not the README's project tree, which draws paths without naming them whole.
    """
    missing = []
    for doc in DOCS:
        text = _doc(doc)
        for path in _REPO_PATH.findall(text) + _COMMAND_PATH.findall(text):
            if path not in GENERATED_PATHS and not (ROOT / path).exists():
                missing.append(f"{doc}: {path}")
        for target in _LINK_TARGET.findall(text):
            if not re.match(r"[a-z]+:", target) and not ((ROOT / doc).parent / target).exists():
                missing.append(f"{doc}: link to {target}")
        for module in _MODULE.findall(text):
            base = ROOT / module.replace(".", "/")
            if not (base.with_suffix(".py").exists() or (base / "__init__.py").exists()):
                missing.append(f"{doc}: python -m {module}")
    assert not missing, missing
