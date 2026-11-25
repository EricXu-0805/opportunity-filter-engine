"""Measure public acceptance cases without using account data or sending any messages."""
import json
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from bs4 import BeautifulSoup

BASE = "https://joinalab.com"
API = "https://opportunity-filter-engine-api.onrender.com/api"
AGENT = "JoinALab/1.0 (project acceptance checks)"
FACULTY = "faculty-uci-pharm-04b7dd6e"
INTERESTS = "condensed matter physics, evolutionary biology, planetary science"
SENTENCE = "I am interested in condensed matter physics, evolutionary biology, and planetary science."

def read(url, data=None):
    headers = {"User-Agent": AGENT}
    if data:
        headers["Content-Type"] = "application/json"
    req = Request(url, headers=headers, data=json.dumps(data).encode() if data else None)
    with urlopen(req, timeout=30) as resp:
        blob = resp.read(4_000_001)
        if len(blob) > 4_000_000:
            raise ValueError("oversize")
        return blob

def watch(key, fn):
    try:
        print(key, json.dumps(fn(), ensure_ascii=True), flush=True)
    except HTTPError as exc:
        print(key, "HTTP", exc.code, flush=True)
    except (URLError, OSError, ValueError, TypeError, KeyError) as exc:
        print(key, type(exc).__name__, flush=True)

def health():
    val=json.loads(read(API + "/health"))
    return {k:v for k,v in val.items() if k in ("status","build_sha","git_commit","build_version","commit","version","deployed_at")}

def api_dates():
    val=json.loads(read(API + "/opportunities/" + FACULTY))
    return {"listed":val.get("last_seen_listed_at"), "fields":{k:(v.get("provenance") or {}).get("observed_at") for k,v in val["detail_fields"]["fields"].items() if v.get("state")=="source"}}

def visible_dates():
    doc=BeautifulSoup(read(BASE + "/opportunities/" + FACULTY), "html.parser")
    return {"school_date":re.findall(r"Observed [0-9-]+",(doc.select_one('[data-testid="fact-field-school"]') or doc).get_text(" ",strip=True))[:2], "footer_date":re.findall(r"Last seen listed:\s*[0-9-]+",doc.get_text(" ",strip=True))[:2]}

def draft(path):
    val=json.loads(read(API+path,{"engine":"template","opportunity_id":FACULTY,"profile":{"name":"QA Student","year":"sophomore","major":"Chemistry","school":"Example University","research_interests_text":INTERESTS}}))
    results={v.get("id","single"):SENTENCE in (v.get("body") or "") for v in val.get("variants",[val]) if v.get("id","single") in ("balanced","skills","single")}
    return {"complete_interest_sentence":results, "engine":val.get("engine"), "pipeline":val.get("pipeline_version")}

watch("health", health)
watch("M177_detail_fields",api_dates)
watch("M177_public_page",visible_dates)
for path in ("/cold-email","/cold-email/variants"):
    watch("M187_template"+path,lambda: draft(path))
