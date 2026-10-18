"""Every CSS selector a collector hands soupsieve must compile under its strict rules.

soupsieve is not pinned (it rides in with beautifulsoup4), so CI and the refresh
runner install its latest release. From 3.0 it parses strictly by default: a
relative selector inside ``:has()`` may be ONE compound after its leading
combinator (``:has(> ul a)`` and ``:has(.name a)`` are rejected), and ``:has()``
may not sit directly inside another ``:has()``. A rejected selector raises inside
the engine's per-unit guard, so the unit logs a warning and collects nothing: on
the 2026-10-17 refresh twenty UT Dallas departments emptied this way.

These tests compile every selector in every school config (card / field /
profile-enrich / pager selectors, which are also the render wait selectors) and
every literal selector the collector code passes to ``select``/``select_one`` or
as a render ``expect_selector``. Where the installed soupsieve predates strict
mode, the two ``:has()`` rules are checked by hand so a local run agrees with CI.
"""

from __future__ import annotations

import ast
import importlib
import pkgutil
import re
from pathlib import Path

import soupsieve as sv

import src.collectors.schools as schools

COLLECTORS_DIR = Path(schools.__file__).resolve().parent.parent

# Keys inside ``selectors`` that hold a regex or a tag name, not a CSS selector.
_NOT_CSS = re.compile(r"(?:_re|_re_text|_strip|_strip_after|_unglue|title_sibling)$")

# Rejected selectors left in place, each with the reason. Shrink only: an entry
# that compiles again fails ``test_known_rejections_are_still_rejected``.
_UNVERIFIED = ("rejected by soupsieve 3; an equivalent selector must be checked "
               "on the live page before it replaces this one")
_ELSEWHERE = "rejected by soupsieve 3; this school's configs are fixed in their own work"


def _cards(module: str, shorts: str, reason: str) -> dict[str, str]:
    return {f"{module}.{s}.scrape.selectors.card": reason for s in shorts.split()}


_KNOWN_REJECTED: dict[str, str] = {
    **_cards("clemson_faculty", "ACCT ECON FIN MGT MKT", _UNVERIFIED),
    **_cards("cmu_faculty", "BIO CHEM ECE MATH PHYS", _UNVERIFIED),
    **_cards("columbia_faculty", "MESAAS", _UNVERIFIED),
    **_cards("fsu_faculty", "BIO", _UNVERIFIED),
    **_cards("georgetown_faculty", "CLSS GERM GOVT HLTH LING MCCT MSBA MSBF MSBK "
             "MSBM MSBO MSBS NURS PSYC SPAN STIA", _ELSEWHERE),
    **_cards("purdue_faculty", "ACCT ECON FIN MIS MKTG OBHR QM SCMO STRAT", _UNVERIFIED),
    **_cards("stanford_faculty", "COMPLIT FRENCHITAL GERMAN IBERLAC SLAVIC", _UNVERIFIED),
    **_cards("udel_faculty", "BME MSEG", _UNVERIFIED),
    **_cards("utk_faculty", "ADPR CSW MABE SIS", _UNVERIFIED),
    **_cards("vt_faculty", "ENGE FREC GEOG SBIO", _UNVERIFIED),
}


def _is_css(parent: str, key: str, value: str) -> bool:
    if value == ":self":  # the engine's "the card itself" marker, not a selector
        return False
    if parent == "selectors":
        return not _NOT_CSS.search(key)
    return key.endswith("selector") or (parent == "paginate" and key == "next")


def _walk(node, path: tuple[str, ...]):
    if isinstance(node, dict):
        label = node.get("short") if isinstance(node.get("short"), str) else None
        here = path + (label,) if label else path
        for key, value in node.items():
            if isinstance(value, str):
                if _is_css(path[-1] if path else "", str(key), value):
                    yield ".".join(here + (str(key),)), value
            elif isinstance(value, dict):
                yield from _walk(value, here + (str(key),))
            elif isinstance(value, list | tuple):
                for item in value:
                    yield from _walk(item, here)


def config_selectors() -> dict[str, str]:
    found: dict[str, str] = {}
    for info in pkgutil.iter_modules(schools.__path__):
        module = importlib.import_module(f"{schools.__name__}.{info.name}")
        school = getattr(module, "SCHOOL", None)
        if isinstance(school, dict):
            for where, selector in _walk(school, (info.name,)):
                found[where if where not in found else f"{where}#{len(found)}"] = selector
    return found


