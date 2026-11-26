"""Read the named person's normal university contact field. Store only matching hashes."""
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from urllib.parse import unquote, urlsplit

from playwright.sync_api import sync_playwright

root = Path(__file__).resolve().parent
source = json.loads((root / "ling-monthly-baseline.json").read_text())
wanted = [r for r in source["rows"] if r["person_contact_field_script"]]
assert len(wanted) == 20
observed = []
with sync_playwright() as api:
    browser = api.chromium.launch()
    page = browser.new_page()
    for row in wanted:
        assert urlsplit(row["url"]).hostname == "www.linguistics.pitt.edu"
        response = page.goto(row["url"], wait_until="domcontentloaded", timeout=35000)
        assert response and response.status == 200, row["id"]
        name = page.locator("h1").first.inner_text().strip()
        assert " ".join(name.split()).casefold() == row["name"].casefold(), (name, row["name"])
        links = page.locator('.views-field-field-email a[href^="mailto:"]')
        links.first.wait_for(state="visible", timeout=5000)
        assert links.count() == 1, row["id"]
        href = links.first.get_attribute("href")
        address = unquote(href.removeprefix("mailto:")).strip().casefold()
        visible = links.first.inner_text().strip().casefold()
        assert visible == address and address.endswith("@pitt.edu"), row["id"]
        digest = sha256(address.encode()).hexdigest()[:16]
        assert [digest] == row["person_contact_field_script"], row["id"]
        observed.append({"id": row["id"], "person_heading": name, "official_url": page.url,
                         "status": response.status, "visible_address_equals_link": True,
                         "contact_field_digest": digest})
    browser.close()
assert len({row["contact_field_digest"] for row in observed}) == 20
Path("browser-results.json").write_text(json.dumps({
    "checked_at": datetime.now(timezone.utc).isoformat(), "result": "twenty named university pages",
    "rows": observed,
}, ensure_ascii=False, indent=2) + "\n")
print("20 individually visible university person fields matched their own source.")
