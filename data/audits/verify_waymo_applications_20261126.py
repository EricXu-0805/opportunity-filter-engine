"""Inspect the public employer requisition links without applying."""
import json
from datetime import datetime, timezone
from pathlib import Path
from playwright.sync_api import sync_playwright
CASES = {'simplify-intern-555a5129-471f-4c93-8e7b-aa4a1996fa61': ['2027 Summer Intern, PhD, Safety Research, Human Behavior Analytics', 'https://careers.withwaymo.com/jobs?gh_jid=8197899'], 'simplify-intern-3f32b0ed-b696-49d8-9b5c-ea946e53c009': ['2027 Summer Intern, MS/PhD, Conflict Behavior', 'https://careers.withwaymo.com/jobs?gh_jid=8210138'], 'simplify-intern-c87514d0-01b1-4240-8fcd-9e9a605d96e1': ['2027 Summer Intern, MBA, Salesforce Product Owner', 'https://careers.withwaymo.com/jobs?gh_jid=8198582'], 'simplify-intern-a9d476c2-4d74-43de-9305-8e0c1bc59841': ['2027 Summer Intern, BS/MS/PhD, Software Engineer, Eval Data Infra', 'https://careers.withwaymo.com/jobs?gh_jid=8257205'], 'simplify-intern-fc6751c5-e093-4970-8fe5-90af5713b9e4': ['2027 Summer Intern, PhD, Research, World Modeling Evaluation', 'https://careers.withwaymo.com/jobs?gh_jid=8265173'], 'simplify-intern-e13a771d-0bef-4eba-8e4c-922902e13085': ['2027 Summer Intern, BS/MS, Software Engineer, Multiverse', 'https://careers.withwaymo.com/jobs?gh_jid=8350832']}
SITE = "https://joinalab.com"
report = {"observed_utc":datetime.now(timezone.utc).isoformat(),"cases":[]}
out=Path("evidence")
out.mkdir(exist_ok=True)
with sync_playwright() as pw:
    browser=pw.chromium.launch(channel="chrome")
    page=browser.new_page(locale="en-US")
    report["backend"]=page.request.get(SITE+"/api/health").json()["release_sha"]
    for oid,(title,url) in CASES.items():
        response=page.goto(SITE+"/opportunities/"+oid,wait_until="domcontentloaded",timeout=60000)
        heading=page.get_by_role("heading",level=1).first
        first=heading.inner_text(timeout=45000)
        retried=False
        if first=="This opportunity is temporarily unavailable":
            retried=True
            page.get_by_role("button",name="Retry",exact=True).click()
            try:
                page.get_by_role("heading",name=title,exact=True).wait_for(timeout=28000)
            except Exception:
                pass
        final=heading.inner_text(timeout=15000)
        links=page.get_by_role("link",name="Apply now",exact=True)
        dest=[ln.get_attribute("href") for ln in links.all()]
        report["cases"].append({"id":oid,"response":response.status,"release":page.locator("html").get_attribute("data-release-sha"),"first":first,"retried":retried,"final":final,"hrefs":dest,"expected_employer_link":url,"matched":final==title and dest==[url]})
        (out/"receipt.json").write_text(json.dumps(report,indent=2)+"\n")
        print(oid,report["cases"][-1]["matched"],retried,flush=True)
    browser.close()
assert all(row["matched"] for row in report["cases"])
