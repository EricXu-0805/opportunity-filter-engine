"""One ordinary public GET per candidate source; keep only status and structural evidence."""

import hashlib
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

pages = {
    "cell_biology": "https://cellbio.jhmi.edu/faculty/",
    "cell_biology_original": "https://cellbio.jhmi.edu/people/deborah-andrew-ph-d/",
    "program_xdbio": "https://xdbio.jhmi.edu/faculty/",
    "program_bcmb": "https://bcmb.bs.jhmi.edu/faculty/",
    "anesthesiology": "https://anesthesiology.hopkinsmedicine.org/faculty/",
    "pathology": "https://pathology.jhu.edu/about/faculty",
    "public_health_mas": "https://e-catalogue.jhu.edu/public-health/departments/MAS-Office/",
}
records = []
for key, url in pages.items():
    checked = datetime.now(UTC).isoformat()
    try:
        res = requests.get(url, timeout=16)
        soup = BeautifulSoup(res.content, "html.parser")
        section = soup.select_one("main") or soup.select_one("#content") or soup
        title = soup.title.get_text(" ", strip=True) if soup.title else ""
        links = set()
        for a in section.select("a[href]"):
            href = urljoin(res.url, a["href"])
            if href.startswith(
                (
                    "https://publichealth.jhu.edu/faculty/",
                    "https://profiles.hopkinsmedicine.org/provider/",
                    "https://hub.jhu.edu/experts/profiles/",
                )
            ):
                links.add(href)
        records.append(
            {
                "key": key,
                "url": url,
                "final": res.url,
                "at": checked,
                "status": res.status_code,
                "bytes": len(res.content),
                "sha256": hashlib.sha256(res.content).hexdigest(),
                "title": title,
                "linked_institutional_profiles": len(links),
                "tables": len(section.find_all("table")),
                "primary_faculty_cards": len(soup.select(".pendari_people_grid_item.primary-faculty")),
                "secondary_appointment_cards": len(
                    soup.select(".pendari_people_grid_item.secondary-appointment-in-cb")
                ),
                "emeritus_cards": len(soup.select(".pendari_people_grid_item.faculty-emeritus-emerita")),
                "headings": len(section.select("h2,h3")),
            }
        )
        print(key, res.status_code, title, len(links), flush=True)
    except requests.RequestException as err:
        records.append({"key": key, "url": url, "at": checked, "error": type(err).__name__})
    time.sleep(0.5)
Path("jhu-current-appointment-sources.json").write_text(json.dumps(records, indent=2) + "\n")
