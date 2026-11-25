"""Provision or verify the private version bucket through the supported Storage API."""
import os

import httpx

BUCKET = "tracker-attachment-versions"
MIME = sorted(("application/pdf", "image/png", "image/jpeg", "image/webp", "image/gif",
               "application/vnd.openxmlformats-officedocument.wordprocessingml.document", "text/plain", "text/markdown"))


def main() -> None:
    endpoint = os.environ["SUPABASE_URL"].rstrip("/") + "/storage/v1/bucket"
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    headers = {"apikey": key, "Authorization": "Bearer " + key}
    with httpx.Client(headers=headers, timeout=15, follow_redirects=False, trust_env=False) as client:
        found = client.get(f"{endpoint}/{BUCKET}")
        if found.status_code in (400, 404) and found.json().get("statusCode") in ("404", 404):
            created = client.post(endpoint, json={"id": BUCKET, "name": BUCKET, "public": False,
                                                  "file_size_limit": 5242880, "allowed_mime_types": MIME})
            created.raise_for_status()
            found = client.get(f"{endpoint}/{BUCKET}")
        found.raise_for_status()
        bucket = found.json()
        if (bucket.get("id") != BUCKET or bucket.get("public") is not False
                or bucket.get("file_size_limit") != 5242880 or sorted(bucket.get("allowed_mime_types") or []) != MIME):
            raise ValueError("Existing version bucket does not match its required private configuration")
    print("Verified private tracker attachment version bucket")


if __name__ == "__main__":
    main()
