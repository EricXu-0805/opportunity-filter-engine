"""Backfill faculty emails via school-specific public routes the generic
2-hop profile scrape cannot reach. Eric-approved 2026-07-10.

**Stanford — constructed SUNet address.** Stanford publishes no faculty email
anywhere public (dept pages, CAP, stanfordwho — all verified), but
profiles.stanford.edu serves a public unauthenticated JSON API whose
``data.uid`` field is the person's real SUNet ID, and Stanford's canonical
address is ``<sunetid>@stanford.edu`` (the convention is independently
validated: every self-listed address observed in the API equals
uid@stanford.edu). The address is CONSTRUCTED, not observed, so each apply
stamps ``metadata.email_source = "constructed_sunetid"``, and a displayName
gate (same surname + same first initial as our pi_name) rejects slug
collisions — the uid itself comes from Stanford's own record for that page,
so there is no name-guessing anywhere.

**Princeton — Wayback recovery.** Current dept sites publish no personal
emails (math never did; physics' redesign removed them; the central directory
is Cloudflare+CAS walled). Old snapshots (2014-2019) of the SAME profile URLs
carry mailto: links, and Princeton netids are stable for a person's tenure.
Targets are only faculty currently in the corpus (present-day faculty), each
recovered address must clear the same personal-email picker as the live
2-hop pass, and apply stamps ``metadata.email_source = "wayback"``.

    python -m src.collectors.email_backfill harvest stanford --out st.json [--sample N] [--resume]
    python -m src.collectors.email_backfill harvest princeton --out pr.json [--sample N] [--resume]
    python -m src.collectors.email_backfill apply st.json pr.json
"""
from __future__ import annotations

import json
import re
import sys
import time

import requests

from .openalex_enrich import _flush_checkpoint, _load_resume_state, _record_url
from .profile_email import PROCESSED_FILE, _pick_personal_email
from .uiuc_experts import _name_parts

_UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
_TIMEOUT = 30

_STANFORD_PROFILE = "https://profiles.stanford.edu/{slug}"
_STANFORD_CAP = "https://profiles.stanford.edu/proxy/api/cap/profiles/{pid}"
_CAP_ID_RE = re.compile(r"proxy/api/cap/profiles/(\d+)/resources/profilephoto")

_CDX = "http://web.archive.org/cdx/search/cdx"
_WAYBACK_RAW = "https://web.archive.org/web/{ts}id_/{url}"
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+(?:\.[\w-]+)+")
# Old-design era (emails still published) first; the current design carries none.
_WAYBACK_WINDOWS = (("2014", "2019"), ("2020", "2022"))


def _slug(url: str | None) -> str | None:
    if not url:
        return None
    tail = url.rstrip("/").rsplit("/", 1)[-1]
    return tail.lower() or None


def _names_agree(pi_name: str, display_name: str) -> bool:
    """Surname equal + compatible first name — the gate that rejects a dept-page
    slug resolving to a different person's Stanford profile. When both sides
    carry a full first name they must be prefix-compatible (accepts Rob/Robert,
    rejects John/Jane); a bare initial accepts any same-initial full name."""
    f1, l1 = _name_parts(pi_name)
    f2, l2 = _name_parts(display_name)
    if not (l1 and l2 and l1.lower() == l2.lower()):
        return False
    if not (f1 and f2):
        return False
    a, b = f1.lower(), f2.lower()
    if a[0] != b[0]:
        return False
    if len(a) > 1 and len(b) > 1 and not (a.startswith(b) or b.startswith(a)):
        return False
    return True


def _get(url: str, **kw):
    try:
        return requests.get(url, headers=_UA, timeout=_TIMEOUT, **kw)
    except requests.RequestException:
        return None


def stanford_email_for(pi_name: str, url: str | None) -> dict | None:
    """{email, uid, display_name} for one Stanford faculty member, or None.
    Two public requests: profile page (slug -> numeric CAP id), then the CAP
    JSON (id -> uid + displayName)."""
    slugs = []
    if (s := _slug(url)):
        slugs.append(s)
    f, last = _name_parts(pi_name)
    if f and last:
        name_slug = re.sub(r"[^a-z-]", "", f"{f.lower()}-{last.lower()}")
        if name_slug not in slugs:
            slugs.append(name_slug)
    for slug in slugs:
        r = _get(_STANFORD_PROFILE.format(slug=slug))
        if r is None or r.status_code != 200:
            continue
        m = _CAP_ID_RE.search(r.text)
        if not m:
            continue
        r2 = _get(_STANFORD_CAP.format(pid=m.group(1)))
        if r2 is None or r2.status_code != 200:
            continue
        try:
            data = r2.json().get("data") or {}
        except ValueError:
            continue
        uid = (data.get("uid") or "").strip().lower()
        display = data.get("displayName") or ""
        if not uid or not _names_agree(pi_name, display):
            continue
        return {"email": f"{uid}@stanford.edu", "uid": uid,
                "display_name": display, "source": "constructed_sunetid"}
    return None


