"""Check the released program periods, skills, directory and archived IDs through production."""
import json
import re
from urllib.parse import quote, urlsplit

from playwright.sync_api import expect, sync_playwright
from verify_m25_results_20261126 import capture, enter_results, is_view, out, receipt, site


cases = [
    ("ext-cmu-reuse", "Carnegie Mellon REUSE", "https://www.cmu.edu/scs/s3d/reuse/", "criteria", "2027-01-28", [], True),
    ("ext-umn-reu", "Computing for Social Good", "https://reu.cs.umn.edu/apply", "programming", None, ["Basic programming"], False),
    ("ext-usc-ict", "Institute for Creative Technologies REU", "https://ict.usc.edu/reu/", "january 27, 2027", "2027-01-27", [], True),
    ("ext-uiuc-ncsa-reu", "FoDOMMaT", "https://reu.ncsa.illinois.edu/", "python", "2027-02-15", ["Python", "machine learning"], True),
    ("ext-utexas-tacc", "TACC REU", "https://tacc.utexas.edu/education/undergraduates-graduates/reu/", "april 1, 2027", "2027-04-01", [], True),
    ("ext-umbc-bigdata", "UMBC Big Data REU", "https://bigdatareu.umbc.edu/2026-program-and-application/", "march 03, 2026", "2026-03-03", [], False),
    ("sro-1532726e", "FoDOMMaT", "https://researchops.web.illinois.edu/opportunity/future-discovery-training-students-build-and-apply-open-source-machine-learning-models", "3/15/27", "2027-03-15", [], True),
    ("uiuc-sro-database", "Summer Research Opportunities Database", "https://researchops.web.illinois.edu/", "how to use", None, [], False),
]


def make_student(page, student):
    school = "uiuc" if student == "uiuc" else "ucb"
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
    college = "College of Computing, Data Science, and Society" if school == "ucb" else "Grainger College of Engineering"
    for selector, value in (("#college", college), ("#major", "Computer Science")):
        field = page.locator(selector)
        if field.evaluate("e=>e.tagName") == "SELECT":
            field.select_option(label=value)
        else:
            field.fill(value)
    page.locator("#grade").select_option(label="Sophomore" if student == "ucb-sophomore" else "Junior")
    interests = "database systems, computer science, summer research" if school == "uiuc" else "machine learning, artificial intelligence, healthcare"
    if student == "ucb-sophomore":
        interests = "machine learning, engineering, data science, undergraduate research, software engineering, creative technologies"
        for index, skill in enumerate(("Python", "machine learning", "C++", "Linux", "data science", "HPC", "software engineering")):
            box = page.get_by_placeholder("Add more…" if index else "Search or add a skill…", exact=True)
            box.fill(skill)
            box.press("Enter")
            chip = page.locator("span.min-w-0.break-all").filter(has_text=re.compile("^" + re.escape(skill) + "$", re.I))
            level = chip.locator("..").get_by_title("Click to change level (Beginner)", exact=True)
            level.click()
            expect(chip.locator("..").get_by_title("Click to change level (Experienced)", exact=True)).to_be_visible()
    page.locator("#research_interests").fill(interests)
    for label in ("Research", "Summer program", "Internship"):
        target = page.locator('fieldset[aria-describedby="seeking-types-help"]').get_by_role("button", name=label, exact=True)
        wanted = student != "ucb-sophomore" or label == "Summer program"
        if (target.get_attribute("aria-pressed") == "true") != wanted:
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


