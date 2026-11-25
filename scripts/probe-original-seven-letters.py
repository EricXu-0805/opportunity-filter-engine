"""Verify the seven original synthetic email previews. No authentication or delivery."""
import json
import time
from urllib.request import Request, urlopen

API = "https://opportunity-filter-engine-api.onrender.com/api"
IDS = ["faculty-mit-math-c77d7010","faculty-duke-bio-8ac60eca","faculty-ucb-stat-58582c90","faculty-amherst-biol-755f25b2","faculty-arizona-cs-0765053d","faculty-asu-cs-c5e431b9","faculty-boulder-aero-2c2b0784"]
SENTENCE = "I am interested in condensed matter physics, evolutionary biology, and planetary science."
PROFILE = {"name":"Audit Student","year":"sophomore","major":"Physics","school":"UIUC","research_interests_text":"condensed matter physics, evolutionary biology, planetary science"}

def read(path, data=None):
    body = None if data is None else json.dumps(data).encode()
    with urlopen(Request(API + path, data=body, headers={"Content-Type":"application/json", "User-Agent":"JoinALab public acceptance"}), timeout=45) as response:
        return json.load(response)

print("health", read("/health").get("release_sha"), flush=True)
for rid in IDS:
    result = read("/cold-email", {"engine":"template", "profile":PROFILE, "opportunity_id":rid})
    passed = result.get("method") == "template" and SENTENCE in result.get("body","")
    print("original", rid, result.get("method"), passed, flush=True)
    assert passed
    time.sleep(1)
variants = read("/cold-email/variants", {"engine":"template", "profile":PROFILE, "opportunity_id":IDS[-1]})
checks = {v["id"]:SENTENCE in v.get("body","") for v in variants["variants"] if v["id"] in ("balanced","skills")}
print("variants", checks, flush=True)
assert checks == {"balanced":True,"skills":True}