def code_selectors() -> dict[str, str]:
    """String literals passed to select()/select_one() or as expect_selector=."""
    found: dict[str, str] = {}
    for path in sorted(COLLECTORS_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            args = []
            if (isinstance(node.func, ast.Attribute)
                    and node.func.attr in ("select", "select_one") and node.args):
                args.append(node.args[0])
            args += [kw.value for kw in node.keywords if kw.arg == "expect_selector"]
            for arg in args:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    where = f"{path.relative_to(COLLECTORS_DIR)}:{node.lineno}"
                    found[where] = arg.value
    return found


def _top_level(text: str):
    """Yield (index, char) for characters outside quotes, brackets and parens;
    a closing paren that would leave the text yields ``(index, ")")`` and stops."""
    depth, quote, i = 0, None, 0
    while i < len(text):
        ch = text[i]
        if ch == "\\":
            i += 2
            continue
        if quote:
            quote = None if ch == quote else quote
        elif ch in "\"'":
            quote = ch
        elif ch in ")]" and depth == 0:
            yield i, ch
            return
        elif depth == 0:
            yield i, ch
        if not quote and ch in "([":
            depth += 1
        elif not quote and ch in ")]":
            depth -= 1
        i += 1


def _has_rule(selector: str) -> str | None:
    """soupsieve 3's strict ``:has()`` rules, for an older installed soupsieve."""
    for m in re.finditer(r":has\(", selector):
        rest = selector[m.end():]
        end = next((i for i, ch in _top_level(rest) if ch == ")"), len(rest))
        argument = rest[:end]
        cuts = [i for i, ch in _top_level(argument) if ch == ","]
        for start, stop in zip([-1, *cuts], [*cuts, len(argument)], strict=True):
            part = argument[start + 1:stop].strip().lstrip(">+~").strip()
            for i, ch in _top_level(part):
                if ch in " \t\r\n\f>+~":
                    return f"complex selector inside :has() at {m.end() + start + 1 + i}"
                if part.startswith(":has(", i):
                    return "a :has() directly inside :has()"
    return None


def strict_error(selector: str) -> str | None:
    try:
        sv.compile(selector)
    except sv.SelectorSyntaxError as e:
        return str(e).splitlines()[0]
    if not hasattr(sv, "NOSTRICT"):  # soupsieve < 3 has no strict mode
        return _has_rule(selector)
    return None


def _rejected(selectors: dict[str, str]) -> dict[str, str]:
    return {where: err for where, sel in selectors.items()
            if (err := strict_error(sel)) is not None}


def test_the_walk_finds_the_selectors_it_must_guard():
    found = config_selectors()
    assert len(found) > 1000
    assert "utdallas_faculty.ECE.scrape.selectors.card" in found
    assert "utdallas_faculty.PHYS.scrape.selectors.card" in found
    assert any(k.endswith(".profile_enrich.email_selector") for k in found)
    assert not any(k.endswith((".title_re", ".name_strip", ".research_re")) for k in found)
    assert code_selectors()


def test_every_config_selector_compiles_strictly():
    rejected = {k: v for k, v in _rejected(config_selectors()).items()
                if k not in _KNOWN_REJECTED}
    assert rejected == {}


def test_every_literal_selector_in_collector_code_compiles_strictly():
    assert _rejected(code_selectors()) == {}


def test_known_rejections_are_still_rejected():
    found = config_selectors()
    stale = [k for k in _KNOWN_REJECTED if k not in found or strict_error(found[k]) is None]
    assert stale == []


def test_the_strict_has_rules_are_enforced_on_any_soupsieve():
    assert strict_error('div:has(> ul.wp-block-list a[href^="mailto:"])')
    assert strict_error(':not(:has(.profile-name a:-soup-contains("(Starts")))')
    assert strict_error("div:has(> div:has(> h3))")
    assert strict_error('div:has(> ul, > p a)')
    assert strict_error('div:has(> ul.wp-block-list):has(a[href^="mailto:"])') is None
    assert strict_error(':not(:has(a:is(.profile-name a):-soup-contains("(Starts")))') is None
    assert strict_error('li:has(> a[title="x > y"]), p:has(+ :is(h2 a))') is None
