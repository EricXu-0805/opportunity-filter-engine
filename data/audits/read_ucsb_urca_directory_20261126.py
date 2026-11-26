"""Read only the public UCSB list of projects seeking research assistants."""
import json
import re
import hashlib
import unicodedata
from datetime import datetime,timezone
from pathlib import Path
from playwright.sync_api import sync_playwright
URLS = ['https://ucsb.my.site.com/urca/s/funding-program/a0W4X00000eIcF7UAK/morphological-variation-in-a-threatened-amphibian', 'https://ucsb.my.site.com/urca/s/funding-program/a0W4X00000eIcFRUA0/morphological-variation-in-a-threatened-amphibian', 'https://ucsb.my.site.com/urca/s/funding-program/a0W4X00000eIcGBUA0/lifeways-at-fortress-taroy-from-egyptian-colony-to-a-postcolonial-era-in-ancie', 'https://ucsb.my.site.com/urca/s/funding-program/a0W4X00000eIcGFUA0/costeffective-hydrogen-production-without-co2-from-hydrocarbon-resources', 'https://ucsb.my.site.com/urca/s/funding-program/a0W4X00000eIcGPUA0/costeffective-hydrogen-production-without-co2-from-hydrocarbon-resources', 'https://ucsb.my.site.com/urca/s/funding-program/a0W4X00000eIcH0UAK/english-broadside-ballad-archive-ebba', 'https://ucsb.my.site.com/urca/s/funding-program/a0W4X00000eIcH1UAK/english-broadside-ballad-archive-ebba', 'https://ucsb.my.site.com/urca/s/funding-program/a0W4X00000eIcHDUA0/learn-to-read-colonial-latin-american-manuscripts-our-paleography-reading-group', 'https://ucsb.my.site.com/urca/s/funding-program/a0W4X00000eIcHvUAK/is-adoption-an-option-law-and-religion-in-alternative-family-formation-in-the-u', 'https://ucsb.my.site.com/urca/s/funding-program/a0W4X00000gOVmPUAW/the-historical-memory-of-indigenous-migrant-communities-in-the-us-and-mexico', 'https://ucsb.my.site.com/urca/s/funding-program/a0WHt00000Fl6yWMAR/fruit-in-a-cage-developmental-of-the-calyx-in-monkeyflowers', 'https://ucsb.my.site.com/urca/s/funding-program/a0WHt00000HBwJyMAL/fruit-in-a-cage-developmental-of-the-caylx-in-monkeyflowers', 'https://ucsb.my.site.com/urca/s/funding-program/a0WVt000007ZH1xMAG/scientific-writer-and-data-scientst-for-the-tau-consortium-bioinformatics-hub', 'https://ucsb.my.site.com/urca/s/funding-program/a0WVt000009bn7pMAA/fruit-in-a-cage-developmental-of-the-calyx-in-monkeyflowers']

def digest(text):
    return hashlib.sha256(" ".join(unicodedata.normalize("NFKC",text).split()).encode()).hexdigest()

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
    directory_cells=table.get_by_role("row").evaluate_all("rows=>rows.map(r=>Array.from(r.querySelectorAll('td')).map(c=>c.innerText.trim())).filter(c=>c.length>=2)")
    projects=[{"title":c[0],"description_digest":digest(c[1]),"tags":c[2] if len(c)>2 else ""} for c in directory_cells]
    matched_details={}
    for address in URLS:
        pg=b.new_page()
        try:
            res=pg.goto(address,wait_until="domcontentloaded",timeout=20000)
            if not res or not res.ok: continue
            main=pg.get_by_role("main")
            main.get_by_role("heading",level=1).wait_for(timeout=16000)
            main.get_by_text("Undergraduate Contribution",exact=True).first.wait_for(timeout=6000)
            txt=main.inner_text()
            found=re.search(r"(?:^|\n)Description\s*\n(.*?)\nUndergraduate Contribution(?:\n|$)",txt,re.S)
            title_field=re.search(r"(?:^|\n)Project Title\s*\n(.*?)\nFaculty Contact(?:\n|$)",txt,re.S)
            tags_field=re.search(r"(?:^|\n)Program Tags\s*\n(.*?)\nWebsite(?:\n|$)",txt,re.S)
            title=title_field[1].strip() if title_field else main.get_by_role("heading",level=1).inner_text().strip()
            matched_details[address.split("/")[-2]]={"title":title,"tags":tags_field[1].strip() if tags_field else "",
            "description_digest":digest(found[1]) if found and found[1].strip() else None}
        except Exception as e:
            print("detail unavailable",address,type(e).__name__)
        finally:
            pg.close()
    out=Path("evidence");out.mkdir(exist_ok=True)
    (out/"ucsb-recruitment-directory.json").write_text(json.dumps({
      "url":url,"observed_at":datetime.now(timezone.utc).isoformat(),"http":resp.status,"titles":titles,"directory":projects,"details":matched_details,
    },indent=2,ensure_ascii=False)+"\n")
    print("Populated directory:",len(titles),"rows,",len(set(titles)),"distinct exact titles")
    b.close()
