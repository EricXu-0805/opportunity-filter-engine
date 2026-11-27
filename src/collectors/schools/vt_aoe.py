"""AOE keeps current appointments and named emeritus biographies on one VT roster."""
from __future__ import annotations

import re
from collections import defaultdict
from copy import deepcopy
from urllib.parse import urljoin, urlsplit

from .. import faculty_graph

DIRECTORY = "https://www.aoe.vt.edu/people/faculty.html"
CURRENT_SECTIONS = r"^(faculty|research faculty and associates|adjunct faculty|affiliate faculty)$"
EMERITUS = "Emeritus faculty"


def mark_emeritus(row: dict, checked_on: str) -> None:
    """Attach the roster's classification without inferring an academic grade."""
    name = row["pi_name"]
    meta = row["metadata"]
    if meta.get("deactivation_reason") != "retired_title" or not meta.get("deactivated_at"):
        meta["deactivated_at"] = checked_on
    meta.update(is_active=False, deactivation_reason="retired_title", faculty_title=EMERITUS)
    meta["faculty_title_observation"] = {
        "name": name, "title": EMERITUS, "source": DIRECTORY, "profile": row["url"], "checked_on": checked_on,
    }
    statement = f"Virginia Tech lists {name} in the Aerospace and Ocean Engineering emeritus faculty directory."
    for key in ("description_raw", "description_clean"):
        row[key] = statement
    row["eligibility"]["eligibility_text_raw"] = statement


class RosterObservation:
    """Only this invocation's official directory can retire a saved appointment."""

    def __init__(self):
        self.appointments = defaultdict(set)
        self.read_current_faculty = False

    def read(self, page):
        for card in page.select("main .vt-list-item-wrapper:has(.vt-list-item-heading[data-itemtype])"):
            link = card.select_one("a.vt-list-item-title-link[href]")
            if not link:
                continue
            name = " ".join(link.stripped_strings)
            name = re.sub(r"\s*,\s*(?:bio|redirect)$", "", name, flags=re.I).strip()
            name = re.sub(r"\s*,\s*P\.?\s?E\.?$", "", name).strip()
            heading = faculty_graph._card_section(card, "h3")
            url = urljoin(DIRECTORY, link["href"].strip())
            item_type = card.select_one(".vt-list-item-heading[data-itemtype]")["data-itemtype"]
            self.appointments[name].add((heading.casefold(), url, item_type))
            if heading.casefold() == "faculty" and item_type == "bio":
                self.read_current_faculty = True

    def archives(self, school: dict, dept: dict) -> list[dict]:
        # A fragment containing only emeritus biographies cannot establish
        # whether the directory also lists the person under current Faculty.
        if not self.read_current_faculty:
            return []
        result = []
        for name, appointments in self.appointments.items():
            # A second section or a namesake with a different page is not
            # unambiguous evidence that the existing appointment ended.
            if len(appointments) != 1:
                continue
            section, url, item_type = next(iter(appointments))
            parsed = urlsplit(url)
            if (section != EMERITUS.casefold() or item_type != "bio" or parsed.scheme != "https"
                    or parsed.netloc != "www.aoe.vt.edu" or not parsed.path.startswith("/people/")
                    or not parsed.path.endswith(".html") or url == DIRECTORY):
                continue
            person = faculty_graph.faculty(name, url=url)
            person["_verification_scope"] = "directory"
            row = faculty_graph._normalize(school, dept, person)
            if row:
                mark_emeritus(row, row["metadata"]["last_seen_at"][:10])
                result.append(row)
        return result


def preserve_history(previous: dict, incoming: dict) -> None:
    """Avoid attributing a retirement, or a subsequent reinstatement, by name alone."""
    if not incoming["id"].startswith("faculty-vt-aoe-"):
        return
    old, new = previous["metadata"], incoming["metadata"]
    prior = old.get("faculty_title_observation") or {}
    fresh = new.get("faculty_title_observation") or {}
    if prior.get("source") != DIRECTORY and fresh.get("source") != DIRECTORY:
        return
    if (previous.get("url") != incoming.get("url") or previous.get("pi_name") != incoming.get("pi_name")
            or previous.get("department") != incoming.get("department")):
        incoming.clear()
        incoming.update(deepcopy(previous))
    elif fresh.get("source") == DIRECTORY and fresh.get("title") == EMERITUS:
        # A directory heading attests to the appointment, not a withdrawal of
        # older biography or contact data. Preserve the rest of the saved row.
        archived = deepcopy(previous)
        mark_emeritus(archived, fresh["checked_on"])
        for key in ("last_seen_at", "last_verified", "verification_scope"):
            archived["metadata"][key] = new[key]
        incoming.clear()
        incoming.update(archived)
