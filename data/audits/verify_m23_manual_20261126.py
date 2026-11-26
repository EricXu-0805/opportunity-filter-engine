"""Read both Illinois undergraduate research guidance pages on production against their live source pages."""
import json
from playwright.sync_api import sync_playwright, expect
from verify_m25_results_20261126 import capture, enter_results, is_view, out, receipt, site

cases = [
    ("uiuc-career-center-ugr", "Undergraduate Research Resources", "https://www.careercenter.illinois.edu/undergraduateresearch", "value of research opportunities"),
    ("uiuc-siebel-ugresearch", "Siebel School — Undergraduate Research Opportunities", "https://siebelschool.illinois.edu/research/undergraduate-research", "undergraduate research"),
    ("uiuc-our-general", "Office of Undergraduate Research", "https://undergradresearch.illinois.edu/", "how to get started"),
]

with sync_playwright() as pw:
    browser = pw.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox", "--disable-dev-shm-usage"])
    ctx = browser.new_context(locale="en-US", service_workers="block", viewport={"width": 1250, "height": 950})
    ctx.add_init_script("if(location.hostname==='joinalab.com'){localStorage.setItem('ofe_onboarding_seen','1');localStorage.setItem('ofe_semantic_rerank_opt_in_v1','0');localStorage.setItem('ofe_lang','en');}")
    page = ctx.new_page()
    page.on("response", capture)
    page.set_default_timeout(40000)
    try:
        receipt["backend_release"] = page.request.get(site + "/api/health").json()["release_sha"]
        assert receipt["backend_release"] == "1b2c5b397c4ddd374d7e2cb4115e7066185fd75d"
        frontend = page.request.get(site)
        assert frontend.ok and "1b2c5b397c4ddd374d7e2cb4115e7066185fd75d" in frontend.text()
        receipt["frontend_release"] = "1b2c5b397c4ddd374d7e2cb4115e7066185fd75d"
        enter_results(page, "uiuc")
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
            assert (detail["id"], detail["url"]) == (oid, source)
            assert detail["target_truth"]["reference_only"] and not detail["target_truth"]["actionable"]
            assert detail.get("is_rolling") is False and not detail["eligibility"].get("skills_required")
            assert not (detail.get("application") or {}).get("application_url")
            entry["target_truth"] = detail["target_truth"]
            entry["detail_skills"] = detail["eligibility"]["skills_required"]
            entry["eligibility"] = {k: detail["eligibility"].get(k) for k in ("international_friendly", "work_auth_notes", "majors")}
            entry["rolling"] = detail.get("is_rolling")
            entry["deadline"] = detail.get("deadline")
            page.goto(site + "/opportunities/" + oid, wait_until="domcontentloaded")
            heading = page.get_by_role("heading", level=1)
            expect(heading).to_be_visible()
            entry["detail_title"] = heading.inner_text()
            expect(page.get_by_role("heading",level=1)).to_have_text(detail["title"],timeout=90000)
            expect(page.locator("a[href="+json.dumps(source)+"]").first).to_be_visible(timeout=90000)
            for role, label in [("link","Apply now"),("button","Draft email")]:
                expect(page.get_by_role(role,name=label,exact=True)).to_have_count(0)
            visible = page.locator("main").inner_text()
            assert "Applications reviewed on a rolling basis" not in visible and "Missing skills: Python" not in visible
            entry["page_excerpt"] = visible[:2500]
            entry["detail_excerpt"] = [s for s in page.locator("main").inner_text().splitlines() if any(k in s.lower() for k in ["python","c++","sql","apply","draft email","rolling","january 28","2027-01-28","basic programming","upcoming","closed"])]
            page.screenshot(path=out / (oid + "-detail.png"))
            from urllib.parse import quote
            with page.expect_response(lambda r: is_view(r) and (r.request.post_data_json or {}).get("view", {}).get("search_query") == query, timeout=90000) as network:
                page.goto(site + "/results?tab=all&ai=0&q=" + quote(query), wait_until="domcontentloaded")
            wire = network.value.json()
            assert network.value.ok
            entry["search_total"] = wire["filtered_total"]
            entry["listed"] = any(row["opportunity_id"] == oid for row in wire["results"])
            assert not entry["listed"] and (not wire["has_more"] or wire["filtered_total"] > 50)
            # If a broad search has multiple pages, walk all of the remaining
            # genuine pages before treating absence on the first as evidence.
            returned = [r["opportunity_id"] for r in wire["results"]]
            while wire["has_more"]:
                next_page = page.get_by_role("button", name="Next", exact=True)
                with page.expect_response(lambda r: is_view(r) and bool((r.request.post_data_json or {}).get("cursor")),timeout=90000) as traversal:
                    next_page.click()
                assert traversal.value.ok
                wire=traversal.value.json()
                current=[r["opportunity_id"] for r in wire["results"]]
                assert current and not set(current).intersection(returned)
                returned.extend(current)
            assert oid not in returned and len(returned)==wire["filtered_total"]
            entry["checked_result_ids"]=returned
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
        (out / "illinois-guides.json").write_text(json.dumps(receipt, indent=2) + "\n")
        print(json.dumps(receipt), flush=True)
        browser.close()
