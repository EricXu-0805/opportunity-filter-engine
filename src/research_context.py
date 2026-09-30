"""Bounded, identity-bound research material; never recruiting or student evidence.

Stored successful snapshots and operational refresh attempts are separate. Public
contexts contain no attempt metadata. Historical validation preserves its saved
status; only research_context_for evaluates current identity and freshness.
"""
from __future__ import annotations

import hashlib
import json
import re
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from urllib.parse import urlsplit, urlunsplit

# school slug -> OpenAlex institution id (resolved once via /institutions). The
# id is matched against each candidate author's full affiliation history, so a
# professor who has since moved is still matched while a same-name person at a
# different school is rejected.
SCHOOL_INST = {
    "uiuc": "I157725225",
    "uw": "I201448701",
    "ucla": "I161318765",
    "utexas": "I86519309",
    "stanford": "I97018004",
    "gatech": "I130701444",
    "wisc": "I135310074",
    # Verified 2026-07-05 via GET /institutions?search=… (display_name + ROR):
    "ucb": "I95457486",        # University of California, Berkeley (ror 01an7q238)
    "umich": "I27837315",      # University of Michigan [Ann Arbor] (ror 00jmfr291)
    "princeton": "I20089843",  # Princeton University (ror 00hx57361)
    "ucsd": "I36258959",       # University of California San Diego (ror 0168r3w48)
    "uchicago": "I40347166",   # University of Chicago (ror 024mw5h28)
    "ucd": "I84218800",        # University of California, Davis (API-verified 2026-07-21)
    "uci": "I204250578",       # University of California, Irvine (ror 04gyf1771)
    "ucsb": "I154570441",      # University of California, Santa Barbara (ror 02t274463)
    "boulder": "I188538660",   # University of Colorado Boulder (ror 02ttsq026)
    "purdue": "I219193219",    # Purdue University West Lafayette (ror 02dqehb95)
    "duke": "I170897317",      # Duke University (ror 00py81415)
    "jhu": "I145311948",       # Johns Hopkins University (OpenAlex-API verified)
    "northwestern": "I111979921",  # Northwestern University (OpenAlex-API verified)
    "upenn": "I79576946",      # University of Pennsylvania (OpenAlex-API verified)
    "caltech": "I122411786",   # California Institute of Technology (OpenAlex-API verified)
    # LAC ranks 11-25 (2026-07-23)
    "grinnell": "I173288447",  # Grinnell College
    "colby": "I27504731",  # Colby College
    "hamilton": "I188592606",  # Hamilton College
    "vassar": "I126820664",  # Vassar College
    "smith": "I202524275",  # Smith College
    "wlu": "I184889055",  # Washington and Lee University
    "colgate": "I39660569",  # Colgate University
    "wesleyan": "I100538780",  # Wesleyan University
    "haverford": "I155707491",  # Haverford College
    "bates": "I37415318",  # Bates College
    "barnard": "I98540497",  # Barnard College
    "coloradocollege": "I189774192",  # Colorado College
    "macalester": "I5444425",  # Macalester College
    "kenyon": "I166972335",  # Kenyon College
    "brynmawr": "I102373834",  # Bryn Mawr College
    # Top-10 liberal arts colleges (2026-07-21)
    "amherst": "I177605424",  # Amherst College
    "swarthmore": "I118020396",  # Swarthmore College
    "pomona": "I177881444",  # Pomona College
    "wellesley": "I189731429",  # Wellesley College
    "bowdoin": "I135474949",  # Bowdoin College
    "carleton": "I188497080",  # Carleton College
    "cmc": "I106107269",  # Claremont McKenna College
    "middlebury": "I195575238",  # Middlebury College
    "davidson": "I141720752",  # Davidson College
    # Wave-3 batch 1 (2026-07-20)
    "bc": "I103531236",  # Boston College
    "emory": "I150468666",  # Emory University
    "georgetown": "I184565670",  # Georgetown University
    "nyu": "I57206974",  # New York University
    "tufts": "I121934306",  # Tufts University
    "uva": "I51556381",  # University of Virginia
    "cornell": "I205783295",   # Cornell University (ror 05bnh6r87, OpenAlex-API verified)
    "rice": "I74775410",       # Rice University (ror 008zs3103, OpenAlex-API verified)
    "vanderbilt": "I200719446",  # Vanderbilt University (ror 02vm5rt34, OpenAlex-API verified)
    "brown": "I27804330",      # Brown University (ror 05gq02987, OpenAlex-API verified)
    "dartmouth": "I107672454",  # Dartmouth College (ror 049s0rh22, OpenAlex-API verified)
    "columbia": "I78577930",
    "mit": "I63966007",        # Massachusetts Institute of Technology (ror 042nb2s44, OpenAlex-API verified)
    "harvard": "I136199984",   # Harvard University (ror 03vek6s52, OpenAlex-API verified)
    "yale": "I32971472",       # Yale University (ror 03v76x132, OpenAlex-API verified)
    "cmu": "I74973139",        # Carnegie Mellon University (ror 05x2bcf33, OpenAlex-API verified)
    # Verified 2026-07-17 via GET /institutions?search=… (Wave-1 final seven):
    "usc": "I1174212",         # University of Southern California
    "umn": "I130238516",       # University of Minnesota [Twin Cities]
    "osu": "I52357470",        # The Ohio State University
    "nd": "I107639228",        # University of Notre Dame
    "rochester": "I5388228",   # University of Rochester
    "uf": "I33213144",         # University of Florida
    "umass": "I24603500",      # University of Massachusetts Amherst
    # Verified 2026-07-18 via GET /institutions?search=… (Wave-2 batch 1):
    "vt": "I859038795",        # Virginia Tech
    "tamu": "I91045830",       # Texas A&M University
    "umd": "I66946132",        # University of Maryland, College Park
    "neu": "I12912129",        # Northeastern University (US — NOT the CN homonym I9224756)
    "sbu": "I59553526",        # Stony Brook University
    "bu": "I111088046",        # Boston University
    "washu": "I204465549",     # Washington University in St. Louis
    "rutgers": "I102322142",   # Rutgers, The State University of New Jersey
    "ncsu": "I137902535",      # North Carolina State University
    "psu": "I130769515",       # Pennsylvania State University
    "ucsc": "I185103710",      # University of California, Santa Cruz
    "arizona": "I138006243",   # University of Arizona
    "ucr": "I103635307",       # University of California, Riverside
    "asu": "I55732556",        # Arizona State University
    "pitt": "I170201317",      # University of Pittsburgh
    "msu": "I87216513",        # Michigan State University
    "buffalo": "I63190737",
    "fsu": "I103163165",
    "usf": "I2613432",
    "utk": "I75027704",
    "clemson": "I8078737",
    "colostate": "I92446798",
    "oregonstate": "I131249849",
    "drexel": "I72816309",
    # Wave-5 batch 1 (2026-07-20)
    "stevens": "I108468826",  # Stevens Institute of Technology
    "njit": "I118118575",  # New Jersey Institute of Technology
    "wpi": "I107077323",  # Worcester Polytechnic Institute
    "uky": "I143302722",  # University of Kentucky
    "lehigh": "I186143895",  # Lehigh University
    "syracuse": "I70983195",  # Syracuse University
    "cincinnati": "I63135867",  # University of Cincinnati
    "unl": "I114395901",  # University of Nebraska-Lincoln
    "unc": "I114027177",  # University of North Carolina at Chapel Hill (API-verified 2026-07-26)
    "lsu": "I121820613",  # Louisiana State University
    "utdallas": "I162577319",  # University of Texas at Dallas
    "casewestern": "I58956616",
    "houston": "I44461941",
    "iastate": "I173911158",
    "indiana": "I4210119109",
    "miami": "I145608581",
    "rpi": "I165799507",
    "ucf": "I106165777",
    "uconn": "I140172145",
    "udel": "I86501945",
    "uiowa": "I126307644",
    "utah": "I223532165",
    # Verified 2026-07-18 via GET /institutions?search=University of Georgia:
    "uga": "I165733156",       # University of Georgia (US, ~141k works)
}

