"""Run one production acceptance check against a stable deployed backend version."""
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from urllib.request import Request, urlopen

SITE = "https://joinalab.com"
REQUIRED = "bcc2c40ef1623d412c73ee0ef3647bbe449b9ecd"
SCOPE = "mvp-core-close-v1-contact-trust-v1-faculty-trust-v1-target-truth-v2"


def read(path):
    sep = "&" if "?" in path else "?"
    request = Request(SITE + path + sep + "verify=" + str(time.time_ns()), headers={"Cache-Control": "no-cache"})
    with urlopen(request, timeout=35) as response:
        return response.read()


def release():
    sha = json.loads(read("/api/health"))["release_sha"]
    if not re.fullmatch(r"[0-9a-f]{40}", sha):
        raise ValueError("Missing production release SHA")
    return sha


def publications():
    from playwright.sync_api import expect, sync_playwright

    cases = {
        "faculty-asu-ece-36055db6": (["composite finger seal", "MHD Simulation"], []),
        "faculty-tamu-mays-2157ba4d": (["Load Forecasting Using MSTL"], ["New Insights on Workplace Mistreatment"]),
    }
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        page = browser.new_page()
        for oid, (removed, retained) in cases.items():
            path = "/opportunities/" + oid + "?_release_scope=" + SCOPE
            data = json.loads(read("/api" + path))
            assert data["id"] == oid
            page.goto(SITE + path, wait_until="domcontentloaded")
            expect(page.get_by_role("heading", level=1)).to_contain_text(data["pi_name"], timeout=30000)
            titles = " ".join(work["title"] for work in data["metadata"].get("recent_works", []))
            visible = page.locator("main").inner_text()
            for text in removed:
                assert all(text.casefold() not in source.casefold() for source in (titles, visible)), (oid, text)
            for text in retained:
                assert all(text.casefold() in source.casefold() for source in (titles, visible)), (oid, text)
            print("PASS", oid, "removed", removed, "retained", retained, "frontend",page.locator("html").get_attribute("data-release-sha"),flush=True)
        browser.close()


if __name__ == "__main__":
    check = sys.argv[1]
    observed = release()
    if check == "readiness":
        comparison = subprocess.check_output(
            ["gh", "api", f"repos/{os.environ['GITHUB_REPOSITORY']}/compare/{REQUIRED}...{observed}", "--jq", ".status"],
            text=True,
        ).strip()
        ready = comparison in {"ahead", "identical"}
        print("Render", observed, "compared with required", REQUIRED, comparison, "ready", ready, flush=True)
        with Path(os.environ["GITHUB_OUTPUT"]).open("a") as output:
            print("ready=" + str(ready).lower(), file=output)
            print("release=" + observed, file=output)
    else:
        assert observed == os.environ["EXPECTED_RELEASE"], (observed, os.environ["EXPECTED_RELEASE"])
        if check == "publications":
            publications()
        else:
            subprocess.run([sys.executable, "-u", "scripts/verify_public_outreach_paths.py", check], check=True)
        assert release() == observed, "Render changed during the observation"
        print("PASS stable backend", observed, check, flush=True)
