"""Backfill faculty contact emails by visiting each professor's own profile page.

Several schools' faculty were scraped from directory *listing* pages whose cards
carry name/title/research but no email — the address lives only on the individual
profile page (the record's ``source_url``). This 2-hop pass fetches that page and
lifts the professor's own address out of its ``mailto:`` links, so cold email can
actually reach them. UCLA / UT Austin / Wisconsin / Princeton / Georgia Tech
profile pages all expose a standard ``mailto:``; the real work is *accuracy* —
picking the person's address and rejecting the department / admin / footer inbox
(``info@``, ``webmaster@``, ``mathfrontdesk@``, a bare ``prof@dept`` placeholder).

Mirrors ``openalex_enrich``: ``harvest_emails`` produces a reviewable ``{url: email}``
map (checkpointed, budget-free but rate-limited), ``apply_emails`` writes it back
updates-only. Run on demand, NOT in the weekly refresh — emails are stable and the
richer-guard keeps them when the weekly scrape re-fetches the same person email-less.
"""
from __future__ import annotations

import json
import logging
import os
import re
import time
from collections import Counter

import requests
from bs4 import BeautifulSoup

from .faculty_graph import _clean_email
from .uiuc_experts import _name_parts
from .uiuc_faculty import HEADERS

logger = logging.getLogger(__name__)

PROCESSED_FILE = "data/processed/opportunities.json"
TIMEOUT = 15

# Local-parts that are a shared inbox, not a person. Exact matches plus a few
# substrings ("under-info", "cs-admissions") that vary by school.
_ADMIN_LOCALPARTS = frozenset({
    "info", "admin", "webmaster", "web", "www", "help", "helpdesk", "contact",
    "office", "frontdesk", "reception", "dept", "department", "staff", "hr",
    "prof", "faculty", "chair", "director", "advising", "advisor", "recruiting",
    "jobs", "grad", "graduate", "undergrad", "undergraduate", "it", "ithelp",
    "support", "noreply", "no-reply", "donotreply", "communications", "media",
    "mail", "postmaster", "listserv",
})
_ADMIN_SUBSTR = ("-info", "info-", "frontdesk", "front-desk", "webmaster",
                 "no-reply", "noreply", "do-not-reply", "helpdesk", "admis",
                 "administrator")


def _is_admin_local(local: str) -> bool:
    local = local.lower()
    return local in _ADMIN_LOCALPARTS or any(s in local for s in _ADMIN_SUBSTR)


def _name_match(local: str, first: str, last: str) -> bool:
    """True when the email local-part plausibly belongs to this person — the last
    name is a run inside it, or it's a common first/last-initial arrangement."""
    key = re.sub(r"[._-]", "", local.lower())
    first, last = (first or "").lower(), (last or "").lower()
    if not last:
        return False
    if last in key:
        return True
    if first:
        arrangements = {
            first + last, last + first, first[0] + last, last + first[0],
        }
        if key in arrangements or key.startswith(first[0] + last):
            return True
    return False


def _pick_personal_email(emails: list[str], pi_name: str) -> str | None:
    """Choose the professor's own institutional address from every email on their
    page. Accuracy-first: drop admin/footer inboxes and non-``.edu`` domains, then
    prefer a name-matching local-part; with several equally-plausible addresses and
    no name match, return None rather than guess."""
    first, last = _name_parts(pi_name)
    seen: set[str] = set()
    cands: list[str] = []
    for raw in emails:
        e = (raw or "").strip().lower()
        if "@" not in e or e in seen:
            continue
        seen.add(e)
        local, _, domain = e.partition("@")
        if not domain.endswith(".edu") or _is_admin_local(local):
            continue
        cands.append(e)
    if not cands:
        return None
    if first and last:
        for e in cands:
            if _name_match(e.partition("@")[0], first, last):
                return e
    return cands[0] if len(cands) == 1 else None


def drop_shared_inboxes(mapping: dict[str, str], name_by_url: dict[str, str]) -> dict[str, str]:
    """Reject shared / department inboxes the single-candidate fallback can latch
    onto when a profile page carries no personal address. An email is trusted only
    when it is unique to one professor, or its local-part matches the name of the
    professor it is attached to — so ``studentinfo@`` shared across 25 faculty is
    dropped, while ``grauman@`` recurring because one professor is listed under two
    departments is kept."""
    freq = Counter(mapping.values())
    clean: dict[str, str] = {}
    for url, email in mapping.items():
        if freq[email] == 1:
            clean[url] = email
            continue
        first, last = _name_parts(name_by_url.get(url, ""))
        if last and _name_match(email.split("@", 1)[0], first, last):
            clean[url] = email
    return clean


def _fetch(url: str) -> BeautifulSoup | None:
    try:
        r = requests.get(url, headers=HEADERS, timeout=TIMEOUT)
    except requests.RequestException:
        return None
    if r.status_code != 200:
        return None
    return BeautifulSoup(r.text, "html.parser")


