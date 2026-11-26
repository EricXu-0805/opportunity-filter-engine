"""Read the independently published Pitt CS and SCI lists, without processing contact fields."""
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup


PAGES = (
    ("cs", "https://www.cs.pitt.edu/people/full-time-faculty",
     ".views-row", ".views-field-title .field-content", ".views-field-field-person-img a[href]"),
    ("school", "https://www.sci.pitt.edu/people/department-computer-science-faculty",
     ".views-row", ".views-field-title a[href]", ".views-field-title a[href]"),
)


def read(authority, url, card_selector, name_selector, link_selector):
    response = requests.get(url, timeout=(10, 30))
    result = {"authority": authority, "url": url, "http": response.status_code, "final_url": response.url, "rows": []}
    if response.ok:
        page = BeautifulSoup(response.content, "html.parser")
        for card in page.select(card_selector):
            name = card.select_one(name_selector)
            link = card.select_one(link_selector)
            title = card.select_one(".views-field-field-title .field-content")
            if name and link and title:
                result["rows"].append({
                    "name": name.get_text(" ", strip=True).rstrip(" »"),
                    "official_rank": title.get_text(" ", strip=True),
                    "individual_url": urljoin(response.url, link["href"]),
                })
    return result


if __name__ == "__main__":
    results = [read(*page) for page in PAGES]
    receipt = {"checked_at": datetime.now(timezone.utc).isoformat(), "sources": results}
    Path("pitt-cs-public-lists.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print([(r["authority"], r["http"], len(r["rows"])) for r in results])
