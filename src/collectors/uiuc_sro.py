"""
Collector for UIUC Summer Research Opportunities Database.
URL: https://researchops.web.illinois.edu/
Drupal CMS with paginated table view.

Usage:
    python -m src.collectors.uiuc_sro              # fetch & preview
    python -m src.collectors.uiuc_sro --save       # fetch & merge into processed data
    python -m src.collectors.uiuc_sro --deep       # deep scrape detail pages
"""

import hashlib
import json
import logging
import re
import time
from copy import deepcopy
from datetime import UTC, datetime
from pathlib import Path
from typing import Optional

import requests
from bs4 import BeautifulSoup

from src.normalizers.deadlines import normalize_deadline, to_legacy

from ..contact_instructions import (
    CAPTURE_KEY,
    SOURCE_KEY,
    capture_failure,
    capture_from_html,
    capture_from_sections,
    capture_metadata,
    retained_sources,
    same_source_page,
)
from ..evidence import INFERRED_FIELDS_KEY
from .base import BaseCollector, RawOpportunity
from .import_document import ImportDocumentError, parse_import_html

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
PROCESSED_DIR = PROJECT_ROOT / "data" / "processed"
PROCESSED_DIR.mkdir(parents=True, exist_ok=True)

# Research area IDs from the Drupal filter
RESEARCH_AREAS = {
    "12": "Agriculture & Food Sciences",
    "14": "Business & Economics",
    "13": "Data Science",
    "11": "Education",
    "2": "Humanities & Arts",
    "1": "Medicine & Health",
    "4": "Natural Sciences",
    "5": "Science & Technology",
    "3": "Social Sciences & Behavior",
}

DEEP_SCRAPE_DELAY = 3  # seconds between detail page fetches


