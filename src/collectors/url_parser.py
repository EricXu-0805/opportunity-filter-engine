"""URL + Text Parser — V1 OG-meta scrape + V2 LLM-enriched structured extraction.

V1 (parse_url) saves the current static HTML body without a model. It keeps
metadata separately and refuses sources with no readable body.

V2 (parse_url_llm) layers a single LLM call on top of V1: feeds the page
existing body excerpt + legacy metadata/body hints to the model with a
strict JSON schema and merges the response into a RawOpportunity. Used
by the /api/import-url backend route the frontend's "Add by URL" flow
calls. Falls back to V1 silently when no LLM provider is configured
(see backend/lib/llm.py::is_configured).

parse_text_llm is the sibling for paste-text imports — same LLM extraction
machinery, but the body comes from the user pasting raw text instead of a
URL we fetched. Used by /api/import-text for sources where the URL is
blocked by anti-bot (LinkedIn job posts), behind a paywall, or simply not
present (Slack/email forwards). Returns None when no LLM is configured —
paste-text has no useful V1 fallback (no OG meta to scrape).
"""

from __future__ import annotations

import ipaddress
import json
import logging
import re
import socket
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Optional
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup, CData, NavigableString, Tag

from ..contact_instructions import capture_from_html, capture_metadata, same_source_page
from .base import RawOpportunity
from .import_document import extract_import_document, read_import_document

logger = logging.getLogger(__name__)

PAGE_FETCH_TIMEOUT_S = 15
LLM_BODY_EXCERPT_CHARS = 4000
# The title and description hints the model gets beside the excerpt. A page's
# metadata is otherwise unbounded, and the whole of it went into the prompt.
LLM_HINT_CHARS = 2000
LLM_MAX_TOKENS = 700

# Hard cap on a fetched body. The timeout bounds one slow connection but not a
# fast multi-GB stream, so an attacker-controlled URL could OOM the dyno by
# returning an unbounded body. 5 MB is generous for any real job/lab/posting
# page; anything larger is rejected before it is buffered into memory.
MAX_FETCH_BYTES = 5 * 1024 * 1024

# Paste-text validation bounds. Below the floor the LLM has nothing useful
# to chew on (a one-line title is better imported as a URL search), and
# above the ceiling the body excerpt truncation drops most of the input
# anyway — and the LLM context is paid per token.
PASTE_TEXT_MIN_CHARS = 50
PASTE_TEXT_MAX_CHARS = 50_000


def parse_url(
    url: str, *, html: Optional[str] = None, content_type: str | None = None,
) -> Optional[RawOpportunity]:
    """Save the current static page's readable text without a model call.

    ``html=`` reuses a fetched document; it does not create a fetch receipt.
    Metadata remains separate and cannot substitute for missing source text.
    """
    if html is None:
        resp = _safe_fetch(url)
        return _parse_fetched_page(url, resp) if resp is not None else None

    return _page_opportunity(url, extract_import_document(html, content_type=content_type))


def _page_opportunity(url: str, document: dict) -> RawOpportunity:
    domain = urlparse(url).netloc
    organization = _domain_to_org(domain)
    deadline = _extract_deadline(document["text"])
    # A guess from the address or a date near "deadline" is not a stated fact.
    inferred = {}
    if organization:
        inferred["organization"] = "heuristic:url_domain"
    if deadline:
        inferred["deadline"] = "heuristic:page_text_date"
    extra_fields = {
        "domain": domain,
        "description_source": "page_text",
        "page_meta_summary": document["meta_summary"],
        "needs_manual_review": True,
    }
    if inferred:
        extra_fields["inferred_fields"] = inferred
    return RawOpportunity(
        source="url_parser",
        source_url=url,
        title=document["title"] or "Untitled Opportunity",
        description_raw=document["text"],
        url=url,
        organization=organization,
        deadline=deadline,
        location=None,
        extra_fields=extra_fields,
    )


