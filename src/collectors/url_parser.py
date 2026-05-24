"""URL Parser — V1 OG-meta scrape + V2 LLM-enriched structured extraction.

V1 (parse_url) reads OpenGraph tags + regex deadline. Best-effort, no LLM
needed, no rate-limited external dep beyond the source URL. Stable since
the very first manual-import iteration.

V2 (parse_url_llm) layers a single LLM call on top of V1: feeds the page
body + V1's already-extracted title/description back to the model with a
strict JSON schema and merges the response into a RawOpportunity. Used
by the /api/import-url backend route the frontend's "Add by URL" flow
calls. Falls back to V1 silently when no LLM provider is configured
(see backend/lib/llm.py::is_configured).
"""

from __future__ import annotations

import ipaddress
import json
import logging
import re
from typing import Optional
from urllib.parse import urlparse

import requests
from bs4 import BeautifulSoup

from .base import RawOpportunity

logger = logging.getLogger(__name__)

PAGE_FETCH_TIMEOUT_S = 15
LLM_BODY_EXCERPT_CHARS = 4000
LLM_MAX_TOKENS = 700


def parse_url(url: str) -> Optional[RawOpportunity]:
    """V1: OG-meta + regex deadline scrape. No LLM."""
    try:
        resp = requests.get(url, timeout=PAGE_FETCH_TIMEOUT_S, headers={
            "User-Agent": "OpportunityFilterEngine/1.0"
        })
        resp.raise_for_status()
    except Exception:
        return None

    soup = BeautifulSoup(resp.text, "html.parser")

    title = ""
    og_title = soup.find("meta", property="og:title")
    if og_title:
        title = og_title.get("content", "")
    elif soup.title:
        title = soup.title.get_text(strip=True)

    description = ""
    og_desc = soup.find("meta", property="og:description")
    meta_desc = soup.find("meta", attrs={"name": "description"})
    if og_desc:
        description = og_desc.get("content", "")
    elif meta_desc:
        description = meta_desc.get("content", "")
    else:
        main = soup.find("main") or soup.find("article") or soup.find("body")
        if main:
            description = main.get_text(separator=" ", strip=True)[:2000]

    domain = urlparse(url).netloc
    organization = _domain_to_org(domain)

    deadline = _extract_deadline(soup.get_text())

    return RawOpportunity(
        source="url_parser",
        source_url=url,
        title=title or "Untitled Opportunity",
        description_raw=description,
        url=url,
        organization=organization,
        deadline=deadline,
        location=None,
        extra_fields={
            "domain": domain,
            "needs_manual_review": True,
        },
    )


def is_safe_url(url: str) -> tuple[bool, str]:
    """SSRF guard for user-supplied URLs.

    Blocks:
      - non-http(s) schemes (file://, gopher://, ftp://, javascript:, etc.)
      - literal IP addresses (any — most attacks pass an IP directly)
      - localhost / *.local / *.internal hostnames
    Hostnames that resolve to a private range only at DNS-resolution time
    are intentionally NOT pre-resolved here (DNS-rebinding TOCTOU);
    relying on requests + TLS verification is good enough for an internal
    admin-side tool. Tighten with a connection-time hook before exposing
    this to unauthenticated traffic.

    Returns (ok, reason) so callers can echo a precise error.
    """
    try:
        parsed = urlparse(url)
    except Exception:
        return False, "malformed url"
    if parsed.scheme not in ("http", "https"):
        return False, f"scheme {parsed.scheme!r} not allowed (http/https only)"
    host = (parsed.hostname or "").lower()
    if not host:
        return False, "missing hostname"
    if host in {"localhost", "localhost.localdomain", "0.0.0.0", "::1"}:
        return False, "localhost not allowed"
    if host.endswith(".local") or host.endswith(".internal") or host.endswith(".localdomain"):
        return False, f"{host!r} not allowed (private TLD)"
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return True, ""
    return False, f"literal IP {ip} not allowed"