class UIUCSROCollector(BaseCollector):
    """Scrapes UIUC Summer Research Opportunities Database."""

    BASE_URL = "https://researchops.web.illinois.edu/"
    MAX_PAGES = 15  # Safety cap; stops when no more rows

    def __init__(self, config: dict = None, deep: bool = False):
        super().__init__(
            source_name="uiuc_sro",
            config=config or {"rate_limit_delay": 3},
        )
        self.deep = deep
        self.evidence = self._new_evidence()

    @staticmethod
    def _new_evidence() -> dict:
        return {
            "list_pages_attempted": 0, "list_pages_loaded": 0, "list_pages_failed": 0,
            "list_complete": False, "list_errors": [],
            "detail_pages_attempted": 0, "detail_pages_loaded": 0, "detail_pages_failed": 0,
            "detail_errors": [], "normalization_failed": 0,
            "condition_capture_counts": {status: 0 for status in ("captured", "empty", "unsupported", "failed")},
            "condition_capture_complete": False,
        }

    def collect(self) -> list[RawOpportunity]:
        """Scrape all paginated pages."""
        opportunities = []
        self.evidence = self._new_evidence()
        for page in range(self.MAX_PAGES):
            url = f"{self.BASE_URL}?page={page}"
            self.evidence["list_pages_attempted"] += 1
            try:
                resp = requests.get(url, timeout=30, headers={
                    "User-Agent": "OpportunityFilterEngine/1.0 (educational project)"
                })
                resp.raise_for_status()
            except Exception:
                self._list_failure(url, "fetch_failed")
                continue
            if not same_source_page(url, getattr(resp, "url", None)):
                self._list_failure(url, "redirect_mismatch" if isinstance(getattr(resp, "url", None), str) else "fetch_metadata_missing")
                continue
            table = BeautifulSoup(resp.text, "html.parser").select_one("table.views-table")
            if table is None or table.select_one("tbody") is None:
                self._list_failure(url, "unsupported_list")
                break
            rows = table.select("tbody tr")
            page_opps = [opp for opp in self._parse_page(resp.text, url) if opp.title and opp.url]
            opportunities.extend(page_opps)
            if len(page_opps) != len(rows):
                self._list_failure(url, "unparsed_rows")
            else:
                self.evidence["list_pages_loaded"] += 1
            if not rows:
                self.evidence["list_complete"] = self.evidence["list_pages_failed"] == 0
                break
            self._rate_limit()
        else:
            self.evidence["list_errors"].append({"reason": "page_limit", "source_url": self.BASE_URL})

        if self.deep:
            for i, opp in enumerate(opportunities):
                self._fetch_detail_page(opp)
                if i < len(opportunities) - 1:
                    time.sleep(DEEP_SCRAPE_DELAY)
        return opportunities

    def _list_failure(self, url: str, reason: str) -> None:
        self.evidence["list_pages_failed"] += 1
        self.evidence["list_errors"].append({"reason": reason, "source_url": url})

    @staticmethod
    def _capture_detail_html(html: str, **binding) -> dict:
        """Adapt raw Drupal labels/items; never infer headings from field names.

        The page is parsed once, within the import reader's limits, and a page
        past them is a failed check. The capture only reads the parsed page,
        so the field fallback below takes it apart in place.
        """
        try:
            soup = parse_import_html(html)
        except ImportDocumentError as error:
            return capture_failure(**binding, reason=error.reason)
        result = capture_from_html(soup, **binding)
        if result.get("reason") not in {"unparsed_relevant_content", "no_supported_content"}:
            return result
        body = soup.find("main") or soup.find("article") or soup.find("body")
        if body is None:
            return result
        sections = []
        # A layout region repeats a field without its label. Only a copy that
        # says exactly what a labelled field of the same name says is dropped;
        # anything else stays in the page and keeps it unsupported.
        for node in list(body.select("div.field--label-hidden")):
            name = next((c for c in node.get("class", []) if c.startswith("field--name-field-")), None)
            twin = body.select_one(f"div.{name}.field--label-inline .field__item") if name else None
            if twin is not None and twin.get_text(" ", strip=True) == node.get_text(" ", strip=True):
                node.decompose()
        # "This opportunity was last updated on <date>": page bookkeeping.
        for node in list(body.select(".views-field-changed")):
            node.decompose()
        # These are fields already read by the detail parser, not new pages.
        for node in list(body.select(
            "div.field--name-field-eligibility, div.field--name-field-eligibility-requirements, "
            "div.field--name-field-requirements, div.field--name-field-deadline, "
            "div.field--name-field-deadline-anticipated, div.field--name-field-application-deadline, "
            "div.field--name-field-application-url, div.field--name-field-apply-url, "
            "div.field--name-field-application-link, "
            "div.field--name-field-link-to-opportunity.field--label-inline, "
            "div.field--name-field-contact-email, div.field--name-field-sponsoring-institution, "
            "div.field--name-field-location, div.field--name-field-timing, "
            "div.field--name-field-deadline-date, div.field--name-field-deadline-free-text, "
            "div.field--name-field-research-area, div.field--name-field-duration, "
            "div.field--name-field-compensation, div.field--name-field-citizenship-requirement"
        )):
            label = node.select_one(".field__label, .field-label")
            if label is None or not label.get_text(" ", strip=True):
                return capture_failure(**binding, status="unsupported", reason="missing_field_label")
            headings = {}
            for previous in body.descendants:
                if previous is node:
                    break
                name = getattr(previous, "name", None)
                if name in {"h1", "h2", "h3", "h4", "h5", "h6"} and not previous.find_parent(
                    ["nav", "header", "footer", "aside", "script", "style"]
                ):
                    level = int(name[1])
                    headings = {depth: text for depth, text in headings.items() if depth < level}
                    headings[level] = previous.get_text(" ", strip=True)
            heading = " > ".join([*headings.values(), label.get_text(" ", strip=True)])
            label.extract()
            text = node.get_text(" ", strip=True)
            if not text:
                return capture_failure(**binding, status="unsupported", reason="empty_field_value")
            sections.append({"heading": heading, "text": text})
            node.decompose()
        remainder = capture_from_html(soup, **binding)
        if remainder["status"] == "unsupported" and remainder.get("reason") != "no_supported_content":
            return remainder
        for source in remainder.get("sources", []):
            sections.extend(source["sections"])
        # A raw field was found, and the rest of the page contains no ignored
        # condition-bearing text. The section helper applies the full budgets.
        return capture_from_sections(sections, **binding) if sections else result

    def _fetch_detail_page(self, opp: RawOpportunity) -> None:
        """Record each attempted detail check, including parse and HTTP failure."""
        self.evidence["detail_pages_attempted"] += 1
        opp.extra_fields.pop("deep_scraped", None)
        try:
            resp = requests.get(opp.url, timeout=30, headers={
                "User-Agent": "OpportunityFilterEngine/1.0 (educational project)"
            })
            resp.raise_for_status()
        except Exception:
            self.evidence["detail_pages_failed"] += 1
            result = capture_failure(source_url=opp.url, reason="fetch_failed")
        else:
            self.evidence["detail_pages_loaded"] += 1
            final = getattr(resp, "url", None)
            binding = dict(source_url=final or opp.url, record_source_url=opp.url,
                           checked_at=datetime.now(UTC).isoformat())
            if not isinstance(final, str):
                result = capture_failure(**binding, reason="fetch_metadata_missing")
            elif not same_source_page(opp.url, final):
                result = capture_failure(**binding, reason="redirect_mismatch")
            else:
                try:
                    result = self._capture_detail_html(resp.text, **binding)
                    if result["status"] in {"captured", "empty"}:
                        detail = self._parse_detail_page(resp.text)
                        if detail.get("description"):
                            opp.description_raw = detail["description"]
                        if detail.get("organization"):
                            opp.organization = detail["organization"]
                        for key in ("eligibility_text", "application_url", "citizenship_info", "paid_info",
                                    "location", "timing", "deadline_anticipated", "research_area",
                                    "duration", "compensation", "citizenship", "program_url"):
                            if detail.get(key):
                                opp.extra_fields[key] = detail[key]
                        if detail.get("deadline"):
                            opp.deadline = detail["deadline"]
                            opp.extra_fields["deadline_raw"] = detail["deadline"]
                        opp.extra_fields["deep_scraped"] = True
                except Exception:
                    result = capture_failure(**binding, reason="parse_failed")
        opp.extra_fields.pop(SOURCE_KEY, None)
        opp.extra_fields.update(capture_metadata(result))
        self.evidence["condition_capture_counts"][result["status"]] += 1
        counts = self.evidence["condition_capture_counts"]
        self.evidence["condition_capture_complete"] = bool(sum(counts.values()) and not counts["unsupported"] and not counts["failed"])
        if result["status"] in {"failed", "unsupported"}:
            self.evidence["detail_errors"].append({"source_url": opp.url, "reason": result["reason"]})

    def _parse_detail_page(self, html: str) -> dict:
        """Parse a detail page and extract structured fields."""
        soup = parse_import_html(html)
        detail = {}

        # Full description - look for the main content area
        content = soup.select_one(
            "div.field--name-body, "
            "div.node__content, "
            "article .field--name-field-description, "
            "div.field--name-field-body"
        )
        if content:
            detail["description"] = content.get_text(separator="\n", strip=True)

        # Sponsoring organization
        org_field = soup.select_one(
            "div.field--name-field-sponsoring-organization, "
            "div.field--name-field-organization, "
            "div.field--name-field-sponsor"
        )
        if org_field:
            detail["organization"] = org_field.get_text(strip=True)
            # Clean common prefixes from Drupal field labels
            for prefix in ["Sponsoring Organization", "Organization", "Sponsor"]:
                if detail["organization"].startswith(prefix):
                    detail["organization"] = detail["organization"][len(prefix):].strip()

        # Eligibility details
        elig_field = soup.select_one(
            "div.field--name-field-eligibility, "
            "div.field--name-field-eligibility-requirements, "
            "div.field--name-field-requirements"
        )
        if elig_field:
            detail["eligibility_text"] = elig_field.get_text(separator=" ", strip=True)

        # Application URL
        app_link = soup.select_one(
            "div.field--name-field-application-url a, "
            "div.field--name-field-apply-url a, "
            "div.field--name-field-application-link a, "
            "a[href*='apply'], a[href*='application']"
        )
        if app_link:
            detail["application_url"] = app_link.get("href", "")

        # Deadline from detail page. Not field-deadline-anticipated: that is
        # the "Anticipated Deadline? Yes" flag, and it read as a deadline of "?Yes".
        deadline_field = soup.select_one(
            "div.field--name-field-deadline, "
            "div.field--name-field-application-deadline"
        )
        if deadline_field:
            detail["deadline"] = deadline_field.get_text(strip=True)
            for prefix in ["Deadline", "Application Deadline", "Anticipated Deadline"]:
                if detail["deadline"].startswith(prefix):
                    detail["deadline"] = detail["deadline"][len(prefix):].strip()

        # Extract citizenship/international info from full page text
        full_text = soup.get_text(separator=" ", strip=True)
        citizenship_keywords = [
            "u.s. citizen", "us citizen", "citizenship required",
            "permanent resident", "us only", "must be a u.s.",
            "u.s. citizenship", "international students welcome",
            "open to all", "international students eligible",
            "all students", "no citizenship requirement",
            "international students", "non-citizen", "visa",
            "green card", "authorized to work", "work authorization",
        ]
        citizenship_mentions = []
        full_lower = full_text.lower()
        for kw in citizenship_keywords:
            idx = full_lower.find(kw)
            if idx != -1:
                start = max(0, idx - 50)
                end = min(len(full_text), idx + len(kw) + 50)
                citizenship_mentions.append(full_text[start:end].strip())
        if citizenship_mentions:
            detail["citizenship_info"] = " | ".join(citizenship_mentions)

        # Detect paid/stipend info
        paid_keywords = ["stipend", "paid", "salary", "compensation", "funded", "unfunded"]
        paid_mentions = []
        for kw in paid_keywords:
            idx = full_lower.find(kw)
            if idx != -1:
                start = max(0, idx - 40)
                end = min(len(full_text), idx + len(kw) + 40)
                paid_mentions.append(full_text[start:end].strip())
        if paid_mentions:
            detail["paid_info"] = " | ".join(paid_mentions)

        # The database's labelled fields state each of these outright; they
        # win over the scans above.
        for key, names in _LABELLED_FIELDS.items():
            value = next((v for v in (_field_value(soup, name) for name in names) if v), "")
            if value:
                detail[key] = value
        link = soup.select_one("div.field--name-field-link-to-opportunity a[href]")
        if link is not None and link["href"].startswith(("http://", "https://")):
            detail["program_url"] = link["href"]

        return detail

    def _parse_page(self, html: str, page_url: str) -> list[RawOpportunity]:
        """Parse a single page of the table-based listing."""
        soup = BeautifulSoup(html, "html.parser")
        opportunities = []

        table = soup.select_one("table.views-table")
        if not table:
            return []

        rows = table.select("tbody tr")
        for row in rows:
            opp = self._parse_row(row, page_url)
            if opp:
                opportunities.append(opp)

        return opportunities

    def _parse_row(self, row, page_url: str) -> Optional[RawOpportunity]:
        """Parse a single table row into RawOpportunity."""
        try:
            # Title and link
            title_td = row.select_one("td.views-field-title")
            if not title_td:
                self.logger.warning(
                    "Skipping SRO row: no td.views-field-title cell "
                    f"(possible Drupal layout change). Row: {str(row)[:200]!r}"
                )
                return None

            link_el = title_td.select_one("a")
            if not link_el:
                self.logger.warning(
                    "Skipping SRO row: title cell has no <a> link "
                    f"(possible Drupal layout change). Cell: {str(title_td)[:200]!r}"
                )
                return None

            title = link_el.get_text(strip=True)
            href = link_el.get("href", "")
            if not href:
                self.logger.warning(
                    f"SRO row {title!r}: title link has empty href "
                    "(possible Drupal layout change); record will have no url"
                )
            if href and not href.startswith("http"):
                href = f"https://researchops.web.illinois.edu{href}"

            # Description (text after the <br> in the same td)
            desc_parts = []
            for child in title_td.children:
                if isinstance(child, str):
                    text = child.strip()
                    if text and text != title:
                        desc_parts.append(text)
            # Also try getting all text minus title
            full_text = title_td.get_text(separator=" ", strip=True)
            description = full_text.replace(title, "", 1).strip()

            # Research area
            area_td = row.select_one("td.views-field-field-research-area")
            research_area = area_td.get_text(strip=True) if area_td else ""

            # Timing
            timing_td = row.select_one("td.views-field-field-timing")
            timing = timing_td.get_text(strip=True) if timing_td else ""

            # Deadline. The earlier selector also matched `td.views-field-nothing`,
            # which is Drupal's generic-purpose cell — when the SRO table layout
            # included a "?" toggle column ("?Yes"/"?No") that selector swallowed
            # the boolean instead of the deadline and corrupted 262/278 records.
            # Use only the specific anticipated-deadline class.
            deadline_td = row.select_one("td.views-field-field-deadline-anticipated")
            deadline_text = deadline_td.get_text(strip=True) if deadline_td else ""

            return RawOpportunity(
                source="uiuc_sro",
                source_url=page_url,
                title=title,
                description_raw=description,
                url=href,
                organization=None,
                deadline=deadline_text if deadline_text else None,
                location=None,
                extra_fields={
                    "research_area": research_area,
                    "timing": timing,
                    "deadline_raw": deadline_text,
                },
            )

        except Exception as e:
            self.logger.error(f"Failed to parse row: {e}")
            return None


