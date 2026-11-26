"""Walk every retirement-coded original ID through the public API router in an isolated app."""
import argparse
import json
import subprocess
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.data_loader import load_opportunities_by_id
from backend.routes.opportunities import router


def main():
    arg = argparse.ArgumentParser()
    arg.add_argument("--out", type=Path, required=True)
    args = arg.parse_args()
    app = FastAPI()
    app.include_router(router, prefix="/api")
    client = TestClient(app)
    scope = "mvp-core-close-v1-contact-trust-v1-faculty-trust-v1-target-truth-v2"
    reasons = Counter()
    shown, omitted = [], []
    for oid, raw in load_opportunities_by_id().items():
        metadata = raw.get("metadata") or {}
        reason = metadata.get("deactivation_reason")
        if (raw.get("source_type") != "faculty_research" or metadata.get("is_active") is not False
                or reason not in ("retired_title", "listed_as_retired", "listed_as_emeritus")):
            continue
        response = client.get("/api/opportunities/" + oid, params={"_release_scope": scope})
        response.raise_for_status()
        detail = response.json()
        assert detail["id"] == oid and detail["target_truth"]["reason_code"] == "inactive"
        assert detail["contact_email_status"] == "unavailable"
        reasons[reason] += 1
        fact = detail.get("historical_faculty_appointment")
        if fact is None:
            omitted.append(oid)
            continue
        observed = (metadata.get("faculty_title_observation") or {}).get("source")
        reviewed = (metadata.get("faculty_profile_review") or {}).get("source_url")
        assert fact["source_url"] in (observed, reviewed) and fact["title"] == metadata["faculty_title"]
        shown.append({"id": oid, "name": detail["pi_name"], "title": fact["title"],
                      "source_url": fact["source_url"], "profile_url": detail["url"]})
    receipt = {"when": datetime.now(UTC).isoformat(),
               "checked_candidate": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
               "environment": "local production dataset and public FastAPI router in a test app",
               "archived_original_ids": sum(reasons.values()), "archive_reasons": reasons,
               "with_verified_historical_appointment": shown, "without_bound_title_evidence": omitted,
               "all_contact_email_status_unavailable": True}
    args.out.write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + "\n")
    print(f"{sum(reasons.values())} archived original IDs, {len(shown)} with a cited title, {len(omitted)} withheld")


if __name__ == "__main__":
    main()
