"""Anonymous, bounded production regression check. Prints counts and public record IDs only."""
import json
import sys
import time
from datetime import date
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, Request, build_opener

API = "https://opportunity-filter-engine-api.onrender.com/api"
SCOPE = "mvp-core-close-v1-contact-trust-v1-faculty-trust-v1-target-truth-v2"
SENTENCE = "i want to study how neural circuits encode memory"
EEB = ["faculty-ucla-eeb-56b5bd06", "faculty-ucla-eeb-04fc2f84", "faculty-ucla-eeb-792288c6",
       "faculty-ucla-eeb-880b1219", "faculty-ucla-eeb-f529eb3c"]
MEMORY = ["faculty-ucb-africam-e6be4620", "faculty-ucb-artprac-f59250ce"]
RSS = {"rss-our-6616fe0f": ["URAP"], "rss-our-7a545fbb": ["FGSRP"], "rss-our-030f0758": []}
results = []


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


class HttpFailure(Exception):
    def __init__(self, status):
        self.status = status


def request(path, body=None):
    time.sleep(1)
    if body is not None:
        assert (path.startswith("/matches/") and path.endswith("?llm=false")
                or path == "/cold-email" and body["engine"] == "template")
    data = json.dumps(body).encode() if body is not None else None
    req = Request(API + path, data=data, headers={"User-Agent": "JoinALab/production-matching-smoke",
                                                  "Accept": "application/json", "Content-Type": "application/json"})
    try:
        with build_opener(NoRedirect()).open(req, timeout=60) as response:
            raw = response.read(8_000_001)
            if len(raw) > 8_000_000:
                raise RuntimeError("size limit")
            return json.loads(raw)
    except HTTPError as exc:
        raise HttpFailure(exc.code) from None


def profile(home, school, major="", fields=(), seeking=("research", "summer_program")):
    return {"name": "", "school": school, "home_school": home, "year": "junior", "major": major,
            "college": "", "secondary_interests": [], "international_student": False,
            "seeking_type": list(seeking), "desired_fields": list(fields), "hard_skills": [], "coursework": [],
            "experience_level": "beginner", "resume_ready": True, "can_cold_email": True,
            "research_interests_text": ", ".join(fields), "linkedin_url": "", "github_url": "",
            "scholar_url": "", "search_weight": 50, "exploring": False, "include_cross_school": False}


def report(case, tested, bad, **info):
    status = "VIOLATIONS" if bad else "PASS" if tested else "NO_ELIGIBLE_SAMPLE"
    results.append(status)
    print(json.dumps({"case": case, "status": status, "evaluated": tested, "violations": len(bad),
                      "violation_ids": bad[:8], **info}), flush=True)


def keys(row):
    tags = row["reasons_fit_keys"]
    if not isinstance(tags, list) or len(tags) != len(row["reasons_fit"]):
        raise ValueError("reason keys unavailable")
    return [(tag["key"], tag["params"]) for tag in tags if tag is not None]


def card_pages(p, count=1, sample_ids=()):
    rows, cursor, generation = [], None, None
    for _ in range(count):
        view = {"today": date.today().isoformat()}
        if sample_ids:
            # The results page applies these client-supplied IDs without storing favorites.
            view.update(tab="starred", favorite_ids=list(sample_ids))
        page = request("/matches/view?llm=false", {"profile": p, "view": view,
                                                   "page_size": 100, "cursor": cursor})
        if page.get("ai_refined") is not False:
            raise ValueError("unexpected mode")
        if generation is not None and page["result_set_id"] != generation:
            raise ValueError("result generation changed")
        generation = page["result_set_id"]
        rows.extend(page["results"])
        cursor = page["next_cursor"]
        if not cursor:
            break
    if len({r["opportunity_id"] for r in rows}) != len(rows):
        raise ValueError("duplicate page")
    return rows


def selected(p, sample_ids):
    rows = card_pages(p, sample_ids=sample_ids)
    if any(row["opportunity_id"] not in sample_ids for row in rows):
        raise ValueError("view included an unrelated ID")
    return {row["opportunity_id"]: row for row in rows}


def detail(rid):
    row = request(f"/opportunities/{rid}?_release_scope={SCOPE}")
    if row.get("id") != rid:
        raise ValueError("unexpected detail record")
    return row


def ucsb():
    p = profile("ucsb", "UC Santa Barbara", seeking=("research",))
    rows = card_pages(p, 2)
    projects = [r for r in rows if r["opportunity"].get("source") == "ucsb_urca_projects"]
    bad = [r["opportunity_id"] for r in projects
           if any(k in {"lab_focus", "research_summary"} for k, _ in keys(r))
           or any("This lab focuses on" in line or "URCA Undergraduate Research Directory" in line
                  for line in r["reasons_fit"])
           or r["opportunity"].get("lab_or_program") == "URCA Undergraduate Research Directory"]
    report("M183-URCA-match-view", len(projects), bad, rows=len(rows), sample_ids=[r["opportunity_id"] for r in projects[:3]])
    rid = "nsf-reu-2548170"
    target = selected(profile("uiuc", "UIUC", "Biology", ("artificial intelligence",), seeking=("summer_program",)), [rid])
    bad = [i for i, row in target.items() if any(k in {"research_summary", "lab_focus"} for k, _ in keys(row))]
    report("M183-NSF-summary", len(target), bad, sample_ids=list(target))


