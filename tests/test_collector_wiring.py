"""Filesystem-level wiring completeness for the collector fleet.

The existing guards close two loops:

  * ``test_deactivate_stale_faculty.test_faculty_sources_match_refresh_all_registrations``
    — refresh_all wiring ↔ FACULTY_SOURCES (both directions), and
  * ``test_campus_graph.TestRegistry`` — SCHOOL_CONFIGS emit maps ↔ SOURCE_DEFAULTS.

What neither can see is a collector module that exists ON DISK but was never
wired anywhere: it appears in no registry, no refresh_all import, and no
summary key, so every registry-vs-registry test passes while the file silently
collects nothing. That exact gap is what this module closes — every test here
starts from the filesystem (``src/collectors/*.py``) and asserts a path into
the refresh pipeline, so "wrote the collector, forgot the wiring" fails CI
instead of shipping a coverage hole.

Everything here is offline: configs are imported (no module does network I/O
at import time) and refresh_all is inspected via ast/source text, never run.
"""

from __future__ import annotations

import ast
import importlib
import re
from pathlib import Path

import src.collectors.campus_graph as campus_graph
import src.collectors.faculty_graph as faculty_graph
import src.collectors.refresh_all as refresh_all
from src.collectors.schools import SCHOOL_CONFIGS
from src.normalizers.deactivate_stale_faculty import FACULTY_SOURCES
from src.normalizers.school_audience import SOURCE_DEFAULTS

COLLECTORS_DIR = Path(refresh_all.__file__).resolve().parent
SCHOOLS_DIR = COLLECTORS_DIR / "schools"

# Modules under src/collectors/ that are deliberately NOT wired into
# refresh_all. Keep each entry justified; the accounting test asserts exact
# equality, so a module wired later must be REMOVED from here (and a new
# unwired module must be added here with a reason) — the list can't go stale
# silently in either direction.
KNOWN_UNWIRED = {
    # -- engines / libraries / registries (consumed by wired collectors) --
    "base",  # vestigial ABC interface; real convention is fetch_and_normalize/merge_into_processed
    "ucb_sources",  # data registry consumed by ucb_campus
    # -- deliberately manual / CLI / API-driven (never on the weekly refresh) --
    "handshake",  # per-school login cookies expire in days; manual --school runs only
    "manual_importer",  # CLI import of hand-curated JSON/CSV entries
    "llm_enrich",  # run-once-per-school LLM keyword mining (cost-controlled)
    "email_backfill",  # run-once Stanford-CAP / Princeton-Wayback email backfill (on-demand)
    "openalex_enrich",  # run-once OpenAlex topic backfill (metered API)
    "profile_email",  # run-once 2-hop profile email backfill (on-demand, not weekly)
    "uiuc_experts",  # monthly Illinois-Experts enrichment, separate CI step
    "url_parser",  # powers /api/import-url — request-driven, not batch
}


def _refresh_all_relative_imports() -> set[str]:
    """Module names refresh_all imports via ``from .x import ...`` (level-1)."""
    tree = ast.parse(Path(refresh_all.__file__).read_text(encoding="utf-8"))
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.level == 1 and node.module:
            names.add(node.module.split(".")[0])
    return names


def _modules_on_disk(directory: Path) -> set[str]:
    return {p.stem for p in directory.glob("*.py")} - {"__init__", "refresh_all"}


def _configs_in_module(module) -> list[dict]:
    """Every module-level dict that looks like a collector config (has 'source')."""
    return [
        v
        for k, v in vars(module).items()
        if isinstance(v, dict) and not k.startswith("__") and "source" in v
    ]