#: Labelled fields on an SRO detail page (Drupal ``field--name-field-<name>``),
#: by the key the parser stores them under; the first name with a value wins.
_LABELLED_FIELDS = {
    "organization": ("sponsoring-institution",),
    "location": ("location",),
    "timing": ("timing",),
    "deadline": ("deadline-date", "deadline-free-text"),
    "deadline_anticipated": ("deadline-anticipated",),
    "research_area": ("research-area",),
    "duration": ("duration",),
    "compensation": ("compensation",),
    "citizenship": ("citizenship-requirement",),
}


def _field_value(soup, name: str) -> str:
    """The items of one labelled field, joined; '' when the page lacks it."""
    node = (soup.select_one(f"div.field--name-field-{name}.field--label-inline")
            or soup.select_one(f"div.field--name-field-{name}"))
    if node is None:
        return ""
    items = [item.get_text(" ", strip=True) for item in node.select(".field__item")]
    return ", ".join(item for item in items if item)


def _detect_international_friendly(text: str) -> str:
    """Heuristic for international student eligibility."""
    lower = text.lower()
    if any(kw in lower for kw in ["u.s. citizen", "us citizen", "citizenship required",
                                    "permanent resident only", "us only",
                                    "must be a u.s.", "u.s. citizenship",
                                    "authorized to work in the united states",
                                    "must be authorized to work in the u.s.",
                                    "u.s. persons only", "u.s. national"]):
        return "no"
    if any(kw in lower for kw in ["international students welcome", "open to all",
                                    "international students eligible", "all students",
                                    "no citizenship requirement",
                                    "international students are encouraged",
                                    "open to international"]):
        return "yes"
    return "unknown"


