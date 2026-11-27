"""Exercise one browser-local interrupted GET and its actual retry on an owned résumé."""
import json
import os
from datetime import datetime, timezone
from hashlib import sha256
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from playwright.sync_api import expect, sync_playwright

import verify_public_matching_experience as shared
from verify_deployed_m39_supplement import stable_read, tab

TITLE = "Fictional field ledger exercise"
TASK = "I organized the fictional specimen observations for this audit."
OMITTED = "The example team summarized the fictional display results."
TARGET_PATH = "/rest/v1/target_resumes"
SAVE_PATH = "/rest/v1/rpc/commit_target_resume_with_provenance_cas"
PROFILE_PATH = "/rest/v1/rpc/commit_profile_patch_cas"
report = {"expected_release": shared.release, "target": shared.target, "stage": "initializing",
          "browser_local_get_failures": 0, "target_saves": [], "steps": []}


def stamp():
    return datetime.now(timezone.utc).isoformat()


def step(label):
    report["steps"].append({"event": label, "utc": stamp()})
    report["stage"] = label
    print(label, flush=True)


def owned_get(request):
    url = urlsplit(request.url)
    if request.method != "GET" or url.hostname != shared.db or url.path != TARGET_PATH:
        return False
    params = parse_qs(url.query)
    assert shared.auth and params["owner_id"] == ["eq." + shared.auth[0]["user"]["id"]]
    assert params["opportunity_id"] == ["eq." + shared.target]
    return True


def guard(route):
    request = route.request
    url = urlsplit(request.url)
    if url.hostname == shared.db and request.method == "POST" and url.path == SAVE_PATH:
        body = request.post_data_json
        assert body.get("p_expected_owner") == shared.auth[0]["user"]["id"]
        assert body.get("p_opportunity_id") == shared.target and TITLE in request.post_data
        assert not report["target_saves"]
        return route.continue_()
    if url.hostname == shared.site.split("//")[1] and request.method == "POST" and url.path != "/api/matches/view":
        return route.abort()
    return shared.guard(route)


def cloud_profile(browser):
    ctx = shared.cold(browser)
    ctx.route("**/*", guard)
    try:
        _, snapshot = stable_read(ctx)
        return snapshot
    finally:
        ctx.close()


def version_pair(check):
    backend = check.get(shared.site + "/api/health", timeout=40000).json()["release_sha"]
    about = check.get(shared.site + "/about", timeout=40000).text()
    assert backend == shared.release and f'data-release-sha="{shared.release}"' in about, "release pair is not the requested deployment"
    return {"frontend": shared.release, "backend": backend, "utc": stamp()}


def doc_receipt(response):
    assert response.status == 200 and owned_get(response.request)
    data = response.json()
    if isinstance(data, list):
        assert len(data) == 1
        data = data[0]
    body = data["doc"]
    assert body["opportunity_id"] == shared.target and TITLE in json.dumps(body)
    encoded = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode()
    return {"http": response.status, "revision": data["revision"], "stored_doc_sha256": sha256(encoded).hexdigest()}


