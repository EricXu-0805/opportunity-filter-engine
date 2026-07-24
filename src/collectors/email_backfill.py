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

**UIUC ECE/CEE — constructed netid address (Eric-approved 2026-07-14).** Both
departments' directory pages expose only shared admin inboxes (nslack@ etc.,
correctly nulled by the shared-inbox pass), leaving ECE at 3% / CEE at 0%
email coverage while every other UIUC college sits at 86-100% — and an ECE
student's top matches are exactly these people. Their profile URLs are
netid-keyed (``ece.illinois.edu/about/directory/faculty/<netid>``), and the
UIUC convention is ``<netid>@illinois.edu``. Validated against every record
with a cross-listed twin carrying a real observed address: 45/45 match, 0
mismatches (ECE 28, CEE 15, legacy hyphenated 2). Offline — no network.
Gates: URL host must be ece/cee.illinois.edu AND the slug must look like a
netid — modern (2-8 alphanumerics) or legacy (``b-hajek``: 1-2 letter initial
segment + surname); firstname-lastname slugs (``masooda-bashir``) are
rejected. Stamps ``metadata.email_source = "constructed_netid"``.

    python -m src.collectors.email_backfill harvest stanford --out st.json [--sample N] [--resume]
    python -m src.collectors.email_backfill harvest princeton --out pr.json [--sample N] [--resume]
    python -m src.collectors.email_backfill apply st.json pr.json
    python -m src.collectors.email_backfill construct-uiuc
"""
from __future__ import annotations

import json
import re
import sys
import time

import requests

from .atomic_json import atomic_write_json
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
    "utexas": lambda o: utexas_dm_email_for(o),
}

# UIUC netid construction: the profile URL must live on one of the two
# netid-keyed department hosts, and its slug must LOOK like a netid. Modern
# netids are 2-8 alphanumerics starting with a letter; legacy ones are a 1-2
# letter initial segment + hyphen + surname (+ optional digit), e.g. b-hajek.
# A dept site whose slugs are firstname-lastname never passes either shape.
_UIUC_NETID_HOST_RE = re.compile(r"^https?://(?:ece|cee)\.illinois\.edu/", re.IGNORECASE)
_UIUC_NETID_RES = (
    re.compile(r"^[a-z][a-z0-9]{1,7}$"),
    re.compile(r"^[a-z]{1,2}-[a-z]+[0-9]?$"),
)


_DM_REPORT = ("https://profiles.digitalmeasures.com/clients/{client}"
              "?reportId={report}&identifierKey=username&identifierValue={username}")
# Same public Digital Measures report the research-expertise enrichment reads
# (source of truth: schools/utexas_faculty.py _MCCOMBS_DM). One report serves
# the whole McCombs college.
_MCCOMBS_DM_CLIENT = "33273f60-e36d-5e3d-aef8-1d2311a16a9c"
_MCCOMBS_DM_REPORT = "f1ba5042-450f-11ef-9a63-33d5f7cc5693"
_MCCOMBS_URL_RE = re.compile(
    r"^https?://(?:www\.)?mccombs\.utexas\.edu/.*[?&]username=([A-Za-z0-9._-]+)",
    re.IGNORECASE,
)
_MAILTO_RE = re.compile(r'mailto:([A-Za-z0-9._%+-]+@[A-Za-z0-9.-]*utexas\.edu)', re.IGNORECASE)
_TAG_RE = re.compile(r"<[^>]+>")


def utexas_dm_email_for(o: dict) -> dict | None:
    """{email, display_block} from the McCombs Digital Measures profile report,
    or None. This is the school's own PUBLISHED contact block (name + title +
    mailto in one record), not a construction: the report is keyed by the
    campus username carried in the record's own listing URL, and the name-agree
    gate rejects a block that names someone else."""
    m = _MCCOMBS_URL_RE.match(_record_url(o) or "")
    if not m:
        return None
    r = _get(_DM_REPORT.format(client=_MCCOMBS_DM_CLIENT, report=_MCCOMBS_DM_REPORT,
                               username=m.group(1)))
    if r is None or r.status_code != 200:
        return None
    try:
        items = (r.json() or {}).get("items") or []
    except ValueError:
        return None
    for it in items:
        blk = it.get("data") if isinstance(it, dict) else None
        recs = blk.get("records") if isinstance(blk, dict) else None
        for rec in recs or []:
            value = rec.get("value") if isinstance(rec, dict) else None
            if not value or "mailto:" not in value:
                continue
            em = _MAILTO_RE.search(value)
            if not em:
                continue
            text = _TAG_RE.sub(" ", value)
            display = text.split("The University of Texas")[0].strip()
            if not _names_agree(o.get("pi_name") or "", display):
                return None
            return {"email": em.group(1), "display_name": display,
                    "source": "digitalmeasures_profile"}
    return None


def uiuc_netid_email_for(o: dict) -> dict | None:
    """Constructed ``<netid>@illinois.edu`` for one UIUC ECE/CEE faculty record,
    or None when the URL isn't on a netid-keyed host or the slug doesn't pass
    the netid shape gates."""
    url = _record_url(o) or ""
    if not _UIUC_NETID_HOST_RE.match(url):
        return None
    slug = _slug(url)
    if not slug or not any(rx.fullmatch(slug) for rx in _UIUC_NETID_RES):
        return None
    return {"email": f"{slug}@illinois.edu", "netid": slug,
            "source": "constructed_netid"}


def construct_uiuc(opps: list[dict]) -> int:
    """Apply the netid construction to every email-less UIUC faculty record
    (updates-only, provenance-stamped via apply_backfill)."""
    mapping = {
        _record_url(o): found
        for o in _targets(opps, "uiuc")
        if (found := uiuc_netid_email_for(o))
    }
    return apply_backfill(opps, mapping)


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
    if not argv or argv[0] not in ("harvest", "apply", "construct-uiuc"):
        print(__doc__)
        return 2
    mode, rest = argv[0], argv[1:]
    opps = json.load(open(PROCESSED_FILE))
    if mode == "construct-uiuc":
        n = construct_uiuc(opps)
        atomic_write_json(PROCESSED_FILE, opps)
        print(f"constructed {n} netid emails -> {PROCESSED_FILE}")
        return 0
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
    atomic_write_json(PROCESSED_FILE, opps)
    print(f"applied {n} emails from {len(rest)} map(s) -> {PROCESSED_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(_cli(sys.argv[1:]))
