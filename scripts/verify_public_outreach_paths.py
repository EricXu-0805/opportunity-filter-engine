"""Check the public match card, detail actions and deterministic unsent draft for three targets."""
import csv
import json
import os
import subprocess
import sys
import time
from contextlib import contextmanager
from urllib.parse import urlsplit

from verify_live_browser_flows import fetch, rpc, stub

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


@contextmanager
def account_fixture(profile):
    process = subprocess.Popen(["node", "frontend/e2e/supabase-stub.mjs"],
                               env={**os.environ, "E2E_SUPABASE_PORT": "51432"}, stdout=subprocess.DEVNULL)
    try:
        for _ in range(60):
            if process.poll() is not None:
                raise RuntimeError("Isolated account service exited")
            try:
                fetch(stub + "/health")
                break
            except OSError:
                time.sleep(.2)
        session = rpc("/auth/v1/signup", {})
        uid = session["user"]["id"]
        saved = rpc("/rest/v1/rpc/commit_profile_patch_cas", {"p_expected_device_id": uid,
                    "p_expected_revision": 0, "p_patch": profile}, {"Authorization": "Bearer " + session["access_token"]})
        assert saved["status"] == "applied"
        yield session
    finally:
        process.terminate()
        process.wait(timeout=5)


def install_account(context, oid, extra_favorites=()):
    def route_account(route):
        req = route.request
        url = urlsplit(req.url)
        cors = {"Access-Control-Allow-Origin": SITE, "Access-Control-Allow-Credentials": "true",
                "Access-Control-Allow-Methods": "GET,POST,PATCH,DELETE,HEAD,OPTIONS",
                "Access-Control-Allow-Headers": req.headers.get("access-control-request-headers", "*"),
                "Access-Control-Expose-Headers": "Content-Range"}
        if req.method == "OPTIONS":
            return route.fulfill(status=204, headers=cors)
        if url.path == "/rest/v1/favorites" and req.method == "GET":
            ids = sorted({oid, *extra_favorites})
            return route.fulfill(status=200, headers={**cors, "Content-Range": f"0-{len(ids)-1}/{len(ids)}"},
                                 json=[{"opportunity_id": key} for key in ids])
        headers = {"Content-Type": "application/json", **{k: v for k, v in req.headers.items()
                   if k in ("authorization", "prefer", "range", "accept")}}
        code, ct, body = fetch(stub + url.path + ("?" + url.query if url.query else ""),
                               req.post_data_buffer, headers, req.method)
        return route.fulfill(status=code, content_type=ct, body=body, headers=cors)
    context.route("https://*.supabase.co/**", route_account)