def _parse_deadline(text: str) -> tuple[Optional[str], bool]:
    """Run a raw SRO deadline string through the central normalizer.

    Returns ``(iso_string_or_None, is_rolling_bool)``. The label-stripping
    that used to live here (``"Anticipated"``, ``"Deadline: "``) has moved
    into ``src.normalizers.deadlines`` so every collector benefits.
    """
    return to_legacy(normalize_deadline(text))


def _detect_paid_status(text: str) -> str:
    """Detect paid/stipend/unpaid from text."""
    lower = text.lower()
    if any(kw in lower for kw in ["stipend", "funded position", "paid position",
                                    "salary", "compensation provided"]):
        return "yes"
    if any(kw in lower for kw in ["unpaid", "unfunded", "volunteer", "no compensation"]):
        return "no"
    return "unknown"


# paid_info concatenates ±40-char windows around paid keywords with ' | ', which
# leaks adjacent metadata into compensation_details ("… Duration 10 weeks
# Compensation $7,000 Citizenship Requirement No …"). Extract the real value.
# Mirrors frontend cleanCompensation (detail-utils.ts) so source + display agree.
_COMP_DOLLAR_RE = re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?(?:\s?(?:/|per)\s?\w+)?", re.IGNORECASE)
_COMP_QUAL_RE = re.compile(
    r"compensation\s+(paid(?:\s+program)?|stipend(?:\s+provided)?|funded|unpaid)",
    re.IGNORECASE,
)
_COMP_DIRTY_RE = re.compile(
    r"citizenship requirement|duration\s+\d|compensation\s+(?:\$|paid|stipend|unpaid)",
    re.IGNORECASE,
)


