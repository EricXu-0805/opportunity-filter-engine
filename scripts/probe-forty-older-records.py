"""One read per distinct listed URL, with exact sample IDs from the 2026-11-16 audit."""
import json
import re
import unicodedata
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from time import sleep
from pathlib import Path
from urllib.error import HTTPError
from urllib.parse import urldefrag, urlsplit
from urllib.request import Request, urlopen
from bs4 import BeautifulSoup

IDS = ["faculty-arizona-nurs-b9364e42","faculty-asu-sols-c29d8618","faculty-asu-sgsup-87ffc60e","faculty-emory-eng-569ded69","faculty-gatech-ece-04da7aa5","faculty-georgetown-mcct-07167550","faculty-indiana-mus-2f6c0b97","faculty-jhu-hart-1b59ac9e","faculty-jhu-eps-3e4b4ab0","faculty-jhu-soc-42e069df","faculty-jhu-pols-a9657c20","faculty-jhu-phys-03dc439e","faculty-jhu-engl-f9b35153","faculty-jhu-sais-3b5f452a","faculty-jhu-mll-48660952","faculty-jhu-phys-46cdcddc","faculty-jhu-hart-9678d844","faculty-jhu-phil-8f22c08b","faculty-oregonstate-cla-5932c611","faculty-oregonstate-cla-0274fa42","faculty-osu-fabe-1abc04a0","faculty-psu-econ-adbbad93","faculty-purdue-math-754ee250","faculty-sbu-cs-7c922688","faculty-sbu-bus-5f5c2e91","faculty-sbu-cs-890dcd54","faculty-tamu-mays-070f9c11","faculty-tamu-inta-c32e8252","faculty-tamu-mays-918c38e2","faculty-tamu-pvfa-84ed8e95","faculty-ucb-cdss-cbe1719c","faculty-ucsd-chem-53a6cbdc","faculty-umd-phys-5e8e0edd","faculty-umd-math-1516d149","faculty-unl-cyaf-eb152ded","faculty-unl-bse-bd974de0","faculty-upenn-asc-68512d0f","faculty-upenn-asc-753320f0","faculty-vanderbilt-engl-582d776a","faculty-wisc-cs-7de28aa7"]
def words(value):
    return re.findall(r"[a-z0-9]+", unicodedata.normalize("NFKD", value).encode("ascii","ignore").decode().lower())

def read(url):
    try:
        with urlopen(Request(url, headers={"User-Agent":"opportunity-filter-engine/official-faculty-check"}), timeout=12) as response:
            soup = BeautifulSoup(response.read(3_000_000), "html.parser")
            for tag in soup.find_all(["script","style"]):
                tag.decompose()
            return response.status, response.url, " ".join(words(soup.get_text(" ", strip=True))), [t.get_text(" ",strip=True)[:180] for t in soup.select("h1, title")[:6]]
    except HTTPError as exc:
        return exc.code, exc.url, "", []
    except (TimeoutError, OSError, ValueError) as exc:
        return type(exc).__name__, url, "", []

rows = {}
for shard in sorted(Path("data/processed/shards").glob("*.json")):
    for row in json.loads(shard.read_text()):
        if row["id"] in IDS: rows[row["id"]] = row
urls = sorted({urldefrag(r["url"])[0] for r in rows.values()})
by_host = defaultdict(list)
for url in urls:
    by_host[urlsplit(url).hostname].append(url)
def inspect_host(group):
    found = {}
    limited = False
    for url in group:
        if limited:
            found[url] = ("deferred_throttle", url, "", [])
            continue
        found[url] = read(url)
        limited = found[url][0] == 429
        sleep(0.4)
    return found
with ThreadPoolExecutor(max_workers=4) as workers:
    pages = {url: result for group in workers.map(inspect_host, by_host.values()) for url, result in group.items()}
for oid in IDS:
    if oid not in rows:
        print(oid, "missing", flush=True)
        continue
    row = rows[oid]
    url = urldefrag(row["url"])[0]
    code, final_url, text, headings = pages[url]
    name = words(row.get("pi_name") or "")
    first_last = bool(len(name) > 1 and re.search(r"\b" + re.escape(name[0]) + r"(?: [\w]+){0,3} " + re.escape(name[-1]) + r"\b", text))
    md = row.get("metadata") or {}
    print(oid, json.dumps({"active":md.get("is_active"),"last":str(md.get("last_seen_at") or "")[:10],"http":code,"final_host":urlsplit(final_url).hostname,"redirected":final_url!=url,"name":first_last,"heading":any(first_last and name[-1] in words(h) for h in headings)}),flush=True)
