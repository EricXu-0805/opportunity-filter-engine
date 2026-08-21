"""R70-A data quality invariants for data/processed/opportunities.json.

These tests lock in the contract established by the R70-A migration so the
data file (and any new collector output merged into it) cannot regress on
the issues we just fixed:

  * Every record exposes description_clean (no more schema-A program_overview
    records with only `description` that the frontend can't read).
  * No record has both `deadline=None` AND `is_rolling != True` for the
    aggregator sources (uiuc_sro / uiuc_our_rss / manual) — those listings
    should always be marked rolling so the UI shows "Rolling" instead of
    a blank timing block.
  * description_clean never exceeds the documented 1500-char cap.
  * IDs remain unique.
  * Past-deadline records are deactivated (with a small leak allowance for
    the historical 1 record we know about; tighter than that would require
    a separate cleanup pass).
"""

from __future__ import annotations

import functools
import json
import re
from datetime import date, datetime
from pathlib import Path

import pytest

DATA_FILE = Path(__file__).resolve().parents[1] / "data" / "processed" / "opportunities.json"
DESCRIPTION_CAP = 1500
ROLLING_DEFAULT_SOURCES = {"uiuc_sro", "uiuc_our_rss", "manual"}
PAST_DEADLINE_LEAK_TOLERANCE = 0  # R70-C: zero tolerance now that deactivate_past runs in refresh_all

# R70-B: corruption patterns that pi_enricher used to emit when
# soup.get_text() concatenated adjacent HTML elements without a separator.
_PHONE_IN_LOCAL = re.compile(r"^[^@]*\d{3,4}-\d{3,4}")
_CAPS_MASHED_LOCAL = re.compile(r"^[A-Z][a-z]+[^A-Z_@]{12,}@")


@functools.lru_cache(maxsize=1)
def _load_data() -> list[dict]:
    # Parsed once per session and shared across every test in this module — the
    # corpus is 300 MB+ and every test below reads it strictly read-only, so
    # re-parsing it per test (there are ~40 of them) was the dominant CI cost.
    # Do not mutate the returned records.
    if not DATA_FILE.exists():
        pytest.skip(f"{DATA_FILE} not present")
    with DATA_FILE.open("r", encoding="utf-8") as f:
        return json.load(f)


def _is_faculty(o: dict) -> bool:
    """Faculty collectors (uiuc_faculty, ucb_eecs_faculty, ucb_stat_faculty)
    all emit source_type='faculty_research'; the ranker's faculty re-weighting
    keys on the same field, so these gates stay in lockstep with scoring as
    new faculty sources are added."""
    return o.get("source_type") == "faculty_research"


