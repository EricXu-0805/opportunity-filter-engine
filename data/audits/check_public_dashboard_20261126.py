"""Verify the real Dashboard-to-Favorites recovery link in a clean synthetic guest."""
import json
import os
import re
from pathlib import Path
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

LANG = os.environ["CHECK_LANGUAGE"]
SITE = "https://joinalab.com"
COPY = {
    "en": ("Could not check deadlines saved in this browser.", "Review browser imports in Favorites"),
    "zh": ("未能读取此浏览器中保存的截止日期。", "前往收藏页查看本机导入的机会"),
}
message, label = COPY[LANG]
record = {"expected_frontend_sha": "0741df3be2d6ccd50e40789f0833f9d21dd0d041", "language": LANG, "site": SITE, "signup": False, "real_favorites_read": False}

def observe(response):
    url = urlsplit(response.url)
    if not (url.hostname or "").endswith(".supabase.co"): return
    if url.path == "/auth/v1/signup" and response.status == 200:
        record["signup"] = True
    if url.path == "/rest/v1/favorites" and response.status == 200:
        record["real_favorites_read"] = True

Path("evidence").mkdir(exist_ok=True)
with sync_playwright() as pw:
    browser = pw.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
    context = browser.new_context(locale="en-US", service_workers="block")
    page = context.new_page()
    page.set_default_timeout(20000)
    page.on("response", observe)
    try:
        response = page.goto(SITE + "/dashboard", wait_until="domcontentloaded")
        assert response.status == 200
        for _ in range(100):
            page.wait_for_timeout(250)
            if record["signup"] and record["real_favorites_read"]: break
        assert record["signup"] and record["real_favorites_read"]
        intro = page.get_by_test_id("onboarding-intro")
        if intro.is_visible():
            page.get_by_test_id("onboarding-skip").click()
            page.get_by_test_id("onboarding-school-uiuc").click()
            page.get_by_test_id("onboarding-primary").click()
            expect(intro).not_to_be_visible(timeout=20000)
        if LANG == "zh":
            page.get_by_role("button", name="切换到中文", exact=True).click()
        expect(page.locator("html")).to_have_attribute("lang", re.compile("^" + LANG))
        # Operate solely on a new guest's browser. Refuse to replace a populated store.
        page.evaluate("""() => {
          const key='ofe_custom_imports';
          const old=localStorage.getItem(key);
          if (old!==null && old!=='[]') throw Error('expected an empty local import list');
          localStorage.setItem(key, '{synthetic-invalid-json');
        }""")
        page.reload(wait_until="domcontentloaded")
        notice = page.get_by_role("status").filter(has_text=message).filter(has=page.get_by_role("link", name=label, exact=True))
        expect(notice).to_be_visible(timeout=35000)
        link = notice.get_by_role("link", name=label, exact=True)
        expect(link).to_have_attribute("href", "/favorites")
        notice.screenshot(path=f"evidence/dashboard-{LANG}.png", animations="disabled")
        if page.get_by_test_id("switcher-confirm").is_visible():
            page.keyboard.press("Escape")
        link.click()
        page.wait_for_url("**/favorites", timeout=30000)
        expect(page.locator("main h1").first).to_be_visible()
        record.update(message=message, link_label=label, destination=urlsplit(page.url).path)
    finally:
        print("PUBLIC RECEIPT", json.dumps(record, ensure_ascii=False))
        browser.close()
