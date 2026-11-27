"""Read only public headings, job titles and profile links on the JHU center's published list."""
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

directory = "https://clf.jhsph.edu/about-us/people"
response = requests.get(directory, timeout=20)
response.raise_for_status()
soup = BeautifulSoup(response.content, "html.parser")
rows = []
for group in soup.select(".people-list-new"):
    label = group.select_one("h2")
    if not label or label.get_text(" ", strip=True) != "Affiliated Faculty":
        continue
    for card in group.select(".people-list-entry__info"):
        anchor = card.select_one("h3 a[href]")
        position = card.select_one("h4")
        url = urljoin(directory, anchor["href"])
        assert url.startswith("https://clf.jhsph.edu/about-us/staff/")
        entry = {"listed_name": anchor.get_text(" ", strip=True), "listed_title": position.get_text(" ", strip=True),
                 "university_person": url, "group": "Affiliated Faculty"}
        try:
            individual = requests.get(url, timeout=16)
            person = BeautifulSoup(individual.content, "html.parser")
            entry.update(status=individual.status_code, final_url=individual.url,
                         person_name=person.h1.get_text(" ", strip=True) if person.h1 else None,
                         person_title=person.h4.get_text(" ", strip=True) if person.h4 else None,
                         observed_at=datetime.now(timezone.utc).isoformat())
        except requests.RequestException as error:
            entry["error"] = type(error).__name__
        rows.append(entry)
        time.sleep(0.5)
receipt = {"roster": directory, "status": response.status_code, "heading": soup.h1.get_text(" ", strip=True),
           "entries": rows, "scope": "Distinct center membership. Only quote a home unit where the university lists it."}
Path("jhu-current-appointment-sources.json").write_text(json.dumps(receipt, indent=2) + "\n")
print(len(rows), "affiliated faculty cards,", sum(r.get("person_title") == r["listed_title"] for r in rows), "confirmed titles")
