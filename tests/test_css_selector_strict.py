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

import pytest
import soupsieve as sv
from bs4 import BeautifulSoup

import src.collectors.schools as schools
from src.collectors import faculty_graph as fg

COLLECTORS_DIR = Path(schools.__file__).resolve().parent.parent

# Keys inside ``selectors`` that hold a regex or a tag name, not a CSS selector.
_NOT_CSS = re.compile(r"(?:_re|_re_text|_strip|_strip_after|_unglue|title_sibling)$")

# What each rewritten card selector replaced: a path inside ``:has()``. soupsieve
# 3+ still parses these with NOSTRICT and older soupsieve parses them as they
# are, so each rewrite is checked against the path it stands for. One row per
# distinct selector: a config that uses it, the old selector, the card's open
# tag, markup that holds the path, markup that holds its last step without it,
# and (where cards nest through something other than a div) the wrapper.
_NOSTRICT = getattr(sv, "NOSTRICT", 0)
_MAILTO = '<a href="mailto:x@example.edu">x</a>'
_GROUP = '<div class="wp-block-group">'
_REPLACED = [
    ("clemson_faculty.ACCT", 'div.columns:has(h4 a[href*="/profiles/"])', '<div class="columns">',
     '<h4><a href="/profiles/x">N</a></h4>', '<a href="/profiles/x">N</a><h4>T</h4>'),
    ("columbia_faculty.MESAAS", "div.col-sm-6:has(b a)", '<div class="col-sm-6">',
     '<b><a href="x">N</a></b>', '<a href="x">N</a><b>T</b>'),
    ("georgetown_faculty.CLSS", "div.gu-block-profile-card:has(p.gu-block-profile-title a)",
     '<div class="gu-block-profile-card">', '<p class="gu-block-profile-title"><a href="x">N</a></p>',
     '<p class="gu-block-profile-title">T</p><a href="x">N</a>'),
    ("georgetown_faculty.MCCT", "div.gu-profile:has(p.gu-profile-title a)", '<div class="gu-profile">',
     '<p class="gu-profile-title"><a href="x">N</a></p>', '<p class="gu-profile-title">T</p><a href="x">N</a>'),
    *[(f"stanford_faculty.{short}", f"div.hb-card:has(.views-field-custm-department-s- a[href*='{dept}'])",
       '<div class="hb-card">', f'<div class="views-field-custm-department-s-"><a href="/{dept}">D</a></div>',
       f'<a href="/{dept}">D</a><div class="views-field-custm-department-s-"><a href="/other">O</a></div>')
      for short, dept in [("COMPLIT", "comparative-literature"), ("FRENCHITAL", "french-and-italian"),
                          ("GERMAN", "german-studies"), ("IBERLAC", "iberian-and-latin-american"),
                          ("SLAVIC", "slavic")]],
    ("udel_faculty.BME", "div.et_pb_text_inner:has(h4 a)", '<div class="et_pb_text_inner">',
     '<h4><a href="x">N</a></h4>', '<a href="x">N</a><h4>T</h4>'),
    ("vt_faculty.ENGE", "div.vt-text:has(p strong a)", '<div class="vt-text">',
     '<p><strong><a href="x">N</a></strong></p>', '<strong><a href="x">N</a></strong><p><a href="x">N</a></p>'),
    ("vt_faculty.FREC", "div.vt-text:has(p strong)", '<div class="vt-text">',
     "<p><strong>N</strong></p>", "<strong>N</strong><p>T</p>"),
    *[("vt_faculty.GEOG", "div.vt-col:has(p a strong), div.vt-col:has(p strong a)", '<div class="vt-col">',
       held, '<a href="x"><strong>N</strong></a><p><a href="x">N</a><strong>T</strong></p>')
      for held in ('<p><a href="x"><strong>N</strong></a></p>', '<p><strong><a href="x">N</a></strong></p>')],
    ("vt_faculty.SBIO", "div.vt-col:has(p strong)", '<div class="vt-col">',
     "<p><strong>N</strong></p>", "<strong>N</strong><p>T</p>"),
    ("purdue_faculty.ACCT", "tr:has(> td > a[href^='mailto:'])", "<tr>",
     f"<td>{_MAILTO}</td><td><table><tr><td>N</td></tr></table></td>", f"<td><b>{_MAILTO}</b></td>",
     "<td><table>{}</table></td>"),
    ("fsu_faculty.BIO", "div.row:has(> div.col-sm-9 > div.faculty-sm-text)", '<div class="row">',
     '<div class="col-sm-9"><div class="faculty-sm-text">N</div></div>',
     '<div class="col-sm-9"><div><div class="faculty-sm-text">N</div></div></div>'),
    ("cmu_faculty.BIO", "div[id]:has(> h2):has(a[href^='mailto:']), div:has(> h2):has(> p a[href^='mailto:'])",
     "<div>", f"<h2>N</h2><p>{_MAILTO}</p>", f"<h2>T</h2><p>t</p><span>{_MAILTO}</span>"),
    ("cmu_faculty.ECE", "div:has(> h2 a[href*='bios/'])", "<div>",
     '<h2><a href="bios/x.html">N</a></h2>', '<h2>T</h2><a href="bios/x.html">N</a>'),
    ("utk_faculty.ADPR", "div.wp-block-group:has(> div > h3.wp-block-heading)", _GROUP,
     f'{_GROUP}<h3 class="wp-block-heading">N</h3></div>{_GROUP}<p>t</p></div>',
     '<h3 class="wp-block-heading">N</h3>', _GROUP + "{}</div>"),
    ("utk_faculty.MABE", "div.wp-block-group:has(> div > h2.wp-block-heading.has-large-font-size)", _GROUP,
     f'{_GROUP}<h2 class="wp-block-heading has-large-font-size">N</h2></div>{_GROUP}<p>t</p></div>',
     '<h2 class="wp-block-heading has-large-font-size">N</h2>', _GROUP + "{}</div>"),
]


