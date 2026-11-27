"""Read only the named saved UT/Columbia pages, university sources and public mathematics directory."""
import concurrent.futures
import datetime
import hashlib
import json
import os
import re
from pathlib import Path

from bs4 import BeautifulSoup
import requests
from playwright.sync_api import sync_playwright

from src.collectors.schools.utexas_faculty import SCHOOL

DEST = Path(os.environ.get("UT_MATH_RECEIPT", "/tmp/ut-math-originals.json"))
SITE = "https://joinalab.com"
SCOPE = "mvp-core-close-v1-contact-trust-v1-faculty-trust-v1-target-truth-v2"
IDS = ["faculty-utexas-math-245fa784", "faculty-utexas-math-3483c4f5", "faculty-columbia-math-245fa784"]
URLS = {
    "UT former official profile": ("https://math.utexas.edu/directory/lucas-mason-brown", []),
    "Lucas personal": ("https://lucasmasonbrown.com/", ["Previously, I was an assistant professor at UT Austin.", "at Columbia University"]),
    "Columbia directory": ("https://www.math.columbia.edu/people/faculty-by-rank/name/lucas-mason-brown/", ["Lucas Mason-Brown", "Assistant Professor"]),
    "Columbia bulletin": ("https://bulletin.columbia.edu/columbia-college/departments-instruction/mathematics/", ["Lucas Mason-Brown", "Assistant Professors"]),
    "Columbia February colloquium": ("https://www.math.columbia.edu/2026/01/17/feb-2nd-colloquium-lucas-mason-brown-texas/", ["Lucas Mason-Brown (Texas)", "February"]),
    "UT Mathematics Uri": ("https://math.utexas.edu/directory/uri-treisman", ["Professor Emeritus","Special Advisor to the Dean","Distinguished Teaching Professor"]),
    "UT Public Affairs Uri": ("https://lbj.utexas.edu/treisman-philip-uri", ["Professor of Public Affairs", "Director"]),
    "UT Dana Center Uri": ("https://www.utdanacenter.org/who-we-are/meet-our-staff/uri-treisman", ["Founder", "June 2023"]),
    "UT Mathematics directory": ("https://math.utexas.edu/directory", ["Directory"]),
}
def now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()
def page(pair):
    key,(url,words)=pair
    try:
        r=requests.get(url,timeout=32)
        s=BeautifulSoup(r.content,"html.parser")
        val=" ".join(s.stripped_strings)
        result={"url":url,"final":r.url,"http":r.status_code,"h1":[t.get_text(" ",strip=True) for t in s.select("h1")][:4],
                "found":{w:w.casefold() in val.casefold() for w in words},"utc":now()}
        if key=="Columbia bulletin":
            item=next((v for v in s.find_all("li") if v.get_text(" ",strip=True)=="Lucas Mason-Brown"),None)
            result["listing_heading"]=item.find_previous(["h2","h3","h4","strong"]).get_text(" ",strip=True) if item else None
        return key,result
    except requests.RequestException as e:
        return key,{"url":url,"error":type(e).__name__,"utc":now()}
def directory():
    dept=next(d for d in SCHOOL["departments"] if d["short"]=="MATH")
    cfg=dept["algolia"]; url=f"https://{cfg['app_id'].lower()}-dsn.algolia.net/1/indexes/{cfg['index']}/query"
    headers={"X-Algolia-Application-Id":cfg["app_id"],"X-Algolia-API-Key":cfg["api_key"]}
    result={}
    for query,filter_ in [("",cfg["filters"]),("Treisman",'department:"Mathematics"'),("Mason-Brown",'department:"Mathematics"')]:
        r=requests.post(url,headers=headers,json={"query":query,"hitsPerPage":1000,"filters":filter_},timeout=35)
        r.raise_for_status(); payload=r.json();hits=payload["hits"]
        assert len(hits)==payload["nbHits"]
        names=[" ".join(str(x.get(f,"")).strip() for f in ("name_first","name_last")).strip() for x in hits]
        key=query or "full_tenure_track";rows=[]
        for x,n in zip(hits,names):
            if "treisman" in n.lower() or "mason-brown" in n.lower():
                rows.append({"name":n,**{k:x[k] for k in ("title","titles","titles_general","titles_professional","professional_title","primary_title","position_type","department","url","url_alias","profile_url","profile_link") if k in x}})
                rows[-1]["source_field_names"]=[k for k in x if "title" in k or "position" in k]
        result[key]={"filter":filter_,"query":query,"http":r.status_code,"count":len(hits),"matching":rows,
                     "name_set_sha256":hashlib.sha256(json.dumps(sorted(names),ensure_ascii=False).encode()).hexdigest(),"utc":now()}
    return result
def public_api(oid):
    r=requests.get(SITE+"/api/opportunities/"+oid,params={"_release_scope":SCOPE},timeout=40)
    b=r.json();truth=b.get("target_truth") or {}
    return oid,{"http":r.status_code,"id":b.get("id"),"name":b.get("pi_name"),"rank":b.get("faculty_title"),
                "url":b.get("url"),"actionable":truth.get("actionable"),"reason":truth.get("reason"),
                "contact_state":b.get("contact_email_status"),"utc":now()}
def read_release():
    r=requests.get(SITE+"/about",timeout=35); front=re.search(r'data-release-sha="([a-f0-9]{40})"',r.text).group(1)
    back=requests.get(SITE+"/api/health",timeout=35).json()["release_sha"]
    return {"frontend":front,"backend":back,"utc":now()}
def public_ui():
    with sync_playwright() as pw:
        browser=pw.chromium.launch(channel="chrome",args=["--no-sandbox"])
        ctx=browser.new_context(locale="en-US", service_workers="block")
        ctx.add_cookies([{"name":"ofe_lang","value":"en","url":SITE}])
        ctx.add_init_script("""localStorage.setItem('ofe_lang','en');localStorage.setItem('ofe_onboarding_seen','1');localStorage.setItem('ofe_school_confirmed',JSON.stringify({slug:'utexas',ts:new Date().toISOString()}))""")
        results={}
        for oid in IDS:
            p=ctx.new_page();r=p.goto(SITE+"/opportunities/"+oid,wait_until="domcontentloaded"); name="Uri Treisman" if oid.endswith("3483c4f5") else "Lucas Mason-Brown"
            p.get_by_text(re.compile(re.escape(name))).first.wait_for(timeout=60000)
            # Detail is hydrated independently of the SSR shell. Wait for either an ordinary current action or the history banner.
            draft=p.get_by_role("button",name="Draft email",exact=True)
            inactive=p.get_by_text(re.compile("inactive|no longer|historical record",re.I))
            draft.or_(inactive).first.wait_for(timeout=60000)
            results[oid]={"http":r.status,"name_visible":True,"draft_visible":draft.is_visible(),"utc":now()}
            p.close()
        browser.close();return results
def main():
    result={"original_ids":IDS,"started_at":now()}
    try:
        result["release_start"]=read_release()
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            result["sources"]=dict(pool.map(page,URLS.items()))
        result["directory"]=directory()
        result["official_detail_api"]=dict(map(public_api,IDS))
        result["official_detail_ui"]=public_ui()
        result["release_end"]=read_release()
        assert result["release_start"]["frontend"]==result["release_start"]["backend"]==result["release_end"]["frontend"]==result["release_end"]["backend"]
        result["complete"]=True
    finally:
        result["finished_at"]=now();DEST.write_text(json.dumps(result,ensure_ascii=False,indent=2)+"\n")
if __name__=="__main__":main()
