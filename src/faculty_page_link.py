"""Whether a faculty row's link is the person's own page or a department roster.

A row carries two links: ``source_url`` (the page the collector read) and
``url`` (the page it shows). Either can be a roster: a collector with no page
for a person writes its unit's directory into both. One row cannot tell, so
the corpus loader looks at all of them once (`mark_roster_links`) and the
public projector publishes the answer per row (`faculty_page`).

A link is a roster when at least three people of one school share it as
either link, when the school config names it as a unit's directory (the link
a person with no page of their own is given), or when it is a text-fragment
passage of the page the row's own review cites (a reviewer who found no page
for the person points into the listing that names them). Three, not two: two
rows on one page are often one person under two spellings, or two heads of
one lab.
"""
from __future__ import annotations

import importlib
import pkgutil
from collections import defaultdict
from functools import cache
from urllib.parse import urldefrag

ROSTER_LINKS_MARKER = "_roster_links"
_SHARED_BY = 3


def link_key(url: object) -> str | None:
    """A link reduced to the page it opens, or None."""
    if not isinstance(url, str) or not url.strip():
        return None
    page, fragment = urldefrag(url.strip())
    # A hash route ("#/directory/person/ada") is the page. An anchor or a text
    # fragment ("#faculty:~:text=Example") is a place on a page others share.
    if fragment.startswith(("/", "!")):
        page = f"{page}#{fragment}"
    return page.rstrip("/")


@cache
def configured_directory_urls() -> dict[str, frozenset[str]]:
    """Collector source -> the unit directories its school config names."""
    from src.collectors import schools

    directories: dict[str, set[str]] = defaultdict(set)
    for module in pkgutil.iter_modules(schools.__path__):
        if not module.name.endswith("_faculty"):
            continue
        school = getattr(importlib.import_module(f"{schools.__name__}.{module.name}"), "SCHOOL", None)
        if not isinstance(school, dict):
            continue
        for unit in school.get("departments") or ():
            if key := link_key(unit.get("directory_url")):
                directories[school.get("source")].add(key)
    return {source: frozenset(urls) for source, urls in directories.items()}


def mark_roster_links(rows: list[dict]) -> None:
    """Record on every faculty row which of its links are rosters."""
    faculty = [row for row in rows if row.get("source_type") == "faculty_research"]
    people: dict[tuple, set[str]] = defaultdict(set)
    for row in faculty:
        name = " ".join(str(row.get("pi_name") or "").casefold().split())
        for key in {link_key(row.get("source_url")), link_key(row.get("url"))} - {None}:
            people[row.get("school"), key].add(name)
    directories = configured_directory_urls()
    for row in faculty:
        source = row.get("source")
        links = {key: url for url in (row.get("source_url"), row.get("url")) if (key := link_key(url))}
        metadata = row.get("metadata")
        review = metadata.get("faculty_profile_review") if isinstance(metadata, dict) else None
        reviewed_roster = link_key(review.get("source_url")) if isinstance(review, dict) else None
        row[ROSTER_LINKS_MARKER] = tuple(
            key for key, url in links.items()
            if len(people[row.get("school"), key]) >= _SHARED_BY or key in directories.get(source, ())
            or (":~:text=" in url and key == reviewed_roster))


def faculty_page(row: dict, links: list[str]) -> dict | None:
    """The link a marked faculty row offers and what it is, or None.

    ``links`` are the row's public links, the cited page before the shown one.
    ``profile``: the first of them that is the person's own page.
    ``directory``: every one is a roster. None on a row the loader never
    marked: without the rest of the corpus nobody can say which it is.
    """
    rosters = row.get(ROSTER_LINKS_MARKER)
    if rosters is None:
        return None
    for url in links:
        if link_key(url) not in rosters:
            return {"kind": "profile", "url": url}
    return {"kind": "directory", "url": links[0]} if links else None