def _clean_compensation(raw: str) -> str:
    """Reduce a deep-scraped paid_info blob to a clean compensation value.

    A clean value passes through untouched; a dirty blob yields the dollar
    amount, then a qualitative label ("Paid Program"/"Stipend Provided"), then a
    bare mention, then '' when nothing is usable (caller shows the paid badge).
    """
    text = (raw or "").strip()
    if not text:
        return ""
    looks_dirty = " | " in text or bool(_COMP_DIRTY_RE.search(text)) or len(text) > 120
    if not looks_dirty:
        return text
    m = _COMP_DOLLAR_RE.search(text)
    if m:
        return re.sub(r"\s+", " ", m.group(0)).strip()
    m = _COMP_QUAL_RE.search(text)
    if m:
        return re.sub(r"\s+", " ", m.group(1)).strip().title()
    if re.search(r"\bstipend\b", text, re.IGNORECASE):
        return "Stipend provided"
    if re.search(r"\bpaid\b", text, re.IGNORECASE):
        return "Paid"
    if re.search(r"\bunpaid\b", text, re.IGNORECASE):
        return "Unpaid"
    return ""


#: How ``eligibility.majors`` is produced here, for ``stamp_inferred``. The SRO
#: listing states a coarse research area ("Medicine & Health", "Natural
#: Sciences") and never a major, so every value in that field is ours.
MAJORS_METHOD = "rule:research_area_bank"


def _research_area_to_majors(area: str) -> list[str]:
    """Map SRO research areas to approximate majors.

    APPROXIMATE is the operative word, and the reason callers must stamp the
    result: "Medicine & Health" yields Biology, Bioengineering and Chemistry
    for every listing under it, whether or not the program says anything about
    who may apply.
    """
    area_lower = area.lower()
    majors = []
    if "science & technology" in area_lower or "natural sciences" in area_lower:
        majors.extend(["CS", "ECE", "Physics", "Chemistry", "Engineering"])
    if "data science" in area_lower:
        majors.extend(["CS", "STAT", "Data Science", "IS"])
    if "medicine" in area_lower or "health" in area_lower:
        majors.extend(["Biology", "Bioengineering", "Chemistry"])
    if "business" in area_lower or "economics" in area_lower:
        majors.extend(["Business", "Economics", "STAT"])
    if "social sciences" in area_lower:
        majors.extend(["Psychology", "Sociology", "Political Science"])
    if "agriculture" in area_lower:
        majors.extend(["Agriculture", "Biology", "Chemistry"])
    if "humanities" in area_lower or "arts" in area_lower:
        majors.extend(["English", "History", "Art"])
    if "education" in area_lower:
        majors.extend(["Education"])
    return list(set(majors))


#: How pay and citizenship are produced when the page has no field stating
#: them, for ``stamp_inferred``: a keyword scan of the description.
PAID_METHOD = "rule:sro_paid_keywords"
CITIZENSHIP_METHOD = "rule:sro_citizenship_keywords"

# The list's deadline cell reads "Anticipated 3/2/27"; the central normalizer
# does not strip that label, so every list deadline came back unparseable.
_ANTICIPATED_RE = re.compile(r"^\s*anticipated\b[\s:]*", re.IGNORECASE)


_UNPAID_RE = re.compile(
    r"\bunpaid\b|\bunfunded\b|\bvolunteer\b|\bno (?:compensation|pay|stipend|salary)\b"
    r"|\bnot (?:paid|funded)\b|^\s*none\s*$",
    re.IGNORECASE,
)
# Any other negation ("Stipend not provided", "No housing; $500 travel")
# leaves what is and is not paid to a reader, and a keyword scan of the same
# words would only read "stipend" back out of it.
_PAY_NEGATION_RE = re.compile(r"\bno\b|\bnot\b|\bnone\b|\bwithout\b", re.IGNORECASE)


