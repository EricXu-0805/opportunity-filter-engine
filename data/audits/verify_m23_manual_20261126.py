"""Read the Caltech office index and the two separate SURF application calendars on production against their live source pages."""
import json
import re
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright, expect
from verify_m25_results_20261126 import capture, enter_results, is_view, out, receipt, site

cases = [
    ("caltech-5ca171e19766","Student-Faculty Programs", "https://sfp.caltech.edu/undergraduate-research/programs","off-campus surf"),
    ("caltech-a56b5e0f17fa","Off-Campus SURF","https://sfp.caltech.edu/undergraduate-research/programs/off-campus-surf","standard surf application"),
    ("caltech-d8e1ba2c4a90","University of Iceland","https://sfp.caltech.edu/undergraduate-research/programs/exchange_programs","march 1, 2027"),
]

def caltech_student(page, school="caltech"):
    page.goto(site, wait_until="domcontentloaded")
    page.locator("#student_name").wait_for(timeout=60000)
    for _ in range(100):
        page.wait_for_timeout(250)
        if receipt["guest_signup"] == 200 and not page.get_by_test_id("hydration-note").is_visible() and not page.get_by_test_id("profile-refresh-status").is_visible():
            break
    assert receipt["guest_signup"] == 200
    campus = page.get_by_test_id("university-card-" + school)
    if not campus.is_visible():
        change = page.get_by_role("button", name="Change", exact=True)
        change.click()
        page.wait_for_timeout(500)
        if not campus.is_visible():
            change.click()
    campus.click()
    page.get_by_test_id("switcher-confirm").click()
    page.locator("#student_name").fill("Sample Student")
    college = "Division of Engineering and Applied Science"
    for selector, value in (("#college", college), ("#major", "Computer Science")):
        field = page.locator("select" + selector)
        expect(field).to_be_enabled(timeout=45000)
        field.select_option(value=value)
        expect(field).to_have_value(value)
    page.locator("#grade").select_option(label="Junior")
    interests = "database systems, computer science, summer research" if school == "uiuc" else "machine learning, artificial intelligence, healthcare"
    page.locator("#research_interests").fill(interests)
    for label in ("Research", "Summer program", "Internship"):
        target = page.locator('fieldset[aria-describedby="seeking-types-help"]').get_by_role("button", name=label, exact=True)
        if target.get_attribute("aria-pressed") != "true":
            target.click()
    generate = page.get_by_test_id("generate-matches")
    try:
        expect(generate).to_be_enabled(timeout=45000)
    except AssertionError:
        receipt["validation"] = page.locator("#match-validation, #profile-save-status").all_inner_texts()
        receipt["selected"] = {id: page.locator("#"+id).input_value() for id in ["college", "major", "grade", "research_interests"]}
        page.screenshot(path=out/"caltech-form.png")
        raise
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

with sync_playwright() as pw:
    browser = pw.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox", "--disable-dev-shm-usage"])
    ctx = browser.new_context(locale="en-US", service_workers="block", viewport={"width": 1250, "height": 950})
    ctx.add_init_script("if(location.hostname==='joinalab.com'){localStorage.setItem('ofe_onboarding_seen','1');localStorage.setItem('ofe_semantic_rerank_opt_in_v1','0');localStorage.setItem('ofe_lang','en');}")
    page = ctx.new_page()
    page.on("response", capture)
    page.set_default_timeout(40000)
    try:
        caltech_student(page)
        for oid, query, source, qualifier in cases:
            entry = receipt[oid] = {"source": source}
            official = page.request.get(source)
            assert official.ok and qualifier in official.text().lower()
            entry["source_http"] = official.status
            api = page.request.get(site + "/api/opportunities/" + oid, params={"_release_scope": "mvp-core-close-v1-contact-trust-v1-faculty-trust-v1-target-truth-v2"})
            entry["detail_http"] = api.status
            if not api.ok:
                raise AssertionError(f"Missing stable record: {oid}")
            detail = api.json()
            entry["target_truth"] = detail["target_truth"]
            entry["detail_skills"] = detail["eligibility"]["skills_required"]
            entry["eligibility"] = {k: detail["eligibility"].get(k) for k in ("international_friendly", "work_auth_notes", "majors")}
            entry["rolling"] = detail.get("is_rolling")
            entry["deadline"] = detail.get("deadline")
            page.goto(site + "/opportunities/" + oid, wait_until="domcontentloaded")
            heading = page.get_by_role("heading", level=1)
            expect(heading).to_be_visible()
            entry["detail_title"] = heading.inner_text()
            entry["detail_excerpt"] = [s for s in page.locator("main").inner_text().splitlines() if any(k in s.lower() for k in ["python","c++","sql","apply","draft email","citizenship","stipend","paid","international","citizen","march","january","february","application","rolling","january 28","2027-01-28","basic programming","upcoming","closed"])]
            page.screenshot(path=out / (oid + "-detail.png"))
            from urllib.parse import quote
            with page.expect_response(lambda r: is_view(r) and (r.request.post_data_json or {}).get("view", {}).get("search_query") == query, timeout=90000) as network:
                page.goto(site + "/results?tab=all&ai=0&q=" + quote(query), wait_until="domcontentloaded")
            wire = network.value.json()
            assert network.value.ok
            entry["search_total"] = wire["filtered_total"]
            entry["listed"] = any(row["opportunity_id"] == oid for row in wire["results"])
            assert entry["listed"] or not wire["has_more"]
            card = page.locator("#match-card-" + oid)
            if entry["listed"]:
                assert detail["target_truth"]["actionable"]
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