def check(page, ctx, oid, query, source, qualifier, deadline, skills, actionable):
    school = receipt["current_profile"]
    entry = receipt[school][oid] = {"official": source}
    tab = ctx.new_page()
    try:
        official = tab.goto(source, wait_until="domcontentloaded")
        entry["official_http"] = official.status
        body = " ".join(tab.locator("body").inner_text().lower().split())
        entry["official_phrase_found"] = qualifier in body
        entry["official_title"] = tab.title()
    finally:
        tab.close()
    api = page.request.get(site + "/api/opportunities/" + oid, params={"_release_scope": "mvp-core-close-v1-contact-trust-v1-faculty-trust-v1-target-truth-v2"})
    entry["detail_http"] = api.status
    assert api.ok
    d = api.json()
    for key in ["id", "deadline", "is_rolling", "target_truth", "application_opens"]:
        entry[key] = d.get(key)
    entry["skills"] = d["eligibility"]["skills_required"]
    entry["citizenship_required"] = d["eligibility"]["citizenship_required"]
    assert entry["id"] == oid and entry["deadline"] == deadline
    assert entry["is_rolling"] is False and entry["skills"] == skills
    truth = entry["target_truth"]
    assert truth["actionable"] is actionable
    if oid == "ext-uiuc-ncsa-reu":
        assert d["application_opens"]["on"] == "2026-12-15"
    if oid == "uiuc-sro-database":
        assert truth["reference_only"] and truth["reason_code"] == "reference_only"
    elif not actionable:
        assert truth["reason_code"] == "listing_closed"
    page.goto(site + "/opportunities/" + oid, wait_until="domcontentloaded")
    h1 = page.get_by_role("heading", level=1)
    expect(h1).to_have_text(d["title"], timeout=45000)
    entry["detail_title"] = h1.inner_text()
    action_pattern = re.compile(r"^(Apply now|Draft email)$", re.I)
    action_controls = [c for role in ["link", "button"] for c in page.get_by_role(role, name=action_pattern).all_text_contents()]
    entry["detail_action_controls"] = action_controls
    if not actionable:
        assert not action_controls
    entry["detail_excerpt"] = [s for s in page.locator("main").inner_text().splitlines() if re.search("python|programming|closed|reference|december|2027|apply|deadline|citizenship|citizens", s, re.I)]
    page.screenshot(path=out / (school + "-" + oid + "-detail.png"))
    with page.expect_response(lambda r: is_view(r) and (r.request.post_data_json or {}).get("view", {}).get("search_query") == query, timeout=90000) as resp:
        page.goto(site + "/results?tab=all&ai=0&q=" + quote(query), wait_until="domcontentloaded")
    assert resp.value.ok
    wire = resp.value.json()
    entry["match_count"] = wire["filtered_total"]
    ids = [r["opportunity_id"] for r in wire["results"]]
    entry["listed"] = oid in ids
    entry["returned_ids"] = ids
    request_body = resp.value.request.post_data_json
    entry["actual_view"] = request_body["view"]
    profile = request_body["profile"]
    entry["student"] = {k: profile.get(k) for k in ("home_school", "degree", "year", "seeking_type", "international_student", "research_interests_text", "desired_fields", "hard_skills", "preferences")}
    assert not wire["has_more"]
    if not actionable:
        assert not entry["listed"]
    entry["estimated"] = d.get("deadline_is_estimate")
    if oid == "sro-1532726e":
        assert entry["estimated"] is True
    if oid == "ext-uiuc-ncsa-reu":
        assert entry["estimated"] is False
    card = page.locator("#match-card-" + oid)
    if entry["listed"]:
        expect(card).to_be_visible(timeout=90000)
        card.get_by_role("button", name="Show details", exact=True).click()
        entry["card_text"] = card.inner_text()
        if oid != "ext-uiuc-ncsa-reu":
            assert not re.search(r"Missing skills:[^\n]*Python", entry["card_text"], re.I)
        card.screenshot(path=out / (school + "-" + oid + "-card.png"), animations="disabled")
    else:
        expect(page.get_by_role("tablist")).to_be_visible(timeout=90000)
        expect(card).to_have_count(0)
    assert entry["official_http"] == 200 and entry["official_phrase_found"]


with sync_playwright() as pw:
    browser = pw.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox", "--disable-dev-shm-usage"])
    failures = {}
    try:
        for school in ("uiuc", "ucb", "ucb-sophomore"):
            ctx = browser.new_context(locale="en-US", service_workers="block", viewport={"width": 1250, "height": 950})
            ctx.add_init_script("if(location.hostname==='joinalab.com'){localStorage.setItem('ofe_onboarding_seen','1');localStorage.setItem('ofe_semantic_rerank_opt_in_v1','0');localStorage.setItem('ofe_lang','en');}")
            page = ctx.new_page()
            page.on("response", capture)
            page.set_default_timeout(40000)
            health = page.request.get(site + "/api/health").json()
            receipt["backend_release"] = health["release_sha"]
            assert receipt["backend_release"] == "db3e8229b64e781b4dc74cddfe2c4acaa13d5896"
            receipt["guest_signup"] = receipt["profile_commit"] = None
            make_student(page, school)
            receipt["current_profile"] = school
            receipt[school] = {"guest_signup": receipt["guest_signup"], "profile_commit": receipt["profile_commit"]}
            for row in cases:
                if school != "uiuc" and not row[-1]:
                    continue
                try:
                    check(page, ctx, *row)
                except Exception as exc:
                    failures[school + "/" + row[0]] = repr(exc)
            ctx.close()
        receipt["failures"] = failures
        assert receipt["ucb"]["ext-usc-ict"].get("listed") is True
        for oid in ("sro-1532726e", "ext-uiuc-ncsa-reu", "ext-cmu-reuse"):
            assert receipt["ucb-sophomore"][oid].get("listed") is True, (oid, receipt["ucb-sophomore"][oid])
        assert not failures, failures
    finally:
        (out / "m23.json").write_text(json.dumps(receipt, indent=2) + "\n")
        print(json.dumps(receipt), flush=True)
        browser.close()