# A field that states pay and otherwise only denies benefits reads as paid:
# "$5,000 stipend; no housing", "$600/week, not including housing". A denied
# benefit counts as a whole clause between "." or ";", or as the last comma
# clause; an earlier comma clause can open a list the negation runs through
# ("no housing, meals, or stipend"). A "." inside "$15.60" or "U.S." splits
# too, but only a whole benefit-denying clause is removed. What is left must
# be nothing but the pay statement: "Program fee: $500/week" or "$500 travel"
# may be money for something else, and "We don't offer a stipend" denies pay.
# Anything else keeps the negation reading below.
_BENEFIT = (
    r"(?:on-campus\s+)?(?:housing|lodging|room|board|meals?|food"
    r"|travel|transportation|airfare|relocation|parking|insurance)"
)
_BENEFITS = rf"{_BENEFIT}(?:\s+(?:and|or)\s+{_BENEFIT})*"
_BENEFIT_DENIED_RE = re.compile(
    rf"\s*(?:(?:no|without|not\s+including|excluding)\s+{_BENEFITS}"
    rf"|{_BENEFITS}\s+(?:is\s+|are\s+)?not\s+(?:provided|included|covered|offered))\s*",
    re.IGNORECASE,
)
_AMOUNT = r"\$\s?[1-9]\d*(?:,\d{3})*(?:\.\d+)?"
_RATE = r"\s*(?:/\s*|per\s+)(?:hour|hr|week|wk|month|mo)\b"
_PAY_WORD = r"(?:stipends?|salary|wages?)"
_PAY_ONLY_RE = re.compile(
    rf"[\s;.,]*(?:paid(?:\s+hourly)?|{_PAY_WORD}(?:\s+provided)?"
    rf"|{_PAY_WORD}\s*(?::\s*|of\s+)?{_AMOUNT}(?:{_RATE})?"
    rf"|{_AMOUNT}(?:{_RATE}(?:\s+{_PAY_WORD})?|\s+{_PAY_WORD}))[\s;.,]*",
    re.IGNORECASE,
)


def _without_denied_benefits(value: str) -> str:
    parts = re.split(r"([;.])", value)
    for i in range(0, len(parts), 2):
        head, comma, tail = parts[i].rpartition(",")
        if _BENEFIT_DENIED_RE.fullmatch(parts[i]):
            parts[i] = ""
        elif comma and _BENEFIT_DENIED_RE.fullmatch(tail):
            parts[i] = head
    return "".join(parts)


def _paid_from_compensation(value: str) -> str:
    """yes/no/unknown from the page's own Compensation field."""
    rest = _without_denied_benefits(value)
    if rest != value and _PAY_ONLY_RE.fullmatch(rest):
        return "yes"
    if _UNPAID_RE.search(value):
        return "no"
    if _PAY_NEGATION_RE.search(value):
        return "unknown"
    if re.search(r"\$\s?\d|\bpaid\b|\bstipends?\b|\bsalary\b|\bwages?\b|\bfunded\b", value, re.IGNORECASE):
        return "yes"
    return "unknown"


def _citizenship_from_field(value: str, description: str) -> tuple[Optional[bool], str]:
    """(citizenship_required, international_friendly) from "Citizenship Requirement".

    The field takes two values on the live database. "No Citizenship
    Requirements" beside a description that restricts by citizenship — "most
    program funding is restricted to U.S. citizens and permanent residents" —
    is a conflict, and a conflict is unknown, not a welcome.
    """
    lower = value.lower()
    if lower.startswith("no citizenship"):
        if _detect_international_friendly(description) == "no":
            return None, "unknown"
        return False, "yes"
    if "required" in lower and ("citizen" in lower or "resident" in lower):
        return True, "no"
    return None, "unknown"


