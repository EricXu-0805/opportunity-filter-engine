"""AOE keeps current appointments and named emeritus biographies on one VT roster."""
from __future__ import annotations

import re
from collections import defaultdict
from copy import deepcopy
from urllib.parse import urljoin, urlsplit

from . import faculty_graph, ucb_common

DIRECTORY = "https://www.aoe.vt.edu/people/faculty.html"
CURRENT_SECTIONS = r"^(faculty|research faculty and associates|adjunct faculty|affiliate faculty)$"
EMERITUS = "Emeritus faculty"


def mark_emeritus(row: dict, checked_on: str) -> None:
    """Attach the roster's classification without inferring an academic grade."""
    name = row["pi_name"]
    meta = row.setdefault("metadata", {})
    if meta.get("deactivation_reason") != "retired_title" or not meta.get("deactivated_at"):
        meta["deactivated_at"] = checked_on
    meta.update(is_active=False, deactivation_reason="retired_title", faculty_title=EMERITUS)
    meta["faculty_title_observation"] = {
        "name": name, "title": EMERITUS, "source": DIRECTORY, "profile": row["url"], "checked_on": checked_on,
    }
    statement = f"Virginia Tech lists {name} in the Aerospace and Ocean Engineering emeritus faculty directory."
    for key in ("description_raw", "description_clean"):
        row[key] = statement
    if not isinstance(row.get("eligibility"), dict):
        row["eligibility"] = {}
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


def _same_role_slug(previous_url: str, current_url: str, *, returning: bool) -> bool:
    base = "https://www.aoe.vt.edu/people/"
    old_role, new_role = ("emeritus", "faculty") if returning else ("faculty", "emeritus")
    match = re.fullmatch(re.escape(base + old_role + "/") + r"([A-Za-z0-9_-]+\.html)", previous_url)
    return bool(match and current_url == base + new_role + "/" + match[1])


def current_roster_reader():
    """Recheck the full roster once per merge only for a returning person's changed URL."""
    observation = None

    def confirms(name: str, url: str) -> bool:
        nonlocal observation
        if observation is None:
            observation = RosterObservation()
            page = ucb_common.fetch_soup(DIRECTORY)
            if page is not None:
                observation.read(page)
        return (observation.read_current_faculty
                and observation.appointments.get(name) == {("faculty", url, "bio")})
    return confirms


def preserve_history(previous: dict, incoming: dict, current_roster) -> None:
    """Avoid attributing a retirement, or a subsequent reinstatement, by name alone."""
    if not incoming["id"].startswith("faculty-vt-aoe-"):
        return
    if previous.get("metadata") is None:
        previous["metadata"] = {}
    old, new = previous["metadata"], incoming["metadata"]
    prior = old.get("faculty_title_observation") or {}
    fresh = new.get("faculty_title_observation") or {}
    if prior.get("source") != DIRECTORY and fresh.get("source") != DIRECTORY:
        return
    old_url, new_url = previous.get("url") or "", incoming.get("url") or ""
    same_person = previous.get("pi_name") == incoming.get("pi_name") and previous.get("department") == incoming.get("department")
    if same_person and old_url != new_url:
        retiring = fresh.get("source") == DIRECTORY and fresh.get("title") == EMERITUS
        returning = prior.get("title") == EMERITUS and new.get("is_active") is True
        same_person = (
            retiring and _same_role_slug(old_url, new_url, returning=False)
            or returning and _same_role_slug(old_url, new_url, returning=True)
            and current_roster(incoming["pi_name"], new_url)
        )
    if not same_person:
        incoming.clear()
        incoming.update(deepcopy(previous))
        incoming.setdefault("metadata", {}).setdefault("first_seen_at", None)
    elif fresh.get("source") == DIRECTORY and fresh.get("title") == EMERITUS:
        # A directory heading attests to the appointment, not a withdrawal of
        # older biography or contact data. Preserve the rest of the saved row.
        archived = deepcopy(previous)
        archived["url"] = incoming["url"]
        archived["source_url"] = incoming["source_url"]
        application = archived.get("application")
        if old_url != new_url and isinstance(application, dict) and application.get("application_url") == old_url:
            application["application_url"] = new_url
        mark_emeritus(archived, fresh["checked_on"])
        archived["metadata"].setdefault("first_seen_at", new.get("first_seen_at"))
        for key in ("last_seen_at", "last_verified", "verification_scope"):
            archived["metadata"][key] = new[key]
        incoming.clear()
        incoming.update(archived)
