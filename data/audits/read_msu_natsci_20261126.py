"""Read only the public MSU directory pages used by the November 24 refresh."""
import ast
from datetime import datetime, timezone
import json
from pathlib import Path
import time

import requests

source = Path("scheduled-source/src/collectors/ucb_common.py")
assignment = next(node for node in ast.parse(source.read_text()).body
                  if isinstance(node, ast.Assign)
                  and any(isinstance(target, ast.Name) and target.id == "HEADERS" for target in node.targets))
headers = ast.literal_eval(assignment.value)
departments = {"PHYS": 34, "MATH": 3, "STAT": 2, "BMB": 6, "MGI": 26, "IBIO": 4, "PSL": 35, "EES": 20}
out = Path("evidence/msu-natsci.json")
out.parent.mkdir(exist_ok=True)
report = {"started": datetime.now(timezone.utc).isoformat(), "school": "msu",
          "collector_source": "573288d8c08cd2ba7deec508f2f71061bebd3328", "departments": {}}
stop = False
for name, org in departments.items():
    pages = []
    seen = set()
    unit = {"organization": org, "pages": pages}
    report["departments"][name] = unit
    for page in range(1, 9):
        url = f"https://directory.natsci.msu.edu/Directory/api/Directory/{org}?page={page}"
        entry = {"page": page}
        pages.append(entry)
        try:
            response = requests.get(url, headers=headers, timeout=25)
            entry.update(http=response.status_code, content_type=response.headers.get("Content-Type"))
            response.raise_for_status()
            payload = response.json()
            if payload.get("organizationId") != org or not isinstance(payload.get("results"), list):
                raise ValueError("unexpected public roster schema")
            ids = [row["id"] for row in payload["results"]]
            if not all(type(identity) is int and identity > 0 for identity in ids):
                raise ValueError("unusable campus identity")
            entry.update(rows=len(ids), stated_total=payload.get("resultCount"), stated_pages=payload.get("pageCount"))
            seen.update(ids)
            unit["distinct_person_ids"] = len(seen)
            if page >= payload["pageCount"]:
                unit["complete"] = len(seen) == payload["resultCount"]
                stop = not unit["complete"]
                break
        except (requests.RequestException, ValueError, TypeError, KeyError) as exc:
            entry["failure"] = type(exc).__name__
            unit["complete"] = False
            stop = True
            break
        time.sleep(0.4)
    print(name, json.dumps(unit), flush=True)
    if stop:
        break
report["finished"] = datetime.now(timezone.utc).isoformat()
report["all_eight_complete"] = len(report["departments"]) == len(departments) and all(
    unit.get("complete") for unit in report["departments"].values())
out.write_text(json.dumps(report, indent=2) + "\n")
