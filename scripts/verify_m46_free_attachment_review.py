"""Audit the free draft's final check and backup on a purpose-created guest without opening a composer."""
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright
import verify_public_matching_experience as shared

CLAIM = "I have attached a copy of my CV."
CONTROL = "I have attached my CV."
OFFER = "I can send a copy of my CV if helpful."
SUBJECT = "Synthetic inquiry on field observations"
report = {"target": shared.target, "validations": [], "opened_popups": 0, "external_composers_opened": 0,
          "confirmed_deliveries": 0, "paid_requests": 0, "skipped_provider_authorization": True}
now = lambda: datetime.now(timezone.utc).isoformat()


def sha(text):
    return hashlib.sha256(text.encode()).hexdigest()


def releases(context):
    backend = context.get(shared.site + "/api/health", timeout=35000).json()["release_sha"]
    about = context.get(shared.site + "/about", timeout=35000).text()
    front = re.search(r'data-release-sha="([a-f0-9]{40})"', about).group(1)
    assert front == backend
    return {"frontend": front, "backend": backend, "utc": now()}


def run():
    with sync_playwright() as pw:
        probe = pw.request.new_context()
        report["start_release"] = releases(probe)
        browser = pw.chromium.launch(channel="chrome", args=["--no-sandbox", "--disable-dev-shm-usage"])
        ctx = shared.cold(browser)
        ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin=shared.site)
        lost = {"validation": False}
        generated = []
        seen = {"paid": 0, "mail": 0, "confirm": 0}

        def protect(route):
            req = route.request
            url = urlsplit(req.url)
            if url.hostname == "joinalab.com" and req.method == "POST":
                if url.path == "/api/cold-email/variants":
                    body = req.post_data_json
                    assert body.get("opportunity_id") == shared.target
                    assert body.get("engine", "template") == "template"
                    return route.continue_()
                if url.path == "/api/cold-email/validate":
                    data = req.post_data_json
                    assert data["opportunity_id"] == shared.target and data["subject"] == SUBJECT
                    if lost["validation"]:
                        lost["validation"] = False
                        return route.abort("internetdisconnected")
                    return route.continue_()
                if url.path != "/api/matches/view":
                    seen["paid"] += int("/tailor" in url.path or "/refine" in url.path or "/billing" in url.path)
                    seen["confirm"] += int("send" in url.path or "interaction" in url.path)
                    return route.abort()
            if url.hostname not in {"joinalab.com", shared.db}:
                seen["mail"] += int(req.is_navigation_request())
                return route.abort()
            return shared.guard(route)

        ctx.route("**/*", protect)
        home = shared.home(ctx)
        home.locator("#student_name").fill(shared.student)
        home.locator("#college").select_option(label="Liberal Arts & Sciences (LAS)")
        home.locator("#major").select_option(label="Integrative Biology")
        home.locator("#grade").select_option(label="Sophomore")
        # Apply an ordinary profile revision first so a fresh target page reads the synthetic identity.
        editor = home.get_by_test_id("resume-master-editor")
        editor.locator(":scope > summary").click()
        editor.get_by_label("Full name", exact=True).fill("Rowan Fictional Observer")
        editor.get_by_role("button", name="Confirm Full name", exact=True).click()
        with home.expect_response(lambda r: urlsplit(r.url).path == "/rest/v1/rpc/commit_profile_patch_cas" and r.ok, timeout=60000):
            editor.get_by_role("button", name="Apply changes").click()
        report["guest"] = {"self_created_anonymous": bool(shared.auth and shared.auth[0]["user"]["is_anonymous"]),
                           "scoped_profile_acknowledged": True}
        p = ctx.new_page()
        p.on("popup", lambda popup: (report.update(opened_popups=report["opened_popups"] + 1), popup.close()))

        def response(r):
            if urlsplit(r.url).path == "/api/cold-email/variants" and r.ok:
                v = r.json()
                generated.append({"count": len(v["variants"]), "method": v["variants"][0]["method"]})
        p.on("response", response)
        p.goto(shared.site + "/opportunities/" + shared.target, wait_until="domcontentloaded")
        p.get_by_role("button", name="Draft email", exact=True).click(timeout=60000)
        for _ in range(170):
            if generated:
                break
            regen = p.get_by_role("button", name="Regenerate from updated materials", exact=True)
            if regen.is_visible():
                regen.click()
            p.wait_for_timeout(250)
        assert generated and generated[-1]["count"] == 3 and generated[-1]["method"] == "template"
        report["free_variants"] = generated[-1]
        subject = p.locator("#cold-email-subject")
        body = p.locator("#cold-email-body")
        copy = p.get_by_role("button", name="Copy", exact=True)
        subject.fill(SUBJECT)

        def clipboard():
            return p.evaluate("navigator.clipboard.readText()")

        def run_check(label, message):
            body.fill(message)
            with p.expect_response(lambda r: urlsplit(r.url).path == "/api/cold-email/validate" and r.request.post_data_json["body"] == message, timeout=60000) as event:
                copy.click()
            r = event.value
            v = r.json()
            assert r.status == 200 and v["opportunity_id"] == shared.target
            entry = {"case": label, "subject": SUBJECT, "body": message, "http": r.status, "outcome": v["outcome"],
                     "issues": v["issues"], "checked_exact_hand_edit": True, "utc": now()}
            report["validations"].append(entry)
            expect(body).to_have_value(message)
            return entry

        blocked = run_check("direct_unconfirmed_attachment", CONTROL)
        assert blocked["outcome"] == "review_required" and "unsupported_attachment_claim" in blocked["issues"]
        expect(p.get_by_text("The draft claims files are attached. No attachment has been confirmed here.")).to_be_visible()
        p.get_by_test_id("copy-draft-only").click()
        expected = "Subject: " + SUBJECT + "\n\n" + CONTROL
        assert clipboard() == expected
        report["flagged_backup"] = {"exact_subject_and_body": True, "sha256": sha(expected), "draft_preserved": True}

        missing = run_check("definitive_copy_of_document", CLAIM)
        if missing["outcome"] == "ready":
            expect(p.get_by_role("button", name="Copied!", exact=True).or_(p.get_by_role("button", name="Copied", exact=True))).to_be_visible(timeout=8000)
            expected = "Subject: " + SUBJECT + "\n\n" + CLAIM
            assert clipboard() == expected
            missing["ordinary_checked_copy_succeeded"] = True
        else:
            assert "unsupported_attachment_claim" in missing["issues"]
        offer = run_check("offer_only", OFFER)
        assert offer["outcome"] == "ready" and not offer["issues"]
        error_text = "I can provide a writing sample if helpful."
        body.fill(error_text)
        lost["validation"] = True
        copy.click()
        expect(p.get_by_text("The check did not finish. Your draft is kept. Retry, or use Copy draft only to keep a backup.")).to_be_visible(timeout=60000)
        expect(body).to_have_value(error_text)
        p.get_by_test_id("copy-draft-only").click()
        expected = "Subject: " + SUBJECT + "\n\n" + error_text
        assert clipboard() == expected
        report["offline_backup"] = {"browser_local_single_failed_validation": True, "draft_preserved": True,
                                    "exact_subject_and_body": True, "sha256": sha(expected)}
        assert report["opened_popups"] == 0 and all(n == 0 for n in seen.values())
        report["end_release"] = releases(probe)
        assert report["end_release"]["backend"] == report["start_release"]["backend"]
        report["evidence_complete"] = True
        ctx.close()
        browser.close()


if __name__ == "__main__":
    try:
        run()
    finally:
        report["finished_at"] = now()
        Path(os.environ["M46_RESULT"]).write_text(json.dumps(report, indent=2) + "\n")
