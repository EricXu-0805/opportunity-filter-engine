"""Observe the existing campus collector and official replacement pages from its normal runner."""
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import requests
from bs4 import BeautifulSoup
from src.collectors import faculty_graph, ucb_common
from src.collectors.schools.uf_faculty import SCHOOL

OLD_ROSTER = "https://www.phys.ufl.edu/wp/index.php/people/faculty/"
CURRENT = "https://phys.ufl.edu/people/faculty/"
OLD_PERSON = "https://phys.ufl.edu/people/faculty/jeff-andrews/"
PERSON = "https://phys.ufl.edu/directory/jeff-andrews/"


def observe(url):
    response = requests.get(url, headers=ucb_common.HEADERS, timeout=35)
    soup = BeautifulSoup(response.content, "html.parser")
    item = {"requested": url, "landed": response.url, "status": response.status_code,
            "headings": [h.get_text(" ", strip=True) for h in soup.select("h1")][:3],
            "body_sha256": hashlib.sha256(response.content).hexdigest(), "legacy_table_rows": len(soup.select("table tr"))}
    if not response.ok:
        return item
    if url in {CURRENT, OLD_ROSTER}:
        names = [h for h in soup.select("h3") if h.get_text(" ", strip=True)]
        sample = next((node for node in names if node.get_text(" ", strip=True) == "Jeff Andrews"), None)
        item["h3_count"] = len(names)
        if sample:
            name = sample.get_text(" ", strip=True)
            ancestors = list(sample.parents)[:7]
            item["sample_structure"] = [{"tag": a.name, "class": a.get("class")} for a in ancestors]
            card = next((a for a in ancestors if a.find("a", href=PERSON) or a.find("a", href="/directory/jeff-andrews/")), None)
            if card:
                item["card_tag"] = card.name
                item["card_class"] = card.get("class")
                item["sample_elements"] = [{"tag":n.name,"class":n.get("class"),
                    "text":n.get_text(" ",strip=True) if n.name in {"h3","p"} and "@" not in n.get_text() and len(n.get_text(strip=True))<90 else "",
                    "link":n.get("href") if (n.get("href") or "").startswith(("https://phys.ufl.edu/directory/", "/directory/")) else None}
                    for n in card.select("h3,p,a,span")]
                if url == CURRENT:
                    items = soup.find_all(card.name, class_=" ".join(card.get("class", []))) if card.get("class") else []
                    item["cards_with_this_class"] = len(items)
                    item["cards"] = [{"heading":h.get_text(" ",strip=True),
                        "biography":a.get("href") if a is not None else None}
                        for c in items if (h:=c.select_one("h3"))
                        for a in [next((l for l in c.find_all("a",href=True)
                                      if "/directory/" in l["href"]),None)]]
    if url == PERSON:
        item["rank_visible"] = "Assistant Professor" in soup.get_text(" ",strip=True)
    return item


def main():
    pages = []
    for url in (OLD_ROSTER, CURRENT, OLD_PERSON, PERSON):
        try:
            pages.append(observe(url))
        except requests.RequestException as e:
            pages.append({"requested":url,"error":type(e).__name__})
    department = next(d for d in SCHOOL["departments"] if d["short"] == "PHY")
    ledger = {}
    rows = faculty_graph.fetch_and_normalize({**SCHOOL,"departments":[department]},deep=True,unit_ledger=ledger)
    stored = [r for r in json.loads(Path("data/processed/shards/uf.json").read_bytes()) if r["id"].startswith("faculty-uf-phy-")]
    unit = ledger.get("phy", {})
    result = {"observed_at":datetime.now(UTC).isoformat(timespec="seconds"),"official_requests":pages,
              "normal_existing_collector_count":len(rows),"normal_existing_original_ids":[r["id"] for r in rows],
              "stored_total":len(stored),"stored_active":sum(r["metadata"].get("is_active") is True for r in stored),
              "unit":{k:unit[k] for k in ("fetch_status","parse_status","observed_count","coverage","completeness_status") if k in unit}}
    Path("../uf-physics-official-structure.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print("HTTP status, source count:", [(p["requested"],p.get("status")) for p in pages],len(rows))


if __name__ == "__main__":
    main()