def raw_to_normalized(raw: RawOpportunity) -> dict:
    """Convert a RawOpportunity from SRO into the normalized schema.

    The detail page is a labelled record (Sponsoring Institution, Location,
    Deadline, Duration, Compensation, Citizenship Requirement, Link to
    Opportunity), so a deep-scraped row takes those values as the page states
    them. Anything a keyword scan produced instead is stamped as inferred.
    """
    desc = raw.description_raw or ""
    extra = raw.extra_fields
    stamps: dict[str, str] = {}

    citizenship_field = extra.get("citizenship", "")
    if citizenship_field:
        citizenship_required, intl = _citizenship_from_field(citizenship_field, desc)
        work_auth_notes = citizenship_field
    else:
        intl = _detect_international_friendly(extra.get("citizenship_info", "") + " " + desc)
        # Tri-state (M03): an unknown intl answer is not "no requirement".
        citizenship_required = True if intl == "no" else (False if intl == "yes" else None)
        work_auth_notes = ""
        if intl != "unknown":
            stamps["eligibility.international_friendly"] = CITIZENSHIP_METHOD
            stamps["eligibility.citizenship_required"] = CITIZENSHIP_METHOD

    # The detail page's Deadline (or the list's "Anticipated 3/2/27" cell),
    # with the page's "Anticipated Deadline?" flag deciding whether it is an
    # estimate; the list label decides when the detail page was not read.
    deadline_raw = extra.get("deadline_raw", "")
    deadline_text = _ANTICIPATED_RE.sub("", deadline_raw).strip()
    flag = str(extra.get("deadline_anticipated", "")).strip().lower()
    anticipated = flag == "yes" if flag in {"yes", "no"} else bool(_ANTICIPATED_RE.match(deadline_raw))
    deadline, is_rolling = _parse_deadline(deadline_text)
    deadline_note = ""
    if deadline and anticipated:
        deadline_note = f"{deadline_text} (anticipated)"
    elif is_rolling:
        deadline_note = deadline_text
    # R70-A: SRO listings without a parseable deadline are aggregator-page
    # entries — default to rolling so the UI shows "Rolling" instead of
    # leaving the timing block blank (was 258 silent records).
    if deadline is None and not is_rolling:
        is_rolling = True

    research_area = extra.get("research_area", "")
    timing = extra.get("timing", "")
    length = extra.get("duration", "")
    majors = _research_area_to_majors(research_area)
    if majors:
        stamps["eligibility.majors"] = MAJORS_METHOD

    compensation = extra.get("compensation", "")
    paid = _paid_from_compensation(compensation) if compensation else "unknown"
    if paid == "unknown" and not _PAY_NEGATION_RE.search(compensation):
        paid = _detect_paid_status(extra.get("paid_info", "") + " " + desc)
        if paid != "unknown":
            stamps["paid"] = PAID_METHOD

    # Use deep-scraped organization if available
    organization = raw.organization or ""

    # The program's own page, from the "Link to Opportunity" field.
    application_url = extra.get("program_url") or extra.get("application_url", raw.url)

    # Eligibility text from detail page
    eligibility_text = extra.get("eligibility_text", desc[:300])

    url_hash = hashlib.md5(raw.url.encode()).hexdigest()[:8]
    opp_id = f"sro-{url_hash}"
    now = datetime.now(UTC).replace(tzinfo=None).isoformat()

    is_deep = extra.get("deep_scraped", False)
    confidence = 0.85 if is_deep else 0.7

    return {
        "id": opp_id,
        "source": "uiuc_sro",
        "source_url": raw.source_url,
        "source_type": "summer_program",
        "title": raw.title.strip(),
        "organization": organization,
        "department": "",
        "lab_or_program": raw.title.strip(),
        "pi_name": None,
        "url": raw.url,
        "location": extra.get("location", ""),
        "on_campus": False,
        "remote_option": "unknown",
        "opportunity_type": "summer_program",
        "paid": paid,
        "compensation_details": compensation,
        "deadline": deadline,
        "deadline_is_estimate": bool(deadline and anticipated),
        "is_rolling": is_rolling,
        "posted_date": None,
        "start_date": None,
        "duration": f"{timing} ({length})" if timing and length else (timing or length or None),
        "eligibility": {
            "preferred_year": ["freshman", "sophomore", "junior", "senior"],
            "min_gpa": None,
            "majors": majors,
            "skills_required": [],
            "skills_preferred": [],
            "citizenship_required": citizenship_required,
            "international_friendly": intl,
            "work_auth_notes": work_auth_notes,
            "eligibility_text_raw": eligibility_text[:500],
        },
        "application": {
            "contact_method": "online",
            "requires_resume": "unknown",
            "requires_cover_letter": "unknown",
            "requires_transcript": "unknown",
            "requires_recommendation": "unknown",
            "application_effort": "medium",
            "application_url": application_url,
        },
        "description_raw": desc,
        "description_clean": desc[:1500],
        "keywords": [a.strip() for a in research_area.split(",") if a.strip()],
        "metadata": {
            "confidence_score": confidence,
            **({SOURCE_KEY: retained_sources(extra[SOURCE_KEY])} if SOURCE_KEY in extra else {}),
            **({CAPTURE_KEY: deepcopy(extra[CAPTURE_KEY])} if CAPTURE_KEY in extra else {}),
            "detail_page_verified": is_deep,
            "last_verified": extra.get(CAPTURE_KEY, {}).get("attempted_at") if is_deep else None,
            "first_seen_at": now,
            "last_seen_at": now,
            "is_active": True,
            "manually_reviewed": False,
            "notes": "Auto-imported from UIUC SRO database" + (" (deep scraped)" if is_deep else ""),
            **({"deadline_note": deadline_note} if deadline_note else {}),
            **({INFERRED_FIELDS_KEY: stamps} if stamps else {}),
        },
    }


def fetch_and_normalize_with_evidence(deep: bool = False) -> tuple[list[dict], dict]:
    """Return records and honest listing/detail completeness from this attempt."""
    collector = UIUCSROCollector(deep=deep)
    raw_opps = collector.collect()
    normalized = []
    for raw in raw_opps:
        try:
            normalized.append(raw_to_normalized(raw))
        except Exception:
            collector.evidence["normalization_failed"] += 1
            logger.error("SRO record normalization failed")
    return normalized, collector.evidence


def fetch_and_normalize(deep: bool = False) -> list[dict]:
    records, _evidence = fetch_and_normalize_with_evidence(deep=deep)
    return records


