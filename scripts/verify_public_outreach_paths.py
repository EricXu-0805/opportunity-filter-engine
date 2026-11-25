"""Check the public match card, detail actions and deterministic unsent draft for three targets."""
import json
import os
import sys
from urllib.parse import urlencode, urlsplit

from playwright.sync_api import expect, sync_playwright

SITE = "https://joinalab.com"
SCOPE = "mvp-core-close-v1-contact-trust-v1-faculty-trust-v1-target-truth-v2"
CASES = {
    "profile": ("faculty-caltech-phys-b6dd07e7", "caltech", "California Institute of Technology", "Physics",
                "mathematical physics, quantum field theory", "Sergei Gukov", "Faculty profile · openings not confirmed"),
    "inquiry": ("faculty-ucb-eecs-d683bc2c", "ucb", "UC Berkeley", "Computer Science",
                "machine learning, artificial intelligence", "Ahmed Alaa", "Faculty contact for inquiries · openings not confirmed"),
    "listing": ("simplify-intern-3ea65aaa-0297-4b8f-9378-51e35478fb95", "uiuc", "University of Illinois Urbana-Champaign",
                "Computer Science", "data engineering, data science, Python", "Octaura", ""),
}


def verify(mode):
    oid, home, school, major, interests, query, badge = CASES[mode]
    profile = {"name": "Sample Student", "institution": school, "home_school": home,
               "grade": "Junior", "major": major, "research_interests": interests,
               "skills": ["Python", "SQL", "statistics"], "seeking_types": ["internship" if mode == "listing" else "research"],
               "coursework": [], "is_international": False, "can_cold_email": True}
    with sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.environ.get("CHROME_BIN", "/usr/bin/google-chrome"),
                                     args=["--disable-dev-shm-usage", "--no-sandbox"])
        context = browser.new_context(service_workers="block", locale="en-US")
        values = {"ofe_profile": json.dumps(profile), "ofe_onboarding_seen": "1", "ofe_lang": "en"}
        context.add_init_script("if(location.hostname==='joinalab.com'&&!localStorage.getItem('oe_seeded')){"
                                "for(const [k,v] of Object.entries(" + json.dumps(values) + "))localStorage.setItem(k,v);"
                                "localStorage.setItem('oe_seeded','1')}")
        page = context.new_page()
        page.set_default_timeout(30000)
        evidence = []
        def matching(response):
            if urlsplit(response.url).path == "/api/matches/view" and response.status == 200:
                payload = response.json()
                assert payload.get("ai_refined") is False
                evidence.extend(r for r in payload["results"] if r["opportunity_id"] == oid)
        page.on("response", matching)
        page.goto(SITE + "/dashboard", wait_until="domcontentloaded", timeout=45000)
        campus = page.get_by_test_id("university-card-" + home)
        try:
            campus.wait_for(timeout=5000)
        except Exception:
            pass
        if campus.is_visible():
            campus.click()
            page.get_by_test_id("switcher-confirm").click()
            expect(campus).to_be_hidden()
        page.goto(SITE + "/results?" + urlencode({"tab": "all", "q": query, "ai":"0"}), wait_until="domcontentloaded")
        card = page.locator("#match-card-" + oid)
        try:
            expect(card).to_be_visible(timeout=85000)
        except Exception:
            print("Match view", page.url, "headings", page.get_by_role("heading").all_text_contents()[:12],
                  "cards", page.locator('[id^="match-card-"]').count(), flush=True)
            raise
        assert evidence, "A real match response for this card is required"
        card.get_by_role("button", name="Show details").click()
        row = evidence[-1]
        link = card.get_by_role("link", name="Apply now", exact=True)
        if badge:
            expect(card.get_by_text(badge, exact=True)).to_be_visible()
            expect(link).to_have_count(0)
            assert row["opportunity"]["record_kind"] == "faculty_contact"
            assert row["opportunity"]["contact_email_status"] == ("unavailable" if mode=="profile" else "sign_in_required")
            assert not row["opportunity"]["application"].get("application_url")
            expected = "verify a contact channel" if mode=="profile" else "brief cold email"
            assert any(expected in step.lower() for step in row["next_steps"]), row["next_steps"]
        else:
            expect(link).to_be_visible()
            assert "octaura/jobs/" in link.get_attribute("href")
            assert row["opportunity"]["record_kind"] == "listing"
        page.goto(SITE + "/opportunities/" + oid, wait_until="domcontentloaded")
        expect(page.get_by_role("heading", level=1)).to_be_visible()
        if badge:
            expect(page.get_by_text(badge, exact=True).first).to_be_visible()
            expect(page.get_by_role("link",name="Apply now",exact=True)).to_have_count(0)
        else:
            expect(page.get_by_role("link",name="Apply now",exact=True).first).to_be_visible()
        draft = context.request.post(SITE+"/api/cold-email", data={"engine":"template", "opportunity_id":oid,
                   "profile":{"name":"Sample Student","year":"junior","major":major,"school":school,"hard_skills":[]}})
        assert draft.ok, draft.status
        body = draft.json()["body"]
        if badge:
            assert "?" in body and not any(x in body.lower() for x in ("your open position","you are hiring"))
        else:
            assert "data engineer intern" in body.lower()
        print(mode, oid, row["opportunity"]["record_kind"], row["opportunity"].get("contact_email_status"),
              "card, next steps, detail action and unsent template verified", flush=True)
        browser.close()


if __name__ == "__main__":
    verify(sys.argv[1])
