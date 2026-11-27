"""Read from the candidate checkout and exercise normal campus merges in a temporary corpus.

Run from a checkout of 587b29ba after assembling its regular data, with that
checkout on PYTHONPATH. The argument is the destination for the JSON receipt.
"""
import copy
import datetime
import hashlib
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from fastapi.testclient import TestClient
from backend.main import app
from backend.routes.opportunities import CURRENT_TRUTH_AWARE_SCOPE
from src.collectors import faculty_graph, ucb_common
from src.collectors.schools import utexas_faculty as ut, columbia_faculty as co

base="e4edf82957625f9573a7af276d3951caa1d54fb5"
mason="faculty-utexas-math-245fa784"; treisman="faculty-utexas-math-3483c4f5";col="faculty-columbia-math-245fa784"
def json_file(p):return json.loads(Path(p).read_bytes())
def git_parent(p):return json.loads(subprocess.check_output(["git","show",base+":"+str(p)]))
def fields(a,b,p=""):
    if a==b:return []
    if isinstance(a,dict) and isinstance(b,dict):
        result=[]
        for k in sorted(set(a)|set(b)):
            if k in a and k in b:result.extend(fields(a[k],b[k],p+"."+k if p else k))
            else:result.append(p+"."+k if p else k)
        return result
    return [p]
def digest(x):return hashlib.sha256(json.dumps(x,ensure_ascii=False,separators=(",",":")).encode()).hexdigest()
def selected(r):
    m=r["metadata"]
    return {"id":r["id"],"name":r["pi_name"],"rank":m.get("faculty_title"),"active":m["is_active"],"reason":m.get("deactivation_reason"),
            "profile":r["url"],"first_seen":m.get("first_seen_at"),"last_seen":m.get("last_seen_at")}
dep=next(d for d in ut.SCHOOL["departments"] if d["short"]=="MATH")
data_path=Path('data/processed/shards');utfile=data_path/'utexas.json';cofile=data_path/'columbia.json'
before=git_parent(utfile);after=json_file(utfile);columbia=json_file(cofile);c0=git_parent(cofile)
assert c0==columbia and len(after)==len(before)==2329 and len(columbia)==1109
idx={r["id"]:r for r in after+columbia}; diff={a["id"]:fields(a,b) for a,b in zip(before,after) if a!=b}
assert set(diff)=={mason,treisman}
old_ids=[r["id"] for r in before+columbia];assert [r["id"] for r in after+columbia]==old_ids
stats='frontend/src/lib/school-stats.json';a=git_parent(stats);b=json_file(stats);diff_stats=fields(a,b)
assert set(diff_stats)=={"schools.utexas.faculty_contact_count","schools.utexas.total_count"}
paths=subprocess.check_output(["git","diff","--name-only",base],text=True).splitlines()
assert set(paths)=={str(utfile),stats}
all_ids=[]
for shard in sorted(data_path.glob("*.json")):
    all_ids.extend(v["id"] for v in json_file(shard))
assert len(all_ids)==len(set(all_ids))==149944
result={"stage":"isolated candidate on B23","base":base,"observed_at":datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "all_originals":len(all_ids),"all_originals_order_sha256":digest(all_ids),
        "all_other_shards_byte_identical":len(list(data_path.glob("*.json")))-1,"two_campuses":len(old_ids),
        "source_fields_changed":diff,"before":[selected(r) for r in before+columbia if r["id"] in (mason,treisman,col)],
        "candidate":[selected(idx[i]) for i in (mason,treisman,col)],"changed_school_coverage":diff_stats,
        "texas_coverage":[a["schools"]["utexas"],b["schools"]["utexas"]],"Columbia_coverage":b["schools"]["columbia"],
        "national":b["national_count"],"schools_count":len(b["schools"]),"merge_replay":[],"candidate_public_api":{}}
