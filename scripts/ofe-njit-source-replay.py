"""Read each official roster once and compare role selectors with visible labels and stored identities."""
import ast
import json
import re
from collections import Counter
from pathlib import Path
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

from bs4 import BeautifulSoup


repo = Path.cwd()
code = (repo / "src/collectors/schools/njit_faculty.py").read_text()
depts = [(ast.literal_eval(node.args[0]), ast.literal_eval(node.args[-1]))
         for node in ast.walk(ast.parse(code))
         if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
         and node.func.id == "_dept"]
held = {urlsplit(row["url"]).path.lower(): row
        for row in json.loads((repo / "data/processed/shards/njit.json").read_text())
        if row.get("source") == "njit_faculty"}
found = set()
for unit, url in depts:
    try:
        req = Request(url, headers={"User-Agent": "opportunity-filter-engine/public-roster-diagnostic"})
        with urlopen(req, timeout=10) as response:
            soup = BeautifulSoup(response.read(4_000_000), "html.parser")
    except (OSError, ValueError) as exc:
        print(unit, type(exc).__name__, flush=True)
        continue
    counts = Counter()
    for link in soup.select("a.column[href*='people.njit.edu/profile/'], li.person > a[href*='people.njit.edu/profile/']"):
        counts["cards"] += 1
        name_node = link.select_one("h1.name, .text-container > :first-child")
        title_node = link.select_one("p.title, .text-container > :nth-child(2)")
        if unit == "CS" and counts["cards"] == 1:
            box = link.select_one(".text-container")
            print("CS text-container descendants", [(d.name, d.get("class", []))
                  for d in box.find_all(True)] if box else [], flush=True)
        text = " ".join(link.stripped_strings)
        ranked = re.search(r"professor|lecturer", text, re.I) is not None
        counts["ranked_labels"] += int(ranked)
        name = name_node.get_text(" ", strip=True) if name_node else ""
        role = title_node.get_text(" ", strip=True) if title_node else ""
        if not name or not re.search(r"professor|lecturer", role, re.I):
            if ranked:
                counts["missed_rank"] += 1
            continue
        counts["selected"] += 1
        path = urlsplit(link["href"]).path.lower()
        found.add(path)
        old = held.get(path)
        if old:
            counts["known_profile"] += 1
            last, sep, first = name.partition(",")
            display = f"{first.strip()} {last.strip()}" if sep else name
            counts["matched_name"] += int(display == old.get("pi_name"))
            counts["matched_role"] += int(role == old["metadata"].get("faculty_title"))
    print(unit, dict(counts), flush=True)
print("unique_selected", len(found), "held_profile_intersection", len(found & held.keys()))