def princeton_wayback_email_for(pi_name: str, url: str | None) -> dict | None:
    """{email, snapshot} recovered from an archived copy of the professor's own
    profile URL, or None. The address must clear ``_pick_personal_email`` (admin
    inboxes and ambiguous multi-candidate pages return None, same as the live
    2-hop pass)."""
    if not url:
        return None
    r = _get(_CDX, params={"url": url, "output": "json",
                           "filter": "statuscode:200", "limit": "200"})
    if r is None or r.status_code != 200:
        return None
    try:
        rows = r.json()
    except ValueError:
        return None
    stamps = [row[1] for row in rows[1:]] if rows else []
    if not stamps:
        return None
    picks: list[str] = []
    for lo, hi in _WAYBACK_WINDOWS:
        window = [t for t in stamps if lo <= t[:4] <= hi]
        if window:
            picks.append(window[-1])  # newest inside the window
    if stamps[0] not in picks:
        picks.append(stamps[0])  # oldest overall as the last resort
    for ts in picks[:3]:
        r2 = _get(_WAYBACK_RAW.format(ts=ts, url=url))
        time.sleep(1.0)  # Wayback rate limit is unforgiving
        if r2 is None or r2.status_code != 200:
            continue
        emails = _EMAIL_RE.findall(r2.text)
        picked = _pick_personal_email(emails, pi_name)
        if picked:
            return {"email": picked, "snapshot": ts, "source": "wayback"}
    return None


_SCHOOL_FNS = {
    "stanford": lambda o: stanford_email_for(o.get("pi_name") or "", _record_url(o)),
    "princeton": lambda o: princeton_wayback_email_for(o.get("pi_name") or "", _record_url(o)),
}


def _targets(opps: list[dict], school: str) -> list[dict]:
    return [
        o for o in opps
        if o.get("school") == school
        and (o.get("source") or "").endswith("_faculty")
        and o.get("pi_name") and _record_url(o)
        and not o.get("contact_email")
    ]


def harvest(opps: list[dict], school: str, *, sample: int | None = None,
            throttle: float = 0.5, progress: bool = False,
            checkpoint_path: str | None = None, checkpoint_every: int = 25,
            resume: bool = False) -> dict[str, dict]:
    """{url: {email, source, ...}} for one school's email-less faculty.
    Same checkpoint discipline as the OpenAlex harvests: matches AND misses
    flush periodically, resume skips both."""
    fn = _SCHOOL_FNS[school]
    targets = _targets(opps, school)
    if sample is not None:
        targets = targets[:sample]
    mapping, misses, targets = _load_resume_state(checkpoint_path, resume, targets)
    for i, o in enumerate(targets):
        found = fn(o)
        time.sleep(throttle)
        if found:
            mapping[_record_url(o)] = found
        else:
            misses.add(_record_url(o))
        if checkpoint_path and (i + 1) % checkpoint_every == 0:
            _flush_checkpoint(checkpoint_path, mapping, misses)
        if progress and (i + 1) % 25 == 0:
            print(f"  ...{i + 1}/{len(targets)}, {len(mapping)} found", flush=True)
    _flush_checkpoint(checkpoint_path, mapping, misses)
    return mapping


def apply_backfill(opps: list[dict], mapping: dict[str, dict]) -> int:
    """Updates-only: set contact_email + metadata.email_source on email-less
    faculty whose URL is in mapping. Never overwrites an existing address."""
    n = 0
    for o in opps:
        if o.get("contact_email"):
            continue
        entry = mapping.get(_record_url(o) or "")
        if not entry or not entry.get("email"):
            continue
        o["contact_email"] = entry["email"]
        o.setdefault("metadata", {})["email_source"] = entry["source"]
        n += 1
    return n


def _cli(argv: list[str]) -> int:
    if not argv or argv[0] not in ("harvest", "apply"):
        print(__doc__)
        return 2
    mode, rest = argv[0], argv[1:]
    opps = json.load(open(PROCESSED_FILE))
    if mode == "harvest":
        school = rest[0]
        if school not in _SCHOOL_FNS:
            print(f"unknown school {school!r}; supported: {sorted(_SCHOOL_FNS)}")
            return 2
        out = "backfill.json"
        sample = None
        resume = "--resume" in rest
        for i, a in enumerate(rest):
            if a == "--out":
                out = rest[i + 1]
            elif a == "--sample":
                sample = int(rest[i + 1])
        mapping = harvest(opps, school, sample=sample, progress=True,
                          checkpoint_path=out, resume=resume)
        print(f"found {len(mapping)} emails -> {out}")
        return 0
    merged: dict = {}
    for f in rest:
        merged.update(json.load(open(f)))
    n = apply_backfill(opps, merged)
    json.dump(opps, open(PROCESSED_FILE, "w"), ensure_ascii=False, indent=2)
    print(f"applied {n} emails from {len(rest)} map(s) -> {PROCESSED_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
