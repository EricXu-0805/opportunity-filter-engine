"""Read production results through the form and collect the released type controls."""
import json
import re
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright, expect

site = "https://joinalab.com"
out = Path("evidence")
out.mkdir(exist_ok=True)
receipt = {"site": site, "guest_signup": None, "profile_commit": None}

def capture(response):
    if response.request.method == "POST":
        path = urlsplit(response.url).path
        if path.endswith("/auth/v1/signup"):
            receipt["guest_signup"] = response.status
        if path.endswith("/rpc/commit_profile_patch_cas"):
            receipt["profile_commit"] = response.status

def read_page(response, kind):
    assert response.ok, response.status
    data = response.json()
    assert data["applied_opportunity_type"] == kind
    assert not data["ai_refined"]
    ids = []
    for row in data["results"]:
        raw = row["opportunity"]["opportunity_type"]
        assert raw.strip().lower().replace(" ", "_") == kind, raw
        ids.append(row["opportunity_id"])
    return {"total": data["filtered_total"], "counts": data["view_counts"], "ids": ids,
            "next_page": bool(data["next_cursor"]), "view_id": data["view_id"]}

def is_view(response):
    return urlsplit(response.url).path == "/api/matches/view" and response.request.method == "POST"

def run(page):
    page.goto(site, wait_until="domcontentloaded")
    page.locator("#student_name").wait_for(timeout=60000)
    for _ in range(100):
        page.wait_for_timeout(250)
        if receipt["guest_signup"] == 200 and not page.get_by_test_id("hydration-note").is_visible() and not page.get_by_test_id("profile-refresh-status").is_visible():
            break
    assert receipt["guest_signup"] == 200
    campus = page.get_by_test_id("university-card-ucb")
    if not campus.is_visible():
        change = page.get_by_role("button", name="Change", exact=True)
        change.click()
        page.wait_for_timeout(500)
        if not campus.is_visible():
            change.click()
    campus.click()
    page.get_by_test_id("switcher-confirm").click()
    page.locator("#student_name").fill("Sample Student")
    for selector, value in (("#college", "College of Computing, Data Science, and Society"), ("#major", "Computer Science")):
        field = page.locator(selector)
        if field.evaluate("e=>e.tagName") == "SELECT":
            field.select_option(label=value)
        else:
            field.fill(value)
    page.locator("#grade").select_option(label="Junior")
    page.locator("#research_interests").fill("machine learning, artificial intelligence, healthcare")
    generate = page.get_by_test_id("generate-matches")
    expect(generate).to_be_enabled(timeout=45000)
    generate.click()
    for _ in range(25):
        page.wait_for_timeout(250)
        if urlsplit(page.url).path.startswith("/results"):
            break
    if urlsplit(page.url).path == "/" and generate.is_enabled():
        generate.click()
    page.wait_for_url(re.compile("/results"), timeout=55000)
    cards = page.locator("[id^=match-card-]")
    cards.first.wait_for(timeout=90000)
    assert receipt["profile_commit"] == 200
    if page.get_by_test_id("switcher-confirm").is_visible():
        page.keyboard.press("Escape")
    all_tab = page.get_by_role("tab", name=re.compile("^All"))
    if all_tab.get_attribute("aria-selected") != "true":
        all_tab.click()
        expect(all_tab).to_have_attribute("aria-selected", "true")
    chips = page.locator("#filter-rail-chips")
    expect(chips).to_be_visible()
    receipt["available_filters"] = chips.locator("select").evaluate_all("xs=>xs.map(x=>x.getAttribute('aria-label'))")
    chips.screenshot(path=out / "filter-rail.png")
    kind = chips.get_by_role("combobox", name="Opportunity type", exact=True)
    receipt["has_type_filter"] = kind.count() == 1
    if kind.count():
        receipt["options"] = kind.locator("option").evaluate_all("xs=>xs.map(x=>x.value)")
        for val in ("research", "summer_program", "internship"):
            with page.expect_response(lambda r: is_view(r) and (r.request.post_data_json or {}).get("view", {}).get("opportunity_type") == val, timeout=90000) as req:
                kind.select_option(value=val)
            first = read_page(req.value, val)
            receipt[val] = {"first": first}
            expect(kind).to_have_value(val)
            if first["ids"]:
                expect(page.locator("#match-card-" + first["ids"][0])).to_be_visible(timeout=50000)
            if val == "research" and first["next_page"]:
                more = page.get_by_role("button", name=re.compile("Show more|Load more", re.I))
                with page.expect_response(lambda r: is_view(r) and bool((r.request.post_data_json or {}).get("cursor")), timeout=90000) as next_req:
                    more.click()
                second = read_page(next_req.value, val)
                assert not set(first["ids"]).intersection(second["ids"])
                assert first["view_id"] == second["view_id"] and first["total"] == second["total"]
                receipt[val]["second"] = second
        chips.screenshot(path=out / "filtered-internships.png")
    oid = "nsf-reu-2548403"
    page.goto(site + "/opportunities/" + oid, wait_until="domcontentloaded")
    marker = page.get_by_text("Estimated by us", exact=True).first
    expect(marker).to_be_visible(timeout=45000)
    receipt["estimated_deadline"] = {"id": oid, "url": page.url, "displayed": marker.locator("..").inner_text()}
    marker.locator("..").screenshot(path=out / "estimated-date.png")

with sync_playwright() as pw:
    browser = pw.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox", "--disable-dev-shm-usage"])
    ctx = browser.new_context(locale="en-US", service_workers="block", viewport={"width": 1250, "height": 950})
    ctx.add_init_script("if(location.hostname==='joinalab.com'){localStorage.setItem('ofe_onboarding_seen','1');localStorage.setItem('ofe_semantic_rerank_opt_in_v1','0');localStorage.setItem('ofe_lang','en');}")
    page = ctx.new_page()
    page.on("response", capture)
    page.set_default_timeout(45000)
    try:
        run(page)
    finally:
        (out / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        print(json.dumps(receipt), flush=True)
        browser.close()