def _carry_inference_stamps(prior: dict, opp: dict, carried: list[str]) -> None:
    """Move inference stamps with the values carried from ``prior``.

    A carried value keeps exactly the stamps it had, so an inferred skill or
    paid flag never becomes a stated one, and a fresh stamp never lands on a
    value this refresh did not produce.
    """
    paths = list(carried)
    prior_meta = prior.get("metadata") if isinstance(prior.get("metadata"), dict) else {}
    if "description_raw" in carried and "skill_mentions" in prior_meta:
        opp["metadata"]["skill_mentions"] = deepcopy(prior_meta["skill_mentions"])
        paths.append("metadata.skill_mentions")

    def owned(path: str) -> bool:
        return any(path == key or path.startswith(key + ".") for key in paths)

    prior_stamps = prior_meta.get(INFERRED_FIELDS_KEY)
    fresh_stamps = opp["metadata"].get(INFERRED_FIELDS_KEY)
    stamps = {path: method for path, method in (fresh_stamps if isinstance(fresh_stamps, dict) else {}).items()
              if not owned(path)}
    stamps.update({path: deepcopy(method) for path, method in
                   (prior_stamps if isinstance(prior_stamps, dict) else {}).items() if owned(path)})
    if stamps:
        opp["metadata"][INFERRED_FIELDS_KEY] = stamps
    else:
        opp["metadata"].pop(INFERRED_FIELDS_KEY, None)


def merge_into_processed(new_opps: list[dict], filepath: str = None) -> tuple[int, int]:
    """Merge new opportunities into the processed data file."""
    filepath = filepath or str(PROCESSED_DIR / "opportunities.json")

    existing = []
    if Path(filepath).exists():
        with open(filepath, encoding="utf-8") as f:
            existing = json.load(f)

    index = {opp["id"]: opp for opp in existing}
    added, updated = 0, 0

    for opp in new_opps:
        if opp["id"] in index:
            opp["metadata"]["first_seen_at"] = index[opp["id"]].get("metadata", {}).get(
                "first_seen_at", opp["metadata"]["first_seen_at"]
            )
            prior = index[opp["id"]]
            # A list refresh cannot prove that previously fetched detail facts
            # disappeared. Retain them without advancing their verification time.
            if opp["metadata"].get("detail_page_verified") is not True:
                carried = [key for key in ("organization", "department", "lab_or_program", "pi_name",
                                           "contact_email", "eligibility", "application", "deadline",
                                           "deadline_is_estimate", "is_rolling", "paid",
                                           "compensation_details", "location", "duration",
                                           "description_raw", "description_clean") if key in prior]
                # The list row is itself a current deadline observation; only
                # an absent one falls back to the prior detail-page value.
                if opp.get("deadline") is not None:
                    carried = [key for key in carried
                               if key not in ("deadline", "deadline_is_estimate", "is_rolling")]
                for key in carried:
                    opp[key] = deepcopy(prior[key])
                if "deadline" in carried:
                    # The note qualifies the deadline ("3/15/27 (anticipated)")
                    # and travels with it.
                    opp["metadata"].pop("deadline_note", None)
                    if prior.get("metadata", {}).get("deadline_note"):
                        opp["metadata"]["deadline_note"] = prior["metadata"]["deadline_note"]
                _carry_inference_stamps(prior, opp, carried)
                if "last_verified" in prior.get("metadata", {}):
                    opp["metadata"]["last_verified"] = prior["metadata"]["last_verified"]
            from .uiuc_faculty import carry_forward_contact_instruction_sources

            carry_forward_contact_instruction_sources(prior, opp)
            index[opp["id"]] = opp
            updated += 1
        else:
            index[opp["id"]] = opp
            added += 1

    all_opps = list(index.values())
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(all_opps, f, indent=2, ensure_ascii=False, default=str)

    return added, updated


if __name__ == "__main__":
    import argparse

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    parser = argparse.ArgumentParser(description="UIUC SRO Collector")
    parser.add_argument("--save", action="store_true", help="Merge into processed/opportunities.json")
    parser.add_argument("--pages", type=int, default=None, help="Max pages to scrape (default: all)")
    parser.add_argument("--deep", action="store_true", help="Deep scrape detail pages for richer data")
    args = parser.parse_args()

    collector = UIUCSROCollector(deep=args.deep)
    if args.pages:
        collector.MAX_PAGES = args.pages

    opps_raw = collector.collect()
    opps = []
    for raw in opps_raw:
        try:
            opps.append(raw_to_normalized(raw))
        except Exception as e:
            logger.error(f"Normalize failed: {e}")

    print(f"\nFetched and normalized {len(opps)} opportunities from SRO")
    if args.deep:
        deep_count = sum(1 for o in opps if o["metadata"]["notes"].endswith("(deep scraped)"))
        print(f"  Deep scraped: {deep_count}/{len(opps)}")
    print()

    for i, opp in enumerate(opps[:5]):
        intl = opp["eligibility"]["international_friendly"]
        paid = opp.get("paid", "unknown")
        deadline = opp.get("deadline") or "none"
        areas = ", ".join(opp.get("keywords", []))
        org = opp.get("organization", "") or "unknown org"
        print(f"[{i+1}] {opp['title'][:65]}")
        print(f"    Org: {org} | Areas: {areas}")
        print(f"    Intl: {intl} | Paid: {paid} | Deadline: {deadline}")
        print(f"    URL: {opp['url']}")
        print()

    if args.save:
        added, updated = merge_into_processed(opps)
        print(f"Saved: {added} new, {updated} updated")
    else:
        print("(Use --save to merge into processed/opportunities.json)")
