"""Check the two published Summer Lab IDs with a synthetic, unsaved student profile.

Run from a source checkout with PYTHONPATH=. and provide the expected deployed Git SHA.
Only the public health, page, and non-LLM read-only matching routes are used.
"""

import argparse
import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import requests

from scripts.measure_match_latency import FIRST_PAGE_VIEW, PERSONAS

HOST_ID = "uchicago-8cd2def060b6"
DIRECTORY_ID = "sro-d6b78515"
HOST_SOURCE = "uchicago_external_research"
DIRECTORY_SOURCE = "uiuc_sro"
CLOSE = datetime(2027, 1, 11, 23, 59, tzinfo=ZoneInfo("America/Chicago"))


def run(session, site, expected_release, check_paid):
    observed = datetime.now(UTC)
    if observed >= CLOSE:
        raise ValueError("The positive matching cases require observation before the January 2027 cutoff.")

    def version():
        front = session.get(f"{site}/about", timeout=45)
        front.raise_for_status()
        marker = re.search(r'data-release-sha="([0-9a-f]{40})"', front.text)
        back = session.get(f"{site}/api/health", timeout=45)
        back.raise_for_status()
        pair = [marker.group(1) if marker else None, back.json()["release_sha"]]
        if pair != [expected_release, expected_release]:
            raise ValueError(f"Observed releases {pair}, expected {expected_release}")
        return pair

    cases = [
        ({}, [HOST_ID]),
        ({"source": HOST_SOURCE}, [HOST_ID]),
        ({"source": DIRECTORY_SOURCE}, [DIRECTORY_ID]),
        ({"tab": "starred", "favorite_ids": [HOST_ID]}, [HOST_ID]),
        ({"tab": "starred", "favorite_ids": [DIRECTORY_ID]}, [DIRECTORY_ID]),
        ({"tab": "starred", "favorite_ids": [HOST_ID, DIRECTORY_ID]}, [HOST_ID, DIRECTORY_ID]),
    ]
    cases_with_profile = [(True, view, ids) for view, ids in cases]
    if check_paid:
        for international in (True, False):
            for view, ids in cases[:3]:
                cases_with_profile.append((international, {**view, "intl": "yes", "paid": "yes"}, ids))
    receipt = {"started": observed.isoformat(), "release": version(), "site": site, "views": []}
    for international, filters, expected_ids in cases_with_profile:
        profile = {
            **PERSONAS["uiuc_cs"], "name": "DSI release check", "school": "University of Chicago",
            "home_school": "uchicago", "college": "The College", "year": "sophomore",
            "desired_fields": ["data science"], "international_student": international,
        }
        view = {**FIRST_PAGE_VIEW, "today": observed.astimezone(CLOSE.tzinfo).date().isoformat(),
                "tab": "all", "search_query": "summer lab", **filters}
        request = {"profile": profile, "view": view, "page_size": 50}
        endpoint = f"{site}/api/matches/view?llm=false"
        response = session.post(endpoint, json=request, timeout=150)
        if response.status_code == 429:
            time.sleep(int(response.headers.get("Retry-After", "60")) + 1)
            response = session.post(endpoint, json=request, timeout=150)
        response.raise_for_status()
        payload = response.json()
        actual = [result["opportunity"]["id"] for result in payload["results"]]
        if sorted(actual) != sorted(expected_ids) or payload["filtered_total"] != len(expected_ids):
            raise AssertionError((filters, expected_ids, actual, payload["filtered_total"]))
        receipt["views"].append({"international_student": international, "filters": filters, "ids": actual,
                                 "count": payload["filtered_total"], "http": response.status_code})
        time.sleep(1)
    receipt["release_after"] = version()
    receipt["finished"] = datetime.now(UTC).isoformat()
    return receipt


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("expected_release")
    parser.add_argument("output", type=Path)
    parser.add_argument("--check-paid", action="store_true", help="Apply once PR 1488 is deployed.")
    args = parser.parse_args()
    if not re.fullmatch("[0-9a-f]{40}", args.expected_release):
        parser.error("A full release SHA is required.")
    with requests.Session() as client:
        result = run(client, "https://joinalab.com", args.expected_release, args.check_paid)
    args.output.write_text(json.dumps(result, indent=2) + "\n")
