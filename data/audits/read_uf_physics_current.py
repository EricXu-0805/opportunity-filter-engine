"""Compare UF's two public directory entry points and the published originals."""
from __future__ import annotations

import hashlib
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from urllib.parse import urljoin, urlsplit

import requests
from bs4 import BeautifulSoup

from src.collectors import faculty_graph, ucb_common
from src.collectors.schools.uf_faculty import SCHOOL

CURRENT = "https://phys.ufl.edu/people/faculty/"
OLD = "https://www.phys.ufl.edu/wp/index.php/people/faculty/"


def fetch(url):
    try:
        r = requests.get(url, headers=ucb_common.HEADERS, timeout=22)
        soup = BeautifulSoup(r.content, "html.parser")
        return ({"requested": url, "landed": r.url, "status": r.status_code,
                 "redirects": [[i.status_code, i.url] for i in r.history],
                 "sha256": hashlib.sha256(r.content).hexdigest(),
                 "headings": [h.get_text(" ", strip=True) for h in soup.select("main h1, article h1")][:3]},
                soup)
    except requests.RequestException as e:
        return {"requested": url, "error": type(e).__name__}, None


def cards(soup):
    out = []
    for card in soup.select("main article.ufclas-team-grid__item"):
        h = card.select_one("h3.ufclas-team-grid__name")
        rank = card.select_one(".ufclas-team-grid__position")
        lt = card.select_one(".ufclas-team-grid__bio a[href]")
        hdr = card.find_previous("h2")
        dst = urljoin(CURRENT, lt["href"]) if lt else None
        out.append({"name": h.get_text(" ", strip=True) if h else None,
                    "rank": rank.get_text(" ", strip=True) if rank else None,
                    "directory_section": hdr.get_text(" ", strip=True) if hdr else None,
                    "profile": dst})
    return out


def check_person(url):
    t, soup=fetch(url)
    if soup and t.get("status")==200:
        title=soup.select("main [class*='position'], main [class*='job-title'], main [class*='faculty-title']")
        t["title_fields"]=[n.get_text(" ",strip=True) for n in title if 0<len(n.get_text(" ",strip=True))<=140][:3]
    time.sleep(0.35)
    return [url,t]


def main():
    dept=next(d for d in SCHOOL["departments"] if d["short"]=="PHY")
    a,old=fetch(OLD);b,live=fetch(CURRENT)
    assert old and live and a["status"]==b["status"]==200
    roster=cards(live);assert roster and cards(old)==roster
    original=[r for r in json.loads(Path("data/processed/shards/uf.json").read_bytes()) if r["id"].startswith("faculty-uf-phy-")]
    ranks=dept["scrape"]["ladder_filter"]
    for i in roster:i["passes_title_gate"]=faculty_graph._passes_ladder(i["rank"] or "",ranks)
    wanted={i["profile"] for i in roster if i["passes_title_gate"] and i["profile"]}
    wanted.update(r["url"].strip() for r in original if r["url"].strip() not in {CURRENT,OLD})
    wanted={s for s in wanted if urlsplit(s).netloc=="phys.ufl.edu"}
    with ThreadPoolExecutor(max_workers=3) as pool: sites=dict(pool.map(check_person,sorted(wanted)))
    result={"timestamp":datetime.now(UTC).isoformat(timespec="seconds"),"legacy":a,"current":b,
            "old_and_new_return_same_ordered_cards":True,"old_table_rows":len(live.select("table tr")),
            "cards":roster,"originals":[{"id":r["id"],"name":r["pi_name"],"old_profile":r["url"],
                "previous_title":r["metadata"]["faculty_title"],"active":r["metadata"].get("is_active")}
                for r in original],"profiles":sites}
    Path("../uf-physics-evidence.json").write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
    print(len(roster), "cards;",sum(i["passes_title_gate"] for i in roster),"passes by title;",len(sites),"public destinations.")
if __name__=="__main__":main()
