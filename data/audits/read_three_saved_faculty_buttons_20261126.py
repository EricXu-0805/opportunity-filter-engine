"""Follow the public faculty controls and record the actual destination and university identity."""
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from urllib.parse import urlsplit, urlunsplit
from playwright.sync_api import TimeoutError as BrowserTimeout, sync_playwright

def clean(url):
    split = urlsplit(url)
    return urlunsplit((split.scheme, split.netloc, split.path, "", ""))

def capture(page, codes):
    try:
        page.wait_for_load_state("domcontentloaded", timeout=22000)
    except Exception:
        pass
    text = " ".join(page.locator("body").inner_text(timeout=5000).split())
    people = r"(?:Ali (?:Al ?Kinoon)|J\. Carr|Jennifer (?:Rose )?Carr|Tameca (?:Jewell|Beckett))"
    return {"published_url": clean(page.url), "navigation_statuses": codes[-6:], "title": page.title(),
            "headings": page.locator("h1,h2,h3").all_inner_texts()[:12],
            "named_line": [m.group(0) for m in re.finditer(r".{0,30}"+people+r".{0,85}",text,re.I)][:4]}

rows = [
    ("faculty-ucf-cs-edfc1c62", "https://www.cecs.ucf.edu/faculty/alialkinoon/"),
    ("faculty-ucsd-phil-a14e93b6", "https://pages.ucsd.edu/~j2carr/"),
    ("faculty-usf-info-e14bee11", "https://www.usf.edu/arts-sciences/departments/information/people/tameca-beckett.aspx"),
]
out={"started_at":datetime.now(timezone.utc).isoformat(),"records":[]}
with sync_playwright() as p:
    browser=p.chromium.launch(channel="chrome")
    context=browser.new_context()
    for orig,alternative in rows:
        entry={"id":orig}
        statuses=[]
        def observed(response):
            if response.request.resource_type == "document":
                statuses.append([clean(response.url), response.status])
        context.on("response",observed)
        page=context.new_page()
        try:
            response=page.goto("https://joinalab.com/opportunities/"+orig,wait_until="domcontentloaded",timeout=35000)
            entry.update(product_status=response.status,release=page.locator("html").get_attribute("data-release-sha"),
                person=page.locator("h1").first.inner_text(),product_url=page.url)
            dialog=page.get_by_role("dialog",name="Welcome to JoinALab")
            try:
                dialog.wait_for(state="visible",timeout=4000)
            except BrowserTimeout:
                pass
            else:
                dialog.get_by_role("button",name="Skip tour",exact=True).click()
                dialog.get_by_test_id("onboarding-school-uiuc").click()
                dialog.get_by_test_id("onboarding-primary").click()
                dialog.wait_for(state="hidden",timeout=30000)
                entry["ordinary_welcome_completed"]=True
            link=page.get_by_role("link",name="View faculty profile",exact=True).first
            entry["actual_button_target"]=link.get_attribute("href",timeout=10000)
            statuses.clear()
            try:
                with page.expect_popup(timeout=26000) as popup:
                    link.click(timeout=20000)
                entry["from_button"]=capture(popup.value,statuses)
            except Exception as exc:
                entry["button_error"]=str(exc)[:900]
                entry["button_response_history"]=list(statuses)
            statuses.clear()
            target=context.new_page()
            target.goto(alternative,wait_until="domcontentloaded",timeout=27000)
            entry["official_comparison"]=capture(target,statuses)
        except Exception as exc:
            entry["error"]=str(exc).splitlines()[0][:220]
        finally:
            context.remove_listener("response",observed)
            for tab in list(context.pages): tab.close()
        out["records"].append(entry)
    context.close()
    browser.close()
out["finished_at"]=datetime.now(timezone.utc).isoformat()
root=Path("evidence");root.mkdir(exist_ok=True)
(root/"three-saved-faculty-buttons.json").write_text(json.dumps(out,indent=2,ensure_ascii=False)+"\n")
print(json.dumps(out,ensure_ascii=False))
