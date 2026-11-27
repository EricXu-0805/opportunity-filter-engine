"""Verify both published Summer Lab bookmarks using one newly created guest."""
import json
import os
import time
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

import verify_public_matching_experience as shared
from verify_deployed_b15_keyboard import check_deployment

ORIGINALS = ("uchicago-8cd2def060b6", "sro-d6b78515")
OUTPUT = Path(os.environ["RUNNER_TEMP"]) / "dsi-saved-originals.json"


def watch_context(browser, observations):
    context = shared.cold(browser)

    def permit_own_bookmark(route):
        request = route.request
        url = urlsplit(request.url)
        if url.hostname != shared.db or url.path != "/rest/v1/favorites" or request.method != "POST":
            return route.fallback()
        post = request.post_data_json
        if shared.auth and isinstance(post, dict) and post.get("device_id") == shared.auth[0]["user"]["id"] and post.get("opportunity_id") in ORIGINALS:
            return route.continue_()
        return route.abort()

    def record(response):
        url = urlsplit(response.url)
        request = response.request
        if url.hostname != shared.db or url.path != "/rest/v1/favorites":
            return
        if request.method == "GET" and response.ok:
            ids = sorted(row["opportunity_id"] for row in response.json())
            assert set(ids).issubset(ORIGINALS)
            observations["server_reads"].append(ids)
        if request.method == "POST":
            observations["saved"].append({"original": request.post_data_json["opportunity_id"], "status": response.status})

    context.route("**/rest/v1/favorites*", permit_own_bookmark)
    context.on("response", record)
    return context


def run(browser):
    receipt = {"release": shared.release, "saved": [], "server_reads": [], "reopened": []}
    try:
        context = watch_context(browser, receipt)
        page = shared.home(context)
        assert len(shared.auth) == 1
        titles = {}
        for original in ORIGINALS:
            page.goto(shared.site + "/opportunities/" + original, wait_until="domcontentloaded")
            title = page.get_by_role("heading", level=1)
            expect(title).to_contain_text("Summer Lab", timeout=45000, ignore_case=True)
            titles[original] = title.inner_text()
            with page.expect_response(lambda r: urlsplit(r.url).path == "/rest/v1/favorites" and r.request.method == "POST" and r.request.post_data_json.get("opportunity_id") == original, timeout=45000) as saved:
                page.get_by_role("button", name="Add to favorites", exact=True).click()
            assert saved.value.ok, saved.value.status
            active = page.get_by_role("button", name="Remove from favorites", exact=True)
            expect(active).to_be_enabled()
            expect(active).to_have_attribute("aria-busy", "false")
        assert len(receipt["saved"]) == 2
        context.close()
        receipt["server_reads_before_new_context"] = len(receipt["server_reads"])
        clean = watch_context(browser, receipt)
        page = clean.new_page()
        for original in ORIGINALS:
            page.goto(shared.site + "/favorites", wait_until="domcontentloaded")
            link = page.locator(f'a[href="/opportunities/{original}"]').first
            expect(link).to_be_visible(timeout=60000)
            expect(link).to_contain_text("Summer Lab", ignore_case=True)
            link.click()
            page.wait_for_url(shared.site + "/opportunities/" + original)
            expect(page.get_by_role("heading", level=1)).to_have_text(titles[original])
            expect(page.get_by_role("button", name="Remove from favorites", exact=True)).to_be_enabled(timeout=45000)
            receipt["reopened"].append({"id": original, "title": titles[original], "page_release": page.locator("html").get_attribute("data-release-sha")})
        assert sorted(ORIGINALS) in receipt["server_reads"][receipt["server_reads_before_new_context"]:]
        assert all(row["page_release"] == shared.release for row in receipt["reopened"])
        assert len(shared.auth) == 1
        receipt["fresh_browser_restored_same_guest"] = True
        clean.close()
        check_deployment(shared.release)
        receipt["completed"] = True
    finally:
        OUTPUT.write_text(json.dumps(receipt, indent=2) + "\n")


if __name__ == "__main__":
    for attempt in range(12):
        try:
            check_deployment(shared.release)
            break
        except (AssertionError, OSError):
            if attempt == 11:
                raise
            time.sleep(30)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        run(browser)
        browser.close()
