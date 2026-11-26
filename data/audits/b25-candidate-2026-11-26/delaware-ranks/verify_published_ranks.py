"""Read the Delaware Materials rank, source and observation date on the official site."""
import argparse
import json
import re
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup

SITE = "https://joinalab.com"
SCOPE = "?_release_scope=mvp-core-close-v1-contact-trust-v1-faculty-trust-v1-target-truth-v2"
FACET = "fact-professor_or_lab-faculty_rank"


def read(path):
    for attempt in range(3):
        try:
            result = requests.get(SITE + path, timeout=(8, 25))
            if result.status_code not in (429, 502, 503, 504) or attempt == 2:
                result.raise_for_status()
                return result
            time.sleep(max(3, int(result.headers.get("Retry-After", 3))))
        except (requests.Timeout, requests.ConnectionError):
            if attempt == 2:
                raise
            time.sleep(3)
    raise RuntimeError(path)


def releases():
    home = read("/").text
    return [re.search(r'data-release-sha="([a-f0-9]{40})"', home)[1], read("/api/health").json()["release_sha"]]


def observe(case, phase):
    oid = case["id"]
    page = BeautifulSoup(read("/opportunities/" + oid).content, "html.parser")
    api = read("/api/opportunities/" + oid + SCOPE).json()
    field = api["detail_fields"]["fields"]["professor_or_lab"]
    rank_node = page.select_one(f'[data-testid="{FACET}"]')
    quotation = page.select_one(f'[data-testid="{FACET}-quote"]')
    citation = page.select_one(f'[data-testid="{FACET}-quote-source"]')
    href = citation.select_one("a[href]") if citation else None
    quote = field["quotes"].get("faculty_rank", {})
    seen = quote.get("observed_at")
    rank = field["explicit"].get("faculty_rank")
    h1 = [el.get_text(" ", strip=True) for el in page.select("h1")]
    shown = rank_node.get_text(" ", strip=True) if rank_node else None
    identity = case["name"] in h1 and api["id"] == oid and api["pi_name"] == case["name"]
    if phase == "after":
        correct = (rank == case["title"] == quote.get("text") and case["source"] == quote.get("source_url")
                   and bool(quotation and quotation.get_text(" ", strip=True) == rank)
                   and bool(href and href["href"] == case["source"])
                   and bool(seen and seen >= "2026-11-26" and citation and seen in citation.get_text(" ", strip=True)))
    else:
        correct = bool("faculty_rank" in field["unknown"] and not rank and not quote and shown
                       and "Not provided" in shown and not quotation and not citation)
    return {"id": oid, "name": case["name"], "role_in_api": rank, "role_quote_in_api": quote,
            "role_in_page": shown, "link_in_role": href["href"] if href else None,
            "page_and_api_identity_match": identity, "passed": bool(identity and correct)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("release")
    parser.add_argument("phase", choices=["old-four", "all-without-rank", "after"])
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    cases = json.loads(Path(__file__).with_name("cases.json").read_text())
    if args.phase == "old-four":
        cases = [case for case in cases if case["old"]]
    before = releases()
    if before != [args.release] * 2:
        raise RuntimeError(before)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda case: observe(case, args.phase), cases))
    after = releases()
    receipt = {"checked_at": datetime.now(timezone.utc).isoformat(), "phase": args.phase,
               "versions_before": before, "versions_after": after, "public_details": results}
    args.output.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    print(f"{sum(row['passed'] for row in results)}/{len(results)}", flush=True)
    if before != after or not all(row["passed"] for row in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