ut_ctrl=next(r for r in after if r['department']=='Department of Mathematics' and r['id'] not in (mason,treisman) and r['metadata']['is_active'])
def shown(label,changes,updated,expected_new=0):
    rows=json_file(ucb_common.PROCESSED_FILE);lookup={r["id"]:r for r in rows}
    assert all(oid in lookup and lookup[oid]["metadata"].get("first_seen_at")==idx[oid]["metadata"].get("first_seen_at") for oid in old_ids)
    assert len(rows)==len(old_ids)+expected_new and updated[0]==changes
    states={i:{"active":lookup[i]["metadata"]["is_active"],"rank":lookup[i]["metadata"]["faculty_title"],
               "name":lookup[i]["pi_name"],"reason":lookup[i]["metadata"].get("deactivation_reason")} for i in (mason,treisman,col)}
    result["merge_replay"].append({"step":label,"added":updated[0],"updated":updated[1],"saved_originals_retained":len(old_ids),
                                   "original_first_seen_preserved":True,"states":states})
    return tuple(states[i]["active"] for i in (mason,treisman,col))
def listed(name,title,url):
    spec=faculty_graph.faculty(name,title=title,url=url)
    spec.update(_verification_scope="directory",_listing_seen_on_source=True)
    return faculty_graph._normalize(ut.SCHOOL,dep,spec)
with tempfile.TemporaryDirectory() as td:
    ucb_common.PROCESSED_FILE=Path(td)/'two-schools.json'
    ucb_common.PROCESSED_FILE.write_text(json.dumps(after+columbia))
    assert shown("unreadable ordinary UT directory",0,ut.merge_into_processed([]))==(False,False,True)
    assert shown("other UT mathematician seen",0,ut.merge_into_processed([copy.deepcopy(ut_ctrl)]))==(False,False,True)
    assert shown("current Columbia person observed",0,co.merge_into_processed([copy.deepcopy(idx[col])]))==(False,False,True)
    assert listed("Uri Treisman","Professor Emeritus",idx[treisman]["url"]) is None
    renamed=listed("Luis Mason-Brown","Assistant Professor",idx[mason]["url"])
    assert renamed["id"]!=mason
    assert shown("simulated different first name at reused UT URL",1,ut.merge_into_processed([renamed]),1)==(False,False,True)
    # Restart the independent return scenario from the unmodified candidate.
    ucb_common.PROCESSED_FILE.write_text(json.dumps(after+columbia))
    ret=[listed("Lucas Mason-Brown, Ph.D.","Associate Professor",idx[mason]["url"]),listed("Uri Treisman","Professor",idx[treisman]["url"])]
    assert [x["id"] for x in ret]==[mason,treisman]
    assert shown("simulated separately affirmed UT appointments and degree-suffixed name",0,ut.merge_into_processed(copy.deepcopy(ret)))==(True,True,True)
    assert shown("repeat ordinary same affirmative listings",0,ut.merge_into_processed(copy.deepcopy(ret)))==(True,True,True)
with TestClient(app) as client:
    for oid in (mason,treisman,col,ut_ctrl["id"]):
        res=client.get("/api/opportunities/"+oid,params={"_release_scope":CURRENT_TRUTH_AWARE_SCOPE})
        data=res.json();truth=data.get("target_truth") or {}
        result["candidate_public_api"][oid]={"http":res.status_code,"name":data.get("pi_name"),"rank":data["detail_fields"]["fields"]["professor_or_lab"]["explicit"].get("faculty_rank"),"rank_quote":data["detail_fields"]["fields"]["professor_or_lab"].get("quotes",{}).get("faculty_rank"),
             "link":data.get("url"),"actionable":truth.get("actionable"),"contact_state":data.get("contact_email_status"),
             "last_seen_listed_at":data.get("last_seen_listed_at")}
        assert res.status_code==200 and data["id"]==oid and truth["actionable"]==(oid not in (mason,treisman))
        if oid==treisman:
            reading=result["candidate_public_api"][oid]
            assert reading["rank"]=="Professor Emeritus" and reading["rank_quote"]["source_url"]==idx[oid]["url"]
            assert reading["rank_quote"]["observed_at"]=="2026-11-27"
        if oid in (mason,treisman):assert data.get("contact_email_status")=="unavailable"
Path(sys.argv[1]).write_text(json.dumps(result,indent=2,ensure_ascii=False)+"\n")
print("All original identifiers, changed fields, reappointments and four normal API responses verified.")
