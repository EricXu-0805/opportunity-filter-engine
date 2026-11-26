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
    college = "Engineering and Applied Science"
    for selector, value in (("#college", college), ("#major", "Computer Science")):
        field = page.locator(selector)
        if field.evaluate("e=>e.tagName") == "SELECT":
            options = field.locator("option").evaluate_all("os => os.filter(o=>o.value).map(o=>({value:o.value,label:o.textContent}))")
            preferred = next((o for o in options if value.lower() in o["label"].lower()), options[0]); field.select_option(value=preferred["value"])
        else:
            field.fill(value)
    page.locator("#grade").select_option(label="Junior")
    interests = "database systems, computer science, summer research" if school == "uiuc" else "machine learning, artificial intelligence, healthcare"
    page.locator("#research_interests").fill(interests)
    for label in ("Research", "Summer program", "Internship"):
        target = page.locator('fieldset[aria-describedby="seeking-types-help"]').get_by_role("button", name=label, exact=True)
        if target.get_attribute("aria-pressed") != "true":
            target.click()
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

def run(page):
    enter_results(page)
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
                more = page.get_by_role("button", name="Next", exact=True)
                with page.expect_response(lambda r: is_view(r) and bool((r.request.post_data_json or {}).get("cursor")), timeout=90000) as next_req:
                    more.click()
                second = read_page(next_req.value, val)
                assert not set(first["ids"]).intersection(second["ids"])
                assert first["view_id"] == second["view_id"] and first["total"] == second["total"]
                receipt[val]["second"] = second
        chips.screenshot(path=out / "filtered-internships.png")
    # Select a whole public tag via the form, then reopen the resulting URL.
    topic = chips.get_by_role("combobox", name="Research topic tag", exact=True)
    receipt["has_research_topic_filter"] = topic.count() == 1
    if topic.count():
        with page.expect_response(lambda r: is_view(r) and not (r.request.post_data_json or {}).get("view", {}).get("opportunity_type"), timeout=90000):
            page.goto(site + "/results?tab=all&ai=0", wait_until="domcontentloaded")
        needle = "machine learning"
        term_requests = lambda r: is_view(r) and (r.request.post_data_json or {}).get("view", {}).get("research_topic", "").casefold() == needle
        topic.fill(needle)
        with page.expect_response(term_requests, timeout=90000) as topic_request:
            chips.get_by_role("button", name="Filter by topic", exact=True).click()
        def check_topic(response):
            result = response.json()
            assert response.ok and not result["ai_refined"]
            assert result["applied_research_topic"] == needle
            assert result["filtered_total"] == result["view_counts"]["all"] > 0
            ids = []
            for row in result["results"]:
                assert needle in {tag.strip().casefold() for tag in row["opportunity"]["keywords"]}
                ids.append(row["opportunity_id"])
            assert ids and len(ids) == len(set(ids))
            return {"total": result["filtered_total"], "ids": ids, "view_id": result["view_id"]}
        selected = check_topic(topic_request.value)
        expect(page.locator("#match-card-" + selected["ids"][0])).to_be_visible(timeout=50000)
        page.wait_for_url(re.compile(r"topic=machine(?:%20|\+)learning"), timeout=30000)
        shared = page.url
        chips.screenshot(path=out / "research-topic.png")
        with page.expect_response(term_requests, timeout=90000) as restored:
            page.goto(shared, wait_until="domcontentloaded")
        reopened = check_topic(restored.value)
        assert reopened["ids"] == selected["ids"] and reopened["total"] == selected["total"]
        receipt["research_topic"] = {"url": shared, "selected": selected, "restored": reopened}
    # From the saved-search discrepancy replay, using the original stable IDs.
    estimates = (
        "nsf-reu-2548403 nsf-reu-2548073 nsf-reu-2548017 nsf-reu-2619097 nsf-reu-2547402 nsf-reu-2548122 "
        "nsf-reu-2547979 nsf-reu-2445879 nsf-reu-2447145 nsf-reu-2447817 nsf-reu-2447649 nsf-reu-2447228 "
        "nsf-reu-2447880 nsf-reu-2447670 nsf-reu-2447359 nsf-reu-2447769 nsf-reu-2447683 nsf-reu-2446949 "
        "nsf-reu-2447304 nsf-reu-2447669 nsf-reu-2447875 nsf-reu-2447543 nsf-reu-2447667 nsf-reu-2609947 "
        "nsf-reu-2547958 nsf-reu-2546381 nsf-reu-2548086 nsf-reu-2548476 nsf-reu-2548380 nsf-reu-2548411 "
        "nsf-reu-2548005 nsf-reu-2548451 nsf-reu-2548268 nsf-reu-2547457 nsf-reu-2446884 nsf-reu-2548272 "
        "nsf-reu-2548189 nsf-reu-2548016 nsf-reu-2548233 nsf-reu-2548040 nsf-reu-2547774 nsf-reu-2547394 "
        "nsf-reu-2548171 nsf-reu-2548378 nsf-reu-2548396 nsf-reu-2548054 nsf-reu-2546940 nsf-reu-2547299 "
        "nsf-reu-2548006 nsf-reu-2548392 nsf-reu-2548175 nsf-reu-2447234 nsf-reu-2548324 nsf-reu-2447634 "
        "nsf-reu-2547564 nsf-reu-2547627 nsf-reu-2548434 nsf-reu-2547923 nsf-reu-2548401 nsf-reu-2447548 "
        "nsf-reu-2547512 nsf-reu-2547945 nsf-reu-2547135 nsf-reu-2548274 nsf-reu-2548144 nsf-reu-2548326 "
        "nsf-reu-2548211 nsf-reu-2547890 nsf-reu-2548510 nsf-reu-2547056 nsf-reu-2548118 nsf-reu-2548038 "
        "nsf-reu-2447829 "
    ).split()
    records = page.request.post(site + "/api/opportunities/batch", data={"ids": estimates}, timeout=90000)
    assert records.ok, records.status
    batch = records.json()
    assert batch["requested"] == batch["found"] == len(set(estimates)) == 73
    dates = {row["id"]: row.get("deadline") for row in batch["opportunities"] if row.get("deadline_is_estimate") is True}
    und = "nsf-reu-2447669"
    if und not in dates:
        assert set(dates) == set(estimates) - {und}
        corrected = page.request.get(site + "/api/opportunities/" + und, params={"_release_scope": "mvp-core-close-v1-contact-trust-v1-faculty-trust-v1-target-truth-v2"})
        assert corrected.ok
        closed = corrected.json()
        assert closed["deadline"] == "2026-03-15" and closed["deadline_is_estimate"] is False
        assert closed["target_truth"]["actionable"] is False
        receipt["host_confirmed_deadlines"] = {und: closed["deadline"]}
    else:
        assert set(dates) == set(estimates)
    receipt["production_estimates"] = dates
    # Read a published results URL with an explicit date selection even when
    # its zero-count option is hidden. All cards and counts come from the
    # production service for the profile submitted through the form above.
    with page.expect_response(lambda r: is_view(r) and (r.request.post_data_json or {}).get("view", {}).get("deadline") == "passed", timeout=90000) as filtered:
        page.goto(site + "/results?tab=all&source=nsf_reu&dl=passed&ai=0", wait_until="domcontentloaded")
    data = filtered.value.json()
    assert filtered.value.ok and data["filtered_total"] == data["view_counts"]["all"] == 0
    assert data["results"] == [] and not data["has_more"]
    receipt["production_passed_nsf_results"] = {"total": data["filtered_total"], "view_id": data["view_id"]}
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