MAX_RESEARCH_WORKS = 3
MAX_RESEARCH_TITLE = 1000
MAX_RESEARCH_ABSTRACT = 12000
RESEARCH_MAX_AGE = timedelta(days=30)
RESEARCH_GATE_VERSION = 3
INVALID_AUTHOR_IDS = frozenset({'https://openalex.org/A9999999999', 'https://openalex.org/A5317838346'})
_SNAPSHOT_KEYS = {'version', 'source', 'record_source_url', 'identity_name', 'institution_id', 'author_id', 'gate_version', 'checked_at', 'works'}
_WORK_KEYS = {'work_id', 'title', 'year', 'publication_date', 'source_url', 'doi', 'abstract', 'abstract_status', 'updated_date'}
_DOI = re.compile(r'^https://doi\.org/10\.[0-9]{4,9}/[^\s?#]+$')
_CHECKED = re.compile(r'^[1-9][0-9]{3}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?Z$')
_DATE = re.compile(r'^[1-9][0-9]{3}-\d{2}-\d{2}$')
_UPDATED = re.compile(r'^[1-9][0-9]{3}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)?)?$')


def _text(value, maximum=None, *, nonblank=False):
    if type(value) is not str or '\x00' in value or (nonblank and not value.strip()):
        raise ValueError('invalid_research_context')
    try:
        value.encode('utf-8')
    except UnicodeEncodeError:
        raise ValueError('invalid_research_context') from None
    if maximum is not None and len(value) > maximum:
        raise ValueError('invalid_research_context')
    return value


