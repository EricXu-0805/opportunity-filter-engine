"""Save one published BME appointment and reopen it as the same guest on the candidate."""
import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlsplit
from urllib.request import urlopen

from playwright.sync_api import expect, sync_playwright

SITE = "http://127.0.0.1:3000"
SCOPE = "mvp-core-close-v1-contact-trust-v1-faculty-trust-v1-target-truth-v2"
SUBJECT = "faculty-osu-bme-5874478d"
B19 = "b129ed3336f1203ae6097a50af9e7e4f8950ac40"
B26 = "2a05dc73ffc05d52777b2f12a0793e2bc6eece15"
CASES = {
    SUBJECT: ("Rengasayee Veeraraghavan", "veeraraghavan.12"),
    "faculty-osu-bme-16e6344f": ("Benjamin Walter", "walter.367"),
    "faculty-osu-bme-c7dcb9ef": ("Ravi Bellamkonda", "bellamkonda.7"),
}
DIRECTORY = "https://bme.osu.edu/directory/department-faculty?page=1"


def public(path):
    with urlopen(SITE + path, timeout=60) as response:
        return json.load(response)


def new_guest(home, account):
    home.goto(SITE + "/", wait_until="domcontentloaded", timeout=70000)
    tour = home.get_by_test_id("onboarding-intro")
    tour.wait_for(timeout=50000)
    tour.get_by_test_id("onboarding-skip").click()
    tour.get_by_test_id("onboarding-school-ncsu").click()
    tour.get_by_test_id("onboarding-primary").click()
    tour.wait_for(state="hidden", timeout=50000)
    home.locator("#student_name").wait_for()
    home.get_by_test_id("hydration-note").wait_for(state="hidden", timeout=50000)
    home.get_by_test_id("profile-refresh-status").wait_for(state="hidden", timeout=50000)
    home.locator("#student_name").fill("Appointment review fixture")
    for selector in ("#college", "#major"):
        field = home.locator(selector)
        if field.evaluate("e => e.tagName") == "SELECT":
            field.locator("option:not([value='']):not([disabled])").first.wait_for(state="attached")
            field.select_option(field.locator("option").evaluate_all("rows => rows.find(x => x.value && !x.disabled).value"))
        else:
            field.fill("Computer Science")
    home.locator("#grade").select_option(label="Junior")
    for _ in range(200):
        if account["signup_http"] == 200 and account["profile_saved"]:
            return
        home.wait_for_timeout(250)
    raise AssertionError("The new guest did not obtain and save a real isolated account profile")


def identity_hash(value):
    return hashlib.sha256(value.encode()).hexdigest()[:20]


def case(page, key, sha, *, navigate=True):
    name, slug = CASES[key]
    if navigate:
        response = page.goto(SITE + "/opportunities/" + key, wait_until="domcontentloaded", timeout=70000)
        assert response and response.status == 200
    main = page.get_by_role("main")
    heading = main.get_by_role("heading", level=1, name=name, exact=True)
    expect(heading).to_be_visible(timeout=60000)
    main.get_by_role("link", name="Back to matches", exact=True).wait_for(timeout=45000)
    assert page.locator("html").get_attribute("data-release-sha") == sha
    api = public("/api/opportunities/" + key + "?" + urlencode({"_release_scope": SCOPE}))
    expected_active = sha == B19 or key != SUBJECT
    assert api["id"] == key and api["pi_name"] == name and api["target_truth"]["actionable"] is expected_active
    official = "https://bme.osu.edu/people/" + slug
    assert api["url"] == api["source_url"] == official
    profile = main.get_by_role("link", name="View faculty profile", exact=True)
    expect(profile).to_be_visible(timeout=30000)
    assert profile.get_attribute("href") == official
    text = main.inner_text()
    assert "Ohio State University" in text
    archived = "This record is no longer active." in text
    assert archived is (not expected_active)
    draft = main.get_by_role("button", name="Draft email", exact=True)
    if expected_active:
        expect(draft).to_be_visible(timeout=45000)
    else:
        expect(draft).to_have_count(0)
        assert "Contact this faculty member to ask" not in text and "Apply now" not in text
    rank = api["metadata"]["faculty_title"]
    rank_quote = api["detail_fields"]["fields"]["professor_or_lab"]["quotes"].get("faculty_rank")
    if key == SUBJECT and sha == B26:
        assert rank == "Adjunct Professor, Biomedical Engineering" and rank_quote == {
            "text": rank, "observed_at": "2026-11-26", "source_url": DIRECTORY,
        }
        assert api["contact_email_status"] == "unavailable" and "contact_email" not in api
    elif key == SUBJECT:
        assert rank == "Professor, Biomedical Engineering"
    paper_titles = [w["title"] for w in api["metadata"]["recent_works"]]
    shown = main.locator('a[href^="https://scholar.google.com/scholar"]').all_text_contents()
    assert len(paper_titles) == 3 and set(paper_titles) == set(shown)
    return {"id": key, "heading": heading.inner_text(), "page": page.url, "campus": "Ohio State University",
            "source_page": official, "archive_banner": archived, "draft_visible": draft.is_visible(),
            "three_visible_papers": shown, "api_appointment": rank, "source_quote": rank_quote,
            "api_contact_email_status": api["contact_email_status"], "release": sha}


