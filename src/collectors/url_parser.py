"""
URL Parser Collector.
Accepts a pasted URL, fetches the page, and extracts opportunity fields.
V1: Basic HTML extraction. V2: LLM-powered structured extraction.
"""

import requests
from bs4 import BeautifulSoup
from typing import Optional
import re

from .base import RawOpportunity


def parse_url(url: str) -> Optional[RawOpportunity]:
    """
    Fetch a URL and extract opportunity information.
    Returns a RawOpportunity with best-effort field extraction.
    """
    try:
        resp = requests.get(url, timeout=30, headers={
            "User-Agent": "OpportunityFilterEngine/1.0"
        })
        resp.raise_for_status()
    except Exception as e:
        return None

    soup = BeautifulSoup(resp.text, "html.parser")

    # Extract title
    title = ""
    og_title = soup.find("meta", property="og:title")
    if og_title:
        title = og_title.get("content", "")
    elif soup.title:
        title = soup.title.get_text(strip=True)

    # Extract description
    description = ""
    og_desc = soup.find("meta", property="og:description")
    meta_desc = soup.find("meta", attrs={"name": "description"})
    if og_desc:
        description = og_desc.get("content", "")
    elif meta_desc:
        description = meta_desc.get("content", "")
    else:
        # Fallback: grab main content text
        main = soup.find("main") or soup.find("article") or soup.find("body")
        if main:
            description = main.get_text(separator=" ", strip=True)[:2000]

    # Extract organization from domain
    from urllib.parse import urlparse
    domain = urlparse(url).netloc
    organization = _domain_to_org(domain)

    # Try to find deadline
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


def _domain_to_org(domain: str) -> Optional[str]:
    """Map common domains to organization names."""
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
    """Try to find a deadline date in text. Returns ISO date string or None."""
    # Common patterns: "Deadline: March 15, 2026", "Due by 3/15/2026", etc.
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


if __name__ == "__main__":
    # Quick test
    test_url = "https://sfp.caltech.edu/undergraduate-research/programs/surf"
    result = parse_url(test_url)
    if result:
        print(f"Title: {result.title}")
        print(f"Org:   {result.organization}")
        print(f"Desc:  {result.description_raw[:200]}...")
    else:
        print("Failed to parse URL")