def normalized_openalex_id(value, kind):
    """Collector accepts short/raw API IDs; persisted/public records require full IDs."""
    if type(value) is not str or kind not in ('A', 'I', 'W'):
        return None
    suffix = value.removeprefix('https://openalex.org/')
    if not re.fullmatch(kind + r'[1-9][0-9]*', suffix):
        return None
    normalized = 'https://openalex.org/' + suffix
    return None if normalized in INVALID_AUTHOR_IDS else normalized


def canonical_doi(value):
    if type(value) is not str:
        return None
    candidate = value.strip()
    for prefix in ('https://doi.org/', 'http://doi.org/', 'https://dx.doi.org/', 'http://dx.doi.org/'):
        if candidate.lower().startswith(prefix):
            candidate = candidate[len(prefix):]
            break
    candidate = 'https://doi.org/' + candidate
    try:
        _text(candidate, 2000)
        if '\\' in candidate:
            return None
    except ValueError:
        return None
    return candidate if _DOI.fullmatch(candidate) else None


def normalized_source_url(value):
    try:
        _text(value, 2000, nonblank=True)
        p = urlsplit(value)
        if p.scheme not in ('http', 'https') or not p.hostname or p.username or p.password or p.fragment:
            return None
        if '\\' in value or any(c.isspace() for c in value):
            return None
        _ = p.port
        return urlunsplit((p.scheme.lower(), p.netloc.lower(), p.path or '/', p.query, ''))
    except (ValueError, TypeError):
        return None


def _stamp(value):
    _text(value)
    if not _CHECKED.fullmatch(value):
        raise ValueError('invalid_research_context')
    return datetime.fromisoformat(value.replace('Z', '+00:00'))


def _snapshot(value):
    if type(value) is not dict or set(value) != _SNAPSHOT_KEYS:
        raise ValueError('invalid_research_context')
    if type(value['version']) is not int or value['version'] != 1 or value['source'] != 'openalex':
        raise ValueError('invalid_research_context')
    if normalized_source_url(value['record_source_url']) is None:
        raise ValueError('invalid_research_context')
    _text(value['identity_name'], 200, nonblank=True)
    for key, kind in [('institution_id', 'I'), ('author_id', 'A')]:
        if normalized_openalex_id(value[key], kind) != value[key] or value[key] is None:
            raise ValueError('invalid_research_context')
    if type(value['gate_version']) is not int or not RESEARCH_GATE_VERSION <= value['gate_version'] <= 9007199254740991:
        raise ValueError('invalid_research_context')
    _stamp(value['checked_at'])
    works = value['works']
    if type(works) is not list or len(works) > MAX_RESEARCH_WORKS:
        raise ValueError('invalid_research_context')
    seen = set()
    for work in works:
        if type(work) is not dict or set(work) != _WORK_KEYS:
            raise ValueError('invalid_research_context')
        wid = work['work_id']
        if normalized_openalex_id(wid, 'W') != wid or wid is None or wid in seen:
            raise ValueError('invalid_research_context')
        seen.add(wid)
        _text(work['title'], MAX_RESEARCH_TITLE, nonblank=True)
        if type(work['year']) is not int or not 1000 <= work['year'] <= 2100:
            raise ValueError('invalid_research_context')
        pub_date = work['publication_date']
        if pub_date is not None:
            if type(pub_date) is not str or not _DATE.fullmatch(pub_date) or date.fromisoformat(pub_date).year != work['year']:
                raise ValueError('invalid_research_context')
        updated = work['updated_date']
        if updated is not None:
            if type(updated) is not str or not _UPDATED.fullmatch(updated):
                raise ValueError('invalid_research_context')
            datetime.fromisoformat(updated.replace('Z', '+00:00'))
        doi = work['doi']
        if doi is not None and (type(doi) is not str or canonical_doi(doi) != doi):
            raise ValueError('invalid_research_context')
        if work['source_url'] != (doi or wid):
            raise ValueError('invalid_research_context')
        status = work['abstract_status']
        if status == 'present':
            _text(work['abstract'], MAX_RESEARCH_ABSTRACT, nonblank=True)
        elif status not in ('missing', 'invalid', 'too_long') or work['abstract'] is not None:
            raise ValueError('invalid_research_context')
    return deepcopy(value)