def verify(mode, score_phase=None, locale="en", export_phase=None, eligibility_phase=None):
    oid, home, school, major, interests, query, badge = CASES[mode]
    college = {"caltech": "Division of Physics, Mathematics and Astronomy",
               "ucb": "College of Computing, Data Science, and Society", "uiuc": "Grainger College of Engineering"}[home]
    profile = {"college": college, "name": "Sample Student", "institution": school, "home_school": home,
               "grade": "Junior", "major": major, "research_interests": interests,
               "skills": ["Python", "SQL", "statistics"], "seeking_types": ["internship" if mode == "listing" else "research"],
               "coursework": [], "is_international": False, "can_cold_email": True}
    if eligibility_phase:
        profile.update(grade='Freshman', major='History', skills=['writing'], research_interests='data engineering')
    with account_fixture(profile) as session, sync_playwright() as pw:
        browser = pw.chromium.launch(executable_path=os.environ.get("CHROME_BIN", "/usr/bin/google-chrome"),
                                     args=["--disable-dev-shm-usage", "--no-sandbox"])
        context = browser.new_context(service_workers="block", locale="zh-CN" if locale == "zh" else "en-US")
        install_account(context, oid, [CASES["profile"][0]] if export_phase else [])
        values = {"ofe_auth": json.dumps(session), "ofe_profile": json.dumps(profile), "ofe_onboarding_seen": "1", "ofe_lang": locale}
        if locale == "zh":
            context.add_cookies([{"name":"ofe_lang","value":"zh","url":SITE}])
        context.add_init_script("if(location.hostname==='joinalab.com'&&!localStorage.getItem('oe_seeded')){"
                                "for(const [k,v] of Object.entries(" + json.dumps(values) + "))localStorage.setItem(k,v);"
                                "localStorage.setItem('oe_seeded','1')}")
        page = context.new_page()
        page.set_default_timeout(30000)
        evidence = []
        def matching(response):
            path = urlsplit(response.url).path
            if path == "/api/matches/view" and response.request.method == "POST":
                request = response.request.post_data_json or {}
                view = request.get("view") or {}
                print("Production match", response.status, view.get("tab"), "selected target",
                      oid in (view.get("favorite_ids") or []), flush=True)
                if response.status != 200:
                    return
                payload = response.json()
                assert payload.get("ai_refined") is False
                evidence.extend(r for r in payload["results"] if r["opportunity_id"] == oid)
        page.on("response", matching)
        page.on("requestfailed", lambda request: print("Failed request", request.method,
                urlsplit(request.url).path, request.failure, flush=True))
        page.on("pageerror", lambda error: print("Page error", str(error)[:240], flush=True))
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
        page.goto(SITE + ("/results?tab=all&ai=0&q=Ahmed%20Alaa" if export_phase else "/results?tab=starred&ai=0"),
                  wait_until="domcontentloaded")
        card = page.locator("#match-card-" + oid)
        try:
            expect(card).to_be_visible(timeout=85000)
        except Exception:
            print("Match view", page.url, "headings", page.get_by_role("heading").all_text_contents()[:12],
                  "cards", page.locator('[id^="match-card-"]').count(), flush=True)
            print("Visible status", " ".join(page.locator("main").inner_text().split())[:1500], flush=True)
            raise
        page.wait_for_timeout(100)
        assert evidence, "A real match response for this card is required"
        if export_phase:
            label = 'Export 2 starred CSV' if export_phase == 'before' else 'Export favorites in this view (CSV)'
            button = page.get_by_role('button', name=label, exact=True)
            expect(button).to_be_visible()
            with page.expect_download() as download:
                button.click()
            with open(download.value.path(), encoding='utf-8-sig', newline='') as f:
                rows = list(csv.DictReader(f))
            assert len(rows) == 1 and rows[0]['Title'] == evidence[-1]['opportunity']['title'], rows
            assert query in rows[0]['Title'], rows
            print('PASS', export_phase, 'saved in account: 2, CSV rows: 1, actual title:', rows[0]['Title'],
                  'button:', label, 'frontend:', page.locator('html').get_attribute('data-release-sha'), flush=True)
            browser.close()
            return
        card.get_by_role("button", name="展开详情" if locale == "zh" else "Show details").click()
        row = evidence[-1]
        if eligibility_phase:
            assert row['opportunity']['title'] == 'Data Engineer Intern'
            wrong_major = 'Prefers Computer Science, Statistics, Data Science'
            wrong_resume = 'Resume required — prepare one before applying'
            for line in row['reasons_fit'] + row['reasons_gap'] + row['next_steps']:
                expect(card.get_by_text(line, exact=True).first).to_be_visible()
            verify = card.locator('summary').filter(has_text='What to verify')
            verify.click()
            labels = verify.locator('..').locator('li').all_text_contents()
            if eligibility_phase == 'before':
                assert wrong_major in row['reasons_gap'] and wrong_resume in row['reasons_gap'], row['reasons_gap']
                assert 'Eligible majors' not in labels and 'Eligible class years' not in labels, labels
            else:
                assert wrong_major not in row['reasons_gap'] and wrong_resume not in row['reasons_gap'], row['reasons_gap']
                assert {'Eligible majors','Eligible class years','Whether a resume is required'} <= set(labels), labels
            page.goto(SITE + '/opportunities/' + oid, wait_until='domcontentloaded')
            expect(page.get_by_role('heading',level=1)).to_contain_text('Data Engineer Intern')
            text = ' '.join(page.locator('main').inner_text().split())
            assert 'class year not provided' in text.casefold() and 'majors system inference' in text.casefold(), text
            assert 'application materials not provided' in text.casefold(), text
            print('PASS listing evidence', eligibility_phase, oid, page.locator('html').get_attribute('data-release-sha'),
                  'gaps', row['reasons_gap'], 'verify',labels,'next steps',row['next_steps'],flush=True)
            browser.close()
            return
        if score_phase:
            heading = "需要核实的条件" if locale == "zh" else "What to verify"
            meaning = ("匹配分用于按你的资料排列推荐顺序。系统不估算录取或收到回复的概率。" if locale == "zh" else
                       "The match score ranks opportunities for your profile. It does not predict admission or a reply.")
            assert row.get("unknowns") and row.get("next_steps")
            if score_phase == "before":
                expect(card.get_by_text(heading,exact=True)).to_have_count(0)
                expect(page.get_by_text(meaning,exact=True)).to_have_count(0)
            else:
                expect(page.get_by_text(meaning,exact=True)).to_be_visible()
                toggle = card.locator("summary").filter(has_text=heading)
                toggle.click()
                labels = {
                    "profile.year": ("Your class year","你的年级"), "profile.major": ("Your major","你的专业"),
                    "opportunity.preferred_year": ("Eligible class years","可申请的年级"),
                    "opportunity.majors": ("Eligible majors","可申请的专业"),
                    "opportunity.international_friendly": ("Eligibility for international students","国际学生申请资格"),
                    "opportunity.paid": ("Compensation","报酬"),
                    "opportunity.application_effort": ("Application effort","申请所需投入"),
                    "opportunity.on_campus": ("Whether the work is on campus","是否需要到校"),
                    "opportunity.deadline": ("Application deadline","申请截止日期"),
                    "profile.gpa": ("Whether your GPA meets the listed minimum","你的 GPA 是否达到所列最低要求"),
                }
                expected = [labels[k][locale == "zh"] for k in row["unknowns"]]
                assert toggle.locator("..").locator("li").all_text_contents() == expected
            for step in row["next_steps"]:
                expect(card.get_by_text(step,exact=True)).to_be_visible()
            if score_phase == "after":
                state = "可联系教师咨询 · 是否招人待确认" if locale == "zh" else badge
                expect(card.get_by_text(state, exact=True)).to_be_visible()
                assert row["opportunity"]["record_kind"] == "faculty_contact"
                assert not row["opportunity"]["application"].get("application_url")
                page.goto(SITE + "/opportunities/" + oid, wait_until="domcontentloaded")
                expect(page.get_by_role("heading", level=1)).to_contain_text(query)
                expect(page.get_by_text(state, exact=True).first).to_be_visible()
                print("Same target and opening status on the expanded result and detail:", oid, state, flush=True)
            print("PASS released match", score_phase, locale, oid, page.locator("html").get_attribute("data-release-sha"),
                  row["final_score"], row["unknowns"], row["next_steps"],flush=True)
            browser.close()
            return
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
        template = draft.json()
        body = template["body"]
        subject = template["subject"]
        expected_subject = "Research inquiry" if badge else "Internship inquiry — Data Engineer Intern"
        assert subject == expected_subject, subject
        if badge:
            assert "?" in body and not any(x in body.lower() for x in ("your open position","you are hiring"))
        else:
            assert "data engineer intern" in body.lower()
        print(mode, oid, row["opportunity"]["record_kind"], row["opportunity"].get("contact_email_status"),
              "card, next steps, detail action and unsent template verified", subject, flush=True)
        browser.close()


if __name__ == "__main__":
    if sys.argv[1].startswith("eligibility-"):
        verify("listing", eligibility_phase=sys.argv[1].split("-")[1])
    elif sys.argv[1].startswith("export-"):
        verify("inquiry", export_phase=sys.argv[1].split("-")[1])
    elif sys.argv[1].startswith("score-"):
        _, phase, locale = sys.argv[1].split("-")
        verify("inquiry", phase, locale)
    else:
        verify(sys.argv[1])