def run():
    with sync_playwright() as pw:
        probe = pw.request.new_context()
        report["initial_pair"] = version_pair(probe)
        browser = pw.chromium.launch(channel="chrome", args=["--no-sandbox", "--disable-dev-shm-usage"])
        existing = shared.cold(browser)
        existing.route("**/*", guard)
        home = shared.home(existing)
        home.locator("#student_name").fill(shared.student)
        home.locator("#college").select_option(label="Liberal Arts & Sciences (LAS)")
        home.locator("#major").select_option(label="Integrative Biology")
        home.locator("#grade").select_option(label="Sophomore")
        editor = home.get_by_test_id("resume-master-editor")
        editor.locator(":scope > summary").click()
        editor.get_by_label("Full name", exact=True).fill("Robin Fictional Observer")
        editor.get_by_role("button", name="Confirm Full name", exact=True).click()
        editor.get_by_role("button", name="Add experience or project").click()
        editor.get_by_label("Role / project title", exact=True).fill(TITLE)
        editor.get_by_role("button", name="Confirm Role / project title").click()
        with home.expect_response(lambda r: urlsplit(r.url).path == PROFILE_PATH and r.ok and TITLE in (r.request.post_data or ""), timeout=60000):
            editor.get_by_role("button", name="Apply changes").click()
        before, profile = cloud_profile(browser)
        activity = profile["resume_master"]["activities"][0]
        assert activity["title"]["value"] == TITLE and activity["title"]["status"] == "confirmed"
        assert profile["resume_master"]["basics"]["name"]["status"] == "confirmed"
        assert not profile.get("experience_entries")
        step("confirmed synthetic master project on the dedicated anonymous account")
        existing.close()
        existing = shared.cold(browser)
        existing.route("**/*", guard)
        _, hydrated = stable_read(existing)
        assert hydrated[0] == before and hydrated[1]["resume_master"] == profile["resume_master"]
        page, dialog = tab(existing)
        create = dialog.get_by_role("button", name="Create from confirmed master")
        try:
            create.click(timeout=30000)
        except Exception:
            report["target_creation_diagnostic"] = {"button_enabled": create.is_enabled(),
                "feature_status": dialog.locator('[role="alert"],[role="status"]').all_inner_texts()[:5],
                "content_hints": [x for x in dialog.locator("p").all_inner_texts() if "master" in x.lower() or "availab" in x.lower()][:6]}
            raise
        with page.expect_response(lambda r: urlsplit(r.url).path == SAVE_PATH, timeout=60000) as saving:
            dialog.get_by_role("button", name="Save target draft", exact=True).click(timeout=60000)
        save = saving.value
        assert save.ok and save.json()["status"] == "saved" and save.json()["revision"] == 1
        report["target_saves"].append({"http": save.status, "revision": 1})
        expect(dialog.get_by_text("Saved version 1", exact=True)).to_be_visible(timeout=60000)
        existing.close()
        step("saved target version one with a real owner-scoped cloud acknowledgement")
        ctx = shared.cold(browser)
        ctx.route("**/*", guard)

        # The deployed PostgREST client automatically retries one immediate socket
        # failure. Hold exactly one owned GET instead. Its real 30-second
        # deadline aborts the read in the browser, without a fake HTTP response.
        held = []
        failed_gets = []
        ctx.on("requestfailed", lambda r: failed_gets.append(r.failure) if owned_get(r) else None)

        def interrupt(route):
            if owned_get(route.request) and report["browser_local_get_failures"] == 0:
                report["browser_local_get_failures"] += 1
                held.append(route)
                report["intercepted_at"] = stamp()
                return
            return route.fallback()

        ctx.route("**/rest/v1/target_resumes?**", interrupt)
        p, d = tab(ctx)
        retry = d.get_by_role("button", name="Retry reading saved résumé", exact=True)
        expect(retry).to_be_visible(timeout=65000)
        assert len(held) == 1
        report["local_timeout_ui_at"] = stamp()
        d.get_by_role("button", name="Add experience details").click()
        panel = d.get_by_test_id("resume-supplement-panel")
        selection = panel.get_by_label("Project or experience in your master résumé")
        selection.select_option(label=TITLE)
        task = panel.get_by_label("What was the task?", exact=True)
        other = panel.get_by_label("What was the outcome, if known?", exact=True)
        task.fill(TASK)
        other.fill(OMITTED)
        panel.get_by_label("Include task", exact=True).check()
        panel.get_by_label("Include outcome", exact=True).uncheck()
        confirm = panel.get_by_role("button", name="Confirm and add to my master résumé")
        expect(confirm).to_be_disabled()
        report["browser_fault"] = {"method": "GET", "path": TARGET_PATH, "owner_and_target_filtered": True,
                                   "held_one_browser_get_without_sending_it_to_the_origin": True,
                                   "deployed_read_timeout_ms": 30000, "observed_request_failures": list(failed_gets),
                                   "error_control_visible": True}
        step("entered two unconfirmed answers in the failed-read form")
        with p.expect_response(lambda r: owned_get(r.request), timeout=60000) as resumed:
            retry.click()
        report["real_retry"] = doc_receipt(resumed.value)
        expect(d.get_by_text("Saved version 1", exact=True)).to_be_visible(timeout=60000)
        expect(task).to_have_value(TASK)
        expect(other).to_have_value(OMITTED)
        expect(selection).to_have_value(activity["id"])
        expect(panel.get_by_label("Include task", exact=True)).to_be_checked()
        expect(panel.get_by_label("Include outcome", exact=True)).not_to_be_checked()
        expect(confirm).to_be_disabled()
        pending, unconfirmed = cloud_profile(browser)
        assert pending == before and not unconfirmed.get("experience_entries")
        assert TASK not in json.dumps(unconfirmed) and OMITTED not in json.dumps(unconfirmed)
        report["before_confirmation"] = {"baseline_profile_revision": before, "after_retry_profile_revision": pending,
             "saved_target_revision": report["real_retry"]["revision"], "retained_form_answers": [TASK, OMITTED],
             "same_selected_project": True, "included_task": True, "included_outcome": False,
             "confirmation_still_required": True, "answers_absent_in_fresh_cloud_read": True}
        step("real 200 restored the saved target and retained both local answers without a cloud write")
        panel.get_by_label("I confirm the selected information is accurate.", exact=True).check()
        with p.expect_response(lambda r: urlsplit(r.url).path == PROFILE_PATH and r.ok and TASK in (r.request.post_data or ""), timeout=60000) as ack:
            confirm.click()
        assert ack.value.json()["status"] == "applied"
        expect(panel.get_by_role("button", name="Added to master résumé")).to_be_visible(timeout=60000)
        after, checked = cloud_profile(browser)
        assert after == pending + 1 == ack.value.json()["revision"]
        entries = checked["experience_entries"]
        assert len(entries) == 1 and TASK in entries[0]["text"] and OMITTED not in json.dumps(checked)
        assert checked["resume_master"]["activities"][0]["details"] == [{"id": entries[0]["id"], "revision": entries[0]["revision"]}]
        ctx.close()
        clean = shared.cold(browser)
        clean.route("**/*", guard)
        real_docs = []
        clean.on("response", lambda r: real_docs.append(doc_receipt(r)) if owned_get(r.request) and r.ok else None)
        _, saved = tab(clean)
        expect(saved.get_by_text("Saved version 1", exact=True)).to_be_visible(timeout=60000)
        assert real_docs and real_docs[-1] == report["real_retry"]
        report["after_confirmation"] = {"profile_revision": after, "saved_target": real_docs[-1],
                                        "selected_answer_confirmed": True, "unselected_answer_absent": True}
        clean.close()
        assert report["browser_local_get_failures"] == 1 and len(report["target_saves"]) == 1
        report["final_pair"] = version_pair(probe)
        step("confirmed only the selected answer and re-read unchanged target version one")
        report["passed"] = True
        browser.close()


if __name__ == "__main__":
    try:
        run()
    finally:
        report["finished_at"] = stamp()
        Path(os.environ["OFE_M39_RESULT"]).write_text(json.dumps(report, indent=2) + "\n")
