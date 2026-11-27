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
    "school_directory": "https://publichealth.jhu.edu/faculty/directory/list",
    "biostat_primary": "https://publichealth.jhu.edu/departments/biostatistics/people/faculty/primary-faculty-within-biostatistics?display_type=table",
    "biostat_catalogue": "https://e-catalogue.jhu.edu/public-health/departments/biostatistics/",
    "epidemiology": "https://publichealth.jhu.edu/departments/epidemiology/people/faculty",
    "welch": "https://publichealth.jhu.edu/welch-center-for-prevention-epidemiology-and-clinical-research/people/core-faculty",
    "university_experts": "https://hub.jhu.edu/experts/topics/public-health/",
    "cross_school_health_engineering": "https://ehe.jhu.edu/faculty-staff/",
    "emergency_medicine": "https://www.hopkinsmedicine.org/emergency-medicine/faculty",
    "psychiatry": "https://www.hopkinsmedicine.org/psychiatry/expert-team",
    "medical_school_provider": "https://profiles.hopkinsmedicine.org/provider/ed-bessman/2709084",
    "biostat_caffo": "https://publichealth.jhu.edu/faculty/1010/brian-s-caffo",
    "biostat_lab": "https://jhudatascience.org/people.html",
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
                "headings": len(section.select("h2,h3")),
            }
        )
        print(key, res.status_code, title, len(links), flush=True)
    except requests.RequestException as err:
        records.append({"key": key, "url": url, "at": checked, "error": type(err).__name__})
    time.sleep(0.5)
Path("jhu-current-appointment-sources.json").write_text(json.dumps(records, indent=2) + "\n")
