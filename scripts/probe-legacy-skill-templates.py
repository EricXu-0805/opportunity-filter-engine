"""Three anonymous template previews of a synthetic profile. No email delivery or model requests."""
import json
import time
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener

URL = "https://opportunity-filter-engine-api.onrender.com/api/cold-email"
TARGET = "boulder-0d8edc5782f3"


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


def check(send):
    for label, fields in (("legacy", {}), ("confirmed", {"confirmed": True}), ("reimported", {"evidenced": True})):
        skill = {"name": "PyTorch", "level": "beginner", "source": "github", **fields}
        profile = {"name": "Example Student", "year": "sophomore", "major": "Engineering",
                   "school": "University of Colorado Boulder", "hard_skills": [skill]}
        out = send({"engine": "template", "profile": profile, "opportunity_id": TARGET})
        if out.get("method") != "template" or not isinstance(out.get("body"), str) or not out["body"].strip():
            raise ValueError("no template preview")
        text = out["body"].casefold()
        count = text.count("pytorch")
        valid = (count == 0 if not fields else count > 0 and "foundational exposure to pytorch" in text)
        print(json.dumps({"case": label, "target_id": TARGET, "method": "template",
                          "skill_mentions": count, "violations": int(not valid)}), flush=True)
        if not valid:
            raise SystemExit(1)


def request(body):
    req = Request(URL, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    time.sleep(1)
    try:
        with build_opener(NoRedirect()).open(req, timeout=45) as response:
            return json.load(response)
    except HTTPError as exc:
        raise SystemExit(f"Unverified: HTTP {exc.code}") from None


if __name__ == "__main__":
    check(request)
