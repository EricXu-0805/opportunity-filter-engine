"""Check the actual B23 merge and both live app versions before opening a visitor."""
import argparse
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.request import urlopen

SITE = "https://joinalab.com"
REPO = "EricXu-0805/opportunity-filter-engine"
PR = "1486"


def live_versions():
    with urlopen(SITE + "/about", timeout=50) as response:
        match = re.search(rb'data-release-sha="([a-f0-9]{40})"', response.read())
    with urlopen(SITE + "/api/health", timeout=50) as response:
        backend = json.load(response)["release_sha"]
    return [match[1].decode() if match else None, backend]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--request", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--environment", type=Path)
    args = parser.parse_args()
    request = json.loads(args.request.read_text())
    sha, scope = request["release_sha"], request["release_scope"]
    if not re.fullmatch(r"[a-f0-9]{40}", sha) or not re.fullmatch(r"[a-zA-Z0-9_.-]{1,120}", scope):
        raise ValueError("Invalid release SHA or product truth scope")
    merged = json.loads(subprocess.check_output([
        "gh", "pr", "view", PR, "--repo", REPO, "--json", "state,mergeCommit,baseRefName",
    ]))
    if (merged["state"] != "MERGED" or merged["baseRefName"] != "main" or
            (merged.get("mergeCommit") or {}).get("oid") != sha):
        raise ValueError("The requested SHA must be the real B23 merge to main")
    versions = live_versions()
    args.out.write_text(json.dumps({"checked_at": datetime.now(timezone.utc).isoformat(),
                                    "pr": PR, "github_merge": sha, "front_and_back": versions}, indent=2) + "\n")
    if versions != [sha, sha]:
        raise ValueError(f"Wait for the same B23 build on both public services: {versions}")
    if args.environment:
        with args.environment.open("a") as output:
            print(f"PUBLIC_SHA={sha}\nPUBLIC_TRUTH_SCOPE={scope}", file=output)


if __name__ == "__main__":
    main()