def _legacy_model_hints(soup: BeautifulSoup) -> tuple[str, str]:
    """Keep the existing model payload separate from locally saved full text.

    Preserve the previous metadata/body hint and title exactly, up to
    LLM_HINT_CHARS each. Full-source model processing is a separate pending
    change, not enabled by source saving.
    """
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
            description = main.get_text(separator=" ", strip=True)
    return (title or "Untitled Opportunity")[:LLM_HINT_CHARS], description[:LLM_HINT_CHARS]



class UrlImportSourceError(ValueError):
    """A fetched page cannot be attributed to the address the user submitted."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def _parse_fetched_page(url: str, response: requests.Response) -> RawOpportunity:
    return _read_fetched_page(url, response)[0]


def _read_fetched_page(url: str, response: requests.Response) -> tuple[RawOpportunity, BeautifulSoup]:
    """The saved draft and the parsed page, which the reader and the capture share."""
    final_url = getattr(response, "url", None)
    if not isinstance(final_url, str) or not final_url:
        raise UrlImportSourceError("unverified_response")
    if not same_source_page(url, final_url):
        # Do not offer the other page's title/body as a draft under the old URL.
        # The user can explicitly import the destination when it is intended.
        raise UrlImportSourceError("redirect_mismatch")
    document, soup = read_import_document(response.text, content_type=response.headers.get("Content-Type"))
    base = _page_opportunity(url, document)
    capture = capture_from_html(
        soup,
        source_url=final_url,
        requested_source_url=url,
        record_source_url=url,
        checked_at=getattr(response, "_ofe_checked_at", None),
    )
    base.extra_fields.update(capture_metadata(capture))
    return base, soup


def is_safe_url(url: str) -> tuple[bool, str]:
    """SSRF guard for user-supplied URLs.

    Blocks:
      - non-http(s) schemes (file://, gopher://, ftp://, javascript:, etc.)
      - literal IP addresses (any — most attacks pass an IP directly)
      - localhost / *.local / *.internal hostnames
    This is the cheap syntactic gate. The DNS-resolution check (a public
    *hostname* that maps to an internal IP) and per-redirect-hop revalidation
    live in ``_safe_fetch``, which is what actually performs network I/O —
    callers that fetch MUST go through it, never ``requests.get`` directly.

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


_MAX_REDIRECT_HOPS = 5


def _ip_is_blocked(ip_str: str) -> bool:
    """True for any non-public address: RFC1918 private, loopback, link-local
    (incl. the 169.254.169.254 cloud-metadata endpoint), reserved, multicast,
    or unspecified."""
    try:
        ip = ipaddress.ip_address(ip_str)
    except ValueError:
        return False
    return (
        ip.is_private or ip.is_loopback or ip.is_link_local
        or ip.is_reserved or ip.is_multicast or ip.is_unspecified
    )


def _host_resolves_to_blocked_ip(host: str) -> bool:
    """True if any address ``host`` resolves to is non-public. Closes the gap
    where ``is_safe_url`` admits a public *hostname* that resolves to an internal
    IP (an attacker pointing their own DNS at 169.254.169.254 or 10.x)."""
    if not host:
        return True
    try:
        infos = socket.getaddrinfo(host, None)
    except (OSError, UnicodeError):
        return False  # unresolvable — let requests fail naturally, don't false-block
    return any(_ip_is_blocked(info[4][0]) for info in infos)


def _safe_fetch(
    url: str,
    *,
    before_request: Callable[[str], bool] | None = None,
    on_response: Callable[[requests.Response], None] | None = None,
) -> Optional[requests.Response]:
    """SSRF-hardened GET — the only network entry point for user-supplied URLs.

    Validates the URL and EVERY redirect hop with ``is_safe_url`` plus a DNS
    check that the host maps only to public IPs, following redirects manually
    (``allow_redirects=False``) so an attacker cannot 302 a public URL to cloud
    metadata or an internal service. Returns the final ``Response`` (after
    ``raise_for_status``), or ``None`` on any block / error / redirect-budget
    overrun.

    Residual: a DNS-rebinding race between this resolution check and requests'
    own connection is not fully closed (that needs a transport that pins the
    validated IP); the manual-redirect + resolve checks defeat the directly
    exploitable bypass, which is the realistic threat for this endpoint.
    """
    # Optional observers let bounded refresh callers account for EVERY real
    # request, including redirect hops. A refusal/exception stops this fetch;
    # neither hook authorizes an otherwise unsafe address.
    headers = {"User-Agent": "OpportunityFilterEngine/1.0"}
    current = url
    try:
        for _ in range(_MAX_REDIRECT_HOPS + 1):
            ok, _reason = is_safe_url(current)
            if not ok:
                return None
            if _host_resolves_to_blocked_ip(urlparse(current).hostname or ""):
                return None
            if before_request is not None and not before_request(current):
                return None
            resp = requests.get(
                current, timeout=PAGE_FETCH_TIMEOUT_S, headers=headers,
                allow_redirects=False, stream=True,
            )
            try:
                if on_response is not None:
                    on_response(resp)
                if resp.is_redirect:
                    location = resp.headers.get("Location")
                    if not location:
                        break
                    current = urljoin(current, location)
                    continue
                resp.raise_for_status()
                declared = resp.headers.get("Content-Length")
                if declared and declared.isdigit() and int(declared) > MAX_FETCH_BYTES:
                    return None
                # Stream the body with a running byte budget so a missing/lying
                # Content-Length can't sneak an unbounded payload into memory.
                body = bytearray()
                for chunk in resp.iter_content(64 * 1024):
                    body.extend(chunk)
                    if len(body) > MAX_FETCH_BYTES:
                        return None
                resp._content = bytes(body)
                resp._content_consumed = True
                resp._ofe_checked_at = datetime.now(UTC).isoformat()
            finally:
                resp.close()
            return resp
    except Exception:
        return None
    return None  # exceeded the redirect budget


def parse_url_llm(url: str) -> Optional[RawOpportunity]:
    """V2: V1 fields + LLM structured extraction.

    Returns the V1 result unmodified when no LLM provider is configured
    (chat_completion returns None) or when the response is unparseable.
    Caller code should always assume V2 is best-effort enrichment on top
    of V1.
    """
    # Fetch once and reuse the body for both V1 parsing and the LLM excerpt
    # (was two separate _safe_fetch round-trips to the same URL).
    response = _safe_fetch(url)
    if response is None:
        return None
    base, soup = _read_fetched_page(url, response)

    body_excerpt = _strip_to_text(soup, limit=LLM_BODY_EXCERPT_CHARS)[:LLM_BODY_EXCERPT_CHARS]
    title_hint, description_hint = _legacy_model_hints(soup)
    enriched = _run_llm_extraction(
        base,
        body_excerpt=body_excerpt,
        url_hint=url,
        title_hint=title_hint,
        description_hint=description_hint,
    )
    # URL flow has the saved static source, so on an LLM failure
    # we return the V1 result rather than failing the whole request.
    return enriched if enriched is not None else base


def parse_text_llm(text: str) -> Optional[RawOpportunity]:
    """Extract a structured opportunity from a free-form pasted text body.

    Sibling of parse_url_llm — same LLM schema, same merge logic, same
    schema validation. The difference: the body excerpt comes from the
    user pasting text directly instead of from a URL we fetched.

    Useful for sources where URL fetching is blocked (LinkedIn anti-bot
    walls, Indeed paywalls), or sources that don't have a URL at all
    (Slack/email forwards of a job description).

    Validation: callers should enforce
    ``PASTE_TEXT_MIN_CHARS <= len(text.strip()) <= PASTE_TEXT_MAX_CHARS``
    before calling. This function trusts the input and only truncates
    further to ``LLM_BODY_EXCERPT_CHARS`` for the LLM prompt.

    Returns None when:
      - the LLM is not configured (paste-text has no V1 fallback; there
        is no OG meta on a plain text body),
      - the LLM call returns no response, or
      - the LLM response is unparseable JSON.

    Returns a merged RawOpportunity with ``llm_enriched=True`` on success.
    """
    base = RawOpportunity(
        source="text_parser",
        source_url="",
        title="Untitled Opportunity",
        description_raw=text,
        url="",
        organization=None,
        extra_fields={"needs_manual_review": True, "description_source": "pasted_text"},
    )

    body_excerpt = text[:LLM_BODY_EXCERPT_CHARS]
    enriched = _run_llm_extraction(
        base,
        body_excerpt=body_excerpt,
        url_hint=None,
        title_hint="",
        description_hint="",
    )
    # paste-text has no useful V1 fallback — if LLM is unconfigured or
    # failed, treat as an unrecoverable error so the route can surface a
    # specific message instead of returning an empty skeleton.
    if enriched is None:
        return None
    if not enriched.extra_fields.get("llm_enriched"):
        # _run_llm_extraction returned `base` unchanged → LLM not configured.
        return None
    return enriched


def _run_llm_extraction(
    base: RawOpportunity,
    *,
    body_excerpt: str,
    url_hint: Optional[str],
    title_hint: str,
    description_hint: str,
) -> Optional[RawOpportunity]:
    """Run a single LLM extraction pass and merge the response into ``base``.

    Shared core between parse_url_llm and parse_text_llm so the LLM
    prompt, schema, JSON parsing, and merge rules stay in one place.

    Returns:
      - ``base`` unchanged when no LLM provider is configured. Callers
        with a V1 fallback (parse_url_llm) treat this as the V1 result;
        callers without (parse_text_llm) detect it via the absence of
        ``llm_enriched`` in extra_fields.
      - ``None`` when the LLM was called but returned an empty response
        or unparseable JSON. Distinct from the "unconfigured" return so
        callers can log + decide whether to surface an error.
      - The merged RawOpportunity on success.
    """
    # Scope is established by this call, never inherited or model-reported.
    extra = dict(base.extra_fields)
    extra.pop("ai_input_scope", None)
    base = _replace(base, extra_fields=extra)
    try:
        from backend.lib.llm import chat_completion, is_configured
    except ImportError:
        return base

    if not is_configured():
        return base

    messages = _build_extraction_messages(
        url=url_hint or "",
        title_hint=title_hint,
        description_hint=description_hint,
        body_excerpt=body_excerpt,
    )
    response_text = chat_completion(messages, max_tokens=LLM_MAX_TOKENS, temperature=0.1)
    if not response_text:
        return None

    parsed = _parse_llm_json(response_text)
    if parsed is None:
        # Deliberately no url_hint here: user-submitted URLs can carry signed
        # tokens / PII in query strings and must not land in logs.
        logger.warning("LLM returned unparseable JSON, no enrichment")
        return None

    result = _merge_llm_into_base(base, parsed)
    result.extra_fields["ai_input_scope"] = (
        "full_source" if _model_received_all(base.description_raw, body_excerpt) else "source_excerpt"
    )
    return result


def _model_received_all(saved_text: str, body_excerpt: str) -> bool:
    """Whether every word of the saved source, in order, was in the model input.

    The excerpt is cut at LLM_BODY_EXCERPT_CHARS and, for pages, drops
    navigation and footers the saved text keeps. Numbers our reader adds to
    ordered-list items are not source words.
    """
    sent = iter(re.findall(r"\w+", body_excerpt))
    return all(word in sent for word in re.findall(r"\w+", re.sub(r"(?m)^-?\d+\. ", "", saved_text)))


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


def _parse_llm_json(text: str) -> Optional[dict]:
    """Forgiving JSON extraction.

    The LLM sometimes wraps JSON in ```json fences or prefaces with an
    apology despite the system prompt. Strip common wrappers, then fall
    back to the span from the first '{' to the last '}' on the first failure.
    Every step is linear in the reply: a page can steer what the model writes.
    """
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned)
        if cleaned.endswith("```"):
            cleaned = cleaned[:-3].rstrip()
    try:
        loaded = json.loads(cleaned)
    except (json.JSONDecodeError, RecursionError):
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end < start:
            return None
        try:
            loaded = json.loads(text[start:end + 1])
        except (json.JSONDecodeError, RecursionError):
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
    inferred = dict(extra.get("inferred_fields") or {})

    title = llm.get("title")
    if isinstance(title, str) and title.strip():
        base = _replace(base, title=title.strip())
        inferred["title"] = "llm:url_parser"

    org = llm.get("organization")
    if isinstance(org, str) and org.strip():
        base = _replace(base, organization=org.strip())
        inferred["organization"] = "llm:url_parser"

    opp_type = llm.get("opportunity_type")
    if isinstance(opp_type, str) and opp_type.lower() in _VALID_OPP_TYPES:
        extra["opportunity_type"] = opp_type.lower()
        inferred["opportunity_type"] = "llm:url_parser"

    location = llm.get("location")
    if isinstance(location, str) and location.strip():
        base = _replace(base, location=location.strip())
        inferred["location"] = "llm:url_parser"

    on_campus = llm.get("on_campus")
    if isinstance(on_campus, bool):
        extra["on_campus"] = on_campus
        inferred["on_campus"] = "llm:url_parser"

    paid = llm.get("paid")
    if isinstance(paid, str) and paid.lower() in _VALID_PAID:
        extra["paid"] = paid.lower()
        inferred["paid"] = "llm:url_parser"

    deadline = llm.get("deadline")
    if isinstance(deadline, str) and _ISO_DATE_RE.match(deadline.strip()):
        base = _replace(base, deadline=deadline.strip())
        inferred["deadline"] = "llm:url_parser"

    description = llm.get("description")
    if isinstance(description, str) and description.strip():
        extra["suggested_description"] = description.strip()
        inferred["suggested_description"] = "llm:url_parser"

    # Model lists are review suggestions, not source-stated qualifications.
    # Preserve every suggested skill while dropping only duplicate labels.
    skills = _coerce_str_list(llm.get("skills_required")) + _coerce_str_list(llm.get("skills_preferred"))
    suggested = []
    seen = set()
    for skill in skills:
        if skill.casefold() not in seen:
            suggested.append(skill)
            seen.add(skill.casefold())
    if suggested:
        extra["suggested_skills"] = suggested
        inferred["suggested_skills"] = "llm:url_parser"

    pref_year = _coerce_str_list(llm.get("preferred_year"), _VALID_YEARS)
    if pref_year:
        extra["preferred_year"] = pref_year
        inferred["preferred_year"] = "llm:url_parser"

    intl = llm.get("international_friendly")
    if isinstance(intl, str) and intl.lower() in _VALID_INTL:
        extra["international_friendly"] = intl.lower()
        inferred["international_friendly"] = "llm:url_parser"

    extra["llm_enriched"] = True
    extra["needs_manual_review"] = True
    if inferred:
        extra["inferred_fields"] = inferred
    return _replace(base, extra_fields=extra)


def _replace(opp: RawOpportunity, **kwargs) -> RawOpportunity:
    from dataclasses import replace
    return replace(opp, **kwargs)


_EXCERPT_SKIP = frozenset({"script", "style", "noscript", "header", "footer", "nav"})


def _strip_to_text(soup: BeautifulSoup, *, limit: Optional[int] = None) -> str:
    """The page's text outside scripts, styles, no-script notices, headers,
    footers and navigation, as get_text(" ", strip=True) joins it.

    Reads the parsed page in one pass without changing it, and stops once the
    text is longer than ``limit``.
    """
    pieces: list[str] = []
    length = 0
    frames = [iter(soup.contents)]
    while frames:
        node = next(frames[-1], None)
        if node is None:
            frames.pop()
        elif isinstance(node, Tag):
            if node.name not in _EXCERPT_SKIP:
                frames.append(iter(node.contents))
        elif type(node) in (NavigableString, CData):
            text = node.strip()
            if text:
                pieces.append(text)
                length += len(text) + 1
                if limit is not None and length > limit:
                    break
    return " ".join(pieces)


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
