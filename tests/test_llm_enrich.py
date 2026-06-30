"""Tests for the run-once LLM faculty enrichment pass (src/collectors/llm_enrich.py).

Network + the LLM call are monkeypatched; the value under test is the structural
accuracy guards (listing-URL skip, thin-page skip, updates-only apply) and the
school filter — not the extraction model itself.
"""
import bs4

from src.collectors import llm_enrich as le


def _soup(html):
    return bs4.BeautifulSoup(html, "html.parser")


PROFILE = "<main><p>" + ("She studies wireless networking and embedded systems. " * 6) + "</p></main>"
THIN = "<main><p>Jane Roe. Assistant Professor. jroe@x.edu.</p></main>"


def test_broad_targets_skips_listing_urls_and_respects_school():
    opps = [
        {"pi_name": "A", "school": "uw", "url": "https://x.edu/a"},          # per-person, fieldless
        {"pi_name": "B", "school": "uw", "url": "https://x.edu/listing"},    # shared listing
        {"pi_name": "C", "school": "uw", "url": "https://x.edu/listing"},    # shared listing
        {"pi_name": "D", "school": "ucla", "url": "https://x.edu/d"},        # other school
        {"pi_name": "E", "school": "uw", "url": "https://x.edu/e", "keywords": ["x"]},  # already keyworded
    ]
    targets = le._broad_targets(opps, schools=["uw"])
    names = {o["pi_name"] for o in targets}
    assert names == {"A"}  # B/C on listing URL, D wrong school, E already has keywords


def test_harvest_thin_and_listing_skip(monkeypatch):
    opps = [
        {"pi_name": "A", "school": "uw", "url": "https://x.edu/a"},          # rich profile
        {"pi_name": "B", "school": "uw", "url": "https://x.edu/thin"},       # thin page
        {"pi_name": "C", "school": "uw", "url": "https://x.edu/listing"},
        {"pi_name": "D", "school": "uw", "url": "https://x.edu/listing"},    # listing -> skipped pre-fetch
    ]
    pages = {"https://x.edu/a": _soup(PROFILE), "https://x.edu/thin": _soup(THIN)}
    monkeypatch.setattr(le, "fetch_soup", lambda u: pages.get(u))
    monkeypatch.setattr(le.time, "sleep", lambda *a: None)
    monkeypatch.setattr(
        le, "_llm_research_keywords",
        lambda body, page: ["wireless networking", "embedded systems"],
    )
    mapping = le.harvest_llm_keywords(opps, schools=["uw"], throttle=0)
    assert mapping == {"https://x.edu/a": ["wireless networking", "embedded systems"]}


def test_apply_is_updates_only():
    opps = [
        {"pi_name": "A", "school": "uw", "url": "https://x.edu/a"},
        {"pi_name": "E", "school": "uw", "url": "https://x.edu/e", "keywords": ["existing"]},
    ]
    mapping = {"https://x.edu/a": ["robotics"], "https://x.edu/e": ["should-not-apply"]}
    n = le.apply_llm_keywords(opps, mapping)
    assert n == 1
    assert opps[0]["keywords"] == ["robotics"]
    assert opps[1]["keywords"] == ["existing"]  # never overwritten