def test_every_collector_module_is_wired_or_known_manual():
    """A src/collectors/*.py module must be imported by refresh_all or appear
    in KNOWN_UNWIRED with a documented reason. Exact set equality both ways:
    an unaccounted module = silent coverage hole; a KNOWN_UNWIRED entry that
    became wired = stale allowlist."""
    on_disk = _modules_on_disk(COLLECTORS_DIR)
    imported = _refresh_all_relative_imports()

    unaccounted = on_disk - imported - KNOWN_UNWIRED
    assert not unaccounted, (
        "collector module(s) on disk but neither imported by refresh_all nor "
        f"in KNOWN_UNWIRED: {sorted(unaccounted)} — wire them into refresh_all "
        "or add them to KNOWN_UNWIRED in this test with a reason"
    )

    stale_allowlist = KNOWN_UNWIRED & imported
    assert not stale_allowlist, (
        f"KNOWN_UNWIRED entries now imported by refresh_all: {sorted(stale_allowlist)} "
        "— remove them from the allowlist"
    )

    missing_files = KNOWN_UNWIRED - on_disk
    assert not missing_files, (
        f"KNOWN_UNWIRED entries with no module on disk: {sorted(missing_files)}"
    )


def test_every_campus_config_module_is_in_school_configs():
    """Every non-faculty module under schools/ must contribute its SCHOOL dict
    to the SCHOOL_CONFIGS registry — the only path into refresh_all's
    campus-graph loop. Checked by object identity, so a copy-paste that
    registers the wrong module's dict also fails."""
    campus_modules = sorted(
        p.stem
        for p in SCHOOLS_DIR.glob("*.py")
        if p.stem != "__init__" and not p.stem.endswith("_faculty")
    )
    assert campus_modules, "no campus config modules found — glob broken?"

    registered_ids = {id(cfg) for cfg in SCHOOL_CONFIGS}
    for name in campus_modules:
        mod = importlib.import_module(f"src.collectors.schools.{name}")
        school = getattr(mod, "SCHOOL", None)
        assert isinstance(school, dict), f"schools/{name}.py exposes no SCHOOL dict"
        assert id(school) in registered_ids, (
            f"schools/{name}.py SCHOOL is not in SCHOOL_CONFIGS — add it to "
            "src/collectors/schools/__init__.py or refresh_all never collects it"
        )

    # And the registry itself must be structurally valid + fully mapped.
    slugs = [cfg.get("school_slug") for cfg in SCHOOL_CONFIGS]
    assert len(slugs) == len(set(slugs)), f"duplicate school_slug in SCHOOL_CONFIGS: {slugs}"
    for cfg in SCHOOL_CONFIGS:
        errors = campus_graph.validate(cfg)
        assert not errors, f"SCHOOL_CONFIGS[{cfg.get('school_slug')}] invalid: {errors}"
        for bucket, (source, _school, _aud) in cfg["emit"].items():
            assert source in SOURCE_DEFAULTS, (
                f"campus-graph source {source!r} ({cfg['school_slug']}/{bucket}) "
                "missing from school_audience.SOURCE_DEFAULTS"
            )


def test_every_faculty_school_module_is_wired_and_registered():
    """Every schools/*_faculty.py must: validate against the engine, be
    imported by refresh_all, and have its source in FACULTY_SOURCES and
    SOURCE_DEFAULTS (school tag == slug). This is the disk-side complement of
    the FACULTY_SOURCES↔refresh_all set-equality test: together they guarantee
    disk → wired → stale-detection → school/audience tagging."""
    faculty_modules = sorted(
        p.stem for p in SCHOOLS_DIR.glob("*_faculty.py")
    )
    assert faculty_modules, "no faculty school modules found — glob broken?"

    imported = _refresh_all_relative_imports()
    refresh_src = Path(refresh_all.__file__).read_text(encoding="utf-8")

    for name in faculty_modules:
        mod = importlib.import_module(f"src.collectors.schools.{name}")
        school = getattr(mod, "SCHOOL", None)
        assert isinstance(school, dict), f"schools/{name}.py exposes no SCHOOL dict"

        errors = faculty_graph.validate(school)
        assert not errors, f"schools/{name}.py SCHOOL invalid: {errors}"

        for fn in ("fetch_and_normalize", "merge_into_processed"):
            assert callable(getattr(mod, fn, None)), (
                f"schools/{name}.py missing the {fn}() wrapper refresh_all calls"
            )

        assert "schools" in imported and f'"{school["source"]}"' in refresh_src, (
            f"schools/{name}.py (source {school['source']!r}) is not wired into "
            "refresh_all's deep faculty loop"
        )
        assert school["source"] in FACULTY_SOURCES, (
            f"{school['source']!r} missing from deactivate_stale_faculty."
            "FACULTY_SOURCES — its stale professors would never be retired"
        )
        assert school["source"] in SOURCE_DEFAULTS, (
            f"{school['source']!r} missing from school_audience.SOURCE_DEFAULTS"
        )
        assert SOURCE_DEFAULTS[school["source"]][0] == school["school_slug"], (
            f"SOURCE_DEFAULTS school tag for {school['source']!r} is "
            f"{SOURCE_DEFAULTS[school['source']][0]!r}, expected the config's "
            f"slug {school['school_slug']!r}"
        )


