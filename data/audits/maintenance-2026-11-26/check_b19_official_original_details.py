"""Read the 17 released detail pages with a fresh student who can see the live draft action."""
import argparse
import json
import time
from datetime import UTC, datetime
from pathlib import Path

import requests
from playwright.sync_api import sync_playwright

from check_b19_original_details import ARCHIVES, CONTROL, CRISP, CUI, SMU, WISCONSIN, check
from check_b21_official_detail_routes import SITE, SCOPE, prepare_visitor


def health():
    answer = requests.get(SITE + "/api/health", timeout=55)
    answer.raise_for_status()
    return answer.json()["release_sha"]


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")


def before_release(page, oid, sha):
    response = requests.get(SITE + "/api/opportunities/" + oid, params={"_release_scope":SCOPE},timeout=50)
    response.raise_for_status()
    data = response.json()
    assert data["id"] == oid and data["target_truth"]["actionable"] is True
    rendered = page.goto(SITE+"/opportunities/"+oid,wait_until="domcontentloaded",timeout=90000)
    assert rendered and rendered.status == 200
    main = page.get_by_role("main")
    main.get_by_role("link",name="Back to matches",exact=True).wait_for(timeout=60000)
    assert page.locator("html").get_attribute("data-release-sha") == sha
    title = main.get_by_role("heading",level=1).inner_text()
    assert title == data["pi_name"]
    assert "This record is no longer active." not in main.inner_text()
    action = main.get_by_role("button",name="Draft email",exact=True)
    action.wait_for(state="visible",timeout=30000)
    return {"api_status":response.status_code, "browser_status":rendered.status, "heading":title,
            "old_reading_url":data.get("url"), "actionable":True, "draft_visible_to_same_visitor":True}


def main(sha, out, before=False):
    assert health() == sha
    report = {"started": datetime.now(UTC).isoformat(timespec="seconds"), "site": SITE,
              "verified_frontend_and_backend_sha": sha, "scope": "Student signs up anonymously through the normal site. The audit selects no external application, contact, or writing action.", "rows": []}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(locale="en-US", viewport={"width":1400,"height":960})
        context.add_cookies([{"name":"ofe_lang","value":"en","url":SITE}])
        visited = []
        def observe(req):
            if req.method not in {"GET","HEAD","OPTIONS"}:
                from urllib.parse import urlsplit
                path = urlsplit(req.url).path
                if any(x in path for x in ("cold-email", "renovate", "tailor", "/api/applications")):
                    visited.append(path)
        context.on("request",observe)
        try:
            prepare_visitor(context,context.new_page(),report)
        except Exception as err:
            report["visitor_setup_error"] = f"{type(err).__name__}: {str(err)[:300]}"
        write(out,report)
        # An active faculty page first confirms that this visitor sees the writing control.
        ids = ([CONTROL[0], *list(ARCHIVES)[:2]] if before else
               [*CONTROL[:1], *ARCHIVES, *CONTROL[1:], CUI, *WISCONSIN, *SMU, CRISP])
        report["phase"] = "B18-before" if before else "B19-after"
        for oid in ids:
            if report["rows"]:
                time.sleep(18)
            page = context.new_page()
            record = {"id":oid, "ok":False}
            try:
                record.update(before_release(page,oid,sha) if before else check(page,SITE,oid,sha,SCOPE))
                action = page.get_by_role("main").get_by_role("button",name="Draft email",exact=True)
                if oid in CONTROL and report.get("normal_visitor"):
                    action.wait_for(state="visible",timeout=25000)
                    record["active_draft_button_visible_to_same_visitor"] = True
                if not before and oid in ARCHIVES:
                    assert not action.is_visible()
                    record["archived_draft_button_absent_for_same_visitor"] = True
                record["ok"] = True
            except Exception as err:
                record["failure"] = f"{type(err).__name__}: {str(err)[:350]}"
                record["headings"] = page.locator("main h1, main h2").all_text_contents()[:15]
            finally:
                page.close()
            report["rows"].append(record)
            write(out,report)
            print(oid,record["ok"],flush=True)
        browser.close()
    report["observed_writing_requests"] = visited
    report["same_backend_at_end"] = health() == sha
    report["finished"] = datetime.now(UTC).isoformat(timespec="seconds")
    write(out,report)
    assert report.get("normal_visitor") and not visited and report["same_backend_at_end"]
    assert len(report["rows"]) == (3 if before else 17) and all(case["ok"] for case in report["rows"])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--sha",required=True)
    parser.add_argument("--out",required=True,type=Path)
    parser.add_argument("--before",action="store_true",help="Capture the three released B18 baseline pages")
    args = parser.parse_args()
    main(args.sha,args.out,args.before)