def run(stage, profile, receipt):
    result = {"stage": stage, "at": datetime.now(timezone.utc).isoformat(), "rows": [], "passed": False}
    account = {"signup_http": None, "profile_saved": False, "favorite_write_http": None,
               "favorite_select_reads": [], "guest_hash": None}
    result["isolated_account"] = account
    sha = B19 if stage == "before" else B26
    assert public("/api/health")["release_sha"] == sha

    def observe(response):
        loc = urlsplit(response.url)
        if loc.path == "/auth/v1/signup":
            account["signup_http"] = response.status
            user = response.json().get("user") or {}
            if user.get("id"):
                account["guest_hash"] = identity_hash(user["id"])
        if loc.path.endswith("/rpc/commit_profile_patch_cas") and response.ok:
            data = response.json()
            row = (data[0] if data else {}) if isinstance(data, list) else data
            if row.get("status") == "applied":
                account["profile_saved"] = True
        if loc.path == "/rest/v1/favorites" and response.ok:
            if response.request.method == "POST":
                data = response.request.post_data_json
                if data.get("opportunity_id") == SUBJECT:
                    account["favorite_write_http"] = response.status
                    account["guest_hash"] = identity_hash(data["device_id"])
            elif response.request.method == "GET":
                owner = (parse_qs(loc.query).get("device_id") or [""])[0].removeprefix("eq.")
                rows = response.json()
                if owner and isinstance(rows, list) and any(v.get("opportunity_id") == SUBJECT for v in rows):
                    account["favorite_select_reads"].append({"http": response.status, "owner_hash": identity_hash(owner),
                                                           "original_id": SUBJECT})
    try:
        with sync_playwright() as pw:
            ctx = pw.chromium.launch_persistent_context(str(profile), headless=True, locale="en-US")
            ctx.on("response", observe)
            page = ctx.new_page()
            if stage == "before":
                new_guest(page, account)
                result["rows"].append(case(page, SUBJECT, sha))
                page.get_by_role("button", name="Add to favorites", exact=True).click()
                expect(page.get_by_role("button", name="Remove from favorites", exact=True)).to_be_enabled(timeout=45000)
                assert account["favorite_write_http"] in (200, 201)
            page.goto(SITE + "/favorites", wait_until="domcontentloaded", timeout=70000)
            favorite = page.locator('a[href="/opportunities/' + SUBJECT + '"]')
            expect(favorite).to_be_visible(timeout=60000)
            assert account["favorite_select_reads"], "No successful authenticated cloud read of this saved ID"
            favorite.click()
            page.wait_for_url("**/opportunities/" + SUBJECT, timeout=45000)
            row = case(page, SUBJECT, sha, navigate=False)
            expect(page.get_by_role("button", name="Remove from favorites", exact=True)).to_be_visible(timeout=45000)
            if stage == "before":
                assert row["three_visible_papers"] == result["rows"][0]["three_visible_papers"]
            else:
                old = json.loads((receipt.parent / "before.json").read_text())
                assert old["passed"] and old["stage"] == "before"
                assert all(v["owner_hash"] == old["isolated_account"]["guest_hash"] for v in account["favorite_select_reads"])
                assert not account["signup_http"] and row["three_visible_papers"] == old["rows"][0]["three_visible_papers"]
                result["rows"].append(row)
                for key in CASES:
                    if key != SUBJECT:
                        result["rows"].append(case(page, key, sha))
            result.update(opened_from_favorites=True, stored_original_id=SUBJECT)
            ctx.close()
        assert public("/api/health")["release_sha"] == sha
        result["passed"] = True
    finally:
        receipt.write_text(json.dumps(result, indent=2) + "\n")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("before", "after"))
    parser.add_argument("profile", type=Path)
    parser.add_argument("receipt", type=Path)
    args = parser.parse_args()
    run(args.stage, args.profile, args.receipt)