def ucla():
    p = profile("ucla", "UCLA", "Ecology and Evolutionary Biology", ("phylogenetics", "evolutionary biology"))
    by_id = {r["opportunity_id"]: r for r in card_pages(p)}
    checked, bad = [], []
    missing = [rid for rid in EEB if rid not in by_id]
    others = selected(p, missing) if missing else {}
    for rid in EEB:
        row = by_id.get(rid) or others.get(rid)
        if row is None:
            continue
        fact = detail(rid)["detail_fields"]["fields"]["research_content"]
        if fact["explicit"] or fact["inferred"]:
            continue
        checked.append(rid)
        if any(k == "interests_lab_focus" for k, _ in keys(row)) or any("'s focus area" in s for s in row["reasons_fit"]):
            bad.append(rid)
    report("M169-original-unsubstantiated-EEB", len(checked), bad, sample_ids=checked, original_in_top100=sum(r in by_id for r in EEB))


def berkeley():
    rid = "ucb-b0c3175dfa7a3a"
    p = profile("ucb", "UC Berkeley", fields=("undergraduate research",))
    target = selected(p, [rid])
    interest_keys = {"interests_match", "interests_match_ours"}
    bad = [i for i, row in target.items()
           if any(k in interest_keys and "undergraduate research" in v.get("terms", "").lower() for k, v in keys(row))]
    report("M174-1-Berkeley-collector-constant", len(target), bad, sample_ids=list(target))
    bad, positives, seen = [], [], []
    for chip in (SENTENCE, "memory"):
        p = profile("ucb", "UC Berkeley", "Cognitive Science", (chip,))
        target = selected(p, MEMORY)
        if chip == SENTENCE:
            seen = list(target)
        for i, row in target.items():
            if any(k in interest_keys and chip in v.get("terms", "").lower() for k, v in keys(row)):
                (bad if chip == SENTENCE else positives).append(i)
    report("M174-2-long-chip-not-a-single-word", len(seen), bad, sample_ids=seen,
           short_chip_positive_control_ids=positives)
    if not positives:
        report("M174-2-positive-control", 0, [])


def rss():
    bad, active, confirmed, archived = [], [], [], []
    for rid, expected in RSS.items():
        row = detail(rid)
        labels = row.get("keywords") or []
        if ("unsorted" in [s.lower() for s in labels] or any(s not in labels for s in expected)
                or (expected and row.get("keywords_attribution") == "inferred")):
            bad.append(rid)
        confirmed.append(rid)
        if row["target_truth"].get("actionable") is True and expected:
            active.append((rid, expected))
        elif row["target_truth"].get("actionable") is False:
            archived.append(rid)
    report("M174-3-RSS-public-attribution", len(confirmed), bad, sample_ids=confirmed, archived=archived)
    bad = []
    checked = []
    for rid, labels in active:
        target = selected(profile("uiuc", "UIUC", fields=labels), [rid])
        for i, r in target.items():
            checked.append(i)
            if any(k == "interests_match_ours" for k, _ in keys(r)):
                bad.append(i)
    report("M174-3-active-RSS-match", len(checked), bad, sample_ids=checked)


def boulder():
    rid = "boulder-0d8edc5782f3"
    p = profile("boulder", "University of Colorado Boulder", "Engineering")
    row = detail(rid)
    target = selected(p, [rid])
    draft = request("/cold-email", {"engine": "template", "opportunity_id": rid,
                                    "profile": {**p, "name": "Sample Student"}})
    if draft.get("method") != "template" or not draft.get("body", "").strip():
        raise ValueError("template unavailable")
    greeting = draft["body"].lstrip().splitlines()[0].casefold()
    stale_text = "team projectsgroup conference travel"
    bad = (bool(row.get("pi_name")) or not greeting
           or any(t in greeting for t in ("conference travel", "projectsgroup"))
           or "travel" in greeting)
    report("M203-template-greeting", 1, [rid] if bad else [], sample_ids=[rid], method=draft["method"])
    bad = [i for i, r in target.items() if stale_text in " ".join(r["reasons_fit"]).casefold()]
    report("M203-matcher-recipient", len(target), bad, sample_ids=list(target))


if __name__ == "__main__":
    for case in (ucsb, ucla, berkeley, rss, boulder):
        try:
            case()
        except HttpFailure as exc:
            print(json.dumps({"case": case.__name__, "status": "HTTP_ERROR", "http": exc.status}), flush=True)
            results.append("HTTP_ERROR")
            if exc.status == 429:
                break
        except (ValueError, KeyError, OSError, TypeError, RuntimeError) as exc:
            print(json.dumps({"case": case.__name__, "status": "INCOMPLETE", "error_type": type(exc).__name__}), flush=True)
            results.append("INCOMPLETE")
    sys.exit(int(any(r in {"INCOMPLETE", "HTTP_ERROR", "VIOLATIONS"} for r in results)))