def test_every_ucb_department_module_is_wired_and_registered():
    """Every ucb_*_faculty.py on disk must expose a config whose source is
    wired into refresh_all, registered in FACULTY_SOURCES, and mapped in
    SOURCE_DEFAULTS. Catches the 'copied a department module, forgot the
    three registries' failure the registry-vs-registry tests can't see."""
    dept_modules = sorted(
        p.stem for p in COLLECTORS_DIR.glob("ucb_*_faculty.py")
    )
    assert len(dept_modules) >= 40, f"expected the UCB fleet, found {len(dept_modules)}"

    refresh_src = Path(refresh_all.__file__).read_text(encoding="utf-8")
    imported = _refresh_all_relative_imports()

    for name in dept_modules:
        mod = importlib.import_module(f"src.collectors.{name}")
        configs = _configs_in_module(mod)
        assert configs, f"{name}.py exposes no *_CONFIG dict with a 'source' key"
        sources = {cfg["source"] for cfg in configs}
        assert len(sources) == 1, f"{name}.py declares multiple sources: {sources}"
        source = sources.pop()

        assert name in imported and f'"{source}"' in refresh_src, (
            f"{name}.py (source {source!r}) is not wired into refresh_all"
        )
        assert source in FACULTY_SOURCES, (
            f"{source!r} missing from FACULTY_SOURCES — stale professors never retired"
        )
        assert source in SOURCE_DEFAULTS, (
            f"{source!r} missing from school_audience.SOURCE_DEFAULTS"
        )


def test_source_defaults_has_no_dead_faculty_entries():
    """Every *_faculty key in SOURCE_DEFAULTS must be a real, registered
    faculty source. A dead entry misleads readers into thinking a collector
    emits that source (e.g. the retired 'uiuc_js_faculty' entry — its records
    always shipped as source='uiuc_faculty')."""
    faculty_keys = {k for k in SOURCE_DEFAULTS if k.endswith("_faculty")}
    dead = faculty_keys - set(FACULTY_SOURCES)
    assert not dead, (
        f"SOURCE_DEFAULTS *_faculty entries no collector emits: {sorted(dead)} "
        "— remove them (or register the source in FACULTY_SOURCES if real)"
    )


def test_refresh_all_status_keys_are_mapped_for_school_audience():
    """Every plain source name refresh_all records in its run summary must be
    mapped in SOURCE_DEFAULTS, so no wired collector's records ever depend on
    the unmapped (None, 'unknown') fallback. Campus-graph run keys
    ('campus_graph:<slug>') and pipeline pseudo-sources are excluded — their
    record-level sources are covered by the emit-map assertions above."""
    refresh_src = Path(refresh_all.__file__).read_text(encoding="utf-8")
    summary_keys = set(re.findall(r'summary\["sources"\]\[([^\]]+)\]', refresh_src))
    literal_keys = {k.strip('"') for k in summary_keys if k.startswith('"')}
    pseudo = {
        "pi_enricher",
        "deactivate_past",
        "deactivate_stale_faculty",
        "school_audience",
        "auto_tagger",
        "intl_reconciliation",
        "faculty_hygiene",  # post-processing pass (keyword clean + person dedup), not a source
        # Run key, not a record source: ucb_campus records ship as
        # ucb_research_programs / ucb_external_research / ucb_labs, whose
        # SOURCE_DEFAULTS coverage is asserted by test_ucb_campus.TestRegistry.
        "ucb_campus",
    }
    unmapped = {
        k for k in literal_keys - pseudo if k not in SOURCE_DEFAULTS
    }
    assert not unmapped, (
        f"refresh_all sources missing from SOURCE_DEFAULTS: {sorted(unmapped)}"
    )
