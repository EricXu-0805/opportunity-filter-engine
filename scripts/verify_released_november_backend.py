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
    from bs4 import BeautifulSoup

    cases = {
        "faculty-asu-ece-36055db6": (["composite finger seal", "MHD Simulation"], []),
        "faculty-tamu-mays-2157ba4d": (["Load Forecasting Using MSTL"], ["New Insights on Workplace Mistreatment"]),
    }
    for oid, (removed, retained) in cases.items():
        path = "/opportunities/" + oid + "?_release_scope=" + SCOPE
        data = json.loads(read("/api" + path))
        assert data["id"] == oid
        page = BeautifulSoup(read(path), "html.parser")
        assert page.select_one("h1") and data["pi_name"].casefold() in page.select_one("h1").get_text(" ",strip=True).casefold()
        titles = " ".join(work["title"] for work in data["metadata"].get("recent_works", []))
        visible = page.select_one("main").get_text(" ", strip=True)
        for text in removed:
            assert all(text.casefold() not in source.casefold() for source in (titles, visible)), (oid, text)
        for text in retained:
            assert all(text.casefold() in source.casefold() for source in (titles, visible)), (oid, text)
        print("PASS", oid, "removed", removed, "retained", retained, "frontend",page.html.get("data-release-sha"),flush=True)


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