def _parse_iso(d):
    if not d or not isinstance(d, str):
        return None
    try:
        if "T" in d:
            return datetime.fromisoformat(d.replace("Z", "+00:00")).date()
        return datetime.strptime(d, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def _data_as_of(data: list[dict]) -> date:
    """The date the snapshot was last refreshed = newest last_seen_at across
    records. The past-deadline invariant must be anchored here, not to
    date.today(): deactivate_past runs at refresh time against the refresh
    clock, so a committed record can only be a *pipeline leak* if its deadline
    had already passed when the data was generated. Anchoring to date.today()
    instead made the test go red at midnight boundaries whenever the committed
    file aged past a still-active deadline — that is staleness, not a bug."""
    seen = [
        _parse_iso((o.get("metadata") or {}).get("last_seen_at"))
        for o in data
    ]
    seen = [d for d in seen if d]
    return max(seen) if seen else date.today()


def _is_past_deadline_leak(opp: dict, as_of: date) -> bool:
    """True iff this record is one deactivate_past should have retired.

    Mirrors the normalizer's deliberate skips, because a gate that demands
    what the normalizer refuses to do can never be satisfied — it just kills
    the refresh run:

      * ``is_rolling`` — an always-open posting whose deadline field is a
        cycle date, not a closing date;
      * ``deadline_is_estimate`` — W11 truthfulness: an nsf_reu deadline
        derived from the award start date is a labeled guess, so a passed
        estimate must not hard-flip is_active (the UI likewise renders past
        estimates as carrying no urgency rather than as 'passed').

    Shared by the snapshot gate and the contract test below so the rule can't
    drift from the normalizer again.
    """
    if opp.get("is_rolling") or opp.get("deadline_is_estimate"):
        return False
    dt = _parse_iso(opp.get("deadline"))
    if not dt or dt >= as_of:
        return False
    return opp.get("metadata", {}).get("is_active") is not False


class TestR70ADataQuality:
    def test_every_record_has_description_clean(self):
        """R70-A backfilled 25 program_overview records that previously
        only had a `description` field. The frontend reads
        `description_clean || description_raw` so every record needs at
        least one of those, and ideally description_clean."""
        data = _load_data()
        missing = [
            o
            for o in data
            if "description_clean" not in o
        ]
        assert not missing, (
            f"{len(missing)} records missing description_clean key "
            f"(first 3 ids: {[o.get('id') for o in missing[:3]]})"
        )

    def test_aggregator_sources_have_deadline_or_rolling(self):
        """R70-A defaulted is_rolling=True for 308 records across
        uiuc_sro/uiuc_our_rss/manual that had no deadline. New records
        from those sources must keep that invariant."""
        data = _load_data()
        offenders = [
            o
            for o in data
            if o.get("source") in ROLLING_DEFAULT_SOURCES
            and not o.get("deadline")
            and o.get("is_rolling") is not True
        ]
        assert not offenders, (
            f"{len(offenders)} records from aggregator sources have "
            f"neither deadline nor is_rolling=True. First 3: "
            f"{[(o.get('source'), o.get('id')) for o in offenders[:3]]}"
        )

    def test_description_clean_within_cap(self):
        """R70-A raised the cap from 500 → 1500; nothing should exceed it."""
        data = _load_data()
        over_cap = [
            o
            for o in data
            if len(o.get("description_clean") or "") > DESCRIPTION_CAP
        ]
        assert not over_cap, (
            f"{len(over_cap)} records exceed the {DESCRIPTION_CAP}-char "
            f"description_clean cap (first 3 ids: "
            f"{[o.get('id') for o in over_cap[:3]]})"
        )

    def test_compensation_details_not_leaked_metadata_blob(self):
        """uiuc_sro deep-scrape built compensation_details by concatenating
        ±40-char windows around paid keywords with ' | ', leaking adjacent
        Duration/Citizenship metadata ("… Duration 10 weeks Compensation $7,000
        Citizenship Requirement No …"). The collector now extracts the real
        value (_clean_compensation); no record may carry the leaked-blob
        signature."""
        leaked = re.compile(r" \| |citizenship requirement|duration\s+\d", re.IGNORECASE)
        offenders = [
            (o.get("id"), (o.get("compensation_details") or "")[:80])
            for o in _load_data()
            if leaked.search(o.get("compensation_details") or "")
        ]
        assert not offenders, (
            f"{len(offenders)} records have a leaked-metadata compensation_details "
            f"blob (collector should emit a clean value). First 3: {offenders[:3]}"
        )

    def test_compensation_no_absurd_hourly_or_redundant_range(self):
        """Handshake mislabeled monthly research/internship stipends as "Per
        hour" ("$2250-$2250 Per hour") and emitted redundant equal ranges. No
        served record may carry a >= $200/hr rate (not a real undergrad wage —
        the collector drops the implausible period) or a duplicated "$X-$X"
        range (collapsed to "$X"). _normalize_compensation enforces both."""
        dup_range = re.compile(r"\$(\d[\d,]*)-\$\1\b")
        offenders = []
        for o in _load_data():
            s = (o.get("compensation_details") or "").replace(",", "")
            if not s:
                continue
            m = re.search(r"\$(\d+)\b", s)
            absurd_hourly = (
                m and int(m.group(1)) >= 200 and re.search(r"\bper hour\b", s, re.I)
            )
            if dup_range.search(s) or absurd_hourly:
                offenders.append((o.get("id"), (o.get("compensation_details") or "")[:60]))
        assert not offenders, (
            f"{len(offenders)} records have an absurd >=$200/hr rate or a "
            f"redundant $X-$X range. First 3: {offenders[:3]}"
        )

    def test_ids_unique(self):
        """Every record has a unique id."""
        data = _load_data()
        ids = [o.get("id") for o in data if o.get("id")]
        assert len(ids) == len(set(ids)), (
            f"Duplicate ids found: {len(ids) - len(set(ids))} duplicates"
        )

    def test_no_deprecated_metadata_keys(self):
        """Five small collectors (siebel/urap/ursa/drp/other) used to emit
        non-canonical metadata field names — first_seen instead of
        first_seen_at and scraped_at instead of last_verified — which the
        rest of the pipeline never reads. After the collector fix + data
        migration no record may carry the deprecated keys."""
        data = _load_data()
        deprecated = {"first_seen", "scraped_at"}
        offenders = [
            (o.get("id"), sorted(deprecated & (o.get("metadata") or {}).keys()))
            for o in data
            if deprecated & (o.get("metadata") or {}).keys()
        ]
        assert not offenders, (
            f"{len(offenders)} records carry deprecated metadata keys "
            f"(first_seen/scraped_at). First 3: {offenders[:3]}"
        )

    def test_ranker_dereferenced_fields_are_well_typed(self):
        """The matcher dereferences ``eligibility``/``metadata`` as dicts and
        iterates ``keywords`` as a list on every served record (rank_all,
        score_eligibility, _similarity_corpus). A collector that emits one of
        these as None or a wrong type would crash the matcher mid-request.
        Guard the contract at the data boundary (the right place) rather than
        with defensive None-checks in the hot ranking loop."""
        offenders: list[tuple] = []
        for o in _load_data():
            elig = o.get("eligibility", {})
            meta = o.get("metadata", {})
            kws = o.get("keywords", [])
            if not isinstance(elig, dict):
                offenders.append((o.get("id"), "eligibility", type(elig).__name__))
            if not isinstance(meta, dict):
                offenders.append((o.get("id"), "metadata", type(meta).__name__))
            if not isinstance(kws, list):
                offenders.append((o.get("id"), "keywords", type(kws).__name__))
        assert not offenders, (
            f"{len(offenders)} records have a matcher-dereferenced field with the "
            f"wrong type (eligibility/metadata must be dicts, keywords a list). "
            f"First 5: {offenders[:5]}"
        )

    def test_no_corrupted_contact_emails(self):
        """R70-B: pi_enricher used to extract phone-number-prefixed or
        capitalized-label-mashed addresses from HTML pages where adjacent
        elements lacked whitespace separators. After the fix + cleanup
        migration, no record should have a contact_email matching the
        known corruption patterns."""
        data = _load_data()
        corrupted = []
        for o in data:
            ce = o.get("contact_email")
            if not isinstance(ce, str) or "@" not in ce:
                continue
            if _PHONE_IN_LOCAL.match(ce) or _CAPS_MASHED_LOCAL.match(ce):
                corrupted.append((o.get("id"), ce))
        assert not corrupted, (
            f"{len(corrupted)} records have corruption-pattern contact_email "
            f"values. First 3: {corrupted[:3]}"
        )

    def test_past_deadline_deactivated(self):
        """Records whose deadline had already passed *as of the snapshot's
        refresh date* must be is_active=False (handled by
        src.normalizers.deactivate_past, wired into refresh_all.py per R70-C
        so every refresh closes the loop). Zero tolerance — any leak means
        deactivate_past was bypassed at generation time.

        Anchored to the data's as-of date (newest last_seen_at), NOT
        date.today(): the deterministic logic of deactivate_past is covered
        separately by TestDeactivatePastLogic, and anchoring this snapshot
        assertion to the wall clock made it flake at midnight boundaries when
        the committed file aged past a deadline that was still live at refresh.
        """
        data = _load_data()
        as_of = _data_as_of(data)
        leaks = [o.get("id") for o in data if _is_past_deadline_leak(o, as_of)]
        assert len(leaks) <= PAST_DEADLINE_LEAK_TOLERANCE, (
            f"{len(leaks)} records past-deadline as of {as_of} still "
            f"is_active=True (tolerance: {PAST_DEADLINE_LEAK_TOLERANCE}). "
            f"First 3: {leaks[:3]}"
        )

    def test_no_shared_department_keyword_pollution(self):
        """DQ-1: a department-wide 'Research Areas' nav block scraped into many
        profiles produced byte-identical multi-keyword sets across same-department
        faculty (74 CS profs all 'doing compilers'), giving false specific matches.
        After the demotion fix no uiuc_faculty multi-keyword set may be shared by
        more than the collector's threshold of same-department peers.

        Deliberately NOT widened to the ucb_* faculty sources: their keywords
        map each professor's curated research-area memberships onto a fixed
        keyword bank, so same-area peers legitimately share small identical
        sets (e.g. 8 EECS profs all tagged AI+Robotics). The shared-set
        heuristic only signals pollution for page-scraped keywords."""
        from collections import defaultdict

        from src.collectors.uiuc_faculty import _SHARED_KEYWORD_POLLUTION_THRESHOLD

        groups: dict[tuple[str, tuple[str, ...]], int] = defaultdict(int)
        for o in _load_data():
            if o.get("source") != "uiuc_faculty":
                continue
            kws = tuple(sorted((k or "").lower() for k in (o.get("keywords") or [])))
            if len(kws) >= 2:
                groups[(o.get("department", ""), kws)] += 1
        polluted = {k: n for k, n in groups.items() if n > _SHARED_KEYWORD_POLLUTION_THRESHOLD}
        assert not polluted, (
            f"{len(polluted)} department-block keyword sets still shared by "
            f">{_SHARED_KEYWORD_POLLUTION_THRESHOLD} peers. First: {list(polluted.items())[:2]}"
        )

    def test_no_shared_admin_contact_emails(self):
        """D3: a scraped department/advising inbox (amwhit@ on 123 profs, nslack@
        on 116) attached as many professors' contact_email misfires cold emails to
        the wrong person. After the null-pass no faculty contact_email may be
        shared by the collector's threshold of distinct professors."""
        from collections import defaultdict

        from src.collectors.uiuc_faculty import _SHARED_ADMIN_EMAIL_THRESHOLD

        names_by_email: dict[str, set[str]] = defaultdict(set)
        for o in _load_data():
            if not _is_faculty(o):
                continue
            email = (o.get("contact_email") or "").strip().lower()
            if email:
                names_by_email[email].add((o.get("pi_name") or "").strip().lower())
        shared = {e: len(n) for e, n in names_by_email.items()
                  if len(n) >= _SHARED_ADMIN_EMAIL_THRESHOLD}
        assert not shared, (
            f"{len(shared)} contact email(s) still shared by "
            f">={_SHARED_ADMIN_EMAIL_THRESHOLD} distinct professors: {shared}"
        )

    def test_faculty_title_parenthetical_is_subset_of_keywords(self):
        """D1/D2: the parenthetical in a faculty title ("— CS (areas)") must name
        only the record's own keywords, never a scraped department nav-menu. Any
        area shown but absent from keywords is false-precise pollution."""
        import re

        offenders = []
        for o in _load_data():
            if not _is_faculty(o):
                continue
            m = re.search(r" — .+? \((.+)\)$", o.get("title", ""))
            if not m:
                continue
            shown = {a.strip().lower() for a in m.group(1).split(",")}
            kws = {(k or "").strip().lower() for k in (o.get("keywords") or [])}
            extra = shown - kws
            if extra:
                offenders.append((o.get("id"), extra))
        assert not offenders, (
            f"{len(offenders)} faculty titles show areas absent from their "
            f"keywords (nav-menu pollution). First: {offenders[:3]}"
        )

    def test_faculty_description_has_no_navmenu_leak(self):
        """D2: scraped page furniture must not survive in faculty descriptions."""
        NAV = ["Once Research Secured", "Administration & Staff", "Colloquia Calendar",
               "Affiliated Faculty", "Labs & Facilities", "Research Institutes and Centers"]
        leaks = [
            o.get("id") for o in _load_data()
            if _is_faculty(o)
            and any(n in (o.get("description_clean") or "") for n in NAV)
        ]
        assert not leaks, f"{len(leaks)} faculty descriptions still leak nav-menu text: {leaks[:3]}"

    def test_faculty_keywords_have_no_fragment_leadins(self):
        """A keyword like 'such as speech' or 'particularly using liquid lithium'
        is a scraped sentence fragment, not a research area — the lead-in must be
        stripped so the real topic ('speech', 'liquid lithium') stands alone."""
        import re
        lead = re.compile(
            r"^(?:such as|particularly|especially|including|namely|e\.g\.?)\b",
            re.IGNORECASE,
        )
        offenders = [
            (o.get("id"), k)
            for o in _load_data()
            if _is_faculty(o)
            for k in (o.get("keywords") or [])
            if lead.match((k or "").strip())
        ]
        assert not offenders, (
            f"{len(offenders)} faculty keywords are sentence fragments. "
            f"First: {offenders[:3]}"
        )

    def test_faculty_keywords_have_no_junk(self):
        """No faculty keyword may be page furniture, a dangling/truncated fragment,
        or a sentence fragment (re-enrich + _strip_furniture_keywords guarantee
        this). Uses the same _is_junk_keyword the pipeline filters on."""
        from src.collectors.uiuc_faculty import _is_junk_keyword
        offenders = [
            (o.get("id"), k)
            for o in _load_data()
            if _is_faculty(o)
            for k in (o.get("keywords") or [])
            if _is_junk_keyword(k)
        ]
        assert not offenders, (
            f"{len(offenders)} faculty keywords are junk (furniture/truncation/"
            f"fragment). First: {offenders[:5]}"
        )

    def test_faculty_keywords_have_no_duplicates(self):
        """A keyword list is a set of distinct areas; a repeated keyword (e.g.
        'genetics, genetics') is scrape noise that also doubles up in the title
        parenthetical. faculty_graph's keyword hygiene de-dupes order-preserving
        (case-insensitively), so no faculty record may carry a duplicate."""
        offenders = []
        for o in _load_data():
            if not _is_faculty(o):
                continue
            kws = o.get("keywords") or []
            lowered = [(k or "").strip().lower() for k in kws]
            if len(lowered) != len(set(lowered)):
                offenders.append((o.get("id"), kws))
        assert not offenders, (
            f"{len(offenders)} faculty records carry duplicate keywords. "
            f"First: {offenders[:3]}"
        )

    def test_no_same_school_same_email_faculty_duplicates(self):
        """A cross-appointed professor listed under two departments shares one
        personal email; those rows must collapse to a single record (else the
        person surfaces twice and could be cold-emailed twice). A genuinely
        shared department/advising inbox is nulled instead. Either way, no two
        ACTIVE faculty at one school may share a non-null contact_email —
        collapse_same_person_faculty guarantees this on every refresh."""
        from collections import defaultdict

        by_key: dict[tuple[str, str], list[str]] = defaultdict(list)
        for o in _load_data():
            if not _is_faculty(o):
                continue
            if not (o.get("metadata") or {}).get("is_active", True):
                continue
            email = (o.get("contact_email") or "").strip().lower()
            if email:
                by_key[(o.get("school"), email)].append(o.get("id"))
        dups = {k: ids for k, ids in by_key.items() if len(ids) > 1}
        assert not dups, (
            f"{len(dups)} school+email pairs have >1 active faculty record "
            f"(uncollapsed joint appointment or shared inbox). First: "
            f"{list(dups.items())[:3]}"
        )

    def test_no_scraped_title_label_leak_in_descriptions(self):
        """A directory card's rank field is sometimes prefixed with its scraped
        label ("Position title: …" / "Title: …"); it must not leak into the
        user-facing description ("Research opportunity with Position title: …").
        The faculty_graph title cleaner strips it at the source."""
        import re
        leak = re.compile(r"\b(?:position\s+title|title)\s*:", re.IGNORECASE)
        offenders = [
            o.get("id") for o in _load_data()
            if _is_faculty(o) and leak.search(o.get("description_clean") or "")
        ]
        assert not offenders, f"{len(offenders)} descriptions leak a scraped title label: {offenders[:5]}"

    def test_single_date_fields_are_iso(self):
        """posted_date, start_date and a timestamped deadline must be ISO
        YYYY-MM-DD so the 'newest' sort, the deadline-urgency badge, and the
        rendered Start date read uniformly across sources (nsf_reu shipped
        posted_date AND start_date as MM/DD/YYYY, handshake shipped a full ISO
        timestamp)."""
        import re
        mmdd = re.compile(r"^\d{1,2}/\d{1,2}/\d{4}$")
        bad_posted = [
            o.get("id") for o in _load_data()
            if isinstance(o.get("posted_date"), str) and mmdd.match(o["posted_date"])
        ]
        bad_start = [
            o.get("id") for o in _load_data()
            if isinstance(o.get("start_date"), str) and mmdd.match(o["start_date"])
        ]
        bad_deadline = [
            o.get("id") for o in _load_data()
            if isinstance(o.get("deadline"), str) and "T" in o["deadline"]
        ]
        assert not bad_posted, f"{len(bad_posted)} posted_date still MM/DD/YYYY: {bad_posted[:5]}"
        assert not bad_start, f"{len(bad_start)} start_date still MM/DD/YYYY: {bad_start[:5]}"
        assert not bad_deadline, f"{len(bad_deadline)} deadline still a timestamp: {bad_deadline[:5]}"

    def test_descriptions_have_no_nav_chrome(self):
        """A whole-page scrape can append site chrome (skip-links, the nav
        toggle, the mobile menu) into a description excerpt — it reads as a
        broken scrape and pollutes text signal. No shown description may carry
        an unambiguous chrome marker."""
        import re
        chrome = re.compile(r"skip to (?:main )?content|toggle navigation", re.IGNORECASE)
        offenders = [
            o.get("id") for o in _load_data()
            if chrome.search((o.get("description_clean") or "") + " " + (o.get("description_raw") or ""))
        ]
        assert not offenders, f"{len(offenders)} descriptions leak nav chrome: {offenders[:5]}"

    def test_faculty_have_no_inferred_skills(self):
        """Faculty are cold-email research contacts, not postings with required
        skills. Inferring skills from research-topic prose is false-precise (a
        topology professor tagged FEA-required) and degrades their match score,
        so no faculty_research record may carry skills_required/skills_preferred."""
        offenders = [
            o.get("id") for o in _load_data()
            if _is_faculty(o) and (
                (o.get("eligibility") or {}).get("skills_required")
                or (o.get("eligibility") or {}).get("skills_preferred")
            )
        ]
        assert not offenders, f"{len(offenders)} faculty carry inferred skills: {offenders[:5]}"

    def test_single_letter_skills_only_with_context(self):
        """Substring skill extraction once matched the bare letters 'C' and 'R'
        inside ordinary prose, tagging 549 NSF REU abstracts with
        skills_required=["C", "R"]. The live enricher legitimately emits them
        only behind context gates ("R programming", not bare "R" — see
        SKILL_PATTERNS), so a single-letter skill is junk exactly when the
        enricher itself would NOT extract it from the record's own text."""
        from src.normalizers.enricher import _combined_text, _extract_skills_from_text

        offenders = []
        for o in _load_data():
            elig = o.get("eligibility") or {}
            singles = {
                s.strip()
                for field in ("skills_required", "skills_preferred")
                for s in elig.get(field) or []
                if isinstance(s, str) and len(s.strip()) <= 1
            }
            if not singles:
                continue
            legitimate = set(_extract_skills_from_text(_combined_text(o)))
            for s in sorted(singles - legitimate):
                offenders.append((o.get("id"), s))
        assert not offenders, (
            f"{len(offenders)} context-less single-letter skill entries: {offenders[:5]}"
        )

    def test_faculty_have_no_bare_research_keyword(self):
        """A bare 'research' (or other nav-junk) single-word keyword is
        zero-signal noise as a tag chip — every faculty keyword must be a real
        area."""
        nav_junk = {"research", "people", "overview", "directory", "news", "events", "resources"}
        offenders = [
            o.get("id") for o in _load_data()
            if _is_faculty(o)
            and any(isinstance(k, str) and k.lower().strip() in nav_junk for k in (o.get("keywords") or []))
        ]
        assert not offenders, f"{len(offenders)} faculty carry a bare nav-junk keyword: {offenders[:5]}"

    def test_no_duplicate_faculty_at_same_url(self):
        """A cross-appointed professor scraped from two department pages shares
        one profile URL — those must be collapsed to a single record so the
        person isn't shown twice in results."""
        from collections import Counter
        counts = Counter(
            (o.get("school"), o.get("url") or o.get("source_url"), o.get("pi_name"))
            for o in _load_data()
            if _is_faculty(o) and o.get("pi_name") and (o.get("url") or o.get("source_url"))
        )
        dups = [k for k, n in counts.items() if n > 1]
        assert not dups, f"{len(dups)} faculty appear >1× at the same URL: {dups[:3]}"

    def test_no_ucb_joint_appointment_duplicates(self):
        """Joint-appointment professors (EECS+Statistics) used to appear in both
        ucb_eecs_faculty and ucb_stat_faculty, surfacing twice in results.
        Dedup policy: keep the ucb_eecs_faculty record (richer keywords), drop
        the ucb_stat_faculty one. No two ucb_* records may share a non-null
        contact_email or a normalized pi_name, so a re-scrape can't silently
        reintroduce the duplicates."""
        from collections import defaultdict

        by_email: dict[str, list[str]] = defaultdict(list)
        by_name: dict[str, list[str]] = defaultdict(list)
        for o in _load_data():
            if not (o.get("source") or "").startswith("ucb_"):
                continue
            email = (o.get("contact_email") or "").strip().lower()
            if email:
                by_email[email].append(o.get("id"))
            name = (o.get("pi_name") or "").casefold().strip()
            if name:
                by_name[name].append(o.get("id"))
        dup_emails = {e: ids for e, ids in by_email.items() if len(ids) > 1}
        dup_names = {n: ids for n, ids in by_name.items() if len(ids) > 1}
        assert not dup_emails and not dup_names, (
            f"ucb_* joint-appointment duplicates: "
            f"shared emails {dup_emails} / shared names {dup_names}"
        )

    def test_no_ucb_institution_pi_names(self):
        """A directory card occasionally mis-selects a non-person element (a
        "UC Berkeley" footer link, a breadcrumb) as a faculty name, entering the
        corpus as pi_name="Berkeley". Caught here even as a single record — the
        joint-appointment test only fires when two such records collide."""
        from src.collectors.ucb_common import _is_person_name

        offenders = [
            (o.get("id"), o.get("pi_name"))
            for o in _load_data()
            if (o.get("source") or "").startswith("ucb_")
            and o.get("pi_name")
            and not _is_person_name(o["pi_name"])
        ]
        assert not offenders, (
            f"{len(offenders)} ucb_* records have an institution/place pi_name "
            f"(scrape mis-selected a non-person element). First: {offenders[:5]}"
        )


class TestDeactivatePastLogic:
    """Deterministic guard for the deactivate_past normalizer itself, using an
    injected `today` so it never depends on the wall clock (unlike the snapshot
    invariant above). This is the real logic contract; the snapshot test only
    confirms the committed file honored it at generation time."""

    REF = date(2026, 1, 15)

    def _run(self, opps):
        from src.normalizers.deactivate_past import deactivate_past

        return deactivate_past(opps, today=self.REF)

    def test_past_deadline_marked_inactive_with_metadata(self):
        opp = {"id": "x", "deadline": "2026-01-01"}
        counts = self._run([opp])
        assert opp["metadata"]["is_active"] is False
        assert opp["metadata"]["deactivated_at"] == self.REF.isoformat()
        assert opp["metadata"]["deactivation_reason"] == "deadline_passed"
        assert counts["newly_deactivated"] == 1

    def test_future_deadline_kept_active(self):
        opp = {"id": "x", "deadline": "2026-12-31"}
        counts = self._run([opp])
        assert opp.get("metadata", {}).get("is_active") is not False
        assert counts["kept_active"] == 1

    def test_rolling_is_skipped(self):
        opp = {"id": "x", "deadline": "2026-01-01", "is_rolling": True}
        counts = self._run([opp])
        assert opp.get("metadata", {}).get("is_active") is not False
        assert counts["skipped_rolling"] == 1

    def test_no_deadline_is_skipped(self):
        opp = {"id": "x", "deadline": None}
        counts = self._run([opp])
        assert counts["skipped_no_deadline"] == 1

    def test_unparseable_deadline_is_skipped(self):
        opp = {"id": "x", "deadline": "sometime next spring"}
        counts = self._run([opp])
        assert opp.get("metadata", {}).get("is_active") is not False
        assert counts["skipped_invalid"] == 1

    def test_already_inactive_is_idempotent(self):
        """Re-running must not overwrite the original deactivated_at stamp."""
        opp = {
            "id": "x",
            "deadline": "2026-01-01",
            "metadata": {"is_active": False, "deactivated_at": "2025-12-01"},
        }
        counts = self._run([opp])
        assert counts["already_inactive"] == 1
        assert counts["newly_deactivated"] == 0
        assert opp["metadata"]["deactivated_at"] == "2025-12-01"

    def test_estimated_deadline_is_skipped(self):
        """W11 truthfulness: an nsf_reu deadline derived from the award start
        date is a labeled guess, so a passed estimate must not hard-flip
        is_active — the UI already renders past estimates as carrying no
        urgency rather than as 'passed'."""
        opp = {"id": "x", "deadline": "2026-01-01", "deadline_is_estimate": True}
        counts = self._run([opp])
        assert opp.get("metadata", {}).get("is_active") is not False
        assert counts["skipped_estimate"] == 1

    def test_snapshot_gate_agrees_with_the_deactivator(self):
        """The snapshot leak rule and the normalizer must classify identically.

        They drifted: W11 (#702) taught deactivate_past to skip estimated
        deadlines, but the snapshot gate above kept the pre-W11 rule at zero
        tolerance — so the moment an estimate's projected date passes, a gate
        the normalizer provably cannot satisfy kills the whole refresh run
        (2026-08-02, 139 nsf_reu records; three more come due 2027-02-15).
        """
        past, future = "2026-01-01", "2026-12-31"
        shapes = [
            {"id": "hard-past", "deadline": past},
            {"id": "hard-future", "deadline": future},
            {"id": "estimate-past", "deadline": past, "deadline_is_estimate": True},
            {"id": "estimate-future", "deadline": future, "deadline_is_estimate": True},
            {"id": "rolling-past", "deadline": past, "is_rolling": True},
            {"id": "no-deadline", "deadline": None},
            {"id": "unparseable", "deadline": "sometime next spring"},
        ]
        self._run(shapes)
        unsatisfiable = [
            opp["id"]
            for opp in shapes
            if _is_past_deadline_leak(opp, self.REF)
            and opp.get("metadata", {}).get("is_active") is not False
        ]
        assert not unsatisfiable, (
            "the snapshot gate flags records deactivate_past deliberately "
            f"leaves active, so no refresh can ever satisfy it: {unsatisfiable}"
        )


class TestDeactivatePastShardPass:
    """The work-file pass alone cannot satisfy the zero-tolerance gate.

    A refresh publishes only the shards its rotation authorized (#722), so a
    record that crosses its deadline in one of the other ~100 shards has its
    retirement computed against the work file and then discarded. The next CI
    run reassembles the corpus from shards and the record is active again —
    which is exactly how handshake-56d6cdae (uiuc, deadline 2026-08-06) failed
    the gate on a day-4 run and killed the 2026-08-13 refresh.
    """

    REF = date(2026, 6, 1)

    def _shard(self, tmp_path, name, records):
        shards = tmp_path / "shards"
        shards.mkdir(exist_ok=True)
        # Committed shards are minified; the pass must round-trip that.
        (shards / f"{name}.json").write_text(
            json.dumps(records, separators=(",", ":")), encoding="utf-8",
        )
        return shards

    def test_retires_a_record_in_a_shard_this_run_never_scraped(self, tmp_path):
        from src.normalizers.deactivate_past import deactivate_past_in_shards

        shards = self._shard(tmp_path, "uiuc", [
            {"id": "stranded", "deadline": "2026-05-01",
             "metadata": {"is_active": True}},
        ])
        changed = deactivate_past_in_shards(shards, self.REF, save=True)

        assert changed["uiuc"]["newly_deactivated"] == 1
        written = json.loads((shards / "uiuc.json").read_text(encoding="utf-8"))
        assert written[0]["metadata"]["is_active"] is False
        assert written[0]["metadata"]["deactivation_reason"] == "deadline_passed"
        # Minified, or the next split diffs every line of a 5 MB shard.
        assert (shards / "uiuc.json").read_text(encoding="utf-8").startswith('[{"id"')

    def test_leaves_untouched_shards_byte_identical(self, tmp_path):
        """It must be safe on shards the run had no authority over.

        Rewriting one from the run's in-memory corpus is what #722 forbade; the
        guarantee here is narrower and mechanical — nothing to retire, nothing
        written.
        """
        from src.normalizers.deactivate_past import deactivate_past_in_shards

        shards = self._shard(tmp_path, "ucb", [
            {"id": "future", "deadline": "2026-12-31", "metadata": {"is_active": True}},
            {"id": "rolling", "deadline": "2026-01-01", "is_rolling": True,
             "metadata": {"is_active": True}},
            {"id": "already", "deadline": "2026-01-01",
             "metadata": {"is_active": False, "deactivated_at": "2026-01-02"}},
        ])
        before = (shards / "ucb.json").read_bytes()
        changed = deactivate_past_in_shards(shards, self.REF, save=True)

        assert changed == {}
        assert (shards / "ucb.json").read_bytes() == before

    def test_dry_run_reports_without_writing(self, tmp_path):
        from src.normalizers.deactivate_past import deactivate_past_in_shards

        shards = self._shard(tmp_path, "mit", [
            {"id": "stranded", "deadline": "2026-05-01",
             "metadata": {"is_active": True}},
        ])
        before = (shards / "mit.json").read_bytes()
        changed = deactivate_past_in_shards(shards, self.REF, save=False)

        assert changed["mit"]["newly_deactivated"] == 1
        assert (shards / "mit.json").read_bytes() == before

    def test_the_publication_path_actually_runs_it(self):
        """Wiring, not capability — the recurring shape of this repo's bugs.

        deactivate_past has been implemented and unit-tested since R70-C; what
        was missing was anything calling it on the committed representation.
        """
        workflow = (
            Path(__file__).resolve().parents[1]
            / ".github" / "workflows" / "refresh-data.yml"
        ).read_text(encoding="utf-8")
        split_at = workflow.index("shard_corpus.py split --only-shards")
        pass_at = workflow.find("deactivate_past --shards --save")
        assert pass_at != -1, (
            "the shard pass is not in the publication path, so retirements "
            "outside this run's rotation are still discarded"
        )
        assert pass_at > split_at, (
            "the pass must run AFTER the split, or the split overwrites the "
            "authorized shards from the work file and re-strands the rest"
        )


class TestOnCampusMeansOnACampus:
    """`on_campus` describes the record, not the reader.

    It used to mean "on the UIUC campus" — the only campus the product served —
    and every collector added after that inherited the literal `False` rather
    than the intent, right through 117 schools. So a Berkeley professor's lab
    said it was not on a campus, and the ranker's F-1 "no work authorization
    concerns" advantage (score_upside, gated on on_campus AND
    opportunity.school == profile.home_school) was unreachable everywhere
    except UIUC. Whose campus it is has its own field and its own comparison;
    this one is about the place.

    The contract lives here rather than in the ~40 per-department collector
    tests that each assert their own copy of it.
    """

    # The one school-scoped source that legitimately lists off-campus employers:
    # a UIUC Handshake posting can be at a company across the country, and the
    # collector already decides per posting from the posting's own city.
    SELF_COMPUTED_SOURCES = {"handshake"}

    def test_no_faculty_record_claims_to_be_off_campus(self):
        offenders = [
            (o.get("source"), o.get("id"))
            for o in _load_data()
            if o.get("source_type") == "faculty_research"
            and o.get("on_campus") is False
        ]
        assert not offenders, (
            f"{len(offenders)} faculty contact records assert off-campus; "
            f"a directory without opening/location evidence must stay unknown. "
            f"First 3: {offenders[:3]}"
        )

    def test_school_scoped_records_are_on_that_schools_campus(self):
        offenders = [
            (o.get("source"), o.get("id"))
            for o in _load_data()
            if o.get("school") is not None
            and o.get("source_type") != "faculty_research"
            and o.get("source") not in self.SELF_COMPUTED_SOURCES
            and o.get("on_campus") is not True
        ]
        assert not offenders, (
            f"{len(offenders)} records are hosted by a school but claim to be "
            f"off-campus. Either the collector inherited the old UIUC-only "
            f"meaning, or the source belongs in SELF_COMPUTED_SOURCES with a "
            f"reason. First 3: {offenders[:3]}"
        )

    def test_the_exception_is_still_earning_its_exception(self):
        """A blanket exception that never differs is just an untested rule."""
        values = {
            o.get("on_campus")
            for o in _load_data()
            if o.get("source") in self.SELF_COMPUTED_SOURCES
        }
        if not values:
            pytest.skip("no records from the self-computing sources in this corpus")
        assert values == {True, False}, (
            "handshake is exempted because it decides per posting; if every "
            "one of its records now agrees, drop the exception instead of "
            "carrying an unused special case"
        )


class TestSchoolAudience:
    """Multi-university Phase 1 (PR #187): every record carries top-level
    `school` (host-school slug, None = national) + `audience`
    ('campus'/'open'/'unknown'), stamped from source-level defaults by
    src/normalizers/school_audience.py. The matcher's discovery-scope filter
    keys on these fields, so an untagged or mistagged record silently leaks
    into (or vanishes from) every user's results."""

    _SLUG_RE = re.compile(r"^[a-z][a-z0-9_-]*$")

    def test_every_record_has_valid_audience(self):
        from src.normalizers.school_audience import VALID_AUDIENCES

        offenders = [
            (o.get("source"), o.get("id"), o.get("audience"))
            for o in _load_data()
            if o.get("audience") not in VALID_AUDIENCES
        ]
        assert not offenders, (
            f"{len(offenders)} records with missing/invalid audience. "
            f"First 3: {offenders[:3]}"
        )

    def test_uiuc_manual_seeds_are_school_tagged(self):
        """The 17 hand-curated uiuc-* manual records shipped school=None for
        months, leaking UIUC lab postings into every school's toggle-off view
        (a UIUC ECE lab ranked #2 for a UCSD CS student — 2026-07 audit).
        Manual seeds hosted at a school must carry its slug and a real
        audience so the scope filter can do its job."""
        offenders = [
            (o["id"], o.get("school"), o.get("audience"))
            for o in _load_data()
            if o.get("source") == "manual" and o["id"].startswith("uiuc-")
            and not (o.get("school") == "uiuc" and o.get("audience") in ("campus", "open"))
        ]
        assert not offenders, (
            f"{len(offenders)} uiuc manual seeds missing school/audience tags. "
            f"First 3: {offenders[:3]}"
        )

    def test_no_fabricated_lab_postings(self):
        """8 prototype-era seed records were hand-written 'typical lab posting'
        fixtures (metadata.notes 'Based on typical ECE lab posting patterns',
        no PI, invented pay details) whose contact_email was nslack@illinois.edu
        — the ECE shared ADVISING inbox, not a lab. A 2026-07 persona audit
        found one ranked #7 high_priority for a CS junior. Purged from
        seed_v1.json + corpus; this pins them (and their placeholder inbox)
        out for good."""
        fabricated = {
            "uiuc-ece-cv-lab", "uiuc-ece-photonics", "uiuc-ece-arch",
            "uiuc-ece-semiconductor", "uiuc-ece-ml-systems",
            "uiuc-ischool-nlp", "uiuc-stat-data-lab", "uiuc-data-systems-lab",
        }
        offenders = [
            (o["id"], o.get("contact_email"))
            for o in _load_data()
            if o["id"] in fabricated or o.get("contact_email") == "nslack@illinois.edu"
        ]
        assert not offenders, (
            f"{len(offenders)} fabricated lab-posting records present. "
            f"First 3: {offenders[:3]}"
        )

    def test_e2e_detail_fixture_present(self):
        """Four Playwright specs (opportunity-detail / similar-and-og /
        tracker-notes + the MatchCard-link test) hard-code
        KNOWN_ID='uiuc-siebel-ugresearch' and GET /opportunities/<id>. If a data
        PR (purge / dedup / collapse / re-key) drops or renames that one record
        the by-id route 404s and ~15 E2E tests cascade-fail four minutes into
        CI with a bare 404 — it happened twice in 2026-07. Pin the fixture so a
        break surfaces instantly in the backend job with an actionable message
        instead of deep in E2E. Keep this ID in sync with KNOWN_ID in
        frontend/e2e/*.spec.ts."""
        e2e_fixture_id = "uiuc-siebel-ugresearch"
        by_id = {o.get("id"): o for o in _load_data()}
        fx = by_id.get(e2e_fixture_id)
        assert fx is not None, (
            f"E2E detail fixture {e2e_fixture_id!r} is gone from the corpus — "
            f"the opportunity-detail / similar-and-og / tracker-notes Playwright "
            f"specs GET /opportunities/{e2e_fixture_id} and will 404-cascade. "
            f"Restore the seed or update KNOWN_ID in frontend/e2e/*.spec.ts."
        )
        assert (fx.get("title") or "").strip(), (
            f"E2E detail fixture {e2e_fixture_id!r} has an empty title; the "
            f"detail SSR / page-title / metadata E2E specs need a non-empty "
            f"title to assert against."
        )

    def test_no_works_list_stamped_across_many_faculty(self):
        """The url-keyed works store once stamped ONE person's papers onto all
        430 JHU faculty sharing a directory URL (2026-07 audit). Co-authors can
        legitimately share papers, so a small overlap is fine — but an identical
        recent_works list on >3 distinct professors is attribution failure."""
        from collections import defaultdict

        sig_names = defaultdict(set)
        for o in _load_data():
            if o.get("is_active") is False or not o.get("pi_name"):
                continue
            works = (o.get("metadata") or {}).get("recent_works") or []
            if len(works) >= 2:
                sig = tuple(
                    re.sub(r"[^a-z0-9]+", " ", str(w.get("title", "")).lower()).strip()
                    for w in works
                )
                sig_names[sig].add(o["pi_name"])
        offenders = {sig[0][:60]: sorted(names)[:4]
                     for sig, names in sig_names.items() if len(names) > 3}
        assert not offenders, (
            f"{len(offenders)} works lists shared across >3 professors. "
            f"Sample: {dict(list(offenders.items())[:2])}"
        )

    def test_school_is_none_or_lowercase_slug(self):
        offenders = [
            (o.get("source"), o.get("id"), o.get("school"))
            for o in _load_data()
            if not ("school" in o and (
                o["school"] is None
                or (isinstance(o["school"], str) and self._SLUG_RE.match(o["school"]))
            ))
        ]
        assert not offenders, (
            f"{len(offenders)} records whose school is not None / a non-empty "
            f"lowercase slug. First 3: {offenders[:3]}"
        )

    def test_per_source_pairs_match_source_defaults(self):
        """Pin every non-manual record's (school, audience) to SOURCE_DEFAULTS
        — manual records may carry per-record overrides, everything else is
        source-determined in Phase 1. Also fails when a new source ships
        without an entry in the mapping.

        The one sanctioned deviation: apply_school_audience flips a record whose
        own text restricts it to its host school from the default (school,
        "unknown") to (school, "campus"). Only that exact flip is tolerated — a
        record claiming "campus" whose text does NOT restrict it is still drift."""
        from src.normalizers.school_audience import (
            SOURCE_DEFAULTS,
            _explicitly_campus_only,
        )

        data = _load_data()
        unmapped = {
            o.get("source") for o in data
            if o.get("source") != "manual" and o.get("source") not in SOURCE_DEFAULTS
        }
        assert not unmapped, (
            f"sources missing from SOURCE_DEFAULTS: {sorted(unmapped)} — add "
            f"them to src/normalizers/school_audience.py"
        )

        def _is_sanctioned_campus_flip(o: dict) -> bool:
            return (
                o.get("audience") == "campus"
                and SOURCE_DEFAULTS[o["source"]] == (o.get("school"), "unknown")
                and _explicitly_campus_only(o.get("school"), o)
            )

        offenders = [
            (o.get("source"), o.get("id"), o.get("school"), o.get("audience"))
            for o in data
            if o.get("source") != "manual"
            and (o.get("school"), o.get("audience")) != SOURCE_DEFAULTS[o["source"]]
            and not _is_sanctioned_campus_flip(o)
        ]
        assert not offenders, (
            f"{len(offenders)} records whose (school, audience) drifted from "
            f"their source default. First 3: {offenders[:3]}"
        )


def test_normalize_compensation_collapses_range_and_drops_absurd_hourly():
    """Unit probes for the Handshake compensation normalizer: collapse an equal
    "$X-$X" range, drop an implausible (>= $200) "Per hour" label, and preserve
    a plausible hourly rate and any non-hourly pay period."""
    from src.collectors.handshake import _normalize_compensation as nc
    assert nc("$2250-$2250 Per hour") == "$2250"
    assert nc("$2000-$3000 Per hour") == "$2000-$3000"
    assert nc("$200000-$200000 Per year") == "$200000 Per year"
    assert nc("$25 Per hour") == "$25 Per hour"          # plausible hourly kept
    assert nc("$25-$30 Per hour") == "$25-$30 Per hour"  # plausible hourly kept
    assert nc("") == ""
    assert nc("Paid") == "Paid"
