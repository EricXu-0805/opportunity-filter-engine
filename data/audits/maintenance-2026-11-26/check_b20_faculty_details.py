"""Read the additional B20 faculty records through ordinary Chrome and the public detail endpoint."""
import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urlsplit

import requests
from playwright.sync_api import sync_playwright


CATALOG = "https://catalog.tamu.edu/graduate/colleges-schools-interdisciplinary/engineering/electrical-computer/#faculty:~:text=Savari%2C%20Serap%20A%2C%20Associate%20Professor"
MATH = "https://as.vanderbilt.edu/math/"
FACULTY = {
    "faculty-tamu-ece-d96cfd82": ("Serap Savari", CATALOG, "Associate Professor, Electrical & Computer Engineering"),
    "faculty-vanderbilt-math-1d5fbacf": ("Krzysztof Kapulkin", MATH + "bio/krzysztof-kapulkin", "Professor of Mathematics · Dual Appointment: Computer Science"),
    "faculty-vanderbilt-math-727dd848": ("Philip Crooke", MATH + "bio/philip-crooke", ""),
    "faculty-vanderbilt-math-f7a0a768": ("Edward Saff", MATH + "bio/edward-saff", ""),
    "faculty-ucsd-nano-8a42e65d": ("Zeinab Jahed", "https://jacobsschool.ucsd.edu/faculty/profile?id=527", "Associate Professor"),
    "faculty-ucf-cs-edfc1c62": ("Ali Al Kinoon", "https://www.cecs.ucf.edu/faculty/alialkinoon/", "Lecturer"),
}


def read(url, params=None):
    for i in range(2):
        response = requests.get(url, params=params, timeout=45)
        if response.status_code != 429 or i:
            response.raise_for_status()
            return response.json()
        time.sleep(int(response.headers.get("Retry-After", "60")) + 1)


def check(page, args, key):
    name, profile, title = FACULTY[key]
    data = read(args.site + "/api/opportunities/" + key, {"_release_scope": args.scope})
    assert (data["id"], data["pi_name"], data["url"]) == (key, name, profile)
    assert data["metadata"].get("faculty_title", "") == title
    assert data["target_truth"]["actionable"]
    quote = data["detail_fields"]["fields"]["professor_or_lab"].get("quotes", {}).get("faculty_rank")
    if key == "faculty-ucsd-nano-8a42e65d":
        assert data["source_url"] == profile
        assert quote["text"] == title and quote["source_url"] == profile
        receipt = data["metadata"]["faculty_title_observation"]
        assert receipt["source"] == receipt["profile"] == profile
        assert receipt["roster_url"] == "https://www.nanoengineering.ucsd.edu/index.php/fac"
    if key.startswith("faculty-vanderbilt"):
        if title:
            assert quote["source_url"] == MATH + "faculty/" and quote["text"] == title
        else:
            assert not quote and not data["metadata"].get("faculty_title_observation")
    url = args.site + "/opportunities/" + key
    response = page.goto(url, wait_until="domcontentloaded", timeout=60000)
    assert response and response.status == 200
    page.get_by_role("link", name="Back to matches", exact=True).wait_for(state="visible", timeout=45000)
    main = page.get_by_role("main")
    assert page.locator("html").get_attribute("data-release-sha") == args.sha
    assert main.get_by_role("heading", level=1).inner_text() == name
    label = "View source" if profile == CATALOG else "View faculty profile"
    action = main.get_by_role("link", name=label, exact=True)
    assert action.is_visible() and action.get_attribute("href") == profile
    if profile == CATALOG:
        assert not main.get_by_role("link", name="View faculty profile", exact=True).is_visible()
    if key.startswith("faculty-vanderbilt") and title:
        assert title in main.inner_text()
    return {"id": key, "url": url, "name": name, "rank": title, "rank_source": quote,
            "link_label": label, "visible_href": profile, "active": True, "passed": True}


def main():
    parser = argparse.ArgumentParser()
    for flag in ("site", "sha", "scope", "out"):
        parser.add_argument("--" + flag, required=True)
    parser.add_argument("--include-ucf", action="store_true")
    args = parser.parse_args()
    assert urlsplit(args.site).hostname in ("127.0.0.1", "localhost", "joinalab.com")
    assert read(args.site + "/api/health")["release_sha"] == args.sha
    rows = []
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(locale="en-US", viewport={"width": 1400, "height": 960})
        for key in FACULTY:
            if key.startswith("faculty-ucf") and not args.include_ucf:
                continue
            page = context.new_page()
            try:
                result = check(page, args, key)
            except Exception as exc:
                result = {"id": key, "passed": False, "error": f"{type(exc).__name__}: {exc}"[:450],
                          "main_text": page.get_by_role("main").all_inner_texts()[:1]}
            print(key, result["passed"], flush=True)
            rows.append(result)
            page.close()
            time.sleep(18)
        browser.close()
    assert read(args.site + "/api/health")["release_sha"] == args.sha
    out = {"release_sha": args.sha, "checked_at": datetime.now(UTC).isoformat(), "site": args.site, "rows": rows}
    Path(args.out).write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    assert all(row["passed"] for row in rows)


if __name__ == "__main__":
    main()