def research_snapshot_version(snapshot):
    copy = _snapshot(snapshot)
    body = json.dumps(copy, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode('utf-8')
    return 'rs1:' + hashlib.sha256(body).hexdigest()


def validate_public_research_context(value):
    """Strict historical shape/hash validation. Do not recompute its saved age/status."""
    try:
        if type(value) is not dict or set(value) != {'version', 'status', 'snapshot'} or type(value['version']) is not int or value['version'] != 1:
            return False
        if value['status'] == 'unavailable':
            return value['snapshot'] is None
        if value['status'] not in ('available', 'stale') or type(value['snapshot']) is not dict:
            return False
        public = value['snapshot']
        if set(public) != _SNAPSHOT_KEYS | {'snapshot_version'}:
            return False
        stored = {k: v for k, v in public.items() if k != 'snapshot_version'}
        return public['snapshot_version'] == research_snapshot_version(stored)
    except (ValueError, TypeError, OverflowError, RecursionError):
        return False


def _now(now):
    value = datetime.now(UTC) if now is None else now
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError('invalid_research_time')
    return value.astimezone(UTC)


def validate_research_snapshot(value, opp, *, now=None):
    """Validate an active corpus binding; return a detached snapshot or None."""
    try:
        snapshot = _snapshot(value)
        if type(opp) is not dict:
            return None
        md = opp.get('metadata')
        if type(md) is not dict or md.get('publication_attribution_status') != 'verified_author_id':
            return None
        if normalized_openalex_id(md.get('publication_author_id'), 'A') != snapshot['author_id']:
            return None
        if type(md.get('works_gate')) is not int or md['works_gate'] != snapshot['gate_version']:
            return None
        current_name = opp.get('pi_name')
        if type(current_name) is not str or ' '.join(current_name.casefold().split()) != ' '.join(snapshot['identity_name'].casefold().split()):
            return None
        current_urls = {normalized_source_url(opp.get(k)) for k in ('source_url', 'url')} - {None}
        if normalized_source_url(snapshot['record_source_url']) not in current_urls:
            return None
        institution = SCHOOL_INST.get(opp.get('school'))
        if normalized_openalex_id(institution, 'I') != snapshot['institution_id']:
            return None
        explicit_institution = md.get('publication_institution_id')
        if explicit_institution is not None and normalized_openalex_id(explicit_institution, 'I') != snapshot['institution_id']:
            return None
        if _stamp(snapshot['checked_at']) > _now(now):
            return None
        return snapshot
    except (ValueError, TypeError, OverflowError, RecursionError):
        return None


def research_context_for(opp, *, now=None):
    unavailable = {'version': 1, 'status': 'unavailable', 'snapshot': None}
    try:
        current = _now(now)
        value = (opp.get('metadata') or {}).get('research_snapshot') if type(opp) is dict else None
        snapshot = validate_research_snapshot(value, opp, now=current)
        if snapshot is None:
            return unavailable
        stale = current - _stamp(snapshot['checked_at']) > RESEARCH_MAX_AGE
        return {'version': 1, 'status': 'stale' if stale else 'available',
                'snapshot': {**snapshot, 'snapshot_version': research_snapshot_version(snapshot)}}
    except (ValueError, TypeError, AttributeError):
        return unavailable
