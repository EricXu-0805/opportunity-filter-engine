"""Use the original four-person browser scenario once B25 is actually public."""
import json
import os
import re
import subprocess
from pathlib import Path

REPO = "EricXu-0805/opportunity-filter-engine"
SOURCE = "dbd0c8b41cfb70cc8bd622b5e26dcf6893745fae"
release = json.loads(Path(__file__).with_name("release-request.json").read_text())["release_sha"]
assert re.fullmatch("[0-9a-f]{40}", release)
pr = json.loads(subprocess.check_output([
    "gh", "pr", "view", "1494", "--repo", REPO, "--json", "state,baseRefName,mergeCommit",
]))
assert pr["state"] == "MERGED" and pr["baseRefName"] == "main" and pr["mergeCommit"]["oid"] == release
comparison = subprocess.check_output([
    "gh", "api", f"repos/{REPO}/compare/{SOURCE}...{release}", "--jq", ".status",
], text=True).strip()
assert comparison in ("ahead", "identical"), comparison
os.environ["CANDIDATE"] = release
import check as original

original.SITE = original.base.SITE = "https://joinalab.com"
original.result["environment"] = "public frontend, account database and same-release API"
original.result["source"] = SOURCE
assert list(original.base.version().values()) == [release, release]
try:
    original.run()
    assert len(original.result["rows"]) == 4
    assert all(original.result["account"].get(k) == v for k, v in [("signup", 200), ("profile_commit", "applied")])
    assert list(original.result["end"].values()) == [release, release]
finally:
    original.save()
