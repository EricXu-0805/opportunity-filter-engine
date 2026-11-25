"""Read-only, one-request measurements for this diagnostic branch."""
import json
import re
from collections import Counter
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
URLS = {
    "wesleyan": "https://www.wesleyan.edu/about/directory/directory-loader.php?title=professor&type=faculty&searchtype=people",
    "njit": "https://cs.njit.edu/faculty",
    "ucsd": "https://math.ucsd.edu/people/faculty",
    "uf": "https://english.ufl.edu/faculty-listing/",
}


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def records(school):
    with (ROOT / "data" / "processed" / "shards" / f"{school}.json").open() as handle:
        rows = json.load(handle)
    return [r for r in rows if r.get("source") == f"{school}_faculty"
            and (r.get("metadata") or {}).get("is_active") is True]


def wesleyan(payload):
    data = json.loads(payload)
    if not isinstance(data, dict):
        return {"top_type": type(data).__name__}
    items = data.get("items")
    result = {"top_type": "dict", "items_type": type(items).__name__}
    if not isinstance(items, dict):
        return result
    groups = [g for g in items.values() if isinstance(g, list)]
    rows = [row for group in groups for row in group if isinstance(row, dict)]
    result.update(group_count=len(groups), record_count=len(rows))
    for key in ["id", "name", "positions", "email", "department_classes"]:
        result[key + "_types"] = dict(Counter(type(r.get(key)).__name__ for r in rows))
    for key in ["positions", "department_classes"]:
        entries = [x for r in rows if isinstance(r.get(key), list) for x in r[key]]
        result[key + "_entry_types"] = dict(Counter(type(x).__name__ for x in entries))
        permitted = {"id", "title", "name", "department", "dept", "department_name", "position",
                     "class", "value", "label", "type", "primary", "rank", "display", "display_name",
                     "sort", "job_title", "jobtitle", "position_title", "org", "org_name"}
        result[key + "_known_keys"] = sorted({k for x in entries if isinstance(x, dict) for k in x} & permitted)
    published = records("wesleyan")
    seeds = {parse_qs(urlsplit(r.get("url") or "").query).get("id", [""])[0]:
             str(r.get("pi_name") or "").strip().casefold() for r in published}
    result["stored_active"] = len(published)
    result["exact_id_overlaps"] = len({str(r.get("id")) for r in rows} & seeds.keys())
    result["matched_id_and_name"] = sum(1 for r in rows if str(r.get("id")) in seeds
                                        and str(r.get("name") or "").strip().casefold() == seeds[str(r["id"])])
    return result


def structure(tag):
    if not tag:
        return None
    return [tag.name, [c for c in tag.get("class", []) if re.fullmatch(r"[A-Za-z][\w-]{0,70}", c)]]


def context(anchor, levels):
    if anchor is None:
        return []
    output = []
    for _ in range(levels):
        if not anchor or anchor.name == "[document]":
            break
        children = [structure(c) for c in anchor.find_all(recursive=False, limit=14)]
        output.append([structure(anchor), children])
        anchor = anchor.parent
    return output


def html_report(school, payload):
    soup = BeautifulSoup(payload, "html.parser")
    if school == "njit":
        anchors = [a for a in soup.select("a[href*='people.njit.edu/profile/']") if a.get_text(strip=True)]
        names = ("a.column", "h1.name", "p.title")
        return {"counts": {s: len(soup.select(s)) for s in names}, "named_profile_anchors": len(anchors),
                "anchor_text_segments": dict(Counter(len(list(a.stripped_strings)) for a in anchors)),
                "first_anchor_and_parents": context(next(iter(anchors), None), 5)}
    if school == "ucsd":
        rows = soup.select("table tr:has(> td:nth-of-type(6))")
        cells = [r.find_all("td", recursive=False) for r in rows]
        item = next(iter(rows), None)
        fields = {"name", "first name", "last name", "office", "phone", "email", "e-mail", "research",
                  "research area", "research interests", "title", "position", "website", "profile", "department"}
        return {"rows": len(rows),
                "known_headers": [h.get_text(" ", strip=True).casefold() for h in soup.select("table th")
                                  if h.get_text(" ", strip=True).casefold() in fields],
                "table": structure(item.find_parent("table")) if item else None, "row": structure(item),
                "cells": [structure(c) for c in cells[0]] if cells else [],
                "name_cells": sum(bool(c[0].get_text(strip=True) and c[1].get_text(strip=True)) for c in cells),
                "first_cell_link": sum(bool(c[0].select_one("a[href]")) for c in cells),
                "cell4_plain_email": sum("@" in c[3].get_text(strip=True) for c in cells),
                "cell4_mailto": sum(bool(c[3].select_one("a[href^='mailto:']")) for c in cells),
                "sixth_cell_title": sum(bool(c[5].get_text(strip=True)) for c in cells)}
    sels = [".card.news-card", ".faculty-listing-item", ".individual-team-member-container",
            ".faculty-listing-bio p:first-child", ".faculty-listing-bio p:nth-of-type(2)",
            ".archive-team-member-name", ".archive-team-member-position"]
    bio = [a for a in soup.select("a[href]") if a.get_text(" ", strip=True).casefold() == "see bio"]
    listed_urls = {urljoin(URLS["uf"], a["href"]).rstrip("/") for a in bio}
    previous = {r["url"].rstrip("/") for r in records("uf") if r.get("url")
                and "english.ufl.edu/" in r["url"] and r["url"] != URLS["uf"]}
    return {"counts": {s: len(soup.select(s)) for s in sels}, "see_bio": len(bio),
            "prior_unique_urls": len(previous), "prior_urls_among_bios": len(previous & listed_urls),
            "first_bio_and_parents": context(next(iter(bio), None), 6)}


if __name__ == "__main__":
    opener = build_opener(NoRedirect())
    for school, url in URLS.items():
        try:
            request = Request(url, headers={"User-Agent": "opportunity-filter-engine/public-roster-diagnostic"})
            with opener.open(request, timeout=14) as response:
                payload = response.read(4_000_001)
                if len(payload) > 4_000_000:
                    print(school, response.status, "body above cap")
                    continue
                result = wesleyan(payload) if school == "wesleyan" else html_report(school, payload)
                print(school, response.status, len(payload), json.dumps(result, ensure_ascii=True))
        except HTTPError as exc:
            print(school, "http", exc.code)
        except (URLError, TimeoutError, OSError, ValueError, KeyError, TypeError) as exc:
            print(school, "unavailable", type(exc).__name__)
