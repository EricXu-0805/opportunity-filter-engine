"""Read the normal sign-in dialog without selecting a provider or sending mail."""
from datetime import datetime, timezone
import json
import re

from playwright.sync_api import sync_playwright


def check_login():
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        page = browser.new_page(locale="en-US")
        response = page.goto("https://joinalab.com/auth/sign-in", wait_until="domcontentloaded")
        assert response.status == 200
        google = page.get_by_test_id("auth-provider-google")
        google.wait_for(state="visible", timeout=45000)
        microsoft_count = page.get_by_test_id("auth-provider-azure").count()
        assert microsoft_count == 0
        released = page.locator("[data-release-sha]").first.get_attribute("data-release-sha")
        assert re.fullmatch(r"[a-f0-9]{40}", released or "")
        print(json.dumps({
            "observed_at": datetime.now(timezone.utc).isoformat(),
            "release": released, "url": page.url, "http": response.status,
            "google_visible": google.is_visible(), "microsoft_buttons": microsoft_count,
            "provider_buttons_clicked": 0,
        }))
        browser.close()


if __name__ == "__main__":
    check_login()
