"""Read the saved staff profile, a retired scientist, and two current chairs in Chromium."""
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlsplit
from urllib.request import urlopen

from playwright.sync_api import sync_playwright

CASES = json.loads(Path(__file__).with_name("four-roles.json").read_text())

def check(site, sha, scope, output):
    def read(path):
        with urlopen(site + path, timeout=50) as response:
            return json.load(response)
    before = read('/api/health')['release_sha']
    assert before == sha
    records = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch()
        context = browser.new_context(locale='en-US')
        account = {'signup_http': None, 'profile_saved': False}
        def observe(response):
            path = urlsplit(response.url).path
            if path == '/auth/v1/signup':
                account['signup_http'] = response.status
            if path.endswith('/rpc/commit_profile_patch_cas') and response.ok:
                result = response.json()
                if isinstance(result, list):
                    result = result[0] if result else {}
                if result.get('status') == 'applied':
                    account['profile_saved'] = True
        context.on('response', observe)
        home = context.new_page()
        home.goto(site + '/', wait_until='domcontentloaded', timeout=60000)
        tour = home.get_by_test_id('onboarding-intro')
        tour.wait_for(timeout=40000)
        tour.get_by_test_id('onboarding-skip').click()
        tour.get_by_test_id('onboarding-school-ncsu').click()
        tour.get_by_test_id('onboarding-primary').click()
        tour.wait_for(state='hidden', timeout=45000)
        home.locator('#student_name').wait_for()
        home.get_by_test_id('hydration-note').wait_for(state='hidden', timeout=45000)
        home.get_by_test_id('profile-refresh-status').wait_for(state='hidden', timeout=45000)
        home.locator('#student_name').fill('Michigan State appointment QA')
        for selector in ('#college', '#major'):
            field = home.locator(selector)
            if field.evaluate('e => e.tagName') == 'SELECT':
                field.locator("option:not([value='']):not([disabled])").first.wait_for(state='attached')
                field.select_option(field.locator('option').evaluate_all('rows => rows.find(x => x.value && !x.disabled).value'))
            else:
                field.fill('Computer Science')
        home.locator('#grade').select_option(label='Junior')
        for _ in range(120):
            if account['signup_http'] == 200 and account['profile_saved']:
                break
            home.wait_for_timeout(250)
        assert account['signup_http'] == 200 and account['profile_saved'], account
        for case in CASES:
            pid = case["id"]
            staff = pid == "faculty-msu-mgi-6af109e0"
            active = case["active"]
            row = {"id": pid, "expected_name": case["name"]}
            page = context.new_page()
            try:
                payload = read("/api/opportunities/" + pid + "?" + urlencode({"_release_scope": scope}))
                row["api_role"] = payload["metadata"]["faculty_title"]
                assert payload["id"] == pid and payload["pi_name"] == case["name"]
                assert row["api_role"] == case["rank"] and payload["target_truth"]["actionable"] == active
                response = page.goto(site + "/opportunities/" + pid, wait_until="domcontentloaded", timeout=60000)
                assert response and response.status == 200
                row["http"] = response.status
                main = page.get_by_role("main")
                main.get_by_role("link", name="Back to matches", exact=True).wait_for(timeout=45000)
                h1 = main.get_by_role("heading", level=1)
                h1.wait_for(timeout=45000)
                row["heading"] = h1.inner_text()
                assert case["name"] in row["heading"] and page.locator("html").get_attribute("data-release-sha") == sha
                source_label = "View source" if staff else "View faculty profile"
                profile_link = main.get_by_role("link", name=source_label, exact=True)
                profile_link.wait_for(timeout=15000)
                if active:
                    main.get_by_role("button", name="Draft email", exact=True).wait_for(timeout=15000)
                # Inspect other expandable sections for misleading contact or faculty text.
                for details in main.locator("details:not([open]) > summary").all():
                    if details.is_visible():
                        details.click()
                row["source_label"] = profile_link.inner_text()
                row["source_target"] = profile_link.get_attribute("href")
                assert row["source_target"] == case["official"], row
                text = main.inner_text()
                all_controls = [str(x).strip() for x in main.locator("a:visible,button:visible").all_inner_texts() if x.strip()]
                row.update(
                    inactive_banner="This record is no longer active." in text,
                    text_has_faculty_profile="faculty research profile" in text.casefold(),
                    view_faculty_profile=main.get_by_role("link", name="View faculty profile", exact=True).count() > 0,
                    generic_contact_invitation="contact this faculty member" in text.casefold(),
                    draft_button_visible=main.get_by_role("button", name="Draft email", exact=True).is_visible(),
                    apply_action_visible=any(x in ("Apply", "Apply now", "Email professor") for x in all_controls),
                    rank_visible=case["rank"] in text,
                    has_staff_summary="Executive Assistant to the Chair and Communications Manager" in text,
                    academic_labels=[t for t in ("Professor or lab", "Recent publications", "Research areas") if t.casefold() in text.casefold()],
                    action_labels=all_controls,
                    api_contact_status=payload.get("contact_email_status"),
                )
                assert row["inactive_banner"] == (not active), row
                assert row["view_faculty_profile"] == (not staff), row
                assert row["generic_contact_invitation"] == active and row["draft_button_visible"] == active, row
                if not active:
                    assert not row["apply_action_visible"], row
                if staff:
                    assert row["has_staff_summary"] and not row["text_has_faculty_profile"], row
                row["verdict"] = "passed"
            except Exception as exc:
                row["verdict"] = "requires review"
                row["failure"] = str(exc)[:2400]
            finally:
                page.screenshot(path=str(output.with_name(pid + ".png")), full_page=True)
                records.append(row)
                page.close()
        browser.close()
    after = read("/api/health")["release_sha"]
    output.write_text(json.dumps({"checked_at": datetime.now(timezone.utc).isoformat(),
                                 "site": site, "signup_and_persisted_synthetic_profile": account,
                                 "release_start": before, "release_end": after, "rows": records}, indent=2) + "\n")
    assert before == after == sha and all(row["verdict"] == "passed" for row in records), "See the four saved detail receipts."
if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    for argument in ['site','sha','scope','out']:
        parser.add_argument('--'+argument, required=True)
    args = parser.parse_args()
    check(args.site, args.sha, args.scope, Path(args.out))
