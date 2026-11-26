"""Compare the student application and separate recommender rules at three production STaRS links."""
import json
from pathlib import Path
from playwright.sync_api import expect, sync_playwright

SITE = "https://joinalab.com"
HOST = "https://www.bumc.bu.edu/gms/students/summer-training-as-research-scholars-program/"
FAQ = HOST + "frequently-asked-questions/"
SCOPE = "mvp-core-close-v1-contact-trust-v1-faculty-trust-v1-target-truth-v2"
PHASE = "baseline"
EXPECTED = None
out = Path("evidence"); out.mkdir(exist_ok=True)
receipt = {"phase": PHASE, "records": {}}
with sync_playwright() as pw:
    browser = pw.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    ctx = browser.new_context(locale="en-US", service_workers="block", viewport={"width": 1260, "height": 950})
    ctx.add_init_script("if(location.hostname==='joinalab.com')localStorage.setItem('ofe_lang','en')")
    page = ctx.new_page()
    try:
        release = ctx.request.get(SITE + "/api/health").json()["release_sha"]
        assert release in ctx.request.get(SITE).text()
        receipt["frontend_release"] = receipt["backend_release"] = release
        assert not EXPECTED or release == EXPECTED
        for kind, url, snippets in (
            ("program", HOST, ("2028 and beyond", "STEM", "3.0", "Three letters", "January 15th, 2027")),
            ("faq", FAQ, ("February 1st", "two-year college", "first year Boston University medical students", "issues with GPA")),
        ):
            resp = page.goto(url, wait_until="domcontentloaded")
            assert resp and resp.ok
            # BU uses accordions. Their content exists in the loaded page even
            # while a section is collapsed.
            body = " ".join((page.locator("body").text_content() or "").split())
            present = [s for s in snippets if s.casefold() in body.casefold()]
            receipt[kind] = {"url": page.url, "title": page.title(), "status": resp.status,
                             "source_terms_present": present, "missing": [s for s in snippets if s not in present]}
        for oid in ("bu-bbc659c6ac92", "sro-60f60fbd", "sro-bc33bc08", "sro-51c40e5b"):
            reply = ctx.request.get(SITE + "/api/opportunities/" + oid, params={"_release_scope": SCOPE})
            entry = receipt["records"][oid] = {"status": reply.status}
            if not reply.ok:
                assert oid == "sro-51c40e5b" and reply.status == 404
                continue
            data = reply.json()
            assert data["id"] == oid
            entry.update({k: data.get(k) for k in ("deadline", "audience", "eligibility", "application")})
            fields = data["detail_fields"]["fields"]
            for k in ("eligibility", "application_method", "timing"):
                entry[k + "_facts"] = fields[k]["explicit"]
                entry[k + "_citations"] = {f: q.get("source_url") for f, q in fields[k]["quotes"].items()}
            if oid == "sro-51c40e5b":
                assert not fields["eligibility"]["explicit"].get("degree_path")
                continue
            page.goto(SITE + "/opportunities/" + oid, wait_until="domcontentloaded")
            expect(page.get_by_role("heading", level=1)).to_have_text(data["title"], timeout=85000)
            facts = page.get_by_test_id("fact-field-eligibility")
            expect(facts).to_be_visible(timeout=60000)
            entry["rendered_eligibility"] = facts.inner_text()
            entry["rendered_materials"] = page.get_by_test_id("fact-field-application_method").inner_text()
            if PHASE == "baseline":
                assert entry["eligibility"]["min_gpa"] is None
                assert entry["application"].get("requires_recommendation") == "unknown"
                assert "degree_path" not in entry["eligibility_facts"]
            else:
                assert entry["deadline"] == "2027-01-15" and entry["audience"] == "open"
                assert entry["eligibility"]["min_gpa"] == 3 and entry["eligibility"]["majors"] == []
                assert entry["application"]["requires_recommendation"] == "yes"
                for facet, term, url in [
                    ("min_gpa","3",HOST), ("degree_path","2028",HOST), ("class_year","junior",HOST),
                    ("citizenship","permanent",HOST), ("research_background","optional",HOST),
                    ("gpa_context","explain",FAQ), ("transfer_students","admitted",FAQ), ("medical_students","first year",FAQ),
                ]:
                    item = page.get_by_test_id("fact-eligibility-" + facet)
                    expect(item).to_contain_text(term)
                    expect(item.get_by_role("link")).to_have_attribute("href",url)
                for facet, text, url in (("requirements","Three recommendation letters",HOST),("recommendation_deadline","February 1",FAQ)):
                    item = page.get_by_test_id("fact-application_method-" + facet)
                    expect(item).to_contain_text(text)
                    expect(item.get_by_role("link")).to_have_attribute("href",url)
            page.get_by_test_id("fact-field-eligibility").screenshot(path=out / (oid + ".png"), animations="disabled")
        assert not receipt["program"]["missing"] and not receipt["faq"]["missing"], (receipt["program"], receipt["faq"])
    finally:
        (out/"boston-stars-eligibility.json").write_text(json.dumps(receipt,indent=2)+"\n")
        print(json.dumps(receipt,ensure_ascii=False))
        browser.close()