def parse_url_llm(url: str) -> Optional[RawOpportunity]:
    """V2: V1 fields + LLM structured extraction.

    Returns the V1 result unmodified when no LLM provider is configured
    (chat_completion returns None) or when the response is unparseable.
    Caller code should always assume V2 is best-effort enrichment on top
    of V1.
    """
    base = parse_url(url)
    if base is None:
        return None

    raw_text = _fetch_text(url)
    if raw_text is None:
        return base

    try:
        from backend.lib.llm import chat_completion, is_configured
    except ImportError:
        return base

    if not is_configured():
        return base

    body_excerpt = _strip_to_text(raw_text)[:LLM_BODY_EXCERPT_CHARS]
    messages = _build_extraction_messages(
        url=url,
        title_hint=base.title,
        description_hint=base.description_raw,
        body_excerpt=body_excerpt,
    )
    response_text = chat_completion(messages, max_tokens=LLM_MAX_TOKENS, temperature=0.1)
    if not response_text:
        return base

    parsed = _parse_llm_json(response_text)
    if parsed is None:
        logger.warning("URL %s: LLM returned unparseable JSON, falling back to V1", url)
        return base

    return _merge_llm_into_base(base, parsed)


EXTRACTION_SYSTEM_PROMPT = """You extract structured data from research / internship / scholarship URLs.
Return ONLY a single JSON object — no markdown, no commentary, no code fences.

Schema (every field is OPTIONAL; omit or use null when not stated in the source):
{
  "title": "string",
  "organization": "string",
  "opportunity_type": "research" | "internship" | "scholarship" | "fellowship" | "conference" | "other",
  "location": "string (e.g. 'Champaign, IL' or 'Remote')",
  "on_campus": boolean,
  "paid": "yes" | "no" | "stipend" | "unknown",
  "deadline": "ISO date YYYY-MM-DD",
  "description": "string (1-3 sentences, max 600 chars)",
  "skills_required": ["string"],
  "skills_preferred": ["string"],
  "preferred_year": ["freshman" | "sophomore" | "junior" | "senior" | "graduate"],
  "international_friendly": "yes" | "no" | "unknown"
}

Rules:
  - Never invent. If the source does not state a field, omit it or use null/"unknown".
  - "on_campus" is true only for UIUC / Urbana-Champaign campus locations.
  - "deadline" must be ISO date (YYYY-MM-DD). Do not include "rolling" or text.
  - For year, infer from phrases like "open to juniors" or "rising sophomores".
"""


def _build_extraction_messages(
    *, url: str, title_hint: str, description_hint: str, body_excerpt: str
) -> list[dict]:
    user_prompt = (
        f"URL: {url}\n"
        f"Title (from OG meta): {title_hint}\n"
        f"Description (from OG meta): {description_hint}\n\n"
        f"Page body excerpt:\n{body_excerpt}"
    )
    return [
        {"role": "system", "content": EXTRACTION_SYSTEM_PROMPT},
        {"role": "user", "content": user_prompt},
    ]


