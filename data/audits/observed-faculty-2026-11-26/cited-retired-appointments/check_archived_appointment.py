"""Compare the real detail API and the student-facing streamed Next.js document."""
import argparse
import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup

SCOPE = "mvp-core-close-v1-contact-trust-v1-faculty-trust-v1-target-truth-v2"
# The titles are read from the original adjudicated sources, not from the response under test.
FACULTY = {
    "faculty-duke-nurs-36cb4f9e": ("Lisa S. Lewis", "Retired Associate Clinical Professor",
        "https://nursing.duke.edu/sites/default/files/documents/Duke%20Nursing%20Magazine%20Fall-Winter%202026.pdf#page=21"),
    "faculty-pitt-ling-14fc90c7": ("Charles Perfetti", "Retired Distinguished University Professor of Psychology",
        "https://lrdc.pitt.edu/departments-and-services/communications-news-media/enduring-legacy-distinguished-university-professor-and-former-lrdc-director-charles-perfetti-retire"),
    "faculty-pitt-ling-84276229": ("Richard Donato", "Emeritus Faculty, School of Education",
        "https://www.app.education.pitt.edu/people/faculty"),
    "faculty-msu-bmb-350c8c60": ("John E. Wilson", "Professor Emeritus",
        "https://bmb.natsci.msu.edu/_assets/files/alumni-and-friends/bmbmag04.pdf"),
}
STAFF_ID = "faculty-msu-mgi-6af109e0"
LABELS = {"en": ("Historical faculty appointment", "University source", "Executive Assistant to the Chair"),
          "zh": ("历史教师职务", "校方依据", "系主任行政助理")}
OUTREACH = {"Apply now", "Draft email", "Write an email", "Reveal email", "立即申请", "起草邮件", "显示邮箱"}


def checked_response(url, **kwargs):
    for attempt in range(3):
        result = requests.get(url, timeout=150, **kwargs)
        if result.status_code == 429 and attempt < 2:
            delay = result.headers.get("Retry-After", "60")
            time.sleep((int(delay) if delay.isdigit() else 60) + 1)
            continue
        result.raise_for_status()
        return result


def visible_main(document):
    main = document.select_one("main")
    assert main is not None
    # Next may append hidden fragments outside <main> and connect them via these stream commands.
    moves = re.compile(r'\$(RS|RC)\("([BPS]:[0-9a-f]+)","([BPS]:[0-9a-f]+)"\)')
    for script in document.find_all("script"):
        for mode, first, second in moves.findall(script.string or ""):
            marker_id, segment_id = (second, first) if mode == "RS" else (first, second)
            marker = document.find("template", id=marker_id)
            segment = document.find("div", id=segment_id, hidden=True)
            if marker is not None and segment is not None:
                marker.replace_with(*list(segment.contents))
    for hidden in main.select("[hidden], [aria-hidden=true], script, template"):
        hidden.decompose()
    return main


def main():
    arg = argparse.ArgumentParser()
    for key in ("api", "ui", "sha", "out"):
        arg.add_argument("--" + key, required=True)
    arg.add_argument("--fixed", action="store_true")
    args = arg.parse_args()
    health = args.api.rstrip("/") + "/api/health"
    assert checked_response(health).json()["release_sha"] == args.sha
    observed = []
    for record_id in [*FACULTY, STAFF_ID]:
        is_staff = record_id == STAFF_ID
        name, title, source = FACULTY.get(record_id, ("Debbie Walton", "", ""))
        detail = checked_response(args.api + "/api/opportunities/" + record_id, params={"_release_scope": SCOPE}).json()
        assert detail["id"] == record_id and detail["pi_name"] == name
        assert detail["target_truth"]["reason_code"] == "inactive" and detail["contact_email_status"] == "unavailable"
        if not is_staff:
            assert detail["metadata"]["faculty_title"] == title
        expected = {"title": title, "source_url": source} if args.fixed and not is_staff else None
        assert detail.get("historical_faculty_appointment") == expected
        for locale, (heading, link, staff_role) in LABELS.items():
            time.sleep(7)
            url = args.ui.rstrip("/") + "/opportunities/" + record_id
            for attempt in range(3):
                html = checked_response(url, cookies={"ofe_lang": locale})
                dom = BeautifulSoup(html.content, "html.parser")
                assert dom.html["lang"] == locale and dom.html["data-release-sha"] == args.sha
                panel = visible_main(dom)
                h1 = panel.select_one("h1")
                if not h1 or h1.get_text(" ", strip=True) not in {
                        "This opportunity is temporarily unavailable", "该机会暂时无法加载"}:
                    break
                if attempt < 2:
                    time.sleep(65)
            assert h1 and name in h1.get_text(" ", strip=True), (record_id, locale, h1)
            text = list(panel.stripped_strings)
            source_urls = [a["href"] for a in panel.select("a[href]") if a.get_text(" ", strip=True) == link]
            assert (heading in text) == bool(expected) and source_urls == ([source] if expected else [])
            if is_staff:
                assert staff_role in " ".join(text)
            else:
                assert (title in text) == args.fixed, (record_id, locale, title)
            assert not OUTREACH.intersection(text) and not panel.select('a[href^="mailto:"]')
            observed.append({"id": record_id, "name": name, "locale": locale, "api_title": detail["metadata"]["faculty_title"],
                             "historical_title_visible": title in text if not is_staff else False,
                             "source_url": source_urls[0] if source_urls else None, "staff_role_visible": is_staff,
                             "contact_email_status": "unavailable", "detail_read_attempts": attempt + 1, "public_outreach_actions": []})
    assert checked_response(health).json()["release_sha"] == args.sha
    Path(args.out).write_text(json.dumps({"release_sha": args.sha, "api": args.api, "ui": args.ui,
        "observed_at": datetime.now(UTC).isoformat(), "expected_fix": args.fixed, "details": observed},
        ensure_ascii=False, indent=2) + "\n")
    print(f"Verified {len(observed)} student-facing documents and {len(FACULTY) + 1} detail APIs.")


if __name__ == "__main__":
    main()