def email_for_profile(url: str, pi_name: str, fetch=None) -> str | None:
    """The professor's own email lifted from their profile page, or None. ``fetch``
    is injectable for tests (returns a BeautifulSoup or None)."""
    soup = (fetch or _fetch)(url)
    if soup is None:
        return None
    emails = [
        e for a in soup.select('a[href^="mailto:"]')
        if (e := _clean_email(a.get("href", "")))
    ]
    if not emails:
        text = soup.get_text(" ", strip=True)
        emails = re.findall(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+", text)
    return _pick_personal_email(emails, pi_name)


def _email_targets(opps: list[dict], schools: list[str] | None) -> list[dict]:
    out = []
    for o in opps:
        if o.get("source_type") != "faculty_research" or o.get("contact_email"):
            continue
        if schools and o.get("school") not in schools:
            continue
        if not (o.get("pi_name") and (o.get("source_url") or o.get("url"))):
            continue
        out.append(o)
    return out


def harvest_emails(
    opps: list[dict],
    *,
    schools: list[str] | None = None,
    sample: int | None = None,
    throttle: float = 0.3,
    progress: bool = False,
    checkpoint_path: str | None = None,
    checkpoint_every: int = 50,
    resume: bool = False,
    fetch=None,
) -> dict[str, str]:
    """``{profile_url: email}`` for email-less faculty whose profile page exposes a
    confidently-personal address. Checkpoints every ``checkpoint_every`` hits so a
    long rate-limited run is never lost; ``resume`` reloads that checkpoint and
    skips URLs already covered."""
    targets = _email_targets(opps, schools)
    if sample is not None:
        targets = targets[:sample]
    mapping: dict[str, str] = {}
    if resume and checkpoint_path and os.path.exists(checkpoint_path):
        mapping = json.load(open(checkpoint_path))
        done = set(mapping)
        before = len(targets)
        targets = [o for o in targets if (o.get("source_url") or o.get("url")) not in done]
        print(f"  resuming: {len(mapping)} already harvested, "
              f"{len(targets)}/{before} targets remain", flush=True)
    since_checkpoint = 0
    for i, o in enumerate(targets):
        url = o.get("source_url") or o.get("url")
        email = email_for_profile(url, o.get("pi_name") or "", fetch=fetch)
        if email:
            mapping[url] = email
            since_checkpoint += 1
            if checkpoint_path and since_checkpoint >= checkpoint_every:
                json.dump(mapping, open(checkpoint_path, "w"), indent=2)
                since_checkpoint = 0
        if fetch is None:
            time.sleep(throttle)
        if progress and (i + 1) % 100 == 0:
            print(f"  ...{i + 1}/{len(targets)}, {len(mapping)} emails", flush=True)
    name_by_url = {
        (o.get("source_url") or o.get("url")): (o.get("pi_name") or "")
        for o in opps
        if o.get("source_type") == "faculty_research"
    }
    mapping = drop_shared_inboxes(mapping, name_by_url)
    if checkpoint_path:
        json.dump(mapping, open(checkpoint_path, "w"), indent=2)
    return mapping


def apply_emails(opps: list[dict], mapping: dict[str, str]) -> int:
    """Updates-only: set ``contact_email`` on email-less faculty whose profile URL
    is in ``mapping``, and align the application contact method. Never overwrites."""
    n = 0
    for o in opps:
        if o.get("source_type") != "faculty_research" or o.get("contact_email"):
            continue
        email = mapping.get(o.get("source_url") or o.get("url"))
        if email:
            o["contact_email"] = email
            o.setdefault("application", {})["contact_method"] = "email"
            n += 1
    return n


def _cli(argv: list[str]) -> int:
    if not argv or argv[0] not in ("harvest", "apply"):
        print(__doc__)
        return 2
    mode, rest = argv[0], argv[1:]
    opps = json.load(open(PROCESSED_FILE))
    if mode == "harvest":
        schools = rest[0].split(",") if rest and not rest[0].startswith("-") else None
        out = "emails.json"
        sample = None
        resume = "--resume" in rest
        for i, a in enumerate(rest):
            if a == "--out":
                out = rest[i + 1]
            elif a == "--sample":
                sample = int(rest[i + 1])
        mapping = harvest_emails(
            opps, schools=schools, sample=sample, progress=True,
            checkpoint_path=out, resume=resume,
        )
        json.dump(mapping, open(out, "w"), indent=2)
        print(f"harvested {len(mapping)} emails -> {out}")
        return 0
    merged: dict = {}
    for f in rest:
        merged.update(json.load(open(f)))
    n = apply_emails(opps, merged)
    json.dump(opps, open(PROCESSED_FILE, "w"), ensure_ascii=False, indent=2)
    print(f"applied {n} emails from {len(rest)} map(s) -> {PROCESSED_FILE}")
    return 0


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    sys.exit(_cli(sys.argv[1:]))
