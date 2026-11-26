"""Read the current named row from three official School of Education faculty tables."""
import json
from datetime import datetime, timezone
from pathlib import Path

import requests
from bs4 import BeautifulSoup


URLS = (
    "https://www.app.education.pitt.edu/people/faculty",
    "https://app.education.pitt.edu/People/ByDept",
    "https://app.education.pitt.edu/people/index",
)
results = []
for url in URLS:
    response = requests.get(url, timeout=(10, 25))
    found = []
    if response.ok:
        soup = BeautifulSoup(response.content, "html.parser")
        for row in soup.select("tr"):
            cells = [td.get_text(" ", strip=True) for td in row.select("td")]
            if cells and cells[0] == "Donato, Richard":
                found.append({"name": cells[0], "role": cells[1]})
    results.append({"url": url, "http": response.status_code, "rows": found})
print(results)
Path("education-faculty.json").write_text(json.dumps({
    "checked_at": datetime.now(timezone.utc).isoformat(), "offices": results,
}, indent=2) + "\n")
