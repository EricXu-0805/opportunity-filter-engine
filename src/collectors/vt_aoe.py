"""AOE keeps current appointments and named emeritus biographies on one VT roster."""
from __future__ import annotations

import re
import time
from collections import defaultdict
from copy import deepcopy
from urllib.parse import urljoin, urlsplit

from . import faculty_graph, ucb_common

DIRECTORY = "https://www.aoe.vt.edu/people/faculty.html"
CURRENT_SECTIONS = r"^(faculty|research faculty and associates|adjunct faculty|affiliate faculty)$"
EMERITUS = "Emeritus faculty"
BIO_SECTIONS = {name.casefold(): name for name in ("Faculty", "Research faculty and associates", "Adjunct faculty")}
ROLE_WORD = re.compile(r"\b(?:professor|faculty|chair|scholar|scientist|director|head|lecturer|instructor|"
                       r"research (?:assistant|associate|engineer)|teaching fellow)\b", re.I)
RESEARCH_PROSE = re.compile(r"\b(?:research (?:interests?|areas?|expertise|focus(?:es)?)|my|our|studies include)\b", re.I)
CURRENT_BIO = re.compile(r"https://www\.aoe\.vt\.edu/people/(?:faculty|faculty-research|adjunct)/[\w-]+\.html")


def _heading_matches(name: str, heading: str) -> bool:
    def tokens(value):
        return value.casefold().replace(".", "").split()

    # Accept an optional middle initial or an explicitly listed nickname.
    # Both first and last names, and every supplied full middle name, must agree.
    for spelling in (re.sub(r"\s*\([^()]+\)", "", name), re.sub(r"^\S+\s+\(([^()]+)\)", r"\1", name)):
        a, b = tokens(spelling), tokens(heading)
        if a == b or (min(len(a), len(b)) >= 2 and a[0] == b[0] and a[-1] == b[-1]
                      and len(a) != len(b) and [x for x in a if len(x) > 1] == [x for x in b if len(x) > 1]):
            return True
    return False


def mark_emeritus(row: dict, checked_on: str) -> None:
    """Attach the roster's classification without inferring an academic grade."""
    name = row["pi_name"]
    meta = row.setdefault("metadata", {})
    if meta.get("deactivation_reason") != "retired_title" or not meta.get("deactivated_at"):
        meta["deactivated_at"] = checked_on
    if "directory_section" in meta:
        meta["directory_section"] = EMERITUS
    meta.pop("faculty_title_read_status", None)
    meta.pop("faculty_directory_section_observation", None)
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
        self.roster_checked_on = None
        self.profile_ranks = {}

    def read(self, page):
        observed = getattr(page, "_ofe_observed_at", None)
        if getattr(page, "_ofe_final_url", None) == DIRECTORY and isinstance(observed, str):
            self.roster_checked_on = observed[:10]
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

    def read_profile(self, page, url, name):
        if not CURRENT_BIO.fullmatch(url):
            return
        checked = getattr(page, "_ofe_observed_at", None)
        if not isinstance(checked, str) or getattr(page, "_ofe_requested_url", None) != url:
            return
        key = (name, url)
        self.profile_ranks[key] = ("unavailable", "", None)
        if ucb_common.profile_page_is_denial(page) or faculty_graph._is_cf_interstitial(page):
            return
        headers = page.select("main .vt-bio-info")
        headings = page.select("main .vt-bio-info > h1.vt-bio-name")
        if not headings or not any(h.get_text(strip=True) for h in headings):
            # A response lacking the biography layout cannot withdraw a role.
            return
        self.profile_ranks[key] = ("unconfirmed", "", None)
        if (getattr(page, "_ofe_final_url", None) != url or len(headers) != 1 or len(headings) != 1
                or not _heading_matches(name, headings[0].get_text(" ", strip=True))):
            return
        fields = headers[0].select(":scope > .vt-bio-title > .vt-person-title")
        if len(fields) != 1:
            return
        title = " ".join(fields[0].stripped_strings)
        if 0 < len(title) <= 180 and ROLE_WORD.search(title) and not RESEARCH_PROSE.search(title):
            self.profile_ranks[key] = ("stated", title, checked[:10])

    def update_current_ranks(self, rows):
        if not self.roster_checked_on:
            return
        for row in rows:
            name, url = row["pi_name"], row["url"]
            if not row["id"].startswith("faculty-vt-aoe-") or not CURRENT_BIO.fullmatch(url):
                continue
            sections = self.appointments.get(name, set())
            if len(sections) != 1:
                continue
            section, listed_url, kind = next(iter(sections))
            if listed_url != url or kind != "bio" or section not in BIO_SECTIONS:
                continue
            key = (name, url)
            if key not in self.profile_ranks and not faculty_graph._source_budget_spent():
                # Defer weekly biography reads until after all department rosters.
                # The optional monthly pass may already have read this profile.
                page = ucb_common.fetch_soup(url, timeout=6, max_retries=1)
                if page is not None:
                    self.read_profile(page, url, name)
                time.sleep(0.2)
            status, title, checked = self.profile_ranks.get(key, ("unavailable", "", None))
            meta = row["metadata"]
            meta["directory_section"] = BIO_SECTIONS[section]
            meta["faculty_directory_section_observation"] = {
                "name": name, "title": BIO_SECTIONS[section], "profile": url, "source": DIRECTORY,
                "checked_on": self.roster_checked_on,
            }
            meta["faculty_title_read_status"] = status
            meta["faculty_title"] = title
            if title:
                meta["faculty_title_observation"] = {"name": name, "source": url, "profile": url, "title": title,
                                                     "roster_url": DIRECTORY, "checked_on": checked}

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
    if (new.get("faculty_title_read_status") == "unavailable" and prior.get("roster_url") == DIRECTORY
            and prior.get("name") == incoming.get("pi_name") == previous.get("pi_name")
            and prior.get("source") == prior.get("profile") == incoming.get("url") == previous.get("url")
            and old.get("directory_section") == new.get("directory_section") and old.get("is_active") is True
            and prior.get("title") == old.get("faculty_title")):
        new["faculty_title"] = prior["title"]
        new["faculty_title_observation"] = deepcopy(prior)
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