_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def _parse_llm_json(text: str) -> Optional[dict]:
    """Forgiving JSON extraction.

    The LLM sometimes wraps JSON in ```json fences or prefaces with an
    apology despite the system prompt. Strip common wrappers, then fall
    back to a greedy {...} regex on the first failure.
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        cleaned = re.sub(r"\s*```$", "", cleaned)
    try:
        loaded = json.loads(cleaned)
    except json.JSONDecodeError:
        match = _JSON_OBJECT_RE.search(text)
        if match is None:
            return None
        try:
            loaded = json.loads(match.group(0))
        except json.JSONDecodeError:
            return None
    return loaded if isinstance(loaded, dict) else None


_VALID_OPP_TYPES = {"research", "internship", "scholarship", "fellowship", "conference", "other"}
_VALID_PAID = {"yes", "no", "stipend", "unknown"}
_VALID_YEARS = {"freshman", "sophomore", "junior", "senior", "graduate"}
_VALID_INTL = {"yes", "no", "unknown"}
_ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _merge_llm_into_base(base: RawOpportunity, llm: dict) -> RawOpportunity:
    """Apply LLM fields on top of the V1 base, dropping anything that fails
    a schema check. Mutates extra_fields with the structured payload so
    downstream normalizers see the rich data.
    """

    def _coerce_str_list(raw: object, allowed: Optional[set[str]] = None) -> list[str]:
        if not isinstance(raw, list):
            return []
        out = []
        for item in raw:
            if not isinstance(item, str):
                continue
            value = item.strip().lower() if allowed else item.strip()
            if not value:
                continue
            if allowed and value not in allowed:
                continue
            out.append(value)
        return out

    extra: dict = dict(base.extra_fields)

    title = llm.get("title")
    if isinstance(title, str) and title.strip():
        base = _replace(base, title=title.strip())

    org = llm.get("organization")
    if isinstance(org, str) and org.strip():
        base = _replace(base, organization=org.strip())

    opp_type = llm.get("opportunity_type")
    if isinstance(opp_type, str) and opp_type.lower() in _VALID_OPP_TYPES:
        extra["opportunity_type"] = opp_type.lower()

    location = llm.get("location")
    if isinstance(location, str) and location.strip():
        base = _replace(base, location=location.strip())

    on_campus = llm.get("on_campus")
    if isinstance(on_campus, bool):
        extra["on_campus"] = on_campus

    paid = llm.get("paid")
    if isinstance(paid, str) and paid.lower() in _VALID_PAID:
        extra["paid"] = paid.lower()

    deadline = llm.get("deadline")
    if isinstance(deadline, str) and _ISO_DATE_RE.match(deadline.strip()):
        base = _replace(base, deadline=deadline.strip())

    description = llm.get("description")
    if isinstance(description, str) and description.strip():
        base = _replace(base, description_raw=description.strip())

    skills_req = _coerce_str_list(llm.get("skills_required"))
    if skills_req:
        extra["skills_required"] = skills_req

    skills_pref = _coerce_str_list(llm.get("skills_preferred"))
    if skills_pref:
        extra["skills_preferred"] = skills_pref

    pref_year = _coerce_str_list(llm.get("preferred_year"), _VALID_YEARS)
    if pref_year:
        extra["preferred_year"] = pref_year

    intl = llm.get("international_friendly")
    if isinstance(intl, str) and intl.lower() in _VALID_INTL:
        extra["international_friendly"] = intl.lower()

    extra["llm_enriched"] = True
    extra["needs_manual_review"] = False
    return _replace(base, extra_fields=extra)


def _replace(opp: RawOpportunity, **kwargs) -> RawOpportunity:
    from dataclasses import replace
    return replace(opp, **kwargs)


def _fetch_text(url: str) -> Optional[str]:
    try:
        resp = requests.get(url, timeout=PAGE_FETCH_TIMEOUT_S, headers={
            "User-Agent": "OpportunityFilterEngine/1.0"
        })
        resp.raise_for_status()
        return resp.text
    except Exception:
        return None


def _strip_to_text(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "header", "footer", "nav"]):
        tag.decompose()
    return soup.get_text(separator=" ", strip=True)


def _domain_to_org(domain: str) -> Optional[str]:
    domain_lower = domain.lower()
    mappings = {
        "illinois.edu": "University of Illinois at Urbana-Champaign",
        "mit.edu": "Massachusetts Institute of Technology",
        "stanford.edu": "Stanford University",
        "caltech.edu": "California Institute of Technology",
        "cmu.edu": "Carnegie Mellon University",
        "berkeley.edu": "University of California, Berkeley",
        "nasa.gov": "NASA",
        "nsf.gov": "National Science Foundation",
        "energy.gov": "Department of Energy",
        "nih.gov": "National Institutes of Health",
    }
    for pattern, org in mappings.items():
        if pattern in domain_lower:
            return org
    return domain


def _extract_deadline(text: str) -> Optional[str]:
    patterns = [
        r"[Dd]eadline[:\s]+(\w+ \d{1,2},?\s*\d{4})",
        r"[Dd]ue\s+(?:by|date)[:\s]+(\w+ \d{1,2},?\s*\d{4})",
        r"[Aa]pply\s+by[:\s]+(\w+ \d{1,2},?\s*\d{4})",
        r"[Cc]losing\s+date[:\s]+(\w+ \d{1,2},?\s*\d{4})",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group(1)
    return None
