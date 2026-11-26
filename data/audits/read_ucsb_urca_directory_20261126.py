"""Read only the public UCSB list of projects seeking research assistants."""
import json
from datetime import datetime,timezone
from pathlib import Path
from playwright.sync_api import sync_playwright
url="https://ucsb.my.site.com/urca/s/urad"
with sync_playwright() as pw:
    b=pw.chromium.launch(channel="chrome")
    p=b.new_page()
    resp=p.goto(url,wait_until="domcontentloaded",timeout=40000)
    assert resp.ok and p.url==url
    p.get_by_text("faculty seeking research assistance",exact=False).wait_for(timeout=40000)
    table=p.get_by_role("table")
    table.get_by_role("row").nth(1).wait_for(timeout=40000)
    titles=table.get_by_role("row").evaluate_all("rows=>rows.map(r => r.querySelector('td')?.innerText.trim()).filter(Boolean)")
    assert len(titles)>0
    out=Path("evidence");out.mkdir(exist_ok=True)
    (out/"ucsb-recruitment-directory.json").write_text(json.dumps({
      "url":url,"observed_at":datetime.now(timezone.utc).isoformat(),"http":resp.status,"titles":titles,
    },indent=2,ensure_ascii=False)+"\n")
    print("Populated directory:",len(titles),"rows,",len(set(titles)),"distinct exact titles")
    b.close()