def _nesting_page(card: str, held: str, loose: str, wrap: str = "<div>{}</div>") -> str:
    """Cards beside, inside and around each other, with and without the path."""
    end = f"</{card[1:-1].split()[0]}>"
    one = f"{card}{held}{end}"
    return (f'<div id="page">{loose}{one}{card}{loose}{end}'
            f"{card}{held}{wrap.format(one)}{end}"
            f"{card}{loose}{wrap.format(one + one)}{end}"
            f"{wrap.format(wrap.format(one))}</div>")


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
    assert _rejected(config_selectors()) == {}


def test_every_literal_selector_in_collector_code_compiles_strictly():
    assert _rejected(code_selectors()) == {}


@pytest.mark.parametrize("row", _REPLACED, ids=[row[0] for row in _REPLACED])
def test_a_rewritten_card_selector_picks_what_its_path_picked(row):
    unit, path, *page = row
    rewrite = config_selectors()[f"{unit}.scrape.selectors.card"]
    soup = BeautifulSoup(_nesting_page(*page), "html.parser")
    picked = sv.select(path, soup, flags=_NOSTRICT)
    assert len(picked) >= 4
    assert [id(el) for el in soup.select(rewrite)] == [id(el) for el in picked]


def test_an_element_nested_past_the_pinned_depths_is_not_selected():
    # at_each_depth trades the path's any-depth reach for a fixed number of levels.
    rows = fg.at_each_depth("tr", 2)
    assert rows == ["tr:not(tr *)", "tr:is(tr *):not(tr tr *)"]
    card = ", ".join(f"{row}:has(a:is({row} > td > *))" for row in rows)
    deep = "<tr id='r{0}'><td><a>x</a></td><td><table>{1}</table></td></tr>"
    soup = BeautifulSoup(deep.format(1, deep.format(2, deep.format(3, ""))), "html.parser")
    assert [el["id"] for el in soup.select(card)] == ["r1", "r2"]


def test_the_strict_has_rules_are_enforced_on_any_soupsieve():
    assert strict_error('div:has(> ul.wp-block-list a[href^="mailto:"])')
    assert strict_error(':not(:has(.profile-name a:-soup-contains("(Starts")))')
    assert strict_error("div:has(> div:has(> h3))")
    assert strict_error('div:has(> ul, > p a)')
    assert strict_error('div:has(> ul.wp-block-list):has(a[href^="mailto:"])') is None
    assert strict_error(':not(:has(a:is(.profile-name a):-soup-contains("(Starts")))') is None
    assert strict_error('li:has(> a[title="x > y"]), p:has(+ :is(h2 a))') is None
