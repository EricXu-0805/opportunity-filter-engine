"""Check the released program periods, skills, directory and archived IDs through production."""
import json
import re
from urllib.parse import quote

from playwright.sync_api import expect, sync_playwright
from verify_m25_results_20261126 import capture, enter_results, is_view, out, receipt, site


cases = [
    ("ext-cmu-reuse", "Carnegie Mellon REUSE", "https://www.cmu.edu/scs/s3d/reuse/", "criteria", "2027-01-28", [], True),
    ("ext-umn-reu", "Computing for Social Good", "https://reu.cs.umn.edu/apply", "programming", None, ["Basic programming"], False),
    ("ext-usc-ict", "Institute for Creative Technologies REU", "https://ict.usc.edu/reu/", "january 27, 2027", "2027-01-27", [], True),
    ("ext-uiuc-ncsa-reu", "FoDOMMaT", "https://reu.ncsa.illinois.edu/", "python", "2027-02-15", ["Python", "machine learning"], True),
    ("ext-utexas-tacc", "TACC REU", "https://tacc.utexas.edu/education/undergraduates-graduates/reu/", "april 1, 2027", "2027-04-01", [], True),
    ("ext-umbc-bigdata", "UMBC Big Data REU", "https://bigdatareu.umbc.edu/2026-program-and-application/", "march 03, 2026", "2026-03-03", [], False),
    ("uiuc-sro-database", "Summer Research Opportunities Database", "https://researchops.web.illinois.edu/", "how to use", None, [], False),
]


def check(page, ctx, oid, query, source, qualifier, deadline, skills, actionable):
    entry = receipt[oid] = {"official": source}
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
    page.screenshot(path=out / (oid + "-detail.png"))
    with page.expect_response(lambda r: is_view(r) and (r.request.post_data_json or {}).get("view", {}).get("search_query") == query, timeout=90000) as resp:
        page.goto(site + "/results?tab=all&ai=0&q=" + quote(query), wait_until="domcontentloaded")
    assert resp.value.ok
    wire = resp.value.json()
    entry["match_count"] = wire["filtered_total"]
    ids = [r["opportunity_id"] for r in wire["results"]]
    entry["listed"] = oid in ids
    assert not wire["has_more"]
    assert entry["listed"] is actionable
    card = page.locator("#match-card-" + oid)
    if actionable:
        expect(card).to_be_visible(timeout=90000)
        card.get_by_role("button", name="Show details", exact=True).click()
        entry["card_text"] = card.inner_text()
        if oid != "ext-uiuc-ncsa-reu":
            assert not re.search(r"Missing skills:[^\n]*Python", entry["card_text"], re.I)
        card.screenshot(path=out / (oid + "-card.png"), animations="disabled")
    else:
        expect(page.get_by_role("tablist")).to_be_visible(timeout=90000)
        expect(card).to_have_count(0)
    assert entry["official_http"] == 200 and entry["official_phrase_found"]


with sync_playwright() as pw:
    browser = pw.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox", "--disable-dev-shm-usage"])
    ctx = browser.new_context(locale="en-US", service_workers="block", viewport={"width": 1250, "height": 950})
    ctx.add_init_script("if(location.hostname==='joinalab.com'){localStorage.setItem('ofe_onboarding_seen','1');localStorage.setItem('ofe_semantic_rerank_opt_in_v1','0');localStorage.setItem('ofe_lang','en');}")
    page = ctx.new_page()
    page.on("response", capture)
    page.set_default_timeout(40000)
    failures = {}
    try:
        health = page.request.get(site + "/api/health").json()
        receipt["backend_release"] = health["release_sha"]
        assert receipt["backend_release"] == "db3e8229b64e781b4dc74cddfe2c4acaa13d5896"
        enter_results(page, "uiuc")
        for row in cases:
            try:
                check(page, ctx, *row)
            except Exception as exc:
                failures[row[0]] = repr(exc)
        receipt["failures"] = failures
        assert not failures, failures
    finally:
        (out / "m23.json").write_text(json.dumps(receipt, indent=2) + "\n")
        print(json.dumps(receipt), flush=True)
        browser.close()
