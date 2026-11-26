"""Read two manually entered program records on production against their live source pages."""
import json
from playwright.sync_api import sync_playwright, expect
from verify_m25_results_20261126 import capture, enter_results, out, receipt, site

cases = [
    ("ext-cmu-reuse", "Carnegie Mellon REUSE", "https://www.cmu.edu/scs/s3d/reuse/", "criteria"),
    ("ext-umn-reu", "Computing for Social Good", "https://reu.cs.umn.edu/apply", "programming"),
]

with sync_playwright() as pw:
    browser = pw.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox", "--disable-dev-shm-usage"])
    ctx = browser.new_context(locale="en-US", service_workers="block", viewport={"width": 1250, "height": 950})
    ctx.add_init_script("if(location.hostname==='joinalab.com'){localStorage.setItem('ofe_onboarding_seen','1');localStorage.setItem('ofe_semantic_rerank_opt_in_v1','0');localStorage.setItem('ofe_lang','en');}")
    page = ctx.new_page()
    page.on("response", capture)
    page.set_default_timeout(40000)
    try:
        enter_results(page)
        for oid, query, source, qualifier in cases:
            entry = receipt[oid] = {"source": source}
            official = page.request.get(source)
            assert official.ok and qualifier in official.text().lower()
            entry["source_http"] = official.status
            api = page.request.get(site + "/api/opportunities/" + oid)
            assert api.ok
            detail = api.json()
            entry["target_truth"] = detail["target_truth"]
            entry["detail_skills"] = detail["eligibility"]["skills_required"]
            entry["rolling"] = detail.get("is_rolling")
            entry["deadline"] = detail.get("deadline")
            page.goto(site + "/opportunities/" + oid, wait_until="domcontentloaded")
            heading = page.get_by_role("heading", level=1)
            expect(heading).to_be_visible()
            entry["detail_title"] = heading.inner_text()
            entry["detail_excerpt"] = [s for s in page.locator("main").inner_text().splitlines() if any(k in s.lower() for k in ["python","c++","rolling","january 28","2027-01-28","basic programming","upcoming","closed"])]
            page.screenshot(path=out / (oid + "-detail.png"))
            from urllib.parse import quote
            page.goto(site + "/results?tab=all&ai=0&q=" + quote(query), wait_until="domcontentloaded")
            card = page.locator("#match-card-" + oid)
            if detail["target_truth"]["actionable"]:
                expect(card).to_be_visible(timeout=90000)
                card.get_by_role("button", name="Show details", exact=True).click()
                entry["card_text"] = card.inner_text()
                card.screenshot(path=out / (oid + "-card.png"), animations="disabled")
            else:
                expect(page.get_by_role("tablist")).to_be_visible(timeout=90000)
                expect(card).to_have_count(0)
    finally:
        (out / "m23.json").write_text(json.dumps(receipt, indent=2) + "\n")
        print(json.dumps(receipt), flush=True)
        browser.close()
